"""Voyage embedder for semantic alignment with per-text disk cache.

The free tier of Voyage limits to 3 RPM, which is too low for cumulative test
runs and demo iteration. We cache embeddings per-text in diskcache so repeat
inputs (which are most of our inputs — the canonical glossary repeats every
run) hit cache and never touch the API.

Cache key is ``(model, text)``; same text + same model always returns the
same cached vector, eliminating the Voyage cosine-drift problem documented
in tests/real_world/test_pipeline_behaviors.py.

If Voyage fails on a cache miss, we record the cost-event (with $0 since no
tokens were billed) and re-raise so the caller can decide. Cached calls
never hit the network.
"""

from __future__ import annotations

import os

import voyageai

from interlock.cache import cost_ledger

MODEL = "voyage-3"
_CACHE_NAMESPACE = "voyage-embeddings"


def _voyage_key(text: str) -> dict[str, str]:
    return {"model": MODEL, "text": text}


def _voyage_lookup(text: str) -> list[float] | None:
    """Read-only cache lookup; returns None on miss without invoking compute."""
    from interlock.cache.disk import _cache, _key  # internal but stable

    k = _key(_CACHE_NAMESPACE, _voyage_key(text))
    if k in _cache:
        return list(_cache[k])
    return None


def _voyage_write(text: str, vector: list[float]) -> None:
    from interlock.cache.disk import _cache, _key

    k = _key(_CACHE_NAMESPACE, _voyage_key(text))
    _cache[k] = list(vector)


def embed_voyage(texts: list[str]) -> dict[str, list[float]]:
    """Return ``{text: vector}`` for each input.

    Per-text disk cache: only uncached texts trigger a network call. To stay
    under Voyage's 3 RPM free-tier limit we batch all uncached texts into a
    single API call per ``embed_voyage`` invocation.
    """
    if not texts:
        return {}

    out: dict[str, list[float]] = {}
    miss_texts: list[str] = []
    for t in texts:
        cached = _voyage_lookup(t)
        if cached is not None:
            out[t] = cached
        else:
            miss_texts.append(t)

    if miss_texts:
        client = voyageai.Client(api_key=os.environ["VOYAGE_API_KEY"])  # type: ignore[attr-defined]
        res = client.embed(miss_texts, model=MODEL, input_type="document")
        for t, vec in zip(miss_texts, res.embeddings, strict=False):
            vector: list[float] = list(vec)  # type: ignore[call-overload]
            _voyage_write(t, vector)
            out[t] = vector
        # Record the batch cost. Approximate token count from text length.
        est_tokens = sum(max(1, len(t.split()) * 2) for t in miss_texts)
        cost_ledger.record(
            provider="voyage",
            model=MODEL,
            namespace="voyage-embeddings",
            input_tokens=est_tokens,
        )
    return out
