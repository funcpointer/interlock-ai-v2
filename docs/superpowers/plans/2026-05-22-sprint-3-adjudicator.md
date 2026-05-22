# Sprint 3 — Adjudicator + Provenance UX Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the reviewer-facing surface that makes the v2 hybrid pivot visible — each `Flag` gains a `provenance` label (`rule_only` / `llm_only` / `mixed_track` / `unknown`), the UI shows a silent-default-prominent-exception badge plus a sidebar filter, and the JSON export + SQLite `decision` table record track-of-origin. Tag exit as `v2.2-adjudicator`.

**Architecture:** Thin post-processing layer (`src/interlock/adjudicator.py`) runs after `detect_flags`. Pure Python function annotates each Flag in place using `dataclasses.replace`. No new LLM calls, no alignment changes, zero per-review cost. `Flag.provenance` defaults to `"unknown"` for hand-constructed flags; adjudicator overwrites with the right label when invoked through the pipeline.

**Tech Stack:** Python 3.12, dataclasses, pydantic (Sprint 2 schemas already present), Streamlit, pytest + pytest-mock, sqlite3 (stdlib), ruff + mypy --strict.

**Spec reference:** `docs/superpowers/specs/2026-05-22-sprint-3-adjudicator-design.md`

---

## File structure

**New files:**

| Path | Responsibility |
|---|---|
| `src/interlock/adjudicator.py` | `adjudicate_flags()` + `_classify_provenance()` pure functions |
| `tests/detect/test_provenance_field.py` | Phase 26.1 — `Flag.provenance` field back-compat tests |
| `tests/test_adjudicator.py` | Phase 26.2 — `adjudicate_flags` annotates all 4 combinations correctly |
| `tests/store/test_sqlite_provenance.py` | Phase 26.5 — schema migration idempotency tests |

**Modified files:**

| Path | What changes |
|---|---|
| `src/interlock/detect/mismatch.py` | `Flag` dataclass gains `provenance: Literal["rule_only", "llm_only", "mixed_track", "unknown"] = "unknown"` field |
| `src/interlock/pipeline.py` | Wires `adjudicate_flags()` after `detect_flags()` (runs always — pure annotation) |
| `src/interlock/ui/app.py` | Badge in flag header (silent on rule_only), sidebar filter radio, per-flag expanded view, JSON export gains `provenance` key |
| `data/interlock.schema.sql` | `ALTER TABLE decision ADD COLUMN provenance TEXT NOT NULL DEFAULT 'unknown';` (additive, idempotent) |
| `tests/e2e/test_pipeline_v2.py` | Adds Sprint 3 snapshot equivalence + provenance integration tests |
| `docs/AUTHORSHIP.md` | Sprint 3 section in existing per-phase format |
| `docs/TDD.md` | Known limits Sprint 3 entry (silent-default reasoning + per-flag provenance taxonomy) |

---

## Phase 26.1 — `Flag.provenance` field

### Task 1.1: Add `provenance` field + back-compat tests

**Files:**
- Create: `tests/detect/test_provenance_field.py`
- Modify: `src/interlock/detect/mismatch.py` (within the `Flag` dataclass)

- [ ] **Step 1: Write the failing test**

```python
# tests/detect/test_provenance_field.py
"""Sprint 3 — Flag.provenance field back-compat tests.

The field defaults to "unknown" so every existing test that constructs
Flag by hand keeps working. The adjudicator (Phase 26.2) overwrites
this default with the right label when invoked through the pipeline.
"""

from __future__ import annotations

from interlock.detect.mismatch import Flag
from interlock.extract.parameters import ParameterRecord


def _record(provenance: str = "regex") -> ParameterRecord:
    return ParameterRecord(
        doc_id="d", page=1, bbox=(0, 0, 100, 10), section=None,
        span_text="5.75%Z", name="%Z", raw_value="5.75 %",
        normalized_magnitude=0.0575, normalized_unit="dimensionless",
        provenance=provenance,  # type: ignore[arg-type]
    )


def _flag(provenance: str = "unknown") -> Flag:
    return Flag(
        parameter="%Z",
        a_record=_record(), b_record=_record(provenance="regex"),
        authoritative_doc_id="d", deviating_doc_id="d",
        confidence=1.0,
        rationale="test",
        authority_rule="MVP",
        severity="major",
        deviation_pct=10.0,
        attribute_family="impedance_pct",
        provenance=provenance,  # type: ignore[arg-type]
    )


def test_provenance_defaults_to_unknown() -> None:
    """No explicit provenance kwarg ⇒ field defaults to 'unknown'."""
    f = Flag(
        parameter="%Z",
        a_record=_record(), b_record=_record(),
        authoritative_doc_id="d", deviating_doc_id="d",
        confidence=1.0,
        rationale="test",
        authority_rule="MVP",
        severity="major",
        deviation_pct=10.0,
        attribute_family="impedance_pct",
    )
    assert f.provenance == "unknown"


def test_provenance_can_be_rule_only() -> None:
    assert _flag(provenance="rule_only").provenance == "rule_only"


def test_provenance_can_be_llm_only() -> None:
    assert _flag(provenance="llm_only").provenance == "llm_only"


def test_provenance_can_be_mixed_track() -> None:
    assert _flag(provenance="mixed_track").provenance == "mixed_track"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/detect/test_provenance_field.py -v`
Expected: All FAIL with `TypeError: __init__() got an unexpected keyword argument 'provenance'`.

- [ ] **Step 3: Add the field to Flag**

First read `src/interlock/detect/mismatch.py` to find the `@dataclass(frozen=True) class Flag` definition. Identify the end of the existing field list (likely after `pairing_confidence`). Add at the end:

```python
# src/interlock/detect/mismatch.py — Imports (add if not present)
from typing import Literal

# Within @dataclass(frozen=True) class Flag, append after the last field:
    # v2 Sprint 3 — provenance label derived from a_record.provenance +
    # b_record.provenance by adjudicate_flags(). Default "unknown" for
    # back-compat with hand-constructed Flags in tests; the adjudicator
    # overwrites with the right label when invoked through the pipeline.
    provenance: Literal["rule_only", "llm_only", "mixed_track", "unknown"] = "unknown"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/detect/test_provenance_field.py -v`
Expected: 4 passed.

- [ ] **Step 5: Full regression to confirm v1 still bit-identical**

Run: `uv run pytest --deselect tests/real_world -q`
Expected: 333 passed (v2.1 baseline) + 4 new = 337 passed.

- [ ] **Step 6: Lint + mypy**

Run: `uv run ruff check src/interlock/detect/mismatch.py tests/detect/test_provenance_field.py && uv run mypy src/interlock/detect/mismatch.py`
Expected: clean.

- [ ] **Step 7: Commit + tag**

```bash
git add src/interlock/detect/mismatch.py tests/detect/test_provenance_field.py
git commit -m "feat(detect): Flag.provenance field (default 'unknown' for back-compat)"
git tag phase-26.1-flag-provenance-field -m "Sprint 3 phase 1: Flag.provenance field with safe default"
git push origin main phase-26.1-flag-provenance-field
```

---

## Phase 26.2 — Adjudicator pure functions

### Task 2.1: `_classify_provenance` + `adjudicate_flags` + tests

**Files:**
- Create: `src/interlock/adjudicator.py`
- Create: `tests/test_adjudicator.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_adjudicator.py
"""Sprint 3 — adjudicator unit tests.

Pure function over a Flag list. No I/O, no LLM call, no alignment
state. Just label derivation from a_record.provenance + b_record.provenance.
"""

from __future__ import annotations

from dataclasses import replace

from interlock.detect.mismatch import Flag
from interlock.extract.parameters import ParameterRecord


def _record(provenance: str = "regex") -> ParameterRecord:
    return ParameterRecord(
        doc_id="d", page=1, bbox=(0, 0, 100, 10), section=None,
        span_text="5.75%Z", name="%Z", raw_value="5.75 %",
        normalized_magnitude=0.0575, normalized_unit="dimensionless",
        provenance=provenance,  # type: ignore[arg-type]
    )


def _flag(a_prov: str, b_prov: str) -> Flag:
    return Flag(
        parameter="%Z",
        a_record=_record(provenance=a_prov),
        b_record=_record(provenance=b_prov),
        authoritative_doc_id="d", deviating_doc_id="d",
        confidence=1.0,
        rationale="test",
        authority_rule="MVP",
        severity="major",
        deviation_pct=10.0,
        attribute_family="impedance_pct",
    )


def test_classify_provenance_both_regex_is_rule_only() -> None:
    from interlock.adjudicator import _classify_provenance
    assert _classify_provenance("regex", "regex") == "rule_only"


def test_classify_provenance_both_llm_is_llm_only() -> None:
    from interlock.adjudicator import _classify_provenance
    assert _classify_provenance("llm", "llm") == "llm_only"


def test_classify_provenance_regex_plus_llm_is_mixed_track() -> None:
    from interlock.adjudicator import _classify_provenance
    assert _classify_provenance("regex", "llm") == "mixed_track"
    assert _classify_provenance("llm", "regex") == "mixed_track"


def test_classify_provenance_none_is_unknown() -> None:
    from interlock.adjudicator import _classify_provenance
    assert _classify_provenance(None, "regex") == "unknown"
    assert _classify_provenance("regex", None) == "unknown"
    assert _classify_provenance(None, None) == "unknown"


def test_adjudicate_flags_annotates_rule_only_flag() -> None:
    from interlock.adjudicator import adjudicate_flags
    flags = [_flag("regex", "regex")]
    out = adjudicate_flags(flags)
    assert len(out) == 1
    assert out[0].provenance == "rule_only"


def test_adjudicate_flags_annotates_llm_only_flag() -> None:
    from interlock.adjudicator import adjudicate_flags
    out = adjudicate_flags([_flag("llm", "llm")])
    assert out[0].provenance == "llm_only"


def test_adjudicate_flags_annotates_mixed_track_flag() -> None:
    from interlock.adjudicator import adjudicate_flags
    out = adjudicate_flags([_flag("regex", "llm")])
    assert out[0].provenance == "mixed_track"


def test_adjudicate_flags_preserves_flag_order() -> None:
    from interlock.adjudicator import adjudicate_flags
    flags = [
        replace(_flag("regex", "regex"), parameter="A"),
        replace(_flag("llm", "llm"), parameter="B"),
        replace(_flag("regex", "llm"), parameter="C"),
    ]
    out = adjudicate_flags(flags)
    assert [f.parameter for f in out] == ["A", "B", "C"]
    assert [f.provenance for f in out] == ["rule_only", "llm_only", "mixed_track"]


def test_adjudicate_flags_preserves_other_fields() -> None:
    """All other Flag fields must pass through unchanged."""
    from interlock.adjudicator import adjudicate_flags
    f = _flag("regex", "llm")
    out = adjudicate_flags([f])
    assert out[0].parameter == f.parameter
    assert out[0].severity == f.severity
    assert out[0].confidence == f.confidence
    assert out[0].deviation_pct == f.deviation_pct
    assert out[0].rationale == f.rationale
    assert out[0].a_record is f.a_record  # same record object
    assert out[0].b_record is f.b_record


def test_adjudicate_flags_empty_input_returns_empty() -> None:
    from interlock.adjudicator import adjudicate_flags
    assert adjudicate_flags([]) == []
```

- [ ] **Step 2: Run; expected to fail**

Run: `uv run pytest tests/test_adjudicator.py -v`
Expected: 10 failures (`ModuleNotFoundError: interlock.adjudicator`).

- [ ] **Step 3: Implement the adjudicator**

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
    """Return new Flag list with provenance annotated per flag.

    Order preserved; all other Flag fields pass through unchanged.
    Empty list → empty list.
    """
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
    """Classify a flag's provenance from its two record provenances.

    Returns one of: rule_only, llm_only, mixed_track, unknown.
    """
    if a_prov is None or b_prov is None:
        return "unknown"
    if a_prov == "regex" and b_prov == "regex":
        return "rule_only"
    if a_prov == "llm" and b_prov == "llm":
        return "llm_only"
    return "mixed_track"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_adjudicator.py -v`
Expected: 10 passed.

- [ ] **Step 5: Lint + mypy**

Run: `uv run ruff check src/interlock/adjudicator.py tests/test_adjudicator.py && uv run mypy src/interlock/adjudicator.py`
Expected: clean.

- [ ] **Step 6: Commit + tag**

```bash
git add src/interlock/adjudicator.py tests/test_adjudicator.py
git commit -m "feat(adjudicator): adjudicate_flags() with 3-state provenance taxonomy"
git tag phase-26.2-adjudicator -m "Sprint 3 phase 2: pure adjudicator + 10 unit tests"
git push origin main phase-26.2-adjudicator
```

---

## Phase 26.3 — Pipeline integration

### Task 3.1: Wire adjudicator after `detect_flags` + snapshot equivalence test

**Files:**
- Modify: `src/interlock/pipeline.py`
- Modify: `tests/e2e/test_pipeline_v2.py` (append tests)

- [ ] **Step 1: Write the failing tests**

Append to `tests/e2e/test_pipeline_v2.py`:

```python
# tests/e2e/test_pipeline_v2.py (append at end)

# --- Sprint 3: adjudicator pipeline integration --------------------------


def test_v1_snapshot_equivalence_all_flags_are_rule_only() -> None:
    """When both tracks off, every flag must be annotated 'rule_only' —
    Sprint 3's promise that v1.5 snapshot equivalence still holds."""
    from interlock.pipeline import review_two_documents_full

    result = review_two_documents_full(
        DOC_A, DOC_B,
        embed_fn=_trivial_embedder,
        classify_docs=False,
        use_llm_extraction=False,
    )
    assert result.flags, "expected non-zero baseline flags from Option 1 fixture"
    for f in result.flags:
        assert f.provenance == "rule_only", (
            f"v1 snapshot broken: flag {f.parameter} got provenance "
            f"{f.provenance!r}, expected 'rule_only'"
        )


def test_pipeline_annotates_provenance_when_llm_extraction_on(mocker) -> None:  # type: ignore[no-untyped-def]
    """With LLM extraction enabled, the pipeline still produces a flag
    list with provenance populated. (Specific labels depend on which
    records the aligner pairs — verified in adjudicator unit tests.)"""
    from interlock.pipeline import review_two_documents_full

    fake = '{"claims":[],"page":1,"notes":""}'
    mocker.patch(
        "interlock.llm_pipeline.extract._call_claude_extract",
        return_value=_fake_extract_response(fake),
    )
    result = review_two_documents_full(
        DOC_A, DOC_B,
        embed_fn=_trivial_embedder,
        classify_docs=False,
        use_llm_extraction=True,
    )
    for f in result.flags:
        # The field must be one of the four enumerated values, never None.
        assert f.provenance in {"rule_only", "llm_only", "mixed_track", "unknown"}


def test_adjudicator_runs_unconditionally() -> None:
    """Even with both tracks off — i.e. the v1.5 path — every flag should
    have provenance set to something (not the default 'unknown')."""
    from interlock.pipeline import review_two_documents_full

    result = review_two_documents_full(
        DOC_A, DOC_B,
        embed_fn=_trivial_embedder,
        classify_docs=False,
        use_llm_extraction=False,
    )
    for f in result.flags:
        assert f.provenance != "unknown", (
            "pipeline must annotate provenance for every flag"
        )
```

- [ ] **Step 2: Run; expected to fail (adjudicator not wired yet)**

Run: `uv run pytest tests/e2e/test_pipeline_v2.py::test_v1_snapshot_equivalence_all_flags_are_rule_only -v`
Expected: FAIL — flags have `provenance="unknown"` because the pipeline doesn't call the adjudicator.

- [ ] **Step 3: Wire the adjudicator into the pipeline**

Read `src/interlock/pipeline.py` to find the existing `detect_flags()` call (it's inside `_stage("detect", "start") ... _stage("detect", "done")`).

Add the adjudicator call immediately after the stage closes — and BEFORE the `use_llm_judge` block (so the judge sees provenance annotations):

```python
# src/interlock/pipeline.py — locate this block:
_stage("detect", "start")
flags = detect_flags(combined, suppress_info=suppress_info)
_stage("detect", "done")

# Add immediately after the closing _stage:
# v2 Sprint 3: annotate provenance. Pure function; zero cost; runs always.
from interlock.adjudicator import adjudicate_flags
flags = adjudicate_flags(flags)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/e2e/test_pipeline_v2.py -v`
Expected: all v2 tests still pass + 3 new Sprint 3 tests pass.

- [ ] **Step 5: Full regression**

Run: `uv run pytest --deselect tests/real_world -q`
Expected: 333 (v2.1) + 4 (26.1) + 10 (26.2) + 3 (26.3) = 350 passed.

- [ ] **Step 6: Lint + mypy**

Run: `uv run ruff check src/interlock/pipeline.py tests/e2e/test_pipeline_v2.py && uv run mypy src/interlock/pipeline.py`
Expected: clean.

- [ ] **Step 7: Commit + tag**

```bash
git add src/interlock/pipeline.py tests/e2e/test_pipeline_v2.py
git commit -m "feat(pipeline): wire adjudicate_flags() after detect_flags()"
git tag phase-26.3-adjudicator-pipeline -m "Sprint 3 phase 3: pipeline integration + v1.5 snapshot equivalence"
git push origin main phase-26.3-adjudicator-pipeline
```

---

## Phase 26.4 — UI badge + sidebar filter + per-flag detail + JSON export

### Task 4.1: Sidebar filter radio

**Files:**
- Modify: `src/interlock/ui/app.py`

- [ ] **Step 1: Locate the existing sidebar block**

Read `src/interlock/ui/app.py` and search for the `classify_docs = st.toggle(` line (Sprint 1 toggle). The Sprint 3 filter goes in a NEW sidebar section AFTER the existing sliders + toggles but BEFORE the `st.divider()` that precedes the "How to read a flag" expander.

- [ ] **Step 2: Add the radio + caption**

In `src/interlock/ui/app.py`, after the threshold slider (locate via `threshold = st.slider`) and before the divider+expander, insert:

```python
    st.divider()

    # --- v2 Sprint 3: provenance filter ---------------------------------

    track_filter = st.radio(
        "Filter by track",
        options=("All", "Deterministic only", "AI-only", "Hybrid sources"),
        index=0,
        help=(
            "Narrow the visible flag list by which track(s) contributed. "
            "Both Track 1 (regex) and Track 2 (LLM) always run when "
            "enabled in the upper sidebar — this filter only changes "
            "what you SEE, not what gets computed."
        ),
    )
    st.caption(
        "⚙ Deterministic = rules found both sides · "
        "🧠 AI-only = LLM found both sides · "
        "🔀 Hybrid sources = rules + LLM, one side each"
    )
```

- [ ] **Step 3: Map the radio value to provenance set**

Below the radio block, add a small helper (after sidebar context closes):

```python
# Just after `with st.sidebar:` block closes, in the module-level scope.
_TRACK_FILTER_MAP: dict[str, set[str]] = {
    "All": {"rule_only", "llm_only", "mixed_track", "unknown"},
    "Deterministic only": {"rule_only"},
    "AI-only": {"llm_only"},
    "Hybrid sources": {"mixed_track"},
}
```

- [ ] **Step 4: Filter the flags before rendering**

Search for the line `above = [f for f in flags if f.confidence >= threshold]` (the existing severity-threshold filter). Update it to also filter on provenance:

```python
# v2 Sprint 3: apply track filter as well as confidence threshold
_allowed_prov = _TRACK_FILTER_MAP.get(track_filter, _TRACK_FILTER_MAP["All"])
above = [
    f for f in flags
    if f.confidence >= threshold and f.provenance in _allowed_prov
]
below = [
    f for f in flags
    if f.confidence < threshold and f.provenance in _allowed_prov
]
```

- [ ] **Step 5: Compile check + manual smoke**

```bash
uv run python -c "import py_compile; py_compile.compile('src/interlock/ui/app.py', doraise=True); print('OK')"
uv run ruff check src/interlock/ui/app.py
uv run mypy src/interlock/ui/app.py
```

Expected: OK + clean. Then optionally run `uv run streamlit run src/interlock/ui/app.py` and manually verify the radio renders + filters work.

- [ ] **Step 6: Commit**

```bash
git add src/interlock/ui/app.py
git commit -m "feat(ui): sidebar track-filter radio (All / Deterministic / AI-only / Hybrid sources)"
```

---

### Task 4.2: Provenance badge in flag header + per-flag detail

**Files:**
- Modify: `src/interlock/ui/app.py`

- [ ] **Step 1: Locate the flag header construction**

Find the block that builds `header` for the per-flag `st.expander`. It already includes severity emoji, parameter, deviation, confidence, and the `⚠️ weak pair` badge (Phase 19 pattern). The provenance badge goes next to weak-pair.

- [ ] **Step 2: Add provenance-badge helper at module level**

Add near the top of `src/interlock/ui/app.py` (after `_SEVERITY` dict, near where other module-level helpers live):

```python
def _provenance_badge(provenance: str) -> str:
    """Return the reviewer-facing badge text for a flag's provenance, or
    empty string for silent default + unknown."""
    if provenance == "llm_only":
        return " · 🧠 AI-only"
    if provenance == "mixed_track":
        return " · 🔀 Hybrid sources"
    # rule_only + unknown both silent — eye drawn to exceptions only
    return ""
```

- [ ] **Step 3: Append the badge to the header**

Find the line that constructs `header = (...)` in the flag-rendering loop. Update to append the provenance badge:

```python
# Before:
header = (
    f"{_SEVERITY[sev]['emoji']} **{f.parameter}** · "
    f"{dev_str} · confidence {f.confidence:.2f}"
    f"{pair_badge}{verdict_badge}"
)

# After (append _provenance_badge call to the end):
prov_badge = _provenance_badge(getattr(f, "provenance", "unknown"))
header = (
    f"{_SEVERITY[sev]['emoji']} **{f.parameter}** · "
    f"{dev_str} · confidence {f.confidence:.2f}"
    f"{pair_badge}{prov_badge}{verdict_badge}"
)
```

- [ ] **Step 4: Add per-flag detail line in expander**

Find the existing `cap = (...)` line inside the per-flag expander body (where Attribute family + pairing_confidence are shown). Append a conditional provenance line:

```python
# After the existing cap = (...) f-string but BEFORE the if weak_pair: cap += ... block,
# add this new conditional:

prov = getattr(f, "provenance", "unknown")
if prov == "llm_only":
    cap += (
        " · Track provenance: 🧠 AI-only — both sides extracted by the LLM layer "
        "(Sprint 2)"
    )
elif prov == "mixed_track":
    a_prov_human = "Rules" if f.a_record.provenance == "regex" else "AI"
    b_prov_human = "Rules" if f.b_record.provenance == "regex" else "AI"
    cap += (
        f" · Track provenance: 🔀 Hybrid — Doc A={a_prov_human} · "
        f"Doc B={b_prov_human}. Verify these two records describe the "
        f"same physical parameter."
    )
# rule_only + unknown → no extra line (clean default)
```

- [ ] **Step 5: Compile + lint check**

```bash
uv run python -c "import py_compile; py_compile.compile('src/interlock/ui/app.py', doraise=True); print('OK')"
uv run ruff check src/interlock/ui/app.py
uv run mypy src/interlock/ui/app.py
```

Expected: OK + clean.

- [ ] **Step 6: Commit**

```bash
git add src/interlock/ui/app.py
git commit -m "feat(ui): provenance badge in flag header + per-flag track detail (silent on rule_only)"
```

---

### Task 4.3: JSON export gains `provenance` key

**Files:**
- Modify: `src/interlock/ui/app.py`

- [ ] **Step 1: Locate the Accept button's session_state.decisions[fid] = {...} assignment**

In `src/interlock/ui/app.py`, the Accept button captures the flag's metadata into a dict for JSON export. Find that dict literal.

- [ ] **Step 2: Add `provenance` key**

Update the dict to include the provenance field:

```python
# Before:
st.session_state["decisions"][fid] = {
    "verdict": "accepted",
    "parameter": f.parameter,
    "severity": sev,
    "deviation_pct": deviation,
    "confidence": f.confidence,
    "rationale": f.rationale,
    "attribute_family": attr_family,
    "authority_rule": f.authority_rule,
    "doc_a_page": f.a_record.page,
    "doc_b_page": f.b_record.page,
    "doc_a_value": f.a_record.raw_value,
    "doc_b_value": f.b_record.raw_value,
}

# After (append provenance key at the end):
st.session_state["decisions"][fid] = {
    "verdict": "accepted",
    "parameter": f.parameter,
    "severity": sev,
    "deviation_pct": deviation,
    "confidence": f.confidence,
    "rationale": f.rationale,
    "attribute_family": attr_family,
    "authority_rule": f.authority_rule,
    "doc_a_page": f.a_record.page,
    "doc_b_page": f.b_record.page,
    "doc_a_value": f.a_record.raw_value,
    "doc_b_value": f.b_record.raw_value,
    "provenance": getattr(f, "provenance", "unknown"),  # v2 Sprint 3
}
```

- [ ] **Step 3: Compile + lint check**

```bash
uv run python -c "import py_compile; py_compile.compile('src/interlock/ui/app.py', doraise=True); print('OK')"
uv run ruff check src/interlock/ui/app.py
uv run mypy src/interlock/ui/app.py
```

Expected: OK + clean.

- [ ] **Step 4: Commit + tag (closes Phase 26.4)**

```bash
git add src/interlock/ui/app.py
git commit -m "feat(ui): JSON export gains provenance key per accepted flag"
git tag phase-26.4-adjudicator-ui -m "Sprint 3 phase 4: UI badges + filter + per-flag detail + JSON export"
git push origin main phase-26.4-adjudicator-ui
```

---

## Phase 26.5 — SQLite schema migration + docs + sprint exit

### Task 5.1: Schema migration

**Files:**
- Modify: `data/interlock.schema.sql`
- Create: `tests/store/test_sqlite_provenance.py`

- [ ] **Step 1: Read existing schema**

Read `data/interlock.schema.sql` to understand the existing `decision` table definition (Phase 14). Note: it uses `CREATE TABLE IF NOT EXISTS ...` for idempotency.

- [ ] **Step 2: Write the failing tests**

```python
# tests/store/test_sqlite_provenance.py
"""Sprint 3 — decision.provenance column migration.

Schema migration is additive. Existing rows get the default value
'unknown'. Running apply_schema twice is idempotent (the ALTER TABLE
is guarded inside the migration logic).
"""

from __future__ import annotations

import sqlite3
from pathlib import Path


def _apply_schema_twice(tmp_path: Path) -> Path:
    """Helper: apply the v2 schema twice to verify idempotency."""
    db_path = tmp_path / "test.db"
    schema = Path("data/interlock.schema.sql").read_text(encoding="utf-8")
    with sqlite3.connect(db_path) as conn:
        conn.executescript(schema)
        conn.commit()
        # Second application — must not raise.
        conn.executescript(schema)
        conn.commit()
    return db_path


def test_decision_table_has_provenance_column(tmp_path: Path) -> None:
    db = _apply_schema_twice(tmp_path)
    with sqlite3.connect(db) as conn:
        cur = conn.execute("PRAGMA table_info(decision)")
        cols = {row[1] for row in cur.fetchall()}
    assert "provenance" in cols


def test_decision_provenance_defaults_to_unknown(tmp_path: Path) -> None:
    db = _apply_schema_twice(tmp_path)
    with sqlite3.connect(db) as conn:
        # Insert a row without specifying provenance — should default.
        conn.execute(
            "INSERT INTO decision (fixture_pair_id, flag_id, verdict) "
            "VALUES ('p1', 'f1', 'accepted')"
        )
        conn.commit()
        cur = conn.execute("SELECT provenance FROM decision WHERE flag_id='f1'")
        row = cur.fetchone()
    assert row is not None
    assert row[0] == "unknown"


def test_apply_schema_idempotent(tmp_path: Path) -> None:
    """Running the migration twice must not raise. Already exercised by
    the _apply_schema_twice helper — this test just makes the assertion
    explicit."""
    db = _apply_schema_twice(tmp_path)
    assert db.exists()


def test_decision_provenance_accepts_known_values(tmp_path: Path) -> None:
    """All four taxonomy values can be inserted and read back."""
    db = _apply_schema_twice(tmp_path)
    with sqlite3.connect(db) as conn:
        for i, prov in enumerate(["rule_only", "llm_only", "mixed_track", "unknown"]):
            conn.execute(
                "INSERT INTO decision (fixture_pair_id, flag_id, verdict, provenance) "
                "VALUES (?, ?, 'accepted', ?)",
                (f"p{i}", f"f{i}", prov),
            )
        conn.commit()
        cur = conn.execute("SELECT flag_id, provenance FROM decision ORDER BY flag_id")
        rows = dict(cur.fetchall())
    assert rows == {
        "f0": "rule_only",
        "f1": "llm_only",
        "f2": "mixed_track",
        "f3": "unknown",
    }
```

- [ ] **Step 3: Run; expected to fail (column doesn't exist yet)**

Run: `uv run pytest tests/store/test_sqlite_provenance.py -v`
Expected: 4 failures (column missing).

- [ ] **Step 4: Apply the schema migration**

Read `data/interlock.schema.sql` and find the `CREATE TABLE IF NOT EXISTS decision (` block. Add a guarded ALTER right after the CREATE block (the apply_schema executescript runs both):

```sql
-- data/interlock.schema.sql — append after the existing CREATE TABLE IF NOT EXISTS decision (...) block

-- v2 Sprint 3: add provenance column to decision table.
-- Idempotent: PRAGMA + INSERT INTO sqlite_master is the safe pattern but
-- sqlite3 doesn't support `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`.
-- We use a try/catch-style: an UPDATE that no-ops if the column exists,
-- combined with the trigger of creating a temp view that depends on the
-- new column being present.
--
-- Simplest safe pattern: wrap in a no-op CREATE/DROP trigger that
-- references the column only when it exists. SQLite executescript
-- treats statement-by-statement: if ALTER fails (column already there),
-- the rest still applies.
--
-- For now, use the simplest approach: a stored proc isn't available in
-- pure SQLite. The cleanest portable approach is:
--   1. Detect column existence at runtime in Python and ALTER if missing.
--
-- Migrating to Python-side migration logic in src/interlock/store/sqlite.py:
```

Actually — since `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` isn't supported in SQLite, the cleanest path is to handle the migration in Python. Update the existing `apply_schema()` function:

Read `src/interlock/store/sqlite.py` to find the `apply_schema()` function. Add a post-step that checks for the column and adds it if missing:

```python
# src/interlock/store/sqlite.py — within apply_schema() or after its
# executescript call, append:

def _ensure_decision_provenance_column(conn: sqlite3.Connection) -> None:
    """v2 Sprint 3 — add decision.provenance column if missing. Idempotent."""
    cur = conn.execute("PRAGMA table_info(decision)")
    cols = {row[1] for row in cur.fetchall()}
    if "provenance" not in cols:
        conn.execute(
            "ALTER TABLE decision ADD COLUMN provenance TEXT NOT NULL "
            "DEFAULT 'unknown'"
        )
        conn.commit()


# In apply_schema(), after the executescript that loads the .sql file,
# call _ensure_decision_provenance_column(conn).
```

- [ ] **Step 5: Update tests to call apply_schema (not raw executescript)**

Edit `tests/store/test_sqlite_provenance.py` to use the project's `apply_schema()` helper instead of raw `executescript`:

```python
# tests/store/test_sqlite_provenance.py — replace _apply_schema_twice helper

import sqlite3
from pathlib import Path

from interlock.store.sqlite import apply_schema


def _apply_schema_twice(tmp_path: Path) -> Path:
    """Apply the v2 schema twice to verify idempotency."""
    db_path = tmp_path / "test.db"
    with sqlite3.connect(db_path) as conn:
        apply_schema(conn)
        apply_schema(conn)  # Second application — must not raise.
    return db_path
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/store/test_sqlite_provenance.py -v`
Expected: 4 passed.

- [ ] **Step 7: Full regression**

Run: `uv run pytest --deselect tests/real_world -q`
Expected: 350 + 4 new = 354 passed.

- [ ] **Step 8: Lint + mypy**

Run: `uv run ruff check src/interlock/store/sqlite.py tests/store/test_sqlite_provenance.py && uv run mypy src/interlock/store/sqlite.py`
Expected: clean.

- [ ] **Step 9: Commit + tag**

```bash
git add src/interlock/store/sqlite.py tests/store/test_sqlite_provenance.py data/interlock.schema.sql
git commit -m "feat(store): decision.provenance column via idempotent Python migration"
git tag phase-26.5-adjudicator-schema -m "Sprint 3 phase 5: SQLite schema migration for decision.provenance"
git push origin main phase-26.5-adjudicator-schema
```

---

### Task 5.2: Docs updates + sprint exit tag

**Files:**
- Modify: `docs/AUTHORSHIP.md`
- Modify: `docs/TDD.md`

- [ ] **Step 1: AUTHORSHIP entry**

Read `docs/AUTHORSHIP.md` to find the existing Sprint-by-Sprint entries (Sprint 1 + Sprint 2). Insert a new Sprint 3 entry following the same per-phase format above the existing Phase 23 entry:

```markdown
<!-- docs/AUTHORSHIP.md — insert after the Sprint 2 (v2) section -->

## Sprint 3 (v2) — Adjudicator + Provenance UX

Shipped via 5 phase tags (`phase-26.1-flag-provenance-field` →
`phase-26.5-adjudicator-schema`) on top of `v2.1-llm-extraction`. Exit
tag: `v2.2-adjudicator`.

**Components landed:**
- `src/interlock/detect/mismatch.py` — `Flag` gains
  `provenance: Literal["rule_only", "llm_only", "mixed_track", "unknown"] = "unknown"`
- `src/interlock/adjudicator.py` — `adjudicate_flags()` pure post-
  processing function + `_classify_provenance()` taxonomy logic
- `src/interlock/pipeline.py` — adjudicator wired after `detect_flags()`;
  runs always (pure annotation, zero cost)
- `src/interlock/ui/app.py` — sidebar track-filter radio
  (All / Deterministic only / AI-only / Hybrid sources); provenance
  badge in flag header (silent on `rule_only`, prominent
  `🧠 AI-only` / `🔀 Hybrid sources` on exceptions); per-flag expanded
  view shows track detail only on non-default; JSON export gains
  `provenance` key per accepted flag
- `src/interlock/store/sqlite.py` + `data/interlock.schema.sql` —
  decision table gains `provenance` column via idempotent Python-side
  migration (sqlite3 doesn't support `ALTER TABLE ... ADD COLUMN IF
  NOT EXISTS`; we PRAGMA-check then ALTER as needed)

**UX revised twice during brainstorming.** Final design uses the
silent-default + prominent-exception pattern (mirrors Phase 19's
`⚠️ weak pair` badge). Internal "Track 1 / Track 2" terminology never
leaks to reviewer-facing labels.

**Cost delta:** $0 dev spend, $0 per-review delta. Sprint 3 is the
cheapest sprint of the v2 plan.

**Test surface delta:** +21 tests (4 Flag field + 10 adjudicator unit
+ 3 pipeline integration + 4 SQLite schema). Total v2 test count at
`v2.2-adjudicator`: 354 passing + the existing live-API slow-marked
suites.

**Honest scope statement.** Sprint 3 ships the labeling. It does NOT
detect "both tracks independently agreed on the same fact" — that
case requires running alignment twice or detecting duplicate records,
both deferred to Sprint 4+. The 3-state taxonomy (rule_only / llm_only
/ mixed_track) reflects what the pipeline's union-merge architecture
actually produces.
```

- [ ] **Step 2: TDD known limits entry**

Read `docs/TDD.md` to find the existing `## Known limits` section. Append a Sprint 3 sub-section after the existing Sprint 1 + Sprint 2 entries:

```markdown
<!-- docs/TDD.md — append in the Known limits section -->

### Sprint 3 (v2) — Adjudicator + provenance UX

**Architecture that generalises:**
- 3-state provenance taxonomy + `unknown` default (back-compat-safe)
- Pure post-processing adjudicator (zero cost, trivially testable)
- Silent-default + prominent-exception badge pattern (reviewer's eye
  drawn to exceptions only)
- Additive schema evolution (`ALTER TABLE ... ADD COLUMN ... DEFAULT
  ...`) via Python-side guarded migration

**Heuristics + scope deliberately limited in Sprint 3:**
- Does NOT detect "both tracks independently agreed" (`both` label).
  Phase 19's alignment gates suppress duplicate records before they
  reach the flag layer, so an organic "both" never forms. Detecting
  it requires running alignment twice or matching duplicate flags
  across runs — deferred to Sprint 4+ pairing reranker work where the
  duplicate-pair problem is already on the table.
- `mixed_track` flags can occur for two reasons: (1) one track found
  the records that paired across docs, or (2) the same fact exists in
  both tracks but alignment picked one record from each track to form
  the pair. Sprint 3 doesn't distinguish these — the badge is "look
  closer" either way.
- Sidebar filter narrows the *visible* flag list but doesn't change
  what's computed. Reviewer can switch back to "All" any time without
  re-running the pipeline.
- Per-flag detail line uses "Rules" / "AI" as the reviewer-facing
  labels for `regex` / `llm`. Internal taxonomy stays unexposed.
```

- [ ] **Step 3: Run full regression to confirm nothing broke**

Run: `uv run pytest --deselect tests/real_world -q`
Expected: 354 passed.

- [ ] **Step 4: Commit docs + sprint exit tag**

```bash
git add docs/AUTHORSHIP.md docs/TDD.md
git commit -m "docs(sprint3): AUTHORSHIP per-phase entry + TDD known-limits"
git tag v2.2-adjudicator -m "v2.2 — adjudicator + provenance UX. Track-of-origin visible per flag. v1.5 snapshot equivalence intact. 354 tests passing."
git push origin main v2.2-adjudicator
```

---

## Self-review checklist (run before merge)

- [ ] Every spec section §1-§7 traces to at least one task above
- [ ] No "TBD" / "TODO" / "implement later" strings in the plan
- [ ] Every code block specifies a complete, runnable change
- [ ] Tag names follow the `phase-26.<N>-<slug>` convention from the spec
- [ ] Final tag is `v2.2-adjudicator`
- [ ] v1.5 snapshot equivalence test exists (Task 3.1)
- [ ] Anti-jargon principle enforced (no "Track 1/2" in reviewer UI)
- [ ] Schema migration is idempotent (Task 5.1 explicit test)
- [ ] Honest-scope disclosure shipped in `docs/TDD.md` (Task 5.2)
