"""Sprint 9 / v2.9 — typed data contracts.

This package holds **only data shapes**, no business logic. Per spec
§2.2 (module split as enforcement mechanism): inventory builders,
matchers, and mutation classifiers live in ``extract/`` and
``align/``. ``model/`` answers "what is the shape of an equipment
entity?" — nothing else.

Phase 33.1 ships ``equipment.py`` with EquipmentMention / Equipment /
EquipmentMatch + their state literals. No builders, no matchers, no
classifiers — those land in Phases 33.2–33.5.
"""
