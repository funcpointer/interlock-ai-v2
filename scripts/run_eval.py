"""Run pipeline against locked fixture pair; score against gold.yaml; write baseline.json.

Usage:
    uv run python scripts/run_eval.py

Reads VOYAGE_API_KEY from environment (.env). Falls back to a deterministic stub
embedder if the key is absent (useful for offline CI).
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import yaml
from dotenv import load_dotenv

load_dotenv()

from interlock.pipeline import review_two_documents  # noqa: E402

GOLD = Path("fixtures/eval/gold.yaml")
OUT = Path("eval/results/baseline.json")
DOC_A = "fixtures/pdfs/doc_a_60pct.pdf"
DOC_B = "fixtures/pdfs/doc_b_90pct.pdf"
SURFACE_THRESHOLD = 0.6


def _stub_embedder(names: list[str]) -> dict[str, list[float]]:
    return {n: [(hash(n) % 1000) / 1000.0, 0.0] for n in names}


def _real_or_stub_embedder():  # type: ignore[no-untyped-def]
    if os.environ.get("VOYAGE_API_KEY"):
        from interlock.align.embed import embed_voyage

        return embed_voyage
    return _stub_embedder


def _norm(s: str | None) -> str:
    return "".join((s or "").split()).casefold()


def _flag_matches_gold(flag, gold) -> bool:  # type: ignore[no-untyped-def]
    """Heuristic match: flag and gold entry refer to same site if page matches
    AND any of (value, span_text) is a whitespace-normalized substring on
    either side of the flag."""
    if flag.a_record.page != gold["doc_a"]["page"]:
        return False
    a_val = _norm(gold["doc_a"].get("value"))
    b_val = _norm(gold["doc_b"].get("value"))
    a_span = _norm(gold["doc_a"].get("span_text"))
    b_span = _norm(gold["doc_b"].get("span_text"))
    flag_a = _norm(flag.a_record.raw_value) + _norm(flag.a_record.span_text)
    flag_b = _norm(flag.b_record.raw_value) + _norm(flag.b_record.span_text)
    if a_val and a_val in flag_a:
        return True
    if b_val and b_val in flag_b:
        return True
    if a_span and a_span in flag_a:
        return True
    if b_span and b_span in flag_b:
        return True
    return False


def main() -> None:
    gold = yaml.safe_load(GOLD.read_text())["flags"]
    embedder = _real_or_stub_embedder()
    # v2.7 — pin to v1.5-deterministic path. The eval gold (Phase 11) was
    # captured against the deterministic pipeline; v2.4+ default LLM lanes
    # introduce non-determinism between runs that breaks the harness's
    # 100% TP recall + 0% FP-trap assertion.
    flags = review_two_documents(
        DOC_A, DOC_B, embed_fn=embedder,
        classify_docs=False,
        use_llm_extraction=False,
        use_llm_reranker=False,
        use_entity_grounding=False,
        use_llm_judge=False,
    )
    above_threshold = [f for f in flags if f.confidence >= SURFACE_THRESHOLD]

    per_id: dict[str, dict[str, object]] = {}
    for g in gold:
        gid = g["id"]
        matched = [f for f in above_threshold if _flag_matches_gold(f, g)]
        per_id[gid] = {
            "expected": g["expected"],
            "category": g["category"],
            "matched_flags": len(matched),
            "result": _result_for(g["expected"], matched),
        }

    tp_ids = [g for g in gold if g["expected"] == "surfaced" and g["id"].startswith("TP")]
    fp_ids = [g for g in gold if g["expected"] == "suppressed"]
    fn_ids = [g for g in gold if g["id"].startswith("FN")]

    tp_hit = sum(1 for g in tp_ids if per_id[g["id"]]["result"] == "TP")
    fp_hit = sum(1 for g in fp_ids if per_id[g["id"]]["result"] == "FP")

    recall_tp = tp_hit / len(tp_ids) if tp_ids else 0.0
    fp_rate_traps = fp_hit / len(fp_ids) if fp_ids else 0.0

    report = {
        "surface_threshold": SURFACE_THRESHOLD,
        "n_flags_total": len(flags),
        "n_flags_above_threshold": len(above_threshold),
        "tp_total": len(tp_ids),
        "tp_hit": tp_hit,
        "fp_traps_total": len(fp_ids),
        "fp_hits": fp_hit,
        "fn_total": len(fn_ids),
        "recall_tp": recall_tp,
        "fp_rate_traps": fp_rate_traps,
        "per_id": per_id,
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))


def _result_for(expected: str, matched) -> str:  # type: ignore[no-untyped-def]
    if expected == "surfaced":
        return "TP" if matched else "FN"
    if expected == "suppressed":
        return "FP" if matched else "TN"
    return "?"


if __name__ == "__main__":
    main()
