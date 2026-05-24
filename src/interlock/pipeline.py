"""End-to-end review pipeline.

Ingest two PDFs, extract parameters, align them, emit directional flags
with severity tiers. Optionally enrich each flag with an LLM significance
judgment for engineering rationale + downstream-effect propagation.

The embedder is injected so tests can use deterministic stubs and the
Streamlit app can wire Voyage.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from interlock.adjudicator import adjudicate_flags
from interlock.align.claims import align_claims_exact
from interlock.align.combiner import combine_alignments
from interlock.align.exact import align_exact
from interlock.align.semantic import align_semantic
from interlock.detect.mismatch import Flag, detect_flags
from interlock.detect.significance import apply_judgment_to_flag, judge
from interlock.extract.entities import claims_from_records
from interlock.extract.parameters import ParameterRecord, extract_parameters
from interlock.ingest.pdf import ingest
from interlock.llm_pipeline.schemas.doc_class import DocClass, DocClassification
from interlock.store import sqlite as store

logger = logging.getLogger(__name__)


def _log_record_tally(
    side: str, doc_id: str, records: list[ParameterRecord],
) -> None:
    """INFO-level: per-(parameter, page, lane) tally of extracted records.

    Output shape (one line per parameter)::

        records A doc_a 'Transformer Impedance': 4
          [p2 vision] 5.75 % (XFMR-001) [p3 regex] 5.75 % () ...

    Use when diagnosing "why didn't TP-N surface": shows whether the
    mutated value was actually extracted, by which lane, on which page.
    """
    by_name: dict[str, list[ParameterRecord]] = {}
    for r in records:
        by_name.setdefault(r.name, []).append(r)
    for name in sorted(by_name):
        recs = by_name[name]
        details = " ".join(
            f"[p{r.page} {r.extraction_lane}] {r.raw_value!r}"
            f"{(' (' + r.entity_tag + ')') if r.entity_tag else ''}"
            for r in recs
        )
        logger.info(
            "records %s %s %r: %d  %s",
            side, doc_id, name, len(recs), details,
        )


def _log_surfaced_flags(flags: list[Flag]) -> None:
    """INFO-level: dump every surfaced flag with full pair detail.
    Easier triage than scrolling through the UI for "why did this
    flag surface?"."""
    for f in flags:
        a_tag = getattr(f.a_record, "entity_tag", "") or "—"
        b_tag = getattr(f.b_record, "entity_tag", "") or "—"
        a_lane = getattr(f.a_record, "extraction_lane", "regex")
        b_lane = getattr(f.b_record, "extraction_lane", "regex")
        logger.info(
            "FLAG %s sev=%s conf=%.2f dev=%.3f%% "
            "A=[%s p%d %s tag=%s] B=[%s p%d %s tag=%s] rule=%s",
            f.parameter, f.severity, f.confidence,
            (f.deviation_pct or 0.0) * 100,
            a_lane, f.a_record.page, f.a_record.raw_value, a_tag,
            b_lane, f.b_record.page, f.b_record.raw_value, b_tag,
            f.authority_rule,
        )


@dataclass(frozen=True)
class ReviewResult:
    """Rich pipeline output. ``flags`` is what the detector emitted; the
    ``unpaired_*`` lists are records the aligner couldn't confidently pair
    across documents (different Device IDs, no positional anchor, etc.) —
    surfacing them lets the reviewer see WHAT we didn't compare instead
    of treating silent gaps as clean runs.

    ``doc_class_a`` / ``doc_class_b`` are populated only when the pipeline
    is called with ``classify_docs=True`` (v2 Sprint 1). Default ``None``
    preserves v1 back-compat across the 261-test invariant suite."""

    flags: list[Flag]
    unpaired_a: list[ParameterRecord] = field(default_factory=list)
    unpaired_b: list[ParameterRecord] = field(default_factory=list)
    doc_class_a: DocClassification | None = None
    doc_class_b: DocClassification | None = None

EmbedFn = Callable[[list[str]], dict[str, list[float]]]
# (stage_id, state) where state is "start" or "done". stage_id values are
# stable strings the UI maps to human labels — adding new stages requires
# UI awareness but never breaks callers that ignore unknown ids.
StageCallback = Callable[[str, str], None]

if TYPE_CHECKING:
    from interlock.ingest.pdf import OcrProgressCallback


def review_two_documents_full(
    pdf_a: str,
    pdf_b: str,
    embed_fn: EmbedFn,
    doc_a_id: str = "doc_a",
    doc_b_id: str = "doc_b",
    same_page_only: bool = True,
    use_llm_judge: bool = True,            # v2.4: flipped to True
    suppress_info: bool = True,
    use_claim_layer: bool = False,
    same_entity_only: bool = True,
    persist_claims: bool = False,
    table_max_pages: int | None = None,
    enable_vision_ocr: bool = False,
    ocr_progress_cb: OcrProgressCallback | None = None,
    stage_cb: StageCallback | None = None,
    classify_docs: bool = True,            # v2.4: flipped to True
    use_llm_extraction: bool = True,       # v2.4: flipped to True
    use_llm_reranker: bool = True,         # v2.4: flipped to True
    use_entity_grounding: bool = True,     # v2.4: new, default True
    project_id: str | None = None,         # v2 Sprint 5a — clause-registry project override
    use_vision_lane: bool = True,          # v2 Sprint 8 — vision lane on diagram pages
    vision_progress_cb: Callable[[int, int, int], None] | None = None,  # (done, total, page)
) -> ReviewResult:
    """Run end-to-end review.

    ``same_page_only=True`` (default) suits revision-diff fixtures where the two
    documents share layout. Set ``False`` for cross-document pairs (e.g. spec ↔
    coordination study) where the same parameter appears on different pages.

    ``use_llm_judge=True`` runs each emitted flag through the LLM
    significance judge (``detect/significance.py``) and enriches severity +
    rationale + confidence with engineering reasoning. Disk-cached per flag,
    so repeated runs only pay LLM cost on new flags.

    ``suppress_info=True`` (default) drops within-tolerance changes from the
    output entirely. Pass ``False`` to receive every classified flag (used
    by the UI's "Suppressed" expander).

    ``use_claim_layer=True`` (Phase 14, opt-in) routes alignment through the
    Entity + Claim layer instead of operating directly on ParameterRecord.
    This enables multi-equipment fixtures (XFMR-001 vs XFMR-002 not confused).
    When False (default) v1.3 behavior is preserved exactly.

    ``same_entity_only=True`` (effective when ``use_claim_layer=True``) keeps
    only pairs whose entity ids match (implicit entities are wildcards).

    ``persist_claims=True`` writes claims and entities to the SQLite store
    for audit/triage. Off by default since the demo loop doesn't need it.

    ``stage_cb`` (optional) fires before/after each major pipeline phase
    so a UI can render per-stage progress instead of a static checklist.
    Emitted ids in order: ``ingest_a``, ``ingest_b``, ``extract``,
    ``align``, ``detect``, ``judge`` (only when ``use_llm_judge=True``
    and at least one flag survived detection).
    """
    def _cb_a(done: int, total: int, page: int) -> None:
        if ocr_progress_cb is not None:
            ocr_progress_cb(done, total, page)

    def _stage(name: str, state: str) -> None:
        if stage_cb is not None:
            stage_cb(name, state)

    # v2 Sprint 1: optional doc-class classifier runs in parallel with the
    # rest of the pipeline. classify_docs=False (default) skips the call
    # entirely → 261-test invariant preserved bit-for-bit.
    doc_class_a: DocClassification | None = None
    doc_class_b: DocClassification | None = None
    classify_executor: ThreadPoolExecutor | None = None
    if classify_docs:
        from interlock.llm_pipeline.classify import classify_doc
        _stage("classify", "start")
        classify_executor = ThreadPoolExecutor(max_workers=2)
        fut_a = classify_executor.submit(classify_doc, pdf_a)
        fut_b = classify_executor.submit(classify_doc, pdf_b)

    pipeline_t0 = time.time()
    logger.info(
        "pipeline START doc_a=%s doc_b=%s same_page_only=%s use_llm_judge=%s "
        "classify_docs=%s use_llm_extraction=%s use_llm_reranker=%s "
        "use_entity_grounding=%s use_vision_lane=%s",
        doc_a_id, doc_b_id, same_page_only, use_llm_judge,
        classify_docs, use_llm_extraction, use_llm_reranker,
        use_entity_grounding, use_vision_lane,
    )

    _stage("ingest_a", "start")
    t = time.time()
    ia = ingest(
        pdf_a,
        doc_id=doc_a_id,
        table_max_pages=table_max_pages,
        enable_vision_ocr=enable_vision_ocr,
        ocr_progress_cb=_cb_a,
    )
    logger.info(
        "ingest A: %d spans in %.2fs", len(ia.spans), time.time() - t,
    )
    _stage("ingest_a", "done")

    _stage("ingest_b", "start")
    t = time.time()
    ib = ingest(
        pdf_b,
        doc_id=doc_b_id,
        table_max_pages=table_max_pages,
        enable_vision_ocr=enable_vision_ocr,
        ocr_progress_cb=_cb_a,
    )
    logger.info(
        "ingest B: %d spans in %.2fs", len(ib.spans), time.time() - t,
    )
    _stage("ingest_b", "done")

    _stage("extract", "start")
    t = time.time()
    pa = extract_parameters(ia.spans)
    pb = extract_parameters(ib.spans)
    logger.info(
        "extract (Track 1 regex): A=%d B=%d records in %.2fs",
        len(pa), len(pb), time.time() - t,
    )
    _stage("extract", "done")

    # v2.8.1: page-structure classification. Always runs (heuristic + diskcached,
    # ~free). Two consumers:
    #   1. Vision lane routes diagram pages to Sonnet 4.5 Vision.
    #   2. entity_bind skips diagram pages (PyMuPDF text-layer y is draw-order
    #      on diagrams, not visual y — the y-enclosure heuristic would
    #      systematically mis-bind, e.g. transformer %Z to nearest fuse model).
    import fitz
    from interlock.llm_pipeline.page_classify import classify_page_structure

    def _page_count(path: str) -> int:
        try:
            d = fitz.open(path)
            n = int(d.page_count)
            d.close()
            return n
        except Exception:
            return 0

    n_pages_a = _page_count(pdf_a)
    n_pages_b = _page_count(pdf_b)
    diagram_pages_a: list[int] = []
    diagram_pages_b: list[int] = []
    try:
        for p in range(1, n_pages_a + 1):
            if classify_page_structure(pdf_a, p) == "diagram":
                diagram_pages_a.append(p)
        for p in range(1, n_pages_b + 1):
            if classify_page_structure(pdf_b, p) == "diagram":
                diagram_pages_b.append(p)
    except Exception as exc:
        logger.warning("page-classify failed: %s", exc)

    # v2 Sprint 8: vision lane for diagram pages. Runs BEFORE Track 2 LLM
    # text extraction so vision-sourced records sit alongside Track 2's
    # text extraction. Per-page routing — only diagram pages call vision.
    if use_vision_lane:
        from interlock.llm_pipeline.vision_extract import vision_extract_page
        _stage("vision_extract", "start")
        vision_t0 = time.time()
        logger.info("vision-lane stage START doc_a=%s doc_b=%s", doc_a_id, doc_b_id)

        total_pages = len(diagram_pages_a) + len(diagram_pages_b)
        logger.info(
            "vision-lane pre-classify A=%d/%d diagram pages, B=%d/%d diagram pages, total=%d",
            len(diagram_pages_a), n_pages_a,
            len(diagram_pages_b), n_pages_b,
            total_pages,
        )
        done = 0
        records_a_before = len(pa)
        records_b_before = len(pb)

        def _emit(page: int) -> None:
            if vision_progress_cb is not None:
                try:
                    vision_progress_cb(done, total_pages, page)
                except Exception:
                    pass

        for p in diagram_pages_a:
            try:
                pa = pa + vision_extract_page(pdf_a, p, doc_id=doc_a_id)
            except Exception as exc:
                logger.warning("vision-lane A/p%d unexpected error: %s", p, exc)
            done += 1
            _emit(p)
        for p in diagram_pages_b:
            try:
                pb = pb + vision_extract_page(pdf_b, p, doc_id=doc_b_id)
            except Exception as exc:
                logger.warning("vision-lane B/p%d unexpected error: %s", p, exc)
            done += 1
            _emit(p)

        added_a = len(pa) - records_a_before
        added_b = len(pb) - records_b_before
        logger.info(
            "vision-lane stage DONE records added A=%d B=%d total=%d in %.1fs",
            added_a, added_b, added_a + added_b, time.time() - vision_t0,
        )
        _stage("vision_extract", "done")

    # v2 Sprint 2: Track 2 LLM extraction (opt-in via use_llm_extraction).
    # Records appended after Track 1; alignment sees the union.
    if use_llm_extraction:
        from interlock.llm_pipeline.extract import extract_claims_from_doc

        cls_a = doc_class_a.doc_class if doc_class_a is not None else DocClass.unknown
        cls_b = doc_class_b.doc_class if doc_class_b is not None else DocClass.unknown

        _stage("llm_extract_a", "start")
        t = time.time()
        try:
            llm_records_a = extract_claims_from_doc(pdf_a, cls_a, doc_id=doc_a_id)
        except Exception as exc:
            logger.warning("Track 2 llm_extract A failed: %s", exc)
            llm_records_a = []
        pa = pa + llm_records_a
        logger.info(
            "llm_extract A: +%d records (cls=%s) in %.2fs; total A=%d",
            len(llm_records_a), cls_a.value, time.time() - t, len(pa),
        )
        _stage("llm_extract_a", "done")

        _stage("llm_extract_b", "start")
        t = time.time()
        try:
            llm_records_b = extract_claims_from_doc(pdf_b, cls_b, doc_id=doc_b_id)
        except Exception as exc:
            logger.warning("Track 2 llm_extract B failed: %s", exc)
            llm_records_b = []
        pb = pb + llm_records_b
        logger.info(
            "llm_extract B: +%d records (cls=%s) in %.2fs; total B=%d",
            len(llm_records_b), cls_b.value, time.time() - t, len(pb),
        )
        _stage("llm_extract_b", "done")

    # v2.8.1: cross-lane same-doc dedup. Collapses Track 1 / Track 2 /
    # vision records that describe the same parameter on the same doc to
    # prevent the cross-lane duplicate-flag class (vision > llm_text > regex).
    # Runs AFTER all extraction lanes, BEFORE entity binding.
    from interlock.extract.dedup import dedup_same_doc_records
    pa = dedup_same_doc_records(pa)
    pb = dedup_same_doc_records(pb)

    # v2.8.3 — per-doc per-parameter tally promoted to INFO. Triage
    # needs to see which params extracted from each doc + on which pages
    # without flipping to DEBUG (which floods with vision-claim DEBUG too).
    _log_record_tally("A", doc_a_id, pa)
    _log_record_tally("B", doc_b_id, pb)

    # v2 Sprint 4.5: entity grounding. Runs AFTER Track 2 union-merge so
    # both Track 1 + Track 2 records get bound by the same detector pass.
    # v2.8.1: diagram_pages_a / diagram_pages_b passed in so the binder
    # skips diagram pages (where PyMuPDF text-layer y is draw-order ≠
    # visual y and y-enclosure systematically mis-binds).
    if use_entity_grounding:
        from interlock.extract.entity_bind import bind_records_to_entities
        from interlock.llm_pipeline.entity_detect import detect_entities_for_doc
        _stage("entity_detect", "start")
        t = time.time()
        try:
            ents_a = detect_entities_for_doc(pdf_a)
            ents_b = detect_entities_for_doc(pdf_b)
            tagged_before_a = sum(1 for r in pa if r.entity_tag)
            tagged_before_b = sum(1 for r in pb if r.entity_tag)
            pa = bind_records_to_entities(
                pa, ents_a, diagram_pages=set(diagram_pages_a),
            )
            pb = bind_records_to_entities(
                pb, ents_b, diagram_pages=set(diagram_pages_b),
            )
            tagged_after_a = sum(1 for r in pa if r.entity_tag)
            tagged_after_b = sum(1 for r in pb if r.entity_tag)
            n_ents_a = sum(len(v) for v in ents_a.values())
            n_ents_b = sum(len(v) for v in ents_b.values())
            logger.info(
                "entity_detect: A=%d entities, B=%d entities; "
                "binds A=%d→%d B=%d→%d (skipped %d/%d diagram pages) in %.2fs",
                n_ents_a, n_ents_b,
                tagged_before_a, tagged_after_a,
                tagged_before_b, tagged_after_b,
                len(diagram_pages_a), len(diagram_pages_b),
                time.time() - t,
            )
        except Exception as exc:
            logger.warning("entity_detect failed: %s — falling back unbound", exc)
        _stage("entity_detect", "done")

    _stage("align", "start")
    if use_claim_layer:
        ca = claims_from_records(pa)
        cb = claims_from_records(pb)
        if persist_claims:
            for c in (*ca, *cb):
                store.upsert_claim(c)
        exact = align_claims_exact(ca, cb, same_entity_only=same_entity_only)
    else:
        exact = align_exact(pa, pb)

    t = time.time()
    semantic = align_semantic(pa, pb, embed_fn=embed_fn, same_page_only=same_page_only)
    combined = combine_alignments(exact, semantic)
    logger.info(
        "align: exact=%d semantic=%d combined=%d pairs (same_page_only=%s) in %.2fs",
        len(exact), len(semantic), len(combined), same_page_only, time.time() - t,
    )

    # v2 Sprint 4: opt-in LLM pairing reranker. Pure pass-through when off.
    if use_llm_reranker:
        from interlock.llm_pipeline.pair import rerank_weak_pairs
        _stage("rerank", "start")
        t = time.time()
        try:
            combined = rerank_weak_pairs(combined)
            logger.info(
                "rerank: %d pairs reviewed in %.2fs", len(combined), time.time() - t,
            )
        except Exception as exc:
            logger.warning("rerank failed: %s — keeping Track 1 verdicts", exc)
        _stage("rerank", "done")

    _stage("align", "done")

    _stage("detect", "start")
    t = time.time()
    flags = detect_flags(combined, suppress_info=suppress_info)
    logger.info(
        "detect: %d flags from %d pairs (suppress_info=%s) in %.2fs",
        len(flags), len(combined), suppress_info, time.time() - t,
    )

    # v2.8.4 — checklist-gap detector. Surfaces in-scope Doc A unpaired
    # records (currently Fuse Designation) whose raw_value also does not
    # appear anywhere in Doc B. Mirrors gold FN-1 (LPN-RK-500SP removed
    # between revisions).
    from interlock.detect.checklist import detect_checklist_gaps
    paired_a_ids_pre = {id(p.a) for p in combined}
    unpaired_a_pre = [r for r in pa if id(r) not in paired_a_ids_pre]
    gap_flags = detect_checklist_gaps(unpaired_a_pre, pb, doc_a_id, doc_b_id)
    if gap_flags:
        flags = flags + gap_flags

    # v2.8.6 — flag-level dedup: collapse cross-page-duplicate flags
    # that all point at the same Doc B record (the "one inconsistency
    # in B paired against N records in A" shape).
    from interlock.detect.flag_dedup import dedup_flags_by_b_record
    flags = dedup_flags_by_b_record(flags)
    _stage("detect", "done")

    # v2 Sprint 3: annotate provenance. Pure function; zero cost; runs always.
    flags = adjudicate_flags(flags)

    if use_llm_judge and flags:
        _stage("judge", "start")
        t = time.time()
        flags = [
            apply_judgment_to_flag(
                f, judge(f, project_id=project_id), project_id=project_id,
            )
            for f in flags
        ]
        logger.info(
            "judge: %d flags judged in %.2fs", len(flags), time.time() - t,
        )
        _stage("judge", "done")

    # Compute unpaired sets from the COMBINED aligned-pair list (before
    # detect_flags filtering, so the reviewer sees every record that had
    # no cross-doc counterpart — not just ones that survived severity
    # classification). Identity by object — pa/pb were the lists handed
    # to the aligners, so id()-equality is exact.
    paired_a_ids = {id(p.a) for p in combined}
    paired_b_ids = {id(p.b) for p in combined}
    unpaired_a = [r for r in pa if id(r) not in paired_a_ids]
    unpaired_b = [r for r in pb if id(r) not in paired_b_ids]

    # Drain classify futures (if running) and collapse failures to
    # unknown(0.0) — pipeline keeps working even if the classifier
    # outage / API timeout would otherwise propagate as an exception.
    if classify_executor is not None:
        try:
            doc_class_a = fut_a.result()
        except Exception as e:
            doc_class_a = DocClassification(
                doc_class=DocClass.unknown, confidence=0.0,
                reasoning=f"classifier raised: {type(e).__name__}: {e}",
            )
        try:
            doc_class_b = fut_b.result()
        except Exception as e:
            doc_class_b = DocClassification(
                doc_class=DocClass.unknown, confidence=0.0,
                reasoning=f"classifier raised: {type(e).__name__}: {e}",
            )
        classify_executor.shutdown(wait=False)
        _stage("classify", "done")
        logger.info(
            "classify: A=%s (conf=%.2f) B=%s (conf=%.2f)",
            doc_class_a.doc_class.value, doc_class_a.confidence,
            doc_class_b.doc_class.value, doc_class_b.confidence,
        )

    _log_surfaced_flags(flags)
    logger.info(
        "pipeline END flags=%d unpaired_a=%d unpaired_b=%d total %.1fs",
        len(flags), len(unpaired_a), len(unpaired_b),
        time.time() - pipeline_t0,
    )

    return ReviewResult(
        flags=flags,
        unpaired_a=unpaired_a,
        unpaired_b=unpaired_b,
        doc_class_a=doc_class_a,
        doc_class_b=doc_class_b,
    )


def review_two_documents(
    pdf_a: str,
    pdf_b: str,
    embed_fn: EmbedFn,
    doc_a_id: str = "doc_a",
    doc_b_id: str = "doc_b",
    same_page_only: bool = True,
    use_llm_judge: bool = True,            # v2.4: flipped to True
    suppress_info: bool = True,
    use_claim_layer: bool = False,
    same_entity_only: bool = True,
    persist_claims: bool = False,
    table_max_pages: int | None = None,
    enable_vision_ocr: bool = False,
    ocr_progress_cb: OcrProgressCallback | None = None,
    stage_cb: StageCallback | None = None,
    classify_docs: bool = True,            # v2.4: flipped to True
    use_llm_extraction: bool = True,       # v2.4: flipped to True
    use_llm_reranker: bool = True,         # v2.4: flipped to True
    use_entity_grounding: bool = True,     # v2.4: new, default True
    project_id: str | None = None,         # v2 Sprint 5a — clause-registry project override
    use_vision_lane: bool = True,          # v2 Sprint 8 — vision lane on diagram pages
    vision_progress_cb: Callable[[int, int, int], None] | None = None,  # (done, total, page)
) -> list[Flag]:
    """Back-compat shim: returns only the flag list.

    New callers should prefer ``review_two_documents_full()`` which also
    returns the unpaired-record lists for honest gap reporting in the UI.
    """
    return review_two_documents_full(
        pdf_a=pdf_a,
        pdf_b=pdf_b,
        embed_fn=embed_fn,
        doc_a_id=doc_a_id,
        doc_b_id=doc_b_id,
        same_page_only=same_page_only,
        use_llm_judge=use_llm_judge,
        suppress_info=suppress_info,
        use_claim_layer=use_claim_layer,
        same_entity_only=same_entity_only,
        persist_claims=persist_claims,
        table_max_pages=table_max_pages,
        enable_vision_ocr=enable_vision_ocr,
        ocr_progress_cb=ocr_progress_cb,
        stage_cb=stage_cb,
        classify_docs=classify_docs,
        use_llm_extraction=use_llm_extraction,
        use_llm_reranker=use_llm_reranker,
        use_entity_grounding=use_entity_grounding,
        project_id=project_id,
        use_vision_lane=use_vision_lane,
        vision_progress_cb=vision_progress_cb,
    ).flags
