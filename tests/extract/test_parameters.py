from interlock.extract.parameters import ParameterRecord, extract_parameters
from interlock.ingest.text import Span


def _s(text: str, page: int = 1, y: float = 0) -> Span:
    return Span(doc_id="d", page=page, bbox=(0, y, 100, y + 10), text=text)


def test_extract_impedance_percent() -> None:
    spans = [_s("5.75%Z, liquid")]
    records = extract_parameters(spans)
    # v2.8.1: canonicalize_param_name maps "%Z" → "Transformer Impedance"
    assert any(r.name == "Transformer Impedance" and "5.75" in r.raw_value for r in records)


def test_extract_transformer_rating_kva() -> None:
    spans = [_s("1000KVA XFMR")]
    records = extract_parameters(spans)
    target = [r for r in records if r.name == "Transformer Rating"]
    assert target
    assert target[0].normalized_magnitude is not None
    # 1000 kVA == 1_000_000 VA in base units
    assert abs(target[0].normalized_magnitude - 1_000_000) < 1


def test_extract_transformer_rating_mva_equivalent_to_kva() -> None:
    spans = [_s("0.15 MVA XFMR")]
    records = extract_parameters(spans)
    target = [r for r in records if r.name == "Transformer Rating"]
    assert target
    # 0.15 MVA == 150 kVA == 150_000 VA
    assert abs(target[0].normalized_magnitude - 150_000) < 1


def test_extract_fault_current() -> None:
    spans = [_s("Fault X1 20,000A RMS Sym")]
    records = extract_parameters(spans)
    target = [r for r in records if r.name == "Fault Current"]
    assert target
    assert abs(target[0].normalized_magnitude - 20_000) < 1


def test_extract_records_carry_citation_tuple() -> None:
    spans = [_s("5.75%Z, liquid", page=3, y=120)]
    records = extract_parameters(spans)
    r = records[0]
    assert isinstance(r, ParameterRecord)
    assert r.doc_id == "d"
    assert r.page == 3
    assert r.bbox == (0, 120, 100, 130)
    assert r.span_text == "5.75%Z, liquid"


def test_extract_ignores_non_parameter_text() -> None:
    spans = [_s("Conclusions"), _s("Notes:")]
    records = extract_parameters(spans)
    assert records == []


def test_extract_handles_ifla() -> None:
    spans = [_s("IFLA=42A")]
    records = extract_parameters(spans)
    # v2.8.1: canonicalize_param_name maps "IFLA" → "Full Load Amperes"
    target = [r for r in records if r.name == "Full Load Amperes"]
    assert target
    assert abs(target[0].normalized_magnitude - 42) < 1


def test_extract_fuse_designation_as_string_value() -> None:
    spans = [_s("LPN-RK-500SP")]
    records = extract_parameters(spans)
    target = [r for r in records if r.name == "Fuse Designation"]
    assert target
    assert target[0].raw_value == "LPN-RK-500SP"
    # No numeric normalization for part numbers.
    assert target[0].normalized_magnitude is None


# ---------- Entity-tag capture (Device ID at start of line) ----------


def test_entity_tag_captures_circled_digit() -> None:
    """Circled digits (①-⑳) at the start of a table row are normalised
    to ASCII so a Device ID painted as ⑥ in Doc A pairs with 6 in Doc B."""
    spans = [_s("⑥ KRP-C-1600SP Class L Fuse")]
    records = extract_parameters(spans)
    target = [r for r in records if r.name == "Fuse Designation"]
    assert target
    assert target[0].entity_tag == "6"


def test_entity_tag_captures_numeric_row_prefix() -> None:
    spans = [_s("21 LPS-RK-100SP Class RK1 Fuse")]
    records = extract_parameters(spans)
    target = [r for r in records if r.name == "Fuse Designation"]
    assert target
    assert target[0].entity_tag == "21"


def test_entity_tag_captures_numbered_list_prefix() -> None:
    spans = [_s("3. KRP-C-1200SP")]
    records = extract_parameters(spans)
    target = [r for r in records if r.name == "Fuse Designation"]
    assert target
    assert target[0].entity_tag == "3"


def test_entity_tag_strips_table_pipe_separator() -> None:
    """OCR-derived table rows look like ``⑥ | KRP-C-1600SP | Class L``
    after v2 prompt. The pipe separator must not block the tag detector."""
    spans = [_s("⑥ | KRP-C-1600SP | Class L Fuse")]
    records = extract_parameters(spans)
    target = [r for r in records if r.name == "Fuse Designation"]
    assert target
    assert target[0].entity_tag == "6"


def test_entity_tag_empty_when_no_leading_marker() -> None:
    spans = [_s("KRP-C-1600SP")]
    records = extract_parameters(spans)
    target = [r for r in records if r.name == "Fuse Designation"]
    assert target
    assert target[0].entity_tag == ""


def test_entity_tag_does_not_misfire_on_value_starting_with_digit() -> None:
    """``5.75%Z, liquid`` starts with a digit. That digit is the value,
    not a Device ID. The leading-marker regex requires whitespace after
    the marker, so this must NOT capture ``5`` as the tag."""
    spans = [_s("5.75%Z, liquid")]
    records = extract_parameters(spans)
    # v2.8.1: %Z canonicalized to Transformer Impedance
    target = [r for r in records if r.name == "Transformer Impedance"]
    assert target
    assert target[0].entity_tag == ""


def test_entity_tag_inherited_by_all_records_from_one_span() -> None:
    """A single tagged span line emitting multiple parameters
    (rare but possible) — all records inherit the row's tag."""
    spans = [_s("⑩ 1000KVA XFMR Inrush 5.75%Z")]
    records = extract_parameters(spans)
    assert records
    assert all(r.entity_tag == "10" for r in records)


def test_multiline_kva_xfmr_captured_by_secondary_pass() -> None:
    """v2.8.7 — doc_a p7 TCC3 table renders "1000KVA" and "XFMR" on
    separate visual lines (different y-rows of the Description column).
    Per-span regex misses these because PyMuPDF's line aggregation
    keeps them as separate spans (y-gap exceeds aggregate threshold).
    The secondary per-page concatenation pass joins them with \\n and
    re-runs the regex (which accepts \\s+ including newlines) to
    recover the multi-line match. Required for TP-3 to surface in
    LLM-on FE mode."""
    spans = [
        _s("1", page=7, y=100),
        _s("1000KVA", page=7, y=120),  # separate y → separate span
        _s("XFMR", page=7, y=140),
        _s("5.75%Z, liquid", page=7, y=160),
    ]
    records = extract_parameters(spans)
    # Per-span: only "5.75%Z" matches via Transformer Impedance pattern.
    # Secondary pass: concatenates the page text "1\n1000KVA\nXFMR\n
    # 5.75%Z..." and re-runs the KVA-XFMR pattern, recovering
    # "1000KVA XFMR" across the newline.
    transformer_rating = [
        r for r in records if r.name == "Transformer Rating"
    ]
    assert transformer_rating, (
        f"expected Transformer Rating record from multi-line aggregation; "
        f"got {[(r.name, r.raw_value) for r in records]}"
    )
    assert any("1000" in r.raw_value for r in transformer_rating)


def test_multiline_pass_does_not_duplicate_existing_records() -> None:
    """v2.8.7 — when per-span regex already extracted a match, the
    secondary pass must NOT emit a duplicate. Dedup key:
    (page, canonical_name, raw_value)."""
    spans = [_s("5.75%Z, liquid", page=3)]
    records = extract_parameters(spans)
    impedance = [r for r in records if r.name == "Transformer Impedance"]
    # One record from per-span; secondary pass sees the same regex
    # match and skips because the key already exists.
    assert len(impedance) == 1


def test_multiline_pass_empty_when_no_spans() -> None:
    assert extract_parameters([]) == []
