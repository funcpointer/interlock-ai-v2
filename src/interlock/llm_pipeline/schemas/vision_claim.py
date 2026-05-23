"""Sprint 8 — VisionClaim + VisionPageResult schemas for vision lane.

Vision extractor returns one of these per page. Each VisionClaim ties a
parameter value to its source entity via the entity_id field — no
post-hoc binding step required.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from interlock.llm_pipeline.schemas.page_structure import PageStructure


class VisionClaim(BaseModel):
    """One claim from a vision extraction call: (entity, parameter, value)
    triple with visual-evidence audit trail."""

    model_config = ConfigDict(frozen=True)

    entity_kind: Literal["equipment", "circuit", "section", "row_item"]
    entity_id: str = Field(min_length=1, max_length=128)
    entity_location_hint: str = Field(max_length=200, default="")
    parameter_name: str = Field(min_length=1, max_length=128)
    raw_value: str = Field(min_length=1, max_length=200)
    visual_evidence: str = Field(min_length=1, max_length=400)


class VisionPageResult(BaseModel):
    """Full response for one page's vision call."""

    model_config = ConfigDict(frozen=True)

    page: int = Field(ge=1)
    page_understanding: str = Field(min_length=1, max_length=400)
    page_layout: PageStructure
    claims: list[VisionClaim] = Field(default_factory=list)
