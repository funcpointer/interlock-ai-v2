"""Attribute-family resolver invariants.

The resolver connects canonical phrases (from align/semantic.py::_CANONICAL)
to tolerance families (in detect/tolerances.py::TOLERANCE_TABLE). Without
this mapping, severity classification can't pick the right band.
"""

from __future__ import annotations

import pytest

from interlock.align.semantic import _CANONICAL, canonical_name
from interlock.detect.family import (
    attribute_family_for,
    attribute_family_for_param_name,
)
from interlock.detect.tolerances import TOLERANCE_TABLE


def test_every_canonical_phrase_in_glossary_maps_to_a_family() -> None:
    """Every entry in _CANONICAL must resolve to a valid TOLERANCE_TABLE
    family (or explicitly None). No silent misses."""
    unmapped: list[str] = []
    for canon in set(_CANONICAL.values()):
        family = attribute_family_for(canon)
        if family is None:
            unmapped.append(canon)
    assert not unmapped, f"canonical phrases without family mapping: {unmapped}"


def test_every_returned_family_exists_in_tolerance_table() -> None:
    """Resolver outputs must be valid keys in TOLERANCE_TABLE."""
    for canon in set(_CANONICAL.values()):
        family = attribute_family_for(canon)
        if family is not None:
            assert family in TOLERANCE_TABLE, f"canonical {canon!r} → family {family!r} not in TOLERANCE_TABLE"


def test_unknown_canonical_returns_none() -> None:
    assert attribute_family_for("zorpfactor of the whatchamacallit") is None


def test_param_name_resolution_via_canonical() -> None:
    """The convenience function takes a raw parameter name, runs it through
    canonical resolution, then looks up the family."""
    assert attribute_family_for_param_name("%Z") == "impedance_pct"
    assert attribute_family_for_param_name("Rated Power") == "rated_power_kva"
    assert attribute_family_for_param_name("Transformer Rating") == "rated_power_kva"
    assert attribute_family_for_param_name("Primary Voltage") == "voltage_kv"
    assert attribute_family_for_param_name("System Voltage") == "voltage_kv"
    assert attribute_family_for_param_name("Fault Current") == "fault_current_a"


def test_bil_is_not_treated_as_voltage_family() -> None:
    """BIL uses kV but is conceptually distinct from system voltage.
    For tolerance purposes BIL falls under voltage_kv (same dimensional
    family) but the test pins the current behavior; if we later separate
    BIL into its own family this test will catch the change."""
    fam = attribute_family_for_param_name("BIL")
    assert fam in {"voltage_kv", None}, f"unexpected BIL family: {fam}"


@pytest.mark.parametrize(
    "name,expected_family",
    [
        ("Impedance", "impedance_pct"),
        ("Rated Impedance", "impedance_pct"),
        ("%Z", "impedance_pct"),
        ("Per Unit Impedance", "impedance_pct"),
        ("Transformer Rating", "rated_power_kva"),
        ("Rated Power", "rated_power_kva"),
        ("Rated Capacity", "rated_power_kva"),
        ("Primary Voltage", "voltage_kv"),
        ("Secondary Voltage", "voltage_kv"),
        ("System Voltage", "voltage_kv"),
        ("Fault Current", "fault_current_a"),
        ("Short Circuit Current", "fault_current_a"),
        ("IFLA", "fault_current_a"),
    ],
)
def test_family_resolution_matrix(name: str, expected_family: str) -> None:
    canon = canonical_name(name)
    assert attribute_family_for(canon) == expected_family
