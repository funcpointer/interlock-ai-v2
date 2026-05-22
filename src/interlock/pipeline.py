"""End-to-end review pipeline.

Ingest two PDFs, extract parameters, align them, emit directional flags
with severity tiers. Optionally enrich each flag with an LLM significance
judgment for engineering rationale + downstream-effect propagation.

The embedder is injected so tests can use deterministic stubs and the
Streamlit app can wire Voyage.
"""

from __future__ import annotations

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
    use_llm_judge: bool = False,
    suppress_info: bool = True,
    use_claim_layer: bool = False,
    same_entity_only: bool = True,
    persist_claims: bool = False,
    table_max_pages: int | None = None,
    enable_vision_ocr: bool = False,
    ocr_progress_cb: OcrProgressCallback | None = None,
    stage_cb: StageCallback | None = None,
    classify_docs: bool = False,
    use_llm_extraction: bool = False,
    use_llm_reranker: bool = False,
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

    _stage("ingest_a", "start")
    ia = ingest(
        pdf_a,
        doc_id=doc_a_id,
        table_max_pages=table_max_pages,
        enable_vision_ocr=enable_vision_ocr,
        ocr_progress_cb=_cb_a,
    )
    _stage("ingest_a", "done")

    _stage("ingest_b", "start")
    ib = ingest(
        pdf_b,
        doc_id=doc_b_id,
        table_max_pages=table_max_pages,
        enable_vision_ocr=enable_vision_ocr,
        ocr_progress_cb=_cb_a,
    )
    _stage("ingest_b", "done")

    _stage("extract", "start")
    pa = extract_parameters(ia.spans)
    pb = extract_parameters(ib.spans)
    _stage("extract", "done")

    # v2 Sprint 2: Track 2 LLM extraction (opt-in via use_llm_extraction).
    # Records appended after Track 1; alignment sees the union.
    if use_llm_extraction:
        from interlock.llm_pipeline.extract import extract_claims_from_doc

        cls_a = doc_class_a.doc_class if doc_class_a is not None else DocClass.unknown
        cls_b = doc_class_b.doc_class if doc_class_b is not None else DocClass.unknown

        _stage("llm_extract_a", "start")
        try:
            llm_records_a = extract_claims_from_doc(pdf_a, cls_a, doc_id=doc_a_id)
        except Exception:
            llm_records_a = []
        pa = pa + llm_records_a
        _stage("llm_extract_a", "done")

        _stage("llm_extract_b", "start")
        try:
            llm_records_b = extract_claims_from_doc(pdf_b, cls_b, doc_id=doc_b_id)
        except Exception:
            llm_records_b = []
        pb = pb + llm_records_b
        _stage("llm_extract_b", "done")

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

    semantic = align_semantic(pa, pb, embed_fn=embed_fn, same_page_only=same_page_only)
    combined = combine_alignments(exact, semantic)

    # v2 Sprint 4: opt-in LLM pairing reranker. Pure pass-through when off.
    if use_llm_reranker:
        from interlock.llm_pipeline.pair import rerank_weak_pairs
        _stage("rerank", "start")
        try:
            combined = rerank_weak_pairs(combined)
        except Exception:
            pass  # API outage / unexpected error → keep Track 1 verdicts
        _stage("rerank", "done")

    _stage("align", "done")

    _stage("detect", "start")
    flags = detect_flags(combined, suppress_info=suppress_info)
    _stage("detect", "done")

    # v2 Sprint 3: annotate provenance. Pure function; zero cost; runs always.
    flags = adjudicate_flags(flags)

    if use_llm_judge and flags:
        _stage("judge", "start")
        flags = [apply_judgment_to_flag(f, judge(f)) for f in flags]
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
    use_llm_judge: bool = False,
    suppress_info: bool = True,
    use_claim_layer: bool = False,
    same_entity_only: bool = True,
    persist_claims: bool = False,
    table_max_pages: int | None = None,
    enable_vision_ocr: bool = False,
    ocr_progress_cb: OcrProgressCallback | None = None,
    stage_cb: StageCallback | None = None,
    classify_docs: bool = False,
    use_llm_extraction: bool = False,
    use_llm_reranker: bool = False,
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
    ).flags
