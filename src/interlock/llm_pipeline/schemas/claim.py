"""ExtractedClaim + PageExtractionResult — Track 2 LLM extraction shapes.

ExtractedClaim is the LLM's per-page output unit. It carries richer info
(reasoning, confidence) than ParameterRecord. The downcast helper
``_claim_to_parameter_record`` flattens an ExtractedClaim into a
ParameterRecord with ``provenance="llm"`` so it can flow through Track 1's
alignment + detection paths unchanged.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from interlock.extract.parameters import ParameterRecord
from interlock.extract.units import normalize_quantity


class ExtractedClaim(BaseModel):
    """One claim the LLM lifted from a page's text."""

    parameter_name: str = Field(
        description="Canonical parameter name (e.g., '%Z', 'Transformer Rating')",
    )
    raw_value: str = Field(
        description="Value exactly as written, with units (e.g., '5.75 %', '1000 kVA')",
    )
    entity_tag: str = Field(
        default="",
        description="Equipment ID if visible (e.g., 'XFMR-001', '⑥'); empty otherwise",
    )
    span_text: str = Field(
        description="Exact sentence/row containing the claim, ≤ 200 chars",
    )
    page: int = Field(ge=1, description="1-indexed source page")
    confidence: float = Field(
        ge=0.0, le=1.0,
        description="How sure the model is that this is a real engineering parameter",
    )
    reasoning: str = Field(default="", description="Optional short explanation")

    model_config = {"frozen": True}


class PageExtractionResult(BaseModel):
    """Per-page LLM response shape."""

    claims: list[ExtractedClaim] = Field(default_factory=list)
    page: int = Field(ge=1)
    notes: str = Field(default="")

    model_config = {"frozen": True}


def _claim_to_parameter_record(
    c: ExtractedClaim,
    doc_id: str,
    source_path: str,
) -> ParameterRecord:
    """Downcast an LLM ExtractedClaim into a ParameterRecord.

    - ``provenance="llm"`` (the discriminator)
    - ``bbox=(0,0,0,0)`` — text-only LLM has no per-claim coords; Phase 19's
      ``_is_ocr_span`` heuristic treats whole-page-bbox-at-origin records as
      OCR-style, matching how the UI already renders them.
    - ``entity_tag`` carries through (Phase 19 alignment uses it).
    - Pint normalisation applied on raw_value; soft-fail to ``None`` on
      non-numeric values (part numbers, qualified text).
    """
    raw = c.raw_value.strip()
    mag: float | None = None
    unit: str | None = None
    try:
        q = normalize_quantity(raw)
        mag = float(q.magnitude)
        unit = str(q.units)
    except Exception:
        # Non-numeric / unparseable — leave normalised fields as None.
        pass
    return ParameterRecord(
        doc_id=doc_id,
        page=c.page,
        bbox=(0.0, 0.0, 0.0, 0.0),
        section=None,
        span_text=c.span_text,
        name=c.parameter_name,
        raw_value=raw,
        normalized_magnitude=mag,
        normalized_unit=unit,
        source_path=source_path,
        entity_tag=c.entity_tag,
        provenance="llm",
        extraction_lane="llm_text",  # v2 Sprint 8
    )
