"""InterLock AI — Streamlit single-page review UI.

Run locally:
    uv run streamlit run src/interlock/ui/app.py

The page expects ``VOYAGE_API_KEY`` in environment (read from .env at boot).
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

load_dotenv()

# Streamlit Cloud secrets bridge: copy any st.secrets entries into os.environ so
# downstream code (Voyage, Anthropic) finds them without conditional imports.
try:
    for k, v in st.secrets.items():  # pragma: no cover
        os.environ.setdefault(k, str(v))
except Exception:  # pragma: no cover
    pass

from interlock.align.embed import embed_voyage  # noqa: E402
from interlock.citation.render import render_citation  # noqa: E402
from interlock.pipeline import review_two_documents  # noqa: E402

st.set_page_config(page_title="InterLock AI — Review", layout="wide")
st.title("InterLock AI — Cross-Document Review")
st.caption(
    "Upload two engineering PDFs from the same project. The authoritative document "
    "(e.g., 60% baseline) is compared against the downstream document (e.g., 90% "
    "revision). InterLock surfaces directional, cited, confidence-scored parameter "
    "mismatches for human review."
)

with st.expander("How to read a flag", expanded=False):
    st.markdown(
        "- **Authority**: the document declared as the source of truth for this parameter.\n"
        "- **Confidence**: extraction × match × authority confidence. Higher = stronger signal.\n"
        "- **Citation**: page + section + quoted text + bbox snippet. Use it to verify "
        "in the source PDF.\n"
        "- **Authority rule (MVP)**: hardcoded — Doc A is the 60% baseline, Doc B is the 90% "
        "revision under review. Configurable per-pair authority is platform-path."
    )

col_a, col_b = st.columns(2)
with col_a:
    a_file = st.file_uploader(
        "Doc A — authoritative (e.g., 60% baseline)", type="pdf", key="a"
    )
with col_b:
    b_file = st.file_uploader(
        "Doc B — downstream (e.g., 90% revision)", type="pdf", key="b"
    )

threshold = st.slider(
    "Suppression threshold (flags below this confidence are hidden)",
    min_value=0.0,
    max_value=1.0,
    value=0.6,
    step=0.05,
)

if "decisions" not in st.session_state:
    st.session_state["decisions"] = {}  # flag_id -> {"verdict": "accepted"|"dismissed", ...}


def _flag_id(flag) -> str:  # type: ignore[no-untyped-def]
    return f"{flag.parameter}|p{flag.a_record.page}|y{int(flag.a_record.bbox[1])}"


if a_file is not None and b_file is not None:
    run = st.button("Run review", type="primary")
else:
    run = False

if run:
    with tempfile.TemporaryDirectory() as td:
        a_path = Path(td) / "doc_a.pdf"
        b_path = Path(td) / "doc_b.pdf"
        a_path.write_bytes(a_file.read())  # type: ignore[union-attr]
        b_path.write_bytes(b_file.read())  # type: ignore[union-attr]
        t0 = time.time()
        try:
            with st.spinner("Reviewing... extracting parameters and aligning across documents."):
                flags = review_two_documents(
                    str(a_path), str(b_path), embed_fn=embed_voyage
                )
        except Exception as e:
            st.error(f"Review failed: {e}")
            st.stop()
        elapsed = time.time() - t0

    st.success(
        f"Review complete in {elapsed:.1f}s. {len(flags)} candidate flag(s) "
        f"({sum(1 for f in flags if f.confidence >= threshold)} above threshold)."
    )
    st.session_state["flags"] = flags
    st.session_state["a_path"] = str(a_path)
    st.session_state["b_path"] = str(b_path)
    st.session_state["decisions"] = {}

flags = st.session_state.get("flags", [])
if flags:
    above = [f for f in flags if f.confidence >= threshold]
    below = [f for f in flags if f.confidence < threshold]

    st.subheader(f"{len(above)} flag(s) above confidence ≥ {threshold:.2f}")
    for f in sorted(above, key=lambda x: -x.confidence):
        fid = _flag_id(f)
        verdict = st.session_state["decisions"].get(fid, {}).get("verdict")
        badge = ""
        if verdict == "accepted":
            badge = "  ✅ Accepted"
        elif verdict == "dismissed":
            badge = "  ✖️ Dismissed"

        with st.expander(
            f"[{f.confidence:.2f}] {f.parameter} · {f.rationale}{badge}",
            expanded=verdict is None,
        ):
            st.caption(f"Authority rule: {f.authority_rule}")
            cit_a = None
            cit_b = None
            try:
                cit_a = render_citation(f.a_record)
                cit_b = render_citation(f.b_record)
            except Exception as e:  # pragma: no cover
                st.warning(f"Could not render citation snippets: {e}")

            ca, cb = st.columns(2)
            with ca:
                st.markdown(
                    f"**Authoritative** · `{Path(f.a_record.doc_id).name}` · "
                    f"p{f.a_record.page} · {f.a_record.section or '—'}"
                )
                if cit_a is not None:
                    st.image(cit_a.snippet_png)
                st.code(f.a_record.span_text)
            with cb:
                st.markdown(
                    f"**Deviation** · `{Path(f.b_record.doc_id).name}` · "
                    f"p{f.b_record.page} · {f.b_record.section or '—'}"
                )
                if cit_b is not None:
                    st.image(cit_b.snippet_png)
                st.code(f.b_record.span_text)

            b_accept, b_dismiss, _ = st.columns([1, 1, 4])
            with b_accept:
                if st.button("Accept", key=f"acc-{fid}"):
                    st.session_state["decisions"][fid] = {
                        "verdict": "accepted",
                        "parameter": f.parameter,
                        "confidence": f.confidence,
                        "rationale": f.rationale,
                        "doc_a_page": f.a_record.page,
                        "doc_b_page": f.b_record.page,
                        "doc_a_value": f.a_record.raw_value,
                        "doc_b_value": f.b_record.raw_value,
                    }
                    st.rerun()
            with b_dismiss:
                if st.button("Dismiss", key=f"dis-{fid}"):
                    st.session_state["decisions"][fid] = {"verdict": "dismissed"}
                    st.rerun()

    if below:
        with st.expander(f"{len(below)} suppressed (below threshold)", expanded=False):
            for f in below:
                st.markdown(f"- [{f.confidence:.2f}] {f.parameter}: {f.rationale}")

    accepted = [
        d for d in st.session_state["decisions"].values() if d.get("verdict") == "accepted"
    ]
    if accepted:
        st.download_button(
            "Export accepted flags (JSON)",
            data=json.dumps(accepted, indent=2),
            file_name="accepted_flags.json",
            mime="application/json",
        )
else:
    st.info("Upload two PDFs and click Run review to begin.")
