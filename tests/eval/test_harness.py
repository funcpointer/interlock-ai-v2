import json
import os
import subprocess
from pathlib import Path

import pytest
import yaml
from dotenv import load_dotenv

load_dotenv()

GOLD = Path("fixtures/eval/gold.yaml")
BASELINE = Path("eval/results/baseline.json")
REQUIRED_IDS = {"TP-1", "TP-2", "TP-3", "FP-1", "FP-2", "FN-1"}


def test_gold_set_complete_and_schema_valid() -> None:
    data = yaml.safe_load(GOLD.read_text())
    assert "flags" in data
    ids = {f["id"] for f in data["flags"]}
    assert REQUIRED_IDS <= ids, f"missing flag ids: {REQUIRED_IDS - ids}"
    for f in data["flags"]:
        assert {"id", "category", "expected", "doc_a", "doc_b"} <= set(
            f
        ), f"{f['id']} missing required keys"
        if f["expected"] == "surfaced":
            assert "min_confidence" in f, f"{f['id']} expected surfaced needs min_confidence"
        if f["expected"] == "suppressed":
            assert "max_confidence" in f, f"{f['id']} expected suppressed needs max_confidence"


@pytest.mark.skipif(
    not os.environ.get("VOYAGE_API_KEY"),
    reason="eval threshold test requires VOYAGE_API_KEY (real pipeline behavior)",
)
def test_eval_meets_acceptance_thresholds() -> None:
    """Run the eval harness end-to-end and enforce FIXTURES §6 thresholds."""
    subprocess.check_call(["uv", "run", "python", "scripts/run_eval.py"])
    res = json.loads(BASELINE.read_text())
    assert res["recall_tp"] == 1.0, f"expected 100% TP recall, got {res['recall_tp']}"
    assert res["fp_rate_traps"] == 0.0, f"expected 0 FP trap surfacing, got {res['fp_rate_traps']}"
