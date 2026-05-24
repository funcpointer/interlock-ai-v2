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
    the SAME page, vision wins. v2.8.8 — same-page only dedup."""
    r1 = _rec(page=7, extraction_lane="llm_text", entity_tag="150 KVA XFMR")
    r2 = _rec(page=7, extraction_lane="vision", entity_tag="XFMR-DRY-150")
    out = dedup_same_doc_records([r1, r2])
    lanes = [r.extraction_lane for r in out]
    assert lanes == ["vision"], (
        f"expected only vision record kept; got lanes={lanes}"
    )


def test_dedup_keeps_llm_text_over_regex() -> None:
    """v2.8.8 — same-page only dedup."""
    r1 = _rec(page=7, extraction_lane="regex", entity_tag="")
    r2 = _rec(page=7, extraction_lane="llm_text", entity_tag="150 KVA XFMR")
    out = dedup_same_doc_records([r1, r2])
    assert [r.extraction_lane for r in out] == ["llm_text"]


def test_dedup_keeps_vision_over_both_others() -> None:
    """Full 3-lane collision on the SAME page — vision wins.
    v2.8.8 — same-page only dedup."""
    r_regex = _rec(page=8, extraction_lane="regex")
    r_llm = _rec(page=8, extraction_lane="llm_text")
    r_vision = _rec(page=8, extraction_lane="vision")
    out = dedup_same_doc_records([r_regex, r_llm, r_vision])
    assert len(out) == 1
    assert out[0].extraction_lane == "vision"


def test_dedup_does_not_merge_across_pages_v2_8_8() -> None:
    """v2.8.8 — same-value records on DIFFERENT pages are NOT duplicates.
    Coordination-study docs reference '1000 kVA' transformer rating from
    multiple TCC tables (p3 TCC1, p5 TCC2, p7 TCC3). These are physically
    the same transformer but each table-row record is a distinct
    positional reference. Previous ±2 page-window was conflating them
    cross-lane and dropping the regex-extracted row-marker-tagged
    records (TP-3 blocker)."""
    r_regex_p7 = _rec(
        page=7, mag=1_000_000.0, unit="kilovolt_ampere",
        raw="1000 kVA", extraction_lane="regex", entity_tag="1",
    )
    r_vision_p6 = _rec(
        page=6, mag=1_000_000.0, unit="kilovolt_ampere",
        raw="1000KVA", extraction_lane="vision", entity_tag="1000KVA",
    )
    out = dedup_same_doc_records([r_regex_p7, r_vision_p6])
    assert len(out) == 2, "different pages must NOT dedup"


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


def test_dedup_collapses_whitespace_punct_differences() -> None:
    """v2.8.4 — '100 kVA' (regex normalized) and '100KVA' (LLM raw) must
    dedup. Same value, different formatting; cross-lane merge previously
    failed when Pint refused to parse the no-space form.

    v2.8.6 — when regex tag is a row marker (digit-only), regex now WINS
    over llm_text because row-anchor is stronger than descriptor-tag.
    Earlier this case had llm_text winning. The dedup itself still
    happens; only the survivor changes."""
    r_regex = _rec(
        page=7, name="Transformer Rating", raw="100 kVA",
        mag=100_000.0, unit="kilovolt_ampere", extraction_lane="regex",
        entity_tag="1",
    )
    r_llm = _rec(
        page=7, name="Transformer Rating", raw="100KVA",
        mag=None, unit=None, extraction_lane="llm_text",
        entity_tag="100KVA XFMR",
    )
    out = dedup_same_doc_records([r_regex, r_llm])
    assert len(out) == 1
    assert out[0].extraction_lane == "regex", (
        "v2.8.6 row-marker promotion: regex with tag='1' beats llm_text"
    )


def test_dedup_numeric_fallback_when_only_one_side_pint_parsed() -> None:
    """v2.8.4 — same numeric value but only one side normalized.
    First-numeric-token fallback should bridge them."""
    r1 = _rec(
        page=3, name="Transformer Impedance", raw="5.75 %",
        mag=5.75, unit="percent", extraction_lane="regex",
    )
    r2 = _rec(
        page=3, name="Transformer Impedance", raw="5.75%Z, liquid",
        mag=None, unit=None, extraction_lane="vision",
        entity_tag="1000KVA XFMR",
    )
    out = dedup_same_doc_records([r1, r2])
    assert len(out) == 1
    assert out[0].extraction_lane == "vision"


def test_dedup_row_marker_regex_beats_descriptor_llm_text() -> None:
    """v2.8.6 — regex record with digit-only entity_tag (row marker like
    '1' from a TCC table) is a STRONGER positional anchor than the
    value-encoding entity_tag the LLM emits ('1000KVA XFMR'). When both
    extract the same value on the same page, keep the regex one so
    cross-doc pairing has a stable handle the mutated docs share."""
    r_regex_rowmarker = _rec(
        page=7, name="Transformer Rating", raw="1000 kVA",
        mag=1_000_000.0, unit="kilovolt_ampere", extraction_lane="regex",
        entity_tag="1",  # row marker
    )
    r_llm_descriptor = _rec(
        page=7, name="Transformer Rating", raw="1000 KVA",
        mag=1_000_000.0, unit="kilovolt_ampere", extraction_lane="llm_text",
        entity_tag="1000KVA XFMR",  # value-encoding tag
    )
    out = dedup_same_doc_records([r_regex_rowmarker, r_llm_descriptor])
    assert len(out) == 1
    assert out[0].extraction_lane == "regex"
    assert out[0].entity_tag == "1"


def test_dedup_vision_still_wins_over_row_marker_regex_on_diagrams() -> None:
    """Row-marker bump must NOT supersede vision priority. Vision returns
    (entity, value) tuples extracted from page image; trust those on
    diagrams over even row-anchored regex."""
    r_vision = _rec(
        page=8, name="Transformer Rating", raw="1000kVA",
        mag=1_000_000.0, unit="kilovolt_ampere", extraction_lane="vision",
        entity_tag="1000kVA",
    )
    r_regex_rowmarker = _rec(
        page=8, name="Transformer Rating", raw="1000 kVA",
        mag=1_000_000.0, unit="kilovolt_ampere", extraction_lane="regex",
        entity_tag="1",
    )
    out = dedup_same_doc_records([r_vision, r_regex_rowmarker])
    assert len(out) == 1
    assert out[0].extraction_lane == "vision"


def test_dedup_regex_without_row_marker_loses_to_llm_text() -> None:
    """Regex with non-digit tag (or empty) stays at base regex priority."""
    r_regex_no_marker = _rec(
        page=3, name="Transformer Impedance", raw="5.75 %",
        mag=5.75, unit="percent", extraction_lane="regex",
        entity_tag="",  # no row marker
    )
    r_llm = _rec(
        page=3, name="Transformer Impedance", raw="5.75%Z",
        mag=None, unit=None, extraction_lane="llm_text",
        entity_tag="1000KVA XFMR",
    )
    out = dedup_same_doc_records([r_regex_no_marker, r_llm])
    assert len(out) == 1
    assert out[0].extraction_lane == "llm_text"


def test_dedup_numeric_fallback_does_not_merge_different_numbers() -> None:
    """Numeric fallback must still distinguish 5.75 from 0.575 even
    when one side lacks Pint magnitude — those are the gold TP-1
    distinct values, not duplicates."""
    r1 = _rec(
        page=3, name="Transformer Impedance", raw="5.75 %",
        mag=5.75, unit="percent", extraction_lane="regex",
    )
    r2 = _rec(
        page=3, name="Transformer Impedance", raw="0.575%Z, liquid",
        mag=None, unit=None, extraction_lane="vision",
    )
    out = dedup_same_doc_records([r1, r2])
    assert len(out) == 2, "different magnitudes must NOT merge"
