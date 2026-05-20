"""End-to-end review pipeline.

Ingest two PDFs, extract parameters, align them, emit directional flags.
The embedder is injected so tests can use deterministic stubs and the
Streamlit app can wire Voyage.
"""

from __future__ import annotations

from collections.abc import Callable

from interlock.align.combiner import combine_alignments
from interlock.align.exact import align_exact
from interlock.align.semantic import align_semantic
from interlock.detect.mismatch import Flag, detect_flags
from interlock.extract.parameters import extract_parameters
from interlock.ingest.pdf import ingest

EmbedFn = Callable[[list[str]], dict[str, list[float]]]


def review_two_documents(
    pdf_a: str,
    pdf_b: str,
    embed_fn: EmbedFn,
    doc_a_id: str = "doc_a",
    doc_b_id: str = "doc_b",
    same_page_only: bool = True,
) -> list[Flag]:
    """Run end-to-end review.

    ``same_page_only=True`` (default) suits revision-diff fixtures where the two
    documents share layout. Set ``False`` for cross-document pairs (e.g. spec ↔
    coordination study) where the same parameter appears on different pages.
    """
    ia = ingest(pdf_a, doc_id=doc_a_id)
    ib = ingest(pdf_b, doc_id=doc_b_id)
    pa = extract_parameters(ia.spans)
    pb = extract_parameters(ib.spans)
    exact = align_exact(pa, pb)
    semantic = align_semantic(pa, pb, embed_fn=embed_fn, same_page_only=same_page_only)
    combined = combine_alignments(exact, semantic)
    return detect_flags(combined)
