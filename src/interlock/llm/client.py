"""Anthropic client wrapper with prompt caching helpers.

Centralizes:
- Model + thinking defaults locked for this project (Opus 4.7, adaptive thinking).
- Two-tier prompt-cache helpers: 1h TTL for slowly-changing engineering ontology
  and canonical glossary; default 5m TTL for per-fixture document text.
- Pydantic-validated structured output via ``client.messages.parse``.

Design notes
------------
The Anthropic Python SDK exposes structured outputs natively (no need for an
external library like Instructor) — see ``messages.parse(output_format=Model)``.
Caching is done by attaching ``cache_control`` blocks to system/text blocks;
the cache reads at ~0.1× input cost and writes at 1.25× (5m) or 2× (1h). Break-
even is 2 requests for 5m and 3 requests for 1h, so the long TTL is only worth
it for content we re-use across many distinct calls (the engineering ontology).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, TypeVar

from anthropic import Anthropic
from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


DEFAULT_MODEL = "claude-opus-4-7"
DEFAULT_MAX_TOKENS = 16_000
DEFAULT_THINKING: dict[str, str] = {"type": "adaptive"}


@dataclass(frozen=True)
class CachedBlock:
    """A text block that should be cached with the given TTL.

    TTL is either ``"5m"`` (default ephemeral; written at 1.25× input cost,
    read at 0.1×) or ``"1h"`` (long; 2× write, 0.1× read). Use ``"1h"`` for
    stable per-project content reused across many calls (engineering
    ontology, glossary). Use ``"5m"`` (or ``None`` → uncached) for per-call
    or per-fixture content.
    """

    text: str
    ttl: str | None = "5m"

    def as_content_block(self) -> dict[str, Any]:
        block: dict[str, Any] = {"type": "text", "text": self.text}
        if self.ttl:
            cache_control: dict[str, str] = {"type": "ephemeral"}
            if self.ttl != "5m":
                cache_control["ttl"] = self.ttl
            block["cache_control"] = cache_control
        return block


def _client() -> Anthropic:
    """Build an Anthropic client. API key resolved from env at call time so
    .env loaded later is still picked up."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError(
            "ANTHROPIC_API_KEY not set. Populate .env from .env.example or "
            "set it in the deployment environment."
        )
    return Anthropic(api_key=api_key)


def call_structured(
    *,
    response_model: type[T],
    system_blocks: list[CachedBlock],
    user_blocks: list[CachedBlock],
    model: str = DEFAULT_MODEL,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    thinking: dict[str, str] | None = None,
) -> tuple[T, dict[str, int]]:
    """Single-shot structured-output call.

    Returns ``(parsed_pydantic_object, usage_dict)`` where ``usage_dict``
    breaks tokens into ``input``, ``cache_creation``, ``cache_read``, and
    ``output``. Use the breakdown to verify cache is firing on repeat calls
    (cache_read should be > 0 on the second call with the same prefix).
    """
    client = _client()
    sys_content = [b.as_content_block() for b in system_blocks]
    user_content = [b.as_content_block() for b in user_blocks]

    # SDK uses TypedDicts for these params; our blocks are dynamically built
    # so we pass dicts and tell mypy we know what we're doing.
    message = client.messages.parse(
        model=model,
        max_tokens=max_tokens,
        thinking=thinking if thinking is not None else DEFAULT_THINKING,  # type: ignore[arg-type]
        system=sys_content,  # type: ignore[arg-type]
        messages=[{"role": "user", "content": user_content}],  # type: ignore[typeddict-item]
        output_format=response_model,
    )

    usage = message.usage
    breakdown = {
        "input": int(usage.input_tokens),
        "cache_creation": int(getattr(usage, "cache_creation_input_tokens", 0) or 0),
        "cache_read": int(getattr(usage, "cache_read_input_tokens", 0) or 0),
        "output": int(usage.output_tokens),
    }
    # `parsed_output` is the canonical accessor on Anthropic SDK ≥ 0.40 for
    # ``messages.parse``; some older versions exposed ``parsed`` on a different
    # path. Be tolerant during the dependency transition.
    parsed = getattr(message, "parsed_output", None) or getattr(message, "parsed", None)
    if parsed is None:
        raise RuntimeError(
            f"messages.parse returned no parsed object; stop_reason={message.stop_reason}"
        )
    return parsed, breakdown
