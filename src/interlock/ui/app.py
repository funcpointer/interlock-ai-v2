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


def _diagnostic_counts(pdf_path: str, doc_id: str, table_max_pages: int) -> dict[str, int]:
    try:
        result = ingest(pdf_path, doc_id=doc_id, table_max_pages=table_max_pages)
        params = extract_parameters(result.spans)
        return {
            "spans": len(result.spans),
            "tables": len(result.tables),
            "params": len(params),
            "low_coverage_pages": len(result.low_coverage_pages),
        }
    except Exception:  # pragma: no cover
        return {"spans": 0, "tables": 0, "params": 0, "low_coverage_pages": 0}


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
    return f"{flag.parameter}|p{flag.a_record.page}|y{int(flag.a_record.bbox[1])}"


run = bool(a_file is not None and b_file is not None and st.button("Run review", type="primary"))

if run:
    _reset_workdir()
    workdir = _ensure_session_workdir()
    a_path = workdir / "doc_a.pdf"
    b_path = workdir / "doc_b.pdf"
    a_path.write_bytes(a_file.read())  # type: ignore[union-attr]
    b_path.write_bytes(b_file.read())  # type: ignore[union-attr]

    t0 = time.time()
    try:
        with st.status("Reviewing PDFs…", expanded=True) as status:
            status.write("⏳ Ingesting Doc A (PyMuPDF spans + Camelot tables)")
            status.write("⏳ Ingesting Doc B (same)")
            status.write(
                f"ℹ️ Camelot is scanning the first {table_max_pages} pages of each "
                "PDF; adjust the slider in the sidebar to expand the scope."
            )
            status.write(
                "⏳ Aligning across documents (exact name + canonical glossary + "
                "Voyage embeddings + Pint unit normalisation)"
            )
            status.write("⏳ Classifying severity against IEEE / IEC tolerance bands")
            if use_llm_judge:
                status.write("⏳ Asking the LLM for engineering rationale (cached)")
            flags = review_two_documents(
                str(a_path),
                str(b_path),
                embed_fn=embed_voyage,
                same_page_only=False,  # Cross-page alignment always — auto-detect heuristic obsolete in v1.5
                use_llm_judge=use_llm_judge,
                table_max_pages=table_max_pages,
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
    st.session_state["diag_a"] = _diagnostic_counts(str(a_path), "doc_a", table_max_pages)
    st.session_state["diag_b"] = _diagnostic_counts(str(b_path), "doc_b", table_max_pages)


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
                st.markdown(
                    f"**Doc A (source of truth)**  \n"
                    f"`{doc_label}` · page {f.a_record.page} · "
                    f"section: {f.a_record.section or '—'}"
                )
                if cit_a is not None:
                    st.image(cit_a.snippet_png)
                st.code(f.a_record.span_text, language="text")
            with cb:
                doc_label = Path(f.b_record.doc_id).name or "doc_b"
                st.markdown(
                    f"**Doc B (deviation candidate)**  \n"
                    f"`{doc_label}` · page {f.b_record.page} · "
                    f"section: {f.b_record.section or '—'}"
                )
                if cit_b is not None:
                    st.image(cit_b.snippet_png)
                st.code(f.b_record.span_text, language="text")

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
