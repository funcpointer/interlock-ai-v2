"""Smoke tests for the cached LLM client wrapper.

The live-API test is `slow`-marked so the cumulative regression skips it; run
explicitly with ``uv run pytest -m slow tests/llm``. Cache-firing verification
is the load-bearing assertion: cache_read must be > 0 on the second call.
"""

from __future__ import annotations

import os
from typing import Literal

import pytest
from dotenv import load_dotenv
from pydantic import BaseModel

load_dotenv(override=True)  # repo conftest also does this; defensive for direct runs

from interlock.llm.client import CachedBlock, call_structured  # noqa: E402


needs_anthropic = pytest.mark.skipif(
    not os.getenv("ANTHROPIC_API_KEY"), reason="ANTHROPIC_API_KEY not set"
)


def test_cached_block_5m_emits_ephemeral_marker() -> None:
    blk = CachedBlock(text="hello", ttl="5m")
    out = blk.as_content_block()
    assert out["type"] == "text"
    assert out["cache_control"] == {"type": "ephemeral"}
    assert "ttl" not in out["cache_control"]


def test_cached_block_1h_emits_ttl() -> None:
    blk = CachedBlock(text="ontology body", ttl="1h")
    out = blk.as_content_block()
    assert out["cache_control"] == {"type": "ephemeral", "ttl": "1h"}


def test_cached_block_none_omits_cache_control() -> None:
    blk = CachedBlock(text="volatile", ttl=None)
    out = blk.as_content_block()
    assert "cache_control" not in out


class TinyClassification(BaseModel):
    label: Literal["positive", "negative", "neutral"]
    confidence: float


@pytest.mark.slow
@needs_anthropic
def test_call_structured_returns_pydantic_and_records_usage() -> None:
    """Minimal live-API roundtrip: a tiny classification, validating that
    the structured-output path returns a Pydantic instance and the usage
    breakdown is populated.
    """
    result, usage = call_structured(
        response_model=TinyClassification,
        system_blocks=[CachedBlock(text="You classify sentiment in one word.", ttl=None)],
        user_blocks=[CachedBlock(text="The service was excellent.", ttl=None)],
        max_tokens=200,
    )
    assert isinstance(result, TinyClassification)
    assert result.label in {"positive", "negative", "neutral"}
    assert usage["output"] > 0
    # On a tiny prompt below the 4096-token cache minimum for Opus 4.7,
    # cache_creation will be 0. The cache-firing test below uses a larger
    # prefix that actually crosses the minimum.


@pytest.mark.slow
@needs_anthropic
def test_call_structured_cache_fires_on_repeat_with_large_cached_prefix() -> None:
    """Cache invariant test: two back-to-back calls with the same large
    system prefix must show cache_read > 0 on the second call.

    The prefix must exceed Opus 4.7's 4096-token minimum to cache; we pad
    with deterministic text so the bytes are byte-identical across calls.
    """
    big_prefix = "Engineering ontology section " + (" ".join([f"item {i}" for i in range(2000)]))
    system = [
        CachedBlock(text="You extract sentiment in one word.", ttl=None),
        CachedBlock(text=big_prefix, ttl="1h"),  # 1h: stable, cross-call
    ]
    user = [CachedBlock(text="The product is fine.", ttl=None)]

    _, first = call_structured(
        response_model=TinyClassification,
        system_blocks=system,
        user_blocks=user,
        max_tokens=200,
    )
    _, second = call_structured(
        response_model=TinyClassification,
        system_blocks=system,
        user_blocks=user,
        max_tokens=200,
    )
    # First call writes; second call reads. If second.cache_read == 0, a
    # silent invalidator broke the prefix.
    assert second["cache_read"] > 0, (
        f"cache miss on repeat call — silent invalidator? "
        f"first={first}, second={second}"
    )
