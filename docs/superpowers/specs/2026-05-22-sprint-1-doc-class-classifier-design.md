# Sprint 1 Design — Doc-Class Classifier (Hybrid Scope)

**Project:** InterLock AI v2
**Sprint:** 1 (week 1–2 of 6-sprint hybrid pivot)
**Baseline:** `v2.0-baseline-from-v1.5-mvp-ready`
**Approved:** 2026-05-22
**Exit tag:** `v2.0-mvp`

---

## Purpose

Sprint 1 delivers the first reviewer-visible v2 capability: a foundation-model classifier that detects what *kind* of engineering document the reviewer just uploaded (coordination study, equipment spec, relay setting sheet, HVAC schedule, P&ID, BOM, civil drawing, or unknown). The classification drives per-class severity-band selection, per-class authority hierarchy resolution, and (Sprint 2 onward) per-class extraction prompts. v1's deterministic pipeline runs unchanged when classification is off or falls back to `unknown`.

This spec is the source-of-truth for what gets built. Implementation plan lives in the subsequent writing-plans output.

---

## §1. Approach + components

**Approach: multi-page evidence aggregation — pages 1, 2, last.**

Page-sampling logic:

| Page count in doc | Pages rendered to model |
|---|---|
| 1 | page 1 |
| 2 | pages 1, 2 |
| ≥ 3 | pages 1, 2, last |

Rationale: title/cover info on page 1 is often decorative; ToC or system-description on page 2 reveals doc structure; revision block on the last page reveals doc type + version. Three images per call cap input-token cost while covering the dominant signal locations.

**Rejected alternatives:**

| Alternative | Why not |
|---|---|
| Page-1 only single-call | Cover page often blank; misclassifies docs with decorative title pages. |
| Full-document multi-image | Token-cost blows up on 50+ page docs; marginal accuracy gain past 3 pages. |
| VLM + text-embedding ensemble | More complex orchestration; small accuracy gain over a strong VLM alone. Defer until ground truth shows marginal lift is real. |

**Model:** `claude-opus-4-7` (reasoning task). Sonnet 4.5 stays in the OCR path for character recognition; Opus is wired in `src/interlock/llm/client.py` via the cached wrapper.

**Components shipped this sprint:**

- `src/interlock/llm_pipeline/__init__.py` — new package root.
- `src/interlock/llm_pipeline/schemas/doc_class.py` — `DocClass` enum + `DocClassification` Pydantic model.
- `src/interlock/llm_pipeline/classify.py` — `classify_doc(pdf_path) -> DocClassification` + multi-image VLM call + diskcache wrapper.
- `src/interlock/llm_pipeline/prompts/classify.md` — system prompt + class definitions (single source of truth).
- `src/interlock/llm_pipeline/prompts/extract/<class>.md` — directory scaffold + README; empty stubs filled in Sprint 2.

**Cost envelope:** 3 page images @ 300 DPI per call ≈ 4500 input tokens × Opus $15/MTok ≈ **$0.07 per classification**. Diskcached on PDF content hash; warm re-runs cost $0.

---

## §2. Schema

```python
# src/interlock/llm_pipeline/schemas/doc_class.py
from enum import Enum
from pydantic import BaseModel, Field

class DocClass(str, Enum):
    coordination_study     = "coordination_study"
    equipment_spec         = "equipment_spec"
    relay_setting_sheet    = "relay_setting_sheet"
    hvac_schedule          = "hvac_schedule"
    pid                    = "pid"          # Piping & Instrumentation Diagram
    bom                    = "bom"
    civil_drawing          = "civil_drawing"
    unknown                = "unknown"

class DocClassification(BaseModel):
    doc_class: DocClass
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str = Field(
        description="1-3 sentences explaining the classification choice"
    )
    detected_indicators: list[str] = Field(
        default_factory=list,
        description=(
            "Concrete visual / textual signals that drove the call "
            "(e.g. 'TCC log-log axes', 'one-line diagram symbols', "
            "'nameplate parameter table', 'tag-style instrument IDs')"
        ),
    )
    pages_consulted: list[int] = Field(
        default_factory=list,
        description="Page numbers rendered to the model (1-indexed)"
    )
```

**Field rationale:**

| Field | Purpose |
|---|---|
| `doc_class` | Routing decision; enum so per-class registries can key off it. |
| `confidence` | Drives `unknown`-fallback threshold; surfaced in UI banner. |
| `reasoning` | Honest framing — reviewer can argue with the model's call. |
| `detected_indicators` | Concrete grounded evidence; useful for debugging classifier drift. |
| `pages_consulted` | Audit trail — which pages did the model actually see? |

**Unknown handling:** when `confidence < 0.6`, classifier returns `DocClass.unknown` regardless of the model's raw output. Downstream pipeline treats `unknown` as the v1 default (no per-class routing) — preserves the Track 1 invariant.

---

## §3. Pipeline integration

**Placement:** classifier runs in parallel with `ingest()` via `ThreadPoolExecutor`. Classifier ~3–6 s warm; ingest ~5–10 s; net pipeline wall-clock unchanged because they overlap. Cached classifications are sub-second.

```
PDF ─┬─> classify_doc(pdf_path) → DocClassification          [NEW, parallel]
     │     • render pages 1, 2, last @ 300 DPI
     │     • single Opus call with Pydantic-validated output
     │     • diskcached on sha256(pdf bytes) + model + prompt_version
     │
     └─> ingest(pdf_path) → IngestResult                     [unchanged]
```

**`ReviewResult` schema extension:**

```python
@dataclass(frozen=True)
class ReviewResult:
    flags: list[Flag]
    unpaired_a: list[ParameterRecord]
    unpaired_b: list[ParameterRecord]
    # NEW Sprint 1 — both default None for back-compat with 261 existing tests
    doc_class_a: DocClassification | None = None
    doc_class_b: DocClassification | None = None
```

**New pipeline kwarg:** `classify_docs: bool = False` on `review_two_documents_full()`. Default off keeps every existing test green unchanged; UI flips it on by default for v2.

**Per-class routing — Sprint 1 hybrid scope:**

| Hook | Sprint 1 | Sprint 2+ |
|---|---|---|
| Per-class extraction prompt registry | Directory scaffolding only — `prompts/extract/<class>.md` empty stubs + README explaining contract | Sprint 2 fills with LLM extraction prompts |
| Per-class tolerance band overrides | Concrete seeded overrides for `coordination_study` (= v1 defaults, made explicit), `equipment_spec` (tighter nameplate-tolerance bands), `relay_setting_sheet` (relay-pickup bands). Other 5 classes inherit v1 defaults via fallback. | Per-project reviewer-loadable overrides (BACKLOG R-G) |
| Per-class authority hierarchy | Concrete maps for `transformer_params` and `relay_settings` families; falls back to v1's "Doc A authoritative" for everything else | Sprint 5 — Standards-as-RAG |
| `unknown` behaviour | Falls back to v1 pipeline path. No new behaviour. | Same |

**Track 1 invariant:** when `classify_docs=False` OR both docs classify as `unknown`, pipeline output is bit-identical to v1.5-mvp-ready. CI gate enforces this via snapshot-equivalence tests against the locked Option 1 + Option 2 fixtures.

---

## §4. UI surface

**Doc-class banner** above flag list, two side-by-side cards:

```
┌─────────────────────────────────────────┐   ┌─────────────────────────────────────────┐
│ 📄 Doc A: Equipment Spec (0.94)         │   │ 📄 Doc B: Coordination Study (0.97)     │
│                                         │   │                                         │
│ "Nameplate parameter table; IEEE C57   │   │ "Log-log TCC curves on multiple pages; │
│ layout; rated kVA + primary/secondary  │   │ fuse-rating table; Eaton title block"   │
│ voltage rows"                           │   │                                         │
└─────────────────────────────────────────┘   └─────────────────────────────────────────┘

Authority: spec → study (per per-class hierarchy for transformer_params)
```

Implementation: two `st.info()` cards in `st.columns(2)`. Bottom line shows the applied authority direction with rationale.

**Detected indicators expander** (collapsed by default):

```
▶ Why this classification? (3 indicators)
```

**Confidence color:**

| `confidence` | UI styling |
|---|---|
| ≥ 0.85 | `st.success` (green) — "high-confidence classification" |
| 0.60–0.85 | `st.info` (blue) — default |
| < 0.60 | `st.warning` (yellow) — "classifier uncertain; v1 default routing" |

**Sidebar toggle:** `Enable doc-class routing` (default ON in v2). Off bypasses classifier; pipeline behaves as v1.5. Lets reviewers compare v1-vs-v2 behaviour on the same upload.

**Honest framing rationale:** reviewers must see *what* was classified and *why*, not just the routing decision. "Model says spec because of these three signals" lets the reviewer overrule when wrong. Mirrors Phase 19's known-limits + unpaired-records honesty norm.

---

## §5. Per-class hook scaffolding (Sprint 1 concrete entries)

**Tolerance overrides** — `src/interlock/detect/tolerances.py` gains a `DocClass`-keyed override layer:

```python
DOC_CLASS_TOLERANCE_OVERRIDES: dict[DocClass, dict[str, ToleranceBand]] = {
    DocClass.equipment_spec: {
        # Tighter — manufacturer nameplate is the authoritative source.
        "impedance_pct":    ToleranceBand(tolerance=5.0,  major=15.0, critical=40.0,
                                          source="IEEE C57.12.00-2015 §9.1 (tightened for nameplate)"),
        "rated_power_kva":  ToleranceBand(tolerance=2.5,  major=7.5,  critical=30.0,
                                          source="IEEE C57.12.00-2015 §5.10 + NEMA TR 1"),
    },
    DocClass.relay_setting_sheet: {
        "fault_current_a":  ToleranceBand(tolerance=5.0,  major=15.0, critical=40.0,
                                          source="IEEE Std 242 (Buff Book) §10.5"),
    },
    DocClass.coordination_study: {
        # v1 defaults — explicit empty entry so the routing path is audit-visible.
    },
    # hvac_schedule, pid, bom, civil_drawing, unknown — intentionally absent.
    # Inherit v1 TOLERANCE_TABLE via the fallback chain.
}

def classify_severity(family: str, deviation_pct: float, doc_class: DocClass | None = None):
    if doc_class and doc_class in DOC_CLASS_TOLERANCE_OVERRIDES:
        override = DOC_CLASS_TOLERANCE_OVERRIDES[doc_class].get(family)
        if override:
            return _classify_against(override, deviation_pct)
    return _classify_against(TOLERANCE_TABLE[family], deviation_pct)
```

**Authority hierarchy** — `src/interlock/detect/authority.py` gains per-class precedence maps:

```python
DOC_CLASS_AUTHORITY: dict[str, list[DocClass]] = {
    "transformer_params": [
        DocClass.coordination_study,
        DocClass.relay_setting_sheet,
        DocClass.equipment_spec,        # winner
    ],
    "relay_settings": [
        DocClass.coordination_study,
        DocClass.equipment_spec,
        DocClass.relay_setting_sheet,   # winner
    ],
}

def resolve_authority(
    doc_a_class: DocClass,
    doc_b_class: DocClass,
    parameter_family: str,
) -> tuple[Side, str]:
    """Return ('doc_a' | 'doc_b', rationale)."""
```

When `parameter_family` has no entry (Sprint 1 ships only `transformer_params` + `relay_settings`), falls back to v1's hardcoded "Doc A authoritative" rule.

**Extraction prompt registry — scaffold only:**

```
src/interlock/llm_pipeline/prompts/extract/
├── coordination_study.md   # empty stub — Sprint 2 fills
├── equipment_spec.md
├── relay_setting_sheet.md
├── hvac_schedule.md
├── pid.md
├── bom.md
├── civil_drawing.md
└── README.md               # documents the contract + Sprint 2 plan
```

Empty stubs prevent ImportError in Sprint 2; README documents the contract.

**Classes that actually do something in Sprint 1:** `coordination_study`, `equipment_spec`, `relay_setting_sheet`. The other 5 classify correctly but inherit v1 behaviour end-to-end. Honest scope statement in v2 TDD § "Known limits — Sprint 1."

---

## §6. Eval corpus + acceptance gate

**Corpus shape:** 15 real + 5 synthetic = 20 docs total.

| Class | Real | Synthetic | Source candidates for real |
|---|---:|---:|---|
| `coordination_study` | 3 | 0 | Existing `doc_a_60pct.pdf`, `doc_b_90pct.pdf`; one more from Bussmann / Eaton / SquareD public sample libraries |
| `equipment_spec` | 2 | 1 | Public transformer / motor data sheets (ABB, Siemens, GE downloads); existing synthetic `spec_xfmr_001.pdf` |
| `relay_setting_sheet` | 2 | 0 | SEL / ABB application notes (existing `real_sel_xfmr_protection.pdf` is one) |
| `hvac_schedule` | 2 | 1 | Public ASHRAE / LEED-submitted mechanical schedules |
| `pid` | 2 | 1 | Public chemical / oil-and-gas EPC sheets; ISA-5.1 samples |
| `bom` | 1 | 1 | Public engineering submittals (SCADA, switchgear assemblies) |
| `civil_drawing` | 2 | 1 | Public civil / grading / DOT submittals |
| `unknown` | 1 | 0 | Existing `real_ieee_xfmr_spec_guide.pdf` — IEEE guide, not an engineering deliverable |
| **Total** | **15** | **5** | |

**Synthetic generation pattern** (same as v1's `spec_xfmr_001.pdf`):
- `fixtures/synthesis/generate_<class>.py` — deterministic Python (reportlab / fpdf2) → PDF
- SHA-256 committed to `fixtures/pdfs/HASHES.txt`
- Disclosed in `docs/AUTHORSHIP.md` and labelled `source: synthetic` in gold YAML

**Gold YAML:** `fixtures/eval/gold_doc_class.yaml`

```yaml
docs:
  - path: fixtures/pdfs/doc_a_60pct.pdf
    expected_class: coordination_study
    expected_min_confidence: 0.85
    source: real
    notes: "Eaton sample coordination study; TCC curves on multiple pages"
  # ... 19 more entries
acceptance:
  overall_accuracy_min: 0.90
  real_only_accuracy_min: 0.85
  synthetic_only_accuracy_min: 1.00
```

**Acceptance gates (CI):**

| Gate | Threshold | Rationale |
|---|---:|---|
| Overall accuracy | ≥ 90 % (≥ 18 / 20) | Sprint exit criterion per PIVOT_PLAN.md |
| Real-doc-only accuracy | ≥ 85 % (≥ 13 / 15) | Honest about real-world variance |
| Synthetic-only accuracy | 100 % (5 / 5) | We crafted them; the classifier must hit them |
| Per-class recall (where ≥ 2 examples) | reported, not gated | Single miss can drop small-bucket recall to 33 %; surface for Sprint 2 corpus planning |
| `unknown` precision | 100 % | A returned `unknown` must really not have been any of the 7 other classes |

**Eval harness:** `scripts/run_doc_class_eval.py` writes `eval/results/doc_class.json` (overall + per-class + per-doc verdict) and `eval/results/doc_class_report.md`. Runs in CI behind `--with-live-api` flag (default off; manual trigger).

**Honest scope statement** ships in `docs/TDD.md` § "Known limits — Sprint 1":
- 20-doc corpus is small; per-class recall < 5 examples has high variance.
- Real-doc sourcing skews toward electrical (our domain); civil + HVAC + P&ID + BOM coverage is lighter.
- Synthetic docs too clean; real-world variance unmeasured for the classes they cover.

---

## §7. TDD checkpoints (7 phases / commits)

Each phase ends green, tagged. v1's 261-test invariant suite stays green at every checkpoint.

| # | Commit | Tests added | Tag |
|---|---|---|---|
| **24.1** | Schemas + module skeleton | `tests/llm_pipeline/test_schemas.py` — enum values, Pydantic validation, `unknown` fallback rule. All mocked. | `phase-24.1-classifier-schemas` |
| **24.2** | `classify_doc()` w/ multi-image VLM call (mocked) | `tests/llm_pipeline/test_classify.py` — mock `_call_claude`; prompt structure; multi-image payload (1 / 2 / 3 pages); JSON parse robustness; diskcache key includes all consulted page sha256s | `phase-24.2-classifier-call` |
| **24.3** | Live-API smoke test on existing 6 fixtures (slow-marked) | `tests/real_world/test_doc_class_live.py` — asserts each existing fixture classifies correctly. Cost ~$0.40 / run. | `phase-24.3-classifier-live` |
| **24.4** | Corpus expansion: 9 real + 5 synthetic added → 20 total | `fixtures/synthesis/generate_<class>.py` × 5 + `HASHES.txt` updates + `gold_doc_class.yaml` + `scripts/run_doc_class_eval.py` + 1 test asserting gold YAML well-formed | `phase-24.4-classifier-corpus` |
| **24.5** | Acceptance-gate eval run + report committed | `eval/results/doc_class.json` + `eval/results/doc_class_report.md` committed; `tests/eval/test_doc_class_gate.py` asserts thresholds; per-class report rendered | `phase-24.5-classifier-eval` |
| **24.6** | Pipeline integration (`classify_docs=False` default) + `ReviewResult` schema extension | `tests/e2e/test_pipeline.py` — back-compat (classify_docs=False bit-identical to v1.5) + new test (classify_docs=True populates doc_class_a / doc_class_b) | `phase-24.6-classifier-pipeline` |
| **24.7** | Per-class hook scaffolding (tolerance overrides + authority for 3 classes; extraction stubs) + UI banner + sidebar toggle | `tests/detect/test_tolerances_per_class.py`, `tests/detect/test_authority_per_class.py`, `tests/e2e/test_pipeline.py::test_unknown_falls_back_to_v1`, UI compile check | `phase-24.7-classifier-hooks` then `v2.0-mvp` |

**Gate at every step:** `uv run pytest --deselect tests/real_world` green; `uv run mypy src/` clean; `uv run ruff check .` clean.

**Phase 24.4** is the biggest single chunk — finding 9 real docs + writing 5 deterministic synth generators. Budget ~1.5 days of the ~2-week sprint.

**Phase 24.5 is the sprint exit criterion.** Below 90 % overall accuracy = stop, expand corpus / iterate prompt before proceeding to 24.6.

---

## §8. Cost + latency envelope

| Operation | Cost | Latency | Cached |
|---|---:|---:|---|
| `classify_doc()` cold | ~$0.07 | 3–6 s | No |
| `classify_doc()` warm | $0 | < 50 ms | Yes |
| Full eval run, 20 docs cold | ~$1.40 | ~60 s | No |
| Full eval run, warm | $0 | ~2 s | Yes |
| Per-review (2 docs, both cold) | ~$0.14 | +0 s wall-clock (parallel w/ ingest) | Per-doc |
| Per-review (warm) | $0 | +0 s | Per-doc |

**Sprint build cost estimate:** $5–10 total Anthropic spend (corpus building + eval calibration + dev iteration). v1 phase-13-through-20 total spend was ~$0.30; Sprint 1 is the first phase where multi-page reasoning meaningfully changes cost.

**Hard cap:** `cost_event` ledger per call; halt + review if single-session dev spend exceeds $20 (same canary pattern v1 used for prompt-caching invariants).

---

## §9. Sprint-1-specific risks

| # | Risk | Mitigation |
|---|---|---|
| S1-R1 | Classifier accuracy < 90 % gate | Iterate prompt; if persistent, escalate to self-consistency sampling (3 samples, majority vote, 3× cost); falls back to `unknown` which preserves v1 behaviour |
| S1-R2 | Real-corpus sourcing harder than expected for some classes | Synthetic-fill is the escape hatch; lean harder on synthetic if needed; honest scope statement in v2 TDD |
| S1-R3 | Per-class tolerance overrides break Track 1 invariants | `classify_docs=False` default + `unknown` fallback preserve v1 path bit-identically; 261-test gate + snapshot-equivalence tests on locked fixtures |
| S1-R4 | Cost spike during dev iteration | Diskcache aggressively; `cost_event` ledger monitored; $20 sprint-day soft cap |
| S1-R5 | Multi-image VLM call fails on small / weird PDFs | `classify_doc()` returns `DocClassification(doc_class=unknown, confidence=0.0, reasoning="render failure: {e}")` instead of raising; pipeline continues |

**S1-R3 is the architectural-safety risk.** Mitigation reinforces the v2 invariant: `classify_docs=False` ⇒ bit-identical to v1.5. CI snapshot-equivalence test on Option 1 + Option 2 locked fixtures enforces this on every PR.

---

## Pointers

- v1 frozen tag: `funcpointer/interlock-ai @ v1.5-mvp-ready` (commit `fc6f24a`)
- v2 baseline tag: `v2.0-baseline-from-v1.5-mvp-ready`
- Pivot plan: `docs/PIVOT_PLAN.md`
- v2 project rules: `CLAUDE.md` (gitignored; per-session AI guidance)
- v1 known-limits this sprint closes: `docs/TDD.md` § "Known limits (Phase 19 honesty disclosure)" — heuristic gates overfit to fuse-coordination tables; doc-class detection absent.
