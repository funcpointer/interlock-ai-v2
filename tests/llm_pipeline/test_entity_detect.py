"""Sprint 4.5 — entity detector unit tests (mocked Claude)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from interlock.cache import disk as disk_cache


def _fake_response(text: str) -> MagicMock:
    content = MagicMock()
    content.text = text
    return MagicMock(content=[content])


@pytest.fixture(autouse=True)
def _clear_entity_cache() -> None:
    disk_cache.clear_namespace("llm-entities")
    yield
    disk_cache.clear_namespace("llm-entities")


def test_detect_entities_returns_validated_list(mocker, monkeypatch, tmp_path) -> None:  # type: ignore[no-untyped-def]
    from interlock.llm_pipeline.entity_detect import detect_entities_on_page
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    pdf = tmp_path / "x.pdf"
    pdf.write_bytes(b"%PDF-1.4\n%%EOF\n")
    mocker.patch(
        "interlock.llm_pipeline.entity_detect._render_page_text",
        return_value="JCN80E motor on the page",
    )
    mocker.patch(
        "interlock.llm_pipeline.entity_detect._call_claude_entity",
        return_value=_fake_response(
            '{"page":2,"entities":['
            '{"label":"JCN80E","kind":"equipment","y_top":100.0,"y_bottom":150.0,"page":2},'
            '{"label":"Main Bus","kind":"circuit","y_top":200.0,"y_bottom":230.0,"page":2}'
            ']}'
        ),
    )
    out = detect_entities_on_page(str(pdf), page=2)
    assert len(out) == 2
    assert out[0].label == "JCN80E"
    assert out[0].kind == "equipment"
    assert out[1].label == "Main Bus"


def test_detect_entities_for_doc_returns_dict_keyed_by_page(mocker, monkeypatch, tmp_path) -> None:  # type: ignore[no-untyped-def]
    from interlock.llm_pipeline.entity_detect import detect_entities_for_doc
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    pdf = tmp_path / "x.pdf"
    pdf.write_bytes(b"%PDF-1.4\n%%EOF\n")
    mocker.patch(
        "interlock.llm_pipeline.entity_detect._page_count",
        return_value=2,
    )
    mocker.patch(
        "interlock.llm_pipeline.entity_detect._render_page_text",
        return_value="page text",
    )
    mocker.patch(
        "interlock.llm_pipeline.entity_detect._call_claude_entity",
        return_value=_fake_response(
            '{"page":1,"entities":['
            '{"label":"XFMR-001","kind":"equipment","y_top":0.0,"y_bottom":10.0,"page":1}'
            ']}'
        ),
    )
    out = detect_entities_for_doc(str(pdf))
    assert isinstance(out, dict)
    assert set(out.keys()) == {1, 2}
    assert all(isinstance(v, list) for v in out.values())


def test_detect_entities_api_failure_returns_empty(mocker, monkeypatch, tmp_path) -> None:  # type: ignore[no-untyped-def]
    from interlock.llm_pipeline.entity_detect import detect_entities_on_page
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    pdf = tmp_path / "x.pdf"
    pdf.write_bytes(b"%PDF-1.4\n%%EOF\n")
    mocker.patch(
        "interlock.llm_pipeline.entity_detect._render_page_text",
        return_value="text",
    )
    mocker.patch(
        "interlock.llm_pipeline.entity_detect._call_claude_entity",
        side_effect=RuntimeError("API down"),
    )
    assert detect_entities_on_page(str(pdf), page=1) == []


def test_detect_entities_parse_failure_returns_empty(mocker, monkeypatch, tmp_path) -> None:  # type: ignore[no-untyped-def]
    from interlock.llm_pipeline.entity_detect import detect_entities_on_page
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    pdf = tmp_path / "x.pdf"
    pdf.write_bytes(b"%PDF-1.4\n%%EOF\n")
    mocker.patch("interlock.llm_pipeline.entity_detect._render_page_text", return_value="text")
    mocker.patch(
        "interlock.llm_pipeline.entity_detect._call_claude_entity",
        return_value=_fake_response("not json"),
    )
    assert detect_entities_on_page(str(pdf), page=1) == []


def test_detect_entities_validation_failure_returns_empty(mocker, monkeypatch, tmp_path) -> None:  # type: ignore[no-untyped-def]
    """Score outside enum → pydantic rejects → empty list."""
    from interlock.llm_pipeline.entity_detect import detect_entities_on_page
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    pdf = tmp_path / "x.pdf"
    pdf.write_bytes(b"%PDF-1.4\n%%EOF\n")
    mocker.patch("interlock.llm_pipeline.entity_detect._render_page_text", return_value="text")
    mocker.patch(
        "interlock.llm_pipeline.entity_detect._call_claude_entity",
        return_value=_fake_response(
            '{"page":1,"entities":['
            '{"label":"X","kind":"bogus_kind","y_top":0,"y_bottom":1,"page":1}'
            ']}'
        ),
    )
    assert detect_entities_on_page(str(pdf), page=1) == []


def test_stoplist_drops_standards_bodies(mocker, monkeypatch, tmp_path) -> None:  # type: ignore[no-untyped-def]
    from interlock.llm_pipeline.entity_detect import detect_entities_on_page
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    pdf = tmp_path / "x.pdf"
    pdf.write_bytes(b"%PDF-1.4\n%%EOF\n")
    mocker.patch("interlock.llm_pipeline.entity_detect._render_page_text", return_value="text")
    mocker.patch(
        "interlock.llm_pipeline.entity_detect._call_claude_entity",
        return_value=_fake_response(
            '{"page":1,"entities":['
            '{"label":"IEEE","kind":"section","y_top":0,"y_bottom":10,"page":1},'
            '{"label":"NEMA","kind":"unknown","y_top":20,"y_bottom":30,"page":1},'
            '{"label":"XFMR-001","kind":"equipment","y_top":40,"y_bottom":50,"page":1}'
            ']}'
        ),
    )
    out = detect_entities_on_page(str(pdf), page=1)
    labels = {e.label for e in out}
    assert "IEEE" not in labels
    assert "NEMA" not in labels
    assert "XFMR-001" in labels


def test_drops_entities_with_inverted_y_range(mocker, monkeypatch, tmp_path) -> None:  # type: ignore[no-untyped-def]
    from interlock.llm_pipeline.entity_detect import detect_entities_on_page
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    pdf = tmp_path / "x.pdf"
    pdf.write_bytes(b"%PDF-1.4\n%%EOF\n")
    mocker.patch("interlock.llm_pipeline.entity_detect._render_page_text", return_value="text")
    mocker.patch(
        "interlock.llm_pipeline.entity_detect._call_claude_entity",
        return_value=_fake_response(
            '{"page":1,"entities":['
            '{"label":"BAD","kind":"equipment","y_top":100,"y_bottom":50,"page":1},'
            '{"label":"GOOD","kind":"equipment","y_top":50,"y_bottom":100,"page":1}'
            ']}'
        ),
    )
    out = detect_entities_on_page(str(pdf), page=1)
    labels = {e.label for e in out}
    assert "BAD" not in labels
    assert "GOOD" in labels


def test_diskcache_hit_skips_api(mocker, monkeypatch, tmp_path) -> None:  # type: ignore[no-untyped-def]
    from interlock.llm_pipeline.entity_detect import detect_entities_on_page
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    pdf = tmp_path / "x.pdf"
    pdf.write_bytes(b"%PDF-1.4\n%%EOF\n")
    mocker.patch("interlock.llm_pipeline.entity_detect._render_page_text", return_value="text")
    spy = mocker.patch(
        "interlock.llm_pipeline.entity_detect._call_claude_entity",
        return_value=_fake_response(
            '{"page":1,"entities":['
            '{"label":"XFMR-001","kind":"equipment","y_top":0,"y_bottom":10,"page":1}'
            ']}'
        ),
    )
    detect_entities_on_page(str(pdf), page=1)
    assert spy.call_count == 1
    detect_entities_on_page(str(pdf), page=1)  # cache hit
    assert spy.call_count == 1


def test_empty_page_text_returns_empty(mocker, monkeypatch, tmp_path) -> None:  # type: ignore[no-untyped-def]
    """If PyMuPDF render returns empty text, skip the API call."""
    from interlock.llm_pipeline.entity_detect import detect_entities_on_page
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    pdf = tmp_path / "x.pdf"
    pdf.write_bytes(b"%PDF-1.4\n%%EOF\n")
    mocker.patch("interlock.llm_pipeline.entity_detect._render_page_text", return_value="")
    spy = mocker.patch("interlock.llm_pipeline.entity_detect._call_claude_entity")
    out = detect_entities_on_page(str(pdf), page=1)
    assert out == []
    assert spy.call_count == 0
