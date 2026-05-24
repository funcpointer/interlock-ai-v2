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
    *,
    page_scope: bool = True,
) -> list[Flag]:
    """Emit Flags for Doc-A unpaired records whose raw_value is missing
    from Doc-B's checklist.

    v2.8.6 — two-pass detector with page-scoping:

    1. **Page-scoped check** (when ``page_scope=True``, default): does
       ``ra.raw_value`` appear in Doc B records on the SAME page? If yes,
       no flag (likely an alignment miss, not a gap).
    2. **Document-wide check**: if missing same-page, does it appear
       ANYWHERE in Doc B? If yes, this is a "page migration" — the line
       moved to a different page in the revision. Logged at INFO so the
       reviewer can see migrations without being flagged, since
       migrations are normal revision flow.
    3. If missing both → true checklist gap → emit Flag.

    Pass ``page_scope=False`` for the old document-wide behavior (any
    occurrence anywhere in B suppresses the gap flag).
    """
    b_values_by_page: dict[int, set[str]] = {}
    b_values_all: set[str] = set()
    for r in all_b_records:
        v = _norm(r.raw_value)
        if not v:
            continue
        b_values_by_page.setdefault(r.page, set()).add(v)
        b_values_all.add(v)

    gaps: list[Flag] = []
    migrations = 0
    logger.debug(
        "checklist-gap pb snapshot: %d total records, %d pages with values; "
        "per-page sizes=%s",
        sum(len(v) for v in b_values_by_page.values()),
        len(b_values_by_page),
        {p: len(v) for p, v in sorted(b_values_by_page.items())},
    )
    for ra in unpaired_a:
        if ra.name not in _GAP_SCOPE:
            continue
        norm_val = _norm(ra.raw_value)
        if not norm_val:
            continue
        if page_scope:
            page_set = b_values_by_page.get(ra.page, set())
            if norm_val in page_set:
                # Present on the same page in B — alignment miss, not gap.
                continue
            # v2.8.7 — when about to flag, dump the page set so triage
            # can see exactly what IS on this B page (in case the value
            # ought to be present but didn't make it into the set).
            sample = sorted(page_set)[:10] if page_set else []
            logger.debug(
                "checklist-gap near-miss: %s %r unpaired on A p%d; "
                "B p%d set size=%d sample=%s; norm_val=%r",
                ra.name, ra.raw_value, ra.page, ra.page,
                len(page_set), sample, norm_val,
            )
            # v2.8.6 — page-scoped strict. Even if the value appears
            # elsewhere in B, a removal from the SAME page (TCC table /
            # spec section context) is a real checklist gap. Log the
            # cross-page occurrence as informational so the reviewer can
            # see the "also appears on B p<N>" context, but DO flag.
            if norm_val in b_values_all:
                other_pages = sorted([
                    p for p, vals in b_values_by_page.items()
                    if norm_val in vals
                ])
                migrations += 1
                logger.info(
                    "checklist gap with cross-page presence: %s %r "
                    "missing on B p%d but appears on B p%s — flagging "
                    "(same-page removal is the gap)",
                    ra.name, ra.raw_value, ra.page, other_pages,
                )
        else:
            if norm_val in b_values_all:
                continue
        gaps.append(_make_gap_flag(ra, doc_a_id, doc_b_id))
    if gaps:
        logger.info(
            "checklist gap: emitted %d flags (params=%s); %d migrations noted",
            len(gaps), sorted({f.parameter for f in gaps}), migrations,
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
