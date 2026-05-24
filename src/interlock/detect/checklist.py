"""v2.8.4 — checklist-gap detector.

A "checklist gap" is a parameter present in one document but missing
from the other. Concrete example from the locked fixture:

    Doc A p7 (TCC3) lists ``LPN-RK-500SP`` as a feeder fuse.
    Doc B p7 has the line removed.

The aligner's job is to PAIR records across documents — when there's no
counterpart, the A record falls into ``unpaired_a`` and stays silent.
That silence is the bug for checklist-style review: the reviewer needs
to see WHAT was dropped, not just the values that changed.

Strategy:
- Scope to string-valued params with stable identity (Fuse Designation
  is the obvious one — part numbers are unique handles). Numeric params
  like '%Z' don't make sense here; a missing impedance is not a
  checklist gap, it's an extractor miss.
- Iterate Doc A unpaired records of the in-scope name list.
- For each, look for a raw_value match (case-insensitive, normalized)
  anywhere in Doc B's record set — paired OR unpaired. If not found,
  emit a checklist-gap flag with low confidence (per gold FN-1 spec,
  min_confidence=0.4).
- Symmetric direction (Doc B present, Doc A absent) is currently out of
  scope — the gold's authority model treats Doc A as source of truth
  for these reviews, so a B-only entry is more often a typo / late
  addition than a real gap. Easy to symmetrize later.
"""

from __future__ import annotations

import logging

from interlock.detect.mismatch import Flag
from interlock.extract.parameters import ParameterRecord

logger = logging.getLogger(__name__)

# Parameter names where a missing entry in Doc B is a meaningful flag.
# Keep this list tight — adding numeric params here turns extractor
# misses into noise.
_GAP_SCOPE: set[str] = {
    "Fuse Designation",
}


def detect_checklist_gaps(
    unpaired_a: list[ParameterRecord],
    all_b_records: list[ParameterRecord],
    doc_a_id: str,
    doc_b_id: str,
) -> list[Flag]:
    """Emit one Flag per Doc-A unpaired record whose raw_value does not
    appear in any Doc-B record."""
    b_values: set[str] = {
        _norm(r.raw_value) for r in all_b_records if r.raw_value
    }
    gaps: list[Flag] = []
    for ra in unpaired_a:
        if ra.name not in _GAP_SCOPE:
            continue
        norm_val = _norm(ra.raw_value)
        if not norm_val:
            continue
        if norm_val in b_values:
            # Value exists somewhere in B — not a true gap, just an
            # alignment miss (which the unpaired-records list already
            # surfaces). Don't double-emit.
            continue
        gaps.append(_make_gap_flag(ra, doc_a_id, doc_b_id))
    if gaps:
        logger.info(
            "checklist gap: emitted %d flags (params=%s)",
            len(gaps), sorted({f.parameter for f in gaps}),
        )
    return gaps


def _norm(s: str | None) -> str:
    return (s or "").strip().upper()


def _make_gap_flag(
    a_record: ParameterRecord, doc_a_id: str, doc_b_id: str,
) -> Flag:
    """Build a checklist-gap Flag. Doc A is source of truth (the spec /
    earlier-phase doc); Doc B is the deviation candidate (the entry was
    removed). A synthetic B-record placeholder is constructed so the UI
    rendering path (which expects both sides) keeps working."""
    placeholder_b = ParameterRecord(
        doc_id=doc_b_id, page=a_record.page,
        bbox=(0.0, 0.0, 0.0, 0.0), section=None,
        span_text="(removed — not present in Doc B)",
        name=a_record.name,
        raw_value="(removed)",
        normalized_magnitude=None,
        normalized_unit=None,
        source_path="",
        entity_tag="",
        provenance="regex",
        extraction_lane="regex",
    )
    return Flag(
        parameter=a_record.name,
        authoritative_doc_id=doc_a_id,
        deviating_doc_id=doc_b_id,
        a_record=a_record,
        b_record=placeholder_b,
        confidence=0.5,  # low — gold FN-1 floor is 0.4, give it some headroom
        rationale=(
            f"{a_record.raw_value!r} present in Doc A (p{a_record.page}) "
            f"but not found anywhere in Doc B — checklist gap."
        ),
        authority_rule="checklist_gap",
        severity="major",
        deviation_pct=0.0,
        attribute_family="checklist_gap",
        pairing_confidence=0.5,
    )
