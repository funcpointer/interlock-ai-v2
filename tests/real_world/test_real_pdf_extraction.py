"""Smoke tests against the real public engineering PDFs in fixtures/pdfs/.

These tests guard the ingestion + extraction pipeline against real-world
documents — small enough to run quickly, broad enough to catch regressions
when extraction patterns or unit aliases change.

Every test here uses an unmodified real PDF; no mutations involved.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from interlock.extract.parameters import ParameterRecord, extract_parameters
from interlock.ingest.pdf import ingest

EATON = "fixtures/pdfs/doc_a_60pct.pdf"
EATON_REV = "fixtures/pdfs/doc_b_90pct.pdf"
SPEC = "fixtures/pdfs/spec_xfmr_001.pdf"
SEL = "fixtures/pdfs/real_sel_xfmr_protection.pdf"
IEEE = "fixtures/pdfs/real_ieee_xfmr_spec_guide.pdf"


def _citation_complete(r: ParameterRecord) -> bool:
    return bool(
        r.doc_id
        and r.page >= 1
        and len(r.bbox) == 4
        and r.bbox[2] > r.bbox[0]
        and r.bbox[3] > r.bbox[1]
        and r.span_text
        and r.name
        and r.raw_value
    )


@pytest.mark.parametrize(
    "pdf,doc_id",
    [
        (EATON, "eaton_60"),
        (EATON_REV, "eaton_90"),
        (SPEC, "spec"),
        (SEL, "sel"),
        (IEEE, "ieee"),
    ],
)
def test_ingest_does_not_crash_on_real_pdf(pdf: str, doc_id: str) -> None:
    assert Path(pdf).exists(), f"fixture missing: {pdf}"
    result = ingest(pdf, doc_id=doc_id)
    assert result.doc_id == doc_id
    assert isinstance(result.spans, list)
    assert isinstance(result.tables, list)
    assert isinstance(result.low_coverage_pages, list)
    # Every real fixture should produce at least some spans.
    assert result.spans, f"no spans extracted from {pdf}"


def test_eaton_baseline_extracts_expected_param_families() -> None:
    result = ingest(EATON, doc_id="eaton_60")
    params = extract_parameters(result.spans)
    names = {p.name for p in params}
    # Eaton coordination study should expose these families.
    assert {"%Z", "Transformer Rating", "Fault Current", "Fuse Designation"} <= names
    assert len(params) >= 40, f"expected ≥40 params from Eaton, got {len(params)}"


def test_spec_extracts_generic_kv_params() -> None:
    result = ingest(SPEC, doc_id="spec")
    params = extract_parameters(result.spans)
    names = {p.name for p in params}
    expected = {"Rated Power", "Primary Voltage", "Secondary Voltage", "Rated Impedance"}
    assert expected <= names, f"missing: {expected - names}"


def test_sel_paper_known_prose_extraction_limit() -> None:
    """SEL transformer protection paper is prose-heavy technical writing.

    Parameter mentions are embedded in sentences (e.g. "the operating signals
    IOP1, IOP2, and IOP3", "the percentage 2 harmonic setting PCT2") not in
    tabular ``Label: value`` layout. Current regex extractors do not catch
    them. Documented as a system limitation; NLP-based extraction lives on
    the platform path (`docs/BACKLOG.md`).

    If this test starts surfacing params, that is good news — update the
    expectation and confirm the patterns are not over-firing.
    """
    result = ingest(SEL, doc_id="sel")
    params = extract_parameters(result.spans)
    assert len(params) == 0, (
        f"SEL surfaced {len(params)} params — patterns expanded? "
        f"Verify no false positives, then update this test."
    )


def test_ieee_guide_known_meta_doc_extraction_limit() -> None:
    """IEEE Guide for Preparation of Transformer Specifications is a meta-doc.

    It teaches how to write a spec, citing example parameter values in prose.
    Our pattern set is tuned for the spec/study layout — generic ``Label:
    value`` lines and the Eaton-specific shape — and intentionally does not
    catch parameters mentioned in instructional prose ("the rated voltage
    shall be ..."). This test pins the current state. Increases here are
    expected as the canonical-glossary and prose-pattern story grows.
    """
    result = ingest(IEEE, doc_id="ieee")
    params = extract_parameters(result.spans)
    # Pin to current behavior: a small handful at most from worked examples.
    assert len(params) <= 5, (
        f"IEEE surfaced {len(params)} params — patterns may be over-firing. "
        f"Spot-check before raising this bound."
    )


@pytest.mark.parametrize("pdf", [EATON, EATON_REV, SPEC, SEL, IEEE])
def test_every_extracted_param_has_complete_citation_tuple(pdf: str) -> None:
    result = ingest(pdf, doc_id="x")
    params = extract_parameters(result.spans)
    incomplete = [p for p in params if not _citation_complete(p)]
    assert not incomplete, f"{len(incomplete)} incomplete citations in {pdf}: {incomplete[:3]}"
