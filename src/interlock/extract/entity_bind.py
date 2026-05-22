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

from dataclasses import replace

from interlock.extract.parameters import ParameterRecord
from interlock.llm_pipeline.schemas.entity import DetectedEntity


def bind_records_to_entities(
    records: list[ParameterRecord],
    entities_by_page: dict[int, list[DetectedEntity]],
) -> list[ParameterRecord]:
    """Return new records with entity_tag populated by y-binding."""
    out: list[ParameterRecord] = []
    for rec in records:
        if rec.entity_tag:
            out.append(rec)
            continue
        page_ents = entities_by_page.get(rec.page, [])
        if not page_ents:
            out.append(rec)
            continue
        y_center = (rec.bbox[1] + rec.bbox[3]) / 2.0
        chosen = _pick_entity(y_center, page_ents)
        if chosen is None:
            out.append(rec)
            continue
        out.append(replace(rec, entity_tag=chosen.label))
    return out


def _pick_entity(
    y_center: float, page_ents: list[DetectedEntity],
) -> DetectedEntity | None:
    """Pick the best-binding entity for a y_center on its page.

    Tightest-fit enclosure wins; else nearest by y-distance.
    Returns None only when page_ents is empty.
    """
    if not page_ents:
        return None
    enclosing = [
        e for e in page_ents
        if e.y_top <= y_center <= e.y_bottom
    ]
    if enclosing:
        return min(enclosing, key=lambda e: e.y_bottom - e.y_top)

    def _dist(e: DetectedEntity) -> float:
        e_center = (e.y_top + e.y_bottom) / 2.0
        return abs(e_center - y_center)

    return min(page_ents, key=_dist)
