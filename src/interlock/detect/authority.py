"""Authority rules — v1 hardcoded default + v2 per-class hierarchy.

v1 rule (still the default in v2 when `classify_docs=False` OR either
class is `DocClass.unknown`): Doc A authoritative over Doc B.

v2 Sprint 1 (BACKLOG.md R-G is the per-project precedence-ladder
follow-up): per-class authority for specific parameter families.
Equipment specs beat coordination studies for transformer_params;
relay setting sheets beat everything for relay_settings.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from interlock.llm_pipeline.schemas.doc_class import DocClass

Side = Literal["doc_a", "doc_b"]


@dataclass(frozen=True)
class AuthorityDecision:
    authoritative_doc_id: str
    deviating_doc_id: str
    confidence: float
    rule: str


_MVP_RULE = "MVP-hardcoded: Doc A (60% baseline) authoritative over Doc B (90% revision)"


def authority_for(
    doc_a_id: str, doc_b_id: str, parameter_name: str
) -> AuthorityDecision:
    return AuthorityDecision(
        authoritative_doc_id=doc_a_id,
        deviating_doc_id=doc_b_id,
        confidence=1.0,
        rule=_MVP_RULE,
    )


# v2 Sprint 1: per-class authority hierarchy. Higher index = more
# authoritative for that family. Classes absent from a hierarchy fall
# back to the v1 "doc_a authoritative" rule, preserving the 261-test
# invariant.
DOC_CLASS_AUTHORITY: dict[str, list[DocClass]] = {
    "transformer_params": [
        DocClass.coordination_study,
        DocClass.relay_setting_sheet,
        DocClass.equipment_spec,         # most authoritative
    ],
    "relay_settings": [
        DocClass.coordination_study,
        DocClass.equipment_spec,
        DocClass.relay_setting_sheet,    # most authoritative
    ],
}


def resolve_authority(
    doc_a_class: DocClass,
    doc_b_class: DocClass,
    parameter_family: str,
) -> tuple[Side, str]:
    """Return ``(authoritative_side, rationale)`` for a parameter family.

    Falls back to v1's hardcoded "doc_a authoritative" when:
      - family has no entry in DOC_CLASS_AUTHORITY, OR
      - either class is DocClass.unknown, OR
      - both classes are absent from the family's hierarchy.

    The fallback preserves the v1 261-test invariant exactly.
    """
    hierarchy = DOC_CLASS_AUTHORITY.get(parameter_family)
    if (
        hierarchy is None
        or doc_a_class == DocClass.unknown
        or doc_b_class == DocClass.unknown
    ):
        return "doc_a", "v1 default (per-class hierarchy not applicable)"

    def rank(c: DocClass) -> int:
        try:
            return hierarchy.index(c)
        except ValueError:
            return -1

    a_rank = rank(doc_a_class)
    b_rank = rank(doc_b_class)
    if a_rank == -1 and b_rank == -1:
        return "doc_a", "v1 default (neither class is in family hierarchy)"
    if a_rank >= b_rank:
        return (
            "doc_a",
            f"per-class hierarchy: {doc_a_class.value} >= {doc_b_class.value} for {parameter_family}",
        )
    return (
        "doc_b",
        f"per-class hierarchy: {doc_b_class.value} > {doc_a_class.value} for {parameter_family}",
    )
