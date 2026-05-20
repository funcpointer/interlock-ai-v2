"""Canonical-glossary correctness tests.

The glossary in ``align/semantic.py`` is the explicit engineering knowledge
that lets Voyage embeddings collapse shorthand to the underlying concept.
These tests pin every entry against its expected canonical phrase, and
verify the behavior of ``canonical_name`` on unknown inputs.
"""

from __future__ import annotations

import pytest

from interlock.align.semantic import _CANONICAL, canonical_name


def test_unknown_name_passes_through_unchanged() -> None:
    assert canonical_name("ZorpFactor") == "ZorpFactor"


def test_empty_name_passes_through() -> None:
    assert canonical_name("") == ""


def test_known_synonyms_collapse_to_same_canonical_phrase() -> None:
    """Within each family every alias must map to the same canonical phrase.
    This is what lets Voyage embeddings score cosine ≈ 1.0 across the family.
    """
    impedance_family = [
        "%Z", "%z", "Z%", "Impedance", "Rated Impedance", "Per Unit Impedance"
    ]
    canon_values = {canonical_name(n) for n in impedance_family}
    assert len(canon_values) == 1, (
        f"impedance family inconsistent: {canon_values}"
    )

    rating_family = [
        "Transformer Rating", "Rated Power", "Rated Capacity", "kVA Rating"
    ]
    assert len({canonical_name(n) for n in rating_family}) == 1


def test_voltage_families_are_distinct_from_each_other() -> None:
    primary_canon = canonical_name("Primary Voltage")
    secondary_canon = canonical_name("Secondary Voltage")
    system_canon = canonical_name("System Voltage")
    # Primary and secondary must NOT collapse to the same canonical phrase —
    # they are conceptually distinct parameters on a transformer nameplate.
    assert primary_canon != secondary_canon
    # System voltage is its own family.
    assert system_canon not in (primary_canon, secondary_canon)


def test_bil_does_not_collapse_into_voltage_families() -> None:
    """Regression: in Phase 11 BIL initially semantic-paired with System
    Voltage because both surfaced as kV; the glossary now keeps them apart.
    """
    bil_canon = canonical_name("BIL")
    system_canon = canonical_name("System Voltage")
    primary_canon = canonical_name("Primary Voltage")
    assert bil_canon not in (system_canon, primary_canon)


@pytest.mark.parametrize(
    "shorthand,expected_substring",
    [
        ("%Z", "impedance"),
        ("Rated Impedance", "impedance"),
        ("Transformer Rating", "apparent power"),
        ("Rated Power", "apparent power"),
        ("Primary Voltage", "primary voltage"),
        ("Secondary Voltage", "secondary voltage"),
        ("System Voltage", "system voltage"),
        ("BIL", "insulation"),
        ("Fault Current", "fault current"),
        ("IFLA", "full load"),
    ],
)
def test_canonical_phrase_contains_expected_concept_word(
    shorthand: str, expected_substring: str
) -> None:
    canon = canonical_name(shorthand)
    assert expected_substring.lower() in canon.lower(), (
        f"canonical({shorthand}) = {canon!r} lacks {expected_substring!r}"
    )


def test_glossary_has_no_duplicate_keys_after_case_norm() -> None:
    """Detect accidental dual entries differing only by case.

    The glossary uses some lowercase variants intentionally (``%z``) but no
    pair of entries should collapse to the same case-folded key with
    differing canonical phrases — that would be an inconsistency.
    """
    by_folded: dict[str, set[str]] = {}
    for k, v in _CANONICAL.items():
        by_folded.setdefault(k.casefold(), set()).add(v)
    inconsistent = {k: vs for k, vs in by_folded.items() if len(vs) > 1}
    assert not inconsistent, (
        f"inconsistent canonical for case-folded keys: {inconsistent}"
    )
