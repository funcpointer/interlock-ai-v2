# InterLock AI

Cross-document discrepancy detection for engineering PDFs. Reviewer uploads two PDFs from the same project; the system surfaces directional, cited, confidence-scored parameter mismatches.

- Locked scope: [`docs/SCOPE.md`](docs/SCOPE.md)
- Locked fixtures: [`docs/FIXTURES.md`](docs/FIXTURES.md)
- Implementation plan: [`docs/superpowers/plans/2026-05-19-interlock-mvp.md`](docs/superpowers/plans/2026-05-19-interlock-mvp.md)
- Backlog (out-of-scope): [`docs/BACKLOG.md`](docs/BACKLOG.md)

## Quick start (local)

```bash
uv sync
uv run pytest
uv run streamlit run src/interlock/ui/app.py
```

## Requirements

- Python 3.12 (pinned in `.python-version`)
- [uv](https://github.com/astral-sh/uv)
- Ghostscript (Camelot dependency): `brew install ghostscript`
- `.env` populated from `.env.example`:
  - `VOYAGE_API_KEY` — required (semantic alignment)
  - `ANTHROPIC_API_KEY` — required (vision fallback path; not exercised by default fixtures)

## Demo

Two fixture pairs ship with the repo.

### Option 1 — revision-diff (60% baseline ↔ 90% revision)

- `doc_a_60pct.pdf` — Doc A (authoritative, real Eaton sample coordination study)
- `doc_b_90pct.pdf` — Doc B (downstream, derived from Doc A with 6 documented mutations — see `fixtures/mutations/MUTATIONS.md`)

Cross-document mode **off**. Expected: 4 flags surfaced at confidence 1.0 (TP-1 impedance, TP-2 fault current, TP-3 transformer rating × 2 sites). Zero false positives. FP-1 unit-equivalent trap (`150 kVA` vs `0.15 MVA`) suppressed by Pint normalization.

### Option 2 — cross-document (equipment spec ↔ coordination study)

- `spec_xfmr_001.pdf` — Doc A (authoritative, synthetic transformer Equipment Data Sheet; see `docs/AUTHORSHIP.md` for disclosure)
- `doc_a_60pct.pdf` — Doc B (downstream, the same Eaton study reused)

Cross-document mode **on**. Expected: 3 flags surfaced via semantic alignment + canonical glossary — Rated Power ↔ Transformer Rating, Rated Impedance ↔ %Z, Primary Voltage ↔ System Voltage. Zero exact-name matches in this pair; the semantic path carries the entire signal.

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

## Phase tags

The repo's history is partitioned into TDD phases; each phase ends in a verifiable checkpoint tag.

```
phase-0-scaffold   phase-3-extract   phase-6-citation   phase-9-deploy
phase-1-fixtures   phase-4-align     phase-7-ui         v1.0-mvp
phase-2-ingest     phase-5-detect    phase-8-eval
```
