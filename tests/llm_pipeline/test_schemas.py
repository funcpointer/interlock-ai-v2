"""Schemas for the doc-class classifier (Sprint 1)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError


def test_doc_class_enum_has_eight_values() -> None:
    """Sprint 1 schema locks in 8 classes. Adding a class is a breaking
    change that requires fresh corpus + acceptance-gate adjustment."""
    from interlock.llm_pipeline.schemas.doc_class import DocClass
    expected = {
        "coordination_study", "equipment_spec", "relay_setting_sheet",
        "hvac_schedule", "pid", "bom", "civil_drawing", "unknown",
    }
    actual = {c.value for c in DocClass}
    assert actual == expected


def test_doc_class_values_are_str_subclass() -> None:
    """Enum values must be plain strings so JSON serialization is clean."""
    from interlock.llm_pipeline.schemas.doc_class import DocClass
    assert isinstance(DocClass.coordination_study.value, str)
    assert DocClass.coordination_study.value == "coordination_study"


def test_doc_classification_minimal_valid() -> None:
    """Required fields: doc_class, confidence, reasoning. Optional lists default empty."""
    from interlock.llm_pipeline.schemas.doc_class import DocClass, DocClassification
    c = DocClassification(
        doc_class=DocClass.coordination_study,
        confidence=0.95,
        reasoning="Eaton TCC layout; log-log curves on pages 4, 6, 8.",
    )
    assert c.doc_class == DocClass.coordination_study
    assert c.confidence == 0.95
    assert c.detected_indicators == []
    assert c.pages_consulted == []


def test_doc_classification_full() -> None:
    from interlock.llm_pipeline.schemas.doc_class import DocClass, DocClassification
    c = DocClassification(
        doc_class=DocClass.equipment_spec,
        confidence=0.92,
        reasoning="IEEE C57 nameplate layout with rated kVA + voltage rows.",
        detected_indicators=["rated kVA row", "primary voltage row", "BIL field"],
        pages_consulted=[1, 2, 5],
    )
    assert c.detected_indicators == ["rated kVA row", "primary voltage row", "BIL field"]
    assert c.pages_consulted == [1, 2, 5]


def test_doc_classification_confidence_above_one_rejected() -> None:
    from interlock.llm_pipeline.schemas.doc_class import DocClass, DocClassification
    with pytest.raises(ValidationError):
        DocClassification(
            doc_class=DocClass.unknown,
            confidence=1.5,
            reasoning="impossible",
        )


def test_doc_classification_confidence_below_zero_rejected() -> None:
    from interlock.llm_pipeline.schemas.doc_class import DocClass, DocClassification
    with pytest.raises(ValidationError):
        DocClassification(
            doc_class=DocClass.unknown,
            confidence=-0.1,
            reasoning="negative",
        )


def test_doc_classification_serializes_class_value_as_string() -> None:
    """model_dump_json must serialise DocClass to its .value string."""
    from interlock.llm_pipeline.schemas.doc_class import DocClass, DocClassification
    c = DocClassification(
        doc_class=DocClass.coordination_study,
        confidence=0.9,
        reasoning="ok",
    )
    payload = c.model_dump_json()
    assert '"coordination_study"' in payload
