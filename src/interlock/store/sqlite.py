"""SQLite-backed store for entity / claim / decision (Phase 14).

Raw-SQL CRUD; no ORM. The schema lives in ``data/interlock.schema.sql`` and
is applied idempotently on first connection. Database path is set via
``INTERLOCK_DB_PATH`` env var (defaults to ``data/interlock.db``).

Design notes
------------
- Claim ids are deterministic (sha256 of canonical key tuple) so upserts are
  natural and cache-friendly. Re-persisting the same logical claim is a
  no-op.
- Upserting a Claim auto-upserts its Entity (FK requirement). Callers don't
  need to track entity persistence separately.
- ``init_schema`` runs the schema file via ``executescript``; the schema uses
  ``CREATE TABLE IF NOT EXISTS`` so it's safe to call on every connect.
"""

from __future__ import annotations

import hashlib
import os
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from interlock.extract.entities import Claim, Entity, EntityType
from interlock.extract.parameters import ParameterRecord


_EXTRACTION_VERSION_DEFAULT = "regex-v1"


@dataclass(frozen=True)
class StoredDecision:
    """A reviewer verdict as persisted in the store."""

    id: int
    fixture_pair_id: str
    flag_id: str
    verdict: str
    reviewer: str | None
    rationale: str | None
    created_at: str


def _db_path() -> Path:
    return Path(os.environ.get("INTERLOCK_DB_PATH", "data/interlock.db"))


def _schema_path() -> Path:
    return Path("data/interlock.schema.sql")


def apply_schema(conn: sqlite3.Connection) -> None:
    """Apply schema + Sprint 3 column migration. Idempotent.

    SQLite doesn't support ``ALTER TABLE ... ADD COLUMN IF NOT EXISTS``,
    so the Sprint 3 ``decision.provenance`` column is added via a
    Python-side PRAGMA check + conditional ALTER. Re-running on a fresh
    or already-migrated DB is safe in both cases.
    """
    if _schema_path().exists():
        conn.executescript(_schema_path().read_text())
    _ensure_decision_provenance_column(conn)
    conn.commit()


def _ensure_decision_provenance_column(conn: sqlite3.Connection) -> None:
    """v2 Sprint 3 — add decision.provenance column if missing. Idempotent."""
    cur = conn.execute("PRAGMA table_info(decision)")
    cols = {row[1] for row in cur.fetchall()}
    if "provenance" not in cols:
        conn.execute(
            "ALTER TABLE decision ADD COLUMN provenance TEXT NOT NULL "
            "DEFAULT 'unknown'"
        )
        conn.commit()


def _connect() -> sqlite3.Connection:
    db = _db_path()
    db.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db)
    conn.execute("PRAGMA foreign_keys = ON")
    apply_schema(conn)
    return conn


def init_schema() -> None:
    """Apply the schema. Safe to call repeatedly."""
    _connect().close()


# ---------------- Entity ----------------


def upsert_entity(entity: Entity) -> None:
    """Insert or update an entity row. Idempotent by primary key."""
    conn = _connect()
    try:
        conn.execute(
            """
            INSERT INTO entity(id, type, label) VALUES (?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET type=excluded.type, label=excluded.label
            """,
            (entity.id, entity.type, entity.label),
        )
        conn.commit()
    finally:
        conn.close()


def get_entity(entity_id: str) -> Entity | None:
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT id, type, label FROM entity WHERE id = ?",
            (entity_id,),
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        return None
    return Entity(id=row[0], type=_coerce_entity_type(row[1]), label=row[2])


def entity_count() -> int:
    conn = _connect()
    try:
        row = conn.execute("SELECT COUNT(*) FROM entity").fetchone()
    finally:
        conn.close()
    return int(row[0])


# ---------------- Claim ----------------


def claim_id(claim: Claim) -> str:
    """Deterministic id from (entity_id, attribute, raw_value, doc_id, page).

    Same logical claim → same id; upserts are natural.
    """
    rec = claim.source_record
    key = "|".join(
        [
            claim.entity.id,
            claim.attribute,
            claim.raw_value,
            rec.doc_id,
            str(rec.page),
        ]
    )
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def upsert_claim(claim: Claim, *, extraction_version: str = _EXTRACTION_VERSION_DEFAULT) -> str:
    """Persist a claim (and its entity). Returns the claim id."""
    upsert_entity(claim.entity)
    cid = claim_id(claim)
    rec = claim.source_record
    conn = _connect()
    try:
        conn.execute(
            """
            INSERT INTO claim(
                id, entity_id, attribute, raw_value,
                normalized_magnitude, normalized_unit,
                doc_id, source_path, page,
                bbox_x0, bbox_y0, bbox_x1, bbox_y1,
                section, span_text, extraction_version
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                attribute=excluded.attribute,
                raw_value=excluded.raw_value,
                normalized_magnitude=excluded.normalized_magnitude,
                normalized_unit=excluded.normalized_unit,
                span_text=excluded.span_text,
                section=excluded.section
            """,
            (
                cid,
                claim.entity.id,
                claim.attribute,
                claim.raw_value,
                rec.normalized_magnitude,
                rec.normalized_unit,
                rec.doc_id,
                getattr(rec, "source_path", "") or "",
                rec.page,
                float(rec.bbox[0]),
                float(rec.bbox[1]),
                float(rec.bbox[2]),
                float(rec.bbox[3]),
                rec.section,
                rec.span_text,
                extraction_version,
            ),
        )
        conn.commit()
    finally:
        conn.close()
    return cid


def claim_count() -> int:
    conn = _connect()
    try:
        row = conn.execute("SELECT COUNT(*) FROM claim").fetchone()
    finally:
        conn.close()
    return int(row[0])


def _row_to_claim(row: tuple[Any, ...]) -> Claim:
    (
        _id,
        entity_id,
        attribute,
        raw_value,
        normalized_magnitude,
        normalized_unit,
        doc_id,
        source_path,
        page,
        bx0,
        by0,
        bx1,
        by1,
        section,
        span_text,
        _extraction_version,
        # Optional join columns when fetched together with entity row
        ent_type,
        ent_label,
    ) = row
    entity = Entity(
        id=cast(str, entity_id),
        type=_coerce_entity_type(cast(str, ent_type)),
        label=cast(str, ent_label),
    )
    record = ParameterRecord(
        doc_id=cast(str, doc_id),
        page=int(page),
        bbox=(float(bx0), float(by0), float(bx1), float(by1)),
        section=cast("str | None", section),
        span_text=cast(str, span_text),
        name=cast(str, attribute),
        raw_value=cast(str, raw_value),
        normalized_magnitude=cast("float | None", normalized_magnitude),
        normalized_unit=cast("str | None", normalized_unit),
        source_path=cast(str, source_path),
    )
    return Claim(
        entity=entity,
        attribute=cast(str, attribute),
        raw_value=cast(str, raw_value),
        source_record=record,
    )


def _claims_select(where_sql: str, params: tuple[Any, ...]) -> list[Claim]:
    conn = _connect()
    try:
        rows = conn.execute(
            f"""
            SELECT
                c.id, c.entity_id, c.attribute, c.raw_value,
                c.normalized_magnitude, c.normalized_unit,
                c.doc_id, c.source_path, c.page,
                c.bbox_x0, c.bbox_y0, c.bbox_x1, c.bbox_y1,
                c.section, c.span_text, c.extraction_version,
                e.type, e.label
            FROM claim c
            JOIN entity e ON e.id = c.entity_id
            {where_sql}
            ORDER BY c.created_at
            """,
            params,
        ).fetchall()
    finally:
        conn.close()
    return [_row_to_claim(row) for row in rows]


def claims_for_entity(entity_id: str) -> list[Claim]:
    return _claims_select("WHERE c.entity_id = ?", (entity_id,))


def claims_for_attribute(attribute: str) -> list[Claim]:
    return _claims_select("WHERE c.attribute = ?", (attribute,))


# ---------------- Decision ----------------


def record_decision(
    *,
    fixture_pair_id: str,
    flag_id: str,
    verdict: str,
    reviewer: str | None = None,
    rationale: str | None = None,
) -> int:
    conn = _connect()
    try:
        cursor = conn.execute(
            """
            INSERT INTO decision(fixture_pair_id, flag_id, verdict, reviewer, rationale)
            VALUES (?, ?, ?, ?, ?)
            """,
            (fixture_pair_id, flag_id, verdict, reviewer, rationale),
        )
        conn.commit()
        return int(cursor.lastrowid or 0)
    finally:
        conn.close()


def decisions_for_pair(fixture_pair_id: str) -> list[StoredDecision]:
    conn = _connect()
    try:
        rows = conn.execute(
            """
            SELECT id, fixture_pair_id, flag_id, verdict, reviewer, rationale, created_at
            FROM decision
            WHERE fixture_pair_id = ?
            ORDER BY created_at
            """,
            (fixture_pair_id,),
        ).fetchall()
    finally:
        conn.close()
    return [
        StoredDecision(
            id=int(r[0]),
            fixture_pair_id=r[1],
            flag_id=r[2],
            verdict=r[3],
            reviewer=r[4],
            rationale=r[5],
            created_at=r[6],
        )
        for r in rows
    ]


# ---------------- helpers ----------------


def _coerce_entity_type(value: str) -> EntityType:
    """SQLite returns plain str; cast into the EntityType literal union."""
    allowed = {
        "transformer",
        "pump",
        "motor",
        "breaker",
        "bus",
        "line",
        "motor_operated_valve",
        "valve",
        "relay",
        "implicit",
    }
    if value not in allowed:
        # Unknown type — fall back to implicit rather than crash on legacy rows.
        return "implicit"
    return value  # type: ignore[return-value]
