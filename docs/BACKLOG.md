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
