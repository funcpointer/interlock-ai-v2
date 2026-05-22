"""Sprint 4.5 — DetectedEntity + PageEntities schema tests."""

from __future__ import annotations

import pytest
from pydantic import ValidationError


def test_detected_entity_constructs_with_valid_fields() -> None:
    from interlock.llm_pipeline.schemas.entity import DetectedEntity
    e = DetectedEntity(label="XFMR-001", kind="equipment", y_top=100.0, y_bottom=150.0, page=2)
    assert e.label == "XFMR-001"
    assert e.kind == "equipment"
    assert e.y_top == 100.0
    assert e.y_bottom == 150.0
    assert e.page == 2


def test_detected_entity_kind_rejects_unknown_literal() -> None:
    from interlock.llm_pipeline.schemas.entity import DetectedEntity
    with pytest.raises(ValidationError):
        DetectedEntity(label="X", kind="bogus", y_top=0.0, y_bottom=10.0, page=1)


def test_detected_entity_label_min_length() -> None:
    from interlock.llm_pipeline.schemas.entity import DetectedEntity
    with pytest.raises(ValidationError):
        DetectedEntity(label="", kind="equipment", y_top=0.0, y_bottom=10.0, page=1)


def test_detected_entity_label_max_length() -> None:
    from interlock.llm_pipeline.schemas.entity import DetectedEntity
    with pytest.raises(ValidationError):
        DetectedEntity(label="x" * 129, kind="equipment", y_top=0.0, y_bottom=10.0, page=1)


def test_detected_entity_y_negative_rejected() -> None:
    from interlock.llm_pipeline.schemas.entity import DetectedEntity
    with pytest.raises(ValidationError):
        DetectedEntity(label="X", kind="equipment", y_top=-1.0, y_bottom=10.0, page=1)


def test_detected_entity_page_must_be_positive() -> None:
    from interlock.llm_pipeline.schemas.entity import DetectedEntity
    with pytest.raises(ValidationError):
        DetectedEntity(label="X", kind="equipment", y_top=0.0, y_bottom=10.0, page=0)


def test_detected_entity_is_frozen() -> None:
    from interlock.llm_pipeline.schemas.entity import DetectedEntity
    e = DetectedEntity(label="X", kind="equipment", y_top=0.0, y_bottom=10.0, page=1)
    with pytest.raises(ValidationError):
        e.label = "Y"  # type: ignore[misc]


def test_page_entities_wraps_list() -> None:
    from interlock.llm_pipeline.schemas.entity import DetectedEntity, PageEntities
    ents = [
        DetectedEntity(label="A", kind="equipment", y_top=0.0, y_bottom=10.0, page=1),
        DetectedEntity(label="B", kind="circuit", y_top=20.0, y_bottom=30.0, page=1),
    ]
    pe = PageEntities(page=1, entities=ents)
    assert pe.page == 1
    assert len(pe.entities) == 2
    assert pe.entities[0].label == "A"


def test_page_entities_empty_list_ok() -> None:
    from interlock.llm_pipeline.schemas.entity import PageEntities
    pe = PageEntities(page=1, entities=[])
    assert pe.entities == []
