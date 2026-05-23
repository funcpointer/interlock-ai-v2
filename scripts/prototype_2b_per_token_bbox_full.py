"""Prototype 2b — full per-token bbox dump across 3 page types.

Fixes proto 2's truncation bug. Tests on:
  1. doc_a p6 (born-digital diagram — same as proto 2 but with full dump)
  2. doc_a_scanned p1 (actual scanned page — the real OCR test case)
  3. spec_xfmr_001 p1 (born-digital table — control case)

Goal: verify Sonnet 4.5 Vision returns reliable per-token bboxes on the
scanned-no-text-layer case (P1 prerequisite for Sprint 10).

Critical questions:
  - Are LPS-RK-100SP / LPS-RK-400SP token bboxes distinguishable on the
    born-digital diagram?
  - Does Sonnet return tokens at all on a true scanned page?
  - Do scanned-page bbox coords match visual layout (sanity check)?

Cost: ~$0.01 × 3 = ~$0.03.
Output: /tmp/proto2b_per_token_bbox.md
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

CASES = [
    ("doc_a_p6_diagram", "fixtures/pdfs/doc_a_60pct.pdf", 6),
    ("doc_a_scanned_p1", "fixtures/pdfs/doc_a_scanned.pdf", 1),
    ("spec_xfmr_p1_table", "fixtures/pdfs/spec_xfmr_001.pdf", 1),
]

PROMPT = """\
This image is a rendered engineering-document page at 300 dpi.

OCR every text token (word or short label). For each, return its
bounding box in PIXEL coordinates relative to the image (origin top-left,
y increases down).

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
  "refusal_reason": "<one sentence why>"
}

Do NOT invent coordinates if you're guessing.
"""


def _page_png(pdf_path: str, page: int, dpi: int = 300):  # type: ignore[no-untyped-def]
    try:
        doc = fitz.open(pdf_path)
    except Exception as e:
        return None, 0, 0, str(e)
    try:
        if page < 1 or page > doc.page_count:
            return None, 0, 0, f"page out of range (1..{doc.page_count})"
        pix = doc[page - 1].get_pixmap(dpi=dpi)
        return base64.b64encode(pix.tobytes("png")).decode(), pix.width, pix.height, None
    finally:
        doc.close()


def _call(image_b64: str) -> str:
    client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    resp = client.messages.create(
        model=MODEL,
        max_tokens=16384,
        messages=[{
            "role": "user",
            "content": [
                {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": image_b64}},
                {"type": "text", "text": PROMPT},
            ],
        }],  # type: ignore[typeddict-item]
    )
    return resp.content[0].text if resp.content else ""


def _parse(text: str) -> dict | None:
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


KEYWORDS = ["LPS-RK", "KRP-C", "JCN", "XFMR", "TRANSFORMER", "kVA", "%Z", "RATED", "VOLTAGE"]


def main() -> int:
    if not os.getenv("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY required")
        return 1

    out_lines = [
        "# Prototype 2b — Per-token bbox extraction (full dump, diverse cases)",
        "",
    ]

    for case_id, path, page in CASES:
        print(f"--- {case_id}: {path} p{page} ---")
        img, w, h, err = _page_png(path, page)
        out_lines.append(f"## {case_id}: `{path}` p{page}")
        out_lines.append("")
        if img is None:
            out_lines.append(f"**FAILED to render:** {err}")
            continue
        out_lines.append(f"Rendered: {w}×{h} px")
        try:
            raw = _call(img)
        except Exception as e:
            out_lines.append(f"**API call failed:** {e}")
            print(f"  call failed: {e}")
            continue
        parsed = _parse(raw)
        if parsed is None:
            out_lines.append("**PARSE FAILED**")
            out_lines.append("```")
            out_lines.append(raw[:1500])
            out_lines.append("```")
            print("  PARSE FAILED")
            continue
        if "refusal_reason" in parsed:
            out_lines.append(f"**MODEL REFUSED:** {parsed['refusal_reason']}")
            print(f"  REFUSED: {parsed['refusal_reason']}")
            continue
        tokens = parsed.get("tokens", [])
        out_lines.append(f"**Tokens returned: {len(tokens)}**")
        out_lines.append("")

        # Highlight keyword-matching tokens
        key_hits = [
            t for t in tokens
            if any(kw.lower() in t.get("text", "").lower() for kw in KEYWORDS)
        ]
        out_lines.append(f"**Keyword-matching tokens ({len(key_hits)}):**")
        out_lines.append("")
        out_lines.append("| text | x_tl | y_tl | x_br | y_br | conf |")
        out_lines.append("|---|---:|---:|---:|---:|---:|")
        for t in key_hits[:30]:
            out_lines.append(
                f"| `{t.get('text', '?')}` | "
                f"{t.get('x_top_left', 0):.0f} | {t.get('y_top_left', 0):.0f} | "
                f"{t.get('x_bottom_right', 0):.0f} | {t.get('y_bottom_right', 0):.0f} | "
                f"{t.get('confidence', 0):.2f} |"
            )
        out_lines.append("")

        # Distinct y-coord test for fuse labels (on diagram pages)
        lps_rk_tokens = [t for t in tokens if "LPS-RK" in t.get("text", "")]
        if lps_rk_tokens:
            y_coords = sorted(round(t.get("y_top_left", 0)) for t in lps_rk_tokens)
            distinct = len(set(y_coords))
            out_lines.append(f"**LPS-RK token y-coord distinguishability:** {distinct} distinct y values among {len(lps_rk_tokens)} tokens — {sorted(set(y_coords))}")
            out_lines.append("")
        print(f"  parsed OK: {len(tokens)} tokens; {len(key_hits)} keyword hits")
        out_lines.append(f"_(full token list omitted from MD; saved to /tmp/proto2b_tokens_{case_id}.json)_")
        Path(f"/tmp/proto2b_tokens_{case_id}.json").write_text(
            json.dumps(tokens, indent=2), encoding="utf-8",
        )
        out_lines.append("")

    out_lines.append("## Assessment")
    out_lines.append("- [ ] doc_a_p6_diagram: are LPS-RK-100SP / LPS-RK-400SP token y-coords distinguishable?")
    out_lines.append("- [ ] doc_a_scanned_p1: did model return tokens AT ALL? (refused → Sprint 10 OCR lane downgrades)")
    out_lines.append("- [ ] spec_xfmr_p1_table: bbox coords reasonable for tabular layout?")
    out_lines.append("- [ ] Confidence values per-token are not all identical (i.e., real variability)?")

    Path("/tmp/proto2b_per_token_bbox.md").write_text("\n".join(out_lines), encoding="utf-8")
    print("wrote /tmp/proto2b_per_token_bbox.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
