from pathlib import Path
from unittest.mock import MagicMock

from interlock.ingest.vision_fallback import VisionResult, vision_extract_page

DOC_A = Path("fixtures/pdfs/doc_a_60pct.pdf")


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
