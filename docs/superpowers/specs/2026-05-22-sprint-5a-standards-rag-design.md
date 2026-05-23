# Sprint 5a — Standards-as-RAG (Curated Clause Registry) Design Spec

**Goal.** Every Track 2 flag carries cited reasoning naming the applicable standards clause + edition. Achieved via a curated YAML clause ontology + structured retrieval injected into the existing LLM judge's prompt. No new LLM call; no embedding store; no copyright exposure.

**Exit tag:** `v2.5-rag`. **PIVOT_PLAN reference:** Sprint 5 — Standards-as-RAG portion only (coupled-effect graph deferred to Sprint 5b).

---

## §1 Approach + Components

Curated YAML clause ontology + structured retrieval inside the existing LLM judge. When `use_llm_judge=True` (Sprint 4.5 default), the judge prompt receives a new "Applicable standards" section listing pre-curated clauses matched by the flag's `attribute_family` (and optionally `doc_class`). Judge cites them in rationale; structured citation list attaches to `Flag.cited_clauses`. No new LLM call; no embedding store; no copyright headache.

**New files:**

| Path | Responsibility |
|---|---|
| `data/standards/clauses.yaml` | ~10–20 seed clauses at ship; grows organically |
| `src/interlock/llm_pipeline/standards.py` | `load_clauses()` + `clauses_for()` + `merge_project_overrides()` + `to_citation()` |
| `src/interlock/llm_pipeline/schemas/clause.py` | `Clause` + `ClauseCitation` pydantic v2 models |
| `tests/llm_pipeline/schemas/test_clause.py` | Phase 29.1 schema validation |
| `tests/llm_pipeline/test_standards.py` | Phase 29.2 registry unit tests |
| `tests/real_world/test_standards_rag_live.py` | Phase 29.6 live exit-gate tests |
| `fixtures/projects/testproj/tolerances.yaml` | Phase 29.4 e2e test fixture |

**Modified:**

| Path | Change |
|---|---|
| `src/interlock/detect/mismatch.py` | `Flag` gains `cited_clauses: tuple[ClauseCitation, ...] = ()` |
| `src/interlock/detect/significance.py` | Judge prompt template gets "Applicable standards" section; `SignificanceJudgment` gains `cited_clause_ids: list[str] = []`; `apply_judgment_to_flag` resolves IDs → `ClauseCitation` |
| `src/interlock/pipeline.py` | New `project_id: str \| None = None` kwarg; passes to `judge()` |
| `src/interlock/ui/app.py` | Sidebar text input "Project ID (optional)"; 📜 chip in flag header; full citations list in expander; JSON export `cited_clauses` key; stage label refresh |

**Per-project override directory:** `fixtures/projects/<project_id>/tolerances.yaml`. Same schema as global; entries override global registry by `clause_id`. Project IDs are user-typed; non-existent path → no override, no error.

**Empty match path:** when zero clauses match a flag's family, the judge runs without the standards block — falls back to current behavior gracefully.

**Cost / latency:** $0 incremental (registry lookup is in-process; LLM judge call already happens). Prompt is ~200 tokens longer per flag; <$0.001 incremental per flag judged.

---

## §2 Schema + Registry Logic

### Schemas (`src/interlock/llm_pipeline/schemas/clause.py`)

```python
from pydantic import BaseModel, ConfigDict, Field


class Clause(BaseModel):
    """One curated clause entry from the YAML registry."""
    model_config = ConfigDict(frozen=True)
    clause_id: str = Field(min_length=1, max_length=64)
    edition_year: int = Field(ge=1900, le=2100)
    source_name: str = Field(min_length=1, max_length=200)
    applicable_families: list[str] = Field(min_length=1)
    applicable_doc_classes: list[str] = Field(default_factory=list)
    tolerance_band: float | None = None
    summary: str = Field(min_length=1, max_length=1000)


class ClauseCitation(BaseModel):
    """Subset of Clause carried on Flag.cited_clauses + JSON export."""
    model_config = ConfigDict(frozen=True)
    clause_id: str
    edition_year: int
    source_name: str
    summary: str
```

### YAML registry shape (`data/standards/clauses.yaml`)

```yaml
clauses:
  - clause_id: IEEE-C57.12.00-2015-5.4
    edition_year: 2015
    source_name: "IEEE C57.12.00-2015 §5.4 (Impedance Tolerance)"
    applicable_families: [impedance_pct]
    applicable_doc_classes: [equipment_spec, coordination_study]
    tolerance_band: 0.075
    summary: |
      Per IEEE C57.12.00-2015 §5.4, the impedance voltage of a two-winding
      transformer shall not differ from the specified value by more than ±7.5%.
      Deviations above this threshold materially affect downstream short-circuit
      duty and protection coordination.
```

Seed at ship: ~10 clauses covering `impedance_pct`, `fault_current_a/ka`, `transformer_rating_va`, `voltage_v/kv`, `motor_fla_a`, `relay_pickup_a`, `fuse_amps`. Most entries leave `applicable_doc_classes` empty (apply to all doc classes); specific where it matters.

### Registry module (`src/interlock/llm_pipeline/standards.py`)

```python
_CLAUSES_PATH = Path("data/standards/clauses.yaml")


def load_clauses(path: Path = _CLAUSES_PATH) -> list[Clause]:
    """Read + validate the YAML registry. mtime-cached.

    Missing file → empty list.
    YAML parse / pydantic validation failure → logged + empty list.
    Bad individual entry → dropped, others retained.
    """


def clauses_for(
    family: str,
    doc_class: str | None = None,
    project_id: str | None = None,
) -> list[Clause]:
    """Return clauses matching attribute_family + (optionally) doc_class.

    project_id triggers merge of fixtures/projects/<project_id>/tolerances.yaml
    if present; project entries override global by clause_id.
    """


def merge_project_overrides(
    base: list[Clause], project_id: str,
) -> list[Clause]:
    """Merge project-specific clauses on top of base by clause_id.

    Project entry with same clause_id replaces base entry; new entries append.
    Non-existent project path → return base unchanged.
    """


def to_citation(clause: Clause) -> ClauseCitation:
    """Project Clause → ClauseCitation (drops applicable_*, tolerance_band)."""
```

**In-memory index** built lazily on first `clauses_for()` call: `_FAMILY_INDEX: dict[str, list[Clause]]`. LRU cache keyed on (file path, file mtime, project_id).

### Judge integration (`src/interlock/detect/significance.py`)

**Prompt template gains a section** rendered only when matches exist:

```
## Applicable standards

When writing the rationale, cite clauses from this list when they ground
the engineering judgment. Reference by `source_name`. Do NOT cite clauses
that aren't on this list.

- [IEEE-C57.12.00-2015-5.4] IEEE C57.12.00-2015 §5.4 (Impedance Tolerance)
  Summary: ...

- [IEEE-242-2001-15.5] IEEE Std 242-2001 §15.5 (Available Fault Current)
  Summary: ...
```

**Response schema** (`SignificanceJudgment`) gains `cited_clause_ids: list[str] = []`. Judge selects which (if any) clauses it cited.

**Empty-match path:** when `clauses_for()` returns empty, the "Applicable standards" section is omitted from the prompt entirely. Judge runs unchanged. `Flag.cited_clauses` stays `()`.

**Cache key impact:** judge's diskcache key gets the matched clause IDs added so prompt edits invalidate correctly.

---

## §3 Pipeline Integration + Back-Compat

### `Flag` extension

```python
@dataclass(frozen=True)
class Flag:
    # ...existing fields including Sprint 4 rerank_rationale...
    cited_clauses: tuple[ClauseCitation, ...] = ()  # v2 Sprint 5a
```

`tuple[...] = ()` because dataclass is frozen; tuple is hashable + safe as default.

### Pipeline kwarg

```python
def review_two_documents_full(
    pdf_a, pdf_b, embed_fn,
    ...
    use_llm_judge: bool = True,
    classify_docs: bool = True,
    use_llm_extraction: bool = True,
    use_llm_reranker: bool = True,
    use_entity_grounding: bool = True,
    project_id: str | None = None,   # v2 Sprint 5a — NEW
) -> ReviewResult:
```

Forwarded to `judge()`:

```python
if use_llm_judge and flags:
    _stage("judge", "start")
    flags = [
        apply_judgment_to_flag(f, judge(f, project_id=project_id))
        for f in flags
    ]
    _stage("judge", "done")
```

### `apply_judgment_to_flag` enhancement

```python
from interlock.llm_pipeline.standards import load_clauses, to_citation

def apply_judgment_to_flag(flag: Flag, judgment: SignificanceJudgment) -> Flag:
    """As before, plus map judgment.cited_clause_ids → ClauseCitation tuple."""
    # ... existing rationale logic ...
    cited: tuple[ClauseCitation, ...] = ()
    if judgment.cited_clause_ids:
        by_id = {c.clause_id: c for c in load_clauses()}
        cited = tuple(
            to_citation(by_id[cid])
            for cid in judgment.cited_clause_ids
            if cid in by_id
        )
    return Flag(
        # ... existing fields ...
        cited_clauses=cited,
    )
```

Hallucinated clause IDs (judge returns something not in the registry) get silently filtered.

### Back-compat guarantees (CI-gated)

1. `use_llm_judge=False` → `Flag.cited_clauses == ()` for every flag. No registry load. Bit-identical to v2.4.
2. `use_llm_judge=True` + missing/empty registry → `Flag.cited_clauses == ()` for every flag. Judge runs without standards section.
3. `use_llm_judge=True` + matching clauses + mocked judge returning valid `cited_clause_ids` → `Flag.cited_clauses` contains resolved citations.
4. `use_llm_judge=True` + judge returns clause ID not in registry → silently filtered.
5. Sprint 4.5's snapshot tests stay green — new field defaults to `()` and existing tests don't check it.

### Stage callback

No new stage. `judge` stage row label updates to **"AI severity + standards citations"** — one-word copy refresh, no semantic change.

### Failure modes (all caught)

- `clauses.yaml` missing → empty list, no error.
- YAML parse error / pydantic validation error → log warning, empty list.
- Project-override file missing → base registry only.
- Judge returns hallucinated clause IDs → filtered silently.
- Judge response missing `cited_clause_ids` → pydantic default empty list.

---

## §4 UI Surface + JSON Export

### Sidebar — Project ID input

```python
project_id_input = st.text_input(
    "Project ID (optional)",
    value="",
    placeholder="e.g. AES-PALM-2025",
    help=(
        "If your project has its own tolerance overrides at "
        "fixtures/projects/<id>/tolerances.yaml, enter the ID here. "
        "Leave blank to use the global standards registry only."
    ),
)
project_id = project_id_input.strip() or None
```

Forwarded to the pipeline call alongside existing kwargs.

### Per-flag header chip

```python
def _standards_chip(flag: Any) -> str:
    """Return compact standards chip for the flag header.

    Most-cited clause's short form → ' · 📜 <short>'.
    Multiple cites → ' · 📜 <short> +N'.
    Empty list → ''.
    """
    cited = getattr(flag, "cited_clauses", ()) or ()
    if not cited:
        return ""
    first = cited[0]
    short = (first.source_name or "").split("§", 1)[0].strip().rstrip(",")
    if not short:
        short = first.clause_id
    if len(cited) > 1:
        return f" · 📜 {short} +{len(cited) - 1}"
    return f" · 📜 {short}"
```

Appended to header chain after `ent_chip`:

```python
std_chip = _standards_chip(f)
header = (
    f"{_SEVERITY[sev]['emoji']} **{f.parameter}** · "
    f"{dev_str} · confidence {f.confidence:.2f}"
    f"{pair_badge}{prov_badge}{ent_chip}{std_chip}{verdict_badge}"
)
```

### Per-flag expander — citations list

```python
cited = getattr(f, "cited_clauses", ()) or ()
if cited:
    st.markdown("**📜 Cited standards:**")
    for c in cited:
        st.markdown(
            f"- **{c.source_name}** ({c.edition_year})  \n"
            f"  _{c.summary}_"
        )
```

### JSON export keys

```python
"cited_clauses": [
    {
        "clause_id": c.clause_id,
        "edition_year": c.edition_year,
        "source_name": c.source_name,
        "summary": c.summary,
    }
    for c in (getattr(f, "cited_clauses", ()) or ())
],
```

### Stage label refresh

```python
"judge": "AI severity + standards citations",
```

---

## §5 TDD Phases (6 phases)

### Phase 29.1 — `Clause` + `ClauseCitation` schemas

- Tests `tests/llm_pipeline/schemas/test_clause.py` (~8): valid construction, kind/year/label bounds, frozen, `applicable_families` min-length, `to_citation()` projection.
- Implement: `src/interlock/llm_pipeline/schemas/clause.py`.
- **Tag:** `phase-29.1-clause-schemas`.

### Phase 29.2 — Registry module + YAML seed

- Tests `tests/llm_pipeline/test_standards.py` (~12): load, missing file, parse error, validation error per-entry drop, `clauses_for(family)`, doc_class filter, empty `applicable_doc_classes` = all, project override replace, project override append, missing project file = base unchanged, `to_citation()` correctness.
- Seed YAML: ~10 high-impact clauses (impedance_pct, fault_current_a/ka, transformer_rating_va, voltage_v/kv, motor_fla_a, relay_pickup_a, fuse_amps).
- Implement: `src/interlock/llm_pipeline/standards.py` with mtime cache.
- **Tag:** `phase-29.2-standards-registry`.

### Phase 29.3 — Judge integration + `Flag.cited_clauses`

- Tests `tests/detect/test_significance.py` (~6): prompt contains "Applicable standards" when matches exist, omits section when empty, hallucinated ID filtered, valid ID resolved, `apply_judgment_to_flag` preserves prior fields + adds cited_clauses, diskcache key includes matched clause IDs.
- Implement: extend `SignificanceJudgment` with `cited_clause_ids`; rewrite `judge()` to inject standards block; update `apply_judgment_to_flag`. Add `Flag.cited_clauses` field.
- **Tag:** `phase-29.3-judge-integration`.

### Phase 29.4 — Pipeline `project_id` kwarg + e2e tests

- Tests appended to `tests/e2e/test_pipeline_v2.py` (~4): `project_id=None` baseline, `project_id="testproj"` with fixture override, `project_id="nonexistent"` graceful, `use_llm_judge=False` + registry present → cited_clauses still `()`.
- Implement: `project_id` kwarg on `review_two_documents_full` + shim.
- Create fixture: `fixtures/projects/testproj/tolerances.yaml` with one override entry.
- **Tag:** `phase-29.4-pipeline-project-id`.

### Phase 29.5 — UI: Project ID input + 📜 chip + expander citations + JSON export

- Sidebar text input below toggles.
- `_standards_chip()` helper + header chain.
- Expander markdown block listing cited clauses.
- JSON export `cited_clauses` key.
- Stage label refresh.
- Manual smoke + compile/lint/mypy.
- **Tag:** `phase-29.5-rag-ui`.

### Phase 29.6 — Live exit gate + docs + sprint exit

- Tests `tests/real_world/test_standards_rag_live.py` (slow + needs_anthropic, 3 tests):
  1. `test_xfmr_impedance_flag_cites_ieee_c57_12_00` — Option 1 fixture %Z flag has ≥1 cited clause referencing IEEE C57.12.00.
  2. `test_fault_current_flag_cites_ieee_242` — Fault Current flag cites IEEE Std 242.
  3. `test_empty_registry_pathological_still_ships_flags` — monkeypatched `_CLAUSES_PATH` → tmp empty file; judge runs without citations; flags still ship; `cited_clauses == ()` everywhere.
- AUTHORSHIP entry + TDD known-limits.
- **Exit tag:** `v2.5-rag`.

---

## §6 Cost + Latency

| | Cold | Warm |
|---|---:|---:|
| Registry load (one-shot) | <50 ms | <5 ms (mtime cached) |
| Per-flag clause lookup | <1 ms | <1 ms |
| Judge prompt token delta | +~200 tokens / flag | $0 |
| Per-flag judge cost delta | +~$0.001 | $0 |
| Locked Option 1 fixture (~10 flags cold) | ~$0.01 added | $0 |

Within PIVOT_PLAN's $0.50–$3 envelope; effectively free incremental cost.

---

## §7 Risks + Mitigations

| Risk | Mitigation |
|---|---|
| Judge hallucinates clause IDs not in registry | Filtered silently in `apply_judgment_to_flag`; CI test gates the behavior. |
| Judge ignores supplied clauses and writes ungrounded rationale | Live exit gate (Phase 29.6) asserts ≥1 cited clause on the %Z and Fault Current canonical flags. |
| Curated paraphrases drift from actual standard text | `summary` is OUR paraphrase, not verbatim. Reviewer cross-checks `source_name + edition_year` against the original standard themselves. No copyright exposure. |
| Per-project override file gets out of sync | Each entry pydantic-validated on load; bad entries dropped + logged. |
| Registry grows large + lookup becomes slow | In-memory `{family → [Clause]}` index built once; O(1) lookup. 1000+ entries comfortable. |
| New parameter families ship flags before clause coverage | Empty-match path: judge runs without standards block; rationale unchanged; UI chip silent. Honest gap easy to identify via JSON export. |
| Sprint 5a copy reads like "RAG" in PIVOT_PLAN but ships as YAML lookup | AUTHORSHIP calls it "curated YAML clause ontology, retrieval via structured lookup at LLM-judge prompt time" — honest framing. Reviewer-facing UI says "Cited standards" — accurate either way. |

---

## Self-review notes

- All 7 sections trace to user-approved choices during brainstorming.
- No "TBD" / "TODO" strings in spec body.
- Type / identifier consistency:
  - `Clause` + `ClauseCitation` consistent across §1–§5.
  - `load_clauses()` / `clauses_for()` / `merge_project_overrides()` / `to_citation()` consistent.
  - `cited_clauses: tuple[ClauseCitation, ...] = ()` consistent on `Flag`.
  - `cited_clause_ids: list[str] = []` on `SignificanceJudgment`.
  - `project_id` kwarg consistent across pipeline + judge + UI.
  - `_NAMESPACE` / cache key pattern: judge's existing namespace; key includes matched clause IDs.
- Phase tags follow `phase-29.<N>-<slug>` convention.
- Final tag `v2.5-rag`.
- Snapshot-equivalence restated: `use_llm_judge=False` → `cited_clauses == ()` bit-identical to v2.4.
- Internal "Track 1/2 / Sprint N" terminology scrubbed from reviewer-facing copy (chip + expander + sidebar input).
