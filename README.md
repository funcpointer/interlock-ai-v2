# InterLock AI v2 — Hybrid Pipeline (Deterministic Floor + Foundation-Model Ceiling)

> **v2 status.** Pivoted from [`funcpointer/interlock-ai`](https://github.com/funcpointer/interlock-ai) at tag `v1.5-mvp-ready`. The v1 repo stays frozen as the deterministic-only edition; this repo is where the hybrid pipeline lands. See [`docs/PIVOT_PLAN.md`](docs/PIVOT_PLAN.md) for pivot rationale + sprint roadmap.

Cross-document discrepancy detection for engineering PDFs. Reviewer uploads two PDFs from the same project; the system surfaces directional, cited, **severity-tiered** parameter mismatches with **identity-aware pairing**, **pairing-confidence scoring**, an **honest unpaired-records surface**, and optional LLM significance judgment.

**v2 adds** (planned, per sprint plan in `docs/PIVOT_PLAN.md`):

| Layer | What it adds | Sprint |
|---|---|---|
| Document classifier (VLM) | Auto-detects doc class (coordination study / spec / HVAC / P&ID / BOM) → routes to per-class extraction + per-class tolerance bands + per-class authority hierarchy | 1 |
| LLM extraction (structured) | Captures prose-embedded params + non-tabular layouts; solves the SEL-paper zero-yield case | 2 |
| Adjudicator + provenance UX | Track 1 (deterministic) and Track 2 (LLM) results merged with per-flag provenance (`✓ both`, `⚙ rule-based`, `🧠 AI-detected`) | 3 |
| LLM pairing reranker | Replaces Phase 19 heuristic overfit with reasoned pairing for ambiguous multi-instance buckets | 4 |
| Standards-as-RAG + coupled-effect graph | Per-flag retrieval of applicable standard edition + project override; impedance change traverses claim graph to flag dependent claims | 5 |
| Per-class eval + calibration | Per-doc-class gold sets; confidence calibration against reviewer accept-rate | 6 |

**Live demo (v1, frozen):** https://interlock-ai-re8mb948inkerzmkn5zpgv.streamlit.app/

**Live demo (v2, hybrid):** TBD — first deploy lands at Sprint 1 close.

- PRD: [`docs/PRD.md`](docs/PRD.md) — reviewer persona, wedge, 5-layer platform path
- TDD: [`docs/TDD.md`](docs/TDD.md) — architecture, tolerance bands, evaluation, known limits
- Architecture diagrams: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — control flow, data flow, cache hierarchy
- Authorship: [`docs/AUTHORSHIP.md`](docs/AUTHORSHIP.md) — what's built / reused / disclosed, per-phase
- Demo script: [`docs/DEMO_SCRIPT.md`](docs/DEMO_SCRIPT.md) — 3-minute walkthrough
- Locked scope + fixtures: [`docs/SCOPE.md`](docs/SCOPE.md), [`docs/FIXTURES.md`](docs/FIXTURES.md)
- Risk register: [`docs/RISK_REGISTER.md`](docs/RISK_REGISTER.md)
- Backlog (out-of-scope): [`docs/BACKLOG.md`](docs/BACKLOG.md)

## Quick start (local)

```bash
uv sync
uv run pytest --deselect tests/real_world   # 261 tests, ~1:30 wall-clock
uv run streamlit run src/interlock/ui/app.py
```

## Requirements

- Python 3.12 (pinned in `.python-version`)
- [uv](https://github.com/astral-sh/uv)
- Ghostscript (Camelot dependency): `brew install ghostscript`
- `.env` populated from `.env.example`:
  - `VOYAGE_API_KEY` — required (semantic alignment + canonical glossary)
  - `ANTHROPIC_API_KEY` — required for the vision-OCR fallback (any scanned-PDF page) and the opt-in LLM significance judge

## Demo

Two fixture pairs ship with the repo.

### Option 1 — revision-diff (60% baseline ↔ 90% revision)

- `doc_a_60pct.pdf` — Doc A (authoritative, real Eaton sample coordination study)
- `doc_b_90pct.pdf` — Doc B (downstream, derived from Doc A with 6 documented mutations — see `fixtures/mutations/MUTATIONS.md`)

Expected: **4 flags** all grouped under **critical** severity — all decimal-shift class (`%Z 5.75 → 0.575`, `Fault Current 20,000 → 200,000 A`, `Transformer Rating 1000 → 100 kVA` × 2 sites). Zero false positives. FP-1 unit-equivalent trap (`150 kVA` vs `0.15 MVA`) suppressed by Pint normalisation. Info-tier within-tolerance changes suppressed by default (drop the confidence threshold slider to surface them).

### Option 2 — cross-document (equipment spec ↔ coordination study)

- `spec_xfmr_001.pdf` — Doc A (authoritative, synthetic transformer Equipment Data Sheet; see `docs/AUTHORSHIP.md` for disclosure)
- `doc_a_60pct.pdf` — Doc B (downstream, the same Eaton study reused)

Expected: **3 flags** surfaced via semantic alignment + canonical glossary:
- `Rated Power 1100 kVA ↔ Transformer Rating 1000 kVA` (minor, 9 % deviation)
- `Primary Voltage 12.47 kV ↔ System Voltage 13.8 kV` (major, 10.7 % deviation, pairing confidence 0.90)
- `Rated Impedance 4.5 % ↔ %Z 5.75 %` (major, 28 % deviation)

Plus **4 unpaired records on the spec side** (Secondary Voltage, Frequency, BIL, Insulation Class — no counterpart in the study) and **49 unpaired records on the study side** (fuse designations + duplicate transformer references — no counterpart in the spec) surfaced in the "📋 Unpaired records" expander for honest gap reporting. Toggle **Use LLM significance judge** in the sidebar to enrich each flag with engineering rationale + downstream-effect propagation (Anthropic Opus 4.7, prompt-cached).

### Option 3 — scanned PDF (vision OCR + plausibility re-OCR)

- `doc_a_scanned.pdf` — JPEG-encoded raster of `doc_a_60pct.pdf` (every page image-only, zero native text)

Enable **Vision OCR** in the sidebar; ingestion routes every low-coverage page through Claude Sonnet 4.5 at 300 DPI with a verification re-OCR pass at 400 DPI when a numeric value falls outside its family's plausibility range. Per-page progress bar in the UI. Pair against `doc_b_90pct.pdf` (or any other doc) for a full review on extracted text. Recovers 54 parameters vs 52 from the native baseline (104 % yield).

A/B comparison verifies Option 2 demonstrates a capability Option 1 cannot:

```bash
uv run python scripts/run_ab.py
cat eval/results/ab_comparison.json
```

## Evaluation

```bash
uv run python scripts/run_eval.py
cat eval/results/baseline.json
```

Gold set: `fixtures/eval/gold.yaml`. Acceptance thresholds locked in `docs/FIXTURES.md` §6 (recall=1.0 on TPs, FP-rate=0.0 on traps).

## Deploy (Streamlit Cloud)

1. Sign in at https://share.streamlit.io with the same GitHub account that owns this repo.
2. New app → repo `funcpointer/interlock-ai`, branch `main`, main file `streamlit_app.py` (root entrypoint shim; real UI in `src/interlock/ui/app.py`).
3. Advanced settings → Python 3.12.
4. Secrets → paste `VOYAGE_API_KEY` and `ANTHROPIC_API_KEY` as TOML.
5. Deploy.

`packages.txt` declares `ghostscript` so Camelot's lattice parser works on the cloud runner.

## Access notes

| Asset | Where | How a reviewer accesses it |
|---|---|---|
| Source code | https://github.com/funcpointer/interlock-ai | Public read. Phase tags + `v1.*` checkpoints provide point-in-time snapshots. |
| Deployed prototype | https://interlock-ai-re8mb948inkerzmkn5zpgv.streamlit.app/ | Public read. Cold start ~30 s on first visit (Streamlit Cloud free tier). |
| Demo video | (URL added after recording) | Public read. |
| Fixture PDFs | `fixtures/pdfs/` in the repo | Tracked in git. Real Eaton document is a public sample; synthetic fixtures disclosed in `docs/AUTHORSHIP.md`. |
| Evaluation gold sets | `fixtures/eval/gold*.yaml` | Tracked in git. Acceptance thresholds in `docs/FIXTURES.md` §6. |
| API keys | Not in the repo (gitignored `.env`) | Reviewer brings their own `VOYAGE_API_KEY` and `ANTHROPIC_API_KEY` for local runs; the deployed Streamlit Cloud instance has them configured server-side. |
| Internal session transcripts / planning notes | `docs/superpowers/`, `CLAUDE.md` | Gitignored. Not part of the submission. |

## Phase tags

The repo's history is partitioned into TDD phases; each phase ends in a verifiable checkpoint tag.

```
phase-0-scaffold              phase-3-extract               phase-6-citation
phase-1-fixtures              phase-4-align                 phase-7-ui
phase-2-ingest                phase-5-detect                phase-8-eval
phase-9-deploy                phase-11-cross-doc            phase-12-real-world
phase-13-tolerance            phase-14-entity-claim         phase-17-deliverables
phase-18-ux-ocr               phase-19-identity-alignment   phase-20-ocr-quality

v1.0-mvp · v1.1-cross-doc · v1.2-real-world · v1.3-tolerance ·
v1.4-entity-claim · v1.5-mvp-ready
```

**Test surface (v1.5-mvp-ready):** 261 passing (default), 83 slow-marked + live-API deselected, mypy strict clean, ruff clean. Cost per demo run < $0.10 with diskcache + Anthropic 1-hour prompt caching on ontology blocks. OCR-enabled run on a 9-page scanned fixture: ~$0.45 cold, ~$0 warm.
