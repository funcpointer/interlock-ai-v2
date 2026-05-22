"""Live-API smoke test for the doc-class classifier.

Hits Claude Opus on the existing 6 fixtures. Slow-marked + skipped
when ANTHROPIC_API_KEY is missing. Roughly $0.40 per cold run; cached
after first call so subsequent runs cost nothing.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from dotenv import load_dotenv

load_dotenv(override=True)

from interlock.llm_pipeline.classify import classify_doc  # noqa: E402
from interlock.llm_pipeline.schemas.doc_class import DocClass  # noqa: E402

pytestmark = pytest.mark.slow

needs_anthropic = pytest.mark.skipif(
    not os.getenv("ANTHROPIC_API_KEY"),
    reason="ANTHROPIC_API_KEY required for live classifier",
)


@needs_anthropic
@pytest.mark.parametrize(
    ("pdf_path", "expected_class"),
    [
        ("fixtures/pdfs/doc_a_60pct.pdf", DocClass.coordination_study),
        ("fixtures/pdfs/doc_b_90pct.pdf", DocClass.coordination_study),
        ("fixtures/pdfs/spec_xfmr_001.pdf", DocClass.equipment_spec),
        # SEL paper is prose-heavy w/ no concrete relay setting tables ⇒
        # correctly classifies as unknown per the structure-over-intent rule.
        ("fixtures/pdfs/real_sel_xfmr_protection.pdf", DocClass.unknown),
    ],
)
def test_classify_existing_fixtures(pdf_path: str, expected_class: DocClass) -> None:
    """Each known fixture must classify correctly with confidence ≥ 0.6
    (i.e., must NOT collapse to unknown)."""
    assert Path(pdf_path).exists(), f"fixture missing: {pdf_path}"
    result = classify_doc(pdf_path)
    assert result.doc_class == expected_class, (
        f"{pdf_path}: expected {expected_class}, got {result.doc_class} "
        f"(confidence {result.confidence:.2f}; reasoning: {result.reasoning})"
    )
    assert result.confidence >= 0.6, (
        f"{pdf_path}: classifier collapsed to unknown — "
        f"raw confidence {result.confidence:.2f}, reasoning: {result.reasoning}"
    )


@needs_anthropic
def test_classify_ieee_guide_returns_unknown_or_equipment_spec() -> None:
    """The IEEE Guide is a meta-instructional document — should classify
    as 'unknown' (it's a standards guide, not an engineering deliverable)
    OR equipment_spec if the model reads it as spec guidance. Both
    interpretations are defensible; the smoke gate accepts either."""
    result = classify_doc("fixtures/pdfs/real_ieee_xfmr_spec_guide.pdf")
    assert result.doc_class in {DocClass.unknown, DocClass.equipment_spec}


@needs_anthropic
def test_classify_scanned_doc_classifies_correctly() -> None:
    """Scanned variant of doc_a_60pct should still classify as
    coordination_study — vision OCR isn't needed because the classifier
    reads the page image directly."""
    result = classify_doc("fixtures/pdfs/doc_a_scanned.pdf")
    assert result.doc_class == DocClass.coordination_study
    assert result.confidence >= 0.6
