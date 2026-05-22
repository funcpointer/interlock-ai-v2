"""Sprint 2 — `_build_extraction_prompt()` resolver tests."""

from __future__ import annotations

from interlock.llm_pipeline.schemas.doc_class import DocClass


def test_base_prompt_exists_and_loads() -> None:
    """Universal _base.md must exist and be non-empty."""
    from interlock.llm_pipeline import extract
    base = (extract._PROMPTS_DIR / "_base.md").read_text(encoding="utf-8")
    assert "Engineering Parameter Extraction" in base
    assert "STRICT JSON" in base


def test_per_class_injection_assembles_for_known_class() -> None:
    """A known class with a non-empty file produces base + class content."""
    from interlock.llm_pipeline.extract import _build_extraction_prompt
    prompt = _build_extraction_prompt(DocClass.coordination_study)
    assert "Engineering Parameter Extraction" in prompt
    assert "Class-specific guidance" in prompt
    assert "coordination study" in prompt.lower()
    assert "%Z" in prompt  # priority family for this class


def test_per_class_injection_handles_unknown_class() -> None:
    """DocClass.unknown falls back to base + generic-guidance stub."""
    from interlock.llm_pipeline.extract import _build_extraction_prompt
    prompt = _build_extraction_prompt(DocClass.unknown)
    assert "Engineering Parameter Extraction" in prompt
    assert "Class-specific guidance" in prompt
    assert "none" in prompt.lower()  # the generic-fallback marker


def test_every_doc_class_resolves_to_a_loadable_prompt() -> None:
    """Every DocClass enum value must produce a parseable prompt string."""
    from interlock.llm_pipeline.extract import _build_extraction_prompt
    for cls in DocClass:
        prompt = _build_extraction_prompt(cls)
        assert isinstance(prompt, str)
        assert len(prompt) > 500, f"Prompt for {cls} suspiciously short"
        assert "claims" in prompt  # schema contract present
