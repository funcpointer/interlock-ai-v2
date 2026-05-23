"""Prototype 1 — does Sonnet 4.5 Vision return useful structured
extraction on a real engineering diagram?

Test case: Option 1 doc_a page 6 (the LPS-RK fuse coordination TCC plot
that produced the demo false positive).

Sends the rendered page PNG to Sonnet 4.5 Vision with a structured-output
prompt asking for (entity_kind, entity_id, parameter, value,
visual_evidence) tuples. Inspect the output for:

  1. Did the model recognize equipment IDs (KRP-C-1600SP, LPS-RK-400SP,
     LPS-RK-100SP, JCN80E)?
  2. Did it correctly attribute fuse values to the right equipment?
  3. Are values like '5.75 %Z' bound to the transformer entity?
  4. Did it return visual_evidence that's reviewer-auditable?
  5. JSON parse rate: did the structured output actually parse?

Cost: ~$0.02 per page × 2 pages = ~$0.04.

Output: /tmp/proto1_vision_extraction.md
"""

from __future__ import annotations

import base64
import json
import os
from pathlib import Path

import fitz
from anthropic import Anthropic
from dotenv import load_dotenv

load_dotenv(override=True)


MODEL = "claude-sonnet-4-5"
DOC_A = "fixtures/pdfs/doc_a_60pct.pdf"
DOC_B = "fixtures/pdfs/doc_b_90pct.pdf"
TEST_PAGE = 6

PROMPT = """\
You are looking at a rendered engineering-document page (likely a
protection coordination study with a Time-Current Curve diagram).

Identify every concrete claim you can extract, structured as JSON. Each
claim must tie a parameter value to its source equipment / circuit /
section, with visual evidence the reviewer can audit.

Return STRICTLY this JSON shape (no prose, no markdown fence):

{
  "page_understanding": "<one sentence describing what this page is>",
  "claims": [
    {
      "entity_kind": "equipment" | "circuit" | "section",
      "entity_id": "<exact label, e.g. 'LPS-RK-100SP' or '400A Feeder'>",
      "entity_location_hint": "<short visual location, e.g. 'top-left' or 'mid-right near MTR START'>",
      "parameter_name": "<e.g. 'Fuse Designation' or 'Impedance' or 'Voltage'>",
      "raw_value": "<exact text as shown>",
      "visual_evidence": "<one sentence: how you tied the value to this entity from visual cues>"
    }
  ]
}

Be conservative. If a value's entity attribution is ambiguous, EITHER:
  - omit the claim entirely, OR
  - set entity_id to "" and explain in visual_evidence.

Do not invent values or part numbers not visible on the page.
"""


def _page_png_b64(pdf_path: str, page: int, dpi: int = 300) -> str:
    doc = fitz.open(pdf_path)
    try:
        pix = doc[page - 1].get_pixmap(dpi=dpi)
        return base64.b64encode(pix.tobytes("png")).decode()
    finally:
        doc.close()


def _call(image_b64: str) -> dict:
    client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    resp = client.messages.create(
        model=MODEL,
        max_tokens=4096,
        messages=[{
            "role": "user",
            "content": [
                {
                    "type": "image",
                    "source": {"type": "base64", "media_type": "image/png", "data": image_b64},
                },
                {"type": "text", "text": PROMPT},
            ],
        }],  # type: ignore[typeddict-item]
    )
    text = resp.content[0].text if resp.content else ""
    return {"raw": text, "usage": getattr(resp, "usage", None)}


def _parse(text: str) -> dict | None:
    import re
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

    out_lines = ["# Prototype 1 — Vision extraction on Option 1 diagram pages", ""]
    parse_ok = 0
    total = 0

    for label, path in [("doc_a", DOC_A), ("doc_b", DOC_B)]:
        total += 1
        print(f"--- {label} page {TEST_PAGE} ---")
        img = _page_png_b64(path, TEST_PAGE)
        result = _call(img)
        raw = result["raw"]
        parsed = _parse(raw)
        out_lines.append(f"## {label}: `{path}` page {TEST_PAGE}")
        out_lines.append("")
        if parsed is None:
            out_lines.append("**PARSE FAILED**")
            out_lines.append("```")
            out_lines.append(raw[:2000])
            out_lines.append("```")
            print("  PARSE FAILED")
            out_lines.append("")
            continue
        parse_ok += 1
        out_lines.append(f"**Page understanding:** {parsed.get('page_understanding', '—')}")
        out_lines.append("")
        claims = parsed.get("claims", [])
        out_lines.append(f"**Claims returned ({len(claims)}):**")
        out_lines.append("")
        for c in claims:
            out_lines.append(
                f"- `{c.get('parameter_name', '?')}` = `{c.get('raw_value', '?')}` "
                f"bound to `{c.get('entity_kind', '?')}:{c.get('entity_id', '')}` "
                f"({c.get('entity_location_hint', '')})\n"
                f"  evidence: _{c.get('visual_evidence', '—')}_"
            )
        print(f"  parsed OK: {len(claims)} claims")
        out_lines.append("")

    out_lines.append("---")
    out_lines.append(f"**Parse rate:** {parse_ok}/{total}")
    out_lines.append("")
    out_lines.append("## Assessment")
    out_lines.append("- [ ] Did model recognize KRP-C-1600SP, LPS-RK-400SP, LPS-RK-100SP, JCN80E?")
    out_lines.append("- [ ] Were fuse values correctly bound to fuse entities (not co-mingled)?")
    out_lines.append("- [ ] Was 5.75 %Z bound to the transformer (not a fuse)?")
    out_lines.append("- [ ] Was 400A Feeder treated as a circuit (kind=circuit)?")
    out_lines.append("- [ ] Visual_evidence text is reviewer-auditable (specific, not generic)?")
    out_lines.append("")

    Path("/tmp/proto1_vision_extraction.md").write_text("\n".join(out_lines), encoding="utf-8")
    print("wrote /tmp/proto1_vision_extraction.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
