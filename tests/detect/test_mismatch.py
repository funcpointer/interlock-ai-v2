from interlock.align.exact import AlignedPair
from interlock.detect.mismatch import Flag, detect_flags
from interlock.extract.parameters import ParameterRecord


def _p(name: str, doc: str, raw: str, mag: float | None, page: int = 1, y: float = 0) -> ParameterRecord:
    return ParameterRecord(
        doc_id=doc, page=page, bbox=(0, y, 100, y + 10), section="sec",
        span_text=f"{name}: {raw}", name=name, raw_value=raw,
        normalized_magnitude=mag, normalized_unit="dim",
    )


def test_value_mismatch_emits_directional_flag() -> None:
    pair = AlignedPair(
        a=_p("%Z", "doc_a", "5.75 %", 0.0575),
        b=_p("%Z", "doc_b", "0.575 %", 0.00575),
        name_match_confidence=1.0,
        value_equivalent=False,
    )
    flags = detect_flags([pair])
    assert len(flags) == 1
    f = flags[0]
    assert isinstance(f, Flag)
    assert f.authoritative_doc_id == "doc_a"
    assert f.deviating_doc_id == "doc_b"
    assert f.confidence >= 0.6


def test_value_equivalent_pair_does_not_emit() -> None:
    pair = AlignedPair(
        a=_p("Voltage", "doc_a", "132 kV", 132_000),
        b=_p("Voltage", "doc_b", "132,000 V", 132_000),
        name_match_confidence=1.0,
        value_equivalent=True,
    )
    assert detect_flags([pair]) == []


def test_missing_magnitudes_do_not_emit() -> None:
    pair = AlignedPair(
        a=_p("Fuse", "doc_a", "KRP-C-1600SP", None),
        b=_p("Fuse", "doc_b", "KRP-C-1600SP", None),
        name_match_confidence=1.0,
        value_equivalent=True,
    )
    assert detect_flags([pair]) == []


def test_string_value_mismatch_emits_flag_via_value_equivalent_false() -> None:
    # Fuse designations differ but no numeric magnitude — should still flag
    # when value_equivalent is False.
    pair = AlignedPair(
        a=_p("Fuse", "doc_a", "KRP-C-1600SP", None),
        b=_p("Fuse", "doc_b", "KRP-C-1601SP", None),
        name_match_confidence=1.0,
        value_equivalent=False,
    )
    flags = detect_flags([pair])
    assert len(flags) == 1


def test_lower_match_confidence_lowers_flag_confidence() -> None:
    pair_high = AlignedPair(
        a=_p("Z", "doc_a", "1 V", 1.0),
        b=_p("Z", "doc_b", "2 V", 2.0),
        name_match_confidence=1.0,
        value_equivalent=False,
    )
    pair_low = AlignedPair(
        a=_p("Z", "doc_a", "1 V", 1.0),
        b=_p("Z", "doc_b", "2 V", 2.0),
        name_match_confidence=0.5,
        value_equivalent=False,
    )
    f_high = detect_flags([pair_high])[0]
    f_low = detect_flags([pair_low])[0]
    assert f_high.confidence > f_low.confidence


# ----- Phase 13: severity-tier assignment -----


def test_decimal_shift_impedance_classifies_critical() -> None:
    """The AES anecdote — 5.75% impedance vs 0.575% — must be critical."""
    pair = AlignedPair(
        a=_p("%Z", "doc_a", "5.75 %", 0.0575),
        b=_p("%Z", "doc_b", "0.575 %", 0.00575),
        name_match_confidence=1.0,
        value_equivalent=False,
    )
    flags = detect_flags([pair])
    assert len(flags) == 1
    assert flags[0].severity == "critical"
    assert flags[0].deviation_pct == 90.0
    assert flags[0].attribute_family == "impedance_pct"


def test_within_tolerance_change_is_suppressed_by_default() -> None:
    """5.75 -> 5.77% impedance is within IEEE C57.12.00 ±7.5% — info,
    suppressed by default."""
    pair = AlignedPair(
        a=_p("%Z", "doc_a", "5.75 %", 0.0575),
        b=_p("%Z", "doc_b", "5.77 %", 0.0577),
        name_match_confidence=1.0,
        value_equivalent=False,
    )
    assert detect_flags([pair]) == []


def test_within_tolerance_change_surfaces_when_info_not_suppressed() -> None:
    """Same as above but with suppress_info=False — flag still emitted,
    severity=info. Useful for the suppressed-pane UI."""
    pair = AlignedPair(
        a=_p("%Z", "doc_a", "5.75 %", 0.0575),
        b=_p("%Z", "doc_b", "5.77 %", 0.0577),
        name_match_confidence=1.0,
        value_equivalent=False,
    )
    flags = detect_flags([pair], suppress_info=False)
    assert len(flags) == 1
    assert flags[0].severity == "info"


def test_rated_power_8pct_classifies_minor() -> None:
    """1000 vs 1080 kVA = 7.4% — above 5% tolerance, below 10% major."""
    pair = AlignedPair(
        a=_p("Rated Power", "doc_a", "1000 kVA", 1_000_000.0),
        b=_p("Rated Power", "doc_b", "1080 kVA", 1_080_000.0),
        name_match_confidence=1.0,
        value_equivalent=False,
    )
    flags = detect_flags([pair])
    assert len(flags) == 1
    assert flags[0].severity == "minor"


def test_voltage_decimal_shift_classifies_critical() -> None:
    """132 kV vs 13.2 kV — 90% deviation, decimal-shift class."""
    pair = AlignedPair(
        a=_p("Primary Voltage", "doc_a", "132 kV", 132_000.0),
        b=_p("Primary Voltage", "doc_b", "13.2 kV", 13_200.0),
        name_match_confidence=1.0,
        value_equivalent=False,
    )
    flags = detect_flags([pair])
    assert flags[0].severity == "critical"


def test_string_only_mismatch_defaults_to_major_severity() -> None:
    """Part-number changes have no tolerance band; default to major (above
    info, surfaces in primary review list)."""
    pair = AlignedPair(
        a=_p("Fuse", "doc_a", "KRP-C-1600SP", None),
        b=_p("Fuse", "doc_b", "KRP-C-1601SP", None),
        name_match_confidence=1.0,
        value_equivalent=False,
    )
    flags = detect_flags([pair])
    assert flags[0].severity == "major"
    assert flags[0].attribute_family is None
