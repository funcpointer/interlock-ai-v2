# InterLock AI v2 — Pivot Plan

**Source:** `funcpointer/interlock-ai @ v1.5-mvp-ready`
**Baseline tag in this repo:** `v2.0-baseline-from-v1.5-mvp-ready`
**Status of v1 repo:** frozen at `v1.5-mvp-ready`; bug-fix-only commits permitted, feature work moves here.

---

## Why pivot

v1 shipped a deterministic, regex-driven, IEEE-cited cross-doc review tool. It catches the AES decimal-error class on coordination-study fixtures, has 261 passing tests, a live demo, and an honest scope statement (`docs/TDD.md` § "Known limits"). That ceiling is real:

- Regex extractors are narrow. Prose-heavy docs (SEL field-case paper) yield zero parameters.
- Alignment heuristics (entity_tag, family prefix, OCR y-degeneracy) are overfit to fuse-coordination tables. HVAC schedules, P&IDs, BOMs, spec sheets with right-aligned ID columns — untested.
- Severity bands are hardcoded with IEEE citations but no per-project ontology loader.
- The LLM significance judge runs as enrichment only; it does not participate in extraction, pairing, or classification.
- No document-class detection. Same code path for every doc shape.

v2 inverts the leverage: foundation models drive extraction + pairing + classification + reasoning; the v1 deterministic path becomes the **floor** — a sanity-check sidecar that catches LLM hallucinations and gives regulators an auditable, reproducible baseline.

---

## Architecture — two-track hybrid

```
PDF (any class, any layout)
 │
 ├──> Track 1 — Deterministic Floor (frozen)
 │     PyMuPDF + Camelot + regex extractors
 │     entity_tag + heuristic gates
 │     IEEE/IEC tolerance bands
 │     Same ParameterRecord + Flag schema
 │
 ├──> Track 2 — Foundation-Model Ceiling (new)
 │     • Doc-class classifier (VLM, first page)
 │     • Structured extraction (messages.parse + Pydantic ontology)
 │     • LLM pairing reranker over Track 1 candidates
 │     • Standards-as-RAG (per-flag clause + edition retrieval)
 │     • Coupled-effect traversal of Phase-14 claim graph
 │     • Always-on chain-of-thought severity with cited reasoning
 │
 └──> ADJUDICATOR
       • Track 1 ∧ Track 2 agree on value & pairing → high-confidence flag, `✓ confirmed`
       • Only Track 1 → `⚙ rule-based`
       • Only Track 2 → `🧠 AI-detected` (regex missed; verify the extraction)
       • Disagree on value → surface both as siblings
       Audit trail records track-of-origin per accepted flag.
```

Both tracks emit the same `Flag` schema so downstream UI, citation rendering, accept/dismiss, and JSON export stay unchanged. Reviewer gains a **provenance filter** to view "deterministic only", "AI only", or "both agree" subsets.

---

## What v2 keeps from v1 (unchanged)

- Severity ≠ confidence axis separation
- `pairing_confidence` as an orthogonal score
- bbox-anchored citation snippets
- Directional authority (source-of-truth vs deviation candidate)
- Reviewer accept/dismiss/override + JSON audit export
- Honest unpaired-records surface
- Diskcache pattern (still cost-saver even at frontier model rates)
- Tolerance bands cited from public standards (precedence ladder added)
- The three demo fixture scenarios (revision diff + cross-doc + scanned OCR)
- 261-test deterministic invariant suite (gates Track 1 forever)

## What v2 drops or demotes from v1

| v1 component | v2 disposition |
|---|---|
| Regex extractors as primary path | Demoted to Track 1 fallback + sanity-checker |
| Hand-curated canonical glossary (`_CANONICAL`) | Becomes labelled training data for fine-tuned embeddings |
| Phase 19 heuristic gates (family prefix, count-ambiguity, y-degeneracy) | Kept inside Track 1; bypassed by Track 2's LLM pairing reranker |
| Single-model OCR | Kept; multi-model consensus is a post-hybrid R&D item |
| Hardcoded per-fixture authority | Replaced by per-class + per-project precedence ladder |
| "Cross-document mode" toggle | Removed — Track 2 auto-detects doc class |
| Vision OCR as opt-in | Always-on for layout-aware extraction (Track 2 reads every page image) |

---

## Sprint roadmap

Each sprint ships a green tag; v1 stays frozen throughout.

### Sprint 1 — Document classifier (2 weeks)

**Deliverable.** First reviewer-visible v2 capability.

- `src/interlock/llm_pipeline/classify.py` — single VLM call on first page returning `DocClass` (one of: `coordination_study`, `equipment_spec`, `relay_setting_sheet`, `hvac_schedule`, `pid`, `bom`, `civil_drawing`, `unknown`).
- Per-class extraction prompt registry (`prompts/extract/<class>.md`).
- Per-class tolerance band override (extends `detect/tolerances.py::TOLERANCE_TABLE`).
- Per-class authority hierarchy (data sheet > spec > study > drawing).
- UI displays "Detected: Coordination Study · IEEE Std 242 tolerances active".
- 5 labelled docs per class (30 total) for the classifier's eval set.

**Exit gate.** Classifier hits ≥ 90 % on the 30-doc held-out set; UI shows detected class on every run.

### Sprint 2 — LLM extraction module (3 weeks)

- `src/interlock/llm_pipeline/extract.py` — `messages.parse(output_format=Claim[])` per page with full equipment ontology Pydantic schema.
- Schema covers entities (XFMR-001, P-101, T-200, CB-52, …), claims with provenance (page, bbox, span_text, source_role), relationships (impedance OF transformer X).
- Solves the SEL prose paper case (zero → expected ≥ 30 params).
- Tool-use: model calls Pint mid-extraction for normalization.
- Diskcached per page (model + prompt_version + sha256(page-text)).

**Exit gate.** Live API run on SEL paper extracts ≥ 30 parameters; live API run on the locked Eaton fixture recovers ≥ 95 % of v1's regex yield (no regression).

### Sprint 3 — Adjudicator + provenance UX (2 weeks)

- `src/interlock/adjudicator.py` — merges Track 1 and Track 2 `Flag` lists into a single ranked list with per-flag `provenance: Literal["both", "rule_only", "llm_only"]`.
- UI flag header gains provenance badge.
- Sidebar filter: deterministic-only / AI-only / both / all.
- Audit trail captures provenance per accepted flag.

**Exit gate.** Both tracks run end-to-end on all three locked demo fixtures; reviewer can filter by provenance; JSON export records track-of-origin.

### Sprint 4 — LLM pairing reranker (3 weeks)

- `src/interlock/llm_pipeline/pair.py` — for each ambiguous multi-instance bucket (Track 1's `pairing_confidence < 0.75` cases), the LLM reads context, ranks Track 1's candidate pairs with reasoning, returns a cross-encoder-style score.
- Weak pairs gain LLM rationale instead of a generic `⚠️ weak pair` badge.
- Replaces Phase 19's overfit heuristics in spirit (heuristics stay in Track 1 for sanity-check).
- Streamed output: pair-by-pair reasoning surfaces as the model thinks.

**Exit gate.** On the user-reported failure cases (KRP-C-1600SP vs LPS-RK-400SP, 150 kVA vs 100 kVA), Track 2 reranker produces correct or correctly-no-pair outcomes ≥ 90 % of the time.

### Sprint 5 — Standards-as-RAG + coupled-effect graph (3 weeks)

- `src/interlock/llm_pipeline/rag.py` — vector store of IEEE/IEC clauses + project tolerance docs; per-flag retrieval of applicable standard edition (C57.12.00-2015 vs -2022) + project override.
- `src/interlock/llm_pipeline/graph.py` — traverses the Phase-14 SQLite claim graph; on accept of an impedance flag, identifies dependent claims (relay pickup, coordination margin, fault duty, conductor sizing) and surfaces them as deferred flags.
- Per-project tolerance ontology loaded automatically from `tolerances.yaml` if present.

**Exit gate.** Every Track 2 flag carries cited reasoning naming the standard clause + edition; accepting a transformer impedance flag surfaces ≥ 1 dependent claim from the claim graph.

### Sprint 6 — Per-class eval + calibration (2 weeks)

- Per-doc-class gold sets (5–10 labelled cases per class, 6+ classes).
- Continuous CI gates on each class.
- Confidence calibration: predicted confidence vs reviewer accept-rate, plotted weekly.
- Bench against published incident database extracts (NERC alerts, IEEE PES case studies).

**Exit gate.** Eval pipeline runs in CI; per-class precision/recall reported on every PR.

---

## Cost / latency envelope

| | v1 (current) | v2 (post-Sprint 6) |
|---|---:|---:|
| Per-flag cost | $0.02–0.05 (Opus judge, opt-in) | $0.05–0.20 (LLM extraction + reasoning per flag, always-on) |
| Per-review cost (~50 flags) | < $0.10 | $0.50–3 |
| Latency per review | 30 s warm / 60 s cold | 60–120 s (Track 2 ~30–60 s, parallel where possible) |
| Generalization (doc classes) | 1 (coordination study) | 6+ |
| Prose extraction yield | 0 on SEL paper | ~80 %+ |
| Reviewer trust signal | Single confidence score | Three orthogonal scores + provenance + cited reasoning |

Still 10–100× cheaper than the senior-engineer hour each review replaces.

---

## Risk register (v2-specific)

| Risk | Mitigation |
|---|---|
| LLM hallucinations on extraction | Adjudicator requires Track 1 agreement or flags as AI-only with prominent provenance badge |
| Determinism loss (same docs → different flags across runs) | Diskcache per page + per pair; self-consistency sampling on critical decisions; audit trail records every track output |
| Black-box severity reasoning | Every Track 2 flag cites the standard clause + edition + project override that produced it |
| Cost runaway on large doc sets | Per-run cost ledger; hard cap configurable per project; LLM extraction only triggered on pages where regex coverage is low |
| Track 2 breaks Track 1's invariants | Track 1 frozen; CI gates Track 1's 261 tests on every v2 commit |
| Per-project standards override drift | Decision-log entry on every override; reviewer audit trail captures band-of-origin per flag |

---

## What to expect when

| Milestone | When | Demo-able |
|---|---|---|
| Sprint 1 ships | week 2 | "v2 detected this as a P&ID and applied process tolerances" |
| Sprint 2 ships | week 5 | SEL prose paper extracts 30+ params |
| Sprint 3 ships | week 7 | Provenance badges on every flag |
| Sprint 4 ships | week 10 | Reasoned pairing on multi-instance ambiguous buckets |
| Sprint 5 ships | week 13 | Cited reasoning + coupled-effect propagation |
| Sprint 6 ships | week 15 | Per-class CI eval running on every commit |

**Total:** ~15 weeks / 3.5 months from `v2.0-baseline-from-v1.5-mvp-ready` to feature-complete hybrid.

---

## Pointers

- Frozen v1 repo: <https://github.com/funcpointer/interlock-ai>
- v1 frozen tag: `v1.5-mvp-ready` (commit `fc6f24a`)
- v2 baseline tag (this repo): `v2.0-baseline-from-v1.5-mvp-ready`
- v1 known limits disclosure (the gaps this pivot closes): `docs/TDD.md` § "Known limits (Phase 19 honesty disclosure)"
- v1 backlog ranking (R-A through R-P): `docs/BACKLOG.md` — Sprint 1–6 above implements R-A, R-B, R-C, R-F, R-G, R-I, R-M in that order.
