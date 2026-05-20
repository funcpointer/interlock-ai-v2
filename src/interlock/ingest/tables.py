"""Table extraction via Camelot with lattice primary, stream fallback.

Camelot may produce zero tables if a PDF lays out text in columns visually without
real table structure (common in promotional engineering PDFs). The function
returns an empty list rather than raising in that case.
"""

from __future__ import annotations

from dataclasses import dataclass

import camelot


@dataclass(frozen=True)
class Cell:
    text: str
    bbox: tuple[float, float, float, float]


@dataclass(frozen=True)
class Table:
    doc_id: str
    page: int
    rows: list[list[Cell]]
    confidence: float


# Camelot scans every page in `pages="all"`, which on long PDFs (e.g. the IEEE
# 56-page guide) takes 90-120 s of wall-clock — enough to make Streamlit Cloud
# feel hung and to time out reviewer patience. We cap the page span by default
# and let callers override for cases where deep table extraction is needed.
DEFAULT_MAX_PAGES = 20


def _page_spec(pdf_path: str, max_pages: int | None) -> str:
    if max_pages is None or max_pages <= 0:
        return "all"
    import fitz  # local import to avoid top-level cost when not needed

    doc = fitz.open(pdf_path)
    try:
        n = len(doc)
    finally:
        doc.close()
    upper = min(n, max_pages)
    return f"1-{upper}" if upper >= 1 else "1"


def extract_tables(
    pdf_path: str,
    pages: str | None = None,
    doc_id: str | None = None,
    max_pages: int | None = DEFAULT_MAX_PAGES,
) -> list[Table]:
    """Extract tables via Camelot.

    Default caps at ``DEFAULT_MAX_PAGES`` (20) so Camelot doesn't scan the
    whole IEEE 56-page guide on every ingest. Pass an explicit ``pages``
    string (e.g. ``"1-3,7"``) or ``pages="all"``/``max_pages=None`` to
    override.
    """
    did = doc_id or pdf_path
    page_spec = pages if pages is not None else _page_spec(pdf_path, max_pages)
    out: list[Table] = []
    for flavor in ("lattice", "stream"):
        try:
            ts = camelot.read_pdf(pdf_path, pages=page_spec, flavor=flavor)  # type: ignore[attr-defined]
        except Exception:
            continue
        if len(ts) == 0:
            continue
        for t in ts:
            rows: list[list[Cell]] = []
            for row in t.cells:
                row_cells = [
                    Cell(text=str(c.text or "").strip(), bbox=(c.x1, c.y1, c.x2, c.y2))
                    for c in row
                ]
                rows.append(row_cells)
            accuracy = float(t.parsing_report.get("accuracy", 0.0)) / 100.0
            out.append(Table(doc_id=did, page=int(t.page), rows=rows, confidence=accuracy))
        if out:
            break
    return out
