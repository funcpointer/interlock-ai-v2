from pathlib import Path

from interlock.ingest.tables import Cell, Table, extract_tables

DOC_A = Path("fixtures/pdfs/doc_a_60pct.pdf")


def test_extract_tables_returns_typed_records_or_empty() -> None:
    # Eaton may or may not contain Camelot-detectable tables (text laid out in
    # columns isn't always a real table). The contract is: returns list[Table]
    # without crashing; each Table has typed cells with bboxes.
    tables = extract_tables(str(DOC_A), pages="1-9")
    assert isinstance(tables, list)
    for t in tables:
        assert isinstance(t, Table)
        assert t.page >= 1
        assert t.rows, "rows must not be empty when a table is produced"
        for row in t.rows:
            for cell in row:
                assert isinstance(cell, Cell)
                assert isinstance(cell.text, str)
                assert len(cell.bbox) == 4
                assert 0.0 <= t.confidence <= 1.0


def test_extract_tables_doc_id_propagates() -> None:
    tables = extract_tables(str(DOC_A), doc_id="docA", pages="1-2")
    for t in tables:
        assert t.doc_id == "docA"
