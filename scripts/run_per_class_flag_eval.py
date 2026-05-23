"""Sprint 6 — per-class flag eval CLI runner.

Walks fixtures/eval/gold_flags/*.yaml, runs the pipeline on each pair,
writes eval/results/per_class.json + per_class.md.

Usage:
    uv run python scripts/run_per_class_flag_eval.py
"""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from interlock.align.embed import embed_voyage
from interlock.eval.per_class import evaluate_class, load_gold_class

GOLD_DIR = Path("fixtures/eval/gold_flags")
OUT_JSON = Path("eval/results/per_class.json")
OUT_MD = Path("eval/results/per_class.md")


def main() -> int:
    if not GOLD_DIR.exists():
        print(f"no gold dir {GOLD_DIR}; nothing to do")
        return 0
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)

    reports: list[dict] = []
    md_lines = ["# Per-class flag eval report", ""]

    for p in sorted(GOLD_DIR.glob("*.yaml")):
        gold = load_gold_class(p)
        if gold is None:
            print(f"skip (load failed): {p}")
            continue
        report = evaluate_class(gold, embed_fn=embed_voyage)
        reports.append({
            "file": str(p),
            "doc_class": report.doc_class,
            "precision": report.precision,
            "recall": report.recall,
            "f1": report.f1,
            "per_pair": [asdict(r) for r in report.per_pair],
        })
        md_lines.append(f"## {report.doc_class}")
        md_lines.append("")
        md_lines.append(
            f"- Precision: **{report.precision:.2f}** | "
            f"Recall: **{report.recall:.2f}** | "
            f"F1: **{report.f1:.2f}** | "
            f"pairs: {len(report.per_pair)}"
        )
        md_lines.append("")
        for pr in report.per_pair:
            md_lines.append(
                f"  - `{pr.pair_id}`: "
                f"TP={pr.tp_ids or '[]'} "
                f"FN={pr.fn_ids or '[]'} "
                f"FP={pr.fp_ids or '[]'}"
            )
        md_lines.append("")

    OUT_JSON.write_text(json.dumps(reports, indent=2), encoding="utf-8")
    OUT_MD.write_text("\n".join(md_lines) + "\n", encoding="utf-8")
    print(f"wrote {OUT_JSON}")
    print(f"wrote {OUT_MD}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
