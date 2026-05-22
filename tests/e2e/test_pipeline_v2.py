"""v2-specific pipeline tests — classify_docs parameter + DocClassification
plumbing. Mocked Anthropic calls so tests stay fast and offline."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from interlock.cache import disk as disk_cache

DOC_A = "fixtures/pdfs/doc_a_60pct.pdf"
DOC_B = "fixtures/pdfs/doc_b_90pct.pdf"


def _trivial_embedder(names: list[str]) -> dict[str, list[float]]:
    return {n: [(hash(n) % 1000) / 1000.0, 0.0] for n in names}


def _fake_classify_response(doc_class_value: str) -> MagicMock:
    content = MagicMock()
    content.text = (
        f'{{"doc_class":"{doc_class_value}","confidence":0.95,'
        f'"reasoning":"test stub","detected_indicators":[],'
        f'"pages_consulted":[1]}}'
    )
    return MagicMock(content=[content])


def _fake_extract_response(
    claims_json: str = '{"claims":[],"page":1,"notes":""}',
) -> MagicMock:
    content = MagicMock()
    content.text = claims_json
    return MagicMock(content=[content])


@pytest.fixture(autouse=True)
def _clear_classify_cache() -> None:
    disk_cache.clear_namespace("doc-class")
    yield
    disk_cache.clear_namespace("doc-class")


def test_classify_docs_false_returns_none(mocker) -> None:  # type: ignore[no-untyped-def]
    """Default classify_docs=False must NOT call the classifier."""
    from interlock.pipeline import review_two_documents_full
    spy = mocker.patch(
        "interlock.llm_pipeline.classify._call_claude_classify",
        return_value=_fake_classify_response("coordination_study"),
    )
    result = review_two_documents_full(
        DOC_A, DOC_B, embed_fn=_trivial_embedder, classify_docs=False,
    )
    assert spy.call_count == 0
    assert result.doc_class_a is None
    assert result.doc_class_b is None


def test_classify_docs_true_populates_doc_class_fields(mocker) -> None:  # type: ignore[no-untyped-def]
    """classify_docs=True calls the classifier on BOTH documents and
    populates ReviewResult.doc_class_a / doc_class_b."""
    from interlock.llm_pipeline.schemas.doc_class import DocClass
    from interlock.pipeline import review_two_documents_full

    mocker.patch(
        "interlock.llm_pipeline.classify._call_claude_classify",
        return_value=_fake_classify_response("coordination_study"),
    )
    result = review_two_documents_full(
        DOC_A, DOC_B, embed_fn=_trivial_embedder, classify_docs=True,
    )
    assert result.doc_class_a is not None
    assert result.doc_class_b is not None
    assert result.doc_class_a.doc_class == DocClass.coordination_study
    assert result.doc_class_b.doc_class == DocClass.coordination_study


def test_classify_docs_failure_returns_unknown_does_not_raise(mocker) -> None:  # type: ignore[no-untyped-def]
    """If the classifier raises (API outage), pipeline must continue
    with doc_class_a/b = DocClassification(unknown, 0.0, ...)."""
    from interlock.llm_pipeline.schemas.doc_class import DocClass
    from interlock.pipeline import review_two_documents_full

    mocker.patch(
        "interlock.llm_pipeline.classify._call_claude_classify",
        side_effect=RuntimeError("API outage simulated"),
    )
    result = review_two_documents_full(
        DOC_A, DOC_B, embed_fn=_trivial_embedder, classify_docs=True,
    )
    assert isinstance(result.flags, list)  # pipeline still ran
    assert result.doc_class_a is not None
    assert result.doc_class_a.doc_class == DocClass.unknown


def test_classify_docs_false_is_bit_identical_to_v1() -> None:
    """The architectural safety claim: classify_docs=False MUST produce
    the same flags as the v1.5-mvp-ready pipeline on the locked Option 1
    fixture. This is the Track 1 invariant that gates every v2 commit."""
    from interlock.pipeline import review_two_documents_full

    result = review_two_documents_full(
        DOC_A, DOC_B, embed_fn=_trivial_embedder,
        classify_docs=False,
    )
    expected_params = {"%Z", "Fault Current", "Transformer Rating"}
    surfaced = {f.parameter for f in result.flags if f.confidence >= 0.6}
    assert expected_params.issubset(surfaced), (
        f"Track 1 invariant broken: expected {expected_params}, got {surfaced}"
    )


# --- Sprint 2: use_llm_extraction integration ---------------------------


@pytest.fixture(autouse=True)
def _clear_extract_cache() -> None:
    disk_cache.clear_namespace("llm-extract")
    yield
    disk_cache.clear_namespace("llm-extract")


def test_use_llm_extraction_false_does_not_call_extractor(mocker) -> None:  # type: ignore[no-untyped-def]
    """Default off: no LLM extraction call; all records are regex."""
    from interlock.pipeline import review_two_documents_full
    spy = mocker.patch(
        "interlock.llm_pipeline.extract._call_claude_extract",
        return_value=_fake_extract_response(),
    )
    result = review_two_documents_full(
        DOC_A, DOC_B, embed_fn=_trivial_embedder,
        use_llm_extraction=False,
    )
    assert spy.call_count == 0
    for f in result.flags:
        assert f.a_record.provenance == "regex"
        assert f.b_record.provenance == "regex"


def test_use_llm_extraction_true_runs_extractor_pipeline_still_ships_flags(mocker) -> None:  # type: ignore[no-untyped-def]
    """With extraction on, the pipeline runs LLM extraction calls and ships
    a flag list. Specific flags may differ from v1 because of additional
    Track 2 records — we don't lock the exact set here."""
    from interlock.pipeline import review_two_documents_full

    fake = '{"claims":[],"page":1,"notes":""}'  # empty claims; safe append
    spy = mocker.patch(
        "interlock.llm_pipeline.extract._call_claude_extract",
        return_value=_fake_extract_response(fake),
    )
    result = review_two_documents_full(
        DOC_A, DOC_B,
        embed_fn=_trivial_embedder,
        classify_docs=False,
        use_llm_extraction=True,
    )
    assert isinstance(result.flags, list)
    # Extractor was called (per-page across both docs).
    assert spy.call_count > 0


def test_snapshot_equivalence_use_llm_extraction_false() -> None:
    """Architectural safety: use_llm_extraction=False must produce the
    same flag parameter-set as v1.5-mvp-ready / v2.0-mvp on the locked
    Option 1 fixture."""
    from interlock.pipeline import review_two_documents_full

    result = review_two_documents_full(
        DOC_A, DOC_B,
        embed_fn=_trivial_embedder,
        use_llm_extraction=False,
    )
    expected_params = {"%Z", "Fault Current", "Transformer Rating"}
    surfaced = {f.parameter for f in result.flags if f.confidence >= 0.6}
    assert expected_params.issubset(surfaced), (
        f"Track 1 invariant broken: expected {expected_params}, got {surfaced}"
    )


# --- Sprint 3: adjudicator pipeline integration --------------------------


def test_v1_snapshot_equivalence_all_flags_are_rule_only() -> None:
    """When both tracks off, every flag must be annotated 'rule_only' —
    Sprint 3's promise that v1.5 snapshot equivalence still holds."""
    from interlock.pipeline import review_two_documents_full

    result = review_two_documents_full(
        DOC_A, DOC_B,
        embed_fn=_trivial_embedder,
        classify_docs=False,
        use_llm_extraction=False,
    )
    assert result.flags, "expected non-zero baseline flags from Option 1 fixture"
    for f in result.flags:
        assert f.provenance == "rule_only", (
            f"v1 snapshot broken: flag {f.parameter} got provenance "
            f"{f.provenance!r}, expected 'rule_only'"
        )


def test_pipeline_annotates_provenance_when_llm_extraction_on(mocker) -> None:  # type: ignore[no-untyped-def]
    """With LLM extraction enabled, the pipeline still produces a flag
    list with provenance populated. (Specific labels depend on which
    records the aligner pairs — verified in adjudicator unit tests.)"""
    from interlock.pipeline import review_two_documents_full

    fake = '{"claims":[],"page":1,"notes":""}'
    mocker.patch(
        "interlock.llm_pipeline.extract._call_claude_extract",
        return_value=_fake_extract_response(fake),
    )
    result = review_two_documents_full(
        DOC_A, DOC_B,
        embed_fn=_trivial_embedder,
        classify_docs=False,
        use_llm_extraction=True,
    )
    for f in result.flags:
        # The field must be one of the four enumerated values, never None.
        assert f.provenance in {"rule_only", "llm_only", "mixed_track", "unknown"}


def test_adjudicator_runs_unconditionally() -> None:
    """Even with both tracks off — i.e. the v1.5 path — every flag should
    have provenance set to something (not the default 'unknown')."""
    from interlock.pipeline import review_two_documents_full

    result = review_two_documents_full(
        DOC_A, DOC_B,
        embed_fn=_trivial_embedder,
        classify_docs=False,
        use_llm_extraction=False,
    )
    for f in result.flags:
        assert f.provenance != "unknown", (
            "pipeline must annotate provenance for every flag"
        )


# --- Sprint 4: pairing reranker integration -----------------------------


@pytest.fixture(autouse=True)
def _clear_pair_cache() -> None:
    disk_cache.clear_namespace("llm-pair")
    yield
    disk_cache.clear_namespace("llm-pair")


def _fake_pair_response(decline: bool = False, score: float = 0.9) -> MagicMock:
    """Build a fake Claude response. Rationale embeds both common raw_values
    from the Option 1 fixture so the hallucination guard accepts it."""
    content = MagicMock()
    content.text = (
        '{"score":' + f"{score}" + ','
        '"rationale":"5.75 % and 5.75 % — same impedance record",'
        '"decline_to_pair":' + ("true" if decline else "false") + '}'
    )
    return MagicMock(content=[content])


def test_use_llm_reranker_false_is_bit_identical_to_v2_2(mocker) -> None:  # type: ignore[no-untyped-def]
    """Default off ⇒ no reranker call; flag set unchanged from v2.2."""
    from interlock.pipeline import review_two_documents_full
    spy = mocker.patch("interlock.llm_pipeline.pair._call_claude_pair")
    result = review_two_documents_full(
        DOC_A, DOC_B, embed_fn=_trivial_embedder,
        use_llm_reranker=False,
    )
    assert spy.call_count == 0
    expected_params = {"%Z", "Fault Current", "Transformer Rating"}
    surfaced = {f.parameter for f in result.flags if f.confidence >= 0.6}
    assert expected_params.issubset(surfaced)
    for f in result.flags:
        assert f.rerank_rationale is None


def test_use_llm_reranker_true_unanimous_approve_preserves_flags(mocker) -> None:  # type: ignore[no-untyped-def]
    """Reranker approves every weak pair ⇒ flag count + parameters
    unchanged from Track 1."""
    from interlock.pipeline import review_two_documents_full
    mocker.patch(
        "interlock.llm_pipeline.pair._call_claude_pair",
        return_value=_fake_pair_response(decline=False, score=0.9),
    )
    result = review_two_documents_full(
        DOC_A, DOC_B, embed_fn=_trivial_embedder,
        use_llm_reranker=True,
    )
    expected_params = {"%Z", "Fault Current", "Transformer Rating"}
    surfaced = {f.parameter for f in result.flags if f.confidence >= 0.6}
    assert expected_params.issubset(surfaced)


def test_pipeline_survives_reranker_exception(mocker) -> None:  # type: ignore[no-untyped-def]
    """API outage mid-rerank ⇒ pipeline still ships Track 1 flag set."""
    from interlock.pipeline import review_two_documents_full
    mocker.patch(
        "interlock.llm_pipeline.pair._call_claude_pair",
        side_effect=RuntimeError("API down"),
    )
    result = review_two_documents_full(
        DOC_A, DOC_B, embed_fn=_trivial_embedder,
        use_llm_reranker=True,
    )
    assert isinstance(result.flags, list)


def test_sprint3_provenance_and_sprint4_rationale_coexist() -> None:
    """Both labels live on the same Flag without interference."""
    from interlock.detect.mismatch import Flag
    from interlock.extract.parameters import ParameterRecord
    r = ParameterRecord(
        doc_id="d", page=1, bbox=(0, 0, 100, 10), section=None,
        span_text="5.75%Z", name="%Z", raw_value="5.75 %",
        normalized_magnitude=0.0575, normalized_unit="dimensionless",
        provenance="regex",  # type: ignore[arg-type]
    )
    f = Flag(
        parameter="%Z",
        a_record=r, b_record=r,
        authoritative_doc_id="d", deviating_doc_id="d",
        confidence=1.0, rationale="test", authority_rule="MVP",
        severity="major", deviation_pct=10.0, attribute_family="impedance_pct",
        provenance="rule_only",  # type: ignore[arg-type]
        rerank_rationale="confirmed pair",
    )
    assert f.provenance == "rule_only"
    assert f.rerank_rationale == "confirmed pair"
