"""Sprint 8 — page-structure heuristic classifier.

For each page: compute char count, line stats, image area ratio.
Map to PageStructure label. Diskcached per (PDF content hash, page).
"""

from __future__ import annotations

from pathlib import Path

import fitz

from interlock.cache import disk as disk_cache
from interlock.llm_pipeline.schemas.page_structure import PageStructure

_NAMESPACE = "page-structure"


def classify_page_structure(pdf_path: str, page: int) -> PageStructure:
    """Heuristic classifier. Cached per (PDF path + size + mtime + page).

    Returns 'mixed' on any failure (missing file, bad page index, render error).
    """
    p = Path(pdf_path)
    if not p.exists():
        return "mixed"
    try:
        stat = p.stat()
        key_payload = {
            "path": str(p.resolve()),
            "size": stat.st_size,
            "mtime": int(stat.st_mtime),
            "page": page,
        }
    except Exception:
        return "mixed"

    def _compute() -> PageStructure:
        return _classify_uncached(pdf_path, page)

    label, _hit = disk_cache.get_or_compute(_NAMESPACE, key_payload, _compute)
    return label


def _classify_uncached(pdf_path: str, page: int) -> PageStructure:
    stats = _compute_layout_stats(pdf_path, page)
    if stats is None:
        return "mixed"
    # Diagram signal fires before sparse-text floor so callout pages with
    # few total chars still route to vision.
    if stats["short_line_ratio"] > 0.6 and stats["avg_line_len"] < 25:
        return "diagram"
    if stats["n_chars"] < 200:
        # Sparse text without diagram-callout signal — likely image-heavy
        # scan. Route to current path (Camelot + regex), which already
        # handles low-text fallback.
        return "mixed"
    if stats["short_line_ratio"] < 0.3 and stats["avg_line_len"] > 40:
        return "prose"
    if stats["image_area_ratio"] > 0.3:
        # Image-heavy with text → treat as diagram for the vision lane.
        return "diagram"
    return "mixed"


def _compute_layout_stats(pdf_path: str, page: int) -> dict[str, float] | None:
    """Return layout statistics for one page; None on failure."""
    try:
        doc = fitz.open(pdf_path)
    except Exception:
        return None
    try:
        if page < 1 or page > doc.page_count:
            return None
        pg = doc[page - 1]
        text = pg.get_text("text") or ""
        n_chars = len(text)
        lines = [ln for ln in text.splitlines() if ln.strip()]
        n_lines = len(lines)
        avg_line_len = sum(len(ln) for ln in lines) / n_lines if n_lines else 0.0
        n_short = sum(1 for ln in lines if len(ln.strip()) < 20)
        short_ratio = n_short / n_lines if n_lines else 0.0
        page_area = pg.rect.width * pg.rect.height
        image_area = 0.0
        for b in pg.get_text("dict").get("blocks", []):
            if b.get("type") == 1:
                r = fitz.Rect(b.get("bbox", (0, 0, 0, 0)))
                image_area += r.width * r.height
        image_ratio = image_area / page_area if page_area else 0.0
        return {
            "n_chars": float(n_chars),
            "n_lines": float(n_lines),
            "avg_line_len": avg_line_len,
            "short_line_ratio": short_ratio,
            "image_area_ratio": image_ratio,
        }
    finally:
        doc.close()
