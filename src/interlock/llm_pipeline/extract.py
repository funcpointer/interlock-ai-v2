"""Track 2 LLM extraction module — per-page Sonnet call with hybrid prompts.

Phase 25.3 ships the prompt-resolver only; phase 25.4 adds the Claude call,
diskcache, hallucination guard, and the public ``extract_claims_from_doc()``
entry point.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

import fitz
from anthropic import Anthropic

from interlock.cache import disk as disk_cache
from interlock.extract.parameters import ParameterRecord
from interlock.llm_pipeline.schemas.claim import (
    ExtractedClaim,
    PageExtractionResult,
    _claim_to_parameter_record,
)
from interlock.llm_pipeline.schemas.doc_class import DocClass

MODEL = "claude-sonnet-4-5"
PROMPT_VERSION = "v1"
_MAX_TOKENS = 2048
_EXTRACT_MAX_WORKERS = 5

_PROMPTS_DIR = Path(__file__).parent / "prompts" / "extract"


def _render_page_text(pdf_path: str, page: int) -> str:
    """Return native page text via PyMuPDF; empty string on any failure.

    ``page`` is 1-indexed (matches PageExtractionResult.page).
    """
    try:
        doc = fitz.open(pdf_path)
    except Exception:
        return ""
    try:
        if page < 1 or page > doc.page_count:
            return ""
        return doc[page - 1].get_text("text") or ""
    finally:
        doc.close()


def _call_claude_extract(page_text: str, prompt: str) -> object:
    """Text-only Claude call. Returns raw Anthropic response."""
    client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    content: list[dict[str, Any]] = [
        {"type": "text", "text": prompt},
        {"type": "text", "text": "## Page text\n\n" + page_text},
    ]
    return client.messages.create(
        model=MODEL,
        max_tokens=_MAX_TOKENS,
        messages=[{"role": "user", "content": content}],  # type: ignore[typeddict-item]
    )


_FENCED_JSON = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)
_BARE_JSON = re.compile(r"(\{.*\})", re.DOTALL)


def _parse_page_payload(raw: str) -> PageExtractionResult:
    """Parse Claude's response text into PageExtractionResult.

    Robust to fenced (```json) and bare-JSON responses.
    """
    m = _FENCED_JSON.search(raw)
    payload_str: str
    if m:
        payload_str = m.group(1)
    else:
        m = _BARE_JSON.search(raw)
        payload_str = m.group(1) if m else raw
    data = json.loads(payload_str)
    return PageExtractionResult(**data)


def _filter_hallucinated_claims(
    claims: list[ExtractedClaim],
    page_text: str,
) -> list[ExtractedClaim]:
    """Drop claims whose span_text is not a verbatim substring of page_text.

    Whitespace-tolerant: collapse runs of whitespace in both before matching,
    so single-space vs double-space differences don't kill real claims.
    """
    normalized_page = re.sub(r"\s+", " ", page_text).strip()
    out: list[ExtractedClaim] = []
    for c in claims:
        normalized_span = re.sub(r"\s+", " ", c.span_text).strip()
        if normalized_span and normalized_span in normalized_page:
            out.append(c)
    return out


# --- Public extractor entry point -----------------------------------------


def _page_count(pdf_path: str) -> int:
    try:
        doc = fitz.open(pdf_path)
    except Exception:
        return 0
    try:
        return int(doc.page_count)
    finally:
        doc.close()


def _extract_one_page(
    pdf_path: str,
    page: int,
    doc_class: DocClass,
) -> list[ExtractedClaim]:
    """Process one page: render text, call Claude, parse, filter hallucinations.

    Diskcached on (page_text_sha, model, prompt_version, doc_class).
    Returns [] on any failure so a single page can't abort the doc.
    """
    page_text = _render_page_text(pdf_path, page)
    if not page_text.strip():
        return []

    cache_key = {
        "page_text_sha": hashlib.sha256(page_text.encode("utf-8")).hexdigest(),
        "model": MODEL,
        "prompt_version": PROMPT_VERSION,
        "doc_class": doc_class.value,
    }

    def _compute() -> dict[str, Any]:
        try:
            prompt = _build_extraction_prompt(doc_class)
            resp = _call_claude_extract(page_text, prompt)
            raw = resp.content[0].text  # type: ignore[attr-defined]
            result = _parse_page_payload(raw)
            return result.model_dump()
        except Exception as e:
            # Return empty result; cache the failure so we don't re-pay.
            return {
                "claims": [],
                "page": page,
                "notes": f"extraction failed: {type(e).__name__}: {e}",
            }

    cached, _hit = disk_cache.get_or_compute("llm-extract", cache_key, _compute)
    try:
        page_result = PageExtractionResult(**cached)
    except Exception:
        return []
    # Override the model's reported page with the actual page so the
    # downcast records match the source page exactly.
    raw_claims = [
        c.model_copy(update={"page": page}) for c in page_result.claims
    ]
    return _filter_hallucinated_claims(raw_claims, page_text)


def extract_claims_from_doc(
    pdf_path: str,
    doc_class: DocClass,
    doc_id: str | None = None,
) -> list[ParameterRecord]:
    """Extract Track 2 LLM claims from every page of a PDF.

    Per-page parallel via ThreadPoolExecutor (max 5 workers, same as
    Sprint 1 OCR). Diskcached per page. Failure of any single page
    contributes 0 claims; rest of the doc proceeds.

    Returns ParameterRecord[] with ``provenance="llm"``. Empty list if
    the PDF can't be opened or every page failed.
    """
    n_pages = _page_count(pdf_path)
    if n_pages == 0:
        return []
    did = doc_id or pdf_path
    out: list[ParameterRecord] = []
    with ThreadPoolExecutor(max_workers=_EXTRACT_MAX_WORKERS) as ex:
        futures = {
            ex.submit(_extract_one_page, pdf_path, p, doc_class): p
            for p in range(1, n_pages + 1)
        }
        for fut in as_completed(futures):
            try:
                page_claims = fut.result()
            except Exception:
                continue
            for c in page_claims:
                out.append(_claim_to_parameter_record(c, did, pdf_path))
    return out


def _build_extraction_prompt(doc_class: DocClass) -> str:
    """Compose base prompt + per-class injection.

    Unknown class OR empty per-class stub falls back to a generic guidance
    placeholder so extraction still runs.
    """
    base = (_PROMPTS_DIR / "_base.md").read_text(encoding="utf-8")
    class_file = _PROMPTS_DIR / f"{doc_class.value}.md"
    has_content = (
        class_file.exists()
        and class_file.is_file()
        and class_file.stat().st_size > 0
    )
    if not has_content:
        return (
            base
            + "\n\n## Class-specific guidance\n\n"
            + "_(none — extract any engineering parameters present in the text)_\n"
        )
    return (
        base
        + "\n\n## Class-specific guidance\n\n"
        + class_file.read_text(encoding="utf-8")
    )
