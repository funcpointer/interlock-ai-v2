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

## Phase 19 — Identity-first alignment + honest gap surface (after v1.5-mvp-ready)

Four-commit refactor responding to user-reported false flags on the OCR-vs-native fuse-table case. Cross-family fuse pairs (KRP-C-1600SP vs LPS-RK-100SP) and cross-position transformer pairs (150 kVA vs 100 kVA on multi-instance pages) were surfacing because alignment had no notion of *which* fuse / *which* transformer a record described — it pairred by parameter name + page + y-proximity, and y-proximity collapsed under OCR (every vision-derived span shares the whole-page bbox).

Each commit individually tested + tagged on `v1.5-mvp-ready`:

- **Commit 1 — entity-tag capture.** `ParameterRecord.entity_tag` field; extractor reads leading row markers from each span (circled digits ①-㉟, "21", "21.", "A1", "T-200") and normalises to ASCII. `align_exact` filters candidates by entity-tag agreement before any positional rule. Records without a tag never cross-pair with tagged records. 11 new tests.
- **Commit 2 — unpaired surface.** `ReviewResult` dataclass + `review_two_documents_full()`; UI "📋 Unpaired records" expander shows records the aligner declined to pair. Converts silent gaps into reviewer-visible tasks. Legacy `review_two_documents()` preserved as a thin shim (20+ call sites untouched). 2 new tests.
- **Commit 3 — pairing confidence.** `pairing_confidence` per pairing rule (1.0 tag-match / 0.9 single-instance / 0.75 multi-instance-distinct-y / 0.5 value-equality-fallback). Surfaced on every `Flag`; folded into overall confidence; weak pairs (<0.75) get a `⚠️ weak pair` badge and are collapsed by default. Also refactored y-degeneracy detection to use the unconsumed candidate pool so the gate stays consistent across iterations within one bucket. 1 new test + 16 existing align tests pass.
- **Commit 4 — OCR prompt v3.** Explicit "preserve Device IDs as the FIRST token of each row; do NOT guess one" directive. `PROMPT_VERSION` bumped v2 → v3 for cache invalidation. Regression test asserts the prompt mentions Device IDs and the ① glyph.

253 tests pass (deselected: live-API).

**Honest scope statement.** The architecture pieces (entity_tag field, ambiguity gates, pairing_confidence, unpaired surface) generalise across document classes. Several specific heuristics — `_LEADING_DEVICE_ID` regex, `_string_family` regex, the OCR prompt's Device-ID examples — are shaped to fuse-coordination tables and will need broadening for HVAC schedules / process P&IDs / spec sheets with right-aligned ID columns. Full table of "what generalises vs what's overfit", untested document classes, and the ranked generalisation plan are in `docs/TDD.md` § "Known limits (Phase 19 honesty disclosure)".

## Phase 14 — Entity + Claim layer (after v1.3-tolerance)

Additive layer above `ParameterRecord` so the pipeline can distinguish equipment within a single document. Phase 14 ships the infrastructure; multi-equipment demo activation is deferred to platform path (entity fingerprinting against implicit-side docs is required for cross-doc multi-equipment scenes — Phase 14b in BACKLOG).

- `src/interlock/extract/entities.py` — `Entity` + `Claim` dataclasses with tag-pattern inference for XFMR / T / P / M / CB / Bus / Line / MOV / V / R prefixes. Implicit-entity fallback per doc. Pure `claims_from_records` (cache-safe).
- `src/interlock/align/claims.py` — claim-aware exact aligner with `same_entity_only` filter. Implicit entities treated as wildcards so Option 1 stays working untouched.
- `src/interlock/store/sqlite.py` — raw-SQL CRUD over the entity / claim / decision schema. Idempotent upserts via deterministic claim IDs (sha256 of canonical key tuple). Auto-applies schema from `data/interlock.schema.sql`.
- `data/interlock.schema.sql` — schema extended with entity / claim / decision tables (cost_event already shipped in Phase 13).
- `src/interlock/pipeline.py` — three new opt-in flags (`use_claim_layer`, `same_entity_only`, `persist_claims`). When all default, v1.3 behavior is preserved bit-for-bit.
- 43 new tests across `tests/extract/test_entities.py`, `tests/store/test_sqlite.py`, `tests/align/test_claim_alignment.py`. Total: 294 passing, 7 deselected (slow).

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
