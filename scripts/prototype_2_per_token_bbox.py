"""Prototype 2 — does Sonnet 4.5 Vision return reliable per-token bboxes
on a scanned-style page?

Test case: render Option 1 doc_a page 6 (the diagram page) at 300 dpi
and ask the model to OCR + return per-token bounding boxes. If it
returns coords, do they match visual positions?

This is the open question from §9 of the design doc. If Sonnet refuses /
hallucinates bboxes, Sprint 10 OCR-modality lane (§4.7) will need to
fall back to whole-page bbox (current Phase 20 behavior).

Cost: ~$0.01.

Output: /tmp/proto2_per_token_bbox.md
"""

from __future__ import annotations

import base64
import json
import os
import re
from pathlib import Path

import fitz
from anthropic import Anthropic
from dotenv import load_dotenv

load_dotenv(override=True)


MODEL = "claude-sonnet-4-5"
DOC_A = "fixtures/pdfs/doc_a_60pct.pdf"
TEST_PAGE = 6

PROMPT = """\
This image is a rendered engineering-document page at 300 dpi.

OCR the text labels (skip the axis tick numbers and the TCC plot curves).
For each text token (word or short label), return its bounding box in
PAGE COORDINATES (origin top-left; y increases down; units are PDF
points after scaling: page width × 72 / dpi).

Return STRICTLY this JSON shape (no prose, no fence):

{
  "page_width_px": <int>,
  "page_height_px": <int>,
  "tokens": [
    {
      "text": "<exact OCR'd text>",
      "x_top_left": <float>,
      "y_top_left": <float>,
      "x_bottom_right": <float>,
      "y_bottom_right": <float>,
      "confidence": <float 0..1>
    }
  ]
}

If you cannot return reliable bounding boxes, return:

{
  "page_width_px": 0,
  "page_height_px": 0,
  "tokens": [],
  "refusal_reason": "<one sentence explaining why bboxes are unavailable>"
}

Do NOT invent coordinates if you're guessing.
"""


def _page_png_b64(pdf_path: str, page: int, dpi: int = 300):  # type: ignore[no-untyped-def]
    doc = fitz.open(pdf_path)
    try:
        pix = doc[page - 1].get_pixmap(dpi=dpi)
        return base64.b64encode(pix.tobytes("png")).decode(), pix.width, pix.height
    finally:
        doc.close()


def _call(image_b64: str) -> dict:
    client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    resp = client.messages.create(
        model=MODEL,
        max_tokens=8192,
        messages=[{
            "role": "user",
            "content": [
                {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": image_b64}},
                {"type": "text", "text": PROMPT},
            ],
        }],  # type: ignore[typeddict-item]
    )
    text = resp.content[0].text if resp.content else ""
    return {"raw": text}


def _parse(text: str) -> dict | None:
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


def main() -> int:
    if not os.getenv("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY required")
        return 1

    img, w, h = _page_png_b64(DOC_A, TEST_PAGE)
    print(f"page rendered: {w}x{h} px")
    result = _call(img)
    parsed = _parse(result["raw"])

    out_lines = [
        "# Prototype 2 — Sonnet 4.5 Vision per-token bbox extraction",
        "",
        f"**Page:** doc_a p{TEST_PAGE} rendered at {w}×{h} px",
        "",
    ]

    if parsed is None:
        out_lines.append("**PARSE FAILED**")
        out_lines.append("```")
        out_lines.append(result["raw"][:2000])
        out_lines.append("```")
    elif "refusal_reason" in parsed:
        out_lines.append(f"**REFUSED:** {parsed['refusal_reason']}")
    else:
        toks = parsed.get("tokens", [])
        out_lines.append(f"**Returned tokens:** {len(toks)}")
        out_lines.append("")
        out_lines.append("Sample tokens (first 20):")
        out_lines.append("")
        out_lines.append("| text | x_tl | y_tl | x_br | y_br | conf |")
        out_lines.append("|---|---:|---:|---:|---:|---:|")
        for t in toks[:20]:
            out_lines.append(
                f"| `{t.get('text', '?')}` | "
                f"{t.get('x_top_left', 0):.0f} | {t.get('y_top_left', 0):.0f} | "
                f"{t.get('x_bottom_right', 0):.0f} | {t.get('y_bottom_right', 0):.0f} | "
                f"{t.get('confidence', 0):.2f} |"
            )
        out_lines.append("")
        out_lines.append("## Assessment")
        out_lines.append("- [ ] Are coordinates in the correct range (0..page_width / 0..page_height)?")
        out_lines.append("- [ ] Are 'LPS-RK-100SP', 'LPS-RK-400SP', 'KRP-C-1600SP' tokens present?")
        out_lines.append("- [ ] Do the LPS-RK token y-coords differ from each other (i.e. distinguishable)?")
        out_lines.append("- [ ] Confidence values look meaningful (not all 1.0)?")

    Path("/tmp/proto2_per_token_bbox.md").write_text("\n".join(out_lines), encoding="utf-8")
    print("wrote /tmp/proto2_per_token_bbox.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
