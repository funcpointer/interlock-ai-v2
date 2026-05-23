"""Global test fixtures.

Sprint 8 — vision lane is default-ON in the pipeline. To keep pre-Sprint-8
tests fast and offline, default to stubbing ``vision_extract_page`` with a
no-op for every test. Tests that want the real path (Sprint 8 unit/e2e
tests and live exit-gate tests) opt in via ``@pytest.mark.vision_lane``.
Without the opt-in marker, the stub returns ``[]`` so the pipeline still
runs but pays no PNG-render / Anthropic-call cost.
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _vision_lane_default_stub(request, mocker):  # type: ignore[no-untyped-def]
    if "vision_lane" in request.keywords:
        # Test opted into the real vision_extract_page path.
        yield
        return
    mocker.patch(
        "interlock.llm_pipeline.vision_extract.vision_extract_page",
        return_value=[],
    )
    yield
