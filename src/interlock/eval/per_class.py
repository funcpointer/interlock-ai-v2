"""Sprint 6 — per-class flag eval harness.

Loads gold flag YAMLs from fixtures/eval/gold_flags/*.yaml, runs the
pipeline on each pair, scores precision/recall/F1 against the expected
surfaced (TP) and suppressed (FP-trap) flag lists.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field

from interlock.detect.mismatch import Flag

logger = logging.getLogger(__name__)

EmbedFn = Callable[[list[str]], dict[str, list[float]]]


class GoldFlag(BaseModel):
    model_config = ConfigDict(frozen=True)
    id: str
    parameter_substr: str
    a_value_substr: str
    b_value_substr: str


class GoldPair(BaseModel):
    model_config = ConfigDict(frozen=True)
    id: str
    doc_a: str
    doc_b: str
    pipeline_kwargs: dict[str, Any] = Field(default_factory=dict)
    surfaced: list[GoldFlag] = Field(default_factory=list)
    suppressed: list[GoldFlag] = Field(default_factory=list)


class GoldClassFile(BaseModel):
    model_config = ConfigDict(frozen=True)
    doc_class: str
    description: str = ""
    pairs: list[GoldPair]


@dataclass(frozen=True)
class PairResult:
    pair_id: str
    tp_ids: list[str] = field(default_factory=list)
    fn_ids: list[str] = field(default_factory=list)
    fp_ids: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ClassEvalReport:
    doc_class: str
    precision: float
    recall: float
    f1: float
    per_pair: list[PairResult] = field(default_factory=list)


def load_gold_class(path: Path) -> GoldClassFile | None:
    """Return GoldClassFile or None on failure."""
    if not path.exists():
        return None
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return GoldClassFile(**raw)
    except Exception as e:
        logger.warning("gold load failed for %s: %s", path, e)
        return None


def flag_matches_gold(flag: Flag, gold: GoldFlag) -> bool:
    """Loose substring match: parameter + both raw_values must contain
    their respective gold substrings (case-insensitive)."""
    if gold.parameter_substr.lower() not in flag.parameter.lower():
        return False
    a_lc = (flag.a_record.raw_value or "").lower()
    b_lc = (flag.b_record.raw_value or "").lower()
    if gold.a_value_substr.lower() not in a_lc:
        return False
    if gold.b_value_substr.lower() not in b_lc:
        return False
    return True


def score_pair(
    gold: GoldPair, flags: list[Flag], *, threshold: float = 0.6,
) -> PairResult:
    """Score a single pair's TP / FN / FP against its gold."""
    above = [f for f in flags if f.confidence >= threshold]
    tp_ids: list[str] = []
    fn_ids: list[str] = []
    for g in gold.surfaced:
        if any(flag_matches_gold(f, g) for f in above):
            tp_ids.append(g.id)
        else:
            fn_ids.append(g.id)
    fp_ids: list[str] = []
    for g in gold.suppressed:
        if any(flag_matches_gold(f, g) for f in above):
            fp_ids.append(g.id)
    return PairResult(pair_id=gold.id, tp_ids=tp_ids, fn_ids=fn_ids, fp_ids=fp_ids)


def _f1(p: float, r: float) -> float:
    if p + r == 0:
        return 0.0
    return 2 * p * r / (p + r)


def evaluate_class(
    gold: GoldClassFile,
    *,
    embed_fn: EmbedFn,
    threshold: float = 0.6,
) -> ClassEvalReport:
    """Run pipeline for each pair; aggregate precision/recall/F1."""
    from interlock.pipeline import review_two_documents

    per_pair: list[PairResult] = []
    total_tp = total_fn = total_fp = 0
    for pair in gold.pairs:
        try:
            flags = review_two_documents(
                pair.doc_a, pair.doc_b,
                embed_fn=embed_fn,
                **pair.pipeline_kwargs,
            )
        except Exception as e:
            logger.warning("pipeline failed for pair %s: %s", pair.id, e)
            flags = []
        r = score_pair(pair, flags, threshold=threshold)
        per_pair.append(r)
        total_tp += len(r.tp_ids)
        total_fn += len(r.fn_ids)
        total_fp += len(r.fp_ids)

    precision = total_tp / (total_tp + total_fp) if (total_tp + total_fp) else 0.0
    recall = total_tp / (total_tp + total_fn) if (total_tp + total_fn) else 0.0
    return ClassEvalReport(
        doc_class=gold.doc_class,
        precision=precision,
        recall=recall,
        f1=_f1(precision, recall),
        per_pair=per_pair,
    )
