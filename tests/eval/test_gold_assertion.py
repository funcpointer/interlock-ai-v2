"""v2.8.6 — gold-fixture regression test.

Locks the behavior of the locked Option 1 fixture pair (``doc_a_60pct``
↔ ``doc_b_90pct``) against the gold YAML at
``fixtures/eval/gold_flags/coordination_study.yaml``.

Runs the pipeline with all LLM features OFF (regex + align + detect
only) so the test is deterministic and offline. Catches regressions
to v2.8.x heuristic changes that might silently drop a TP or surface
a known FP.

Currently asserted:
- TP-1 (Transformer Impedance 5.75 → 0.575 on p3): MUST surface.
- TP-2 (Fault Current 20,000 → 200,000 on p2): MUST surface.
- FP-1 (150 kVA ↔ 0.15 MVA Transformer Rating equivalence): must NOT
  surface (same magnitude, different units).
- FN-1 (LPN-RK-500SP gap on p7): MUST surface via checklist gap
  detector (v2.8.4).

NOT YET asserted (known gaps):
- TP-3 (Transformer Rating 1000 → 100 kVA on p7): blocked by cross-doc
  entity resolution; tackled in v2.8.7+ / Sprint 9.
"""

from __future__ import annotations

import pytest

DOC_A = "fixtures/pdfs/doc_a_60pct.pdf"
DOC_B = "fixtures/pdfs/doc_b_90pct.pdf"

pytestmark = pytest.mark.slow


def _trivial_embedder(names: list[str]) -> dict[str, list[float]]:
    """Deterministic stub. Returns 2-D vectors hashed from the name.
    Pipeline uses the embedder for semantic alignment fallback; the stub
    keeps the test offline without forcing semantic alignment to also be
    disabled."""
    return {n: [(hash(n) % 1000) / 1000.0, 0.0] for n in names}


def _run() -> object:
    from interlock.pipeline import review_two_documents_full
    return review_two_documents_full(
        DOC_A, DOC_B,
        embed_fn=_trivial_embedder,
        classify_docs=False,
        use_llm_extraction=False,
        use_llm_reranker=False,
        use_entity_grounding=False,
        use_llm_judge=False,
        use_vision_lane=False,  # offline determinism
        same_page_only=False,
    )


def _has_flag(flags, parameter_substr: str, a_substr: str, b_substr: str) -> bool:
    for f in flags:
        if parameter_substr.lower() not in f.parameter.lower():
            continue
        a = (f.a_record.raw_value or "")
        b = (f.b_record.raw_value or "")
        if a_substr in a and b_substr in b:
            return True
        if a_substr in b and b_substr in a:
            return True
    return False


def test_gold_tp_1_impedance_surfaces() -> None:
    """5.75%Z (A p3) → 0.575%Z (B p3) — decimal-shift impedance error.
    The flagship demo flag; must always surface."""
    result = _run()
    assert _has_flag(
        result.flags, "Impedance", "5.75", "0.575",
    ), (
        f"TP-1 missing. Surfaced flags: "
        f"{[(f.parameter, f.a_record.raw_value, f.b_record.raw_value) for f in result.flags]}"
    )


def test_gold_tp_2_fault_current_surfaces() -> None:
    """20,000A (A p2) → 200,000A (B p2) — fault-current decimal shift.
    Was being dropped pre-v2.8.5 due to _string_family false fallback."""
    result = _run()
    assert _has_flag(
        result.flags, "Fault Current", "20,000", "200,000",
    ), (
        f"TP-2 missing. Surfaced flags: "
        f"{[(f.parameter, f.a_record.raw_value, f.b_record.raw_value) for f in result.flags]}"
    )


def test_gold_fp_1_kva_mva_equivalence_does_not_flag() -> None:
    """150 kVA == 0.15 MVA — dimensionally equivalent, NOT a flag.
    Locks the equivalence-suppression behavior so future heuristic
    changes can't silently re-surface this trap."""
    result = _run()
    flagged = _has_flag(
        result.flags, "kVA", "150", "0.15",
    ) or _has_flag(
        result.flags, "Transformer Rating", "150", "0.15",
    )
    assert not flagged, (
        f"FP-1 regressed — 150 kVA / 0.15 MVA equivalence surfaced. "
        f"Surfaced flags: "
        f"{[(f.parameter, f.a_record.raw_value, f.b_record.raw_value) for f in result.flags]}"
    )


def test_gold_fn_1_lpn_rk_500sp_gap_surfaces() -> None:
    """LPN-RK-500SP appears in doc_a p7 TCC3 table but is REMOVED from
    doc_b p7. v2.8.4 checklist-gap detector should surface this with
    authority_rule='checklist_gap'.

    v2.8.6 — gap detector is page-scoped: missing on B p7 specifically
    triggers gap, even when the fuse model number appears on other B
    pages (typical: one-line on p2 still references the fuse)."""
    result = _run()
    gap_flags = [
        f for f in result.flags
        if f.authority_rule == "checklist_gap"
        and "LPN-RK-500SP" in (f.a_record.raw_value or "")
    ]
    assert gap_flags, (
        f"FN-1 missing — LPN-RK-500SP checklist gap not surfaced. "
        f"Authority rules in result: "
        f"{sorted({f.authority_rule for f in result.flags})}"
    )


def test_gold_tp_3_transformer_rating_surfaces() -> None:
    """TP-3 (1000 kVA → 100 kVA on p7).

    Started surfacing at v2.8.6 once the row-marker dedup priority flip
    landed: regex with digit-only entity_tag ('1', '2' table row markers)
    survives cross-lane dedup over LLM-text records with value-encoding
    descriptor tags ('1000KVA XFMR'), giving align_exact a stable
    positional anchor that's identical across docs even though the
    value mutated."""
    result = _run()
    assert _has_flag(
        result.flags, "Transformer Rating", "1000", "100",
    ), (
        f"TP-3 regressed. Surfaced flags: "
        f"{[(f.parameter, f.a_record.raw_value, f.b_record.raw_value) for f in result.flags]}"
    )


# --- v2.8.7 — LLM-on gold variant ----------------------------------
#
# The offline tests above run with all LLM features OFF. That catches
# offline-deterministic regressions but misses ones in the rerank /
# judge / vision-lane interaction. The LLM-on variant runs with all
# LLM-driven features ON and mocks the API calls so it stays offline
# + cheap. Catches the field-trip TP-2 regression (rerank declined
# the 20kA↔200kA pair on tag mismatch) that the offline path didn't.


def _llm_on_run(mocker) -> object:  # type: ignore[no-untyped-def]
    """Run the full pipeline with all LLM features ON, mocking each
    external call with a permissive response."""
    from unittest.mock import MagicMock

    from interlock.pipeline import review_two_documents_full

    def _resp(text: str) -> MagicMock:
        block = MagicMock()
        block.text = text
        return MagicMock(content=[block])

    # 1. Doc classifier: coordination_study with high confidence.
    mocker.patch(
        "interlock.llm_pipeline.classify._call_claude_classify",
        return_value=_resp(
            '{"doc_class":"coordination_study","confidence":0.95,'
            '"reasoning":"test stub","detected_indicators":[],'
            '"pages_consulted":[1]}'
        ),
    )

    # 2. Track 2 LLM text extractor: empty per-page response (regex
    # carries the load). Permissive — won't add noise.
    mocker.patch(
        "interlock.llm_pipeline.extract._call_claude_extract",
        return_value=_resp('{"claims":[],"page":1,"notes":""}'),
    )

    # 3. Entity detector: empty per-page response.
    mocker.patch(
        "interlock.llm_pipeline.entity_detect._call_claude_entity",
        return_value=_resp('{"entities":[],"page":1}'),
    )

    # 4. Pair reranker: re-score weak pairs at 0.85 (above threshold,
    # not declined). Reroutes pairs through the reranker path without
    # actually dropping any. Catches the v2.8.7 #B override: when
    # mocked rationale references both raw_values + declines, override
    # kicks in for >3× magnitude pairs.
    mocker.patch(
        "interlock.llm_pipeline.pair._call_claude_pair",
        return_value=_resp(
            '{"score":0.85,"rationale":"stub keeping pair","decline_to_pair":false}'
        ),
    )

    # 5. Significance judge: pass-through severity, generic rationale.
    # call_structured returns (SignificanceJudgment, usage) tuple.
    from interlock.detect.significance import SignificanceJudgment
    judgment = SignificanceJudgment(
        severity="critical",
        within_typical_tolerance=False,
        engineering_explanation="stub judge rationale for test",
        downstream_effects=[],
        confidence=0.9,
        cited_clause_ids=[],
    )
    mocker.patch(
        "interlock.detect.significance.call_structured",
        return_value=(judgment, MagicMock(input_tokens=0, output_tokens=0)),
    )

    # 6. Vision lane: stub no claims so the vision path runs but adds
    # nothing. (Real vision-lane calls are expensive + non-deterministic.)
    mocker.patch(
        "interlock.llm_pipeline.vision_extract._call_claude_vision",
        return_value=_resp(
            '{"page":1,"page_understanding":"stub","page_layout":"diagram",'
            '"claims":[]}'
        ),
    )

    return review_two_documents_full(
        DOC_A, DOC_B,
        embed_fn=_trivial_embedder,
        classify_docs=True,
        use_llm_extraction=True,
        use_llm_reranker=True,
        use_entity_grounding=True,
        use_llm_judge=True,
        use_vision_lane=True,
        same_page_only=False,
    )


def test_gold_llm_on_tp_1_surfaces(mocker) -> None:  # type: ignore[no-untyped-def]
    """LLM-on variant: TP-1 must still surface through the full
    pipeline with rerank + judge active."""
    result = _llm_on_run(mocker)
    assert _has_flag(
        result.flags, "Impedance", "5.75", "0.575",
    ), (
        f"TP-1 missed in LLM-on mode. Flags: "
        f"{[(f.parameter, f.a_record.raw_value, f.b_record.raw_value) for f in result.flags]}"
    )


def test_gold_llm_on_tp_2_survives_rerank(mocker) -> None:  # type: ignore[no-untyped-def]
    """LLM-on variant: TP-2 Fault Current 20kA → 200kA must survive
    rerank. The field-trip regression (v2.8.7 fix #B) was rerank
    declining the pair on tag-string mismatch ('X1' vs 'Fault X')."""
    result = _llm_on_run(mocker)
    assert _has_flag(
        result.flags, "Fault Current", "20", "200",
    ), (
        f"TP-2 dropped by rerank in LLM-on mode. Flags: "
        f"{[(f.parameter, f.a_record.raw_value, f.b_record.raw_value) for f in result.flags]}"
    )


def test_gold_llm_on_fn_1_surfaces(mocker) -> None:  # type: ignore[no-untyped-def]
    """LLM-on variant: checklist gap detector still emits LPN-RK-500SP."""
    result = _llm_on_run(mocker)
    gap_flags = [
        f for f in result.flags
        if f.authority_rule == "checklist_gap"
        and "LPN-RK-500SP" in (f.a_record.raw_value or "")
    ]
    if not gap_flags:
        # Diagnostic dump on failure — see where LPN-RK-500SP went.
        a_records = [
            (r.extraction_lane, r.page, r.raw_value, r.entity_tag)
            for r in result.unpaired_a
            if "LPN-RK-500SP" in (r.raw_value or "")
        ]
        b_records = [
            (r.extraction_lane, r.page, r.raw_value)
            for r in result.unpaired_b
            if "LPN-RK-500SP" in (r.raw_value or "")
        ]
        paired = [
            (f.parameter, f.a_record.raw_value, f.a_record.page,
             f.b_record.raw_value, f.b_record.page)
            for f in result.flags
            if "LPN-RK-500SP" in (f.a_record.raw_value or "")
            or "LPN-RK-500SP" in (f.b_record.raw_value or "")
        ]
        raise AssertionError(
            f"FN-1 missing in LLM-on mode. "
            f"Doc A unpaired LPN-RK-500SP: {a_records}; "
            f"Doc B unpaired LPN-RK-500SP: {b_records}; "
            f"flags with LPN-RK-500SP: {paired}; "
            f"total unpaired_a={len(result.unpaired_a)} "
            f"unpaired_b={len(result.unpaired_b)} "
            f"total flags={len(result.flags)}"
        )
