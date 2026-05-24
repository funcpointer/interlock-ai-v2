"""v2.8.1 — canonical parameter-name alias tests."""

from __future__ import annotations


def test_impedance_aliases_collapse_to_transformer_impedance() -> None:
    """%Z (Track 1 regex) and 'Transformer Impedance' (Track 2 LLM) must
    collapse to the same canonical form so cross-lane dedup + alignment
    treat them as one parameter."""
    from interlock.extract.parameters import canonicalize_param_name
    assert canonicalize_param_name("%Z") == "Transformer Impedance"
    assert canonicalize_param_name("Transformer Impedance") == "Transformer Impedance"
    assert canonicalize_param_name("impedance") == "Transformer Impedance"
    assert canonicalize_param_name("Impedance %") == "Transformer Impedance"


def test_fla_aliases_collapse() -> None:
    from interlock.extract.parameters import canonicalize_param_name
    assert canonicalize_param_name("IFLA") == "Full Load Amperes"
    assert canonicalize_param_name("FLA") == "Full Load Amperes"
    assert canonicalize_param_name("Full Load Amperes") == "Full Load Amperes"


def test_passthrough_for_unknown_names() -> None:
    """Names with no alias survive unchanged — never silently rename
    something the alias map doesn't know."""
    from interlock.extract.parameters import canonicalize_param_name
    assert canonicalize_param_name("Something Bespoke") == "Something Bespoke"
    assert canonicalize_param_name("") == ""


def test_canonicalize_is_case_insensitive_keys() -> None:
    from interlock.extract.parameters import canonicalize_param_name
    assert canonicalize_param_name("%z") == "Transformer Impedance"
    assert canonicalize_param_name("  %Z  ") == "Transformer Impedance"


def test_extract_parameters_emits_canonical_names() -> None:
    """Track 1 regex extractor must apply canonicalize_param_name at
    emission time — downstream stages should never see '%Z' as a
    record.name on a regex-extracted record."""
    from interlock.extract.parameters import extract_parameters
    from interlock.ingest.text import Span

    spans = [
        Span(
            doc_id="d", page=1, bbox=(0.0, 0.0, 100.0, 10.0),
            text="5.75%Z, liquid filled", source_path="",
        ),
    ]
    recs = extract_parameters(spans)
    assert any(r.name == "Transformer Impedance" for r in recs), (
        f"expected canonical 'Transformer Impedance' in {[r.name for r in recs]}"
    )
    assert not any(r.name == "%Z" for r in recs), (
        "regex emitted raw '%Z' instead of canonical form"
    )
