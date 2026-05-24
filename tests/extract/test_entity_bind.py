"""Sprint 4.5 — entity binding (y-range enclosure + nearest fallback) tests."""

from __future__ import annotations

from interlock.extract.parameters import ParameterRecord
from interlock.llm_pipeline.schemas.entity import DetectedEntity


def _record(name: str = "P", raw: str = "1 A", page: int = 1,
            y_top: float = 0.0, y_bottom: float = 10.0,
            entity_tag: str = "") -> ParameterRecord:
    return ParameterRecord(
        doc_id="d", page=page, bbox=(0.0, y_top, 100.0, y_bottom),
        section=None, span_text=raw, name=name, raw_value=raw,
        normalized_magnitude=1.0, normalized_unit="ampere",
        entity_tag=entity_tag,
    )


def _entity(label: str, y_top: float, y_bottom: float, page: int = 1) -> DetectedEntity:
    return DetectedEntity(
        label=label, kind="equipment", y_top=y_top, y_bottom=y_bottom, page=page,
    )


def test_y_enclosure_binds_record_to_enclosing_entity() -> None:
    from interlock.extract.entity_bind import bind_records_to_entities
    rec = _record(y_top=100, y_bottom=110)
    ents = {1: [_entity("XFMR-001", y_top=80, y_bottom=130)]}
    out = bind_records_to_entities([rec], ents)
    assert out[0].entity_tag == "XFMR-001"


def test_multiple_enclosing_entities_tightest_fit_wins() -> None:
    from interlock.extract.entity_bind import bind_records_to_entities
    rec = _record(y_top=100, y_bottom=110)
    ents = {1: [
        _entity("OUTER", y_top=0, y_bottom=200),
        _entity("INNER", y_top=90, y_bottom=120),
    ]}
    out = bind_records_to_entities([rec], ents)
    assert out[0].entity_tag == "INNER"


def test_no_enclosure_leaves_tag_empty() -> None:
    """v2.7 hotfix: dropped nearest-y fallback.

    On diagram pages, PyMuPDF text-layer y is draw-order y, not visual y.
    Nearest-y fallback mixes incompatible coordinate spaces and produces
    systematic mis-bindings. Honest unbinding (empty tag) is now preferred;
    downstream alignment handles untagged records under its own rules
    (semantic asymmetric-allow per Sprint 5a).
    """
    from interlock.extract.entity_bind import bind_records_to_entities
    rec = _record(y_top=100, y_bottom=110)
    ents = {1: [
        _entity("FAR", y_top=0, y_bottom=10),
        _entity("NEAR_BUT_NOT_ENCLOSING", y_top=120, y_bottom=140),
    ]}
    out = bind_records_to_entities([rec], ents)
    assert out[0].entity_tag == "", (
        "no enclosure → empty tag (no nearest fallback). "
        f"Got {out[0].entity_tag!r}."
    )


def test_no_enclosure_does_not_pick_nearest_even_when_close() -> None:
    """Belt-and-suspenders: a tightly-enclosing nearby entity that JUST
    misses the y_center must NOT bind. Verifies fallback truly removed."""
    from interlock.extract.entity_bind import bind_records_to_entities
    rec = _record(y_top=100, y_bottom=110)  # y_center = 105
    ents = {1: [
        _entity("ALMOST_ENCLOSING", y_top=80, y_bottom=104),  # 1px short
    ]}
    out = bind_records_to_entities([rec], ents)
    assert out[0].entity_tag == ""


def test_no_entities_on_page_leaves_tag_empty() -> None:
    from interlock.extract.entity_bind import bind_records_to_entities
    rec = _record()
    out = bind_records_to_entities([rec], {})
    assert out[0].entity_tag == ""


def test_existing_entity_tag_is_preserved() -> None:
    """Track 1 leading-row marker (e.g. circled digit) wins over spatial binding."""
    from interlock.extract.entity_bind import bind_records_to_entities
    rec = _record(entity_tag="6")
    ents = {1: [_entity("XFMR-001", y_top=0, y_bottom=200)]}
    out = bind_records_to_entities([rec], ents)
    assert out[0].entity_tag == "6"


def test_empty_record_list_returns_empty() -> None:
    from interlock.extract.entity_bind import bind_records_to_entities
    assert bind_records_to_entities([], {1: [_entity("X", 0, 10)]}) == []


def test_page_mismatch_ignored() -> None:
    """Record on page 2 should not bind to entities on page 3."""
    from interlock.extract.entity_bind import bind_records_to_entities
    rec = _record(page=2)
    ents = {3: [_entity("X", y_top=0, y_bottom=10, page=3)]}
    out = bind_records_to_entities([rec], ents)
    assert out[0].entity_tag == ""


def test_returns_new_records_does_not_mutate() -> None:
    from interlock.extract.entity_bind import bind_records_to_entities
    rec = _record(y_top=100, y_bottom=110)
    ents = {1: [_entity("XFMR-001", y_top=80, y_bottom=130)]}
    out = bind_records_to_entities([rec], ents)
    assert rec.entity_tag == ""
    assert out[0].entity_tag == "XFMR-001"


def test_diagram_pages_skip_binding() -> None:
    """v2.8.1 — records on diagram pages must skip the y-enclosure binding.
    The vision lane is the authority on diagram pages; running y-binding
    on top re-introduces the draw-order-y vs visual-y coord-space bug
    (e.g. binding a transformer %Z value to an enclosing fuse entity)."""
    from interlock.extract.entity_bind import bind_records_to_entities
    # Record on page 8 (diagram) with empty tag would otherwise bind to the
    # enclosing entity "KRP-C1600SP" — the exact failure mode seen on
    # doc_a_60pct p8.
    rec = _record(page=8, y_top=100, y_bottom=110)
    ents = {8: [_entity("KRP-C1600SP", y_top=80, y_bottom=130, page=8)]}
    out = bind_records_to_entities([rec], ents, diagram_pages={8})
    assert out[0].entity_tag == "", (
        "diagram-page record must skip binding; expected empty tag, "
        f"got {out[0].entity_tag!r}"
    )


def test_diagram_pages_preserves_existing_tag() -> None:
    """v2.8.1 — diagram-page skip must NOT clear an already-set entity_tag
    (e.g. one populated by the vision lane)."""
    from interlock.extract.entity_bind import bind_records_to_entities
    rec = _record(page=8, entity_tag="LPS-RK-400SP")
    ents = {8: [_entity("KRP-C1600SP", y_top=0, y_bottom=200, page=8)]}
    out = bind_records_to_entities([rec], ents, diagram_pages={8})
    assert out[0].entity_tag == "LPS-RK-400SP"


def test_diagram_pages_non_listed_page_still_binds() -> None:
    """v2.8.1 — only pages in diagram_pages are skipped; others bind."""
    from interlock.extract.entity_bind import bind_records_to_entities
    rec = _record(page=2, y_top=100, y_bottom=110)
    ents = {2: [_entity("XFMR-001", y_top=80, y_bottom=130, page=2)]}
    out = bind_records_to_entities([rec], ents, diagram_pages={8})
    assert out[0].entity_tag == "XFMR-001"
