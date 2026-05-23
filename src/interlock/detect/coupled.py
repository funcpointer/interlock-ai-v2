"""Sprint 5b — coupled-effect graph for parameter families.

Encodes the canonical engineering knowledge that one parameter family's
change cascades into specific dependent families. Same engineering domain
knowledge as the LLM judge's _ONTOLOGY_BLOCK; we ship a hand-curated
static map here so the reviewer surface is deterministic + auditable +
free of LLM noise.

When the Phase 14 SQLite store is populated (via persist_claims=True),
``coupled_claims_for()`` also surfaces matching persisted claims so the
reviewer sees the actual cross-document records that may need
re-verification, not just the family names.
"""

from __future__ import annotations

from interlock.extract.entities import Claim
from interlock.store.sqlite import claims_for_attribute

COUPLED_FAMILIES: dict[str, list[str]] = {
    "impedance_pct": [
        "fault_current_a", "fault_current_ka",
        "relay_pickup_a", "coordination_margin_pct",
        "voltage_regulation_pct",
    ],
    "transformer_rating_va": [
        "cable_ampacity_a", "breaker_interrupting_ka",
        "ct_ratio", "transformer_loading_pct",
    ],
    "voltage_v": [
        "bil_kv", "surge_arrester_rating_kv",
        "clearance_mm", "conductor_amp",
    ],
    "voltage_kv": [
        "bil_kv", "surge_arrester_rating_kv",
        "clearance_mm", "conductor_amp",
    ],
    "fault_current_a": [
        "relay_pickup_a", "breaker_interrupting_ka",
        "ground_grid_size_m2", "arc_flash_cal_cm2",
    ],
    "fault_current_ka": [
        "relay_pickup_a", "breaker_interrupting_ka",
        "ground_grid_size_m2", "arc_flash_cal_cm2",
    ],
    "motor_fla_a": [
        "cable_ampacity_a", "overload_pickup_a",
        "starting_current_a",
    ],
    "relay_pickup_a": [
        "coordination_margin_pct", "trip_curve_time_s",
    ],
    "fuse_amps": [
        "coordination_margin_pct", "trip_curve_time_s",
        "breaker_interrupting_ka",
    ],
    "breaker_interrupting_ka": [
        "fault_current_ka", "arc_flash_cal_cm2",
    ],
}


def coupled_families_for(family: str | None) -> list[str]:
    """Return the dependent parameter families for a given primary family.

    Empty list when family is None / unknown / not in the static map.
    Returns a fresh copy so caller mutations don't affect the map.
    """
    if not family:
        return []
    return list(COUPLED_FAMILIES.get(family, []))


def coupled_claims_for(family: str | None) -> list[Claim]:
    """Return persisted Phase-14 claims whose attribute matches any of the
    dependent families. Empty list when the store has no matching claims
    (default state when persist_claims=False)."""
    families = coupled_families_for(family)
    if not families:
        return []
    out: list[Claim] = []
    for fam in families:
        try:
            out.extend(claims_for_attribute(fam))
        except Exception:
            # Store unreachable / schema mismatch — silent skip; UI will show
            # "no persisted claim found in store" for that family.
            pass
    return out
