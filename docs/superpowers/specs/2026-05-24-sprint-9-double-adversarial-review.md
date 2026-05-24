# Sprint 9 Double-Adversarial Review

**Source:** `/Users/kc/Documents/Codex/2026-05-24/take-a-look-at-this-and/sprint-9-double-adversarial-review.md` (Codex hostile double-pass)
**Subject:** `2026-05-24-sprint-9-cross-doc-entity-resolution.md` v1 (pre-revision)
**Status:** definitive — drove the v2 hardening of the Sprint 9 spec

Reproduced into-repo because the review is the contract for v2.9 implementation.

---

## Bottom Line

Sprint 9 helps only if it creates a real, auditable equipment identity layer. The current spec does not yet do that. It says "inventory" and "cross-doc matcher," but the core identity contract is still fuzzy:

- no one-to-one / one-to-many / many-to-one policy
- no abstain state
- no contradiction scoring
- no evidence-span requirement
- no stable definition of equipment identity
- no policy for sparse-vs-rich descriptors
- no table/row-context model
- no explicit treatment of vision-only evidence
- no matcher acceptance tests that attack false merges and false splits separately

If implemented as written, Sprint 9 likely moves the v2.8.x heuristic problem into a higher-level fuzzy matcher. Better shape, same disease.

**Call:** do Sprint 9, but harden the spec first. Minimum hardening is one day, not a sprint detour.

---

## Reviewer 1: False-Merge Attacker

### Attack 1: Same Rating, Different Physical Transformers
Three `1000 kVA` transformers across p3/p5/p7; only p7 mutates to `100 kVA`. Doc B also has vision/LLM descriptor `1000KVA XFMR` on p6.
- Jaccard, page locality, and embedding all collapse them.
- TP-3 disappears one abstraction layer higher.
- **Required:** global bipartite assignment; ambiguous-match abstain state; disambiguator requirement for repeated same-kind/same-rating.

### Attack 2: Sparse Descriptor Eats Rich Descriptor
Doc A `1000KVA XFMR liquid 5.75%Z`; Doc B `1000KVA XFMR` ×2. Jaccard fails when one side is sparse.
- **Required:** typed descriptor roles (identity vs mutable vs weak). Mutable parameters must not be used as hard identity descriptors without a contradiction-aware mode.

### Attack 3: Embedding Collapse
`KRP-C-1600SP` vs `LPS-RK-225SP` in same table — embedding collapses distinct fuse families.
- **Required:** embedding may only generate candidates. Exact designation disagreement blocks finalization.

### Attack 4: Page Locality Lies
Same equipment moved p7→p8 in B; B p7 has decoy.
- **Required:** page locality is weak tie-breaker only. Structural context (table title, row neighborhood, sibling rows, column names, page role) ranks above page proximity.

### Attack 5: Vision Descriptor Becomes Identity Poison
Vision emits `1000KVA XFMR` as entity_id; mutation changes value.
- **Required:** inventory must split `entity_id` into display label / kind / immutable anchors / mutable parameter claims / evidence source. Value-bearing labels CANNOT be identity anchors.

---

## Reviewer 2: False-Split / Missing-Gap Attacker

### Attack 6: Rich Descriptor Change Causes False Split
Same row, rating mutated; descriptor fingerprint changes exactly when mutation matters.
- **Required:** identity computed BEFORE parameter comparison. Mutable disagreement routes to mutation classification, not split identity.

### Attack 7: Table Row Identity Is Under-Specified
Fuse checklist table; row marker `1` repeats across pages/tables.
- **Required:** `context_id` + `row_id` + column headers + sibling row signatures + section/title + page role. Checklist gap must be `row_missing_in_matched_table_context`, not raw-value-missing-on-page.

### Attack 8: Same Equipment Across Pages Splits
p2 one-line + p5 TCC + p7 schedule reference the same transformer.
- **Required:** Equipment is a cluster of `EquipmentMention` objects; each mention carries page, bbox, source lane, context, claims.

### Attack 9: Vision-Only Evidence Dropped
Rotated label visible only in rendered image.
- **Required:** vision claim schema needs grounding modes: `text_layer_grounded` / `ocr_grounded` / `image_region_grounded` / `ungrounded_rejected`. Inventory accepts `image_region_grounded` with bbox/crop + confidence cap.

### Attack 10: Gold Backfills Current Bugs
Existing gold encodes v2.8 quirks.
- **Required:** gold re-authored at equipment level — expected inventory, matches, mutations, add/remove, ambiguous cases, non-goals. Record-level flags become derived outputs.

---

## Missing Architecture Contracts

1. Equipment is a cluster of mentions, not a single extracted record.
2. Mentions must carry evidence spans/bboxes and source lane.
3. Identity descriptors and mutable parameters must be separated.
4. Matching must be global one-to-one bipartite assignment by default.
5. One-to-many and many-to-one require explicit output states.
6. Ambiguity must be first-class: `matched`, `unmatched`, `ambiguous`, `conflict`.
7. Embedding is candidate generation only.
8. Page locality is a tie-breaker only, not medium-confidence evidence.
9. Vision-only evidence needs its own grounding mode.
10. Checklist gaps must be table/row-context gaps, not page/value gaps.
11. Gold must assert equipment inventory and matches, not only final flags.

---

## Acceptance Gate

10 fixtures must exist before Sprint 9 integration starts:

| # | Fixture | Tests |
|---|---|---|
| 1 | three_1000kva_transformers_only_p7_mutates | no false merge |
| 2 | rich_a_sparse_b_duplicate_transformers | abstain on sparse-vs-rich |
| 3 | same_table_similar_fuse_designations | exact designation blocks merge |
| 4 | same_equipment_moved_one_page_wrong_same_page_decoy | structural context > page locality |
| 5 | vision_label_contains_mutated_value | value_change, not add+remove |
| 6 | rating_mutation_same_row_same_context | identity before mutation |
| 7 | fuse_present_elsewhere_removed_from_matched_table | context-aware gap |
| 8 | one_equipment_three_mentions_across_pages | cluster, not split |
| 9 | rotated_label_image_only | preserve via image_region_grounded |
| 10 | gold_truth_vs_legacy_flags | equipment gold > legacy flag gold |

Pass condition: no false merge in 1–5, no false split in 6–9, equipment-level gold beats legacy in 10.

---

## Help-or-Hurt

This double-adversarial pass helps if it changes the spec now. It hurts if it becomes more review theater while implementation proceeds with the current matcher contract.

**Hard call:** Sprint 9 is the right move, but the current spec is not implementation-ready. It needs a match contract and adversarial fixtures first. Without that, v2.9 will be v2.8 with nicer nouns.
