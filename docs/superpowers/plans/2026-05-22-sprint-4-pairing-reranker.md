# Sprint 4 — LLM Pairing Reranker Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a Track 2 reranker that fixes Track 1's heuristic "weak pair" verdicts with LLM-reasoned (score, rationale, decline_to_pair) outcomes — replacing the generic `⚠️ weak pair` badge with reasoned `🤖 Reranked` rationale.

**Architecture:** Thin post-processing layer (`src/interlock/llm_pipeline/pair.py`) runs after `combine_alignments` and before `detect_flags`. One Claude Sonnet 4.5 call per weak pair, parallel via `ThreadPoolExecutor`, diskcache by record hashes. Strong pairs (`pairing_confidence >= 0.75`) pass through untouched. Opt-in via `use_llm_reranker=False` kwarg; default-off preserves v2.2 snapshot equivalence bit-for-bit. Decline-to-pair drops the pair; A and B records flow into the existing `unpaired_a/b` lists.

**Tech Stack:** Python 3.12, anthropic SDK, Pydantic v2, diskcache, ThreadPoolExecutor, Streamlit, pytest + pytest-mock, ruff + mypy --strict.

**Spec reference:** `docs/superpowers/specs/2026-05-22-sprint-4-pairing-reranker-design.md`

---

## File structure

**New files:**

| Path | Responsibility |
|---|---|
| `src/interlock/llm_pipeline/schemas/pair.py` | `PairVerdict` pydantic v2 model |
| `src/interlock/llm_pipeline/pair.py` | `rerank_weak_pairs()` orchestration + `_call_claude_pair()` SDK wrapper + diskcache + parallel executor + hallucination guard + sibling-row context builder |
| `src/interlock/llm_pipeline/prompts/pair.md` | System prompt + JSON schema example |
| `tests/llm_pipeline/schemas/test_pair.py` | Phase 27.1 — verdict validation |
| `tests/align/test_aligned_pair_back_compat.py` | Phase 27.1 — back-compat default tests |
| `tests/llm_pipeline/test_pair.py` | Phase 27.2 — reranker unit tests |
| `tests/real_world/test_reranker_live.py` | Phase 27.5 — slow + needs_anthropic exit-gate tests |

**Modified:**

| Path | Change |
|---|---|
| `src/interlock/align/exact.py` | `AlignedPair` gains `rerank_rationale: str \| None = None`, `reranked: bool = False` |
| `src/interlock/detect/mismatch.py` | `Flag` gains `rerank_rationale: str \| None = None`; `detect_flags()` copies from pair |
| `src/interlock/pipeline.py` | `use_llm_reranker` kwarg (default False) on both `review_two_documents_full` + `review_two_documents`; calls `rerank_weak_pairs()` between `combine_alignments` and `detect_flags`; stage callback `rerank` |
| `src/interlock/ui/app.py` | Sidebar toggle; `🤖 Reranked` badge; rationale `st.info()` in expander; JSON export key; stage row in `_STAGE_LABELS` |
| `tests/e2e/test_pipeline_v2.py` | Sprint 4 integration tests appended |
| `docs/AUTHORSHIP.md` | Sprint 4 per-phase entry |
| `docs/TDD.md` | Sprint 4 known-limits entry |

---

## Phase 27.1 — `PairVerdict` schema + `AlignedPair` back-compat fields

### Task 1.1: `PairVerdict` pydantic model

**Files:**
- Create: `src/interlock/llm_pipeline/schemas/pair.py`
- Create: `tests/llm_pipeline/schemas/test_pair.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/llm_pipeline/schemas/test_pair.py
"""Sprint 4 — PairVerdict pydantic model validation tests."""

from __future__ import annotations

import pytest
from pydantic import ValidationError


def test_pair_verdict_constructs_with_valid_fields() -> None:
    from interlock.llm_pipeline.schemas.pair import PairVerdict
    v = PairVerdict(
        score=0.9,
        rationale="200A and 200A — same physical feeder rating",
        decline_to_pair=False,
    )
    assert v.score == 0.9
    assert "200A" in v.rationale
    assert v.decline_to_pair is False


def test_pair_verdict_decline_defaults_false() -> None:
    from interlock.llm_pipeline.schemas.pair import PairVerdict
    v = PairVerdict(score=0.5, rationale="uncertain")
    assert v.decline_to_pair is False


def test_pair_verdict_score_below_zero_rejected() -> None:
    from interlock.llm_pipeline.schemas.pair import PairVerdict
    with pytest.raises(ValidationError):
        PairVerdict(score=-0.1, rationale="x")


def test_pair_verdict_score_above_one_rejected() -> None:
    from interlock.llm_pipeline.schemas.pair import PairVerdict
    with pytest.raises(ValidationError):
        PairVerdict(score=1.1, rationale="x")


def test_pair_verdict_empty_rationale_rejected() -> None:
    from interlock.llm_pipeline.schemas.pair import PairVerdict
    with pytest.raises(ValidationError):
        PairVerdict(score=0.5, rationale="")


def test_pair_verdict_is_frozen() -> None:
    from interlock.llm_pipeline.schemas.pair import PairVerdict
    v = PairVerdict(score=0.5, rationale="x")
    with pytest.raises(ValidationError):
        v.score = 0.9  # type: ignore[misc]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/llm_pipeline/schemas/test_pair.py -v`
Expected: 6 FAIL with `ModuleNotFoundError: interlock.llm_pipeline.schemas.pair`.

- [ ] **Step 3: Implement the schema**

Read `src/interlock/llm_pipeline/schemas/doc_class.py` first to match the project's pydantic v2 style + import surface.

```python
# src/interlock/llm_pipeline/schemas/pair.py
"""Sprint 4 — PairVerdict schema for the LLM pairing reranker.

Returned by the Sonnet 4.5 reranker for each weak pair (Track 1
pairing_confidence < 0.75). `score` overwrites pairing_confidence;
`rationale` surfaces in the UI replacing the generic ⚠️ weak pair badge;
`decline_to_pair=True` drops the pair (A and B records flow into the
existing unpaired_a/b lists).
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class PairVerdict(BaseModel):
    """One reranker verdict for a single weak pair."""

    model_config = ConfigDict(frozen=True)

    score: float = Field(ge=0.0, le=1.0)
    rationale: str = Field(min_length=1, max_length=2000)
    decline_to_pair: bool = False
```

- [ ] **Step 4: Ensure `tests/llm_pipeline/schemas/` has `__init__.py`**

```bash
[ -f tests/llm_pipeline/schemas/__init__.py ] || touch tests/llm_pipeline/schemas/__init__.py
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/llm_pipeline/schemas/test_pair.py -v`
Expected: 6 passed.

- [ ] **Step 6: Lint + mypy**

Run: `uv run ruff check src/interlock/llm_pipeline/schemas/pair.py tests/llm_pipeline/schemas/test_pair.py && uv run mypy src/interlock/llm_pipeline/schemas/pair.py`
Expected: clean.

### Task 1.2: `AlignedPair` back-compat fields

**Files:**
- Modify: `src/interlock/align/exact.py` (within the `AlignedPair` dataclass)
- Create: `tests/align/test_aligned_pair_back_compat.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/align/test_aligned_pair_back_compat.py
"""Sprint 4 — AlignedPair back-compat default tests.

Two new fields default to None / False so every existing alignment test
that constructs AlignedPair by hand keeps working. The reranker
(Phase 27.2) overwrites these when invoked through the pipeline.
"""

from __future__ import annotations

from interlock.align.exact import AlignedPair
from interlock.extract.parameters import ParameterRecord


def _record() -> ParameterRecord:
    return ParameterRecord(
        doc_id="d", page=1, bbox=(0, 0, 100, 10), section=None,
        span_text="200A", name="Feeder Rating", raw_value="200 A",
        normalized_magnitude=200.0, normalized_unit="ampere",
    )


def test_rerank_rationale_defaults_to_none() -> None:
    p = AlignedPair(
        a=_record(), b=_record(),
        name_match_confidence=1.0, value_equivalent=True,
    )
    assert p.rerank_rationale is None


def test_reranked_defaults_to_false() -> None:
    p = AlignedPair(
        a=_record(), b=_record(),
        name_match_confidence=1.0, value_equivalent=True,
    )
    assert p.reranked is False


def test_rerank_fields_can_be_set_explicitly() -> None:
    p = AlignedPair(
        a=_record(), b=_record(),
        name_match_confidence=1.0, value_equivalent=True,
        rerank_rationale="confirmed pair",
        reranked=True,
    )
    assert p.rerank_rationale == "confirmed pair"
    assert p.reranked is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/align/test_aligned_pair_back_compat.py -v`
Expected: 3 FAIL with `TypeError: __init__() got an unexpected keyword argument 'rerank_rationale'`.

- [ ] **Step 3: Extend `AlignedPair`**

Read `src/interlock/align/exact.py` lines 38–54 to locate the existing `AlignedPair` dataclass with `pairing_confidence: float = 1.0` as the last field. Append two new fields at the end:

```python
# src/interlock/align/exact.py — within @dataclass(frozen=True) class AlignedPair,
# AFTER the existing `pairing_confidence: float = 1.0` line, append:

    # v2 Sprint 4 — LLM reranker outputs. Defaults preserve back-compat
    # with hand-built AlignedPair in legacy alignment tests.
    rerank_rationale: str | None = None
    reranked: bool = False
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/align/test_aligned_pair_back_compat.py -v`
Expected: 3 passed.

- [ ] **Step 5: Full regression to confirm alignment back-compat**

Run: `uv run pytest --deselect tests/real_world -q 2>&1 | tail -3`
Expected: 354 (v2.2 baseline) + 6 (Task 1.1) + 3 (Task 1.2) = 363 passed.

- [ ] **Step 6: Lint + mypy**

Run: `uv run ruff check src/interlock/align/exact.py tests/align/test_aligned_pair_back_compat.py && uv run mypy src/interlock/align/exact.py`
Expected: clean.

- [ ] **Step 7: Commit + tag (closes Phase 27.1)**

```bash
git add src/interlock/llm_pipeline/schemas/pair.py \
        src/interlock/align/exact.py \
        tests/llm_pipeline/schemas/test_pair.py \
        tests/llm_pipeline/schemas/__init__.py \
        tests/align/test_aligned_pair_back_compat.py
git commit -m "feat(schemas): PairVerdict + AlignedPair rerank fields (back-compat defaults)"
git tag phase-27.1-rerank-schemas -m "Sprint 4 phase 1: PairVerdict + AlignedPair back-compat fields"
git push origin main phase-27.1-rerank-schemas
```

---

## Phase 27.2 — Reranker module (`rerank_weak_pairs`)

### Task 2.1: Prompt file

**Files:**
- Create: `src/interlock/llm_pipeline/prompts/pair.md`

- [ ] **Step 1: Write the prompt file**

```markdown
<!-- src/interlock/llm_pipeline/prompts/pair.md -->
# Pairing reranker — engineering review

You verify whether two engineering-document records refer to the same physical parameter on the same physical equipment.

## Decision rule

Return one JSON object with three fields:

- `score` — float in [0,1]. 1.0 = certain same record; 0.0 = certain different records; intermediate values reflect uncertainty.
- `rationale` — one paragraph (≤ 400 chars). Cite both `raw_value`s explicitly. Reference any context that drove your decision (page numbers, section headings, sibling rows).
- `decline_to_pair` — boolean. Set `true` when the values clearly refer to different physical things (different feeder, different transformer, different fuse family), even if both share a parameter name.

## Heuristics

1. **Same value on both pages** → strong signal of same record, unless surrounding context shows they're different physical instances (e.g. one-line diagram with multiple feeders labelled separately).
2. **Different values, same equipment** → keep the pair (this is a real mismatch worth flagging). Authority direction is decided downstream; you only verify the pair is real.
3. **Different values, evidence of different equipment** → decline_to_pair. Look for: different `entity_tag`, different `section`, sibling rows on the same page showing both records co-exist in their respective documents.
4. **Identical-name reference cards / tutorial diagrams** (Eaton coordination tutorials, IEEE example one-lines): a "200A Feeder" and "400A Feeder" labelled side-by-side are different physical examples. If one record's `raw_value` appears in the other doc's siblings on the same page, decline_to_pair.

## Output format

Return raw JSON, no prose, no markdown fence:

```
{"score": 0.05, "rationale": "200A Feeder on Doc A p2 is a different physical example than 400A Feeder on Doc B p6. Doc A p2 also contains a '400A Feeder' label and Doc B p2 also contains a '200A Feeder' label — they're side-by-side tutorial examples, not the same record.", "decline_to_pair": true}
```
```

- [ ] **Step 2: Commit prompt**

```bash
git add src/interlock/llm_pipeline/prompts/pair.md
git commit -m "feat(prompts): Sprint 4 pairing reranker system prompt"
```

### Task 2.2: Reranker module unit tests + implementation

**Files:**
- Create: `src/interlock/llm_pipeline/pair.py`
- Create: `tests/llm_pipeline/test_pair.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/llm_pipeline/test_pair.py
"""Sprint 4 — reranker unit tests (mocked Claude)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from interlock.align.exact import AlignedPair
from interlock.cache import disk as disk_cache
from interlock.extract.parameters import ParameterRecord


def _record(name: str = "Feeder Rating", raw: str = "200 A", page: int = 2) -> ParameterRecord:
    return ParameterRecord(
        doc_id="d", page=page, bbox=(0, 0, 100, 10), section=None,
        span_text=raw, name=name, raw_value=raw,
        normalized_magnitude=200.0, normalized_unit="ampere",
    )


def _pair(
    a_raw: str = "200 A",
    b_raw: str = "200 A",
    pairing_conf: float = 0.5,
    a_page: int = 2,
    b_page: int = 2,
) -> AlignedPair:
    return AlignedPair(
        a=_record(raw=a_raw, page=a_page),
        b=_record(raw=b_raw, page=b_page),
        name_match_confidence=1.0,
        value_equivalent=False,
        pairing_confidence=pairing_conf,
    )


def _fake_response(text: str) -> MagicMock:
    content = MagicMock()
    content.text = text
    return MagicMock(content=[content])


@pytest.fixture(autouse=True)
def _clear_pair_cache() -> None:
    disk_cache.clear_namespace("llm-pair")
    yield
    disk_cache.clear_namespace("llm-pair")


def test_strong_pairs_pass_through_untouched(mocker, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from interlock.llm_pipeline.pair import rerank_weak_pairs
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    spy = mocker.patch("interlock.llm_pipeline.pair._call_claude_pair")
    p = _pair(pairing_conf=0.9)
    out = rerank_weak_pairs([p])
    assert spy.call_count == 0
    assert len(out) == 1
    assert out[0].reranked is False
    assert out[0].pairing_confidence == 0.9


def test_decline_to_pair_drops_pair(mocker, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from interlock.llm_pipeline.pair import rerank_weak_pairs
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    mocker.patch(
        "interlock.llm_pipeline.pair._call_claude_pair",
        return_value=_fake_response(
            '{"score":0.05,"rationale":"200 A vs 400 A are different feeders","decline_to_pair":true}'
        ),
    )
    p = _pair(a_raw="200 A", b_raw="400 A")
    out = rerank_weak_pairs([p])
    assert out == []


def test_keep_with_score_overwrites_pairing_confidence(mocker, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from interlock.llm_pipeline.pair import rerank_weak_pairs
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    mocker.patch(
        "interlock.llm_pipeline.pair._call_claude_pair",
        return_value=_fake_response(
            '{"score":0.95,"rationale":"200 A on both pages — same feeder","decline_to_pair":false}'
        ),
    )
    p = _pair(pairing_conf=0.5)
    out = rerank_weak_pairs([p])
    assert len(out) == 1
    assert out[0].pairing_confidence == 0.95
    assert out[0].reranked is True
    assert out[0].rerank_rationale is not None
    assert "200 A" in out[0].rerank_rationale


def test_hallucination_guard_keeps_track_1(mocker, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """Rationale mentions neither raw_value → reject the verdict."""
    from interlock.llm_pipeline.pair import rerank_weak_pairs
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    mocker.patch(
        "interlock.llm_pipeline.pair._call_claude_pair",
        return_value=_fake_response(
            '{"score":0.99,"rationale":"both records describe the same equipment","decline_to_pair":false}'
        ),
    )
    p = _pair(a_raw="200 A", b_raw="400 A", pairing_conf=0.5)
    out = rerank_weak_pairs([p])
    assert len(out) == 1
    assert out[0].pairing_confidence == 0.5  # unchanged
    assert out[0].reranked is False
    assert out[0].rerank_rationale is None


def test_api_failure_keeps_track_1(mocker, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from interlock.llm_pipeline.pair import rerank_weak_pairs
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    mocker.patch(
        "interlock.llm_pipeline.pair._call_claude_pair",
        side_effect=RuntimeError("API down"),
    )
    p = _pair(pairing_conf=0.5)
    out = rerank_weak_pairs([p])
    assert len(out) == 1
    assert out[0].pairing_confidence == 0.5
    assert out[0].reranked is False


def test_parse_failure_keeps_track_1(mocker, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """Claude returned garbage JSON → keep Track 1 verdict."""
    from interlock.llm_pipeline.pair import rerank_weak_pairs
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    mocker.patch(
        "interlock.llm_pipeline.pair._call_claude_pair",
        return_value=_fake_response("not json at all"),
    )
    p = _pair(pairing_conf=0.5)
    out = rerank_weak_pairs([p])
    assert len(out) == 1
    assert out[0].pairing_confidence == 0.5
    assert out[0].reranked is False


def test_validation_failure_keeps_track_1(mocker, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """Score outside [0,1] → pydantic rejects → keep Track 1."""
    from interlock.llm_pipeline.pair import rerank_weak_pairs
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    mocker.patch(
        "interlock.llm_pipeline.pair._call_claude_pair",
        return_value=_fake_response(
            '{"score":1.5,"rationale":"200 A","decline_to_pair":false}'
        ),
    )
    p = _pair(pairing_conf=0.5)
    out = rerank_weak_pairs([p])
    assert len(out) == 1
    assert out[0].reranked is False


def test_order_preserved_across_parallel_calls(mocker, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """Returned order matches input order even with parallel dispatch."""
    from interlock.llm_pipeline.pair import rerank_weak_pairs
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    mocker.patch(
        "interlock.llm_pipeline.pair._call_claude_pair",
        return_value=_fake_response(
            '{"score":0.8,"rationale":"200 A on both pages","decline_to_pair":false}'
        ),
    )
    pairs = [
        _pair(a_raw=f"{i*100} A", b_raw=f"{i*100} A", pairing_conf=0.5)
        for i in (1, 2, 3, 4, 5)
    ]
    out = rerank_weak_pairs(pairs)
    assert len(out) == 5
    assert [p.a.raw_value for p in out] == ["100 A", "200 A", "300 A", "400 A", "500 A"]


def test_diskcache_hit_short_circuits(mocker, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from interlock.llm_pipeline.pair import rerank_weak_pairs
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    spy = mocker.patch(
        "interlock.llm_pipeline.pair._call_claude_pair",
        return_value=_fake_response(
            '{"score":0.9,"rationale":"200 A on both","decline_to_pair":false}'
        ),
    )
    p = _pair(pairing_conf=0.5)
    rerank_weak_pairs([p])
    assert spy.call_count == 1
    rerank_weak_pairs([p])  # second call — cache hit
    assert spy.call_count == 1


def test_empty_input_returns_empty(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from interlock.llm_pipeline.pair import rerank_weak_pairs
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    assert rerank_weak_pairs([]) == []
```

- [ ] **Step 2: Run; expected to fail**

Run: `uv run pytest tests/llm_pipeline/test_pair.py -v`
Expected: 10 failures (`ModuleNotFoundError: interlock.llm_pipeline.pair`).

- [ ] **Step 3: Verify diskcache namespace API**

```bash
grep -n "def clear_namespace\|def get\|def put\|def cache_key" src/interlock/cache/disk.py
```

Confirm the helper names (`get`, `put`, `cache_key`, `clear_namespace`) match what we'll use below. If they differ, adjust the implementation accordingly.

- [ ] **Step 4: Implement the reranker module**

```python
# src/interlock/llm_pipeline/pair.py
"""Sprint 4 — LLM pairing reranker over Track 1 weak pairs.

For each AlignedPair with pairing_confidence < weak_threshold, call
Claude Sonnet 4.5 with both records' context (plus the 2 nearest sibling
rows on each side) and ask for a (score, rationale, decline_to_pair)
verdict. Strong pairs pass through untouched.

Failure modes (API outage, parse error, pydantic validation error,
hallucination guard rejection) all collapse to "keep Track 1 verdict":
the original pair is preserved, pairing_confidence unchanged,
reranked=False.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from typing import Any

from anthropic import Anthropic

from interlock.align.exact import AlignedPair
from interlock.cache import disk as disk_cache
from interlock.llm_pipeline.schemas.pair import PairVerdict

MODEL = "claude-sonnet-4-5"
PROMPT_VERSION = "v1"
_MAX_TOKENS = 1024
_RERANK_MAX_WORKERS = 5
_NAMESPACE = "llm-pair"
_PROMPT_PATH = Path(__file__).parent / "prompts" / "pair.md"


def rerank_weak_pairs(
    pairs: list[AlignedPair],
    *,
    weak_threshold: float = 0.75,
    max_workers: int = _RERANK_MAX_WORKERS,
) -> list[AlignedPair]:
    """Rerank pairs with pairing_confidence < weak_threshold via Claude.

    Order preserved for survivors. Pairs whose verdict is
    decline_to_pair drop out (callers downstream recompute
    unpaired_a/b from the surviving list).
    """
    if not pairs:
        return []

    # Partition: indices of weak pairs to rerank, rest pass through.
    weak_indices = [i for i, p in enumerate(pairs) if p.pairing_confidence < weak_threshold]
    if not weak_indices:
        return list(pairs)

    # Parallel dispatch — preserve original index for in-order reassembly.
    verdicts: dict[int, PairVerdict | None] = {}
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = {
            ex.submit(_rerank_one, pairs[i]): i for i in weak_indices
        }
        for fut in futures:
            idx = futures[fut]
            try:
                verdicts[idx] = fut.result()
            except Exception:
                verdicts[idx] = None

    out: list[AlignedPair] = []
    for i, p in enumerate(pairs):
        if i not in weak_indices:
            out.append(p)
            continue
        v = verdicts.get(i)
        if v is None:
            # API / parse / hallucination failure — keep Track 1.
            out.append(p)
            continue
        if v.decline_to_pair:
            continue  # drop the pair
        out.append(
            replace(
                p,
                pairing_confidence=v.score,
                rerank_rationale=v.rationale,
                reranked=True,
            )
        )
    return out


def _rerank_one(pair: AlignedPair) -> PairVerdict | None:
    """Return a validated PairVerdict, or None on any failure.

    None semantics: caller falls back to the original Track 1 pair.
    """
    prompt = _build_prompt(pair)
    key = _cache_key(pair, prompt)

    cached = disk_cache.get(_NAMESPACE, key)
    if cached is not None:
        try:
            return PairVerdict.model_validate_json(cached)
        except Exception:
            pass  # fall through and re-call

    try:
        raw_resp = _call_claude_pair(prompt)
    except Exception:
        return None

    text = _response_text(raw_resp)
    payload = _parse_json(text)
    if payload is None:
        return None
    try:
        verdict = PairVerdict(**payload)
    except Exception:
        return None

    if not _hallucination_guard_ok(verdict, pair):
        return None

    disk_cache.put(_NAMESPACE, key, verdict.model_dump_json())
    return verdict


def _build_prompt(pair: AlignedPair) -> str:
    """Compose the user-turn prompt: system prompt + both records' context."""
    sys_prompt = _PROMPT_PATH.read_text(encoding="utf-8")
    a, b = pair.a, pair.b
    body = (
        f"## Doc A record\n\n"
        f"- name: {a.name}\n"
        f"- raw_value: {a.raw_value}\n"
        f"- page: {a.page}\n"
        f"- section: {a.section or '—'}\n"
        f"- entity_tag: {a.entity_tag or '—'}\n"
        f"- span_text: {a.span_text!r}\n\n"
        f"## Doc B record\n\n"
        f"- name: {b.name}\n"
        f"- raw_value: {b.raw_value}\n"
        f"- page: {b.page}\n"
        f"- section: {b.section or '—'}\n"
        f"- entity_tag: {b.entity_tag or '—'}\n"
        f"- span_text: {b.span_text!r}\n\n"
        f"## Track 1 verdict\n\n"
        f"- pairing_confidence: {pair.pairing_confidence:.2f}\n"
        f"- name_match_confidence: {pair.name_match_confidence:.2f}\n"
        f"- value_equivalent: {pair.value_equivalent}\n\n"
        f"Return a single JSON object with score, rationale, decline_to_pair.\n"
    )
    return sys_prompt + "\n\n" + body


def _call_claude_pair(prompt: str) -> object:
    """Single text-only Claude call. Returns raw Anthropic response."""
    client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
    return client.messages.create(
        model=MODEL,
        max_tokens=_MAX_TOKENS,
        messages=[{"role": "user", "content": content}],  # type: ignore[typeddict-item]
    )


def _response_text(resp: object) -> str:
    """Extract the text payload from an Anthropic Message response."""
    blocks = getattr(resp, "content", None) or []
    if not blocks:
        return ""
    first = blocks[0]
    return getattr(first, "text", "") or ""


_FENCED_JSON = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)
_BARE_JSON = re.compile(r"(\{.*\})", re.DOTALL)


def _parse_json(raw: str) -> dict[str, Any] | None:
    """Parse Claude's text into a JSON dict. Tolerant of fenced output."""
    m = _FENCED_JSON.search(raw)
    payload_str: str | None = None
    if m:
        payload_str = m.group(1)
    else:
        m2 = _BARE_JSON.search(raw)
        if m2:
            payload_str = m2.group(1)
    if payload_str is None:
        return None
    try:
        loaded = json.loads(payload_str)
    except json.JSONDecodeError:
        return None
    if not isinstance(loaded, dict):
        return None
    return loaded


def _hallucination_guard_ok(verdict: PairVerdict, pair: AlignedPair) -> bool:
    """Rationale must mention at least one of the two raw_values
    (case-insensitive substring match). Defends against generic
    confabulation."""
    rat = verdict.rationale.lower()
    a_raw = (pair.a.raw_value or "").strip().lower()
    b_raw = (pair.b.raw_value or "").strip().lower()
    return (a_raw and a_raw in rat) or (b_raw and b_raw in rat)


def _cache_key(pair: AlignedPair, prompt: str) -> str:
    """Content-hash key. Different (a, b) records or prompt edits invalidate."""
    a, b = pair.a, pair.b
    parts = [
        MODEL, PROMPT_VERSION,
        a.doc_id, str(a.page), a.name, a.raw_value, a.span_text or "",
        b.doc_id, str(b.page), b.name, b.raw_value, b.span_text or "",
        hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:16],
    ]
    blob = "|".join(parts)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/llm_pipeline/test_pair.py -v`
Expected: 10 passed.

- [ ] **Step 6: Lint + mypy**

Run: `uv run ruff check src/interlock/llm_pipeline/pair.py tests/llm_pipeline/test_pair.py && uv run mypy src/interlock/llm_pipeline/pair.py`
Expected: clean.

- [ ] **Step 7: Full regression**

Run: `uv run pytest --deselect tests/real_world -q 2>&1 | tail -3`
Expected: 363 + 10 = 373 passed.

- [ ] **Step 8: Commit + tag (closes Phase 27.2)**

```bash
git add src/interlock/llm_pipeline/pair.py tests/llm_pipeline/test_pair.py
git commit -m "feat(llm_pipeline): rerank_weak_pairs() — Sonnet 4.5 parallel reranker + 10 unit tests"
git tag phase-27.2-rerank-module -m "Sprint 4 phase 2: reranker module + hallucination guard + cache"
git push origin main phase-27.2-rerank-module
```

---

## Phase 27.3 — Pipeline integration + `Flag.rerank_rationale`

### Task 3.1: `Flag.rerank_rationale` field + detect_flags propagation

**Files:**
- Modify: `src/interlock/detect/mismatch.py`

- [ ] **Step 1: Add the field**

Read `src/interlock/detect/mismatch.py` to locate the `Flag` dataclass (Sprint 3 already added `provenance` as the last field). Append after `provenance`:

```python
# src/interlock/detect/mismatch.py — within @dataclass(frozen=True) class Flag,
# AFTER the existing `provenance: Literal[...] = "unknown"` field, append:

    # v2 Sprint 4 — copied from AlignedPair.rerank_rationale by detect_flags.
    # None when the reranker didn't run or didn't approve this pair.
    rerank_rationale: str | None = None
```

- [ ] **Step 2: Propagate from pair to flag in `detect_flags`**

Locate the `Flag(...)` constructor call inside `detect_flags()` (around line 106). Add one new line at the end of the kwargs list, before the closing `)`:

```python
# Append `rerank_rationale=p.rerank_rationale,` as the last kwarg in the existing
# Flag(...) constructor inside detect_flags() — keep all existing kwargs unchanged.
```

The full call after edit:

```python
out.append(
    Flag(
        parameter=p.a.name,
        authoritative_doc_id=decision.authoritative_doc_id,
        deviating_doc_id=decision.deviating_doc_id,
        a_record=p.a,
        b_record=p.b,
        confidence=conf,
        rationale=(
            f"{p.a.raw_value} (authoritative, p{p.a.page}) "
            f"≠ {p.b.raw_value} (deviation, p{p.b.page})"
        ),
        authority_rule=decision.rule,
        severity=severity,
        deviation_pct=dev,
        attribute_family=family,
        pairing_confidence=p.pairing_confidence,
        rerank_rationale=p.rerank_rationale,
    )
)
```

- [ ] **Step 3: Lint + mypy**

Run: `uv run ruff check src/interlock/detect/mismatch.py && uv run mypy src/interlock/detect/mismatch.py`
Expected: clean.

### Task 3.2: Pipeline `use_llm_reranker` kwarg + tests

**Files:**
- Modify: `src/interlock/pipeline.py`
- Modify: `tests/e2e/test_pipeline_v2.py` (append)

- [ ] **Step 1: Write the failing tests**

Append to `tests/e2e/test_pipeline_v2.py`:

```python
# tests/e2e/test_pipeline_v2.py (append at end)

# --- Sprint 4: pairing reranker integration -----------------------------


@pytest.fixture(autouse=True)
def _clear_pair_cache() -> None:
    from interlock.cache import disk as disk_cache
    disk_cache.clear_namespace("llm-pair")
    yield
    disk_cache.clear_namespace("llm-pair")


def _fake_pair_response(decline: bool = False, score: float = 0.9) -> MagicMock:
    """Build a fake Claude response. Rationale embeds both common raw_values
    from the Option 1 fixture so the hallucination guard accepts it."""
    content = MagicMock()
    content.text = (
        '{"score":' + f"{score}" + ','
        '"rationale":"5.75 % and 5.75 % — same impedance record",'
        '"decline_to_pair":' + ("true" if decline else "false") + '}'
    )
    return MagicMock(content=[content])


def test_use_llm_reranker_false_is_bit_identical_to_v2_2(mocker) -> None:  # type: ignore[no-untyped-def]
    """Default off ⇒ no reranker call; flag set unchanged from v2.2."""
    from interlock.pipeline import review_two_documents_full
    spy = mocker.patch("interlock.llm_pipeline.pair._call_claude_pair")
    result = review_two_documents_full(
        DOC_A, DOC_B, embed_fn=_trivial_embedder,
        use_llm_reranker=False,
    )
    assert spy.call_count == 0
    expected_params = {"%Z", "Fault Current", "Transformer Rating"}
    surfaced = {f.parameter for f in result.flags if f.confidence >= 0.6}
    assert expected_params.issubset(surfaced)
    for f in result.flags:
        assert f.rerank_rationale is None


def test_use_llm_reranker_true_unanimous_approve_preserves_flags(mocker) -> None:  # type: ignore[no-untyped-def]
    """Reranker approves every weak pair ⇒ flag count + parameters
    unchanged from Track 1."""
    from interlock.pipeline import review_two_documents_full
    mocker.patch(
        "interlock.llm_pipeline.pair._call_claude_pair",
        return_value=_fake_pair_response(decline=False, score=0.9),
    )
    result = review_two_documents_full(
        DOC_A, DOC_B, embed_fn=_trivial_embedder,
        use_llm_reranker=True,
    )
    expected_params = {"%Z", "Fault Current", "Transformer Rating"}
    surfaced = {f.parameter for f in result.flags if f.confidence >= 0.6}
    assert expected_params.issubset(surfaced)


def test_pipeline_survives_reranker_exception(mocker) -> None:  # type: ignore[no-untyped-def]
    """API outage mid-rerank ⇒ pipeline still ships Track 1 flag set."""
    from interlock.pipeline import review_two_documents_full
    mocker.patch(
        "interlock.llm_pipeline.pair._call_claude_pair",
        side_effect=RuntimeError("API down"),
    )
    result = review_two_documents_full(
        DOC_A, DOC_B, embed_fn=_trivial_embedder,
        use_llm_reranker=True,
    )
    assert isinstance(result.flags, list)


def test_sprint3_provenance_and_sprint4_rationale_coexist() -> None:
    """Both labels live on the same Flag without interference."""
    from interlock.detect.mismatch import Flag
    from interlock.extract.parameters import ParameterRecord
    r = ParameterRecord(
        doc_id="d", page=1, bbox=(0, 0, 100, 10), section=None,
        span_text="5.75%Z", name="%Z", raw_value="5.75 %",
        normalized_magnitude=0.0575, normalized_unit="dimensionless",
        provenance="regex",  # type: ignore[arg-type]
    )
    f = Flag(
        parameter="%Z",
        a_record=r, b_record=r,
        authoritative_doc_id="d", deviating_doc_id="d",
        confidence=1.0, rationale="test", authority_rule="MVP",
        severity="major", deviation_pct=10.0, attribute_family="impedance_pct",
        provenance="rule_only",  # type: ignore[arg-type]
        rerank_rationale="confirmed pair",
    )
    assert f.provenance == "rule_only"
    assert f.rerank_rationale == "confirmed pair"
```

- [ ] **Step 2: Run; expected to fail (kwarg not wired yet)**

Run: `uv run pytest tests/e2e/test_pipeline_v2.py::test_use_llm_reranker_false_is_bit_identical_to_v2_2 -v`
Expected: FAIL — `TypeError: review_two_documents_full() got an unexpected keyword argument 'use_llm_reranker'`.

- [ ] **Step 3: Wire `use_llm_reranker` into `review_two_documents_full`**

Read `src/interlock/pipeline.py` to confirm the existing kwarg list shape. Add `use_llm_reranker` between `classify_docs` and `use_llm_extraction`:

```python
# src/interlock/pipeline.py — within review_two_documents_full signature,
# alongside the existing classify_docs / use_llm_extraction kwargs:

    classify_docs: bool = False,
    use_llm_extraction: bool = False,
    use_llm_reranker: bool = False,
```

Same addition to `review_two_documents` (the back-compat shim).

- [ ] **Step 4: Wire the reranker call between `combine_alignments` and `_stage("align", "done")`**

Locate the existing block:

```python
exact = align_exact(pa, pb)
# (or align_claims_exact branch)
semantic = align_semantic(...)
combined = combine_alignments(exact, semantic)
_stage("align", "done")
```

Insert the reranker between `combine_alignments` and `_stage("align", "done")`:

```python
combined = combine_alignments(exact, semantic)

# v2 Sprint 4: opt-in LLM pairing reranker. Pure pass-through when off.
if use_llm_reranker:
    from interlock.llm_pipeline.pair import rerank_weak_pairs
    _stage("rerank", "start")
    try:
        combined = rerank_weak_pairs(combined)
    except Exception:
        pass  # API outage / unexpected error → keep Track 1 verdicts
    _stage("rerank", "done")

_stage("align", "done")
```

- [ ] **Step 5: Forward the new kwarg through `review_two_documents`**

In the back-compat shim's body (which calls `review_two_documents_full(...)`), add:

```python
        use_llm_reranker=use_llm_reranker,
```

after the existing `use_llm_extraction=use_llm_extraction,` line.

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/e2e/test_pipeline_v2.py -v`
Expected: all v2 tests pass + 4 new Sprint 4 tests pass.

- [ ] **Step 7: Full regression**

Run: `uv run pytest --deselect tests/real_world -q 2>&1 | tail -3`
Expected: 373 + 4 = 377 passed.

- [ ] **Step 8: Lint + mypy**

Run: `uv run ruff check src/interlock/pipeline.py tests/e2e/test_pipeline_v2.py && uv run mypy src/interlock/pipeline.py`
Expected: clean.

- [ ] **Step 9: Commit + tag (closes Phase 27.3)**

```bash
git add src/interlock/detect/mismatch.py src/interlock/pipeline.py tests/e2e/test_pipeline_v2.py
git commit -m "feat(pipeline): wire rerank_weak_pairs() between align and detect"
git tag phase-27.3-rerank-pipeline -m "Sprint 4 phase 3: pipeline integration + Flag.rerank_rationale + 4 e2e tests"
git push origin main phase-27.3-rerank-pipeline
```

---

## Phase 27.4 — UI surface

### Task 4.1: Sidebar toggle + stage row

**Files:**
- Modify: `src/interlock/ui/app.py`

- [ ] **Step 1: Add the sidebar toggle**

Read `src/interlock/ui/app.py` to find the existing `use_llm_extraction = st.toggle(...)` block (added during the recent hotfix). Add the reranker toggle immediately after it, before the next `st.divider()`:

```python
# src/interlock/ui/app.py — INSERT after use_llm_extraction toggle, in the sidebar:

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

- [ ] **Step 2: Add stage label + extend the stage order list**

Locate `_STAGE_LABELS` (dict around line 376 inside the `if run:` block) and `_STAGE_ORDER` list (around line 384). Add the rerank entry:

```python
# src/interlock/ui/app.py — within the `if run:` block:

    _STAGE_LABELS: dict[str, str] = {
        "ingest_a": "Ingesting Doc A (PyMuPDF spans + Camelot tables)",
        "ingest_b": "Ingesting Doc B (PyMuPDF spans + Camelot tables)",
        "extract": "Extracting parameters (regex patterns + Pint unit normalisation)",
        "align": "Aligning across documents (exact name + canonical glossary + Voyage embeddings)",
        "rerank": "Reranking weak Track 1 pairs (Claude Sonnet 4.5, parallel × 5, cached)",
        "detect": "Detecting mismatches + classifying severity (IEEE / IEC tolerance bands)",
        "judge": "LLM significance judgement (Claude, cached per flag)",
    }
    _STAGE_ORDER: list[str] = ["ingest_a", "ingest_b", "extract", "align"]
    if use_llm_reranker:
        _STAGE_ORDER.append("rerank")
    _STAGE_ORDER.append("detect")
    if use_llm_judge:
        _STAGE_ORDER.append("judge")
```

- [ ] **Step 3: Forward `use_llm_reranker` into the pipeline call**

Locate the `review_two_documents_full(...)` call inside the `if run:` block and append the new kwarg next to the existing `use_llm_extraction=use_llm_extraction,` line:

```python
            review_result = review_two_documents_full(
                str(a_path),
                str(b_path),
                embed_fn=embed_voyage,
                same_page_only=False,
                use_llm_judge=use_llm_judge,
                table_max_pages=table_max_pages,
                enable_vision_ocr=enable_vision_ocr,
                ocr_progress_cb=_ocr_cb if enable_vision_ocr else None,
                stage_cb=_stage_cb,
                classify_docs=classify_docs,
                use_llm_extraction=use_llm_extraction,
                use_llm_reranker=use_llm_reranker,
            )
```

- [ ] **Step 4: Compile + lint + mypy**

```bash
uv run python -c "import py_compile; py_compile.compile('src/interlock/ui/app.py', doraise=True); print('OK')"
uv run ruff check src/interlock/ui/app.py
uv run mypy src/interlock/ui/app.py
```

Expected: OK + clean.

- [ ] **Step 5: Commit**

```bash
git add src/interlock/ui/app.py
git commit -m "feat(ui): sidebar use_llm_reranker toggle + 'rerank' stage row"
```

### Task 4.2: Reranked badge + rationale in flag header / expander

**Files:**
- Modify: `src/interlock/ui/app.py`

- [ ] **Step 1: Add the `_rerank_badge` helper at module level**

Add near the existing `_provenance_badge` helper (Sprint 3):

```python
# src/interlock/ui/app.py — INSERT next to _provenance_badge:

def _rerank_badge(flag: Any) -> str:
    """Return reviewer-facing badge text for a flag's reranker status.

    Reranked + strong score → '🤖 Reranked'.
    Reranked + weak score (LLM ran but still uncertain) → '🤖 Reranked · ⚠️ low score'.
    Not reranked → '' (caller falls back to the legacy ⚠️ weak pair badge).
    """
    if not getattr(flag, "rerank_rationale", None):
        return ""
    if getattr(flag, "pairing_confidence", 1.0) < 0.75:
        return " · 🤖 Reranked · ⚠️ low score"
    return " · 🤖 Reranked"
```

- [ ] **Step 2: Update the flag header construction**

Locate the existing block (around line 695):

```python
        pairing_conf = getattr(f, "pairing_confidence", 1.0)
        weak_pair = pairing_conf < 0.75
        pair_badge = " · ⚠️ weak pair" if weak_pair else ""
        # v2 Sprint 3: silent on rule_only, prominent on llm_only / mixed_track
        prov_badge = _provenance_badge(getattr(f, "provenance", "unknown"))
        header = (
            f"{_SEVERITY[sev]['emoji']} **{f.parameter}** · "
            f"{dev_str} · confidence {f.confidence:.2f}"
            f"{pair_badge}{prov_badge}{verdict_badge}"
        )
```

Update to use the rerank badge in place of the weak-pair badge when the reranker ran:

```python
        pairing_conf = getattr(f, "pairing_confidence", 1.0)
        weak_pair = pairing_conf < 0.75
        # v2 Sprint 4: rerank badge overrides the legacy weak-pair badge
        # when the reranker has spoken on this pair.
        rerank_b = _rerank_badge(f)
        pair_badge = rerank_b if rerank_b else (" · ⚠️ weak pair" if weak_pair else "")
        # v2 Sprint 3: silent on rule_only, prominent on llm_only / mixed_track
        prov_badge = _provenance_badge(getattr(f, "provenance", "unknown"))
        header = (
            f"{_SEVERITY[sev]['emoji']} **{f.parameter}** · "
            f"{dev_str} · confidence {f.confidence:.2f}"
            f"{pair_badge}{prov_badge}{verdict_badge}"
        )
```

- [ ] **Step 3: Add rationale `st.info()` inside the expander body**

Locate the per-flag expander body (after the `st.caption(cap)` call, before the citation columns). Insert:

```python
            # v2 Sprint 4: surface reranker rationale prominently when present.
            if getattr(f, "rerank_rationale", None):
                st.info(f"🤖 **Reranker:** {f.rerank_rationale}")
```

- [ ] **Step 4: Compile + lint + mypy**

```bash
uv run python -c "import py_compile; py_compile.compile('src/interlock/ui/app.py', doraise=True); print('OK')"
uv run ruff check src/interlock/ui/app.py
uv run mypy src/interlock/ui/app.py
```

Expected: OK + clean.

- [ ] **Step 5: Commit**

```bash
git add src/interlock/ui/app.py
git commit -m "feat(ui): 🤖 Reranked badge + rationale st.info() in flag expander"
```

### Task 4.3: JSON export gains `rerank_rationale` key

**Files:**
- Modify: `src/interlock/ui/app.py`

- [ ] **Step 1: Locate the Accept-button decisions dict**

In `src/interlock/ui/app.py`, find the `st.session_state["decisions"][fid] = {...}` dict literal under the Accept button handler (Sprint 3 added the `"provenance"` key at the end).

- [ ] **Step 2: Append `rerank_rationale` key**

```python
# Update the dict literal to append rerank_rationale as the last key:

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
                        "rerank_rationale": getattr(f, "rerank_rationale", None),  # v2 Sprint 4
                    }
```

- [ ] **Step 3: Compile + lint + mypy**

```bash
uv run python -c "import py_compile; py_compile.compile('src/interlock/ui/app.py', doraise=True); print('OK')"
uv run ruff check src/interlock/ui/app.py
uv run mypy src/interlock/ui/app.py
```

Expected: OK + clean.

- [ ] **Step 4: Commit + tag (closes Phase 27.4)**

```bash
git add src/interlock/ui/app.py
git commit -m "feat(ui): JSON export gains rerank_rationale key per accepted flag"
git tag phase-27.4-rerank-ui -m "Sprint 4 phase 4: UI badge + rationale + JSON export + stage row"
git push origin main phase-27.4-rerank-ui
```

---

## Phase 27.5 — Live-API exit gate + docs + sprint exit

### Task 5.1: Live-API exit-gate tests

**Files:**
- Create: `tests/real_world/test_reranker_live.py`

- [ ] **Step 1: Write the slow-marked live tests**

```python
# tests/real_world/test_reranker_live.py
"""Sprint 4 exit gate — live-API eval of the LLM pairing reranker.

Slow-marked. Skipped without ANTHROPIC_API_KEY.

Cost: ~$0.01 per test cold (1 reranker call each), $0 warm.

Exit-gate cases (from PIVOT_PLAN Sprint 4):
1. KRP-C-1600SP (main fuse) vs LPS-RK-400SP (branch fuse) — different
   ampacity families. Reranker must decline_to_pair OR score < 0.5.
2. 150 kVA (XFMR-001) vs 100 kVA (XFMR-002) on a one-line diagram —
   two different transformers labelled side-by-side. Reranker must
   decline_to_pair OR score < 0.5.
"""

from __future__ import annotations

import os

import pytest
from dotenv import load_dotenv

load_dotenv(override=True)

pytestmark = pytest.mark.slow

needs_anthropic = pytest.mark.skipif(
    not os.getenv("ANTHROPIC_API_KEY"),
    reason="ANTHROPIC_API_KEY required for live reranker",
)


def _record(name: str, raw: str, page: int, span: str | None = None, doc_id: str = "doc") -> "ParameterRecord":  # type: ignore[name-defined]
    from interlock.extract.parameters import ParameterRecord
    return ParameterRecord(
        doc_id=doc_id, page=page, bbox=(0, 0, 100, 10), section=None,
        span_text=span or raw, name=name, raw_value=raw,
        normalized_magnitude=None, normalized_unit=None,
    )


@needs_anthropic
def test_krp_c_lps_rk_pair_correctly_declined() -> None:
    """Fuse part-numbers from different ampacity families must NOT pair."""
    from interlock.align.exact import AlignedPair
    from interlock.llm_pipeline.pair import rerank_weak_pairs

    a = _record(
        "Fuse Designation", "KRP-C-1600SP", page=4,
        span="Main feeder fuse KRP-C-1600SP 1600A class L",
        doc_id="doc_a",
    )
    b = _record(
        "Fuse Designation", "LPS-RK-400SP", page=5,
        span="Branch circuit fuse LPS-RK-400SP 400A class RK1",
        doc_id="doc_b",
    )
    pair = AlignedPair(
        a=a, b=b, name_match_confidence=1.0, value_equivalent=False,
        pairing_confidence=0.5,
    )
    out = rerank_weak_pairs([pair])
    if not out:
        return  # decline_to_pair dropped the pair — success
    assert len(out) == 1
    assert out[0].pairing_confidence < 0.5, (
        f"reranker should low-score this pair, got "
        f"{out[0].pairing_confidence}: {out[0].rerank_rationale}"
    )


@needs_anthropic
def test_150kva_100kva_pair_correctly_declined() -> None:
    """Two different transformers on a one-line diagram must NOT pair."""
    from interlock.align.exact import AlignedPair
    from interlock.llm_pipeline.pair import rerank_weak_pairs

    a = _record(
        "Rated Power", "150 kVA", page=2,
        span="XFMR-001 nameplate: 150 kVA 13.8kV-480V",
        doc_id="doc_a",
    )
    b = _record(
        "Rated Power", "100 kVA", page=2,
        span="XFMR-002 nameplate: 100 kVA 13.8kV-208V",
        doc_id="doc_b",
    )
    pair = AlignedPair(
        a=a, b=b, name_match_confidence=1.0, value_equivalent=False,
        pairing_confidence=0.5,
    )
    out = rerank_weak_pairs([pair])
    if not out:
        return
    assert len(out) == 1
    assert out[0].pairing_confidence < 0.5, (
        f"reranker should low-score this pair, got "
        f"{out[0].pairing_confidence}: {out[0].rerank_rationale}"
    )


@needs_anthropic
def test_same_value_same_section_correctly_paired() -> None:
    """Positive control: same value on both sides in the same section
    should rerank to a HIGH score (and not be dropped)."""
    from interlock.align.exact import AlignedPair
    from interlock.llm_pipeline.pair import rerank_weak_pairs

    a = _record(
        "Rated Impedance", "5.75 %", page=3,
        span="Z = 5.75 % per IEEE C57.12.00",
        doc_id="doc_a",
    )
    b = _record(
        "Rated Impedance", "5.75 %", page=4,
        span="Impedance: 5.75 % at 75°C",
        doc_id="doc_b",
    )
    pair = AlignedPair(
        a=a, b=b, name_match_confidence=1.0, value_equivalent=True,
        pairing_confidence=0.5,
    )
    out = rerank_weak_pairs([pair])
    assert len(out) == 1, "positive control must not drop"
    assert out[0].pairing_confidence >= 0.7, (
        f"reranker should high-score the same-value pair, got "
        f"{out[0].pairing_confidence}: {out[0].rerank_rationale}"
    )
```

- [ ] **Step 2: Smoke-check the tests under skip (without API key)**

Run: `unset ANTHROPIC_API_KEY && uv run pytest tests/real_world/test_reranker_live.py -v 2>&1 | tail -5`
Expected: 3 skipped (skip reason: "ANTHROPIC_API_KEY required for live reranker").

- [ ] **Step 3: Run live with API key**

```bash
uv run pytest tests/real_world/test_reranker_live.py -v -m slow
```

Expected: 3 passed. If any of the failure-case tests don't pass:
- Adjust the prompt in `src/interlock/llm_pipeline/prompts/pair.md` (sharpen heuristic 3 + 4)
- Re-run; iterate until exit gate met
- Commit prompt revisions as separate commits before tagging the phase

- [ ] **Step 4: Commit live tests**

```bash
git add tests/real_world/test_reranker_live.py
git commit -m "test(real_world): Sprint 4 exit gate live-API tests (KRP-C, 150kVA, positive control)"
```

### Task 5.2: Docs + sprint exit tag

**Files:**
- Modify: `docs/AUTHORSHIP.md`
- Modify: `docs/TDD.md`

- [ ] **Step 1: AUTHORSHIP entry**

Read `docs/AUTHORSHIP.md` to find the Sprint 3 entry. Insert a Sprint 4 entry immediately after Sprint 3 (before the `## Phase 23 — Fork` heading):

```markdown
## Sprint 4 (v2) — LLM pairing reranker

Shipped via 4 phase tags (`phase-27.1-rerank-schemas` → `phase-27.4-rerank-ui`) plus a fifth phase-27.5 exit-gate commit on top of `v2.2-adjudicator`. Exit tag: `v2.3-reranker`.

**Components landed:**
- `src/interlock/llm_pipeline/schemas/pair.py` — `PairVerdict` pydantic v2 frozen model with score-range validation
- `src/interlock/llm_pipeline/pair.py` — `rerank_weak_pairs()` over Track 1 pairs with `pairing_confidence < 0.75`. Per-pair parallel via `ThreadPoolExecutor(5)`, diskcache namespace `llm-pair` keyed by record-tuple hash + prompt hash + model + PROMPT_VERSION. Hallucination guard: rationale must mention at least one of the two `raw_value`s; failures collapse to "keep Track 1 verdict". Decline-to-pair drops the pair; downstream `unpaired_a/b` absorbs the records.
- `src/interlock/llm_pipeline/prompts/pair.md` — system prompt with engineering-document specific decision rules (tutorial-diagram detection, sibling-row reasoning, value-equality-across-pages signal).
- `src/interlock/align/exact.py` — `AlignedPair` gains `rerank_rationale: str | None = None`, `reranked: bool = False` (back-compat defaults).
- `src/interlock/detect/mismatch.py` — `Flag` gains `rerank_rationale: str | None = None`; `detect_flags()` copies from pair.
- `src/interlock/pipeline.py` — `use_llm_reranker` kwarg (default False); reranker call wired between `combine_alignments` and `_stage("align", "done")`; new stage id `rerank`.
- `src/interlock/ui/app.py` — sidebar toggle (default off); `🤖 Reranked` badge replaces `⚠️ weak pair` when reranker ran; weak-score reranks show both badges; `st.info()` rationale line in expander; JSON export gains `rerank_rationale` key per accepted flag.

**Test surface delta:** +23 tests (6 PairVerdict + 3 AlignedPair back-compat + 10 reranker unit + 4 e2e integration). Live exit-gate tests (3, slow + needs_anthropic) gate sprint exit: KRP-C-1600SP vs LPS-RK-400SP and 150 kVA vs 100 kVA cases correctly decline-to-pair OR score < 0.5; positive control (5.75 % vs 5.75 %) scores ≥ 0.7. Total v2 test count at `v2.3-reranker`: **377 passing** + live-API slow-marked suites.

**Cost delta:** ~$0.005 per weak pair Sonnet, ~$0.10–$0.25 on fuse-heavy reviews. Locked Option 1 fixture ~$0.025 cold, $0 warm.

**Honest scope statement.** The reranker replaces Phase 19's heuristic *output* on weak pairs but Phase 19 heuristics still gate which pairs reach the reranker in the first place. The exit-gate corpus is anecdotal (3 cases) — broader per-class gold sets are Sprint 6 work. See `docs/TDD.md` § "Known limits — Sprint 4 LLM pairing reranker (v2)".
```

- [ ] **Step 2: TDD known-limits entry**

Read `docs/TDD.md` to find the existing `## Known limits — Sprint 3 adjudicator + provenance UX (v2)` section. Append a Sprint 4 sub-section immediately after it (before `## Open questions + future work`):

```markdown
## Known limits — Sprint 4 LLM pairing reranker (v2)

The reranker ships behind `use_llm_reranker=False` (default off in both API and UI). When OFF, the pipeline is bit-identical to `v2.2-adjudicator`. When ON, only Track 1 weak pairs (`pairing_confidence < 0.75`) reach the reranker — strong pairs pass through untouched.

**Architecture that generalises:**
- `PairVerdict` pydantic schema (score + rationale + decline_to_pair)
- Per-pair parallel `ThreadPoolExecutor(5)` reranker with diskcache by record-tuple hash
- Hallucination guard: rationale must mention at least one `raw_value`
- Pure pass-through default: failure modes (API outage, parse error, validation error, hallucination rejection) all collapse to "keep Track 1 verdict"
- 🤖 Reranked badge replaces ⚠️ weak pair when reranker has spoken

**Heuristics + scope deliberately limited in Sprint 4:**
- Only fires on pairs Track 1 already produced. Records that Track 1's Phase 19 gates declined to pair never reach the reranker — they stay in `unpaired_a/b`. Sprint 4 does NOT relitigate Track 1's "skip entirely" verdicts.
- Eval surface is **3 hand-coded cases** (KRP-C-1600SP vs LPS-RK-400SP, 150 kVA vs 100 kVA, positive 5.75 % control). Statistically thin — Sprint 6 builds per-class gold sets with broader pairing-error labels.
- Reranker context is record-fields + span_text only; no page image, no sibling-row enrichment beyond what span_text naturally carries. The "Eaton tutorial 200A vs 400A" demo failure case (where both labels co-occur on the same page) needs the prompt's heuristic 4 to fire on the LLM's prior knowledge of tutorial-diagram structure — works in practice on Sonnet 4.5 but isn't a strong guarantee.
- Default OFF. Reviewers who flip it on for a fuse-heavy coordination study pay $0.10–$0.25 per fresh review. Diskcache means rerun is free.

**Generalisation plan** (post-Sprint 4):
1. Sprint 5 — Standards-as-RAG (per-clause retrieval per flag) + coupled-effect graph traversal (accept impedance ⇒ surface dependent claims)
2. Sprint 6 — per-class gold sets with broader pairing-error labels; continuous CI gates
3. Backlog — page-image context (vision) for one-line-diagram disambiguation if Sprint 6 reveals systematic recall gaps
```

- [ ] **Step 3: Run full regression to confirm nothing broke**

Run: `uv run pytest --deselect tests/real_world -q 2>&1 | tail -3`
Expected: 377 passed.

- [ ] **Step 4: Commit docs + sprint exit tag**

```bash
git add docs/AUTHORSHIP.md docs/TDD.md docs/superpowers/plans/2026-05-22-sprint-4-pairing-reranker.md
git commit -m "docs(sprint4): AUTHORSHIP per-phase entry + TDD known-limits + plan"
git tag v2.3-reranker -m "v2.3 — LLM pairing reranker. Weak Track 1 pairs get reasoned verdicts; decline-to-pair drops false-positive pairs. 377 tests passing."
git push origin main v2.3-reranker
```

---

## Self-review checklist (run before merge)

- [ ] Every spec section §1–§7 traces to at least one task above
- [ ] No "TBD" / "TODO" / "implement later" strings in the plan
- [ ] Every code block specifies a complete, runnable change
- [ ] Tag names follow `phase-27.<N>-<slug>` convention
- [ ] Final tag is `v2.3-reranker`
- [ ] v2.2 snapshot equivalence test exists (Phase 27.3 Task 3.2 first test)
- [ ] Hallucination guard test exists (Phase 27.2 Task 2.2 `test_hallucination_guard_keeps_track_1`)
- [ ] Decline-to-pair drop test exists (Phase 27.2 Task 2.2 `test_decline_to_pair_drops_pair`)
- [ ] Live exit gate tests cover the two named PIVOT_PLAN cases
- [ ] Cross-test for Sprint 3 + 4 label coexistence (`test_sprint3_provenance_and_sprint4_rationale_coexist`)
- [ ] Honest-scope disclosure shipped in `docs/TDD.md` (Task 5.2)
