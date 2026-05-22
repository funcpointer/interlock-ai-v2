"""Classifier tests — mocked Anthropic calls only. Live-API behaviour
is verified in tests/real_world/test_doc_class_live.py (slow-marked)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from interlock.cache import disk as disk_cache


@pytest.fixture(autouse=True)
def _clear_classify_cache() -> None:
    """Classifications are diskcache-keyed by PDF content hash; clear between
    tests so a mocked response in test A doesn't leak into test B."""
    disk_cache.clear_namespace("doc-class")
    yield
    disk_cache.clear_namespace("doc-class")


def test_sample_pages_single_page_pdf() -> None:
    from interlock.llm_pipeline.classify import _sample_pages
    assert _sample_pages(1) == [1]


def test_sample_pages_two_page_pdf() -> None:
    from interlock.llm_pipeline.classify import _sample_pages
    assert _sample_pages(2) == [1, 2]


def test_sample_pages_three_page_pdf() -> None:
    from interlock.llm_pipeline.classify import _sample_pages
    assert _sample_pages(3) == [1, 2, 3]


def test_sample_pages_ten_page_pdf_picks_first_second_last() -> None:
    from interlock.llm_pipeline.classify import _sample_pages
    assert _sample_pages(10) == [1, 2, 10]


def test_sample_pages_zero_page_returns_empty() -> None:
    from interlock.llm_pipeline.classify import _sample_pages
    assert _sample_pages(0) == []


DOC_A = Path("fixtures/pdfs/doc_a_60pct.pdf")


def _fake_response(text: str) -> MagicMock:
    """Claude-shaped mock carrying a JSON payload in content[0].text."""
    content = MagicMock()
    content.text = text
    return MagicMock(content=[content])


def test_classify_doc_returns_doc_classification(mocker) -> None:  # type: ignore[no-untyped-def]
    from interlock.llm_pipeline.classify import classify_doc
    from interlock.llm_pipeline.schemas.doc_class import DocClass, DocClassification

    fake_json = (
        '{"doc_class":"coordination_study","confidence":0.94,'
        '"reasoning":"TCC log-log curves on pages 4, 6, 8.",'
        '"detected_indicators":["TCC log-log axes","fuse-rating table"],'
        '"pages_consulted":[1,2,9]}'
    )
    spy = mocker.patch(
        "interlock.llm_pipeline.classify._call_claude_classify",
        return_value=_fake_response(fake_json),
    )
    result = classify_doc(str(DOC_A))
    assert isinstance(result, DocClassification)
    assert result.doc_class == DocClass.coordination_study
    assert result.confidence == 0.94
    assert spy.call_count == 1


def test_classify_doc_diskcache_skips_second_call(mocker) -> None:  # type: ignore[no-untyped-def]
    from interlock.llm_pipeline.classify import classify_doc

    fake_json = (
        '{"doc_class":"equipment_spec","confidence":0.9,'
        '"reasoning":"nameplate table","detected_indicators":[],'
        '"pages_consulted":[1]}'
    )
    spy = mocker.patch(
        "interlock.llm_pipeline.classify._call_claude_classify",
        return_value=_fake_response(fake_json),
    )
    classify_doc(str(DOC_A))
    classify_doc(str(DOC_A))
    assert spy.call_count == 1, "second call should hit diskcache, not the API"


def test_classify_doc_unknown_fallback_when_confidence_below_threshold(mocker) -> None:  # type: ignore[no-untyped-def]
    from interlock.llm_pipeline.classify import classify_doc
    from interlock.llm_pipeline.schemas.doc_class import DocClass

    fake_json = (
        '{"doc_class":"pid","confidence":0.4,'
        '"reasoning":"some signals but unsure","detected_indicators":[],'
        '"pages_consulted":[1]}'
    )
    mocker.patch(
        "interlock.llm_pipeline.classify._call_claude_classify",
        return_value=_fake_response(fake_json),
    )
    result = classify_doc(str(DOC_A))
    assert result.doc_class == DocClass.unknown, (
        "confidence 0.4 < 0.6 threshold must collapse to DocClass.unknown"
    )
    assert result.confidence == 0.4  # raw confidence preserved for audit trail


def test_classify_doc_robust_to_fenced_json_response(mocker) -> None:  # type: ignore[no-untyped-def]
    """Real Claude responses sometimes wrap JSON in ```json fences."""
    from interlock.llm_pipeline.classify import classify_doc
    from interlock.llm_pipeline.schemas.doc_class import DocClass

    wrapped = (
        'Here is my classification:\n```json\n'
        '{"doc_class":"bom","confidence":0.85,"reasoning":"item list",'
        '"detected_indicators":[],"pages_consulted":[1]}\n```'
    )
    mocker.patch(
        "interlock.llm_pipeline.classify._call_claude_classify",
        return_value=_fake_response(wrapped),
    )
    result = classify_doc(str(DOC_A))
    assert result.doc_class == DocClass.bom


def test_classify_doc_render_failure_returns_unknown(mocker) -> None:  # type: ignore[no-untyped-def]
    """A render exception (corrupt PDF, missing file) must collapse to
    unknown(0.0) — pipeline keeps running."""
    from interlock.llm_pipeline.classify import classify_doc
    from interlock.llm_pipeline.schemas.doc_class import DocClass

    result = classify_doc("/nonexistent/path/missing.pdf")
    assert result.doc_class == DocClass.unknown
    assert result.confidence == 0.0
    assert "open" in result.reasoning.lower() or "render" in result.reasoning.lower()
