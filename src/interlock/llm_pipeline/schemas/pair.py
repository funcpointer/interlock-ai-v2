"""Sprint 4 — PairVerdict schema for the LLM pairing reranker.

Returned by the Sonnet 4.5 reranker for each weak pair (Track 1
pairing_confidence < 0.75). `score` overwrites pairing_confidence;
`rationale` surfaces in the UI replacing the generic ⚠️ weak pair badge;
`decline_to_pair=True` drops the pair (A and B records flow into the
existing unpaired_a/b lists).
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class PairVerdict(BaseModel):
    """One reranker verdict for a single weak pair."""

    model_config = ConfigDict(frozen=True)

    score: float = Field(ge=0.0, le=1.0)
    rationale: str = Field(min_length=1, max_length=2000)
    decline_to_pair: bool = False
