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
from typing import Any

import yaml

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
# Adapter scaffolding for Phase 33.1+
# ----------------------------------------------------------------------
# Phase 33.1 will replace these stubs with real conversions into the
# typed schemas. For now they raise NotImplementedError so any
# accidental Phase 33.1 usage of these helpers fails loudly instead
# of silently producing dict-shaped fakes.


def to_equipment_a(attack_entry: dict[str, Any]) -> list[Any]:
    """Stub. Phase 33.1 will return ``list[Equipment]``."""
    raise NotImplementedError(
        "Phase 33.1 hook — typed Equipment schema not yet shipped. "
        "Phase 33.0a tests assert on dict-shaped gold directly."
    )


def to_equipment_b(attack_entry: dict[str, Any]) -> list[Any]:
    """Stub. Phase 33.1 will return ``list[Equipment]``."""
    raise NotImplementedError(
        "Phase 33.1 hook — typed Equipment schema not yet shipped."
    )


def to_synthetic_records(attack_entry: dict[str, Any], side: str) -> list[dict[str, Any]]:
    """Return the synthetic_inputs records for one side ('doc_a' or
    'doc_b'). Returns plain dicts; Phase 33.1+ will wrap them in
    ``ParameterRecord`` / ``Span`` instances via lifters at the call
    site."""
    if side not in ("doc_a", "doc_b"):
        raise ValueError(f"side must be 'doc_a' or 'doc_b', got {side!r}")
    records = attack_entry.get("synthetic_inputs", {}).get(side, {}).get("records", [])
    return list(records)
