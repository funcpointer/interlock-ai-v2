"""Phase 33.3 — equipment inventory builder tests.

Covers Sprint 9 attacks where inventory clustering is the contract:

- **Attack 1** three_1000kva_transformers_only_p7_mutates — same
  rating, distinct (context_id, row_id) → 3 separate Equipment, NOT
  cross-page merge.
- **Attack 3** same_table_similar_fuse_designations — part-number
  identity anchors survive; different fuse families don't merge.
- **Attack 5** vision_label_contains_mutated_value — `1000KVA XFMR`
  entity_tag is value-encoded and MUST NOT become canonical_id /
  identity_anchor.
- **Attack 6** rating_mutation_same_row_same_context — identity
  computed first, mutation lives in parameters.
- **Attack 8** one_equipment_three_mentions_across_pages — three
  mentions, same kind + same rating, different contexts, no
  contradicting anchors → ambiguous_cluster with mention_count == 3.
- **Attack 12** intra_doc_three_lanes_disagree_on_row_34 — same
  (context, row), conflicting identity anchors → lane_conflict.
"""

from __future__ import annotations

import pytest

from interlock.extract.equipment_inventory import build_equipment_inventory
from interlock.model.equipment import Equipment
from tests.fixtures.equipment.synthetic import attack, to_synthetic_records


# ---------------------------------------------------------------------------
# Output shape — every gold attack lifts without raising
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "attack_name",
    [
        "three_1000kva_transformers_only_p7_mutates",
        "rich_a_sparse_b_duplicate_transformers",
        "same_table_similar_fuse_designations",
        "same_equipment_moved_one_page_wrong_same_page_decoy",
        "vision_label_contains_mutated_value",
        "rating_mutation_same_row_same_context",
        "fuse_present_elsewhere_removed_from_matched_table",
        "one_equipment_three_mentions_across_pages",
        "rotated_label_image_only",
        "gold_truth_vs_legacy_flags",
        "context_title_renamed_same_structure",
        "intra_doc_three_lanes_disagree_on_row_34",
        "forbidden_match_row_marker_collision",
    ],
)
def test_gold_attack_inventory_builds_without_invariant_violations(
    attack_name: str,
) -> None:
    """Every attack's synthetic records pass through
    build_equipment_inventory + validate_equipment cleanly. If gold
    encodes an Equipment that violates §2.1 invariants, validate_*
    raises — this test catches gold-side drift."""
    entry = attack(attack_name)
    for side in ("doc_a", "doc_b"):
        recs = to_synthetic_records(entry, side)
        if not recs:
            continue
        inv = build_equipment_inventory(recs, doc_id=side)
        for eq in inv:
            assert isinstance(eq, Equipment)
            assert eq.doc_id == side


# ---------------------------------------------------------------------------
# Attack 1 — three 1000kVA transformers don't cross-page merge
# ---------------------------------------------------------------------------


def test_attack_1_three_transformers_stay_distinct() -> None:
    """Same kVA + same row marker `1`, distinct context_ids
    (tcc1/tcc2/tcc3). Inventory MUST produce 3 transformer Equipment,
    one per context, NOT a single merged cluster."""
    entry = attack("three_1000kva_transformers_only_p7_mutates")
    recs = to_synthetic_records(entry, "doc_a")
    inv = build_equipment_inventory(recs, doc_id="doc_a")

    transformers = [e for e in inv if e.kind == "transformer"]
    assert len(transformers) == 3, (
        f"expected 3 transformer Equipment (one per tcc); got {len(transformers)}: "
        f"{[e.canonical_id for e in transformers]}"
    )
    canonical_ids = {e.canonical_id for e in transformers}
    assert canonical_ids == {
        "transformer:tcc1:row_1",
        "transformer:tcc2:row_1",
        "transformer:tcc3:row_1",
    }
    # canonical_id must NOT embed "1000kva" (invariant #2)
    for cid in canonical_ids:
        assert "kva" not in cid.lower()


def test_attack_1_canonical_id_no_mutable_values_anywhere() -> None:
    """Invariant #2 stays hot even when many same-value records
    arrive. Strong sweep on canonical_id strings."""
    entry = attack("three_1000kva_transformers_only_p7_mutates")
    for side in ("doc_a", "doc_b"):
        recs = to_synthetic_records(entry, side)
        if not recs:
            continue
        inv = build_equipment_inventory(recs, doc_id=side)
        for eq in inv:
            assert "1000" not in eq.canonical_id
            assert "100kva" not in eq.canonical_id.lower()


# ---------------------------------------------------------------------------
# Attack 3 — fuse part-number families
# ---------------------------------------------------------------------------


def test_attack_3_distinct_fuse_part_numbers_stay_distinct() -> None:
    """Three fuse rows in the same TCC3 table. Part-number anchors
    keep them separate (each fuse becomes its own Equipment)."""
    entry = attack("same_table_similar_fuse_designations")
    inv = build_equipment_inventory(
        to_synthetic_records(entry, "doc_a"), doc_id="doc_a",
    )
    fuse_eqs = [e for e in inv if e.kind == "fuse"]
    assert len(fuse_eqs) >= 3, (
        f"expected >= 3 fuse Equipment; got {len(fuse_eqs)}: "
        f"{[e.canonical_id for e in fuse_eqs]}"
    )
    # Part numbers appear in identity_anchors.
    anchors_seen: set[str] = set()
    for eq in fuse_eqs:
        anchors_seen.update(eq.identity_anchors)
    assert "KRP-C-1600SP" in anchors_seen
    assert "LPS-RK-225SP" in anchors_seen
    assert "LPN-RK-500SP" in anchors_seen


# ---------------------------------------------------------------------------
# Attack 5 — value-bearing vision label NOT identity
# ---------------------------------------------------------------------------


def test_attack_5_vision_label_does_not_become_identity() -> None:
    """`1000KVA XFMR` is a vision entity_id that contains a mutable
    value. Phase 33.3 MUST:
      - NOT put the raw label in canonical_id
      - NOT put it in identity_anchors (its embedded value would
        violate Invariant #2)
      - Keep `1000KVA` in parameters (the value mutation IS the thing
        we want to detect cross-doc)"""
    entry = attack("vision_label_contains_mutated_value")
    inv = build_equipment_inventory(
        to_synthetic_records(entry, "doc_a"), doc_id="doc_a",
    )
    assert len(inv) == 1
    eq = inv[0]
    assert eq.kind == "transformer"
    # canonical_id contains context but NOT the value
    assert "1000KVA" not in eq.canonical_id
    assert "1000" not in eq.canonical_id
    # Value lives in parameters, not anchors
    assert "1000KVA" not in eq.identity_anchors
    assert "Transformer Rating" in eq.parameters
    assert eq.parameters["Transformer Rating"] == "1000KVA"


# ---------------------------------------------------------------------------
# Attack 6 — identity stable, mutation in parameters
# ---------------------------------------------------------------------------


def test_attack_6_rating_mutation_kept_in_parameters() -> None:
    """Same row, same context — identity is computed from
    (context, row), mutation is reflected only in parameters."""
    entry = attack("rating_mutation_same_row_same_context")
    a_inv = build_equipment_inventory(
        to_synthetic_records(entry, "doc_a"), doc_id="doc_a",
    )
    b_inv = build_equipment_inventory(
        to_synthetic_records(entry, "doc_b"), doc_id="doc_b",
    )
    # One transformer Equipment per doc.
    a_xfmr = [e for e in a_inv if e.kind == "transformer"]
    b_xfmr = [e for e in b_inv if e.kind == "transformer"]
    assert len(a_xfmr) == 1
    assert len(b_xfmr) == 1
    # canonical_id agrees across docs — identity stable.
    assert a_xfmr[0].canonical_id == b_xfmr[0].canonical_id
    # Parameter values DIFFER (mutation).
    assert a_xfmr[0].parameters.get("Transformer Rating") == "1000 kVA"
    assert b_xfmr[0].parameters.get("Transformer Rating") == "100 kVA"


# ---------------------------------------------------------------------------
# Attack 8 — ambiguous cross-context cluster
# ---------------------------------------------------------------------------


def test_attack_8_three_mentions_cluster_as_ambiguous() -> None:
    """Three mentions across (one_line p2, tcc2_diagram p5,
    transformer_schedule p7). Same kind, same rating. Different
    anchors per mention. Cluster MUST surface as a single Equipment
    with cluster_status='ambiguous_cluster' and 3 mentions."""
    entry = attack("one_equipment_three_mentions_across_pages")
    inv = build_equipment_inventory(
        to_synthetic_records(entry, "doc_a"), doc_id="doc_a",
    )
    # Should produce ONE transformer Equipment with 3 mentions —
    # NOT three separate Equipment.
    transformers = [e for e in inv if e.kind == "transformer"]
    if len(transformers) == 1:
        eq = transformers[0]
        assert eq.cluster_status == "ambiguous_cluster"
        assert len(eq.mentions) == 3
    else:
        # If Phase 33.3 hasn't fully resolved this case, surface the
        # expected shape for diagnosis.
        pytest.fail(
            f"expected 1 ambiguous_cluster Equipment with 3 mentions; "
            f"got {len(transformers)} transformer Equipment: "
            f"{[(e.canonical_id, e.cluster_status, len(e.mentions)) for e in transformers]}"
        )


# ---------------------------------------------------------------------------
# Attack 12 — intra-doc lane conflict
# ---------------------------------------------------------------------------


def test_attack_12_lane_conflict_at_same_row() -> None:
    """Three lanes (regex / llm_text / vision) emit different identity
    claims for tcc3:row_34. ONE Equipment with cluster_status =
    lane_conflict, 3 mentions."""
    entry = attack("intra_doc_three_lanes_disagree_on_row_34")
    inv = build_equipment_inventory(
        to_synthetic_records(entry, "doc_a"), doc_id="doc_a",
    )
    fuse_eqs = [e for e in inv if e.kind == "fuse"]
    assert len(fuse_eqs) == 1, (
        f"expected 1 lane-conflict fuse Equipment; got {len(fuse_eqs)}: "
        f"{[(e.canonical_id, e.cluster_status) for e in fuse_eqs]}"
    )
    eq = fuse_eqs[0]
    assert eq.cluster_status == "lane_conflict"
    assert len(eq.mentions) == 3
    # Lane priority: regex with row marker wins → primary anchor is
    # "LPN-RK-500SP" (regex source). JCN 80E preserved as weak descriptor.
    assert "LPN-RK-500SP" in eq.identity_anchors


# ---------------------------------------------------------------------------
# Mutable parameter never lands in identity_anchors
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "attack_name",
    [
        "three_1000kva_transformers_only_p7_mutates",
        "rich_a_sparse_b_duplicate_transformers",
        "vision_label_contains_mutated_value",
        "rating_mutation_same_row_same_context",
        "one_equipment_three_mentions_across_pages",
    ],
)
def test_mutable_parameter_values_never_in_identity_anchors(
    attack_name: str,
) -> None:
    """Spec §2.1 invariant #2: mutable parameter values must NOT
    appear in identity_anchors. ``validate_equipment`` catches the
    direct collision (anchor == value); this test sweeps the gold to
    confirm builder doesn't construct anchors from numeric+unit
    tokens like '1000KVA'."""
    entry = attack(attack_name)
    for side in ("doc_a", "doc_b"):
        recs = to_synthetic_records(entry, side)
        if not recs:
            continue
        for eq in build_equipment_inventory(recs, doc_id=side):
            for anchor in eq.identity_anchors:
                # Anchor must not contain digit+unit pattern.
                # validate_equipment already enforces canonical_id;
                # this test reinforces for identity_anchors.
                assert "kva" not in anchor.lower() or "-" in anchor, (
                    f"{attack_name}: anchor {anchor!r} contains mutable "
                    f"value pattern in {eq.canonical_id}"
                )


# ---------------------------------------------------------------------------
# Mentions carry source-lane + grounding through
# ---------------------------------------------------------------------------


def test_mentions_preserve_source_lane_and_grounding() -> None:
    """Every mention's source_lane + grounding round-trip from the
    synthetic input. Phase 33.4 matcher uses these for lane-conflict
    rationale + grounding-mode confidence cap."""
    entry = attack("intra_doc_three_lanes_disagree_on_row_34")
    inv = build_equipment_inventory(
        to_synthetic_records(entry, "doc_a"), doc_id="doc_a",
    )
    fuse_eqs = [e for e in inv if e.kind == "fuse"]
    assert fuse_eqs
    lanes = {m.source_lane for e in fuse_eqs for m in e.mentions}
    assert lanes == {"regex", "llm_text", "vision"}


# ---------------------------------------------------------------------------
# Cross-doc context alignment (Attack 11) — inventory accepts a
# cross_doc_contexts kwarg
# ---------------------------------------------------------------------------


def test_cross_doc_context_alignment_aliases_canonical_id() -> None:
    """When inventory builder is called with cross_doc_contexts from
    the other doc, the aliased canonical_id (Attack 11) propagates
    into canonical_id construction."""
    from interlock.extract.context import extract_contexts

    entry = attack("context_title_renamed_same_structure")
    a_recs = to_synthetic_records(entry, "doc_a")
    b_recs = to_synthetic_records(entry, "doc_b")

    b_contexts = extract_contexts(b_recs, doc_id="doc_b")
    a_inv = build_equipment_inventory(
        a_recs, doc_id="doc_a", cross_doc_contexts=b_contexts,
    )
    a_contexts = extract_contexts(a_recs, doc_id="doc_a")
    b_inv = build_equipment_inventory(
        b_recs, doc_id="doc_b", cross_doc_contexts=a_contexts,
    )
    # Both sides should derive the same aliased canonical_id.
    a_canonicals = {e.canonical_id for e in a_inv}
    b_canonicals = {e.canonical_id for e in b_inv}
    assert a_canonicals == b_canonicals, (
        f"cross-doc alias did not propagate: a={a_canonicals} b={b_canonicals}"
    )
