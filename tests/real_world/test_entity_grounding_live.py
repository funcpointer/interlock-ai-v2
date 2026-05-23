"""Sprint 4.5 exit gate — live-API eval of entity grounding.

Slow-marked. Skipped without ANTHROPIC_API_KEY.

Exit-gate cases:
1. Eaton coordination-study tutorial: 200A Feeder vs 400A Feeder false
   positive (different physical example circuits both labelled identically
   in both docs).
2. Eaton coordination-study tutorial: 77A FLA vs 42A IFLA on JCN80E
   motor false positive (different physical parameters of the same motor).
3. Positive control: the canonical Option 1 %Z 5.2% vs 4.8% mismatch
   STILL surfaces with grounding on.

Cost: ~$0.10–0.20 per cold run (entity detector scans all pages of both
fixtures, ~18 pages total at $0.005/page); $0 warm.
"""

from __future__ import annotations

import os

import pytest
from dotenv import load_dotenv

from interlock.cache import disk as disk_cache

load_dotenv(override=True)

pytestmark = pytest.mark.slow

needs_anthropic = pytest.mark.skipif(
    not os.getenv("ANTHROPIC_API_KEY"),
    reason="ANTHROPIC_API_KEY required for live entity grounding",
)

DOC_A = "fixtures/pdfs/doc_a_60pct.pdf"
DOC_B = "fixtures/pdfs/doc_b_90pct.pdf"


def _trivial_embedder(names: list[str]) -> dict[str, list[float]]:
    return {n: [(hash(n) % 1000) / 1000.0, 0.0] for n in names}


@pytest.fixture(autouse=True)
def _clear_entity_cache() -> None:
    disk_cache.clear_namespace("llm-entities")
    yield


@needs_anthropic
def test_feeder_200a_400a_false_positive_suppressed() -> None:
    """200A Feeder on p2 vs 400A Feeder on p6 must NOT surface as a
    Feeder Rating mismatch when entity grounding is on."""
    from interlock.pipeline import review_two_documents_full
    result = review_two_documents_full(
        DOC_A, DOC_B, embed_fn=_trivial_embedder,
        same_page_only=False,
        classify_docs=False,
        use_llm_extraction=True,
        use_llm_reranker=False,
        use_entity_grounding=True,
        use_llm_judge=False,
    )
    feeder_flags = [f for f in result.flags if "feeder" in f.parameter.lower()]
    for f in feeder_flags:
        # Exclude comma-containing values (Fault Current 200,000 etc) so
        # the test specifically targets the 200A↔400A tutorial pair, not
        # unrelated LLM-extraction-taxonomy issues.
        a_val = f.a_record.raw_value.lower().replace(" ", "")
        b_val = f.b_record.raw_value.lower().replace(" ", "")
        if "," in a_val or "," in b_val:
            continue
        is_200_400 = (
            ("200a" in a_val and "400a" in b_val)
            or ("400a" in a_val and "200a" in b_val)
        )
        assert not is_200_400, (
            f"200A/400A feeder false positive should be suppressed; got "
            f"{f.parameter}: A={f.a_record.raw_value} (p{f.a_record.page}) "
            f"B={f.b_record.raw_value} (p{f.b_record.page})"
        )


@needs_anthropic
def test_motor_fla_77a_42a_false_positive_suppressed() -> None:
    """77A FLA vs 42A IFLA on the same motor (JCN80E) must NOT surface
    as a Motor FLA mismatch when entity grounding is on."""
    from interlock.pipeline import review_two_documents_full
    result = review_two_documents_full(
        DOC_A, DOC_B, embed_fn=_trivial_embedder,
        same_page_only=False,
        classify_docs=False,
        use_llm_extraction=True,
        use_llm_reranker=False,
        use_entity_grounding=True,
        use_llm_judge=False,
    )
    fla_flags = [
        f for f in result.flags
        if "fla" in f.parameter.lower() or "motor" in f.parameter.lower()
    ]
    for f in fla_flags:
        a_val = f.a_record.raw_value.replace(" ", "").lower()
        b_val = f.b_record.raw_value.replace(" ", "").lower()
        is_77_42 = (
            ("77" in a_val and "42" in b_val)
            or ("42" in a_val and "77" in b_val)
        )
        assert not is_77_42, (
            f"77/42 motor FLA false positive should be suppressed; got "
            f"{f.parameter}: A={f.a_record.raw_value} B={f.b_record.raw_value}"
        )


@needs_anthropic
def test_real_xfmr_impedance_still_flags_with_grounding() -> None:
    """Positive control: canonical Option 1 %Z mismatch (4.8 % vs 5.2 %)
    STILL surfaces with grounding on. Entity grounding must not regress
    real mismatches on real equipment."""
    from interlock.pipeline import review_two_documents_full
    result = review_two_documents_full(
        DOC_A, DOC_B, embed_fn=_trivial_embedder,
        same_page_only=False,
        classify_docs=False,
        use_llm_extraction=False,
        use_llm_reranker=False,
        use_entity_grounding=True,
        use_llm_judge=False,
    )
    expected_params = {"%Z", "Fault Current", "Transformer Rating"}
    surfaced = {f.parameter for f in result.flags if f.confidence >= 0.6}
    assert expected_params.issubset(surfaced), (
        f"entity grounding regressed v1.5 snapshot: expected {expected_params}, "
        f"got {surfaced}"
    )
