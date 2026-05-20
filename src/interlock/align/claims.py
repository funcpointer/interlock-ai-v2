"""Entity-aware alignment over Claim[] (Task 14.3).

Thin wrapper on top of the existing ``align_exact`` (and later ``align_semantic``)
that operates on ``Claim`` inputs and optionally filters pairs to same-entity
matches only. Existing record-based aligners are unchanged so v1.3 tests keep
passing untouched.

Semantics
---------
- ``same_entity_only=True`` is the safe default for multi-equipment fixtures
  (Phase 16). With explicit equipment tags in the source spans, only pairs
  whose entity ids match are kept.
- Implicit entities (``implicit_<doc_id>``) are treated as wildcards under
  ``same_entity_only=True``. They occur when a span has no equipment tag —
  the revision-diff fixture (Option 1) is entirely implicit. Treating them
  as wildcards keeps Option 1 working unchanged.
- An explicit entity paired with an implicit entity is **rejected** under
  ``same_entity_only=True`` — that prevents accidental cross-entity matches
  in mixed fixtures.

DocETL vocabulary alignment
---------------------------
This module implements the ``resolve`` operator's pair-generation step.
"""

from __future__ import annotations

from interlock.align.exact import AlignedPair, align_exact
from interlock.extract.entities import Claim


def _is_implicit(claim: Claim) -> bool:
    return claim.entity.type == "implicit"


def _claims_to_records_by_identity(claims: list[Claim]) -> dict[int, Claim]:
    """Index claims by the id() of their source record so we can recover
    the originating Claim from an AlignedPair (which carries records, not
    claims)."""
    return {id(c.source_record): c for c in claims}


def _entities_match(a: Claim, b: Claim) -> bool:
    """Same-entity-only rule with implicit-wildcard semantics."""
    if _is_implicit(a) and _is_implicit(b):
        return True
    if _is_implicit(a) or _is_implicit(b):
        return False
    return a.entity.id == b.entity.id


def align_claims_exact(
    a: list[Claim],
    b: list[Claim],
    *,
    same_entity_only: bool = True,
) -> list[AlignedPair]:
    """Exact-name alignment over Claim[] with optional same-entity filter.

    Reuses the layout-anchored ``align_exact`` for the heavy lifting; we
    only do the entity gate on the output pairs.
    """
    records_a = [c.source_record for c in a]
    records_b = [c.source_record for c in b]
    raw_pairs = align_exact(records_a, records_b)
    if not same_entity_only:
        return raw_pairs

    a_idx = _claims_to_records_by_identity(a)
    b_idx = _claims_to_records_by_identity(b)

    out: list[AlignedPair] = []
    for p in raw_pairs:
        ca = a_idx.get(id(p.a))
        cb = b_idx.get(id(p.b))
        if ca is None or cb is None:
            # Should not happen for well-formed inputs; be defensive.
            continue
        if _entities_match(ca, cb):
            out.append(p)
    return out
