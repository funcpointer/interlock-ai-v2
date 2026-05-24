"""Phase 33.2 — context extraction tests.

Covers the context-touching attacks from Sprint 9 Phase 33.0a gold:

- **Attack 4** moved-table-p7-to-p8 — page distance must not break
  context match.
- **Attack 7** fuse-present-elsewhere-removed-from-matched-table —
  distinct contexts (``tcc3`` table vs ``one_line``) for the same
  fuse model number.
- **Attack 11** context-title-renamed — "TCC3" ↔ "Coordination Curve 3"
  share canonical id.
- **Attack 13** forbidden-match-row-marker-collision — same row id
  in different contexts must NOT merge into one context.

Schema-shape tests for :class:`ExtractedContext` itself stay narrow:
Phase 33.2 doesn't compute column_headers (those wait on Phase 33.5
Camelot wiring). The tests assert what Phase 33.2 actually delivers.
"""

from __future__ import annotations

import pytest

from interlock.extract.context import (
    ExtractedContext,
    align_contexts_across_docs,
    canonicalize_context_title,
    extract_contexts,
)
from tests.fixtures.equipment.synthetic import attack, to_synthetic_records


# ---------------------------------------------------------------------------
# canonicalize_context_title — alias collapse rules
# ---------------------------------------------------------------------------


def test_canonical_empty_input() -> None:
    assert canonicalize_context_title("") == ""
    assert canonicalize_context_title("   ") == ""


def test_canonical_tcc_family_aliases() -> None:
    """Attack 11 — multiple title variants of the same TCC must
    collapse to the same canonical id."""
    canonical = "tcc3"
    for variant in (
        "TCC3",
        "tcc3",
        "TCC 3",
        "Coordination Curve 3",
        "Coordination Plot 3",
        "Time Current Curve 3",
        "Transformer Inrush 3",
    ):
        assert canonicalize_context_title(variant) == canonical, (
            f"variant {variant!r} did not canonicalize to {canonical!r}"
        )


def test_canonical_one_line_family() -> None:
    for variant in ("One Line", "one_line", "Single Line", "single-line", "One-Line Diagram"):
        assert canonicalize_context_title(variant) == "one_line"


def test_canonical_unknown_titles_slug_through() -> None:
    """Unknown titles fall back to a stable slug — uninterpreted but
    deterministic. Phase 33.6 UI gives reviewers a way to map novel
    titles into the alias map."""
    assert canonicalize_context_title("Some Bespoke Section") == "somebespokesection"


# ---------------------------------------------------------------------------
# extract_contexts — per-doc grouping
# ---------------------------------------------------------------------------


def test_extract_contexts_groups_records_by_title() -> None:
    """Records with the same raw_title cluster into one
    ExtractedContext. Distinct titles produce distinct contexts."""
    records = [
        {"page": 3, "context_id": "tcc1", "row_id": "1", "name": "X", "raw_value": "1"},
        {"page": 3, "context_id": "tcc1", "row_id": "2", "name": "Y", "raw_value": "2"},
        {"page": 7, "context_id": "tcc3", "row_id": "1", "name": "Z", "raw_value": "3"},
    ]
    contexts = extract_contexts(records, doc_id="doc_a")
    by_canonical = {c.canonical_id: c for c in contexts}
    assert set(by_canonical) == {"tcc1", "tcc3"}
    assert by_canonical["tcc1"].row_count == 2
    assert by_canonical["tcc3"].row_count == 1


def test_extract_contexts_skips_records_without_context_id() -> None:
    """Records without a context_id live in document-wide space and
    don't anchor any context."""
    records = [
        {"page": 1, "name": "Spec", "raw_value": "v"},  # no context_id
        {"page": 3, "context_id": "tcc1", "row_id": "1", "name": "X", "raw_value": "1"},
    ]
    contexts = extract_contexts(records, doc_id="doc_a")
    assert len(contexts) == 1
    assert contexts[0].canonical_id == "tcc1"


def test_extract_contexts_attack_13_row_marker_collision() -> None:
    """Attack 13 — two rows share row marker '2' but in different
    tables. extract_contexts MUST produce two distinct
    ExtractedContext objects, not collapse them under row id alone."""
    records_a = [
        {"page": 3, "context_id": "tcc1", "row_id": "2", "name": "Transformer Rating", "raw_value": "1000 kVA"},
    ]
    records_b = [
        {"page": 7, "context_id": "tcc3", "row_id": "2", "name": "Transformer Rating", "raw_value": "1000 kVA"},
    ]
    a_ctx = extract_contexts(records_a, doc_id="doc_a")
    b_ctx = extract_contexts(records_b, doc_id="doc_b")
    assert len(a_ctx) == 1 and a_ctx[0].canonical_id == "tcc1"
    assert len(b_ctx) == 1 and b_ctx[0].canonical_id == "tcc3"
    assert a_ctx[0].canonical_id != b_ctx[0].canonical_id, (
        "row marker collision must not merge contexts"
    )


def test_extract_contexts_attack_7_fuse_two_contexts() -> None:
    """Attack 7 — same fuse model appears in BOTH the TCC3 table
    (row 34) AND the one-line callout (no row marker). These are
    distinct contexts; extract_contexts must surface both."""
    records = [
        {"page": 7, "context_id": "tcc3", "row_id": "34", "name": "Fuse Designation", "raw_value": "LPN-RK-500SP"},
        {"page": 2, "context_id": "one_line", "name": "Fuse Designation", "raw_value": "LPN-RK-500SP"},
    ]
    contexts = extract_contexts(records, doc_id="doc_a")
    canonical_ids = {c.canonical_id for c in contexts}
    assert canonical_ids == {"tcc3", "one_line"}


def test_extract_contexts_attack_4_pages_belong_to_one_context() -> None:
    """Attack 4 — table moved from p7 in doc_a to p8 in doc_b. Within
    EACH doc the table is one context; cross-doc alignment happens in
    align_contexts_across_docs (next test)."""
    # doc_a: table on p7
    a_recs = [
        {"page": 7, "context_id": "tcc3", "row_id": "31", "name": "Fuse Designation", "raw_value": "LPS-RK-225SP"},
    ]
    # doc_b: same table moved to p8
    b_recs = [
        {"page": 8, "context_id": "tcc3", "row_id": "31", "name": "Fuse Designation", "raw_value": "LPS-RK-225SP"},
    ]
    a_ctx = extract_contexts(a_recs, doc_id="doc_a")
    b_ctx = extract_contexts(b_recs, doc_id="doc_b")
    assert len(a_ctx) == 1
    assert len(b_ctx) == 1
    assert a_ctx[0].canonical_id == b_ctx[0].canonical_id == "tcc3"
    # Pages differ but canonical_id is the cross-doc handle, not the page set.
    assert a_ctx[0].page_set == frozenset({7})
    assert b_ctx[0].page_set == frozenset({8})


def test_extract_contexts_kind_heuristic_table_row() -> None:
    """Heuristic: titles containing 'tcc' or 'curve' or 'table' →
    table_row kind."""
    recs = [{"page": 3, "context_id": "tcc1", "row_id": "1", "name": "X", "raw_value": "1"}]
    ctx = extract_contexts(recs, doc_id="doc_a")[0]
    assert ctx.kind == "table_row"


def test_extract_contexts_kind_heuristic_diagram() -> None:
    recs = [{"page": 2, "context_id": "one_line", "name": "Fuse Designation", "raw_value": "X"}]
    ctx = extract_contexts(recs, doc_id="doc_a")[0]
    assert ctx.kind == "diagram_label"


def test_extract_contexts_kind_heuristic_schedule() -> None:
    recs = [{"page": 7, "context_id": "schedule", "row_id": "T1", "name": "X", "raw_value": "1"}]
    ctx = extract_contexts(recs, doc_id="doc_a")[0]
    assert ctx.kind == "schedule"


# ---------------------------------------------------------------------------
# align_contexts_across_docs — Attack 11 cross-doc alignment
# ---------------------------------------------------------------------------


def test_align_contexts_attack_11_renamed_same_structure() -> None:
    """Attack 11 — doc_a calls it "TCC3"; doc_b calls it
    "Coordination Curve 3". Same canonical id post-alignment.
    Lookup by (doc_id, raw_title) returns the shared canonical."""
    a_recs = [
        {"page": 7, "context_id": "TCC3", "row_id": "1", "name": "Transformer Rating", "raw_value": "1000 kVA"},
    ]
    b_recs = [
        {"page": 7, "context_id": "Coordination Curve 3", "row_id": "1", "name": "Transformer Rating", "raw_value": "1000 kVA"},
    ]
    a_ctx = extract_contexts(a_recs, doc_id="doc_a")
    b_ctx = extract_contexts(b_recs, doc_id="doc_b")
    align = align_contexts_across_docs(a_ctx, b_ctx)
    assert align[("doc_a", "TCC3")] == "tcc3"
    assert align[("doc_b", "Coordination Curve 3")] == "tcc3"


def test_align_contexts_no_false_merge_attack_13() -> None:
    """Attack 13 — alignment must NOT merge tcc1 with tcc3 even if a
    record in each shares row marker '2'."""
    a_recs = [
        {"page": 3, "context_id": "tcc1", "row_id": "2", "name": "Transformer Rating", "raw_value": "1000 kVA"},
    ]
    b_recs = [
        {"page": 7, "context_id": "tcc3", "row_id": "2", "name": "Transformer Rating", "raw_value": "1000 kVA"},
    ]
    align = align_contexts_across_docs(
        extract_contexts(a_recs, doc_id="doc_a"),
        extract_contexts(b_recs, doc_id="doc_b"),
    )
    assert align[("doc_a", "tcc1")] == "tcc1"
    assert align[("doc_b", "tcc3")] == "tcc3"
    assert align[("doc_a", "tcc1")] != align[("doc_b", "tcc3")]


def test_align_contexts_structural_fingerprint_promotes_shared_canonical() -> None:
    """When two contexts share column_headers + row_count but
    canonical_ids differ, the lexicographically-smaller canonical_id
    wins as the shared cross-doc handle. (Phase 33.2 stub for the
    Phase 33.5 Camelot-driven case.)"""
    a_ctx = [
        ExtractedContext(
            doc_id="doc_a",
            raw_title="Table A",
            canonical_id="alpha",
            kind="table_row",
            column_headers=("Device ID", "Description", "Comment"),
            row_count=5,
            page_set=frozenset({3}),
        ),
    ]
    b_ctx = [
        ExtractedContext(
            doc_id="doc_b",
            raw_title="Table B",
            canonical_id="bravo",
            kind="table_row",
            column_headers=("Device ID", "Description", "Comment"),
            row_count=5,
            page_set=frozenset({4}),
        ),
    ]
    align = align_contexts_across_docs(a_ctx, b_ctx)
    assert align[("doc_a", "Table A")] == "alpha"
    assert align[("doc_b", "Table B")] == "alpha"


# ---------------------------------------------------------------------------
# Gold integration — every attack with context_id-bearing records
# must extract cleanly through Phase 33.2.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "attack_name",
    [
        "three_1000kva_transformers_only_p7_mutates",
        "rich_a_sparse_b_duplicate_transformers",
        "same_table_similar_fuse_designations",
        "same_equipment_moved_one_page_wrong_same_page_decoy",
        "fuse_present_elsewhere_removed_from_matched_table",
        "context_title_renamed_same_structure",
        "intra_doc_three_lanes_disagree_on_row_34",
        "forbidden_match_row_marker_collision",
    ],
)
def test_gold_attack_contexts_extract_cleanly(attack_name: str) -> None:
    """Every gold attack with context-bearing records produces
    non-empty ExtractedContext objects for at least one doc."""
    entry = attack(attack_name)
    a_recs = to_synthetic_records(entry, "doc_a")
    b_recs = to_synthetic_records(entry, "doc_b")
    a_ctx = extract_contexts(a_recs, doc_id="doc_a")
    b_ctx = extract_contexts(b_recs, doc_id="doc_b")
    # At least one side should produce contexts. Fixtures that have
    # only doc_a (e.g. intra_doc_three_lanes_disagree_on_row_34) get
    # a non-empty list for a_ctx.
    assert a_ctx or b_ctx, (
        f"attack {attack_name!r}: no contexts extracted from either side. "
        f"a_records={len(a_recs)} b_records={len(b_recs)}"
    )
    for ctx in (*a_ctx, *b_ctx):
        assert ctx.canonical_id, f"{attack_name}: empty canonical_id"
        assert ctx.kind in ("table_row", "diagram_label", "prose", "schedule")


def test_gold_attack_11_cross_doc_canonical_matches() -> None:
    """Spec-specific: attack 11 exercises the alias-collapse path
    end-to-end via gold."""
    entry = attack("context_title_renamed_same_structure")
    a_recs = to_synthetic_records(entry, "doc_a")
    b_recs = to_synthetic_records(entry, "doc_b")
    a_ctx = extract_contexts(a_recs, doc_id="doc_a")
    b_ctx = extract_contexts(b_recs, doc_id="doc_b")
    align = align_contexts_across_docs(a_ctx, b_ctx)
    # Both raw titles must map to the same canonical id.
    a_canonical = align[("doc_a", "TCC3")]
    b_canonical = align[("doc_b", "Coordination Curve 3")]
    assert a_canonical == b_canonical == "tcc3"
