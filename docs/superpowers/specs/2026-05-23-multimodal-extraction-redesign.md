# Multi-Modal Extraction + Entity Grounding Redesign

**Status:** Design doc. Not approved for implementation. Captures the first-principles diagnosis of the v2.7 entity-binding failure class + proposes a multi-sprint architectural extension.

**Date:** 2026-05-23
**Author:** AI session (Claude) + human review pending
**Supersedes:** Sprint 7 "audit chain" / "pattern registry" patches considered earlier in the session.

---

## 0. TL;DR

The v2.7 pipeline assumes PyMuPDF text-layer y-coordinates equal visual y-coordinates. **This is true for prose and tables; false for diagram pages.** On diagrams, the LLM entity detector returns visually-correct y-bands, but PyMuPDF spans report PDF text-layer draw-order y — a different coordinate system. The binder's y-enclosure + nearest-y-fallback then mis-binds extraction records to wrong entities, producing high-confidence false positives like the user's reported `LPS-RK-400SP ≠ LPS-RK-100SP` flag with `entity_tag=LPS-RK-100SP` on both records.

This is **not** a calibration bug. It's an architectural assumption violated by diagram pages. Fixing it requires:

1. **Page-structure-aware extraction routing** (prose → text LLM; table → Camelot+regex; diagram → vision LLM).
2. **Span-identity binding** instead of y-coordinate binding (drop the heuristic; bind by which PyMuPDF span the value came from).
3. **Typed entity model** (kind, canonical_id, location_hint, source_spans) replacing flat `entity_tag: str`.
4. **Pipeline-pass audit chain** so every Track's contribution to a flag is auditable and revertable.

Estimated scope: 3 sprints (Sprint 7 audit + classifier; Sprint 8 vision lane; Sprint 9 entity model refactor).

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

## 4. First-principles design

### 4.1 Two coordinate spaces, never mixed

Make the distinction explicit:
- **Image coordinate space:** where the page is rendered visually (the PNG at 300dpi the detector saw). Y here matches what a human sees.
- **Text-layer coordinate space:** the y a PyMuPDF span reports. On prose/tables, equal to image y; on diagrams, arbitrary.

The binder must never compare a value from one space to a position in the other. Two implementation options:

**Option A — Drop y-coordinate binding entirely.** Detector returns *which text spans* are entity labels, not y-coords. Binder matches records to entities by checking which span the record was extracted from (or near in the same span text). Pure span-identity binding. Eliminates the coordinate-space concept.

**Option B — Normalize both spaces.** For each PyMuPDF span, locate its rendered position in the image (via OCR-from-image or vision query) and store the *image* y on the record. Then binder operates entirely in image space.

A is simpler. B is more expensive but works for vision-extracted entities that have no corresponding text-layer span. Recommended: **A as default, B as fallback when vision extraction outpaces PyMuPDF text coverage.**

### 4.2 Page-structure routing

A page-structure classifier (LLM-based or heuristic) routes each page to one of three extraction lanes:

| Lane | Routing rule | Extractor |
|---|---|---|
| Prose | low short-line-ratio (<0.3) + high avg line length (>40) | Track 2 LLM text extraction |
| Table | Camelot detects a structured grid OR high cell-aligned line count | Track 1 regex + Camelot row records |
| Diagram | high short-line-ratio (>0.6) AND low avg line length AND no Camelot grid | **NEW: Vision extraction via Sonnet 4.5 Vision** |

Heuristic prototype already validated: `scripts/diagnose_page_structures.py` correctly identifies pages 2-8 of Option 1 as `diagram-callouts`, page 1 as `table-or-mixed`, page 9 as `prose`. Tweak thresholds with broader corpus; ship the routing layer first.

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

### 4.6 Cross-document entity resolution

Once entities are typed, cross-document pairing becomes an entity-resolution problem:

- For each (Doc A entity, Doc B entity) pair, ask: do they refer to the same physical thing?
- Match-key: `(kind, canonical_id)` — but canonical_id may differ across docs (Doc A uses `T-1`, Doc B uses `XFMR-001`).
- Resolution: a per-doc-pair LLM call (~$0.01) that takes the entity lists from both docs and returns a mapping. Cheap; cacheable on the entity-list-hash.

Within each resolved entity pair, value comparison happens normally. Across non-resolved pairs, no comparison.

This is the architectural inversion my earlier proposal described. It's expensive enough to defer until #4.1–#4.5 are in place.

---

## 5. Rollout plan

### Sprint 7 — Page-structure classifier + audit chain (no behavior change)

**Goal:** Ship instrumentation. No flag set changes. Reviewer can see what each Track did.

- Page-structure heuristic classifier (already prototyped). Emits structure label per page; nothing routes yet.
- Audit chain plumbing: `Flag.audit_chain` field; each Track writes to it; UI surfaces the chain in the per-flag expander.
- Reviewer sees the existing bad behavior, attributed to the right step.

Cost: $0 incremental. Time: 2-3 days.

### Sprint 8 — Vision lane for diagram pages

**Goal:** Eliminate the coordinate-space mismatch on diagrams.

- Vision extraction module: Sonnet 4.5 Vision call per diagram page, returns structured `(entity_kind, entity_id, parameter, value)` tuples.
- Vision-extracted records carry full `EntityRef`; bypass the y-binding step entirely.
- Pipeline routes diagram pages to vision lane (per structure classifier); prose / table pages stay on current lanes.
- Live exit gate: the user's `LPS-RK-400SP vs LPS-RK-100SP` false positive does NOT surface.

Cost: ~$0.02 per diagram page cold; cached. Time: 1 sprint.

### Sprint 9 — Typed Entity model + cross-doc resolution

**Goal:** Replace `entity_tag: str` with `EntityRef` everywhere. Add cross-doc entity resolution as a pipeline stage.

- Refactor `ParameterRecord.entity_tag` → `ParameterRecord.entity: EntityRef | None`.
- Update Phase 19 alignment + Sprint 4 reranker + Sprint 4.5 grounding to consume `EntityRef`.
- New cross-doc entity-resolution LLM call (~$0.01 per pair, cached).
- Audit chain entries become richer (entity changes attributed to specific Tracks).

Cost: large refactor; ~2 sprints' time. Behavior change: cleaner cross-doc pairing on multi-equipment docs.

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

If yes → Sprint 7 spec + plan, ship, then Sprint 8, then Sprint 9.

If no → revise §4 based on what's actually needed.

Either way, the v2.7 patch path (more y-binding heuristics, more pattern registries) is the wrong direction. The pipeline needs the multi-modal extension to honestly support arbitrary engineering documents.
