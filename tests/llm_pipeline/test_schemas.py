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
