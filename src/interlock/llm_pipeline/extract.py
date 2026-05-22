"""Track 2 LLM extraction module — per-page Sonnet call with hybrid prompts.

Phase 25.3 ships the prompt-resolver only; phase 25.4 adds the Claude call,
diskcache, hallucination guard, and the public ``extract_claims_from_doc()``
entry point.
"""

from __future__ import annotations

from pathlib import Path

from interlock.llm_pipeline.schemas.doc_class import DocClass

_PROMPTS_DIR = Path(__file__).parent / "prompts" / "extract"


def _build_extraction_prompt(doc_class: DocClass) -> str:
    """Compose base prompt + per-class injection.

    Unknown class OR empty per-class stub falls back to a generic guidance
    placeholder so extraction still runs.
    """
    base = (_PROMPTS_DIR / "_base.md").read_text(encoding="utf-8")
    class_file = _PROMPTS_DIR / f"{doc_class.value}.md"
    has_content = (
        class_file.exists()
        and class_file.is_file()
        and class_file.stat().st_size > 0
    )
    if not has_content:
        return (
            base
            + "\n\n## Class-specific guidance\n\n"
            + "_(none — extract any engineering parameters present in the text)_\n"
        )
    return (
        base
        + "\n\n## Class-specific guidance\n\n"
        + class_file.read_text(encoding="utf-8")
    )
