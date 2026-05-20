from interlock.extract.sections import attribute_sections
from interlock.ingest.text import Span


def _span(text: str, page: int, y: float) -> Span:
    return Span(doc_id="d", page=page, bbox=(0, y, 100, y + 10), text=text)


def test_heading_attached_to_following_spans_on_same_page() -> None:
    spans = [
        _span("1. Overview", 1, 50),
        _span("Some text under overview.", 1, 70),
        _span("2. Coordination Tables", 1, 200),
        _span("Z = 5.75%", 1, 220),
    ]
    out = attribute_sections(spans)
    by_text = {s.span.text: s.section for s in out}
    assert by_text["Some text under overview."] == "1. Overview"
    assert by_text["Z = 5.75%"] == "2. Coordination Tables"


def test_heading_does_not_leak_across_pages() -> None:
    spans = [
        _span("1. Overview", 1, 50),
        _span("Some text.", 1, 70),
        _span("Other page first line.", 2, 50),
    ]
    out = attribute_sections(spans)
    by_text = {s.span.text: s.section for s in out}
    assert by_text["Some text."] == "1. Overview"
    # Page 2 first line has no preceding heading on its page.
    assert by_text["Other page first line."] is None


def test_time_current_curve_pattern_recognized_as_heading() -> None:
    spans = [
        _span("Time Current Curve #1 (TCC1)", 3, 30),
        _span("Z = 5.75%", 3, 60),
    ]
    out = attribute_sections(spans)
    by_text = {s.span.text: s.section for s in out}
    assert by_text["Z = 5.75%"] == "Time Current Curve #1 (TCC1)"


def test_attribute_preserves_span_object() -> None:
    spans = [_span("1. Overview", 1, 50), _span("Text", 1, 70)]
    out = attribute_sections(spans)
    assert out[0].span.text == "1. Overview"
    assert out[1].span.text == "Text"
    assert out[1].page == 1
