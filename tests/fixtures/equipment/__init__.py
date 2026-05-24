"""Phase 33.0a equipment-identity acceptance fixtures.

Source of truth: ``fixtures/eval/equipment_identity_gold.yaml``.
Companion: ``docs/superpowers/specs/2026-05-24-sprint-9-cross-doc-entity-resolution.md``.

Per spec §12 "Stop revising": this package's existence + the gold
YAML are the gate for Phase 33.1. CI pre-commit check should fail any
attempt to add ``src/interlock/model/equipment.py`` while this
package is empty.
"""
