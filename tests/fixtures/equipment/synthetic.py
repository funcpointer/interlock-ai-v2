"""Synthetic fixture loaders for Phase 33.0a equipment-identity gold.

Phase 33.0a is contract-only — no production model classes exist yet
(Phase 33.1 ships ``src/interlock/model/equipment.py``). This module
returns dict-shaped data parsed from the gold YAML so tests can:

1. Assert YAML schema + invariants now (Phase 33.0a)
2. Switch to typed Equipment/Match assertions once Phase 33.1 lands

Functions intentionally return plain ``dict``s + ``list``s. Phase 33.1
will add ``to_equipment(...)`` adapters that lift them into typed
``Equipment`` instances.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml

if TYPE_CHECKING:
    from interlock.model.equipment import Equipment

_GOLD_PATH = (
    Path(__file__).resolve().parents[3]
    / "fixtures"
    / "eval"
    / "equipment_identity_gold.yaml"
)


def load_gold() -> dict[str, Any]:
    """Load the full equipment-identity gold YAML as a dict."""
    with _GOLD_PATH.open("r", encoding="utf-8") as f:
        data: dict[str, Any] = yaml.safe_load(f)
    return data


def attacks() -> list[dict[str, Any]]:
    """Return the list of attack fixtures (14 entries)."""
    return list(load_gold()["attacks"])


def attack(name: str) -> dict[str, Any]:
    """Return a single attack fixture by name. Raises if not found.

    Used by per-attack pytest parametrize cases."""
    for entry in attacks():
        if entry["name"] == name:
            return entry
    raise KeyError(f"attack {name!r} not found in equipment_identity_gold.yaml")


def attack_names() -> list[str]:
    """Stable order of attack names — used by pytest.mark.parametrize."""
    return [a["name"] for a in attacks()]


def global_invariants() -> list[dict[str, Any]]:
    """Return the global_invariants block — spec §2.1 guardrails."""
    return list(load_gold().get("global_invariants", []))


# ----------------------------------------------------------------------
# Adapters into the Phase 33.1 typed schemas
# ----------------------------------------------------------------------
# These lifters convert the dict-shaped gold YAML into typed
# ``Equipment`` instances from ``src/interlock/model/equipment.py``.
# Phase 33.1 only wires the inventory side — match-side lifting (gold
# ``expected_matches`` → ``EquipmentMatch``) lands in Phase 33.4 when
# the matcher exists.


def to_equipment_a(attack_entry: dict[str, Any]) -> list["Equipment"]:
    """Lift gold ``expected_inventory_a`` into typed Equipment objects.

    Returns an empty list when the attack declares no inventory
    expectation (e.g. matcher-only fixtures). Each Equipment instance
    is run through ``validate_equipment`` so any §2.1 invariant
    violation in the gold itself trips the lifter loudly."""
    return _lift_inventory(attack_entry, side="doc_a")


def to_equipment_b(attack_entry: dict[str, Any]) -> list["Equipment"]:
    """Lift gold ``expected_inventory_b`` into typed Equipment objects."""
    return _lift_inventory(attack_entry, side="doc_b")


def _lift_inventory(attack_entry: dict[str, Any], side: str) -> list["Equipment"]:
    from interlock.model.equipment import Equipment, validate_equipment

    if side not in ("doc_a", "doc_b"):
        raise ValueError(f"side must be 'doc_a' or 'doc_b', got {side!r}")

    block_name = "expected_inventory_a" if side == "doc_a" else "expected_inventory_b"
    entries = attack_entry.get(block_name, []) or []

    out: list[Equipment] = []
    for entry in entries:
        eq = Equipment(
            doc_id=side,
            canonical_id=entry["canonical_id"],
            kind=entry["kind"],
            identity_anchors=tuple(entry.get("identity_anchors", []) or []),
            weak_descriptors=tuple(entry.get("weak_descriptors", []) or []),
            parameters=dict(entry.get("parameters", {}) or {}),
            mentions=(),  # Phase 33.2 builder populates; gold doesn't enumerate
            confidence=float(entry.get("confidence", entry.get("confidence_cap", 1.0))),
            cluster_status=entry.get("cluster_status", "confident_cluster"),
        )
        validate_equipment(eq)
        out.append(eq)
    return out




def to_synthetic_records(attack_entry: dict[str, Any], side: str) -> list[dict[str, Any]]:
    """Return the synthetic_inputs records for one side ('doc_a' or
    'doc_b'). Returns plain dicts; Phase 33.1+ will wrap them in
    ``ParameterRecord`` / ``Span`` instances via lifters at the call
    site."""
    if side not in ("doc_a", "doc_b"):
        raise ValueError(f"side must be 'doc_a' or 'doc_b', got {side!r}")
    records = attack_entry.get("synthetic_inputs", {}).get(side, {}).get("records", [])
    return list(records)
