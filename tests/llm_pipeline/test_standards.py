"""Sprint 5a — standards registry unit tests."""

from __future__ import annotations

from pathlib import Path


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


def test_to_citation_projects_correct_fields() -> None:
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
