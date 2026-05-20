"""Voyage embedder for semantic alignment.

No fallback provider in MVP. If Voyage fails, the caller decides whether to
skip semantic alignment (exact alignment still runs) or surface the error.
"""

from __future__ import annotations

import os

import voyageai

MODEL = "voyage-3"


def embed_voyage(texts: list[str]) -> dict[str, list[float]]:
    if not texts:
        return {}
    client = voyageai.Client(api_key=os.environ["VOYAGE_API_KEY"])  # type: ignore[attr-defined]
    res = client.embed(texts, model=MODEL, input_type="document")
    embeddings: list[list[float]] = [list(v) for v in res.embeddings]
    return dict(zip(texts, embeddings, strict=False))
