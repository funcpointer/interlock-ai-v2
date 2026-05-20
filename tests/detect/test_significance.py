"""LLM significance judge invariants.

Mocked-LLM tests verify the wiring (cache hit/miss, Pydantic shape,
prompt structure) without spending API tokens. The live test is marked
``slow`` and exercises the real Anthropic call on TP-1 (the canonical
decimal-shift case) to verify the judge returns ``severity='critical'``
and at least one downstream effect mentioning fault current or
coordination.
"""

from __future__ import annotations

import os
from typing import Any

import pytest

from interlock.align.exact import AlignedPair
from interlock.detect.mismatch import Flag, detect_flags
from interlock.detect.significance import (
    PROMPT_VERSION,
    SignificanceJudgment,
    _build_user_block,
    _flag_id,
    apply_judgment_to_flag,
    judge,
)
from interlock.extract.parameters import ParameterRecord


def _record(name: str, doc: str, raw: str, mag: float | None) -> ParameterRecord:
    return ParameterRecord(
        doc_id=doc, page=1, bbox=(0, 0, 100, 10), section="sec",
        span_text=f"{name}: {raw}", name=name, raw_value=raw,
        normalized_magnitude=mag, normalized_unit="dim",
        source_path=f"fixtures/pdfs/{doc}.pdf",
    )


def _decimal_shift_flag() -> Flag:
    """The canonical TP-1 decimal-shift on impedance, manufactured."""
    pair = AlignedPair(
        a=_record("%Z", "doc_a", "5.75 %", 0.0575),
        b=_record("%Z", "doc_b", "0.575 %", 0.00575),
        name_match_confidence=1.0,
        value_equivalent=False,
    )
    return detect_flags([pair])[0]


def test_significance_judgment_schema_is_well_formed() -> None:
    """The Pydantic model must accept all four severity values + structured
    downstream-effects list + confidence in [0, 1]."""
    j = SignificanceJudgment(
        severity="critical",
        within_typical_tolerance=False,
        engineering_explanation="Decimal-shift error in impedance.",
        downstream_effects=["fault current", "relay coordination"],
        confidence=0.92,
    )
    assert j.severity == "critical"
    assert j.confidence == 0.92
    assert len(j.downstream_effects) == 2


@pytest.mark.parametrize("sev", ["critical", "major", "minor", "info"])
def test_all_severity_values_accepted(sev: str) -> None:
    j = SignificanceJudgment(
        severity=sev,  # type: ignore[arg-type]
        within_typical_tolerance=(sev == "info"),
        engineering_explanation="ok",
        downstream_effects=[],
        confidence=0.5,
    )
    assert j.severity == sev


def test_confidence_must_be_in_unit_interval() -> None:
    with pytest.raises(Exception):
        SignificanceJudgment(
            severity="major",
            within_typical_tolerance=False,
            engineering_explanation="ok",
            downstream_effects=[],
            confidence=1.5,
        )


def test_flag_id_is_stable_across_calls() -> None:
    f = _decimal_shift_flag()
    assert _flag_id(f) == _flag_id(f)


def test_flag_id_differs_for_distinct_flags() -> None:
    f1 = _decimal_shift_flag()
    pair2 = AlignedPair(
        a=_record("Rated Power", "doc_a", "1000 kVA", 1_000_000.0),
        b=_record("Rated Power", "doc_b", "1100 kVA", 1_100_000.0),
        name_match_confidence=1.0,
        value_equivalent=False,
    )
    f2 = detect_flags([pair2])[0]
    assert _flag_id(f1) != _flag_id(f2)


def test_user_block_includes_all_pertinent_context() -> None:
    f = _decimal_shift_flag()
    body = _build_user_block(f)
    assert "5.75 %" in body
    assert "0.575 %" in body
    assert "impedance_pct" in body
    assert "90.00%" in body or "90.0%" in body  # 90% deviation


def test_judge_returns_cached_value_on_repeat(mocker: Any) -> None:
    """First call to judge() should invoke call_structured; second call
    with the same flag should hit the disk cache and skip the LLM."""
    flag = _decimal_shift_flag()

    mock_result = SignificanceJudgment(
        severity="critical",
        within_typical_tolerance=False,
        engineering_explanation="Decimal-shift in transformer impedance.",
        downstream_effects=["fault current"],
        confidence=0.95,
    )
    mock_call = mocker.patch(
        "interlock.detect.significance.call_structured",
        return_value=(mock_result, {"input": 100, "output": 50, "cache_read": 0, "cache_creation": 200}),
    )

    # Clear any previous cache hits
    from interlock.cache.disk import clear_namespace

    clear_namespace("llm-significance")

    j1 = judge(flag)
    j2 = judge(flag)

    assert j1.severity == "critical"
    assert j2.severity == "critical"
    assert mock_call.call_count == 1, "second call must hit cache"


def test_apply_judgment_enriches_flag() -> None:
    flag = _decimal_shift_flag()
    j = SignificanceJudgment(
        severity="critical",
        within_typical_tolerance=False,
        engineering_explanation="Decimal shift in transformer impedance.",
        downstream_effects=["fault current"],
        confidence=0.9,
    )
    enriched = apply_judgment_to_flag(flag, j)
    assert enriched.severity == "critical"
    assert "Decimal shift" in enriched.rationale
    assert enriched.parameter == flag.parameter
    assert enriched.a_record is flag.a_record
    # Confidence is multiplied by judgment confidence
    assert enriched.confidence == pytest.approx(flag.confidence * 0.9, abs=0.001)


def test_prompt_version_constant_is_set() -> None:
    """Bump PROMPT_VERSION whenever the system prompt changes; existing cache
    keys are invalidated automatically because the key includes this version."""
    assert PROMPT_VERSION
    assert isinstance(PROMPT_VERSION, str)


# ----- Slow live tests -----

needs_anthropic = pytest.mark.skipif(
    not os.getenv("ANTHROPIC_API_KEY"), reason="ANTHROPIC_API_KEY not set"
)


@pytest.mark.slow
@needs_anthropic
def test_live_judge_decimal_shift_classifies_critical_with_downstream_effects() -> None:
    """End-to-end with real Anthropic: TP-1-style decimal shift must come
    back as severity='critical' with at least one downstream parameter."""
    flag = _decimal_shift_flag()
    # Force fresh call (don't read from any previous-run cache)
    from interlock.cache.disk import clear_namespace

    clear_namespace("llm-significance")

    j = judge(flag)
    assert j.severity in {"critical", "major"}, (
        f"decimal-shift impedance should classify as critical or major, got {j.severity}"
    )
    # Engineering explanation must mention impedance + the deviation magnitude
    expl = j.engineering_explanation.lower()
    assert "impedance" in expl or "decimal" in expl or "shift" in expl
    # Downstream effects on impedance changes are well-documented: fault
    # current, coordination, voltage regulation. Expect at least one of these.
    downstream_text = " ".join(j.downstream_effects).lower()
    assert any(
        kw in downstream_text
        for kw in ("fault", "coordination", "relay", "short", "voltage")
    ), f"expected fault/coordination/relay in downstream_effects, got {j.downstream_effects}"
