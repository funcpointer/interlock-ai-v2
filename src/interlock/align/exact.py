"""Exact-name alignment with positional 1-to-1 pairing.

When two documents share layout (e.g., a 90% revision derived from a 60%
baseline), records with the same name pair greedily by (page, y-center)
proximity. This avoids the cross-product explosion that would happen if every
A record with name X matched every B record with name X.

Pairing is intra-page: only same-page records may pair.

Multi-instance string parameters (e.g., 5+ "Fuse Designation" rows on a
one-line diagram) get a stricter pairing rule: candidates must share a
family prefix with the source record. Without this guard, positional
pairing produces nonsense flags like ``KRP-C-1600SP (1600 A main) vs
LPS-RK-100SP (100 A branch)`` — two different physical devices that have
nothing to do with each other.

When candidate y-centers are all identical (the OCR signature: every
vision-derived span shares a whole-page bbox), positional pairing
degenerates to first-in-iteration order. In that case we require an
exact value-equal candidate; if none exists we skip the pair entirely.
This suppresses bad numeric pairs too — e.g., ``150 kVA ↔ 100 kVA``
when a one-line diagram has multiple transformers and the OCR side has
no per-row y information to disambiguate.

Both rules are heuristic stand-ins for real entity grounding (which the
Phase-14 claim layer provides when enabled).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from interlock.extract.parameters import ParameterRecord
from interlock.extract.units import equivalent


@dataclass(frozen=True)
class AlignedPair:
    a: ParameterRecord
    b: ParameterRecord
    name_match_confidence: float
    value_equivalent: bool
    # How certain we are this pair represents the same logical record
    # across the two docs. Separate from name_match_confidence (which
    # only scores name-string similarity) — pairing_confidence reflects
    # the strength of the *correspondence rule* that fired:
    #   1.0  entity_tag (Device ID) match — strongest, identity-based
    #   0.9  single-instance unambiguous positional pair
    #   0.75 multi-instance equal-count distinct-y positional pair
    #   0.5  ambiguity fallback (value-equality after degeneracy gate)
    # Defaults to 1.0 for back-compat with hand-built AlignedPair in
    # legacy tests.
    pairing_confidence: float = 1.0
    # v2 Sprint 4 — LLM reranker outputs. Defaults preserve back-compat
    # with hand-built AlignedPair in legacy alignment tests.
    rerank_rationale: str | None = None
    reranked: bool = False


def _y_center(r: ParameterRecord) -> float:
    return (r.bbox[1] + r.bbox[3]) / 2


# Capture the alphabetic family prefix preceding the first digit run.
# "KRP-C-1600SP" -> "KRP-C", "LPS-RK-100SP" -> "LPS-RK", "LPN-RK-200SP"
# -> "LPN-RK". Used to gate cross-family pairing of string-valued params.
_FAMILY_RE = re.compile(r"^([A-Z][A-Z\-]*?)-?\d")

# Sentinel returned when no real alphabetic-prefix family is present.
# v2.8.5 — the previous fallback returned the full raw_value, which
# meant any string-valued record with differing raw_value would fail the
# family filter (e.g. Fault Current values like '20,000A RMS Sym' vs
# '200,000A RMS Sym' — different strings, same parameter, legitimately
# distinct magnitudes). Treat sentinel as "no family constraint" at
# the filter site so those pairs can still match.
_NO_FAMILY = "__NO_FAMILY__"


def _string_family(raw_value: str) -> str:
    """Return the alphabetic family prefix of a string-valued parameter,
    or ``_NO_FAMILY`` if the raw_value has no fuse-style prefix shape.

    Callers must skip the family-equality filter when EITHER side is
    ``_NO_FAMILY`` — otherwise legitimate string-valued numeric params
    (Fault Current, Inrush Current) get filtered out of the candidate
    pool by raw-value inequality.
    """
    m = _FAMILY_RE.match(raw_value.strip())
    return m.group(1) if m else _NO_FAMILY


def _family_compatible(a: str, b: str) -> bool:
    """True when two records' string-families are compatible. ``_NO_FAMILY``
    on either side is permissive (no constraint)."""
    if a == _NO_FAMILY or b == _NO_FAMILY:
        return True
    return a == b


def align_exact(
    a: list[ParameterRecord], b: list[ParameterRecord], y_tol: float = 1000.0
) -> list[AlignedPair]:
    """Pair records by exact name + greedy positional proximity.

    For each (a record, candidate b records with same name on same page),
    pick the b record with minimum y-center distance not yet used. y_tol is
    intentionally loose because page heights vary; tightness is delegated to
    later confidence scoring rather than hard-rejecting at this stage.

    String-valued parameters (no Pint magnitude) additionally require a
    matching family prefix — see module docstring for rationale.
    """
    by_name_b: dict[str, list[ParameterRecord]] = {}
    for r in b:
        by_name_b.setdefault(r.name.strip().lower(), []).append(r)

    # Per-(page, name) counts on each side. Used to detect ambiguous
    # multi-instance pairing where positional pairing isn't trustworthy.
    def _counts(records: list[ParameterRecord]) -> dict[tuple[int, str], int]:
        out: dict[tuple[int, str], int] = {}
        for r in records:
            k = (r.page, r.name.strip().lower())
            out[k] = out.get(k, 0) + 1
        return out

    a_counts = _counts(a)
    b_counts = _counts(b)

    def _filtered_pool(ra: ParameterRecord) -> list[ParameterRecord]:
        """Candidate B records for ``ra`` after all *identity* filters —
        page, entity-tag compatibility, and family prefix for string-valued
        params. Does NOT subtract ``used_b``. Used both for choosing the
        best candidate and for measuring the bucket's true ambiguity
        (count + y-degeneracy) so the gate behaves consistently across
        iterations within one (page, name) bucket.

        v2.8.4 — strict-tag pass first, then relaxed fallback. Strict
        keeps the current Phase 19 / Sprint 5a behavior (exact tag match
        or both empty). The relaxed fallback kicks in only when strict
        pool is empty: same page + same name + dim-compatible regardless
        of tag, paired with a low pairing_confidence so weak pairs are
        flagged for reranker review. This unblocks cross-doc mutations
        where Track 2 LLM emits descriptor-tags like '1000KVA XFMR' on
        one side while Track 1 regex emits row-marker tags like '1' on
        the other.
        """
        same_page = [
            rb
            for rb in by_name_b.get(ra.name.strip().lower(), [])
            if rb.page == ra.page
        ]
        # Strict pass: identical tags (or both empty).
        if ra.entity_tag:
            strict = [rb for rb in same_page if rb.entity_tag == ra.entity_tag]
        else:
            strict = [rb for rb in same_page if not rb.entity_tag]
        if ra.normalized_magnitude is None:
            fam_a = _string_family(ra.raw_value)
            strict = [
                rb for rb in strict
                if _family_compatible(_string_family(rb.raw_value), fam_a)
            ]
        if strict:
            return strict
        # v2.8.4 — relaxed fallback. Same page + same name; ignore tag.
        # Keep the family filter for string-valued params (e.g. fuse
        # designation families must still match — different fuse classes
        # are not interchangeable even when tags differ).
        # v2.8.5 — ``_family_compatible`` treats ``_NO_FAMILY`` as
        # unconstrained so Fault-Current-style raw strings still pool.
        if ra.normalized_magnitude is None:
            fam_a = _string_family(ra.raw_value)
            return [
                rb for rb in same_page
                if _family_compatible(_string_family(rb.raw_value), fam_a)
            ]
        return same_page

    out: list[AlignedPair] = []
    used_b: set[int] = set()
    for ra in a:
        # Identity-filtered pool: what we *could* pair with if no B were
        # consumed. Drives the ambiguity decision.
        pool = _filtered_pool(ra)
        if not pool:
            continue
        # What's still available right now (subtract consumed B records).
        same_page = [rb for rb in pool if id(rb) not in used_b]
        if not same_page:
            continue
        tag_anchored = bool(ra.entity_tag)
        # Ambiguity gate: trigger when positional pairing can't be trusted.
        # Two distinct conditions both fold into "pair only on value equality":
        #   (a) Count mismatch with multi-instance — A has 2, B has 1 (or
        #       vice versa) for this (page, name). The fewer side has no
        #       way to identify which A position it corresponds to.
        #   (b) OCR y-degeneracy — multiple identity-eligible B candidates
        #       share one y-center (vision OCR spans inherit the whole-page
        #       bbox). Measured on the unconsumed-pool so the gate stays
        #       consistent for the second iteration in a bucket too.
        # Either way the safe move is: pair only an exact value-equal
        # candidate, else skip (no false flag from cross-position pairing).
        key = (ra.page, ra.name.strip().lower())
        n_a = a_counts.get(key, 0)
        n_b = b_counts.get(key, 0)
        count_ambiguous = (n_a != n_b) and (n_a > 1 or n_b > 1)
        y_degenerate = (
            len(pool) > 1 and len({_y_center(rb) for rb in pool}) == 1
        )
        if count_ambiguous or y_degenerate:
            value_match = next(
                (rb for rb in same_page if equivalent(ra.raw_value, rb.raw_value)),
                None,
            )
            if value_match is None:
                continue
            used_b.add(id(value_match))
            # Ambiguity fallback: value-equal candidate is our only signal.
            # Pair is genuine ("same value, no contradiction") but we have
            # no positional evidence so confidence stays low.
            # v2.8.4 — confidence further reduced when tags differ.
            vm_tag_match = bool(ra.entity_tag) == bool(value_match.entity_tag) and (
                ra.entity_tag == value_match.entity_tag
                if ra.entity_tag
                else True
            )
            vm_pconf = (
                1.0 if (tag_anchored and vm_tag_match)
                else 0.5 if vm_tag_match
                else 0.4
            )
            out.append(
                AlignedPair(
                    a=ra,
                    b=value_match,
                    name_match_confidence=1.0,
                    value_equivalent=True,
                    pairing_confidence=vm_pconf,
                )
            )
            continue
        best_rb = min(same_page, key=lambda rb: abs(_y_center(rb) - _y_center(ra)))
        if abs(_y_center(best_rb) - _y_center(ra)) > y_tol:
            continue
        used_b.add(id(best_rb))
        # Positional pair confidence depends on how unambiguous the
        # bucket was. Tag-anchored exact match = 1.0; single-instance on
        # both sides = 0.9; multi-instance equal-count distinct-y = 0.75.
        # v2.8.4: when the strict-tag pool was empty and we matched via
        # the relaxed fallback (tags differ), drop confidence so the
        # reranker has a clear weak-pair signal to investigate.
        tag_match = bool(ra.entity_tag) == bool(best_rb.entity_tag) and (
            ra.entity_tag == best_rb.entity_tag
            if ra.entity_tag
            else True
        )
        if tag_anchored and tag_match:
            pconf = 1.0
        elif not tag_match:
            pconf = 0.55  # tag mismatch — weak pair; reranker / judge inspects
        elif n_a <= 1 and n_b <= 1:
            pconf = 0.9
        else:
            pconf = 0.75
        out.append(
            AlignedPair(
                a=ra,
                b=best_rb,
                name_match_confidence=1.0,
                value_equivalent=equivalent(ra.raw_value, best_rb.raw_value),
                pairing_confidence=pconf,
            )
        )
    return out
