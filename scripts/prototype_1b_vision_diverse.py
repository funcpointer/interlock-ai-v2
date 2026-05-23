"""Prototype 1b — vision extraction across diverse page types + doc classes.

Tests proto 1's vision-extraction premise on:
  1. doc_a p1 (born-digital, table-or-mixed)        — Option 1 fixture cover
  2. doc_a p9 (born-digital, prose)                  — Option 1 closing prose
  3. spec_xfmr_001.pdf p1 (born-digital, table-form) — real equipment spec
  4. synth_pid.pdf p1 (born-digital, diagram)        — P&ID schematic
  5. synth_bom.pdf p1 (born-digital, table)          — BOM
  6. synth_civil_drawing.pdf p1 (born-digital, drawing) — civil drawing
  7. synth_hvac_schedule.pdf p1 (born-digital, table) — HVAC schedule
  8. real_ieee_xfmr_spec_guide.pdf p2 (born-digital, prose) — IEEE guide

Goal: does proto 1's structured extraction generalize across the document zoo?
Or does it overfit to the Eaton-tutorial diagram structure?

Cost: ~$0.02 × 8 pages = ~$0.16.
Output: /tmp/proto1b_vision_diverse.md
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
    ("opt1_p1_table-mixed", "fixtures/pdfs/doc_a_60pct.pdf", 1),
    ("opt1_p9_prose", "fixtures/pdfs/doc_a_60pct.pdf", 9),
    ("spec_xfmr_p1", "fixtures/pdfs/spec_xfmr_001.pdf", 1),
    ("synth_pid_p1", "fixtures/pdfs/synth_pid.pdf", 1),
    ("synth_bom_p1", "fixtures/pdfs/synth_bom.pdf", 1),
    ("synth_civil_p1", "fixtures/pdfs/synth_civil_drawing.pdf", 1),
    ("synth_hvac_p1", "fixtures/pdfs/synth_hvac_schedule.pdf", 1),
    ("real_ieee_p2", "fixtures/pdfs/real_ieee_xfmr_spec_guide.pdf", 2),
]

PROMPT = """\
You are looking at a rendered engineering-document page. Identify every
concrete claim you can extract — value tied to source entity / circuit /
section — with visual evidence the reviewer can audit.

Return STRICTLY this JSON shape (no prose, no markdown fence):

{
  "page_understanding": "<one sentence: what this page is>",
  "page_layout": "<prose | table | diagram | form | mixed>",
  "claims": [
    {
      "entity_kind": "equipment" | "circuit" | "section" | "row_item",
      "entity_id": "<exact label as shown>",
      "entity_location_hint": "<short visual location>",
      "parameter_name": "<e.g. 'Rated Power' or 'Voltage'>",
      "raw_value": "<exact text>",
      "visual_evidence": "<one sentence tying value to entity from visuals>"
    }
  ]
}

Be conservative. Omit ambiguous claims rather than guessing. Do not invent
values not visible on the page.
"""


def _page_png_b64(pdf_path: str, page: int, dpi: int = 300) -> str | None:
    try:
        doc = fitz.open(pdf_path)
    except Exception as e:
        print(f"  open failed: {e}")
        return None
    try:
        if page < 1 or page > doc.page_count:
            return None
        pix = doc[page - 1].get_pixmap(dpi=dpi)
        return base64.b64encode(pix.tobytes("png")).decode()
    finally:
        doc.close()


def _call(image_b64: str) -> str:
    client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    resp = client.messages.create(
        model=MODEL,
        max_tokens=4096,
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


def main() -> int:
    if not os.getenv("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY required")
        return 1

    out_lines = [
        "# Prototype 1b — Vision extraction across diverse page types",
        "",
        "Validates proto 1's premise on 8 diverse pages from 8 different",
        "PDFs spanning prose, table, diagram, form, schematic, civil drawing.",
        "",
    ]
    parse_ok = 0
    total = 0

    for case_id, path, page in CASES:
        total += 1
        print(f"--- {case_id}: {path} p{page} ---")
        img = _page_png_b64(path, page)
        if img is None:
            out_lines.append(f"## {case_id}: PDF open / page-out-of-range failed for `{path}` p{page}")
            continue
        try:
            raw = _call(img)
        except Exception as e:
            out_lines.append(f"## {case_id}: API call failed — {e}")
            print(f"  call failed: {e}")
            continue
        parsed = _parse(raw)
        out_lines.append(f"## {case_id}: `{path}` p{page}")
        out_lines.append("")
        if parsed is None:
            out_lines.append("**PARSE FAILED**")
            out_lines.append("```")
            out_lines.append(raw[:1500])
            out_lines.append("```")
            print("  PARSE FAILED")
            continue
        parse_ok += 1
        out_lines.append(f"**Page understanding:** {parsed.get('page_understanding', '—')}")
        out_lines.append(f"**Detected layout:** `{parsed.get('page_layout', '?')}`")
        out_lines.append("")
        claims = parsed.get("claims", [])
        out_lines.append(f"**Claims returned: {len(claims)}**")
        for c in claims[:12]:
            out_lines.append(
                f"- `{c.get('parameter_name', '?')}` = `{c.get('raw_value', '?')}` "
                f"bound to `{c.get('entity_kind', '?')}:{c.get('entity_id', '')}` "
                f"({c.get('entity_location_hint', '')})\n"
                f"  evidence: _{c.get('visual_evidence', '—')[:200]}_"
            )
        if len(claims) > 12:
            out_lines.append(f"... and {len(claims) - 12} more")
        out_lines.append("")
        print(f"  parsed OK: {len(claims)} claims; layout={parsed.get('page_layout', '?')}")

    out_lines.append("---")
    out_lines.append(f"**Parse rate:** {parse_ok}/{total}")
    out_lines.append("")
    out_lines.append("## Cross-doc-class assessment")
    out_lines.append("- [ ] Did each doc class produce SOMETHING (non-empty claim list)?")
    out_lines.append("- [ ] Did `page_layout` field match the actual layout?")
    out_lines.append("- [ ] Were values bound to plausible entities (not random labels)?")
    out_lines.append("- [ ] Did diagram pages return `kind=equipment/circuit` (not just `section`)?")
    out_lines.append("- [ ] Did table pages return `kind=row_item` for table rows?")

    Path("/tmp/proto1b_vision_diverse.md").write_text("\n".join(out_lines), encoding="utf-8")
    print(f"wrote /tmp/proto1b_vision_diverse.md (parse rate {parse_ok}/{total})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
