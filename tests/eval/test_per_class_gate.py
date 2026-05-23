"""Sprint 6 — soft per-class CI gate.

For each gold class file in fixtures/eval/gold_flags/, run the harness
and assert precision ≥ floor / recall ≥ floor. Sparse classes (< 3 gold
cases) are xfail-soft so corpus growth doesn't break CI.

Slow-marked (Voyage required); skipped without VOYAGE_API_KEY.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

pytestmark = pytest.mark.slow

needs_voyage = pytest.mark.skipif(
    not os.getenv("VOYAGE_API_KEY"),
    reason="VOYAGE_API_KEY required for live pipeline eval",
)

GOLD_DIR = Path("fixtures/eval/gold_flags")
PRECISION_FLOOR = 0.6
RECALL_FLOOR = 0.6
SPARSE_THRESHOLD = 3


def _gold_files() -> list[Path]:
    if not GOLD_DIR.exists():
        return []
    return sorted(GOLD_DIR.glob("*.yaml"))


@needs_voyage
@pytest.mark.parametrize(
    "gold_path", _gold_files(), ids=lambda p: p.stem,
)
def test_per_class_meets_precision_recall_floor(gold_path: Path) -> None:
    """Per-class precision + recall must meet floor. Sparse classes
    (< 3 gold cases counting TP + FP traps across all pairs) → xfail."""
    from interlock.align.embed import embed_voyage
    from interlock.eval.per_class import evaluate_class, load_gold_class

    gold = load_gold_class(gold_path)
    assert gold is not None, f"gold load failed for {gold_path}"
    gold_count = sum(
        len(p.surfaced) + len(p.suppressed) for p in gold.pairs
    )
    if gold_count < SPARSE_THRESHOLD:
        pytest.xfail(
            f"sparse gold for {gold.doc_class} (n={gold_count}); "
            f"floor enforcement deferred until corpus grows"
        )

    report = evaluate_class(gold, embed_fn=embed_voyage)
    assert report.precision >= PRECISION_FLOOR, (
        f"{gold.doc_class}: precision {report.precision:.2f} < "
        f"floor {PRECISION_FLOOR}; per_pair={report.per_pair}"
    )
    assert report.recall >= RECALL_FLOOR, (
        f"{gold.doc_class}: recall {report.recall:.2f} < "
        f"floor {RECALL_FLOOR}; per_pair={report.per_pair}"
    )
