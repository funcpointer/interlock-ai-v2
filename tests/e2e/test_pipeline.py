from interlock.pipeline import (
    ReviewResult,
    review_two_documents,
    review_two_documents_full,
)

DOC_A = "fixtures/pdfs/doc_a_60pct.pdf"
DOC_B = "fixtures/pdfs/doc_b_90pct.pdf"


def _trivial_embedder(names: list[str]) -> dict[str, list[float]]:
    # Deterministic vectors derived from string hash; semantic alignment
    # rarely hits its threshold here, which is fine — exact alignment carries.
    return {n: [(hash(n) % 1000) / 1000.0, 0.0] for n in names}


def test_pipeline_surfaces_at_least_three_planted_mismatches() -> None:
    flags = review_two_documents(DOC_A, DOC_B, embed_fn=_trivial_embedder)
    # 3 TPs are planted in fixtures (TP-1 impedance, TP-2 fault current, TP-3 transformer rating).
    high = [f for f in flags if f.confidence >= 0.6]
    assert len(high) >= 3, f"expected ≥3 high-confidence flags, got {len(high)}"


def test_pipeline_does_not_surface_fp_traps_above_threshold() -> None:
    flags = review_two_documents(DOC_A, DOC_B, embed_fn=_trivial_embedder)
    # FP-1: 150 kVA vs 0.15 MVA — unit-equivalent, must not flag.
    for f in flags:
        if f.parameter == "Transformer Rating":
            # If both magnitudes round to 150_000 VA, suppress.
            if (
                f.a_record.normalized_magnitude is not None
                and abs(f.a_record.normalized_magnitude - 150_000) < 1
            ):
                raise AssertionError(f"FP-1 trap surfaced: {f.rationale}")


def test_pipeline_emits_directional_flags() -> None:
    flags = review_two_documents(DOC_A, DOC_B, embed_fn=_trivial_embedder)
    for f in flags:
        assert f.authoritative_doc_id == "doc_a"
        assert f.deviating_doc_id == "doc_b"
        assert f.a_record.page >= 1
        assert f.b_record.page >= 1
        assert f.a_record.span_text
        assert f.b_record.span_text


def test_review_two_documents_full_returns_review_result() -> None:
    """The _full variant returns ReviewResult; the legacy shim still
    returns just the flag list."""
    result = review_two_documents_full(DOC_A, DOC_B, embed_fn=_trivial_embedder)
    assert isinstance(result, ReviewResult)
    assert isinstance(result.flags, list)
    assert isinstance(result.unpaired_a, list)
    assert isinstance(result.unpaired_b, list)
    # Legacy shim must return the same flag list.
    legacy_flags = review_two_documents(DOC_A, DOC_B, embed_fn=_trivial_embedder)
    assert {(f.parameter, f.a_record.raw_value, f.b_record.raw_value) for f in legacy_flags} == {
        (f.parameter, f.a_record.raw_value, f.b_record.raw_value) for f in result.flags
    }


def test_unpaired_records_disjoint_from_paired_records() -> None:
    """Every unpaired record must NOT appear as a.a_record or b.b_record
    in any flag — otherwise the UI would double-count the same record as
    both a flag AND a gap."""
    result = review_two_documents_full(DOC_A, DOC_B, embed_fn=_trivial_embedder)
    flagged_a_ids = {id(f.a_record) for f in result.flags}
    flagged_b_ids = {id(f.b_record) for f in result.flags}
    for r in result.unpaired_a:
        assert id(r) not in flagged_a_ids, f"record both unpaired and flagged: {r.name}={r.raw_value}"
    for r in result.unpaired_b:
        assert id(r) not in flagged_b_ids, f"record both unpaired and flagged: {r.name}={r.raw_value}"


def test_pipeline_stage_cb_fires_in_order() -> None:
    """UI relies on stage_cb to drive per-stage progress placeholders.

    Each stage must fire (start, then done) and the overall sequence of
    starts must match the declared pipeline order — otherwise the
    placeholders flicker out of order or some never resolve.
    """
    calls: list[tuple[str, str]] = []
    review_two_documents(
        DOC_A,
        DOC_B,
        embed_fn=_trivial_embedder,
        use_llm_judge=False,
        stage_cb=lambda sid, state: calls.append((sid, state)),
    )
    starts = [sid for (sid, state) in calls if state == "start"]
    dones = [sid for (sid, state) in calls if state == "done"]
    assert starts == ["ingest_a", "ingest_b", "extract", "align", "detect"]
    assert dones == starts, "every started stage must also complete"
    # No "judge" stage when use_llm_judge=False.
    assert "judge" not in starts
