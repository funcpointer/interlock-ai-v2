# Sprint 9 / v2.9 — Cross-Doc Entity Resolution

**Date:** 2026-05-24
**Status:** spec draft (pre-Codex-rescue findings)
**Baseline:** `v2.8.7-fe-4of4`
**Target tag:** `v2.9.0-cross-doc-entities`

---

## 1. Why this sprint

The v2.8.x patch series (5 tags: v2.8.1 → v2.8.7) shipped 23 surgical fixes for symptoms of one missing core feature: **a per-document equipment inventory + cross-document entity matcher**. Each FE run reveals a new flake the offline tests don't catch because the offline tests have a cleaner record set.

The v2.8.x patches add value but don't compound:
- v2.8.4 relaxed-tag align pool unblocks tag-mismatch pairs
- v2.8.5 `_string_family` sentinel unblocks numeric-leading raw values
- v2.8.6 row-marker dedup priority + flag dedup + page-scoped gap
- v2.8.7 ambiguity-gate bypass, rerank decline override, multi-line regex, lenient family prefix

Each one fixes a real bug. Together they're brittle because the pipeline still doesn't know "doc_a row 2 transformer" is the same physical equipment as "doc_b row 2 transformer". It infers from value-encoding entity_tags, row markers, and y-positions — all of which break in non-trivial layouts.

Sprint 9 replaces the inference chain with an explicit, audited equipment map.

---

## 2. Goals

- Per-document **equipment inventory**: every transformer / fuse / cable / breaker the doc references, with stable ID, type, page locations, and parameter values.
- Cross-document **entity match**: for every doc-A equipment, find the doc-B equipment (or "missing").
- Detect mode shifts from "compare values for paired entities" to "flag unpaired entities as checklist gaps" — the existing v2.8.6 gap detector becomes the OFFICIAL gap path.
- Drop the v2.8.x heuristic patches that the new layer subsumes (clean up tech debt).

**Non-goals (deferred):**
- Audit chain instrumentation (was deferred from Sprint 7; defer again).
- Multi-project entity aliases (per-project entity hint hooks).
- Embedding-based parameter-name clustering (Class E noise — separate sprint).

---

## 3. Architecture

### 3.1 EquipmentInventory schema

```python
@dataclass(frozen=True)
class Equipment:
    doc_id: str
    canonical_id: str           # stable identifier within this doc
    kind: Literal["transformer", "fuse", "breaker", "cable", "relay", "other"]
    descriptors: tuple[str, ...]  # ["1000KVA", "XFMR", "liquid", "5.75%Z"]
    pages: tuple[int, ...]
    parameters: dict[str, str]  # {"Transformer Rating": "1000 kVA", ...}
    confidence: float
```

### 3.2 InventoryBuilder

```python
def build_equipment_inventory(
    records: list[ParameterRecord],
    spans: list[Span],
    page_structure: dict[int, PageStructure],
) -> list[Equipment]:
    ...
```

Implementation: cluster records by (page-neighborhood, entity_tag, value-coherence). On diagram pages, use vision lane's entity_kind+entity_id directly. On table pages, group by row marker. On prose pages, infer from descriptor co-occurrence within a paragraph.

### 3.3 EntityMatcher (cross-doc)

```python
@dataclass(frozen=True)
class EquipmentMatch:
    doc_a_equipment: Equipment | None
    doc_b_equipment: Equipment | None
    confidence: float
    rationale: str

def match_equipment_across_docs(
    a_inv: list[Equipment],
    b_inv: list[Equipment],
) -> list[EquipmentMatch]:
    ...
```

Matching strategy:
1. **Exact descriptor match** (Jaccard ≥ 0.8 on descriptor tuples). High confidence.
2. **Kind + page locality** (same kind, overlapping page set). Medium confidence.
3. **Fingerprint embedding** (Voyage on `kind + descriptors`, cosine ≥ 0.85). Low-medium.
4. **Unmatched**: equipment present in one doc only → checklist gap candidate.

### 3.4 Pipeline integration

```
extract (Track 1 + Track 2 + vision)
    ↓
dedup_same_doc_records
    ↓
build_equipment_inventory ← NEW
    ↓
entity_bind (uses inventory for grounding; replaces v2.8.1 diagram-skip)
    ↓
align_exact / align_semantic (now entity-aware via inventory)
    ↓
match_equipment_across_docs ← NEW
    ↓
detect_flags + detect_checklist_gaps (uses match results)
```

Inventory becomes the spine. Alignment + detection consult it instead of inferring from raw entity_tag strings.

### 3.5 Mutation classification

For matched equipment, classify the mutation type per parameter:
- `value_change` (1000 kVA → 100 kVA): existing flag path
- `parameter_added` (Doc B has impedance Doc A doesn't): new path, lower severity
- `parameter_removed` (Doc A has it, Doc B doesn't): new path

For unmatched equipment:
- `equipment_removed` (in A, not in B): checklist gap (v2.8.6 path)
- `equipment_added` (in B, not in A): noteworthy but lower severity

---

## 4. Replaces / supersedes

These v2.8.x heuristics get retired when v2.9 ships:

| v2.8.x | Subsumed by |
|---|---|
| v2.8.4 relaxed-tag align pool | Entity match provides authoritative pairing; relaxed pool no longer needed |
| v2.8.6 row-marker dedup priority flip | Inventory uses positional anchors directly; dedup priority becomes simpler |
| v2.8.6 page-scoped checklist gap | Replaced by `equipment_removed` classification on match results |
| v2.8.7 ambiguity-gate bypass | Entity match disambiguates by inventory identity, not record counts |
| v2.8.7 rerank decline override | Rerank no longer needed for tag-mismatch cases (entity match resolves them) |
| v2.8.7 multi-line secondary regex | Inventory builder consumes all spans + cross-line evidence |

Retain:
- v2.8.1 canonical parameter name alias map (orthogonal)
- v2.8.3 cross-page asymmetric refuse in semantic (still useful as guardrail)
- v2.8.5 `_string_family` sentinel (still useful for non-equipment params)
- v2.8.7 `_string_family` lenient prefix (orthogonal correctness fix)

---

## 5. Test surface

Required new tests:
- `tests/extract/test_equipment_inventory.py` — single-doc inventory builder, ~10 tests
- `tests/extract/test_entity_match.py` — cross-doc matcher, ~10 tests
- `tests/eval/test_gold_assertion.py` — keep all 8 current tests + add 4 more covering equipment-level cases (1000kVA equipment unchanged in B → no flag; mutated → flag; removed → gap; added → notice)

Required gold yaml additions:
- Equipment IDs explicit (e.g. "doc_a row 2 = transformer slot at TCC3 inrush")
- Equipment-level expectations: what equipment SHOULD match, what should be flagged as gap

---

## 6. Open questions for Codex's diagnosis

Codex `rescue` agent is investigating v2.8.7's TP-3 + FN-1 FE-mode failures (launched 2026-05-24 10:10). Findings will inform:

1. Whether v2.8.7 multi-line regex is structurally insufficient (vs just buggy)
2. Whether dedup priority on row markers helps or hurts in real layouts
3. Whether the inventory builder needs vision-lane integration as a *requirement* not a fallback
4. Cost ceiling: building inventory adds another LLM pass — what's the budget?

When Codex reports, this spec gets a `## 7. Codex-rescue findings` section and any architectural changes folded in.

---

## 7. Sequencing

- **Phase 33.1** — Equipment schema + per-doc inventory builder. Tests offline.
- **Phase 33.2** — Cross-doc matcher. Tests use synthetic equipment lists.
- **Phase 33.3** — Pipeline integration. Replaces existing align/gap with inventory-mediated path. Gates: all v2.8.x gold tests still pass + new equipment tests pass.
- **Phase 33.4** — Retire subsumed heuristics. PR-by-PR with regression-test gate.
- **Phase 33.5** — UI surface: inventory panel showing matched equipment + gaps explicitly. Reviewer can override matches.

Tag at each phase + sprint exit `v2.9.0-cross-doc-entities`.

---

## 8. Cost + risk

| Risk | Mitigation |
|---|---|
| Inventory builder is itself an LLM pass — extra latency + cost | Make it cached + opt-in initially (`use_inventory: bool = True`) |
| Bad inventory → bad matches → worse flags than current | A/B gate on gold tests before retiring v2.8.x patches |
| Vision-lane stochasticity persists | Inventory consolidates evidence across vision + LLM + regex; less per-call sensitivity |
| Scope creep (audit chain, multi-project) | Explicit non-goals above; defer to Sprint 10+ |

Estimated effort: 1–2 days for Phase 33.1–33.3 minimum viable subsystem; +1 day for clean retirement + UI. Total ~3 days.

---

## 9. Decision needed before kickoff

- Codex-rescue findings (in-flight): if a quick patch unblocks TP-3/FN-1, slot it before Sprint 9 to avoid burning more demo time on this fixture
- Sprint 9 scope: minimum viable (Phase 33.1–33.3) vs full (33.1–33.5)
- Gold yaml expansion timing: now (write the equipment-level expectations during 33.1) vs after (add when reviewer-tested)
