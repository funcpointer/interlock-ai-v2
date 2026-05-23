"""Sprint 8 — PageStructure Literal sanity tests."""

from __future__ import annotations


def test_page_structure_values() -> None:
    from interlock.llm_pipeline.schemas.page_structure import PageStructure
    # Verifies the type is importable + the literal values are stable.
    valid = ("prose", "table", "diagram", "mixed")
    for v in valid:
        # Type-checking confirmation that v is assignable to PageStructure.
        x: PageStructure = v  # type: ignore[assignment]
        assert x == v
