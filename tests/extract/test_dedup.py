"""v2.8.1 — cross-lane same-doc dedup tests."""

from __future__ import annotations

from interlock.extract.dedup import dedup_same_doc_records
from interlock.extract.parameters import ParameterRecord


def _rec(
    doc_id: str = "doc_a",
    page: int = 1,
    name: str = "Transformer Impedance",
    raw: str = "5.75 %",
    mag: float | None = 5.75,
    unit: str | None = "percent",
    entity_tag: str = "",
    extraction_lane: str = "regex",
) -> ParameterRecord:
    return ParameterRecord(
        doc_id=doc_id, page=page,
        bbox=(0.0, 0.0, 0.0, 0.0), section=None,
        span_text=raw, name=name, raw_value=raw,
        normalized_magnitude=mag, normalized_unit=unit,
        entity_tag=entity_tag,
        provenance="llm" if extraction_lane != "regex" else "regex",
        extraction_lane=extraction_lane,  # type: ignore[arg-type]
    )


def test_dedup_keeps_vision_over_llm_text() -> None:
    """When vision + llm_text record the same value in the same doc on
    nearby pages, vision wins."""
    r1 = _rec(page=7, extraction_lane="llm_text", entity_tag="150 KVA XFMR")
    r2 = _rec(page=8, extraction_lane="vision", entity_tag="XFMR-DRY-150")
    out = dedup_same_doc_records([r1, r2])
    lanes = [r.extraction_lane for r in out]
    assert lanes == ["vision"], (
        f"expected only vision record kept; got lanes={lanes}"
    )


def test_dedup_keeps_llm_text_over_regex() -> None:
    r1 = _rec(page=8, extraction_lane="regex", entity_tag="")
    r2 = _rec(page=7, extraction_lane="llm_text", entity_tag="150 KVA XFMR")
    out = dedup_same_doc_records([r1, r2])
    assert [r.extraction_lane for r in out] == ["llm_text"]


def test_dedup_keeps_vision_over_both_others() -> None:
    """Full 3-lane collision — vision wins."""
    r_regex = _rec(page=8, extraction_lane="regex")
    r_llm = _rec(page=7, extraction_lane="llm_text")
    r_vision = _rec(page=8, extraction_lane="vision")
    out = dedup_same_doc_records([r_regex, r_llm, r_vision])
    assert len(out) == 1
    assert out[0].extraction_lane == "vision"


def test_dedup_does_not_merge_across_documents() -> None:
    """Cross-doc records with identical values must NEVER be merged
    here — that's the aligner's job downstream."""
    r_a = _rec(doc_id="doc_a", extraction_lane="regex")
    r_b = _rec(doc_id="doc_b", extraction_lane="regex")
    out = dedup_same_doc_records([r_a, r_b])
    assert len(out) == 2
    assert {r.doc_id for r in out} == {"doc_a", "doc_b"}


def test_dedup_does_not_merge_different_parameters() -> None:
    r1 = _rec(name="Transformer Impedance", extraction_lane="regex")
    r2 = _rec(name="Full Load Amperes", extraction_lane="llm_text",
              mag=42.0, unit="ampere", raw="42 A")
    out = dedup_same_doc_records([r1, r2])
    assert len(out) == 2


def test_dedup_does_not_merge_different_magnitudes() -> None:
    """5.75% and 2.00% are NOT duplicates — they're the actual cross-doc
    anomaly we want to catch."""
    r1 = _rec(page=7, mag=5.75, extraction_lane="llm_text")
    r2 = _rec(page=8, mag=2.00, extraction_lane="regex", raw="2.00 %")
    out = dedup_same_doc_records([r1, r2])
    assert len(out) == 2


def test_dedup_respects_page_window() -> None:
    """Records on pages far apart are NOT merged even if values match —
    they might be separate readings of different equipment."""
    r1 = _rec(page=1, extraction_lane="regex")
    r2 = _rec(page=20, extraction_lane="vision")
    out = dedup_same_doc_records([r1, r2])
    assert len(out) == 2


def test_dedup_handles_string_values_no_magnitude() -> None:
    """Fuse Designation has string raw_value, no normalized_magnitude.
    Same string across lanes → dedup."""
    r1 = _rec(
        name="Fuse Designation", raw="LPS-RK-100SP", mag=None, unit=None,
        extraction_lane="regex",
    )
    r2 = _rec(
        name="Fuse Designation", raw="LPS-RK-100SP", mag=None, unit=None,
        extraction_lane="vision", entity_tag="LPS-RK-100SP",
    )
    out = dedup_same_doc_records([r1, r2])
    assert len(out) == 1
    assert out[0].extraction_lane == "vision"


def test_dedup_preserves_input_order_within_lane() -> None:
    """When nothing dedups, output order matches input order."""
    r1 = _rec(page=1, name="A", mag=1.0, raw="1 A", unit="ampere",
              extraction_lane="regex")
    r2 = _rec(page=2, name="B", mag=2.0, raw="2 A", unit="ampere",
              extraction_lane="regex")
    r3 = _rec(page=3, name="C", mag=3.0, raw="3 A", unit="ampere",
              extraction_lane="regex")
    out = dedup_same_doc_records([r1, r2, r3])
    assert [r.name for r in out] == ["A", "B", "C"]


def test_dedup_empty_input_returns_empty() -> None:
    assert dedup_same_doc_records([]) == []
