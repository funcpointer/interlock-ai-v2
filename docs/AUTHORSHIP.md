# InterLock AI MVP — Authorship Note

## What I personally built

All source under `src/interlock/`:

- `ingest/text.py` — PyMuPDF span extraction with bbox, plus `aggregate_line_spans` for merging same-y spans before regex matching.
- `ingest/tables.py` — Camelot lattice/stream wrapper with typed cells.
- `ingest/vision_fallback.py` — Claude Sonnet 4.5 vision fallback with robust JSON parsing (handles fenced/bare/prose-wrapped responses).
- `ingest/pdf.py` — orchestrator with low-coverage page routing.
- `extract/units.py` — Pint registry with `%` 0.01-ratio definition and string-equality short-circuit for non-numeric tokens (fuse part numbers).
- `extract/sections.py` — page-scoped heading attribution with three patterns suited to Eaton-style numbering.
- `extract/parameters.py` — domain-specific pattern set yielding typed `ParameterRecord` with citation tuple.
- `align/exact.py` — layout-anchored exact-name pairing with greedy 1-to-1 positional minimization.
- `align/semantic.py` — Voyage embedding alignment with same-page constraint and string-record exclusion (two guards added after observing real-fixture noise).
- `align/embed.py` — Voyage `voyage-3` embedder (Voyage-only, no fallback provider — OpenAI was dropped per project constraints).
- `align/combiner.py` — exact-precedent dedupe.
- `detect/authority.py` — hardcoded MVP authority decision.
- `detect/confidence.py` — extraction × match × authority formula.
- `detect/mismatch.py` — directional Flag emission with rationale.
- `citation/render.py` — bbox-highlighted PNG snippet renderer.
- `pipeline.py` — end-to-end orchestrator.
- `ui/app.py` — Streamlit single-page review UI with Accept/Dismiss/Export controls and slider-driven suppression threshold.

Fixture engineering:
- `scripts/page_scan.py` — Doc A per-page text dump used to select mutation sites.
- `scripts/make_symbol_probe.py` — generates the symbol-fidelity probe PDF with Arial Unicode embedded.
- `scripts/run_eval.py` — evaluation harness; writes per-id results and aggregate metrics.
- `fixtures/mutations/apply_mutations.py` — **deterministic mutation engine.** Reads a 6-entry mutation table and rewrites Doc A into Doc B via PyMuPDF redaction-with-replacement. Re-runnable from source any time.
- `fixtures/mutations/MUTATIONS.md` — full mutation log (3 TPs, 2 FPs, 1 FN).
- `fixtures/eval/gold.yaml` — labeled evaluation set derived from the mutation log.

Tests:
- ~70 tests across 12 modules covering ingest, extraction, alignment, detection, citation, eval harness, and an e2e smoke. Each phase landed via TDD: failing test → minimal implementation → green → commit. 11 phase tags in git history (`phase-0-scaffold` … `phase-9-deploy`).

Documentation (all written by me from scratch as part of the engineering process, not generated):
- `docs/SCOPE.md` — locked scope, anti-scope, success criteria, glossary, assumptions, risks.
- `docs/FIXTURES.md` — locked PDF pair, mutation policy, authority declaration, gold-set schema.
- `docs/superpowers/plans/2026-05-19-interlock-mvp.md` — phased TDD execution plan, 11 phases.
- `docs/PRD.md`, `docs/TDD.md`, this file.

## What I reused

External libraries (off-the-shelf, no modification):

- **PyMuPDF (`fitz`)** for PDF span/page extraction and bbox-anchored citation rendering. Chose over `pdfplumber` for speed and tighter Unicode handling.
- **Camelot** with `[base]` extras for table extraction.
- **Pint** for unit normalization, including handling of Greek `μ`, `Ω`, and SI prefixes natively.
- **Voyage AI Python SDK** (`voyageai`, model `voyage-3`) for semantic name embeddings.
- **Anthropic Python SDK** (`anthropic`, model `claude-sonnet-4-5`) for the vision fallback path.
- **Streamlit** for the single-page review UI.
- **uv** for dependency management and reproducible builds.
- **pytest** + **pytest-mock** for tests.
- **ruff** + **mypy** for lint and types (strict mode).

The Eaton sample coordination study (`fixtures/pdfs/doc_a_60pct.pdf`) is a real public document, used as-is. SHA-256 captured in `fixtures/pdfs/HASHES.txt` for provenance.

## What broke (and what I disclosed)

- **Camelot's "tables" on Eaton are chart axes, not parameter tables.** Lattice mode happily returned 50-row × 38-column "tables" representing the log-log coordination-curve grids on pages 4/6/8. The real parameter signal lives in span text. I logged the finding in `docs/BACKLOG.md`, kept the table extractor as a no-cost path for future fixtures with native PDF tables (data sheets, equipment schedules), and shifted parameter extraction to be span-driven.

- **First-cut semantic alignment paired unrelated records across pages.** When the FN-1 mutation removed `LPN-RK-500SP` from Doc B, the leftover A record found the next-most-similar fuse on Doc B page 2 (`KRP-C-1600SP`) via Voyage embedding cosine. Two guards added: (1) `same_page_only=True` default, (2) exclude string-valued records from semantic matching entirely. Eval re-ran cleanly after.

- **`equivalent()` initially returned False for matching fuse part numbers** because Pint couldn't parse them and the except clause returned False. Added a case-insensitive string-equality short-circuit before the Pint path.

- **Pint aliasing for μF and Ω was redundant.** First attempt defined `@alias microfarad = μF` which raised `KeyError: 'microfarad'` because Pint already understands `μF` and `Ω` natively via prefix resolution. Removed the redundant aliases; only `percent = 0.01 = %` is custom.

- **PyMuPDF's `helv` built-in font lacks Greek glyphs.** The symbol-fidelity probe failed initially because `insert_text(fontname="helv", ...)` couldn't render Ω, μ, θ, Δ, cos φ. Switched to embedding macOS's Arial Unicode TTF via `page.insert_font(fontfile=...)`. All 12 required symbols now round-trip.

- **CDN downloads from this network repeatedly failed** (curl exit codes 56, 92 against eaton.com). Handed off to manual download by the user.

- **Anthropic API access cost confusion.** Claude Max subscription does not include API credits. Initially planned to drop Anthropic entirely; user later added a personal API key, so vision fallback path was restored (used only for low-coverage pages, of which Eaton has none).

## How I debugged it

- **TDD as the primary debugging tool.** Every component started with a failing test that named the desired behavior in terms of inputs and outputs. When a real-fixture run surfaced an unexpected flag (e.g., the cross-page fuse mismatch), I traced the offending path, added a unit test that reproduced the misbehavior with stubs, then fixed the implementation and watched the new test go green. Same-page-only and string-record-exclusion guards both landed this way.

- **Print-trace-then-test on the real fixture.** For pattern-extraction work I ran ad-hoc Python on Doc A + Doc B before writing tests, to see which spans the regex set actually catches. Eaton revealed that parameters live in patterns like `1000KVA XFMR`, `5.75%Z, liquid`, and `Fault X1 20,000A RMS Sym` — not in the `Name: value` shape the plan template assumed. Adapted the pattern set.

- **mypy --strict + ruff on every commit.** Caught Pint's `Quantity` typing quirks, missing return annotations, and a few `None`-vs-`Citation` assignment bugs in the UI flow before they hit runtime.

- **Phase tags as rollback points.** Each phase ended at a green tag. When the semantic-alignment guards required code changes, I knew exactly which tag was the last-known-good if anything cascaded.

## Fixture disclosure (mandatory)

**Doc B (`fixtures/pdfs/doc_b_90pct.pdf`) is not an independent document.** It is a deterministic derivation of Doc A (the public Eaton sample coordination study), created by `fixtures/mutations/apply_mutations.py` to inject six labeled engineering-realistic mutations:

- 3 true-positive value mismatches (decimal-shift on transformer impedance, on fault current, on transformer rating)
- 2 false-positive traps (unit-equivalent value rewrite; heading-only rephrase)
- 1 false-negative checklist gap (parameter removal)

This is disclosed in `docs/FIXTURES.md` §2 and §3, in the eval gold set, and is intentional: the brief required two real PDFs ingested, and the fixture pair demonstrates the system's behavior on a controlled, labeled, reproducible test case.

**Doc A of the Option 2 fixture pair (`fixtures/pdfs/spec_xfmr_001.pdf`) is also not a real document.** It is a deterministically generated synthetic transformer Equipment Data Sheet, produced by `fixtures/synthesis/generate_spec.py`, shaped to match an IEEE C57.12.00 / ANSI C57.12.10 nameplate spec. Used to demonstrate cross-document semantic alignment between heterogeneous document types when paired with the Eaton coordination study. Disclosed in `docs/FIXTURES.md` §2B. Real-spec curation (using a public manufacturer data sheet) is Option 4 in `docs/BACKLOG.md`.

## Sprint 1 (v2) — Doc-class classifier + per-class hooks

Shipped via 7 phase tags (`phase-24.1-classifier-schemas` → `phase-24.7-classifier-hooks`) on top of `v2.0-baseline-from-v1.5-mvp-ready`. Exit tag: `v2.0-mvp`.

**Components landed:**
- `src/interlock/llm_pipeline/schemas/doc_class.py` — `DocClass` enum (8 values) + `DocClassification` Pydantic model with confidence-range validation and frozen-model semantics for audit-trail safety
- `src/interlock/llm_pipeline/classify.py` — multi-page VLM classifier (pages 1/2/last @ 300 DPI), `claude-opus-4-7`, Pydantic-validated structured output, diskcached on PDF content hash + model + prompt_version + DPI, confidence < 0.6 → `unknown` fallback, render-failure-safe (returns `unknown(0.0)` instead of raising)
- `src/interlock/llm_pipeline/prompts/classify.md` — classification system prompt with 8 class definitions, confidence calibration ladder, and the **structure-over-authorial-intent** principle (live-API smoke proved v1 prompt was too strict — sample/educational documents that have the structural signals classify as the matching class, not `unknown`). Bumped to `PROMPT_VERSION = "v2"`.
- `src/interlock/llm_pipeline/prompts/extract/<class>.md` × 7 — empty stubs for Sprint 2's extraction prompt registry + README explaining contract
- `src/interlock/detect/tolerances.py` — `DOC_CLASS_TOLERANCE_OVERRIDES` layer with v1-default fallback; concrete entries for `equipment_spec` (tighter impedance + rated_power bands) and `relay_setting_sheet` (tighter fault_current band)
- `src/interlock/detect/authority.py` — `DOC_CLASS_AUTHORITY` map for `transformer_params` + `relay_settings` families with v1-default fallback (`doc_a` authoritative when family or class is missing from the hierarchy, or when either class is `DocClass.unknown`)
- `src/interlock/pipeline.py` — `classify_docs` kwarg (default `False`); `ReviewResult` extended with `doc_class_a` / `doc_class_b: DocClassification | None`; parallel classification via `ThreadPoolExecutor(max_workers=2)` overlapping with `ingest()`; classifier failure collapses to `unknown(0.0)` so pipeline keeps producing flags
- `src/interlock/ui/app.py` — sidebar "Doc-class routing (v2 Sprint 1)" toggle (default ON); two-column doc-class banner above metrics row with confidence-graded styling (`st.success` ≥ 0.85, `st.info` 0.60–0.85, `st.warning` < 0.60); detected-indicators expander
- 5 deterministic synthetic-fixture generators producing PDFs across `hvac_schedule`, `pid`, `bom`, `civil_drawing`, and a 2nd `equipment_spec` variant (motor data sheet)

**Eval shipped:**
- 11-doc partial acceptance corpus (6 existing real + 5 new synthetic) at `fixtures/eval/gold_doc_class.yaml` — full 20-doc target (with 9 more real sourced PDFs) is the immediate follow-up
- Acceptance harness `scripts/run_doc_class_eval.py` (writes per-doc JSON + Markdown report)
- CI gate at `tests/eval/test_doc_class_gate.py` enforcing overall ≥ 85 % / real ≥ 80 % / synthetic = 100 % / unknown precision = 100 % on the partial corpus (restore to 90 / 85 / 100 / 100 when corpus reaches 20)
- Live-API smoke at `tests/real_world/test_doc_class_live.py` against 6 existing fixtures (~$0.40 per cold run)

**Eval result on partial corpus:** **11/11 = 100 %** (5/5 synthetic, 5/5 real (4 fixtures + scanned), 1/1 unknown). All acceptance gates green.

**Test surface delta:** +27 tests (7 schemas, 10 classifier mocked, 4 v2 pipeline + Track 1 snapshot, 5 tolerance per-class, 5 authority per-class, 6 gold YAML well-formed, 4 CI gate). Total v2 test count at `v2.0-mvp`: **292 passing + 8 live-API slow-marked**, deselected by default.

**Cost delta:** Sprint 1 dev iteration spend ~$1.50 (live-API smoke twice + partial-corpus eval once, cached thereafter).

**Honest scope statement.** See `docs/TDD.md` § "Known limits — Sprint 1 doc-class classifier (v2)" for what generalises vs what's overfit, and which 5 of 8 classes still inherit v1 behaviour end-to-end. The 11-doc partial corpus is acknowledged as smaller than the 20-doc spec target — the remaining 9 real PDFs are a sourcing exercise, not a code blocker.

## Sprint 3 (v2) — Adjudicator + Provenance UX

Shipped via 5 phase tags (`phase-26.1-flag-provenance-field` → `phase-26.5-adjudicator-schema`) on top of `v2.1-llm-extraction`. Exit tag: `v2.2-adjudicator`.

**Components landed:**
- `src/interlock/detect/mismatch.py` — `Flag` gains `provenance: Literal["rule_only", "llm_only", "mixed_track", "unknown"] = "unknown"`
- `src/interlock/adjudicator.py` — `adjudicate_flags()` pure post-processing function + `_classify_provenance()` taxonomy logic
- `src/interlock/pipeline.py` — adjudicator wired after `detect_flags()`; runs always (pure annotation, zero cost)
- `src/interlock/ui/app.py` — sidebar track-filter radio (All / Deterministic only / AI-only / Hybrid sources); provenance badge in flag header (silent on `rule_only`, prominent `🧠 AI-only` / `🔀 Hybrid sources` on exceptions); per-flag expanded view shows track detail only on non-default; JSON export gains `provenance` key per accepted flag
- `src/interlock/store/sqlite.py` + `data/interlock.schema.sql` — decision table gains `provenance` column via idempotent Python-side migration (sqlite3 doesn't support `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`; we PRAGMA-check then ALTER as needed). New public `apply_schema(conn)` consolidates schema + migration so tests can target a fresh in-memory DB without going through `_connect()`.

**UX revised twice during brainstorming.** Final design uses the silent-default + prominent-exception pattern (mirrors Phase 19's `⚠️ weak pair` badge). Internal "Track 1 / Track 2" terminology never leaks to reviewer-facing labels.

**Cost delta:** $0 dev spend, $0 per-review delta. Sprint 3 is the cheapest sprint of the v2 plan.

**Test surface delta:** +21 tests (4 Flag field + 10 adjudicator unit + 3 pipeline integration + 4 SQLite schema). Total v2 test count at `v2.2-adjudicator`: **354 passing** + the existing live-API slow-marked suites.

**Honest scope statement.** Sprint 3 ships the labeling. It does NOT detect "both tracks independently agreed on the same fact" — that case requires running alignment twice or detecting duplicate records, both deferred to Sprint 4+. The 3-state taxonomy (`rule_only` / `llm_only` / `mixed_track`) reflects what the pipeline's union-merge architecture actually produces.

## Phase 23 — Fork to interlock-ai-v2 + hybrid-pivot positioning (this repo's baseline)

After v1's submission delivery (Phase 22), the v1 repo `funcpointer/interlock-ai` was frozen at `v1.5-mvp-ready`. This repo (`funcpointer/interlock-ai-v2`) carries forward the full v1 git history (every phase tag, every v1.x tag) and adds a `v2.0-baseline-from-v1.5-mvp-ready` tag at HEAD.

The pivot rationale, two-track architecture (deterministic floor + foundation-model ceiling), sprint roadmap, cost/latency envelope, and risk register are documented in [`docs/PIVOT_PLAN.md`](PIVOT_PLAN.md). This authorship section is the chronological log; the architectural framing lives in PIVOT_PLAN.

**What was carried over verbatim from v1:**
- `src/interlock/` — all modules (align, extract, detect, ingest, citation, llm, store, pipeline, ui)
- `tests/` — 261-test deterministic invariant suite
- `fixtures/` — three locked demo fixture scenarios (revision diff + cross-doc + scanned OCR)
- `docs/` — PRD, TDD, ARCHITECTURE, FIXTURES, SCOPE, RISK_REGISTER, DEMO_SCRIPT, BACKLOG, plus this AUTHORSHIP
- All 23 git tags (`phase-0-scaffold` → `phase-20-ocr-quality`, `v1.0-mvp` → `v1.5-mvp-ready`)

**What was added at fork-time (this commit set):**
- `docs/PIVOT_PLAN.md` — pivot rationale + sprint roadmap + cost/latency envelope + v2-specific risks
- README banner repositioning v2 as the hybrid pivot; deterministic-only v1 stays live as a frozen reference
- v2-specific CLAUDE.md (gitignored) with project rules: Track 1 frozen, all feature work in Track 2 / adjudicator
- This AUTHORSHIP section

**What stays frozen forever in v2:** Track 1 (`src/interlock/align/`, `src/interlock/extract/`, `src/interlock/detect/`). The 261 deterministic tests gate every v2 commit. Bug-fix-only commits permitted under CI gating; no feature work.

**v2 sprint cadence** (full schedule in `docs/PIVOT_PLAN.md`):

| Sprint | Adds |
|---|---|
| 1 | Doc-class classifier (VLM); per-class extraction/tolerance/authority routing |
| 2 | LLM extraction module (Pydantic ontology); solves prose-paper zero-yield case |
| 3 | Adjudicator + per-flag provenance UX (`✓ both`, `⚙ rule-based`, `🧠 AI-detected`) |
| 4 | LLM pairing reranker for ambiguous multi-instance buckets (replaces Phase 19 heuristic overfit) |
| 5 | Standards-as-RAG (per-flag clause + edition retrieval) + coupled-effect graph traversal |
| 6 | Per-class eval + confidence calibration in CI |

Total: ~15 weeks from v2.0-baseline-from-v1.5-mvp-ready to feature-complete hybrid. v1 demo URL stays live throughout; v2 demo URL lands at Sprint 1 close.

## Phase 19 — Identity-first alignment + honest gap surface (after v1.5-mvp-ready)

Four-commit refactor responding to user-reported false flags on the OCR-vs-native fuse-table case. Cross-family fuse pairs (KRP-C-1600SP vs LPS-RK-100SP) and cross-position transformer pairs (150 kVA vs 100 kVA on multi-instance pages) were surfacing because alignment had no notion of *which* fuse / *which* transformer a record described — it pairred by parameter name + page + y-proximity, and y-proximity collapsed under OCR (every vision-derived span shares the whole-page bbox).

Each commit individually tested + tagged on `v1.5-mvp-ready`:

- **Commit 1 — entity-tag capture.** `ParameterRecord.entity_tag` field; extractor reads leading row markers from each span (circled digits ①-㉟, "21", "21.", "A1", "T-200") and normalises to ASCII. `align_exact` filters candidates by entity-tag agreement before any positional rule. Records without a tag never cross-pair with tagged records. 11 new tests.
- **Commit 2 — unpaired surface.** `ReviewResult` dataclass + `review_two_documents_full()`; UI "📋 Unpaired records" expander shows records the aligner declined to pair. Converts silent gaps into reviewer-visible tasks. Legacy `review_two_documents()` preserved as a thin shim (20+ call sites untouched). 2 new tests.
- **Commit 3 — pairing confidence.** `pairing_confidence` per pairing rule (1.0 tag-match / 0.9 single-instance / 0.75 multi-instance-distinct-y / 0.5 value-equality-fallback). Surfaced on every `Flag`; folded into overall confidence; weak pairs (<0.75) get a `⚠️ weak pair` badge and are collapsed by default. Also refactored y-degeneracy detection to use the unconsumed candidate pool so the gate stays consistent across iterations within one bucket. 1 new test + 16 existing align tests pass.
- **Commit 4 — OCR prompt v3.** Explicit "preserve Device IDs as the FIRST token of each row; do NOT guess one" directive. `PROMPT_VERSION` bumped v2 → v3 for cache invalidation. Regression test asserts the prompt mentions Device IDs and the ① glyph.

**Honest scope statement.** The architecture pieces (entity_tag field, ambiguity gates, pairing_confidence, unpaired surface) generalise across document classes. Several specific heuristics — `_LEADING_DEVICE_ID` regex, `_string_family` regex, the OCR prompt's Device-ID examples — are shaped to fuse-coordination tables and will need broadening for HVAC schedules / process P&IDs / spec sheets with right-aligned ID columns. Full table of "what generalises vs what's overfit", untested document classes, and the ranked generalisation plan are in `docs/TDD.md` § "Known limits (Phase 19 honesty disclosure)".

## Phase 20 — OCR quality: DPI bump + plausibility re-OCR (after Phase 19)

Two-commit OCR-quality refresh in response to the question "are we super sure Claude vision is the best we can do here?". Reviewed OSS alternatives (Tesseract, PaddleOCR, Surya, docTR) and multi-pass algorithms (layout pre-pass, two-engine consensus, targeted re-OCR). Picked the two cheapest high-leverage changes for the deadline; rest in TDD generalisation plan.

- **Commit 1 — DPI bump 200 → 300.** Vision rasterised at 200 DPI sat near the model's resolution floor for tight numeric strings; the user-reported `5.75%Z → 0.575%Z` hallucination is the signature failure mode. Bump roughly doubles input tokens per OCR'd page (~$0.10) but materially improves character recognition. Cache key includes `_DPI` so old cached entries recompute automatically.
- **Commit 2 — Two-pass plausibility re-OCR.** After the first OCR call, scan the returned text for engineering tokens (impedance, rated power, voltage, fault current, IFLA) and validate each against a wide per-family plausibility range (sanity bands, not tolerance — purpose is to catch decimal slips, not flag unusual-but-real values). When any token is implausible, issue a second call at 400 DPI with a verification-focused prompt explicitly warning the model about decimal-place misreads. Pass with fewer implausible tokens wins; tie keeps pass 1 (no flapping). `PROMPT_VERSION` bumped v3 → v4. `VisionResult.reocr_triggered` field exposes telemetry. 8 new tests (validator + re-OCR flow).

Live verification: 261 tests pass; OCR yield on `doc_a_scanned.pdf` recovers 54 params vs 52 native (104 % recovery); re-OCR did not fire on any of 9 pages in the locked scanned fixture (DPI bump alone resolved the previously-hallucinating `5.75%Z` case); impedance set matches native almost exactly. Cost stayed at ~$0.05 per OCR'd page on this fixture; expect ~$0.10 per page on docs with truly bad scans where re-OCR triggers.

**Honest scope statement.** Both passes use the same model — multi-model consensus would catch model-specific failure modes but expands scope mid-submission. We have no ground-truth OCR accuracy metric beyond parameter-recovery yield, so claims about "Claude vs Tesseract vs Surya" are vibes-based for now. Building a labelled OCR test corpus is in the post-MVP generalisation plan.

## Phase 19 — Identity-first alignment + honest gap surface (after v1.5-mvp-ready)

Four-commit refactor responding to user-reported false flags on the OCR-vs-native fuse-table case. Cross-family fuse pairs (KRP-C-1600SP vs LPS-RK-100SP) and cross-position transformer pairs (150 kVA vs 100 kVA on multi-instance pages) were surfacing because alignment had no notion of *which* fuse / *which* transformer a record described — it pairred by parameter name + page + y-proximity, and y-proximity collapsed under OCR (every vision-derived span shares the whole-page bbox).

Each commit individually tested + tagged on `v1.5-mvp-ready`:

- **Commit 1 — entity-tag capture.** `ParameterRecord.entity_tag` field; extractor reads leading row markers from each span (circled digits ①-㉟, "21", "21.", "A1", "T-200") and normalises to ASCII. `align_exact` filters candidates by entity-tag agreement before any positional rule. Records without a tag never cross-pair with tagged records. 11 new tests.
- **Commit 2 — unpaired surface.** `ReviewResult` dataclass + `review_two_documents_full()`; UI "📋 Unpaired records" expander shows records the aligner declined to pair. Converts silent gaps into reviewer-visible tasks. Legacy `review_two_documents()` preserved as a thin shim (20+ call sites untouched). 2 new tests.
- **Commit 3 — pairing confidence.** `pairing_confidence` per pairing rule (1.0 tag-match / 0.9 single-instance / 0.75 multi-instance-distinct-y / 0.5 value-equality-fallback). Surfaced on every `Flag`; folded into overall confidence; weak pairs (<0.75) get a `⚠️ weak pair` badge and are collapsed by default. Also refactored y-degeneracy detection to use the unconsumed candidate pool so the gate stays consistent across iterations within one bucket. 1 new test + 16 existing align tests pass.
- **Commit 4 — OCR prompt v3.** Explicit "preserve Device IDs as the FIRST token of each row; do NOT guess one" directive. `PROMPT_VERSION` bumped v2 → v3 for cache invalidation. Regression test asserts the prompt mentions Device IDs and the ① glyph.

## Phase 14 — Entity + Claim layer (after v1.3-tolerance)

Additive layer above `ParameterRecord` so the pipeline can distinguish equipment within a single document. Phase 14 ships the infrastructure; multi-equipment demo activation is deferred to platform path (entity fingerprinting against implicit-side docs is required for cross-doc multi-equipment scenes — `docs/BACKLOG.md` R-F).

- `src/interlock/extract/entities.py` — `Entity` + `Claim` dataclasses with tag-pattern inference for XFMR / T / P / M / CB / Bus / Line / MOV / V / R prefixes. Implicit-entity fallback per doc. Pure `claims_from_records` (cache-safe).
- `src/interlock/align/claims.py` — claim-aware exact aligner with `same_entity_only` filter. Implicit entities treated as wildcards so Option 1 stays working untouched.
- `src/interlock/store/sqlite.py` — raw-SQL CRUD over the entity / claim / decision schema. Idempotent upserts via deterministic claim IDs (sha256 of canonical key tuple). Auto-applies schema from `data/interlock.schema.sql`.
- `data/interlock.schema.sql` — schema extended with entity / claim / decision tables (cost_event already shipped in Phase 13).
- `src/interlock/pipeline.py` — three new opt-in flags (`use_claim_layer`, `same_entity_only`, `persist_claims`). When all default, v1.3 behavior is preserved bit-for-bit.
- 43 new tests across `tests/extract/test_entities.py`, `tests/store/test_sqlite.py`, `tests/align/test_claim_alignment.py`. (At Phase 14 close: 294 passing, 7 deselected. Current `v1.5-mvp-ready`: 261 passing, 83 deselected after the Phase 19/20 work consolidated some redundant tests and added live-API real-world suites.)

## Phase 13 — Tolerance bands + severity tiers + LLM significance (after v1.2-real-world)

Replaces "every mismatch surfaces at confidence 1.0" overflagging with engineering-tolerance-aware severity classification, plus an opt-in LLM second-opinion judge.

- `src/interlock/cache/disk.py` — diskcache wrapper with content-hash keys + namespace isolation. 7 tests.
- `src/interlock/cache/cost_ledger.py` — SQLite-backed per-call cost ledger. Pricing constants inline with citations (Anthropic platform pricing, Voyage docs). 10 tests.
- `src/interlock/detect/tolerances.py` — per-attribute-family tolerance bands sourced from IEEE C57.12.00, IEC 60076-1, IEEE Std 242, NEMA TR 1. Includes runtime override hook (`set_tolerance_overrides`) and explicit honest framing of these as starting defaults, not absolute truth. 34 tests.
- `src/interlock/detect/family.py` — canonical-phrase → tolerance-family resolver. 18 tests.
- `src/interlock/detect/significance.py` — LLM significance judge via Pydantic-validated `messages.parse` on Claude Opus 4.7 with two-tier prompt caching (1h ontology, 5m fixture text). Disk-cached results so repeat runs cost ≈ $0. 12 tests including 1 live-API.
- `src/interlock/llm/client.py` — cached Anthropic client wrapper with locked defaults. 5 tests including 2 live-API cache invariants.
- `src/interlock/detect/mismatch.py` — `Flag` extended with `severity`, `deviation_pct`, `attribute_family` fields. `suppress_info` parameter (default True) drops within-tolerance changes from the primary review list.
- `src/interlock/pipeline.py` — `use_llm_judge` + `suppress_info` opt-in flags.
- `src/interlock/ui/app.py` — severity grouping (critical/major/minor/info), color coding, LLM toggle.

Tolerance framing (per request): the shipped bands are documented as starting defaults driven by 5 real-world variance factors (standard edition, owner internal standards, equipment class, review phase, risk posture). Runtime override hook lets a reviewer team load AES-STD-XXX values without forking code.

## Phase 12 — real-world test expansion (after v1.1-cross-doc)

Added 7 test files under `tests/real_world/` and `tests/align/test_canonical.py`. ~50 new test cases across:
- real-PDF extraction smoke (Eaton/spec/SEL/IEEE)
- pipeline behaviors (self-compare, unrelated docs, determinism, cross-doc-mode safety)
- edge cases (empty PDF, single-page, prose-only, part-numbers-only, disjoint-doc, lying-embedder dim-filter)
- canonical glossary (synonym collapse, family separation, BIL/voltage distinction, no case-fold dupes)
- citation e2e (PNG signature, audit-tuple completeness, doc_id integrity, authority direction)
- perf budgets (ingest, extract, Option 1, Option 2 — slow-marked)
- properties (Pint equivalence/non-equivalence matrix, same_dimension matrix, confidence formula multiplication/clamping/monotonicity, alignment symmetry)

Added two real public PDFs as tracked fixtures:
- `fixtures/pdfs/real_sel_xfmr_protection.pdf` — SEL 6079 transformer protection
- `fixtures/pdfs/real_ieee_xfmr_spec_guide.pdf` — IEEE Guide for Preparation of Transformer Specifications

Bug surfaced and fixed in this phase: `render_citation` opened `record.doc_id` as a file path, but pipeline assigned `doc_id` as a logical label. Deployed Streamlit app silently failed citation snippets. Fix: added `source_path` field to `Span` and `ParameterRecord` (populated by `extract_spans` from the actual file path); renderer prefers `source_path` with `doc_id` fallback for back-compat.

Real-world finding: SEL transformer-protection paper is prose-heavy ("the percentage 2 harmonic setting PCT2..."), and current regex extractors miss it. Documented as system limitation; NLP-based extraction lives in `docs/BACKLOG.md`.

## Phase 11 — cross-doc additions (after v1.0-mvp)

Built after the initial MVP shipped to demonstrate the cross-document wedge that the revision-diff fixture leaves dormant:

- `fixtures/synthesis/generate_spec.py` — synthetic transformer spec generator.
- `fixtures/eval/gold_cross_doc.yaml` — Option 2 gold set.
- `scripts/run_ab.py` — A/B comparison harness producing `eval/results/ab_comparison.json`.
- `src/interlock/align/semantic.py` — `_CANONICAL` engineering-shorthand glossary (`%Z` → impedance, `Rated Power` → transformer rated apparent power, `BIL` → basic insulation level, etc.); `same_dimension` filter rejecting voltage↔current false pairs.
- `src/interlock/extract/parameters.py` — generic `Label: number unit` pattern for data-sheet layouts; `System Voltage` standalone pattern anchored to span start.
- `src/interlock/extract/units.py` — `same_dimension(a, b)` helper.
- `src/interlock/pipeline.py` — `same_page_only` parameter plumbed through.
- `src/interlock/ui/app.py` — "Cross-document mode" checkbox.
- `tests/eval/test_harness_cross_doc.py` — Option 2 gold-set acceptance test.
- `docs/superpowers/plans/2026-05-20-cross-doc-option2.md` — phase-11 plan.
