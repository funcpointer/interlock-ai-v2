from pathlib import Path
from unittest.mock import MagicMock

import pytest

from interlock.cache import disk as disk_cache
from interlock.ingest.vision_fallback import (
    PROMPT,
    PROMPT_VERSION,
    VisionResult,
    vision_extract_page,
)

DOC_A = Path("fixtures/pdfs/doc_a_60pct.pdf")


@pytest.fixture(autouse=True)
def _clear_vision_cache() -> None:
    """Vision results are diskcache-keyed by PDF content + page; clear the
    namespace between tests so a mocked response in test A doesn't leak
    into test B (same fixture PDF, same page)."""
    disk_cache.clear_namespace("vision-ocr")
    yield
    disk_cache.clear_namespace("vision-ocr")


def test_vision_extract_page_returns_text_and_confidence(mocker) -> None:  # type: ignore[no-untyped-def]
    fake_content = MagicMock()
    fake_content.text = '{"text":"Z=5.75%","confidence":0.92}'
    fake_response = MagicMock(content=[fake_content])
    mocker.patch(
        "interlock.ingest.vision_fallback._call_claude",
        return_value=fake_response,
    )
    result = vision_extract_page(str(DOC_A), page=1)
    assert isinstance(result, VisionResult)
    assert "5.75" in result.text
    assert 0 < result.confidence <= 1


def test_prompt_includes_critical_transcription_directives() -> None:
    """Regression guard for OCR snippet quality.

    Without explicit line-break / column-order / verbatim directives the
    model glues unrelated lines together and downstream excerpts read as
    nonsense ("proceed 0.575%Z, liquid"). Lock those rules in.
    """
    low = PROMPT.lower()
    assert "verbatim" in low, "must demand verbatim transcription"
    assert "line break" in low or "newline" in low, "must require line-break preservation"
    assert "column" in low, "must specify multi-column reading order"
    assert "table" in low, "must specify table-row handling"
    assert "%Z" in PROMPT, "must call out engineering notation"
    assert PROMPT_VERSION, "PROMPT_VERSION must be non-empty (cache invalidation key)"


def test_vision_extract_page_robust_to_extra_prose(mocker) -> None:  # type: ignore[no-untyped-def]
    # Real Claude responses sometimes wrap JSON in fenced code blocks or add prose.
    fake_content = MagicMock()
    fake_content.text = 'Here is the JSON:\n```json\n{"text":"abc","confidence":0.5}\n```'
    fake_response = MagicMock(content=[fake_content])
    mocker.patch(
        "interlock.ingest.vision_fallback._call_claude",
        return_value=fake_response,
    )
    result = vision_extract_page(str(DOC_A), page=1)
    assert result.text == "abc"
    assert result.confidence == 0.5
