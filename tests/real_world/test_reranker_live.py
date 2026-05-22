"""Sprint 4 exit gate — live-API eval of the LLM pairing reranker.

Slow-marked. Skipped without ANTHROPIC_API_KEY.

Cost: ~$0.01 per test cold (1 reranker call each), $0 warm.

Exit-gate cases (from PIVOT_PLAN Sprint 4):
1. KRP-C-1600SP (main fuse) vs LPS-RK-400SP (branch fuse) — different
   ampacity families. Reranker must decline_to_pair OR score < 0.5.
2. 150 kVA (XFMR-001) vs 100 kVA (XFMR-002) on a one-line diagram —
   two different transformers labelled side-by-side. Reranker must
   decline_to_pair OR score < 0.5.
3. Positive control — same value, same equipment-class context.
   Reranker must score >= 0.7 and NOT decline.
"""

from __future__ import annotations

import os

import pytest
from dotenv import load_dotenv

load_dotenv(override=True)

pytestmark = pytest.mark.slow

needs_anthropic = pytest.mark.skipif(
    not os.getenv("ANTHROPIC_API_KEY"),
    reason="ANTHROPIC_API_KEY required for live reranker",
)


def _record(name: str, raw: str, page: int, span: str | None = None, doc_id: str = "doc"):  # type: ignore[no-untyped-def]
    from interlock.extract.parameters import ParameterRecord
    return ParameterRecord(
        doc_id=doc_id, page=page, bbox=(0, 0, 100, 10), section=None,
        span_text=span or raw, name=name, raw_value=raw,
        normalized_magnitude=None, normalized_unit=None,
    )


@needs_anthropic
def test_krp_c_lps_rk_pair_correctly_declined() -> None:
    """Fuse part-numbers from different ampacity families must NOT pair."""
    from interlock.align.exact import AlignedPair
    from interlock.llm_pipeline.pair import rerank_weak_pairs

    a = _record(
        "Fuse Designation", "KRP-C-1600SP", page=4,
        span="Main feeder fuse KRP-C-1600SP 1600A class L",
        doc_id="doc_a",
    )
    b = _record(
        "Fuse Designation", "LPS-RK-400SP", page=5,
        span="Branch circuit fuse LPS-RK-400SP 400A class RK1",
        doc_id="doc_b",
    )
    pair = AlignedPair(
        a=a, b=b, name_match_confidence=1.0, value_equivalent=False,
        pairing_confidence=0.5,
    )
    out = rerank_weak_pairs([pair])
    if not out:
        return  # decline_to_pair dropped the pair — success
    assert len(out) == 1
    assert out[0].pairing_confidence < 0.5, (
        f"reranker should low-score this pair, got "
        f"{out[0].pairing_confidence}: {out[0].rerank_rationale}"
    )


@needs_anthropic
def test_150kva_100kva_pair_correctly_declined() -> None:
    """Two different transformers on a one-line diagram must NOT pair."""
    from interlock.align.exact import AlignedPair
    from interlock.llm_pipeline.pair import rerank_weak_pairs

    a = _record(
        "Rated Power", "150 kVA", page=2,
        span="XFMR-001 nameplate: 150 kVA 13.8kV-480V",
        doc_id="doc_a",
    )
    b = _record(
        "Rated Power", "100 kVA", page=2,
        span="XFMR-002 nameplate: 100 kVA 13.8kV-208V",
        doc_id="doc_b",
    )
    pair = AlignedPair(
        a=a, b=b, name_match_confidence=1.0, value_equivalent=False,
        pairing_confidence=0.5,
    )
    out = rerank_weak_pairs([pair])
    if not out:
        return
    assert len(out) == 1
    assert out[0].pairing_confidence < 0.5, (
        f"reranker should low-score this pair, got "
        f"{out[0].pairing_confidence}: {out[0].rerank_rationale}"
    )


@needs_anthropic
def test_same_value_same_section_correctly_paired() -> None:
    """Positive control: same value on both sides in the same section
    should rerank to a HIGH score (and not be dropped)."""
    from interlock.align.exact import AlignedPair
    from interlock.llm_pipeline.pair import rerank_weak_pairs

    a = _record(
        "Rated Impedance", "5.75 %", page=3,
        span="Z = 5.75 % per IEEE C57.12.00",
        doc_id="doc_a",
    )
    b = _record(
        "Rated Impedance", "5.75 %", page=4,
        span="Impedance: 5.75 % at 75°C",
        doc_id="doc_b",
    )
    pair = AlignedPair(
        a=a, b=b, name_match_confidence=1.0, value_equivalent=True,
        pairing_confidence=0.5,
    )
    out = rerank_weak_pairs([pair])
    assert len(out) == 1, "positive control must not drop"
    assert out[0].pairing_confidence >= 0.7, (
        f"reranker should high-score the same-value pair, got "
        f"{out[0].pairing_confidence}: {out[0].rerank_rationale}"
    )
