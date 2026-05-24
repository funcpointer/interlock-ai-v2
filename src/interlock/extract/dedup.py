"""v2.8.1 — cross-lane same-doc record dedup.

Track 1 regex, Track 2 LLM-text, and Sprint 8 vision lane can all extract
the same physical parameter from the same document. Without dedup they
generate parallel pairs at alignment time, surfacing the same anomaly
multiple times in the UI (one ``%Z``-name flag, one ``Transformer Impedance``
flag — both about the same value).

Strategy: within each document, collapse records that describe the same
``(canonical_name, normalized_magnitude ± epsilon, page-window)``. When a
collision is found, keep ONE record by lane priority:

    vision > llm_text > regex

Rationale for priority:
- ``vision`` returns (entity, value) tuples extracted from the page image,
  so the entity binding is reliable on diagram pages.
- ``llm_text`` understands prose / table layouts the regex doesn't and
  often carries a cleaner entity_tag from the LLM's full-page reading.
- ``regex`` is deterministic but blind to context; useful as the floor.

Out of scope: cross-document dedup, fuzzy-name matching (handled by the
semantic aligner downstream), or unit conversion (records here are
already Pint-normalized).
"""

from __future__ import annotations

import logging
import math
import re
from collections.abc import Iterable

from interlock.extract.parameters import ParameterRecord

logger = logging.getLogger(__name__)

# Lane priority: smaller = higher priority (kept on collision).
_LANE_PRIORITY: dict[str, int] = {
    "vision": 0,
    "llm_text": 1,
    "regex": 2,
}

# v2.8.6 — row-marker regex override: when a regex record carries a
# digit-only entity_tag (e.g. "1", "32"), its positional anchor is
# usually MORE reliable for cross-doc pairing than the value-encoding
# entity_tag emitted by LLM/vision (e.g. "1000KVA XFMR", which changes
# when the value mutates). For records colliding within a doc, promote
# the row-marker regex record over its descriptor-tagged peers.
_ROW_MARKER_RE = re.compile(r"^\d+$")


def _is_row_marker_tag(tag: str) -> bool:
    return bool(_ROW_MARKER_RE.match((tag or "").strip()))

# How far apart (in pages) two records can be and still count as the
# "same" value within ONE doc. v2.8.8 — tightened from 2 to 0 (same
# page only). The previous ±2 window was conflating physically
# different equipment that happens to share a value across pages — e.g.
# doc_a Transformer Rating '1000 kVA' appears on TCC1 p3, TCC2 p5, and
# TCC3 p7 with row-marker tags '1', '1', '1' — three DIFFERENT
# transformer slots referenced in three different coordination
# studies, sharing only the kVA rating. With window=2 the regex p7
# 1000kVA record got cross-lane-deduped against the vision p6 1000kVA
# record (page distance 1), blocking TP-3 from surfacing.
#
# Within-doc dedup is now strictly same-page. Cross-document
# "value-shifted-by-page-in-revision" is handled separately by
# alignment, not by dedup.
_PAGE_WINDOW = 0

# Magnitude equality tolerance (relative). 0.1% covers Pint precision +
# typical PDF text-extraction noise without merging distinct values.
_MAGNITUDE_RTOL = 1e-3


def dedup_same_doc_records(
    records: list[ParameterRecord],
) -> list[ParameterRecord]:
    """Collapse cross-lane duplicates within each document.

    Cross-document records are NEVER merged — the aligner handles that
    with its own machinery. Returns a NEW list; input is not mutated.
    """
    by_doc: dict[str, list[ParameterRecord]] = {}
    for r in records:
        by_doc.setdefault(r.doc_id, []).append(r)

    out: list[ParameterRecord] = []
    total_dropped = 0
    for doc_id, recs in by_doc.items():
        kept, dropped = _dedup_one_doc(recs)
        out.extend(kept)
        total_dropped += dropped
        if dropped:
            logger.info(
                "dedup %s: %d in -> %d out (dropped %d cross-lane duplicates)",
                doc_id, len(recs), len(kept), dropped,
            )
    if total_dropped == 0:
        logger.info("dedup: no cross-lane duplicates across %d records", len(records))
    return out


def _effective_priority(rec: ParameterRecord) -> int:
    """Lane priority with v2.8.6 row-marker promotion.

    Regex records carrying a digit-only entity_tag (table row markers)
    score better than their nominal lane rank because the row marker
    is a stronger positional anchor than the value-encoding tags LLM /
    vision emit. Brings same-row records across docs together when
    descriptor tags differ due to the very mutation we want to detect.
    """
    base = _LANE_PRIORITY.get(rec.extraction_lane, 99)
    if rec.extraction_lane == "regex" and _is_row_marker_tag(rec.entity_tag):
        # Slot regex-with-row-marker BETWEEN vision (0) and llm_text (1).
        # Vision still wins on diagram pages (its (entity, value) tuples
        # are strongest there); row-marker regex beats LLM-text descriptor
        # tags everywhere else.
        return 1  # tie with llm_text; alphabetical fallback in stable sort
    return base


def _dedup_one_doc(
    records: list[ParameterRecord],
) -> tuple[list[ParameterRecord], int]:
    """Per-document dedup pass. Returns (kept, dropped_count)."""
    # Sort by effective priority so the highest-priority record is
    # processed first for each (name, magnitude) cluster.
    indexed = sorted(
        enumerate(records),
        key=lambda pair: _effective_priority(pair[1]),
    )
    kept_keys: list[tuple[ParameterRecord, list[int]]] = []
    drop_idx: set[int] = set()

    for idx, rec in indexed:
        merged = False
        for kept_rec, kept_pages in kept_keys:
            if _is_duplicate(rec, kept_rec, kept_pages):
                # Lower-priority duplicate of an already-kept record.
                drop_idx.add(idx)
                kept_pages.append(rec.page)
                merged = True
                break
        if not merged:
            kept_keys.append((rec, [rec.page]))

    kept = [r for i, r in enumerate(records) if i not in drop_idx]
    return kept, len(drop_idx)


def _is_duplicate(
    candidate: ParameterRecord,
    kept: ParameterRecord,
    kept_pages: Iterable[int],
) -> bool:
    """v2.8.1 — Dedup intentionally restricted to CROSS-LANE collisions.

    Same-lane same-name records are legitimate multiple readings of the
    parameter at different physical locations in the document (e.g. the
    Track 1 regex matches ``1000KVA XFMR`` once per TCC plot referencing
    it). Merging those would silently shrink the record set the aligner
    sees and break same-page pairing on later pages.

    Cross-lane records, by contrast, are the same physical parameter
    re-extracted by a different pipeline lane (regex / llm_text / vision)
    — that's the duplication this dedup exists to collapse.
    """
    if candidate.extraction_lane == kept.extraction_lane:
        return False
    if candidate.name != kept.name:
        return False
    if not any(
        abs(candidate.page - p) <= _PAGE_WINDOW for p in kept_pages
    ):
        return False
    return _magnitudes_match(candidate, kept)


_NUMERIC_TOKEN = re.compile(r"\d[\d,]*\.?\d*")
_NON_ALNUM = re.compile(r"[^a-z0-9.%]+")


def _normalize_raw_value(raw: str) -> str:
    """Collapse formatting noise: lowercase, drop all whitespace + most
    punctuation. So '100 kVA' and '100KVA' compare equal even when one
    side's Pint normalization failed."""
    if not raw:
        return ""
    s = raw.strip().lower().replace(",", "")
    return _NON_ALNUM.sub("", s)


def _extract_magnitude_from_raw(raw: str) -> float | None:
    """Best-effort numeric extraction when normalized_magnitude is None.
    Returns the FIRST number found in raw_value. Used as a fallback
    bridge across lanes when one side parsed via Pint and the other
    didn't (e.g. '100KVA' fails Pint but '100 kVA' succeeds)."""
    m = _NUMERIC_TOKEN.search(raw or "")
    if not m:
        return None
    try:
        return float(m.group(0).replace(",", ""))
    except ValueError:
        return None


def _magnitudes_match(a: ParameterRecord, b: ParameterRecord) -> bool:
    """Return True when two records describe the same value.

    Numeric path: both have ``normalized_magnitude`` set → compare with
    relative tolerance ``_MAGNITUDE_RTOL``. Same unit required when both
    set.

    String path: at least one record lacks numeric normalization (common
    when LLM emits ``100KVA`` without a separator and Pint refuses to
    parse it). v2.8.4 — try harder before giving up: (a) compare
    whitespace/punctuation-stripped raw_values; (b) extract the first
    numeric token from each side and compare with the same relative
    tolerance. Returns True if either passes.
    """
    am = a.normalized_magnitude
    bm = b.normalized_magnitude
    if am is not None and bm is not None:
        if a.normalized_unit and b.normalized_unit and a.normalized_unit != b.normalized_unit:
            return False
        if am == 0 and bm == 0:
            return True
        return math.isclose(am, bm, rel_tol=_MAGNITUDE_RTOL, abs_tol=0.0)
    # String path — normalize whitespace + punctuation first.
    av = _normalize_raw_value(a.raw_value)
    bv = _normalize_raw_value(b.raw_value)
    if av and av == bv:
        return True
    # Numeric fallback: best-effort scrape of leading number from each
    # raw_value. Catches '100KVA' vs '100 kVA' when only one side's
    # Pint parse succeeded.
    fa = am if am is not None else _extract_magnitude_from_raw(a.raw_value)
    fb = bm if bm is not None else _extract_magnitude_from_raw(b.raw_value)
    if fa is not None and fb is not None:
        if fa == 0 and fb == 0:
            return True
        return math.isclose(fa, fb, rel_tol=_MAGNITUDE_RTOL, abs_tol=0.0)
    return False
