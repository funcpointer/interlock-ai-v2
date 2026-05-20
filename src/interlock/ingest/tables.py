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


def extract_tables(pdf_path: str, pages: str = "all", doc_id: str | None = None) -> list[Table]:
    did = doc_id or pdf_path
    out: list[Table] = []
    for flavor in ("lattice", "stream"):
        try:
            ts = camelot.read_pdf(pdf_path, pages=pages, flavor=flavor)  # type: ignore[attr-defined]
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
