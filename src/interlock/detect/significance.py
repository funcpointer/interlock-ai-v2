"""LLM-based significance judgment with engineering reasoning.

The rules-based ``classify()`` in ``tolerances.py`` gives a fast,
deterministic severity tier from a deviation percentage. But it can't reason
about *why* a value differs (design vs operating values, alternate scenarios,
typo patterns) or what *downstream* parameters become suspect.

``judge()`` calls Claude with a prompt that frames the difference in
engineering-domain terms and asks for:
- severity tier (with reasoning)
- whether the change is within typical tolerance
- a 1–2 sentence engineering explanation
- a list of downstream parameters whose correctness depends on this value
- the model's self-reported confidence

The call is wrapped in two caches:
1. Disk cache (per flag_id + prompt_version + model) — survives across
   pipeline runs, avoids re-paying for the same flag.
2. Anthropic prompt cache (1h TTL on the engineering preamble + ontology +
   glossary blocks) — ~90% cost reduction on the system prompt portion.

Use ``judge_batch()`` to amortize the LLM cost across a flag list with a
single shared prompt-prefix cache.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from interlock.cache import cost_ledger
from interlock.cache.disk import get_or_compute
from interlock.detect.mismatch import Flag
from interlock.llm.client import DEFAULT_MODEL, CachedBlock, call_structured
from interlock.llm_pipeline.standards import clauses_for, to_citation

PROMPT_VERSION = "v1"
_CACHE_NAMESPACE = "llm-significance"


class SignificanceJudgment(BaseModel):
    """LLM's assessment of one flag's engineering significance."""

    severity: Literal["critical", "major", "minor", "info"] = Field(
        description=(
            "Severity tier. 'critical' for likely outright errors (decimal "
            "shifts, units mistakes); 'major' for changes outside typical "
            "design tolerance that need explanation; 'minor' for noticeable "
            "changes worth a reviewer's eye; 'info' for within-tolerance "
            "differences not worth flagging."
        )
    )
    within_typical_tolerance: bool = Field(
        description=(
            "True when the change is within industry-typical manufacturing "
            "or measurement tolerance for the parameter family."
        )
    )
    engineering_explanation: str = Field(
        description=(
            "One or two sentences explaining the engineering implication of "
            "the change. Reference the parameter family and what a senior "
            "reviewer would conclude."
        )
    )
    downstream_effects: list[str] = Field(
        default_factory=list,
        description=(
            "List of parameters whose correctness depends on this value and "
            "should be re-verified if this value changed. Empty if none."
        ),
    )
    confidence: float = Field(
        ge=0.0,
        le=1.0,
        description=(
            "Self-reported confidence in this judgment, in [0,1]. Use lower "
            "values when the parameter family is ambiguous or the values "
            "could be interpreted multiple ways (design vs operating)."
        ),
    )
    cited_clause_ids: list[str] = Field(
        default_factory=list,
        description=(
            "Clause IDs from the supplied 'Applicable standards' list that "
            "you cited in the engineering explanation. Must be exact matches "
            "to provided clause_id values. Leave empty when no clauses were "
            "supplied or none apply."
        ),
    )


_SYSTEM_PREAMBLE = """\
You are a senior power systems engineer reviewing a parameter mismatch \
between two engineering documents. Classify the difference's engineering \
significance using the following framework:

- "critical" — likely an outright error (decimal shifts, units confusion, \
  ratio reversals). Acting on this value could cause equipment damage or \
  protection misoperation. Example: transformer impedance 5.75% read as \
  0.575% would cause grossly incorrect short-circuit calculations.
- "major" — outside typical design tolerance for the parameter family. \
  Needs explicit explanation (RFI, engineer review). Could indicate a \
  vendor change, design revision, or transcription error.
- "minor" — outside typical manufacturing/measurement tolerance but \
  within plausible design variation. Worth a reviewer's eye but unlikely \
  to be wrong.
- "info" — within typical manufacturing or measurement tolerance per \
  applicable standard (IEEE C57.12.00, IEC 60076, etc.). Does not merit \
  attention in normal review.

Be conservative: prefer "major" when uncertain rather than over-flagging.
Always report downstream effects when the parameter family has known \
cross-discipline dependencies (e.g. transformer impedance affects \
short-circuit study, relay coordination, voltage regulation).
"""

_ONTOLOGY_BLOCK = """\
Parameter family tolerance reference (typical manufacturing tolerance):
- transformer impedance %Z: ±7.5% per IEEE C57.12.00 §9.1 Table 17
- transformer rated kVA: ±5% typical, ±10% with loading classification
- voltage ratio: ±0.5% per IEC 60076-1 §5.3
- fault current calculation: ±20% per IEEE Std 242 (Buff Book)

Decimal-shift errors (deviation ≥ 50%) are always classified as critical \
regardless of family — these are the dominant class of catastrophic design \
review failures.

Cross-discipline dependencies (incomplete list, use as guidance):
- Transformer %Z change → re-verify: short-circuit currents, relay pickup \
  settings, voltage regulation, coordination curve overlap.
- Rated kVA change → re-verify: cable ampacity sizing, breaker interrupting \
  capacity, transformer thermal loading, protection CT ratios.
- Primary voltage change → re-verify: insulation coordination (BIL), \
  surge arrester ratings, clearance requirements, conductor sizing.
- Fault current change → re-verify: relay pickup margins, breaker \
  interrupting rating, ground grid sizing.
"""


def _build_user_block(flag: Flag) -> str:
    """Compose the per-flag user-message content."""
    a_val = flag.a_record.raw_value
    b_val = flag.b_record.raw_value
    family = flag.attribute_family or "unknown"
    return (
        f"Parameter: {flag.parameter!r}\n"
        f"Attribute family: {family}\n"
        f"Authoritative document value (Doc A): {a_val}\n"
        f"Downstream document value (Doc B): {b_val}\n"
        f"Computed relative deviation: {flag.deviation_pct:.2f}%\n"
        f"Source context (Doc A span): {flag.a_record.span_text}\n"
        f"Source context (Doc B span): {flag.b_record.span_text}\n\n"
        f"Classify the significance of this difference per the framework "
        f"in your system instructions, list any downstream parameters that "
        f"should be re-verified, and provide your self-reported confidence."
    )


def _build_standards_block(flag: Flag, project_id: str | None) -> tuple[str, list[str]]:
    """Return (rendered_text, matched_clause_ids).

    Empty string + [] when no matches OR no attribute_family on the flag.
    """
    family = (flag.attribute_family or "").strip()
    if not family:
        return "", []
    matched = clauses_for(family, doc_class=None, project_id=project_id)
    if not matched:
        return "", []
    lines = [
        "",
        "## Applicable standards",
        "",
        "When writing the rationale, cite clauses from this list when they "
        "ground the engineering judgment. Reference by `source_name`. Do "
        "NOT cite clauses that aren't on this list. Use the bracketed "
        "`clause_id` in your `cited_clause_ids` response field.",
        "",
    ]
    for c in matched:
        lines.append(f"- [{c.clause_id}] {c.source_name}")
        lines.append(f"  Summary: {c.summary.strip()}")
        lines.append("")
    return "\n".join(lines), [c.clause_id for c in matched]


def _flag_id(flag: Flag) -> str:
    """Stable identifier for a flag — used as cache key material."""
    return (
        f"{flag.parameter}|{flag.a_record.doc_id}|p{flag.a_record.page}|"
        f"y{int(flag.a_record.bbox[1])}|{flag.a_record.raw_value}|"
        f"vs|{flag.b_record.doc_id}|p{flag.b_record.page}|{flag.b_record.raw_value}"
    )


def judge(
    flag: Flag,
    *,
    model: str = DEFAULT_MODEL,
    project_id: str | None = None,
) -> SignificanceJudgment:
    """Get an LLM significance judgment for one flag.

    Disk-cached on ``(flag_id, prompt_version, model, matched_clause_ids)``.
    Anthropic prompt cache (1h TTL) covers the system preamble + ontology so
    repeated calls within the same hour pay ~10% of the system-prompt token
    cost. v2 Sprint 5a — `project_id` triggers project-specific clause
    overrides; matched clause IDs are part of the cache key so registry
    growth invalidates correctly.
    """
    standards_text, matched_ids = _build_standards_block(flag, project_id)

    payload = {
        "flag_id": _flag_id(flag),
        "prompt_version": PROMPT_VERSION,
        "model": model,
        "matched_clause_ids": matched_ids,
    }

    def _compute() -> SignificanceJudgment:
        system_blocks = [
            CachedBlock(text=_SYSTEM_PREAMBLE, ttl="1h"),
            CachedBlock(text=_ONTOLOGY_BLOCK, ttl="1h"),
        ]
        user_text = _build_user_block(flag)
        if standards_text:
            user_text = user_text + standards_text
        user_blocks = [CachedBlock(text=user_text, ttl=None)]
        result, usage = call_structured(
            response_model=SignificanceJudgment,
            system_blocks=system_blocks,
            user_blocks=user_blocks,
            model=model,
        )
        cost_ledger.record(
            provider="anthropic",
            model=model,
            namespace=_CACHE_NAMESPACE,
            input_tokens=usage.get("input", 0),
            cache_read_tokens=usage.get("cache_read", 0),
            cache_creation_tokens=usage.get("cache_creation", 0),
            output_tokens=usage.get("output", 0),
            cache_ttl="1h",
        )
        return result

    value, _hit = get_or_compute(_CACHE_NAMESPACE, payload, _compute)
    return value


def judge_batch(flags: list[Flag], *, model: str = DEFAULT_MODEL) -> dict[str, SignificanceJudgment]:
    """Apply ``judge`` to a flag list. Returns ``{flag_id: judgment}``.

    Each call is independently disk-cached, so re-running on the same flags
    is free after the first pass. The Anthropic prompt cache amortizes the
    system-prompt cost across the batch.
    """
    out: dict[str, SignificanceJudgment] = {}
    for f in flags:
        out[_flag_id(f)] = judge(f, model=model)
    return out


def apply_judgment_to_flag(
    flag: Flag,
    judgment: SignificanceJudgment,
    *,
    project_id: str | None = None,
) -> Flag:
    """Return a new Flag with severity + rationale enriched from the LLM
    judgment. Authority + citation tuple are preserved verbatim.

    v2 Sprint 5a — ``project_id`` is forwarded to the clause-registry lookup
    so per-project overrides resolve to the right Clause when the LLM cited
    an overridden ID.
    """
    new_rationale = (
        f"{flag.rationale} — {judgment.engineering_explanation}"
        if judgment.engineering_explanation
        else flag.rationale
    )
    # v2 Sprint 5a — resolve cited_clause_ids → ClauseCitation tuple.
    # Hallucinated IDs (not in registry) are silently dropped.
    from interlock.llm_pipeline.schemas.clause import ClauseCitation
    from interlock.llm_pipeline.standards import (
        load_clauses, merge_project_overrides,
    )

    cited: tuple[ClauseCitation, ...] = ()
    if judgment.cited_clause_ids:
        base = load_clauses()
        clauses = (
            merge_project_overrides(base, project_id) if project_id else base
        )
        by_id = {c.clause_id: c for c in clauses}
        cited = tuple(
            to_citation(by_id[cid])
            for cid in judgment.cited_clause_ids
            if cid in by_id
        )
    return Flag(
        parameter=flag.parameter,
        authoritative_doc_id=flag.authoritative_doc_id,
        deviating_doc_id=flag.deviating_doc_id,
        a_record=flag.a_record,
        b_record=flag.b_record,
        confidence=flag.confidence * judgment.confidence,
        rationale=new_rationale,
        authority_rule=flag.authority_rule,
        severity=judgment.severity,
        deviation_pct=flag.deviation_pct,
        attribute_family=flag.attribute_family,
        pairing_confidence=flag.pairing_confidence,
        provenance=flag.provenance,
        rerank_rationale=flag.rerank_rationale,
        cited_clauses=cited,
    )
