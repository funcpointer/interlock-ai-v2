"""Claim-aware alignment (Task 14.3).

Layered on top of the existing exact/semantic aligners — Claim[] inputs are
unwrapped to their source ParameterRecords for the underlying logic, then
optionally filtered to same-entity pairs only.

Tests pin:
1. Backward compatibility: a Claim-aware call with single-entity input
   produces the same pairs as the underlying ParameterRecord aligner.
2. Multi-equipment safety: when same_entity_only=True, P-101 attributes
   never pair with P-102 attributes even if names match.
3. Default behavior: same_entity_only=True is the safe default once
   explicit entities exist in the input.
4. Implicit-entity records still pair across docs (they share the same
   implicit_<doc> entity per side, but cross-doc the implicit entities
   differ — which would mean no cross-doc pairing — so we treat implicit
   as a wildcard).
"""

from __future__ import annotations

from interlock.align.claims import align_claims_exact
from interlock.extract.entities import Claim, Entity
from interlock.extract.parameters import ParameterRecord


def _record(
    name: str, raw: str, doc: str, mag: float | None = None, page: int = 1, y: float = 0.0
) -> ParameterRecord:
    return ParameterRecord(
        doc_id=doc,
        page=page,
        bbox=(0.0, y, 100.0, y + 10.0),
        section=None,
        span_text=f"{name}: {raw}",
        name=name,
        raw_value=raw,
        normalized_magnitude=mag,
        normalized_unit="x",
    )


def _claim(
    entity_id: str,
    entity_type: str,
    name: str,
    raw: str,
    doc: str,
    mag: float | None = None,
    y: float = 0.0,
) -> Claim:
    return Claim(
        entity=Entity(id=entity_id, type=entity_type, label=entity_id),  # type: ignore[arg-type]
        attribute=name,
        raw_value=raw,
        source_record=_record(name, raw, doc, mag, y=y),
    )


# ----- Backward compatibility -----


def test_claim_align_with_single_entity_matches_record_align() -> None:
    """When every claim is on the same entity, claim-aware align should
    produce the same pairs as the underlying record aligner."""
    a = [
        _claim("xfmr_001", "transformer", "Rated Power", "1000 kVA", "doc_a", mag=1e6),
        _claim("xfmr_001", "transformer", "Impedance", "5.75 %", "doc_a", mag=0.0575, y=20),
    ]
    b = [
        _claim("xfmr_001", "transformer", "Rated Power", "1000 kVA", "doc_b", mag=1e6),
        _claim("xfmr_001", "transformer", "Impedance", "5.75 %", "doc_b", mag=0.0575, y=20),
    ]
    pairs = align_claims_exact(a, b, same_entity_only=True)
    assert len(pairs) == 2


# ----- Multi-equipment safety -----


def test_multi_equipment_safe_alignment_does_not_cross_entities() -> None:
    """P-101 attributes must not pair with P-102 attributes when
    same_entity_only=True, even though the attribute names match."""
    a = [
        _claim("p_101", "pump", "Flow Rate", "1200 gpm", "doc_a", mag=1200),
        _claim("p_102", "pump", "Flow Rate", "950 gpm", "doc_a", mag=950, y=20),
    ]
    b = [
        _claim("p_101", "pump", "Flow Rate", "1100 gpm", "doc_b", mag=1100),
        _claim("p_102", "pump", "Flow Rate", "950 gpm", "doc_b", mag=950, y=20),
    ]
    pairs = align_claims_exact(a, b, same_entity_only=True)
    assert len(pairs) == 2
    # Pair entity ids must match within each pair
    for p in pairs:
        # AlignedPair carries the underlying records; entity is on the claim
        # but we need to verify the alignment direction was correct.
        # Extract via raw_value pairing: P-101 1200 → 1100, P-102 950 → 950.
        if p.a.raw_value == "1200 gpm":
            assert p.b.raw_value == "1100 gpm"
        elif p.a.raw_value == "950 gpm":
            assert p.b.raw_value == "950 gpm"


def test_same_entity_only_false_allows_cross_entity_pairing() -> None:
    """For revision-diff cases where no explicit entities exist (Option 1
    fixture), same_entity_only=False falls back to the original layout-anchored
    pairing — implicit entities don't constrain anything."""
    a = [
        _claim("implicit_doc_a", "implicit", "Impedance", "5.75 %", "doc_a", mag=0.0575),
    ]
    b = [
        _claim("implicit_doc_b", "implicit", "Impedance", "5.75 %", "doc_b", mag=0.0575),
    ]
    # With same_entity_only=False the cross-doc implicit pair is allowed.
    pairs = align_claims_exact(a, b, same_entity_only=False)
    assert len(pairs) == 1


def test_implicit_entity_is_treated_as_wildcard_under_same_entity_only() -> None:
    """Implicit entities are per-doc placeholders, never literally equal across
    docs. The same_entity_only filter must treat them as a wildcard so the
    revision-diff fixture (Option 1) still aligns under default settings."""
    a = [
        _claim("implicit_doc_a", "implicit", "Impedance", "5.75 %", "doc_a", mag=0.0575),
    ]
    b = [
        _claim("implicit_doc_b", "implicit", "Impedance", "0.575 %", "doc_b", mag=0.00575),
    ]
    pairs = align_claims_exact(a, b, same_entity_only=True)
    assert len(pairs) == 1  # implicit-vs-implicit allowed


def test_explicit_entity_cannot_pair_with_implicit() -> None:
    """If A has an explicit entity but B's record is implicit, no pair under
    same_entity_only=True. The pipeline can fall back to same_entity_only=False
    when needed; this strict semantic prevents accidental cross-entity matches
    in mixed fixtures."""
    a = [_claim("p_101", "pump", "Flow", "1200 gpm", "doc_a", mag=1200)]
    b = [_claim("implicit_doc_b", "implicit", "Flow", "1100 gpm", "doc_b", mag=1100)]
    pairs = align_claims_exact(a, b, same_entity_only=True)
    assert pairs == []


def test_alignment_returns_aligned_pairs_compatible_with_detect_flags() -> None:
    """Output type must be AlignedPair[] so the existing detect_flags
    pipeline accepts it unchanged."""
    from interlock.align.exact import AlignedPair
    from interlock.detect.mismatch import detect_flags

    a = [_claim("xfmr_001", "transformer", "Impedance", "5.75 %", "doc_a", mag=0.0575)]
    b = [_claim("xfmr_001", "transformer", "Impedance", "0.575 %", "doc_b", mag=0.00575)]
    pairs = align_claims_exact(a, b, same_entity_only=True)
    assert all(isinstance(p, AlignedPair) for p in pairs)
    flags = detect_flags(pairs)
    assert len(flags) == 1
    assert flags[0].severity == "critical"
