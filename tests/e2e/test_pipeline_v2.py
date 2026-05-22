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
