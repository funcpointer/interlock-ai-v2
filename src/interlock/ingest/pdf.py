"""Top-level ingestion orchestrator.

Runs PyMuPDF span extraction + Camelot table extraction. Flags pages with
near-zero text density so a vision fallback can be routed at the pipeline level.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import fitz

from .tables import Table, extract_tables
from .text import Span, aggregate_line_spans, extract_spans

MIN_CHARS_PER_PAGE = 80


@dataclass(frozen=True)
class IngestResult:
    doc_id: str
    spans: list[Span]
    tables: list[Table]
    low_coverage_pages: list[int] = field(default_factory=list)


def ingest(
    pdf_path: str,
    doc_id: str | None = None,
    *,
    table_max_pages: int | None = None,
) -> IngestResult:
    """Run PyMuPDF span + Camelot table extraction.

    ``table_max_pages`` caps the Camelot page span; ``None`` defers to the
    default in ``extract_tables`` (currently 20). Pass an int to override
    or 0 to scan every page (long PDFs will be slow).
    """
    did = doc_id or pdf_path
    raw_spans = extract_spans(pdf_path, did)
    merged_spans = aggregate_line_spans(raw_spans)
    if table_max_pages is None:
        tables = extract_tables(pdf_path, doc_id=did)
    else:
        tables = extract_tables(pdf_path, doc_id=did, max_pages=table_max_pages or None)

    low_cov: list[int] = []
    doc = fitz.open(pdf_path)
    try:
        for i, page in enumerate(doc, start=1):
            text = page.get_text("text").strip()
            if len(text) < MIN_CHARS_PER_PAGE:
                low_cov.append(i)
    finally:
        doc.close()

    return IngestResult(doc_id=did, spans=merged_spans, tables=tables, low_coverage_pages=low_cov)
