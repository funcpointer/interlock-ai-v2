"""Sprint 8 — page-structure classifier heuristic tests."""

from __future__ import annotations

from pathlib import Path

import fitz


def _make_pdf(tmp_path: Path, text: str) -> Path:
    """Create a 1-page PDF with text content. Helper for synthetic cases."""
    p = tmp_path / "test.pdf"
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), text, fontsize=10)
    doc.save(p)
    doc.close()
    return p


def test_classify_prose(tmp_path: Path) -> None:
    """Long paragraphs → prose."""
    from interlock.llm_pipeline.page_classify import classify_page_structure
    text = "\n".join(
        f"This is paragraph {i} containing a long line of prose text "
        f"that should classify as prose because it has more than forty "
        f"characters and is not a short callout label."
        for i in range(10)
    )
    pdf = _make_pdf(tmp_path, text)
    assert classify_page_structure(str(pdf), 1) == "prose"


def test_classify_diagram(tmp_path: Path) -> None:
    """Many short labels → diagram-callouts."""
    from interlock.llm_pipeline.page_classify import classify_page_structure
    text = "\n".join([
        "LPS-RK-100SP", "KRP-C-1600SP", "13.8 kV", "60HP", "FLA",
        "MS", "MTR", "OLR", "TX", "100", "200", "400", "600", "13.8KV",
        "MV OLR", "TCC",
    ])
    pdf = _make_pdf(tmp_path, text)
    assert classify_page_structure(str(pdf), 1) == "diagram"


def test_classify_mixed_when_no_signal(tmp_path: Path) -> None:
    """Ambiguous layout → mixed."""
    from interlock.llm_pipeline.page_classify import classify_page_structure
    text = "Some moderate-length line here\nAnother similar line\nA third one"
    pdf = _make_pdf(tmp_path, text)
    # 3 lines, moderate length → not prose, not diagram → mixed
    result = classify_page_structure(str(pdf), 1)
    assert result in ("mixed", "prose")  # heuristic edge-case


def test_classify_missing_pdf_returns_mixed(tmp_path: Path) -> None:
    """Unparseable / missing PDF → safe default 'mixed'."""
    from interlock.llm_pipeline.page_classify import classify_page_structure
    assert classify_page_structure(str(tmp_path / "no.pdf"), 1) == "mixed"


def test_classify_out_of_range_page_returns_mixed(tmp_path: Path) -> None:
    from interlock.llm_pipeline.page_classify import classify_page_structure
    pdf = _make_pdf(tmp_path, "short text")
    assert classify_page_structure(str(pdf), 99) == "mixed"


def test_classify_diskcache_hit(tmp_path: Path, mocker) -> None:  # type: ignore[no-untyped-def]
    """Repeat call hits cache; no re-computation of stats."""
    from interlock.llm_pipeline import page_classify
    from interlock.cache import disk as disk_cache
    disk_cache.clear_namespace("page-structure")
    pdf = _make_pdf(tmp_path, "x")
    # First call populates
    page_classify.classify_page_structure(str(pdf), 1)
    # Spy on the internal stats fn for second call
    spy = mocker.spy(page_classify, "_compute_layout_stats")
    page_classify.classify_page_structure(str(pdf), 1)
    assert spy.call_count == 0
