"""Sprint 4 — reranker unit tests (mocked Claude)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from interlock.align.exact import AlignedPair
from interlock.cache import disk as disk_cache
from interlock.extract.parameters import ParameterRecord


def _record(name: str = "Feeder Rating", raw: str = "200 A", page: int = 2) -> ParameterRecord:
    return ParameterRecord(
        doc_id="d", page=page, bbox=(0, 0, 100, 10), section=None,
        span_text=raw, name=name, raw_value=raw,
        normalized_magnitude=200.0, normalized_unit="ampere",
    )


def _pair(
    a_raw: str = "200 A",
    b_raw: str = "200 A",
    pairing_conf: float = 0.5,
    a_page: int = 2,
    b_page: int = 2,
) -> AlignedPair:
    return AlignedPair(
        a=_record(raw=a_raw, page=a_page),
        b=_record(raw=b_raw, page=b_page),
        name_match_confidence=1.0,
        value_equivalent=False,
        pairing_confidence=pairing_conf,
    )


def _fake_response(text: str) -> MagicMock:
    content = MagicMock()
    content.text = text
    return MagicMock(content=[content])


@pytest.fixture(autouse=True)
def _clear_pair_cache() -> None:
    disk_cache.clear_namespace("llm-pair")
    yield
    disk_cache.clear_namespace("llm-pair")


def test_strong_pairs_pass_through_untouched(mocker, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from interlock.llm_pipeline.pair import rerank_weak_pairs
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    spy = mocker.patch("interlock.llm_pipeline.pair._call_claude_pair")
    p = _pair(pairing_conf=0.9)
    out = rerank_weak_pairs([p])
    assert spy.call_count == 0
    assert len(out) == 1
    assert out[0].reranked is False
    assert out[0].pairing_confidence == 0.9


def test_decline_to_pair_drops_pair(mocker, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from interlock.llm_pipeline.pair import rerank_weak_pairs
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    mocker.patch(
        "interlock.llm_pipeline.pair._call_claude_pair",
        return_value=_fake_response(
            '{"score":0.05,"rationale":"200 A vs 400 A are different feeders","decline_to_pair":true}'
        ),
    )
    p = _pair(a_raw="200 A", b_raw="400 A")
    out = rerank_weak_pairs([p])
    assert out == []


def test_keep_with_score_overwrites_pairing_confidence(mocker, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from interlock.llm_pipeline.pair import rerank_weak_pairs
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    mocker.patch(
        "interlock.llm_pipeline.pair._call_claude_pair",
        return_value=_fake_response(
            '{"score":0.95,"rationale":"200 A on both pages — same feeder","decline_to_pair":false}'
        ),
    )
    p = _pair(pairing_conf=0.5)
    out = rerank_weak_pairs([p])
    assert len(out) == 1
    assert out[0].pairing_confidence == 0.95
    assert out[0].reranked is True
    assert out[0].rerank_rationale is not None
    assert "200 A" in out[0].rerank_rationale


def test_hallucination_guard_keeps_track_1(mocker, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """Rationale mentions neither raw_value → reject the verdict."""
    from interlock.llm_pipeline.pair import rerank_weak_pairs
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    mocker.patch(
        "interlock.llm_pipeline.pair._call_claude_pair",
        return_value=_fake_response(
            '{"score":0.99,"rationale":"both records describe the same equipment","decline_to_pair":false}'
        ),
    )
    p = _pair(a_raw="200 A", b_raw="400 A", pairing_conf=0.5)
    out = rerank_weak_pairs([p])
    assert len(out) == 1
    assert out[0].pairing_confidence == 0.5  # unchanged
    assert out[0].reranked is False
    assert out[0].rerank_rationale is None


def test_api_failure_keeps_track_1(mocker, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from interlock.llm_pipeline.pair import rerank_weak_pairs
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    mocker.patch(
        "interlock.llm_pipeline.pair._call_claude_pair",
        side_effect=RuntimeError("API down"),
    )
    p = _pair(pairing_conf=0.5)
    out = rerank_weak_pairs([p])
    assert len(out) == 1
    assert out[0].pairing_confidence == 0.5
    assert out[0].reranked is False


def test_parse_failure_keeps_track_1(mocker, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """Claude returned garbage JSON → keep Track 1 verdict."""
    from interlock.llm_pipeline.pair import rerank_weak_pairs
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    mocker.patch(
        "interlock.llm_pipeline.pair._call_claude_pair",
        return_value=_fake_response("not json at all"),
    )
    p = _pair(pairing_conf=0.5)
    out = rerank_weak_pairs([p])
    assert len(out) == 1
    assert out[0].pairing_confidence == 0.5
    assert out[0].reranked is False


def test_validation_failure_keeps_track_1(mocker, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """Score outside [0,1] → pydantic rejects → keep Track 1."""
    from interlock.llm_pipeline.pair import rerank_weak_pairs
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    mocker.patch(
        "interlock.llm_pipeline.pair._call_claude_pair",
        return_value=_fake_response(
            '{"score":1.5,"rationale":"200 A","decline_to_pair":false}'
        ),
    )
    p = _pair(pairing_conf=0.5)
    out = rerank_weak_pairs([p])
    assert len(out) == 1
    assert out[0].reranked is False


def test_order_preserved_across_parallel_calls(mocker, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """Returned order matches input order even with parallel dispatch."""
    from interlock.llm_pipeline.pair import rerank_weak_pairs
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    def _resp_for(*args, **kwargs):  # type: ignore[no-untyped-def]
        # Return a generic response mentioning a numeric value that any
        # raw_value will substring-match (each raw is e.g. "100 A", "200 A",
        # so just include the value range from input prompt).
        return _fake_response(
            '{"score":0.8,"rationale":"value appears as 100 A 200 A 300 A '
            '400 A 500 A on both pages","decline_to_pair":false}'
        )

    mocker.patch(
        "interlock.llm_pipeline.pair._call_claude_pair",
        side_effect=_resp_for,
    )
    pairs = [
        _pair(a_raw=f"{i*100} A", b_raw=f"{i*100} A", pairing_conf=0.5)
        for i in (1, 2, 3, 4, 5)
    ]
    out = rerank_weak_pairs(pairs)
    assert len(out) == 5
    assert [p.a.raw_value for p in out] == ["100 A", "200 A", "300 A", "400 A", "500 A"]


def test_diskcache_hit_short_circuits(mocker, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from interlock.llm_pipeline.pair import rerank_weak_pairs
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    spy = mocker.patch(
        "interlock.llm_pipeline.pair._call_claude_pair",
        return_value=_fake_response(
            '{"score":0.9,"rationale":"200 A on both","decline_to_pair":false}'
        ),
    )
    p = _pair(pairing_conf=0.5)
    rerank_weak_pairs([p])
    assert spy.call_count == 1
    rerank_weak_pairs([p])  # second call — cache hit
    assert spy.call_count == 1


def test_empty_input_returns_empty(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from interlock.llm_pipeline.pair import rerank_weak_pairs
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    assert rerank_weak_pairs([]) == []
