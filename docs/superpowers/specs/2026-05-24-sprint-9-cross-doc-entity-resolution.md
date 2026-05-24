# Sprint 9 / v2.9 — Evidence Attribution + Cross-Doc Entity Resolution

**Date:** 2026-05-24 (v3 — first-principles thesis + invariants)
**Status:** spec — hardened, awaiting acceptance-fixture authoring before kickoff. STOP REVISING; start Phase 33.0a.
**Baseline:** `v2.8.8-dedup-page-exact`
**Target tag:** `v2.9.0-evidence-graph`
**Companion reviews:**
- `2026-05-24-v2.8.x-adversarial-review.md` (session-internal)
- `2026-05-24-codex-adversarial-review.md` (Codex first pass)
- `2026-05-24-sprint-9-double-adversarial-review.md` (Codex hostile double-pass + 4 peer-review additions)

The double-adversarial review is an attack list, not a complete contract. Peer review of that file surfaced one hidden contradiction (resolved below in §3.4) and four additional attacks (11–14) now folded into §5. A subsequent first-principles critique reframed the whole sprint as an evidence-attribution problem — that thesis is now §1.

---

## 1. Thesis — evidence attribution, not text matching

Engineering document review is not primarily a text matching problem. It is an **evidence attribution problem**.

The system must answer these six questions, **in order**:

1. **What did the document visibly say?** (raw text, image regions, table structure)
2. **Where did it say it?** (page, bbox, span, context)
3. **What equipment mention does that evidence refer to?** (entity-aware extraction)
4. **Which mentions form the same equipment inside one document?** (intra-doc clustering)
5. **Which equipment in Doc A corresponds to which equipment in Doc B?** (cross-doc matching)
6. **Which parameters changed, appeared, disappeared, or became ambiguous?** (mutation classification → flags)

The v2.8.x patch series **started at step 6** (emit flags from paired records) and worked backward, deriving identity, context, and cross-doc correspondence post-hoc from string heuristics. That inversion is why "the same concept — equipment identity — is re-derived in `exact.py`, `dedup.py`, `checklist.py`, `pair.py`, and the vision guard" (Codex's diagnosis).

Sprint 9 **starts at step 1 and moves forward**. Each step produces a typed, audited artifact that the next step consumes. Flags are the bottom of the graph, not the top.

```
PDF evidence → mentions → equipment entities → cross-doc matches → parameter mutations → flags
```

---

## 2. Why this sprint

The v2.8.x patch series shipped 28 surgical fixes for symptoms of one missing core feature: **a per-document equipment inventory + cross-document entity matcher**. Codex's hostile review names the disease: *"the same concept — equipment identity — is re-derived in `exact.py`, `dedup.py`, `checklist.py`, `pair.py`, and the vision guard."* Sprint 9 makes equipment identity an explicit, auditable subsystem AND demotes `ParameterRecord` from a pairing-driver to evidence attached to equipment.

---

## 2.1 Invariants / Non-Negotiables

These are the guardrails the implementation cannot drift from. Every reviewer-facing decision, every test, every retirement of a v2.8 heuristic must respect them. Any PR that violates an invariant is rejected, not patched.

1. **`ParameterRecord` cannot create a final flag without either (a) equipment binding or (b) explicit non-equipment classification.** Records are evidence, not flag drivers.
2. **Mutable parameter values cannot be canonical equipment IDs.** `transformer:1000KVA` is forbidden. `transformer:tcc3_table_row_2` is the shape. The mutation IS the thing we're trying to detect — encoding the mutated value as identity guarantees we fail to detect it.
3. **Page number cannot be primary identity evidence.** Page locality is a tie-breaker only. Revisions reflow; identity must survive that.
4. **Embeddings cannot remove candidates from the true-match search space unless recall is tested.** Embedding is for candidate generation, never finalization. Recall ≥ 99% on gold expected_matches asserted by matcher unit tests.
5. **`ambiguous` is a valid output, not a failure.** The matcher is allowed to abstain. Reviewer resolves; the system surfaces evidence and waits.
6. **Legacy v2.8 paths must stay until switch tests prove replacement.** No retirement without paired gold-passing both with the heuristic ON and OFF. v2.8.x is the safety net during transition.
7. **Vision claims without text-layer grounding are not silently dropped.** They get `image_region_grounded` mode with bbox+crop evidence and a lower confidence cap. Hallucination guard becomes evidence-mode triage, not censorship.
8. **LLMs classify evidence; they don't own identity.** See §2.3 LLM-use policy.

---

## 2.2 Module split (the enforcement mechanism)

The module layout is not cosmetic. It is the boundary that prevents the v2.8 disease from re-emerging — where context extraction, identity clustering, and matching each get re-invented as scattered helpers in other files.

```
src/interlock/
  model/
    equipment.py          ← Data contracts: EquipmentMention, Equipment,
                            ClusterStatus, EquipmentMatch.
                            Pure dataclasses + enums. No logic.

  extract/
    context.py            ← NEW. Document/table/row/section context
                            extraction. Produces context_id, row_id,
                            column headers, sibling row signatures.
                            Owns context-alias canonicalization
                            (structural fingerprint + LLM proposer).

    equipment_inventory.py ← NEW. Mention clustering + parameter
                            attachment. Consumes ParameterRecord +
                            Span + context output. Produces list[Equipment].
                            Owns ClusterStatus assignment + lane_conflict
                            resolution.

    parameters.py         ← UNCHANGED structurally. ParameterRecord stays
                            but becomes evidence attached to equipment,
                            not a pairing driver. v2.8 alias map retained.

  align/
    equipment_match.py    ← NEW. Cross-doc bipartite assignment.
                            Consumes two list[Equipment]. Produces
                            list[EquipmentMatch] with 5 status states.
                            Owns embedding shortlist + recall test gate.

    exact.py              ← REDUCED ROLE. Used only for non-equipment-bearing
                            parameters (system voltages, doc-wide currents).
                            v2.8 heuristics here retire behind switch tests.

    semantic.py           ← REDUCED ROLE. Same boundary as exact.py.

  detect/
    equipment_mutations.py ← NEW. Mutation classification on
                            matched-equipment pairs. Produces value_change /
                            parameter_added / parameter_removed /
                            equipment_added / equipment_removed /
                            ambiguous_match / equipment_conflict flags.

    checklist.py          ← REDUCED ROLE. Becomes a sub-case of
                            equipment_mutations.py (unmatched_a in
                            table_row context). Old page-scoped logic
                            retires behind switch test.

    mismatch.py           ← REDUCED ROLE. Used only for non-equipment-bearing
                            parameters via legacy align paths.

  llm_pipeline/
    vision_extract.py     ← UPDATED. Returns claims with grounding mode
                            (text_layer_grounded / ocr_grounded /
                            image_region_grounded / heuristic). No hard drops.

    pair.py               ← REDUCED ROLE. Used only for non-equipment-bearing
                            weak pairs. Decline-override (v2.8.7) retires
                            behind switch test.
```

**The rule:** if context extraction, mention clustering, or cross-doc matching logic appears anywhere other than the named module, it's a bug. Reviewer checklist asks "does this belong in `context.py` / `equipment_inventory.py` / `equipment_match.py`?" before merge.

---

## 2.3 LLM-use policy

LLMs are powerful pattern matchers and terrible identity authorities. Sprint 9 uses them, but with explicit constraints.

**LLM is USED for:**

- **Equipment kind classification** (`inventory builder`): given a mention's text + context, classify into `{transformer, fuse, breaker, cable, relay, other}`. Constrained output schema; mention's evidence text passed as proof.
- **Context alias suggestion** (`context.py`): given two docs' table title lists, propose bipartite alias map. Reviewer confirms; alias map cached per-project.
- **Ambiguous match explanation** (`equipment_match.py`): when matcher returns `ambiguous`, LLM generates reviewer-facing rationale explaining the candidates + their evidence. Never decides.
- **Final flag rationale** (`equipment_mutations.py` → `judge`): existing significance-judge path, unchanged.

**LLM is NOT USED for:**

- **Silent identity decisions.** LLM cannot output `canonical_id = "..."` without rule-based blocking-key + score component checks first.
- **Match finalization.** LLM proposes; deterministic rules accept/reject/abstain. Bipartite assignment is hard math, not chat.
- **Replacing contradiction rules.** Hard contradictions (exact-token designation disagreement, kind mismatch) are deterministic blocks. LLM cannot override them.
- **Candidate pruning.** Embedding may rank candidates, but cannot remove them from the search space unless recall is tested.

**Cost discipline:** Every LLM call is cached. Phase 33.0a fixture authoring verifies caches work — no live API call in the matcher unit-test path.

---

## 2.4 Transition cost (v2.8.8 → v2.9 cohabitation)

The Codex first-principles critique skips the transition. This section names it.

The v2.8.8 baseline is the demo path. v2.9 builds in parallel. Cohabitation lasts ≥ Phase 33.1–33.4 (~17 hours of work + review time):

1. **Phase 33.0a–33.4** — v2.8.8 paths remain primary. v2.9 modules are added but NOT wired into the default pipeline. All v2.8.x tests + gold tests pass unchanged.
2. **Phase 33.5** — pipeline integration adds a `use_equipment_inventory: bool = False` kwarg (default OFF). When ON, equipment-bearing parameter paths route through inventory + matcher. When OFF, v2.8.8 behavior. Both modes tested.
3. **Phase 33.5 mid-sprint** — switch tests per §6 retirement table. Each retired v2.8 heuristic must pass gold both with the heuristic ON and OFF (via the new path).
4. **Phase 33.6 + post-sprint** — flip default to `use_equipment_inventory=True`. v2.8.x paths retain compile until v2.10 cleanup sprint.

**Demo path during transition:** `use_equipment_inventory=False` is the safe default. Demo continues on v2.8.8 while v2.9 ships behind the toggle. Switch happens after Phase 33.5 switch tests pass.

**What this costs:** approximately 4–6 hours of duplicate-path maintenance over the sprint. Acceptable price for not breaking the demo path.

---

## 2. Bottom line from the double-adversarial review

> Sprint 9 is the right move, but the current spec is not implementation-ready. It needs a match contract and adversarial fixtures first. Without that, v2.9 will be v2.8 with nicer nouns.

The contract pieces the v1 spec missed:

1. Equipment is a **cluster of mentions**, not a single extracted record
2. Mentions carry evidence spans / bboxes / source lane / grounding mode
3. **Identity descriptors and mutable parameters must be separated** (Attack 5 + 6)
4. Matching is **global one-to-one bipartite assignment** by default
5. One-to-many and many-to-one require **explicit output states**
6. **Ambiguity is first-class:** `matched`, `unmatched_a`, `unmatched_b`, `ambiguous`, `conflict`
7. Embedding is **candidate generation only** — never finalizer
8. Page locality is a **tie-breaker only**, not medium-confidence evidence
9. Vision-only evidence needs its **own grounding mode** + confidence cap
10. Checklist gaps must be **table/row-context gaps**, not page/value gaps
11. Gold must assert **equipment inventory and matches**, not only final flags

These are all baked into §3–§5 below.

---

## 3. Architecture (hardened)

### 3.1 Mention schema

Defined in `src/interlock/model/equipment.py`:

```python
@dataclass(frozen=True)
class EquipmentMention:
    """One observed reference to a piece of equipment in a document.

    Equipment identity is built by CLUSTERING multiple mentions — never
    by treating one mention as the canonical equipment. This is the
    fundamental shape v2.8.x got wrong: each ParameterRecord was both
    a parameter observation AND an implicit equipment claim.
    """
    doc_id: str
    page: int
    bbox: tuple[float, float, float, float] | None
    source_lane: Literal["regex", "llm_text", "vision"]
    context_kind: Literal["table_row", "diagram_label", "prose", "schedule"]
    context_id: str | None        # table title or section header
    row_id: str | None            # row marker within context_id (e.g. "34")
    evidence_text: str            # span text that supports this mention
    grounding: Literal[
        "text_layer_grounded",    # PyMuPDF text contains evidence_text
        "ocr_grounded",           # vision-OCR text contains it (rotated, image-embedded)
        "image_region_grounded",  # vision claim only, bbox + crop available
        "heuristic",              # no direct grounding (Track 1 regex with no row marker)
    ]
```

### 3.2 Equipment schema

Defined in `src/interlock/model/equipment.py`:

```python
@dataclass(frozen=True)
class Equipment:
    doc_id: str
    canonical_id: str             # stable within this doc; algorithm defined in §3.3
    kind: Literal["transformer", "fuse", "breaker", "cable", "relay", "other"]

    # v2.9 critical split: identity vs parameter
    identity_anchors: tuple[str, ...]   # row_id within context, part-number, label
    weak_descriptors: tuple[str, ...]   # "liquid", "XFMR", "TCC" (context only)
    parameters: dict[str, str]          # mutable values: rating, impedance, etc.

    mentions: tuple[EquipmentMention, ...]
    confidence: float             # of the cluster itself (how confident we are
                                  # these mentions are the same equipment)
```

### 3.3 canonical_id algorithm

Stability rules in priority order:

1. **Strong anchor present** → `canonical_id = "{kind}:{strongest_anchor}"`. Examples:
   - Fuse with explicit part number: `fuse:LPN-RK-500SP`
   - Transformer with row marker in a named table: `transformer:tcc3_table_row_2`
2. **No strong anchor but kind + context_id + row_id unique within doc** → `canonical_id = "{kind}:{context_id}:{row_id}"`. Example: `transformer:tcc1_table_row_1`
3. **Diagram-only equipment, vision-grounded** → `canonical_id = "{kind}:diagram_p{page}_loc_{bbox_centroid_quantized}"`. Stable per layout.
4. **Heuristic fallback** → `canonical_id = "{kind}:cluster_{cluster_hash}"`. Used only as last resort; carries low cluster confidence.

`canonical_id` is **never** value-encoded. `"transformer:1000KVA"` is forbidden — that's the v2.8 mistake the review names as "Attack 5: Vision Descriptor Becomes Identity Poison."

### 3.4 Inventory builder

Defined in `src/interlock/extract/equipment_inventory.py`. Context extraction (used as input) lives in `src/interlock/extract/context.py`.

```python
def build_equipment_inventory(
    records: list[ParameterRecord],
    spans: list[Span],
    page_structure: dict[int, PageStructure],
    pdf_path: str,
) -> list[Equipment]:
    ...
```

Stages:

1. **Mention extraction** — every ParameterRecord that names an equipment-bearing entity becomes a `EquipmentMention`. Vision records pass through with `grounding="image_region_grounded"` when their entity_id isn't in the PyMuPDF text (replacing the current hard-drop hallucination guard).
2. **Context attribution** — table title / section header / diagram name attached to each mention via `context_id`.
3. **Clustering** — mentions are clustered into Equipment objects with one of three statuses:

   ```python
   class ClusterStatus(StrEnum):
       confident_cluster = "confident_cluster"
       ambiguous_cluster = "ambiguous_cluster"
       forbidden_cluster = "forbidden_cluster"
   ```

   **confident_cluster** rules (strong evidence — auto-cluster):
   - Same `context_id` + same `row_id` (deterministic table-row grouping)
   - Same identity anchor (part number, equipment label)
   - Same diagram + nearby bbox (within bbox-radius threshold)

   **ambiguous_cluster** rules (plausible same equipment but no hard anchor — surface for reviewer, do NOT auto-merge silently):
   - Same `kind` across mentions
   - All mentions share the SAME mutable-parameter value (e.g. both say "1000 kVA") — value coincidence raises probability
   - No identity anchor disagreement
   - Used for Attack 8 shape: p2 one-line + p5 TCC + p7 schedule all describe a transformer with the same kVA rating but no explicit label. Reviewer confirms or splits.

   **forbidden_cluster** rules (contradictory evidence — never auto-cluster):
   - Different mutable-parameter values that aren't reconcilable (1000 kVA vs 150 kVA without label disambiguator)
   - Identity anchor disagreement (LPN-RK-500SP vs JCN 80E)

   Cross-context clustering (Attack 8) is permitted ONLY at `ambiguous_cluster` confidence with the reviewer-resolve loop. Original rule "no clustering across context_kind without strong anchor agreement" is too tight — it would block legitimate same-equipment-across-pages cases. Allowing `ambiguous_cluster` recovers them with an explicit "we're not certain" signal.

4. **Lane conflict resolution** (BEFORE parameter attachment; Attack 12) — multiple lanes claiming the same `(context_id, row_id)` slot with different identity anchors:
   - Must produce ONE Equipment cluster with `cluster_status="lane_conflict"` substate
   - Each lane's claim is preserved as a separate mention with its `source_lane` and `evidence_text`
   - Lane priority for the cluster's `identity_anchors` selection: regex with row marker > LLM ≥ 0.8 confidence > vision `text_layer_grounded` > vision `image_region_grounded` > LLM low-confidence
   - Reviewer surface: cluster shows "3 lanes disagree on this row's equipment label" with each lane's evidence

5. **Parameter attachment** — mutable parameter values from clustered mentions become `Equipment.parameters`. Conflicting values across mentions of the same equipment surface as `parameter_conflict` (separate from `lane_conflict` which is about identity).

Inventory builder is **vision-aware but not vision-dependent**: works on text-only docs via heuristic anchors.

### 3.5 Cross-doc matcher

Schema in `src/interlock/model/equipment.py`. Algorithm in `src/interlock/align/equipment_match.py`.

```python
@dataclass(frozen=True)
class EquipmentMatch:
    doc_a_equipment: Equipment | None
    doc_b_equipment: Equipment | None
    status: Literal[
        "matched",
        "unmatched_a",
        "unmatched_b",
        "ambiguous",       # multiple candidates within margin — abstain
        "conflict",        # hard contradiction (e.g. designation mismatch)
    ]
    confidence: float
    candidate_scores: tuple[tuple[str, float, str], ...]  # (cid, score, reason)
    rationale: str

def match_equipment_across_docs(
    a_inv: list[Equipment],
    b_inv: list[Equipment],
) -> list[EquipmentMatch]:
    ...
```

Matching algorithm:

1. **Context alias canonicalization** (Attack 11): before equipment-level matching, build a context-alias map. Two contexts (`context_id` values) are aliased when:
   - Structural fingerprint matches (column headers + row count + section relative position within doc)
   - OR LLM context-title classifier proposes them as aliases (constrained: input is both doc title lists; output is a bipartite alias proposal; reviewer can override per project)
   - OR per-project alias map supplies the mapping explicitly
   Context alias map persists in `Equipment.metadata["aliased_context_id"]` so the matcher uses a stable cross-doc handle.

2. **Blocking keys** (deterministic, fast):
   - `kind` (transformers don't match fuses)
   - Strong identity anchor exact match (part numbers, row markers within aliased contexts)
   - Aliased `context_id` agreement (post-canonicalization)

3. **Embedding shortlist with recall guarantee** (Attack 14):
   - Embedding generates candidate set per A equipment
   - Shortlist size: minimum k=20, auto-grown when candidate density warrants
   - Cosine threshold: include all candidates above an absolute threshold (0.3), not just top-k by rank
   - Recall test as gate: for every `expected_match` in gold, the true B equipment MUST appear in A's shortlist. Recall ≥ 99% asserted by matcher unit test.

4. **Bipartite assignment** — global Hungarian-style optimization over the blocked + shortlisted candidate set. NOT greedy local pairing. Maximizes total score subject to one-to-one constraint.

5. **Score components** (sum, bounded):
   - Identity-anchor agreement (+0.5)
   - Aliased-context agreement (+0.2)
   - Weak-descriptor Jaccard (+0.1)
   - Page proximity (+0.05 max; tie-breaker only)
   - **Contradiction penalty**: exact-token disagreement on identity anchors → −0.5 (blocks high-confidence match)
   - **Embedding similarity**: candidate-generation only, **never produces final match alone**

6. **Acceptance rule:**
   - Top score ≥ 0.6 AND margin over runner-up ≥ 0.1 → `matched`
   - Top score ≥ 0.6 but margin < 0.1 → `ambiguous`
   - Top score < 0.6 but blocking keys agreed → `ambiguous`
   - Contradiction penalty fired → `conflict`
   - Otherwise → `unmatched_a` / `unmatched_b`

7. **Forbidden-match assertion** (Attack 13): for every `expected_no_match` pair in gold, the assigned matching must NOT pair them. Test gate — matcher fails if any forbidden pair surfaces with `status="matched"`.

### 3.6 Mutation classification (replaces v2.8.x flag emission)

Defined in `src/interlock/detect/equipment_mutations.py`. For each `EquipmentMatch`:

| Match status | Action |
|---|---|
| `matched` | For each parameter, compare values across docs → `value_change` / `parameter_added` / `parameter_removed` flags |
| `unmatched_a` | Surface as `equipment_removed` flag (replaces v2.8.6 checklist gap for equipment-level removals) |
| `unmatched_b` | Surface as `equipment_added` flag (new — reviewers need to see additions) |
| `ambiguous` | Surface as `ambiguous_match` review prompt; reviewer chooses |
| `conflict` | Surface as `equipment_conflict` flag; the contradiction itself is the audit item |

Checklist gaps for fuses-in-tables become a SUB-CASE of `unmatched_a` where the unmatched equipment is in a `table_row` context.

---

## 4. Pipeline integration

```
ingest
    ↓
extract (Track 1 + Track 2 + vision)
    ↓
dedup_same_doc_records (v2.8.x — retained as cleanup, narrower role)
    ↓
build_equipment_inventory ← NEW (§3.4)
    ↓
match_equipment_across_docs ← NEW (§3.5)
    ↓
classify_mutations (§3.6)
    ↓
detect_flags (legacy path retained for non-equipment params, e.g. system voltage)
    ↓
adjudicate / judge / render
```

Inventory + matcher REPLACE the equipment-pairing inference in `align/exact.py`, `align/semantic.py` (for equipment-bearing parameters), and `detect/checklist.py`. Legacy paths stay for parameters that aren't equipment-bound (e.g. doc-wide voltages, system-level current ratings).

---

## 5. Acceptance fixtures (gate to Sprint 9 implementation start)

The double-adversarial review demands these BEFORE integration starts. They're synthetic — small purpose-built PDFs that isolate each attack vector. Each carries an equipment-level gold YAML with explicit expected inventory + matches + mutations.

### False-merge fixtures (must NOT collapse distinct equipment)

1. `three_1000kva_transformers_only_p7_mutates` — three 1000kVA transformers across p3/p5/p7; only p7 mutates to 100kVA. Expected: 3 matched equipment, 1 value_change. Forbid: any cross-page merge.
2. `rich_a_sparse_b_duplicate_transformers` — Doc A has rich descriptor (rating + impedance + voltage); Doc B has two sparse 1000KVA transformers. Expected: `ambiguous` unless non-mutable anchor distinguishes them.
3. `same_table_similar_fuse_designations` — KRP-C-1600SP and LPS-RK-225SP in same table; one removed locally but appears elsewhere. Expected: exact part-number disagreement blocks merge.
4. `same_equipment_moved_one_page_wrong_same_page_decoy` — same equipment moved p7→p8 in B; B p7 has different-equipment decoy. Expected: match by structural context, not page locality.
5. `vision_label_contains_mutated_value` — vision emits `1000KVA XFMR` as entity_id; mutation changes to `100KVA`. Expected: `value_change` on matched equipment, NOT `equipment_removed + equipment_added`.

### False-split fixtures (must NOT fail to match same equipment)

6. `rating_mutation_same_row_same_context` — same row, same table, mutated rating. Expected: 1 match + 1 `value_change`. Forbid: split into add+remove.
7. `fuse_present_elsewhere_removed_from_matched_table` — fuse removed from doc_b p7 TCC3 table; still appears on doc_b p2 one-line. Expected: gap flag iff matched table contexts agree on row presence.
8. `one_equipment_three_mentions_across_pages` — single transformer referenced on p2 one-line + p5 TCC + p7 schedule. Expected: 1 Equipment object with 3 mentions, not 3 Equipment objects.
9. `rotated_label_image_only` — equipment label rotated, PyMuPDF text-layer empty; vision OCR sees it. Expected: equipment preserved with `image_region_grounded` evidence + medium confidence (NOT dropped by hallucination guard).

### Gold-as-oracle fixture

10. `gold_truth_vs_legacy_flags` — case where v2.8.8 produces a flag set that disagrees with equipment-level gold. Equipment gold wins; v2.9 must reproduce equipment gold even though it breaks the legacy flag.

### Peer-review additions (Attacks 11–14)

11. `context_title_renamed_same_structure` — doc_a "TCC3" vs doc_b "Coordination Curve 3"; identical row structure. Context-alias canonicalization must produce aliased `context_id`, equipment in both tables must match.

12. `intra_doc_three_lanes_disagree_on_row_34` — regex says `LPN-RK-500SP`, LLM says `JCN 80E`, vision says blank for the same `(context_id, row_id)`. Inventory must produce ONE Equipment cluster with `cluster_status="lane_conflict"`, each lane's claim preserved as separate mention. Identity anchor selection follows lane priority.

13. `forbidden_match_row_marker_collision` — two rows share row marker `2` across different aliased contexts. Gold's `expected_no_match` block lists this pair as forbidden. Matcher must not match them; test asserts zero forbidden matches.

14. `embedding_shortlist_true_match_at_rank_12` — synthetic 50-equipment doc pair where true match for a specific A equipment is rank 12 by embedding. Shortlist size + cosine threshold must include rank-12 candidates. Recall test asserts true match ∈ shortlist for every gold expected_match.

### Phase 33.0 staging

The "all fixtures before code" gate stands, but split into two stages to avoid PDF authoring blocking the matcher work:

- **Phase 33.0a** (~2hr): synthetic record-level fixtures for all 14 attacks. Constructed via `ParameterRecord` / `Span` / `EquipmentMention` instances directly in pytest fixtures. Gates the matcher + inventory unit tests.
- **Phase 33.0b** (~1 day): polished PDF fixtures for ingestion + vision integration tests. Gates the e2e tests but NOT the matcher unit tests. Can land in parallel with implementation.

**Pass condition for Sprint 9 implementation start:** all 14 synthetic record-level fixtures (Phase 33.0a) authored + gold YAML written. PDF fixtures (Phase 33.0b) follow.

---

## 6. Subsumed v2.8.x heuristics (retirement plan)

Each retirement requires a **switch test**: gold passes with the heuristic ON, then ALSO passes with it OFF. Heuristics with no switch test stay until Sprint 10.

| v2.8.x | Retirement gate |
|---|---|
| v2.8.4 relaxed-tag align pool | Equipment match provides authoritative pairing → no need for relaxed pool. Switch test: all gold + acceptance fixtures pass with relaxed pool disabled. |
| v2.8.6 row-marker dedup priority flip | Inventory clusters mentions via row_id directly. Switch test: TP-3 surfaces without the priority flip. |
| v2.8.6 page-scoped checklist gap | Replaced by `unmatched_a` in `table_row` context. Switch test: FN-1 surfaces via new path + 3 false gaps (LPS-RK-225SP × 2, KRP-C-1600SP) do NOT surface. |
| v2.8.7 ambiguity-gate bypass | Equipment match disambiguates by inventory identity, not record counts. Switch test: TP-1 surfaces via new path. |
| v2.8.7 rerank decline override | Match scoring + contradiction penalties handle the tag-mismatch decline case. Switch test: TP-2 surfaces without override. |
| v2.8.7 multi-line secondary regex | Inventory builder consumes all spans + cross-line evidence within a context. Switch test: TP-3 surfaces without secondary regex. |
| v2.8.7 `_string_family` lenient prefix | Replaced by structured `kind` + `identity_anchors`. Switch test: fuse-family fixture (#3) passes without family regex. |
| v2.8.8 `_PAGE_WINDOW=0` | Dedup becomes pure within-page extraction-duplicate cleanup; inventory handles cross-page identity. Switch test: Attack 8 fixture passes. |

Retain (orthogonal correctness):
- v2.8.1 canonical parameter name alias map
- v2.8.3 cross-page asymmetric refuse in semantic
- v2.8.5 `_string_family` _NO_FAMILY sentinel (for non-equipment numeric params)
- v2.8.6 flag-level dedup by Doc-B-record-identity (still useful for legacy non-equipment-bound flag path)

---

## 7. Vision-lane integration

Replaces the current hard-drop hallucination guard with **grounding modes**:

| Mode | When | Inventory acceptance | Confidence cap |
|---|---|---|---|
| `text_layer_grounded` | entity_id substring in PyMuPDF text | Full | 1.0 |
| `ocr_grounded` | entity_id in vision-OCR text union'd with PyMuPDF | Full | 0.9 |
| `image_region_grounded` | entity_id only visible in rendered image (rotated, embedded) | With bbox+crop evidence | 0.75 |
| `heuristic` | no direct grounding | Cluster confidence drops; flag for review | 0.5 |

`image_region_grounded` requires the vision claim to include bbox coordinates; renderer can show the crop for reviewer confirmation. No more silent hallucination-guard drops.

---

## 8. Cost model

Per-doc, per-stage cost (estimated):

| Stage | Calls | Per-call | Per-doc total |
|---|---|---|---|
| Inventory builder (LLM-assisted kind classification) | ~50 records × 1 | $0.001 | $0.05 |
| Equipment matcher (deterministic; no LLM unless ambiguous) | 0 base + N for ambiguous resolution | $0.005 ambiguous tie-break | ≤ $0.02 |
| Equipment-level judge (severity, downstream effects) | ~10 matches × 1 | $0.02 | $0.20 |

**Per-review cost (cold):** ~$0.50 inventory + ~$0.04 matcher + ~$0.40 judge = ~$0.94 (down from v2.8 ~$1.50 because vision lane fires less often when inventory cluster covers the equipment already).

Caching: inventory keyed on `(pdf_path, size, mtime)`; matcher keyed on `(a_inventory_hash, b_inventory_hash)`. Warm review = $0.

---

## 9. Gold YAML expansion (prerequisite — ~2hr before Sprint 9)

Re-authored at equipment level (replaces current record-level as source of truth):

```yaml
doc_class: coordination_study
pairs:
  - id: option1-60vs90
    doc_a: fixtures/pdfs/doc_a_60pct.pdf
    doc_b: fixtures/pdfs/doc_b_90pct.pdf

    expected_inventory_a:
      - canonical_id: "transformer:tcc1_table_row_1"
        kind: transformer
        parameters: {Transformer Rating: "1000 kVA"}
      - canonical_id: "transformer:tcc1_table_row_2"
        kind: transformer
        parameters: {Transformer Rating: "1000 kVA", Transformer Impedance: "5.75 %"}
      # ... full inventory

    expected_matches:
      - a: "transformer:tcc1_table_row_2"
        b: "transformer:tcc1_table_row_2"
        status: matched
        mutations:
          - parameter: "Transformer Impedance"
            kind: value_change
            a_value: "5.75 %"
            b_value: "0.575 %"
      - a: "transformer:tcc3_table_row_2"
        b: "transformer:tcc3_table_row_2"
        status: matched
        mutations:
          - parameter: "Transformer Rating"
            kind: value_change
            a_value: "1000 kVA"
            b_value: "100 kVA"
      - a: "fuse:tcc3_table_row_34_LPN-RK-500SP"
        b: null
        status: unmatched_a
        mutation: equipment_removed
      - a: "fault_current:p2_X1"
        b: "fault_current:p2_X1"
        status: matched
        mutations:
          - parameter: "Fault Current"
            kind: value_change
            a_value: "20,000 A"
            b_value: "200,000 A"

    expected_unmatched_b:
      # Equipment in B with no A counterpart — surfaces as equipment_added
      - b: "transformer:tcc3_dry_type_annotation"  # the 0.15 MVA XFMR FP trap
        status: unmatched_b
        mutation: equipment_added
        severity: info  # planted FP trap

    expected_no_match:
      # Pairs that MUST NOT match (Attack 13). Matcher test fails if any
      # surface with status="matched". Catches false merges that don't
      # show up in the final flag stream.
      - a: "transformer:tcc3_table_row_2"
        b: "transformer:tcc1_table_row_2"
        reason: "Different aliased contexts; row marker collision is coincidence."
      - a: "fuse:LPS-RK-225SP_tcc3_table_row_31"
        b: "fuse:LPS-RK-200SP_tcc1_table_row_11"
        reason: "Different fuse families."

    explicit_ambiguous:
      # Equipment where the matcher MUST abstain (no human-clear answer)
      - description: "p2 ∆-Y annotation 5.75% vs 2% — same transformer or different sub-equipment?"
        a_anchor: "transformer:p2_one_line"
        b_anchor: "transformer:p2_one_line"
        expected_status: ambiguous
        reviewer_note: "Reviewer must resolve manually"
```

Legacy record-level expectations (`surfaced`, `suppressed`) move to a derived test:
`test_legacy_flag_view_matches_equipment_mutations` — equipment gold renders to flags; legacy view diffs against it.

---

## 10. Sequencing

All v2.9 work happens behind a `use_equipment_inventory: bool = False` pipeline kwarg (see §2.4 transition cost). v2.8.8 remains the default + demo path until Phase 33.5 switch tests pass.

- **Phase 33.0a** (prerequisite, ~2hr) — synthetic record-level fixtures for all 14 attacks + equipment-level gold YAML expansion. NO code changes; data + spec only. Gates matcher + inventory unit tests.
- **Phase 33.0b** (parallel, ~1 day) — polished PDF fixtures for ingestion + vision integration tests. Can land in parallel with Phase 33.1+; gates e2e tests only.
- **Phase 33.1** (~4hr) — `src/interlock/model/equipment.py` schemas: `EquipmentMention`, `Equipment`, `ClusterStatus`, `EquipmentMatch`. Pure dataclasses + enums, no logic. Tests offline using Phase 33.0a fixtures.
- **Phase 33.2** (~3hr) — `src/interlock/extract/context.py`: context extraction (table title, section header, row markers, column headers, sibling row signatures) + context-alias canonicalization via structural fingerprint. LLM context-title proposer constrained to schema. Unit tests cover Attack 11.
- **Phase 33.3** (~6hr) — `src/interlock/extract/equipment_inventory.py`: mention extraction, cluster status assignment (confident / ambiguous / forbidden / lane_conflict), parameter attachment, lane-conflict resolution. Text-only docs first; vision integration in Phase 33.5. All 14 record-level fixtures pass.
- **Phase 33.4** (~4hr) — `src/interlock/align/equipment_match.py`: blocking keys → embedding shortlist (recall ≥ 99% test gate) → bipartite assignment → score components → 5-state acceptance. `expected_no_match` forbidden-match test gate. Covers Attacks 1–6, 13, 14.
- **Phase 33.5** (~5hr) — `src/interlock/detect/equipment_mutations.py` + vision grounding modes (`llm_pipeline/vision_extract.py` update — no hard drops, returns grounding mode + bbox crop on image-only evidence). Pipeline integration behind `use_equipment_inventory` kwarg. Switch tests per §6 gate each v2.8 heuristic retirement. Covers Attack 9.
- **Phase 33.6** (~3hr) — UI surface: equipment-inventory panel; reviewer can resolve `ambiguous_cluster`, `ambiguous` match, `lane_conflict`, and confirm `image_region_grounded` evidence. Flip `use_equipment_inventory=True` default. v2.8.x paths retain compile until v2.10 cleanup.

Tag at each phase + sprint exit `v2.9.0-evidence-graph`.

**Total:** ~27 hours implementation + ~2hr Phase 33.0a prerequisite + 4–6hr transition-path duplicate maintenance = ~33–35 hours ≈ 4–4.5 dev-days. PDF fixtures (Phase 33.0b) parallel.

---

## 11. Open questions deferred into Phase 33.0a fixture authoring

These don't block kickoff but get answered while authoring fixtures (Phase 33.0a is where they get pinned by example):

1. **Equipment ontology granularity.** Sub-types (Class L vs Class RK1 fuse) — fixture #3 (`same_table_similar_fuse_designations`) pins the decision: sub-type lives in `identity_anchors` because exact-token disagreement must block merge.
2. **Mutable parameter list.** Per-kind classification gets baked into Phase 33.0a equipment-level gold (each Equipment in gold lists its parameters explicitly; what's not listed isn't a parameter).
3. **Reviewer override persistence model.** Per-project file at `fixtures/projects/<id>/equipment_overrides.yaml`; default empty. Phase 33.6 UI design.

---

## 12. Stop revising

This spec is v3. It has absorbed:

- Codex first-pass adversarial review (angles A–G)
- Codex hostile double-adversarial review (Attacks 1–10 + 11 missing contracts + minimum spec patch)
- Peer review of the in-repo summary (Attacks 11–14 + `ambiguous_cluster` resolution + Phase 33.0a/b split)
- Codex first-principles critique (evidence-attribution thesis + ParameterRecord demotion + module split as enforcement + LLM-use policy + invariants section)

**Further revisions are not the bottleneck.** The bottleneck is Phase 33.0a — 14 synthetic record-level fixtures + equipment-level gold YAML. Without those, the spec is theater.

**Help-or-hurt test:** this spec is only worth the rewrite cost if Phase 33.0a starts now. If the next session opens with another spec review instead of fixture-authoring, the team has chosen review theater over progress and v2.9 will be v2.8 with nicer nouns.

**Phase 33.0a gate (enforced via CI check):** the file `tests/fixtures/equipment/__init__.py` must exist before any `src/interlock/model/equipment.py` exists. A simple pre-commit hook can enforce this.

---

## Companion docs

- `2026-05-24-v2.8.x-adversarial-review.md` — session-internal review of the v2.8.x patch series
- `2026-05-24-codex-adversarial-review.md` — Codex first pass
- `2026-05-24-sprint-9-double-adversarial-review.md` — Codex hostile double-pass + peer-review patch (Attacks 11–14)
- *(this file)* — spec v3 after first-principles critique
