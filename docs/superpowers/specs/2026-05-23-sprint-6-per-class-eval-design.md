# Sprint 6 — Per-class Eval + Confidence Calibration Design Spec

**Goal.** Ship the per-doc-class gold-flag harness + confidence-calibration infra so v2 has measurable per-class precision/recall + a Brier-score reliability report. PIVOT_PLAN Sprint 6.

**Exit tag:** `v2.7-eval`. Honest-scope: ships infrastructure + 1 seed gold set (coordination_study Option 1). Other doc classes filled incrementally as fixtures arrive (fixture sourcing is content work, not code scope).

---

## §1 Approach + Components

Three deliverables, all deterministic, all offline-runnable:

1. **Per-class gold-flag schema** — YAML at `fixtures/eval/gold_flags/<doc_class>.yaml`. Each file lists fixture-pairs of that doc class with expected `surfaced` flags (positives) + `suppressed` flags (false-positive traps).

2. **Per-class eval harness** — `scripts/run_per_class_flag_eval.py`. Runs `review_two_documents()` on each pair; compares actual flags against gold; writes a per-class JSON report + Markdown summary with precision/recall/F1 + count of FP traps that leaked.

3. **Confidence calibration script** — `scripts/run_confidence_calibration.py`. Bins predicted confidence into deciles; computes accept-rate per bin via the gold "surfaced" labels; reports Brier score + a reliability table (`docs/eval/confidence_calibration.md`).

**Soft CI gate** — `tests/eval/test_per_class_gate.py`. Per-class precision ≥ floor / recall ≥ floor (initial floor 0.6 / 0.6). Marked `xfail` when corpus has < 3 gold cases for a class so sparse coverage doesn't break CI.

**No new LLM cost.** All scripts use existing pipeline output (which is itself cached).

**Seed gold:** Sprint 6 ships one populated gold YAML: `coordination_study.yaml` matching the existing Option 1 fixture pair (the 3 TP flags: %Z, Fault Current, Transformer Rating; the 2 FP traps already encoded in `tests/eval/test_cross_doc_default_safe_on_option1.py`).

**New files:**

| Path | Responsibility |
|---|---|
| `fixtures/eval/gold_flags/coordination_study.yaml` | Seed per-class gold for coordination_study |
| `src/interlock/eval/per_class.py` | Gold-loading + per-class precision/recall computation |
| `src/interlock/eval/calibration.py` | Confidence binning + Brier score |
| `scripts/run_per_class_flag_eval.py` | CLI runner over all per-class gold files |
| `scripts/run_confidence_calibration.py` | CLI calibration reporter |
| `tests/eval/test_per_class.py` | Unit tests for gold load + metric math |
| `tests/eval/test_calibration.py` | Unit tests for binning + Brier |
| `tests/eval/test_per_class_gate.py` | Soft CI gate |
| `eval/results/per_class.json` | Latest per-class run output (gitignored or committed for baseline) |
| `docs/eval/confidence_calibration.md` | Latest calibration table (committed) |

**Modified:** `docs/AUTHORSHIP.md` + `docs/TDD.md`.

---

## §2 Per-class Gold Schema

```yaml
# fixtures/eval/gold_flags/coordination_study.yaml
doc_class: coordination_study
description: |
  Per-class flag gold set for coordination_study fixtures. Each pair lists
  expected surfaced flags (true positives) + suppressed flags (false-positive
  traps). Harness scores precision/recall against this set.

pairs:
  - id: option1-60vs90
    doc_a: fixtures/pdfs/doc_a_60pct.pdf
    doc_b: fixtures/pdfs/doc_b_90pct.pdf
    pipeline_kwargs:
      classify_docs: false
      use_llm_extraction: false
      use_llm_reranker: false
      use_entity_grounding: false
      use_llm_judge: false
      same_page_only: false
    surfaced:
      - id: TP-1
        parameter_substr: "%Z"
        a_value_substr: "5.75"
        b_value_substr: "0.575"
      - id: TP-2
        parameter_substr: "Fault Current"
        a_value_substr: "20,000"
        b_value_substr: "200,000"
      - id: TP-3
        parameter_substr: "Transformer Rating"
        a_value_substr: "1000 kVA"
        b_value_substr: "100 kVA"
    suppressed:
      - id: FP-1
        parameter_substr: "kVA"
        a_value_substr: "150"
        b_value_substr: "0.15"
```

Schema (`src/interlock/eval/per_class.py`):

```python
class GoldFlag(BaseModel):
    model_config = ConfigDict(frozen=True)
    id: str
    parameter_substr: str
    a_value_substr: str
    b_value_substr: str


class GoldPair(BaseModel):
    model_config = ConfigDict(frozen=True)
    id: str
    doc_a: str
    doc_b: str
    pipeline_kwargs: dict[str, object] = Field(default_factory=dict)
    surfaced: list[GoldFlag] = Field(default_factory=list)
    suppressed: list[GoldFlag] = Field(default_factory=list)


class GoldClassFile(BaseModel):
    model_config = ConfigDict(frozen=True)
    doc_class: str
    description: str = ""
    pairs: list[GoldPair]
```

Matcher (loose substring on parameter name + raw_value, case-insensitive):

```python
def flag_matches_gold(flag: Flag, gold: GoldFlag) -> bool:
    if gold.parameter_substr.lower() not in flag.parameter.lower():
        return False
    a_lc = (flag.a_record.raw_value or "").lower()
    b_lc = (flag.b_record.raw_value or "").lower()
    if gold.a_value_substr.lower() not in a_lc:
        return False
    if gold.b_value_substr.lower() not in b_lc:
        return False
    return True
```

---

## §3 Eval Harness

```python
# src/interlock/eval/per_class.py
def evaluate_class(
    gold: GoldClassFile,
    *,
    embed_fn: EmbedFn,
    threshold: float = 0.6,
) -> ClassEvalReport:
    """For each pair in gold: run pipeline → score TP/FP/FN.

    Returns ClassEvalReport(precision, recall, f1, per_pair_results).
    """
```

Per-pair scoring:
- TP = gold.surfaced that found a matching flag with confidence ≥ threshold.
- FN = gold.surfaced with no matching flag.
- FP = gold.suppressed that did surface (matched a flag above threshold).

Precision = `TP / (TP + FP)` (clamped 0 when denominator 0).
Recall = `TP / (TP + FN)`.
F1 = harmonic mean.

CLI: `python scripts/run_per_class_flag_eval.py` walks `fixtures/eval/gold_flags/*.yaml`, runs `evaluate_class()`, writes `eval/results/per_class.json` + Markdown summary at `eval/results/per_class.md`.

---

## §4 Confidence Calibration

```python
# src/interlock/eval/calibration.py
def calibrate(
    flags_with_labels: list[tuple[Flag, bool]],  # (flag, is_true_positive)
    *,
    n_bins: int = 10,
) -> CalibrationReport:
    """Bin flags by predicted confidence; compute observed accept-rate per bin.

    Returns CalibrationReport(brier_score, bins=[{lo, hi, count, predicted_avg,
    observed_rate}, ...]).
    """
```

Brier score: `mean((confidence - is_tp)^2)`. Lower is better; perfect calibration = 0.

Reliability table written to `docs/eval/confidence_calibration.md`:

| Bin | Count | Predicted (avg) | Observed (TP rate) | Diff |
|---|---:|---:|---:|---:|
| 0.0–0.1 | 0 | — | — | — |
| 0.5–0.6 | 5 | 0.55 | 0.80 | +0.25 (underconfident) |
| 0.9–1.0 | 12 | 0.95 | 1.00 | +0.05 |
| **Brier score: 0.073** | | | | |

CLI: `python scripts/run_confidence_calibration.py` reads `eval/results/per_class.json`, builds labels from gold matches, writes calibration table.

---

## §5 TDD Phases (5 phases)

### Phase 31.1 — Per-class gold schema + 1 seed file

- Tests `tests/eval/test_per_class.py` (~8): schema load, missing file errors gracefully, `flag_matches_gold` substring semantics, pair-without-surfaced/suppressed edge cases.
- Implement schema in `src/interlock/eval/per_class.py`.
- Write `fixtures/eval/gold_flags/coordination_study.yaml`.
- **Tag:** `phase-31.1-per-class-gold`.

### Phase 31.2 — Eval harness + script

- Tests (~6): TP / FN / FP scoring math, precision/recall/F1 computation, empty gold returns zeros not NaN, threshold filter applies correctly.
- Implement `evaluate_class()` + `ClassEvalReport`.
- Implement `scripts/run_per_class_flag_eval.py` CLI.
- **Tag:** `phase-31.2-eval-harness`.

### Phase 31.3 — Confidence calibration

- Tests `tests/eval/test_calibration.py` (~6): Brier score correctness, bin assignment (edge cases at 0 and 1), empty input returns zeros, single bin all-zeros / all-ones.
- Implement `calibrate()` + `CalibrationReport`.
- Implement `scripts/run_confidence_calibration.py` CLI.
- **Tag:** `phase-31.3-calibration`.

### Phase 31.4 — Soft CI gate

- Tests `tests/eval/test_per_class_gate.py`: for each gold class file, assert precision ≥ 0.6 AND recall ≥ 0.6. `xfail` when class has < 3 gold cases (sparse → noisy).
- **Tag:** `phase-31.4-ci-gate`.

### Phase 31.5 — Docs + sprint exit

- AUTHORSHIP + TDD known-limits.
- Run harness once → commit `eval/results/per_class.json` + `docs/eval/confidence_calibration.md` as baseline.
- **Exit tag:** `v2.7-eval`.

---

## §6 Cost + Latency

| | Cold | Warm |
|---|---:|---:|
| Harness run on Option 1 pair (rule-only) | ~10 s (Voyage embed) | ~5 s (cached) |
| Per-class loop (1 class × 1 pair) | ~10 s | ~5 s |
| Calibration script | <1 s | <1 s |
| LLM cost | **$0** (rule-only gold) | **$0** |

When the gold corpus includes pipeline_kwargs with `use_llm_judge=true`, costs scale per Sprint 5a/4.5 envelopes.

---

## §7 Risks + Mitigations

| Risk | Mitigation |
|---|---|
| Per-class gold is sparse early (only 1 class populated at ship) | Honest-scope statement; soft CI gate xfails sparse classes; content sourcing is follow-up work. |
| Substring matcher false-matches across very similar params | Matcher requires BOTH parameter substring + both raw_value substrings — three independent gates reduce collisions. Gold YAML reviewer audits matches at commit. |
| Calibration table misleading on small sample sizes | Bin counts < 5 marked as "_insufficient sample_" in the Markdown table. Brier headline reports n + 95% CI when available. (CI calc deferred — initial release shows count only.) |
| Pipeline change breaks gold scoring overnight | The gold YAML pins `pipeline_kwargs` per pair — explicit reproducibility. v2.x feature flips (defaults flips) don't silently drift gold scoring. |
| Reviewers conflate Brier with accuracy | Markdown header explains: lower = better, 0 = perfect, 0.25 = random. |

---

## Self-review notes

- All sections trace to PIVOT_PLAN Sprint 6 scope.
- No "TBD" strings.
- Identifier consistency: `GoldFlag` / `GoldPair` / `GoldClassFile` / `ClassEvalReport` / `CalibrationReport` used uniformly.
- Phase tags `phase-31.<N>-<slug>`.
- Final tag `v2.7-eval`.
- Honest-scope: ships infra + 1 seed gold; corpus growth is content sourcing.
