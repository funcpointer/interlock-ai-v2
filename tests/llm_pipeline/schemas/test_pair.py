"""Sprint 4 — PairVerdict pydantic model validation tests."""

from __future__ import annotations

import pytest
from pydantic import ValidationError


def test_pair_verdict_constructs_with_valid_fields() -> None:
    from interlock.llm_pipeline.schemas.pair import PairVerdict
    v = PairVerdict(
        score=0.9,
        rationale="200A and 200A — same physical feeder rating",
        decline_to_pair=False,
    )
    assert v.score == 0.9
    assert "200A" in v.rationale
    assert v.decline_to_pair is False


def test_pair_verdict_decline_defaults_false() -> None:
    from interlock.llm_pipeline.schemas.pair import PairVerdict
    v = PairVerdict(score=0.5, rationale="uncertain")
    assert v.decline_to_pair is False


def test_pair_verdict_score_below_zero_rejected() -> None:
    from interlock.llm_pipeline.schemas.pair import PairVerdict
    with pytest.raises(ValidationError):
        PairVerdict(score=-0.1, rationale="x")


def test_pair_verdict_score_above_one_rejected() -> None:
    from interlock.llm_pipeline.schemas.pair import PairVerdict
    with pytest.raises(ValidationError):
        PairVerdict(score=1.1, rationale="x")


def test_pair_verdict_empty_rationale_rejected() -> None:
    from interlock.llm_pipeline.schemas.pair import PairVerdict
    with pytest.raises(ValidationError):
        PairVerdict(score=0.5, rationale="")


def test_pair_verdict_is_frozen() -> None:
    from interlock.llm_pipeline.schemas.pair import PairVerdict
    v = PairVerdict(score=0.5, rationale="x")
    with pytest.raises(ValidationError):
        v.score = 0.9  # type: ignore[misc]
