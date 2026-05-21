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
from interlock.pipeline import review_two_documents  # noqa: E402


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

    st.markdown("**Suppress flags below**")
    threshold = st.slider(
        "Suppress flags below this confidence",
        min_value=0.0,
        max_value=1.0,
        value=0.6,
        step=0.05,
        label_visibility="collapsed",
        help=(
            "Confidence is extraction × match × authority, in [0, 1]. Flags "
            "below this score stay accessible in the 'Suppressed' expander."
        ),
    )

    st.markdown("**AI-judged severity**")
    use_llm_judge = st.toggle(
        "AI rationale + downstream-effect propagation (on by default)",
        value=True,
        help=(
            "Each surfaced flag is sent to Claude Opus 4.7 with a cached "
            "engineering ontology, returning a written rationale and a list "
            "of downstream parameters that may be affected. Disk-cached, so "
            "repeat runs cost nothing.\n\n"
            "Toggle off for a fully deterministic, rule-only severity path."
        ),
    )

    st.markdown("**Table-scan page cap**")
    table_max_pages = st.slider(
        "Camelot scans this many leading pages per PDF",
        min_value=5,
        max_value=200,
        value=20,
        step=5,
        label_visibility="collapsed",
        help=(
            "Camelot table extraction scans this many pages from the start "
            "of each PDF. Higher = more thorough but slower; the deployed UI "
            "feels frozen above ~100 pages without progress feedback. "
            "Increase if your PDFs put critical tables late."
        ),
    )

    st.markdown("**OCR on scanned pages**")
    enable_vision_ocr = st.toggle(
        "Vision OCR for low-coverage pages (Claude Sonnet 4.5)",
        value=True,
        help=(
            "When a page produces fewer than 80 characters of native text "
            "(scanned image, image-only blueprint), route it through Claude's "
            "vision model to recover the text. Cached after first call. "
            "Toggle off for a fully offline / no-vision run."
        ),
    )

    st.divider()
    with st.expander("How to read a flag", expanded=False):
        st.markdown(
            "- **Severity** comes from per-attribute tolerance bands sourced "
            "from public standards (IEEE C57, IEC 60076, NEMA TR 1, "
            "IEEE Std 242). Within-tolerance changes classify as `info` and "
            "are hidden by default.\n"
            "- **Confidence** = extraction × match × authority, in [0, 1].\n"
            "- **Authority direction** — Doc A is treated as the source-of-"
            "truth side; Doc B is the deviation candidate. Per-project "
            "configurable authority is on the roadmap.\n"
            "- **Citation** is a bounding-box snippet of the source page so "
            "you can verify the finding without alt-tabbing.\n"
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
    a_path = workdir / "doc_a.pdf"
    b_path = workdir / "doc_b.pdf"
    a_path.write_bytes(a_file.read())  # type: ignore[union-attr]
    b_path.write_bytes(b_file.read())  # type: ignore[union-attr]

    # Each stage gets its own placeholder so the row's icon/elapsed time
    # can update independently as the pipeline progresses. Without per-row
    # placeholders, st.status writes accumulate top-to-bottom and you can
    # only ever see "running" or "done" for the whole block, not each step.
    _STAGE_LABELS: dict[str, str] = {
        "ingest_a": "Ingesting Doc A (PyMuPDF spans + Camelot tables)",
        "ingest_b": "Ingesting Doc B (PyMuPDF spans + Camelot tables)",
        "extract": "Extracting parameters (regex patterns + Pint unit normalisation)",
        "align": "Aligning across documents (exact name + canonical glossary + Voyage embeddings)",
        "detect": "Detecting mismatches + classifying severity (IEEE / IEC tolerance bands)",
        "judge": "LLM significance judgement (Claude, cached per flag)",
    }
    _STAGE_ORDER: list[str] = ["ingest_a", "ingest_b", "extract", "align", "detect"]
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

            flags = review_two_documents(
                str(a_path),
                str(b_path),
                embed_fn=embed_voyage,
                same_page_only=False,  # Cross-page alignment always — auto-detect heuristic obsolete in v1.5
                use_llm_judge=use_llm_judge,
                table_max_pages=table_max_pages,
                enable_vision_ocr=enable_vision_ocr,
                ocr_progress_cb=_ocr_cb if enable_vision_ocr else None,
                stage_cb=_stage_cb,
            )
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
    above = [f for f in flags if f.confidence >= threshold]
    below = [f for f in flags if f.confidence < threshold]

    sev_counts: dict[str, int] = {}
    for f in above:
        s = getattr(f, "severity", "major")
        sev_counts[s] = sev_counts.get(s, 0) + 1

    cols = st.columns([2, 1, 1, 1, 1])
    cols[0].metric("Time", f"{elapsed:.1f} s")
    cols[1].metric("Surfaced", f"{len(above)}")
    cols[2].metric("🔴 Critical", f"{sev_counts.get('critical', 0)}")
    cols[3].metric("🟠 Major", f"{sev_counts.get('major', 0)}")
    cols[4].metric("🟡 Minor", f"{sev_counts.get('minor', 0)}")

    judge_caption = (
        "AI-judged severity + downstream effects"
        if st.session_state.get("use_llm_judge_at_run")
        else "Rule-based severity (deterministic mode)"
    )
    st.caption(judge_caption)

    if not above and not below:
        diag_a = st.session_state.get("diag_a", {})
        diag_b = st.session_state.get("diag_b", {})
        a_p = diag_a.get("params", 0)
        b_p = diag_b.get("params", 0)
        if a_p == 0 and b_p == 0:
            st.warning(
                "**No common ground between these two documents.**  \n"
                "Neither PDF yielded engineering parameters that the system "
                "could extract. The two files look unrelated, or they are "
                "prose-heavy / meta-instructional documents (parameters "
                "embedded in sentences rather than `Label: value` rows), "
                "or both pages were scanned images."
            )
        elif a_p == 0 or b_p == 0:
            empty_side = "A" if a_p == 0 else "B"
            other = "B" if empty_side == "A" else "A"
            st.warning(
                f"**Only Doc {other} yielded extractable parameters.**  \n"
                f"Doc {empty_side} produced 0 parameters; Doc {other} produced "
                f"{max(a_p, b_p)}. Without parameters on both sides, no "
                f"cross-document pairs can form. Doc {empty_side} is likely "
                "prose-heavy, a meta / instructional document, or scanned."
            )
        else:
            st.info(
                "**Documents extracted parameters but nothing aligned to a "
                "mismatch.**  \n"
                f"Doc A produced {a_p} parameters, Doc B produced {b_p}. "
                "Either the parameters named in each don't overlap, every "
                "overlapping value is unit-equivalent (e.g. `150 kVA` vs "
                "`0.15 MVA`), or every numeric difference falls below the "
                "suppression threshold. Lower the threshold in the sidebar "
                "to surface lower-confidence flags."
            )

        with st.expander("Diagnostic counts", expanded=False):
            col1, col2 = st.columns(2)
            with col1:
                st.markdown("**Doc A**")
                st.caption(
                    f"spans: {diag_a.get('spans', 0)} · "
                    f"tables: {diag_a.get('tables', 0)} · "
                    f"**extractable params: {a_p}** · "
                    f"low-coverage pages: {diag_a.get('low_coverage_pages', 0)}"
                )
            with col2:
                st.markdown("**Doc B**")
                st.caption(
                    f"spans: {diag_b.get('spans', 0)} · "
                    f"tables: {diag_b.get('tables', 0)} · "
                    f"**extractable params: {b_p}** · "
                    f"low-coverage pages: {diag_b.get('low_coverage_pages', 0)}"
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

        header = (
            f"{_SEVERITY[sev]['emoji']} **{f.parameter}** · "
            f"{dev_str} · confidence {f.confidence:.2f}{verdict_badge}"
        )

        with st.expander(
            header,
            expanded=verdict is None and sev in {"critical", "major"},
        ):
            st.markdown(_severity_chip(sev), unsafe_allow_html=True)
            st.markdown(f"**Rationale:** {f.rationale}")
            st.caption(
                f"Attribute family: `{attr_family}` · "
                f"Doc A treated as source of truth"
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
                doc_label = Path(f.a_record.doc_id).name or "doc_a"
                ocr_note_a = (
                    " · 🔍 OCR (whole-page snippet — vision model has no per-word bbox)"
                    if _is_ocr_span(f.a_record)
                    else ""
                )
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
                doc_label = Path(f.b_record.doc_id).name or "doc_b"
                ocr_note_b = (
                    " · 🔍 OCR (whole-page snippet — vision model has no per-word bbox)"
                    if _is_ocr_span(f.b_record)
                    else ""
                )
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
