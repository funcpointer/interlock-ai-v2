"""Sprint 9 / v2.9 — equipment-identity data contracts.

Pure dataclasses + Literal aliases. **No business logic.** Per spec
§2.2: any function that DERIVES Equipment objects from extraction
output lives in ``src/interlock/extract/equipment_inventory.py``
(Phase 33.2). Any function that MATCHES Equipment across docs lives
in ``src/interlock/align/equipment_match.py`` (Phase 33.4). This
module owns the shape and only the shape.

Spec §2.1 invariants enforced as small `validate_*` helpers below
(used by tests + Phase 33.2 builders, never as silent guards inside
the dataclasses themselves — they're frozen + explicit).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal

# ---------------------------------------------------------------------------
# State literals (Phase 33.1 — final shape pinned by gold YAML)
# ---------------------------------------------------------------------------

# Top-level equipment kind taxonomy. Sub-types (Class L vs Class RK1
# fuse, liquid-filled vs dry-type transformer) live in
# ``identity_anchors`` per spec §11 deferred-Q-1.
EquipmentKind = Literal[
    "transformer",
    "fuse",
    "breaker",
    "cable",
    "relay",
    "other",
]

# Which extraction lane produced a mention. Mirrors
# ``ParameterRecord.extraction_lane`` from v2 Sprint 8.
SourceLane = Literal["regex", "llm_text", "vision"]

# Context that a mention occupies on the page. Affects clustering +
# matching rules — table rows cluster by (context_id, row_id);
# diagrams cluster by bbox proximity; etc.
ContextKind = Literal["table_row", "diagram_label", "prose", "schedule"]

# How the mention's evidence is grounded in the page. Replaces the
# v2.8 hard-drop hallucination guard with explicit modes per spec §7.
GroundingMode = Literal[
    "text_layer_grounded",   # PyMuPDF text contains evidence_text
    "ocr_grounded",          # vision-OCR text contains it (rotated, image-embedded)
    "image_region_grounded", # vision claim only; bbox+crop carries evidence
    "heuristic",             # no direct grounding (Track 1 regex, no row marker)
]

# Cluster status assigned by the inventory builder per spec §3.4.
# Drives matcher behavior + reviewer UI surface.
ClusterStatus = Literal[
    "confident_cluster",  # strong anchor agrees across mentions
    "ambiguous_cluster",  # plausible but uncertain (Attack 8 recovery)
    "forbidden_cluster",  # contradictory evidence; never auto-cluster
    "lane_conflict",      # multiple lanes claim same slot with different identity
]

# Cross-doc match status per spec §3.5. Five-state enum makes
# ambiguity + conflict first-class — never silently coerced to
# matched-or-unmatched.
MatchStatus = Literal[
    "matched",
    "unmatched_a",
    "unmatched_b",
    "ambiguous",
    "conflict",
]


# ---------------------------------------------------------------------------
# EquipmentMention — atomic unit (spec §3.1)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EquipmentMention:
    """One observed reference to a piece of equipment in a document.

    Equipment identity is built by **clustering** multiple mentions
    (see ``Equipment``). This is the fundamental shape v2.8.x got
    wrong: each ``ParameterRecord`` was both a parameter observation
    AND an implicit equipment claim. Phase 33.1 separates them.
    """

    doc_id: str
    page: int
    bbox: tuple[float, float, float, float] | None
    source_lane: SourceLane
    context_kind: ContextKind
    context_id: str | None
    row_id: str | None
    evidence_text: str
    grounding: GroundingMode


# ---------------------------------------------------------------------------
# Equipment — cluster of mentions (spec §3.2)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Equipment:
    """A clustered identity over one or more :class:`EquipmentMention`.

    Spec §2.1 invariants:
      - ``canonical_id`` MUST NOT embed mutable parameter values
        (``transformer:1000KVA`` is forbidden).
      - ``identity_anchors`` are IMMUTABLE keys (row markers, part
        numbers, stable labels).
      - ``parameters`` are MUTABLE — they're what cross-doc mutation
        detection compares.
      - ``weak_descriptors`` are context tokens (XFMR / liquid / TCC)
        that bias matching but never decide identity alone.
    """

    doc_id: str
    canonical_id: str
    kind: EquipmentKind
    identity_anchors: tuple[str, ...] = field(default_factory=tuple)
    weak_descriptors: tuple[str, ...] = field(default_factory=tuple)
    parameters: dict[str, str] = field(default_factory=dict)
    mentions: tuple[EquipmentMention, ...] = field(default_factory=tuple)
    confidence: float = 1.0
    cluster_status: ClusterStatus = "confident_cluster"


# ---------------------------------------------------------------------------
# EquipmentMatch — cross-doc pairing outcome (spec §3.5)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EquipmentMatch:
    """One pairing outcome from the cross-doc matcher.

    ``status`` is the five-state enum. ``doc_a_equipment`` /
    ``doc_b_equipment`` may be ``None`` for ``unmatched_*`` states;
    both are populated for ``matched`` / ``ambiguous`` / ``conflict``.
    """

    doc_a_equipment: Equipment | None
    doc_b_equipment: Equipment | None
    status: MatchStatus
    confidence: float = 0.0
    candidate_scores: tuple[tuple[str, float, str], ...] = field(default_factory=tuple)
    rationale: str = ""


# ---------------------------------------------------------------------------
# Validation helpers (spec §2.1 invariants made executable)
# ---------------------------------------------------------------------------
#
# These are SMALL, EXPLICIT functions — not auto-validators baked into
# the dataclasses. Phase 33.0a tests call them; Phase 33.2 inventory
# builder calls them; nothing else does. The invariants are gates,
# not silent enforcement.


# Pattern: digit-run followed by an electrical unit suffix. Matches
# the v2.8 mistake shape (transformer:1000KVA, fuse:200A, etc).
_MUTABLE_VALUE_IN_ID_RE = re.compile(
    r"\b\d[\d,]*\.?\d*\s*(kva|mva|kv|mv|ka|va|hz|°c|°f|ω|μf|%|v|a)\b",
    re.IGNORECASE,
)


def validate_canonical_id_no_mutable_values(canonical_id: str) -> None:
    """Raise ``ValueError`` when ``canonical_id`` embeds a digit+unit
    token that smells like a mutable parameter value.

    Spec §2.1 invariant #2. The most common violation is encoding
    the equipment's value rating into its identity
    (``transformer:1000KVA``), which then guarantees a value mutation
    appears as ``equipment_removed + equipment_added`` instead of
    ``value_change``.
    """
    if _MUTABLE_VALUE_IN_ID_RE.search(canonical_id):
        raise ValueError(
            f"canonical_id {canonical_id!r} embeds a mutable value "
            "token (digit+unit). Identity must be stable across "
            "mutations — use anchors like context_id + row_id or "
            "exact part numbers instead. See spec §2.1 invariant #2."
        )


# Page-only canonical_id pattern. ``transformer:p3`` is forbidden;
# ``transformer:tcc1:row_1`` or ``transformer:diagram:p3_loc_centroid``
# are both fine because they carry context.
_PAGE_ONLY_RE = re.compile(r"^[a-z]+:p\d+$")


def validate_canonical_id_not_page_only(canonical_id: str) -> None:
    """Raise ``ValueError`` when ``canonical_id`` is *solely* page-
    indexed. Page is a tie-breaker per spec §2.1 invariant #3, not
    primary identity."""
    if _PAGE_ONLY_RE.match(canonical_id):
        raise ValueError(
            f"canonical_id {canonical_id!r} is page-only. Page is a "
            "tie-breaker, not identity. Add context_id, anchor, or "
            "bbox-centroid suffix. See spec §2.1 invariant #3."
        )


def validate_identity_anchors_not_in_parameters(
    identity_anchors: tuple[str, ...],
    parameters: dict[str, str],
) -> None:
    """Raise ``ValueError`` when an identity_anchor also appears as a
    parameter value. The two roles are mutually exclusive per spec
    §2.1 invariant #2 — anchors are immutable, parameters are mutable.
    """
    if not identity_anchors or not parameters:
        return
    anchor_set = {a.strip() if isinstance(a, str) else a for a in identity_anchors}
    param_values = {
        v.strip() if isinstance(v, str) else v for v in parameters.values()
    }
    collision = anchor_set & param_values
    if collision:
        raise ValueError(
            f"identity_anchors {sorted(collision)!r} also appear as "
            "parameter values in the same Equipment. Anchors are "
            "immutable; parameters are mutable. See spec §2.1 "
            "invariant #2."
        )


def validate_equipment(eq: Equipment) -> None:
    """Run all §2.1 invariants on an Equipment instance. Raises on
    first violation. Phase 33.2+ inventory builder calls this before
    returning; Phase 33.0a tests call it directly on lifted gold."""
    validate_canonical_id_no_mutable_values(eq.canonical_id)
    validate_canonical_id_not_page_only(eq.canonical_id)
    validate_identity_anchors_not_in_parameters(eq.identity_anchors, eq.parameters)
