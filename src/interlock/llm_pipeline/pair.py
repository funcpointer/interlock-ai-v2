"""Sprint 4 — LLM pairing reranker over Track 1 weak pairs.

For each AlignedPair with pairing_confidence < weak_threshold, call
Claude Sonnet 4.5 with both records' context and ask for a
(score, rationale, decline_to_pair) verdict. Strong pairs pass through
untouched.

Failure modes (API outage, parse error, pydantic validation error,
hallucination guard rejection) all collapse to "keep Track 1 verdict":
the original pair is preserved, pairing_confidence unchanged,
reranked=False. Failures are signaled by raising _RerankFailed from the
compute closure, which propagates through disk_cache.get_or_compute so
nothing gets cached.
"""

from __future__ import annotations

import json
import os
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from typing import Any

from anthropic import Anthropic

from interlock.align.exact import AlignedPair
from interlock.cache import disk as disk_cache
from interlock.llm_pipeline.schemas.pair import PairVerdict

MODEL = "claude-sonnet-4-5"
PROMPT_VERSION = "v1"
_MAX_TOKENS = 1024
_RERANK_MAX_WORKERS = 5
_NAMESPACE = "llm-pair"
_PROMPT_PATH = Path(__file__).parent / "prompts" / "pair.md"


class _RerankFailed(Exception):
    """Sentinel: compute closure couldn't produce a valid verdict.

    Propagated through disk_cache.get_or_compute so the failed attempt
    is NOT cached. Caller falls back to the original Track 1 pair.
    """


def rerank_weak_pairs(
    pairs: list[AlignedPair],
    *,
    weak_threshold: float = 0.75,
    max_workers: int = _RERANK_MAX_WORKERS,
) -> list[AlignedPair]:
    """Rerank pairs with pairing_confidence < weak_threshold via Claude.

    Order preserved for survivors. Pairs whose verdict is
    decline_to_pair drop out (callers downstream recompute
    unpaired_a/b from the surviving list).
    """
    if not pairs:
        return []

    weak_indices = [
        i for i, p in enumerate(pairs) if p.pairing_confidence < weak_threshold
    ]
    if not weak_indices:
        return list(pairs)

    verdicts: dict[int, PairVerdict | None] = {}
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = {ex.submit(_rerank_one, pairs[i]): i for i in weak_indices}
        for fut in futures:
            idx = futures[fut]
            try:
                verdicts[idx] = fut.result()
            except Exception:
                verdicts[idx] = None

    out: list[AlignedPair] = []
    for i, p in enumerate(pairs):
        if i not in weak_indices:
            out.append(p)
            continue
        v = verdicts.get(i)
        if v is None:
            out.append(p)
            continue
        if v.decline_to_pair:
            continue
        out.append(
            replace(
                p,
                pairing_confidence=v.score,
                rerank_rationale=v.rationale,
                reranked=True,
            )
        )
    return out


def _rerank_one(pair: AlignedPair) -> PairVerdict | None:
    """Return a validated PairVerdict, or None on any failure.

    Uses disk_cache.get_or_compute; the compute closure raises
    _RerankFailed on any failure so nothing bad gets cached.
    """
    prompt = _build_prompt(pair)
    payload = _cache_payload(pair, prompt)

    def _compute() -> PairVerdict:
        raw_resp = _call_claude_pair(prompt)
        text = _response_text(raw_resp)
        loaded = _parse_json(text)
        if loaded is None:
            raise _RerankFailed("json parse")
        try:
            verdict = PairVerdict(**loaded)
        except Exception as e:
            raise _RerankFailed(f"validation: {e}") from None
        if not _hallucination_guard_ok(verdict, pair):
            raise _RerankFailed("hallucination guard")
        return verdict

    try:
        verdict, _hit = disk_cache.get_or_compute(_NAMESPACE, payload, _compute)
    except _RerankFailed:
        return None
    except Exception:
        return None
    return verdict


def _build_prompt(pair: AlignedPair) -> str:
    """Compose the user-turn prompt: system prompt + both records' context."""
    sys_prompt = _PROMPT_PATH.read_text(encoding="utf-8")
    a, b = pair.a, pair.b
    body = (
        f"## Doc A record\n\n"
        f"- name: {a.name}\n"
        f"- raw_value: {a.raw_value}\n"
        f"- page: {a.page}\n"
        f"- section: {a.section or '—'}\n"
        f"- entity_tag: {a.entity_tag or '—'}\n"
        f"- span_text: {a.span_text!r}\n\n"
        f"## Doc B record\n\n"
        f"- name: {b.name}\n"
        f"- raw_value: {b.raw_value}\n"
        f"- page: {b.page}\n"
        f"- section: {b.section or '—'}\n"
        f"- entity_tag: {b.entity_tag or '—'}\n"
        f"- span_text: {b.span_text!r}\n\n"
        f"## Track 1 verdict\n\n"
        f"- pairing_confidence: {pair.pairing_confidence:.2f}\n"
        f"- name_match_confidence: {pair.name_match_confidence:.2f}\n"
        f"- value_equivalent: {pair.value_equivalent}\n\n"
        f"Return a single JSON object with score, rationale, decline_to_pair.\n"
    )
    return sys_prompt + "\n\n" + body


def _call_claude_pair(prompt: str) -> object:
    """Single text-only Claude call. Returns raw Anthropic response."""
    client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
    return client.messages.create(
        model=MODEL,
        max_tokens=_MAX_TOKENS,
        messages=[{"role": "user", "content": content}],  # type: ignore[typeddict-item]
    )


def _response_text(resp: object) -> str:
    """Extract the text payload from an Anthropic Message response."""
    blocks = getattr(resp, "content", None) or []
    if not blocks:
        return ""
    first = blocks[0]
    return getattr(first, "text", "") or ""


_FENCED_JSON = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)
_BARE_JSON = re.compile(r"(\{.*\})", re.DOTALL)


def _parse_json(raw: str) -> dict[str, Any] | None:
    """Parse Claude's text into a JSON dict. Tolerant of fenced output."""
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


def _hallucination_guard_ok(verdict: PairVerdict, pair: AlignedPair) -> bool:
    """Rationale must mention at least one of the two raw_values
    (case-insensitive substring match). Defends against generic
    confabulation."""
    rat = verdict.rationale.lower()
    a_raw = (pair.a.raw_value or "").strip().lower()
    b_raw = (pair.b.raw_value or "").strip().lower()
    if a_raw and a_raw in rat:
        return True
    if b_raw and b_raw in rat:
        return True
    return False


def _cache_payload(pair: AlignedPair, prompt: str) -> dict[str, Any]:
    """Cache key material: model + prompt-version + both records' identity
    fields + prompt hash. Different inputs → different key."""
    a, b = pair.a, pair.b
    return {
        "model": MODEL,
        "prompt_version": PROMPT_VERSION,
        "a_doc": a.doc_id,
        "a_page": a.page,
        "a_name": a.name,
        "a_raw": a.raw_value,
        "a_span": a.span_text or "",
        "b_doc": b.doc_id,
        "b_page": b.page,
        "b_name": b.name,
        "b_raw": b.raw_value,
        "b_span": b.span_text or "",
        "prompt": prompt,
    }
