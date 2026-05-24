"""Emit directional flags from aligned pairs.

A Flag declares which doc is authoritative for the parameter family and which
is deviating, with citations on both sides, an assembled confidence, and an
engineering-tolerance-aware severity tier.

Severity classification (Phase 13)
----------------------------------
For numeric mismatches we compute the relative deviation between the two
magnitudes and bucket against tolerance bands per attribute family
(``detect/tolerances.py``). The ``info`` tier is suppressed by default —
those changes are within typical tolerance and don't merit reviewer time.

String-valued mismatches (part-number changes) classify as ``major`` by
default since they're not amenable to numeric tolerance reasoning but are
real engineering changes that need a reviewer's eye.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Literal

from interlock.align.exact import AlignedPair
from interlock.detect.authority import authority_for
from interlock.detect.confidence import flag_confidence
from interlock.detect.family import attribute_family_for_param_name
from interlock.detect.tolerances import Severity, classify, relative_deviation
from interlock.extract.parameters import ParameterRecord
from interlock.llm_pipeline.schemas.clause import ClauseCitation

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Flag:
    parameter: str
    authoritative_doc_id: str
    deviating_doc_id: str
    a_record: ParameterRecord
    b_record: ParameterRecord
    confidence: float
    rationale: str
    authority_rule: str
    severity: Severity = "major"  # default for back-compat with hand-built tests
    deviation_pct: float = 0.0
    attribute_family: str | None = None
    # Mirror of AlignedPair.pairing_confidence so the UI can surface
    # *why* a flag's overall confidence is what it is — "we're not sure
    # these two records describe the same thing" is a different story
    # than "we're sure they do but the value gap is small".
    pairing_confidence: float = 1.0
    # v2 Sprint 3 — provenance label derived from a_record.provenance +
    # b_record.provenance by adjudicate_flags(). Default "unknown" for
    # back-compat with hand-constructed Flags in tests; the adjudicator
    # overwrites with the right label when invoked through the pipeline.
    provenance: Literal["rule_only", "llm_only", "mixed_track", "unknown"] = "unknown"
    # v2 Sprint 4 — copied from AlignedPair.rerank_rationale by detect_flags.
    # None when the reranker didn't run or didn't approve this pair.
    rerank_rationale: str | None = None
    # v2 Sprint 5a — clauses cited by the LLM judge. Empty tuple when
    # the judge didn't run or the registry had no matches.
    cited_clauses: tuple[ClauseCitation, ...] = ()


def detect_flags(
    pairs: list[AlignedPair],
    *,
    suppress_info: bool = True,
) -> list[Flag]:
    """Convert aligned pairs into directional flags with severity tiers.

    ``suppress_info=True`` (default) drops within-tolerance changes from the
    output entirely — they don't merit reviewer attention. Set ``False`` to
    return every classified flag (useful for the suppressed-pane UI).
    """
    out: list[Flag] = []
    skipped_equivalent = 0
    skipped_info = 0
    for p in pairs:
        if p.value_equivalent:
            skipped_equivalent += 1
            continue
        # If both magnitudes are present and numerically equal, suppress
        # (defensive: equivalent() should already have caught this).
        if (
            p.a.normalized_magnitude is not None
            and p.b.normalized_magnitude is not None
            and p.a.normalized_magnitude == p.b.normalized_magnitude
        ):
            skipped_equivalent += 1
            continue

        # Classify severity via tolerance bands when both sides are numeric;
        # otherwise treat string-only mismatches as 'major' (a part-number
        # change is engineering-meaningful by construction).
        family = attribute_family_for_param_name(p.a.name)
        if (
            p.a.normalized_magnitude is not None
            and p.b.normalized_magnitude is not None
            and family is not None
        ):
            dev = relative_deviation(p.a.normalized_magnitude, p.b.normalized_magnitude)
            severity = classify(family, dev)
        elif p.a.normalized_magnitude is not None and p.b.normalized_magnitude is not None:
            # Numeric but unknown family — fall back to default bands.
            dev = relative_deviation(p.a.normalized_magnitude, p.b.normalized_magnitude)
            severity = classify("_default_unknown", dev)
        else:
            dev = 0.0
            severity = "major"

        if suppress_info and severity == "info":
            skipped_info += 1
            logger.debug(
                "detect: suppress info pair %s A=%r p%d B=%r p%d dev=%.3f%%",
                p.a.name, p.a.raw_value, p.a.page,
                p.b.raw_value, p.b.page, dev * 100 if dev else 0.0,
            )
            continue

        decision = authority_for(p.a.doc_id, p.b.doc_id, p.a.name)
        # Fold pairing_confidence into the match factor so a weak
        # correspondence (e.g. value-equality fallback) doesn't get
        # presented with the same authority as a Device-ID match.
        conf = flag_confidence(
            extraction=1.0,
            match=p.name_match_confidence * p.pairing_confidence,
            authority=decision.confidence,
        )
        logger.debug(
            "detect: FLAG %s sev=%s dev=%.3f%% conf=%.2f A=%r p%d B=%r p%d "
            "rule=%s family=%s",
            p.a.name, severity, dev * 100 if dev else 0.0, conf,
            p.a.raw_value, p.a.page, p.b.raw_value, p.b.page,
            decision.rule, family,
        )
        out.append(
            Flag(
                parameter=p.a.name,
                authoritative_doc_id=decision.authoritative_doc_id,
                deviating_doc_id=decision.deviating_doc_id,
                a_record=p.a,
                b_record=p.b,
                confidence=conf,
                rationale=(
                    f"{p.a.raw_value} (authoritative, p{p.a.page}) "
                    f"≠ {p.b.raw_value} (deviation, p{p.b.page})"
                ),
                authority_rule=decision.rule,
                severity=severity,
                deviation_pct=dev,
                attribute_family=family,
                pairing_confidence=p.pairing_confidence,
                rerank_rationale=p.rerank_rationale,
            )
        )
    logger.info(
        "detect: emitted %d flags (suppressed equivalent=%d info=%d) from %d pairs",
        len(out), skipped_equivalent, skipped_info, len(pairs),
    )
    return out
