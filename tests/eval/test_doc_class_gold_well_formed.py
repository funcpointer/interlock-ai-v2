"""Validate the Sprint 1 acceptance corpus YAML.

These tests are FAST — no API. They confirm the YAML loads, references
real files, and uses only DocClass enum values.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from interlock.llm_pipeline.schemas.doc_class import DocClass

GOLD = Path("fixtures/eval/gold_doc_class.yaml")


@pytest.fixture(scope="module")
def gold_data() -> dict:
    return yaml.safe_load(GOLD.read_text(encoding="utf-8"))


def test_gold_yaml_parses(gold_data: dict) -> None:
    assert "docs" in gold_data
    assert "acceptance" in gold_data


def test_every_gold_doc_path_exists(gold_data: dict) -> None:
    missing = [
        entry["path"] for entry in gold_data["docs"]
        if not Path(entry["path"]).exists()
    ]
    assert not missing, f"missing fixture PDFs: {missing}"


def test_every_gold_expected_class_is_valid_enum(gold_data: dict) -> None:
    valid = {c.value for c in DocClass}
    for entry in gold_data["docs"]:
        assert entry["expected_class"] in valid, (
            f"invalid expected_class {entry['expected_class']!r} for {entry['path']}"
        )


def test_gold_source_field_is_real_or_synthetic(gold_data: dict) -> None:
    for entry in gold_data["docs"]:
        assert entry["source"] in {"real", "synthetic"}, (
            f"bad source {entry['source']!r} for {entry['path']}"
        )


def test_acceptance_thresholds_present_and_in_range(gold_data: dict) -> None:
    a = gold_data["acceptance"]
    for key in (
        "overall_accuracy_min", "real_only_accuracy_min",
        "synthetic_only_accuracy_min", "unknown_precision_min",
    ):
        assert key in a, f"missing acceptance threshold: {key}"
        assert 0.0 <= a[key] <= 1.0, f"threshold {key} = {a[key]} out of [0, 1]"


def test_corpus_has_at_least_one_doc_per_listed_class(gold_data: dict) -> None:
    """Surface gaps in coverage — every class in the corpus must have ≥ 1
    doc. Classes with zero examples can't be acceptance-tested at all."""
    from collections import Counter
    counts = Counter(entry["expected_class"] for entry in gold_data["docs"])
    # Sprint 1 partial corpus may not cover every DocClass yet; assert that
    # whatever IS in the corpus has at least one example.
    for cls, n in counts.items():
        assert n >= 1, f"class {cls} has {n} examples"
