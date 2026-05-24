"""Sprint 8 — vision extractor unit tests (mocked Sonnet 4.5 Vision)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import fitz
import pytest

from interlock.cache import disk as disk_cache

# These tests EXERCISE vision_extract_page directly; opt out of the
# global conftest stub that defaults it to return [].
pytestmark = pytest.mark.vision_lane


def _make_pdf(tmp_path: Path, text: str) -> Path:
    p = tmp_path / "test.pdf"
    doc = fitz.open()
    pg = doc.new_page()
    pg.insert_text((72, 72), text, fontsize=10)
    doc.save(p)
    doc.close()
    return p


def _fake_response(payload: dict) -> MagicMock:
    content = MagicMock()
    content.text = json.dumps(payload)
    return MagicMock(content=[content])


@pytest.fixture(autouse=True)
def _clear_vision_cache():  # type: ignore[no-untyped-def]
    disk_cache.clear_namespace("llm-vision")
    yield
    disk_cache.clear_namespace("llm-vision")


def test_vision_extract_parses_valid_response(mocker, monkeypatch, tmp_path) -> None:  # type: ignore[no-untyped-def]
    from interlock.llm_pipeline.vision_extract import vision_extract_page
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    pdf = _make_pdf(tmp_path, "LPS-RK-100SP transformer page")
    mocker.patch(
        "interlock.llm_pipeline.vision_extract._call_claude_vision",
        return_value=_fake_response({
            "page": 1,
            "page_understanding": "test",
            "page_layout": "diagram",
            "claims": [
                {
                    "entity_kind": "equipment",
                    "entity_id": "LPS-RK-100SP",
                    "entity_location_hint": "top",
                    "parameter_name": "Fuse Designation",
                    "raw_value": "LPS-RK-100SP",
                    "visual_evidence": "Label below transformer symbol.",
                },
            ],
        }),
    )
    out = vision_extract_page(str(pdf), 1, doc_id="d")
    assert len(out) == 1
    assert out[0].entity_tag == "LPS-RK-100SP"
    assert out[0].extraction_lane == "vision"
    assert out[0].raw_value == "LPS-RK-100SP"
    assert out[0].name == "Fuse Designation"


def test_vision_extract_parses_fenced_json(mocker, monkeypatch, tmp_path) -> None:  # type: ignore[no-untyped-def]
    """Sonnet may wrap JSON in a markdown ```json fence; parser must handle."""
    from interlock.llm_pipeline.vision_extract import vision_extract_page
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    pdf = _make_pdf(tmp_path, "XFMR-001 spec sheet")
    fenced = (
        '```json\n'
        '{"page":1,"page_understanding":"x","page_layout":"prose","claims":['
        '{"entity_kind":"equipment","entity_id":"XFMR-001","entity_location_hint":"",'
        '"parameter_name":"Voltage","raw_value":"480V","visual_evidence":"e"}'
        ']}\n'
        '```'
    )
    resp = MagicMock(content=[MagicMock(text=fenced)])
    mocker.patch(
        "interlock.llm_pipeline.vision_extract._call_claude_vision",
        return_value=resp,
    )
    out = vision_extract_page(str(pdf), 1, doc_id="d")
    assert len(out) == 1
    assert out[0].entity_tag == "XFMR-001"


def test_vision_extract_api_failure_returns_empty(mocker, monkeypatch, tmp_path) -> None:  # type: ignore[no-untyped-def]
    from interlock.llm_pipeline.vision_extract import vision_extract_page
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    pdf = _make_pdf(tmp_path, "x")
    mocker.patch(
        "interlock.llm_pipeline.vision_extract._call_claude_vision",
        side_effect=RuntimeError("API down"),
    )
    assert vision_extract_page(str(pdf), 1, doc_id="d") == []


def test_vision_extract_parse_failure_returns_empty(mocker, monkeypatch, tmp_path) -> None:  # type: ignore[no-untyped-def]
    from interlock.llm_pipeline.vision_extract import vision_extract_page
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    pdf = _make_pdf(tmp_path, "x")
    mocker.patch(
        "interlock.llm_pipeline.vision_extract._call_claude_vision",
        return_value=_fake_response({"not": "a valid VisionPageResult"}),
    )
    assert vision_extract_page(str(pdf), 1, doc_id="d") == []


def test_vision_extract_hallucination_guard_drops_invented_entity(
    mocker, monkeypatch, tmp_path,
) -> None:  # type: ignore[no-untyped-def]
    """Claim whose entity_id substring is NOT in the page text → dropped."""
    from interlock.llm_pipeline.vision_extract import vision_extract_page
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    pdf = _make_pdf(tmp_path, "ONLY LPS-RK-100SP is on this page")
    mocker.patch(
        "interlock.llm_pipeline.vision_extract._call_claude_vision",
        return_value=_fake_response({
            "page": 1, "page_understanding": "x", "page_layout": "diagram",
            "claims": [
                {
                    "entity_kind": "equipment", "entity_id": "LPS-RK-100SP",
                    "entity_location_hint": "", "parameter_name": "P",
                    "raw_value": "V", "visual_evidence": "e",
                },
                {
                    "entity_kind": "equipment", "entity_id": "HALLUCINATED-XYZ",
                    "entity_location_hint": "", "parameter_name": "P",
                    "raw_value": "V", "visual_evidence": "e",
                },
            ],
        }),
    )
    out = vision_extract_page(str(pdf), 1, doc_id="d")
    ids = [r.entity_tag for r in out]
    assert "LPS-RK-100SP" in ids
    assert "HALLUCINATED-XYZ" not in ids


def test_vision_extract_diskcache_hit(mocker, monkeypatch, tmp_path) -> None:  # type: ignore[no-untyped-def]
    from interlock.llm_pipeline.vision_extract import vision_extract_page
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    pdf = _make_pdf(tmp_path, "X with content")
    spy = mocker.patch(
        "interlock.llm_pipeline.vision_extract._call_claude_vision",
        return_value=_fake_response({
            "page": 1, "page_understanding": "x", "page_layout": "diagram",
            "claims": [],
        }),
    )
    vision_extract_page(str(pdf), 1, doc_id="d")
    assert spy.call_count == 1
    vision_extract_page(str(pdf), 1, doc_id="d")  # cache hit
    assert spy.call_count == 1


def test_vision_extract_diskcache_resolves_path(mocker, monkeypatch, tmp_path) -> None:  # type: ignore[no-untyped-def]
    """Sprint 8 cache audit — different paths to the same file (e.g. with
    './' prefix, symlink, or via relative cwd) must hit the same key.
    Otherwise the second call re-invokes the Anthropic API."""
    from interlock.llm_pipeline.vision_extract import vision_extract_page
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    pdf = _make_pdf(tmp_path, "ANCHOR-XYZ content")
    spy = mocker.patch(
        "interlock.llm_pipeline.vision_extract._call_claude_vision",
        return_value=_fake_response({
            "page": 1, "page_understanding": "x", "page_layout": "diagram",
            "claims": [],
        }),
    )
    # First call uses the canonical absolute path.
    vision_extract_page(str(pdf), 1, doc_id="d")
    assert spy.call_count == 1
    # Second call uses a path that resolves to the same file (insert './'
    # midway so the raw string differs but Path.resolve() collapses it).
    aliased = str(pdf.parent) + "/./" + pdf.name
    assert aliased != str(pdf)
    vision_extract_page(aliased, 1, doc_id="d")
    assert spy.call_count == 1, "expected cache hit via Path.resolve()"


def test_vision_extract_diskcache_invalidates_on_pdf_replace(  # type: ignore[no-untyped-def]
    mocker, monkeypatch, tmp_path,
) -> None:
    """Sprint 8 cache audit — replacing the PDF in place with new content
    must invalidate the cache via size/mtime, even if the same path is
    reused."""
    import time as _time

    from interlock.llm_pipeline.vision_extract import vision_extract_page
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    pdf = _make_pdf(tmp_path, "ORIGINAL CONTENT entity ALPHA-1")
    spy = mocker.patch(
        "interlock.llm_pipeline.vision_extract._call_claude_vision",
        return_value=_fake_response({
            "page": 1, "page_understanding": "x", "page_layout": "diagram",
            "claims": [],
        }),
    )
    vision_extract_page(str(pdf), 1, doc_id="d")
    assert spy.call_count == 1
    # Replace the PDF in place with materially different content.
    # Sleep 1.1s so mtime tick is observable on filesystems with 1s mtime.
    _time.sleep(1.1)
    pdf.unlink()
    pdf2 = _make_pdf(tmp_path, "REPLACED CONTENT entity OMEGA-9 with more text")
    assert str(pdf2) == str(pdf)
    vision_extract_page(str(pdf), 1, doc_id="d")
    assert spy.call_count == 2, "expected cache miss after PDF replace"


def test_vision_extract_sets_extraction_lane_vision(
    mocker, monkeypatch, tmp_path,
) -> None:  # type: ignore[no-untyped-def]
    from interlock.llm_pipeline.vision_extract import vision_extract_page
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    pdf = _make_pdf(tmp_path, "TANK-1 on page")
    mocker.patch(
        "interlock.llm_pipeline.vision_extract._call_claude_vision",
        return_value=_fake_response({
            "page": 1, "page_understanding": "x", "page_layout": "diagram",
            "claims": [
                {
                    "entity_kind": "equipment", "entity_id": "TANK-1",
                    "entity_location_hint": "", "parameter_name": "Volume",
                    "raw_value": "100 gal", "visual_evidence": "e",
                },
            ],
        }),
    )
    out = vision_extract_page(str(pdf), 1, doc_id="d")
    assert len(out) == 1
    assert out[0].extraction_lane == "vision"


def test_vision_extract_empty_claims_returns_empty(
    mocker, monkeypatch, tmp_path,
) -> None:  # type: ignore[no-untyped-def]
    from interlock.llm_pipeline.vision_extract import vision_extract_page
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    pdf = _make_pdf(tmp_path, "x")
    mocker.patch(
        "interlock.llm_pipeline.vision_extract._call_claude_vision",
        return_value=_fake_response({
            "page": 1, "page_understanding": "x", "page_layout": "diagram",
            "claims": [],
        }),
    )
    assert vision_extract_page(str(pdf), 1, doc_id="d") == []


def test_vision_extract_pdf_missing_returns_empty(monkeypatch, tmp_path) -> None:  # type: ignore[no-untyped-def]
    from interlock.llm_pipeline.vision_extract import vision_extract_page
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    assert vision_extract_page(str(tmp_path / "missing.pdf"), 1, doc_id="d") == []


def test_hallucination_guard_accepts_line_broken_compound_id(
    mocker, monkeypatch, tmp_path,
) -> None:  # type: ignore[no-untyped-def]
    """Vision often emits compound entity_ids like '1000KVA 480/277V'
    that appear on the page split across line breaks. Whitespace-
    normalized substring matching must accept those."""
    from interlock.llm_pipeline.vision_extract import vision_extract_page
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    # Page text has the tokens on separate lines (PyMuPDF reads diagram
    # callouts in draw order, so multi-line is common).
    pdf = _make_pdf(tmp_path, "Equipment list:\n1000KVA\n480/277V\nsome other text")
    mocker.patch(
        "interlock.llm_pipeline.vision_extract._call_claude_vision",
        return_value=_fake_response({
            "page": 1, "page_understanding": "x", "page_layout": "diagram",
            "claims": [
                {
                    "entity_kind": "equipment", "entity_id": "1000KVA 480/277V",
                    "entity_location_hint": "", "parameter_name": "Transformer Rating",
                    "raw_value": "1000 kVA", "visual_evidence": "label below symbol",
                },
            ],
        }),
    )
    out = vision_extract_page(str(pdf), 1, doc_id="d")
    assert len(out) == 1, (
        "expected compound entity_id to ground via whitespace-normalized check"
    )
    assert out[0].entity_tag == "1000KVA 480/277V"


def test_hallucination_guard_per_word_fallback_accepts_reordered_tokens(
    mocker, monkeypatch, tmp_path,
) -> None:  # type: ignore[no-untyped-def]
    """When the model reorders tokens (e.g. emits '60HP 3Ø 7.7A FLA'
    but the page shows '60HP 7.7A 3Ø FLA' elsewhere), per-word fallback
    must accept it as long as every word appears on the page."""
    from interlock.llm_pipeline.vision_extract import vision_extract_page
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    pdf = _make_pdf(tmp_path, "Motor data:\n60HP 7.7A 3Ø FLA cont duty")
    mocker.patch(
        "interlock.llm_pipeline.vision_extract._call_claude_vision",
        return_value=_fake_response({
            "page": 1, "page_understanding": "x", "page_layout": "diagram",
            "claims": [
                {
                    "entity_kind": "equipment", "entity_id": "60HP 3Ø 7.7A FLA",
                    "entity_location_hint": "", "parameter_name": "Motor Rating",
                    "raw_value": "60 HP", "visual_evidence": "ms",
                },
            ],
        }),
    )
    out = vision_extract_page(str(pdf), 1, doc_id="d")
    assert len(out) == 1


def test_hallucination_guard_still_rejects_pure_inventions(
    mocker, monkeypatch, tmp_path,
) -> None:  # type: ignore[no-untyped-def]
    """Pure inventions (no overlapping tokens with page text) must still
    be dropped — the per-word fallback can't open the door wide enough
    to let made-up labels through."""
    from interlock.llm_pipeline.vision_extract import vision_extract_page
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    pdf = _make_pdf(tmp_path, "Only LPS-RK-100SP and KRP-C-1600SP on this page")
    mocker.patch(
        "interlock.llm_pipeline.vision_extract._call_claude_vision",
        return_value=_fake_response({
            "page": 1, "page_understanding": "x", "page_layout": "diagram",
            "claims": [
                {
                    "entity_kind": "equipment", "entity_id": "ZYX-9999",
                    "entity_location_hint": "", "parameter_name": "P",
                    "raw_value": "V", "visual_evidence": "e",
                },
            ],
        }),
    )
    out = vision_extract_page(str(pdf), 1, doc_id="d")
    assert out == [], "pure invention must still be dropped"
