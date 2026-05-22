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
