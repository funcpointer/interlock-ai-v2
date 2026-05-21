"""Table extraction via Camelot with lattice primary, stream fallback.

Camelot may produce zero tables if a PDF lays out text in columns visually without
real table structure (common in promotional engineering PDFs). The function
returns an empty list rather than raising in that case.

Image-only PDFs (scans) are detected up front via PyMuPDF text-density and
skipped — Camelot warns 'page-N is image-based' on every page otherwise,
flooding the log without producing any tables. Vision OCR (in
``ingest/vision_fallback.py``) is the appropriate path for those docs.
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass

import camelot
import fitz


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


_IMAGE_ONLY_TEXT_THRESHOLD = 80


def _is_image_only(pdf_path: str, max_pages: int | None) -> bool:
    """True if every (capped) page yields < 80 native characters.

    Camelot has no value on such PDFs and emits a 'page-N is image-based'
    warning per page; we short-circuit before invoking it.
    """
    doc = fitz.open(pdf_path)
    try:
        n = len(doc)
        upper = min(n, max_pages) if max_pages and max_pages > 0 else n
        for i in range(upper):
            text = doc[i].get_text("text").strip()
            if len(text) >= _IMAGE_ONLY_TEXT_THRESHOLD:
                return False
        return True
    finally:
        doc.close()


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

    Image-only PDFs short-circuit to an empty list — Camelot can't parse
    them and only emits warnings. Vision OCR handles those pages instead.
    """
    did = doc_id or pdf_path
    if _is_image_only(pdf_path, max_pages):
        return []
    page_spec = pages if pages is not None else _page_spec(pdf_path, max_pages)
    out: list[Table] = []
    for flavor in ("lattice", "stream"):
        try:
            with warnings.catch_warnings():
                # 'page-N is image-based, camelot only works on text-based pages.'
                # We've already short-circuited fully image-only PDFs above; this
                # filter just silences the noise on mixed PDFs where some pages
                # happen to be scanned.
                warnings.filterwarnings(
                    "ignore",
                    message=r"page-\d+ is image-based.*",
                    category=UserWarning,
                )
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
