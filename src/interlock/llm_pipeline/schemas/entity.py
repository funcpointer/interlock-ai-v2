"""Sprint 4.5 — DetectedEntity + PageEntities schemas for entity grounding.

The detector returns equipment / circuit / section IDs detected on each
page along with their y-coordinate ranges. Track 1 + Track 2 records bind
to these by y-range enclosure (with nearest-y fallback) so Phase 19's
existing same-entity-only pairing rule can refuse cross-entity matches.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

EntityKind = Literal["equipment", "circuit", "section", "unknown"]


class DetectedEntity(BaseModel):
    """One equipment / circuit / section ID detected on a page."""

    model_config = ConfigDict(frozen=True)

    label: str = Field(min_length=1, max_length=128)
    kind: EntityKind
    y_top: float = Field(ge=0.0)
    y_bottom: float = Field(ge=0.0)
    page: int = Field(ge=1)


class PageEntities(BaseModel):
    """Wrapper for one page's entity list (the LLM returns this shape)."""

    model_config = ConfigDict(frozen=True)

    page: int = Field(ge=1)
    entities: list[DetectedEntity]
