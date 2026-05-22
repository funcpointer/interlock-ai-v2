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
