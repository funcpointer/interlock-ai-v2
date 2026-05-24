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
from typing import Literal, NamedTuple

from interlock.extract.units import normalize_quantity
from interlock.ingest.text import Span

# v2.8.1 — canonical parameter-name aliases. Track 1 regex emits short
# names ("%Z", "IFLA"); Track 2 LLM-text emits prose names ("Transformer
# Impedance", "Full Load Amperes"); vision lane emits its own. Alias map
# collapses synonyms so cross-lane dedup + alignment treat them as one
# canonical parameter. Keys lowercased + stripped; right side is the
# canonical display form.
_PARAM_NAME_ALIASES: dict[str, str] = {
    # Impedance percent
    "%z": "Transformer Impedance",
    "z%": "Transformer Impedance",
    "impedance": "Transformer Impedance",
    "impedance %": "Transformer Impedance",
    "transformer impedance": "Transformer Impedance",
    "transformer impedance %": "Transformer Impedance",
    # Full-load amperes
    "ifla": "Full Load Amperes",
    "fla": "Full Load Amperes",
    "full load amperes": "Full Load Amperes",
    "full-load amperes": "Full Load Amperes",
    "full load current": "Full Load Amperes",
    # Fault current
    "fault current": "Fault Current",
    "short-circuit current": "Fault Current",
    "short circuit current": "Fault Current",
    # Transformer rating
    "transformer rating": "Transformer Rating",
    "kva rating": "Transformer Rating",
    "rated power": "Transformer Rating",
    # System voltage
    "system voltage": "System Voltage",
    "voltage": "System Voltage",
    "nominal voltage": "System Voltage",
    "rated voltage": "System Voltage",
    # Fuse designation (already exact match across lanes most of the time)
    "fuse designation": "Fuse Designation",
    "fuse part number": "Fuse Designation",
}


def canonicalize_param_name(name: str) -> str:
    """Map a raw parameter name to its canonical form. Pass-through when
    no alias exists so unknown names survive unchanged."""
    key = (name or "").strip().lower()
    return _PARAM_NAME_ALIASES.get(key, name)


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
    # Path to the source PDF on disk. Carried alongside doc_id so the
    # citation renderer can always open the file. Defaults to empty for
    # back-compat (renderer falls back to doc_id).
    source_path: str = ""
    # Leading Device ID / row marker scraped from the start of the source
    # line (e.g. "⑥" in "⑥ | KRP-C-1600SP | Class L"). When present this
    # ties the record to a specific table row / device, giving alignment
    # a real identity to pair on instead of guessing by position. Empty
    # string when no marker was detected. Normalised to ASCII (circled
    # digits → "1".."20"; uppercase otherwise) so "⑥" in Doc A matches
    # "6." in Doc B.
    entity_tag: str = ""
    # v2 Sprint 2: which track emitted this record. Default "regex"
    # preserves bit-identity for every existing caller; the LLM extractor
    # (Track 2) sets it to "llm" at downcast time. Adjudicator (Sprint 3)
    # uses this for per-flag provenance UX.
    provenance: Literal["regex", "llm"] = "regex"
    # v2 Sprint 8 — extraction lane provenance for routing audit.
    # 'regex' = Track 1 deterministic regex extraction.
    # 'llm_text' = Track 2 LLM text extraction (Sprint 2).
    # 'vision' = Sprint 8 vision extraction (diagram pages).
    extraction_lane: Literal["regex", "llm_text", "vision"] = "regex"


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


# Leading Device ID / row-marker detector. Matches the FIRST token on a
# line when it looks like a table-row identifier:
#   - Circled digits ① - ⑳ (U+2460-U+2473) and ㉑ - ㉟ (U+3251-U+325F)
#   - Numbered list / row prefix: "1", "1.", "1)", "21", "21."
#   - Equipment-style code: "A1", "F2", "T-200" (uppercase letter then
#     1-3 digits, optional hyphen)
# The regex requires the marker to be followed by whitespace then a
# recognised engineering token start, so prose like "1. TCC1 includes…"
# (where the digit is part of a sentence) is *not* captured as an entity.
_LEADING_DEVICE_ID = re.compile(
    r"^[\s|]*"
    r"("
        r"[①-⑳]"               # ① - ⑳
        r"|[㉑-㉟]"              # ㉑ - ㉟
        r"|\d{1,3}[.)]?"                 # 1, 1., 1), 21, 21.
        r"|[A-Z][\-]?\d{1,3}"            # A1, F2, T-200
    r")"
    r"\s+"
)

# Map circled digit → ASCII so "⑥" in Doc A matches "6" in Doc B.
_CIRCLED_DIGIT_MAP: dict[str, str] = {
    chr(0x2460 + i): str(i + 1) for i in range(20)  # ① - ⑳
}
_CIRCLED_DIGIT_MAP.update({chr(0x3251 + i): str(21 + i) for i in range(15)})  # ㉑ - ㉟


def _normalize_entity_tag(raw_tag: str) -> str:
    """Canonical form of a Device ID so cross-doc matches survive
    glyph variations: ``⑥``, ``6``, ``6.``, ``6)`` all collapse to ``6``."""
    t = raw_tag.strip().rstrip(".)").upper()
    return _CIRCLED_DIGIT_MAP.get(t, t)


def _detect_entity_tag(span_text: str) -> str:
    """Return the normalised Device ID at the start of ``span_text``, or
    empty string if no row marker is present. Operates on per-line spans
    (native PyMuPDF line aggregation or per-line OCR splits)."""
    m = _LEADING_DEVICE_ID.match(span_text)
    if not m:
        return ""
    return _normalize_entity_tag(m.group(1))


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
        # Detect the row's Device ID once per span; every parameter
        # extracted from this line inherits it. Empty string when the
        # line doesn't start with a recognised marker.
        entity_tag = _detect_entity_tag(span.text)
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
                        name=canonicalize_param_name(pat.name),  # v2.8.1
                        raw_value=raw_value,
                        normalized_magnitude=mag,
                        normalized_unit=unit,
                        source_path=span.source_path,
                        entity_tag=entity_tag,
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
                    name=canonicalize_param_name(name),  # v2.8.1
                    raw_value=raw_value,
                    normalized_magnitude=mag,
                    normalized_unit=unit,
                    source_path=span.source_path,
                    entity_tag=entity_tag,
                )
            )
    return out
