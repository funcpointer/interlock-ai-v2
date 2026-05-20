# InterLock AI — Backlog

Anything that surfaces during MVP execution and would expand scope goes here. The plan in `docs/superpowers/plans/2026-05-19-interlock-mvp.md` forbids in-phase work on these.

## Platform-path items (seed)

- Phase-to-phase comparison across 30/60/90 (multi-document session).
- Configurable authority UI (reviewer declares per-pair authority before run).
- DMS integration (SharePoint, Bentley ProjectWise, Autodesk Docs).
- Persistent review sessions and audit log.
- CAD / geometry comparison (bananaz.ai-style).
- Bidirectional annotation round-trip back to source PDF.
- Standards-as-authority pass (IEEE, IEC, NERC).

## Discovered during execution

- 2026-05-20 (P2): Camelot detects chart axes (50-row × 38-col grids) on Eaton coordination-curve pages, not the device-ID tables. The device-ID "tables" are visually-laid-out paragraphs, not bordered tables. For this fixture, parameter extraction is span-driven; the table-cell extractor in the plan (Tasks 3.3b/3.3c) was skipped. Platform-path: real engineering specs with native PDF tables (transformer data sheets, equipment schedules) will exercise this.

- 2026-05-20 (P11): Voyage `voyage-3` embeddings alone do not match engineering shorthand reliably ("%Z" ↔ "Impedance" cosine ≈ 0.44; "Rated Power" ↔ "Transformer Rating" ≈ 0.66, both below the 0.85 alignment threshold). A small canonical glossary in `align/semantic.py` (`_CANONICAL`) maps shorthand to canonical phrases before embedding; cosine on canonical forms is then ≈ 1.0. This is explicit engineering knowledge baked into the system. Extend per fixture family. Voyage rerank-2 considered as an alternative but glossary is more interpretable and faster.

## Closed (done in this build)

- ~~Cross-document semantic alignment fixture (Option 2)~~ — done 2026-05-20. See `docs/superpowers/plans/2026-05-20-cross-doc-option2.md`. Verified strictly stronger than Option 1 by `scripts/run_ab.py` / `eval/results/ab_comparison.json`.

## Strategic direction (five-layer consistency engine — see `docs/PRD.md` §4)

MVP lives in layers 1, 2, and partial 4 + basic 5. The following items expand each layer toward the "engineering consistency operating system" framing.

### Phase 13 — Entity + Claim graph (L2/L3 foundation, highest leverage)

- Refactor `ParameterRecord` into `Entity` + `Claim(entity, attribute, value, source)`.
- Entity types: pump, transformer, line, circuit, breaker, fuse, requirement, assumption.
- Pair on `(entity, attribute)` instead of parameter name.
- Trigger: Option 4 fixture (real multi-equipment spec ↔ study).
- Estimated effort: 1–2 days.
- Unlocks Phases 14–20.

### Phase 14 — Material significance + tolerance bands (L4)

- Per-attribute engineering tolerances (transformer impedance ±5% is normal; 10% requires explanation).
- Severity tiers per flag: critical / major / minor / informational.
- Drops noise rate further; reviewers see *what matters*, not *what differs*.

### Phase 15 — Revision lineage (L2/L3)

- Per-document revision metadata (Rev A / B / C, dates, supersession chain).
- Supersession-aware authority: "Rev C supersedes Rev B" overrides hardcoded rules.
- Parameter-evolution timeline per claim.

### Phase 16 — Coupled-effect propagation (L4)

- Graph traversal: claim X changes → identify derived claims that become suspect.
- "Transformer impedance changed → recheck coordination study and relay settings" without re-reading both documents.

### Phase 17 — Standards-as-authority (L4)

- IEEE / IEC / NERC code-edition tracking.
- Project-vs-code compliance pass.
- Eliminates the slowest senior-reviewer task: standards cross-reference.

### Phase 18 — Multi-doc review sessions + DMS integration (L1/L5)

- Whole-project corpora.
- SharePoint / Bentley ProjectWise / Autodesk Docs ingest.
- Triage queue with ownership, comment threads, status lifecycle.

### Phase 19 — CAD geometry comparison (L1/L4)

- 2D/3D drawing comparison (bananaz.ai-class) integrated with the same claim graph.
- One consistency engine across drawings + specs, not two siloed tools.

### Phase 20 — Continuous engineering assurance (L1–L5 evolution)

- Always-on monitor across project lifecycle (design → procurement → construction → as-built).
- Asset operators pay for traceable assurance across years of project deliverables.

## Still open

- **Option 4** — real (non-synthetic) spec ↔ study pair. The Option 2 synthetic spec proves the pipeline; Option 4 proves it on uncurated reality. Candidate: SEL 6079 transformer protection paper paired with a public manufacturer data sheet.
- Standards-as-authority pass (IEEE / IEC / NERC compliance check against project documents).
- Vision-fallback exercise on a scanned-PDF spec (current fixtures all native-text).
- **Prose-embedded parameter extraction.** Phase 12 confirmed SEL transformer-protection paper is prose-heavy ("the percentage 2 harmonic setting PCT2 is also calculated..."); current regex extractors yield zero parameters. NLP / LLM-based extraction needed for technical papers. Pinned at zero by `tests/real_world/test_real_pdf_extraction.py::test_sel_paper_known_prose_extraction_limit`.
- **Camelot on long PDFs is slow.** Phase 12 noted IEEE 56-page extraction takes ~110 s due to per-page Camelot scans. Either skip Camelot above N pages, run lattice/stream in parallel, or cap pages.

## Discovered in Phase 12

- 2026-05-20 (P12): `render_citation` bug — `fitz.open(record.doc_id)` requires `doc_id` to be a real file path, but the pipeline default sets `doc_id="doc_a"` (a label). In the deployed Streamlit app this caused silent citation-snippet failures (the warning was caught). **Fixed** by adding `source_path` to `Span` and `ParameterRecord`. Renderer prefers `source_path` with `doc_id` fallback.
- 2026-05-20 (P12): Voyage embedding API has minor non-determinism across calls (cosine drift ~1e-3). Idempotency tests must check flag-parameter *sets*, not exact confidence values.
