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

    out: list[AlignedPair] = []
    used_b: set[int] = set()
    for ra in a:
        candidates = by_name_b.get(ra.name.strip().lower(), [])
        if not candidates:
            continue
        same_page = [rb for rb in candidates if rb.page == ra.page and id(rb) not in used_b]
        if not same_page:
            continue
        # Entity-tag gate (highest priority). When the extractor captured a
        # leading Device ID on this row, only pair with the same Device ID
        # on the other side. Records without a tag never pair with tagged
        # records — that cross-pair is exactly the failure mode where
        # "⑥ KRP-C" gets matched against "21 LPS-RK" because the algorithm
        # had no identity signal beyond name. If no same-tag candidate
        # exists, the record goes unpaired (no false flag).
        if ra.entity_tag:
            same_page = [rb for rb in same_page if rb.entity_tag == ra.entity_tag]
        else:
            same_page = [rb for rb in same_page if not rb.entity_tag]
        if not same_page:
            continue
        # String-valued (no normalized_magnitude): require same family prefix
        # so KRP-C never pairs with LPS-RK. Position is still used to choose
        # among same-family candidates.
        if ra.normalized_magnitude is None:
            fam_a = _string_family(ra.raw_value)
            same_page = [rb for rb in same_page if _string_family(rb.raw_value) == fam_a]
            if not same_page:
                continue
        # Ambiguity gate: trigger when positional pairing can't be trusted.
        # Two distinct conditions both fold into "pair only on value equality":
        #   (a) Count mismatch with multi-instance — A has 2, B has 1 (or
        #       vice versa) for this (page, name). The fewer side has no
        #       way to identify which A position it corresponds to.
        #   (b) OCR y-degeneracy — multiple B candidates all share one
        #       y-center (vision OCR spans inherit the whole-page bbox),
        #       so y-distance pairing collapses to first-in-iteration.
        # Either way the safe move is: pair only an exact value-equal
        # candidate, else skip (no false flag from cross-position pairing).
        key = (ra.page, ra.name.strip().lower())
        n_a = a_counts.get(key, 0)
        n_b = b_counts.get(key, 0)
        count_ambiguous = (n_a != n_b) and (n_a > 1 or n_b > 1)
        y_degenerate = (
            len(same_page) > 1 and len({_y_center(rb) for rb in same_page}) == 1
        )
        if count_ambiguous or y_degenerate:
            value_match = next(
                (rb for rb in same_page if equivalent(ra.raw_value, rb.raw_value)),
                None,
            )
            if value_match is None:
                continue
            used_b.add(id(value_match))
            out.append(
                AlignedPair(
                    a=ra,
                    b=value_match,
                    name_match_confidence=1.0,
                    value_equivalent=True,
                )
            )
            continue
        best_rb = min(same_page, key=lambda rb: abs(_y_center(rb) - _y_center(ra)))
        if abs(_y_center(best_rb) - _y_center(ra)) > y_tol:
            continue
        used_b.add(id(best_rb))
        out.append(
            AlignedPair(
                a=ra,
                b=best_rb,
                name_match_confidence=1.0,
                value_equivalent=equivalent(ra.raw_value, best_rb.raw_value),
            )
        )
    return out
