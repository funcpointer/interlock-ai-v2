"""Sprint 3 — decision.provenance column migration.

Schema migration is additive. Existing rows get the default value
'unknown'. Running apply_schema twice is idempotent (the ALTER TABLE
is guarded inside the migration logic).
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from interlock.store.sqlite import apply_schema


def _apply_schema_twice(tmp_path: Path) -> Path:
    """Apply the v2 schema twice to verify idempotency."""
    db_path = tmp_path / "test.db"
    with sqlite3.connect(db_path) as conn:
        apply_schema(conn)
        apply_schema(conn)  # Second application — must not raise.
    return db_path


def test_decision_table_has_provenance_column(tmp_path: Path) -> None:
    db = _apply_schema_twice(tmp_path)
    with sqlite3.connect(db) as conn:
        cur = conn.execute("PRAGMA table_info(decision)")
        cols = {row[1] for row in cur.fetchall()}
    assert "provenance" in cols


def test_decision_provenance_defaults_to_unknown(tmp_path: Path) -> None:
    db = _apply_schema_twice(tmp_path)
    with sqlite3.connect(db) as conn:
        # Insert a row without specifying provenance — should default.
        conn.execute(
            "INSERT INTO decision (fixture_pair_id, flag_id, verdict) "
            "VALUES ('p1', 'f1', 'accepted')"
        )
        conn.commit()
        cur = conn.execute("SELECT provenance FROM decision WHERE flag_id='f1'")
        row = cur.fetchone()
    assert row is not None
    assert row[0] == "unknown"


def test_apply_schema_idempotent(tmp_path: Path) -> None:
    """Running the migration twice must not raise. Already exercised by
    the _apply_schema_twice helper — this test just makes the assertion
    explicit."""
    db = _apply_schema_twice(tmp_path)
    assert db.exists()


def test_decision_provenance_accepts_known_values(tmp_path: Path) -> None:
    """All four taxonomy values can be inserted and read back."""
    db = _apply_schema_twice(tmp_path)
    with sqlite3.connect(db) as conn:
        for i, prov in enumerate(["rule_only", "llm_only", "mixed_track", "unknown"]):
            conn.execute(
                "INSERT INTO decision (fixture_pair_id, flag_id, verdict, provenance) "
                "VALUES (?, ?, 'accepted', ?)",
                (f"p{i}", f"f{i}", prov),
            )
        conn.commit()
        cur = conn.execute("SELECT flag_id, provenance FROM decision ORDER BY flag_id")
        rows = dict(cur.fetchall())
    assert rows == {
        "f0": "rule_only",
        "f1": "llm_only",
        "f2": "mixed_track",
        "f3": "unknown",
    }
