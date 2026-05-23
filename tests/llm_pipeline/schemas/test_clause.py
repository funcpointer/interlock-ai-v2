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
