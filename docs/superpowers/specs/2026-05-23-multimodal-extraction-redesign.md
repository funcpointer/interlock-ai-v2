# Multi-Modal Extraction + Entity Grounding Redesign

**Status:** Design doc. Not approved for implementation. Captures the first-principles diagnosis of the v2.7 entity-binding failure class + proposes a multi-sprint architectural extension.

**Date:** 2026-05-23
**Author:** AI session (Claude) + human review pending
**Supersedes:** Sprint 7 "audit chain" / "pattern registry" patches considered earlier in the session.

---

## 0. TL;DR

The v2.7 pipeline assumes PyMuPDF text-layer y-coordinates equal visual y-coordinates. **This is true for prose and tables; false for diagram pages.** On diagrams, the LLM entity detector returns visually-correct y-bands, but PyMuPDF spans report PDF text-layer draw-order y — a different coordinate system. The binder's y-enclosure + nearest-y-fallback then mis-binds extraction records to wrong entities, producing high-confidence false positives like the user's reported `LPS-RK-400SP ≠ LPS-RK-100SP` flag with `entity_tag=LPS-RK-100SP` on both records.

This is **not** a calibration bug. It's an architectural assumption violated by an entire class of pages. Engineering documents span four orthogonal axes the current pipeline conflates: **source** (born-digital vs scanned/OCR), **layout** (prose / table / diagram / schematic / mixed), **doc class** (spec / study / drawing / BOM / ...), and **cross-doc role** (single-doc review vs multi-doc cross-reference where naming conventions differ).

Fixing it requires:

1. **Per-page extraction-modality routing** (source × layout matrix → distinct extraction lanes; OCR-quality awareness baked in).
2. **Span-identity binding** instead of y-coordinate binding (drop the heuristic; bind by which extraction span the value came from).
3. **Typed entity model** (kind, canonical_id, location_hint, source_spans) replacing flat `entity_tag: str`.
4. **Cross-document entity resolution** as a first-class pipeline stage (so Doc A's `T-1` resolves to Doc B's `XFMR-001` before value comparison runs).
5. **OCR-modality-aware extraction lane** (when PyMuPDF returns whole-page bbox via vision-OCR fallback, no per-record y exists — entity grounding must operate on text proximity within the OCR'd span, not on y).
6. **Per-project entity-alias override** (`fixtures/projects/<id>/entity_aliases.yaml`) — when LLM resolution is uncertain or wrong, reviewer declares ground truth.
7. **Pipeline-pass audit chain** so every Track's contribution to a flag is auditable and revertable.
8. **Explicit no-overfitting test matrix** (§10) — design must pass synthetic cases across all four axes, not just the Option 1 false-positive.

Estimated scope: 4 sprints (Sprint 7 audit + structure-classifier; Sprint 8 vision lane for diagrams + OCR-modality routing; Sprint 9 typed EntityRef + cross-doc resolution + project aliases; Sprint 10 test-matrix gold corpus).

---

## 1. The bug, in one paragraph

A reviewer ran the pipeline on the locked Option 1 fixture (`doc_a_60pct.pdf` + `doc_b_90pct.pdf`). A flag surfaced with header `🔴 %Z · Δ 65.2% · confidence 0.96 · 🏷️ A:LPS-RK-100SP / B:LPS-RK-200SP · 📜 IEEE C57.12.00-2015` and rationale `LPS-RK-400SP ≠ LPS-RK-100SP — Fuse rating differs by 4×`. The equipment binding shows both records bound to `LPS-RK-100SP`, even though the raw values are different fuse part numbers. The Standards judge confidently cited IEEE C57.12.00-2015 as if it applied. The flag is wrong: these are different fuses on different circuits in an Eaton coordination tutorial diagram, not a same-equipment value mismatch.

## 2. Reproduction + data

### 2.1 Diagnostic script (committed in this design's branch)

`scripts/diagnose_p6_y_alignment.py` dumps:
- Page 6 entity detector output (with y-coords)
- Page 6 Track 1 extracted records (with y-coords)
- Page 6 raw PyMuPDF text-layer lines

Run output:

```
=== doc_a p6 ===

Detector returned 9 entities:
  y=[   30.0..   50.0] range=  20.0 kind=section     label='Time Current Curve #2 (TCC2)'
  y=[   60.0..   80.0] range=  20.0 kind=equipment   label='KRP-C-1600SP'
  y=[   80.0..  100.0] range=  20.0 kind=equipment   label='LPS-RK-400SP'
  y=[  100.0..  120.0] range=  20.0 kind=equipment   label='LPS-RK-100SP'
  y=[  140.0..  160.0] range=  20.0 kind=circuit     label='400A Feeder'
  y=[  350.0..  370.0] range=  20.0 kind=equipment   label='JCN80E'
  y=[  400.0..  420.0] range=  20.0 kind=equipment   label='LPS-RK-100SP'
  y=[  540.0..  560.0] range=  20.0 kind=equipment   label='JCN 80E'
  y=[  720.0..  740.0] range=  20.0 kind=equipment   label='KRP-C-1600SP'

Track 1 records on p6 (7):
  y=  225.4 name=System Voltage    raw='13.8 kV'         NEAREST ['400A Feeder'] (dist 75.4)
  y=  254.7 name=Fuse Designation  raw='LPS-RK-100SP'    NEAREST ['400A Feeder'] (dist 104.7)
  y=  282.2 name=Fuse Designation  raw='KRP-C-1600SP'    NEAREST ['JCN80E']     (dist 77.8)
  y=  344.5 name=%Z                raw='5.75 %'          NEAREST ['JCN80E']     (dist 15.5)
  y=  405.1 name=Fuse Designation  raw='KRP-C-1600SP'    ENCLOSED-BY ['LPS-RK-100SP']
  y=  460.6 name=Fuse Designation  raw='LPS-RK-400SP'    NEAREST ['LPS-RK-100SP'] (dist 50.6)
  y=  522.2 name=Fuse Designation  raw='LPS-RK-100SP'    NEAREST ['JCN 80E']     (dist 27.8)
```

### 2.2 What the data shows

Every `Fuse Designation` record's PyMuPDF y is far from the detector's y for the same label:

| Label | Detector visual y | Record PyMuPDF y | Δ |
|---|---:|---:|---:|
| `LPS-RK-400SP` | 80–100 | 460.6 | ~360 |
| `LPS-RK-100SP` (1st) | 100–120 | 254.7 | ~140 |
| `LPS-RK-100SP` (2nd) | 400–420 | 522.2 | ~110 |
| `KRP-C-1600SP` (1st) | 60–80 | 282.2 | ~210 |

The y-coordinates are unrelated. PyMuPDF text-layer y reflects **draw order** in the PDF — the order the original drawing tool emitted labels — not visual layout position. On a vector diagram (TCC plot), draw order is arbitrary.

Tables and prose work because PyMuPDF text-layer y *does* match visual y when text is laid out in reading order. Diagrams break the assumption.

### 2.3 The mis-binding chain

1. Record `LPS-RK-400SP` at y=460.6 has no entity enclosure (no detector entity covers y=460).
2. Binder falls back to nearest-y: `LPS-RK-100SP` at y=400-420 (distance 50.6) wins.
3. Record `LPS-RK-100SP` at y=522.2 has no enclosure either; nearest is `JCN 80E` at y=540-560 (distance 27.8) — wins. But for the cross-doc pair shown by the user, the SAME records on Doc B differ slightly; one ended up bound to `LPS-RK-100SP` (likely from a sibling on Doc B's same page).
4. Phase 19's same-tag rule sees `entity_tag=LPS-RK-100SP` on both sides → allows the pair.
5. `pairing_confidence=1.00` because the rule fired cleanly. No reranker trigger (≥ 0.75).
6. LLM judge cites IEEE C57.12.00-2015 because the parameter is `%Z` (per the registry) — except this isn't a %Z mismatch, it's a Fuse Designation mismatch. Two bugs compound: parameter mislabeling + entity misbinding.

### 2.4 Why the demo couldn't have caught this earlier

The Sprint 4.5 live exit-gate tested two specific known cases (200A/400A Feeder + 77/42 Motor FLA). It tested **flag suppression**, not entity-binding correctness. A spuriously created flag with wrong binding passed through because the test heuristic looked at parameter name and raw values, not entity binding correctness.

The Sprint 6 per-class gold harness *would* catch this if the gold set encoded "these two records should NOT pair." We have no such case in the seed gold yet — the seed only covers TPs and a single FP trap, not the wrong-binding class.

---

## 3. Root-cause class

The failure is one instance of a broader class: **the pipeline implicitly assumes all pages are text-flow documents**. Three specific assumptions break on engineering diagrams:

1. **Position assumption.** PyMuPDF text-layer y ≈ visual y. False on diagrams.
2. **Spatial-grouping assumption.** Nearby labels in y describe the same logical entity. False on diagrams — circuit ID and equipment ID may be visually adjacent but logically belong to different circuits.
3. **Linear-reading assumption.** Text extracted top-to-bottom reflects the document's information order. False on diagrams — the canonical reading is the topology (a graph), not a line of text.

Engineering documents commonly mix these structures within a single PDF:
- Cover sheets (prose)
- Specification sheets (tables)
- Schematics + one-line diagrams (vector graphics with embedded text)
- Coordination study reports (mix of prose + curves + tables)

A pipeline that treats every page as text-flow will systematically fail on schematic / one-line pages, which are the most safety-critical content in the demo's domain.

---

## 3.5 The four scope axes — why this is not a one-fix problem

The reported failure is one point in a much larger problem space. The pipeline must handle the **product** of these axes, not any single column:

### Source axis
- **Born-digital, clean text layer.** PyMuPDF text + bbox are reliable. Default v1 assumption.
- **Born-digital, diagram with text layer.** PyMuPDF returns labels but y-coords are draw-order (this design's reported failure).
- **Scanned with sidecar OCR.** Old PDFs include pre-baked OCR text layer. Quality variable; PyMuPDF reads it; bbox y is OCR-derived (better than draw-order but errors exist).
- **Scanned, no text layer.** Phase 20 `enable_vision_ocr` path: Sonnet 4.5 Vision returns whole-page text with bbox=(0, 0, page_width, page_height). **No per-record y exists at all.**
- **Mixed within one PDF.** Cover page is scanned; spec sheet is born-digital. Each page may need different handling.

### Layout axis
- **Prose** (multi-line paragraphs).
- **Table** (Camelot-detectable grid).
- **Diagram** (TCC plot, one-line, schematic — labels at arbitrary positions).
- **Form** (key-value pairs in callout boxes).
- **Mixed** (one page combines prose paragraph + a small table + a schematic snippet).

### Doc-class axis (Sprint 1 — already routed)
- Equipment spec / coordination study / relay setting sheet / BOM / civil drawing / HVAC schedule / P&ID / one-line diagram / unknown.

### Cross-doc role axis
- **Single-doc review.** No cross-reference. Internal consistency only.
- **Two docs, same conventions.** Both use same equipment IDs. Direct entity-id match works (current behavior).
- **Two docs, different conventions.** Doc A: `T-1`, Doc B: `XFMR-001`. **Needs explicit cross-doc entity resolution.**
- **Two docs, different scope.** Doc A covers a substation; Doc B is just one transformer. Subset matching required.
- **Two docs, different classes.** Doc A spec vs Doc B study. Different vocabularies for same concepts. Requires both doc-class routing AND entity resolution.
- **Asymmetric quality.** Doc A is born-digital with good entity detection; Doc B is scanned with poor entity detection. Cross-doc pair must be resilient to one-sided entity loss.

### Implication

The pipeline's current architecture handles **one column of each axis**:
- Source: born-digital prose.
- Layout: prose.
- Doc class: any (Sprint 1 routes correctly).
- Cross-doc role: same-conventions only.

Every other combination either silently fails (this design's reported case) or works by accident. Sprints 7–10 must be designed to handle the full matrix — **not the union of point fixes**.

---

## 4. First-principles design

### 4.1 Two coordinate spaces, never mixed

Make the distinction explicit:
- **Image coordinate space:** where the page is rendered visually (the PNG at 300dpi the detector saw). Y here matches what a human sees.
- **Text-layer coordinate space:** the y a PyMuPDF span reports. On prose/tables, equal to image y; on diagrams, arbitrary.

The binder must never compare a value from one space to a position in the other. Two implementation options:

**Option A — Drop y-coordinate binding entirely.** Detector returns *which text spans* are entity labels, not y-coords. Binder matches records to entities by checking which span the record was extracted from (or near in the same span text). Pure span-identity binding. Eliminates the coordinate-space concept.

**Option B — Normalize both spaces.** For each PyMuPDF span, locate its rendered position in the image (via OCR-from-image or vision query) and store the *image* y on the record. Then binder operates entirely in image space.

A is simpler. B is more expensive but works for vision-extracted entities that have no corresponding text-layer span. Recommended: **A as default, B as fallback when vision extraction outpaces PyMuPDF text coverage.**

### 4.2 Per-page extraction-modality routing (source × layout matrix)

Each page is routed by the cross of **source** (born-digital text-layer quality) and **layout** (prose / table / diagram). The matrix:

| Source ↓ / Layout → | Prose | Table | Diagram |
|---|---|---|---|
| **Born-digital, clean** | Track 2 LLM text extraction | Track 1 regex + Camelot rows | **NEW: Vision lane** (Sonnet 4.5 Vision on the rendered page) |
| **Born-digital, diagram-callouts** | (rare; treat as prose) | (rare; treat as table) | **NEW: Vision lane** (text-layer y is unreliable per §3.5 + §4.1) |
| **Scanned, sidecar OCR** | Track 2 LLM text extraction with low-confidence-flag if OCR confidence < 0.85 | Track 1 regex + Camelot rows; flag low-confidence | **NEW: Vision lane** |
| **Scanned, no text layer** (Phase 20 fallback) | **NEW: OCR-modality lane** (§4.8) — full-page text from Sonnet 4.5 Vision, span-identity binding within the OCR'd text | (same) | **NEW: Vision lane** (already vision-based; just adopt the new structured-output prompt) |

**Source detection** runs at ingest time before any extraction:
- PyMuPDF reports text-layer coverage; pages with <80 native chars get the existing Phase 20 vision OCR fallback (already shipping).
- For pages with native text, a tiny structural classifier (prototyped in `scripts/diagnose_page_structures.py`) maps layout: prose / table / diagram.

**Routing decision is per-page, not per-doc.** A coordination study with a prose cover, a tabular fault-current summary, and 6 schematic pages gets prose lane for the cover, table lane for the summary, vision lane for the schematics — all in one review.

Heuristic prototype already validated on Option 1: pages 2-8 → `diagram-callouts` (route to vision); page 1 → `table-or-mixed` (route to table+regex); page 9 → `prose` (route to LLM text extraction). Tune thresholds on broader corpus before shipping.

### 4.3 Vision extraction for diagrams

On diagram pages, render the page as a PNG and send to Claude Sonnet 4.5 Vision with a structured-output prompt that returns entity-grounded claims directly:

```json
[
  {
    "entity_kind": "equipment",
    "entity_id": "LPS-RK-400SP",
    "entity_location_hint": "main_feeder",
    "parameter_name": "Fuse Designation",
    "raw_value": "LPS-RK-400SP",
    "visual_evidence": "located mid-page-left, labelled 'Main Feeder'"
  },
  ...
]
```

Key properties:
- Entity and value are returned **together** — no post-hoc binding needed.
- `entity_location_hint` is a free-text disambiguator for cases where two devices share an ID (e.g., two identical 100A fuses on different circuits). Optional; LLM provides when topology is clear.
- `visual_evidence` is the LLM's self-grounding — auditable by the reviewer.

Cost: ~$0.02 per diagram page (single Sonnet 4.5 Vision call with the page image). For a 9-page coordination study with 7 diagram pages: ~$0.14 added per cold run. Cached on PDF content hash.

### 4.4 Typed Entity model

Replace flat `entity_tag: str` with a typed dataclass:

```python
@dataclass(frozen=True)
class EntityRef:
    kind: Literal["equipment", "circuit", "section", "row_marker"]
    canonical_id: str       # "LPS-RK-100SP" or "row_3" or "Bus_A"
    location_hint: str | None = None  # "main_feeder", "page2_top_left"
    source_span_text: str | None = None  # the PyMuPDF span this came from
```

`ParameterRecord.entity_tag: str` → `ParameterRecord.entity: EntityRef | None`.

Two records bind to the same entity iff:
1. `kind == kind` AND `canonical_id == canonical_id` AND (`location_hint` is None on both OR `location_hint` matches)

Cross-doc pairing rule:
- Strict-same-entity: pair iff entities match per the rule above
- Strict-different-entity: refuse pair iff both have entities AND they don't match
- One-sided-entity: allow pair (semantic alignment territory)
- Both-no-entity: allow pair (semantic alignment territory)

This subsumes the current Phase 19 rule + the Sprint 4.5 grounding refinement + the Sprint 5a hotfix asymmetric-allow into a single coherent semantics.

### 4.5 Pipeline-pass audit chain

Every Track that reads or writes a flag adds an audit-chain entry:

```python
@dataclass(frozen=True)
class AuditStep:
    track: str          # "track1_regex", "track2_llm_extract", "entity_grounding", ...
    action: Literal["created", "modified", "removed", "annotated"]
    field: str | None   # which field was touched
    before: Any | None
    after: Any | None
    reason: str         # short human-readable reason
```

`Flag.audit_chain: tuple[AuditStep, ...] = ()` grows as the flag traverses the pipeline. Reviewer panel surfaces:

```
TP-1 (LPS-RK-400SP vs LPS-RK-100SP):
  Track 1 (regex):  created — Fuse Designation extraction on p6 y=460.6
  Entity grounding: modified entity_tag — was "", now "LPS-RK-100SP"
                    reason: nearest-y-fallback (no enclosing entity)
  Reranker:         skipped — pairing_confidence=1.0 ≥ 0.75
  Standards judge:  annotated rationale + cited IEEE C57.12.00-2015 §5.4
                    reason: parameter_family=impedance_pct (WRONG: this is a fuse, not %Z)
```

Audit chain costs ~100 bytes per flag. Surfaces silent regressions immediately. Critical for trust + debugging.

### 4.6 Cross-document entity resolution (expanded)

Once entities are typed, cross-document pairing becomes an explicit entity-resolution stage in the pipeline — not a side-effect of value alignment.

**Pipeline position.** Runs *after* per-doc entity extraction (Sprint 8 vision lane + Sprint 9 typed extraction), *before* any value comparison or flag detection.

**Inputs:** two `list[EntityRef]` — one per doc — each annotated with `kind`, `canonical_id`, `location_hint`, `source_span_text`, plus a list of values attached to each entity.

**Output:** a `list[EntityPair]` — the resolved mapping between Doc A entities and Doc B entities, with confidence per pair. Value comparison then runs only within each resolved pair.

**Resolution mechanism (three layers, in order):**

1. **Exact-canonical match.** If both entities have identical `(kind, canonical_id)`, pair with confidence 1.0. Free. Default case.
2. **Per-project alias lookup.** Check `fixtures/projects/<project_id>/entity_aliases.yaml` (see §4.8) for reviewer-declared aliases (e.g., `T-1: XFMR-001`). Pair with confidence 0.95 if alias declared.
3. **LLM-resolved pairing.** Remaining unmatched entities → one Sonnet 4.5 call per doc-pair. Input: the two unmatched entity lists with their `source_span_text` + `location_hint`. Output: structured JSON mapping with per-pair confidence + rationale. ~$0.01 per doc-pair; cached on `(entity_list_a_hash, entity_list_b_hash, prompt_version, model)`.

**Failure modes:**
- LLM resolution returns nothing → entities stay unmatched → records flow into `unpaired_a`/`unpaired_b` honestly.
- LLM hallucinates a mapping not justifiable from source spans → hallucination guard (rationale must cite at least one canonical_id from each side) drops the mapping → unmatched.
- Asymmetric scope (Doc A has 20 entities, Doc B has 3) → only the matched 3 pair; remaining 17 Doc A entities go to `unpaired_a`.

**Reviewer surface.** The audit chain (§4.5) records every resolution step. A new "Entity resolution" expander in the UI shows the resolved mapping per doc-pair with confidence + rationale. Reviewer can override via the project-alias file (§4.8) and the override survives across runs.

**Cross-doc role coverage** (per §3.5 axis):
- Same conventions → exact-canonical match (free, instant).
- Different conventions → LLM resolution (cheap, cached).
- Different scope → asymmetric resolution → unmatched on the larger side surfaces in unpaired.
- Different classes → resolution prompt knows both `doc_class`es and adapts.
- Asymmetric quality → resolution is best-effort; honest gap > false pair.

### 4.7 OCR-modality lane (scanned, no text layer)

When Phase 20's vision-OCR fallback fires (page has < 80 native chars), the resulting "span" is a single full-page string with bbox = (0, 0, page_width, page_height). **There is no per-record y.** The current `_is_ocr_span()` heuristic in `ui/app.py` treats this as a whole-page snippet for citation rendering — but entity grounding currently has no analog handling.

**New OCR-modality extraction lane:**

1. Vision OCR returns the page text + a list of `(token, image_y_top, image_y_bottom)` tuples (Sonnet 4.5 Vision can return per-token bboxes when prompted explicitly — Phase 20 only asked for whole text).
2. Per-token bboxes → spans equivalent to PyMuPDF spans. Now span-identity binding (§4.1 option A) works the same as on born-digital text.
3. Entity detection runs on the OCR'd text + visual page; same pipeline as born-digital. Detector y-coords ARE in image space (same space as the OCR per-token y).

**Cost.** Phase 20's vision call already costs ~$0.005 per OCR'd page. Adding per-token bbox output costs the same (just a prompt change requesting the new field).

**Failure mode.** OCR'd text may have token-level errors (`LPS-RK-l00SP` vs `LPS-RK-100SP`). Entity resolution (§4.6) must use canonical-id similarity, not strict equality, when source confidence is low. Sprint 9 LLM resolution handles this naturally (the prompt sees both tokens + can reason about typos).

### 4.8 Per-project entity-alias override

For reviewer-declared cross-doc mappings (or to override LLM resolution errors), introduce per-project alias files:

```yaml
# fixtures/projects/<project_id>/entity_aliases.yaml
aliases:
  - doc_a_id: "T-1"
    doc_b_id: "XFMR-001"
    kind: "equipment"
    rationale: "Per project memo 2026-05-15, T-1 in the BOD = XFMR-001 in the spec sheet."
  - doc_a_id: "M-103"
    doc_b_id: "MTR-3"
    kind: "equipment"
```

Loaded by entity-resolution stage (§4.6 layer 2) before LLM resolution fires. Same project-id mechanism as Sprint 5a's `fixtures/projects/<id>/tolerances.yaml`. UI exposes the existing "Project ID (optional)" text input — alias file picked up automatically.

**Reviewer workflow.**
1. Run a review without aliases.
2. Spot a wrong (or missing) cross-doc mapping in the entity-resolution audit expander.
3. Add an entry to `entity_aliases.yaml` (or via a UI editor in a later sprint).
4. Re-run; alias takes precedence over LLM resolution.

---

## 5. Rollout plan (4 sprints)

### Sprint 7 — Page-structure classifier + audit chain (no behavior change)

**Goal:** Ship instrumentation. No flag set changes. Reviewer can see what each Track did + page structure routing decision.

- Page-structure heuristic classifier (already prototyped in `scripts/diagnose_page_structures.py`). Emits source × layout label per page; nothing routes yet.
- Source detection: PyMuPDF coverage check (already exists for Phase 20 vision-OCR threshold) + layout classifier (prose / table / diagram / mixed).
- Audit chain plumbing: `Flag.audit_chain` field; each Track writes to it; UI surfaces the chain in the per-flag expander.
- Reviewer sees the existing bad behavior, attributed to the right step.

Cost: $0 incremental. Time: 2-3 days.

### Sprint 8 — Vision extraction lane (diagrams) + OCR-modality lane (scanned-no-text)

**Goal:** Eliminate the coordinate-space mismatch on diagrams AND give scanned-no-text pages a real entity-grounding path.

- Vision extraction module (§4.3): Sonnet 4.5 Vision call per diagram page, returns structured `(entity_kind, entity_id, parameter, value, visual_evidence)` tuples. ~$0.02 per diagram page; cached.
- OCR-modality lane (§4.7): Phase 20's vision-OCR fallback prompt extended to return per-token bboxes. Span-identity binding works on OCR'd pages the same as born-digital. ~$0 incremental (same call, richer schema).
- Pipeline routes pages by the source × layout matrix (§4.2). Born-digital prose / table pages stay on current lanes.
- Live exit gates:
  - Born-digital diagram: user's `LPS-RK-400SP vs LPS-RK-100SP` false positive does NOT surface.
  - Scanned diagram (synthesized fixture): same false positive shape on a scanned page does NOT surface.
  - Mixed-source PDF: each page routes independently; flags from each page carry the right `extraction_lane` audit-chain step.

Cost: ~$0.14 per cold review on a 9-page coordination study (7 diagram pages × $0.02). Cached. Time: 1 sprint.

### Sprint 9 — Typed EntityRef + cross-doc resolution + per-project aliases

**Goal:** Replace flat `entity_tag: str` with `EntityRef` everywhere; add cross-doc entity resolution as a first-class pipeline stage; support reviewer-declared aliases.

- Refactor `ParameterRecord.entity_tag` → `ParameterRecord.entity: EntityRef | None`. Phased back-compat shims.
- Update Phase 19 alignment + Sprint 4 reranker + Sprint 4.5 grounding + Sprint 5a/5b/6 modules to consume `EntityRef`.
- New cross-doc entity-resolution stage (§4.6): three-layer (exact / project-alias / LLM-resolved). ~$0.01 per doc-pair cold; cached on entity-list hashes.
- Per-project entity-alias YAML (§4.8): `fixtures/projects/<id>/entity_aliases.yaml`. Loaded by resolution stage.
- Audit chain entries become richer (entity creation, alias hit, LLM resolution mapping with rationale).
- UI: "Entity resolution" expander shows the resolved mapping with confidence + override hint.
- Live exit gates:
  - Same-conventions doc-pair: existing behavior preserved (regression test).
  - Different-conventions doc-pair (synthetic Doc A `T-1` vs Doc B `XFMR-001`): pair resolves correctly via LLM, flags surface.
  - Project-alias override: declared alias takes precedence over LLM resolution.

Cost: ~$0.01 per cold review (resolution call). Time: ~2 weeks (large refactor).

### Sprint 10 — Test-matrix gold corpus + CI gates

**Goal:** Validate the multi-modal pipeline against the §3.5 scope axes; gate every commit.

- Synthesize / source fixtures for each cell of the §10 test matrix (born-digital prose / table / diagram × scanned-OCR × same-conventions / different-conventions / asymmetric-quality).
- Per-matrix-cell gold flag YAML in `fixtures/eval/gold_flags/`, leveraging Sprint 6's per-class harness.
- CI gate: precision ≥ 0.8 / recall ≥ 0.7 per matrix cell with ≥ 5 cases (xfail-soft on sparse cells).
- Audit-chain regression test: every flag in every matrix cell has a complete audit chain entry per Track.
- Calibration report (Sprint 6 reuse): per-matrix-cell Brier breakdown.

Cost: $0 incremental code; corpus growth is content sourcing. Time: 2 weeks.

---

## 6. Out of scope (deliberate deferrals)

- **Full RAG over verbatim standards.** Sprint 5a's curated YAML is the right shape; embedding-based RAG is a v3 concern.
- **Coupled-effect graph traversal beyond static map.** Sprint 5b's static map is sufficient until the per-class gold corpus is large enough to validate ML-based dependency inference.
- **OCR-from-image for prose pages.** PyMuPDF text extraction works for prose. No need to bypass.
- **Pattern registry for equipment-ID detection.** Replaced by vision extraction in Sprint 8 — the LLM recognizes equipment IDs natively without us curating regexes.

---

## 7. Risks + open questions

| Risk | Mitigation |
|---|---|
| Vision extraction is non-deterministic + hard to gate | Live exit-gate tests on specific cases (KRP-C, 200A/400A, %Z); diskcache makes repeat runs deterministic |
| Cost increase per cold run (~$0.14 added for a 9-page coord study) | Within PIVOT_PLAN's $0.50–$3 envelope; cached after first run |
| Page-structure classifier mis-routes | Heuristic is conservative (only routes high-confidence diagrams to vision); falls back to text lane on ambiguity |
| `EntityRef` refactor breaks every existing test | Sprint 9 is large; phased migration with back-compat shims; CI keeps green at each phase |
| Audit chain UI clutters reviewer view | Hidden behind expander toggle; default off; advanced-mode flag |
| Vision LLM may hallucinate entity_id | Same hallucination guard as Sprint 4 reranker: `entity_id` must appear in the page text; otherwise drop |

**Open questions:**

1. How wide is the corpus where structure classifier matters? Need broader test corpus to tune thresholds.
2. Cross-doc entity resolution at scale: how does it behave on 50-entity docs vs 5-entity docs?
3. Is there a deterministic alternative to vision for simple diagrams (e.g., parse PDF vector primitives directly)? Probably yes for born-digital PDFs; not for scans.
4. What's the right reviewer UX for `EntityRef.location_hint`? Surface as a chip? In the expander? Hidden until clicked?

---

## 8. Decision needed

Before any code: **does the architecture proposed in §4 + the rollout in §5 match the project's direction?**

If yes → Sprint 7 spec + plan, ship, then 8, then 9, then 10.

If no → revise §4 based on what's actually needed.

Either way, the v2.7 patch path (more y-binding heuristics, more pattern registries) is the wrong direction. The pipeline needs the multi-modal extension to honestly support arbitrary engineering documents.

---

## 9. Adversarial review of this design

Before approval, attacking the design's own weaknesses:

**Vision lane is the new single point of failure.** If Sonnet 4.5 Vision has an outage or returns garbage, diagram pages produce nothing. Mitigation: Phase 20 vision-OCR fallback path is already in place; vision-lane failure routes to OCR-modality lane (same model, different prompt) → eventual fallback to text-only Track 2 with `low_confidence=True` flag. Never zero output.

**Cross-doc entity resolution at scale (50×50 entities).** O(N×M) token cost balloons. Mitigation: two-step resolution — first an embedding-based shortlist (top 10 candidate matches per entity), then LLM resolves only the shortlist. Same cost shape as Sprint 4 reranker.

**Per-project entity aliases require human curation.** Onboarding cost per project. Mitigation: alias file is optional; pipeline works without it (just relies on LLM resolution). Aliases become the escape hatch when LLM resolution is wrong, not a prerequisite.

**EntityRef refactor regresses every existing test.** Yes. Sprint 9 must phase the migration: add `entity` field alongside `entity_tag` first; migrate consumers one by one; deprecate `entity_tag` only after all consumers move. Standard back-compat shim pattern.

**Vision LLM may hallucinate entity_id from page noise.** Same hallucination guard as Sprint 4 reranker + Sprint 5a citation: `entity_id` must appear in the page text (or in the rendered image as recognizable visual). Validation in pipeline; failures drop silently.

**OCR-modality per-token bbox extraction may not be reliable from Sonnet 4.5 Vision.** Open question. If unreliable, fall back to OCR'd text only and accept the loss of per-record y on scanned pages (records get bbox=(0,0,page_w,page_h); pairing relies on text proximity within the OCR'd span instead).

---

## 10. Anti-overfitting test matrix

**Principle.** No fix ships until it passes a synthetic test matrix covering the cross-product of §3.5 axes. The Option 1 fixture is one cell. Sprints 7–10 must demonstrate behavior on **every** cell the architecture claims to support.

**Matrix (16 minimum cells; expand as classes grow):**

| # | Source | Layout | Cross-doc role | Doc class | Fixture status |
|---:|---|---|---|---|---|
| 1 | born-digital | prose | single-doc | spec | existing fixture |
| 2 | born-digital | prose | same-conv | spec ↔ spec | Option 1 cover |
| 3 | born-digital | table | same-conv | spec ↔ study | existing |
| 4 | born-digital | table | different-conv | spec ↔ BOM | **TODO synthesize** |
| 5 | born-digital | diagram | same-conv | study ↔ study | Option 1 pages 2-8 (currently failing) |
| 6 | born-digital | diagram | different-conv | spec ↔ study | **TODO synthesize** |
| 7 | scanned-sidecar | prose | same-conv | spec ↔ spec | **TODO source real** |
| 8 | scanned-sidecar | table | same-conv | BOM ↔ BOM | **TODO source real** |
| 9 | scanned-sidecar | diagram | same-conv | one-line ↔ one-line | **TODO source real** |
| 10 | scanned-no-text | prose | same-conv | older spec scan | **TODO source real** |
| 11 | scanned-no-text | table | same-conv | older BOM scan | **TODO source real** |
| 12 | scanned-no-text | diagram | same-conv | older drawing scan | **TODO source real** |
| 13 | mixed (page-level) | prose+table+diagram | same-conv | full coordination study | **TODO synthesize** |
| 14 | mixed (asymmetric quality) | A born-digital / B scanned | same-conv | spec vs scanned spec | **TODO synthesize** |
| 15 | born-digital | diagram | asymmetric scope | substation ↔ single transformer | **TODO synthesize** |
| 16 | mixed | mixed | different-conv + asymmetric | realistic project pair | **TODO source real** |

**Each cell has:**
- A fixture pair (synthesized OR sourced).
- Per-class gold YAML in `fixtures/eval/gold_flags/<cell_id>.yaml` (Sprint 6 schema).
- CI gate: precision ≥ 0.8 / recall ≥ 0.7 once cell has ≥ 5 labelled cases.

**Anti-overfitting discipline:**
- Sprint 7 audit chain ships → run on **every existing cell**; document baseline metrics per cell.
- Sprint 8 vision lane ships → must improve cells 5 + 6 + 12 + 16 by ≥ 1 metric point each, AND not regress cells 1-3 + 9 by more than 0.05.
- Sprint 9 cross-doc resolution ships → must improve cells 4 + 6 + 14 + 16 by ≥ 1 metric point each, AND not regress others.
- Sprint 10 makes the matrix CI-gated.

**No PR merges (Sprint 7+) without** a per-cell delta report attached. This is the discipline that prevents the design from drifting back into overfitting to one demo fixture.

---

*End of design doc. Awaiting review.*
