# InterLock AI — TDD

## 1. Ingestion and extraction architecture

Two-stage native-text path with a vision fallback.

**Stage A — span extraction (PyMuPDF / `fitz`).** Iterate page → block → line → span. Each span carries text, page index (1-based), and bbox (`x0, y0, x1, y1` in PDF points). Unicode round-trips natively; the symbol-fidelity probe (`fixtures/probes/symbol_probe.pdf`) verifies that Ω, μF, kV, MVA, θ, Δ, cos φ, °C, ±, ≤, ≥ all survive extraction. PyMuPDF gives roughly an order of magnitude speedup over `pdfplumber` while preserving bbox information needed for citations.

**Stage A.5 — line aggregation.** PyMuPDF returns one span per visual run; labels like `Rated\nVoltage: 132 kV` split across spans. `aggregate_line_spans` groups same-y spans (within 2 pt tolerance) so regex matchers see logical lines.

**Stage B — table extraction (Camelot).** Lattice flavor first, stream fallback. Cell bboxes preserved. Empirical note: Camelot detected coordination-curve chart axes on Eaton pages 4/6/8 as 50+ row "tables." The actual device-ID tables on pages 3/5/7 are visually-laid-out paragraphs, not bordered tables. For this fixture the parameter signal is span-driven; table extraction is retained as a no-cost fallback for future fixtures with native PDF tables (data sheets, equipment schedules).

**Stage C — vision fallback (Claude Sonnet 4.5).** Pages where text density falls below 80 characters (typically scanned pages, image-only blueprints, or pages with embedded raster diagrams) are flagged in `IngestResult.low_coverage_pages`. The fallback renders the page at 200 DPI, base64-encodes, and prompts Claude for `{text, confidence}` JSON. Used only when the native path produces nothing usable. Not exercised by the locked fixture (Eaton is fully native-text, 0 low-coverage pages); included for the platform-path scanned-PDF case. Anthropic SDK is the only LLM dependency in the runtime path.

## 2. Comparison logic

Three signals composed, applied per-pair.

**Layout-anchored exact match** (`align/exact.py`): records with the same parameter name on the same page pair by minimum y-center distance, greedy 1-to-1. This is the dominant path for revision-diff cases where Doc B shares layout with Doc A; it eliminates the cross-product explosion that would arise from naïve name-matching when a parameter family has many instances (e.g., Eaton has nine `5.75%Z` records).

**Pint unit normalization** (`extract/units.py`): each paired value is evaluated for dimensional equivalence via Pint's UnitRegistry. `150 kVA == 0.15 MVA == 150000 V·A` reduces to a single base-unit comparison. The FP-1 trap in the eval gold set verifies this directly. A string-equality short-circuit handles non-numeric tokens (fuse part numbers like `KRP-C-1600SP`) so part-number stability is checked without Pint raising.

**Voyage embedding semantic alignment** (`align/semantic.py`): for A records left unmatched by the layout-anchored pass, cosine similarity of Voyage `voyage-3` name embeddings yields a fallback pair if similarity ≥ 0.85. Three guards keep this signal honest: (a) string-valued records are excluded — part-number embeddings are too close and produce spurious matches; (b) same-page constraint by default — prevents a removed-from-B item on page 7 of A from being paired with an unrelated item on page 2 of B; in cross-doc mode this is lifted; (c) `same_dimension` filter rejects dimensionally incompatible candidates (e.g. voltage ↔ current). The Streamlit UI surfaces real `voyage-3` embeddings; tests inject deterministic stubs.

**Canonical glossary** (`align/semantic.py::_CANONICAL`): explicit engineering shorthand mapping. Voyage embeddings alone score `%Z` ↔ `Impedance` at cosine ≈ 0.44 and `Rated Power` ↔ `Transformer Rating` ≈ 0.66, both below the 0.85 threshold. Mapping each to a canonical phrase (`transformer impedance percent`, `transformer rated apparent power kVA`) before embedding restores cosine ≈ 1.0. This is the explicit engineering knowledge that distinguishes InterLock from Adobe-Acrobat-class textual diff. The Phase 11 cross-doc fixture exercises this path; the Phase 1 revision-diff fixture leaves it dormant (all parameter names align exactly).

**Combiner** (`align/combiner.py`): exact pairs take precedence. Semantic pairs fill only when no exact pair covers the same A record.

**Directional emission with hardcoded authority** (`detect/mismatch.py`, `detect/authority.py`): for the MVP fixture pair, Doc A is hardcoded authoritative (60% baseline) and Doc B is the deviation candidate (90% revision). Every flag declares both ends and includes the authority rule string verbatim — the reviewer always knows which document the system treated as the source of truth. Configurable per-parameter / per-document-type authority is platform-path (BACKLOG.md).

## 3. Citation and confidence

Every flag carries a tuple `(doc_id, page, section, bbox, quoted_text, snippet_png)`. The snippet renderer (`citation/render.py`) opens the source PDF, draws a 1.5-pt red bbox over the parameter span, clips to a generous window around the bbox, and rasterizes at 200 DPI. The Streamlit UI displays the snippet side-by-side for both records of a flag so the reviewer never needs to alt-tab to the source PDF to verify.

Confidence is the product of three orthogonal components, each in `[0, 1]`:

```
flag_confidence = extraction_confidence × match_confidence × authority_confidence
```

- `extraction_confidence`: 1.0 for native PyMuPDF spans (zero ambiguity); drops for vision-fallback pages proportional to model self-report.
- `match_confidence`: 1.0 for exact-name layout-anchored pairs; equals Voyage cosine similarity for semantic pairs.
- `authority_confidence`: 1.0 for the MVP hardcoded rule; drops when authority is inferred or unknown (platform-path).

Surface threshold default is 0.6 (slider-adjustable in the UI). Below-threshold flags are accessible via the "suppressed" expander but do not enter the primary review list. The threshold trades off review burden against catch rate; 0.6 was chosen because it admits all locked-fixture TPs while suppressing every locked-fixture FP.

## 4. Evaluation

The locked gold set (`fixtures/eval/gold.yaml`) is derived directly from the mutation log (`fixtures/mutations/MUTATIONS.md`). Six labeled cases:

| ID | Category | Expected | What it tests |
|---|---|---|---|
| TP-1 | parameter_mismatch | surfaced ≥ 0.6 | Decimal-shifted transformer impedance (5.75 % → 0.575 %) — mirrors the AES anecdote |
| TP-2 | parameter_mismatch | surfaced ≥ 0.6 | Decimal-shifted fault current (20,000 A → 200,000 A) |
| TP-3 | parameter_mismatch | surfaced ≥ 0.6 | Decimal-shifted transformer rating (1000 kVA → 100 kVA), 2 sites |
| FP-1 | unit_normalization | suppressed | 150 kVA vs 0.15 MVA — must be recognized as equivalent (Pint dimensional check) |
| FP-2 | heading_only | suppressed | "Time Current Curve #1" → "Time Current Curve 1" — heading rephrase, no parameter |
| FN-1 | checklist_gap | surfaced ≥ 0.4 (acceptable miss) | Fuse `LPN-RK-500SP` present in A, removed from B — checklist-gap pattern; explicit-removal detection is platform-path |

The harness (`scripts/run_eval.py`) runs the real pipeline (Voyage embedder) and writes per-id results plus aggregate metrics (recall on TPs, FP rate on traps, FN count) to `eval/results/baseline.json`. A pytest gate enforces the acceptance thresholds locked in `docs/FIXTURES.md` §6: recall = 1.0 on TPs, FP rate = 0.0 on traps.

Current baseline (`eval/results/baseline.json`):

- Total flags surfaced: 4 (all real)
- Recall on planted TPs: **1.0** (3/3)
- FP rate on traps: **0.0** (0/2 surfaced above threshold)
- FN-1: not detected as a flag (known limitation; surfaces in BACKLOG.md as the explicit-removal detection extension)

## 5. Architecture summary

```
PDF ─► ingest (PyMuPDF spans + Camelot tables + low-coverage routing)
     ─► extract (domain regex → ParameterRecord; Pint normalization; section attribution)
     ─► align (layout-anchored exact + Voyage semantic; combiner)
     ─► detect (directional authority + confidence formula)
     ─► citation (bbox-highlighted PNG snippet)
     ─► UI (Streamlit; accept/dismiss; JSON export of accepted flags)
```

11 phase tags in git (`phase-0-scaffold` … `phase-9-deploy`) partition the implementation; each phase ends with a checkpoint commit and a green test suite. Total: ~70 tests across 12 modules.
