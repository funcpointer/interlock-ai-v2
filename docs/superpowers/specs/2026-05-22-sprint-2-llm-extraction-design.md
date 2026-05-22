# Sprint 2 Design — LLM Extraction (Track 2)

**Project:** InterLock AI v2
**Sprint:** 2 (week 3–5 of 6-sprint hybrid pivot)
**Baseline:** `v2.0-mvp`
**Approved:** 2026-05-22
**Exit tag:** `v2.1-llm-extraction`

---

## Purpose

Sprint 2 ships the **hybrid wedge** — a Track 2 LLM extraction module that runs alongside Track 1's regex extractor and emits structured `ParameterRecord`s tagged with `provenance="llm"`. This solves v1's prose-paper zero-yield case (SEL conference paper currently extracts 0 parameters; Sprint 2 target ≥ 30) without touching Track 1's deterministic invariant.

The pipeline gains an opt-in `use_llm_extraction` kwarg. When `True`, Track 1 + Track 2 records are unioned into the alignment input. When `False`, behaviour is bit-identical to v2.0-mvp (and via Sprint 1's invariant chain, bit-identical to v1.5-mvp-ready).

Per-page parallel calls to `claude-sonnet-4-5` over native text (no VLM in Sprint 2 — VLM is Sprint 1's classifier territory). Hybrid prompts: a universal base + per-class injection from `prompts/extract/<class>.md` keyed off Sprint 1's classifier output.

---

## §1. Approach + components

**Approach: per-page text-only Sonnet 4.5 call with hybrid prompts.**

For each PDF, for each page:

1. Render `page.get_text("text")` (PyMuPDF) — already produced by v1's ingest path; for scanned pages the per-line OCR text from Phase 18 covers this.
2. Look up the doc's Sprint 1 classifier output → load `prompts/extract/<class>.md` and inject into the universal base prompt.
3. Call `claude-sonnet-4-5` via `messages.parse` with the `PageExtractionResult` Pydantic schema.
4. Validate output. Reject claims whose `span_text` is not a verbatim substring of the page text (anti-hallucination guard).
5. Downcast surviving claims to `ParameterRecord(provenance="llm", ...)`.
6. Append to v1's regex-extracted records before alignment runs.

**Why Sonnet over Opus.** Structured extraction is a fit-the-schema task, not a deep-reasoning task. Sonnet at ~$0.012 per page vs Opus at ~$0.06 per page is a 5× cost saving. Live eval at phase 25.6 will measure whether Sonnet underperforms; escalate to Opus only if SEL paper fails the ≥ 30 gate.

**Why hybrid prompts over pure-per-class.** Schema is universal — same Pydantic model regardless of class. Per-class injection adds class-specific examples + critical-field hints. Single source of truth on schema; class knowledge lives in 7 small markdown files reviewers can audit + edit without touching code.

**Why text-only over VLM.** v1's PyMuPDF + per-line OCR pipeline already produces text. Sprint 2's job is to turn that text into structured claims that regex misses (prose-embedded params, non-tabular layouts). VLM is overkill for the prose case and 6× more expensive.

**Rejected alternatives:**

| Alternative | Why not |
|---|---|
| Per-class prompts (no shared base) | 7 prompts to maintain in lockstep on schema changes; duplication of schema spec; brittle to schema evolution. |
| Universal prompt only (no per-class) | Dilutes per-class fidelity — HVAC schedule's CFM column gets missed when the same prompt also covers fuse tables. Class-specific cues matter for narrow-vocabulary extraction. |
| Whole-doc single call | 1M-token Opus context is expensive ($0.30–1.00 per doc); single point of failure; no partial cache hits when one page changes. |
| Page-image VLM | 6× cost vs text-only; v1 already produces text reliably; VLM overkill for prose extraction. |
| Tool-use Pint mid-extraction | More LLM round-trips; harder to debug. Post-process Pint normalization on the downcast path is simpler and deterministic. |

**Components shipped this sprint:**

- `src/interlock/llm_pipeline/schemas/claim.py` — `ExtractedClaim` + `PageExtractionResult` Pydantic models
- `src/interlock/llm_pipeline/extract.py` — `extract_claims_from_doc(pdf_path, doc_class) -> list[ParameterRecord]` with per-page ThreadPoolExecutor parallelism + diskcache
- `src/interlock/llm_pipeline/prompts/extract/_base.md` — universal extraction prompt + schema description
- `src/interlock/llm_pipeline/prompts/extract/<class>.md` × 7 — per-class injection content (filled this sprint)
- `src/interlock/extract/parameters.py` — `ParameterRecord` gains `provenance: Literal["regex", "llm"] = "regex"` field
- `src/interlock/pipeline.py` — `use_llm_extraction: bool = False` kwarg; Track 2 stage callback (`llm_extract_a`, `llm_extract_b`); merges Track 2 records into the per-doc record list before alignment

**Cost envelope:** per-page Sonnet ~$0.012 cold, $0 warm. Eaton 9-page fixture cold ≈ $0.10. SEL paper 18 pages cold ≈ $0.20.

---

## §2. Schema

```python
# src/interlock/llm_pipeline/schemas/claim.py
from pydantic import BaseModel, Field


class ExtractedClaim(BaseModel):
    """One claim the LLM lifted from a page's text."""

    # Identity — for downcast to ParameterRecord
    parameter_name: str = Field(
        description="Canonical parameter name (e.g., '%Z', 'Transformer Rating', 'Fault Current')"
    )
    raw_value: str = Field(
        description="The value exactly as written in the source text, including units"
    )

    # Entity binding (Phase 19 entity_tag carries forward to ParameterRecord)
    entity_tag: str = Field(
        default="",
        description="Device ID / equipment tag if visible (e.g., 'XFMR-001', 'T-1', '⑥'). Empty if no identifier in the text.",
    )

    # Source provenance
    span_text: str = Field(
        description="The exact sentence or table-row text containing the claim, ≤ 200 chars",
    )
    page: int = Field(ge=1)
    confidence: float = Field(
        ge=0.0, le=1.0,
        description="How sure the model is that this is a real engineering parameter",
    )
    reasoning: str = Field(default="", description="Optional short explanation")

    model_config = {"frozen": True}


class PageExtractionResult(BaseModel):
    """LLM response shape per page — list of claims + meta."""

    claims: list[ExtractedClaim] = Field(default_factory=list)
    page: int = Field(ge=1)
    notes: str = Field(default="", description="One-line summary or empty")

    model_config = {"frozen": True}
```

**Downcast to ParameterRecord:**

```python
def _claim_to_parameter_record(
    c: ExtractedClaim, doc_id: str, source_path: str
) -> ParameterRecord:
    raw = c.raw_value.strip()
    try:
        q = normalize_quantity(raw)
        mag, unit = float(q.magnitude), str(q.units)
    except Exception:
        mag, unit = None, None
    return ParameterRecord(
        doc_id=doc_id,
        page=c.page,
        bbox=(0.0, 0.0, 0.0, 0.0),  # text-only — no per-claim bbox available
        section=None,
        span_text=c.span_text,
        name=c.parameter_name,
        raw_value=raw,
        normalized_magnitude=mag,
        normalized_unit=unit,
        source_path=source_path,
        entity_tag=c.entity_tag,
        provenance="llm",
    )
```

**Schema decisions:**

| Decision | Rationale |
|---|---|
| `ExtractedClaim` is a separate schema (not directly `ParameterRecord`) | LLM emits richer info (reasoning, confidence). Downcast strips to ParameterRecord shape; richer fields go into the extract.py audit log. |
| `bbox=(0,0,0,0)` for LLM records | LLM sees text, not coords. Phase 19's `_is_ocr_span` heuristic (whole-page bbox at origin) treats these like OCR spans — same UI behaviour (whole-page snippet caption). |
| `entity_tag` reuses Phase 19's field on `ParameterRecord` | LLM can populate it naturally from the text. Phase 19's identity-aware alignment works on Track 2 records for free. |
| `provenance` is the ONLY new `ParameterRecord` field | Smallest change to Track 1's surface area. Tests constructing `ParameterRecord` by hand still work (default `"regex"`). |
| `frozen=True` on both schemas | Immutable; audit-trail-friendly. Matches `DocClassification` from Sprint 1. |

---

## §3. Pipeline integration

**Where Track 2 sits:**

```
PDF
 ├── classify_doc(pdf_path)              [Sprint 1, parallel w/ ingest]
 │
 ├── ingest(pdf_path)                    [Track 1 — unchanged]
 │     IngestResult (spans, tables)
 │
 ├── extract_parameters(spans)           [Track 1 — emits provenance="regex"]
 │
 └── extract_claims_from_doc(            [Track 2 — NEW, opt-in]
       pdf_path, doc_class)
       per-page parallel via ThreadPoolExecutor(max_workers=5)
       emits ParameterRecord with provenance="llm"

  ↓ Pipeline returns Track 1 ∪ Track 2 records to align/detect/...
    Alignment + detection paths unchanged — they see records, not provenance
```

**Pipeline signature additions:**

```python
def review_two_documents_full(
    ...existing kwargs,
    classify_docs: bool = False,        # Sprint 1
    use_llm_extraction: bool = False,   # Sprint 2 — NEW
) -> ReviewResult:
```

**Opt-in chain:**

| Mode | What runs |
|---|---|
| `classify_docs=False, use_llm_extraction=False` | v1.5 bit-identical (snapshot-equivalence CI gate) |
| `classify_docs=True, use_llm_extraction=False` | Sprint 1 behaviour (classifier banner + per-class severity bands) |
| `classify_docs=True, use_llm_extraction=True` | **Full v2 Sprint 2** — Track 1 + Track 2 records merged into alignment input |
| `classify_docs=False, use_llm_extraction=True` | Allowed but degenerate — LLM extraction uses `unknown` class → falls back to base prompt only (no per-class injection). Useful for Track-2-in-isolation testing. |

**Track 1 invariant preserved:** when `use_llm_extraction=False`, no LLM extraction call fires. v1's 261-test invariant suite + v2.0-mvp's snapshot-equivalence test continue passing unchanged on every Sprint 2 commit.

**Merge logic (Sprint 2 — naïve union):**

```python
if use_llm_extraction:
    _stage("llm_extract_a", "start")
    llm_records_a = extract_claims_from_doc(
        pdf_a,
        doc_class_a.doc_class if doc_class_a else DocClass.unknown,
    )
    pa = pa + llm_records_a   # Track 1 first, Track 2 appended
    _stage("llm_extract_a", "done")

    _stage("llm_extract_b", "start")
    llm_records_b = extract_claims_from_doc(
        pdf_b,
        doc_class_b.doc_class if doc_class_b else DocClass.unknown,
    )
    pb = pb + llm_records_b
    _stage("llm_extract_b", "done")
```

The dumb append works because:

- Phase 19's alignment gates (entity_tag agreement, family-prefix, OCR y-degeneracy) treat LLM records like OCR records (whole-page bbox at origin) → they don't mis-pair with native regex records on the same page.
- `entity_tag` agreement gate ensures `LLM(KRP-C-1600SP, tag="6")` only pairs with `LLM(KRP-C-1600SP, tag="6")` from the other doc.
- Duplicate detection (Track 1 and Track 2 both extracted the same parameter from the same page) is deferred to **Sprint 3's adjudicator** — both flow through Sprint 2.

**Caching:**

| Cache layer | Key | What's cached |
|---|---|---|
| diskcache namespace `llm-extract` | `sha256(page_text + model + prompt_version + doc_class)` | `PageExtractionResult.model_dump_json()` |
| Per-page granularity | Re-running on a doc with one page changed: ~99% cache hit | |

**Failure handling (mirrors Sprint 1 + Phase 20):** when an LLM call fails (timeout, malformed JSON, Pydantic validation error), that page contributes zero claims. Logged via existing `cost_event` ledger; pipeline keeps running. No `unknown`-fallback semantics for extraction — empty list is the right answer when extraction fails.

**Stage progress UX:** two new stage IDs (`llm_extract_a`, `llm_extract_b`) added to the existing stage_cb. UI shows them only when `use_llm_extraction=True`.

---

## §4. Prompt strategy — hybrid base + per-class injection

**Composition at runtime:**

```python
def _build_extraction_prompt(doc_class: DocClass) -> str:
    base = (PROMPTS_DIR / "_base.md").read_text(encoding="utf-8")
    class_file = PROMPTS_DIR / "extract" / f"{doc_class.value}.md"
    if not class_file.exists() or class_file.stat().st_size == 0:
        return (
            base
            + "\n\n## Class-specific guidance\n\n"
            + "_(none — extract any engineering parameters present in the text)_\n"
        )
    return (
        base
        + "\n\n## Class-specific guidance\n\n"
        + class_file.read_text(encoding="utf-8")
    )
```

**Base prompt contents (full version written in implementation):**

- What counts as a parameter (positive examples + negative examples — section headings, page numbers, footnotes don't count)
- Schema contract — exact `ExtractedClaim` field-by-field description
- Honest extraction rules:
  - Reassemble values that span line breaks ("5.75\n%Z" → "5.75 %Z")
  - Qualified values OK with confidence ≤ 0.7 ("approximately 5.75 %Z")
  - Empty-page response shape (return `{claims: [], notes: "no claims on this page"}`)
  - Never invent units
  - `entity_tag` only when source text clearly identifies the equipment; never guess
- Output JSON contract — strict, no fences

**Per-class injection — what each file adds:**

| File | Priority families + class-specific hints |
|---|---|
| `coordination_study.md` | `%Z`, `Transformer Rating`, `Fault Current`, `Fuse Designation`, `Time Dial`, `Pickup`. Few-shot examples from Eaton fixture patterns (`1000KVA XFMR Inrush`, `5.75%Z, liquid filled`, `Fault X1 20,000A RMS Sym`). Note: TCC plot images have numeric callouts the text layer doesn't capture — extract what's in the text. |
| `equipment_spec.md` | `Rated Power`, `Primary Voltage`, `Secondary Voltage`, `Rated Impedance`, `BIL`, `Frequency`, `Insulation Class`, `Temperature Rise`. Layout hint: nameplate tables are key:value pairs. |
| `relay_setting_sheet.md` | Pickup elements (`50P1`, `50P2`, `51P`, `51N`, `87T`), time-dial values, curve types, trip targets. Pickup values often qualified ("PCT2 = 30 %" or "Pickup: 600 A"). Treat element codes as `parameter_name` directly. |
| `hvac_schedule.md` | `CFM`, `GPM`, `Tonnage`, `kW`, `EWT/LWT`. Tabular schedules; one row per equipment tag (AHU-1, FCU-3) → row's tag becomes `entity_tag`. |
| `pid.md` | Instrument tags + setpoints (`PT-100 setpoint 50 psig`). Bubble notation; PV/PT/FT/LIC are tag prefixes. |
| `bom.md` | Part numbers, manufacturers, quantities. Line-item tables; each row's part number → `parameter_name="Part Number"`, BOM item number → `entity_tag`. |
| `civil_drawing.md` | Elevations (`FFE`, `TOC`, `BOC`, `IE`), grade slopes, soil bearing. Callouts overlaid on drawings; values often followed by unit (ft, in, °). |

**Why this works:**

- Schema is universal — one Pydantic model, one parser, one downcast path.
- Class knowledge in 7 audit-able markdown files; new doc classes added to Sprint 1's classifier just need a new file (no extractor code change).
- Falls back gracefully when class is `unknown` or per-class file is an empty stub (Sprint 1 shipped the 7 files as empty stubs — they're filled this sprint).

---

## §5. TDD checkpoints / 6 phases

Each phase ends green, tagged. v1's 261-test invariant + v2.0-mvp's snapshot-equivalence tests stay green at every checkpoint.

| # | Commit | Tests added | Tag |
|---|---|---|---|
| **25.1** | `ParameterRecord.provenance` field + back-compat tests | `tests/extract/test_provenance_field.py` — default `"regex"`, Track 1 still works, Pydantic serialization round-trip, every existing test that constructs `ParameterRecord` by hand still passes | `phase-25.1-extraction-provenance-field` |
| **25.2** | Schemas: `ExtractedClaim` + `PageExtractionResult` + downcast helper | `tests/llm_pipeline/test_extraction_schemas.py` — field validation, claim→ParameterRecord downcast preserves entity_tag + sets provenance="llm", confidence range, empty-claims case, frozen-model immutability | `phase-25.2-extraction-schemas` |
| **25.3** | Universal base prompt + 7 per-class injection files + `_build_extraction_prompt()` resolver | `tests/llm_pipeline/test_extraction_prompts.py` — base prompt loads, per-class injection assembles, unknown class falls back to base+generic, empty-stub falls back too, every class file produces parseable markdown | `phase-25.3-extraction-prompts` |
| **25.4** | `extract_claims_from_doc()` w/ mocked Claude calls (parallel per-page, diskcache, hallucination guard) | `tests/llm_pipeline/test_extract.py` — page-text rendering, ThreadPoolExecutor parallelism, JSON parse robustness (fenced + bare + prose-wrapped), diskcache hit on 2nd call, validation failure → empty list, per-page-failure isolation, hallucinated `span_text` (not a substring of page text) gets dropped pre-downcast | `phase-25.4-extraction-call` |
| **25.5** | Pipeline integration: `use_llm_extraction` kwarg + Track 1 ∪ Track 2 merge | `tests/e2e/test_pipeline_v2.py` — back-compat (`use_llm_extraction=False` is bit-identical to v2.0-mvp), Track 2 records appear with `provenance="llm"`, stage_cb fires `llm_extract_a/b`, snapshot-equivalence vs v1.5 on locked fixtures | `phase-25.5-extraction-pipeline` |
| **25.6** | Live-API eval against SEL paper + Eaton fixture + sprint exit tag | `tests/real_world/test_llm_extraction_live.py` — SEL paper ≥ 30 params (was 0), Eaton recovers ≥ 95% of v1 regex yield (≥ 50 of 52 params), Option 2 cross-doc still surfaces the 3 known flags | `phase-25.6-extraction-eval` then `v2.1-llm-extraction` |

**Gate between every step:** `uv run pytest --deselect tests/real_world` green; `uv run mypy src/` clean; `uv run ruff check .` clean.

**Phase 25.3 (prompts) is the biggest content chunk** — ~1.5 days of careful prompt engineering across 8 markdown files (base + 7 per-class).

**Phase 25.6's eval is the sprint exit criterion:**

| Gate | Threshold | Rationale |
|---|---:|---|
| SEL paper params extracted | ≥ 30 | Currently 0 with regex. Proves "captures prose-embedded params." |
| Eaton fixture regex yield recovery | ≥ 95% (≥ 50 of 52) | Proves Track 2 doesn't regress what Track 1 already catches when run alone. |
| Option 2 cross-doc flag count | exactly 3 (same as v1.5-mvp-ready) | Proves Track 2 doesn't introduce false-positive noise. |
| No `provenance="llm"` record has `bbox` non-zero | invariant | Catches accidental bbox-fabrication bugs. |

If any gate fails: iterate prompts (bump `PROMPT_VERSION` per the existing diskcache invalidation contract), don't tag v2.1-llm-extraction.

---

## §6. Cost + latency envelope

| Operation | Cost | Latency | Cached |
|---|---:|---:|---|
| `extract_claims_from_doc` cold (10-page doc) | ~$0.12 | ~5–10 s (parallel × 5) | No |
| `extract_claims_from_doc` warm | $0 | < 100 ms | Yes |
| Per-review pipeline addition (2 docs, ~20 pages total, cold) | ~$0.24 | +0–3 s wall-clock (parallel w/ alignment) | Per-page |
| Full SEL-paper eval cold | ~$0.20 | ~10 s | Yes |

**Sprint 2 build cost estimate:** $5–15 total Anthropic spend across prompt iteration + corpus runs. Logged via `cost_event` ledger; halt + review if single-session dev spend exceeds $25.

---

## §7. Sprint-2-specific risks

| # | Risk | Mitigation |
|---|---|---|
| S2-R1 | Sonnet underperforms vs Opus on prose extraction | Escalation path: bump `MODEL` constant in `extract.py` to `"claude-opus-4-7"`, re-run eval. 5× cost. Decision at phase 25.6 if SEL paper fails ≥ 30 gate. |
| S2-R2 | LLM hallucinates parameters not in source | Verifier guard inside `extract_claims_from_doc`: re-check that `span_text` is a verbatim substring of the page text (whitespace-flexible). Reject hallucinated claims pre-downcast. Has a dedicated test. |
| S2-R3 | Track 2 records mis-pair with Track 1 records on the same page | Phase 19 entity_tag + y-degeneracy gates already cover this. LLM records have whole-page bbox at origin → treated as OCR-style → never positionally mis-pair with native records on the same page. Adjudicator (Sprint 3) handles duplicates explicitly. |
| S2-R4 | Per-page parallel API calls overload Anthropic rate-limit | ThreadPoolExecutor capped at `max_workers=5` (same as Sprint 1 OCR). SDK auto-retry on 429. |
| S2-R5 | Cost runaway on large docs (50+ pages) | Diskcache means re-runs free. Per-page granularity → partial cache hits OK. Soft cap via `cost_event` ledger; hard cap configurable. |
| S2-R6 | Prompt drift across class files | Single base prompt for schema/contract; class files add domain hints only. Regression test: every per-class file gets concatenated with base + parsed as valid markdown structurally. |
| S2-R7 | Determinism loss on flag set across runs | Diskcache makes warm runs deterministic. Cold runs may surface different LLM records on identical input. Mitigation: existing v1.2-phase test asserts flag *parameter-set* stability not absolute confidence (carry forward to Track 2). |

**S2-R3 is the architectural-safety risk.** Mitigation: snapshot-equivalence test on Option 1 + Option 2 fixtures (`use_llm_extraction=False` produces same flags as v1.5) gates every Sprint 2 commit in CI.

---

## Pointers

- Sprint 1 spec (classifier): `docs/superpowers/specs/2026-05-22-sprint-1-doc-class-classifier-design.md`
- Sprint 1 baseline (this sprint builds on): tag `v2.0-mvp`
- v1 frozen reference: `funcpointer/interlock-ai @ v1.5-mvp-ready` (commit `fc6f24a`)
- v2 baseline: tag `v2.0-baseline-from-v1.5-mvp-ready`
- Pivot plan: `docs/PIVOT_PLAN.md`
- Project rules (v2-specific, gitignored): `CLAUDE.md`
- v1 known-limits this sprint closes:
  - `docs/TDD.md` § "Open questions + future work" → "Prose extraction (open): SEL-style prose-heavy papers are a documented zero-yield case for the regex extractor."
  - `docs/BACKLOG.md` R-M (prose-embedded parameter extraction)
