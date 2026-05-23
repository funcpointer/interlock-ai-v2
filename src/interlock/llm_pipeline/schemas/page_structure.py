"""Sprint 8 — page-structure Literal used by the per-page routing matrix.

prose:    multi-line paragraphs (short_line_ratio < 0.3, avg_line_len > 40)
table:    Camelot-detectable grid OR (image_area > 0.3 AND not diagram)
diagram:  diagram-callouts layout (short_line_ratio > 0.6, avg_line_len < 25)
mixed:    none of the above; default fallback
"""

from __future__ import annotations

from typing import Literal

PageStructure = Literal["prose", "table", "diagram", "mixed"]
