"""Attribute each span to the most recent preceding heading on the same page.

A 'heading' is detected by any of a small set of patterns suited to Eaton-style
engineering documents:
  - Numbered: "1. Title", "2.3 Sub-Title"
  - Lettered: "a. Sub-section"
  - Named TCC: "Time Current Curve #N (TCCx)"

The plan keeps this surface area small; configurability is platform-path.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from interlock.ingest.text import Span

_HEADING_PATTERNS = [
    re.compile(r"^\d+(\.\d+)*\.?\s+\S"),
    re.compile(r"^[a-z]\.\s+\S"),
    re.compile(r"^Time Current Curve\b"),
]


@dataclass(frozen=True)
class AttributedSpan:
    span: Span
    section: str | None

    @property
    def text(self) -> str:
        return self.span.text

    @property
    def page(self) -> int:
        return self.span.page


def _is_heading(text: str) -> bool:
    return any(p.match(text) for p in _HEADING_PATTERNS)


def attribute_sections(spans: list[Span]) -> list[AttributedSpan]:
    out: list[AttributedSpan] = []
    current_by_page: dict[int, str | None] = {}
    for s in sorted(spans, key=lambda s: (s.page, s.bbox[1])):
        if _is_heading(s.text):
            current_by_page[s.page] = s.text
            out.append(AttributedSpan(span=s, section=s.text))
        else:
            out.append(AttributedSpan(span=s, section=current_by_page.get(s.page)))
    return out
