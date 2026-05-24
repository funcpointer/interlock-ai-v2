"""v2.8.4 — checklist-gap detector tests."""

from __future__ import annotations

from interlock.detect.checklist import detect_checklist_gaps
from interlock.extract.parameters import ParameterRecord


def _rec(
    doc_id: str = "doc_a",
    name: str = "Fuse Designation",
    raw: str = "LPN-RK-500SP",
    page: int = 7,
) -> ParameterRecord:
    return ParameterRecord(
        doc_id=doc_id, page=page,
        bbox=(0.0, 0.0, 0.0, 0.0), section=None,
        span_text=raw, name=name, raw_value=raw,
        normalized_magnitude=None, normalized_unit=None,
    )


def test_gap_emitted_when_value_missing_from_doc_b() -> None:
    """Gold FN-1 shape — LPN-RK-500SP in Doc A p7 unpaired, not in any
    Doc B record → emit one checklist-gap flag."""
    unpaired_a = [_rec()]
    all_b = [_rec(doc_id="doc_b", raw="LPS-RK-225SP")]
    flags = detect_checklist_gaps(unpaired_a, all_b, "doc_a", "doc_b")
    assert len(flags) == 1
    assert flags[0].parameter == "Fuse Designation"
    assert flags[0].authoritative_doc_id == "doc_a"
    assert flags[0].deviating_doc_id == "doc_b"
    assert flags[0].authority_rule == "checklist_gap"
    assert flags[0].a_record.raw_value == "LPN-RK-500SP"
    assert flags[0].b_record.raw_value == "(removed)"
    assert flags[0].confidence >= 0.4  # gold FN-1 min_confidence


def test_no_gap_when_value_present_anywhere_in_doc_b() -> None:
    """LPN-RK-500SP is unpaired in A but DOES appear in B (just paired
    weirdly or with a different name). Don't emit a gap — the value
    isn't missing, the alignment is just lossy."""
    unpaired_a = [_rec()]
    all_b = [_rec(doc_id="doc_b", page=3, raw="LPN-RK-500SP")]
    flags = detect_checklist_gaps(unpaired_a, all_b, "doc_a", "doc_b")
    assert flags == []


def test_gap_scope_limited_to_string_valued_params() -> None:
    """Numeric params (Transformer Impedance, Fault Current, etc.) are
    out of scope. A missing impedance isn't a checklist gap — it's an
    extractor miss."""
    unpaired_a = [
        ParameterRecord(
            doc_id="doc_a", page=3,
            bbox=(0.0, 0.0, 0.0, 0.0), section=None,
            span_text="5.75 %", name="Transformer Impedance",
            raw_value="5.75 %",
            normalized_magnitude=5.75, normalized_unit="percent",
        ),
    ]
    all_b: list[ParameterRecord] = []
    flags = detect_checklist_gaps(unpaired_a, all_b, "doc_a", "doc_b")
    assert flags == []


def test_value_match_is_case_insensitive_and_normalized() -> None:
    """Different casings / whitespace shouldn't fool the gap detector
    into a false positive."""
    unpaired_a = [_rec(raw="LPN-RK-500SP")]
    all_b = [_rec(doc_id="doc_b", raw=" lpn-rk-500sp ")]
    flags = detect_checklist_gaps(unpaired_a, all_b, "doc_a", "doc_b")
    assert flags == []


def test_empty_unpaired_returns_empty() -> None:
    assert detect_checklist_gaps([], [], "doc_a", "doc_b") == []


def test_multiple_gaps_each_emit_one_flag() -> None:
    unpaired_a = [
        _rec(raw="LPN-RK-500SP"),
        _rec(raw="JCN 80E", page=5),
    ]
    all_b = [_rec(doc_id="doc_b", raw="LPS-RK-225SP")]
    flags = detect_checklist_gaps(unpaired_a, all_b, "doc_a", "doc_b")
    assert {f.a_record.raw_value for f in flags} == {"LPN-RK-500SP", "JCN 80E"}
