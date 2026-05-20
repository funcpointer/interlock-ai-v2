"""Text span extraction with bounding boxes via PyMuPDF.

A Span is the atomic unit downstream extractors consume: a contiguous run of text
with its page number, bbox, and source document id.

`aggregate_line_spans` joins adjacent spans on the same visual line so that
labels like "Rated\\nVoltage: 132 kV" become a single regex-matchable string.
"""

from __future__ import annotations

from dataclasses import dataclass

import fitz


@dataclass(frozen=True)
class Span:
    doc_id: str
    page: int
    bbox: tuple[float, float, float, float]
    text: str


def extract_spans(pdf_path: str, doc_id: str | None = None) -> list[Span]:
    did = doc_id or pdf_path
    out: list[Span] = []
    doc = fitz.open(pdf_path)
    try:
        for i, page in enumerate(doc, start=1):
            data = page.get_text("dict")
            for block in data.get("blocks", []):
                for line in block.get("lines", []):
                    for span in line.get("spans", []):
                        text = (span.get("text") or "").strip()
                        if not text:
                            continue
                        bbox = tuple(span["bbox"])
                        assert len(bbox) == 4
                        out.append(Span(doc_id=did, page=i, bbox=bbox, text=text))
    finally:
        doc.close()
    return out


def aggregate_line_spans(spans: list[Span], y_tol: float = 2.0) -> list[Span]:
    """Group spans on the same line (same page, y center within y_tol) into one Span.

    The merged Span's bbox is the union; its text is the original-order concatenation
    joined by a single space. Preserves doc_id and page.
    """
    if not spans:
        return []
    # Bucket by page first.
    by_page: dict[int, list[Span]] = {}
    for s in spans:
        by_page.setdefault(s.page, []).append(s)

    out: list[Span] = []
    for page, page_spans in by_page.items():
        # Sort by y_center then x.
        sorted_spans = sorted(page_spans, key=lambda s: ((s.bbox[1] + s.bbox[3]) / 2, s.bbox[0]))
        line: list[Span] = []
        line_y: float | None = None
        for s in sorted_spans:
            ymid = (s.bbox[1] + s.bbox[3]) / 2
            if line_y is None or abs(ymid - line_y) <= y_tol:
                line.append(s)
                line_y = ymid if line_y is None else line_y
            else:
                out.append(_merge(line))
                line = [s]
                line_y = ymid
        if line:
            out.append(_merge(line))
    return out


def _merge(line: list[Span]) -> Span:
    # x-order
    ordered = sorted(line, key=lambda s: s.bbox[0])
    xs = [s.bbox[0] for s in ordered] + [s.bbox[2] for s in ordered]
    ys = [s.bbox[1] for s in ordered] + [s.bbox[3] for s in ordered]
    bbox = (min(xs), min(ys), max(xs), max(ys))
    text = " ".join(s.text for s in ordered)
    return Span(doc_id=ordered[0].doc_id, page=ordered[0].page, bbox=bbox, text=text)
