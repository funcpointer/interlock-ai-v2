"""InterLock AI — Streamlit single-page review UI.

Run locally:
    uv run streamlit run src/interlock/ui/app.py

Reads ``VOYAGE_API_KEY`` and (optional) ``ANTHROPIC_API_KEY`` from the
environment. On Streamlit Cloud, ``st.secrets`` values are bridged into
``os.environ`` at import time.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
import time
from pathlib import Path
from typing import Any

import streamlit as st
from dotenv import load_dotenv

load_dotenv()

# Streamlit Cloud secrets bridge: copy any st.secrets entries into os.environ
# so downstream code (Voyage, Anthropic) finds them without conditional imports.
try:
    for k, v in st.secrets.items():  # pragma: no cover
        os.environ.setdefault(k, str(v))
except Exception:  # pragma: no cover
    pass

from interlock.align.embed import embed_voyage  # noqa: E402
from interlock.citation.render import render_citation  # noqa: E402
from interlock.extract.parameters import extract_parameters  # noqa: E402
from interlock.ingest.pdf import ingest  # noqa: E402
from interlock.pipeline import review_two_documents_full  # noqa: E402


# ----------------------------------------------------------------------
# Page config + theme
# ----------------------------------------------------------------------

st.set_page_config(
    page_title="InterLock AI — Review",
    layout="wide",
    initial_sidebar_state="expanded",
)

_SEVERITY = {
    "critical": {"emoji": "🔴", "label": "CRITICAL", "border": "#c0392b", "bg": "#fdecea"},
    "major":    {"emoji": "🟠", "label": "MAJOR",    "border": "#d35400", "bg": "#fef0e6"},
    "minor":    {"emoji": "🟡", "label": "MINOR",    "border": "#b7950b", "bg": "#fff8db"},
    "info":     {"emoji": "⚪", "label": "INFO",     "border": "#7f8c8d", "bg": "#f2f3f4"},
}
_SEVERITY_ORDER = {"critical": 0, "major": 1, "minor": 2, "info": 3}

# v2 Sprint 3: maps reviewer-facing filter labels → provenance set the
# flag's provenance field must belong to to be visible. "All" surfaces
# every label including the defensive "unknown".
_TRACK_FILTER_MAP: dict[str, set[str]] = {
    "All": {"rule_only", "llm_only", "mixed_track", "unknown"},
    "Rules only": {"rule_only"},
    "AI only": {"llm_only"},
    "Mixed sources": {"mixed_track"},
}


def _provenance_badge(provenance: str) -> str:
    """Return reviewer-facing badge text for a flag's provenance.

    Silent default on rule_only + unknown — eye drawn to exceptions only,
    mirroring Phase 19's ⚠️ weak-pair pattern.
    """
    if provenance == "llm_only":
        return " · 🧠 AI only"
    if provenance == "mixed_track":
        return " · 🔀 Mixed sources"
    return ""


def _rerank_badge(flag: Any) -> str:
    """Return reviewer-facing badge text for a flag's reranker status.

    Reranked + strong score → '🤖 Reranked'.
    Reranked + weak score (LLM ran but still uncertain) → '🤖 Reranked · ⚠️ low score'.
    Not reranked → '' (caller falls back to the legacy ⚠️ weak pair badge).
    """
    if not getattr(flag, "rerank_rationale", None):
        return ""
    if getattr(flag, "pairing_confidence", 1.0) < 0.75:
        return " · 🤖 Reranked · ⚠️ low score"
    return " · 🤖 Reranked"


def _standards_chip(flag: Any) -> str:
    """Return compact standards chip for the flag header.

    Most-cited clause's short form → ' · 📜 <short>'.
    Multiple cites → ' · 📜 <short> +N'.
    Empty list → '' (silent).
    """
    cited = getattr(flag, "cited_clauses", ()) or ()
    if not cited:
        return ""
    first = cited[0]
    short = (first.source_name or "").split("§", 1)[0].strip().rstrip(",")
    if not short:
        short = first.clause_id
    if len(cited) > 1:
        return f" · 📜 {short} +{len(cited) - 1}"
    return f" · 📜 {short}"


def _entity_chip(flag: Any) -> str:
    """Return entity-tag chip text for the flag header.

    Same-tag both sides → ' · 🏷️ <tag>'.
    Different tags → ' · 🏷️ A:<a> / B:<b>' (rare; detector asymmetry).
    Both empty → '' (silent — most flags pre-grounding).
    """
    a_tag = (getattr(flag.a_record, "entity_tag", "") or "").strip()
    b_tag = (getattr(flag.b_record, "entity_tag", "") or "").strip()
    if not a_tag and not b_tag:
        return ""
    if a_tag and b_tag and a_tag == b_tag:
        return f" · 🏷️ {a_tag}"
    if a_tag and b_tag:
        return f" · 🏷️ A:{a_tag} / B:{b_tag}"
    return f" · 🏷️ {a_tag or b_tag}"


# ----------------------------------------------------------------------
# Per-session workdir (PDFs must survive across Streamlit reruns so the
# citation renderer can still find them when the reviewer clicks
# Accept/Dismiss). Cleared on a new upload.
# ----------------------------------------------------------------------


def _ensure_session_workdir() -> Path:
    if "workdir" not in st.session_state or not Path(st.session_state["workdir"]).exists():
        st.session_state["workdir"] = tempfile.mkdtemp(prefix="interlock_")
    return Path(st.session_state["workdir"])


def _reset_workdir() -> None:
    old = st.session_state.get("workdir")
    if old and Path(old).exists():
        shutil.rmtree(old, ignore_errors=True)
    st.session_state["workdir"] = tempfile.mkdtemp(prefix="interlock_")


def _diagnostic_counts(
    pdf_path: str,
    doc_id: str,
    table_max_pages: int,
    enable_vision_ocr: bool = False,
) -> dict[str, int]:
    try:
        result = ingest(
            pdf_path,
            doc_id=doc_id,
            table_max_pages=table_max_pages,
            enable_vision_ocr=enable_vision_ocr,
        )
        params = extract_parameters(result.spans)
        return {
            "spans": len(result.spans),
            "tables": len(result.tables),
            "params": len(params),
            "low_coverage_pages": len(result.low_coverage_pages),
            "ocr_pages": len(result.ocr_pages),
        }
    except Exception:  # pragma: no cover
        return {"spans": 0, "tables": 0, "params": 0, "low_coverage_pages": 0, "ocr_pages": 0}


# ----------------------------------------------------------------------
# Header
# ----------------------------------------------------------------------

st.title("InterLock AI")
st.markdown(
    "**Cross-document discrepancy detection for engineering PDFs.** "
    "Upload two PDFs from the same project — equipment specs, coordination "
    "studies, design revisions — and InterLock surfaces directional, cited, "
    "severity-tiered parameter mismatches for review."
)

# Severity legend at the top — replaces the sidebar "How to read a flag" expander
# so the reviewer sees what the colours mean before any review runs.
st.markdown(
    "<div style='display:flex;gap:12px;flex-wrap:wrap;font-size:0.85em;color:#555;'>"
    f"{_SEVERITY['critical']['emoji']} critical (decimal-shift class)  "
    f"{_SEVERITY['major']['emoji']} major (outside design tolerance)  "
    f"{_SEVERITY['minor']['emoji']} minor (above manufacturing tolerance)  "
    f"{_SEVERITY['info']['emoji']} info (within tolerance — hidden by default)"
    "</div>",
    unsafe_allow_html=True,
)


# ----------------------------------------------------------------------
# Sidebar — three sliders + one toggle. No mode toggle, no cost meter.
# ----------------------------------------------------------------------

with st.sidebar:
    st.header("Review settings")
    st.caption(
        "Ordered by influence on the review run: input handling first, "
        "analysis depth next, display filter last."
    )

    # --- Input handling ---------------------------------------------------

    classify_docs = st.toggle(
        "Doc-class routing",
        value=True,
        help=(
            "When ON, each PDF is classified on upload and per-class "
            "tolerance bands + authority hierarchy apply where defined. "
            "When OFF, the review uses generic defaults. Unknown "
            "classifications fall back to defaults regardless."
        ),
    )

    enable_vision_ocr = st.toggle(
        "Vision OCR for low-coverage pages",
        value=True,
        help=(
            "When a page produces fewer than 80 characters of native text "
            "(scanned image, image-only blueprint), route it through Claude "
            "Sonnet 4.5 vision to recover the text. Diskcached on PDF "
            "content hash, so repeat runs on the same scanned PDF are free. "
            "Toggle off for a fully offline / no-vision run."
        ),
    )

    table_max_pages = st.slider(
        "Camelot table-scan page cap",
        min_value=5,
        max_value=200,
        value=20,
        step=5,
        help=(
            "Camelot table extraction scans this many leading pages per PDF. "
            "Higher = more thorough but slower; the deployed UI feels frozen "
            "above ~100 pages without progress feedback. Increase if your "
            "PDFs put critical tables late."
        ),
    )

    st.divider()

    # --- Analysis depth ---------------------------------------------------

    use_llm_extraction = st.toggle(
        "AI parameter extraction",
        value=True,
        help=(
            "Recovers parameters from prose-heavy documents that pattern "
            "rules miss. Cold cost ~$0.10–$0.30 per 30-page PDF; cached "
            "after first run.\n\n"
            "Toggle off to disable AI extraction."
        ),
    )

    use_entity_grounding = st.toggle(
        "Equipment-aware matching",
        value=True,
        help=(
            "Detects equipment IDs on each page and refuses to pair "
            "values across different physical equipment. Catches "
            "cross-instance false positives. Cold cost ~$0.005 per "
            "page; cached."
        ),
    )

    use_llm_reranker = st.toggle(
        "AI pairing review",
        value=True,
        help=(
            "When automatic matching is uncertain, asks AI to verify each "
            "pair with reasoning. Replaces generic ⚠️ pairing warnings "
            "with explanations. Cold cost ~$0.005 per uncertain pair; "
            "cached."
        ),
    )

    use_llm_judge = st.toggle(
        "AI severity + downstream effects",
        value=True,
        help=(
            "AI rationale per flag + dependent-parameter callouts. Cold "
            "cost ~$0.02–$0.05 per flag; cached.\n\n"
            "Toggle off for rule-only severity."
        ),
    )

    project_id_input = st.text_input(
        "Project ID (optional)",
        value="",
        placeholder="e.g. AES-PALM-2025",
        help=(
            "If your project has its own tolerance overrides at "
            "fixtures/projects/<id>/tolerances.yaml, enter the ID here. "
            "Leave blank to use the global standards registry only."
        ),
    )
    # Normalize empty string → None for the pipeline.
    project_id = project_id_input.strip() or None

    st.divider()

    # --- Display filter ---------------------------------------------------

    threshold = st.slider(
        "Suppress flags below this confidence",
        min_value=0.0,
        max_value=1.0,
        value=0.6,
        step=0.05,
        help=(
            "Confidence is **extraction × (match × pairing) × authority**, "
            "clamped to [0, 1]. A weak pairing automatically pulls overall "
            "confidence down. Flags below the threshold stay accessible in "
            "the **Suppressed** expander on the results page."
        ),
    )

    st.divider()

    # --- v2 Sprint 3: provenance filter ---------------------------------

    track_filter = st.radio(
        "Filter by source",
        options=("All", "Rules only", "AI only", "Mixed sources"),
        index=0,
        help=(
            "Narrow the visible flag list by which source(s) contributed. "
            "Both rule-based and AI extraction run when their toggles are "
            "on above — this filter only changes what you SEE, not "
            "what gets computed."
        ),
    )
    st.caption(
        "⚙ Rules only · 🧠 AI only · 🔀 Mixed sources"
    )

    st.divider()
    with st.expander("How to read a flag", expanded=False):
        st.markdown(
            "- **Severity** comes from per-attribute tolerance bands sourced "
            "from public standards (IEEE C57, IEC 60076, NEMA TR 1, "
            "IEEE Std 242). Within-tolerance changes classify as `info` and "
            "are hidden by default.\n"
            "- **Confidence** = `extraction × (match × pairing) × authority`, "
            "clamped to [0, 1]. The three sub-scores answer three different "
            "questions: how sure about the values, how sure about the "
            "pairing (are these the same physical record?), and how sure "
            "about the authority direction.\n"
            "- **Pairing confidence** is surfaced separately on each flag. "
            "Pairs below 0.75 get a `⚠️ weak pair` badge and are collapsed "
            "by default — verify the correspondence before treating the gap "
            "as a fact.\n"
            "- **Authority direction** — Doc A is treated as the source-of-"
            "truth side; Doc B is the deviation candidate. Per-project "
            "configurable authority is on the roadmap (see BACKLOG R-G).\n"
            "- **Citation** is a bounding-box snippet of the source page so "
            "you can verify the finding without alt-tabbing.\n"
            "- **Unpaired records** (separate expander after the flag list) "
            "are records the aligner declined to pair across documents. "
            "Review them so silent gaps aren't mistaken for clean runs.\n"
            "- **Accept / Dismiss** records your verdict for the JSON audit "
            "export at the bottom of the page."
        )


# ----------------------------------------------------------------------
# Uploaders
# ----------------------------------------------------------------------

col_a, col_b = st.columns(2)
with col_a:
    a_file = st.file_uploader(
        "Doc A (source of truth — e.g. equipment spec or 60 % baseline)",
        type="pdf",
        key="a",
    )
with col_b:
    b_file = st.file_uploader(
        "Doc B (deviation candidate — e.g. coordination study or 90 % revision)",
        type="pdf",
        key="b",
    )


# ----------------------------------------------------------------------
# Run
# ----------------------------------------------------------------------


def _flag_id(flag: Any) -> str:
    """Unique key per flag for Streamlit widget IDs.

    Just (parameter, page, y0) is not unique — a doc with several spans of
    the same name on the same page at near-zero y produces colliding keys
    (StreamlitDuplicateElementKey). Include both records' bboxes + raw values
    to guarantee uniqueness across the surfaced flag set.
    """
    a = flag.a_record
    b = flag.b_record
    return (
        f"{flag.parameter}"
        f"|a:p{a.page}y{int(a.bbox[1])}x{int(a.bbox[0])}:{a.raw_value}"
        f"|b:p{b.page}y{int(b.bbox[1])}x{int(b.bbox[0])}:{b.raw_value}"
    )


def _is_ocr_span(record: Any) -> bool:
    """A vision-OCR span has its bbox set to the full page rectangle
    (x0=0 at the bottom-left). Used to render a different snippet style."""
    return bool(record.bbox[0] == 0 and record.bbox[1] == 0)


def _whole_page_note(record: Any) -> str:
    """Return the right reviewer-facing note when a record's bbox is
    whole-page-at-origin. Distinguishes vision-OCR records from Sprint 2
    LLM-extracted records (both end up with bbox starting at (0,0))."""
    if not _is_ocr_span(record):
        return ""
    if getattr(record, "provenance", "regex") == "llm":
        return (
            " · 🤖 AI extraction (whole-page snippet — text-only LLM "
            "has no per-record bbox)"
        )
    return " · 🔍 OCR (whole-page snippet — vision model has no per-word bbox)"


def _locate_raw_value(text: str, raw: str) -> tuple[int, int]:
    """Return ``(start, end)`` of raw_value within text, or ``(-1, -1)``.

    raw_value is built as ``f"{token} {unit}"`` (e.g. ``"5.75 %"``) but the
    surface form in PDFs often elides the space (``"5.75%Z"``). We try:

      1. exact (case-insensitive)
      2. whitespace-flexible regex (``5\\.75\\s*%``)
      3. leading numeric token alone (``5.75``)

    Each tier locates the actual offset and length in the original text so
    the excerpt window centers on what the reviewer is looking for.
    """
    if not raw:
        return -1, -1
    idx = text.find(raw)
    if idx >= 0:
        return idx, idx + len(raw)
    idx = text.lower().find(raw.lower())
    if idx >= 0:
        return idx, idx + len(raw)
    # Whitespace-flexible: each \s+ in raw becomes \s* in the search.
    parts = [re.escape(p) for p in re.split(r"\s+", raw) if p]
    if parts:
        m = re.search(r"\s*".join(parts), text, re.IGNORECASE)
        if m is not None:
            return m.start(), m.end()
    # Numeric token alone — catches "5.75" inside "5.75%Z".
    nm = re.search(r"\d[\d,]*\.?\d*", raw)
    if nm is not None:
        tm = re.search(re.escape(nm.group(0)), text)
        if tm is not None:
            return tm.start(), tm.end()
    return -1, -1


def _span_excerpt(record: Any, context_chars: int = 120) -> str:
    """Return the chunk of span_text around the record's raw_value.

    Native spans hold one logical line already; the excerpt collapses to
    the span_text itself. Vision-OCR spans hold whole-page text — we
    locate the raw_value within and return ±context_chars around it with
    ellipses so the reviewer sees the relevant fragment instead of the
    entire page transcription.
    """
    text = record.span_text or ""
    raw = (record.raw_value or "").strip()
    if not raw or len(text) <= 300:
        return text
    start_idx, end_idx = _locate_raw_value(text, raw)
    if start_idx < 0:
        # Fallback: first chunk only — at least bound the visible payload.
        return text[: 2 * context_chars] + (" …" if len(text) > 2 * context_chars else "")
    start = max(0, start_idx - context_chars)
    end = min(len(text), end_idx + context_chars)
    prefix = "… " if start > 0 else ""
    suffix = " …" if end < len(text) else ""
    return f"{prefix}{text[start:end]}{suffix}"


run = bool(a_file is not None and b_file is not None and st.button("Run review", type="primary"))

if run:
    _reset_workdir()
    workdir = _ensure_session_workdir()
    # Preserve original uploaded filenames so the citation panel shows
    # "spec_xfmr_001.pdf" instead of a generic "doc_a.pdf". Use Path().name
    # to strip any directory traversal in the upload metadata. Fall back to
    # generic names if Streamlit somehow didn't surface a usable filename.
    a_name = Path(getattr(a_file, "name", "") or "doc_a.pdf").name or "doc_a.pdf"
    b_name = Path(getattr(b_file, "name", "") or "doc_b.pdf").name or "doc_b.pdf"
    # Same-name collision guard (user uploads two files called "design.pdf")
    if a_name == b_name:
        b_name = f"b_{b_name}"
    a_path = workdir / a_name
    b_path = workdir / b_name
    a_path.write_bytes(a_file.read())  # type: ignore[union-attr]
    b_path.write_bytes(b_file.read())  # type: ignore[union-attr]

    # Each stage gets its own placeholder so the row's icon/elapsed time
    # can update independently as the pipeline progresses. Without per-row
    # placeholders, st.status writes accumulate top-to-bottom and you can
    # only ever see "running" or "done" for the whole block, not each step.
    _STAGE_LABELS: dict[str, str] = {
        "ingest_a": "Reading Doc A (text spans + tables)",
        "ingest_b": "Reading Doc B (text spans + tables)",
        "classify": "Classifying document types (AI)",
        "extract": "Extracting parameters",
        "llm_extract_a": "AI parameter extraction — Doc A",
        "llm_extract_b": "AI parameter extraction — Doc B",
        "entity_detect": "Detecting equipment IDs (AI)",
        "align": "Matching parameters across documents",
        "rerank": "Reviewing ambiguous pairs with AI",
        "detect": "Detecting mismatches",
        "judge": "AI severity + standards citations",
    }
    _STAGE_ORDER: list[str] = ["ingest_a", "ingest_b", "extract"]
    if use_entity_grounding:
        _STAGE_ORDER.append("entity_detect")
    _STAGE_ORDER.append("align")
    if use_llm_reranker:
        _STAGE_ORDER.append("rerank")
    _STAGE_ORDER.append("detect")
    if use_llm_judge:
        _STAGE_ORDER.append("judge")

    t0 = time.time()
    try:
        with st.status("Reviewing PDFs…", expanded=True) as status:
            status.write(
                f"ℹ️ Camelot scans the first {table_max_pages} pages per PDF. "
                "Adjust via the sidebar slider if relevant tables sit deeper."
            )
            stage_placeholders: dict[str, Any] = {
                sid: status.empty() for sid in _STAGE_ORDER
            }
            for sid in _STAGE_ORDER:
                stage_placeholders[sid].markdown(f"⏸️ {_STAGE_LABELS[sid]}")

            stage_starts: dict[str, float] = {}
            ocr_bar_holder: dict[str, Any] = {}

            def _stage_cb(stage_id: str, state: str) -> None:
                ph = stage_placeholders.get(stage_id)
                if ph is None:
                    return
                label = _STAGE_LABELS[stage_id]
                if state == "start":
                    stage_starts[stage_id] = time.time()
                    ph.markdown(f"⏳ **{label}…**")
                elif state == "done":
                    dt = time.time() - stage_starts.get(stage_id, time.time())
                    ph.markdown(f"✅ {label} · {dt:.1f}s")

            def _ocr_cb(done: int, total: int, page: int) -> None:
                # Lazy-create OCR row + bar so it never appears when no
                # low-coverage pages need vision fallback.
                if "bar" not in ocr_bar_holder:
                    ocr_bar_holder["label"] = status.empty()
                    ocr_bar_holder["label"].markdown(
                        "⏳ **Vision OCR on low-coverage pages "
                        "(Claude Sonnet 4.5, parallel × 5, cached)**"
                    )
                    ocr_bar_holder["bar"] = st.progress(0.0, text="OCR: starting…")
                    ocr_bar_holder["start"] = time.time()
                ratio = done / max(total, 1)
                ocr_bar_holder["bar"].progress(
                    min(ratio, 1.0),
                    text=f"OCR: {done}/{total} pages complete (last: page {page})",
                )
                if done >= total:
                    dt = time.time() - ocr_bar_holder["start"]
                    ocr_bar_holder["label"].markdown(
                        f"✅ Vision OCR on low-coverage pages · {total} page(s) · {dt:.1f}s"
                    )

            review_result = review_two_documents_full(
                str(a_path),
                str(b_path),
                embed_fn=embed_voyage,
                same_page_only=False,  # Cross-page alignment always — auto-detect heuristic obsolete in v1.5
                use_llm_judge=use_llm_judge,
                table_max_pages=table_max_pages,
                enable_vision_ocr=enable_vision_ocr,
                ocr_progress_cb=_ocr_cb if enable_vision_ocr else None,
                stage_cb=_stage_cb,
                classify_docs=classify_docs,
                use_llm_extraction=use_llm_extraction,
                use_llm_reranker=use_llm_reranker,
                use_entity_grounding=use_entity_grounding,
                project_id=project_id,
            )
            flags = review_result.flags
            status.update(
                label=f"Review complete in {time.time() - t0:.1f}s",
                state="complete",
                expanded=False,
            )
    except Exception as e:
        st.error(
            f"Review failed: {type(e).__name__}: {e}\n\n"
            "Common causes: missing `VOYAGE_API_KEY`, malformed PDF, or "
            "Voyage / Anthropic rate-limit. Check your environment variables "
            "and try again."
        )
        st.stop()
    elapsed = time.time() - t0

    st.session_state["flags"] = flags
    st.session_state["unpaired_a"] = review_result.unpaired_a
    st.session_state["unpaired_b"] = review_result.unpaired_b
    st.session_state["doc_class_a"] = review_result.doc_class_a
    st.session_state["doc_class_b"] = review_result.doc_class_b
    st.session_state["a_path"] = str(a_path)
    st.session_state["b_path"] = str(b_path)
    st.session_state["elapsed"] = elapsed
    st.session_state["use_llm_judge_at_run"] = use_llm_judge
    st.session_state["table_max_pages_at_run"] = table_max_pages
    st.session_state["decisions"] = {}
    # Note: diagnostic counts call ingest a second time with the same OCR
    # setting. Vision results are diskcache-keyed by (text/image hash); the
    # second pass costs ~0 if the first pass succeeded.
    st.session_state["diag_a"] = _diagnostic_counts(
        str(a_path), "doc_a", table_max_pages, enable_vision_ocr
    )
    st.session_state["diag_b"] = _diagnostic_counts(
        str(b_path), "doc_b", table_max_pages, enable_vision_ocr
    )


# ----------------------------------------------------------------------
# Results
# ----------------------------------------------------------------------


def _flag_sort_key(f: Any) -> tuple[int, float]:
    sev = getattr(f, "severity", "major")
    return (_SEVERITY_ORDER.get(sev, 1), -f.confidence)


def _severity_chip(sev: str) -> str:
    style = _SEVERITY.get(sev, _SEVERITY["major"])
    return (
        f"<span style='background:{style['bg']};color:#222;"
        f"border:1px solid {style['border']};border-radius:4px;"
        f"padding:2px 8px;font-weight:600;font-size:0.85em;'>"
        f"{style['emoji']} {style['label']}</span>"
    )


flags = st.session_state.get("flags", [])
if flags:
    elapsed = st.session_state.get("elapsed", 0.0)
    # v2 Sprint 3: apply track filter as well as confidence threshold.
    _allowed_prov = _TRACK_FILTER_MAP.get(track_filter, _TRACK_FILTER_MAP["All"])
    above = [
        f for f in flags
        if f.confidence >= threshold
        and getattr(f, "provenance", "unknown") in _allowed_prov
    ]
    below = [
        f for f in flags
        if f.confidence < threshold
        and getattr(f, "provenance", "unknown") in _allowed_prov
    ]

    # v2 Sprint 1: doc-class banner above metrics row. Shows what the
    # classifier returned per doc and which severity bands / authority
    # hierarchy are in effect for this review.
    _dc_a = st.session_state.get("doc_class_a")
    _dc_b = st.session_state.get("doc_class_b")
    if _dc_a is not None and _dc_b is not None:
        _bcol_a, _bcol_b = st.columns(2)

        def _doc_class_banner(col: Any, label: str, dc: Any) -> None:
            with col:
                conf = dc.confidence
                if conf >= 0.85:
                    box_fn = st.success
                elif conf >= 0.60:
                    box_fn = st.info
                else:
                    box_fn = st.warning
                pretty = dc.doc_class.value.replace("_", " ").title()
                box_fn(
                    f"📄 **{label}: {pretty}** ({conf:.2f})\n\n"
                    f"_{dc.reasoning}_"
                )

        _doc_class_banner(_bcol_a, "Doc A", _dc_a)
        _doc_class_banner(_bcol_b, "Doc B", _dc_b)
        _inds_a = list(_dc_a.detected_indicators) if _dc_a.detected_indicators else []
        _inds_b = list(_dc_b.detected_indicators) if _dc_b.detected_indicators else []
        if _inds_a or _inds_b:
            with st.expander(
                f"Why these classifications? "
                f"({len(_inds_a) + len(_inds_b)} indicators)",
                expanded=False,
            ):
                if _inds_a:
                    st.markdown("**Doc A indicators:**")
                    for ind in _inds_a:
                        st.markdown(f"- {ind}")
                if _inds_b:
                    st.markdown("**Doc B indicators:**")
                    for ind in _inds_b:
                        st.markdown(f"- {ind}")

    sev_counts: dict[str, int] = {}
    for f in above:
        s = getattr(f, "severity", "major")
        sev_counts[s] = sev_counts.get(s, 0) + 1

    unpaired_a_count = len(st.session_state.get("unpaired_a", []))
    unpaired_b_count = len(st.session_state.get("unpaired_b", []))
    unpaired_total = unpaired_a_count + unpaired_b_count

    cols = st.columns([2, 1, 1, 1, 1, 1])
    cols[0].metric("Time", f"{elapsed:.1f} s")
    cols[1].metric("Surfaced", f"{len(above)}")
    cols[2].metric("🔴 Critical", f"{sev_counts.get('critical', 0)}")
    cols[3].metric("🟠 Major", f"{sev_counts.get('major', 0)}")
    cols[4].metric("🟡 Minor", f"{sev_counts.get('minor', 0)}")
    cols[5].metric(
        "📋 Unpaired",
        f"{unpaired_total}",
        help=(
            f"{unpaired_a_count} records in Doc A and {unpaired_b_count} in "
            "Doc B had no confident counterpart and were NOT compared. "
            "Listed in the 'Unpaired records' expander below."
        ),
    )

    judge_caption = (
        "AI severity + downstream effects"
        if st.session_state.get("use_llm_judge_at_run")
        else "Rule-only severity"
    )
    st.caption(judge_caption)

    diag_a = st.session_state.get("diag_a", {})
    diag_b = st.session_state.get("diag_b", {})
    a_p = diag_a.get("params", 0)
    b_p = diag_b.get("params", 0)

    if not above:
        # Surface a diagnosis whenever NOTHING reached the reviewer above
        # the suppression threshold — distinct from "nothing classified at
        # all," which is the all-empty case.
        if not below:
            if a_p == 0 and b_p == 0:
                st.warning(
                    "**No common ground between these two documents.**  \n"
                    "Neither PDF yielded engineering parameters that the "
                    "system could extract. The two files look unrelated, or "
                    "they are prose-heavy / meta-instructional documents "
                    "(parameters embedded in sentences rather than "
                    "`Label: value` rows), or both pages were scanned images."
                )
            elif a_p == 0 or b_p == 0:
                empty_side = "A" if a_p == 0 else "B"
                other = "B" if empty_side == "A" else "A"
                st.warning(
                    f"**Only Doc {other} yielded extractable parameters.**  \n"
                    f"Doc {empty_side} produced 0 parameters; Doc {other} "
                    f"produced {max(a_p, b_p)}. Without parameters on both "
                    f"sides, no cross-document pairs can form. Doc "
                    f"{empty_side} is likely prose-heavy, a meta / "
                    "instructional document, or scanned."
                )
            else:
                st.info(
                    "**Documents extracted parameters but nothing aligned "
                    "to a mismatch.**  \n"
                    f"Doc A produced {a_p} parameters, Doc B produced {b_p}. "
                    "Either the parameters named in each don't overlap, "
                    "every overlapping value is unit-equivalent (e.g. "
                    "`150 kVA` vs `0.15 MVA`), or every numeric difference "
                    "falls within the configured tolerance bands."
                )
        else:
            st.info(
                f"**All {len(below)} flag(s) sit below the {threshold:.2f} "
                "suppression threshold.**  \n"
                "The pipeline classified candidate mismatches but none "
                "cleared the confidence bar. Drop the threshold slider in "
                "the sidebar to surface them, or open the **Suppressed** "
                "expander below."
            )

    # Diagnostic panel is now always available — useful for confidence-
    # building on successful runs too, not only on empty results.
    with st.expander("Diagnostic counts (per-doc extraction stats)", expanded=False):
        col1, col2 = st.columns(2)
        with col1:
            st.markdown("**Doc A**")
            st.caption(
                f"spans: {diag_a.get('spans', 0)} · "
                f"tables: {diag_a.get('tables', 0)} · "
                f"**extractable params: {a_p}** · "
                f"low-coverage pages: {diag_a.get('low_coverage_pages', 0)} · "
                f"OCR pages: {diag_a.get('ocr_pages', 0)}"
            )
        with col2:
            st.markdown("**Doc B**")
            st.caption(
                f"spans: {diag_b.get('spans', 0)} · "
                f"tables: {diag_b.get('tables', 0)} · "
                f"**extractable params: {b_p}** · "
                f"low-coverage pages: {diag_b.get('low_coverage_pages', 0)} · "
                f"OCR pages: {diag_b.get('ocr_pages', 0)}"
            )

    for f in sorted(above, key=_flag_sort_key):
        fid = _flag_id(f)
        verdict = st.session_state["decisions"].get(fid, {}).get("verdict")
        sev = getattr(f, "severity", "major")
        deviation = getattr(f, "deviation_pct", 0.0)
        dev_str = f"Δ {deviation:.1f}%" if deviation else "string change"
        attr_family = getattr(f, "attribute_family", None) or "—"

        verdict_badge = ""
        if verdict == "accepted":
            verdict_badge = " · ✅ Accepted"
        elif verdict == "dismissed":
            verdict_badge = " · ✖️ Dismissed"

        pairing_conf = getattr(f, "pairing_confidence", 1.0)
        weak_pair = pairing_conf < 0.75
        # v2 Sprint 4: rerank badge overrides the legacy weak-pair badge
        # when the reranker has spoken on this pair.
        rerank_b = _rerank_badge(f)
        pair_badge = rerank_b if rerank_b else (" · ⚠️ weak pair" if weak_pair else "")
        # v2 Sprint 3: silent on rule_only, prominent on llm_only / mixed_track
        prov_badge = _provenance_badge(getattr(f, "provenance", "unknown"))
        # v2 Sprint 4.5: equipment-binding chip; silent when both sides untagged
        ent_chip = _entity_chip(f)
        # v2 Sprint 5a: cited standards chip; silent when no citations
        std_chip = _standards_chip(f)
        header = (
            f"{_SEVERITY[sev]['emoji']} **{f.parameter}** · "
            f"{dev_str} · confidence {f.confidence:.2f}"
            f"{pair_badge}{prov_badge}{ent_chip}{std_chip}{verdict_badge}"
        )

        with st.expander(
            header,
            expanded=verdict is None and sev in {"critical", "major"} and not weak_pair,
        ):
            st.markdown(_severity_chip(sev), unsafe_allow_html=True)
            st.markdown(f"**Rationale:** {f.rationale}")
            cap = (
                f"Attribute family: `{attr_family}` · "
                f"pairing confidence {pairing_conf:.2f} · "
                f"Doc A treated as source of truth"
            )
            if weak_pair:
                cap += (
                    " · ⚠️ pairing is uncertain (no Device ID match; "
                    "value-equality or low-similarity fallback) — verify "
                    "these two records describe the same physical device "
                    "before acting"
                )
            # v2 Sprint 3: per-flag track detail (silent on rule_only/unknown)
            prov = getattr(f, "provenance", "unknown")
            if prov == "llm_only":
                cap += " · Both sides found by AI"
            elif prov == "mixed_track":
                a_prov_human = "Rules" if f.a_record.provenance == "regex" else "AI"
                b_prov_human = "Rules" if f.b_record.provenance == "regex" else "AI"
                cap += (
                    f" · Mixed sources — Doc A: {a_prov_human} · "
                    f"Doc B: {b_prov_human}. Verify these two records "
                    f"describe the same physical parameter."
                )
            st.caption(cap)

            # v2 Sprint 4: surface reranker rationale prominently when present.
            if getattr(f, "rerank_rationale", None):
                st.info(f"🤖 **Reranker:** {f.rerank_rationale}")

            # v2 Sprint 4.5: per-flag equipment binding line (silent both empty)
            _a_tag = (getattr(f.a_record, "entity_tag", "") or "").strip()
            _b_tag = (getattr(f.b_record, "entity_tag", "") or "").strip()
            if _a_tag or _b_tag:
                st.caption(
                    f"🏷️ Equipment binding — Doc A: `{_a_tag or '—'}` · "
                    f"Doc B: `{_b_tag or '—'}`"
                )

            # v2 Sprint 5a: full list of cited standards.
            _cited = getattr(f, "cited_clauses", ()) or ()
            if _cited:
                st.markdown("**📜 Cited standards:**")
                for c in _cited:
                    st.markdown(
                        f"- **{c.source_name}** ({c.edition_year})  \n"
                        f"  _{c.summary}_"
                    )

            cit_a = None
            cit_b = None
            err_a = err_b = None
            try:
                cit_a = render_citation(f.a_record)
            except Exception as e:  # pragma: no cover
                err_a = f"{type(e).__name__}: {e}"
            try:
                cit_b = render_citation(f.b_record)
            except Exception as e:  # pragma: no cover
                err_b = f"{type(e).__name__}: {e}"
            if err_a or err_b:
                st.warning(
                    "Citation snippet rendering failed — re-run the review:\n"
                    f"- Doc A: {err_a or 'ok'}\n- Doc B: {err_b or 'ok'}"
                )

            ca, cb = st.columns(2)
            with ca:
                # Prefer source_path (real filename, e.g. "spec_xfmr_001.pdf")
                # over doc_id (logical label, e.g. "doc_a") so the reviewer
                # sees what they uploaded, not the internal handle.
                doc_label = (
                    Path(f.a_record.source_path).name
                    if f.a_record.source_path
                    else Path(f.a_record.doc_id).name
                ) or "doc_a"
                ocr_note_a = _whole_page_note(f.a_record)
                st.markdown(
                    f"**Doc A (source of truth)**  \n"
                    f"`{doc_label}` · page {f.a_record.page} · "
                    f"section: {f.a_record.section or '—'}{ocr_note_a}"
                )
                if cit_a is not None:
                    # Smaller display width for whole-page OCR snippets so the
                    # column doesn't dwarf the narrow-span deviation side.
                    if _is_ocr_span(f.a_record):
                        st.image(cit_a.snippet_png, width=320)
                    else:
                        st.image(cit_a.snippet_png)
                st.code(_span_excerpt(f.a_record), language="text")
            with cb:
                doc_label = (
                    Path(f.b_record.source_path).name
                    if f.b_record.source_path
                    else Path(f.b_record.doc_id).name
                ) or "doc_b"
                ocr_note_b = _whole_page_note(f.b_record)
                st.markdown(
                    f"**Doc B (deviation candidate)**  \n"
                    f"`{doc_label}` · page {f.b_record.page} · "
                    f"section: {f.b_record.section or '—'}{ocr_note_b}"
                )
                if cit_b is not None:
                    if _is_ocr_span(f.b_record):
                        st.image(cit_b.snippet_png, width=320)
                    else:
                        st.image(cit_b.snippet_png)
                st.code(_span_excerpt(f.b_record), language="text")

            b_accept, b_dismiss, _spacer = st.columns([1, 1, 4])
            with b_accept:
                if st.button("✅ Accept", key=f"acc-{fid}", use_container_width=True):
                    st.session_state["decisions"][fid] = {
                        "verdict": "accepted",
                        "parameter": f.parameter,
                        "severity": sev,
                        "deviation_pct": deviation,
                        "confidence": f.confidence,
                        "rationale": f.rationale,
                        "attribute_family": attr_family,
                        "authority_rule": f.authority_rule,
                        "doc_a_page": f.a_record.page,
                        "doc_b_page": f.b_record.page,
                        "doc_a_value": f.a_record.raw_value,
                        "doc_b_value": f.b_record.raw_value,
                        "provenance": getattr(f, "provenance", "unknown"),  # v2 Sprint 3
                        "rerank_rationale": getattr(f, "rerank_rationale", None),  # v2 Sprint 4
                        "entity_a": (getattr(f.a_record, "entity_tag", "") or None),  # v2 Sprint 4.5
                        "entity_b": (getattr(f.b_record, "entity_tag", "") or None),  # v2 Sprint 4.5
                        "cited_clauses": [  # v2 Sprint 5a
                            {
                                "clause_id": c.clause_id,
                                "edition_year": c.edition_year,
                                "source_name": c.source_name,
                                "summary": c.summary,
                            }
                            for c in (getattr(f, "cited_clauses", ()) or ())
                        ],
                    }
                    st.rerun()
            with b_dismiss:
                if st.button("✖ Dismiss", key=f"dis-{fid}", use_container_width=True):
                    st.session_state["decisions"][fid] = {"verdict": "dismissed"}
                    st.rerun()

    if below:
        with st.expander(
            f"{len(below)} suppressed flag(s) below confidence threshold",
            expanded=False,
        ):
            st.caption(
                "These flags were classified but their confidence is below "
                f"the {threshold:.2f} suppression threshold. Lower the "
                "threshold in the sidebar to surface them."
            )
            for f in sorted(below, key=_flag_sort_key):
                sev = getattr(f, "severity", "major")
                st.markdown(
                    f"{_SEVERITY[sev]['emoji']} **[{f.confidence:.2f}]** "
                    f"`{f.parameter}` · {f.rationale}"
                )

    unpaired_a = st.session_state.get("unpaired_a", [])
    unpaired_b = st.session_state.get("unpaired_b", [])
    if unpaired_a or unpaired_b:
        with st.expander(
            f"📋 Unpaired records — {len(unpaired_a)} in Doc A, "
            f"{len(unpaired_b)} in Doc B (not compared)",
            expanded=False,
        ):
            st.caption(
                "These parameter records had no confident counterpart in the "
                "other document and were NOT compared. Common reasons: "
                "different Device ID (table row), present in one doc but "
                "absent from the other, or OCR ambiguity prevented a safe "
                "pairing. Review manually to confirm none represent a real "
                "deletion or specification gap."
            )

            def _render_unpaired_column(
                records: list[Any],
                doc_label_prefix: str,
            ) -> None:
                # Group by parameter name so a 49-row list (Option 2 Doc B)
                # collapses into ~5 family buckets the reviewer can scan.
                by_family: dict[str, list[Any]] = {}
                for r in records:
                    by_family.setdefault(r.name, []).append(r)
                st.markdown(f"**{doc_label_prefix} — {len(records)} unpaired**")
                if not records:
                    st.caption("_(none)_")
                    return
                # Largest buckets first so reviewer sees the dominant gap.
                for family, items in sorted(
                    by_family.items(), key=lambda kv: (-len(kv[1]), kv[0])
                ):
                    label = (
                        f"**{family}** · {len(items)} record(s)"
                        if len(items) > 1
                        else f"**{family}**"
                    )
                    # Expand by default only for small buckets so the
                    # reviewer isn't drowning in fuse rows.
                    with st.expander(label, expanded=len(items) <= 3):
                        for r in sorted(
                            items, key=lambda x: (x.page, x.raw_value)
                        ):
                            tag = f"`#{r.entity_tag}` " if r.entity_tag else ""
                            st.markdown(
                                f"- p{r.page} · {tag}`{r.raw_value}`"
                            )

            up_a, up_b = st.columns(2)
            with up_a:
                _render_unpaired_column(unpaired_a, "Doc A")
            with up_b:
                _render_unpaired_column(unpaired_b, "Doc B")

    accepted = [
        d for d in st.session_state["decisions"].values() if d.get("verdict") == "accepted"
    ]
    if accepted:
        st.divider()
        st.download_button(
            "📥 Export accepted flags (JSON)",
            data=json.dumps(accepted, indent=2),
            file_name="interlock_accepted_flags.json",
            mime="application/json",
            type="primary",
        )

elif not run:
    st.info(
        "Upload two PDFs and click **Run review** to begin. "
        "Demo fixtures live in `fixtures/pdfs/` of the source repo."
    )
