"""Sprint 5a — Clause + ClauseCitation schemas for standards registry.

Clause is the rich on-disk entry loaded from data/standards/clauses.yaml.
ClauseCitation is the slim projection carried on Flag.cited_clauses + JSON
export — drops applicable_* and tolerance_band so the reviewer-facing
surface only carries human-readable citation fields.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class Clause(BaseModel):
    """One curated clause entry from the YAML registry."""

    model_config = ConfigDict(frozen=True)

    clause_id: str = Field(min_length=1, max_length=64)
    edition_year: int = Field(ge=1900, le=2100)
    source_name: str = Field(min_length=1, max_length=200)
    applicable_families: list[str] = Field(min_length=1)
    applicable_doc_classes: list[str] = Field(default_factory=list)
    tolerance_band: float | None = None
    summary: str = Field(min_length=1, max_length=1000)


class ClauseCitation(BaseModel):
    """Slim subset of Clause carried on Flag + JSON export."""

    model_config = ConfigDict(frozen=True)

    clause_id: str
    edition_year: int
    source_name: str
    summary: str
