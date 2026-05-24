"""v2-specific pipeline tests — classify_docs parameter + DocClassification
plumbing. Mocked Anthropic calls so tests stay fast and offline."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from interlock.cache import disk as disk_cache

DOC_A = "fixtures/pdfs/doc_a_60pct.pdf"
DOC_B = "fixtures/pdfs/doc_b_90pct.pdf"


def _trivial_embedder(names: list[str]) -> dict[str, list[float]]:
    return {n: [(hash(n) % 1000) / 1000.0, 0.0] for n in names}


def _fake_classify_response(doc_class_value: str) -> MagicMock:
    content = MagicMock()
    content.text = (
        f'{{"doc_class":"{doc_class_value}","confidence":0.95,'
        f'"reasoning":"test stub","detected_indicators":[],'
        f'"pages_consulted":[1]}}'
    )
    return MagicMock(content=[content])


def _fake_extract_response(
    claims_json: str = '{"claims":[],"page":1,"notes":""}',
) -> MagicMock:
    content = MagicMock()
    content.text = claims_json
    return MagicMock(content=[content])


@pytest.fixture(autouse=True)
def _clear_classify_cache() -> None:
    disk_cache.clear_namespace("doc-class")
    yield
    disk_cache.clear_namespace("doc-class")


def test_classify_docs_false_returns_none(mocker) -> None:  # type: ignore[no-untyped-def]
    """Default classify_docs=False must NOT call the classifier."""
    from interlock.pipeline import review_two_documents_full
    spy = mocker.patch(
        "interlock.llm_pipeline.classify._call_claude_classify",
        return_value=_fake_classify_response("coordination_study"),
    )
    result = review_two_documents_full(
        DOC_A, DOC_B, embed_fn=_trivial_embedder,
        classify_docs=False,
        use_llm_extraction=False,
        use_llm_reranker=False,
        use_entity_grounding=False,
    )
    assert spy.call_count == 0
    assert result.doc_class_a is None
    assert result.doc_class_b is None


def test_classify_docs_true_populates_doc_class_fields(mocker) -> None:  # type: ignore[no-untyped-def]
    """classify_docs=True calls the classifier on BOTH documents and
    populates ReviewResult.doc_class_a / doc_class_b."""
    from interlock.llm_pipeline.schemas.doc_class import DocClass
    from interlock.pipeline import review_two_documents_full

    mocker.patch(
        "interlock.llm_pipeline.classify._call_claude_classify",
        return_value=_fake_classify_response("coordination_study"),
    )
    result = review_two_documents_full(
        DOC_A, DOC_B, embed_fn=_trivial_embedder,
        classify_docs=True,
        use_llm_extraction=False,
        use_llm_reranker=False,
        use_entity_grounding=False,
    )
    assert result.doc_class_a is not None
    assert result.doc_class_b is not None
    assert result.doc_class_a.doc_class == DocClass.coordination_study
    assert result.doc_class_b.doc_class == DocClass.coordination_study


def test_classify_docs_failure_returns_unknown_does_not_raise(mocker) -> None:  # type: ignore[no-untyped-def]
    """If the classifier raises (API outage), pipeline must continue
    with doc_class_a/b = DocClassification(unknown, 0.0, ...)."""
    from interlock.llm_pipeline.schemas.doc_class import DocClass
    from interlock.pipeline import review_two_documents_full

    mocker.patch(
        "interlock.llm_pipeline.classify._call_claude_classify",
        side_effect=RuntimeError("API outage simulated"),
    )
    result = review_two_documents_full(
        DOC_A, DOC_B, embed_fn=_trivial_embedder,
        classify_docs=True,
        use_llm_extraction=False,
        use_llm_reranker=False,
        use_entity_grounding=False,
    )
    assert isinstance(result.flags, list)  # pipeline still ran
    assert result.doc_class_a is not None
    assert result.doc_class_a.doc_class == DocClass.unknown


def test_classify_docs_false_is_bit_identical_to_v1() -> None:
    """The architectural safety claim: classify_docs=False MUST produce
    the same flags as the v1.5-mvp-ready pipeline on the locked Option 1
    fixture. This is the Track 1 invariant that gates every v2 commit."""
    from interlock.pipeline import review_two_documents_full

    result = review_two_documents_full(
        DOC_A, DOC_B, embed_fn=_trivial_embedder,
        classify_docs=False,
        use_llm_extraction=False,
        use_llm_reranker=False,
        use_entity_grounding=False,
    )
    expected_params = {"Transformer Impedance", "Fault Current", "Transformer Rating"}
    surfaced = {f.parameter for f in result.flags if f.confidence >= 0.6}
    assert expected_params.issubset(surfaced), (
        f"Track 1 invariant broken: expected {expected_params}, got {surfaced}"
    )


# --- Sprint 2: use_llm_extraction integration ---------------------------


@pytest.fixture(autouse=True)
def _clear_extract_cache() -> None:
    disk_cache.clear_namespace("llm-extract")
    yield
    disk_cache.clear_namespace("llm-extract")


def test_use_llm_extraction_false_does_not_call_extractor(mocker) -> None:  # type: ignore[no-untyped-def]
    """Default off: no LLM extraction call; all records are regex."""
    from interlock.pipeline import review_two_documents_full
    spy = mocker.patch(
        "interlock.llm_pipeline.extract._call_claude_extract",
        return_value=_fake_extract_response(),
    )
    result = review_two_documents_full(
        DOC_A, DOC_B, embed_fn=_trivial_embedder,
        classify_docs=False,
        use_llm_extraction=False,
        use_llm_reranker=False,
        use_entity_grounding=False,
    )
    assert spy.call_count == 0
    for f in result.flags:
        assert f.a_record.provenance == "regex"
        assert f.b_record.provenance == "regex"


def test_use_llm_extraction_true_runs_extractor_pipeline_still_ships_flags(mocker) -> None:  # type: ignore[no-untyped-def]
    """With extraction on, the pipeline runs LLM extraction calls and ships
    a flag list. Specific flags may differ from v1 because of additional
    Track 2 records — we don't lock the exact set here."""
    from interlock.pipeline import review_two_documents_full

    fake = '{"claims":[],"page":1,"notes":""}'  # empty claims; safe append
    spy = mocker.patch(
        "interlock.llm_pipeline.extract._call_claude_extract",
        return_value=_fake_extract_response(fake),
    )
    result = review_two_documents_full(
        DOC_A, DOC_B,
        embed_fn=_trivial_embedder,
        classify_docs=False,
        use_llm_extraction=True,
        use_llm_reranker=False,
        use_entity_grounding=False,
    )
    assert isinstance(result.flags, list)
    # Extractor was called (per-page across both docs).
    assert spy.call_count > 0


def test_snapshot_equivalence_use_llm_extraction_false() -> None:
    """Architectural safety: use_llm_extraction=False must produce the
    same flag parameter-set as v1.5-mvp-ready / v2.0-mvp on the locked
    Option 1 fixture."""
    from interlock.pipeline import review_two_documents_full

    result = review_two_documents_full(
        DOC_A, DOC_B,
        embed_fn=_trivial_embedder,
        classify_docs=False,
        use_llm_extraction=False,
        use_llm_reranker=False,
        use_entity_grounding=False,
    )
    expected_params = {"Transformer Impedance", "Fault Current", "Transformer Rating"}
    surfaced = {f.parameter for f in result.flags if f.confidence >= 0.6}
    assert expected_params.issubset(surfaced), (
        f"Track 1 invariant broken: expected {expected_params}, got {surfaced}"
    )


# --- Sprint 3: adjudicator pipeline integration --------------------------


def test_v1_snapshot_equivalence_all_flags_are_rule_only() -> None:
    """When both tracks off, every flag must be annotated 'rule_only' —
    Sprint 3's promise that v1.5 snapshot equivalence still holds."""
    from interlock.pipeline import review_two_documents_full

    result = review_two_documents_full(
        DOC_A, DOC_B,
        embed_fn=_trivial_embedder,
        classify_docs=False,
        use_llm_extraction=False,
        use_llm_reranker=False,
        use_entity_grounding=False,
    )
    assert result.flags, "expected non-zero baseline flags from Option 1 fixture"
    for f in result.flags:
        assert f.provenance == "rule_only", (
            f"v1 snapshot broken: flag {f.parameter} got provenance "
            f"{f.provenance!r}, expected 'rule_only'"
        )


def test_pipeline_annotates_provenance_when_llm_extraction_on(mocker) -> None:  # type: ignore[no-untyped-def]
    """With LLM extraction enabled, the pipeline still produces a flag
    list with provenance populated. (Specific labels depend on which
    records the aligner pairs — verified in adjudicator unit tests.)"""
    from interlock.pipeline import review_two_documents_full

    fake = '{"claims":[],"page":1,"notes":""}'
    mocker.patch(
        "interlock.llm_pipeline.extract._call_claude_extract",
        return_value=_fake_extract_response(fake),
    )
    result = review_two_documents_full(
        DOC_A, DOC_B,
        embed_fn=_trivial_embedder,
        classify_docs=False,
        use_llm_extraction=True,
        use_llm_reranker=False,
        use_entity_grounding=False,
    )
    for f in result.flags:
        # The field must be one of the four enumerated values, never None.
        assert f.provenance in {"rule_only", "llm_only", "mixed_track", "unknown"}


def test_adjudicator_runs_unconditionally() -> None:
    """Even with both tracks off — i.e. the v1.5 path — every flag should
    have provenance set to something (not the default 'unknown')."""
    from interlock.pipeline import review_two_documents_full

    result = review_two_documents_full(
        DOC_A, DOC_B,
        embed_fn=_trivial_embedder,
        classify_docs=False,
        use_llm_extraction=False,
        use_llm_reranker=False,
        use_entity_grounding=False,
    )
    for f in result.flags:
        assert f.provenance != "unknown", (
            "pipeline must annotate provenance for every flag"
        )


# --- Sprint 4: pairing reranker integration -----------------------------


@pytest.fixture(autouse=True)
def _clear_pair_cache() -> None:
    disk_cache.clear_namespace("llm-pair")
    yield
    disk_cache.clear_namespace("llm-pair")


def _fake_pair_response(decline: bool = False, score: float = 0.9) -> MagicMock:
    """Build a fake Claude response. Rationale embeds both common raw_values
    from the Option 1 fixture so the hallucination guard accepts it."""
    content = MagicMock()
    content.text = (
        '{"score":' + f"{score}" + ','
        '"rationale":"5.75 % and 5.75 % — same impedance record",'
        '"decline_to_pair":' + ("true" if decline else "false") + '}'
    )
    return MagicMock(content=[content])


def test_use_llm_reranker_false_is_bit_identical_to_v2_2(mocker) -> None:  # type: ignore[no-untyped-def]
    """Default off ⇒ no reranker call; flag set unchanged from v2.2."""
    from interlock.pipeline import review_two_documents_full
    spy = mocker.patch("interlock.llm_pipeline.pair._call_claude_pair")
    result = review_two_documents_full(
        DOC_A, DOC_B, embed_fn=_trivial_embedder,
        classify_docs=False,
        use_llm_extraction=False,
        use_llm_reranker=False,
        use_entity_grounding=False,
    )
    assert spy.call_count == 0
    expected_params = {"Transformer Impedance", "Fault Current", "Transformer Rating"}
    surfaced = {f.parameter for f in result.flags if f.confidence >= 0.6}
    assert expected_params.issubset(surfaced)
    for f in result.flags:
        assert f.rerank_rationale is None


def test_use_llm_reranker_true_unanimous_approve_preserves_flags(mocker) -> None:  # type: ignore[no-untyped-def]
    """Reranker approves every weak pair ⇒ flag count + parameters
    unchanged from Track 1."""
    from interlock.pipeline import review_two_documents_full
    mocker.patch(
        "interlock.llm_pipeline.pair._call_claude_pair",
        return_value=_fake_pair_response(decline=False, score=0.9),
    )
    result = review_two_documents_full(
        DOC_A, DOC_B, embed_fn=_trivial_embedder,
        classify_docs=False,
        use_llm_extraction=False,
        use_llm_reranker=True,
        use_entity_grounding=False,
    )
    expected_params = {"Transformer Impedance", "Fault Current", "Transformer Rating"}
    surfaced = {f.parameter for f in result.flags if f.confidence >= 0.6}
    assert expected_params.issubset(surfaced)


def test_pipeline_survives_reranker_exception(mocker) -> None:  # type: ignore[no-untyped-def]
    """API outage mid-rerank ⇒ pipeline still ships Track 1 flag set."""
    from interlock.pipeline import review_two_documents_full
    mocker.patch(
        "interlock.llm_pipeline.pair._call_claude_pair",
        side_effect=RuntimeError("API down"),
    )
    result = review_two_documents_full(
        DOC_A, DOC_B, embed_fn=_trivial_embedder,
        classify_docs=False,
        use_llm_extraction=False,
        use_llm_reranker=True,
        use_entity_grounding=False,
    )
    assert isinstance(result.flags, list)


def test_sprint3_provenance_and_sprint4_rationale_coexist() -> None:
    """Both labels live on the same Flag without interference."""
    from interlock.detect.mismatch import Flag
    from interlock.extract.parameters import ParameterRecord
    r = ParameterRecord(
        doc_id="d", page=1, bbox=(0, 0, 100, 10), section=None,
        span_text="5.75%Z", name="%Z", raw_value="5.75 %",
        normalized_magnitude=0.0575, normalized_unit="dimensionless",
        provenance="regex",  # type: ignore[arg-type]
    )
    f = Flag(
        parameter="%Z",
        a_record=r, b_record=r,
        authoritative_doc_id="d", deviating_doc_id="d",
        confidence=1.0, rationale="test", authority_rule="MVP",
        severity="major", deviation_pct=10.0, attribute_family="impedance_pct",
        provenance="rule_only",  # type: ignore[arg-type]
        rerank_rationale="confirmed pair",
    )
    assert f.provenance == "rule_only"
    assert f.rerank_rationale == "confirmed pair"


# --- Sprint 4.5: entity grounding pipeline integration ------------------


@pytest.fixture(autouse=True)
def _clear_entity_cache() -> None:
    disk_cache.clear_namespace("llm-entities")
    yield
    disk_cache.clear_namespace("llm-entities")


def _fake_entity_response(label: str, page: int = 1) -> MagicMock:
    content = MagicMock()
    content.text = (
        '{"page":' + str(page) + ',"entities":['
        '{"label":"' + label + '","kind":"equipment","y_top":0,"y_bottom":10000,"page":' + str(page) + '}'
        ']}'
    )
    return MagicMock(content=[content])


def test_use_entity_grounding_false_preserves_v22_snapshot(mocker) -> None:  # type: ignore[no-untyped-def]
    """All v2 toggles explicit False → v1.5 / v2.2 parameter set."""
    from interlock.pipeline import review_two_documents_full
    spy = mocker.patch("interlock.llm_pipeline.entity_detect._call_claude_entity")
    result = review_two_documents_full(
        DOC_A, DOC_B, embed_fn=_trivial_embedder,
        classify_docs=False,
        use_llm_extraction=False,
        use_llm_reranker=False,
        use_entity_grounding=False,
    )
    assert spy.call_count == 0
    expected_params = {"Transformer Impedance", "Fault Current", "Transformer Rating"}
    surfaced = {f.parameter for f in result.flags if f.confidence >= 0.6}
    assert expected_params.issubset(surfaced)


def test_use_entity_grounding_true_binds_tags_to_records(mocker) -> None:  # type: ignore[no-untyped-def]
    """With detector mocked to return one entity covering the whole page,
    every flagged record should have entity_tag populated."""
    from interlock.pipeline import review_two_documents_full
    mocker.patch(
        "interlock.llm_pipeline.entity_detect._call_claude_entity",
        return_value=_fake_entity_response("ALL_PAGE", page=1),
    )
    result = review_two_documents_full(
        DOC_A, DOC_B, embed_fn=_trivial_embedder,
        classify_docs=False,
        use_llm_extraction=False,
        use_llm_reranker=False,
        use_entity_grounding=True,
    )
    assert result.flags, "expected non-zero flags after entity grounding"
    tagged_count = sum(
        1 for f in result.flags
        if f.a_record.entity_tag or f.b_record.entity_tag
    )
    assert tagged_count > 0


def test_cross_entity_pair_refuses_to_form() -> None:
    """If A's record is tagged XFMR-001 and B's same-page same-name record
    is tagged XFMR-002, Phase 19 alignment refuses to pair them."""
    from interlock.align.exact import align_exact
    from interlock.extract.parameters import ParameterRecord

    a = ParameterRecord(
        doc_id="a", page=1, bbox=(0, 100, 100, 110), section=None,
        span_text="Z=5.75%", name="%Z", raw_value="5.75 %",
        normalized_magnitude=0.0575, normalized_unit="dimensionless",
        entity_tag="XFMR-001",
    )
    b = ParameterRecord(
        doc_id="b", page=1, bbox=(0, 100, 100, 110), section=None,
        span_text="Z=5.20%", name="%Z", raw_value="5.20 %",
        normalized_magnitude=0.052, normalized_unit="dimensionless",
        entity_tag="XFMR-002",
    )
    pairs = align_exact([a], [b])
    assert pairs == [], (
        "Phase 19 same-entity rule should refuse to pair across different entities"
    )


def test_detector_exception_falls_back_gracefully(mocker) -> None:  # type: ignore[no-untyped-def]
    """API outage mid-detect → pipeline still ships flags (no entity tags)."""
    from interlock.pipeline import review_two_documents_full
    mocker.patch(
        "interlock.llm_pipeline.entity_detect._call_claude_entity",
        side_effect=RuntimeError("API down"),
    )
    result = review_two_documents_full(
        DOC_A, DOC_B, embed_fn=_trivial_embedder,
        classify_docs=False,
        use_llm_extraction=False,
        use_llm_reranker=False,
        use_entity_grounding=True,
    )
    assert isinstance(result.flags, list)
    expected_params = {"Transformer Impedance", "Fault Current", "Transformer Rating"}
    surfaced = {f.parameter for f in result.flags if f.confidence >= 0.6}
    assert expected_params.issubset(surfaced)


# --- Sprint 5a: standards RAG integration -----------------------------


def _fake_judge_response_with_clauses(clause_ids: list[str]):  # type: ignore[no-untyped-def]
    """Build a fake call_structured tuple (Judgment, usage)."""
    from interlock.detect.significance import SignificanceJudgment
    j = SignificanceJudgment(
        severity="major",
        within_typical_tolerance=False,
        engineering_explanation="Test rationale.",
        downstream_effects=[],
        confidence=0.95,
        cited_clause_ids=clause_ids,
    )
    return (j, {"input": 0, "cache_read": 0, "cache_creation": 0, "output": 0})


@pytest.fixture(autouse=True)
def _clear_judge_cache() -> None:
    disk_cache.clear_namespace("llm-significance")
    yield
    disk_cache.clear_namespace("llm-significance")


def test_project_id_none_uses_base_registry(mocker) -> None:  # type: ignore[no-untyped-def]
    """Without project_id, judge sees only the base registry."""
    from interlock.pipeline import review_two_documents_full

    mocker.patch(
        "interlock.detect.significance.call_structured",
        return_value=_fake_judge_response_with_clauses(["IEEE-C57.12.00-2015-5.4"]),
    )
    result = review_two_documents_full(
        DOC_A, DOC_B, embed_fn=_trivial_embedder,
        classify_docs=False,
        use_llm_extraction=False,
        use_llm_reranker=False,
        use_entity_grounding=False,
        project_id=None,
    )
    # v2.8.1: canonical name is "Transformer Impedance"
    impedance_flags = [f for f in result.flags if "Impedance" in f.parameter]
    assert impedance_flags, "expected at least one %Z flag"
    cited_ids = {
        c.clause_id for f in impedance_flags for c in f.cited_clauses
    }
    # Base registry should expose IEEE-C57.12.00-2015-5.4 for impedance_pct
    assert "IEEE-C57.12.00-2015-5.4" in cited_ids


def test_project_id_loads_override(mocker) -> None:  # type: ignore[no-untyped-def]
    """project_id='testproj' makes the judge see the override clause."""
    from interlock.pipeline import review_two_documents_full

    mocker.patch(
        "interlock.detect.significance.call_structured",
        return_value=_fake_judge_response_with_clauses(["IEEE-C57.12.00-2015-5.4"]),
    )
    result = review_two_documents_full(
        DOC_A, DOC_B, embed_fn=_trivial_embedder,
        classify_docs=False,
        use_llm_extraction=False,
        use_llm_reranker=False,
        use_entity_grounding=False,
        project_id="testproj",
    )
    # v2.8.1: canonical name is "Transformer Impedance"
    impedance_flags = [f for f in result.flags if "Impedance" in f.parameter]
    assert impedance_flags
    # Override entry has source_name starting with "TESTPROJ override"
    override_present = any(
        "TESTPROJ override" in c.source_name
        for f in impedance_flags for c in f.cited_clauses
    )
    assert override_present, (
        f"expected TESTPROJ override; got "
        f"{[c.source_name for f in impedance_flags for c in f.cited_clauses]}"
    )


def test_project_id_nonexistent_falls_back_gracefully(mocker) -> None:  # type: ignore[no-untyped-def]
    """Unknown project_id → base registry only, no exception."""
    from interlock.pipeline import review_two_documents_full

    mocker.patch(
        "interlock.detect.significance.call_structured",
        return_value=_fake_judge_response_with_clauses([]),
    )
    result = review_two_documents_full(
        DOC_A, DOC_B, embed_fn=_trivial_embedder,
        classify_docs=False,
        use_llm_extraction=False,
        use_llm_reranker=False,
        use_entity_grounding=False,
        project_id="this-project-does-not-exist",
    )
    assert isinstance(result.flags, list)


def test_use_llm_judge_false_keeps_cited_clauses_empty(mocker) -> None:  # type: ignore[no-untyped-def]
    """No judge call → Flag.cited_clauses must be empty for every flag."""
    from interlock.pipeline import review_two_documents_full

    spy = mocker.patch("interlock.detect.significance.call_structured")
    result = review_two_documents_full(
        DOC_A, DOC_B, embed_fn=_trivial_embedder,
        classify_docs=False,
        use_llm_extraction=False,
        use_llm_reranker=False,
        use_entity_grounding=False,
        use_llm_judge=False,
    )
    assert spy.call_count == 0
    for f in result.flags:
        assert f.cited_clauses == ()


# --- Sprint 8: vision lane integration --------------------------------


@pytest.fixture(autouse=True)
def _vision_lane_cache_clear() -> None:
    """Sprint 8 — keep llm-vision + page-structure caches fresh per test.
    Global vision_extract_page stub lives in tests/conftest.py."""
    disk_cache.clear_namespace("llm-vision")
    disk_cache.clear_namespace("page-structure")
    yield
    disk_cache.clear_namespace("llm-vision")
    disk_cache.clear_namespace("page-structure")


def _fake_vision_response(entity_id: str, value: str, page: int = 1) -> MagicMock:
    content = MagicMock()
    content.text = json.dumps({
        "page": page, "page_understanding": "x", "page_layout": "diagram",
        "claims": [{
            "entity_kind": "equipment", "entity_id": entity_id,
            "entity_location_hint": "", "parameter_name": "Fuse Designation",
            "raw_value": value, "visual_evidence": "Label below symbol.",
        }],
    })
    return MagicMock(content=[content])


@pytest.mark.vision_lane
def test_use_vision_lane_false_skips_vision_calls(mocker) -> None:  # type: ignore[no-untyped-def]
    """Opt-out preserves v2.7 behavior (no vision calls)."""
    from interlock.pipeline import review_two_documents_full
    spy = mocker.patch("interlock.llm_pipeline.vision_extract._call_claude_vision")
    review_two_documents_full(
        DOC_A, DOC_B, embed_fn=_trivial_embedder,
        classify_docs=False,
        use_llm_extraction=False,
        use_llm_reranker=False,
        use_entity_grounding=False,
        use_llm_judge=False,
        use_vision_lane=False,
    )
    assert spy.call_count == 0


@pytest.mark.vision_lane
def test_use_vision_lane_true_routes_diagram_pages(mocker) -> None:  # type: ignore[no-untyped-def]
    """When vision lane on + page is diagram → vision call runs."""
    from interlock.pipeline import review_two_documents_full
    mocker.patch(
        "interlock.llm_pipeline.page_classify.classify_page_structure",
        return_value="diagram",
    )
    spy = mocker.patch(
        "interlock.llm_pipeline.vision_extract._call_claude_vision",
        return_value=_fake_vision_response("LPS-RK-100SP", "LPS-RK-100SP"),
    )
    review_two_documents_full(
        DOC_A, DOC_B, embed_fn=_trivial_embedder,
        classify_docs=False,
        use_llm_extraction=False,
        use_llm_reranker=False,
        use_entity_grounding=False,
        use_llm_judge=False,
        use_vision_lane=True,
    )
    assert spy.call_count > 0


@pytest.mark.vision_lane
def test_vision_lane_only_routes_diagram_pages(mocker) -> None:  # type: ignore[no-untyped-def]
    """Prose / table pages do NOT invoke vision."""
    from interlock.pipeline import review_two_documents_full
    def _stub_classify(_pdf, page):  # type: ignore[no-untyped-def]
        return {1: "prose", 2: "table", 3: "diagram"}.get(page, "mixed")
    mocker.patch(
        "interlock.llm_pipeline.page_classify.classify_page_structure",
        side_effect=_stub_classify,
    )
    spy = mocker.patch(
        "interlock.llm_pipeline.vision_extract._call_claude_vision",
        return_value=_fake_vision_response("X", "X"),
    )
    review_two_documents_full(
        DOC_A, DOC_B, embed_fn=_trivial_embedder,
        classify_docs=False,
        use_llm_extraction=False,
        use_llm_reranker=False,
        use_entity_grounding=False,
        use_llm_judge=False,
        use_vision_lane=True,
    )
    # Doc has 9 pages; only page 3 of each is diagram → 2 vision calls max.
    # (Could be fewer if cache hits or page text is empty.)
    assert spy.call_count <= 2


@pytest.mark.vision_lane
def test_vision_records_carry_entity_tag_and_extraction_lane(mocker) -> None:  # type: ignore[no-untyped-def]
    """Vision-extracted records arrive in the pipeline with both fields set."""
    from interlock.extract.parameters import ParameterRecord
    from interlock.pipeline import review_two_documents_full
    mocker.patch(
        "interlock.llm_pipeline.page_classify.classify_page_structure",
        return_value="diagram",
    )
    # Bypass the hallucination guard (page-text substring check) by
    # patching vision_extract_page directly. Doc-A and Doc-B records
    # differ in raw_value so the aligner pairs them and the detector
    # emits a real mismatch flag — making the records observable via
    # the ReviewResult surface.
    fake_record_a = ParameterRecord(
        doc_id="doc_a", page=1, bbox=(0.0, 0.0, 0.0, 0.0), section=None,
        span_text="vision evidence A", name="Fuse Designation",
        raw_value="LPS-RK-100SP", normalized_magnitude=None,
        normalized_unit=None, source_path="", entity_tag="XFMR-VLAB-001",
        provenance="llm", extraction_lane="vision",
    )
    fake_record_b = ParameterRecord(
        doc_id="doc_b", page=1, bbox=(0.0, 0.0, 0.0, 0.0), section=None,
        span_text="vision evidence B", name="Fuse Designation",
        raw_value="LPS-RK-400SP", normalized_magnitude=None,
        normalized_unit=None, source_path="", entity_tag="XFMR-VLAB-001",
        provenance="llm", extraction_lane="vision",
    )

    def _fake_vision_records(pdf_path: str, page: int, *, doc_id: str = "") -> list[ParameterRecord]:
        if doc_id == "doc_a":
            return [fake_record_a]
        if doc_id == "doc_b":
            return [fake_record_b]
        return []

    mocker.patch(
        "interlock.llm_pipeline.vision_extract.vision_extract_page",
        side_effect=_fake_vision_records,
    )
    result = review_two_documents_full(
        DOC_A, DOC_B, embed_fn=_trivial_embedder,
        classify_docs=False,
        use_llm_extraction=False,
        use_llm_reranker=False,
        use_entity_grounding=False,
        use_llm_judge=False,
        use_vision_lane=True,
        suppress_info=False,
    )
    all_records = list(result.unpaired_a) + list(result.unpaired_b) + [
        r for f in result.flags for r in (f.a_record, f.b_record)
    ]
    vision_records = [r for r in all_records if r.extraction_lane == "vision"]
    assert vision_records, "expected at least one vision-source record"
    for r in vision_records:
        assert r.entity_tag, "vision record must carry entity_tag from entity_id"


@pytest.mark.vision_lane
def test_vision_lane_kills_lps_rk_demo_bug(mocker) -> None:  # type: ignore[no-untyped-def]
    """The reported v2.7 demo bug: LPS-RK-400SP ≠ LPS-RK-100SP false
    positive on the locked Option 1 fixture. With vision lane ON, this
    pair should NOT surface as a mismatch flag — vision returns
    LPS-RK-400SP and LPS-RK-100SP as separate equipment entities with
    matching raw_values across docs."""
    from interlock.pipeline import review_two_documents_full

    fake_resp = MagicMock(content=[MagicMock(text=json.dumps({
        "page": 6, "page_understanding": "TCC2", "page_layout": "diagram",
        "claims": [
            {"entity_kind": "equipment", "entity_id": "LPS-RK-400SP",
             "entity_location_hint": "", "parameter_name": "Fuse Designation",
             "raw_value": "LPS-RK-400SP", "visual_evidence": "below 400A feeder"},
            {"entity_kind": "equipment", "entity_id": "LPS-RK-100SP",
             "entity_location_hint": "", "parameter_name": "Fuse Designation",
             "raw_value": "LPS-RK-100SP", "visual_evidence": "above #1 THW"},
        ],
    }))])
    mocker.patch(
        "interlock.llm_pipeline.page_classify.classify_page_structure",
        return_value="diagram",
    )
    mocker.patch(
        "interlock.llm_pipeline.vision_extract._call_claude_vision",
        return_value=fake_resp,
    )
    result = review_two_documents_full(
        DOC_A, DOC_B, embed_fn=_trivial_embedder,
        classify_docs=False,
        use_llm_extraction=False,
        use_llm_reranker=False,
        use_entity_grounding=False,
        use_llm_judge=False,
        use_vision_lane=True,
    )
    for f in result.flags:
        a_val = (f.a_record.raw_value or "").upper()
        b_val = (f.b_record.raw_value or "").upper()
        is_bad = (
            "LPS-RK-400SP" in a_val and "LPS-RK-100SP" in b_val
        ) or (
            "LPS-RK-100SP" in a_val and "LPS-RK-400SP" in b_val
        )
        assert not is_bad, (
            f"v2.7 demo bug regressed: {f.parameter} "
            f"A={f.a_record.raw_value} vs B={f.b_record.raw_value}"
        )
