import pytest

from interlock.extract.units import equivalent, normalize_quantity, parse_quantity


def test_parse_basic_voltage() -> None:
    q = parse_quantity("132 kV")
    assert q.magnitude == 132
    assert "kilovolt" in str(q.units)


def test_normalize_to_base_si_volts() -> None:
    q = normalize_quantity("132 kV")
    assert q.magnitude == pytest.approx(132_000.0)


def test_equivalence_across_unit_forms() -> None:
    assert equivalent("132 kV", "132,000 V")
    assert equivalent("25 MVA", "25000 kVA")
    assert equivalent("150 kVA", "0.15 MVA")
    assert not equivalent("5.75 %", "0.575 %")


def test_percent_handling() -> None:
    # 5.75% should equal 0.0575 as a dimensionless ratio.
    assert equivalent("5.75 %", "0.0575")
    # And differ from 0.575%.
    assert not equivalent("5.75 %", "0.575 %")


def test_micro_prefix_unicode() -> None:
    # μF should parse the same as uF.
    q = parse_quantity("4.7 μF")
    assert q.magnitude == pytest.approx(4.7)


def test_equivalent_handles_garbage_safely() -> None:
    # Non-parseable input must return False, not raise.
    assert not equivalent("garbage", "132 kV")
    assert not equivalent("132 kV", "")


def test_dimensionality_mismatch_is_not_equivalent() -> None:
    assert not equivalent("132 kV", "132 kA")
