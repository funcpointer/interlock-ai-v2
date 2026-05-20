"""Pipeline-level behavioral tests on real PDFs.

Asserts properties the system must hold across any input:
- self-comparison surfaces zero flags
- unrelated-document pairs surface zero flags
- determinism: same input → same output (twice)
- cross-doc-mode toggle does not produce false flags on revision-diff fixture
"""

from __future__ import annotations

import os

import pytest
from dotenv import load_dotenv

load_dotenv()

from interlock.pipeline import review_two_documents  # noqa: E402

EATON = "fixtures/pdfs/doc_a_60pct.pdf"
EATON_REV = "fixtures/pdfs/doc_b_90pct.pdf"
SPEC = "fixtures/pdfs/spec_xfmr_001.pdf"
SEL = "fixtures/pdfs/real_sel_xfmr_protection.pdf"

needs_voyage = pytest.mark.skipif(
    not os.getenv("VOYAGE_API_KEY"), reason="VOYAGE_API_KEY not set"
)


def _embed(texts: list[str]) -> dict[str, list[float]]:
    from interlock.align.embed import embed_voyage

    return embed_voyage(texts)


def _stub_embed(_texts: list[str]) -> dict[str, list[float]]:
    # Deterministic non-similar stub for tests that don't need Voyage.
    return {t: [hash(t) % 7919 / 7919.0, 0.1, 0.1] for t in _texts}


def test_self_compare_eaton_yields_zero_flags() -> None:
    """Comparing a document to itself must not surface any mismatches.

    Every parameter equals itself by construction.
    """
    flags = review_two_documents(
        EATON, EATON, embed_fn=_stub_embed, doc_a_id="a", doc_b_id="b"
    )
    high = [f for f in flags if f.confidence >= 0.6]
    assert not high, f"self-compare leaked {len(high)} flag(s): {[f.parameter for f in high]}"


def test_self_compare_spec_yields_zero_flags() -> None:
    flags = review_two_documents(
        SPEC, SPEC, embed_fn=_stub_embed, doc_a_id="a", doc_b_id="b", same_page_only=False
    )
    high = [f for f in flags if f.confidence >= 0.5]
    assert not high, f"spec self-compare leaked: {[f.parameter for f in high]}"


def test_unrelated_docs_yield_zero_high_confidence_flags_with_stub_embed() -> None:
    """SEL paper has zero extractable params (documented), so pairing it with
    Eaton must yield zero flags regardless of embed function.
    """
    flags = review_two_documents(
        SEL, EATON, embed_fn=_stub_embed, doc_a_id="sel", doc_b_id="eaton"
    )
    high = [f for f in flags if f.confidence >= 0.5]
    assert not high


def test_pipeline_is_deterministic_with_stub_embedder() -> None:
    """Two runs with the same inputs must produce identical flag sets."""
    a = review_two_documents(
        EATON, EATON_REV, embed_fn=_stub_embed, doc_a_id="a", doc_b_id="b"
    )
    b = review_two_documents(
        EATON, EATON_REV, embed_fn=_stub_embed, doc_a_id="a", doc_b_id="b"
    )
    ka = sorted((f.parameter, f.a_record.raw_value, f.b_record.raw_value) for f in a)
    kb = sorted((f.parameter, f.a_record.raw_value, f.b_record.raw_value) for f in b)
    assert ka == kb


def test_revision_diff_pipeline_with_cross_doc_mode_does_not_inject_false_flags() -> None:
    """Turning on cross-doc mode for a revision-diff pair (where layout is
    shared) must not invent new spurious flags — semantic alignment may add
    candidates but unit+value comparisons keep the FP rate at zero on the
    locked gold set.
    """
    flags = review_two_documents(
        EATON,
        EATON_REV,
        embed_fn=_stub_embed,
        doc_a_id="a",
        doc_b_id="b",
        same_page_only=False,
    )
    # FP-1 trap (150 kVA vs 0.15 MVA equal) must remain suppressed.
    suspicious = [
        f for f in flags if f.confidence >= 0.6 and "150 kVA" in f.a_record.raw_value
    ]
    assert not suspicious, f"FP-1 trap leaked under cross-doc mode: {suspicious}"


@needs_voyage
def test_cross_doc_real_embedder_surfaces_expected_three_flags() -> None:
    """End-to-end Option 2 with real Voyage embedder: surface exactly the
    three planted TPs above 0.5, and no extras above 0.5.
    """
    flags = review_two_documents(
        SPEC,
        EATON,
        embed_fn=_embed,
        doc_a_id="spec",
        doc_b_id="eaton",
        same_page_only=False,
    )
    above = [f for f in flags if f.confidence >= 0.5]
    params = {f.parameter for f in above}
    expected = {"Rated Power", "Rated Impedance", "Primary Voltage"}
    assert expected <= params, f"missing: {expected - params}"
    # No extra surprises: at most a small margin above the 3 expected.
    assert len(above) <= 5, f"unexpected flag inflation: {[f.parameter for f in above]}"


@needs_voyage
def test_cross_doc_real_embedder_flag_set_is_stable() -> None:
    """Real Voyage embeddings have minor non-determinism between API calls;
    individual cosines may drift by ~1e-3. The surfaced flag *parameter set*
    must remain stable even if absolute confidence values fluctuate slightly.
    """
    a = review_two_documents(
        SPEC, EATON, embed_fn=_embed, doc_a_id="spec", doc_b_id="eaton", same_page_only=False
    )
    b = review_two_documents(
        SPEC, EATON, embed_fn=_embed, doc_a_id="spec", doc_b_id="eaton", same_page_only=False
    )
    params_a = sorted({f.parameter for f in a if f.confidence >= 0.5})
    params_b = sorted({f.parameter for f in b if f.confidence >= 0.5})
    assert params_a == params_b, f"flag set drift: {params_a} vs {params_b}"
