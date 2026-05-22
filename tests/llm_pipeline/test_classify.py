"""Classifier tests — mocked Anthropic calls only. Live-API behaviour
is verified in tests/real_world/test_doc_class_live.py (slow-marked)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from interlock.cache import disk as disk_cache


@pytest.fixture(autouse=True)
def _clear_classify_cache() -> None:
    """Classifications are diskcache-keyed by PDF content hash; clear between
    tests so a mocked response in test A doesn't leak into test B."""
    disk_cache.clear_namespace("doc-class")
    yield
    disk_cache.clear_namespace("doc-class")


def test_sample_pages_single_page_pdf() -> None:
    from interlock.llm_pipeline.classify import _sample_pages
    assert _sample_pages(1) == [1]


def test_sample_pages_two_page_pdf() -> None:
    from interlock.llm_pipeline.classify import _sample_pages
    assert _sample_pages(2) == [1, 2]


def test_sample_pages_three_page_pdf() -> None:
    from interlock.llm_pipeline.classify import _sample_pages
    assert _sample_pages(3) == [1, 2, 3]


def test_sample_pages_ten_page_pdf_picks_first_second_last() -> None:
    from interlock.llm_pipeline.classify import _sample_pages
    assert _sample_pages(10) == [1, 2, 10]


def test_sample_pages_zero_page_returns_empty() -> None:
    from interlock.llm_pipeline.classify import _sample_pages
    assert _sample_pages(0) == []
