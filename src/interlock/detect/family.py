"""Map canonical parameter phrases to tolerance families.

The pipeline already canonicalizes parameter names (in ``align/semantic.py``)
so synonyms collapse to a single phrase. This module connects each canonical
phrase to a tolerance family in ``detect/tolerances.py``.

When a new canonical phrase is added to the glossary, also add a row here.
The test suite enforces that every canonical phrase maps to a valid family
(or explicitly None for "no tolerance band yet").
"""

from __future__ import annotations

from interlock.align.semantic import canonical_name

# Map canonical phrase → tolerance family.
# Keep in lockstep with align/semantic.py::_CANONICAL.
_FAMILY: dict[str, str | None] = {
    # Impedance family
    "transformer impedance percent": "impedance_pct",
    # Rated power family
    "transformer rated apparent power kVA": "rated_power_kva",
    # Voltage families — all use the same tolerance family today; if BIL or
    # secondary voltages later need their own bands, split here.
    "transformer primary voltage kV": "voltage_kv",
    "transformer secondary voltage V": "voltage_kv",
    "system voltage kV": "voltage_kv",
    "basic insulation level dielectric withstand": "voltage_kv",
    # Current families
    "short circuit fault current": "fault_current_a",
    "full load amperes IFLA": "fault_current_a",
}


def attribute_family_for(canonical_phrase: str) -> str | None:
    """Return the tolerance family for a canonical phrase, or None.

    Returning None means "no tolerance band defined for this phrase yet."
    The severity classifier will fall back to default bands.
    """
    return _FAMILY.get(canonical_phrase)


def attribute_family_for_param_name(name: str) -> str | None:
    """Resolve a raw parameter name to a tolerance family in one step.

    Equivalent to ``attribute_family_for(canonical_name(name))``.
    """
    return attribute_family_for(canonical_name(name))
