"""Diagnostic dump — observe entity detector + binder behavior on Option 1.

NO code changes. Pure observation. Writes /tmp/entity_diag.json + .md so
we can see, per page, per record:

  1. Page text (truncated to first 2000 chars per page)
  2. Entities detected (label, kind, y_top, y_bottom)
  3. Track 1 records extracted (raw_value, bbox, leading-marker entity_tag)
  4. Track 2 LLM records extracted (raw_value, page, name)
  5. After binding: chosen entity_tag per record + reason (enclosure / nearest
     / preserved / no-entity)

Use: uv run python scripts/diagnose_entity_binding.py
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import fitz

from interlock.cache import disk as disk_cache
from interlock.extract.entity_bind import _pick_entity
from interlock.extract.parameters import ParameterRecord, extract_parameters
from interlock.ingest.pdf import ingest
from interlock.llm_pipeline.entity_detect import detect_entities_for_doc
from interlock.llm_pipeline.extract import extract_claims_from_doc
from interlock.llm_pipeline.schemas.doc_class import DocClass
from interlock.llm_pipeline.schemas.entity import DetectedEntity

DOC_A = "fixtures/pdfs/doc_a_60pct.pdf"
DOC_B = "fixtures/pdfs/doc_b_90pct.pdf"

OUT_JSON = Path("/tmp/entity_diag.json")
OUT_MD = Path("/tmp/entity_diag.md")


@dataclass
class BindDecision:
    record_name: str
    record_raw: str
    record_page: int
    record_y_center: float
    chosen_tag: str | None
    chosen_reason: str  # enclosure / nearest / preserved / no-entity
    enclosure_count: int  # how many entities enclosed this y_center


def _y_center(rec: ParameterRecord) -> float:
    return (rec.bbox[1] + rec.bbox[3]) / 2.0


def _bind_with_reason(
    rec: ParameterRecord, ents: list[DetectedEntity],
) -> BindDecision:
    """Replicate entity_bind.bind_records_to_entities but record reasoning."""
    yc = _y_center(rec)
    if rec.entity_tag:
        return BindDecision(
            record_name=rec.name, record_raw=rec.raw_value,
            record_page=rec.page, record_y_center=yc,
            chosen_tag=rec.entity_tag, chosen_reason="preserved-by-track1",
            enclosure_count=0,
        )
    if not ents:
        return BindDecision(
            record_name=rec.name, record_raw=rec.raw_value,
            record_page=rec.page, record_y_center=yc,
            chosen_tag=None, chosen_reason="no-entity-on-page",
            enclosure_count=0,
        )
    enclosing = [e for e in ents if e.y_top <= yc <= e.y_bottom]
    if enclosing:
        chosen = min(enclosing, key=lambda e: e.y_bottom - e.y_top)
        return BindDecision(
            record_name=rec.name, record_raw=rec.raw_value,
            record_page=rec.page, record_y_center=yc,
            chosen_tag=chosen.label, chosen_reason="enclosure",
            enclosure_count=len(enclosing),
        )
    chosen = _pick_entity(yc, ents)
    return BindDecision(
        record_name=rec.name, record_raw=rec.raw_value,
        record_page=rec.page, record_y_center=yc,
        chosen_tag=chosen.label if chosen else None,
        chosen_reason="nearest-fallback",
        enclosure_count=0,
    )


def _dump_pdf(label: str, pdf_path: str) -> dict[str, Any]:
    print(f"--- {label}: {pdf_path} ---")
    # Track 1 ingest + extract
    ing = ingest(pdf_path, doc_id=label, table_max_pages=20)
    track1 = extract_parameters(ing.spans)

    # Track 2 LLM extract (cached if previously run)
    try:
        track2 = extract_claims_from_doc(
            pdf_path, doc_class=DocClass.coordination_study,
            doc_id=label,
        )
    except Exception as e:
        print(f"  track2 failed: {e}")
        track2 = []

    # Entity detection (cached)
    try:
        ents_by_page = detect_entities_for_doc(pdf_path)
    except Exception as e:
        print(f"  entity detect failed: {e}")
        ents_by_page = {}

    # Page texts (first 2k chars per page) for visual reference
    page_texts: dict[int, str] = {}
    try:
        doc = fitz.open(pdf_path)
        for p in range(doc.page_count):
            page_texts[p + 1] = (doc[p].get_text("text") or "")[:2000]
        doc.close()
    except Exception:
        pass

    # Bind every record (Track 1 + Track 2), record decisions
    all_records: list[ParameterRecord] = list(track1) + list(track2)
    decisions: list[BindDecision] = []
    for rec in all_records:
        ents = ents_by_page.get(rec.page, [])
        decisions.append(_bind_with_reason(rec, ents))

    # Per-page counts + per-page entities
    per_page: dict[int, dict[str, Any]] = {}
    pages = sorted(set(p for p in ents_by_page) | set(d.record_page for d in decisions))
    for p in pages:
        page_ents = ents_by_page.get(p, [])
        page_decisions = [d for d in decisions if d.record_page == p]
        per_page[p] = {
            "page_text_preview": page_texts.get(p, ""),
            "entities": [
                {
                    "label": e.label, "kind": e.kind,
                    "y_top": e.y_top, "y_bottom": e.y_bottom,
                }
                for e in page_ents
            ],
            "decisions": [
                {
                    "record_name": d.record_name,
                    "record_raw": d.record_raw,
                    "y_center": d.record_y_center,
                    "chosen_tag": d.chosen_tag,
                    "chosen_reason": d.chosen_reason,
                    "enclosure_count": d.enclosure_count,
                }
                for d in page_decisions
            ],
        }

    return {
        "doc": label,
        "path": pdf_path,
        "track1_count": len(track1),
        "track2_count": len(track2),
        "entity_count": sum(len(v) for v in ents_by_page.values()),
        "per_page": per_page,
    }


def main() -> int:
    # Don't wipe caches — we want to observe the actual production behavior.
    print("Caches preserved. Observing production behavior.")
    print(f"disk_cache namespaces: llm-extract, llm-entities, llm-significance ...")
    a_dump = _dump_pdf("doc_a", DOC_A)
    b_dump = _dump_pdf("doc_b", DOC_B)

    OUT_JSON.write_text(json.dumps({"a": a_dump, "b": b_dump}, indent=2),
                        encoding="utf-8")

    # Markdown summary for human review
    lines = ["# Entity-binding diagnostic dump", ""]
    for label, dump in [("Doc A", a_dump), ("Doc B", b_dump)]:
        lines.append(f"## {label}: `{dump['path']}`")
        lines.append("")
        lines.append(f"- Track 1 records: {dump['track1_count']}")
        lines.append(f"- Track 2 records: {dump['track2_count']}")
        lines.append(f"- Entities detected (total across pages): {dump['entity_count']}")
        lines.append("")
        for p, page in sorted(dump["per_page"].items()):
            lines.append(f"### {label} page {p}")
            lines.append("")
            lines.append(f"**Entities ({len(page['entities'])}):**")
            for e in page["entities"]:
                lines.append(
                    f"- `{e['label']}` ({e['kind']}) y=[{e['y_top']:.1f}..{e['y_bottom']:.1f}]"
                )
            lines.append("")
            lines.append(f"**Records ({len(page['decisions'])}) with bind decisions:**")
            for d in page["decisions"]:
                bad = ""
                if d["chosen_reason"] == "nearest-fallback":
                    bad = " ⚠️ FALLBACK"
                lines.append(
                    f"- `{d['record_name']}` = `{d['record_raw']}` "
                    f"y={d['y_center']:.1f} → `{d['chosen_tag']}` "
                    f"({d['chosen_reason']}{bad})"
                )
            lines.append("")
    OUT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {OUT_JSON}")
    print(f"wrote {OUT_MD}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
