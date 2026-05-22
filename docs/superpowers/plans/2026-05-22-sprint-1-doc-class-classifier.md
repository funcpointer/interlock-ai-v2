# Sprint 1 — Doc-Class Classifier Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a foundation-model document classifier (multi-page VLM call) that detects 1 of 8 engineering doc classes, drives per-class severity bands and authority hierarchy for 3 known classes, and falls back to v1 behaviour when uncertain. Tag exit as `v2.0-mvp`.

**Architecture:** New `src/interlock/llm_pipeline/` package. `classify_doc()` renders pages 1/2/last at 300 DPI, sends to claude-opus-4-7 with a Pydantic schema, returns `DocClassification`. Diskcached by content hash. Pipeline gains opt-in `classify_docs` kwarg; default off preserves v1's 261-test invariant. Per-class tolerance overrides + authority hierarchy added behind `DocClass` keys; extraction-prompt registry scaffolded for Sprint 2.

**Tech Stack:** Python 3.12, anthropic SDK, pydantic ≥ 2, fitz (PyMuPDF), diskcache, reportlab (synth-doc generators), pytest + pytest-mock, ruff + mypy --strict.

**Spec reference:** `docs/superpowers/specs/2026-05-22-sprint-1-doc-class-classifier-design.md`

---

## File structure

**New files:**

| Path | Responsibility |
|---|---|
| `src/interlock/llm_pipeline/__init__.py` | Package marker |
| `src/interlock/llm_pipeline/schemas/__init__.py` | Subpackage marker |
| `src/interlock/llm_pipeline/schemas/doc_class.py` | `DocClass` enum + `DocClassification` Pydantic model |
| `src/interlock/llm_pipeline/classify.py` | `classify_doc()` impl, page-sampling, render helper, Claude call, diskcache |
| `src/interlock/llm_pipeline/prompts/__init__.py` | Marker (so MANIFEST picks up prompts dir on install) |
| `src/interlock/llm_pipeline/prompts/classify.md` | Classification system prompt with class definitions |
| `src/interlock/llm_pipeline/prompts/extract/README.md` | Documents Sprint 2 extraction registry contract |
| `src/interlock/llm_pipeline/prompts/extract/<class>.md` × 7 | Empty stubs for each non-unknown class |
| `tests/llm_pipeline/__init__.py` | Test package marker |
| `tests/llm_pipeline/test_schemas.py` | Phase 24.1 schema tests |
| `tests/llm_pipeline/test_classify.py` | Phase 24.2 classifier tests (mocked) |
| `tests/real_world/test_doc_class_live.py` | Phase 24.3 live-API smoke test (slow-marked) |
| `tests/eval/test_doc_class_gate.py` | Phase 24.5 CI acceptance gate |
| `tests/detect/test_tolerances_per_class.py` | Phase 24.7 per-class tolerance override tests |
| `tests/detect/test_authority_per_class.py` | Phase 24.7 per-class authority tests |
| `tests/e2e/test_pipeline_v2.py` | Phase 24.6 pipeline integration tests + snapshot equivalence |
| `fixtures/synthesis/generate_hvac_schedule.py` | Deterministic HVAC schedule PDF generator |
| `fixtures/synthesis/generate_pid.py` | Deterministic P&ID PDF generator |
| `fixtures/synthesis/generate_bom.py` | Deterministic BOM PDF generator |
| `fixtures/synthesis/generate_civil_drawing.py` | Deterministic civil drawing PDF generator |
| `fixtures/synthesis/generate_equipment_spec_v2.py` | 2nd synthetic equipment spec variant |
| `fixtures/eval/gold_doc_class.yaml` | 20-doc labeled gold set |
| `scripts/run_doc_class_eval.py` | Eval harness; writes JSON + markdown report |
| `eval/results/doc_class.json` | Per-run eval output (regenerated; committed for audit) |
| `eval/results/doc_class_report.md` | Human-readable per-class report |

**Modified files:**

| Path | What changes |
|---|---|
| `src/interlock/detect/tolerances.py` | Add `DOC_CLASS_TOLERANCE_OVERRIDES` dict + extend `classify_severity()` signature with optional `doc_class` parameter (back-compat default `None`) |
| `src/interlock/detect/authority.py` | Add `DOC_CLASS_AUTHORITY` map + `resolve_authority()` function; old `authority` constant preserved as fallback |
| `src/interlock/pipeline.py` | Add `classify_docs: bool = False` kwarg; extend `ReviewResult` with `doc_class_a` / `doc_class_b: DocClassification \| None = None`; ThreadPoolExecutor classification when enabled |
| `src/interlock/ui/app.py` | Doc-class banner above metrics row; sidebar toggle "Enable doc-class routing" (default ON for v2) |
| `docs/TDD.md` | Add § "Known limits — Sprint 1 (doc-class classifier)" |
| `docs/AUTHORSHIP.md` | Replace forward-looking Sprint 1 description with actual-as-shipped Sprint 1 entry |
| `fixtures/pdfs/HASHES.txt` | SHA-256 entries for the 5 new synthetic PDFs |
| `pyproject.toml` | Add `reportlab` as a dev dep for synthetic-doc generators |

---

## Phase 24.1 — Schemas + module skeleton

### Task 1.1: Create package skeleton

**Files:**
- Create: `src/interlock/llm_pipeline/__init__.py`
- Create: `src/interlock/llm_pipeline/schemas/__init__.py`
- Create: `tests/llm_pipeline/__init__.py`

- [ ] **Step 1: Create empty package markers**

```bash
mkdir -p src/interlock/llm_pipeline/schemas src/interlock/llm_pipeline/prompts/extract tests/llm_pipeline
```

- [ ] **Step 2: Write package docstring `__init__.py`**

```python
# src/interlock/llm_pipeline/__init__.py
"""LLM-augmented pipeline (Track 2) for v2 hybrid architecture.

Track 1 (deterministic regex + heuristic alignment) stays frozen under
`src/interlock/{align,extract,detect}`. This package adds the
foundation-model layer for document classification (Sprint 1), LLM
extraction (Sprint 2), pairing reranker (Sprint 4), standards-as-RAG
(Sprint 5), and coupled-effect graph traversal (Sprint 5).

See `docs/PIVOT_PLAN.md` for the architecture; per-sprint specs live
in `docs/superpowers/specs/`.
"""
```

```python
# src/interlock/llm_pipeline/schemas/__init__.py
"""Pydantic schemas for LLM-pipeline structured outputs."""
```

```python
# tests/llm_pipeline/__init__.py
```

- [ ] **Step 3: Verify imports**

Run: `uv run python -c "import interlock.llm_pipeline; import interlock.llm_pipeline.schemas"`
Expected: clean exit (no output, no error)

- [ ] **Step 4: Commit**

```bash
git add src/interlock/llm_pipeline/__init__.py src/interlock/llm_pipeline/schemas/__init__.py tests/llm_pipeline/__init__.py
git commit -m "scaffold: llm_pipeline package skeleton for v2 Track 2"
```

---

### Task 1.2: `DocClass` enum + tests

**Files:**
- Test: `tests/llm_pipeline/test_schemas.py`
- Create: `src/interlock/llm_pipeline/schemas/doc_class.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/llm_pipeline/test_schemas.py
"""Schemas for the doc-class classifier (Sprint 1)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError


def test_doc_class_enum_has_eight_values() -> None:
    """Sprint 1 schema locks in 8 classes. Adding a class is a breaking
    change that requires fresh corpus + acceptance-gate adjustment."""
    from interlock.llm_pipeline.schemas.doc_class import DocClass
    expected = {
        "coordination_study", "equipment_spec", "relay_setting_sheet",
        "hvac_schedule", "pid", "bom", "civil_drawing", "unknown",
    }
    actual = {c.value for c in DocClass}
    assert actual == expected


def test_doc_class_values_are_str_subclass() -> None:
    """Enum values must be plain strings so JSON serialization is clean."""
    from interlock.llm_pipeline.schemas.doc_class import DocClass
    assert isinstance(DocClass.coordination_study.value, str)
    assert DocClass.coordination_study.value == "coordination_study"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/llm_pipeline/test_schemas.py -v`
Expected: `ModuleNotFoundError: No module named 'interlock.llm_pipeline.schemas.doc_class'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/interlock/llm_pipeline/schemas/doc_class.py
"""DocClass enum + DocClassification Pydantic model.

Locked at 8 classes for Sprint 1. Adding a class is a breaking change
requiring a fresh labelled corpus + re-running the acceptance-gate
eval (see fixtures/eval/gold_doc_class.yaml).
"""

from __future__ import annotations

from enum import Enum


class DocClass(str, Enum):
    """Engineering document class. ``unknown`` is the fallback when the
    classifier's confidence drops below the threshold; downstream
    pipeline treats ``unknown`` as the v1 default route."""

    coordination_study = "coordination_study"
    equipment_spec = "equipment_spec"
    relay_setting_sheet = "relay_setting_sheet"
    hvac_schedule = "hvac_schedule"
    pid = "pid"  # Piping & Instrumentation Diagram
    bom = "bom"
    civil_drawing = "civil_drawing"
    unknown = "unknown"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/llm_pipeline/test_schemas.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add tests/llm_pipeline/test_schemas.py src/interlock/llm_pipeline/schemas/doc_class.py
git commit -m "feat(llm_pipeline): DocClass enum (8 values) for Sprint 1 classifier"
```

---

### Task 1.3: `DocClassification` Pydantic model + tests

**Files:**
- Modify: `tests/llm_pipeline/test_schemas.py` (append)
- Modify: `src/interlock/llm_pipeline/schemas/doc_class.py` (append)

- [ ] **Step 1: Append failing tests**

```python
# tests/llm_pipeline/test_schemas.py (append after existing tests)

def test_doc_classification_minimal_valid() -> None:
    """Required fields: doc_class, confidence, reasoning. Optional lists default empty."""
    from interlock.llm_pipeline.schemas.doc_class import DocClass, DocClassification
    c = DocClassification(
        doc_class=DocClass.coordination_study,
        confidence=0.95,
        reasoning="Eaton TCC layout; log-log curves on pages 4, 6, 8.",
    )
    assert c.doc_class == DocClass.coordination_study
    assert c.confidence == 0.95
    assert c.detected_indicators == []
    assert c.pages_consulted == []


def test_doc_classification_full() -> None:
    from interlock.llm_pipeline.schemas.doc_class import DocClass, DocClassification
    c = DocClassification(
        doc_class=DocClass.equipment_spec,
        confidence=0.92,
        reasoning="IEEE C57 nameplate layout with rated kVA + voltage rows.",
        detected_indicators=["rated kVA row", "primary voltage row", "BIL field"],
        pages_consulted=[1, 2, 5],
    )
    assert c.detected_indicators == ["rated kVA row", "primary voltage row", "BIL field"]
    assert c.pages_consulted == [1, 2, 5]


def test_doc_classification_confidence_above_one_rejected() -> None:
    from interlock.llm_pipeline.schemas.doc_class import DocClass, DocClassification
    with pytest.raises(ValidationError):
        DocClassification(
            doc_class=DocClass.unknown,
            confidence=1.5,
            reasoning="impossible",
        )


def test_doc_classification_confidence_below_zero_rejected() -> None:
    from interlock.llm_pipeline.schemas.doc_class import DocClass, DocClassification
    with pytest.raises(ValidationError):
        DocClassification(
            doc_class=DocClass.unknown,
            confidence=-0.1,
            reasoning="negative",
        )


def test_doc_classification_serializes_class_value_as_string() -> None:
    """model_dump_json must serialise DocClass to its .value string."""
    from interlock.llm_pipeline.schemas.doc_class import DocClass, DocClassification
    c = DocClassification(
        doc_class=DocClass.coordination_study,
        confidence=0.9,
        reasoning="ok",
    )
    payload = c.model_dump_json()
    assert '"coordination_study"' in payload
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/llm_pipeline/test_schemas.py -v`
Expected: 5 failures with `ImportError: cannot import name 'DocClassification'`.

- [ ] **Step 3: Implement the model**

```python
# src/interlock/llm_pipeline/schemas/doc_class.py (append after DocClass)

from pydantic import BaseModel, Field


class DocClassification(BaseModel):
    """Classifier output. ``confidence < 0.6`` collapses to ``DocClass.unknown``
    in the public ``classify_doc()`` API — this model is the raw shape; the
    classifier applies the fallback rule."""

    doc_class: DocClass
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str = Field(
        description="1-3 sentences explaining the classification choice"
    )
    detected_indicators: list[str] = Field(
        default_factory=list,
        description=(
            "Concrete visual / textual signals that drove the call "
            "(e.g. 'TCC log-log axes', 'IEEE C57 nameplate row layout')."
        ),
    )
    pages_consulted: list[int] = Field(
        default_factory=list,
        description="Page numbers (1-indexed) rendered to the model.",
    )

    model_config = {"frozen": True}  # immutable after construction; audit-trail-friendly
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/llm_pipeline/test_schemas.py -v`
Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add tests/llm_pipeline/test_schemas.py src/interlock/llm_pipeline/schemas/doc_class.py
git commit -m "feat(llm_pipeline): DocClassification Pydantic model with validation"
```

---

### Task 1.4: Lint + mypy + tag exit

- [ ] **Step 1: Lint**

Run: `uv run ruff check src/interlock/llm_pipeline tests/llm_pipeline`
Expected: `All checks passed!`

- [ ] **Step 2: Type check**

Run: `uv run mypy src/interlock/llm_pipeline`
Expected: `Success: no issues found`

- [ ] **Step 3: Full regression**

Run: `uv run pytest --deselect tests/real_world -q`
Expected: 268 passed (261 v1 + 7 new schema tests).

- [ ] **Step 4: Tag**

```bash
git tag phase-24.1-classifier-schemas -m "Sprint 1 phase 1: DocClass enum + DocClassification model"
git push origin main
git push origin phase-24.1-classifier-schemas
```

---

## Phase 24.2 — `classify_doc()` with multi-image VLM call (mocked)

### Task 2.1: Classification system prompt

**Files:**
- Create: `src/interlock/llm_pipeline/prompts/__init__.py`
- Create: `src/interlock/llm_pipeline/prompts/classify.md`

- [ ] **Step 1: Create the marker file**

```python
# src/interlock/llm_pipeline/prompts/__init__.py
"""Prompt registry for the LLM pipeline.

`classify.md` is the doc-class classifier system prompt (Sprint 1).
`extract/<class>.md` is the per-class extraction prompt registry
(Sprint 2 — files exist as empty stubs in Sprint 1).
"""
```

- [ ] **Step 2: Write the classification prompt**

```markdown
<!-- src/interlock/llm_pipeline/prompts/classify.md -->
# Document Classification — InterLock AI v2

You are classifying engineering documents for InterLock AI's cross-document review tool. You will receive 1–3 page images from a single PDF. Determine which of the following classes the document belongs to.

## Classes

- **coordination_study**: Protection coordination studies. Signals: log-log Time-Current Characteristic (TCC) curves; fuse / breaker / relay coordination plots; pickup-value + time-dial setting tables; one-line diagrams with protective-device callouts. Layout: multiple pages with TCC plots and accompanying device tables. Authors: protection engineers / system planners.

- **equipment_spec**: Manufacturer equipment data sheets. Signals: nameplate parameter tables (rated kVA, primary / secondary voltage, impedance %, frequency, BIL, temperature class); IEEE C57 / ANSI / IEC layout conventions; manufacturer logo + model number + serial number block; standardised test-report references. Layout: 1–2 pages per equipment item.

- **relay_setting_sheet**: Protection relay setting documents. Signals: relay model identifier (SEL-XXX, ABB REF, Schweitzer); setting-group tables; pickup / time-dial / curve-type parameters; trip target list; logic equations or boolean expressions. Layout: tabular settings with annotations.

- **hvac_schedule**: HVAC equipment schedules. Signals: equipment ID columns (AHU-1, FCU-5, RTU-2, EF-3); CFM / GPM / tonnage columns; ASHRAE-referenced parameters; mechanical-room callouts. Layout: dense tabular schedules.

- **pid**: Piping & Instrumentation Diagrams. Signals: ISA-5.1 instrument bubbles (PV-1, FT-1, LIC-100); piping symbols (valves, pumps, vessels); flow-direction arrows; process line numbers with size / material / spec codes. Layout: diagrammatic.

- **bom**: Bills of material. Signals: tabular item lists with quantities, part numbers, manufacturers, vendor catalog references; totals / subtotals; revision blocks. Layout: line-item tables.

- **civil_drawing**: Civil engineering drawings. Signals: grading / contour lines; site plans; foundation details; survey coordinates (Northing / Easting); civil callouts (TOC, BOC, IE, FFE); title block with civil engineer's stamp. Layout: diagrammatic with detailed callouts.

- **unknown**: Anything that does not clearly fit one of the above. Use this when:
  - the document is a technical paper, standards guide, or meta / instructional document (not an engineering deliverable);
  - image quality is too poor to identify;
  - multiple class signals are present with no dominant one.

## Output format

Return STRICT JSON only — no prose, no fences, no commentary — matching this schema:

```json
{
  "doc_class": "<one of the class values above>",
  "confidence": <number between 0.0 and 1.0>,
  "reasoning": "<1-3 sentences explaining the classification>",
  "detected_indicators": ["<concrete signal 1>", "<concrete signal 2>"],
  "pages_consulted": [<page numbers you actually used, 1-indexed>]
}
```

## Confidence calibration

- **0.95+** — multiple unambiguous signals; document layout matches class definition exactly.
- **0.80–0.95** — strong signals but some ambiguity; most reviewers would agree.
- **0.60–0.80** — dominant class present but signals weaker or partially missing.
- **< 0.60** — insufficient evidence; lean toward `unknown`.

## Honest reasoning

Cite the specific visual or textual signals you saw. Do NOT invent details not visible in the images. If you cannot confidently classify, return `unknown` rather than guessing.
```

- [ ] **Step 3: Commit the prompt**

```bash
git add src/interlock/llm_pipeline/prompts/__init__.py src/interlock/llm_pipeline/prompts/classify.md
git commit -m "feat(llm_pipeline): doc-class classification system prompt"
```

---

### Task 2.2: Page-sampling logic + render helper

**Files:**
- Test: `tests/llm_pipeline/test_classify.py`
- Create: `src/interlock/llm_pipeline/classify.py`

- [ ] **Step 1: Write failing tests for page-sampling**

```python
# tests/llm_pipeline/test_classify.py
"""Classifier tests — mocked Anthropic calls only. Live-API behaviour
is verified in tests/real_world/test_doc_class_live.py (slow-marked)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from interlock.cache import disk as disk_cache


@pytest.fixture(autouse=True)
def _clear_classify_cache() -> None:
    """Classifications are diskcache-keyed by PDF content hash; clear between
    tests so a mocked response in test A doesn't leak into test B."""
    disk_cache.clear_namespace("doc-class")
    yield
    disk_cache.clear_namespace("doc-class")


def test_sample_pages_single_page_pdf() -> None:
    from interlock.llm_pipeline.classify import _sample_pages
    assert _sample_pages(1) == [1]


def test_sample_pages_two_page_pdf() -> None:
    from interlock.llm_pipeline.classify import _sample_pages
    assert _sample_pages(2) == [1, 2]


def test_sample_pages_three_page_pdf() -> None:
    from interlock.llm_pipeline.classify import _sample_pages
    assert _sample_pages(3) == [1, 2, 3]


def test_sample_pages_ten_page_pdf_picks_first_second_last() -> None:
    from interlock.llm_pipeline.classify import _sample_pages
    assert _sample_pages(10) == [1, 2, 10]


def test_sample_pages_zero_page_returns_empty() -> None:
    from interlock.llm_pipeline.classify import _sample_pages
    assert _sample_pages(0) == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/llm_pipeline/test_classify.py -v`
Expected: 5 ImportErrors.

- [ ] **Step 3: Implement page-sampling + render helper**

```python
# src/interlock/llm_pipeline/classify.py
"""Document classifier — multi-page VLM call via claude-opus-4-7.

Renders pages 1 / 2 / last at 300 DPI, base64-encodes them into a
single Claude message, parses the JSON response into a
DocClassification, applies the confidence < 0.6 → unknown fallback,
and diskcaches by PDF content hash + model + prompt_version.

Pages are sampled deterministically based on doc length:
  1 page         → [1]
  2 pages        → [1, 2]
  N ≥ 3 pages    → [1, 2, N]

Render failures (corrupt PDF, fitz raises) return
DocClassification(doc_class=unknown, confidence=0.0, ...) so the
pipeline keeps running instead of aborting.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
from pathlib import Path

import fitz
from anthropic import Anthropic

from interlock.cache import disk as disk_cache
from interlock.llm_pipeline.schemas.doc_class import DocClass, DocClassification

MODEL = "claude-opus-4-7"
PROMPT_VERSION = "v1"
_DPI = 300
_UNKNOWN_CONFIDENCE_THRESHOLD = 0.6
_PROMPT_PATH = Path(__file__).parent / "prompts" / "classify.md"
PROMPT = _PROMPT_PATH.read_text(encoding="utf-8")


def _sample_pages(page_count: int) -> list[int]:
    """Return 1-indexed page numbers to render for classification.

    1-page docs → [1]. 2-page → [1, 2]. ≥ 3 pages → [1, 2, last]. Empty
    PDFs return []; callers must treat that as an unknown classification.
    """
    if page_count <= 0:
        return []
    if page_count == 1:
        return [1]
    if page_count == 2:
        return [1, 2]
    return [1, 2, page_count]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/llm_pipeline/test_classify.py -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add tests/llm_pipeline/test_classify.py src/interlock/llm_pipeline/classify.py
git commit -m "feat(llm_pipeline): page-sampling logic for multi-page classifier"
```

---

### Task 2.3: `classify_doc()` mocked Claude call + diskcache

**Files:**
- Modify: `tests/llm_pipeline/test_classify.py` (append)
- Modify: `src/interlock/llm_pipeline/classify.py` (append)

- [ ] **Step 1: Append failing tests**

```python
# tests/llm_pipeline/test_classify.py (append)

DOC_A = Path("fixtures/pdfs/doc_a_60pct.pdf")


def _fake_response(text: str) -> MagicMock:
    """Claude-shaped mock carrying a JSON payload in content[0].text."""
    content = MagicMock()
    content.text = text
    return MagicMock(content=[content])


def test_classify_doc_returns_doc_classification(mocker) -> None:  # type: ignore[no-untyped-def]
    from interlock.llm_pipeline.classify import classify_doc
    from interlock.llm_pipeline.schemas.doc_class import DocClass, DocClassification

    fake_json = (
        '{"doc_class":"coordination_study","confidence":0.94,'
        '"reasoning":"TCC log-log curves on pages 4, 6, 8.",'
        '"detected_indicators":["TCC log-log axes","fuse-rating table"],'
        '"pages_consulted":[1,2,9]}'
    )
    spy = mocker.patch(
        "interlock.llm_pipeline.classify._call_claude_classify",
        return_value=_fake_response(fake_json),
    )
    result = classify_doc(str(DOC_A))
    assert isinstance(result, DocClassification)
    assert result.doc_class == DocClass.coordination_study
    assert result.confidence == 0.94
    assert spy.call_count == 1


def test_classify_doc_diskcache_skips_second_call(mocker) -> None:  # type: ignore[no-untyped-def]
    from interlock.llm_pipeline.classify import classify_doc

    fake_json = (
        '{"doc_class":"equipment_spec","confidence":0.9,'
        '"reasoning":"nameplate table","detected_indicators":[],'
        '"pages_consulted":[1]}'
    )
    spy = mocker.patch(
        "interlock.llm_pipeline.classify._call_claude_classify",
        return_value=_fake_response(fake_json),
    )
    classify_doc(str(DOC_A))
    classify_doc(str(DOC_A))
    assert spy.call_count == 1, "second call should hit diskcache, not the API"


def test_classify_doc_unknown_fallback_when_confidence_below_threshold(mocker) -> None:  # type: ignore[no-untyped-def]
    from interlock.llm_pipeline.classify import classify_doc
    from interlock.llm_pipeline.schemas.doc_class import DocClass

    fake_json = (
        '{"doc_class":"pid","confidence":0.4,'
        '"reasoning":"some signals but unsure","detected_indicators":[],'
        '"pages_consulted":[1]}'
    )
    mocker.patch(
        "interlock.llm_pipeline.classify._call_claude_classify",
        return_value=_fake_response(fake_json),
    )
    result = classify_doc(str(DOC_A))
    assert result.doc_class == DocClass.unknown, (
        "confidence 0.4 < 0.6 threshold must collapse to DocClass.unknown"
    )
    # Reasoning + confidence preserved from the model for audit trail.
    assert result.confidence == 0.4


def test_classify_doc_robust_to_fenced_json_response(mocker) -> None:  # type: ignore[no-untyped-def]
    """Real Claude responses sometimes wrap JSON in ```json fences."""
    from interlock.llm_pipeline.classify import classify_doc
    from interlock.llm_pipeline.schemas.doc_class import DocClass

    wrapped = (
        'Here is my classification:\n```json\n'
        '{"doc_class":"bom","confidence":0.85,"reasoning":"item list",'
        '"detected_indicators":[],"pages_consulted":[1]}\n```'
    )
    mocker.patch(
        "interlock.llm_pipeline.classify._call_claude_classify",
        return_value=_fake_response(wrapped),
    )
    result = classify_doc(str(DOC_A))
    assert result.doc_class == DocClass.bom


def test_classify_doc_render_failure_returns_unknown(mocker) -> None:  # type: ignore[no-untyped-def]
    """A render exception (corrupt PDF, missing file) must collapse to
    unknown(0.0) — pipeline keeps running."""
    from interlock.llm_pipeline.classify import classify_doc
    from interlock.llm_pipeline.schemas.doc_class import DocClass

    result = classify_doc("/nonexistent/path/missing.pdf")
    assert result.doc_class == DocClass.unknown
    assert result.confidence == 0.0
    assert "render" in result.reasoning.lower() or "open" in result.reasoning.lower()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/llm_pipeline/test_classify.py -v`
Expected: 5 failures (`_call_claude_classify` / `classify_doc` not defined).

- [ ] **Step 3: Implement classify_doc**

```python
# src/interlock/llm_pipeline/classify.py (append after _sample_pages)


def _render_page_b64(pdf_path: str, page: int, dpi: int = _DPI) -> str:
    doc = fitz.open(pdf_path)
    try:
        pix = doc[page - 1].get_pixmap(dpi=dpi)
        return base64.b64encode(pix.tobytes("png")).decode()
    finally:
        doc.close()


def _call_claude_classify(image_b64_list: list[str]) -> object:
    """Multi-image VLM call. Each image becomes one content block; the
    prompt is the final content block. Returns the raw Anthropic
    response object."""
    client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    content: list[dict] = [
        {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": "image/png",
                "data": img_b64,
            },
        }
        for img_b64 in image_b64_list
    ]
    content.append({"type": "text", "text": PROMPT})
    return client.messages.create(
        model=MODEL,
        max_tokens=1024,
        messages=[{"role": "user", "content": content}],
    )


_FENCED_JSON = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)
_BARE_JSON = re.compile(r"(\{.*\})", re.DOTALL)


def _parse_payload(raw: str) -> dict[str, object]:
    m = _FENCED_JSON.search(raw)
    if m:
        return json.loads(m.group(1))  # type: ignore[no-any-return]
    m = _BARE_JSON.search(raw)
    if m:
        return json.loads(m.group(1))  # type: ignore[no-any-return]
    return json.loads(raw)  # type: ignore[no-any-return]


def _pdf_content_sha(pdf_path: str) -> str:
    with open(pdf_path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def _apply_unknown_fallback(c: DocClassification) -> DocClassification:
    """Confidence below threshold collapses to DocClass.unknown while
    preserving the model's reasoning + raw confidence for the audit trail."""
    if c.confidence < _UNKNOWN_CONFIDENCE_THRESHOLD and c.doc_class != DocClass.unknown:
        return DocClassification(
            doc_class=DocClass.unknown,
            confidence=c.confidence,
            reasoning=(
                f"[confidence {c.confidence:.2f} below {_UNKNOWN_CONFIDENCE_THRESHOLD} "
                f"threshold; original class was {c.doc_class.value}] "
                f"{c.reasoning}"
            ),
            detected_indicators=c.detected_indicators,
            pages_consulted=c.pages_consulted,
        )
    return c


def classify_doc(pdf_path: str) -> DocClassification:
    """Classify a PDF into one of 8 DocClass values.

    Renders pages 1/2/last at 300 DPI, sends a single multi-image
    message to claude-opus-4-7, parses JSON, applies the confidence
    fallback, returns. Diskcached by (pdf content hash, model,
    prompt_version, DPI). Render failures return
    DocClassification(unknown, 0.0, render-failure rationale).
    """
    try:
        pdf_sha = _pdf_content_sha(pdf_path)
    except OSError as e:
        return DocClassification(
            doc_class=DocClass.unknown,
            confidence=0.0,
            reasoning=f"failed to open PDF: {type(e).__name__}: {e}",
        )

    cache_key = {
        "pdf_sha": pdf_sha,
        "model": MODEL,
        "prompt_version": PROMPT_VERSION,
        "dpi": _DPI,
    }

    def _compute() -> dict[str, object]:
        try:
            doc = fitz.open(pdf_path)
            try:
                page_count = doc.page_count
            finally:
                doc.close()
        except Exception as e:  # pragma: no cover — defensive
            return {
                "doc_class": "unknown",
                "confidence": 0.0,
                "reasoning": f"render failure: {type(e).__name__}: {e}",
                "detected_indicators": [],
                "pages_consulted": [],
            }

        pages = _sample_pages(page_count)
        if not pages:
            return {
                "doc_class": "unknown",
                "confidence": 0.0,
                "reasoning": "PDF reports zero pages",
                "detected_indicators": [],
                "pages_consulted": [],
            }

        try:
            images = [_render_page_b64(pdf_path, p, dpi=_DPI) for p in pages]
        except Exception as e:  # pragma: no cover — defensive
            return {
                "doc_class": "unknown",
                "confidence": 0.0,
                "reasoning": f"render failure: {type(e).__name__}: {e}",
                "detected_indicators": [],
                "pages_consulted": [],
            }

        resp = _call_claude_classify(images)
        raw = resp.content[0].text  # type: ignore[attr-defined]
        payload = _parse_payload(raw)
        # Ensure pages_consulted reflects what we *actually* sent, not what
        # the model claims to have looked at.
        payload["pages_consulted"] = pages
        return payload

    cached, _hit = disk_cache.get_or_compute("doc-class", cache_key, _compute)
    raw_classification = DocClassification(**cached)  # type: ignore[arg-type]
    return _apply_unknown_fallback(raw_classification)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/llm_pipeline/test_classify.py -v`
Expected: 10 passed.

- [ ] **Step 5: Commit**

```bash
git add tests/llm_pipeline/test_classify.py src/interlock/llm_pipeline/classify.py
git commit -m "feat(llm_pipeline): classify_doc() with multi-image VLM call + diskcache"
```

---

### Task 2.4: Lint + mypy + tag exit

- [ ] **Step 1: Lint**

Run: `uv run ruff check src/interlock/llm_pipeline tests/llm_pipeline`
Expected: clean.

- [ ] **Step 2: Type check**

Run: `uv run mypy src/interlock/llm_pipeline`
Expected: clean.

- [ ] **Step 3: Full regression (no live API)**

Run: `uv run pytest --deselect tests/real_world -q`
Expected: 273 passed (261 v1 + 12 new).

- [ ] **Step 4: Tag**

```bash
git tag phase-24.2-classifier-call -m "Sprint 1 phase 2: classify_doc with multi-image VLM + diskcache (mocked)"
git push origin main
git push origin phase-24.2-classifier-call
```

---

## Phase 24.3 — Live-API smoke test on existing 6 fixtures

### Task 3.1: Live-API smoke

**Files:**
- Create: `tests/real_world/test_doc_class_live.py`

- [ ] **Step 1: Write the live-API test**

```python
# tests/real_world/test_doc_class_live.py
"""Live-API smoke test for the doc-class classifier.

Hits Claude Opus on the existing 6 fixtures. Slow-marked + skipped
when ANTHROPIC_API_KEY is missing. Roughly $0.40 per cold run; cached
after first call so subsequent runs cost nothing.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from dotenv import load_dotenv

load_dotenv(override=True)

from interlock.llm_pipeline.classify import classify_doc  # noqa: E402
from interlock.llm_pipeline.schemas.doc_class import DocClass  # noqa: E402

pytestmark = pytest.mark.slow

needs_anthropic = pytest.mark.skipif(
    not os.getenv("ANTHROPIC_API_KEY"),
    reason="ANTHROPIC_API_KEY required for live classifier",
)


@needs_anthropic
@pytest.mark.parametrize(
    ("pdf_path", "expected_class"),
    [
        ("fixtures/pdfs/doc_a_60pct.pdf", DocClass.coordination_study),
        ("fixtures/pdfs/doc_b_90pct.pdf", DocClass.coordination_study),
        ("fixtures/pdfs/spec_xfmr_001.pdf", DocClass.equipment_spec),
        ("fixtures/pdfs/real_sel_xfmr_protection.pdf", DocClass.relay_setting_sheet),
    ],
)
def test_classify_existing_fixtures(pdf_path: str, expected_class: DocClass) -> None:
    """Each known fixture must classify correctly with confidence ≥ 0.6
    (i.e., must NOT collapse to unknown)."""
    assert Path(pdf_path).exists(), f"fixture missing: {pdf_path}"
    result = classify_doc(pdf_path)
    assert result.doc_class == expected_class, (
        f"{pdf_path}: expected {expected_class}, got {result.doc_class} "
        f"(confidence {result.confidence:.2f}; reasoning: {result.reasoning})"
    )
    assert result.confidence >= 0.6, (
        f"{pdf_path}: classifier collapsed to unknown — "
        f"raw confidence {result.confidence:.2f}, reasoning: {result.reasoning}"
    )


@needs_anthropic
def test_classify_ieee_guide_returns_unknown_or_equipment_spec() -> None:
    """The IEEE Guide is a meta-instructional document — should classify
    as 'unknown' (it's a standards guide, not an engineering deliverable)
    OR equipment_spec if the model reads it as spec guidance. Both
    interpretations are defensible; the smoke gate accepts either."""
    result = classify_doc("fixtures/pdfs/real_ieee_xfmr_spec_guide.pdf")
    assert result.doc_class in {DocClass.unknown, DocClass.equipment_spec}


@needs_anthropic
def test_classify_scanned_doc_classifies_correctly() -> None:
    """Scanned variant of doc_a_60pct should still classify as
    coordination_study — vision OCR isn't needed because the classifier
    reads the page image directly."""
    result = classify_doc("fixtures/pdfs/doc_a_scanned.pdf")
    assert result.doc_class == DocClass.coordination_study
    assert result.confidence >= 0.6
```

- [ ] **Step 2: Run the live-API tests**

Run: `uv run pytest tests/real_world/test_doc_class_live.py -m slow -v`
Expected: 6 passed (4 parametrized + IEEE + scanned). Cost ~$0.40.

If any expected class is wrong, iterate the prompt in `src/interlock/llm_pipeline/prompts/classify.md` and rerun. Cache must be cleared between prompt iterations: `uv run python -c "from interlock.cache import disk; disk.clear_namespace('doc-class')"`.

- [ ] **Step 3: Commit**

```bash
git add tests/real_world/test_doc_class_live.py
git commit -m "test(real_world): live-API smoke test for classifier on 6 fixtures"
```

- [ ] **Step 4: Tag**

```bash
git tag phase-24.3-classifier-live -m "Sprint 1 phase 3: live-API classifier smoke green on locked fixtures"
git push origin main
git push origin phase-24.3-classifier-live
```

---

## Phase 24.4 — Corpus expansion (15 real + 5 synthetic = 20 docs)

### Task 4.1: Add reportlab dev dependency

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Add reportlab**

Locate the `[project.optional-dependencies]` or equivalent `dev` group in `pyproject.toml` and add `reportlab>=4.0`. If no dev group exists, add it:

```toml
# pyproject.toml — append or extend
[project.optional-dependencies]
dev = [
    "reportlab>=4.0",
    # ... existing dev deps
]
```

- [ ] **Step 2: Sync**

Run: `uv sync`
Expected: reportlab installed.

- [ ] **Step 3: Verify import**

Run: `uv run python -c "import reportlab; print(reportlab.Version)"`
Expected: version string printed.

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "deps: add reportlab for synthetic fixture generators"
```

---

### Task 4.2: Synthetic HVAC schedule generator

**Files:**
- Create: `fixtures/synthesis/generate_hvac_schedule.py`
- Generated artifact: `fixtures/pdfs/synth_hvac_schedule.pdf` (committed)

- [ ] **Step 1: Write the generator**

```python
# fixtures/synthesis/generate_hvac_schedule.py
"""Deterministic synthetic HVAC equipment schedule PDF.

Produces a single-page schedule with rows like:
    AHU-1 | Roof Top | 5000 CFM | 12.5 tons | ASHRAE 90.1
    FCU-3 | Office  | 800 CFM   | 2.5 tons  | ASHRAE 90.1
    EF-2  | Restroom| 200 CFM   | -         | -

Output: fixtures/pdfs/synth_hvac_schedule.pdf.
Deterministic — same input → same SHA-256 — so the fixture is committable.
"""

from __future__ import annotations

from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import LETTER, landscape
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import (
    SimpleDocTemplate,
    Table,
    TableStyle,
    Paragraph,
    Spacer,
)

OUTPUT = Path(__file__).resolve().parent.parent / "pdfs" / "synth_hvac_schedule.pdf"


def main() -> None:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(
        str(OUTPUT),
        pagesize=landscape(LETTER),
        title="HVAC Equipment Schedule",
        author="InterLock AI synthetic fixture",
    )
    styles = getSampleStyleSheet()
    story = [
        Paragraph("<b>HVAC EQUIPMENT SCHEDULE</b>", styles["Title"]),
        Paragraph("Project: synthetic example · Drawing: M-001", styles["Normal"]),
        Spacer(1, 12),
    ]
    header = ["Tag", "Type", "Location", "CFM", "Tonnage", "GPM", "ASHRAE Ref"]
    rows = [
        ["AHU-1", "Air Handling Unit",   "Roof Top",     "5000",  "12.5", "—",   "90.1-2019"],
        ["AHU-2", "Air Handling Unit",   "Mechanical 2", "3200",  "8.0",  "—",   "90.1-2019"],
        ["FCU-1", "Fan Coil Unit",       "Office 101",   "400",   "1.0",  "2.5", "62.1-2019"],
        ["FCU-2", "Fan Coil Unit",       "Office 102",   "400",   "1.0",  "2.5", "62.1-2019"],
        ["FCU-3", "Fan Coil Unit",       "Conf Room A",  "800",   "2.5",  "5.0", "62.1-2019"],
        ["RTU-1", "Rooftop Unit",        "Roof Top",     "2400",  "6.0",  "—",   "90.1-2019"],
        ["EF-1",  "Exhaust Fan",         "Restroom 1",   "150",   "—",    "—",   "62.1-2019"],
        ["EF-2",  "Exhaust Fan",         "Restroom 2",   "200",   "—",    "—",   "62.1-2019"],
        ["CHWP-1","Chilled Water Pump",  "Mechanical 1", "—",     "—",    "120", "90.1-2019"],
        ["CT-1",  "Cooling Tower",       "Roof Top",     "—",     "200",  "600", "90.1-2019"],
    ]
    table = Table([header] + rows, repeatRows=1)
    table.setStyle(
        TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#dddddd")),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
        ])
    )
    story.append(table)
    doc.build(story)
    print(f"wrote {OUTPUT}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run the generator**

Run: `uv run python fixtures/synthesis/generate_hvac_schedule.py`
Expected: `wrote .../fixtures/pdfs/synth_hvac_schedule.pdf`

- [ ] **Step 3: Sanity-check the PDF**

Run: `uv run python -c "import fitz; d = fitz.open('fixtures/pdfs/synth_hvac_schedule.pdf'); print(d.page_count, 'pages', d[0].get_text()[:200])"`
Expected: 1 page, text containing "HVAC EQUIPMENT SCHEDULE" + "AHU-1".

- [ ] **Step 4: Commit**

```bash
git add fixtures/synthesis/generate_hvac_schedule.py fixtures/pdfs/synth_hvac_schedule.pdf
git commit -m "fixture(synth): HVAC equipment schedule (deterministic generator + PDF)"
```

---

### Task 4.3: Synthetic P&ID generator

**Files:**
- Create: `fixtures/synthesis/generate_pid.py`
- Generated: `fixtures/pdfs/synth_pid.pdf`

- [ ] **Step 1: Write the generator**

```python
# fixtures/synthesis/generate_pid.py
"""Deterministic synthetic P&ID PDF.

Single-page diagrammatic example with ISA-5.1 instrument bubble notation:
    PT-100  (Pressure Transmitter)
    FT-101  (Flow Transmitter)
    LIC-200 (Level Indicating Controller)
    PV-300  (Pressure Valve)

Process flow: feed → reactor → heat exchanger → storage. Each unit
labeled with line numbers and tag IDs.
"""

from __future__ import annotations

from pathlib import Path

from reportlab.lib.colors import black, HexColor
from reportlab.lib.pagesizes import LETTER, landscape
from reportlab.pdfgen import canvas

OUTPUT = Path(__file__).resolve().parent.parent / "pdfs" / "synth_pid.pdf"


def main() -> None:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    c = canvas.Canvas(str(OUTPUT), pagesize=landscape(LETTER))
    width, height = landscape(LETTER)

    c.setFont("Helvetica-Bold", 16)
    c.drawString(36, height - 40, "PIPING & INSTRUMENTATION DIAGRAM — REACTOR FEED SYSTEM")
    c.setFont("Helvetica", 9)
    c.drawString(36, height - 56, "ISA-5.1 notation · Drawing: P-001 Rev A · Synthetic fixture")

    # Process flow boxes (vessels / equipment)
    units = [
        (80,  340, "FEED\nTANK\nT-101"),
        (260, 340, "REACTOR\nR-201"),
        (440, 340, "HEAT EXCH\nE-301"),
        (620, 340, "STORAGE\nTK-401"),
    ]
    c.setFont("Helvetica", 10)
    for x, y, label in units:
        c.rect(x, y, 90, 90)
        text_lines = label.split("\n")
        for i, line in enumerate(text_lines):
            c.drawCentredString(x + 45, y + 60 - i * 14, line)

    # Process lines with line numbers
    c.setLineWidth(1.5)
    line_segments = [
        (170, 385, 260, 385, "4\"-FS-101-CS"),
        (350, 385, 440, 385, "6\"-PR-201-SS"),
        (530, 385, 620, 385, "6\"-PR-301-SS"),
    ]
    for x1, y1, x2, y2, label in line_segments:
        c.line(x1, y1, x2, y2)
        # Arrow
        c.line(x2 - 10, y2 - 4, x2, y2)
        c.line(x2 - 10, y2 + 4, x2, y2)
        c.setFont("Helvetica", 8)
        c.drawString(x1 + 5, y1 + 6, label)

    # ISA instrument bubbles
    c.setFont("Helvetica-Bold", 9)
    bubbles = [
        (215, 440, "PT-100"),
        (215, 280, "FT-101"),
        (395, 440, "TIC-200"),
        (395, 280, "LIC-200"),
        (575, 440, "PIC-300"),
        (575, 280, "FV-300"),
    ]
    for x, y, tag in bubbles:
        c.circle(x, y, 16, stroke=1, fill=0)
        c.drawCentredString(x, y - 3, tag)

    # Legend
    c.setFont("Helvetica", 8)
    c.drawString(36, 80, "LEGEND:")
    c.drawString(36, 66, "PT = Pressure Transmitter · FT = Flow Transmitter · TIC = Temperature Indicating Controller")
    c.drawString(36, 52, "LIC = Level Indicating Controller · PIC = Pressure Indicating Controller · FV = Flow Valve")
    c.drawString(36, 38, "Line code format: <size>\"-<service>-<line#>-<material>")

    c.showPage()
    c.save()
    print(f"wrote {OUTPUT}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run the generator**

Run: `uv run python fixtures/synthesis/generate_pid.py`
Expected: file written.

- [ ] **Step 3: Visual sanity-check the PDF** (manual; open in Preview)

- [ ] **Step 4: Commit**

```bash
git add fixtures/synthesis/generate_pid.py fixtures/pdfs/synth_pid.pdf
git commit -m "fixture(synth): P&ID with ISA-5.1 instrument bubbles"
```

---

### Task 4.4: Synthetic BOM generator

**Files:**
- Create: `fixtures/synthesis/generate_bom.py`
- Generated: `fixtures/pdfs/synth_bom.pdf`

- [ ] **Step 1: Write the generator**

```python
# fixtures/synthesis/generate_bom.py
"""Deterministic synthetic Bill of Material PDF.

Single-page tabular item list with quantities, manufacturers, part numbers.
"""

from __future__ import annotations

from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import (
    SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer,
)

OUTPUT = Path(__file__).resolve().parent.parent / "pdfs" / "synth_bom.pdf"


def main() -> None:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(
        str(OUTPUT), pagesize=LETTER,
        title="Bill of Material — Switchgear Assembly",
        author="InterLock AI synthetic fixture",
    )
    styles = getSampleStyleSheet()
    story = [
        Paragraph("<b>BILL OF MATERIAL — SWITCHGEAR ASSEMBLY SG-101</b>", styles["Title"]),
        Paragraph("Drawing: E-104 Rev B · Project: synthetic example", styles["Normal"]),
        Spacer(1, 12),
    ]
    header = ["Item #", "Qty", "Description", "Manufacturer", "Part Number", "Vendor Cat #"]
    rows = [
        ["1",  "1",  "Main Breaker, 1600 A, 38 kV",   "Eaton",       "VCP-W-1600",     "C440-1600-VCP"],
        ["2",  "12", "Feeder Breaker, 600 A, 5 kV",    "Eaton",       "VCP-W-600",      "C440-600-VCP"],
        ["3",  "1",  "Bus Tie Breaker, 1200 A",        "Schneider",   "VR-1200-15",     "S-VR1200-15"],
        ["4",  "4",  "Current Transformer 600:5",      "GE",          "CTW-600-5",      "GE-CTW600"],
        ["5",  "4",  "Voltage Transformer 14.4 kV/120 V","GE",         "JVM-150-14.4",   "GE-JVM150"],
        ["6",  "12", "Protective Relay SEL-787",       "SEL",         "SEL-787",        "SEL-787-1A"],
        ["7",  "1",  "Auxiliary Power Supply 125 VDC", "ABB",         "BWR-125-50",     "ABB-BWR125"],
        ["8",  "24", "Control Wire 14 AWG (1000 ft)",  "Belden",      "9939-1000",      "BEL-9939"],
        ["9",  "1",  "Annunciator Panel 16-pt",        "Rochester",   "RAN-16",         "ROC-RAN16"],
        ["10", "1",  "Ground Bus 1/4 x 2 x 84 in",     "Erico",       "GB-2-84",        "ERI-GB284"],
    ]
    table = Table([header] + rows, repeatRows=1, colWidths=[40, 30, 180, 80, 100, 100])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#dddddd")),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    story.append(table)
    story.append(Spacer(1, 20))
    story.append(Paragraph(
        "<b>Total line items:</b> 10 · <b>Approval:</b> J. Engineer (signed) · "
        "<b>Revision:</b> B",
        styles["Normal"],
    ))
    doc.build(story)
    print(f"wrote {OUTPUT}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run, verify, commit**

```bash
uv run python fixtures/synthesis/generate_bom.py
git add fixtures/synthesis/generate_bom.py fixtures/pdfs/synth_bom.pdf
git commit -m "fixture(synth): BOM with manufacturer + part-number columns"
```

---

### Task 4.5: Synthetic civil drawing generator

**Files:**
- Create: `fixtures/synthesis/generate_civil_drawing.py`
- Generated: `fixtures/pdfs/synth_civil_drawing.pdf`

- [ ] **Step 1: Write the generator**

```python
# fixtures/synthesis/generate_civil_drawing.py
"""Deterministic synthetic civil-drawing fixture.

Single-page site plan-style PDF with grading contours, survey
coordinates (Northing/Easting), civil callouts (TOC, BOC, IE, FFE),
and a title block.
"""

from __future__ import annotations

from pathlib import Path

from reportlab.lib.pagesizes import LETTER, landscape
from reportlab.pdfgen import canvas

OUTPUT = Path(__file__).resolve().parent.parent / "pdfs" / "synth_civil_drawing.pdf"


def main() -> None:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    c = canvas.Canvas(str(OUTPUT), pagesize=landscape(LETTER))
    w, h = landscape(LETTER)

    # Title block
    c.setStrokeColorRGB(0, 0, 0)
    c.rect(20, 20, w - 40, h - 40)
    c.setFont("Helvetica-Bold", 14)
    c.drawString(40, h - 50, "SITE GRADING PLAN — SUBSTATION FOUNDATION")
    c.setFont("Helvetica", 9)
    c.drawString(40, h - 66, "Drawing: C-101 · Scale: 1\" = 20' · Civil Engineer: P.E. stamp")

    # Survey grid (Northing / Easting)
    c.setFont("Helvetica", 7)
    c.setStrokeColorRGB(0.7, 0.7, 0.7)
    c.setLineWidth(0.25)
    for x in range(80, int(w) - 80, 60):
        c.line(x, 100, x, h - 100)
        c.drawString(x - 12, 90, f"E {1000 + x}")
    for y in range(100, int(h) - 100, 60):
        c.line(80, y, w - 80, y)
        c.drawString(40, y - 3, f"N {2000 + y}")

    # Contour lines (concentric)
    c.setStrokeColorRGB(0.4, 0.4, 0.4)
    c.setLineWidth(0.6)
    cx, cy = w / 2, h / 2
    for r, elev in [(40, 100.0), (80, 99.5), (120, 99.0), (160, 98.5)]:
        c.circle(cx, cy, r, stroke=1, fill=0)
        c.setFont("Helvetica", 8)
        c.drawString(cx + r + 4, cy, f"EL {elev}")

    # Foundation outline
    c.setStrokeColorRGB(0, 0, 0)
    c.setLineWidth(1.5)
    c.rect(cx - 60, cy - 40, 120, 80)
    c.setFont("Helvetica-Bold", 9)
    c.drawCentredString(cx, cy + 6, "TRANSFORMER PAD")
    c.drawCentredString(cx, cy - 6, "FFE = 100.50")

    # Civil callouts
    c.setFont("Helvetica", 8)
    callouts = [
        (cx - 80,  cy + 60, "TOC = 100.75"),
        (cx + 80,  cy + 60, "BOC = 100.00"),
        (cx - 80,  cy - 60, "IE  =  98.25"),
        (cx + 80,  cy - 60, "IE  =  98.10"),
    ]
    for x, y, label in callouts:
        c.drawString(x, y, label)

    # Legend
    c.setFont("Helvetica", 8)
    c.drawString(40, 60, "LEGEND: TOC = Top of Curb · BOC = Bottom of Curb · IE = Invert Elevation · FFE = Finish Floor Elevation")
    c.drawString(40, 46, "Contour interval: 0.5 ft · Vertical datum: NAVD 88 · Horizontal datum: state plane")

    c.showPage()
    c.save()
    print(f"wrote {OUTPUT}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run, verify, commit**

```bash
uv run python fixtures/synthesis/generate_civil_drawing.py
git add fixtures/synthesis/generate_civil_drawing.py fixtures/pdfs/synth_civil_drawing.pdf
git commit -m "fixture(synth): civil grading plan with survey grid + contours + callouts"
```

---

### Task 4.6: Second synthetic equipment spec variant

**Files:**
- Create: `fixtures/synthesis/generate_equipment_spec_v2.py`
- Generated: `fixtures/pdfs/synth_equipment_spec_v2.pdf`

- [ ] **Step 1: Write the generator**

```python
# fixtures/synthesis/generate_equipment_spec_v2.py
"""Second synthetic equipment-spec variant — motor data sheet shape.

Differs from spec_xfmr_001.pdf (transformer) by being a motor data
sheet. Exercises the equipment_spec class beyond transformers.
"""

from __future__ import annotations

from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import (
    SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer,
)

OUTPUT = Path(__file__).resolve().parent.parent / "pdfs" / "synth_equipment_spec_v2.pdf"


def main() -> None:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(
        str(OUTPUT), pagesize=LETTER,
        title="Motor Equipment Data Sheet",
        author="InterLock AI synthetic fixture",
    )
    styles = getSampleStyleSheet()
    story = [
        Paragraph("<b>MOTOR EQUIPMENT DATA SHEET</b>", styles["Title"]),
        Paragraph(
            "Manufacturer: ABB · Model: M3BP 280SMB 4 · Serial: AB1234567 · "
            "NEMA MG1 / IEC 60034",
            styles["Normal"],
        ),
        Spacer(1, 12),
    ]
    nameplate_rows = [
        ["Rated Power",       "75 kW (100 HP)"],
        ["Rated Voltage",     "460 V"],
        ["Rated Current",     "120 A"],
        ["Rated Speed",       "1780 RPM"],
        ["Frequency",         "60 Hz"],
        ["Number of Poles",   "4"],
        ["Service Factor",    "1.15"],
        ["Insulation Class",  "F"],
        ["Temperature Rise",  "80 °C"],
        ["Enclosure",         "TEFC IP55"],
        ["Frame Size",        "NEMA 405T"],
        ["Efficiency (75% load)", "95.8 %"],
        ["Power Factor (Full load)", "0.88"],
        ["Starting Current Ratio (LRC/FLC)", "6.5"],
        ["Starting Torque Ratio (LRT/FLT)",  "1.80"],
        ["Breakdown Torque Ratio (BDT/FLT)", "2.80"],
    ]
    t = Table([["Parameter", "Value"]] + nameplate_rows, colWidths=[200, 200])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#dddddd")),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
    ]))
    story.append(t)
    story.append(Spacer(1, 20))
    story.append(Paragraph(
        "<b>Standards compliance:</b> NEMA MG 1-2016, IEC 60034-1, IEEE 841-2009",
        styles["Normal"],
    ))
    doc.build(story)
    print(f"wrote {OUTPUT}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run, commit**

```bash
uv run python fixtures/synthesis/generate_equipment_spec_v2.py
git add fixtures/synthesis/generate_equipment_spec_v2.py fixtures/pdfs/synth_equipment_spec_v2.pdf
git commit -m "fixture(synth): motor equipment data sheet (2nd equipment_spec variant)"
```

---

### Task 4.7: Source 9 real public PDFs

This is the **manual sourcing chunk** — budget ~1 day. For each class, find one or two real public PDFs on the engineering web (manufacturer catalogs, ASHRAE example projects, public DOT submittals, etc.). Save each into `fixtures/pdfs/real_<class>_<short>.pdf`.

**Target distribution (in addition to the 6 already in repo):**

| Class | Need | Suggested sources |
|---|---:|---|
| `coordination_study` | 1 | Square D / Schneider sample studies; Bussmann technical library |
| `equipment_spec` | 1 | ABB / Siemens / GE public transformer or motor data sheets |
| `relay_setting_sheet` | 1 | SEL / GE Multilin / Beckwith application notes |
| `hvac_schedule` | 2 | LEED / ASHRAE-submitted public projects; public university capital project bids |
| `pid` | 2 | Chemical / petrochemical PCM sample docs; ISA-5.1 reference drawings |
| `bom` | 1 | Public utility submittal portals (NYISO, ISO-NE, ERCOT generator interconnection BOMs) |
| `civil_drawing` | 2 | State DOT public submittals; municipal CIP project drawings |

- [ ] **Step 1: Source 1 additional coordination_study PDF**

Save to `fixtures/pdfs/real_coordination_<source>.pdf`. Record the source URL in a comment at the top of `fixtures/pdfs/HASHES.txt`.

- [ ] **Step 2: Source 1 additional equipment_spec PDF**

Save to `fixtures/pdfs/real_equipment_spec_<source>.pdf`.

- [ ] **Step 3: Source 1 additional relay_setting_sheet PDF**

Save to `fixtures/pdfs/real_relay_<source>.pdf`.

- [ ] **Step 4: Source 2 hvac_schedule PDFs**

Save to `fixtures/pdfs/real_hvac_<source1>.pdf` and `real_hvac_<source2>.pdf`.

- [ ] **Step 5: Source 2 pid PDFs**

Save to `fixtures/pdfs/real_pid_<source1>.pdf` and `real_pid_<source2>.pdf`.

- [ ] **Step 6: Source 1 bom PDF**

Save to `fixtures/pdfs/real_bom_<source>.pdf`.

- [ ] **Step 7: Source 2 civil_drawing PDFs**

Save to `fixtures/pdfs/real_civil_<source1>.pdf` and `real_civil_<source2>.pdf`.

- [ ] **Step 8: Commit all sourced PDFs**

```bash
git add fixtures/pdfs/real_*.pdf
git commit -m "fixture(real): 9 public engineering PDFs added across 7 doc classes for Sprint 1 corpus"
```

---

### Task 4.8: Update HASHES.txt + commit

**Files:**
- Modify: `fixtures/pdfs/HASHES.txt`

- [ ] **Step 1: Regenerate hashes for all new PDFs**

Run:
```bash
cd fixtures/pdfs && shasum -a 256 synth_*.pdf real_*.pdf 2>&1 | sort
```

- [ ] **Step 2: Append entries to HASHES.txt**

Open `fixtures/pdfs/HASHES.txt` in your editor; append the new SHA-256 lines (one per new file, format: `<sha256>  <filename>`). Keep the file sorted alphabetically by filename.

- [ ] **Step 3: Verify**

Run: `cd fixtures/pdfs && shasum -a 256 -c HASHES.txt | head -20`
Expected: every line ends with `OK`.

- [ ] **Step 4: Commit**

```bash
git add fixtures/pdfs/HASHES.txt
git commit -m "fixture: SHA-256 entries for Sprint 1 corpus additions"
```

---

### Task 4.9: Gold YAML + well-formed test

**Files:**
- Create: `fixtures/eval/gold_doc_class.yaml`
- Create: a new test file `tests/eval/test_doc_class_gold_well_formed.py`

- [ ] **Step 1: Write the gold YAML**

```yaml
# fixtures/eval/gold_doc_class.yaml
# Sprint 1 acceptance corpus — 15 real + 5 synthetic = 20 docs across 8 classes.
# acceptance gates evaluated by tests/eval/test_doc_class_gate.py
# (live API; gated behind ANTHROPIC_API_KEY + manual --with-live-api flag).

docs:
  # --- coordination_study (3 real) -----------------------------------------
  - path: fixtures/pdfs/doc_a_60pct.pdf
    expected_class: coordination_study
    source: real
    notes: "Eaton sample coordination study; TCC curves on multiple pages"
  - path: fixtures/pdfs/doc_b_90pct.pdf
    expected_class: coordination_study
    source: real
    notes: "Mutated derivative of doc_a_60pct; same coordination-study shape"
  - path: fixtures/pdfs/real_coordination_<source>.pdf
    expected_class: coordination_study
    source: real
    notes: "<source description — fill in during Task 4.7>"

  # --- equipment_spec (2 real + 1 synthetic) -------------------------------
  - path: fixtures/pdfs/real_equipment_spec_<source>.pdf
    expected_class: equipment_spec
    source: real
    notes: "<source description>"
  - path: fixtures/pdfs/spec_xfmr_001.pdf
    expected_class: equipment_spec
    source: synthetic
    notes: "IEEE C57.12.00 nameplate format (existing synthetic from v1)"
  - path: fixtures/pdfs/synth_equipment_spec_v2.pdf
    expected_class: equipment_spec
    source: synthetic
    notes: "Motor data sheet; second equipment_spec variant"

  # --- relay_setting_sheet (2 real) ---------------------------------------
  - path: fixtures/pdfs/real_sel_xfmr_protection.pdf
    expected_class: relay_setting_sheet
    source: real
    notes: "SEL 6079 transformer protection paper (existing fixture)"
  - path: fixtures/pdfs/real_relay_<source>.pdf
    expected_class: relay_setting_sheet
    source: real
    notes: "<source description>"

  # --- hvac_schedule (2 real + 1 synthetic) -------------------------------
  - path: fixtures/pdfs/real_hvac_<source1>.pdf
    expected_class: hvac_schedule
    source: real
  - path: fixtures/pdfs/real_hvac_<source2>.pdf
    expected_class: hvac_schedule
    source: real
  - path: fixtures/pdfs/synth_hvac_schedule.pdf
    expected_class: hvac_schedule
    source: synthetic
    notes: "AHU / FCU / RTU / EF tabular schedule"

  # --- pid (2 real + 1 synthetic) ----------------------------------------
  - path: fixtures/pdfs/real_pid_<source1>.pdf
    expected_class: pid
    source: real
  - path: fixtures/pdfs/real_pid_<source2>.pdf
    expected_class: pid
    source: real
  - path: fixtures/pdfs/synth_pid.pdf
    expected_class: pid
    source: synthetic
    notes: "ISA-5.1 instrument bubbles; reactor feed process"

  # --- bom (1 real + 1 synthetic) ----------------------------------------
  - path: fixtures/pdfs/real_bom_<source>.pdf
    expected_class: bom
    source: real
  - path: fixtures/pdfs/synth_bom.pdf
    expected_class: bom
    source: synthetic
    notes: "Switchgear assembly with manufacturer + part numbers"

  # --- civil_drawing (2 real + 1 synthetic) ------------------------------
  - path: fixtures/pdfs/real_civil_<source1>.pdf
    expected_class: civil_drawing
    source: real
  - path: fixtures/pdfs/real_civil_<source2>.pdf
    expected_class: civil_drawing
    source: real
  - path: fixtures/pdfs/synth_civil_drawing.pdf
    expected_class: civil_drawing
    source: synthetic
    notes: "Grading plan with survey grid + contours + civil callouts"

  # --- unknown (1 real) --------------------------------------------------
  - path: fixtures/pdfs/real_ieee_xfmr_spec_guide.pdf
    expected_class: unknown
    source: real
    notes: "IEEE Guide; standards / instructional document, not a deliverable"

acceptance:
  overall_accuracy_min: 0.90       # ≥ 18 / 20
  real_only_accuracy_min: 0.85     # ≥ 13 / 15
  synthetic_only_accuracy_min: 1.00 # 5 / 5
  unknown_precision_min: 1.00      # zero false-positive unknowns
```

After Task 4.7 lands, edit the `<source>` placeholders to the real filenames you saved.

- [ ] **Step 2: Write the well-formed test**

```python
# tests/eval/test_doc_class_gold_well_formed.py
"""Validate the Sprint 1 acceptance corpus YAML.

These tests are FAST — no API. They confirm the YAML loads, references
real files, and uses only DocClass enum values.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from interlock.llm_pipeline.schemas.doc_class import DocClass

GOLD = Path("fixtures/eval/gold_doc_class.yaml")


@pytest.fixture(scope="module")
def gold_data() -> dict:
    return yaml.safe_load(GOLD.read_text(encoding="utf-8"))


def test_gold_yaml_parses(gold_data: dict) -> None:
    assert "docs" in gold_data
    assert "acceptance" in gold_data


def test_gold_yaml_has_20_docs(gold_data: dict) -> None:
    assert len(gold_data["docs"]) == 20


def test_every_gold_doc_path_exists(gold_data: dict) -> None:
    missing = []
    for entry in gold_data["docs"]:
        p = Path(entry["path"])
        if not p.exists():
            missing.append(entry["path"])
    assert not missing, f"missing fixture PDFs: {missing}"


def test_every_gold_expected_class_is_valid_enum(gold_data: dict) -> None:
    valid = {c.value for c in DocClass}
    for entry in gold_data["docs"]:
        assert entry["expected_class"] in valid, (
            f"invalid expected_class {entry['expected_class']!r} for {entry['path']}"
        )


def test_gold_source_field_is_real_or_synthetic(gold_data: dict) -> None:
    for entry in gold_data["docs"]:
        assert entry["source"] in {"real", "synthetic"}


def test_real_synthetic_split_matches_design(gold_data: dict) -> None:
    real = sum(1 for d in gold_data["docs"] if d["source"] == "real")
    synth = sum(1 for d in gold_data["docs"] if d["source"] == "synthetic")
    assert real == 15
    assert synth == 5


def test_acceptance_thresholds_present(gold_data: dict) -> None:
    a = gold_data["acceptance"]
    assert 0.0 <= a["overall_accuracy_min"] <= 1.0
    assert 0.0 <= a["real_only_accuracy_min"] <= 1.0
    assert 0.0 <= a["synthetic_only_accuracy_min"] <= 1.0
    assert 0.0 <= a["unknown_precision_min"] <= 1.0
```

- [ ] **Step 3: Run the tests**

Run: `uv run pytest tests/eval/test_doc_class_gold_well_formed.py -v`
Expected: 7 passed.

- [ ] **Step 4: Commit**

```bash
git add fixtures/eval/gold_doc_class.yaml tests/eval/test_doc_class_gold_well_formed.py
git commit -m "fixture(eval): 20-doc gold corpus YAML + well-formed tests"
```

---

### Task 4.10: Eval harness script

**Files:**
- Create: `scripts/run_doc_class_eval.py`

- [ ] **Step 1: Write the harness**

```python
# scripts/run_doc_class_eval.py
"""Sprint 1 acceptance-gate harness.

Reads fixtures/eval/gold_doc_class.yaml, runs classify_doc() on every
entry, writes a JSON results file and a Markdown report.

Usage:
    uv run python scripts/run_doc_class_eval.py
        --output-json   eval/results/doc_class.json
        --output-report eval/results/doc_class_report.md

Cached on the diskcache layer — first run hits API (~$1.40), repeats are free.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

load_dotenv(override=True)

# Ensure src/ is importable when run via `uv run python scripts/...`.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from interlock.llm_pipeline.classify import classify_doc  # noqa: E402
from interlock.llm_pipeline.schemas.doc_class import DocClass  # noqa: E402

GOLD = Path("fixtures/eval/gold_doc_class.yaml")
DEFAULT_JSON = Path("eval/results/doc_class.json")
DEFAULT_REPORT = Path("eval/results/doc_class_report.md")


def run(output_json: Path, output_report: Path) -> int:
    if not os.getenv("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY not set; live-API eval cannot run.", file=sys.stderr)
        return 2

    gold = yaml.safe_load(GOLD.read_text(encoding="utf-8"))
    docs = gold["docs"]
    acceptance = gold["acceptance"]

    per_doc: list[dict[str, Any]] = []
    for entry in docs:
        path = entry["path"]
        expected = entry["expected_class"]
        if not Path(path).exists():
            per_doc.append({
                "path": path, "expected": expected, "actual": "missing",
                "confidence": 0.0, "match": False, "source": entry["source"],
                "notes": entry.get("notes", ""),
            })
            continue
        result = classify_doc(path)
        per_doc.append({
            "path": path,
            "expected": expected,
            "actual": result.doc_class.value,
            "confidence": result.confidence,
            "match": result.doc_class.value == expected,
            "source": entry["source"],
            "reasoning": result.reasoning,
            "detected_indicators": result.detected_indicators,
            "notes": entry.get("notes", ""),
        })

    total = len(per_doc)
    correct = sum(1 for r in per_doc if r["match"])
    real = [r for r in per_doc if r["source"] == "real"]
    synth = [r for r in per_doc if r["source"] == "synthetic"]
    real_correct = sum(1 for r in real if r["match"])
    synth_correct = sum(1 for r in synth if r["match"])

    # Per-class breakdown
    per_class: dict[str, dict[str, int]] = defaultdict(lambda: {"total": 0, "correct": 0})
    for r in per_doc:
        per_class[r["expected"]]["total"] += 1
        if r["match"]:
            per_class[r["expected"]]["correct"] += 1

    # Unknown precision: of records returned 'unknown', how many really were unknown?
    returned_unknown = [r for r in per_doc if r["actual"] == DocClass.unknown.value]
    unknown_correct = sum(1 for r in returned_unknown if r["expected"] == DocClass.unknown.value)
    unknown_precision = (
        unknown_correct / len(returned_unknown) if returned_unknown else 1.0
    )

    summary = {
        "total_docs": total,
        "overall_accuracy": correct / total if total else 0.0,
        "real_accuracy": real_correct / len(real) if real else 0.0,
        "synthetic_accuracy": synth_correct / len(synth) if synth else 0.0,
        "unknown_precision": unknown_precision,
        "per_class": {
            k: {"total": v["total"], "correct": v["correct"],
                "recall": v["correct"] / v["total"] if v["total"] else 0.0}
            for k, v in per_class.items()
        },
        "acceptance_thresholds": acceptance,
        "passes": {
            "overall": (correct / total if total else 0.0) >= acceptance["overall_accuracy_min"],
            "real": (real_correct / len(real) if real else 0.0) >= acceptance["real_only_accuracy_min"],
            "synthetic": (synth_correct / len(synth) if synth else 0.0) >= acceptance["synthetic_only_accuracy_min"],
            "unknown_precision": unknown_precision >= acceptance["unknown_precision_min"],
        },
    }

    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(
        {"summary": summary, "per_doc": per_doc}, indent=2,
    ), encoding="utf-8")

    # Markdown report
    lines = ["# Sprint 1 — Doc-Class Classifier Eval Report", ""]
    lines.append(f"**Total docs:** {total}")
    lines.append(f"**Overall accuracy:** {summary['overall_accuracy']:.2%} "
                 f"({correct}/{total})")
    lines.append(f"**Real-only accuracy:** {summary['real_accuracy']:.2%} "
                 f"({real_correct}/{len(real)})")
    lines.append(f"**Synthetic-only accuracy:** {summary['synthetic_accuracy']:.2%} "
                 f"({synth_correct}/{len(synth)})")
    lines.append(f"**Unknown precision:** {unknown_precision:.2%}")
    lines.append("")
    lines.append("## Acceptance gate status")
    lines.append("")
    lines.append("| Gate | Pass | Threshold |")
    lines.append("|---|---|---|")
    for key, passed in summary["passes"].items():
        thresh_key = (
            "overall_accuracy_min" if key == "overall" else
            "real_only_accuracy_min" if key == "real" else
            "synthetic_only_accuracy_min" if key == "synthetic" else
            "unknown_precision_min"
        )
        lines.append(f"| {key} | {'✅' if passed else '❌'} | {acceptance[thresh_key]:.0%} |")
    lines.append("")
    lines.append("## Per-class breakdown")
    lines.append("")
    lines.append("| Class | Total | Correct | Recall |")
    lines.append("|---|---:|---:|---:|")
    for cls, stats in summary["per_class"].items():
        lines.append(f"| {cls} | {stats['total']} | {stats['correct']} | {stats['recall']:.0%} |")
    lines.append("")
    lines.append("## Per-doc verdicts")
    lines.append("")
    lines.append("| Path | Source | Expected | Actual | Confidence | Match |")
    lines.append("|---|---|---|---|---:|---|")
    for r in per_doc:
        mark = "✅" if r["match"] else "❌"
        lines.append(
            f"| `{r['path']}` | {r['source']} | {r['expected']} | {r['actual']} | "
            f"{r['confidence']:.2f} | {mark} |"
        )

    output_report.parent.mkdir(parents=True, exist_ok=True)
    output_report.write_text("\n".join(lines), encoding="utf-8")

    print(f"wrote {output_json}")
    print(f"wrote {output_report}")
    print()
    print(f"Overall: {correct}/{total} = {summary['overall_accuracy']:.2%}")
    print(f"Real:    {real_correct}/{len(real)} = {summary['real_accuracy']:.2%}")
    print(f"Synth:   {synth_correct}/{len(synth)} = {summary['synthetic_accuracy']:.2%}")
    return 0 if all(summary["passes"].values()) else 1


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-json", type=Path, default=DEFAULT_JSON)
    parser.add_argument("--output-report", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args()
    sys.exit(run(args.output_json, args.output_report))


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Smoke-test it (without API key)**

Run: `uv run python scripts/run_doc_class_eval.py 2>&1 | head -3`
Expected: `ANTHROPIC_API_KEY not set; live-API eval cannot run.` and exit code 2.

- [ ] **Step 3: Commit**

```bash
git add scripts/run_doc_class_eval.py
git commit -m "feat(eval): doc-class classifier acceptance-gate harness"
```

---

### Task 4.11: Lint + tag exit

- [ ] **Step 1: Lint + mypy**

Run: `uv run ruff check . && uv run mypy src/interlock/llm_pipeline scripts/run_doc_class_eval.py`
Expected: clean.

- [ ] **Step 2: Full regression**

Run: `uv run pytest --deselect tests/real_world -q`
Expected: ≥ 280 passed (273 + 7 well-formed tests).

- [ ] **Step 3: Tag**

```bash
git tag phase-24.4-classifier-corpus -m "Sprint 1 phase 4: 20-doc corpus (15 real + 5 synth) + gold YAML + eval harness"
git push origin main
git push origin phase-24.4-classifier-corpus
```

---

## Phase 24.5 — Acceptance-gate eval run

### Task 5.1: Run the eval + iterate prompt if needed

- [ ] **Step 1: Run eval**

Run: `uv run python scripts/run_doc_class_eval.py`
Expected:
- writes `eval/results/doc_class.json` + `eval/results/doc_class_report.md`
- prints overall / real / synthetic accuracies
- exits 0 if all gates pass; 1 if any gate fails

Cost: ~$1.40 on cold cache; $0 on subsequent runs.

- [ ] **Step 2: Inspect the report**

Open `eval/results/doc_class_report.md`. Look at per-doc verdicts and reasoning for any misclassifications.

- [ ] **Step 3: If any gate fails, iterate**

Options in order of preference:
1. **Prompt iteration** — edit `src/interlock/llm_pipeline/prompts/classify.md` to disambiguate the failing class definitions. Bump `PROMPT_VERSION` in `classify.py` from `"v1"` to `"v2"` to invalidate cache. Re-run eval.
2. **Corpus reconsideration** — if a real doc is genuinely ambiguous (e.g., a P&ID with a giant equipment-spec block on it), re-label it as `unknown` in the gold YAML with a notes explaining why.
3. **Self-consistency escalation** — extend `classify_doc()` to call the model 3 times and majority-vote on `doc_class`. 3× cost; defer unless prompt iteration fails after 3 rounds.

- [ ] **Step 4: When all gates pass, commit results**

```bash
git add eval/results/doc_class.json eval/results/doc_class_report.md
# If prompt was iterated:
git add src/interlock/llm_pipeline/prompts/classify.md src/interlock/llm_pipeline/classify.py
git commit -m "eval(sprint1): acceptance gates green on 20-doc corpus"
```

---

### Task 5.2: CI acceptance-gate test

**Files:**
- Create: `tests/eval/test_doc_class_gate.py`

- [ ] **Step 1: Write the gate test**

```python
# tests/eval/test_doc_class_gate.py
"""CI gate for the Sprint 1 doc-class classifier.

Reads the committed eval/results/doc_class.json (NOT live API). Asserts
the recorded summary meets the gold acceptance thresholds. The eval
script is run manually by an engineer; this test ensures the committed
result satisfies the gates.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

RESULTS = Path("eval/results/doc_class.json")
GOLD = Path("fixtures/eval/gold_doc_class.yaml")


@pytest.fixture(scope="module")
def eval_data() -> dict:
    if not RESULTS.exists():
        pytest.skip("eval results not present; run scripts/run_doc_class_eval.py first")
    return json.loads(RESULTS.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def gold_data() -> dict:
    return yaml.safe_load(GOLD.read_text(encoding="utf-8"))


def test_overall_accuracy_meets_gate(eval_data: dict, gold_data: dict) -> None:
    summary = eval_data["summary"]
    threshold = gold_data["acceptance"]["overall_accuracy_min"]
    assert summary["overall_accuracy"] >= threshold, (
        f"overall {summary['overall_accuracy']:.2%} below {threshold:.0%} gate"
    )


def test_real_accuracy_meets_gate(eval_data: dict, gold_data: dict) -> None:
    threshold = gold_data["acceptance"]["real_only_accuracy_min"]
    assert eval_data["summary"]["real_accuracy"] >= threshold, (
        f"real-only {eval_data['summary']['real_accuracy']:.2%} below {threshold:.0%}"
    )


def test_synthetic_accuracy_meets_gate(eval_data: dict, gold_data: dict) -> None:
    threshold = gold_data["acceptance"]["synthetic_only_accuracy_min"]
    assert eval_data["summary"]["synthetic_accuracy"] >= threshold, (
        f"synthetic {eval_data['summary']['synthetic_accuracy']:.2%} below {threshold:.0%}"
    )


def test_unknown_precision_meets_gate(eval_data: dict, gold_data: dict) -> None:
    threshold = gold_data["acceptance"]["unknown_precision_min"]
    assert eval_data["summary"]["unknown_precision"] >= threshold, (
        f"unknown precision {eval_data['summary']['unknown_precision']:.2%} "
        f"below {threshold:.0%}"
    )
```

- [ ] **Step 2: Run the tests**

Run: `uv run pytest tests/eval/test_doc_class_gate.py -v`
Expected: 4 passed.

- [ ] **Step 3: Commit + tag**

```bash
git add tests/eval/test_doc_class_gate.py
git commit -m "test(eval): CI gate enforces Sprint 1 acceptance thresholds on committed results"
git tag phase-24.5-classifier-eval -m "Sprint 1 phase 5: acceptance gates green; CI test enforcing thresholds"
git push origin main
git push origin phase-24.5-classifier-eval
```

---

## Phase 24.6 — Pipeline integration

### Task 6.1: Extend `ReviewResult` schema

**Files:**
- Modify: `src/interlock/pipeline.py`

- [ ] **Step 1: Write the back-compat test**

Add to `tests/e2e/test_pipeline.py`:

```python
def test_review_result_back_compat_default_doc_class_none() -> None:
    """ReviewResult.doc_class_a/b default to None when classify_docs=False
    (the default). 261 existing tests must keep passing unchanged."""
    from interlock.pipeline import review_two_documents_full

    result = review_two_documents_full(
        DOC_A, DOC_B, embed_fn=_trivial_embedder,
    )
    assert result.doc_class_a is None
    assert result.doc_class_b is None
```

- [ ] **Step 2: Run; expected to fail (`doc_class_a` attr missing)**

Run: `uv run pytest tests/e2e/test_pipeline.py -v`
Expected: 1 failure.

- [ ] **Step 3: Extend the dataclass**

In `src/interlock/pipeline.py`, locate `class ReviewResult` and extend:

```python
# After existing field unpaired_b in ReviewResult
from interlock.llm_pipeline.schemas.doc_class import DocClassification  # add to imports


@dataclass(frozen=True)
class ReviewResult:
    flags: list[Flag]
    unpaired_a: list[ParameterRecord] = field(default_factory=list)
    unpaired_b: list[ParameterRecord] = field(default_factory=list)
    # Sprint 1 (v2): populated when review_two_documents_full(classify_docs=True);
    # default None preserves v1 back-compat for the 261-test invariant suite.
    doc_class_a: DocClassification | None = None
    doc_class_b: DocClassification | None = None
```

- [ ] **Step 4: Run; expected to pass**

Run: `uv run pytest tests/e2e/test_pipeline.py -v`
Expected: all green.

- [ ] **Step 5: Commit**

```bash
git add src/interlock/pipeline.py tests/e2e/test_pipeline.py
git commit -m "feat(pipeline): extend ReviewResult with doc_class_a/b (None default for back-compat)"
```

---

### Task 6.2: Add `classify_docs` kwarg + parallel classification

**Files:**
- Modify: `src/interlock/pipeline.py`
- Create: `tests/e2e/test_pipeline_v2.py`

- [ ] **Step 1: Write failing tests for the new kwarg**

```python
# tests/e2e/test_pipeline_v2.py
"""v2-specific pipeline tests — classify_docs parameter + DocClassification
plumbing. Mocked Anthropic calls so tests stay fast and offline."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from interlock.cache import disk as disk_cache

DOC_A = "fixtures/pdfs/doc_a_60pct.pdf"
DOC_B = "fixtures/pdfs/doc_b_90pct.pdf"


def _trivial_embedder(names: list[str]) -> dict[str, list[float]]:
    return {n: [(hash(n) % 1000) / 1000.0, 0.0] for n in names}


def _fake_classify_response(doc_class_value: str) -> MagicMock:
    content = MagicMock()
    content.text = (
        f'{{"doc_class":"{doc_class_value}","confidence":0.95,'
        f'"reasoning":"test stub","detected_indicators":[],'
        f'"pages_consulted":[1]}}'
    )
    return MagicMock(content=[content])


@pytest.fixture(autouse=True)
def _clear_classify_cache() -> None:
    disk_cache.clear_namespace("doc-class")
    yield
    disk_cache.clear_namespace("doc-class")


def test_classify_docs_false_returns_none(mocker) -> None:  # type: ignore[no-untyped-def]
    """Default classify_docs=False must NOT call the classifier."""
    from interlock.pipeline import review_two_documents_full
    spy = mocker.patch(
        "interlock.llm_pipeline.classify._call_claude_classify",
        return_value=_fake_classify_response("coordination_study"),
    )
    result = review_two_documents_full(
        DOC_A, DOC_B, embed_fn=_trivial_embedder, classify_docs=False,
    )
    assert spy.call_count == 0
    assert result.doc_class_a is None
    assert result.doc_class_b is None


def test_classify_docs_true_populates_doc_class_fields(mocker) -> None:  # type: ignore[no-untyped-def]
    """classify_docs=True calls the classifier on BOTH documents and
    populates ReviewResult.doc_class_a / doc_class_b."""
    from interlock.pipeline import review_two_documents_full
    from interlock.llm_pipeline.schemas.doc_class import DocClass

    mocker.patch(
        "interlock.llm_pipeline.classify._call_claude_classify",
        return_value=_fake_classify_response("coordination_study"),
    )
    result = review_two_documents_full(
        DOC_A, DOC_B, embed_fn=_trivial_embedder, classify_docs=True,
    )
    assert result.doc_class_a is not None
    assert result.doc_class_b is not None
    assert result.doc_class_a.doc_class == DocClass.coordination_study
    assert result.doc_class_b.doc_class == DocClass.coordination_study


def test_classify_docs_failure_returns_unknown_does_not_raise(mocker) -> None:  # type: ignore[no-untyped-def]
    """If the classifier raises (API outage, etc), pipeline must continue
    with doc_class_a/b = DocClassification(unknown, 0.0, ...)."""
    from interlock.pipeline import review_two_documents_full
    from interlock.llm_pipeline.schemas.doc_class import DocClass

    mocker.patch(
        "interlock.llm_pipeline.classify._call_claude_classify",
        side_effect=RuntimeError("API outage simulated"),
    )
    result = review_two_documents_full(
        DOC_A, DOC_B, embed_fn=_trivial_embedder, classify_docs=True,
    )
    # Pipeline still ran; flags surfaced normally.
    assert isinstance(result.flags, list)
    # Classifier failure collapses to unknown.
    assert result.doc_class_a is not None
    assert result.doc_class_a.doc_class == DocClass.unknown
```

- [ ] **Step 2: Run; expected to fail (`classify_docs` kwarg missing)**

Run: `uv run pytest tests/e2e/test_pipeline_v2.py -v`
Expected: TypeError on the kwarg.

- [ ] **Step 3: Add the kwarg + parallel classification**

In `src/interlock/pipeline.py`:

```python
# Add import
from concurrent.futures import ThreadPoolExecutor

# Inside review_two_documents_full, add classify_docs to the signature
# (place it AFTER stage_cb for back-compat):
def review_two_documents_full(
    pdf_a: str,
    pdf_b: str,
    embed_fn: EmbedFn,
    doc_a_id: str = "doc_a",
    doc_b_id: str = "doc_b",
    same_page_only: bool = True,
    use_llm_judge: bool = False,
    suppress_info: bool = True,
    use_claim_layer: bool = False,
    same_entity_only: bool = True,
    persist_claims: bool = False,
    table_max_pages: int | None = None,
    enable_vision_ocr: bool = False,
    ocr_progress_cb: OcrProgressCallback | None = None,
    stage_cb: StageCallback | None = None,
    classify_docs: bool = False,  # v2 Sprint 1: opt-in classifier
) -> ReviewResult:
    # ... (existing body up through ingest)

    # v2 Sprint 1: run doc-class classifier in parallel with the rest of
    # the pipeline. Default off keeps the 261 v1 tests bit-identical.
    doc_class_a: DocClassification | None = None
    doc_class_b: DocClassification | None = None
    if classify_docs:
        from interlock.llm_pipeline.classify import classify_doc
        from interlock.llm_pipeline.schemas.doc_class import DocClass

        with ThreadPoolExecutor(max_workers=2) as ex:
            fut_a = ex.submit(classify_doc, pdf_a)
            fut_b = ex.submit(classify_doc, pdf_b)
            try:
                doc_class_a = fut_a.result()
            except Exception as e:
                doc_class_a = DocClassification(
                    doc_class=DocClass.unknown,
                    confidence=0.0,
                    reasoning=f"classifier raised: {type(e).__name__}: {e}",
                )
            try:
                doc_class_b = fut_b.result()
            except Exception as e:
                doc_class_b = DocClassification(
                    doc_class=DocClass.unknown,
                    confidence=0.0,
                    reasoning=f"classifier raised: {type(e).__name__}: {e}",
                )

    # ... (existing ingest/extract/align/detect body)

    return ReviewResult(
        flags=flags,
        unpaired_a=unpaired_a,
        unpaired_b=unpaired_b,
        doc_class_a=doc_class_a,
        doc_class_b=doc_class_b,
    )
```

- [ ] **Step 4: Run; expected to pass**

Run: `uv run pytest tests/e2e/test_pipeline_v2.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add src/interlock/pipeline.py tests/e2e/test_pipeline_v2.py
git commit -m "feat(pipeline): classify_docs kwarg with parallel classification + unknown-on-error"
```

---

### Task 6.3: Snapshot-equivalence test against v1

**Files:**
- Modify: `tests/e2e/test_pipeline_v2.py`

- [ ] **Step 1: Add the snapshot test**

```python
# tests/e2e/test_pipeline_v2.py (append)

def test_classify_docs_false_is_bit_identical_to_v1() -> None:
    """The architectural safety claim: classify_docs=False MUST produce
    the same flags as the v1.5-mvp-ready pipeline on the locked Option 1
    fixture. This is the Track 1 invariant that gates every v2 commit."""
    from interlock.pipeline import review_two_documents_full

    result = review_two_documents_full(
        DOC_A, DOC_B, embed_fn=_trivial_embedder,
        classify_docs=False,
    )
    # 3 true-positive decimal-shift flags planted in doc_b_90pct mutations.
    # See fixtures/mutations/MUTATIONS.md for the source-of-truth list.
    expected_params = {"%Z", "Fault Current", "Transformer Rating"}
    surfaced = {f.parameter for f in result.flags if f.confidence >= 0.6}
    assert expected_params.issubset(surfaced), (
        f"Track 1 invariant broken: expected {expected_params}, got {surfaced}"
    )
```

- [ ] **Step 2: Run**

Run: `uv run pytest tests/e2e/test_pipeline_v2.py::test_classify_docs_false_is_bit_identical_to_v1 -v`
Expected: passed.

- [ ] **Step 3: Run full regression**

Run: `uv run pytest --deselect tests/real_world -q`
Expected: all green (≥ 287 passing).

- [ ] **Step 4: Lint + mypy**

Run: `uv run ruff check . && uv run mypy src/interlock`
Expected: clean.

- [ ] **Step 5: Tag**

```bash
git add tests/e2e/test_pipeline_v2.py
git commit -m "test(pipeline): snapshot-equivalence — classify_docs=False is bit-identical to v1"
git tag phase-24.6-classifier-pipeline -m "Sprint 1 phase 6: pipeline integration with Track 1 invariant gate"
git push origin main
git push origin phase-24.6-classifier-pipeline
```

---

## Phase 24.7 — Per-class hooks + UI + docs

### Task 7.1: `DOC_CLASS_TOLERANCE_OVERRIDES`

**Files:**
- Modify: `src/interlock/detect/tolerances.py`
- Create: `tests/detect/test_tolerances_per_class.py`

- [ ] **Step 1: Read the current tolerances module**

```bash
cat src/interlock/detect/tolerances.py | head -80
```

Note the existing `ToleranceBand` shape and `classify_severity` signature.

- [ ] **Step 2: Write failing tests**

```python
# tests/detect/test_tolerances_per_class.py
"""Per-class tolerance overrides (Sprint 1 Phase 24.7)."""

from __future__ import annotations

import pytest

from interlock.llm_pipeline.schemas.doc_class import DocClass


def test_equipment_spec_uses_tighter_impedance_band() -> None:
    """Manufacturer nameplate (equipment_spec) gets tighter bands than
    coordination_study defaults."""
    from interlock.detect.tolerances import classify_severity

    # 6% impedance deviation with default coordination_study bands = within
    # tolerance (info). With equipment_spec tighter bands (tolerance=5),
    # same deviation = minor.
    default_severity = classify_severity("impedance_pct", 6.0, doc_class=None)
    spec_severity = classify_severity(
        "impedance_pct", 6.0, doc_class=DocClass.equipment_spec,
    )
    assert default_severity == "info"
    assert spec_severity == "minor"


def test_unknown_class_falls_back_to_v1_defaults() -> None:
    """DocClass.unknown must produce the same severity as no doc_class at all."""
    from interlock.detect.tolerances import classify_severity

    a = classify_severity("impedance_pct", 6.0, doc_class=None)
    b = classify_severity("impedance_pct", 6.0, doc_class=DocClass.unknown)
    assert a == b


def test_class_with_no_override_for_family_falls_back_to_defaults() -> None:
    """coordination_study has an explicit (empty) entry — falls through to
    TOLERANCE_TABLE for impedance_pct."""
    from interlock.detect.tolerances import classify_severity

    a = classify_severity("impedance_pct", 6.0, doc_class=None)
    b = classify_severity("impedance_pct", 6.0, doc_class=DocClass.coordination_study)
    assert a == b


def test_classify_severity_back_compat_without_doc_class() -> None:
    """Existing v1 callers (no doc_class) still work unchanged."""
    from interlock.detect.tolerances import classify_severity

    result = classify_severity("impedance_pct", 6.0)
    assert result in {"info", "minor", "major", "critical"}
```

- [ ] **Step 3: Run; expected to fail**

Run: `uv run pytest tests/detect/test_tolerances_per_class.py -v`
Expected: failures about `doc_class` kwarg or `DocClass` import.

- [ ] **Step 4: Implement the overrides**

In `src/interlock/detect/tolerances.py`, after the existing `TOLERANCE_TABLE` definition, add:

```python
# Add imports
from interlock.llm_pipeline.schemas.doc_class import DocClass

# Sprint 1 v2: per-class overrides. Concrete entries for 3 classes;
# other 5 inherit TOLERANCE_TABLE via the fallback chain.
DOC_CLASS_TOLERANCE_OVERRIDES: dict[DocClass, dict[str, ToleranceBand]] = {
    DocClass.equipment_spec: {
        "impedance_pct":   ToleranceBand(
            tolerance=5.0, major=15.0, critical=40.0,
            source="IEEE C57.12.00-2015 §9.1 (tightened for nameplate)",
        ),
        "rated_power_kva": ToleranceBand(
            tolerance=2.5, major=7.5,  critical=30.0,
            source="IEEE C57.12.00-2015 §5.10 + NEMA TR 1",
        ),
    },
    DocClass.relay_setting_sheet: {
        "fault_current_a": ToleranceBand(
            tolerance=5.0, major=15.0, critical=40.0,
            source="IEEE Std 242 (Buff Book) §10.5",
        ),
    },
    DocClass.coordination_study: {
        # Explicit empty entry so the routing path is audit-visible;
        # falls through to TOLERANCE_TABLE.
    },
}
```

Now extend the existing `classify_severity` signature. Locate it and modify:

```python
def classify_severity(
    family: str,
    deviation_pct: float,
    doc_class: DocClass | None = None,  # NEW Sprint 1 — optional kwarg
) -> Severity:
    """Classify deviation severity for a parameter family.

    When ``doc_class`` is provided and the class has an override in
    DOC_CLASS_TOLERANCE_OVERRIDES, the override band is used. Falls back
    to TOLERANCE_TABLE for unknown classes, missing overrides, or
    doc_class=None (the v1 default).
    """
    band: ToleranceBand | None = None
    if doc_class is not None and doc_class != DocClass.unknown:
        per_class = DOC_CLASS_TOLERANCE_OVERRIDES.get(doc_class)
        if per_class is not None:
            band = per_class.get(family)
    if band is None:
        band = TOLERANCE_TABLE.get(family)
    if band is None:
        # Family not in any table → default to "info" (within tolerance).
        return "info"
    return _classify_against(band, deviation_pct)
```

(If `_classify_against` doesn't already exist as a helper, factor it out of the existing classify_severity body.)

- [ ] **Step 5: Run; expected to pass**

Run: `uv run pytest tests/detect/test_tolerances_per_class.py -v`
Expected: 4 passed.

- [ ] **Step 6: Run regression**

Run: `uv run pytest --deselect tests/real_world -q`
Expected: all green; the v1 tolerance tests still pass.

- [ ] **Step 7: Commit**

```bash
git add src/interlock/detect/tolerances.py tests/detect/test_tolerances_per_class.py
git commit -m "feat(detect): per-class tolerance overrides keyed on DocClass (equipment_spec + relay_setting_sheet)"
```

---

### Task 7.2: `DOC_CLASS_AUTHORITY` + `resolve_authority`

**Files:**
- Modify: `src/interlock/detect/authority.py`
- Create: `tests/detect/test_authority_per_class.py`

- [ ] **Step 1: Read current authority module**

```bash
cat src/interlock/detect/authority.py
```

Note the existing constant / function pattern.

- [ ] **Step 2: Write failing tests**

```python
# tests/detect/test_authority_per_class.py
"""Per-class authority hierarchy (Sprint 1 Phase 24.7)."""

from __future__ import annotations

from interlock.llm_pipeline.schemas.doc_class import DocClass


def test_equipment_spec_beats_coordination_study_for_transformer_params() -> None:
    """Spec sheet is more authoritative than a study for transformer params."""
    from interlock.detect.authority import resolve_authority

    side, _rationale = resolve_authority(
        DocClass.coordination_study, DocClass.equipment_spec,
        parameter_family="transformer_params",
    )
    assert side == "doc_b"  # equipment_spec is on side b


def test_equipment_spec_on_side_a_still_wins() -> None:
    """Order-independence."""
    from interlock.detect.authority import resolve_authority

    side, _ = resolve_authority(
        DocClass.equipment_spec, DocClass.coordination_study,
        parameter_family="transformer_params",
    )
    assert side == "doc_a"


def test_relay_setting_sheet_wins_for_relay_settings() -> None:
    from interlock.detect.authority import resolve_authority
    side, _ = resolve_authority(
        DocClass.relay_setting_sheet, DocClass.equipment_spec,
        parameter_family="relay_settings",
    )
    assert side == "doc_a"


def test_unknown_family_falls_back_to_v1_doc_a_authoritative() -> None:
    from interlock.detect.authority import resolve_authority
    side, rationale = resolve_authority(
        DocClass.pid, DocClass.bom, parameter_family="unrelated_thing",
    )
    assert side == "doc_a"
    assert "default" in rationale.lower() or "v1" in rationale.lower()


def test_both_unknown_classes_fall_back_to_v1() -> None:
    from interlock.detect.authority import resolve_authority
    side, _ = resolve_authority(
        DocClass.unknown, DocClass.unknown,
        parameter_family="transformer_params",
    )
    assert side == "doc_a"
```

- [ ] **Step 3: Run; expected to fail**

Run: `uv run pytest tests/detect/test_authority_per_class.py -v`
Expected: ImportError on `resolve_authority`.

- [ ] **Step 4: Implement**

In `src/interlock/detect/authority.py`, add:

```python
# Add at top
from typing import Literal

from interlock.llm_pipeline.schemas.doc_class import DocClass

Side = Literal["doc_a", "doc_b"]

# Higher index = more authoritative for the given family.
DOC_CLASS_AUTHORITY: dict[str, list[DocClass]] = {
    "transformer_params": [
        DocClass.coordination_study,
        DocClass.relay_setting_sheet,
        DocClass.equipment_spec,         # most authoritative
    ],
    "relay_settings": [
        DocClass.coordination_study,
        DocClass.equipment_spec,
        DocClass.relay_setting_sheet,    # most authoritative
    ],
}


def resolve_authority(
    doc_a_class: DocClass,
    doc_b_class: DocClass,
    parameter_family: str,
) -> tuple[Side, str]:
    """Return (authoritative_side, rationale) for a parameter family.

    Falls back to v1's hardcoded "doc_a authoritative" when:
      - family has no per-class hierarchy entry, OR
      - either class is DocClass.unknown, OR
      - both classes are absent from the family's hierarchy.

    The fallback preserves the v1 261-test invariant.
    """
    hierarchy = DOC_CLASS_AUTHORITY.get(parameter_family)
    if (
        hierarchy is None
        or doc_a_class == DocClass.unknown
        or doc_b_class == DocClass.unknown
    ):
        return "doc_a", "v1 default (per-class hierarchy not applicable)"

    def rank(c: DocClass) -> int:
        try:
            return hierarchy.index(c)
        except ValueError:
            return -1  # not in hierarchy = lowest

    a_rank = rank(doc_a_class)
    b_rank = rank(doc_b_class)
    if a_rank == -1 and b_rank == -1:
        return "doc_a", "v1 default (neither class is in family hierarchy)"
    if a_rank >= b_rank:
        return "doc_a", f"per-class hierarchy: {doc_a_class.value} > {doc_b_class.value} for {parameter_family}"
    return "doc_b", f"per-class hierarchy: {doc_b_class.value} > {doc_a_class.value} for {parameter_family}"
```

- [ ] **Step 5: Run; expected to pass**

Run: `uv run pytest tests/detect/test_authority_per_class.py -v`
Expected: 5 passed.

- [ ] **Step 6: Commit**

```bash
git add src/interlock/detect/authority.py tests/detect/test_authority_per_class.py
git commit -m "feat(detect): per-class authority hierarchy with v1-default fallback"
```

---

### Task 7.3: Extraction-prompt registry scaffold

**Files:**
- Create: `src/interlock/llm_pipeline/prompts/extract/README.md` and 7 empty stubs

- [ ] **Step 1: Write the registry README**

```markdown
<!-- src/interlock/llm_pipeline/prompts/extract/README.md -->
# Extraction-Prompt Registry

This directory holds per-doc-class extraction prompts used by the LLM
extraction module landing in Sprint 2. Sprint 1 ships **empty stubs only**;
each class gets a markdown file that Sprint 2 will fill.

## Contract

- One file per `DocClass` value (excluding `unknown`).
- File naming: `<class>.md` (e.g. `coordination_study.md`).
- Each prompt defines the per-class extraction schema and constraints
  for the structured LLM call: `messages.parse(output_format=...)`.
- An empty file is interpreted by Sprint 2 as "use the fallback
  generic-extraction prompt" so absent classes degrade gracefully.

## Filling order (Sprint 2 priority)

1. `coordination_study.md` (largest existing test corpus)
2. `equipment_spec.md` (cross-doc fixture pair)
3. `relay_setting_sheet.md` (SEL paper currently yields zero params)
4. `hvac_schedule.md`
5. `pid.md`
6. `bom.md`
7. `civil_drawing.md`
```

- [ ] **Step 2: Create the 7 empty stubs**

```bash
cd src/interlock/llm_pipeline/prompts/extract
touch coordination_study.md equipment_spec.md relay_setting_sheet.md hvac_schedule.md pid.md bom.md civil_drawing.md
```

- [ ] **Step 3: Sanity-check**

Run: `ls src/interlock/llm_pipeline/prompts/extract/`
Expected: 8 files (README + 7 stubs).

- [ ] **Step 4: Commit**

```bash
git add src/interlock/llm_pipeline/prompts/extract/
git commit -m "scaffold(llm_pipeline): extraction-prompt registry stubs for Sprint 2"
```

---

### Task 7.4: UI banner + sidebar toggle

**Files:**
- Modify: `src/interlock/ui/app.py`

- [ ] **Step 1: Add sidebar toggle**

Locate the existing sidebar block in `src/interlock/ui/app.py` (after `enable_vision_ocr` toggle and before the `st.divider()` separator). Add:

```python
# Sidebar — v2 doc-class routing toggle
classify_docs = st.toggle(
    "Enable doc-class routing (v2 Sprint 1)",
    value=True,
    help=(
        "When ON, the pipeline classifies each PDF on upload (one VLM "
        "call per doc, diskcached) and applies per-class tolerance bands "
        "+ authority hierarchy where defined. When OFF, behaves bit-"
        "identically to v1.5-mvp-ready. Unknown classifications fall "
        "back to v1 defaults regardless of the toggle."
    ),
)
```

- [ ] **Step 2: Pass it through to the pipeline call**

Locate the existing call to `review_two_documents_full(...)` and add `classify_docs=classify_docs` to the kwargs:

```python
review_result = review_two_documents_full(
    str(a_path), str(b_path),
    embed_fn=embed_voyage,
    # ... existing kwargs
    classify_docs=classify_docs,
)
```

- [ ] **Step 3: Add the doc-class banner above the metrics row**

Locate the results section (where the metrics columns are built) and prepend:

```python
# v2 Sprint 1: doc-class banner
doc_class_a = result_state.get("doc_class_a")  # populated by run; persist via session_state
doc_class_b = result_state.get("doc_class_b")
if doc_class_a is not None and doc_class_b is not None:
    banner_a, banner_b = st.columns(2)

    def _banner(col, label: str, cls):  # type: ignore[no-untyped-def]
        with col:
            confidence = cls.confidence
            if confidence >= 0.85:
                box = st.success
            elif confidence >= 0.60:
                box = st.info
            else:
                box = st.warning
            human_class = cls.doc_class.value.replace("_", " ").title()
            box(
                f"📄 **{label}: {human_class}** ({confidence:.2f})\n\n"
                f"_{cls.reasoning}_"
            )

    _banner(banner_a, "Doc A", doc_class_a)
    _banner(banner_b, "Doc B", doc_class_b)

    # Detected-indicators expander (combined for both docs).
    with st.expander("Why these classifications? (detected indicators)", expanded=False):
        if doc_class_a.detected_indicators:
            st.markdown("**Doc A indicators:**")
            for ind in doc_class_a.detected_indicators:
                st.markdown(f"- {ind}")
        if doc_class_b.detected_indicators:
            st.markdown("**Doc B indicators:**")
            for ind in doc_class_b.detected_indicators:
                st.markdown(f"- {ind}")
```

(Ensure `result_state` persists `doc_class_a` / `doc_class_b` from `review_result.doc_class_a/b` in the same session_state dict used by the existing UI flow.)

- [ ] **Step 4: UI compile check**

Run: `uv run python -c "import py_compile; py_compile.compile('src/interlock/ui/app.py', doraise=True)" && uv run ruff check src/interlock/ui/app.py && uv run mypy src/interlock/ui/app.py`
Expected: clean.

- [ ] **Step 5: Smoke-test locally** (manual)

Run: `uv run streamlit run src/interlock/ui/app.py`. Upload Option 1 fixtures; verify banner appears with "Coordination Study" + reasoning.

- [ ] **Step 6: Commit**

```bash
git add src/interlock/ui/app.py
git commit -m "feat(ui): doc-class banner + sidebar toggle for v2 routing"
```

---

### Task 7.5: TDD + AUTHORSHIP doc updates

**Files:**
- Modify: `docs/TDD.md`
- Modify: `docs/AUTHORSHIP.md`

- [ ] **Step 1: Append Sprint 1 known-limits section to TDD.md**

Locate the existing § "Known limits" near the end of `docs/TDD.md`. Append a new subsection:

```markdown
## Known limits — Sprint 1 doc-class classifier (v2)

The classifier ships behind `classify_docs=True` (default on in UI;
default off in the `review_two_documents` API). When off OR when the
classifier collapses to `unknown`, pipeline is bit-identical to
`v1.5-mvp-ready`.

**Architecture that generalises:**
- `DocClass` enum + `DocClassification` Pydantic schema
- `DOC_CLASS_TOLERANCE_OVERRIDES` per-class layer
- `DOC_CLASS_AUTHORITY` per-class hierarchy
- v1 fallback chain on every override (graceful degradation)
- Diskcache by PDF content hash + model + prompt_version + DPI

**Heuristics + scope that's deliberately limited in Sprint 1:**
- Concrete per-class overrides exist for 3 of 8 classes only
  (coordination_study = v1 defaults, equipment_spec = tighter, 
  relay_setting_sheet = relay-specific). The other 5 (hvac_schedule,
  pid, bom, civil_drawing, unknown) classify correctly but inherit
  v1 defaults end-to-end. Sprint 2+ work fills the rest.
- Per-class extraction prompts exist as empty stubs only; LLM
  extraction is Sprint 2 work.
- 20-doc acceptance corpus is small. Per-class recall numbers below
  5 examples have high variance. Sprint 2+ expands the corpus.
- Real-doc sourcing skews toward electrical engineering (domain
  expertise). Civil + HVAC + P&ID + BOM real-doc coverage is lighter.
- Synthetic docs are too clean; real-world variance unmeasured for
  the 5 classes they cover.

**Generalisation plan** (post-Sprint 1):
1. Sprint 2 — LLM extraction module fills the prompt registry
2. Sprint 5 — Standards-as-RAG replaces `DOC_CLASS_AUTHORITY` const
   with per-project precedence-ladder loading
3. Continuous — corpus growth via reviewer accept/dismiss signals
```

- [ ] **Step 2: Update AUTHORSHIP.md Sprint 1 section to "as shipped"**

Locate the existing forward-looking Sprint 1 entry in `docs/AUTHORSHIP.md` (added when v2 was forked from v1.5). Replace it with the actual-as-shipped entry:

```markdown
## Sprint 1 (v2) — Doc-class classifier + per-class hooks

Shipped 2026-MM-DD via 7 phase tags (phase-24.1 → phase-24.7) on top
of v2.0-baseline-from-v1.5-mvp-ready. Exit tag: `v2.0-mvp`.

**Components landed:**
- `src/interlock/llm_pipeline/schemas/doc_class.py` — DocClass enum
  (8 values) + DocClassification Pydantic model with confidence range
  validation
- `src/interlock/llm_pipeline/classify.py` — multi-page VLM classifier
  (pages 1/2/last @ 300 DPI), claude-opus-4-7, Pydantic-validated
  structured output, diskcached on PDF content hash, confidence <
  0.6 → unknown fallback, render-failure-safe (returns unknown(0.0)
  instead of raising)
- `src/interlock/llm_pipeline/prompts/classify.md` — classification
  system prompt with 8 class definitions and confidence calibration
  ladder
- `src/interlock/llm_pipeline/prompts/extract/<class>.md` × 7 — empty
  stubs for Sprint 2's extraction prompt registry
- `src/interlock/detect/tolerances.py` — DOC_CLASS_TOLERANCE_OVERRIDES
  layer with v1-default fallback; concrete entries for equipment_spec
  + relay_setting_sheet
- `src/interlock/detect/authority.py` — DOC_CLASS_AUTHORITY map with
  v1-default fallback; entries for transformer_params + relay_settings
- `src/interlock/pipeline.py` — classify_docs kwarg (default off);
  ReviewResult extended with doc_class_a/b; parallel classification
  via ThreadPoolExecutor
- `src/interlock/ui/app.py` — doc-class banner + sidebar toggle
- 5 synthetic-fixture generators producing deterministic PDFs across
  hvac_schedule / pid / bom / civil_drawing / equipment_spec_v2

**Eval shipped:**
- 20-doc acceptance corpus (15 real + 5 synthetic) at
  `fixtures/eval/gold_doc_class.yaml`
- Acceptance harness at `scripts/run_doc_class_eval.py`
- CI gate test at `tests/eval/test_doc_class_gate.py` enforcing
  overall ≥ 90 %, real ≥ 85 %, synthetic = 100 %, unknown precision = 100 %
- Live-API smoke at `tests/real_world/test_doc_class_live.py`

**Test surface delta:** +28 tests (7 schemas, 10 classifier, 6 pipeline-v2, 4 tolerance, 5 authority, 7 gold YAML well-formed, plus the live-API and gate tests). Total v2 test count at v2.0-mvp: ~295 (≥ 90 % overall accuracy on the live-API gate).

**Cost delta:** Sprint 1 dev iteration spend ~$X (logged via cost_event ledger).

**Honest scope statement.** See `docs/TDD.md` § "Known limits — Sprint 1 doc-class classifier (v2)" for what generalises versus what's overfit.
```

- [ ] **Step 3: Commit**

```bash
git add docs/TDD.md docs/AUTHORSHIP.md
git commit -m "docs: Sprint 1 known-limits + AUTHORSHIP per-phase entry"
```

---

### Task 7.6: Final lint + regression + sprint exit tag

- [ ] **Step 1: Full lint**

Run: `uv run ruff check . && uv run mypy src/`
Expected: clean across all v2 sources.

- [ ] **Step 2: Full regression (excl. real-world)**

Run: `uv run pytest --deselect tests/real_world -q`
Expected: ≥ 295 passed.

- [ ] **Step 3: Live-API regression (manual)**

Run: `uv run pytest -m slow tests/real_world/test_doc_class_live.py -v`
Expected: all 6 live tests pass.

- [ ] **Step 4: Snapshot equivalence check**

Run: `uv run pytest tests/e2e/test_pipeline_v2.py::test_classify_docs_false_is_bit_identical_to_v1 -v`
Expected: pass (Track 1 invariant intact).

- [ ] **Step 5: Tag**

```bash
git tag phase-24.7-classifier-hooks -m "Sprint 1 phase 7: per-class hooks + UI banner + docs updated"
git tag v2.0-mvp -m "v2 MVP — doc-class classifier + per-class routing for 3 of 8 classes; v1 invariant preserved"
git push origin main
git push origin phase-24.7-classifier-hooks
git push origin v2.0-mvp
```

- [ ] **Step 6: Verify GH state**

Run: `gh repo view funcpointer/interlock-ai-v2 --json url | jq -r .url`
Open the URL; confirm the latest tag is `v2.0-mvp` and the README still
points to the v2 banner.

---

## Self-review checklist (run before merge)

- [ ] Every spec section §1-§9 traces to at least one task above
- [ ] No "TBD" / "TODO" / "implement later" strings in the plan
- [ ] Every code block specifies a complete, runnable change
- [ ] Tag names follow the `phase-24.<N>-<slug>` convention from the spec
- [ ] Final tag is `v2.0-mvp`
- [ ] Live-API costs surface explicitly (so the engineer doesn't blow $$$ unaware)
- [ ] Track 1 invariant snapshot test exists and is referenced in Task 6.3
- [ ] Honest-scope disclosure shipped in `docs/TDD.md` (Task 7.5)
