# Sprint 8 — Vision lane for diagram pages (+ Sprint 7-lite: structure classifier)

**Goal.** Ship the proper architectural fix for diagram-page entity binding: per-page page-structure classifier routes diagram pages to a Sonnet 4.5 Vision extraction lane that returns structured `(entity_kind, entity_id, parameter, value, visual_evidence)` tuples directly — bypassing the broken PyMuPDF-text-layer-y binding entirely. Prose + table pages stay on current lanes.

**Exit tag:** `v2.8-vision-lane`. **Spec parent:** `2026-05-23-multimodal-extraction-redesign.md`.

**Scope decision (per reviewer):** Sprint 7's audit chain piece deferred to Sprint 9.5; Sprint 7's structure-classifier piece bundled into Sprint 8 (it's a hard dependency anyway).

---

## §1 What ships

### (a) Page-structure classifier (Sprint 7-lite)

Heuristic + cached per (PDF hash, page). Emits per-page label:

| Label | Heuristic |
|---|---|
| `prose` | short_line_ratio < 0.3 AND avg_line_len > 40 |
| `diagram` | short_line_ratio > 0.6 AND avg_line_len < 25 |
| `table` | Camelot detects a grid OR (image_area_ratio > 0.3 AND not diagram) |
| `mixed` | otherwise |

Prototype already validated in `scripts/diagnose_page_structures.py` against Option 1 fixture (8 pages classified correctly).

### (b) Vision extraction lane (new)

When page label = `diagram`, the pipeline calls Sonnet 4.5 Vision with proto 1's confirmed prompt shape:

```json
{
  "page_understanding": "...",
  "page_layout": "diagram",
  "claims": [
    {
      "entity_kind": "equipment" | "circuit" | "section" | "row_item",
      "entity_id": "<as shown on page>",
      "entity_location_hint": "<short visual location>",
      "parameter_name": "<canonicalized>",
      "raw_value": "<exact text>",
      "visual_evidence": "<sentence tying value to entity>"
    }
  ]
}
```

Each returned claim becomes a `ParameterRecord` with `entity_tag = entity_id` set DIRECTLY (no binding step). Span-identity binding via the `entity_id` itself.

### (c) Routing in the pipeline

```python
# In pipeline.py — runs after ingest, before extract:
if use_llm_extraction:
    for page_num in range(1, n_pages + 1):
        label = classify_page_structure(pdf_path, page_num)
        if label == "diagram":
            records = vision_extract_page(pdf_path, page_num, doc_class)
        else:
            records = current_extraction_path(spans_on_page)
        all_records.extend(records)
```

No behavior change for prose/table pages. Diagram pages skip the broken Track 1 / Track 2 / entity-grounding chain entirely.

### (d) Pipeline kwarg

`use_vision_lane: bool = True` (default ON; opt-out for back-compat). Like every previous Track 2 toggle, default-True ships the new behavior to demo users.

---

## §2 Schema additions

**`PageStructure` enum** (`src/interlock/llm_pipeline/schemas/page_structure.py`):

```python
PageStructure = Literal["prose", "table", "diagram", "mixed"]
```

**`VisionClaim`** (`src/interlock/llm_pipeline/schemas/vision_claim.py`):

```python
class VisionClaim(BaseModel):
    model_config = ConfigDict(frozen=True)
    entity_kind: Literal["equipment", "circuit", "section", "row_item"]
    entity_id: str = Field(min_length=1, max_length=128)
    entity_location_hint: str = Field(max_length=200, default="")
    parameter_name: str = Field(min_length=1, max_length=128)
    raw_value: str = Field(min_length=1, max_length=200)
    visual_evidence: str = Field(min_length=1, max_length=400)


class VisionPageResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    page: int = Field(ge=1)
    page_understanding: str = Field(min_length=1, max_length=400)
    page_layout: PageStructure
    claims: list[VisionClaim] = Field(default_factory=list)
```

**`ParameterRecord` extension** (additive, back-compat):

```python
# Existing fields unchanged. Add:
extraction_lane: Literal["regex", "llm_text", "vision"] = "regex"
```

Sprint 5a `provenance` field already distinguishes `regex` from `llm` (LLM text extraction). The new `extraction_lane` is finer-grained: `regex` | `llm_text` | `vision`. Sprint 9.5 audit chain will consume this.

---

## §3 New modules

| Path | Responsibility |
|---|---|
| `src/interlock/llm_pipeline/schemas/page_structure.py` | `PageStructure` Literal |
| `src/interlock/llm_pipeline/schemas/vision_claim.py` | `VisionClaim` + `VisionPageResult` pydantic models |
| `src/interlock/llm_pipeline/page_classify.py` | `classify_page_structure(pdf_path, page) → PageStructure`; heuristic + diskcache |
| `src/interlock/llm_pipeline/vision_extract.py` | `vision_extract_page(pdf_path, page, doc_class) → list[ParameterRecord]`; vision LLM call + diskcache + hallucination guard + parse |
| `src/interlock/llm_pipeline/prompts/vision_extract.md` | System prompt (locked from proto 1 shape) |

**Modified:**

| Path | Change |
|---|---|
| `src/interlock/extract/parameters.py` | `ParameterRecord` gains `extraction_lane: Literal["regex", "llm_text", "vision"] = "regex"` |
| `src/interlock/pipeline.py` | New `use_vision_lane: bool = True` kwarg; per-page routing logic between ingest and extract |
| `src/interlock/ui/app.py` | Sidebar toggle "Vision extraction for diagram pages" (default ON); per-flag chip "📷 Vision" when source record extraction_lane="vision" |

---

## §4 Failure modes + mitigations

| Failure | Mitigation |
|---|---|
| Vision API outage on a single page | Per-page try/except → record list stays empty for that page; downstream alignment runs on whatever did extract |
| Vision API outage on ALL pages | Page-level errors → no vision records anywhere → flag list comes from regex + LLM-text only. Demo bug RE-EMERGES on that run, but pipeline ships flags. Reviewer sees fewer / no `📷 Vision` chips → visible signal of degraded mode |
| Hallucinated entity_id (not present in page text) | Vision claim's `entity_id` substring-checked against the page's PyMuPDF text → drop hallucinated claims (same hallucination guard pattern as Sprint 2 + Sprint 4) |
| Vision returns claims for prose pages (we never asked) | Routing only sends `diagram` pages to vision; prose pages never invoke it |
| JSON parse failure | Three-tier fallback: fenced JSON regex → bare JSON regex → `[]` (graceful empty) |
| Structure classifier misroutes a table as diagram | Vision lane STILL extracts useful claims from tables (proto 1b validated: form layout returns 12 claims). Misrouting wastes ~$0.02 but produces non-broken output |
| Diskcache stale (page text changed but cache hit) | Cache key includes hash of PyMuPDF page text (already in Sprint 5a `_short_hash` pattern); changes invalidate |

---

## §5 Cost + latency

| | Cold | Warm |
|---|---:|---:|
| Page structure classifier | <10 ms | <1 ms (mtime cache) |
| Vision extraction per diagram page | ~$0.02 (Sonnet 4.5 Vision, 300dpi PNG + structured-output prompt) | $0 (diskcache) |
| Locked Option 1 fixture (~7 diagram pages) | ~$0.14 | $0 |

Within PIVOT_PLAN $0.50–$3 envelope.

---

## §6 TDD phases (5 phases)

### Phase 32.1 — Schemas + structure classifier

- Tests: `tests/llm_pipeline/schemas/test_vision_claim.py` (~6) — validation, min/max length, enum literals, frozen.
- Tests: `tests/llm_pipeline/test_page_classify.py` (~5) — prose/table/diagram/mixed cases on synthetic page text; diskcache hit.
- Implement: schemas + `classify_page_structure()`.
- **Tag:** `phase-32.1-vision-schemas`.

### Phase 32.2 — Vision extraction module (mocked tests)

- Tests `tests/llm_pipeline/test_vision_extract.py` (~10):
  - Valid response parses into `VisionPageResult`
  - Fenced ```` ```json ```` response parses (proto 1 + 1b parse issue caught)
  - Bare JSON response parses
  - API outage → empty list (no exception)
  - Parse error → empty list
  - Pydantic validation error → empty list
  - Hallucination guard: claim's `entity_id` not in page text → dropped
  - Diskcache hit short-circuits API call
  - `extraction_lane="vision"` set on every returned record
  - Empty `claims` list → empty record list
- Implement: `vision_extract_page()` + prompt file (locked from proto 1 shape).
- **Tag:** `phase-32.2-vision-extract`.

### Phase 32.3 — Pipeline integration + per-page routing

- Tests appended to `tests/e2e/test_pipeline_v2.py` (~5):
  - `use_vision_lane=False` → no vision calls; behavior bit-identical to v2.7
  - `use_vision_lane=True` + mocked vision returning claims → claims flow into alignment; flag set includes vision-sourced records
  - Mixed routing: diagram pages → vision, prose pages → current path; per-page audit-friendly
  - LPS-RK regression test: with vision lane ON on Option 1 fixture, the `LPS-RK-400SP ≠ LPS-RK-100SP` false positive does NOT surface
  - Doc class router still routes correctly (vision lane is orthogonal to doc-class)
- Implement: pipeline kwarg + per-page loop.
- **Tag:** `phase-32.3-vision-pipeline`.

### Phase 32.4 — UI surface

- Sidebar toggle "Vision extraction for diagram pages" (default ON), help text + cost note.
- Per-flag chip `📷 Vision` when at least one of the pair's records has `extraction_lane="vision"`.
- Stage label `vision_extract` between `extract` and `align`.
- JSON export `extraction_lane_a` / `extraction_lane_b` keys.
- Manual smoke + compile + lint + mypy.
- **Tag:** `phase-32.4-vision-ui`.

### Phase 32.5 — Live exit gate + docs + sprint exit

- Tests `tests/real_world/test_vision_lane_live.py` (slow + needs_anthropic, ~3):
  1. Option 1 doc_a p6 fresh vision call returns ≥ 1 claim with `entity_kind=equipment` AND `entity_id="LPS-RK-400SP"` (proven by proto 1).
  2. Cross-doc on Option 1 with vision lane ON: false-positive `LPS-RK-400SP ≠ LPS-RK-100SP` does NOT surface (the actual demo bug fix).
  3. P&ID fixture (synth_pid.pdf) returns ≥ 5 claims with `entity_kind=circuit` for pipe lines (proves generalization beyond coordination studies, per proto 1b).
- AUTHORSHIP + TDD known-limits.
- **Exit tag:** `v2.8-vision-lane`.

---

## §7 Anti-overfitting commitments

Per the §10 matrix in the multi-modal redesign doc:

- Sprint 8 must improve cells **1, 2, 3, 5** (born-digital prose / table / diagram on same-conv pairs) AND not regress others by more than 0.05.
- Live exit-gate test #3 (P&ID synth fixture) explicitly tests generalization beyond the Option 1 fixture.
- Mocked test for `use_vision_lane=False` preserves v2.7 baseline bit-for-bit.
- Each phase tags + commits independently so we can bisect any regression.

---

## §8 Deferred to Sprint 9.5

- Audit chain (`Flag.audit_chain`) — instrumentation panel. Sprint 8 ships without it; reviewer sees `📷 Vision` chip as the only signal of new behavior.
- Sprint 9 cross-doc resolution (P0).
- Sprint 10 OCR-modality lane (P1).
- Sprint 11 CI matrix gates.
