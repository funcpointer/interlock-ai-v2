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
import logging
import os
import re
import time
from pathlib import Path
from typing import Any

import fitz
from anthropic import Anthropic

from interlock.cache import disk as disk_cache
from interlock.extract.parameters import ParameterRecord, canonicalize_param_name
from interlock.llm_pipeline.schemas.vision_claim import VisionClaim, VisionPageResult

logger = logging.getLogger(__name__)

MODEL = "claude-sonnet-4-5"
PROMPT_VERSION = "v1"
_MAX_TOKENS = 4096
_NAMESPACE = "llm-vision"
_PROMPT_PATH = Path(__file__).parent / "prompts" / "vision_extract.md"


def vision_extract_page(
    pdf_path: str, page: int, *, doc_id: str = "",
) -> list[ParameterRecord]:
    """Vision-extract claims from one page. [] on any failure."""
    pdf_label = Path(pdf_path).stem or pdf_path
    tag = f"{pdf_label}/p{page}"
    if not Path(pdf_path).exists():
        logger.warning("vision-lane %s missing pdf — skip", tag)
        return []
    page_text = _page_text(pdf_path, page)
    payload = _cache_payload(pdf_path, page, page_text)

    def _compute() -> list[ParameterRecord]:
        t0 = time.time()
        img_b64 = _page_png_b64(pdf_path, page)
        if not img_b64:
            logger.warning("vision-lane %s render failed — skip", tag)
            return []
        render_ms = (time.time() - t0) * 1000
        prompt = _build_prompt(page)
        t1 = time.time()
        try:
            resp = _call_claude_vision(img_b64, prompt)
        except Exception as exc:
            logger.warning(
                "vision-lane %s API error: %s — returning []", tag, exc,
            )
            return []
        api_ms = (time.time() - t1) * 1000
        text = _response_text(resp)
        loaded = _parse_json(text)
        if loaded is None:
            logger.warning(
                "vision-lane %s parse failed — no JSON in response (len=%d) — returning []",
                tag, len(text),
            )
            return []
        try:
            wrapped = VisionPageResult(**loaded)
        except Exception as exc:
            logger.warning(
                "vision-lane %s schema validation failed: %s — returning []",
                tag, exc,
            )
            return []
        # Hallucination guard: entity_id must be grounded in the page
        # text. Two-tier check:
        #   1. Whitespace-normalized substring match (handles line-broken
        #      compound IDs like "1000KVA 480/277V" where the page text
        #      has "1000KVA\n480/277V").
        #   2. Per-word fallback — every word in entity_id must appear
        #      somewhere in the page text. Catches compound descriptors
        #      whose word order differs from page layout while still
        #      rejecting pure inventions ("HALLUCINATED-XYZ" survives
        #      neither test).
        kept = [
            c for c in wrapped.claims if _entity_grounded(c.entity_id, page_text)
        ]
        dropped = len(wrapped.claims) - len(kept)
        if dropped:
            dropped_ids = [
                c.entity_id for c in wrapped.claims
                if not _entity_grounded(c.entity_id, page_text)
            ]
            logger.warning(
                "vision-lane %s hallucination guard dropped %d/%d claims (ids=%s)",
                tag, dropped, len(wrapped.claims), dropped_ids,
            )
        logger.info(
            "vision-lane %s MISS render=%.0fms api=%.0fms claims=%d (kept %d/%d) layout=%s",
            tag, render_ms, api_ms, len(kept), len(kept), len(wrapped.claims),
            wrapped.page_layout,
        )
        return [
            _claim_to_record(c, doc_id=doc_id, page=page, source_path=pdf_path)
            for c in kept
        ]

    value, hit = disk_cache.get_or_compute(_NAMESPACE, payload, _compute)
    if hit:
        logger.info("vision-lane %s HIT claims=%d", tag, len(value))
    return value


def _claim_to_record(
    claim: VisionClaim, *, doc_id: str, page: int, source_path: str,
) -> ParameterRecord:
    return ParameterRecord(
        doc_id=doc_id, page=page,
        bbox=(0.0, 0.0, 0.0, 0.0),
        section=None,
        span_text=claim.visual_evidence,
        name=canonicalize_param_name(claim.parameter_name),  # v2.8.1
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
_WHITESPACE = re.compile(r"\s+")
_TOKEN = re.compile(r"\w[\w./\\\-]*")


def _entity_grounded(entity_id: str, page_text: str) -> bool:
    """Return True when entity_id is plausibly anchored to page text.

    Step 1 (cheap): whitespace-collapsed substring match. ``1000KVA
    480/277V`` matches a page with ``1000KVA\\n480/277V`` because both
    sides collapse to ``1000kva 480/277v``.

    Step 2 (fallback): every \\w-token in entity_id must appear in the
    page text. Lets the model emit compound descriptors whose token
    order differs from page layout while still rejecting pure
    inventions (``HALLUCINATED-XYZ`` has no token match).
    """
    if not entity_id:
        return False
    eid = entity_id.lower()
    page_lower = page_text.lower()
    eid_collapsed = _WHITESPACE.sub(" ", eid).strip()
    page_collapsed = _WHITESPACE.sub(" ", page_lower)
    if eid_collapsed in page_collapsed:
        return True
    # Per-word fallback — every meaningful token must show up somewhere.
    tokens = [t.group(0) for t in _TOKEN.finditer(eid)]
    if not tokens:
        return False
    return all(t in page_collapsed for t in tokens)


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
    """Cache key for vision lane. Aligned with page-structure cache:
    resolve() + size + mtime catches in-place PDF replace; page_text_hash
    is an additional signal (cheap belt-and-suspenders)."""
    p = Path(pdf_path)
    try:
        resolved = str(p.resolve())
    except Exception:
        resolved = pdf_path
    try:
        stat = p.stat()
        size = stat.st_size
        mtime = int(stat.st_mtime)
    except Exception:
        size = 0
        mtime = 0
    return {
        "model": MODEL,
        "prompt_version": PROMPT_VERSION,
        "page": page,
        "page_text_hash": hashlib.sha256(page_text.encode("utf-8")).hexdigest()[:32],
        "pdf_path": resolved,
        "size": size,
        "mtime": mtime,
    }
