# Sprint 9 Double-Adversarial Review

**Source:** `/Users/kc/Documents/Codex/2026-05-24/take-a-look-at-this-and/sprint-9-double-adversarial-review.md` (Codex hostile double-pass) + appendix patch from peer review of this review
**Subject:** `2026-05-24-sprint-9-cross-doc-entity-resolution.md` v1 (pre-revision)
**Status:** attack list — not a complete contract. The Sprint 9 spec absorbs most of it. Use this as a checklist of known failure modes, not as the source of truth.

Reproduced into-repo because the review drives the v2.9 implementation gates. Peer review of this file identified four additional attacks (§§11–14 below) and one framing fix.

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

---

## Appendix: Peer-Review Findings on This Review

Peer review of the in-repo summary identified that it over-claims authority ("definitive") and compressed away sharp edges of the original (expected wrong behavior, required spec deltas, concrete acceptance semantics). Above framing is now fixed. Additionally, the peer review surfaced one hidden contradiction in the spec the original attacks did not catch, and four new attacks the original missed.

### Contradiction in v2 Sprint 9 spec: cross-context clustering rule

Attack 8 demands p2 one-line + p5 TCC + p7 schedule cluster into ONE Equipment object with three mentions. The Sprint 9 spec §3.4 clustering rule says: *"No clustering across context_kind without strong anchor agreement."* If the transformer has no explicit part-number label (common — most coordination-study transformers are described by kVA + voltage + connection only), the rule blocks the very clustering Attack 8 requires.

**Resolution:** add a third clustering state — `ambiguous_cluster`:

```python
class ClusterStatus(StrEnum):
    confident_cluster = "confident_cluster"  # strong anchor agrees across mentions
    ambiguous_cluster = "ambiguous_cluster"  # plausible but uncertain; reviewer resolves
    forbidden_cluster = "forbidden_cluster"  # contradictory evidence; never auto-cluster
```

Rules for `ambiguous_cluster`:
- Same `kind` across mentions
- All mentions share the SAME mutable-parameter value when extracted (e.g. both mentions say "1000 kVA") — the value coincidence raises probability that they're the same equipment
- No identity anchor disagreement (don't merge "1000 kVA" with "150 kVA" cluster even if same kind)
- Surfaces in UI as cluster-proposal that reviewer can confirm or split

This resolves the Attack 8 fixture while keeping the spec's safety constraint against Attack 5 (vision label as identity poison).

### Attack 11: Context Alias Drift

**Fixture shape:**
- doc_a TCC3 page header: "TCC3 — Coordination Curve #3"
- doc_b same page header: "TCC #3" or "Coordination Plot 3" or "Transformer Inrush — Curve 3"
- Same physical curve / coordination context

**Spec weakness:** Spec mentions `context_id` but does not specify how context_id is canonicalized across docs. Two docs use different titles for the same TCC table → different `context_id` → matcher treats them as different contexts → equipment in them doesn't cluster cross-doc.

**Expected wrong behavior:** False splits when title variants differ. A docs author rewords "TCC3" to "Coordination Curve 3" between revisions → all equipment in that table becomes unmatched.

**Required spec change:** `context_id` requires its own canonicalization layer. Options:
- Alias map (per-project, reviewer-editable)
- LLM context-title classifier (constrained: input doc_a + doc_b title list; output: bipartite alias proposal; reviewer confirms)
- Structural fingerprint: column headers + row count + section relative position. Two contexts with the same structural fingerprint = aliased even if titles differ.

**Acceptance fixture:** `context_title_renamed_same_structure` — doc_a "TCC3" + doc_b "Coordination Curve 3" + identical row structure → equipment in both must match.

### Attack 12: Intra-Document Lane Conflict

**Fixture shape:**
- doc_a p7 row 34: regex extracts `LPN-RK-500SP`
- doc_a p7 row 34: Track 2 LLM extracts `JCN 80E` (wrong-row attribution)
- doc_a p7 row 34: vision extracts blank (description column unreadable)

**Spec weakness:** Inventory clustering must reconcile three lanes' DIFFERENT readings of the same row before cross-doc matching even starts. Spec §3.4 says "mention extraction" then "clustering" but doesn't specify lane-conflict policy.

**Expected wrong behavior:** Either:
- (a) Inventory creates TWO Equipment objects (one from regex, one from LLM) → cross-doc matching gets confused → false matches downstream
- (b) Vision's empty reading overrides text lanes → equipment marked as not-present

**Required spec change:** Lane conflict resolution before clustering:
- Same `(context_id, row_id)` across lanes → MUST be one Equipment cluster
- Identity anchor conflicts (regex says LPN-RK-500SP, LLM says JCN 80E) → cluster status = `lane_conflict`; mention preserved per lane; reviewer or majority rule resolves
- Lane priority for identity claims: regex with row marker > LLM with confidence ≥ 0.8 > vision with `text_layer_grounded` > vision `image_region_grounded` > LLM low-confidence

**Acceptance fixture:** `intra_doc_three_lanes_disagree_on_row_34` — three lanes return different identity claims; inventory must produce one Equipment with `lane_conflict` status, not three Equipments.

### Attack 13: Expected Forbidden Matches

**Fixture shape:**
- Equipment-level gold says: doc_a `transformer:tcc3_table_row_2` matches doc_b `transformer:tcc3_table_row_2`. ✓
- Gold is silent on: doc_a `transformer:tcc3_table_row_2` should NEVER match doc_b `transformer:tcc1_table_row_2`. (Same row marker `2`, different table.)
- Matcher accidentally pairs them via fallback rules.

**Spec weakness:** Gold asserts expected matches but not forbidden matches. Final flag output might look correct (no wrong flag emitted) while the underlying match is wrong, deferring the bug to a fixture where the wrong match has visible consequences.

**Expected wrong behavior:** Sprint 9 ships with hidden false matches that pass gold; show up in production when a downstream stage exposes them.

**Required spec change:** Equipment-level gold YAML must include `expected_no_match` block enumerating pairs that MUST NOT match:

```yaml
expected_no_match:
  - a: "transformer:tcc3_table_row_2"
    b: "transformer:tcc1_table_row_2"
    reason: "Different tables; row marker collision is coincidence."
  - a: "fuse:LPS-RK-225SP_tcc3_table_row_31"
    b: "fuse:LPS-RK-200SP_tcc1_table_row_11"
    reason: "Different fuse families."
```

Matcher tests assert ZERO matches in `expected_no_match` rows.

**Acceptance fixture:** `forbidden_match_row_marker_collision` — two rows share marker `2` across different tables; expected_no_match must be respected.

### Attack 14: Embedding Shortlist Recall

**Fixture shape:**
- Doc A has 50 equipment.
- Doc B has 50 equipment.
- For a specific A equipment, the TRUE match is the 12th most embedding-similar B equipment.
- Matcher shortlists top-10 by embedding, then applies deterministic rules.

**Spec weakness:** "Embedding as candidate generation only" is necessary but not sufficient. If the shortlist truncation removes the true match, downstream rules never see it. Embedding's job becomes RECALL@k, not just rank.

**Expected wrong behavior:** True match never reaches the bipartite assignment; `unmatched_a` reported; equipment removal/addition flag emitted falsely.

**Required spec change:**
- Embedding shortlist size MUST be calibrated: minimum k=20, with k auto-grown when the candidate set is dense
- Embedding cosine threshold for shortlist inclusion (not just rank): include all candidates above a low absolute threshold (e.g. 0.3) regardless of rank position
- Recall test as gate: for each gold expected_match, the true B equipment MUST appear in A's shortlist. Matcher unit tests assert shortlist recall ≥ 99% on gold.

**Acceptance fixture:** `embedding_shortlist_true_match_at_rank_12` — synthetic 50-equipment doc pair where the true match is rank 12 by embedding; matcher must still find it.

### Phase 33.0 Fixture Authoring Risk

The original review's "all 10 fixtures before implementation" gate is good discipline. But:

- **Polished PDF fixtures are expensive.** Each requires real or synthetic engineering content + layout that triggers the attack vector. Building all 10 as PDFs could take 1–2 days alone.
- **Synthetic record-level fixtures are fast.** A `pytest` fixture that constructs `ParameterRecord` / `Span` / `EquipmentMention` instances directly costs minutes per attack.

**Practical sequencing:** Phase 33.0a (synthetic record-level fixtures, ~2hr) gates the matcher unit tests. Phase 33.0b (PDF fixtures, ~1 day) gates the ingestion + vision integration tests. Implementation can proceed against Phase 33.0a while PDF fixtures land in parallel.

---

## Updated Acceptance Fixture List

Attacks 11–14 add 4 fixtures:

11. `context_title_renamed_same_structure`
12. `intra_doc_three_lanes_disagree_on_row_34`
13. `forbidden_match_row_marker_collision`
14. `embedding_shortlist_true_match_at_rank_12`

**Total: 14 acceptance fixtures.** Each must be authored as a synthetic record-level fixture (Phase 33.0a) before matcher unit tests. PDF fixtures (Phase 33.0b) are recommended but not gating for matcher work.
