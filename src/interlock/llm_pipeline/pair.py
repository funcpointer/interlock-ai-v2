"""Sprint 4 — LLM pairing reranker over Track 1 weak pairs.

For each AlignedPair with pairing_confidence <= weak_threshold, call
Claude Sonnet 4.5 with both records' context and ask for a
(score, rationale, decline_to_pair) verdict. Strong pairs pass through
untouched. Boundary is INCLUSIVE so Phase 19's multi-instance
equal-count distinct-y pairs (assigned exactly 0.75) get reranked
instead of slipping through unreviewed.

Failure modes (API outage, parse error, pydantic validation error,
hallucination guard rejection) all collapse to "keep Track 1 verdict":
the original pair is preserved, pairing_confidence unchanged,
reranked=False. Failures are signaled by raising _RerankFailed from the
compute closure, which propagates through disk_cache.get_or_compute so
nothing gets cached.
"""

from __future__ import annotations

import json
import logging
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


logger = logging.getLogger(__name__)

_DECIMAL_SHIFT_FACTOR = 3.0  # > 3× magnitude ratio = decimal-shift class
_NUMERIC_TOKEN_RE = re.compile(r"\d[\d,]*\.?\d*")


def _scrape_first_number(s: str) -> float | None:
    """Best-effort first-numeric-token extraction. Used when Pint
    normalization failed (e.g. raw '20,000A RMS Sym' isn't parseable
    as a pure unit but the leading number IS the value)."""
    m = _NUMERIC_TOKEN_RE.search(s or "")
    if not m:
        return None
    try:
        return float(m.group(0).replace(",", ""))
    except ValueError:
        return None


def _is_decimal_shift_magnitude(pair: AlignedPair) -> bool:
    """True when ra and rb magnitudes differ by more than
    ``_DECIMAL_SHIFT_FACTOR`` ×. Considered "obviously a real mutation"
    regardless of entity-tag mismatch — magnitude evidence outweighs
    string-name evidence for this class of error.

    Uses normalized_magnitude when both sides have it, else falls back
    to first-numeric-token scrape (catches '20,000A RMS Sym' shape
    that Pint refuses to parse)."""
    a_mag = pair.a.normalized_magnitude
    b_mag = pair.b.normalized_magnitude
    if a_mag is None:
        a_mag = _scrape_first_number(pair.a.raw_value)
    if b_mag is None:
        b_mag = _scrape_first_number(pair.b.raw_value)
    if a_mag is None or b_mag is None:
        return False
    if a_mag == 0 or b_mag == 0:
        return abs(a_mag - b_mag) > 0
    ratio = max(a_mag, b_mag) / min(a_mag, b_mag)
    return ratio > _DECIMAL_SHIFT_FACTOR


def rerank_weak_pairs(
    pairs: list[AlignedPair],
    *,
    weak_threshold: float = 0.75,
    max_workers: int = _RERANK_MAX_WORKERS,
) -> list[AlignedPair]:
    """Rerank pairs with pairing_confidence <= weak_threshold via Claude.

    Order preserved for survivors. Pairs whose verdict is
    decline_to_pair drop out (callers downstream recompute
    unpaired_a/b from the surviving list).

    Boundary is INCLUSIVE on weak_threshold so Phase 19's multi-instance
    equal-count distinct-y pairs (which carry exactly 0.75) reach the
    reranker. Strict-less-than caused boundary-case false positives.
    """
    if not pairs:
        return []

    weak_indices = [
        i for i, p in enumerate(pairs) if p.pairing_confidence <= weak_threshold
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
    declined = 0
    rescored = 0
    api_failures = 0
    for i, p in enumerate(pairs):
        if i not in weak_indices:
            out.append(p)
            continue
        v = verdicts.get(i)
        if v is None:
            api_failures += 1
            logger.debug(
                "rerank API/parse failure on pair %s/p%d %r ↔ %s/p%d %r — "
                "keeping Track 1 verdict",
                p.a.doc_id, p.a.page, p.a.raw_value,
                p.b.doc_id, p.b.page, p.b.raw_value,
            )
            out.append(p)
            continue
        if v.decline_to_pair:
            # v2.8.7 — override rerank decline when normalized magnitudes
            # differ by > 3× (decimal-shift class). The field-trip TP-2
            # case: 20,000A vs 200,000A with entity_tags 'X1' vs 'Fault X'.
            # Reranker treated the tag-string difference as evidence of
            # different entities and declined; the 10× magnitude shift is
            # textbook decimal-shift mutation that MUST surface. Magnitude
            # evidence outweighs tag-string evidence for this class.
            if _is_decimal_shift_magnitude(p):
                logger.info(
                    "rerank OVERRIDE decline %s p%d %r ↔ p%d %r — "
                    "magnitudes differ > 3× (decimal-shift class), "
                    "ignoring rerank decline rationale: %s",
                    p.a.name, p.a.page, p.a.raw_value,
                    p.b.page, p.b.raw_value, v.rationale[:120],
                )
                rescored += 1
                # Preserve the decline rationale as audit trail but use
                # ra's original pairing_confidence (don't trust rerank's
                # score either, since it intended to drop the pair).
                out.append(
                    replace(
                        p,
                        rerank_rationale=(
                            f"[override: magnitude differs >3×, decline "
                            f"ignored] {v.rationale}"
                        ),
                        reranked=True,
                    )
                )
                continue
            declined += 1
            logger.info(
                "rerank DECLINED %s p%d %r ↔ p%d %r (orig_pconf=%.2f): %s",
                p.a.name, p.a.page, p.a.raw_value,
                p.b.page, p.b.raw_value, p.pairing_confidence,
                v.rationale[:120],
            )
            continue
        rescored += 1
        logger.debug(
            "rerank rescored %s p%d %r ↔ p%d %r: pconf %.2f → %.2f",
            p.a.name, p.a.page, p.a.raw_value,
            p.b.page, p.b.raw_value, p.pairing_confidence, v.score,
        )
        out.append(
            replace(
                p,
                pairing_confidence=v.score,
                rerank_rationale=v.rationale,
                reranked=True,
            )
        )
    logger.info(
        "rerank summary: %d weak pairs → %d kept-rescored, %d declined "
        "(dropped), %d API failures (kept original)",
        len(weak_indices), rescored, declined, api_failures,
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
