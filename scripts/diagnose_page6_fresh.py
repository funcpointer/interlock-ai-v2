"""Diagnostic — bust cache, rerun detector + LLM extraction on page 6 of
both Option 1 PDFs. Goal: see what the LLM ACTUALLY returns for the
prose pages where the user's false-positive flag formed.

Writes /tmp/page6_fresh.json + .md.

Cost: ~$0.02 (one detector call + one extract call per doc per page).
"""

from __future__ import annotations

import json
from pathlib import Path

import fitz
from dotenv import load_dotenv

load_dotenv(override=True)

from interlock.cache import disk as disk_cache
from interlock.llm_pipeline.entity_detect import detect_entities_on_page
from interlock.llm_pipeline.extract import _call_claude_extract, _parse_page_payload
from interlock.llm_pipeline.schemas.doc_class import DocClass

DOC_A = "fixtures/pdfs/doc_a_60pct.pdf"
DOC_B = "fixtures/pdfs/doc_b_90pct.pdf"
OUT_JSON = Path("/tmp/page6_fresh.json")
OUT_MD = Path("/tmp/page6_fresh.md")


def _page_text(pdf_path: str, page: int) -> str:
    doc = fitz.open(pdf_path)
    try:
        return doc[page - 1].get_text("text") or ""
    finally:
        doc.close()


def _fresh_detector(pdf_path: str, page: int) -> list[dict]:
    # Bust cache namespace for entities so this page re-calls.
    disk_cache.clear_namespace("llm-entities")
    ents = detect_entities_on_page(pdf_path, page)
    return [
        {"label": e.label, "kind": e.kind,
         "y_top": e.y_top, "y_bottom": e.y_bottom}
        for e in ents
    ]


def _fresh_extract(pdf_path: str, page: int) -> dict:
    """Direct LLM extract call (uses the existing extract module's prompt
    builder + parser; bypasses diskcache by calling _call_claude_extract
    directly with a fresh prompt)."""
    from interlock.llm_pipeline.extract import _build_extraction_prompt
    page_text = _page_text(pdf_path, page)
    prompt = _build_extraction_prompt(DocClass.coordination_study)
    try:
        resp = _call_claude_extract(page_text, prompt)
    except Exception as e:
        return {"error": str(e), "claims": []}
    text = getattr(resp.content[0], "text", "") if resp.content else ""
    try:
        parsed = _parse_page_payload(text)
        claims = [
            {
                "parameter_name": c.parameter_name,
                "raw_value": c.raw_value,
                "entity_tag": c.entity_tag,
                "confidence": c.confidence,
                "span_text": (c.span_text or "")[:200],
            }
            for c in parsed.claims
        ]
        return {"page": parsed.page, "claims": claims, "notes": parsed.notes,
                "raw_text_first300": text[:300]}
    except Exception as e:
        return {"error": str(e), "raw_text_first300": text[:300]}


def main() -> int:
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    results = {}
    for label, path in [("doc_a", DOC_A), ("doc_b", DOC_B)]:
        results[label] = {"page": 6, "path": path}
        print(f"--- {label} page 6 ---")
        results[label]["page_text_first800"] = _page_text(path, 6)[:800]
        print("  fresh detector...")
        results[label]["entities"] = _fresh_detector(path, 6)
        print(f"    -> {len(results[label]['entities'])} entities")
        print("  fresh extract (no cache)...")
        results[label]["extract"] = _fresh_extract(path, 6)
        ec = results[label]["extract"].get("claims", [])
        print(f"    -> {len(ec)} claims")
    OUT_JSON.write_text(json.dumps(results, indent=2), encoding="utf-8")

    # Markdown
    lines = ["# Page 6 fresh diagnostic", ""]
    for label, dump in results.items():
        lines.append(f"## {label}: `{dump['path']}`")
        lines.append("")
        lines.append("### Page text preview")
        lines.append("```")
        lines.append(dump["page_text_first800"])
        lines.append("```")
        lines.append("")
        lines.append(f"### Entities detected ({len(dump['entities'])})")
        for e in dump["entities"]:
            lines.append(
                f"- `{e['label']}` ({e['kind']}) "
                f"y=[{e['y_top']:.1f}..{e['y_bottom']:.1f}]"
            )
        lines.append("")
        ex = dump["extract"]
        if "error" in ex:
            lines.append(f"### LLM extract: ERROR `{ex['error']}`")
            lines.append(f"raw response start: `{ex.get('raw_text_first300', '')!r}`")
        else:
            lines.append(f"### LLM extract ({len(ex['claims'])} claims)")
            for c in ex["claims"]:
                lines.append(
                    f"- `{c['parameter_name']}` = `{c['raw_value']}` "
                    f"entity_tag=`{c['entity_tag']}` conf={c['confidence']:.2f} "
                    f"span=`{c['span_text']}`"
                )
        lines.append("")
    OUT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {OUT_JSON}")
    print(f"wrote {OUT_MD}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
