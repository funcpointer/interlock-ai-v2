"""Sprint 3 — adjudicator unit tests.

Pure function over a Flag list. No I/O, no LLM call, no alignment
state. Just label derivation from a_record.provenance + b_record.provenance.
"""

from __future__ import annotations

from dataclasses import replace

from interlock.detect.mismatch import Flag
from interlock.extract.parameters import ParameterRecord


def _record(provenance: str = "regex") -> ParameterRecord:
    return ParameterRecord(
        doc_id="d", page=1, bbox=(0, 0, 100, 10), section=None,
        span_text="5.75%Z", name="%Z", raw_value="5.75 %",
        normalized_magnitude=0.0575, normalized_unit="dimensionless",
        provenance=provenance,  # type: ignore[arg-type]
    )


def _flag(a_prov: str, b_prov: str) -> Flag:
    return Flag(
        parameter="%Z",
        a_record=_record(provenance=a_prov),
        b_record=_record(provenance=b_prov),
        authoritative_doc_id="d", deviating_doc_id="d",
        confidence=1.0,
        rationale="test",
        authority_rule="MVP",
        severity="major",
        deviation_pct=10.0,
        attribute_family="impedance_pct",
    )


def test_classify_provenance_both_regex_is_rule_only() -> None:
    from interlock.adjudicator import _classify_provenance
    assert _classify_provenance("regex", "regex") == "rule_only"


def test_classify_provenance_both_llm_is_llm_only() -> None:
    from interlock.adjudicator import _classify_provenance
    assert _classify_provenance("llm", "llm") == "llm_only"


def test_classify_provenance_regex_plus_llm_is_mixed_track() -> None:
    from interlock.adjudicator import _classify_provenance
    assert _classify_provenance("regex", "llm") == "mixed_track"
    assert _classify_provenance("llm", "regex") == "mixed_track"


def test_classify_provenance_none_is_unknown() -> None:
    from interlock.adjudicator import _classify_provenance
    assert _classify_provenance(None, "regex") == "unknown"
    assert _classify_provenance("regex", None) == "unknown"
    assert _classify_provenance(None, None) == "unknown"


def test_adjudicate_flags_annotates_rule_only_flag() -> None:
    from interlock.adjudicator import adjudicate_flags
    flags = [_flag("regex", "regex")]
    out = adjudicate_flags(flags)
    assert len(out) == 1
    assert out[0].provenance == "rule_only"


def test_adjudicate_flags_annotates_llm_only_flag() -> None:
    from interlock.adjudicator import adjudicate_flags
    out = adjudicate_flags([_flag("llm", "llm")])
    assert out[0].provenance == "llm_only"


def test_adjudicate_flags_annotates_mixed_track_flag() -> None:
    from interlock.adjudicator import adjudicate_flags
    out = adjudicate_flags([_flag("regex", "llm")])
    assert out[0].provenance == "mixed_track"


def test_adjudicate_flags_preserves_flag_order() -> None:
    from interlock.adjudicator import adjudicate_flags
    flags = [
        replace(_flag("regex", "regex"), parameter="A"),
        replace(_flag("llm", "llm"), parameter="B"),
        replace(_flag("regex", "llm"), parameter="C"),
    ]
    out = adjudicate_flags(flags)
    assert [f.parameter for f in out] == ["A", "B", "C"]
    assert [f.provenance for f in out] == ["rule_only", "llm_only", "mixed_track"]


def test_adjudicate_flags_preserves_other_fields() -> None:
    """All other Flag fields must pass through unchanged."""
    from interlock.adjudicator import adjudicate_flags
    f = _flag("regex", "llm")
    out = adjudicate_flags([f])
    assert out[0].parameter == f.parameter
    assert out[0].severity == f.severity
    assert out[0].confidence == f.confidence
    assert out[0].deviation_pct == f.deviation_pct
    assert out[0].rationale == f.rationale
    assert out[0].a_record is f.a_record  # same record object
    assert out[0].b_record is f.b_record


def test_adjudicate_flags_empty_input_returns_empty() -> None:
    from interlock.adjudicator import adjudicate_flags
    assert adjudicate_flags([]) == []
