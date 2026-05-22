"""Sprint 2 — provenance field on ParameterRecord.

The field defaults to "regex" so every existing test that constructs
ParameterRecord by hand keeps working. Track 1 extractor populates it
implicitly via the default. Track 2 (Sprint 2) sets it to "llm"
explicitly at downcast time.
"""

from __future__ import annotations

from interlock.extract.parameters import ParameterRecord


def _rec(provenance: str = "regex") -> ParameterRecord:
    """Construct a minimal ParameterRecord for tests."""
    return ParameterRecord(
        doc_id="d",
        page=1,
        bbox=(0, 0, 100, 10),
        section=None,
        span_text="5.75%Z",
        name="%Z",
        raw_value="5.75 %",
        normalized_magnitude=0.0575,
        normalized_unit="dimensionless",
        provenance=provenance,  # type: ignore[arg-type]
    )


def test_provenance_defaults_to_regex() -> None:
    """No explicit provenance kwarg ⇒ field defaults to 'regex'."""
    r = ParameterRecord(
        doc_id="d", page=1, bbox=(0, 0, 100, 10), section=None,
        span_text="5.75%Z", name="%Z", raw_value="5.75 %",
        normalized_magnitude=0.0575, normalized_unit="dimensionless",
    )
    assert r.provenance == "regex"


def test_provenance_can_be_llm() -> None:
    r = _rec(provenance="llm")
    assert r.provenance == "llm"


def test_existing_extract_parameters_emit_regex_provenance() -> None:
    """v1's regex extractor must keep emitting records that downstream
    can identify as Track 1."""
    from interlock.extract.parameters import extract_parameters
    from interlock.ingest.text import Span

    spans = [Span(doc_id="d", page=1, bbox=(0, 0, 100, 10), text="5.75%Z, liquid")]
    records = extract_parameters(spans)
    assert records
    for r in records:
        assert r.provenance == "regex"
