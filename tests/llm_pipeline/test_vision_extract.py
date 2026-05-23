"""Sprint 8 — vision extractor unit tests (mocked Sonnet 4.5 Vision)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import fitz
import pytest

from interlock.cache import disk as disk_cache


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
