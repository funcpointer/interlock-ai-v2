"""Sprint 6 — confidence calibration CLI runner.

Re-runs the pipeline for every pair in fixtures/eval/gold_flags/*.yaml,
labels each surfaced flag as TP / not-TP using the gold's surfaced list,
then computes Brier + reliability bins. Writes docs/eval/confidence_calibration.md.

Usage:
    uv run python scripts/run_confidence_calibration.py
"""

from __future__ import annotations

from pathlib import Path

from interlock.align.embed import embed_voyage
from interlock.detect.mismatch import Flag
from interlock.eval.calibration import calibrate, render_markdown
from interlock.eval.per_class import (
    flag_matches_gold,
    load_gold_class,
)

GOLD_DIR = Path("fixtures/eval/gold_flags")
OUT_MD = Path("docs/eval/confidence_calibration.md")


def main() -> int:
    if not GOLD_DIR.exists():
        print(f"no gold dir {GOLD_DIR}; nothing to do")
        return 0
    OUT_MD.parent.mkdir(parents=True, exist_ok=True)

    from interlock.pipeline import review_two_documents

    labeled: list[tuple[Flag, bool]] = []
    for p in sorted(GOLD_DIR.glob("*.yaml")):
        gold = load_gold_class(p)
        if gold is None:
            continue
        for pair in gold.pairs:
            try:
                flags = review_two_documents(
                    pair.doc_a, pair.doc_b,
                    embed_fn=embed_voyage,
                    **pair.pipeline_kwargs,
                )
            except Exception as e:
                print(f"pipeline failed for {pair.id}: {e}")
                continue
            for f in flags:
                is_tp = any(flag_matches_gold(f, g) for g in pair.surfaced)
                labeled.append((f, is_tp))

    report = calibrate(labeled)
    OUT_MD.write_text(render_markdown(report), encoding="utf-8")
    print(f"wrote {OUT_MD} (n={report.n}, brier={report.brier_score:.4f})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
