"""Document classifier — multi-page VLM call via claude-opus-4-7.

Renders pages 1 / 2 / last at 300 DPI, base64-encodes them into a
single Claude message, parses the JSON response into a
DocClassification, applies the confidence < 0.6 → unknown fallback,
and diskcaches by PDF content hash + model + prompt_version.

Pages are sampled deterministically based on doc length:
  1 page         → [1]
  2 pages        → [1, 2]
  N ≥ 3 pages    → [1, 2, N]

Render failures (corrupt PDF, fitz raises) return
DocClassification(doc_class=unknown, confidence=0.0, ...) so the
pipeline keeps running instead of aborting.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any

import fitz
from anthropic import Anthropic

from interlock.cache import disk as disk_cache
from interlock.llm_pipeline.schemas.doc_class import DocClass, DocClassification

MODEL = "claude-opus-4-7"
PROMPT_VERSION = "v1"
_DPI = 300
_UNKNOWN_CONFIDENCE_THRESHOLD = 0.6
_PROMPT_PATH = Path(__file__).parent / "prompts" / "classify.md"
PROMPT = _PROMPT_PATH.read_text(encoding="utf-8")


def _sample_pages(page_count: int) -> list[int]:
    """Return 1-indexed page numbers to render for classification.

    1-page docs → [1]. 2-page → [1, 2]. ≥ 3 pages → [1, 2, last]. Empty
    PDFs return []; callers must treat that as an unknown classification.
    """
    if page_count <= 0:
        return []
    if page_count == 1:
        return [1]
    if page_count == 2:
        return [1, 2]
    return [1, 2, page_count]


def _render_page_b64(pdf_path: str, page: int, dpi: int = _DPI) -> str:
    doc = fitz.open(pdf_path)
    try:
        pix = doc[page - 1].get_pixmap(dpi=dpi)
        return base64.b64encode(pix.tobytes("png")).decode()
    finally:
        doc.close()


def _call_claude_classify(image_b64_list: list[str]) -> object:
    """Multi-image VLM call. Each image becomes one content block; the
    prompt is the final content block. Returns the raw Anthropic
    response object."""
    client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    content: list[dict[str, Any]] = [
        {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": "image/png",
                "data": img_b64,
            },
        }
        for img_b64 in image_b64_list
    ]
    content.append({"type": "text", "text": PROMPT})
    return client.messages.create(
        model=MODEL,
        max_tokens=1024,
        messages=[{"role": "user", "content": content}],  # type: ignore[typeddict-item]
    )


_FENCED_JSON = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)
_BARE_JSON = re.compile(r"(\{.*\})", re.DOTALL)


def _parse_payload(raw: str) -> dict[str, object]:
    m = _FENCED_JSON.search(raw)
    if m:
        return json.loads(m.group(1))  # type: ignore[no-any-return]
    m = _BARE_JSON.search(raw)
    if m:
        return json.loads(m.group(1))  # type: ignore[no-any-return]
    return json.loads(raw)  # type: ignore[no-any-return]


def _pdf_content_sha(pdf_path: str) -> str:
    with open(pdf_path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def _apply_unknown_fallback(c: DocClassification) -> DocClassification:
    """Confidence below threshold collapses to DocClass.unknown while
    preserving the model's reasoning + raw confidence for the audit trail."""
    if c.confidence < _UNKNOWN_CONFIDENCE_THRESHOLD and c.doc_class != DocClass.unknown:
        return DocClassification(
            doc_class=DocClass.unknown,
            confidence=c.confidence,
            reasoning=(
                f"[confidence {c.confidence:.2f} below {_UNKNOWN_CONFIDENCE_THRESHOLD} "
                f"threshold; original class was {c.doc_class.value}] "
                f"{c.reasoning}"
            ),
            detected_indicators=c.detected_indicators,
            pages_consulted=c.pages_consulted,
        )
    return c


def classify_doc(pdf_path: str) -> DocClassification:
    """Classify a PDF into one of 8 DocClass values.

    Renders pages 1/2/last at 300 DPI, sends a single multi-image
    message to claude-opus-4-7, parses JSON, applies the confidence
    fallback, returns. Diskcached by (pdf content hash, model,
    prompt_version, DPI). Render failures return
    DocClassification(unknown, 0.0, render-failure rationale).
    """
    try:
        pdf_sha = _pdf_content_sha(pdf_path)
    except OSError as e:
        return DocClassification(
            doc_class=DocClass.unknown,
            confidence=0.0,
            reasoning=f"failed to open PDF: {type(e).__name__}: {e}",
        )

    cache_key = {
        "pdf_sha": pdf_sha,
        "model": MODEL,
        "prompt_version": PROMPT_VERSION,
        "dpi": _DPI,
    }

    def _compute() -> dict[str, object]:
        try:
            doc = fitz.open(pdf_path)
            try:
                page_count = doc.page_count
            finally:
                doc.close()
        except Exception as e:  # pragma: no cover — defensive
            return {
                "doc_class": "unknown",
                "confidence": 0.0,
                "reasoning": f"render failure: {type(e).__name__}: {e}",
                "detected_indicators": [],
                "pages_consulted": [],
            }

        pages = _sample_pages(page_count)
        if not pages:
            return {
                "doc_class": "unknown",
                "confidence": 0.0,
                "reasoning": "PDF reports zero pages",
                "detected_indicators": [],
                "pages_consulted": [],
            }

        try:
            images = [_render_page_b64(pdf_path, p, dpi=_DPI) for p in pages]
        except Exception as e:  # pragma: no cover — defensive
            return {
                "doc_class": "unknown",
                "confidence": 0.0,
                "reasoning": f"render failure: {type(e).__name__}: {e}",
                "detected_indicators": [],
                "pages_consulted": [],
            }

        resp = _call_claude_classify(images)
        raw = resp.content[0].text  # type: ignore[attr-defined]
        payload = _parse_payload(raw)
        # Ensure pages_consulted reflects what we *actually* sent, not what
        # the model claims to have looked at.
        payload["pages_consulted"] = pages
        return payload

    cached, _hit = disk_cache.get_or_compute("doc-class", cache_key, _compute)
    raw_classification = DocClassification(**cached)  # type: ignore[arg-type]
    return _apply_unknown_fallback(raw_classification)
