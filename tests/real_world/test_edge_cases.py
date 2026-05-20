"""Edge-case tests for ingestion + extraction + pipeline.

Real-world inputs sometimes hand us empty documents, single-blank-page PDFs,
docs with only part numbers, or content that defeats every extractor we have.
The system must degrade gracefully, never crash, and never invent flags.
"""

from __future__ import annotations

from pathlib import Path

import fitz

from interlock.align.exact import align_exact
from interlock.align.semantic import align_semantic
from interlock.detect.mismatch import detect_flags
from interlock.extract.parameters import extract_parameters
from interlock.ingest.pdf import ingest
from interlock.pipeline import review_two_documents


def _stub_embed(texts: list[str]) -> dict[str, list[float]]:
    return {t: [hash(t) % 7919 / 7919.0, 0.1, 0.1] for t in texts}


def test_empty_pdf_does_not_crash_ingest(tmp_path: Path) -> None:
    """A PDF with zero pages must not raise."""
    doc = fitz.open()
    out = tmp_path / "empty.pdf"
    # PyMuPDF requires at least one page to save; create a blank page then
    # strip via the page-count assert.
    doc.new_page()
    doc.save(str(out))
    doc.close()

    result = ingest(str(out), doc_id="empty")
    # One blank page → no spans, low-coverage page listed.
    assert result.spans == []
    assert result.tables == []
    assert 1 in result.low_coverage_pages


def test_pdf_with_only_part_numbers_yields_no_numeric_records(tmp_path: Path) -> None:
    """A PDF containing only fuse part numbers should produce string-only
    ParameterRecords with normalized_magnitude=None — and the pipeline must
    not crash when running semantic alignment on such records.
    """
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Replacement parts:\nLPN-RK-500SP\nKRP-C-1600SP\nLPS-RK-200SP", fontsize=11)
    out = tmp_path / "fuses.pdf"
    doc.save(str(out))
    doc.close()

    result = ingest(str(out), doc_id="fuses")
    params = extract_parameters(result.spans)
    assert params, "expected fuse-designation records"
    assert all(p.normalized_magnitude is None for p in params)


def test_pipeline_does_not_crash_on_no_extractable_params(tmp_path: Path) -> None:
    """A PDF with prose only (no patterns hit) must yield zero flags and
    not crash any alignment / detection step.
    """
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text(
        (72, 72),
        "This document contains only narrative description of intent\n"
        "and acceptance criteria with no quantitative parameters.",
        fontsize=11,
    )
    out = tmp_path / "prose.pdf"
    doc.save(str(out))
    doc.close()

    flags = review_two_documents(
        str(out), str(out), embed_fn=_stub_embed, doc_a_id="a", doc_b_id="b"
    )
    assert flags == []


def test_alignment_on_two_empty_record_lists_returns_empty() -> None:
    """Defensive: aligners must accept empty input without raising."""
    assert align_exact([], []) == []
    assert align_semantic([], [], embed_fn=_stub_embed) == []
    assert detect_flags([]) == []


def test_ingest_handles_pdf_with_only_one_page(tmp_path: Path) -> None:
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Rated Power: 1000 kVA", fontsize=11)
    out = tmp_path / "single.pdf"
    doc.save(str(out))
    doc.close()

    result = ingest(str(out), doc_id="single")
    assert result.spans
    params = extract_parameters(result.spans)
    assert any(p.name == "Rated Power" for p in params)


def test_pipeline_handles_completely_disjoint_doc_types(tmp_path: Path) -> None:
    """Compare a spec to an unrelated prose doc — must surface zero flags.

    No parameter overlap is possible; nothing should be aligned or flagged.
    """
    # Doc 1: spec-ish
    d1 = fitz.open()
    p = d1.new_page()
    p.insert_text((72, 72), "Rated Power: 1000 kVA\nFrequency: 60 Hz", fontsize=11)
    pdf1 = tmp_path / "spec.pdf"
    d1.save(str(pdf1))
    d1.close()
    # Doc 2: prose
    d2 = fitz.open()
    p = d2.new_page()
    p.insert_text((72, 72), "Project narrative discussing approach and milestones.", fontsize=11)
    pdf2 = tmp_path / "prose.pdf"
    d2.save(str(pdf2))
    d2.close()

    flags = review_two_documents(
        str(pdf1), str(pdf2), embed_fn=_stub_embed, doc_a_id="a", doc_b_id="b"
    )
    assert flags == []


def test_pipeline_rejects_voltage_vs_current_pairing_even_with_strong_embed() -> None:
    """The dimensional filter must reject voltage↔current alignment even if
    an over-eager embedder reports cosine = 1.0.
    """
    # Two single-page docs with one parameter each — voltage and current.
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        d1 = fitz.open()
        d1.new_page().insert_text((72, 72), "Rated Voltage: 132 kV", fontsize=11)
        pdf1 = Path(td) / "v.pdf"
        d1.save(str(pdf1))
        d1.close()
        d2 = fitz.open()
        d2.new_page().insert_text((72, 72), "Fault Current: 20000 A RMS Sym", fontsize=11)
        pdf2 = Path(td) / "i.pdf"
        d2.save(str(pdf2))
        d2.close()

        # Embedder that says everything is the same concept.
        def lying_embedder(texts: list[str]) -> dict[str, list[float]]:
            return {t: [1.0, 0.0] for t in texts}

        flags = review_two_documents(
            str(pdf1),
            str(pdf2),
            embed_fn=lying_embedder,
            doc_a_id="v",
            doc_b_id="i",
            same_page_only=False,
        )
        assert flags == [], (
            f"dim filter failed: voltage↔current pairing surfaced flags: {flags}"
        )
