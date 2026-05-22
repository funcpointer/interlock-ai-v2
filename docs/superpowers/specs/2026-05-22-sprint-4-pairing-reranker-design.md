# Sprint 4 — LLM Pairing Reranker (Design Spec)

**Goal.** Replace Track 1's heuristic "weak pair" verdict on ambiguous multi-instance pairing buckets with reasoned LLM verdicts. Each weak pair (`pairing_confidence < 0.75`) is sent to Claude Sonnet 4.5 with both records' context; the model returns a score, a one-paragraph rationale, and an optional `decline_to_pair` flag. Pairs above threshold pass through untouched.

**Exit tag:** `v2.3-reranker`. **PIVOT_PLAN reference:** Sprint 4 row.

---

## §1 Approach + Components

One LLM call per Track 1 weak pair (`pairing_confidence < 0.75`). Reranker is a pure post-processing step between `combine_alignments` and `detect_flags`. Opt-in via `use_llm_reranker` kwarg; same shape as Sprints 1–3 (classifier, extractor, judge): isolated module + parallel `ThreadPoolExecutor` + diskcache + graceful failure → Track 1 fallback.

**New files:**

| Path | Responsibility |
|---|---|
| `src/interlock/llm_pipeline/pair.py` | `rerank_weak_pairs()` orchestration + `_call_claude_pair()` SDK wrapper + diskcache + parallel executor + hallucination guard |
| `src/interlock/llm_pipeline/schemas/pair.py` | `PairVerdict` pydantic v2 model |
| `src/interlock/llm_pipeline/prompts/pair.md` | System prompt; authority-hierarchy summary; "same physical record" criteria; JSON schema |

**Modified:**

| Path | Change |
|---|---|
| `src/interlock/align/exact.py` | `AlignedPair` gains `rerank_rationale: str \| None = None`, `reranked: bool = False` |
| `src/interlock/detect/mismatch.py` | `Flag` gains `rerank_rationale: str \| None = None`; `detect_flags` copies from pair |
| `src/interlock/pipeline.py` | `use_llm_reranker` kwarg (default False); calls `rerank_weak_pairs()` between `combine_alignments` and `detect_flags`; new stage id `rerank` |
| `src/interlock/ui/app.py` | Sidebar toggle; `🤖 Reranked` badge; rationale line in expander; JSON export key |

---

## §2 Schema + Reranker Logic

### `PairVerdict`

```python
class PairVerdict(BaseModel):
    model_config = ConfigDict(frozen=True)
    score: float = Field(ge=0.0, le=1.0)
    rationale: str = Field(min_length=1, max_length=2000)
    decline_to_pair: bool = False
```

Validation: score range, non-empty rationale.

### `rerank_weak_pairs(pairs, *, weak_threshold=0.75, max_workers=5)`

```python
def rerank_weak_pairs(
    pairs: list[AlignedPair],
    *,
    weak_threshold: float = 0.75,
    max_workers: int = 5,
) -> list[AlignedPair]:
    """Rerank pairs whose pairing_confidence < weak_threshold via Claude.

    Pairs above threshold pass through untouched (order preserved).
    Weak pairs are dispatched in parallel; each returns a PairVerdict.
    Pairs whose verdict is decline_to_pair drop out — callers' downstream
    unpaired_a/b computation absorbs the dropped records automatically.
    """
```

### Per-pair flow

1. **Build prompt context** with both records' `name`, `raw_value`, `page`, `section`, `entity_tag`, `span_text`, plus the 2 nearest sibling rows on each side from the same `(page, name)` bucket. Handles narrow `span_text` cases (`KRP-C-1600SP` extracted alone needs surrounding fuse-table context).
2. **Diskcache key:** `sha256(prompt + a_record_hash + b_record_hash + PROMPT_VERSION + model)`. Namespace `llm-pair`.
3. **Call** Claude Sonnet 4.5 with structured JSON response; pydantic validates.
4. **Hallucination guard:** verdict.rationale must contain at least one of the two `raw_value` tokens (case-insensitive substring). Rejected → treat as failure → keep Track 1 verdict.
5. **API / parse / validation failure** → keep original Track 1 pair (`pairing_confidence` unchanged, `reranked=False`, no rationale).
6. **Success** → `replace(pair, pairing_confidence=verdict.score, rerank_rationale=verdict.rationale, reranked=True)`. If `decline_to_pair=True`, omit the pair from output entirely.

### Parallelism

`ThreadPoolExecutor(max_workers=5)`, same cap as Sprint 2 extractor. Anthropic Sonnet RPM accommodates without 429s in practice.

### Cost ledger

Each call appends a `cost_event` row with `namespace='pair-rerank'`, `model='claude-sonnet-4-5'`, and token counts pulled from the response usage block. Same Phase 13 pattern.

---

## §3 UI Surface

### Sidebar toggle

```python
use_llm_reranker = st.toggle(
    "Track 2 LLM pairing reranker (v2 Sprint 4)",
    value=False,
    help=(
        "When a pair has low Track 1 pairing_confidence (< 0.75), send "
        "both records' context to Claude Sonnet 4.5. The reranker scores "
        "the pair, writes a one-paragraph rationale, and may decline to "
        "pair (drops the candidate flag). Replaces the generic "
        "⚠️ weak pair badge with reasoned verdicts.\n\n"
        "Cost: ~$0.005 per weak pair, diskcached per (record, record)."
    ),
)
```

### Header badge

- Reranked pair, score ≥ 0.75 → ` · 🤖 Reranked` (replaces ⚠️ weak pair).
- Reranked pair, score < 0.75 → ` · 🤖 Reranked · ⚠️ low score` (both visible — model ran but still uncertain).
- Not reranked (`reranked=False`) → existing `⚠️ weak pair` behavior.
- Sprint 3 provenance badge (`🧠 AI-only`, `🔀 Hybrid sources`) is independent and stacks alongside.

### Per-flag expander body

When `rerank_rationale` is present, add a new line above the citation columns:

```python
if f.rerank_rationale:
    st.info(f"🤖 **Reranker:** {f.rerank_rationale}")
```

### JSON export

Decisions dict gains `"rerank_rationale": getattr(f, "rerank_rationale", None)` so accepted-flag exports include the reasoning.

### Decline-to-pair

The dropped A and B records flow into the existing `📋 Unpaired records` expander automatically — pipeline already recomputes unpaired_a/b from the surviving `combined` list. No new UI plumbing.

### Stage row

New stage id `rerank` between `align` and `detect`. Label: "Reranking weak Track 1 pairs (Claude Sonnet 4.5, parallel × 5, cached)". Stage skipped entirely when `use_llm_reranker=False` or no weak pairs exist.

---

## §4 Pipeline Integration + Back-Compat

### `AlignedPair` extension

```python
@dataclass(frozen=True)
class AlignedPair:
    # ...existing fields...
    rerank_rationale: str | None = None
    reranked: bool = False
```

Defaults preserve hand-built `AlignedPair` back-compat across the legacy alignment tests.

### `Flag` extension

```python
@dataclass(frozen=True)
class Flag:
    # ...existing fields including provenance from Sprint 3...
    rerank_rationale: str | None = None
```

`detect_flags()` copies `rerank_rationale` from `pair.rerank_rationale` (one new line in the `Flag(...)` constructor call).

### Pipeline wiring

```python
combined = combine_alignments(exact, semantic)

if use_llm_reranker:
    from interlock.llm_pipeline.pair import rerank_weak_pairs
    _stage("rerank", "start")
    try:
        combined = rerank_weak_pairs(combined)
    except Exception:
        pass  # API outage → keep Track 1 verdicts
    _stage("rerank", "done")

_stage("align", "done")
```

### Back-compat guarantees (CI-gated)

1. `use_llm_reranker=False` (default) → pipeline bit-identical to `v2.2-adjudicator`. All 354 existing tests stay green.
2. `use_llm_reranker=True` with mocked Claude returning unanimous `score=0.9, decline_to_pair=False` → flag count and parameter set unchanged from Track 1.
3. `use_llm_reranker=True` with mocked Claude returning `decline_to_pair=True` → reranked pair drops; A and B records appear in `unpaired_a` / `unpaired_b`.
4. API failure mid-call → that pair keeps Track 1 verdict (no exception propagates).

### SQLite

No schema change. The reranker rationale is a runtime artifact carried on Flag and surfaced in the JSON export — same shape as Sprint 3's `provenance` key addition (which also lives in JSON, not SQL).

---

## §5 TDD Checkpoints + 5 Phases

### Phase 27.1 — `PairVerdict` schema + back-compat `AlignedPair` fields

**Tests:**
- `tests/llm_pipeline/schemas/test_pair.py` — verdict validation (score range [0,1], non-empty rationale, decline_to_pair defaults False).
- `tests/align/test_aligned_pair_back_compat.py` — `rerank_rationale=None` and `reranked=False` defaults preserve every existing alignment test.

**Implement:** extend `AlignedPair`, add `PairVerdict` pydantic model.

**Tag:** `phase-27.1-rerank-schemas`.

### Phase 27.2 — Reranker module with mocked Claude

**Tests** (`tests/llm_pipeline/test_pair.py`), minimum 10:
1. Weak-pair selection: pairs with `pairing_confidence >= 0.75` untouched (no LLM call).
2. `decline_to_pair=True` drops the pair from output.
3. `decline_to_pair=False` overwrites `pairing_confidence` with `verdict.score`.
4. `rerank_rationale` carried onto returned pair.
5. `reranked=True` set on every reranked pair.
6. Hallucination guard: rationale missing both raw_values → keep Track 1 verdict.
7. Parallel ordering: returned list order matches input order.
8. API failure → keep Track 1 verdict (no exception escapes).
9. Pydantic validation failure → keep Track 1.
10. Diskcache hit short-circuits the API call.
11. Empty input → empty output.

**Implement:** `src/interlock/llm_pipeline/pair.py` with `rerank_weak_pairs()`, `_call_claude_pair()`, prompt loader. Prompt file `src/interlock/llm_pipeline/prompts/pair.md`.

**Tag:** `phase-27.2-rerank-module`.

### Phase 27.3 — Pipeline integration + `Flag.rerank_rationale`

**Tests** (append to `tests/e2e/test_pipeline_v2.py`):
1. `use_llm_reranker=False` is bit-identical to v2.2 snapshot equivalence.
2. `use_llm_reranker=True` with mocked unanimous-approve produces same flag set.
3. Mocked `decline_to_pair=True` drops the pair; A and B records appear in `unpaired_a` / `unpaired_b`.
4. Reranker exception caught in pipeline → flags still ship.
5. Sprint 3 provenance label + Sprint 4 rerank_rationale coexist on a single flag.

**Implement:** `Flag.rerank_rationale` field; `detect_flags` copies from pair; pipeline kwarg + call site; stage callback id `rerank`.

**Tag:** `phase-27.3-rerank-pipeline`.

### Phase 27.4 — UI surface

**Manual smoke + compile checks** (no Streamlit unit tests):
- Sidebar toggle renders.
- Pair with `reranked=True` shows `🤖 Reranked` badge.
- Pair with `reranked=True` AND `pairing_confidence < 0.75` shows `🤖 Reranked · ⚠️ low score`.
- Expander shows rationale as `st.info()` block above citation columns.
- JSON export accepted-flag dict contains `rerank_rationale` key.
- Stage callback row appears in `st.status` only when reranker ran.

**Tag:** `phase-27.4-rerank-ui`.

### Phase 27.5 — Live-API exit gate + docs

**Tests** (`tests/real_world/test_reranker_live.py`, slow + needs_anthropic):

1. `test_krp_c_lps_rk_pair_correctly_declined` — fuse part-numbers from different ampacity families (KRP-C-1600SP main vs LPS-RK-400SP branch). Assert `decline_to_pair=True` or `score < 0.5`.
2. `test_150kva_100kva_pair_correctly_declined` — two transformers' nameplate values on the same one-line diagram. Assert decline or low score.

Either case uses existing fixtures if the pair surfaces there; otherwise hand-craft minimal 1-page PDFs with the failure-case rows.

**Docs:**
- `docs/AUTHORSHIP.md` — Sprint 4 per-phase entry.
- `docs/TDD.md` — known-limits Sprint 4 entry (heuristics-stay-in-Track-1, anecdotal eval surface, no per-class gold yet).

**Exit tag:** `v2.3-reranker`.

---

## §6 Cost + Latency

| | Cold | Warm |
|---|---:|---:|
| Per weak pair | ~$0.005 (Sonnet 4.5, ~600 in / ~150 out tokens) | $0 (diskcache hit) |
| Locked Option 1 fixture (~3–5 weak pairs) | ~$0.025 | $0 |
| Coordination study with many fuses (~20–50 weak pairs) | $0.10–$0.25 | $0 |
| Latency added | ~3–8 s parallel × 5 workers | <100 ms (cache hit) |

Within PIVOT_PLAN's $0.50–$3 per-review budget alongside Sprints 2 + 3.

---

## §7 Risks + Mitigations

| Risk | Mitigation |
|---|---|
| LLM over-confidently pairs wrong records (regresses Track 1's "decline to pair" wisdom) | Hallucination guard: rationale must mention one of the two raw_values. Live exit gate on KRP-C / 150 kVA cases. Default off. |
| Streamlit UI blocks on parallel pool exhaustion | ThreadPoolExecutor capped at 5; stage callback fires `rerank start/done` so user sees progress; whole rerank stage skipped when no weak pairs exist. |
| Cost surprise on fuse-heavy diagrams | Toggle default off. Sidebar help quotes "$0.10–$0.25 on fuse-heavy diagrams" explicitly. Diskcache means rerun is free. |
| Reranker disagrees with Sprint 3 adjudicator | Orthogonal: provenance describes tracks-of-origin; reranker affects pairing_confidence + rationale. Cross-test asserts both labels coexist on a single flag (Phase 27.3 test #5). |
| Prompt drift across model versions | `PROMPT_VERSION = "v1"` constant in pair.py; cache key includes it; live exit gate at sprint exit catches behavior drift. |
| API failure mid-review causes blank flag list | Per-pair try/except → keep Track 1 verdict on failure. CI test asserts pipeline still returns flags when mocked Claude raises. |
| KRP-C / 150 kVA cases are anecdotal — eval surface is shallow | Acknowledged in TDD known-limits. Sprint 6 adds per-class gold sets with broader pairing-error labels. |

---

## Self-review notes

- All 7 sections traced to user-approved choices during brainstorming.
- No "TBD" / "TODO" strings in spec body.
- Schema field types specified concretely (`str | None`, `bool`, `float`).
- Phase tags follow `phase-27.<N>-<slug>` convention.
- Final tag `v2.3-reranker`.
- Snapshot-equivalence guarantee restated in §4 (`use_llm_reranker=False` → bit-identical to v2.2).
- "Track 1 / Track 2" terminology stays internal (per Sprint 3 convention); reviewer-facing labels use "Rules" / "AI" / "Reranker".
