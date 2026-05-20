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
from interlock.cache.cost_ledger import summary as cost_summary  # noqa: E402
from interlock.citation.render import render_citation  # noqa: E402
from interlock.pipeline import review_two_documents  # noqa: E402


# ----------------------------------------------------------------------
# Page config + global styles
# ----------------------------------------------------------------------

st.set_page_config(
    page_title="InterLock AI — Review",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Per-severity color theme used for cards in the flag list.
_SEVERITY = {
    "critical": {"emoji": "🔴", "label": "CRITICAL", "border": "#c0392b", "bg": "#fdecea"},
    "major":    {"emoji": "🟠", "label": "MAJOR",    "border": "#d35400", "bg": "#fef0e6"},
    "minor":    {"emoji": "🟡", "label": "MINOR",    "border": "#b7950b", "bg": "#fff8db"},
    "info":     {"emoji": "⚪", "label": "INFO",     "border": "#7f8c8d", "bg": "#f2f3f4"},
}
_SEVERITY_ORDER = {"critical": 0, "major": 1, "minor": 2, "info": 3}


# ----------------------------------------------------------------------
# Persistent temp dir per session (fix for the citation-render bug where
# the previous implementation used `tempfile.TemporaryDirectory` as a
# context manager that deleted the uploaded PDFs as soon as the pipeline
# call returned — subsequent reruns triggered by Accept/Dismiss buttons
# then tried to open paths that no longer existed and got
# "no such file: /tmp/.../doc_a.pdf").
# ----------------------------------------------------------------------


def _ensure_session_workdir() -> Path:
    """Return a per-session temp dir that lives across Streamlit reruns.

    Streamlit's `session_state` survives reruns but is reset on a hard
    refresh / new session, at which point we want a fresh temp dir.
    """
    if "workdir" not in st.session_state or not Path(st.session_state["workdir"]).exists():
        st.session_state["workdir"] = tempfile.mkdtemp(prefix="interlock_")
    return Path(st.session_state["workdir"])


def _reset_workdir() -> None:
    """Wipe and recreate the session workdir when new PDFs are uploaded."""
    old = st.session_state.get("workdir")
    if old and Path(old).exists():
        shutil.rmtree(old, ignore_errors=True)
    st.session_state["workdir"] = tempfile.mkdtemp(prefix="interlock_")


# ----------------------------------------------------------------------
# Header
# ----------------------------------------------------------------------

st.title("InterLock AI")
st.markdown(
    "**Cross-document discrepancy detection for engineering PDFs** — "
    "upload two PDFs from the same project, get directional, cited, "
    "severity-tiered parameter mismatches for review."
)

# ----------------------------------------------------------------------
# Sidebar — controls + cost meter
# ----------------------------------------------------------------------

with st.sidebar:
    st.header("Review settings")

    st.markdown("**Comparison mode**")
    fixture_mode = st.radio(
        "fixture mode",
        options=("Revision diff (same layout)", "Cross-document (spec ↔ study)"),
        index=0,
        label_visibility="collapsed",
        help=(
            "Revision diff: Doc A and Doc B share layout (e.g., 60% baseline vs "
            "90% revision of the same coordination study). The aligner pairs by "
            "exact parameter name on the same page.\n\n"
            "Cross-document: Doc A and Doc B are different document types "
            "(e.g., transformer spec ↔ coordination study). The aligner uses "
            "the canonical-name glossary and allows pairs across pages."
        ),
    )
    cross_doc_mode = fixture_mode.startswith("Cross-document")

    st.markdown("**Severity threshold**")
    threshold = st.slider(
        "Suppress flags below this confidence",
        min_value=0.0,
        max_value=1.0,
        value=0.6,
        step=0.05,
        label_visibility="collapsed",
        help=(
            "Hide flags whose computed confidence falls below this value. "
            "Suppressed flags remain accessible in the 'Suppressed' expander "
            "below the main list."
        ),
    )

    st.markdown("**Significance reasoning**")
    use_llm_judge = st.toggle(
        "Use LLM to enrich severity (Claude Opus 4.7)",
        value=False,
        help=(
            "Off: rule-based severity from IEEE/IEC tolerance bands per parameter "
            "family — fast, deterministic, free.\n\n"
            "On: each surfaced flag is sent to Claude Opus 4.7 with a cached "
            "engineering ontology. Returns severity + rationale + suspected "
            "downstream effects. Adds ~2 s and ~$0.01 per new flag; cached "
            "after first call so repeat runs cost ≈ $0."
        ),
    )

    st.divider()
    st.markdown("**Session cost so far**")
    try:
        s = cost_summary()
        st.metric("Total spend (USD)", f"${s.total_usd:.4f}")
        if s.by_provider:
            for provider, amt in sorted(s.by_provider.items()):
                st.caption(f"{provider}: ${amt:.4f}")
        st.caption(f"{s.n_events} API call(s) recorded.")
    except Exception:  # pragma: no cover
        st.caption("Cost ledger unavailable.")

    st.divider()
    with st.expander("How to read a flag", expanded=False):
        st.markdown(
            "- **Severity** is computed from a per-parameter-family tolerance "
            "band (e.g., IEEE C57.12.00 §9.1 Table 17 for transformer "
            "impedance). Within-tolerance changes classify as **info** and are "
            "suppressed.\n"
            "- **Authority** is the document declared as source-of-truth for "
            "the parameter family. Today's rule is hardcoded for the locked "
            "demo fixtures — Doc A is authoritative, Doc B is the deviation "
            "candidate. Per-project configurable authority is platform-path.\n"
            "- **Confidence** = extraction × match × authority. All three are "
            "in [0, 1]; the product is what you see.\n"
            "- **Citation** is a bbox-highlighted snippet of the source page. "
            "Verify the finding in seconds without leaving the page.\n"
            "- **Accept / Dismiss** records your verdict in the session; "
            "accepted flags export as JSON for the audit log."
        )


# ----------------------------------------------------------------------
# Uploaders
# ----------------------------------------------------------------------

col_a, col_b = st.columns(2)
with col_a:
    a_file = st.file_uploader(
        "Doc A — authoritative (e.g., 60 % baseline or equipment spec)",
        type="pdf",
        key="a",
    )
with col_b:
    b_file = st.file_uploader(
        "Doc B — downstream (e.g., 90 % revision or coordination study)",
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
    # New upload = fresh workdir so a previous session's PDFs don't linger.
    _reset_workdir()
    workdir = _ensure_session_workdir()
    a_path = workdir / "doc_a.pdf"
    b_path = workdir / "doc_b.pdf"
    a_path.write_bytes(a_file.read())  # type: ignore[union-attr]
    b_path.write_bytes(b_file.read())  # type: ignore[union-attr]

    spinner_msg = (
        "Reviewing — extracting parameters, aligning, asking the LLM for "
        "engineering significance."
        if use_llm_judge
        else "Reviewing — extracting parameters and aligning across documents."
    )
    t0 = time.time()
    try:
        with st.spinner(spinner_msg):
            flags = review_two_documents(
                str(a_path),
                str(b_path),
                embed_fn=embed_voyage,
                same_page_only=not cross_doc_mode,
                use_llm_judge=use_llm_judge,
            )
    except Exception as e:
        st.error(
            f"Review failed: {type(e).__name__}: {e}\n\n"
            "Common causes: missing VOYAGE_API_KEY, malformed PDF, or "
            "Voyage / Anthropic rate-limit. Check the sidebar cost meter and "
            "the .env values, then try again."
        )
        st.stop()
    elapsed = time.time() - t0

    st.session_state["flags"] = flags
    st.session_state["a_path"] = str(a_path)
    st.session_state["b_path"] = str(b_path)
    st.session_state["elapsed"] = elapsed
    st.session_state["use_llm_judge_at_run"] = use_llm_judge
    st.session_state["cross_doc_mode_at_run"] = cross_doc_mode
    st.session_state["decisions"] = {}


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
        sev_counts[getattr(f, "severity", "major")] = sev_counts.get(
            getattr(f, "severity", "major"), 0
        ) + 1

    cols = st.columns([2, 1, 1, 1, 1])
    cols[0].metric("Time", f"{elapsed:.1f} s")
    cols[1].metric("Surfaced", f"{len(above)}")
    cols[2].metric("🔴 Critical", f"{sev_counts.get('critical', 0)}")
    cols[3].metric("🟠 Major", f"{sev_counts.get('major', 0)}")
    cols[4].metric("🟡 Minor", f"{sev_counts.get('minor', 0)}")

    mode_label = (
        "Cross-document (spec ↔ study)"
        if st.session_state.get("cross_doc_mode_at_run")
        else "Revision diff (same layout)"
    )
    judge_label = "with LLM enrichment" if st.session_state.get("use_llm_judge_at_run") else "rule-based severity"
    st.caption(f"Mode: {mode_label} · {judge_label}")

    if not above and not below:
        st.info(
            "No mismatches surfaced. Either the documents agree on every "
            "extracted parameter, or no parameters were extractable from "
            "this pair (check the ingest coverage in the source PDFs)."
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
            st.caption(f"Attribute family: `{attr_family}` · Authority: {f.authority_rule}")

            # Citation snippets
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
                    "Citation snippet rendering failed (this is usually a "
                    "stale path; re-run the review):\n"
                    f"- A: {err_a or 'ok'}\n- B: {err_b or 'ok'}"
                )

            ca, cb = st.columns(2)
            with ca:
                doc_label = Path(f.a_record.doc_id).name or "doc_a"
                st.markdown(
                    f"**Authoritative**  \n"
                    f"`{doc_label}` · page {f.a_record.page} · "
                    f"section: {f.a_record.section or '—'}"
                )
                if cit_a is not None:
                    st.image(cit_a.snippet_png)
                st.code(f.a_record.span_text, language="text")
            with cb:
                doc_label = Path(f.b_record.doc_id).name or "doc_b"
                st.markdown(
                    f"**Deviation candidate**  \n"
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
                f"the {threshold:.2f} suppression threshold. Lower the threshold "
                "in the sidebar to surface them."
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
