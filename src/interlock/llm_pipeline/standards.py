"""Sprint 5a — curated standards-clause registry.

Loads data/standards/clauses.yaml + (optional) per-project overrides at
fixtures/projects/<project_id>/tolerances.yaml. Provides per-family
lookup with optional doc_class filtering.

Failure modes (missing file, YAML parse error, pydantic validation error,
bad individual entry) all collapse to '[]' so the LLM judge keeps running
gracefully without grounding.
"""

from __future__ import annotations

import logging
from pathlib import Path

import yaml

from interlock.llm_pipeline.schemas.clause import Clause, ClauseCitation

logger = logging.getLogger(__name__)

_CLAUSES_PATH = Path("data/standards/clauses.yaml")
_PROJECTS_ROOT = Path("fixtures/projects")


def load_clauses(path: Path | None = None) -> list[Clause]:
    """Return list of validated Clause entries from YAML.

    Missing file → []. Parse / validation error → logged + [].
    Individual bad entries dropped; others retained.
    """
    p = path if path is not None else _CLAUSES_PATH
    if not p.exists():
        return []
    try:
        raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as e:
        logger.warning("standards: YAML parse failed for %s: %s", p, e)
        return []
    entries = raw.get("clauses") if isinstance(raw, dict) else None
    if not isinstance(entries, list):
        return []
    out: list[Clause] = []
    for i, entry in enumerate(entries):
        if not isinstance(entry, dict):
            continue
        try:
            out.append(Clause(**entry))
        except Exception as e:
            logger.warning(
                "standards: dropping invalid entry #%d in %s: %s", i, p, e,
            )
    return out


def _project_overrides_path(project_id: str) -> Path:
    return _PROJECTS_ROOT / project_id / "tolerances.yaml"


def merge_project_overrides(base: list[Clause], project_id: str) -> list[Clause]:
    """Merge project overrides into base by clause_id.

    Project entry with same clause_id replaces base entry. Project entries
    with novel clause_ids are appended. Missing override file → base
    unchanged.
    """
    override_path = _project_overrides_path(project_id)
    if not override_path.exists():
        return base
    overrides = load_clauses(override_path)
    if not overrides:
        return base
    by_id: dict[str, Clause] = {c.clause_id: c for c in base}
    for o in overrides:
        by_id[o.clause_id] = o
    return list(by_id.values())


def clauses_for(
    family: str,
    doc_class: str | None = None,
    project_id: str | None = None,
) -> list[Clause]:
    """Return clauses matching attribute_family + optionally doc_class.

    Family match: any entry whose ``applicable_families`` contains ``family``.
    Doc-class filter: entry passes if ``applicable_doc_classes`` is empty
    (applies to all) OR contains the supplied ``doc_class``. When
    ``doc_class is None`` the filter is skipped entirely.
    """
    base = load_clauses()
    if project_id:
        clauses = merge_project_overrides(base, project_id)
    else:
        clauses = base
    out: list[Clause] = []
    for c in clauses:
        if family not in c.applicable_families:
            continue
        if doc_class is not None and c.applicable_doc_classes:
            if doc_class not in c.applicable_doc_classes:
                continue
        out.append(c)
    return out


def to_citation(clause: Clause) -> ClauseCitation:
    """Project Clause → ClauseCitation (slim, reviewer-facing fields)."""
    return ClauseCitation(
        clause_id=clause.clause_id,
        edition_year=clause.edition_year,
        source_name=clause.source_name,
        summary=clause.summary,
    )
