"""Sprint 5a — significance judge standards-RAG integration tests."""

from __future__ import annotations

import pytest

from interlock.cache import disk as disk_cache
from interlock.detect.mismatch import Flag
from interlock.extract.parameters import ParameterRecord


def _record(name: str = "%Z", raw: str = "5.75 %") -> ParameterRecord:
    return ParameterRecord(
        doc_id="d", page=1, bbox=(0, 0, 100, 10), section=None,
        span_text=raw, name=name, raw_value=raw,
        normalized_magnitude=0.0575, normalized_unit="dimensionless",
    )


def _flag(family: str = "impedance_pct") -> Flag:
    return Flag(
        parameter="%Z",
        a_record=_record(), b_record=_record(raw="5.20 %"),
        authoritative_doc_id="d", deviating_doc_id="d",
        confidence=1.0, rationale="test", authority_rule="MVP",
        severity="major", deviation_pct=10.0,
        attribute_family=family,
    )


@pytest.fixture(autouse=True)
def _clear_judge_cache() -> None:
    disk_cache.clear_namespace("llm-significance")
    yield
    disk_cache.clear_namespace("llm-significance")


def test_judge_prompt_includes_applicable_standards_when_matches(mocker, monkeypatch, tmp_path) -> None:  # type: ignore[no-untyped-def]
    """Judge user block contains 'Applicable standards' section when
    the registry has matching clauses for the flag's family."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    from interlock.detect.significance import judge
    from interlock.llm_pipeline import standards as std

    p = tmp_path / "clauses.yaml"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("""\
clauses:
  - clause_id: TEST-IMPZ
    edition_year: 2020
    source_name: Test impedance standard
    applicable_families: [impedance_pct]
    summary: Test summary
""", encoding="utf-8")
    monkeypatch.setattr(std, "_CLAUSES_PATH", p)

    captured: dict[str, list] = {}

    def _fake_call_structured(*, response_model, system_blocks, user_blocks, model):  # type: ignore[no-untyped-def]
        captured["user_blocks"] = user_blocks
        return (
            response_model(
                severity="major",
                within_typical_tolerance=False,
                engineering_explanation="Test explanation citing Test impedance standard.",
                downstream_effects=[],
                confidence=0.9,
                cited_clause_ids=["TEST-IMPZ"],
            ),
            {"input": 0, "cache_read": 0, "cache_creation": 0, "output": 0},
        )

    mocker.patch("interlock.detect.significance.call_structured", side_effect=_fake_call_structured)
    out = judge(_flag())
    user_text = "\n".join(b.text for b in captured["user_blocks"])
    assert "Applicable standards" in user_text
    assert "TEST-IMPZ" in user_text
    assert out.cited_clause_ids == ["TEST-IMPZ"]


def test_judge_prompt_omits_standards_section_when_empty(mocker, monkeypatch, tmp_path) -> None:  # type: ignore[no-untyped-def]
    """Empty registry → judge prompt has no 'Applicable standards' section."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    from interlock.detect.significance import judge
    from interlock.llm_pipeline import standards as std

    p = tmp_path / "missing.yaml"  # don't create it
    monkeypatch.setattr(std, "_CLAUSES_PATH", p)

    captured: dict[str, list] = {}

    def _fake_call_structured(*, response_model, system_blocks, user_blocks, model):  # type: ignore[no-untyped-def]
        captured["user_blocks"] = user_blocks
        return (
            response_model(
                severity="major",
                within_typical_tolerance=False,
                engineering_explanation="Test.",
                downstream_effects=[],
                confidence=0.9,
            ),
            {"input": 0, "cache_read": 0, "cache_creation": 0, "output": 0},
        )

    mocker.patch("interlock.detect.significance.call_structured", side_effect=_fake_call_structured)
    judge(_flag())
    user_text = "\n".join(b.text for b in captured["user_blocks"])
    assert "Applicable standards" not in user_text


def test_apply_judgment_resolves_clause_ids_to_citations(monkeypatch, tmp_path) -> None:  # type: ignore[no-untyped-def]
    """apply_judgment_to_flag should turn cited_clause_ids into ClauseCitation tuple."""
    from interlock.detect.significance import (
        SignificanceJudgment,
        apply_judgment_to_flag,
    )
    from interlock.llm_pipeline import standards as std

    p = tmp_path / "clauses.yaml"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("""\
clauses:
  - clause_id: TEST-IMPZ
    edition_year: 2020
    source_name: Test impedance standard
    applicable_families: [impedance_pct]
    summary: Test summary
""", encoding="utf-8")
    monkeypatch.setattr(std, "_CLAUSES_PATH", p)

    j = SignificanceJudgment(
        severity="major",
        within_typical_tolerance=False,
        engineering_explanation="Test.",
        downstream_effects=[],
        confidence=0.9,
        cited_clause_ids=["TEST-IMPZ"],
    )
    out = apply_judgment_to_flag(_flag(), j)
    assert len(out.cited_clauses) == 1
    assert out.cited_clauses[0].clause_id == "TEST-IMPZ"
    assert out.cited_clauses[0].source_name == "Test impedance standard"


def test_hallucinated_clause_id_filtered_silently(monkeypatch, tmp_path) -> None:  # type: ignore[no-untyped-def]
    """Clause ID not in registry → silently dropped from cited_clauses."""
    from interlock.detect.significance import (
        SignificanceJudgment,
        apply_judgment_to_flag,
    )
    from interlock.llm_pipeline import standards as std

    p = tmp_path / "clauses.yaml"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("""\
clauses:
  - clause_id: TEST-REAL
    edition_year: 2020
    source_name: Real
    applicable_families: [x]
    summary: real
""", encoding="utf-8")
    monkeypatch.setattr(std, "_CLAUSES_PATH", p)

    j = SignificanceJudgment(
        severity="major",
        within_typical_tolerance=False,
        engineering_explanation="Test.",
        downstream_effects=[],
        confidence=0.9,
        cited_clause_ids=["TEST-REAL", "HALLUCINATED-ID"],
    )
    out = apply_judgment_to_flag(_flag(), j)
    assert [c.clause_id for c in out.cited_clauses] == ["TEST-REAL"]


def test_apply_judgment_preserves_sprint_3_4_4_5_fields() -> None:
    """Sprint 3 provenance, Sprint 4 rerank_rationale, Phase 19
    pairing_confidence must survive judge rebuild."""
    from interlock.detect.significance import (
        SignificanceJudgment,
        apply_judgment_to_flag,
    )
    f = Flag(
        parameter="%Z",
        a_record=_record(), b_record=_record(raw="5.20 %"),
        authoritative_doc_id="d", deviating_doc_id="d",
        confidence=1.0, rationale="r", authority_rule="MVP",
        severity="major", deviation_pct=10.0,
        attribute_family="impedance_pct",
        pairing_confidence=0.6,
        provenance="rule_only",  # type: ignore[arg-type]
        rerank_rationale="ok",
    )
    j = SignificanceJudgment(
        severity="critical",
        within_typical_tolerance=False,
        engineering_explanation="explained",
        downstream_effects=["x"],
        confidence=0.95,
        cited_clause_ids=[],
    )
    out = apply_judgment_to_flag(f, j)
    assert out.provenance == "rule_only"
    assert out.rerank_rationale == "ok"
    assert out.pairing_confidence == 0.6
    assert out.severity == "critical"
    assert out.cited_clauses == ()


def test_judge_cache_key_includes_matched_clause_ids(mocker, monkeypatch, tmp_path) -> None:  # type: ignore[no-untyped-def]
    """Growing the registry should invalidate the cache for affected
    flags. Cache key must depend on matched clause IDs, not just flag id."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    from interlock.detect.significance import judge
    from interlock.llm_pipeline import standards as std

    p = tmp_path / "clauses.yaml"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("""\
clauses:
  - clause_id: A
    edition_year: 2020
    source_name: A
    applicable_families: [impedance_pct]
    summary: a
""", encoding="utf-8")
    monkeypatch.setattr(std, "_CLAUSES_PATH", p)

    call_count = {"n": 0}

    def _fake_call_structured(*, response_model, system_blocks, user_blocks, model):  # type: ignore[no-untyped-def]
        call_count["n"] += 1
        return (
            response_model(
                severity="major",
                within_typical_tolerance=False,
                engineering_explanation="x",
                downstream_effects=[],
                confidence=0.9,
                cited_clause_ids=[],
            ),
            {"input": 0, "cache_read": 0, "cache_creation": 0, "output": 0},
        )

    mocker.patch("interlock.detect.significance.call_structured", side_effect=_fake_call_structured)

    judge(_flag())
    assert call_count["n"] == 1

    # Grow registry — same flag should re-call (different matched clauses).
    p.write_text("""\
clauses:
  - clause_id: A
    edition_year: 2020
    source_name: A
    applicable_families: [impedance_pct]
    summary: a
  - clause_id: B
    edition_year: 2021
    source_name: B
    applicable_families: [impedance_pct]
    summary: b
""", encoding="utf-8")
    judge(_flag())
    assert call_count["n"] == 2, (
        "Cache must invalidate when matched clause IDs change; "
        f"call count stayed at {call_count['n']}"
    )
