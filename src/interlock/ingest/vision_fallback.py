"""Vision-model fallback via Claude Sonnet 4.6.

Invoked only for low-coverage pages (PyMuPDF + Camelot extracted little text).
Eaton fixture is fully native-text so this path is rarely exercised in the
demo; included for the platform-path scanned-PDF case.
"""

from __future__ import annotations

import base64
import json
import os
import re
from dataclasses import dataclass

import fitz
from anthropic import Anthropic

MODEL = "claude-sonnet-4-5"
PROMPT = (
    "You are extracting engineering parameters from a single PDF page image. "
    "Return STRICT JSON only with this shape: "
    '{"text": <full extracted text as a single string>, '
    '"confidence": <number between 0 and 1>}. '
    "Preserve Greek letters and electrical units (Ω, μF, kV, MVA) and table structure."
)


@dataclass(frozen=True)
class VisionResult:
    text: str
    confidence: float


def _call_claude(image_b64: str) -> object:
    client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    return client.messages.create(
        model=MODEL,
        max_tokens=2048,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/png",
                            "data": image_b64,
                        },
                    },
                    {"type": "text", "text": PROMPT},
                ],
            }
        ],
    )


_FENCED_JSON = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)
_BARE_JSON = re.compile(r"(\{.*\})", re.DOTALL)


def _parse_payload(raw: str) -> dict[str, object]:
    m = _FENCED_JSON.search(raw)
    if m:
        return json.loads(m.group(1))  # type: ignore[no-any-return]
    m = _BARE_JSON.search(raw)
    if m:
        return json.loads(m.group(1))  # type: ignore[no-any-return]
    return json.loads(raw)  # type: ignore[no-any-return]


def vision_extract_page(pdf_path: str, page: int) -> VisionResult:
    doc = fitz.open(pdf_path)
    try:
        pix = doc[page - 1].get_pixmap(dpi=200)
        img_b64 = base64.b64encode(pix.tobytes("png")).decode()
    finally:
        doc.close()
    resp = _call_claude(img_b64)
    raw = resp.content[0].text  # type: ignore[attr-defined]
    payload = _parse_payload(raw)
    return VisionResult(
        text=str(payload["text"]),
        confidence=float(payload["confidence"]),  # type: ignore[arg-type]
    )
