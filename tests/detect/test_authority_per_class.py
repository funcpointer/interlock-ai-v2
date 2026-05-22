"""Per-class authority hierarchy (Sprint 1 Phase 24.7)."""

from __future__ import annotations

from interlock.llm_pipeline.schemas.doc_class import DocClass


def test_equipment_spec_beats_coordination_study_for_transformer_params() -> None:
    """Spec sheet is more authoritative than a study for transformer params."""
    from interlock.detect.authority import resolve_authority

    side, _rationale = resolve_authority(
        DocClass.coordination_study, DocClass.equipment_spec,
        parameter_family="transformer_params",
    )
    assert side == "doc_b"  # equipment_spec is on side b


def test_equipment_spec_on_side_a_still_wins() -> None:
    """Order-independence."""
    from interlock.detect.authority import resolve_authority

    side, _ = resolve_authority(
        DocClass.equipment_spec, DocClass.coordination_study,
        parameter_family="transformer_params",
    )
    assert side == "doc_a"


def test_relay_setting_sheet_wins_for_relay_settings() -> None:
    from interlock.detect.authority import resolve_authority
    side, _ = resolve_authority(
        DocClass.relay_setting_sheet, DocClass.equipment_spec,
        parameter_family="relay_settings",
    )
    assert side == "doc_a"


def test_unknown_family_falls_back_to_v1_doc_a_authoritative() -> None:
    from interlock.detect.authority import resolve_authority
    side, rationale = resolve_authority(
        DocClass.pid, DocClass.bom, parameter_family="unrelated_thing",
    )
    assert side == "doc_a"
    assert "default" in rationale.lower() or "v1" in rationale.lower()


def test_both_unknown_classes_fall_back_to_v1() -> None:
    from interlock.detect.authority import resolve_authority
    side, _ = resolve_authority(
        DocClass.unknown, DocClass.unknown,
        parameter_family="transformer_params",
    )
    assert side == "doc_a"
