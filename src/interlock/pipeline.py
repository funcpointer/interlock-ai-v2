"""End-to-end review pipeline.

Ingest two PDFs, extract parameters, align them, emit directional flags
with severity tiers. Optionally enrich each flag with an LLM significance
judgment for engineering rationale + downstream-effect propagation.

The embedder is injected so tests can use deterministic stubs and the
Streamlit app can wire Voyage.
"""

from __future__ import annotations

from collections.abc import Callable

from interlock.align.claims import align_claims_exact
from interlock.align.combiner import combine_alignments
from interlock.align.exact import align_exact
from interlock.align.semantic import align_semantic
from interlock.detect.mismatch import Flag, detect_flags
from interlock.detect.significance import apply_judgment_to_flag, judge
from interlock.extract.entities import claims_from_records
from interlock.extract.parameters import extract_parameters
from interlock.ingest.pdf import ingest
from interlock.store import sqlite as store

EmbedFn = Callable[[list[str]], dict[str, list[float]]]


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
) -> list[Flag]:
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
    """
    ia = ingest(pdf_a, doc_id=doc_a_id)
    ib = ingest(pdf_b, doc_id=doc_b_id)
    pa = extract_parameters(ia.spans)
    pb = extract_parameters(ib.spans)

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
    flags = detect_flags(combined, suppress_info=suppress_info)
    if use_llm_judge and flags:
        flags = [apply_judgment_to_flag(f, judge(f)) for f in flags]
    return flags
