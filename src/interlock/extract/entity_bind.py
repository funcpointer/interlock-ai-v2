"""Sprint 4.5 — bind ParameterRecord.entity_tag from detected entities.

Pure post-processor over a record list. For each record on each page:
  1. Find entities on the same page whose [y_top, y_bottom] encloses
     the record's bbox y_center.
  2. On multiple enclosures, pick the tightest fit (smallest range).
  3. On no enclosure, fall back to nearest entity by y-distance.
  4. If no same-page entity exists OR the record already has a tag,
     leave the record's entity_tag unchanged.

Returns a NEW list of records (records are frozen dataclasses; we use
dataclasses.replace).
"""

from __future__ import annotations

import logging
from dataclasses import replace

from interlock.extract.parameters import ParameterRecord
from interlock.llm_pipeline.schemas.entity import DetectedEntity

logger = logging.getLogger(__name__)


def bind_records_to_entities(
    records: list[ParameterRecord],
    entities_by_page: dict[int, list[DetectedEntity]],
    *,
    diagram_pages: set[int] | None = None,
) -> list[ParameterRecord]:
    """Return new records with entity_tag populated by y-binding.

    v2.8.1 — ``diagram_pages`` (optional set of 1-indexed page numbers)
    skips binding for any record on a diagram page. On diagram pages
    (TCC plots, one-lines, P&IDs) the vision lane already supplies
    correct (entity, value) tuples; running y-binding on top of that
    re-introduces the draw-order-y vs visual-y coord-space bug that the
    Sprint 8 hotfix called out (e.g. binding a transformer ``%Z`` value
    to an unrelated fuse model that happens to enclose its text-layer
    y_center on the diagram).
    """
    diagram_pages = diagram_pages or set()
    out: list[ParameterRecord] = []
    skipped_diagram = 0
    skipped_already_tagged = 0
    skipped_no_entities = 0
    skipped_no_enclosure = 0
    bound = 0
    for rec in records:
        if rec.page in diagram_pages:
            # Skip binding entirely. Vision lane is the authority on
            # diagram pages; non-vision records keep their original tag
            # (typically empty for Track 1 regex, populated by Track 2 LLM).
            out.append(rec)
            skipped_diagram += 1
            continue
        if rec.entity_tag:
            out.append(rec)
            skipped_already_tagged += 1
            continue
        page_ents = entities_by_page.get(rec.page, [])
        if not page_ents:
            out.append(rec)
            skipped_no_entities += 1
            continue
        y_center = (rec.bbox[1] + rec.bbox[3]) / 2.0
        chosen = _pick_entity(y_center, page_ents)
        if chosen is None:
            out.append(rec)
            skipped_no_enclosure += 1
            continue
        logger.debug(
            "entity_bind: %s p%d %r → %s (y_center=%.1f, %d candidates)",
            rec.doc_id, rec.page, rec.raw_value, chosen.label,
            y_center, len(page_ents),
        )
        out.append(replace(rec, entity_tag=chosen.label))
        bound += 1
    logger.debug(
        "entity_bind summary: %d bound, skipped (diagram=%d already_tagged=%d "
        "no_entities=%d no_enclosure=%d), %d total records",
        bound, skipped_diagram, skipped_already_tagged,
        skipped_no_entities, skipped_no_enclosure, len(records),
    )
    return out


def _pick_entity(
    y_center: float, page_ents: list[DetectedEntity],
) -> DetectedEntity | None:
    """Pick the enclosing entity for a y_center on its page.

    Tightest-fit enclosure wins. Returns None when nothing encloses
    the y_center — including when page_ents is empty.

    v2.7 hotfix: dropped nearest-y fallback. On diagram pages, PyMuPDF
    text-layer y is draw-order y, not visual y. The detector's y is
    visual y. Nearest-fallback mixed the two coordinate spaces and
    produced systematic mis-bindings (e.g. LPS-RK-400SP record bound to
    LPS-RK-100SP entity 50px away in PyMuPDF space, even though the
    visual layout puts them in different regions of the page). Honest
    unbinding (entity_tag stays empty) lets downstream alignment
    (semantic / reranker) handle the case under their own rules, rather
    than locking in a false same-tag pair with confidence 1.00.

    The proper long-term fix is the Sprint 8 vision lane, where vision
    extraction returns (entity, value) tuples together in image-space,
    eliminating the binding step.
    """
    if not page_ents:
        return None
    enclosing = [
        e for e in page_ents
        if e.y_top <= y_center <= e.y_bottom
    ]
    if enclosing:
        return min(enclosing, key=lambda e: e.y_bottom - e.y_top)
    return None
