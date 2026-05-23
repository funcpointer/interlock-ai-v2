"""Sprint 8 — Sonnet 4.5 Vision per-page extractor.

For diagram pages, render the page as PNG and ask Sonnet 4.5 Vision to
return structured (entity, parameter, value) tuples. Vision-extracted
ParameterRecords carry entity_tag set DIRECTLY from entity_id — no
post-hoc binding step. extraction_lane="vision" so downstream audit
distinguishes from regex / llm_text.

Failure modes (API outage, parse error, validation error, hallucination
guard rejection) all collapse to '[]' for the page; the rest of the
pipeline proceeds with whatever did extract.
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
from interlock.extract.parameters import ParameterRecord
from interlock.llm_pipeline.schemas.vision_claim import VisionClaim, VisionPageResult

MODEL = "claude-sonnet-4-5"
PROMPT_VERSION = "v1"
_MAX_TOKENS = 4096
_NAMESPACE = "llm-vision"
_PROMPT_PATH = Path(__file__).parent / "prompts" / "vision_extract.md"


def vision_extract_page(
    pdf_path: str, page: int, *, doc_id: str = "",
) -> list[ParameterRecord]:
    """Vision-extract claims from one page. [] on any failure."""
    if not Path(pdf_path).exists():
        return []
    page_text = _page_text(pdf_path, page)
    payload = _cache_payload(pdf_path, page, page_text)

    def _compute() -> list[ParameterRecord]:
        img_b64 = _page_png_b64(pdf_path, page)
        if not img_b64:
            return []
        prompt = _build_prompt(page)
        try:
            resp = _call_claude_vision(img_b64, prompt)
        except Exception:
            return []
        text = _response_text(resp)
        loaded = _parse_json(text)
        if loaded is None:
            return []
        try:
            wrapped = VisionPageResult(**loaded)
        except Exception:
            return []
        # Hallucination guard: each claim's entity_id must be a substring
        # of the page text (case-insensitive). Drops invented IDs.
        page_text_lower = page_text.lower()
        kept = [
            c for c in wrapped.claims
            if c.entity_id.lower() in page_text_lower
        ]
        return [
            _claim_to_record(c, doc_id=doc_id, page=page, source_path=pdf_path)
            for c in kept
        ]

    value, _hit = disk_cache.get_or_compute(_NAMESPACE, payload, _compute)
    return value


def _claim_to_record(
    claim: VisionClaim, *, doc_id: str, page: int, source_path: str,
) -> ParameterRecord:
    return ParameterRecord(
        doc_id=doc_id, page=page,
        bbox=(0.0, 0.0, 0.0, 0.0),
        section=None,
        span_text=claim.visual_evidence,
        name=claim.parameter_name,
        raw_value=claim.raw_value,
        normalized_magnitude=None,
        normalized_unit=None,
        source_path=source_path,
        entity_tag=claim.entity_id,
        provenance="llm",
        extraction_lane="vision",
    )


def _page_text(pdf_path: str, page: int) -> str:
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


def _page_png_b64(pdf_path: str, page: int, dpi: int = 300) -> str:
    try:
        doc = fitz.open(pdf_path)
    except Exception:
        return ""
    try:
        if page < 1 or page > doc.page_count:
            return ""
        pix = doc[page - 1].get_pixmap(dpi=dpi)
        return base64.b64encode(pix.tobytes("png")).decode()
    finally:
        doc.close()


def _build_prompt(page: int) -> str:
    sys_prompt = _PROMPT_PATH.read_text(encoding="utf-8")
    return sys_prompt + f"\n\n(You are looking at page {page}.)"


def _call_claude_vision(image_b64: str, prompt: str) -> object:
    client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    return client.messages.create(
        model=MODEL,
        max_tokens=_MAX_TOKENS,
        messages=[{
            "role": "user",
            "content": [
                {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": image_b64}},
                {"type": "text", "text": prompt},
            ],
        }],
    )


def _response_text(resp: object) -> str:
    blocks = getattr(resp, "content", None) or []
    if not blocks:
        return ""
    first = blocks[0]
    return getattr(first, "text", "") or ""


_FENCED_JSON = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)
_BARE_JSON = re.compile(r"(\{.*\})", re.DOTALL)


def _parse_json(raw: str) -> dict[str, Any] | None:
    m = _FENCED_JSON.search(raw)
    payload_str: str | None = None
    if m:
        payload_str = m.group(1)
    else:
        m2 = _BARE_JSON.search(raw)
        if m2:
            payload_str = m2.group(1)
    if payload_str is None:
        return None
    try:
        loaded = json.loads(payload_str)
    except json.JSONDecodeError:
        return None
    if not isinstance(loaded, dict):
        return None
    return loaded


def _cache_payload(pdf_path: str, page: int, page_text: str) -> dict[str, Any]:
    return {
        "model": MODEL,
        "prompt_version": PROMPT_VERSION,
        "page": page,
        "page_text_hash": hashlib.sha256(page_text.encode("utf-8")).hexdigest()[:32],
        "pdf_path": pdf_path,
    }
