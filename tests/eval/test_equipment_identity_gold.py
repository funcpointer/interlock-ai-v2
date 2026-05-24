"""Phase 33.0a — equipment-identity gold contract tests.

Two tiers:

1. **Structural tests (run now, every CI build)** — verify the gold
   YAML loads, every attack has required fields, no invariant is
   violated structurally. These are the spec-freeze enforcement.

2. **xfail stubs (skip until Phase 33.1)** — one xfail per attack
   asserting equipment inventory / matches / mutations against the
   not-yet-implemented ``src/interlock/model/equipment.py`` +
   ``src/interlock/extract/equipment_inventory.py`` +
   ``src/interlock/align/equipment_match.py``. When schemas land, the
   xfails activate as real assertions.

Source of truth: ``fixtures/eval/equipment_identity_gold.yaml``.
Spec: ``docs/superpowers/specs/2026-05-24-sprint-9-cross-doc-entity-resolution.md``.
"""

from __future__ import annotations

import re

import pytest

from tests.fixtures.equipment.synthetic import (
    attack_names,
    attacks,
    global_invariants,
    load_gold,
)

# ----------------------------------------------------------------------
# Tier 1 — structural tests (active now)
# ----------------------------------------------------------------------


def test_gold_yaml_loads() -> None:
    """Spec freeze enforcement: gold YAML must parse cleanly."""
    gold = load_gold()
    assert gold["version"] == 1
    assert gold["status"] == "contract-frozen"
    assert "attacks" in gold
    assert "global_invariants" in gold


def test_all_14_attacks_present() -> None:
    """Spec §5 enumerates 10 attacks; peer-review patch adds 4 more.
    The contract requires exactly 14."""
    names = attack_names()
    assert len(names) == 14, (
        f"expected 14 attack fixtures (10 base + 4 peer-review); "
        f"got {len(names)}: {names}"
    )

    required = {
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
        "embedding_shortlist_true_match_at_rank_12",
    }
    missing = required - set(names)
    assert not missing, f"required attacks missing from gold: {sorted(missing)}"


@pytest.mark.parametrize("entry", attacks(), ids=attack_names())
def test_attack_has_required_fields(entry: dict) -> None:
    """Every attack must declare name, description, synthetic_inputs.
    Outcome blocks (matches / no_match / ambiguous / mutations) are
    optional per attack but at least ONE outcome block must be present."""
    assert "name" in entry
    assert "description" in entry
    assert "synthetic_inputs" in entry

    outcome_blocks = {
        "expected_matches",
        "expected_no_match",
        "expected_ambiguous",
        "expected_conflict",
        "expected_unmatched_a",
        "expected_unmatched_b",
        "expected_inventory_a",
        "expected_inventory_b",
        "expected_recall",
        "expected_context_aliases",
        "expected_legacy_flags",
        "expected_legacy_flags_v2_8",
    }
    declared = outcome_blocks & set(entry.keys())
    assert declared, (
        f"attack {entry['name']!r} declares no expected_* outcome block; "
        f"contract requires at least one"
    )


@pytest.mark.parametrize("entry", attacks(), ids=attack_names())
def test_synthetic_inputs_have_doc_a_and_doc_b(entry: dict) -> None:
    """Every attack supplies records for both docs (some may be empty
    list, but the key must exist)."""
    si = entry["synthetic_inputs"]
    assert "doc_a" in si, f"{entry['name']}: synthetic_inputs.doc_a missing"
    # doc_b can be omitted (e.g. intra_doc_three_lanes is doc_a only)
    if "doc_b" in si:
        assert "records" in si["doc_b"]
    assert "records" in si["doc_a"]


# ----------------------------------------------------------------------
# Tier 1 — global invariants (spec §2.1)
# ----------------------------------------------------------------------


def test_global_invariants_block_present() -> None:
    """Spec §2.1 invariants must be declared in gold."""
    inv = global_invariants()
    assert inv, "global_invariants block missing from gold YAML"

    required_invariants = {
        "canonical_id_no_mutable_values",
        "identity_anchors_are_immutable",
        "page_not_primary_identity",
        "ambiguous_is_valid",
        "legacy_flags_derived_only",
    }
    declared = {i["id"] for i in inv}
    missing = required_invariants - declared
    assert not missing, f"missing invariants: {sorted(missing)}"


_CANONICAL_ID_VALUE_PATTERN = re.compile(
    r":\s*\d[\d,]*\.?\d*\s*(kva|mva|kv|a|v|hz|%)",
    re.IGNORECASE,
)


@pytest.mark.parametrize("entry", attacks(), ids=attack_names())
def test_invariant_canonical_id_no_mutable_values(entry: dict) -> None:
    """§2.1 #2 — canonical_id MUST NOT contain mutable parameter
    values (digit-followed-by-unit pattern). 'transformer:1000KVA' is
    forbidden. Encoded as a regex check on every canonical_id across
    all expected_inventory_* / expected_matches blocks."""
    for block_name in ("expected_inventory_a", "expected_inventory_b"):
        for eq in entry.get(block_name, []) or []:
            cid = eq.get("canonical_id", "")
            if _CANONICAL_ID_VALUE_PATTERN.search(cid):
                pytest.fail(
                    f"{entry['name']!r} invariant violation: canonical_id "
                    f"{cid!r} in {block_name} embeds a mutable value. "
                    "Use stable anchors (context, row, part_number) instead."
                )


_PAGE_ONLY_CANONICAL = re.compile(r"^[a-z]+:p\d+$")


@pytest.mark.parametrize("entry", attacks(), ids=attack_names())
def test_invariant_canonical_id_not_page_only(entry: dict) -> None:
    """§2.1 #3 — page-only canonical_id is forbidden (page is
    tie-breaker, not primary identity). Pattern 'transformer:p3'
    without context is rejected; 'transformer:diagram:p3_loc_x' OK."""
    for block_name in ("expected_inventory_a", "expected_inventory_b"):
        for eq in entry.get(block_name, []) or []:
            cid = eq.get("canonical_id", "")
            if _PAGE_ONLY_CANONICAL.match(cid):
                pytest.fail(
                    f"{entry['name']!r}: canonical_id {cid!r} is "
                    "page-only. Page is a tie-breaker; identity needs "
                    "context, anchor, or both."
                )


@pytest.mark.parametrize("entry", attacks(), ids=attack_names())
def test_invariant_identity_anchors_not_in_parameters(entry: dict) -> None:
    """§2.1 #2 reinforced — identity_anchors must NOT appear as values
    in the same Equipment's parameters dict. 1000KVA cannot be both
    anchor and parameter."""
    for block_name in ("expected_inventory_a", "expected_inventory_b"):
        for eq in entry.get(block_name, []) or []:
            anchors = set(eq.get("identity_anchors", []) or [])
            params = (eq.get("parameters", {}) or {}).values()
            collision = anchors & {v.strip() if isinstance(v, str) else v for v in params}
            if collision:
                pytest.fail(
                    f"{entry['name']!r} {block_name}: identity_anchor "
                    f"{collision!r} also appears as parameter value. "
                    "Anchors must be IMMUTABLE; parameters are MUTABLE."
                )


# ----------------------------------------------------------------------
# Tier 2 — schema-shape tests (Phase 33.1 active; broader contract
# stays skipped until Phase 33.2/33.3/33.4 ship builders + matcher)
# ----------------------------------------------------------------------
#
# Phase 33.1 acceptance: Tier 2 no longer skips. Each attack gets
# tests that exercise the typed schemas — gold YAML lifts cleanly
# into Equipment instances, invariants enforced. Full inventory /
# match / mutation behavior tests come in later phases.


from tests.fixtures.equipment.synthetic import (  # noqa: E402
    attack,
    to_equipment_a,
    to_equipment_b,
)


@pytest.mark.parametrize("attack_name", attack_names())
def test_attack_inventory_lifts_into_typed_equipment(attack_name: str) -> None:
    """Phase 33.1 — every attack's expected_inventory_a/b dicts must
    lift cleanly into ``Equipment`` instances. Side effects:

    1. Equipment dataclass instantiates (no missing required fields,
       no type errors in literals).
    2. ``validate_equipment`` passes — all spec §2.1 invariants hold
       on the gold itself. If the gold violates an invariant, the
       lifter raises and this test fails — the gold IS the contract.
    """
    from interlock.model.equipment import Equipment

    entry = attack(attack_name)
    a_inv = to_equipment_a(entry)
    b_inv = to_equipment_b(entry)

    # Both sides return lists (possibly empty for matcher-only fixtures).
    assert isinstance(a_inv, list)
    assert isinstance(b_inv, list)
    for eq in (*a_inv, *b_inv):
        assert isinstance(eq, Equipment)
        # canonical_id non-empty and a string
        assert isinstance(eq.canonical_id, str) and eq.canonical_id
        # kind is one of the allowed Literal values
        assert eq.kind in (
            "transformer", "fuse", "breaker", "cable", "relay", "other",
        )
        # cluster_status is in the allowed set
        assert eq.cluster_status in (
            "confident_cluster", "ambiguous_cluster",
            "forbidden_cluster", "lane_conflict",
        )


@pytest.mark.parametrize("attack_name", attack_names())
def test_attack_inventory_doc_id_matches_side(attack_name: str) -> None:
    """Lifter sets ``doc_id`` from the side. Equipment from
    ``to_equipment_a`` carry ``doc_id='doc_a'``; from
    ``to_equipment_b``, ``doc_id='doc_b'``. Phase 33.4 matcher uses
    this to refuse same-side pairs."""
    entry = attack(attack_name)
    for eq in to_equipment_a(entry):
        assert eq.doc_id == "doc_a", (
            f"{attack_name}: doc_a Equipment carries doc_id={eq.doc_id!r}"
        )
    for eq in to_equipment_b(entry):
        assert eq.doc_id == "doc_b", (
            f"{attack_name}: doc_b Equipment carries doc_id={eq.doc_id!r}"
        )


@pytest.mark.parametrize("attack_name", attack_names())
def test_attack_inventory_invariants_pass_via_validator(attack_name: str) -> None:
    """Spec §2.1 invariants are enforced by
    ``model.equipment.validate_equipment``. Lifter already calls it,
    so this test confirms the gold itself doesn't violate the
    invariants — catches authoring drift if someone edits the gold
    without re-running the structural tier."""
    from interlock.model.equipment import validate_equipment

    entry = attack(attack_name)
    for eq in (*to_equipment_a(entry), *to_equipment_b(entry)):
        # Should not raise. If it did, lifter would have already raised
        # — this is the belt-and-suspenders check.
        validate_equipment(eq)


def test_phase_33_1_schemas_importable() -> None:
    """Phase 33.1 ships ``interlock.model.equipment`` with the public
    contract. Spec §10 acceptance: this import must succeed (then
    Tier 2 tests unblock automatically)."""
    from interlock.model.equipment import (
        ClusterStatus,
        ContextKind,
        Equipment,
        EquipmentKind,
        EquipmentMatch,
        EquipmentMention,
        GroundingMode,
        MatchStatus,
        SourceLane,
        validate_canonical_id_no_mutable_values,
        validate_canonical_id_not_page_only,
        validate_equipment,
        validate_identity_anchors_not_in_parameters,
    )

    # Compile-time-ish: ensure the names exist and have the expected
    # general shape. Runtime checks for Literal-typed values happen
    # via the lifter tests above.
    assert Equipment is not None
    assert EquipmentMention is not None
    assert EquipmentMatch is not None
    # Literal aliases are themselves callable in type-system terms but
    # at runtime they're just ``typing.Literal[...]`` — not callable.
    # Just verify they exist as imported names.
    _ = (EquipmentKind, SourceLane, ContextKind, GroundingMode)
    _ = (ClusterStatus, MatchStatus)
    _ = (
        validate_canonical_id_no_mutable_values,
        validate_canonical_id_not_page_only,
        validate_equipment,
        validate_identity_anchors_not_in_parameters,
    )


def test_validators_reject_known_bad_canonical_ids() -> None:
    """Negative tests for the validators themselves — confirm they
    actually trip on the patterns the spec forbids."""
    from interlock.model.equipment import (
        validate_canonical_id_no_mutable_values,
        validate_canonical_id_not_page_only,
        validate_identity_anchors_not_in_parameters,
    )

    # Mutable-value embedding — spec §2.1 invariant #2
    with pytest.raises(ValueError, match="mutable value"):
        validate_canonical_id_no_mutable_values("transformer:1000KVA")
    with pytest.raises(ValueError, match="mutable value"):
        validate_canonical_id_no_mutable_values("fuse:200A")

    # Page-only — spec §2.1 invariant #3
    with pytest.raises(ValueError, match="page-only"):
        validate_canonical_id_not_page_only("transformer:p3")

    # Anchor/parameter collision — spec §2.1 invariant #2
    with pytest.raises(ValueError, match="immutable"):
        validate_identity_anchors_not_in_parameters(
            identity_anchors=("1000 kVA",),
            parameters={"Transformer Rating": "1000 kVA"},
        )

    # Positive cases should NOT raise.
    validate_canonical_id_no_mutable_values("transformer:tcc1:row_1")
    validate_canonical_id_not_page_only("transformer:tcc1:row_1")
    validate_identity_anchors_not_in_parameters(
        identity_anchors=("tcc1", "row_1"),
        parameters={"Transformer Rating": "1000 kVA"},
    )


# ----------------------------------------------------------------------
# Tier 2 — full inventory + match + mutation contract tests
# ----------------------------------------------------------------------
# These remain SKIPPED until Phase 33.2+33.3+33.4 ship the inventory
# builder, context extraction, and matcher. Phase 33.1 only certifies
# the schemas + gold lifting.


def _inventory_builder_available() -> bool:
    try:
        import importlib
        importlib.import_module("interlock.extract.equipment_inventory")
        return True
    except ImportError:
        return False


def _matcher_available() -> bool:
    try:
        import importlib
        importlib.import_module("interlock.align.equipment_match")
        return True
    except ImportError:
        return False


_PHASE_33_2_SHIPPED = _inventory_builder_available()
_PHASE_33_4_SHIPPED = _matcher_available()


@pytest.mark.parametrize("attack_name", attack_names())
def test_attack_satisfied_by_pipeline(attack_name: str) -> None:
    """Full pipeline contract test — runs the synthetic_inputs through
    the real inventory builder + matcher and asserts every expected_*
    outcome. Unblocks when Phase 33.2 (inventory) AND Phase 33.4
    (matcher) ship. Phase 33.1 leaves this skipped."""
    if not (_PHASE_33_2_SHIPPED and _PHASE_33_4_SHIPPED):
        pytest.skip(
            f"attack {attack_name!r}: "
            f"inventory builder {'shipped' if _PHASE_33_2_SHIPPED else 'pending'}; "
            f"matcher {'shipped' if _PHASE_33_4_SHIPPED else 'pending'}. "
            "Phase 33.1 ships schemas only — tier-2 schema tests above "
            "exercise the contract this phase delivers."
        )
    # Phase 33.2+33.4 implementation note: see Phase 33.0a docstring
    # for the 8-step assertion plan once both modules import.
    pytest.fail(
        "Phase 33.2/33.4 implementation must replace this stub. See "
        "test docstring above for the 8-step assertion plan."
    )


# ----------------------------------------------------------------------
# Spec-freeze enforcement
# ----------------------------------------------------------------------


def test_spec_freeze_marker_in_gold() -> None:
    """The gold YAML carries ``status: contract-frozen``. If this
    test breaks, someone changed the gold's status — check whether
    the spec-freeze decision was reversed deliberately."""
    gold = load_gold()
    assert gold["status"] == "contract-frozen", (
        "gold YAML status changed from 'contract-frozen'. Either revert "
        "or follow up with a spec-revision PR + reviewer sign-off."
    )


def test_companion_spec_path_correct() -> None:
    """Gold YAML must point at the live spec, not a stale draft."""
    gold = load_gold()
    expected = "docs/superpowers/specs/2026-05-24-sprint-9-cross-doc-entity-resolution.md"
    assert gold["companion_spec"] == expected, (
        f"companion_spec mismatch — gold points at {gold['companion_spec']!r}, "
        f"expected {expected!r}"
    )
