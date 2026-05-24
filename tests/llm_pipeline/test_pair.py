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


def test_boundary_075_does_get_reranked(mocker, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """Phase 19 assigns exactly 0.75 to multi-instance equal-count
    distinct-y pairs. The reranker boundary is INCLUSIVE so these get
    a chance at LLM review — strict-less-than caused boundary-case
    false positives (e.g. cross-instance 'Motor FLA' pairs)."""
    from interlock.llm_pipeline.pair import rerank_weak_pairs
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    spy = mocker.patch(
        "interlock.llm_pipeline.pair._call_claude_pair",
        return_value=_fake_response(
            '{"score":0.05,"rationale":"77 A vs 42 A are different motor parameters",'
            '"decline_to_pair":true}'
        ),
    )
    p = _pair(a_raw="77 A", b_raw="42 A", pairing_conf=0.75)
    out = rerank_weak_pairs([p])
    assert spy.call_count == 1
    assert out == []  # decline_to_pair dropped it


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


def _pair_with_mags(
    a_mag: float, b_mag: float,
    a_raw: str | None = None, b_raw: str | None = None,
    a_tag: str = "", b_tag: str = "",
    a_unit: str | None = "ampere", b_unit: str | None = "ampere",
    pairing_conf: float = 0.55,
) -> AlignedPair:
    a_rec = ParameterRecord(
        doc_id="a", page=2, bbox=(0, 0, 100, 10), section=None,
        span_text=a_raw or f"{a_mag} A", name="Fault Current",
        raw_value=a_raw or f"{a_mag} A",
        normalized_magnitude=a_mag, normalized_unit=a_unit,
        entity_tag=a_tag,
    )
    b_rec = ParameterRecord(
        doc_id="b", page=2, bbox=(0, 0, 100, 10), section=None,
        span_text=b_raw or f"{b_mag} A", name="Fault Current",
        raw_value=b_raw or f"{b_mag} A",
        normalized_magnitude=b_mag, normalized_unit=b_unit,
        entity_tag=b_tag,
    )
    return AlignedPair(
        a=a_rec, b=b_rec,
        name_match_confidence=1.0, value_equivalent=False,
        pairing_confidence=pairing_conf,
    )


def test_decline_overridden_when_magnitudes_differ_more_than_3x(
    mocker, monkeypatch,
) -> None:  # type: ignore[no-untyped-def]
    """v2.8.7 — rerank decline overridden when normalized magnitudes
    differ by > 3× (decimal-shift class). Field-trip TP-2 reproduction:
    20kA vs 200kA with tags 'X1' vs 'Fault X' was being declined by
    rerank on tag-string mismatch even though the 10× magnitude shift
    is textbook decimal-shift mutation."""
    from interlock.llm_pipeline.pair import rerank_weak_pairs
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    p = _pair_with_mags(
        a_mag=20_000, b_mag=200_000,
        a_raw="20000 A", b_raw="200000 A",
        a_tag="X1", b_tag="Fault X",
    )
    mocker.patch(
        "interlock.llm_pipeline.pair._call_claude_pair",
        return_value=_fake_response(
            '{"score":0.05,"rationale":"20000 A vs 200000 A different entities","decline_to_pair":true}'
        ),
    )
    out = rerank_weak_pairs([p])
    assert len(out) == 1, "decline override must keep the pair"
    assert out[0].reranked is True
    assert "override" in (out[0].rerank_rationale or "").lower()


def test_decline_kept_when_magnitudes_within_3x(
    mocker, monkeypatch,
) -> None:  # type: ignore[no-untyped-def]
    """v2.8.7 — override scopes to decimal-shift class. When magnitudes
    are within 3× (no clear decimal-shift signal), rerank's decline
    judgment still wins. Prevents the override from masking
    legitimate cross-entity refusals on small-deviation pairs."""
    from interlock.llm_pipeline.pair import rerank_weak_pairs
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    p = _pair_with_mags(
        a_mag=200, b_mag=400,  # 2× — within decimal-shift threshold
        a_tag="X1", b_tag="X2",
    )
    mocker.patch(
        "interlock.llm_pipeline.pair._call_claude_pair",
        return_value=_fake_response(
            # Rationale references the actual raw values so hallucination
            # guard passes; decline still wins because magnitude ratio
            # is only 2× (below the 3× threshold).
            '{"score":0.05,"rationale":"200 A vs 400 A different entities","decline_to_pair":true}'
        ),
    )
    out = rerank_weak_pairs([p])
    assert out == [], (
        "2× ratio is not decimal-shift; rerank decline should stand"
    )


def test_decline_override_works_with_unit_string_fallback(
    mocker, monkeypatch,
) -> None:  # type: ignore[no-untyped-def]
    """v2.8.7 — Pint refused '20,000A RMS Sym'? Override falls back to
    numeric-token scrape. Locks the behavior so the field-trip TP-2
    shape (string-valued, no Pint mag) still triggers the override."""
    from interlock.llm_pipeline.pair import rerank_weak_pairs
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    p = _pair_with_mags(
        a_mag=None,  # type: ignore[arg-type]
        b_mag=None,  # type: ignore[arg-type]
        a_raw="20,000A RMS Sym",
        b_raw="200,000A RMS Sym",
        a_unit=None, b_unit=None,
        a_tag="X1", b_tag="Fault X",
    )
    mocker.patch(
        "interlock.llm_pipeline.pair._call_claude_pair",
        return_value=_fake_response(
            '{"score":0.05,"rationale":"20,000A RMS Sym vs 200,000A RMS Sym different entities","decline_to_pair":true}'
        ),
    )
    out = rerank_weak_pairs([p])
    assert len(out) == 1, (
        "numeric-scrape fallback must trigger override even when "
        "Pint magnitudes are None"
    )
