"""Sprint 9 / v2.9 — equipment inventory builder (Phase 33.3).

Converts a stream of evidence (synthetic dict records in Phase 33.3;
real :class:`ParameterRecord` + :class:`Span` in Phase 33.5) into a
list of :class:`Equipment` per document. Spec §2.2 boundary:

- This module **clusters mentions into Equipment**.
- It does NOT match cross-doc — that's
  :mod:`interlock.align.equipment_match` (Phase 33.4).
- It does NOT classify mutations — that's
  :mod:`interlock.detect.equipment_mutations` (Phase 33.5).
- It does NOT call LLMs — Phase 33.3 is deterministic-only. LLM kind
  classification is a Phase 33.5+ extension when the rule-based
  inference proves insufficient.

Core rules (spec §2.1 + §3.4):

1. ``ParameterRecord`` (or its synthetic-dict cousin) is **evidence**.
   Each becomes one :class:`EquipmentMention`. Identity is computed
   from clustering across mentions, never from a single record.
2. ``canonical_id`` MUST NOT encode mutable parameter values
   (``validate_equipment`` enforces).
3. Same ``(context_id, row_id, kind)`` clusters deterministically as
   ``confident_cluster`` — unless the lanes within the row disagree
   on identity anchors (then ``lane_conflict``).
4. Same strong identity anchor across mentions (part number,
   equipment label) clusters deterministically.
5. Cross-context clustering only with strong anchor agreement.
   Otherwise — when same kind + same mutable value + no anchor
   disagreement — emit ``ambiguous_cluster``.
6. Anything else stays as a singleton ``confident_cluster``.
"""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Iterable
from typing import Any

from interlock.extract.context import (
    ExtractedContext,
    align_contexts_across_docs,
    extract_contexts,
)
from interlock.model.equipment import (
    ContextKind,
    Equipment,
    EquipmentKind,
    EquipmentMention,
    GroundingMode,
    SourceLane,
    validate_equipment,
)

# ---------------------------------------------------------------------------
# Identity-anchor recognition
# ---------------------------------------------------------------------------
#
# Anchors are stable handles whose disagreement BLOCKS clustering.
# Patterns recognised here MUST NOT match value-encoded labels like
# "1000KVA XFMR" (Invariant #2). The shared `_MUTABLE_VALUE_IN_ID_RE`
# from :mod:`model.equipment` gates that.

from interlock.model.equipment import _MUTABLE_VALUE_IN_ID_RE  # noqa: PLC2701

# Recognised identity-bearing label shapes. Order matters: more
# specific patterns first.
_ANCHOR_PATTERNS: list[re.Pattern[str]] = [
    # Bussmann fuse family (LPS-RK-200SP, LPN-RK-500SP, LPJ-, KRP-C-, etc).
    re.compile(r"\b(?:LPS|LPN|LPJ|KRP|FNQ|FRS|FRN)-[A-Z]+-\d+[A-Z]+\b"),
    # E-rated / current-limiting (JCN-80E, JJN-30, JJS-200).
    re.compile(r"\b(?:JCN|JJN|JJS|EC|KTK)\s*[\-]?\s*\d+[A-Z]*\b"),
    # Transformer / equipment slot labels (XFMR-1, T1, T-1, TX-2).
    re.compile(r"\b(?:XFMR|TX|T)\s*[\-]?\s*[A-Z]?\d+[A-Z]?\b"),
]


def _extract_identity_anchor(s: str) -> str | None:
    """Return the leading identity anchor from ``s`` if one is present
    AND ``s`` does not embed a mutable value token (per spec §2.1 #2).

    Returns the FIRST regex match (anchor pattern hit). Free-form
    strings without a recognised pattern → ``None`` (the caller treats
    them as weak descriptors).
    """
    if not s:
        return None
    stripped = s.strip()
    if _MUTABLE_VALUE_IN_ID_RE.search(stripped):
        return None  # value-encoded; never identity
    for pat in _ANCHOR_PATTERNS:
        m = pat.search(stripped)
        if m:
            return m.group(0).strip()
    return None


# ---------------------------------------------------------------------------
# Kind inference (rule-based; LLM classifier is a Phase 33.5+ option)
# ---------------------------------------------------------------------------

_KIND_KEYWORDS: list[tuple[EquipmentKind, tuple[str, ...]]] = [
    ("transformer", ("xfmr", "transformer", "kva ", "mva ")),
    ("fuse", ("fuse", "lps-rk", "lpn-rk", "krp-c", "jcn ", "lpj-", "jjn-", "frs-")),
    ("breaker", ("breaker", "circuit breaker", "mccb", " cb ", "20a cb")),
    ("relay", ("relay", "overload relay", "mv olr", "overcurrent relay")),
    ("cable", ("conductor", "cable", "thw", "xlp", "kcmil", "awg")),
]


def _infer_kind(mention_strs: Iterable[str]) -> EquipmentKind:
    """Cheap, deterministic kind inference from any mention string
    (parameter name + raw value + entity tag concatenated)."""
    joined = " ".join(s.lower() for s in mention_strs if s)
    for kind, keywords in _KIND_KEYWORDS:
        if any(k in joined for k in keywords):
            return kind
    return "other"


# ---------------------------------------------------------------------------
# Source-lane priority for lane-conflict resolution (spec §3.4)
# ---------------------------------------------------------------------------

_LANE_PRIORITY: dict[SourceLane, int] = {
    "regex": 0,      # most deterministic
    "llm_text": 1,
    "vision": 2,
}


def _pick_primary_mention(
    mentions: list[EquipmentMention],
) -> EquipmentMention:
    """Lowest source-lane priority wins; ties broken by page asc."""
    return min(
        mentions,
        key=lambda m: (_LANE_PRIORITY.get(m.source_lane, 99), m.page),
    )


# ---------------------------------------------------------------------------
# Mention construction
# ---------------------------------------------------------------------------


def _mention_from_record(
    rec: dict[str, Any],
    doc_id: str,
    canonical_context_id: str,
    context_kind: ContextKind,
) -> EquipmentMention:
    """Convert one synthetic-dict record into an EquipmentMention.

    Phase 33.5 will replace this with a ``ParameterRecord``-typed
    overload while preserving the same shape. For now Phase 33.3
    consumes the dict directly from the gold YAML.
    """
    bbox = rec.get("bbox")
    bbox_tuple: tuple[float, float, float, float] | None
    if bbox and len(bbox) == 4:
        bbox_tuple = (
            float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3]),
        )
    else:
        bbox_tuple = None

    grounding: GroundingMode = rec.get("grounding", "heuristic")
    if grounding not in (
        "text_layer_grounded", "ocr_grounded",
        "image_region_grounded", "heuristic",
    ):
        grounding = "heuristic"

    return EquipmentMention(
        doc_id=doc_id,
        page=int(rec["page"]),
        bbox=bbox_tuple,
        source_lane=rec.get("source_lane", "regex"),
        context_kind=context_kind,
        context_id=canonical_context_id or None,
        row_id=str(rec["row_id"]) if rec.get("row_id") else None,
        evidence_text=str(rec.get("raw_value") or rec.get("entity_tag") or ""),
        grounding=grounding,
    )


# ---------------------------------------------------------------------------
# Cluster grouping
# ---------------------------------------------------------------------------


_LEADING_NUMERIC_RE = re.compile(r"\d[\d,]*\.?\d*")


def _coincidence_key(raw_value: Any, normalized_magnitude: Any) -> str:
    """Stable string for cross-mention value coincidence detection
    (Pass 3 ambiguous_cluster grouping).

    Always scrapes the leading numeric token from raw_value when
    possible — same key for "1000 kVA", "1000KVA", "1,000 kVA". Falls
    back to normalized_magnitude when raw_value has no digits."""
    if raw_value is not None:
        m = _LEADING_NUMERIC_RE.search(str(raw_value))
        if m:
            return m.group(0).replace(",", "")
    if normalized_magnitude is not None:
        try:
            return f"{float(normalized_magnitude):.6g}"
        except (TypeError, ValueError):
            pass
    return ""


# ---------------------------------------------------------------------------
# Equipment construction
# ---------------------------------------------------------------------------


def _build_canonical_id(
    kind: EquipmentKind,
    context_id: str | None,
    row_id: str | None,
    part_number: str | None,
    page: int,
    bbox: tuple[float, float, float, float] | None,
) -> str:
    """Deterministic canonical-id construction per spec §3.3.

    Priority:
    1. context + row (+ optional part number) — table-row anchored
    2. part-number only — equipment-label anchored
    3. context + page location — diagram anchored (no row marker)
    4. fallback — kind + page (only when nothing else available)
    """
    if context_id and row_id:
        base = f"{kind}:{context_id}:row_{row_id}"
        if part_number:
            return f"{base}:{part_number}"
        return base
    if part_number:
        return f"{kind}:{part_number}"
    if context_id:
        # Diagram-only: encode page + quantized bbox centroid so
        # canonical_id stays stable across runs but distinguishes
        # multiple equipment on the same diagram page.
        loc = _quantized_centroid(bbox, page)
        return f"{kind}:{context_id}:{loc}"
    # Last resort. Should rarely fire — caller's records should at
    # least have context_id.
    return f"{kind}:p{page}"


def _quantized_centroid(
    bbox: tuple[float, float, float, float] | None, page: int,
) -> str:
    """Stable bbox-anchored location label. When bbox is None, use a
    page-only sentinel ('p{page}_loc_centroid' to keep the canonical
    structure consistent with image-grounded cases)."""
    if bbox is None:
        return f"p{page}_loc_centroid"
    cx = round((bbox[0] + bbox[2]) / 2.0)
    cy = round((bbox[1] + bbox[3]) / 2.0)
    return f"p{page}_loc_{cx}_{cy}"


def _equipment_from_cluster(
    cluster_mentions: list[EquipmentMention],
    cluster_records: list[dict[str, Any]],
    *,
    doc_id: str,
    cluster_status: str,
    canonical_context_id: str | None,
) -> Equipment:
    """Build one Equipment from a clustered set of mentions + their
    source records. Determines kind, anchors, parameters, canonical_id."""
    # 1. Kind inference from concatenated mention evidence + record names.
    text_blobs = []
    for m in cluster_mentions:
        text_blobs.append(m.evidence_text)
    for r in cluster_records:
        text_blobs.append(r.get("name", ""))
        text_blobs.append(r.get("entity_tag", ""))
    kind = _infer_kind(text_blobs)

    # 2. Identity anchor extraction — from raw_value, entity_tag.
    anchor_candidates: list[str] = []
    weak_descriptors: list[str] = []
    for r in cluster_records:
        for src_field in ("raw_value", "entity_tag"):
            val = r.get(src_field)
            if not val:
                continue
            anchor = _extract_identity_anchor(str(val))
            if anchor:
                if anchor not in anchor_candidates:
                    anchor_candidates.append(anchor)
            else:
                # Value-encoded or unrecognised — weak descriptor.
                v = str(val).strip()
                if v and v not in weak_descriptors:
                    weak_descriptors.append(v)

    # 3. Row marker + context as additional identity anchors.
    row_ids = sorted({m.row_id for m in cluster_mentions if m.row_id})
    primary_row_id = row_ids[0] if row_ids else None

    structural_anchors: list[str] = []
    if canonical_context_id:
        structural_anchors.append(canonical_context_id)
    if primary_row_id:
        structural_anchors.append(f"row_{primary_row_id}")

    # 4. Combine: prefer part-number anchors first, then structural.
    identity_anchors = []
    for a in anchor_candidates:
        if a not in identity_anchors:
            identity_anchors.append(a)
    for a in structural_anchors:
        if a not in identity_anchors:
            identity_anchors.append(a)

    # 5. Parameter attachment — record.name → record.raw_value.
    # Skip records where raw_value IS an identity anchor (e.g. the
    # part-number value extracted under name='Fuse Designation' is
    # the equipment's identity label, not a mutable parameter).
    # Without this gate `LPN-RK-500SP` would appear in both
    # identity_anchors and parameters, tripping
    # validate_identity_anchors_not_in_parameters.
    anchor_set = set(identity_anchors)
    parameters: dict[str, str] = {}
    for r in cluster_records:
        name = r.get("name")
        if not name:
            continue
        # Skip records whose `name` is the identity-bearing classifier
        # (Fuse Designation, Equipment ID, Device ID) — those are
        # identity claims, not parameter claims.
        if name.lower() in (
            "equipment id", "device id", "row",
            "fuse designation",  # part number IS identity, not parameter
            "equipment identifier", "equipment label",
            "device reference",
        ):
            continue
        raw_val = r.get("raw_value")
        if not raw_val:
            continue
        # Defensive: if the raw_value collides with an extracted
        # anchor, it's identity not parameter — skip.
        if str(raw_val).strip() in anchor_set:
            continue
        if raw_val not in parameters.values():
            parameters[name] = str(raw_val)

    # 6. canonical_id.
    primary_part_number = next(
        (a for a in anchor_candidates if a),
        None,
    )
    primary_mention = _pick_primary_mention(cluster_mentions)
    canonical_id = _build_canonical_id(
        kind=kind,
        context_id=canonical_context_id,
        row_id=primary_row_id,
        part_number=primary_part_number,
        page=primary_mention.page,
        bbox=primary_mention.bbox,
    )

    # 7. Confidence by status.
    confidence_by_status = {
        "confident_cluster": 0.95,
        "ambiguous_cluster": 0.6,
        "lane_conflict": 0.55,
        "forbidden_cluster": 0.0,
    }
    confidence = confidence_by_status.get(cluster_status, 0.7)

    eq = Equipment(
        doc_id=doc_id,
        canonical_id=canonical_id,
        kind=kind,
        identity_anchors=tuple(identity_anchors),
        weak_descriptors=tuple(weak_descriptors),
        parameters=parameters,
        mentions=tuple(cluster_mentions),
        confidence=confidence,
        cluster_status=cluster_status,  # type: ignore[arg-type]
    )
    validate_equipment(eq)
    return eq


# ---------------------------------------------------------------------------
# Clustering passes
# ---------------------------------------------------------------------------


_PART_NUMBER_ANCHOR_RE = re.compile(
    r"\b(?:LPS|LPN|LPJ|KRP|FNQ|FRS|FRN|JCN|JJN|JJS|EC|KTK)[\-\s]"
)


def _is_part_number_anchor(anchor: str) -> bool:
    """A part-number anchor (Bussmann fuse family, E-rated fuse) is a
    STRONG identity claim — different part numbers across mentions
    MUST block clustering. Equipment-label anchors like XFMR-1 / T1
    are weaker and allow ambiguous_cluster across contexts."""
    return bool(_PART_NUMBER_ANCHOR_RE.search(anchor))


def _cluster_records(
    records: list[dict[str, Any]],
    mentions: list[EquipmentMention],
    canonical_context_lookup: dict[str, str],
) -> list[tuple[str, list[dict[str, Any]], list[EquipmentMention], str | None]]:
    """Group records into clusters. Returns list of
    ``(cluster_status, records, mentions, canonical_context_id)``
    tuples in deterministic order.

    Algorithm (spec §3.4) — 4 passes:

    1. **Row-anchored grouping.** Group by
       ``(canonical_context_id, row_id)`` when both present. Multi-
       mention rows form clusters now; single-mention rows are
       provisionally clustered (will get pulled into Pass 3 if cross-
       context coincidence emerges). Within multi-mention rows, lane
       disagreement on identity anchors → ``lane_conflict``.

    2. **Part-number anchor agreement.** Among records with the SAME
       recognized part-number anchor (e.g. multiple LPN-RK-500SP
       mentions across contexts), cluster as ``confident_cluster``.

    3. **Cross-context coincidence — ambiguous_cluster.** Among
       unclustered records (including row-anchored singletons), group
       by ``(kind, coincidence_key)`` (numeric leading-token). Only
       fires when the group spans **multiple context_kinds** (e.g.
       diagram_label + schedule, not three table_row contexts). Part-
       number anchor disagreement BLOCKS the cluster (forbidden);
       equipment-label disagreement is allowed (anchors merge into
       cluster, with one chosen as primary).

    4. **Singletons.** Any record not pulled into a cluster becomes
       its own ``confident_cluster``.
    """
    used_indices: set[int] = set()
    clusters: list[tuple[str, list[dict[str, Any]], list[EquipmentMention], str | None]] = []

    # ---- Pass 1: row-anchored MULTI-mention clusters
    by_row: dict[tuple[str, str], list[int]] = defaultdict(list)
    for i, m in enumerate(mentions):
        if m.context_id and m.row_id:
            by_row[(m.context_id, m.row_id)].append(i)

    multi_row_idxs: dict[tuple[str, str], list[int]] = {}
    single_row_idxs: dict[tuple[str, str], list[int]] = {}
    for key, idxs in by_row.items():
        if len(idxs) >= 2:
            multi_row_idxs[key] = idxs
        else:
            single_row_idxs[key] = idxs

    for (ctx_raw, _row), idxs in sorted(multi_row_idxs.items()):
        cluster_recs = [records[i] for i in idxs]
        cluster_mens = [mentions[i] for i in idxs]
        recognized_anchors: set[str] = set()
        for r in cluster_recs:
            for src_field in ("raw_value", "entity_tag"):
                val = r.get(src_field)
                if val:
                    anchor = _extract_identity_anchor(str(val))
                    if anchor:
                        recognized_anchors.add(anchor)
        status = "lane_conflict" if len(recognized_anchors) > 1 else "confident_cluster"
        clusters.append((status, cluster_recs, cluster_mens, ctx_raw))
        used_indices.update(idxs)

    # ---- Pass 2: part-number anchor agreement across mentions
    by_anchor: dict[str, list[int]] = defaultdict(list)
    for i, _ in enumerate(mentions):
        if i in used_indices:
            continue
        rec = records[i]
        for src_field in ("raw_value", "entity_tag"):
            val = rec.get(src_field)
            if not val:
                continue
            anchor = _extract_identity_anchor(str(val))
            if anchor:
                by_anchor[anchor].append(i)
                break

    for anchor, idxs in sorted(by_anchor.items()):
        if len(idxs) < 2:
            continue
        cluster_recs = [records[i] for i in idxs]
        cluster_mens = [mentions[i] for i in idxs]
        ctx_set = {mentions[i].context_id for i in idxs}
        primary_ctx = next(iter(ctx_set)) if len(ctx_set) == 1 else _pick_primary_mention(cluster_mens).context_id
        clusters.append(("confident_cluster", cluster_recs, cluster_mens, primary_ctx))
        used_indices.update(idxs)

    # ---- Pass 3: cross-context coincidence (ambiguous_cluster)
    # Build candidate groups from records NOT yet clustered + records
    # in SINGLETON row-buckets (which are eligible to be pulled in).
    candidate_idxs = set(range(len(mentions))) - used_indices
    # Map provisional row-singletons back to candidates by collecting
    # their indices.
    for idxs in single_row_idxs.values():
        candidate_idxs.update(idxs)

    by_kind_value: dict[tuple[EquipmentKind, str], list[int]] = defaultdict(list)
    for i in candidate_idxs:
        rec = records[i]
        ev = rec.get("raw_value") or rec.get("entity_tag") or ""
        kind = _infer_kind([rec.get("name", ""), rec.get("entity_tag", ""), str(ev)])
        coincidence = _coincidence_key(rec.get("raw_value"), rec.get("normalized_magnitude"))
        if not coincidence:
            continue
        by_kind_value[(kind, coincidence)].append(i)

    pulled_for_ambiguous: set[int] = set()
    for (_kind, _val), idxs in sorted(by_kind_value.items()):
        if len(idxs) < 2:
            continue
        # Spans multiple context_kinds? If NOT, these are distinct
        # equipment instances in the same context family (Attack 1
        # shape: three TCC tables, each a separate transformer).
        # If YES, plausible same equipment seen from different
        # angles (Attack 8 shape).
        context_kinds = {mentions[i].context_kind for i in idxs}
        if len(context_kinds) < 2:
            continue
        # Part-number disagreement → forbidden, don't cluster.
        part_anchors: set[str] = set()
        for i in idxs:
            rec = records[i]
            for src_field in ("raw_value", "entity_tag"):
                a = _extract_identity_anchor(str(rec.get(src_field) or ""))
                if a and _is_part_number_anchor(a):
                    part_anchors.add(a)
        if len(part_anchors) >= 2:
            continue
        cluster_recs = [records[i] for i in idxs]
        cluster_mens = [mentions[i] for i in idxs]
        primary = _pick_primary_mention(cluster_mens)
        clusters.append(
            ("ambiguous_cluster", cluster_recs, cluster_mens, primary.context_id)
        )
        pulled_for_ambiguous.update(idxs)

    # Drop provisional row-singletons that got pulled into ambiguous.
    # Re-emit row-singletons that weren't pulled as confident clusters.
    for (_ctx, _row), idxs in sorted(single_row_idxs.items()):
        if any(i in pulled_for_ambiguous for i in idxs):
            continue
        if any(i in used_indices for i in idxs):
            continue
        cluster_recs = [records[i] for i in idxs]
        cluster_mens = [mentions[i] for i in idxs]
        clusters.append(
            ("confident_cluster", cluster_recs, cluster_mens, mentions[idxs[0]].context_id)
        )
        used_indices.update(idxs)
    used_indices.update(pulled_for_ambiguous)

    # ---- Pass 4: remaining singletons
    for i in range(len(mentions)):
        if i in used_indices:
            continue
        clusters.append(
            ("confident_cluster", [records[i]], [mentions[i]], mentions[i].context_id)
        )
        used_indices.add(i)

    return clusters


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def build_equipment_inventory(
    records: Iterable[dict[str, Any]],
    *,
    doc_id: str,
    cross_doc_contexts: list[ExtractedContext] | None = None,
) -> list[Equipment]:
    """Convert evidence records into a list of :class:`Equipment`.

    Phase 33.3 contract:

    - ``records`` is iterable of dict-shaped synthetic records (gold
      YAML shape). Phase 33.5 will accept :class:`ParameterRecord`
      via a thin adapter.
    - ``doc_id`` distinguishes doc_a vs doc_b. Stamped on every
      :class:`Equipment` + :class:`EquipmentMention` so cross-doc
      matching (Phase 33.4) can refuse same-side pairs.
    - ``cross_doc_contexts`` (optional) lets the caller pass the
      OTHER doc's contexts so :func:`align_contexts_across_docs`
      can promote a shared canonical_id across the docs (Attack 11).
      Pass ``None`` for single-doc operation.

    Output: list of :class:`Equipment` in deterministic order
    (sorted by canonical_id). Each Equipment passes
    ``validate_equipment``.
    """
    records_list = list(records)

    # 1. Extract per-doc contexts.
    own_contexts = extract_contexts(records_list, doc_id=doc_id)

    # 2. Optional cross-doc canonical alignment.
    if cross_doc_contexts is not None:
        alias_map = align_contexts_across_docs(own_contexts, cross_doc_contexts)
    else:
        alias_map = {(c.doc_id, c.raw_title): c.canonical_id for c in own_contexts}

    # 3. Build lookup from raw_title → canonical_id within this doc.
    raw_to_canonical: dict[str, str] = {}
    raw_to_kind: dict[str, ContextKind] = {}
    for ctx in own_contexts:
        raw_to_canonical[ctx.raw_title] = alias_map.get(
            (doc_id, ctx.raw_title), ctx.canonical_id,
        )
        raw_to_kind[ctx.raw_title] = ctx.kind

    # 4. Lift records → mentions.
    mentions: list[EquipmentMention] = []
    for rec in records_list:
        raw_title = rec.get("context_id") or ""
        canonical = raw_to_canonical.get(raw_title, "")
        context_kind: ContextKind = raw_to_kind.get(raw_title, "prose")
        mentions.append(
            _mention_from_record(
                rec,
                doc_id=doc_id,
                canonical_context_id=canonical,
                context_kind=context_kind,
            )
        )

    # 5. Cluster.
    clusters = _cluster_records(records_list, mentions, raw_to_canonical)

    # 6. Build Equipment per cluster.
    equipment_list: list[Equipment] = []
    for status, cluster_recs, cluster_mens, canonical_context in clusters:
        eq = _equipment_from_cluster(
            cluster_mens,
            cluster_recs,
            doc_id=doc_id,
            cluster_status=status,
            canonical_context_id=canonical_context,
        )
        equipment_list.append(eq)

    return sorted(equipment_list, key=lambda e: e.canonical_id)
