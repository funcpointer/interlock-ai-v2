"""Prototype 3b — cross-doc resolution on REAL doc pairs.

Tests proto 3's premise on entities extracted from actual PDFs, not
synthesized lists. Three real doc-pair scenarios:

  1. spec_xfmr_001 ↔ doc_a_60pct
     (real equipment spec vs Eaton coordination tutorial; same-conv
      partially, with some differing namings)

  2. real_ieee_xfmr_spec_guide ↔ real_sel_xfmr_protection
     (IEEE C57 guide vs SEL relay protection paper; very different docs
      with semantic overlap)

  3. synth_equipment_spec_v2 ↔ synth_relay_setting_sheet
     (synthetic spec vs synthetic relay sheet; tests pure conventions
      gap on docs we control)

Extracts entities from each doc via vision call (proto 1b pattern),
then resolves cross-doc via proto 3 pattern.

Cost: ~$0.06 (4 vision calls + 3 resolution calls).
Output: /tmp/proto3b_cross_doc_real.md
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

DOC_PAIRS = [
    (
        "spec_vs_eaton",
        "fixtures/pdfs/spec_xfmr_001.pdf", 1,
        "fixtures/pdfs/doc_a_60pct.pdf", 7,
    ),
    (
        "ieee_vs_sel",
        "fixtures/pdfs/real_ieee_xfmr_spec_guide.pdf", 2,
        "fixtures/pdfs/real_sel_xfmr_protection.pdf", 2,
    ),
    (
        "synth_spec_vs_relay",
        "fixtures/pdfs/synth_equipment_spec_v2.pdf", 1,
        "fixtures/pdfs/synth_relay_setting_sheet.pdf", 1,
    ),
]

EXTRACT_PROMPT = """\
This is a rendered engineering-document page. List every distinct
physical entity (equipment, circuit, section reference) you can identify
on this page. For each entity, return:

  - `id` — the entity's name/designation as shown
  - `kind` — equipment | circuit | section | other
  - `context` — one sentence describing what the entity is + any
    nearby parameter values that help identify it

Return STRICTLY this JSON shape (no prose, no fence):

{
  "entities": [
    {"id": "<string>", "kind": "<string>", "context": "<sentence>"}
  ]
}

Be conservative. Skip generic labels like "FLA" or axis numbers.
Focus on identifiable physical things.
"""

RESOLVE_PROMPT_TEMPLATE = """\
You are resolving entity references across two engineering documents.

Doc A entities (with context):
{doc_a}

Doc B entities (with context):
{doc_b}

For each Doc A entity, decide if it refers to the same physical thing as
one of the Doc B entities. Use context to ground decisions.

Return STRICTLY this JSON shape (no prose, no fence):

{{
  "mappings": [
    {{
      "doc_a_id": "<id>",
      "doc_b_id": "<id or empty if unmatched>",
      "confidence": <float 0..1>,
      "rationale": "<sentence; cite both ids when mapping; explicit when no match>"
    }}
  ]
}}

Only return mappings the context CLEARLY supports. When in doubt, leave
doc_b_id empty rather than guess.
"""


def _png(pdf_path: str, page: int) -> str | None:
    try:
        doc = fitz.open(pdf_path)
    except Exception:
        return None
    try:
        if page < 1 or page > doc.page_count:
            return None
        pix = doc[page - 1].get_pixmap(dpi=300)
        return base64.b64encode(pix.tobytes("png")).decode()
    finally:
        doc.close()


def _call_vision(image_b64: str, prompt: str) -> str:
    client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    resp = client.messages.create(
        model=MODEL,
        max_tokens=2048,
        messages=[{
            "role": "user",
            "content": [
                {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": image_b64}},
                {"type": "text", "text": prompt},
            ],
        }],  # type: ignore[typeddict-item]
    )
    return resp.content[0].text if resp.content else ""


def _call_text(prompt: str) -> str:
    client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    resp = client.messages.create(
        model=MODEL,
        max_tokens=2048,
        messages=[{"role": "user", "content": [{"type": "text", "text": prompt}]}],  # type: ignore[typeddict-item]
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


def _extract_entities(pdf_path: str, page: int) -> list[dict]:
    img = _png(pdf_path, page)
    if img is None:
        return []
    raw = _call_vision(img, EXTRACT_PROMPT)
    parsed = _parse(raw)
    if parsed is None:
        return []
    return parsed.get("entities", [])


def _resolve(doc_a: list[dict], doc_b: list[dict]) -> list[dict]:
    fmt = lambda es: "\n".join(f"  - {e.get('kind', '?')}/{e.get('id', '?')}: {e.get('context', '')}" for e in es)
    prompt = RESOLVE_PROMPT_TEMPLATE.format(doc_a=fmt(doc_a), doc_b=fmt(doc_b))
    raw = _call_text(prompt)
    parsed = _parse(raw)
    return parsed.get("mappings", []) if parsed else []


def main() -> int:
    if not os.getenv("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY required")
        return 1

    out_lines = ["# Prototype 3b — Cross-doc resolution on REAL doc pairs", ""]

    for pair_id, doc_a_path, doc_a_page, doc_b_path, doc_b_page in DOC_PAIRS:
        print(f"--- {pair_id} ---")
        print(f"  extracting entities from {doc_a_path} p{doc_a_page}...")
        a_ents = _extract_entities(doc_a_path, doc_a_page)
        print(f"    -> {len(a_ents)} entities")
        print(f"  extracting entities from {doc_b_path} p{doc_b_page}...")
        b_ents = _extract_entities(doc_b_path, doc_b_page)
        print(f"    -> {len(b_ents)} entities")
        print(f"  resolving cross-doc mapping...")
        mappings = _resolve(a_ents, b_ents)
        print(f"    -> {len(mappings)} mappings")

        out_lines.append(f"## {pair_id}")
        out_lines.append("")
        out_lines.append(f"**Doc A:** `{doc_a_path}` p{doc_a_page} → {len(a_ents)} entities")
        for e in a_ents:
            out_lines.append(f"- `{e.get('id', '?')}` ({e.get('kind', '?')}): {e.get('context', '')[:150]}")
        out_lines.append("")
        out_lines.append(f"**Doc B:** `{doc_b_path}` p{doc_b_page} → {len(b_ents)} entities")
        for e in b_ents:
            out_lines.append(f"- `{e.get('id', '?')}` ({e.get('kind', '?')}): {e.get('context', '')[:150]}")
        out_lines.append("")
        out_lines.append(f"**Cross-doc mappings ({len(mappings)}):**")
        out_lines.append("")
        if not mappings:
            out_lines.append("_(no mappings)_")
        else:
            out_lines.append("| Doc A | Doc B | Conf | Rationale |")
            out_lines.append("|---|---|---:|---|")
            for m in mappings:
                out_lines.append(
                    f"| `{m.get('doc_a_id', '?')}` | "
                    f"`{m.get('doc_b_id', '') or '(unmatched)'}` | "
                    f"{m.get('confidence', 0):.2f} | "
                    f"{m.get('rationale', '—')[:200]} |"
                )
        out_lines.append("")

    out_lines.append("## Assessment")
    out_lines.append("- [ ] spec_vs_eaton: did the spec's XFMR-001 map to Eaton's '1000 KVA Xfmr' (or similar)?")
    out_lines.append("- [ ] ieee_vs_sel: are mappings semantically defensible despite very different doc structures?")
    out_lines.append("- [ ] synth_spec_vs_relay: synthetic-pair mappings follow expected naming overlap?")
    out_lines.append("- [ ] Per-pair confidence values reflect actual mapping strength (not all 1.0)?")
    out_lines.append("- [ ] Did model ever invent mappings (cite a doc_a_id NOT in the supplied list)?")

    Path("/tmp/proto3b_cross_doc_real.md").write_text("\n".join(out_lines), encoding="utf-8")
    print("wrote /tmp/proto3b_cross_doc_real.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
