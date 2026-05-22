# Sprint 3 Design — Adjudicator + Provenance UX

**Project:** InterLock AI v2
**Sprint:** 3 (week 6–7 of 6-sprint hybrid pivot)
**Baseline:** `v2.1-llm-extraction`
**Approved:** 2026-05-22
**Exit tag:** `v2.2-adjudicator`

---

## Purpose

Sprint 3 makes the v2 hybrid advantage **visible to reviewers** by annotating each surfaced flag with the track(s) that contributed to it and providing reviewer-facing UX to filter / inspect by track of origin.

No new capability, no new LLM call, no new alignment behaviour. Sprint 3 is a thin annotation layer on top of v2.1's union-merged flag pipeline plus the UX surfaces that make the annotation reviewer-actionable. It's the cheapest sprint of the v2 plan — $0 build cost, $0 per-review cost — and the deliverable is "the hybrid pivot is no longer invisible to reviewers."

Exit when:
- Every emitted `Flag` carries a `provenance` label derived from its `a_record` + `b_record` provenance fields
- UI shows reviewer-facing badges (silent default, prominent exceptions) + a sidebar filter
- JSON export records track-of-origin per accepted flag
- v1.5-mvp-ready snapshot equivalence still holds bit-identically

---

## §1. Approach + components

**Approach: thin adjudicator post-processes the existing flag list; UI surfaces a derived provenance badge per flag.**

Pipeline doesn't change structurally — Track 1 + Track 2 records still flow to alignment + detect as before. After `detect_flags` produces the flag list, a new `adjudicate_flags()` function annotates each flag with `provenance: Literal["rule_only", "llm_only", "mixed_track", "unknown"]` derived from its `a_record.provenance + b_record.provenance`.

**Why post-processing over re-architecture:**

- No alignment changes needed — Phase 19 entity-tag + ambiguity gates already do the right thing on unioned records
- Provenance is a property OF a flag (not an alternative path); a separate annotator keeps `detect/mismatch` pure
- Trivial to test (pure function on Flag list); trivial to roll back if reviewer feedback rejects the framing

**Rejected alternatives:**

| Alternative | Why not |
|---|---|
| Run alignment twice (per track), merge flag lists | Doubles compute. Requires conflict resolution at the flag level (same parameter from both tracks → which wins?). Sprint 4's pairing reranker may resurface this; Sprint 3 stays cheap. |
| Detect "both tracks independently agree" via duplicate detection | Phase 19's gates suppress duplicate records at the alignment layer so a "both agree" flag never forms organically. Detecting it would need running alignment per-track + matching flags across runs — same complexity as the rejected alternative. Worth Sprint 4+. |
| Per-side provenance only (no merged label) | Already accessible via `flag.a_record.provenance` + `flag.b_record.provenance`. The derived label is the reviewer-facing simplification; the per-side raw signal remains visible in the per-flag expander when non-default. |

**Components:**

| Path | Responsibility |
|---|---|
| `src/interlock/adjudicator.py` | `adjudicate_flags(list[Flag]) -> list[Flag]` annotates each Flag with `provenance` field |
| `src/interlock/detect/mismatch.py` | `Flag` gains `provenance: Literal["rule_only", "llm_only", "mixed_track", "unknown"] = "unknown"` field (default for back-compat) |
| `src/interlock/pipeline.py` | Wires adjudicator after `detect_flags`; runs whenever pipeline runs (no opt-in toggle — pure annotation, zero cost) |
| `src/interlock/ui/app.py` | Provenance badge in flag header (silent default + prominent exceptions); sidebar filter (radio: All / Deterministic / AI-only / Hybrid sources); per-flag expanded view shows track detail when non-default |
| `src/interlock/store/sqlite.py` + `data/interlock.schema.sql` | `decision` table gains a `provenance` column (additive `ALTER TABLE ... ADD COLUMN ... DEFAULT 'unknown'`) |
| JSON export in `ui/app.py` | Each exported flag dict gains a `provenance` key |

**Cost envelope:** zero — adjudicator is a pure Python function over the existing flag list. No new LLM calls, no new I/O.

---

## §2. Schema + adjudicator logic

**`Flag.provenance` field with safe default:**

```python
# src/interlock/detect/mismatch.py — within Flag dataclass
@dataclass(frozen=True)
class Flag:
    # ...existing fields...
    # v2 Sprint 3 — provenance label derived from a_record.provenance +
    # b_record.provenance by adjudicate_flags(). Default "unknown" for
    # back-compat with hand-constructed Flags in tests.
    provenance: Literal["rule_only", "llm_only", "mixed_track", "unknown"] = "unknown"
```

**Adjudicator logic — pure function, fully mechanical:**

```python
# src/interlock/adjudicator.py
"""Sprint 3 — flag-level provenance annotation.

Derives the per-flag provenance label from the records that contributed
to it. This is a thin post-processing layer; no flag is added, removed,
or reordered.

Provenance taxonomy (3-state + unknown):
  - "rule_only"   : both records are Track 1 (regex extraction)
  - "llm_only"    : both records are Track 2 (LLM extraction)
  - "mixed_track" : one record from each track — different tracks
                    contributed to the same cross-doc comparison
  - "unknown"     : either record's provenance is unset (defensive;
                    shouldn't happen in pipeline flow but covers
                    hand-constructed Flags in tests)
"""

from __future__ import annotations

from dataclasses import replace

from interlock.detect.mismatch import Flag


def adjudicate_flags(flags: list[Flag]) -> list[Flag]:
    """Return new Flag list with provenance annotated per flag."""
    out: list[Flag] = []
    for f in flags:
        a_prov = getattr(f.a_record, "provenance", None)
        b_prov = getattr(f.b_record, "provenance", None)
        provenance = _classify_provenance(a_prov, b_prov)
        out.append(replace(f, provenance=provenance))
    return out


def _classify_provenance(
    a_prov: str | None, b_prov: str | None,
) -> str:
    if a_prov is None or b_prov is None:
        return "unknown"
    if a_prov == "regex" and b_prov == "regex":
        return "rule_only"
    if a_prov == "llm" and b_prov == "llm":
        return "llm_only"
    return "mixed_track"
```

**Pipeline integration:**

```python
# src/interlock/pipeline.py — after the existing detect_flags() call
_stage("detect", "start")
flags = detect_flags(combined, suppress_info=suppress_info)
_stage("detect", "done")

# v2 Sprint 3: annotate provenance. Pure function; zero cost; runs always.
from interlock.adjudicator import adjudicate_flags
flags = adjudicate_flags(flags)
```

**Why this shape:**

| Choice | Rationale |
|---|---|
| Add field to `Flag`, not a separate `FlagWithProvenance` type | UI + JSON export + downstream code all reference one canonical type. Smallest change. |
| Default `"unknown"` (not `"rule_only"`) | Hand-constructed Flags in tests + the existing 261 v1 tests use regex records by default, so they'd land `rule_only` after adjudication — same as we want. But the field DEFAULT is `"unknown"` because Flag may be constructed without going through the pipeline. Adjudicator overwrites with the right label when it runs. |
| Adjudicator runs always (not opt-in) | Cost is zero. Reviewers always benefit from the label, even when looking at v1.5-style runs where every flag will be `rule_only`. |
| `dataclasses.replace` for immutability | Mirrors how Phase 19 `pairing_confidence` was added — Flag stays frozen-friendly. |

---

## §3. UI surface — badge + filter (silent default, prominent exceptions)

**Provenance badge in flag header:**

| Provenance | Badge? | Wording | What it tells the reviewer |
|---|---|---|---|
| `rule_only` | **silent — no badge** | n/a | Assumed default. Reviewer's eye not drawn here. |
| `llm_only` | YES — prominent | **🧠 AI-only** | Both sides of this comparison were found by the LLM extraction layer; rule-based extraction missed them. **Verify the values exist in the source before acting.** |
| `mixed_track` | YES — prominent | **🔀 Hybrid sources** | One side caught by rules, the other by AI. Alignment paired them. **Verify the two records describe the same physical parameter before acting.** |

Placement: appended to the existing flag header alongside severity + dev% + confidence + pairing badge:

```
🔴 CRITICAL · %Z · Δ 90% · confidence 1.00
🟠 MAJOR · Rated Power · Δ 9% · confidence 1.00 · 🧠 AI-only · ⚠️ weak pair
🟠 MAJOR · Pickup PCT2 · Δ 33% · confidence 0.85 · 🔀 Hybrid sources
```

Mirrors the existing `⚠️ weak pair` pattern — appears only when the reviewer needs to look closer.

**Sidebar filter — radio:**

```
Filter by track
( ) All flags (default)
( ) ⚙ Deterministic only (rules found both sides)
( ) 🧠 AI-only (LLM found both sides)
( ) 🔀 Hybrid sources (rules + LLM, one side each)
```

Each option names *what gets shown* in plain language. No "Track 1" / "Track 2" anywhere in reviewer-facing text.

When set to anything other than "All", flags not matching the filter hide from the main results pane (still accessible by switching the filter back).

**Sidebar caption clarifying scope:**

```
> Track filter narrows what's shown. Both Track 1 (regex) and
> Track 2 (LLM) always run when enabled in the upper sidebar
> — the filter doesn't change what gets computed.
```

**Per-flag expanded view — show extra detail only when non-default:**

| Provenance | Extra line in expander |
|---|---|
| `rule_only` | _(no extra line — clean)_ |
| `llm_only` | `Track provenance: 🧠 AI-only — both sides extracted by the LLM layer (Sprint 2)` |
| `mixed_track` | `Track provenance: 🔀 Hybrid — Doc A=Rules · Doc B=AI. Verify these two records describe the same physical parameter.` |

The per-side line is verbose ONLY when it carries meaning. Pure-rule runs (v1.5 behaviour or v2 runs where regex catches everything) are clean.

**JSON export** — each accepted-flag entry gains a `provenance` key:

```json
{
  "verdict": "accepted",
  "parameter": "%Z",
  "severity": "critical",
  "deviation_pct": 90.0,
  "confidence": 1.0,
  "provenance": "rule_only",
  "doc_a_value": "5.75 %",
  "doc_b_value": "0.575 %",
  ...
}
```

Reviewer downstream tooling can group / filter / audit by track-of-origin.

---

## §4. Audit trail + back-compat

**Audit trail beyond the JSON export.**

Phase 14 shipped a `decision` table in `data/interlock.schema.sql` for SQLite-persisted reviewer verdicts. v2 UI doesn't currently write to it — the JSON export is the audit surface. Sprint 3 doesn't change that wiring; it adds `provenance` to whatever audit surface IS in use.

Schema change in `data/interlock.schema.sql`:

```sql
-- Sprint 3 addition (backwards-compatible — column added with default)
ALTER TABLE decision ADD COLUMN provenance TEXT NOT NULL DEFAULT 'unknown';
```

Schema migration is idempotent via the existing `apply_schema()` pattern in `src/interlock/store/sqlite.py`. Stores that never call `apply_schema` (the default v1 + v2 path) ignore this entirely. Stores that DO call it (Phase 14 `persist_claims=True`) gain the column with a safe default for any pre-Sprint-3 rows.

**Back-compat invariants reinforced in Sprint 3:**

| Surface | What stays the same |
|---|---|
| v1.5 snapshot equivalence | `classify_docs=False` + `use_llm_extraction=False` still bit-identical (adjudicator runs but every flag gets `rule_only` — same flag set, same severity, same confidence) |
| 261-test v1 invariant suite | Still gates every commit. Flag's new `provenance` field has `"unknown"` default so hand-constructed Flags in tests don't break. |
| Pipeline return type | `ReviewResult` unchanged; only `Flag.provenance` field is new |
| `review_two_documents()` shim | Unchanged signature; still returns `list[Flag]` |
| JSON export | Existing keys preserved; `provenance` added as a new key |
| Per-flag UI block | Existing severity / confidence / pairing badges + Accept/Dismiss buttons unchanged |

---

## §5. TDD checkpoints / 5 phases

Sprint 3 breaks into 5 commits. Sized smaller than Sprint 2 (no LLM calls, no prompt engineering, no live API gates).

| # | Commit | Tests added | Tag |
|---|---|---|---|
| **26.1** | `Flag.provenance` field with `"unknown"` default | `tests/detect/test_provenance_field.py` — default `"unknown"`, can be set to each of 4 values, existing Flag construction unchanged | `phase-26.1-flag-provenance-field` |
| **26.2** | `adjudicator.py` — `adjudicate_flags()` + `_classify_provenance()` pure functions | `tests/test_adjudicator.py` — all 4 combinations (regex+regex → rule_only, llm+llm → llm_only, regex+llm → mixed_track, missing/None → unknown), preserves flag order, preserves all other Flag fields, empty list → empty list | `phase-26.2-adjudicator` |
| **26.3** | Pipeline wires adjudicator after `detect_flags` | `tests/e2e/test_pipeline_v2.py` — v1.5 snapshot equivalence holds (every flag is `rule_only` when both tracks off), `use_llm_extraction=True` produces mixed/llm_only flags, JSON export contains `provenance` key | `phase-26.3-adjudicator-pipeline` |
| **26.4** | UI badges + sidebar filter + per-flag expanded view + JSON export | UI compile check; manual smoke test on locked fixtures; no automated UI tests (Streamlit pattern matches Sprint 1's banner pattern) | `phase-26.4-adjudicator-ui` |
| **26.5** | SQLite schema migration (`provenance` column on `decision`) + AUTHORSHIP entry + TDD known-limits update + sprint exit | `tests/store/test_sqlite_provenance.py` — `ALTER TABLE` idempotent (running migration twice is a no-op), new rows get `provenance` value, pre-Sprint-3 rows get `"unknown"` default; sprint exit tag | `phase-26.5-adjudicator-schema` then `v2.2-adjudicator` |

**Gate between every step:** `uv run pytest --deselect tests/real_world` green; `uv run mypy src/` clean; `uv run ruff check .` clean. v1's 261-test invariant suite + v2.0-mvp's snapshot equivalence + v2.1's Track 2 tests all stay green at every checkpoint.

**Phase 26.4 (UI) is the heaviest** — three UI changes (badge, filter, per-flag detail line) + the JSON export key. ~half day of careful Streamlit work + manual smoke testing. No automated UI tests because Streamlit's testing surface is shallow; mirrors the pattern Sprint 1's banner work followed.

**Phase 26.5's tag is the sprint exit criterion** — `v2.2-adjudicator`. By definition Sprint 3 doesn't have a quantitative live-API exit gate (no LLM extraction quality to measure) — the exit signal is "snapshot equivalence still holds + UI surfaces provenance correctly on locked fixtures via manual smoke test."

---

## §6. Cost + latency envelope

| Operation | Cost | Latency | Cached |
|---|---:|---:|---|
| `adjudicate_flags()` per pipeline run | $0 | < 10 ms (pure Python over flag list) | N/A |
| Total Sprint 3 build | $0 dev spend | ~3–5 hours wall-clock | N/A |
| Per-review delta | $0 | + < 10 ms | N/A |

**Sprint 3 is the cheapest sprint of the v2 plan.** No LLM calls; no API costs. The exit deliverable is reviewer-facing UX, not capability expansion. Sprint 4 (pairing reranker) and Sprint 5 (Standards-as-RAG) resume the cost curve.

---

## §7. Sprint-3-specific risks

| # | Risk | Mitigation |
|---|---|---|
| S3-R1 | Internal "track" terminology leaks to reviewers | Badges + filter use reviewer-facing labels (AI-only, Hybrid sources, Deterministic). "Track" appears only in the per-flag expanded detail line where the reviewer has already opted into the detail. |
| S3-R2 | `rule_only` badge on every Eaton flag = visual noise | `rule_only` is **silent — no badge**. Eye drawn to exceptions (`llm_only`, `mixed_track`) only. |
| S3-R3 | JSON export shape change breaks downstream tooling reading old exports | Change is additive (new key, no removed keys). Downstream tooling using `dict.get("provenance", "unknown")` handles both old + new exports gracefully. Document in AUTHORSHIP. |
| S3-R4 | SQLite schema migration corrupts existing dev databases | `ALTER TABLE ... ADD COLUMN ... DEFAULT 'unknown'` is idempotent + safe in SQLite. Test asserts running the migration twice is a no-op. Pre-Sprint-3 dev DBs (which used `persist_claims=True`) gain the column on next `apply_schema` call. |
| S3-R5 | UI filter hides flags the reviewer needs but doesn't realize | Default "All". Filter caption explicitly notes "narrows what you SEE, not what gets computed." Sidebar position keeps it visible while reviewer triages. |
| S3-R6 | Reviewers conflate `llm_only` with "lower quality" finding | Tooltip on the badge spells out the right interpretation: AI surfaced a real comparison that the regex layer missed (a Sprint 2 prose-extraction win); **verify** the values exist in the source. The badge is a "look closer" signal, not a quality-downgrade. |

**S3-R3 is the architectural-safety risk.** Mitigation reinforces additive-only schema evolution.

---

## Pointers

- v2.1 baseline (this sprint builds on): tag `v2.1-llm-extraction`
- v2.0-mvp Sprint 1 spec: `docs/superpowers/specs/2026-05-22-sprint-1-doc-class-classifier-design.md`
- v2.1 Sprint 2 spec: `docs/superpowers/specs/2026-05-22-sprint-2-llm-extraction-design.md`
- v1 frozen reference: `funcpointer/interlock-ai @ v1.5-mvp-ready` (commit `fc6f24a`)
- Pivot plan: `docs/PIVOT_PLAN.md` § "Sprint 3 — Adjudicator + provenance UX"
- Project rules (v2-specific, gitignored): `CLAUDE.md`
