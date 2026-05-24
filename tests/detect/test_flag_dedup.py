"""v2.8.6 — flag-level dedup tests."""

from __future__ import annotations

from interlock.detect.flag_dedup import dedup_flags_by_b_record
from interlock.detect.mismatch import Flag
from interlock.extract.parameters import ParameterRecord


def _rec(doc: str = "doc_a", page: int = 1, raw: str = "5.75 %") -> ParameterRecord:
    return ParameterRecord(
        doc_id=doc, page=page,
        bbox=(0.0, 0.0, 0.0, 0.0), section=None,
        span_text=raw, name="Transformer Impedance", raw_value=raw,
        normalized_magnitude=5.75 if "5.75" in raw else 2.0,
        normalized_unit="percent",
    )


def _flag(
    a_record: ParameterRecord,
    b_record: ParameterRecord,
    parameter: str = "Transformer Impedance",
    confidence: float = 0.9,
    deviation_pct: float = 65.0,
) -> Flag:
    return Flag(
        parameter=parameter,
        authoritative_doc_id="doc_a",
        deviating_doc_id="doc_b",
        a_record=a_record,
        b_record=b_record,
        confidence=confidence,
        rationale="test",
        authority_rule="test",
        severity="critical",
        deviation_pct=deviation_pct,
        attribute_family="impedance_pct",
        pairing_confidence=0.9,
    )


def test_dedup_collapses_flags_sharing_same_b_record() -> None:
    """The exact field-trip shape: N Doc-A pages each paired with the
    SAME Doc-B record (one anomaly in B fanning out across A's pages)
    → keep ONE flag, the highest-confidence."""
    b_rec = _rec(doc="doc_b", page=2, raw="2 %")
    a_p3 = _rec(doc="doc_a", page=3, raw="5.75 %")
    a_p6 = _rec(doc="doc_a", page=6, raw="5.75 %")
    a_p8 = _rec(doc="doc_a", page=8, raw="5.75 %")
    flags = [
        _flag(a_p3, b_rec, confidence=0.95),
        _flag(a_p6, b_rec, confidence=0.92),
        _flag(a_p8, b_rec, confidence=0.94),
    ]
    out = dedup_flags_by_b_record(flags)
    assert len(out) == 1
    # Highest confidence wins (0.95, A p3).
    assert out[0].confidence == 0.95
    assert out[0].a_record.page == 3


def test_dedup_keeps_flags_with_different_b_records() -> None:
    """Two separate Doc-B anomalies must both survive — even if their
    values look similar — because they describe distinct records."""
    b1 = _rec(doc="doc_b", page=2, raw="2 %")
    b2 = _rec(doc="doc_b", page=3, raw="2 %")
    a = _rec(doc="doc_a", page=3, raw="5.75 %")
    flags = [_flag(a, b1), _flag(a, b2)]
    out = dedup_flags_by_b_record(flags)
    assert len(out) == 2


def test_dedup_keeps_flags_with_different_parameters() -> None:
    """Same B record but flagged under two different parameter names
    (rare; happens when one cell contains both a value and a marker
    that emit as different params). Don't merge across parameters."""
    b = _rec(doc="doc_b", page=2)
    a = _rec(doc="doc_a", page=3)
    f1 = _flag(a, b, parameter="Transformer Impedance")
    f2 = _flag(a, b, parameter="Some Other Param")
    out = dedup_flags_by_b_record([f1, f2])
    assert len(out) == 2


def test_dedup_tiebreaker_closer_page_distance_wins() -> None:
    """When confidences tie, prefer the smaller cross-page distance —
    same-page pairings are more likely the true correspondence."""
    b = _rec(doc="doc_b", page=3, raw="2 %")
    a_p3 = _rec(doc="doc_a", page=3, raw="5.75 %")
    a_p7 = _rec(doc="doc_a", page=7, raw="5.75 %")
    flags = [
        _flag(a_p7, b, confidence=0.9),
        _flag(a_p3, b, confidence=0.9),  # zero cross-page distance
    ]
    out = dedup_flags_by_b_record(flags)
    assert len(out) == 1
    assert out[0].a_record.page == 3


def test_dedup_single_flag_passthrough() -> None:
    b = _rec(doc="doc_b")
    a = _rec(doc="doc_a")
    out = dedup_flags_by_b_record([_flag(a, b)])
    assert len(out) == 1


def test_dedup_empty_input_returns_empty() -> None:
    assert dedup_flags_by_b_record([]) == []
