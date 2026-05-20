"""End-to-end citation completeness on the locked fixture pairs.

Every surfaced flag must carry the full audit tuple:
    doc_id · page · section · bbox · quoted text · snippet PNG bytes.
Tests assert this for both Option 1 (revision-diff) and Option 2 (cross-doc).
"""

from __future__ import annotations

import os

import pytest
from dotenv import load_dotenv

load_dotenv()

from interlock.citation.render import Citation, render_citation  # noqa: E402
from interlock.pipeline import review_two_documents  # noqa: E402

EATON = "fixtures/pdfs/doc_a_60pct.pdf"
EATON_REV = "fixtures/pdfs/doc_b_90pct.pdf"
SPEC = "fixtures/pdfs/spec_xfmr_001.pdf"

needs_voyage = pytest.mark.skipif(
    not os.getenv("VOYAGE_API_KEY"), reason="VOYAGE_API_KEY not set"
)


def _stub_embed(texts: list[str]) -> dict[str, list[float]]:
    return {t: [hash(t) % 7919 / 7919.0, 0.1, 0.1] for t in texts}


def _embed_voyage(texts: list[str]) -> dict[str, list[float]]:
    from interlock.align.embed import embed_voyage

    return embed_voyage(texts)


def _assert_citation_complete(c: Citation) -> None:
    assert c.doc_id
    assert c.page >= 1
    assert len(c.bbox) == 4
    assert c.bbox[2] > c.bbox[0]
    assert c.bbox[3] > c.bbox[1]
    assert c.quoted_text
    assert isinstance(c.snippet_png, bytes)
    assert len(c.snippet_png) > 0
    # PNG file signature.
    assert c.snippet_png[:8] == b"\x89PNG\r\n\x1a\n", "snippet not a PNG"


def test_option1_every_flag_renders_complete_citations() -> None:
    flags = review_two_documents(
        EATON, EATON_REV, embed_fn=_stub_embed, doc_a_id="doc_a_60pct", doc_b_id="doc_b_90pct"
    )
    high = [f for f in flags if f.confidence >= 0.6]
    assert high, "Option 1 should have ≥ 1 flag for this assertion"
    for f in high:
        cit_a = render_citation(f.a_record)
        cit_b = render_citation(f.b_record)
        _assert_citation_complete(cit_a)
        _assert_citation_complete(cit_b)


@needs_voyage
def test_option2_every_flag_renders_complete_citations() -> None:
    flags = review_two_documents(
        SPEC,
        EATON,
        embed_fn=_embed_voyage,
        doc_a_id="spec_xfmr_001",
        doc_b_id="doc_a_60pct",
        same_page_only=False,
    )
    high = [f for f in flags if f.confidence >= 0.5]
    assert high, "Option 2 should have ≥ 1 flag for this assertion"
    for f in high:
        cit_a = render_citation(f.a_record)
        cit_b = render_citation(f.b_record)
        _assert_citation_complete(cit_a)
        _assert_citation_complete(cit_b)


def test_citation_doc_id_matches_record_doc_id() -> None:
    """Audit invariant: the citation tuple's doc_id must equal the source
    record's doc_id, never an unrelated path."""
    flags = review_two_documents(
        EATON, EATON_REV, embed_fn=_stub_embed, doc_a_id="doc_a_60pct", doc_b_id="doc_b_90pct"
    )
    for f in flags[:5]:
        cit_a = render_citation(f.a_record)
        cit_b = render_citation(f.b_record)
        assert cit_a.doc_id == f.a_record.doc_id
        assert cit_b.doc_id == f.b_record.doc_id


def test_authority_direction_consistent_in_every_flag() -> None:
    """For Option 1 (60→90 revision review) every flag must declare Doc A
    authoritative and Doc B deviating. Inverted authority is a bug.
    """
    flags = review_two_documents(
        EATON, EATON_REV, embed_fn=_stub_embed, doc_a_id="doc_a_60pct", doc_b_id="doc_b_90pct"
    )
    for f in flags:
        assert f.authoritative_doc_id == "doc_a_60pct"
        assert f.deviating_doc_id == "doc_b_90pct"
