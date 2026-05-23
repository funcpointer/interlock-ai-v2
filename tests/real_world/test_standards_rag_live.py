"""Sprint 5a exit gate — live-API eval of standards RAG.

Slow-marked. Skipped without ANTHROPIC_API_KEY.

Exit-gate cases:
1. %Z mismatch on Option 1 fixture → at least one cited clause referencing
   IEEE C57.12.00 (the canonical transformer-impedance standard).
2. Fault Current mismatch → at least one cited clause referencing IEEE 242
   or IEEE C37.04 (interrupting-rating / available-fault-current standards).
3. Empty-registry pathological case → judge runs without citations; flags
   still ship; cited_clauses == () everywhere.

Cost: ~$0.05 per cold run (small flag set on Option 1 fixture); $0 warm.
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
    reason="ANTHROPIC_API_KEY required for live standards RAG",
)

DOC_A = "fixtures/pdfs/doc_a_60pct.pdf"
DOC_B = "fixtures/pdfs/doc_b_90pct.pdf"


def _trivial_embedder(names: list[str]) -> dict[str, list[float]]:
    return {n: [(hash(n) % 1000) / 1000.0, 0.0] for n in names}


@pytest.fixture(autouse=True)
def _clear_judge_cache() -> None:
    disk_cache.clear_namespace("llm-significance")
    yield


@needs_anthropic
def test_xfmr_impedance_flag_cites_ieee_c57_12_00() -> None:
    """%Z mismatch must surface ≥1 cited clause referencing IEEE C57.12.00."""
    from interlock.pipeline import review_two_documents_full

    result = review_two_documents_full(
        DOC_A, DOC_B, embed_fn=_trivial_embedder,
        same_page_only=False,
        classify_docs=False,
        use_llm_extraction=False,
        use_llm_reranker=False,
        use_entity_grounding=False,
        use_llm_judge=True,
    )
    z_flags = [
        f for f in result.flags
        if "%Z" in f.parameter or "impedance" in f.parameter.lower()
    ]
    assert z_flags, "expected %Z flag on Option 1 fixture"
    cited_sources = [
        c.source_name for f in z_flags for c in f.cited_clauses
    ]
    assert any("C57.12.00" in s for s in cited_sources), (
        f"expected ≥1 IEEE C57.12.00 citation on %Z flag; got: {cited_sources}"
    )


@needs_anthropic
def test_fault_current_flag_cites_ieee_242_or_c37() -> None:
    """Fault Current mismatch must cite IEEE 242 or IEEE C37.04."""
    from interlock.pipeline import review_two_documents_full

    result = review_two_documents_full(
        DOC_A, DOC_B, embed_fn=_trivial_embedder,
        same_page_only=False,
        classify_docs=False,
        use_llm_extraction=False,
        use_llm_reranker=False,
        use_entity_grounding=False,
        use_llm_judge=True,
    )
    fc_flags = [f for f in result.flags if "fault" in f.parameter.lower()]
    assert fc_flags, "expected Fault Current flag on Option 1 fixture"
    cited_sources = [
        c.source_name for f in fc_flags for c in f.cited_clauses
    ]
    assert any(("242" in s) or ("C37" in s) for s in cited_sources), (
        f"expected ≥1 IEEE 242 / C37 citation on Fault Current flag; "
        f"got: {cited_sources}"
    )


@needs_anthropic
def test_empty_registry_pathological_still_ships_flags(monkeypatch, tmp_path) -> None:  # type: ignore[no-untyped-def]
    """Empty registry → judge runs without citations; flags still ship."""
    from interlock.llm_pipeline import standards as std
    from interlock.pipeline import review_two_documents_full

    empty = tmp_path / "empty.yaml"
    empty.write_text("clauses: []\n", encoding="utf-8")
    monkeypatch.setattr(std, "_CLAUSES_PATH", empty)

    result = review_two_documents_full(
        DOC_A, DOC_B, embed_fn=_trivial_embedder,
        same_page_only=False,
        classify_docs=False,
        use_llm_extraction=False,
        use_llm_reranker=False,
        use_entity_grounding=False,
        use_llm_judge=True,
    )
    assert result.flags, "flags should still ship when registry is empty"
    for f in result.flags:
        assert f.cited_clauses == (), (
            f"expected empty cited_clauses on every flag with empty registry; "
            f"got {f.cited_clauses}"
        )
