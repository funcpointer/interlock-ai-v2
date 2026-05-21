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


def _y_center(r: ParameterRecord) -> float:
    return (r.bbox[1] + r.bbox[3]) / 2


# Capture the alphabetic family prefix preceding the first digit run.
# "KRP-C-1600SP" -> "KRP-C", "LPS-RK-100SP" -> "LPS-RK", "LPN-RK-200SP"
# -> "LPN-RK". Used to gate cross-family pairing of string-valued params.
_FAMILY_RE = re.compile(r"^([A-Z][A-Z\-]*?)-?\d")


def _string_family(raw_value: str) -> str:
    """Return the alphabetic family prefix of a string-valued parameter.

    Falls back to the full value when no leading prefix-then-digit shape is
    present (so unrelated string params still self-match by equality).
    """
    m = _FAMILY_RE.match(raw_value.strip())
    return m.group(1) if m else raw_value.strip()


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
        page, entity-tag agreement, and family prefix for string-valued
        params. Does NOT subtract ``used_b``. Used both for choosing the
        best candidate and for measuring the bucket's true ambiguity
        (count + y-degeneracy) so the gate behaves consistently across
        iterations within one (page, name) bucket."""
        pool = [
            rb
            for rb in by_name_b.get(ra.name.strip().lower(), [])
            if rb.page == ra.page
        ]
        if ra.entity_tag:
            pool = [rb for rb in pool if rb.entity_tag == ra.entity_tag]
        else:
            pool = [rb for rb in pool if not rb.entity_tag]
        if ra.normalized_magnitude is None:
            fam_a = _string_family(ra.raw_value)
            pool = [rb for rb in pool if _string_family(rb.raw_value) == fam_a]
        return pool

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
            out.append(
                AlignedPair(
                    a=ra,
                    b=value_match,
                    name_match_confidence=1.0,
                    value_equivalent=True,
                    pairing_confidence=1.0 if tag_anchored else 0.5,
                )
            )
            continue
        best_rb = min(same_page, key=lambda rb: abs(_y_center(rb) - _y_center(ra)))
        if abs(_y_center(best_rb) - _y_center(ra)) > y_tol:
            continue
        used_b.add(id(best_rb))
        # Positional pair confidence depends on how unambiguous the
        # bucket was. Tag-anchored = 1.0; single-instance on both sides
        # = 0.9; multi-instance equal-count distinct-y = 0.75.
        if tag_anchored:
            pconf = 1.0
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
