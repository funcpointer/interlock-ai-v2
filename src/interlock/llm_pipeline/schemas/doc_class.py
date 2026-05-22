"""DocClass enum + DocClassification Pydantic model.

Locked at 8 classes for Sprint 1. Adding a class is a breaking change
requiring a fresh labelled corpus + re-running the acceptance-gate
eval (see fixtures/eval/gold_doc_class.yaml).
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class DocClass(str, Enum):
    """Engineering document class. ``unknown`` is the fallback when the
    classifier's confidence drops below the threshold; downstream
    pipeline treats ``unknown`` as the v1 default route."""

    coordination_study = "coordination_study"
    equipment_spec = "equipment_spec"
    relay_setting_sheet = "relay_setting_sheet"
    hvac_schedule = "hvac_schedule"
    pid = "pid"  # Piping & Instrumentation Diagram
    bom = "bom"
    civil_drawing = "civil_drawing"
    unknown = "unknown"


class DocClassification(BaseModel):
    """Classifier output. ``confidence < 0.6`` collapses to ``DocClass.unknown``
    in the public ``classify_doc()`` API — this model is the raw shape; the
    classifier applies the fallback rule."""

    doc_class: DocClass
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str = Field(
        description="1-3 sentences explaining the classification choice"
    )
    detected_indicators: list[str] = Field(
        default_factory=list,
        description=(
            "Concrete visual / textual signals that drove the call "
            "(e.g. 'TCC log-log axes', 'IEEE C57 nameplate row layout')."
        ),
    )
    pages_consulted: list[int] = Field(
        default_factory=list,
        description="Page numbers (1-indexed) rendered to the model.",
    )

    model_config = {"frozen": True}  # immutable; audit-trail-friendly
