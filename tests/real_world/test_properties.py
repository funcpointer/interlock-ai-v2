"""Property tests for unit normalization, confidence, and alignment invariants.

Asserts the system holds invariants across a range of inputs — small step
toward fuzz/property coverage without taking a hard dependency on Hypothesis.
"""

from __future__ import annotations

import pytest

from interlock.align.exact import AlignedPair, align_exact
from interlock.detect.confidence import flag_confidence
from interlock.detect.mismatch import detect_flags
from interlock.extract.parameters import ParameterRecord
from interlock.extract.units import equivalent, normalize_quantity, same_dimension

# ---------- Pint normalization properties ----------

UNIT_EQUIVALENT_PAIRS = [
    ("132 kV", "132000 V"),
    ("132 kV", "0.132 MV"),
    ("1000 kVA", "1 MVA"),
    ("1000 kVA", "1000000 VA"),
    ("5.75 %", "0.0575"),
    ("100 %", "1"),
    ("60 Hz", "60 Hz"),
    ("1 kA", "1000 A"),
]

UNIT_INEQUIVALENT_PAIRS = [
    ("132 kV", "20000 A"),     # different dimension
    ("1000 kVA", "5.75 %"),    # different dimension
    ("5.75 %", "0.575 %"),     # same dimension, different value
    ("132 kV", "133 kV"),      # same unit, different value
    ("1000 kVA", "1100 kVA"),  # same unit, different value
]


@pytest.mark.parametrize("a,b", UNIT_EQUIVALENT_PAIRS)
def test_equivalent_handles_known_engineering_unit_equivalences(a: str, b: str) -> None:
    assert equivalent(a, b), f"Pint failed equivalence: {a} == {b}"


@pytest.mark.parametrize("a,b", UNIT_INEQUIVALENT_PAIRS)
def test_equivalent_rejects_inequivalent_pairs(a: str, b: str) -> None:
    assert not equivalent(a, b), f"false equivalence: {a} == {b}"


@pytest.mark.parametrize("a,b", UNIT_EQUIVALENT_PAIRS + [("132 kV", "133 kV")])
def test_same_dimension_holds_for_dimensionally_compatible_pairs(a: str, b: str) -> None:
    assert same_dimension(a, b)


@pytest.mark.parametrize(
    "a,b",
    [
        ("132 kV", "1000 kVA"),
        ("60 Hz", "100 A"),
        ("5.75 %", "20000 A"),
        ("100 °C", "132 kV"),
    ],
)
def test_same_dimension_rejects_dimensionally_incompatible_pairs(a: str, b: str) -> None:
    assert not same_dimension(a, b)


def test_normalize_quantity_idempotent_to_base_units() -> None:
    q1 = normalize_quantity("132 kV")
    q2 = normalize_quantity(f"{q1.magnitude} {q1.units}")
    assert q1.magnitude == q2.magnitude
    assert q1.units == q2.units


# ---------- Confidence formula properties ----------


@pytest.mark.parametrize(
    "e,m,a,expected",
    [
        (1.0, 1.0, 1.0, 1.0),
        (0.0, 1.0, 1.0, 0.0),
        (1.0, 0.0, 1.0, 0.0),
        (1.0, 1.0, 0.0, 0.0),
        (0.5, 0.5, 0.5, 0.125),
        (0.7, 0.8, 1.0, 0.56),
        (-1.0, 1.0, 1.0, 0.0),  # clamped
        (2.0, 1.0, 1.0, 1.0),   # clamped
    ],
)
def test_flag_confidence_multiplies_and_clamps(
    e: float, m: float, a: float, expected: float
) -> None:
    assert abs(flag_confidence(extraction=e, match=m, authority=a) - expected) < 1e-9


def test_flag_confidence_is_monotone_in_each_component() -> None:
    """Holding two components fixed, increasing the third never decreases the
    output."""
    base = flag_confidence(extraction=0.5, match=0.5, authority=0.5)
    for kw in ("extraction", "match", "authority"):
        kwargs = {"extraction": 0.5, "match": 0.5, "authority": 0.5}
        kwargs[kw] = 0.9
        assert flag_confidence(**kwargs) >= base


# ---------- Alignment invariants ----------


def _rec(name: str, raw: str, mag: float | None, doc: str = "a") -> ParameterRecord:
    return ParameterRecord(
        doc_id=doc,
        page=1,
        bbox=(0, 0, 100, 10),
        section=None,
        span_text=f"{name}: {raw}",
        name=name,
        raw_value=raw,
        normalized_magnitude=mag,
        normalized_unit="x",
    )


def test_align_exact_is_symmetric_in_value_equivalence() -> None:
    """If A↔B is value-equivalent, B↔A is also value-equivalent."""
    a = [_rec("Voltage", "132 kV", 132000.0, "A")]
    b = [_rec("Voltage", "132000 V", 132000.0, "B")]
    p_ab = align_exact(a, b)
    p_ba = align_exact(b, a)
    assert p_ab and p_ba
    assert p_ab[0].value_equivalent == p_ba[0].value_equivalent


def test_align_exact_never_pairs_records_with_different_names() -> None:
    a = [_rec("Voltage", "132 kV", 132000.0, "A")]
    b = [_rec("Current", "100 A", 100.0, "B")]
    assert align_exact(a, b) == []


def test_detect_flags_no_flag_when_values_match() -> None:
    a = [_rec("Voltage", "132 kV", 132000.0, "A")]
    b = [_rec("Voltage", "132000 V", 132000.0, "B")]
    pairs = align_exact(a, b)
    assert pairs and pairs[0].value_equivalent
    assert detect_flags(pairs) == []


def test_detect_flags_emits_for_unequal_values() -> None:
    a = [_rec("Voltage", "132 kV", 132000.0, "A")]
    b = [_rec("Voltage", "138 kV", 138000.0, "B")]
    pairs = align_exact(a, b)
    flags = detect_flags(pairs)
    assert len(flags) == 1
    assert flags[0].parameter == "Voltage"


def test_detect_flags_emits_for_string_only_mismatch_same_name() -> None:
    """Fuse-part-number changes between revisions are real engineering
    discrepancies — a 500A fuse swapped for a 225A fuse changes protection
    behavior. The pipeline correctly surfaces these as flags.

    Behavior pinning: when align_exact pairs two records on identical name
    and equivalent()=False (because the raw strings differ), detect_flags
    emits a flag at confidence = name_match × authority (no extraction
    discount because spans are native-text).
    """
    a = [_rec("Fuse Designation", "LPN-RK-500SP", None, "A")]
    b = [_rec("Fuse Designation", "LPN-RK-225SP", None, "B")]
    pair = AlignedPair(a=a[0], b=b[0], name_match_confidence=1.0, value_equivalent=False)
    flags = detect_flags([pair])
    assert len(flags) == 1
    assert flags[0].parameter == "Fuse Designation"
    assert "LPN-RK-500SP" in flags[0].a_record.raw_value
    assert "LPN-RK-225SP" in flags[0].b_record.raw_value


def test_detect_flags_skips_string_only_equivalent_records() -> None:
    """When two string-only records have value_equivalent=True (e.g. equal
    part numbers possibly differing in whitespace), no flag is emitted.
    """
    a = [_rec("Fuse Designation", "LPN-RK-500SP", None, "A")]
    b = [_rec("Fuse Designation", "LPN-RK-500SP", None, "B")]
    pair = AlignedPair(a=a[0], b=b[0], name_match_confidence=1.0, value_equivalent=True)
    assert detect_flags([pair]) == []
