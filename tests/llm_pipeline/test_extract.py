"""Sprint 2 — LLM extractor tests (mocked Claude). Live-API behavior
is verified in tests/real_world/test_llm_extraction_live.py."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from interlock.cache import disk as disk_cache

DOC_A = "fixtures/pdfs/doc_a_60pct.pdf"


@pytest.fixture(autouse=True)
def _clear_extract_cache() -> None:
    disk_cache.clear_namespace("llm-extract")
    yield
    disk_cache.clear_namespace("llm-extract")


def test_render_page_text_returns_native_text() -> None:
    """Helper extracts page text via PyMuPDF (the same source v1 uses)."""
    from interlock.llm_pipeline.extract import _render_page_text
    text = _render_page_text(DOC_A, page=1)
    assert isinstance(text, str)
    assert len(text) > 100


def test_render_page_text_out_of_range_returns_empty() -> None:
    """Page beyond doc length returns empty string, not exception."""
    from interlock.llm_pipeline.extract import _render_page_text
    text = _render_page_text(DOC_A, page=99999)
    assert text == ""


def test_render_page_text_missing_file_returns_empty() -> None:
    from interlock.llm_pipeline.extract import _render_page_text
    text = _render_page_text("/nonexistent.pdf", page=1)
    assert text == ""


def _fake_response(text: str) -> MagicMock:
    content = MagicMock()
    content.text = text
    return MagicMock(content=[content])


def test_call_claude_extract_constructs_text_only_message(mocker, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """The call must send NO image content (text-only) and include the
    composed prompt + the page text."""
    from interlock.llm_pipeline.extract import _call_claude_extract

    # Production code reads ANTHROPIC_API_KEY at client construction;
    # the SDK is mocked but Python still evaluates the kwarg expression.
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    fake_resp = _fake_response('{"claims":[],"page":1,"notes":""}')
    create = mocker.patch("interlock.llm_pipeline.extract.Anthropic")
    create.return_value.messages.create.return_value = fake_resp
    _call_claude_extract("PAGE TEXT HERE", "PROMPT HERE")
    call_args = create.return_value.messages.create.call_args
    msg = call_args.kwargs["messages"][0]
    assert msg["role"] == "user"
    content_blocks = msg["content"]
    assert all(b["type"] == "text" for b in content_blocks)
    joined = " ".join(b["text"] for b in content_blocks)
    assert "PAGE TEXT HERE" in joined
    assert "PROMPT HERE" in joined


def test_parse_page_payload_handles_strict_json() -> None:
    from interlock.llm_pipeline.extract import _parse_page_payload
    raw = (
        '{"claims":[{"parameter_name":"%Z","raw_value":"5.75 %",'
        '"span_text":"5.75%Z","page":3,"confidence":0.9}],'
        '"page":3,"notes":""}'
    )
    out = _parse_page_payload(raw)
    assert out.page == 3
    assert len(out.claims) == 1
    assert out.claims[0].parameter_name == "%Z"


def test_parse_page_payload_handles_fenced_json() -> None:
    """Some models wrap JSON in ```json fences."""
    from interlock.llm_pipeline.extract import _parse_page_payload
    raw = (
        'Here is the JSON:\n```json\n'
        '{"claims":[],"page":1,"notes":"empty"}\n```'
    )
    out = _parse_page_payload(raw)
    assert out.page == 1
    assert out.claims == []


def test_hallucination_guard_drops_claims_with_invented_span_text() -> None:
    """span_text must be a verbatim substring of the page text — otherwise
    the LLM invented it. Drop pre-downcast."""
    from interlock.llm_pipeline.extract import _filter_hallucinated_claims
    from interlock.llm_pipeline.schemas.claim import ExtractedClaim

    page_text = "Transformer XFMR-001 rated 1000 kVA, 5.75 %Z impedance, liquid-filled."
    claims = [
        ExtractedClaim(
            parameter_name="%Z", raw_value="5.75 %",
            span_text="5.75 %Z impedance",
            page=1, confidence=0.9,
        ),
        ExtractedClaim(
            parameter_name="%Z", raw_value="0.575 %",
            span_text="impedance is 0.575 percent, not in the source",
            page=1, confidence=0.9,
        ),
    ]
    surviving = _filter_hallucinated_claims(claims, page_text)
    assert len(surviving) == 1
    assert surviving[0].raw_value == "5.75 %"


def test_extract_claims_from_doc_returns_parameter_records(mocker) -> None:  # type: ignore[no-untyped-def]
    """End-to-end: PDF → list[ParameterRecord] w/ provenance='llm'."""
    from interlock.llm_pipeline.extract import extract_claims_from_doc
    from interlock.llm_pipeline.schemas.doc_class import DocClass

    fake_json = (
        '{"claims":[{"parameter_name":"%Z","raw_value":"5.75 %",'
        '"entity_tag":"2","span_text":"5.75",'
        '"page":1,"confidence":0.9}],"page":1,"notes":""}'
    )
    # Hallucination guard checks "5.75" is in the page text. Doc A's pages
    # contain "5.75%Z" so this passes.
    mocker.patch(
        "interlock.llm_pipeline.extract._call_claude_extract",
        return_value=_fake_response(fake_json),
    )
    records = extract_claims_from_doc(DOC_A, DocClass.coordination_study)
    assert all(r.provenance == "llm" for r in records)
    assert len(records) >= 1
    impedance_records = [r for r in records if r.name == "%Z"]
    assert impedance_records


def test_extract_claims_diskcached_skips_second_call(mocker) -> None:  # type: ignore[no-untyped-def]
    """Per-page diskcache: same PDF run twice → second run uses cache only."""
    from interlock.llm_pipeline.extract import extract_claims_from_doc
    from interlock.llm_pipeline.schemas.doc_class import DocClass

    fake_json = '{"claims":[],"page":1,"notes":""}'
    spy = mocker.patch(
        "interlock.llm_pipeline.extract._call_claude_extract",
        return_value=_fake_response(fake_json),
    )
    extract_claims_from_doc(DOC_A, DocClass.coordination_study)
    first_call_count = spy.call_count
    extract_claims_from_doc(DOC_A, DocClass.coordination_study)
    assert spy.call_count == first_call_count, (
        "second call should be all-cache hits, no new API calls"
    )


def test_extract_claims_continues_on_per_page_failure(mocker) -> None:  # type: ignore[no-untyped-def]
    """A single page raising must not abort the whole document."""
    from interlock.llm_pipeline.extract import extract_claims_from_doc
    from interlock.llm_pipeline.schemas.doc_class import DocClass

    call_count = {"n": 0}

    def flaky_call(*args, **kwargs):  # type: ignore[no-untyped-def]
        call_count["n"] += 1
        if call_count["n"] == 3:
            raise RuntimeError("simulated API failure on page 3")
        return _fake_response('{"claims":[],"page":1,"notes":""}')

    mocker.patch(
        "interlock.llm_pipeline.extract._call_claude_extract",
        side_effect=flaky_call,
    )
    records = extract_claims_from_doc(DOC_A, DocClass.coordination_study)
    assert isinstance(records, list)


def test_extract_claims_validation_failure_returns_empty_for_that_page(mocker) -> None:  # type: ignore[no-untyped-def]
    """Malformed JSON / schema mismatch → that page contributes 0 claims."""
    from interlock.llm_pipeline.extract import extract_claims_from_doc
    from interlock.llm_pipeline.schemas.doc_class import DocClass

    mocker.patch(
        "interlock.llm_pipeline.extract._call_claude_extract",
        return_value=_fake_response("this is not JSON at all"),
    )
    records = extract_claims_from_doc(DOC_A, DocClass.coordination_study)
    assert records == []


def test_hallucination_guard_whitespace_tolerant() -> None:
    """Real claim w/ minor whitespace differences from source should survive."""
    from interlock.llm_pipeline.extract import _filter_hallucinated_claims
    from interlock.llm_pipeline.schemas.claim import ExtractedClaim

    page_text = "Rated 1000 kVA,  13.8 kV primary."  # double space in source
    claims = [
        ExtractedClaim(
            parameter_name="Transformer Rating",
            raw_value="1000 kVA",
            span_text="Rated 1000 kVA, 13.8 kV primary.",  # single space
            page=1, confidence=0.95,
        ),
    ]
    surviving = _filter_hallucinated_claims(claims, page_text)
    assert len(surviving) == 1
