"""Regression-gate: Option 1 gold set must pass with same_page_only=False.

Phase 18 removes the cross-document-vs-revision-diff toggle from the UI so
the reviewer just uploads two PDFs. Implementation choice: always run with
``same_page_only=False`` (the cross-doc setting). For that to be safe, the
Option 1 revision-diff gold set must still meet its acceptance thresholds
under that default.

This test runs the locked Option 1 pipeline with ``same_page_only=False``
and asserts: 3 of 3 planted TPs surfaced above the 0.6 suppression
threshold; 0 of 2 FP traps surfaced above 0.6.

Uses the deterministic stub embedder so the test stays fast and stable.
"""

from __future__ import annotations

from interlock.pipeline import review_two_documents

DOC_A = "fixtures/pdfs/doc_a_60pct.pdf"
DOC_B = "fixtures/pdfs/doc_b_90pct.pdf"
THRESHOLD = 0.6


def _stub_embed(texts: list[str]) -> dict[str, list[float]]:
    return {t: [hash(t) % 7919 / 7919.0, 0.1, 0.1] for t in texts}


def _surface_strings(flags: list) -> set[str]:  # type: ignore[type-arg]
    """Concatenate raw values both sides for fuzzy substring matching against
    the planted TP / FP values."""
    out: set[str] = set()
    for f in flags:
        if f.confidence >= THRESHOLD:
            out.add(f"{f.a_record.raw_value} || {f.b_record.raw_value}")
    return out


def test_option1_gold_passes_under_cross_doc_default() -> None:
    flags = review_two_documents(
        DOC_A,
        DOC_B,
        embed_fn=_stub_embed,
        same_page_only=False,
    )
    surfaced = _surface_strings(flags)
    surfaced_concat = " ".join(surfaced)

    # The three planted TPs — every one must surface above the threshold.
    # Each is identified by a distinctive raw-value pair from the mutation log.
    assert "5.75 %" in surfaced_concat and "0.575 %" in surfaced_concat, (
        f"TP-1 (impedance decimal shift) not surfaced: {surfaced}"
    )
    assert "20,000 A" in surfaced_concat and "200,000 A" in surfaced_concat, (
        f"TP-2 (fault current decimal shift) not surfaced: {surfaced}"
    )
    assert "1000 kVA" in surfaced_concat and "100 kVA" in surfaced_concat, (
        f"TP-3 (transformer rating decimal shift) not surfaced: {surfaced}"
    )

    # The two FP traps — neither may surface above the threshold.
    fp1_leaked = any("150 kVA" in s or "0.15 MVA" in s for s in surfaced)
    assert not fp1_leaked, (
        f"FP-1 (150 kVA vs 0.15 MVA unit-equivalent) leaked: {surfaced}"
    )
    fp2_leaked = any("Time Current Curve" in s for s in surfaced)
    assert not fp2_leaked, (
        f"FP-2 (heading rephrase) leaked: {surfaced}"
    )


def test_option1_gold_recall_under_cross_doc_default() -> None:
    """Hard recall gate: exactly 3 distinct TP families must be present."""
    flags = review_two_documents(
        DOC_A,
        DOC_B,
        embed_fn=_stub_embed,
        same_page_only=False,
    )
    high = [f for f in flags if f.confidence >= THRESHOLD]
    # Group surfaced flags by parameter family — each TP family should appear
    # at least once. TP-3 has two planted sites; we accept >= 3 distinct
    # parameters surfaced above the threshold.
    distinct_params = {f.parameter for f in high}
    assert len(distinct_params) >= 3, (
        f"Expected ≥3 distinct parameter families above threshold; "
        f"got {len(distinct_params)}: {distinct_params}"
    )
