"""Sprint 8 — VisionClaim + VisionPageResult validation tests."""

from __future__ import annotations

import pytest
from pydantic import ValidationError


def test_vision_claim_constructs() -> None:
    from interlock.llm_pipeline.schemas.vision_claim import VisionClaim
    c = VisionClaim(
        entity_kind="equipment",
        entity_id="LPS-RK-100SP",
        entity_location_hint="mid-left of one-line diagram",
        parameter_name="Fuse Designation",
        raw_value="LPS-RK-100SP",
        visual_evidence="Label appears next to a fuse symbol below the transformer.",
    )
    assert c.entity_kind == "equipment"
    assert c.entity_id == "LPS-RK-100SP"


def test_vision_claim_kind_enum_validated() -> None:
    from interlock.llm_pipeline.schemas.vision_claim import VisionClaim
    with pytest.raises(ValidationError):
        VisionClaim(
            entity_kind="bogus",  # type: ignore[arg-type]
            entity_id="X", entity_location_hint="",
            parameter_name="P", raw_value="V", visual_evidence="E",
        )


def test_vision_claim_min_lengths_enforced() -> None:
    from interlock.llm_pipeline.schemas.vision_claim import VisionClaim
    with pytest.raises(ValidationError):
        VisionClaim(
            entity_kind="equipment",
            entity_id="",  # min_length=1
            entity_location_hint="", parameter_name="P",
            raw_value="V", visual_evidence="E",
        )


def test_vision_claim_is_frozen() -> None:
    from interlock.llm_pipeline.schemas.vision_claim import VisionClaim
    c = VisionClaim(
        entity_kind="equipment", entity_id="X", entity_location_hint="",
        parameter_name="P", raw_value="V", visual_evidence="E",
    )
    with pytest.raises(ValidationError):
        c.entity_id = "Y"  # type: ignore[misc]


def test_vision_page_result_constructs() -> None:
    from interlock.llm_pipeline.schemas.vision_claim import VisionClaim, VisionPageResult
    r = VisionPageResult(
        page=1,
        page_understanding="One-line diagram with TCC plot",
        page_layout="diagram",
        claims=[
            VisionClaim(
                entity_kind="equipment", entity_id="X",
                entity_location_hint="top-left",
                parameter_name="P", raw_value="V", visual_evidence="E",
            ),
        ],
    )
    assert r.page == 1
    assert len(r.claims) == 1


def test_vision_page_result_empty_claims_ok() -> None:
    from interlock.llm_pipeline.schemas.vision_claim import VisionPageResult
    r = VisionPageResult(
        page=1, page_understanding="empty page",
        page_layout="prose", claims=[],
    )
    assert r.claims == []
