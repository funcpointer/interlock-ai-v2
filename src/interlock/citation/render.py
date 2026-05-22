"""Render a citation tuple with a bbox-highlighted PNG snippet of the source page."""

from __future__ import annotations

from dataclasses import dataclass

import fitz

from interlock.extract.parameters import ParameterRecord


@dataclass(frozen=True)
class Citation:
    doc_id: str
    page: int
    section: str | None
    bbox: tuple[float, float, float, float]
    quoted_text: str
    snippet_png: bytes


_PAD = 12
_DPI = 200


def render_citation(record: ParameterRecord) -> Citation:
    # Prefer source_path (always a real file path when populated by the
    # ingest pipeline); fall back to doc_id for direct/unit-test usage where
    # callers set doc_id == path.
    path = record.source_path or record.doc_id
    doc = fitz.open(path)
    try:
        page = doc[record.page - 1]
        rect = fitz.Rect(*record.bbox)
        # v2 Sprint 2 fix: LLM-extracted records carry bbox=(0,0,0,0) —
        # text-only LLM has no per-token coords. Detect zero-area bbox and
        # render the whole page without highlight so the snippet shows real
        # content instead of a blank 48×12 strip at the page top-left.
        if rect.is_empty or rect.get_area() <= 0:
            clip = page.rect
        else:
            page.draw_rect(rect, color=(1, 0, 0), width=1.5, overlay=True)
            clip = fitz.Rect(
                max(rect.x0 - _PAD, 0),
                max(rect.y0 - _PAD, 0),
                rect.x1 + _PAD * 4,  # extra horizontal context
                rect.y1 + _PAD,
            )
        pix = page.get_pixmap(clip=clip, dpi=_DPI)
        png = pix.tobytes("png")
    finally:
        doc.close()
    return Citation(
        doc_id=record.doc_id,
        page=record.page,
        section=record.section,
        bbox=record.bbox,
        quoted_text=record.span_text,
        snippet_png=png,
    )
