"""Performance budgets pinning the deployed-demo's experience.

If these slip, the demo gets sluggish. Marked slow so CI can opt in/out
with ``-m "not slow"``. SCOPE §6.2 says a review must complete in under 90 s
end-to-end on the locked fixtures; we keep generous local margins so a slow
laptop or warm-up still passes.
"""

from __future__ import annotations

import os
import time

import pytest
from dotenv import load_dotenv

load_dotenv()

from interlock.extract.parameters import extract_parameters  # noqa: E402
from interlock.ingest.pdf import ingest  # noqa: E402
from interlock.pipeline import review_two_documents  # noqa: E402

EATON = "fixtures/pdfs/doc_a_60pct.pdf"
EATON_REV = "fixtures/pdfs/doc_b_90pct.pdf"
SPEC = "fixtures/pdfs/spec_xfmr_001.pdf"

pytestmark = pytest.mark.slow


def _stub_embed(texts: list[str]) -> dict[str, list[float]]:
    return {t: [hash(t) % 7919 / 7919.0, 0.1, 0.1] for t in texts}


def _embed_voyage(texts: list[str]) -> dict[str, list[float]]:
    from interlock.align.embed import embed_voyage

    return embed_voyage(texts)


def test_ingest_eaton_under_5s() -> None:
    t0 = time.time()
    result = ingest(EATON, doc_id="eaton")
    elapsed = time.time() - t0
    assert result.spans
    assert elapsed < 5.0, f"Eaton ingest took {elapsed:.2f}s"


def test_extract_eaton_params_under_1s() -> None:
    result = ingest(EATON, doc_id="eaton")
    t0 = time.time()
    params = extract_parameters(result.spans)
    elapsed = time.time() - t0
    assert params
    assert elapsed < 1.0, f"Eaton extraction took {elapsed:.2f}s"


def test_option1_pipeline_under_30s() -> None:
    t0 = time.time()
    flags = review_two_documents(
        EATON, EATON_REV, embed_fn=_stub_embed, doc_a_id="a", doc_b_id="b"
    )
    elapsed = time.time() - t0
    assert flags
    assert elapsed < 30.0, f"Option 1 pipeline took {elapsed:.2f}s (budget 30s)"


@pytest.mark.skipif(not os.getenv("VOYAGE_API_KEY"), reason="VOYAGE_API_KEY not set")
def test_option2_pipeline_with_real_voyage_under_30s() -> None:
    t0 = time.time()
    flags = review_two_documents(
        SPEC,
        EATON,
        embed_fn=_embed_voyage,
        doc_a_id="spec",
        doc_b_id="eaton",
        same_page_only=False,
    )
    elapsed = time.time() - t0
    assert flags
    assert elapsed < 30.0, f"Option 2 pipeline took {elapsed:.2f}s"
