"""Sprint 4 — AlignedPair back-compat default tests.

Two new fields default to None / False so every existing alignment test
that constructs AlignedPair by hand keeps working. The reranker
(Phase 27.2) overwrites these when invoked through the pipeline.
"""

from __future__ import annotations

from interlock.align.exact import AlignedPair
from interlock.extract.parameters import ParameterRecord


def _record() -> ParameterRecord:
    return ParameterRecord(
        doc_id="d", page=1, bbox=(0, 0, 100, 10), section=None,
        span_text="200A", name="Feeder Rating", raw_value="200 A",
        normalized_magnitude=200.0, normalized_unit="ampere",
    )


def test_rerank_rationale_defaults_to_none() -> None:
    p = AlignedPair(
        a=_record(), b=_record(),
        name_match_confidence=1.0, value_equivalent=True,
    )
    assert p.rerank_rationale is None


def test_reranked_defaults_to_false() -> None:
    p = AlignedPair(
        a=_record(), b=_record(),
        name_match_confidence=1.0, value_equivalent=True,
    )
    assert p.reranked is False


def test_rerank_fields_can_be_set_explicitly() -> None:
    p = AlignedPair(
        a=_record(), b=_record(),
        name_match_confidence=1.0, value_equivalent=True,
        rerank_rationale="confirmed pair",
        reranked=True,
    )
    assert p.rerank_rationale == "confirmed pair"
    assert p.reranked is True
