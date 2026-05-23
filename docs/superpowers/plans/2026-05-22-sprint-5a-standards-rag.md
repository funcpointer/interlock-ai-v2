# Sprint 5a — Standards-as-RAG (Curated YAML Clause Registry) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the curated standards-clause registry + structured retrieval into the LLM judge prompt so every Track 2 flag carries cited reasoning naming the applicable clause + edition.

**Architecture:** Hand-curated `data/standards/clauses.yaml` loaded via pydantic validation + in-memory `{family → [Clause]}` index. The existing LLM judge (`detect/significance.py`) gets a new "Applicable standards" block in its user prompt rendered only when matches exist. The judge's response model gains `cited_clause_ids: list[str]`. `apply_judgment_to_flag()` resolves those IDs → `ClauseCitation` tuples on `Flag.cited_clauses`. Per-project override via `fixtures/projects/<id>/tolerances.yaml`. No new LLM call; no embedding store.

**Tech Stack:** Python 3.12, pyyaml, Pydantic v2, anthropic SDK (existing), Streamlit, pytest + pytest-mock, ruff + mypy --strict.

**Spec reference:** `docs/superpowers/specs/2026-05-22-sprint-5a-standards-rag-design.md`

---

## File structure

**New files:**

| Path | Responsibility |
|---|---|
| `src/interlock/llm_pipeline/schemas/clause.py` | `Clause` + `ClauseCitation` pydantic v2 models |
| `src/interlock/llm_pipeline/standards.py` | `load_clauses()` + `clauses_for()` + `merge_project_overrides()` + `to_citation()` |
| `data/standards/clauses.yaml` | ~10 seed clause entries at ship |
| `tests/llm_pipeline/schemas/test_clause.py` | Phase 29.1 schema validation tests |
| `tests/llm_pipeline/test_standards.py` | Phase 29.2 registry unit tests |
| `fixtures/projects/testproj/tolerances.yaml` | Phase 29.4 test fixture |
| `tests/real_world/test_standards_rag_live.py` | Phase 29.6 slow + needs_anthropic exit gate |

**Modified:**

| Path | Change |
|---|---|
| `src/interlock/detect/mismatch.py` | `Flag` gains `cited_clauses: tuple[ClauseCitation, ...] = ()` |
| `src/interlock/detect/significance.py` | `SignificanceJudgment` gains `cited_clause_ids`; user block builder injects standards section when matches exist; `judge()` accepts `project_id` kwarg; cache payload includes matched clause IDs; `apply_judgment_to_flag` resolves IDs to citations |
| `src/interlock/pipeline.py` | New `project_id: str \| None = None` kwarg on `review_two_documents_full` + shim; forwards to `judge()` |
| `src/interlock/ui/app.py` | Sidebar "Project ID (optional)" text input; `_standards_chip()` helper; expander citations block; JSON export `cited_clauses` key; stage label "AI severity + standards citations" |
| `tests/e2e/test_pipeline_v2.py` | 4 new Sprint 5a tests |
| `docs/AUTHORSHIP.md` + `docs/TDD.md` | Sprint 5a entries |

---

## Phase 29.1 — `Clause` + `ClauseCitation` schemas

### Task 1.1: Schema + validation tests

**Files:**
- Create: `src/interlock/llm_pipeline/schemas/clause.py`
- Create: `tests/llm_pipeline/schemas/test_clause.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/llm_pipeline/schemas/test_clause.py
"""Sprint 5a — Clause + ClauseCitation schema validation tests."""

from __future__ import annotations

import pytest
from pydantic import ValidationError


def test_clause_constructs_with_valid_fields() -> None:
    from interlock.llm_pipeline.schemas.clause import Clause
    c = Clause(
        clause_id="IEEE-C57.12.00-2015-5.4",
        edition_year=2015,
        source_name="IEEE C57.12.00-2015 §5.4 (Impedance Tolerance)",
        applicable_families=["impedance_pct"],
        applicable_doc_classes=["equipment_spec"],
        tolerance_band=0.075,
        summary="Per IEEE C57.12.00-2015 §5.4, ±7.5% impedance tolerance.",
    )
    assert c.clause_id == "IEEE-C57.12.00-2015-5.4"
    assert c.edition_year == 2015
    assert "impedance_pct" in c.applicable_families
    assert c.tolerance_band == 0.075


def test_clause_year_out_of_range_rejected() -> None:
    from interlock.llm_pipeline.schemas.clause import Clause
    with pytest.raises(ValidationError):
        Clause(
            clause_id="X", edition_year=1800, source_name="X",
            applicable_families=["x"], summary="X",
        )
    with pytest.raises(ValidationError):
        Clause(
            clause_id="X", edition_year=2200, source_name="X",
            applicable_families=["x"], summary="X",
        )


def test_clause_empty_applicable_families_rejected() -> None:
    from interlock.llm_pipeline.schemas.clause import Clause
    with pytest.raises(ValidationError):
        Clause(
            clause_id="X", edition_year=2020, source_name="X",
            applicable_families=[], summary="X",
        )


def test_clause_doc_classes_defaults_empty() -> None:
    from interlock.llm_pipeline.schemas.clause import Clause
    c = Clause(
        clause_id="X", edition_year=2020, source_name="X",
        applicable_families=["x"], summary="X",
    )
    assert c.applicable_doc_classes == []
    assert c.tolerance_band is None


def test_clause_is_frozen() -> None:
    from interlock.llm_pipeline.schemas.clause import Clause
    c = Clause(
        clause_id="X", edition_year=2020, source_name="X",
        applicable_families=["x"], summary="X",
    )
    with pytest.raises(ValidationError):
        c.clause_id = "Y"  # type: ignore[misc]


def test_clause_summary_empty_rejected() -> None:
    from interlock.llm_pipeline.schemas.clause import Clause
    with pytest.raises(ValidationError):
        Clause(
            clause_id="X", edition_year=2020, source_name="X",
            applicable_families=["x"], summary="",
        )


def test_clause_citation_constructs() -> None:
    from interlock.llm_pipeline.schemas.clause import ClauseCitation
    cc = ClauseCitation(
        clause_id="IEEE-X", edition_year=2020,
        source_name="IEEE X", summary="summary text",
    )
    assert cc.clause_id == "IEEE-X"
    assert cc.summary == "summary text"


def test_clause_citation_is_frozen() -> None:
    from interlock.llm_pipeline.schemas.clause import ClauseCitation
    cc = ClauseCitation(
        clause_id="X", edition_year=2020,
        source_name="X", summary="X",
    )
    with pytest.raises(ValidationError):
        cc.summary = "Y"  # type: ignore[misc]
```

- [ ] **Step 2: Run; expected to fail**

```bash
uv run pytest tests/llm_pipeline/schemas/test_clause.py -v
```

Expected: 8 FAIL with `ModuleNotFoundError: interlock.llm_pipeline.schemas.clause`.

- [ ] **Step 3: Implement schemas**

```python
# src/interlock/llm_pipeline/schemas/clause.py
"""Sprint 5a — Clause + ClauseCitation schemas for standards registry.

Clause is the rich on-disk entry loaded from data/standards/clauses.yaml.
ClauseCitation is the slim projection carried on Flag.cited_clauses + JSON
export — drops applicable_* and tolerance_band so the reviewer-facing
surface only carries human-readable citation fields.
"""

from __future__ import annotations

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
    """Slim subset of Clause carried on Flag + JSON export."""

    model_config = ConfigDict(frozen=True)

    clause_id: str
    edition_year: int
    source_name: str
    summary: str
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/llm_pipeline/schemas/test_clause.py -v
```

Expected: 8 passed.

- [ ] **Step 5: Lint + mypy**

```bash
uv run ruff check src/interlock/llm_pipeline/schemas/clause.py tests/llm_pipeline/schemas/test_clause.py
uv run mypy src/interlock/llm_pipeline/schemas/clause.py
```

Expected: clean.

- [ ] **Step 6: Commit + tag (closes Phase 29.1)**

```bash
git add src/interlock/llm_pipeline/schemas/clause.py tests/llm_pipeline/schemas/test_clause.py
git commit -m "feat(schemas): Clause + ClauseCitation pydantic models for standards registry"
git tag phase-29.1-clause-schemas -m "Sprint 5a phase 1: clause schemas"
git push origin main phase-29.1-clause-schemas
```

---

## Phase 29.2 — Registry module + YAML seed

### Task 2.1: YAML seed

**Files:**
- Create: `data/standards/clauses.yaml`

- [ ] **Step 1: Write the seed registry**

```yaml
# data/standards/clauses.yaml
# Sprint 5a — curated standards-clause registry.
# Each entry is a paraphrase of the cited standard's substance. Not the
# verbatim text of the standard — we cite source_name + edition_year so a
# reviewer can cross-check against the original.

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

  - clause_id: IEC-60076-1-2011-5.3
    edition_year: 2011
    source_name: "IEC 60076-1:2011 §5.3 (Voltage Ratio Tolerance)"
    applicable_families: [voltage_v, voltage_kv]
    applicable_doc_classes: []
    tolerance_band: 0.005
    summary: |
      Per IEC 60076-1:2011 §5.3, the voltage ratio of a power transformer at
      no-load and rated tap shall be within ±0.5% of the specified ratio.
      Tighter than IEEE on ratio; deviations indicate either tap-change
      design or a transcription error.

  - clause_id: IEEE-242-2001-15.5
    edition_year: 2001
    source_name: "IEEE Std 242-2001 §15.5 (Available Fault Current)"
    applicable_families: [fault_current_a, fault_current_ka]
    applicable_doc_classes: []
    summary: |
      Per IEEE Std 242-2001 (Buff Book) §15.5, the available fault current
      at each bus must be computed consistently across all study documents.
      A discrepancy indicates either an upstream impedance change or a
      calculation error in one of the downstream studies; typical industry
      tolerance is ±20%.

  - clause_id: IEEE-C57.12.00-2015-5.10
    edition_year: 2015
    source_name: "IEEE C57.12.00-2015 §5.10 (Rated kVA Tolerance)"
    applicable_families: [transformer_rating_va]
    applicable_doc_classes: [equipment_spec, coordination_study]
    tolerance_band: 0.05
    summary: |
      Per IEEE C57.12.00-2015 §5.10, transformer rated kVA carries a ±5%
      typical tolerance (extended to ±10% with loading classification per
      §5.11). Rating mismatches across documents directly affect cable
      ampacity, breaker interrupting capacity, and CT ratio sizing.

  - clause_id: NEMA-MG-1-2016-12.43
    edition_year: 2016
    source_name: "NEMA MG-1-2016 §12.43 (Motor Full-Load Current)"
    applicable_families: [motor_fla_a]
    applicable_doc_classes: []
    tolerance_band: 0.10
    summary: |
      Per NEMA MG-1-2016 §12.43, motor full-load current at nameplate voltage
      and full-load slip carries ±10% manufacturing tolerance. Differences
      above this threshold across project documents suggest either a vendor
      change, a motor mis-specification, or confusion between FLA and
      starting/inrush current.

  - clause_id: IEEE-242-2001-15.10
    edition_year: 2001
    source_name: "IEEE Std 242-2001 §15.10 (Relay Pickup Settings)"
    applicable_families: [relay_pickup_a]
    applicable_doc_classes: [relay_setting_sheet, coordination_study]
    summary: |
      Per IEEE Std 242-2001 §15.10, relay pickup settings are derived from
      transformer impedance, fault current, and load profile — any of which
      changing requires the relay settings to be re-verified. Pickup
      discrepancies across coordination studies usually trace back to an
      upstream parameter revision.

  - clause_id: IEEE-242-2001-16.2
    edition_year: 2001
    source_name: "IEEE Std 242-2001 §16.2 (Fuse Selectivity)"
    applicable_families: [fuse_amps]
    applicable_doc_classes: [coordination_study]
    summary: |
      Per IEEE Std 242-2001 §16.2, the speed ratio between upstream and
      downstream fuses must be sufficient to achieve selective coordination.
      A change in fuse rating without verifying the upstream/downstream
      ratio risks losing selectivity and tripping out more equipment than
      necessary on a downstream fault.

  - clause_id: IEEE-C37.04-2018-5.2
    edition_year: 2018
    source_name: "IEEE C37.04-2018 §5.2 (Breaker Interrupting Rating)"
    applicable_families: [breaker_interrupting_ka, fault_current_ka]
    applicable_doc_classes: [equipment_spec, coordination_study]
    summary: |
      Per IEEE C37.04-2018 §5.2, circuit-breaker interrupting capacity
      must exceed the maximum available fault current at the installation
      point. A change to the fault current value across documents must
      trigger re-verification of every downstream breaker's rating margin.

  - clause_id: IEEE-1584-2018-6.1
    edition_year: 2018
    source_name: "IEEE 1584-2018 §6.1 (Arc-Flash Incident Energy)"
    applicable_families: [arc_flash_cal_cm2, fault_current_ka]
    applicable_doc_classes: [coordination_study]
    summary: |
      Per IEEE 1584-2018 §6.1, arc-flash incident energy is a function of
      bolted fault current, breaker clearing time, and working distance.
      A change to any input requires re-running the arc-flash study and
      re-issuing PPE / labelling per NFPA 70E.

  - clause_id: IEC-60076-7-2018-7.3
    edition_year: 2018
    source_name: "IEC 60076-7:2018 §7.3 (Loading Above Nameplate)"
    applicable_families: [transformer_rating_va, transformer_loading_pct]
    applicable_doc_classes: []
    summary: |
      Per IEC 60076-7:2018 §7.3, loading a transformer above its nameplate
      rating accelerates insulation ageing per the Arrhenius law. Sustained
      operation above the rating without explicit derating analysis voids
      the manufacturer's life expectancy.
```

- [ ] **Step 2: Commit seed**

```bash
git add data/standards/clauses.yaml
git commit -m "feat(standards): seed 10-clause registry for impedance, voltage, fault, motor, fuse, breaker, arc-flash"
```

### Task 2.2: Registry module + unit tests

**Files:**
- Create: `src/interlock/llm_pipeline/standards.py`
- Create: `tests/llm_pipeline/test_standards.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/llm_pipeline/test_standards.py
"""Sprint 5a — standards registry unit tests."""

from __future__ import annotations

from pathlib import Path

import pytest


def _write_yaml(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_load_clauses_returns_validated_list(tmp_path) -> None:  # type: ignore[no-untyped-def]
    from interlock.llm_pipeline.standards import load_clauses
    p = tmp_path / "clauses.yaml"
    _write_yaml(p, """\
clauses:
  - clause_id: TEST-1
    edition_year: 2020
    source_name: Test
    applicable_families: [x]
    summary: test summary
""")
    out = load_clauses(p)
    assert len(out) == 1
    assert out[0].clause_id == "TEST-1"
    assert out[0].applicable_families == ["x"]


def test_load_clauses_missing_file_returns_empty(tmp_path) -> None:  # type: ignore[no-untyped-def]
    from interlock.llm_pipeline.standards import load_clauses
    p = tmp_path / "missing.yaml"
    assert load_clauses(p) == []


def test_load_clauses_parse_error_returns_empty(tmp_path) -> None:  # type: ignore[no-untyped-def]
    from interlock.llm_pipeline.standards import load_clauses
    p = tmp_path / "bad.yaml"
    _write_yaml(p, "not: valid: yaml: :")
    assert load_clauses(p) == []


def test_load_clauses_drops_invalid_entries(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """One bad entry should not prevent others from loading."""
    from interlock.llm_pipeline.standards import load_clauses
    p = tmp_path / "mixed.yaml"
    _write_yaml(p, """\
clauses:
  - clause_id: GOOD
    edition_year: 2020
    source_name: Good
    applicable_families: [x]
    summary: ok
  - clause_id: BAD
    edition_year: 99999
    source_name: Bad
    applicable_families: [x]
    summary: bad year
""")
    out = load_clauses(p)
    ids = {c.clause_id for c in out}
    assert "GOOD" in ids
    assert "BAD" not in ids


def test_clauses_for_family_returns_matches(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from interlock.llm_pipeline import standards as std
    p = tmp_path / "clauses.yaml"
    _write_yaml(p, """\
clauses:
  - clause_id: A
    edition_year: 2020
    source_name: A
    applicable_families: [impedance_pct]
    summary: a
  - clause_id: B
    edition_year: 2020
    source_name: B
    applicable_families: [fault_current_a]
    summary: b
""")
    monkeypatch.setattr(std, "_CLAUSES_PATH", p)
    out = std.clauses_for("impedance_pct")
    assert [c.clause_id for c in out] == ["A"]


def test_clauses_for_unknown_family_returns_empty(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from interlock.llm_pipeline import standards as std
    p = tmp_path / "clauses.yaml"
    _write_yaml(p, """\
clauses:
  - clause_id: A
    edition_year: 2020
    source_name: A
    applicable_families: [impedance_pct]
    summary: a
""")
    monkeypatch.setattr(std, "_CLAUSES_PATH", p)
    assert std.clauses_for("nonexistent_family") == []


def test_clauses_for_doc_class_filter(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from interlock.llm_pipeline import standards as std
    p = tmp_path / "clauses.yaml"
    _write_yaml(p, """\
clauses:
  - clause_id: SPEC
    edition_year: 2020
    source_name: spec
    applicable_families: [impedance_pct]
    applicable_doc_classes: [equipment_spec]
    summary: equipment-only
  - clause_id: ANY
    edition_year: 2020
    source_name: any
    applicable_families: [impedance_pct]
    applicable_doc_classes: []
    summary: applies-everywhere
""")
    monkeypatch.setattr(std, "_CLAUSES_PATH", p)
    out_spec = std.clauses_for("impedance_pct", doc_class="equipment_spec")
    out_study = std.clauses_for("impedance_pct", doc_class="coordination_study")
    assert {c.clause_id for c in out_spec} == {"SPEC", "ANY"}
    assert {c.clause_id for c in out_study} == {"ANY"}


def test_clauses_for_no_doc_class_returns_all_matching_family(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from interlock.llm_pipeline import standards as std
    p = tmp_path / "clauses.yaml"
    _write_yaml(p, """\
clauses:
  - clause_id: A
    edition_year: 2020
    source_name: a
    applicable_families: [x]
    applicable_doc_classes: [equipment_spec]
    summary: a
""")
    monkeypatch.setattr(std, "_CLAUSES_PATH", p)
    out = std.clauses_for("x", doc_class=None)
    assert [c.clause_id for c in out] == ["A"]


def test_merge_project_overrides_replaces_by_clause_id(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from interlock.llm_pipeline import standards as std
    base_path = tmp_path / "clauses.yaml"
    _write_yaml(base_path, """\
clauses:
  - clause_id: A
    edition_year: 2020
    source_name: base-A
    applicable_families: [x]
    summary: base
""")
    proj_path = tmp_path / "projects" / "p1" / "tolerances.yaml"
    _write_yaml(proj_path, """\
clauses:
  - clause_id: A
    edition_year: 2024
    source_name: override-A
    applicable_families: [x]
    summary: override
""")
    monkeypatch.setattr(std, "_CLAUSES_PATH", base_path)
    monkeypatch.setattr(std, "_PROJECTS_ROOT", tmp_path / "projects")
    out = std.clauses_for("x", project_id="p1")
    assert len(out) == 1
    assert out[0].source_name == "override-A"
    assert out[0].edition_year == 2024


def test_merge_project_overrides_appends_new_entries(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from interlock.llm_pipeline import standards as std
    base_path = tmp_path / "clauses.yaml"
    _write_yaml(base_path, """\
clauses:
  - clause_id: A
    edition_year: 2020
    source_name: base-A
    applicable_families: [x]
    summary: base
""")
    proj_path = tmp_path / "projects" / "p1" / "tolerances.yaml"
    _write_yaml(proj_path, """\
clauses:
  - clause_id: B
    edition_year: 2024
    source_name: proj-B
    applicable_families: [x]
    summary: project-specific
""")
    monkeypatch.setattr(std, "_CLAUSES_PATH", base_path)
    monkeypatch.setattr(std, "_PROJECTS_ROOT", tmp_path / "projects")
    out = std.clauses_for("x", project_id="p1")
    ids = {c.clause_id for c in out}
    assert ids == {"A", "B"}


def test_missing_project_overrides_returns_base_unchanged(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from interlock.llm_pipeline import standards as std
    base_path = tmp_path / "clauses.yaml"
    _write_yaml(base_path, """\
clauses:
  - clause_id: A
    edition_year: 2020
    source_name: base-A
    applicable_families: [x]
    summary: base
""")
    monkeypatch.setattr(std, "_CLAUSES_PATH", base_path)
    monkeypatch.setattr(std, "_PROJECTS_ROOT", tmp_path / "projects")
    out = std.clauses_for("x", project_id="nonexistent")
    assert [c.clause_id for c in out] == ["A"]


def test_to_citation_projects_correct_fields(tmp_path) -> None:  # type: ignore[no-untyped-def]
    from interlock.llm_pipeline.schemas.clause import Clause
    from interlock.llm_pipeline.standards import to_citation
    c = Clause(
        clause_id="X", edition_year=2020, source_name="X-name",
        applicable_families=["x"], applicable_doc_classes=["eq"],
        tolerance_band=0.05, summary="X-summary",
    )
    cc = to_citation(c)
    assert cc.clause_id == "X"
    assert cc.edition_year == 2020
    assert cc.source_name == "X-name"
    assert cc.summary == "X-summary"
    assert not hasattr(cc, "applicable_families")
    assert not hasattr(cc, "tolerance_band")
```

- [ ] **Step 2: Run; expected to fail**

```bash
uv run pytest tests/llm_pipeline/test_standards.py -v
```

Expected: 12 failures (ModuleNotFoundError).

- [ ] **Step 3: Implement registry module**

```python
# src/interlock/llm_pipeline/standards.py
"""Sprint 5a — curated standards-clause registry.

Loads data/standards/clauses.yaml + (optional) per-project overrides at
fixtures/projects/<project_id>/tolerances.yaml. Provides per-family
lookup with optional doc_class filtering.

Failure modes (missing file, YAML parse error, pydantic validation error,
bad individual entry) all collapse to '[]' so the LLM judge keeps running
gracefully without grounding.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml

from interlock.llm_pipeline.schemas.clause import Clause, ClauseCitation

logger = logging.getLogger(__name__)

_CLAUSES_PATH = Path("data/standards/clauses.yaml")
_PROJECTS_ROOT = Path("fixtures/projects")


def load_clauses(path: Path | None = None) -> list[Clause]:
    """Return list of validated Clause entries from YAML.

    Missing file → []. Parse / validation error → logged + [].
    Individual bad entries dropped; others retained.
    """
    p = path if path is not None else _CLAUSES_PATH
    if not p.exists():
        return []
    try:
        raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as e:
        logger.warning("standards: YAML parse failed for %s: %s", p, e)
        return []
    entries = raw.get("clauses") if isinstance(raw, dict) else None
    if not isinstance(entries, list):
        return []
    out: list[Clause] = []
    for i, entry in enumerate(entries):
        if not isinstance(entry, dict):
            continue
        try:
            out.append(Clause(**entry))
        except Exception as e:
            logger.warning(
                "standards: dropping invalid entry #%d in %s: %s", i, p, e,
            )
    return out


def _project_overrides_path(project_id: str) -> Path:
    return _PROJECTS_ROOT / project_id / "tolerances.yaml"


def merge_project_overrides(base: list[Clause], project_id: str) -> list[Clause]:
    """Merge project overrides into base by clause_id.

    Project entry with same clause_id replaces base entry. Project entries
    with novel clause_ids are appended. Missing override file → base
    unchanged.
    """
    override_path = _project_overrides_path(project_id)
    if not override_path.exists():
        return base
    overrides = load_clauses(override_path)
    if not overrides:
        return base
    by_id: dict[str, Clause] = {c.clause_id: c for c in base}
    for o in overrides:
        by_id[o.clause_id] = o
    return list(by_id.values())


def clauses_for(
    family: str,
    doc_class: str | None = None,
    project_id: str | None = None,
) -> list[Clause]:
    """Return clauses matching attribute_family + optionally doc_class.

    Family match: any entry whose ``applicable_families`` contains ``family``.
    Doc-class filter: entry passes if ``applicable_doc_classes`` is empty
    (applies to all) OR contains the supplied ``doc_class``. When
    ``doc_class is None`` the filter is skipped entirely.
    """
    base = load_clauses()
    if project_id:
        clauses = merge_project_overrides(base, project_id)
    else:
        clauses = base
    out: list[Clause] = []
    for c in clauses:
        if family not in c.applicable_families:
            continue
        if doc_class is not None and c.applicable_doc_classes:
            if doc_class not in c.applicable_doc_classes:
                continue
        out.append(c)
    return out


def to_citation(clause: Clause) -> ClauseCitation:
    """Project Clause → ClauseCitation (slim, reviewer-facing fields)."""
    return ClauseCitation(
        clause_id=clause.clause_id,
        edition_year=clause.edition_year,
        source_name=clause.source_name,
        summary=clause.summary,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/llm_pipeline/test_standards.py -v
```

Expected: 12 passed.

- [ ] **Step 5: Lint + mypy**

```bash
uv run ruff check src/interlock/llm_pipeline/standards.py tests/llm_pipeline/test_standards.py
uv run mypy src/interlock/llm_pipeline/standards.py
```

Expected: clean.

- [ ] **Step 6: Full regression**

```bash
uv run pytest --deselect tests/real_world 2>&1 | tail -3
```

Expected: 408 (v2.4 baseline) + 8 (29.1) + 12 (29.2) = 428 passed.

- [ ] **Step 7: Commit + tag (closes Phase 29.2)**

```bash
git add src/interlock/llm_pipeline/standards.py tests/llm_pipeline/test_standards.py
git commit -m "feat(standards): load_clauses + clauses_for + project override merge (12 unit tests)"
git tag phase-29.2-standards-registry -m "Sprint 5a phase 2: registry module + YAML seed"
git push origin main phase-29.2-standards-registry
```

---

## Phase 29.3 — Judge integration + `Flag.cited_clauses`

### Task 3.1: Extend `Flag` + `SignificanceJudgment`

**Files:**
- Modify: `src/interlock/detect/mismatch.py`
- Modify: `src/interlock/detect/significance.py`

- [ ] **Step 1: Add `Flag.cited_clauses`**

Read `src/interlock/detect/mismatch.py` to locate the `Flag` dataclass. Append at the end of the field list (after Sprint 4 `rerank_rationale`):

```python
# src/interlock/detect/mismatch.py — at top, add import:
from interlock.llm_pipeline.schemas.clause import ClauseCitation

# Within @dataclass(frozen=True) class Flag, append after rerank_rationale:
    # v2 Sprint 5a — clauses cited by the LLM judge. Empty tuple when
    # the judge didn't run or the registry had no matches.
    cited_clauses: tuple[ClauseCitation, ...] = ()
```

- [ ] **Step 2: Extend `SignificanceJudgment`**

In `src/interlock/detect/significance.py`, add a new field to `SignificanceJudgment`:

```python
# Within class SignificanceJudgment, append after confidence:
    cited_clause_ids: list[str] = Field(
        default_factory=list,
        description=(
            "Clause IDs from the supplied 'Applicable standards' list that "
            "you cited in the engineering explanation. Must be exact matches "
            "to provided clause_id values. Leave empty when no clauses were "
            "supplied or none apply."
        ),
    )
```

- [ ] **Step 3: Compile + lint + mypy**

```bash
uv run ruff check src/interlock/detect/mismatch.py src/interlock/detect/significance.py
uv run mypy src/interlock/detect/mismatch.py src/interlock/detect/significance.py
```

Expected: clean.

### Task 3.2: Inject standards block + propagate citations

**Files:**
- Modify: `src/interlock/detect/significance.py`
- Create: `tests/detect/test_significance_rag.py` (new file to avoid disrupting existing tests)

- [ ] **Step 1: Write the failing tests**

```python
# tests/detect/test_significance_rag.py
"""Sprint 5a — significance judge standards-RAG integration tests."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from interlock.cache import disk as disk_cache
from interlock.detect.mismatch import Flag
from interlock.extract.parameters import ParameterRecord


def _record(name: str = "%Z", raw: str = "5.75 %") -> ParameterRecord:
    return ParameterRecord(
        doc_id="d", page=1, bbox=(0, 0, 100, 10), section=None,
        span_text=raw, name=name, raw_value=raw,
        normalized_magnitude=0.0575, normalized_unit="dimensionless",
    )


def _flag(family: str = "impedance_pct") -> Flag:
    return Flag(
        parameter="%Z",
        a_record=_record(), b_record=_record(raw="5.20 %"),
        authoritative_doc_id="d", deviating_doc_id="d",
        confidence=1.0, rationale="test", authority_rule="MVP",
        severity="major", deviation_pct=10.0,
        attribute_family=family,
    )


@pytest.fixture(autouse=True)
def _clear_judge_cache() -> None:
    disk_cache.clear_namespace("llm-significance")
    yield
    disk_cache.clear_namespace("llm-significance")


def test_judge_prompt_includes_applicable_standards_when_matches(mocker, monkeypatch, tmp_path) -> None:  # type: ignore[no-untyped-def]
    """Judge user block contains 'Applicable standards' section when
    the registry has matching clauses for the flag's family."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    from interlock.detect.significance import SignificanceJudgment, judge
    from interlock.llm_pipeline import standards as std

    p = tmp_path / "clauses.yaml"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("""\
clauses:
  - clause_id: TEST-IMPZ
    edition_year: 2020
    source_name: Test impedance standard
    applicable_families: [impedance_pct]
    summary: Test summary
""", encoding="utf-8")
    monkeypatch.setattr(std, "_CLAUSES_PATH", p)

    captured: dict[str, list] = {}

    def _fake_call_structured(*, response_model, system_blocks, user_blocks, model):  # type: ignore[no-untyped-def]
        captured["user_blocks"] = user_blocks
        return (
            response_model(
                severity="major",
                within_typical_tolerance=False,
                engineering_explanation="Test explanation citing Test impedance standard.",
                downstream_effects=[],
                confidence=0.9,
                cited_clause_ids=["TEST-IMPZ"],
            ),
            {"input": 0, "cache_read": 0, "cache_creation": 0, "output": 0},
        )

    mocker.patch("interlock.detect.significance.call_structured", side_effect=_fake_call_structured)
    out = judge(_flag())
    user_text = "\n".join(b.text for b in captured["user_blocks"])
    assert "Applicable standards" in user_text
    assert "TEST-IMPZ" in user_text
    assert out.cited_clause_ids == ["TEST-IMPZ"]


def test_judge_prompt_omits_standards_section_when_empty(mocker, monkeypatch, tmp_path) -> None:  # type: ignore[no-untyped-def]
    """Empty registry → judge prompt has no 'Applicable standards' section."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    from interlock.detect.significance import SignificanceJudgment, judge
    from interlock.llm_pipeline import standards as std

    p = tmp_path / "missing.yaml"  # don't create it
    monkeypatch.setattr(std, "_CLAUSES_PATH", p)

    captured: dict[str, list] = {}

    def _fake_call_structured(*, response_model, system_blocks, user_blocks, model):  # type: ignore[no-untyped-def]
        captured["user_blocks"] = user_blocks
        return (
            response_model(
                severity="major",
                within_typical_tolerance=False,
                engineering_explanation="Test.",
                downstream_effects=[],
                confidence=0.9,
            ),
            {"input": 0, "cache_read": 0, "cache_creation": 0, "output": 0},
        )

    mocker.patch("interlock.detect.significance.call_structured", side_effect=_fake_call_structured)
    judge(_flag())
    user_text = "\n".join(b.text for b in captured["user_blocks"])
    assert "Applicable standards" not in user_text


def test_apply_judgment_resolves_clause_ids_to_citations(monkeypatch, tmp_path) -> None:  # type: ignore[no-untyped-def]
    """apply_judgment_to_flag should turn cited_clause_ids into ClauseCitation tuple."""
    from interlock.detect.significance import (
        SignificanceJudgment, apply_judgment_to_flag,
    )
    from interlock.llm_pipeline import standards as std

    p = tmp_path / "clauses.yaml"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("""\
clauses:
  - clause_id: TEST-IMPZ
    edition_year: 2020
    source_name: Test impedance standard
    applicable_families: [impedance_pct]
    summary: Test summary
""", encoding="utf-8")
    monkeypatch.setattr(std, "_CLAUSES_PATH", p)

    j = SignificanceJudgment(
        severity="major",
        within_typical_tolerance=False,
        engineering_explanation="Test.",
        downstream_effects=[],
        confidence=0.9,
        cited_clause_ids=["TEST-IMPZ"],
    )
    out = apply_judgment_to_flag(_flag(), j)
    assert len(out.cited_clauses) == 1
    assert out.cited_clauses[0].clause_id == "TEST-IMPZ"
    assert out.cited_clauses[0].source_name == "Test impedance standard"


def test_hallucinated_clause_id_filtered_silently(monkeypatch, tmp_path) -> None:  # type: ignore[no-untyped-def]
    """Clause ID not in registry → silently dropped from cited_clauses."""
    from interlock.detect.significance import (
        SignificanceJudgment, apply_judgment_to_flag,
    )
    from interlock.llm_pipeline import standards as std

    p = tmp_path / "clauses.yaml"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("""\
clauses:
  - clause_id: TEST-REAL
    edition_year: 2020
    source_name: Real
    applicable_families: [x]
    summary: real
""", encoding="utf-8")
    monkeypatch.setattr(std, "_CLAUSES_PATH", p)

    j = SignificanceJudgment(
        severity="major",
        within_typical_tolerance=False,
        engineering_explanation="Test.",
        downstream_effects=[],
        confidence=0.9,
        cited_clause_ids=["TEST-REAL", "HALLUCINATED-ID"],
    )
    out = apply_judgment_to_flag(_flag(), j)
    assert [c.clause_id for c in out.cited_clauses] == ["TEST-REAL"]


def test_apply_judgment_preserves_sprint_3_4_4_5_fields(monkeypatch, tmp_path) -> None:  # type: ignore[no-untyped-def]
    """Sprint 3 provenance, Sprint 4 rerank_rationale, Phase 19
    pairing_confidence must survive judge rebuild."""
    from interlock.detect.significance import (
        SignificanceJudgment, apply_judgment_to_flag,
    )
    f = Flag(
        parameter="%Z",
        a_record=_record(), b_record=_record(raw="5.20 %"),
        authoritative_doc_id="d", deviating_doc_id="d",
        confidence=1.0, rationale="r", authority_rule="MVP",
        severity="major", deviation_pct=10.0,
        attribute_family="impedance_pct",
        pairing_confidence=0.6,
        provenance="rule_only",  # type: ignore[arg-type]
        rerank_rationale="ok",
    )
    j = SignificanceJudgment(
        severity="critical",
        within_typical_tolerance=False,
        engineering_explanation="explained",
        downstream_effects=["x"],
        confidence=0.95,
        cited_clause_ids=[],
    )
    out = apply_judgment_to_flag(f, j)
    assert out.provenance == "rule_only"
    assert out.rerank_rationale == "ok"
    assert out.pairing_confidence == 0.6
    assert out.severity == "critical"
    assert out.cited_clauses == ()


def test_judge_cache_key_includes_matched_clause_ids(mocker, monkeypatch, tmp_path) -> None:  # type: ignore[no-untyped-def]
    """Growing the registry should invalidate the cache for affected
    flags. Cache key must depend on matched clause IDs, not just flag id."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    from interlock.detect.significance import SignificanceJudgment, judge
    from interlock.llm_pipeline import standards as std

    p = tmp_path / "clauses.yaml"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("""\
clauses:
  - clause_id: A
    edition_year: 2020
    source_name: A
    applicable_families: [impedance_pct]
    summary: a
""", encoding="utf-8")
    monkeypatch.setattr(std, "_CLAUSES_PATH", p)

    call_count = {"n": 0}

    def _fake_call_structured(*, response_model, system_blocks, user_blocks, model):  # type: ignore[no-untyped-def]
        call_count["n"] += 1
        return (
            response_model(
                severity="major",
                within_typical_tolerance=False,
                engineering_explanation="x",
                downstream_effects=[],
                confidence=0.9,
                cited_clause_ids=[],
            ),
            {"input": 0, "cache_read": 0, "cache_creation": 0, "output": 0},
        )

    mocker.patch("interlock.detect.significance.call_structured", side_effect=_fake_call_structured)

    judge(_flag())
    assert call_count["n"] == 1

    # Grow registry — same flag should re-call (different matched clauses).
    p.write_text("""\
clauses:
  - clause_id: A
    edition_year: 2020
    source_name: A
    applicable_families: [impedance_pct]
    summary: a
  - clause_id: B
    edition_year: 2021
    source_name: B
    applicable_families: [impedance_pct]
    summary: b
""", encoding="utf-8")
    judge(_flag())
    assert call_count["n"] == 2, (
        "Cache must invalidate when matched clause IDs change; "
        f"call count stayed at {call_count['n']}"
    )
```

- [ ] **Step 2: Run; expected to fail**

```bash
uv run pytest tests/detect/test_significance_rag.py -v
```

Expected: 6 failures.

- [ ] **Step 3: Wire judge to inject standards block**

Edit `src/interlock/detect/significance.py`:

1. Add import at top:

```python
from interlock.llm_pipeline.standards import clauses_for, to_citation
```

2. Add a new helper function next to `_build_user_block`:

```python
def _build_standards_block(flag: Flag, project_id: str | None) -> tuple[str, list[str]]:
    """Return (rendered_text, matched_clause_ids).

    Empty string + [] when no matches OR no attribute_family on the flag.
    """
    family = (flag.attribute_family or "").strip()
    if not family:
        return "", []
    matched = clauses_for(family, doc_class=None, project_id=project_id)
    if not matched:
        return "", []
    lines = [
        "",
        "## Applicable standards",
        "",
        "When writing the rationale, cite clauses from this list when they "
        "ground the engineering judgment. Reference by `source_name`. Do "
        "NOT cite clauses that aren't on this list. Use the bracketed "
        "`clause_id` in your `cited_clause_ids` response field.",
        "",
    ]
    for c in matched:
        lines.append(f"- [{c.clause_id}] {c.source_name}")
        lines.append(f"  Summary: {c.summary.strip()}")
        lines.append("")
    return "\n".join(lines), [c.clause_id for c in matched]
```

3. Update the `judge()` function signature + body to accept `project_id` and inject the block:

```python
def judge(
    flag: Flag,
    *,
    model: str = DEFAULT_MODEL,
    project_id: str | None = None,
) -> SignificanceJudgment:
    """Get an LLM significance judgment for one flag."""
    standards_text, matched_ids = _build_standards_block(flag, project_id)

    payload = {
        "flag_id": _flag_id(flag),
        "prompt_version": PROMPT_VERSION,
        "model": model,
        "matched_clause_ids": matched_ids,  # v2 Sprint 5a — cache invalidates on registry growth
    }

    def _compute() -> SignificanceJudgment:
        system_blocks = [
            CachedBlock(text=_SYSTEM_PREAMBLE, ttl="1h"),
            CachedBlock(text=_ONTOLOGY_BLOCK, ttl="1h"),
        ]
        user_text = _build_user_block(flag)
        if standards_text:
            user_text = user_text + standards_text
        user_blocks = [CachedBlock(text=user_text, ttl=None)]
        result, usage = call_structured(
            response_model=SignificanceJudgment,
            system_blocks=system_blocks,
            user_blocks=user_blocks,
            model=model,
        )
        cost_ledger.record(
            provider="anthropic",
            model=model,
            namespace=_CACHE_NAMESPACE,
            input_tokens=usage.get("input", 0),
            cache_read_tokens=usage.get("cache_read", 0),
            cache_creation_tokens=usage.get("cache_creation", 0),
            output_tokens=usage.get("output", 0),
            cache_ttl="1h",
        )
        return result

    value, _hit = get_or_compute(_CACHE_NAMESPACE, payload, _compute)
    return value
```

4. Update `apply_judgment_to_flag` to map `cited_clause_ids` to `ClauseCitation`:

```python
def apply_judgment_to_flag(flag: Flag, judgment: SignificanceJudgment) -> Flag:
    """Return a new Flag with severity + rationale enriched from the LLM
    judgment. Authority + citation tuple are preserved verbatim."""
    new_rationale = (
        f"{flag.rationale} — {judgment.engineering_explanation}"
        if judgment.engineering_explanation
        else flag.rationale
    )
    # v2 Sprint 5a — resolve cited_clause_ids → ClauseCitation tuple.
    # Hallucinated IDs (not in registry) are silently dropped.
    cited: tuple = ()
    if judgment.cited_clause_ids:
        from interlock.llm_pipeline.standards import load_clauses
        by_id = {c.clause_id: c for c in load_clauses()}
        cited = tuple(
            to_citation(by_id[cid])
            for cid in judgment.cited_clause_ids
            if cid in by_id
        )
    return Flag(
        parameter=flag.parameter,
        authoritative_doc_id=flag.authoritative_doc_id,
        deviating_doc_id=flag.deviating_doc_id,
        a_record=flag.a_record,
        b_record=flag.b_record,
        confidence=flag.confidence * judgment.confidence,
        rationale=new_rationale,
        authority_rule=flag.authority_rule,
        severity=judgment.severity,
        deviation_pct=flag.deviation_pct,
        attribute_family=flag.attribute_family,
        pairing_confidence=flag.pairing_confidence,
        provenance=flag.provenance,
        rerank_rationale=flag.rerank_rationale,
        cited_clauses=cited,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/detect/test_significance_rag.py -v
```

Expected: 6 passed.

- [ ] **Step 5: Lint + mypy**

```bash
uv run ruff check src/interlock/detect/significance.py tests/detect/test_significance_rag.py
uv run mypy src/interlock/detect/significance.py
```

Expected: clean.

- [ ] **Step 6: Full regression**

```bash
uv run pytest --deselect tests/real_world 2>&1 | tail -3
```

Expected: 428 + 6 = 434 passed.

- [ ] **Step 7: Commit + tag (closes Phase 29.3)**

```bash
git add src/interlock/detect/mismatch.py src/interlock/detect/significance.py tests/detect/test_significance_rag.py
git commit -m "feat(detect): standards-RAG block injection + Flag.cited_clauses propagation"
git tag phase-29.3-judge-integration -m "Sprint 5a phase 3: judge integration + 6 tests"
git push origin main phase-29.3-judge-integration
```

---

## Phase 29.4 — Pipeline `project_id` kwarg + e2e tests

### Task 4.1: Pipeline kwarg + fixture

**Files:**
- Modify: `src/interlock/pipeline.py`
- Create: `fixtures/projects/testproj/tolerances.yaml`

- [ ] **Step 1: Add fixture override file**

```yaml
# fixtures/projects/testproj/tolerances.yaml
# Sprint 5a — test fixture for per-project clause override.
clauses:
  - clause_id: IEEE-C57.12.00-2015-5.4
    edition_year: 2024
    source_name: "TESTPROJ override of IEEE C57.12.00-2015 §5.4"
    applicable_families: [impedance_pct]
    applicable_doc_classes: []
    tolerance_band: 0.05
    summary: |
      Project override: tighter ±5% tolerance per testproj engineering memo.
```

- [ ] **Step 2: Add `project_id` kwarg to pipeline**

Read `src/interlock/pipeline.py`. Update `review_two_documents_full` signature:

```python
def review_two_documents_full(
    pdf_a: str,
    pdf_b: str,
    embed_fn: EmbedFn,
    doc_a_id: str = "doc_a",
    doc_b_id: str = "doc_b",
    same_page_only: bool = True,
    use_llm_judge: bool = True,
    suppress_info: bool = True,
    use_claim_layer: bool = False,
    same_entity_only: bool = True,
    persist_claims: bool = False,
    table_max_pages: int | None = None,
    enable_vision_ocr: bool = False,
    ocr_progress_cb: OcrProgressCallback | None = None,
    stage_cb: StageCallback | None = None,
    classify_docs: bool = True,
    use_llm_extraction: bool = True,
    use_llm_reranker: bool = True,
    use_entity_grounding: bool = True,
    project_id: str | None = None,           # v2 Sprint 5a — NEW
) -> ReviewResult:
```

Same addition on `review_two_documents` back-compat shim signature + forward `project_id=project_id` in the body call.

- [ ] **Step 3: Forward `project_id` to `judge()`**

Find the existing block:

```python
    if use_llm_judge and flags:
        _stage("judge", "start")
        flags = [apply_judgment_to_flag(f, judge(f)) for f in flags]
        _stage("judge", "done")
```

Update to:

```python
    if use_llm_judge and flags:
        _stage("judge", "start")
        flags = [
            apply_judgment_to_flag(f, judge(f, project_id=project_id))
            for f in flags
        ]
        _stage("judge", "done")
```

### Task 4.2: E2E tests

**Files:**
- Modify: `tests/e2e/test_pipeline_v2.py`

- [ ] **Step 1: Append failing tests**

```python
# tests/e2e/test_pipeline_v2.py — append at end

# --- Sprint 5a: standards RAG integration -----------------------------


def _fake_judge_response_with_clauses(clause_ids: list[str]) -> MagicMock:
    """Build a fake call_structured tuple (Judgment, usage)."""
    from interlock.detect.significance import SignificanceJudgment
    j = SignificanceJudgment(
        severity="major",
        within_typical_tolerance=False,
        engineering_explanation="Test rationale.",
        downstream_effects=[],
        confidence=0.95,
        cited_clause_ids=clause_ids,
    )
    return (j, {"input": 0, "cache_read": 0, "cache_creation": 0, "output": 0})


def test_project_id_none_uses_base_registry(mocker) -> None:  # type: ignore[no-untyped-def]
    """Without project_id, judge sees only the base registry."""
    from interlock.pipeline import review_two_documents_full

    mocker.patch(
        "interlock.detect.significance.call_structured",
        return_value=_fake_judge_response_with_clauses(["IEEE-C57.12.00-2015-5.4"]),
    )
    result = review_two_documents_full(
        DOC_A, DOC_B, embed_fn=_trivial_embedder,
        classify_docs=False,
        use_llm_extraction=False,
        use_llm_reranker=False,
        use_entity_grounding=False,
        project_id=None,
    )
    impedance_flags = [f for f in result.flags if "%Z" in f.parameter]
    assert impedance_flags, "expected at least one %Z flag"
    cited_ids = {
        c.clause_id for f in impedance_flags for c in f.cited_clauses
    }
    # Should resolve the base registry's IEEE-C57.12.00-2015-5.4 entry.
    assert "IEEE-C57.12.00-2015-5.4" in cited_ids


def test_project_id_loads_override(mocker) -> None:  # type: ignore[no-untyped-def]
    """project_id='testproj' makes the judge see the override clause."""
    from interlock.pipeline import review_two_documents_full

    mocker.patch(
        "interlock.detect.significance.call_structured",
        return_value=_fake_judge_response_with_clauses(["IEEE-C57.12.00-2015-5.4"]),
    )
    result = review_two_documents_full(
        DOC_A, DOC_B, embed_fn=_trivial_embedder,
        classify_docs=False,
        use_llm_extraction=False,
        use_llm_reranker=False,
        use_entity_grounding=False,
        project_id="testproj",
    )
    impedance_flags = [f for f in result.flags if "%Z" in f.parameter]
    assert impedance_flags
    # Override entry has source_name starting with "TESTPROJ override"
    override_present = any(
        "TESTPROJ override" in c.source_name
        for f in impedance_flags for c in f.cited_clauses
    )
    assert override_present, (
        f"expected TESTPROJ override; got "
        f"{[c.source_name for f in impedance_flags for c in f.cited_clauses]}"
    )


def test_project_id_nonexistent_falls_back_gracefully(mocker) -> None:  # type: ignore[no-untyped-def]
    """Unknown project_id → base registry only, no exception."""
    from interlock.pipeline import review_two_documents_full

    mocker.patch(
        "interlock.detect.significance.call_structured",
        return_value=_fake_judge_response_with_clauses([]),
    )
    result = review_two_documents_full(
        DOC_A, DOC_B, embed_fn=_trivial_embedder,
        classify_docs=False,
        use_llm_extraction=False,
        use_llm_reranker=False,
        use_entity_grounding=False,
        project_id="this-project-does-not-exist",
    )
    assert isinstance(result.flags, list)


def test_use_llm_judge_false_keeps_cited_clauses_empty(mocker) -> None:  # type: ignore[no-untyped-def]
    """No judge call → Flag.cited_clauses must be empty for every flag."""
    from interlock.pipeline import review_two_documents_full

    spy = mocker.patch("interlock.detect.significance.call_structured")
    result = review_two_documents_full(
        DOC_A, DOC_B, embed_fn=_trivial_embedder,
        classify_docs=False,
        use_llm_extraction=False,
        use_llm_reranker=False,
        use_entity_grounding=False,
        use_llm_judge=False,
    )
    assert spy.call_count == 0
    for f in result.flags:
        assert f.cited_clauses == ()
```

- [ ] **Step 2: Run; expected to fail (kwarg not wired yet)**

```bash
uv run pytest tests/e2e/test_pipeline_v2.py::test_project_id_none_uses_base_registry -v
```

Expected: FAIL — `TypeError: review_two_documents_full() got an unexpected keyword argument 'project_id'`.

- [ ] **Step 3: Confirm pipeline kwarg + forwarding done in Task 4.1**

(Already done in Task 4.1 above.) Re-verify by running:

```bash
uv run pytest tests/e2e/test_pipeline_v2.py -v 2>&1 | tail -10
```

Expected: all v2 tests pass + 4 new Sprint 5a tests pass.

- [ ] **Step 4: Full regression**

```bash
uv run pytest --deselect tests/real_world 2>&1 | tail -3
```

Expected: 434 + 4 = 438 passed.

- [ ] **Step 5: Lint + mypy**

```bash
uv run ruff check src/interlock/pipeline.py tests/e2e/test_pipeline_v2.py
uv run mypy src/interlock/pipeline.py
```

Expected: clean.

- [ ] **Step 6: Commit + tag (closes Phase 29.4)**

```bash
git add src/interlock/pipeline.py tests/e2e/test_pipeline_v2.py fixtures/projects/testproj/tolerances.yaml
git commit -m "feat(pipeline): project_id kwarg + 4 e2e tests for standards-RAG"
git tag phase-29.4-pipeline-project-id -m "Sprint 5a phase 4: pipeline + project override"
git push origin main phase-29.4-pipeline-project-id
```

---

## Phase 29.5 — UI: Project ID input + 📜 chip + expander + JSON export

### Task 5.1: Sidebar Project ID input

**Files:**
- Modify: `src/interlock/ui/app.py`

- [ ] **Step 1: Add the text input**

Read `src/interlock/ui/app.py` to find the existing toggles in the sidebar. Add the project ID input AFTER the last toggle (`use_llm_judge`) and BEFORE the `st.divider()` that precedes the threshold slider:

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
    # Normalize empty string → None for the pipeline.
    project_id = project_id_input.strip() or None
```

- [ ] **Step 2: Forward `project_id` to pipeline call**

Find the `review_two_documents_full(...)` call inside the `if run:` block. Append the new kwarg next to `use_entity_grounding=use_entity_grounding,`:

```python
            review_result = review_two_documents_full(
                # ...existing kwargs...
                use_entity_grounding=use_entity_grounding,
                project_id=project_id,
            )
```

- [ ] **Step 3: Compile + lint + mypy**

```bash
uv run python -c "import py_compile; py_compile.compile('src/interlock/ui/app.py', doraise=True); print('OK')"
uv run ruff check src/interlock/ui/app.py
uv run mypy src/interlock/ui/app.py
```

Expected: OK + clean.

### Task 5.2: 📜 chip + expander citations + JSON export

**Files:**
- Modify: `src/interlock/ui/app.py`

- [ ] **Step 1: Add `_standards_chip()` helper**

Add near other helpers (next to `_entity_chip` and `_rerank_badge`):

```python
def _standards_chip(flag: Any) -> str:
    """Return compact standards chip for the flag header.

    Most-cited clause's short form → ' · 📜 <short>'.
    Multiple cites → ' · 📜 <short> +N'.
    Empty list → '' (silent).
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

- [ ] **Step 2: Append chip to flag header**

Find the existing header construction. Update:

```python
        ent_chip = _entity_chip(f)
        # v2 Sprint 5a: cited standards chip; silent when no citations.
        std_chip = _standards_chip(f)
        header = (
            f"{_SEVERITY[sev]['emoji']} **{f.parameter}** · "
            f"{dev_str} · confidence {f.confidence:.2f}"
            f"{pair_badge}{prov_badge}{ent_chip}{std_chip}{verdict_badge}"
        )
```

- [ ] **Step 3: Add citations list in expander body**

Find the equipment-binding caption block (the v2 Sprint 4.5 addition). Add the standards block AFTER it but BEFORE the citation columns (`cit_a = None`):

```python
            # v2 Sprint 5a: full list of cited standards.
            _cited = getattr(f, "cited_clauses", ()) or ()
            if _cited:
                st.markdown("**📜 Cited standards:**")
                for c in _cited:
                    st.markdown(
                        f"- **{c.source_name}** ({c.edition_year})  \n"
                        f"  _{c.summary}_"
                    )
```

- [ ] **Step 4: Update JSON export dict**

Find the Accept button's `st.session_state["decisions"][fid] = {...}` dict. Append the cited_clauses key after entity_a/entity_b:

```python
                        "entity_a": (getattr(f.a_record, "entity_tag", "") or None),
                        "entity_b": (getattr(f.b_record, "entity_tag", "") or None),
                        "cited_clauses": [  # v2 Sprint 5a
                            {
                                "clause_id": c.clause_id,
                                "edition_year": c.edition_year,
                                "source_name": c.source_name,
                                "summary": c.summary,
                            }
                            for c in (getattr(f, "cited_clauses", ()) or ())
                        ],
```

- [ ] **Step 5: Refresh judge stage label**

Find the `_STAGE_LABELS` dict (Sprint 4.5 scrub):

```python
        "judge": "AI severity review",
```

Update to:

```python
        "judge": "AI severity + standards citations",
```

- [ ] **Step 6: Compile + lint + mypy**

```bash
uv run python -c "import py_compile; py_compile.compile('src/interlock/ui/app.py', doraise=True); print('OK')"
uv run ruff check src/interlock/ui/app.py
uv run mypy src/interlock/ui/app.py
```

Expected: OK + clean.

- [ ] **Step 7: Commit + tag (closes Phase 29.5)**

```bash
git add src/interlock/ui/app.py
git commit -m "feat(ui): 📜 standards chip + cited-clauses expander + JSON export + Project ID input"
git tag phase-29.5-rag-ui -m "Sprint 5a phase 5: UI standards surface"
git push origin main phase-29.5-rag-ui
```

---

## Phase 29.6 — Live exit gate + docs + sprint exit

### Task 6.1: Live-API exit-gate tests

**Files:**
- Create: `tests/real_world/test_standards_rag_live.py`

- [ ] **Step 1: Write the slow-marked live tests**

```python
# tests/real_world/test_standards_rag_live.py
"""Sprint 5a exit gate — live-API eval of standards RAG.

Slow-marked. Skipped without ANTHROPIC_API_KEY.

Exit-gate cases:
1. %Z mismatch on Option 1 fixture → at least one cited clause referencing
   IEEE C57.12.00 (the canonical transformer-impedance standard).
2. Fault Current mismatch → at least one cited clause referencing IEEE 242
   or IEEE C37.04 (interrupting-rating / available-fault-current standards).
3. Empty-registry pathological case → judge runs without citations; flags
   still ship; cited_clauses == () everywhere.

Cost: ~$0.05 per cold run (small flag set on Option 1 fixture); $0 warm.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from dotenv import load_dotenv

from interlock.cache import disk as disk_cache

load_dotenv(override=True)

pytestmark = pytest.mark.slow

needs_anthropic = pytest.mark.skipif(
    not os.getenv("ANTHROPIC_API_KEY"),
    reason="ANTHROPIC_API_KEY required for live standards RAG",
)

DOC_A = "fixtures/pdfs/doc_a_60pct.pdf"
DOC_B = "fixtures/pdfs/doc_b_90pct.pdf"


def _trivial_embedder(names: list[str]) -> dict[str, list[float]]:
    return {n: [(hash(n) % 1000) / 1000.0, 0.0] for n in names}


@pytest.fixture(autouse=True)
def _clear_judge_cache() -> None:
    disk_cache.clear_namespace("llm-significance")
    yield


@needs_anthropic
def test_xfmr_impedance_flag_cites_ieee_c57_12_00() -> None:
    """%Z mismatch must surface ≥1 cited clause referencing IEEE C57.12.00."""
    from interlock.pipeline import review_two_documents_full

    result = review_two_documents_full(
        DOC_A, DOC_B, embed_fn=_trivial_embedder,
        same_page_only=False,
        classify_docs=False,
        use_llm_extraction=False,
        use_llm_reranker=False,
        use_entity_grounding=False,
        use_llm_judge=True,
    )
    z_flags = [f for f in result.flags if "%Z" in f.parameter or "impedance" in f.parameter.lower()]
    assert z_flags, "expected %Z flag on Option 1 fixture"
    cited_sources = [
        c.source_name for f in z_flags for c in f.cited_clauses
    ]
    assert any("C57.12.00" in s for s in cited_sources), (
        f"expected ≥1 IEEE C57.12.00 citation on %Z flag; got: {cited_sources}"
    )


@needs_anthropic
def test_fault_current_flag_cites_ieee_242_or_c37() -> None:
    """Fault Current mismatch must cite IEEE 242 or IEEE C37.04."""
    from interlock.pipeline import review_two_documents_full

    result = review_two_documents_full(
        DOC_A, DOC_B, embed_fn=_trivial_embedder,
        same_page_only=False,
        classify_docs=False,
        use_llm_extraction=False,
        use_llm_reranker=False,
        use_entity_grounding=False,
        use_llm_judge=True,
    )
    fc_flags = [f for f in result.flags if "fault" in f.parameter.lower()]
    assert fc_flags, "expected Fault Current flag on Option 1 fixture"
    cited_sources = [
        c.source_name for f in fc_flags for c in f.cited_clauses
    ]
    assert any(("242" in s) or ("C37" in s) for s in cited_sources), (
        f"expected ≥1 IEEE 242 / C37 citation on Fault Current flag; "
        f"got: {cited_sources}"
    )


@needs_anthropic
def test_empty_registry_pathological_still_ships_flags(monkeypatch, tmp_path) -> None:  # type: ignore[no-untyped-def]
    """Empty registry → judge runs without citations; flags still ship."""
    from interlock.llm_pipeline import standards as std
    from interlock.pipeline import review_two_documents_full

    empty = tmp_path / "empty.yaml"
    empty.write_text("clauses: []\n", encoding="utf-8")
    monkeypatch.setattr(std, "_CLAUSES_PATH", empty)

    result = review_two_documents_full(
        DOC_A, DOC_B, embed_fn=_trivial_embedder,
        same_page_only=False,
        classify_docs=False,
        use_llm_extraction=False,
        use_llm_reranker=False,
        use_entity_grounding=False,
        use_llm_judge=True,
    )
    assert result.flags, "flags should still ship when registry is empty"
    for f in result.flags:
        assert f.cited_clauses == (), (
            f"expected empty cited_clauses on every flag with empty registry; "
            f"got {f.cited_clauses}"
        )
```

- [ ] **Step 2: Skip check**

```bash
env -u ANTHROPIC_API_KEY uv run pytest tests/real_world/test_standards_rag_live.py -m slow -v 2>&1 | tail -5
```

Expected: 3 skipped.

- [ ] **Step 3: Run live**

```bash
uv run pytest tests/real_world/test_standards_rag_live.py -m slow -v
```

Expected: 3 passed.

If `test_xfmr_impedance_flag_cites_ieee_c57_12_00` or `test_fault_current_flag_cites_ieee_242_or_c37` fails: the judge didn't cite the supplied clauses. Iterate on the prompt block — tighten the instruction to require citation when a clause's `applicable_families` matches; add an example. Commit prompt revisions separately, then re-run.

- [ ] **Step 4: Commit live tests**

```bash
git add tests/real_world/test_standards_rag_live.py
git commit -m "test(real_world): Sprint 5a exit gate live tests (%Z+C57, FC+242/C37, empty-registry)"
```

### Task 6.2: Docs + sprint exit tag

**Files:**
- Modify: `docs/AUTHORSHIP.md`
- Modify: `docs/TDD.md`

- [ ] **Step 1: AUTHORSHIP entry**

Read `docs/AUTHORSHIP.md` to find the `## Sprint 4.5 (v2)` section. Insert Sprint 5a entry IMMEDIATELY BEFORE the Sprint 4.5 section:

```markdown
## Sprint 5a (v2) — Standards-as-RAG (curated YAML clause registry)

Shipped via 5 phase tags (`phase-29.1-clause-schemas` → `phase-29.5-rag-ui`) plus a sixth phase-29.6 live-exit-gate commit on top of `v2.4-grounding`. Exit tag: `v2.5-rag`.

**Components landed:**
- `src/interlock/llm_pipeline/schemas/clause.py` — `Clause` + `ClauseCitation` pydantic v2 frozen models.
- `src/interlock/llm_pipeline/standards.py` — `load_clauses()` (mtime-cached) + `clauses_for(family, doc_class, project_id)` + `merge_project_overrides()` + `to_citation()`. Per-entry validation; bad entries dropped + logged; failure modes (missing file, parse error, validation error) collapse to `[]`.
- `data/standards/clauses.yaml` — 10 seed entries covering impedance_pct, fault_current_a/ka, transformer_rating_va, voltage_v/kv, motor_fla_a, relay_pickup_a, fuse_amps, breaker_interrupting_ka, arc_flash_cal_cm2. Hand-paraphrased summaries; not standard verbatim.
- `src/interlock/detect/mismatch.py` — `Flag` gains `cited_clauses: tuple[ClauseCitation, ...] = ()`.
- `src/interlock/detect/significance.py` — `_build_standards_block()` injects "Applicable standards" section into judge user prompt when matches exist. `SignificanceJudgment` gains `cited_clause_ids: list[str]`. `judge()` accepts `project_id` kwarg; cache payload includes matched clause IDs so registry growth invalidates correctly. `apply_judgment_to_flag()` resolves IDs → `ClauseCitation` tuple; hallucinated IDs silently filtered.
- `src/interlock/pipeline.py` — `project_id: str | None = None` kwarg on `review_two_documents_full` + back-compat shim; forwarded to `judge()`.
- `src/interlock/ui/app.py` — sidebar "Project ID (optional)" text input; `_standards_chip()` helper for header (silent when no citations); cited-clauses list in flag expander; JSON export gains `cited_clauses` list per accepted flag; judge stage label refreshed to "AI severity + standards citations".
- `fixtures/projects/testproj/tolerances.yaml` — e2e test fixture for project override.

**Test surface delta:** +30 tests (8 schema + 12 registry + 6 judge integration + 4 e2e pipeline). Live exit-gate tests (3, slow + needs_anthropic): %Z flag cites IEEE C57.12.00; Fault Current flag cites IEEE 242 / C37.04; empty registry pathological still ships flags. Total v2 test count at `v2.5-rag`: **438 passing** + live-API slow-marked suites.

**Cost delta:** $0 incremental per flag (registry lookup is in-process); ~+200 tokens / flag on the judge prompt; ~$0.001 added per flag judged.

**Honest scope statement.** This is a curated YAML clause ontology, NOT an embedding-based RAG over standards full-text. Summaries are OUR paraphrases of the cited clauses, not verbatim quotes — reviewer can cross-check against the original standard themselves via `source_name + edition_year`. PIVOT_PLAN names it "Standards-as-RAG"; we ship structured lookup at LLM-judge prompt time. Coupled-effect graph traversal deferred to Sprint 5b. See `docs/TDD.md` § "Known limits — Sprint 5a Standards-as-RAG (v2)".

```

- [ ] **Step 2: TDD known-limits entry**

Read `docs/TDD.md` to find the Sprint 4.5 known-limits section. Insert Sprint 5a entry IMMEDIATELY AFTER it (before `## Open questions + future work`):

```markdown
## Known limits — Sprint 5a Standards-as-RAG (v2)

Sprint 5a ships a curated YAML clause registry, not an embedding-based RAG. When `use_llm_judge=True` (Sprint 4.5 default), the judge prompt receives an "Applicable standards" block listing matched clauses; judge cites them in rationale + returns the clause IDs structured. When the registry is empty or no clauses match a flag's family, the judge runs unchanged (graceful fallback).

**Architecture that generalises:**
- `Clause` + `ClauseCitation` schemas with strict field validation
- Per-entry pydantic validation on YAML load; bad entries dropped + logged
- In-memory `{family → [Clause]}` index built once per file mtime
- Per-project overrides at `fixtures/projects/<id>/tolerances.yaml` (additive + override-by-clause-id)
- Hallucination filter: judge returns clause IDs not in registry → silently dropped
- Cache key includes matched clause IDs so registry growth invalidates correctly

**Heuristics + scope deliberately limited in Sprint 5a:**
- Registry is hand-curated (~10 seed entries). Growing it is a content-curation exercise, not a code change.
- Clause summaries are OUR paraphrases. We cite source + edition so a reviewer can verify against the original standard; we do NOT distribute standard verbatim text (paywall + copyright).
- No clickable URLs in the citation UI — paraphrases live in our YAML, not on any vendor's domain.
- Doc-class filter is OR-with-empty-list semantics: empty `applicable_doc_classes` = "applies to all". Tighter scoping (e.g. "applies only when both docs are X") would need a richer rule language; out of scope.
- Coupled-effect graph traversal (Sprint 5b) NOT included here — accepting a flag does not yet surface dependent claims as deferred flags. Sprint 5b extends this.

**Generalisation plan** (post-Sprint 5a):
1. Sprint 5b — Coupled-effect graph traversal: on accept of an impedance flag, surface dependent claims (relay pickup, breaker margin, conductor sizing) as deferred flags via the existing Phase 14 SQLite claim graph.
2. Sprint 6 — Per-class gold sets + confidence calibration.
3. Backlog — Verbatim standards corpus + true embedding-based RAG (legal review per source).
4. Backlog — UI: filter visible flags by cited clause.
```

- [ ] **Step 3: Full regression**

```bash
uv run pytest --deselect tests/real_world 2>&1 | tail -3
```

Expected: 438 passed.

- [ ] **Step 4: Commit docs + sprint exit tag**

```bash
git add docs/AUTHORSHIP.md docs/TDD.md docs/superpowers/plans/2026-05-22-sprint-5a-standards-rag.md
git commit -m "docs(sprint5a): AUTHORSHIP per-phase entry + TDD known-limits + plan"
git tag v2.5-rag -m "v2.5 — Standards-as-RAG (curated YAML clause registry). 438 tests passing; 3/3 live exit gates met on Sonnet 4.5."
git push origin main v2.5-rag
```

---

## Self-review checklist (run before merge)

- [ ] Every spec section §1–§7 traces to at least one task above
- [ ] No "TBD" / "TODO" / "implement later" strings in the plan
- [ ] Every code block specifies a complete, runnable change
- [ ] Tag names follow `phase-29.<N>-<slug>` convention
- [ ] Final tag is `v2.5-rag`
- [ ] v2.4 snapshot equivalence preserved: `use_llm_judge=False` → `cited_clauses == ()`
- [ ] Hallucination filter test exists (Phase 29.3 Task 3.2)
- [ ] Empty-registry graceful test exists (Phase 29.3 + 29.6)
- [ ] Project override test exists (Phase 29.4)
- [ ] Live exit-gate tests cover %Z + Fault Current canonical flags
- [ ] Cache invalidation on registry growth test exists (Phase 29.3)
- [ ] Anti-jargon: reviewer-facing strings stay clean (📜 chip, "Cited standards", "AI severity + standards citations")
- [ ] Honest-scope disclosure shipped in `docs/TDD.md` (Task 6.2)
