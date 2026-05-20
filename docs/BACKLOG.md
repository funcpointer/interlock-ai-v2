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

## Still open

- **Option 4** — real (non-synthetic) spec ↔ study pair. The Option 2 synthetic spec proves the pipeline; Option 4 proves it on uncurated reality. Candidate: SEL 6079 transformer protection paper paired with a public manufacturer data sheet.
- Standards-as-authority pass (IEEE / IEC / NERC compliance check against project documents).
- Vision-fallback exercise on a scanned-PDF spec (current fixtures all native-text).
