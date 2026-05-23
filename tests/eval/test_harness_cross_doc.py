"""Option 2 (cross-doc) gold-set acceptance test.

Runs the pipeline against the synthetic transformer spec ↔ Eaton coordination
study pair and asserts:
- All TP-CD flags surfaced at confidence ≥ 0.5.
- No FP-CD trap surfaced at confidence ≥ 0.5.

Skipped when VOYAGE_API_KEY is unset (uses real Voyage embeddings).
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
import yaml
from dotenv import load_dotenv

load_dotenv()

GOLD = Path("fixtures/eval/gold_cross_doc.yaml")


@pytest.mark.skipif(not os.getenv("VOYAGE_API_KEY"), reason="VOYAGE_API_KEY not set")
def test_cross_doc_gold_set_thresholds() -> None:
    from interlock.align.embed import embed_voyage
    from interlock.pipeline import review_two_documents

    spec = yaml.safe_load(GOLD.read_text())
    pair = spec["pair"]
    threshold = spec["acceptance"]["surface_threshold"]

    flags = review_two_documents(
        pair["doc_a"],
        pair["doc_b"],
        embed_fn=embed_voyage,
        doc_a_id=pair["doc_a_id"],
        doc_b_id=pair["doc_b_id"],
        same_page_only=False,
        classify_docs=False,
        use_llm_extraction=False,
        use_llm_reranker=False,
        use_entity_grounding=False,
        use_llm_judge=False,
    )
    above = [f for f in flags if f.confidence >= threshold]

    surfaced_text = " ".join(
        f"{f.parameter} {f.a_record.raw_value} {f.b_record.raw_value}" for f in above
    ).lower()

    # TPs: each gold value substring should appear in some surfaced flag.
    tps = [g for g in spec["flags"] if g["expected"] == "surfaced"]
    missing = [
        g["id"]
        for g in tps
        if g["doc_a_value"].lower().split()[0] not in surfaced_text
    ]
    assert not missing, f"missing TP flags: {missing}; surfaced: {surfaced_text}"

    # FPs: gold values should NOT appear in surfaced flags.
    fps = [g for g in spec["flags"] if g["expected"] == "suppressed"]
    leaked = [
        g["id"]
        for g in fps
        if g["doc_a_value"].lower().split()[0] in surfaced_text
    ]
    assert not leaked, f"FP traps leaked: {leaked}; surfaced: {surfaced_text}"
