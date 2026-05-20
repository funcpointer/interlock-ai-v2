"""Domain-specific parameter extraction.

Engineering PDFs rarely format parameters as plain ``Name: value`` lines.
Instead values appear with adjacent unit markers and contextual nouns
("5.75%Z, liquid", "1000KVA XFMR", "Fault X1 20,000A RMS Sym").

We use an explicit pattern set per known parameter family. Each pattern yields
a ParameterRecord with citation tuple, canonical name, raw value, and
Pint-normalized magnitude/unit.

The pattern set is small by design. New patterns are added per fixture family.
Generic NLP-style extraction is platform-path.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import NamedTuple

from interlock.extract.units import normalize_quantity
from interlock.ingest.text import Span


@dataclass(frozen=True)
class ParameterRecord:
    doc_id: str
    page: int
    bbox: tuple[float, float, float, float]
    section: str | None
    span_text: str
    name: str
    raw_value: str
    normalized_magnitude: float | None
    normalized_unit: str | None


class _Pattern(NamedTuple):
    regex: re.Pattern[str]
    name: str
    unit_for_quantity: str | None  # None means raw_value is a string token (e.g., part number)


_PATTERNS: list[_Pattern] = [
    # Impedance percent: "5.75%Z" or "5.75 %Z"
    _Pattern(re.compile(r"(\d[\d,]*\.?\d*)\s*%\s*Z\b"), "%Z", "%"),
    # Fault current with RMS Sym context: "Fault X1 20,000A RMS Sym"
    _Pattern(
        re.compile(r"Fault\s+\S+\s+(\d[\d,]*\.?\d*)\s*A\s+RMS\s+Sym", re.IGNORECASE),
        "Fault Current",
        "A",
    ),
    # XFMR rating in kVA or KVA: "1000KVA XFMR", "150 KVA XFMR"
    _Pattern(
        re.compile(r"(\d[\d,]*\.?\d*)\s*K?VA\s+XFMR", re.IGNORECASE),
        "Transformer Rating",
        "kVA",
    ),
    # XFMR rating in MVA: "0.15 MVA XFMR"
    _Pattern(
        re.compile(r"(\d[\d,]*\.?\d*)\s*MVA\s+XFMR", re.IGNORECASE),
        "Transformer Rating",
        "MVA",
    ),
    # IFLA = NN A
    _Pattern(re.compile(r"IFLA\s*=\s*(\d[\d,]*\.?\d*)\s*A\b"), "IFLA", "A"),
    # System voltage standalone — Eaton shape "13.8KV" appearing alone on a span.
    # Anchored to span start to avoid catching values inside ``Label: NN kV``
    # pairs (those go through the generic pattern instead).
    _Pattern(
        re.compile(r"^(\d[\d,]*\.?\d*)\s*(?:kV|KV)\b(?!A)"),
        "System Voltage",
        "kV",
    ),
    # Fuse designations (string-valued)
    _Pattern(re.compile(r"\b(LPN-RK-\d+SP)\b"), "Fuse Designation", None),
    _Pattern(re.compile(r"\b(LPS-RK-\d+SP)\b"), "Fuse Designation", None),
    _Pattern(re.compile(r"\b(KRP-C-\d+SP)\b"), "Fuse Designation", None),
]


# Generic "Label: number unit" pattern for data-sheet / spec layouts where
# parameters appear as ``Rated Power: 1100 kVA`` lines. Constrained to a
# recognized engineering unit suffix so it does not over-fire on prose like
# ``Notes: 1. TCC1 includes...``.
_GENERIC_KV = re.compile(
    r"^(?P<name>[A-Z][A-Za-z][A-Za-z ]{0,40}?)\s*:\s*"
    r"(?P<num>\d[\d,]*\.?\d*)\s*"
    r"(?P<unit>kVA|MVA|kV|MV|kA|VA|kHz|MHz|Hz|°C|°F|Ω|μF|%|V|A)"
    r"(?:\s|$|[^A-Za-z0-9])"
)


def extract_parameters(
    spans: list[Span],
    section_by_span: dict[int, str | None] | None = None,
) -> list[ParameterRecord]:
    """Return parameter records found across ``spans``.

    ``section_by_span`` maps id(span) -> section heading (from sections module).
    Optional — when omitted, section is None on every record.
    """
    out: list[ParameterRecord] = []
    section_by_span = section_by_span or {}
    for span in spans:
        # 1) Domain-specific patterns (Eaton-tuned).
        for pat in _PATTERNS:
            for m in pat.regex.finditer(span.text):
                token = m.group(1)
                if pat.unit_for_quantity is None:
                    raw_value = token
                    mag, unit = None, None
                else:
                    raw_value = f"{token} {pat.unit_for_quantity}"
                    try:
                        q = normalize_quantity(raw_value)
                        mag = float(q.magnitude)
                        unit = str(q.units)
                    except Exception:
                        mag, unit = None, None
                out.append(
                    ParameterRecord(
                        doc_id=span.doc_id,
                        page=span.page,
                        bbox=span.bbox,
                        section=section_by_span.get(id(span)),
                        span_text=span.text,
                        name=pat.name,
                        raw_value=raw_value,
                        normalized_magnitude=mag,
                        normalized_unit=unit,
                    )
                )
        # 2) Generic ``Label: number unit`` (spec / data-sheet shape).
        gm = _GENERIC_KV.match(span.text.strip())
        if gm:
            name = gm.group("name").strip()
            raw_value = f"{gm.group('num')} {gm.group('unit')}"
            try:
                q = normalize_quantity(raw_value)
                mag = float(q.magnitude)
                unit = str(q.units)
            except Exception:
                mag, unit = None, None
            out.append(
                ParameterRecord(
                    doc_id=span.doc_id,
                    page=span.page,
                    bbox=span.bbox,
                    section=section_by_span.get(id(span)),
                    span_text=span.text,
                    name=name,
                    raw_value=raw_value,
                    normalized_magnitude=mag,
                    normalized_unit=unit,
                )
            )
    return out
