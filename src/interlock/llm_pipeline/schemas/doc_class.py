"""DocClass enum + DocClassification Pydantic model.

Locked at 8 classes for Sprint 1. Adding a class is a breaking change
requiring a fresh labelled corpus + re-running the acceptance-gate
eval (see fixtures/eval/gold_doc_class.yaml).
"""

from __future__ import annotations

from enum import Enum


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
