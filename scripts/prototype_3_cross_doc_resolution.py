"""Prototype 3 — does cross-doc entity resolution work on a synthetic
different-conventions pair?

Test case: synthesize two minimal entity lists. Doc A uses generic
'T-1', 'T-2', 'M-3', 'F-12' naming. Doc B uses verbose 'XFMR-001',
'XFMR-002', 'MOTOR-003', 'FUSE-012'. Ask Sonnet 4.5 to map them.

Verify:
  1. Does the model correctly map T-1 → XFMR-001 (and not T-1 → XFMR-002)?
  2. Does it return per-pair confidence + rationale?
  3. Does it handle the absent-on-one-side case (Doc A has 'T-3', Doc B
     doesn't) — leave unmatched?
  4. Does it refuse to invent mappings when entities are obviously
     unrelated (T-1 → MOTOR-003)?

Cost: ~$0.01.

Output: /tmp/proto3_cross_doc_resolution.md
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

from anthropic import Anthropic
from dotenv import load_dotenv

load_dotenv(override=True)


MODEL = "claude-sonnet-4-5"

DOC_A_ENTITIES = [
    {"kind": "equipment", "id": "T-1", "context": "Main transformer per 1-line diagram §2.1; 1500 kVA 13.8/0.48 kV"},
    {"kind": "equipment", "id": "T-2", "context": "Auxiliary transformer per §2.2; 500 kVA 13.8/0.48 kV"},
    {"kind": "equipment", "id": "M-3", "context": "Main feed pump motor per §3.4; 200 HP"},
    {"kind": "equipment", "id": "F-12", "context": "Main feeder fuse downstream of T-1; 1600A class L"},
    {"kind": "equipment", "id": "T-3", "context": "Backup transformer per §2.3; 250 kVA — NOT ON DOC B"},
]

DOC_B_ENTITIES = [
    {"kind": "equipment", "id": "XFMR-001", "context": "Main step-down transformer; 1500 kVA 13.8/0.48 kV (per equipment data sheet)"},
    {"kind": "equipment", "id": "XFMR-002", "context": "Aux transformer; 500 kVA 13.8/0.48 kV"},
    {"kind": "equipment", "id": "MOTOR-003", "context": "Feed pump motor; 200 HP per nameplate"},
    {"kind": "equipment", "id": "FUSE-012", "context": "Main feeder fuse KRP-C-1600SP class L"},
    {"kind": "equipment", "id": "RELAY-045", "context": "Overcurrent relay 50/51 — NOT ON DOC A"},
]

PROMPT = """\
You are resolving entity references across two engineering documents.

Doc A entities (with context):
{doc_a}

Doc B entities (with context):
{doc_b}

For each Doc A entity, decide whether it refers to the same physical
thing as one of the Doc B entities. Use the context to ground decisions.

Return STRICTLY this JSON shape (no prose, no fence):

{{
  "mappings": [
    {{
      "doc_a_id": "<id>",
      "doc_b_id": "<id or empty if unmatched>",
      "confidence": <float 0..1>,
      "rationale": "<one sentence; must cite both ids when mapping; explicit when no match>"
    }}
  ]
}}

Only return mappings the context CLEARLY supports. When in doubt, leave
doc_b_id empty rather than guess. Do not invent ids that aren't in the
provided lists.
"""


def _call(prompt: str) -> str:
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


def _format_entities(entities: list[dict]) -> str:
    lines = []
    for e in entities:
        lines.append(f"  - {e['kind']}/{e['id']}: {e['context']}")
    return "\n".join(lines)


def main() -> int:
    if not os.getenv("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY required")
        return 1

    prompt = PROMPT.format(
        doc_a=_format_entities(DOC_A_ENTITIES),
        doc_b=_format_entities(DOC_B_ENTITIES),
    )
    print("calling resolver...")
    raw = _call(prompt)
    parsed = _parse(raw)

    out_lines = [
        "# Prototype 3 — Cross-doc entity resolution",
        "",
        "## Setup",
        "",
        f"**Doc A entities ({len(DOC_A_ENTITIES)}):**",
    ]
    for e in DOC_A_ENTITIES:
        out_lines.append(f"- `{e['id']}` ({e['kind']}): {e['context']}")
    out_lines.append("")
    out_lines.append(f"**Doc B entities ({len(DOC_B_ENTITIES)}):**")
    for e in DOC_B_ENTITIES:
        out_lines.append(f"- `{e['id']}` ({e['kind']}): {e['context']}")
    out_lines.append("")

    out_lines.append("## Expected mappings")
    out_lines.append("- T-1 → XFMR-001 (both 1500 kVA main transformer)")
    out_lines.append("- T-2 → XFMR-002 (both 500 kVA aux)")
    out_lines.append("- M-3 → MOTOR-003 (both 200 HP pump motor)")
    out_lines.append("- F-12 → FUSE-012 (both main feeder fuse, 1600A class L)")
    out_lines.append("- T-3 → (unmatched; no equivalent in Doc B)")
    out_lines.append("")

    out_lines.append("## Actual model output")
    out_lines.append("")
    if parsed is None:
        out_lines.append("**PARSE FAILED**")
        out_lines.append("```")
        out_lines.append(raw[:2000])
        out_lines.append("```")
    else:
        mappings = parsed.get("mappings", [])
        out_lines.append("| Doc A | Doc B | Confidence | Rationale |")
        out_lines.append("|---|---|---:|---|")
        for m in mappings:
            out_lines.append(
                f"| `{m.get('doc_a_id', '?')}` | "
                f"`{m.get('doc_b_id', '') or '(unmatched)'}` | "
                f"{m.get('confidence', 0):.2f} | "
                f"{m.get('rationale', '—')} |"
            )

    out_lines.append("")
    out_lines.append("## Assessment")
    out_lines.append("- [ ] T-1 mapped to XFMR-001 (not XFMR-002)?")
    out_lines.append("- [ ] T-2 mapped to XFMR-002?")
    out_lines.append("- [ ] M-3 mapped to MOTOR-003?")
    out_lines.append("- [ ] F-12 mapped to FUSE-012?")
    out_lines.append("- [ ] T-3 correctly UNMATCHED?")
    out_lines.append("- [ ] RELAY-045 either listed as unmatched or absent (not invented as a Doc A counterpart)?")
    out_lines.append("- [ ] Each rationale cites BOTH ids (hallucination guard candidate)?")

    Path("/tmp/proto3_cross_doc_resolution.md").write_text("\n".join(out_lines), encoding="utf-8")
    print("wrote /tmp/proto3_cross_doc_resolution.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
