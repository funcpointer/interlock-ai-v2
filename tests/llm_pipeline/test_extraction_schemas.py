"""Sprint 2 — ExtractedClaim + PageExtractionResult + downcast tests."""

from __future__ import annotations

import pytest
from pydantic import ValidationError


def test_extracted_claim_minimal_valid() -> None:
    from interlock.llm_pipeline.schemas.claim import ExtractedClaim
    c = ExtractedClaim(
        parameter_name="%Z",
        raw_value="5.75 %",
        span_text="Transformer impedance is 5.75 %Z, liquid-filled.",
        page=3,
        confidence=0.92,
    )
    assert c.parameter_name == "%Z"
    assert c.entity_tag == ""  # default
    assert c.reasoning == ""    # default


def test_extracted_claim_full() -> None:
    from interlock.llm_pipeline.schemas.claim import ExtractedClaim
    c = ExtractedClaim(
        parameter_name="Transformer Rating",
        raw_value="1000 kVA",
        entity_tag="XFMR-001",
        span_text="XFMR-001 is rated 1000 kVA, 13.8 kV primary.",
        page=2,
        confidence=0.96,
        reasoning="Direct nameplate parameter row with rated kVA + voltage",
    )
    assert c.entity_tag == "XFMR-001"
    assert c.reasoning.startswith("Direct")


def test_extracted_claim_confidence_out_of_range_rejected() -> None:
    from interlock.llm_pipeline.schemas.claim import ExtractedClaim
    with pytest.raises(ValidationError):
        ExtractedClaim(
            parameter_name="%Z", raw_value="5.75 %",
            span_text="impossible", page=1, confidence=1.5,
        )


def test_extracted_claim_page_must_be_positive() -> None:
    from interlock.llm_pipeline.schemas.claim import ExtractedClaim
    with pytest.raises(ValidationError):
        ExtractedClaim(
            parameter_name="%Z", raw_value="5.75 %",
            span_text="impossible", page=0, confidence=0.9,
        )


def test_extracted_claim_frozen() -> None:
    """Audit-trail-friendly — claims cannot be mutated after construction."""
    from interlock.llm_pipeline.schemas.claim import ExtractedClaim
    c = ExtractedClaim(
        parameter_name="%Z", raw_value="5.75 %",
        span_text="text", page=1, confidence=0.9,
    )
    with pytest.raises(ValidationError):
        c.confidence = 0.5  # type: ignore[misc]


def test_page_extraction_result_empty_claims_valid() -> None:
    from interlock.llm_pipeline.schemas.claim import PageExtractionResult
    r = PageExtractionResult(page=1)
    assert r.claims == []
    assert r.notes == ""


def test_page_extraction_result_with_claims() -> None:
    from interlock.llm_pipeline.schemas.claim import ExtractedClaim, PageExtractionResult
    r = PageExtractionResult(
        page=2,
        claims=[
            ExtractedClaim(
                parameter_name="%Z", raw_value="5.75 %",
                span_text="...", page=2, confidence=0.9,
            ),
        ],
        notes="impedance found",
    )
    assert len(r.claims) == 1
    assert r.notes == "impedance found"


def test_downcast_claim_to_parameter_record() -> None:
    """Downcast preserves entity_tag, sets provenance='llm', sets bbox to origin."""
    from interlock.llm_pipeline.schemas.claim import (
        ExtractedClaim, _claim_to_parameter_record,
    )
    c = ExtractedClaim(
        parameter_name="%Z",
        raw_value="5.75 %",
        entity_tag="6",
        span_text="⑥ XFMR-001 5.75 %Z",
        page=3,
        confidence=0.95,
    )
    record = _claim_to_parameter_record(c, doc_id="doc_a", source_path="/tmp/x.pdf")
    assert record.provenance == "llm"
    assert record.entity_tag == "6"
    assert record.page == 3
    assert record.bbox == (0.0, 0.0, 0.0, 0.0)
    assert record.span_text.startswith("⑥")
    # v2.8.1: canonicalize_param_name maps "%Z" → "Transformer Impedance"
    assert record.name == "Transformer Impedance"
    assert record.raw_value == "5.75 %"
    assert record.normalized_magnitude is not None  # Pint applied


def test_downcast_handles_unitless_raw_value() -> None:
    """Raw value with no unit ⇒ normalized_magnitude/unit are None, not crash."""
    from interlock.llm_pipeline.schemas.claim import (
        ExtractedClaim, _claim_to_parameter_record,
    )
    c = ExtractedClaim(
        parameter_name="Fuse Designation",
        raw_value="LPN-RK-500SP",
        span_text="Fuse: LPN-RK-500SP",
        page=1,
        confidence=0.9,
    )
    record = _claim_to_parameter_record(c, doc_id="d", source_path="/tmp/x.pdf")
    assert record.provenance == "llm"
    assert record.normalized_magnitude is None
    assert record.normalized_unit is None
    assert record.raw_value == "LPN-RK-500SP"
