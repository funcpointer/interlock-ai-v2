"""Sprint 1 acceptance-gate harness.

Reads fixtures/eval/gold_doc_class.yaml, runs classify_doc() on every
entry, writes a JSON results file and a Markdown report.

Usage:
    uv run python scripts/run_doc_class_eval.py
        --output-json   eval/results/doc_class.json
        --output-report eval/results/doc_class_report.md

Cached on the diskcache layer — first run hits API (~$1.40), repeats are free.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

load_dotenv(override=True)

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from interlock.llm_pipeline.classify import classify_doc  # noqa: E402
from interlock.llm_pipeline.schemas.doc_class import DocClass  # noqa: E402

GOLD = Path("fixtures/eval/gold_doc_class.yaml")
DEFAULT_JSON = Path("eval/results/doc_class.json")
DEFAULT_REPORT = Path("eval/results/doc_class_report.md")


def run(output_json: Path, output_report: Path) -> int:
    if not os.getenv("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY not set; live-API eval cannot run.", file=sys.stderr)
        return 2

    gold = yaml.safe_load(GOLD.read_text(encoding="utf-8"))
    docs = gold["docs"]
    acceptance = gold["acceptance"]

    per_doc: list[dict[str, Any]] = []
    for entry in docs:
        path = entry["path"]
        expected = entry["expected_class"]
        if not Path(path).exists():
            per_doc.append({
                "path": path, "expected": expected, "actual": "missing",
                "confidence": 0.0, "match": False, "source": entry["source"],
                "notes": entry.get("notes", ""),
            })
            continue
        result = classify_doc(path)
        per_doc.append({
            "path": path,
            "expected": expected,
            "actual": result.doc_class.value,
            "confidence": result.confidence,
            "match": result.doc_class.value == expected,
            "source": entry["source"],
            "reasoning": result.reasoning,
            "detected_indicators": result.detected_indicators,
            "notes": entry.get("notes", ""),
        })

    total = len(per_doc)
    correct = sum(1 for r in per_doc if r["match"])
    real = [r for r in per_doc if r["source"] == "real"]
    synth = [r for r in per_doc if r["source"] == "synthetic"]
    real_correct = sum(1 for r in real if r["match"])
    synth_correct = sum(1 for r in synth if r["match"])

    per_class: dict[str, dict[str, int]] = defaultdict(lambda: {"total": 0, "correct": 0})
    for r in per_doc:
        per_class[r["expected"]]["total"] += 1
        if r["match"]:
            per_class[r["expected"]]["correct"] += 1

    returned_unknown = [r for r in per_doc if r["actual"] == DocClass.unknown.value]
    unknown_correct = sum(1 for r in returned_unknown if r["expected"] == DocClass.unknown.value)
    unknown_precision = (
        unknown_correct / len(returned_unknown) if returned_unknown else 1.0
    )

    summary = {
        "total_docs": total,
        "overall_accuracy": correct / total if total else 0.0,
        "real_accuracy": real_correct / len(real) if real else 0.0,
        "synthetic_accuracy": synth_correct / len(synth) if synth else 0.0,
        "unknown_precision": unknown_precision,
        "per_class": {
            k: {
                "total": v["total"], "correct": v["correct"],
                "recall": v["correct"] / v["total"] if v["total"] else 0.0,
            }
            for k, v in per_class.items()
        },
        "acceptance_thresholds": acceptance,
        "passes": {
            "overall": (correct / total if total else 0.0) >= acceptance["overall_accuracy_min"],
            "real": (real_correct / len(real) if real else 0.0) >= acceptance["real_only_accuracy_min"],
            "synthetic": (synth_correct / len(synth) if synth else 0.0) >= acceptance["synthetic_only_accuracy_min"],
            "unknown_precision": unknown_precision >= acceptance["unknown_precision_min"],
        },
    }

    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(
        {"summary": summary, "per_doc": per_doc}, indent=2,
    ), encoding="utf-8")

    lines = ["# Sprint 1 — Doc-Class Classifier Eval Report", ""]
    lines.append(f"**Total docs:** {total}")
    lines.append(f"**Overall accuracy:** {summary['overall_accuracy']:.2%} "
                 f"({correct}/{total})")
    lines.append(f"**Real-only accuracy:** {summary['real_accuracy']:.2%} "
                 f"({real_correct}/{len(real)})")
    lines.append(f"**Synthetic-only accuracy:** {summary['synthetic_accuracy']:.2%} "
                 f"({synth_correct}/{len(synth)})")
    lines.append(f"**Unknown precision:** {unknown_precision:.2%}")
    lines.append("")
    lines.append("## Acceptance gate status")
    lines.append("")
    lines.append("| Gate | Pass | Threshold |")
    lines.append("|---|---|---|")
    for key, passed in summary["passes"].items():
        thresh_key = (
            "overall_accuracy_min" if key == "overall" else
            "real_only_accuracy_min" if key == "real" else
            "synthetic_only_accuracy_min" if key == "synthetic" else
            "unknown_precision_min"
        )
        lines.append(f"| {key} | {'✅' if passed else '❌'} | {acceptance[thresh_key]:.0%} |")
    lines.append("")
    lines.append("## Per-class breakdown")
    lines.append("")
    lines.append("| Class | Total | Correct | Recall |")
    lines.append("|---|---:|---:|---:|")
    for cls, stats in summary["per_class"].items():
        lines.append(f"| {cls} | {stats['total']} | {stats['correct']} | {stats['recall']:.0%} |")
    lines.append("")
    lines.append("## Per-doc verdicts")
    lines.append("")
    lines.append("| Path | Source | Expected | Actual | Confidence | Match |")
    lines.append("|---|---|---|---|---:|---|")
    for r in per_doc:
        mark = "✅" if r["match"] else "❌"
        lines.append(
            f"| `{r['path']}` | {r['source']} | {r['expected']} | {r['actual']} | "
            f"{r['confidence']:.2f} | {mark} |"
        )

    output_report.parent.mkdir(parents=True, exist_ok=True)
    output_report.write_text("\n".join(lines), encoding="utf-8")

    print(f"wrote {output_json}")
    print(f"wrote {output_report}")
    print()
    print(f"Overall: {correct}/{total} = {summary['overall_accuracy']:.2%}")
    print(f"Real:    {real_correct}/{len(real)} = {summary['real_accuracy']:.2%}")
    print(f"Synth:   {synth_correct}/{len(synth)} = {summary['synthetic_accuracy']:.2%}")
    return 0 if all(summary["passes"].values()) else 1


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-json", type=Path, default=DEFAULT_JSON)
    parser.add_argument("--output-report", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args()
    sys.exit(run(args.output_json, args.output_report))


if __name__ == "__main__":
    main()
