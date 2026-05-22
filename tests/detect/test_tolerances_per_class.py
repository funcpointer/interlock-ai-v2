"""Per-class tolerance overrides (Sprint 1 Phase 24.7)."""

from __future__ import annotations

from interlock.llm_pipeline.schemas.doc_class import DocClass


def test_equipment_spec_uses_tighter_impedance_band() -> None:
    """Manufacturer nameplate (equipment_spec) gets tighter bands than
    coordination_study defaults."""
    from interlock.detect.tolerances import classify

    # 6% impedance deviation with default coordination_study bands = within
    # tolerance (info). With equipment_spec tighter bands (tolerance=5),
    # same deviation = minor.
    default_severity = classify("impedance_pct", 6.0, doc_class=None)
    spec_severity = classify(
        "impedance_pct", 6.0, doc_class=DocClass.equipment_spec,
    )
    assert default_severity == "info"
    assert spec_severity == "minor"


def test_unknown_class_falls_back_to_v1_defaults() -> None:
    """DocClass.unknown must produce the same severity as no doc_class at all."""
    from interlock.detect.tolerances import classify

    a = classify("impedance_pct", 6.0, doc_class=None)
    b = classify("impedance_pct", 6.0, doc_class=DocClass.unknown)
    assert a == b


def test_class_with_no_override_for_family_falls_back_to_defaults() -> None:
    """coordination_study has an explicit (empty) entry — falls through to
    TOLERANCE_TABLE for impedance_pct."""
    from interlock.detect.tolerances import classify

    a = classify("impedance_pct", 6.0, doc_class=None)
    b = classify("impedance_pct", 6.0, doc_class=DocClass.coordination_study)
    assert a == b


def test_classify_back_compat_without_doc_class() -> None:
    """Existing v1 callers (no doc_class) still work unchanged."""
    from interlock.detect.tolerances import classify

    result = classify("impedance_pct", 6.0)
    assert result in {"info", "minor", "major", "critical"}


def test_relay_setting_sheet_tightens_fault_current_band() -> None:
    """Relay setting documents tighten the fault_current_a major boundary
    from 20% (default) to 15% — so a 17% deviation classifies as `minor`
    by default but `major` for a relay setting sheet."""
    from interlock.detect.tolerances import classify

    default_sev = classify("fault_current_a", 17.0, doc_class=None)
    relay_sev = classify(
        "fault_current_a", 17.0, doc_class=DocClass.relay_setting_sheet,
    )
    assert default_sev == "minor"
    assert relay_sev == "major"
