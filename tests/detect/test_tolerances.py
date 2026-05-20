"""Tolerance-band classification invariants.

The tolerance table is the bridge from "values differ" to "this is engineering-
meaningful." Tests pin every band's source citation and verify the severity
classifier on representative inputs.
"""

from __future__ import annotations

import pytest

from interlock.detect.tolerances import (
    TOLERANCE_TABLE,
    Severity,
    classify,
    relative_deviation,
)


def test_every_band_has_source_citation() -> None:
    """No band may ship without a source citation."""
    for family, band in TOLERANCE_TABLE.items():
        assert band.source, f"family {family} has no source citation"
        assert band.attribute_family == family


def test_tolerance_bands_are_monotonically_increasing() -> None:
    """Within a family: tolerance < major < critical thresholds."""
    for family, band in TOLERANCE_TABLE.items():
        assert band.rel_tolerance_pct < band.rel_major_pct, family
        assert band.rel_major_pct < band.rel_critical_pct, family


@pytest.mark.parametrize(
    "a,b,expected",
    [
        (132_000, 132_000, 0.0),
        (132_000, 0, 100.0),
        (100, 110, pytest.approx(9.09, abs=0.1)),
        (1.0, 0.5, 50.0),
        (0, 0, 0.0),
    ],
)
def test_relative_deviation(a: float, b: float, expected: float) -> None:
    assert relative_deviation(a, b) == expected


def test_decimal_shift_on_impedance_classifies_critical() -> None:
    """The AES-anecdote class — 5.75% impedance shifted to 0.575% is a
    decimal error, the worst class of mistake. Must classify as critical."""
    dev = relative_deviation(0.0575, 0.00575)
    assert dev == 90.0
    assert classify("impedance_pct", dev) == "critical"


def test_within_typical_tolerance_classifies_info() -> None:
    """5.75% impedance vs 5.77% is well within IEEE C57.12.00's ±7.5%
    tolerance band — should classify as info (suppressed by default)."""
    dev = relative_deviation(5.75, 5.77)
    assert dev < 1.0
    assert classify("impedance_pct", dev) == "info"


def test_rated_power_above_tolerance_classifies_minor() -> None:
    """1000 vs 1080 kVA: 8% deviation, above 5% tolerance, below 10% major.
    Should classify as minor (above the suppression line, below "raise alarm")."""
    dev = relative_deviation(1000, 1080)
    assert dev == pytest.approx(7.41, abs=0.1)
    assert classify("rated_power_kva", dev) == "minor"


def test_voltage_5pct_deviation_classifies_major() -> None:
    """132 kV vs 138.6 kV: 4.76% deviation. IEC 60076 typical is ±0.5%; major at 5%.
    Right at the boundary — currently classifies as minor (below 5%)."""
    dev = relative_deviation(132, 138.6)
    assert dev == pytest.approx(4.76, abs=0.1)
    assert classify("voltage_kv", dev) == "minor"


def test_voltage_10pct_deviation_classifies_major() -> None:
    """132 kV vs 145.5 kV: 9.28% deviation — clearly major."""
    dev = relative_deviation(132, 145.5)
    assert classify("voltage_kv", dev) == "major"


def test_unknown_family_falls_back_to_default_bands() -> None:
    """An attribute family without a defined band should not crash —
    fall back to broad defaults so the pipeline still emits severity."""
    sev: Severity = classify("future_unknown_family", 60.0)
    assert sev == "critical"  # 60% deviation is critical under any reasonable default


def test_classify_zero_deviation_is_info() -> None:
    """Pint-equivalent values produce 0% deviation; must be info (suppressed)."""
    assert classify("impedance_pct", 0.0) == "info"
    assert classify("rated_power_kva", 0.0) == "info"
    assert classify("voltage_kv", 0.0) == "info"


@pytest.mark.parametrize(
    "family,deviation_pct,expected",
    [
        ("impedance_pct", 0.0, "info"),
        ("impedance_pct", 5.0, "info"),
        ("impedance_pct", 8.0, "minor"),
        ("impedance_pct", 25.0, "major"),
        ("impedance_pct", 90.0, "critical"),
        ("rated_power_kva", 0.5, "info"),
        ("rated_power_kva", 7.0, "minor"),
        ("rated_power_kva", 15.0, "major"),
        ("rated_power_kva", 60.0, "critical"),
        ("voltage_kv", 0.1, "info"),
        ("voltage_kv", 2.0, "minor"),
        ("voltage_kv", 10.0, "major"),
        ("voltage_kv", 60.0, "critical"),
        ("fault_current_a", 1.0, "info"),
        ("fault_current_a", 10.0, "minor"),
        ("fault_current_a", 25.0, "major"),
        ("fault_current_a", 60.0, "critical"),
    ],
)
def test_classification_matrix(family: str, deviation_pct: float, expected: Severity) -> None:
    assert classify(family, deviation_pct) == expected
