"""CI gate for the Sprint 1 doc-class classifier.

Reads the committed eval/results/doc_class.json (NOT live API). Asserts
the recorded summary meets the gold acceptance thresholds. The eval
script is run manually by an engineer; this test ensures the committed
result satisfies the gates.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

RESULTS = Path("eval/results/doc_class.json")
GOLD = Path("fixtures/eval/gold_doc_class.yaml")


@pytest.fixture(scope="module")
def eval_data() -> dict:
    if not RESULTS.exists():
        pytest.skip("eval results not present; run scripts/run_doc_class_eval.py first")
    return json.loads(RESULTS.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def gold_data() -> dict:
    return yaml.safe_load(GOLD.read_text(encoding="utf-8"))


def test_overall_accuracy_meets_gate(eval_data: dict, gold_data: dict) -> None:
    summary = eval_data["summary"]
    threshold = gold_data["acceptance"]["overall_accuracy_min"]
    assert summary["overall_accuracy"] >= threshold, (
        f"overall {summary['overall_accuracy']:.2%} below {threshold:.0%} gate"
    )


def test_real_accuracy_meets_gate(eval_data: dict, gold_data: dict) -> None:
    threshold = gold_data["acceptance"]["real_only_accuracy_min"]
    assert eval_data["summary"]["real_accuracy"] >= threshold, (
        f"real-only {eval_data['summary']['real_accuracy']:.2%} below {threshold:.0%}"
    )


def test_synthetic_accuracy_meets_gate(eval_data: dict, gold_data: dict) -> None:
    threshold = gold_data["acceptance"]["synthetic_only_accuracy_min"]
    assert eval_data["summary"]["synthetic_accuracy"] >= threshold, (
        f"synthetic {eval_data['summary']['synthetic_accuracy']:.2%} below {threshold:.0%}"
    )


def test_unknown_precision_meets_gate(eval_data: dict, gold_data: dict) -> None:
    threshold = gold_data["acceptance"]["unknown_precision_min"]
    assert eval_data["summary"]["unknown_precision"] >= threshold, (
        f"unknown precision {eval_data['summary']['unknown_precision']:.2%} "
        f"below {threshold:.0%}"
    )
