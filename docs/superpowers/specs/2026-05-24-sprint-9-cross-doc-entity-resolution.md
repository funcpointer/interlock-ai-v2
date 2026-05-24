# Sprint 9 / v2.9 — Cross-Doc Entity Resolution

**Date:** 2026-05-24 (revised after double-adversarial review)
**Status:** spec — hardened, awaiting acceptance-fixture authoring before kickoff
**Baseline:** `v2.8.8-dedup-page-exact`
**Target tag:** `v2.9.0-cross-doc-entities`
**Companion reviews:**
- `2026-05-24-v2.8.x-adversarial-review.md` (session-internal)
- `2026-05-24-codex-adversarial-review.md` (Codex first pass)
- `/Users/kc/Documents/Codex/2026-05-24/take-a-look-at-this-and/sprint-9-double-adversarial-review.md` (Codex hostile double-pass — definitive)

---

## 1. Why this sprint (unchanged)

The v2.8.x patch series shipped 28 surgical fixes for symptoms of one missing core feature: **a per-document equipment inventory + cross-document entity matcher**. Codex's hostile review names the disease: *"the same concept — equipment identity — is re-derived in `exact.py`, `dedup.py`, `checklist.py`, `pair.py`, and the vision guard."* Sprint 9 makes equipment identity an explicit, auditable subsystem.

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
3. **Clustering** — mentions are clustered into Equipment objects. Cluster keys, in priority order:
   - Same `context_id` + same `row_id` (deterministic table-row grouping)
   - Same identity anchor (part number, equipment label)
   - Same diagram + nearby bbox (within bbox-radius threshold)
   - **No clustering across context_kind without strong anchor agreement** (prevents Attack 8 — p2 one-line + p5 TCC plot don't auto-merge unless they share a part number or explicit label).
4. **Parameter attachment** — mutable parameter values from clustered mentions become `Equipment.parameters`.

Inventory builder is **vision-aware but not vision-dependent**: works on text-only docs via heuristic anchors.

### 3.5 Cross-doc matcher

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

1. **Blocking keys** (deterministic, fast):
   - `kind` (transformers don't match fuses)
   - Strong identity anchor exact match (part numbers, row markers within named tables)
2. **Bipartite assignment** — global Hungarian-style optimization over the blocked candidate set. NOT greedy local pairing.
3. **Score components** (sum, bounded):
   - Identity-anchor agreement (+0.5)
   - Context agreement (table name, section) (+0.2)
   - Weak-descriptor Jaccard (+0.1)
   - Page proximity (+0.05 max; tie-breaker only)
   - **Contradiction penalty**: exact-token disagreement on identity anchors → −0.5 (blocks high-confidence match)
   - **Embedding similarity**: candidate-generation only, **never produces final match alone**
4. **Acceptance rule:**
   - Top score ≥ 0.6 AND margin over runner-up ≥ 0.1 → `matched`
   - Top score ≥ 0.6 but margin < 0.1 → `ambiguous`
   - Top score < 0.6 but blocking keys agreed → `ambiguous`
   - Contradiction penalty fired → `conflict`
   - Otherwise → `unmatched_a` / `unmatched_b`

### 3.6 Mutation classification (replaces v2.8.x flag emission)

For each `EquipmentMatch`:

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

**Pass condition for Sprint 9 implementation start:** all 10 fixtures authored + their gold YAML written. Implementation begins ONLY when fixtures exist.

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

    expected_no_match:
      # Equipment that exists in B but has no A counterpart
      - b: "transformer:tcc3_dry_type_annotation"  # the 0.15 MVA XFMR FP trap
        status: unmatched_b
        mutation: equipment_added
        severity: info  # planted FP trap

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

- **Phase 33.0** (prerequisite, ~3hr) — author 10 acceptance fixtures + their gold YAML; expand `coordination_study.yaml` to equipment level. NO code changes; data + spec only.
- **Phase 33.1** (~4hr) — `EquipmentMention` + `Equipment` schemas. Tests offline.
- **Phase 33.2** (~6hr) — `build_equipment_inventory` for text-only docs (regex + LLM-text only; no vision integration yet). All 10 acceptance fixtures pass on text-only path.
- **Phase 33.3** (~3hr) — Cross-doc matcher with bipartite assignment + contradiction penalties + ambiguous/conflict states. Unit tests cover Attacks 1–10.
- **Phase 33.4** (~3hr) — Vision-lane integration with grounding modes; `image_region_grounded` path replaces hallucination guard.
- **Phase 33.5** (~4hr) — Pipeline integration. Replaces equipment-bearing parameter paths in align/checklist. Legacy paths stay for non-equipment parameters. Switch tests per §6 gate each retirement.
- **Phase 33.6** (~2hr) — UI surface: equipment-inventory panel; reviewer can resolve `ambiguous` matches and confirm `image_region_grounded` evidence.

Tag at each phase + sprint exit `v2.9.0-cross-doc-entities`.

**Total:** ~25 hours = ~3 dev-days. The prerequisite (Phase 33.0) is ~3hr and gates everything.

---

## 11. Open questions still

The double-adversarial review left these explicit:

1. **Equipment ontology granularity.** Spec says `kind ∈ {transformer, fuse, breaker, cable, relay, other}`. Sub-types (Class L vs Class RK1 fuse) matter for some matches but not others. Where does sub-type live — in `identity_anchors` or as a separate field?
2. **Mutable parameter list.** Spec says identity_anchors are immutable; parameters are mutable. But "Transformer Rating" might be either (a transformer's nameplate kVA is usually fixed; a mutation usually means a transcription error). Need an explicit per-kind classification.
3. **Cross-document context_id matching.** doc_a's `tcc1_table_row_2` must match doc_b's `tcc1_table_row_2`. But what if the table title shifted in B revision ("TCC1" → "Coordination Curve 1")? Need a context_id alias map (cheap LLM call + cache).
4. **Reviewer override surface.** When matcher returns `ambiguous`, reviewer must resolve. UI for this is in Phase 33.6 but the persistence model (where does the override get saved? per-project?) needs design.

These don't block Sprint 9 kickoff but should be answered during Phase 33.0.

---

## 12. Help-or-hurt test (from the double-adversarial review)

> This double-adversarial pass helps if it changes the spec now. It hurts if it becomes more review theater while implementation proceeds with the current matcher contract.

Specifically: this v2 spec is **only worth the rewrite if Phase 33.0 happens before any code**. If we skip the fixture authoring and start Phase 33.1 directly, we're back to v2.8-with-nicer-nouns.

Phase 33.0 gate: 10 acceptance fixtures + gold YAML expansion committed before any `src/interlock/extract/equipment_inventory.py` exists. Enforced via a single CI check (file existence).
