"""Diagnostic — characterize page structures across both Option 1 PDFs.

For each page: dump text density, image area ratio, line/whitespace stats,
detector entities, LLM extract claim count. Goal: see WHY entity detector
returns 0 on some pages + the structural correlation.

Writes /tmp/page_structures.json + .md.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import fitz
from dotenv import load_dotenv

load_dotenv(override=True)

from interlock.cache import disk as disk_cache
from interlock.llm_pipeline.entity_detect import detect_entities_on_page

DOCS = [
    ("doc_a", "fixtures/pdfs/doc_a_60pct.pdf"),
    ("doc_b", "fixtures/pdfs/doc_b_90pct.pdf"),
]
OUT_JSON = Path("/tmp/page_structures.json")
OUT_MD = Path("/tmp/page_structures.md")


def _classify_page_layout(page: "fitz.Page") -> dict:
    """Heuristic structure classification: prose vs table vs diagram."""
    text = page.get_text("text") or ""
    n_chars = len(text)
    lines = [l for l in text.splitlines() if l.strip()]
    n_lines = len(lines)
    avg_line_len = (sum(len(l) for l in lines) / n_lines) if n_lines else 0.0
    # Lines that are "short" (< 20 chars) → typical of diagram callouts
    n_short_lines = sum(1 for l in lines if len(l.strip()) < 20)
    short_ratio = (n_short_lines / n_lines) if n_lines else 0.0

    # Image area: sum of image blocks vs page area
    page_area = page.rect.width * page.rect.height
    image_area = 0.0
    blocks = page.get_text("dict").get("blocks", [])
    for b in blocks:
        if b.get("type") == 1:  # image block
            r = fitz.Rect(b.get("bbox", (0, 0, 0, 0)))
            image_area += r.width * r.height
    image_ratio = image_area / page_area if page_area else 0.0

    # Heuristic label
    if n_chars < 200:
        label = "sparse / image"
    elif short_ratio > 0.6 and avg_line_len < 25:
        label = "diagram-callouts"
    elif short_ratio < 0.3 and avg_line_len > 40:
        label = "prose"
    elif image_ratio > 0.3:
        label = "mixed-image-text"
    else:
        label = "table-or-mixed"

    return {
        "label": label,
        "n_chars": n_chars,
        "n_lines": n_lines,
        "avg_line_len": round(avg_line_len, 1),
        "short_line_ratio": round(short_ratio, 2),
        "image_area_ratio": round(image_ratio, 2),
    }


def main() -> int:
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    has_anthropic = bool(os.getenv("ANTHROPIC_API_KEY"))
    print(f"ANTHROPIC_API_KEY present: {has_anthropic}")

    results = {}
    for label, path in DOCS:
        print(f"--- {label}: {path} ---")
        doc = fitz.open(path)
        try:
            n_pages = doc.page_count
            per_page = {}
            for p in range(1, n_pages + 1):
                structure = _classify_page_layout(doc[p - 1])
                # Bust entity cache for this page, get fresh detector output
                disk_cache.clear_namespace("llm-entities")
                ents = detect_entities_on_page(path, p)
                per_page[p] = {
                    "structure": structure,
                    "entities_n": len(ents),
                    "entity_labels": [e.label for e in ents[:5]],
                }
                print(
                    f"  p{p}: {structure['label']:20s} chars={structure['n_chars']:5d} "
                    f"short_ratio={structure['short_line_ratio']:.2f} "
                    f"img_ratio={structure['image_area_ratio']:.2f} "
                    f"→ ents={len(ents)}"
                )
            results[label] = {"path": path, "n_pages": n_pages, "per_page": per_page}
        finally:
            doc.close()

    OUT_JSON.write_text(json.dumps(results, indent=2), encoding="utf-8")

    lines = ["# Page-structure diagnostic", ""]
    for label, dump in results.items():
        lines.append(f"## {label}: `{dump['path']}` ({dump['n_pages']} pages)")
        lines.append("")
        lines.append("| Page | Label | Chars | Lines | AvgLen | ShortR | ImgR | Entities |")
        lines.append("|---:|---|---:|---:|---:|---:|---:|---:|")
        for p, info in dump["per_page"].items():
            s = info["structure"]
            lines.append(
                f"| {p} | {s['label']} | {s['n_chars']} | {s['n_lines']} | "
                f"{s['avg_line_len']} | {s['short_line_ratio']} | "
                f"{s['image_area_ratio']} | {info['entities_n']} "
                f"({', '.join(info['entity_labels']) if info['entity_labels'] else '—'}) |"
            )
        lines.append("")
    OUT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {OUT_JSON}")
    print(f"wrote {OUT_MD}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
