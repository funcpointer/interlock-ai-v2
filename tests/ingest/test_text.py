from pathlib import Path

import fitz

from interlock.ingest.text import Span, aggregate_line_spans, extract_spans

PROBE = Path("fixtures/probes/symbol_probe.pdf")
DOC_A = Path("fixtures/pdfs/doc_a_60pct.pdf")
REQUIRED = ["Ω", "μ", "μF", "kV", "MVA", "θ", "Δ", "cos φ", "°C", "±", "≤", "≥"]


def test_symbol_probe_roundtrip() -> None:
    assert PROBE.exists(), "symbol probe PDF must exist"
    doc = fitz.open(str(PROBE))
    text = "".join(p.get_text("text") for p in doc)
    doc.close()
    missing = [s for s in REQUIRED if s not in text]
    assert not missing, f"symbols missing from extracted text: {missing}"


def test_extract_spans_returns_text_page_bbox() -> None:
    spans = extract_spans(str(PROBE))
    assert spans, "expected at least one span"
    for s in spans:
        assert isinstance(s, Span)
        assert s.text
        assert s.page >= 1
        assert len(s.bbox) == 4
        assert s.bbox[2] > s.bbox[0] and s.bbox[3] > s.bbox[1]


def test_extract_spans_preserves_unicode() -> None:
    spans = extract_spans(str(PROBE))
    joined = " ".join(s.text for s in spans)
    for sym in ["Ω", "μF", "kV", "Δ", "θ", "cos φ"]:
        assert sym in joined, f"missing {sym}"


def test_extract_spans_doc_id_propagates() -> None:
    spans = extract_spans(str(PROBE), doc_id="probe")
    assert all(s.doc_id == "probe" for s in spans)


def test_aggregate_line_spans_joins_same_y_within_tolerance() -> None:
    # Two spans on roughly the same y coordinate should join into one logical line.
    a = Span(doc_id="d", page=1, bbox=(10, 100, 50, 110), text="Rated")
    b = Span(doc_id="d", page=1, bbox=(55, 101, 100, 110), text="Voltage")
    c = Span(doc_id="d", page=1, bbox=(10, 200, 100, 210), text="Other")
    merged = aggregate_line_spans([a, b, c], y_tol=3.0)
    texts = [m.text for m in merged]
    assert "Rated Voltage" in texts
    assert "Other" in texts


def test_aggregate_line_spans_preserves_page_isolation() -> None:
    # Same y on different pages should NOT join.
    a = Span(doc_id="d", page=1, bbox=(10, 100, 50, 110), text="A")
    b = Span(doc_id="d", page=2, bbox=(10, 100, 50, 110), text="B")
    merged = aggregate_line_spans([a, b])
    texts = [m.text for m in merged]
    assert "A" in texts and "B" in texts
    assert "A B" not in texts


def test_extract_spans_doc_a_native_text() -> None:
    # Sanity: real fixture extracts plenty of spans on every page.
    spans = extract_spans(str(DOC_A))
    pages_seen = {s.page for s in spans}
    assert pages_seen == set(range(1, 10)), f"expected pages 1-9, got {pages_seen}"
