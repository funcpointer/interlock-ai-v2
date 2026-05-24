"""Sprint 9 / v2.9 — context extraction (Phase 33.2).

Per spec §2.2 (module split as enforcement): context lives here, not
inside the inventory builder, not in alignment, not in detect. If a
function derives "what context does this mention live in?" anywhere
else in the codebase, it's a bug.

Phase 33.2 scope (deliberately narrow):
- Define :class:`ExtractedContext` shape.
- Extract contexts from already-tagged records (Phase 33.0a/33.1
  synthetic input shape carries ``context_id`` explicitly).
- Canonicalize context titles via deterministic rules + small alias
  map (no LLM).
- Cross-doc structural-fingerprint alignment for the
  ``moved-table-page`` and ``title-renamed`` shapes (Attacks 4 + 11).

Out of scope (later phases):
- Real PyMuPDF span analysis (Phase 33.5 wires this against ingest).
- LLM context-title classifier (spec §3.5 — opt-in tie-breaker).
- Per-project alias overrides (spec §11 deferred Q3 / Phase 33.6 UI).
- Clustering equipment by context (Phase 33.3 inventory builder).
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from interlock.model.equipment import ContextKind

# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ExtractedContext:
    """One named context within a document — table, diagram, schedule,
    or prose section.

    ``canonical_id`` is the stable cross-doc handle; ``raw_title`` is
    the literal text the doc used. Two contexts with the same
    structural fingerprint but different titles share ``canonical_id``
    after :func:`align_contexts_across_docs` runs.
    """

    doc_id: str
    raw_title: str
    canonical_id: str
    kind: ContextKind
    column_headers: tuple[str, ...] = field(default_factory=tuple)
    row_count: int = 0
    page_set: frozenset[int] = field(default_factory=frozenset)


# ---------------------------------------------------------------------------
# Title canonicalization
# ---------------------------------------------------------------------------

# Explicit alias map for known title variants. Reviewer can extend
# via per-project overrides in Phase 33.6 UI. Keys are slugged
# (lowercase, non-alnum stripped) so spelling/spacing variants
# collapse to the same key before lookup.
_TITLE_ALIASES: dict[str, str] = {
    # TCC family — coordination-study coordination-curve tables/plots
    "tcc1": "tcc1",
    "tcc2": "tcc2",
    "tcc3": "tcc3",
    "coordinationcurve1": "tcc1",
    "coordinationcurve2": "tcc2",
    "coordinationcurve3": "tcc3",
    "coordinationplot1": "tcc1",
    "coordinationplot2": "tcc2",
    "coordinationplot3": "tcc3",
    "timecurrentcurve1": "tcc1",
    "timecurrentcurve2": "tcc2",
    "timecurrentcurve3": "tcc3",
    "timecurrentcurve1tcc1": "tcc1",
    "timecurrentcurve2tcc2": "tcc2",
    "timecurrentcurve3tcc3": "tcc3",
    "transformerinrush1": "tcc1",
    "transformerinrush2": "tcc2",
    "transformerinrush3": "tcc3",
    # One-line / single-line diagram family
    "oneline": "one_line",
    "one_line": "one_line",
    "singleline": "one_line",
    "single_line": "one_line",
    "onelinediagram": "one_line",
    # Schedule
    "schedule": "schedule",
    "transformerschedule": "transformer_schedule",
    "fuseschedule": "fuse_schedule",
}

# Pattern-based fallback for TCC-like names with explicit "N" suffix
# that aren't in the alias map verbatim. Captures "Coordination Curve 3"
# → "tcc3" via the integer suffix.
_TCC_PATTERN = re.compile(
    r"^(?:tcc|coordinationcurve|coordinationplot|timecurrentcurve"
    r"|transformerinrush)\s*(\d+)$",
)

_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def canonicalize_context_title(raw: str) -> str:
    """Normalize a context title to its stable cross-doc handle.

    Rules, in priority order:

    1. Empty/whitespace → empty string (caller treats as "no context").
    2. Slugged input matches the explicit alias map → mapped value.
    3. Slugged input matches the TCC pattern (``tccN`` /
       ``coordinationcurveN``/etc) → ``tccN``.
    4. Fallback → the slugged input itself (stable but uninterpreted).
    """
    if not raw:
        return ""
    slug = _NON_ALNUM.sub("", raw.strip().lower())
    if not slug:
        return ""
    if slug in _TITLE_ALIASES:
        return _TITLE_ALIASES[slug]
    m = _TCC_PATTERN.match(slug)
    if m:
        return f"tcc{m.group(1)}"
    return slug


# ---------------------------------------------------------------------------
# Per-doc context extraction
# ---------------------------------------------------------------------------


def extract_contexts(
    records: Iterable[dict[str, Any]],
    doc_id: str,
) -> list[ExtractedContext]:
    """Group records by raw context title; produce one
    :class:`ExtractedContext` per distinct context within ``doc_id``.

    Phase 33.2 consumes the dict-shaped synthetic records the Phase
    33.0a gold ships (records carry ``context_id``, ``row_id``,
    ``page`` directly). Phase 33.5 will wire this against real
    :class:`ParameterRecord` + :class:`Span` ingestion.

    ``raw_title`` is the input ``context_id`` value verbatim (so
    "TCC3" stays "TCC3" before canonicalization). ``canonical_id`` is
    computed via :func:`canonicalize_context_title`. ``column_headers``
    are not yet derivable from Phase 33.0a inputs; Phase 33.5 wires
    table-header detection from Camelot output.

    Records without a ``context_id`` are dropped (they live in
    document-wide / non-equipment-bound space and don't anchor any
    context).
    """
    by_title: dict[str, list[dict[str, Any]]] = {}
    for rec in records:
        title = rec.get("context_id")
        if not title:
            continue
        by_title.setdefault(str(title), []).append(rec)

    out: list[ExtractedContext] = []
    for raw_title, group in by_title.items():
        canonical = canonicalize_context_title(raw_title)
        rows = {rec.get("row_id") for rec in group if rec.get("row_id")}
        pages = {int(rec.get("page", 0)) for rec in group if rec.get("page")}
        # ``kind`` heuristic from raw title; Phase 33.5 will refine via
        # PageStructure classifier.
        kind = _infer_kind(raw_title)
        out.append(
            ExtractedContext(
                doc_id=doc_id,
                raw_title=raw_title,
                canonical_id=canonical or raw_title.lower(),
                kind=kind,
                column_headers=(),
                row_count=len(rows),
                page_set=frozenset(pages),
            )
        )
    # Sort for deterministic test output.
    return sorted(out, key=lambda c: (c.canonical_id, c.raw_title))


def _infer_kind(raw_title: str) -> ContextKind:
    """Cheap deterministic kind inference from the title string. Phase
    33.5 will replace with a real classifier."""
    slug = _NON_ALNUM.sub("", raw_title.strip().lower())
    if "diagram" in slug or "oneline" in slug or "singleline" in slug:
        return "diagram_label"
    if "schedule" in slug:
        return "schedule"
    if "tcc" in slug or "curve" in slug or "plot" in slug or "table" in slug:
        return "table_row"
    return "prose"


# ---------------------------------------------------------------------------
# Cross-doc structural-fingerprint alignment (Attack 4 + 11)
# ---------------------------------------------------------------------------


def align_contexts_across_docs(
    a_contexts: list[ExtractedContext],
    b_contexts: list[ExtractedContext],
) -> dict[tuple[str, str], str]:
    """Map ``(doc_id, raw_title) → canonical_id`` after cross-doc
    alignment.

    Two contexts cross-doc-align when EITHER:

    1. Their canonical_ids already match (same alias bucket).
    2. Their structural fingerprints match — column headers + row
       count agree exactly. Page numbers MUST NOT influence the
       match (spec §2.1 invariant #3: page is tie-breaker only).

    The returned map covers both docs; lookup keys are ``(doc_id,
    raw_title)`` so the caller can resolve any mention's context.

    Phase 33.2 limit: Attack 11 ("Coordination Curve 3" ↔ "TCC3")
    is handled by the canonical map in
    :func:`canonicalize_context_title`. Pure structural-fingerprint
    rescue (titles unrelated but column headers identical) requires
    column-header data Phase 33.5 will supply via Camelot. Until
    then, canonical-id agreement IS the alignment rule.
    """
    out: dict[tuple[str, str], str] = {}

    # Tier 1 — already-canonical agreement
    for ctx in a_contexts + b_contexts:
        out[(ctx.doc_id, ctx.raw_title)] = ctx.canonical_id

    # Tier 2 — structural fingerprint when canonical_ids differ
    # (Phase 33.5+ once Camelot wires column_headers + row_count
    # from real ingest data). Phase 33.2 placeholder: when both
    # contexts carry the same non-empty column_headers AND row_count,
    # promote the lower-doc canonical_id as shared.
    by_fingerprint: dict[tuple[tuple[str, ...], int], list[ExtractedContext]] = {}
    for ctx in a_contexts + b_contexts:
        fp = (ctx.column_headers, ctx.row_count)
        if not ctx.column_headers or ctx.row_count == 0:
            continue
        by_fingerprint.setdefault(fp, []).append(ctx)
    for ctxs in by_fingerprint.values():
        if len({c.canonical_id for c in ctxs}) <= 1:
            continue
        # Pick the lexicographically smallest canonical_id as the
        # shared handle; rewrite the others.
        shared = min(c.canonical_id for c in ctxs)
        for c in ctxs:
            out[(c.doc_id, c.raw_title)] = shared

    return out
