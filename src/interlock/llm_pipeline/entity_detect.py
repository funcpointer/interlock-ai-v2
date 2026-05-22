"""Sprint 4.5 — per-page Sonnet 4.5 entity detector.

Returns the equipment / circuit / section IDs detected on each page
with y-coordinate ranges. Diskcached per (PDF content hash, page,
PROMPT_VERSION, model). Failure modes (API outage, parse error,
validation error, stoplist drop) all collapse to '[]' for the page.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import fitz
from anthropic import Anthropic

from interlock.cache import disk as disk_cache
from interlock.llm_pipeline.schemas.entity import DetectedEntity, PageEntities

MODEL = "claude-sonnet-4-5"
PROMPT_VERSION = "v1"
_MAX_TOKENS = 2048
_DETECT_MAX_WORKERS = 5
_NAMESPACE = "llm-entities"
_PROMPT_PATH = Path(__file__).parent / "prompts" / "entity_detect.md"

# Labels we never accept as entity IDs even if the model returns them.
_STOPLIST: frozenset[str] = frozenset({
    "IEEE", "IEC", "NEMA", "ANSI", "UL", "NFPA",
    "Example", "Figure", "Note", "Table", "See",
})


def detect_entities_on_page(pdf_path: str, page: int) -> list[DetectedEntity]:
    """Return entities on one page. [] on any failure."""
    page_text = _render_page_text(pdf_path, page)
    if not page_text:
        return []
    payload = _cache_payload(pdf_path, page, page_text)

    def _compute() -> list[DetectedEntity]:
        prompt = _build_prompt(page_text, page)
        try:
            resp = _call_claude_entity(prompt)
        except Exception:
            return []
        text = _response_text(resp)
        loaded = _parse_json(text)
        if loaded is None:
            return []
        try:
            wrapped = PageEntities(**loaded)
        except Exception:
            return []
        return _filter_stoplist_and_y(wrapped.entities)

    value, _hit = disk_cache.get_or_compute(_NAMESPACE, payload, _compute)
    return value


def detect_entities_for_doc(
    pdf_path: str, max_workers: int = _DETECT_MAX_WORKERS,
) -> dict[int, list[DetectedEntity]]:
    """Parallel-per-page wrapper. Returns {page_number: [DetectedEntity, ...]}."""
    n = _page_count(pdf_path)
    if n <= 0:
        return {}
    out: dict[int, list[DetectedEntity]] = {p: [] for p in range(1, n + 1)}
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = {
            ex.submit(detect_entities_on_page, pdf_path, p): p
            for p in range(1, n + 1)
        }
        for fut in futures:
            p = futures[fut]
            try:
                out[p] = fut.result()
            except Exception:
                out[p] = []
    return out


def _filter_stoplist_and_y(entities: list[DetectedEntity]) -> list[DetectedEntity]:
    """Drop entities on the stoplist OR with inverted y range."""
    return [
        e for e in entities
        if e.label.strip() not in _STOPLIST
        and e.y_top <= e.y_bottom
    ]


def _render_page_text(pdf_path: str, page: int) -> str:
    """Return native page text via PyMuPDF; empty string on failure.
    ``page`` is 1-indexed."""
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


def _page_count(pdf_path: str) -> int:
    """Return doc page count; 0 on render failure."""
    try:
        doc = fitz.open(pdf_path)
    except Exception:
        return 0
    try:
        return int(doc.page_count)
    finally:
        doc.close()


def _build_prompt(page_text: str, page: int) -> str:
    sys_prompt = _PROMPT_PATH.read_text(encoding="utf-8")
    body = f"\n\n## Page {page} text\n\n{page_text}\n"
    return sys_prompt + body


def _call_claude_entity(prompt: str) -> object:
    """Single text-only Claude call. Returns raw Anthropic response."""
    client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
    return client.messages.create(
        model=MODEL,
        max_tokens=_MAX_TOKENS,
        messages=[{"role": "user", "content": content}],  # type: ignore[typeddict-item]
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
    """Cache key material. Different PDFs / pages / prompts → different key."""
    return {
        "model": MODEL,
        "prompt_version": PROMPT_VERSION,
        "page": page,
        "page_text_hash": _short_hash(page_text),
        "pdf_path": pdf_path,
    }


def _short_hash(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()[:32]
