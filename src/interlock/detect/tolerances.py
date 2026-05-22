"""Per-attribute engineering tolerance bands.

These values bridge "values differ" to "this is engineering-meaningful." The
classifier turns a relative deviation percent into a severity tier:

  critical — likely an outright error (decimal shift, units mistake)
  major    — outside design tolerance, requires explanation
  minor    — outside manufacturing tolerance, worth a reviewer's eye
  info     — within typical tolerance; suppressed from the default flag list


HONEST CAVEAT — TOLERANCE BANDS ARE STARTING DEFAULTS, NOT ABSOLUTE TRUTH
========================================================================

The numeric thresholds shipped in this module are **industry-typical
defaults** appropriate for a generic transformer + protection-coordination
context, sourced from published standards. They are deliberately
conservative starting points. They are **not** the right values for every
project.

In real deployments, tolerance bands depend on:

1. **The applicable standard edition.** IEEE C57.12.00 has revised tolerance
   tables across 2006 / 2010 / 2015 / 2022 editions; IEC 60076 has its own
   cadence. The values that govern a project are those named in its design
   basis document, not the latest revision of the standard.
2. **The owner's internal engineering standards.** Utilities like AES often
   maintain internal "AES-STD-XXX" documents that tighten or relax tolerances
   relative to industry standards based on operating experience and risk
   posture.
3. **The equipment class and vintage.** A 1980s legacy transformer has
   different acceptance tolerances than a new manufacturer-issued unit.
   Nuclear-grade is tighter than utility-scale solar.
4. **The discipline and review phase.** At 30 % review, larger drift is
   acceptable because design is fluid; at 90 % and IFC, the bar tightens
   because changes propagate downstream.
5. **The risk posture of the asset.** A 5 % impedance drift on a station
   service transformer is different from the same drift on a generator
   step-up transformer feeding the grid.

The hardcoded values here are intentionally a **single, defensible, public-
source baseline** so the system has a working classifier out of the box for
demos and small-project use. They are explicitly not the answer for AES-grade
production review.

The platform path (see docs/BACKLOG.md → Phase 17) makes tolerances:
- per-project configurable from a YAML / SQLite config
- per-attribute-family overridable at session start
- reviewer-amendable mid-session with audit trail
- backed by an editable "tolerance ontology" the reviewer team owns

Until then, the override hooks below let a caller swap the defaults at
runtime without forking the module. The shipped values cite their public
sources so reviewers can argue with the numbers rather than guess at them.


Citation conventions:
- "IEEE C57.12.00" — IEEE Standard for General Requirements for Liquid-
  Immersed Distribution, Power, and Regulating Transformers (2015 ed unless
  otherwise noted).
- "IEC 60076-1" — Power transformers — Part 1: General (2011 ed).
- "IEEE Std 242" — IEEE Recommended Practice for Protection and Coordination
  of Industrial and Commercial Power Systems (Buff Book).
- "NEMA TR 1" — Transformers, Step Voltage Regulators, and Reactors.
- "industry-typical" — flagged where a quantitative band is not pinned by a
  standard; backed by common review-practice norms, not published tables.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Severity = Literal["critical", "major", "minor", "info"]


@dataclass(frozen=True)
class ToleranceBand:
    """A four-tier tolerance band per attribute family.

    Thresholds are *relative deviation in percent*. A reading 8% above
    the reference falls into the band whose ``rel_tolerance_pct < 8 <=
    rel_major_pct`` and classifies as minor; above ``rel_major_pct`` is
    major; above ``rel_critical_pct`` is critical.
    """

    attribute_family: str
    rel_tolerance_pct: float
    rel_major_pct: float
    rel_critical_pct: float
    source: str


# Source citation legend:
#
# [IEEE-C57] IEEE C57.12.00-2015 §9.1 Table 17 — transformer impedance
#            tolerance is ±7.5% of nameplate for two-winding transformers.
# [IEC-60076] IEC 60076-1:2011 §5.3 — voltage ratio tolerance is the smaller
#             of ±0.5% or 1/10 of the impedance percentage.
# [IEEE-C57-§5.10] IEEE C57.12.00-2015 §5.10 — kVA rating tolerance ±10%
#             accounting for loading classifications.
# [NEMA-TR-1] NEMA TR 1-2013 — corroborates IEEE C57 transformer ratings.
# [industry-typical] Where the standard is silent on a quantitative band,
#             we use industry-common practice; flagged in source string.
#
# Decimal-shift errors land at 50%+ deviation regardless of family — that
# threshold is consistent across all bands and is the canonical AES anecdote
# (transformer impedance 5.75% misread as 0.575%).

TOLERANCE_TABLE: dict[str, ToleranceBand] = {
    "impedance_pct": ToleranceBand(
        attribute_family="impedance_pct",
        rel_tolerance_pct=7.5,
        rel_major_pct=20.0,
        rel_critical_pct=50.0,
        source="IEEE C57.12.00-2015 §9.1 Table 17 (±7.5% impedance tolerance)",
    ),
    "rated_power_kva": ToleranceBand(
        attribute_family="rated_power_kva",
        rel_tolerance_pct=5.0,
        rel_major_pct=10.0,
        rel_critical_pct=50.0,
        source="IEEE C57.12.00-2015 §5.10 (rated kVA tolerance); NEMA TR 1-2013",
    ),
    "voltage_kv": ToleranceBand(
        attribute_family="voltage_kv",
        rel_tolerance_pct=0.5,
        rel_major_pct=5.0,
        rel_critical_pct=50.0,
        source="IEC 60076-1:2011 §5.3 (voltage ratio ±0.5%); IEEE C57.12.00-2015 §5.7",
    ),
    "fault_current_a": ToleranceBand(
        attribute_family="fault_current_a",
        rel_tolerance_pct=5.0,
        rel_major_pct=20.0,
        rel_critical_pct=50.0,
        source="industry-typical; IEEE Std 242-2001 (Buff Book) recommends ±20% for "
        "short-circuit study inputs (see BACKLOG Phase 17 standards-as-authority)",
    ),
}


# Fallback band when an unknown attribute family is classified. Broad enough
# to still catch decimal-shift errors as critical while staying loose enough
# that we don't spuriously alarm on small deviations.
_DEFAULT_BAND = ToleranceBand(
    attribute_family="_default",
    rel_tolerance_pct=1.0,
    rel_major_pct=10.0,
    rel_critical_pct=50.0,
    source="default fallback (unknown attribute family)",
)


# Runtime overrides — populated by ``set_tolerance_overrides`` so a caller
# (e.g. a Streamlit session, a CLI flag, a per-project YAML loader) can
# replace any subset of the shipped defaults without forking this module.
# Override entries take precedence over TOLERANCE_TABLE in ``classify``.
_OVERRIDES: dict[str, ToleranceBand] = {}


def set_tolerance_overrides(overrides: dict[str, ToleranceBand]) -> None:
    """Replace zero or more shipped tolerance bands at runtime.

    Pass the family name as the key. Calling with ``{}`` clears all
    overrides. The shipped ``TOLERANCE_TABLE`` is never mutated; the
    overrides live in a separate map consulted first by ``classify``.

    Example::

        from interlock.detect.tolerances import set_tolerance_overrides, ToleranceBand
        # AES project standard tightens transformer impedance to ±5 %.
        set_tolerance_overrides({
            "impedance_pct": ToleranceBand(
                attribute_family="impedance_pct",
                rel_tolerance_pct=5.0,
                rel_major_pct=15.0,
                rel_critical_pct=50.0,
                source="AES-STD-XYZ §4.2 (tighter than IEEE C57.12.00)",
            ),
        })
    """
    global _OVERRIDES
    _OVERRIDES = dict(overrides)


def active_tolerance_band(attribute_family: str) -> ToleranceBand:
    """Return the band currently in effect for an attribute family.

    Override (if set) wins over shipped default. If neither maps the family,
    returns the broad fallback band.
    """
    if attribute_family in _OVERRIDES:
        return _OVERRIDES[attribute_family]
    return TOLERANCE_TABLE.get(attribute_family, _DEFAULT_BAND)


# v2 Sprint 1: per-class tolerance overrides. Concrete entries for 3
# classes; other 5 (and DocClass.unknown) inherit TOLERANCE_TABLE via
# fallback chain. When the caller does not pass doc_class, behaviour
# is bit-identical to v1.5-mvp-ready.
from interlock.llm_pipeline.schemas.doc_class import DocClass  # noqa: E402

DOC_CLASS_TOLERANCE_OVERRIDES: dict[DocClass, dict[str, ToleranceBand]] = {
    DocClass.equipment_spec: {
        "impedance_pct": ToleranceBand(
            attribute_family="impedance_pct",
            rel_tolerance_pct=5.0, rel_major_pct=15.0, rel_critical_pct=40.0,
            source="IEEE C57.12.00-2015 §9.1 (tightened for nameplate)",
        ),
        "rated_power_kva": ToleranceBand(
            attribute_family="rated_power_kva",
            rel_tolerance_pct=2.5, rel_major_pct=7.5, rel_critical_pct=30.0,
            source="IEEE C57.12.00-2015 §5.10 + NEMA TR 1 (tightened for nameplate)",
        ),
    },
    DocClass.relay_setting_sheet: {
        "fault_current_a": ToleranceBand(
            attribute_family="fault_current_a",
            rel_tolerance_pct=5.0, rel_major_pct=15.0, rel_critical_pct=40.0,
            source="IEEE Std 242 (Buff Book) §10.5",
        ),
    },
    DocClass.coordination_study: {
        # Explicit empty entry so the routing path is audit-visible; falls
        # through to TOLERANCE_TABLE for every family.
    },
}


def classify(
    attribute_family: str,
    deviation_pct: float,
    doc_class: DocClass | None = None,
) -> Severity:
    """Bucket a relative deviation into a severity tier.

    deviation_pct is expected to be the output of ``relative_deviation``
    (i.e. percent, where 50.0 means "half-magnitude difference").

    When ``doc_class`` is provided and the class has an override in
    ``DOC_CLASS_TOLERANCE_OVERRIDES`` for this family, the override band
    wins. Falls back to runtime ``_OVERRIDES`` and TOLERANCE_TABLE for
    DocClass.unknown, missing class entries, or doc_class=None — the
    v1 default path.
    """
    band: ToleranceBand | None = None
    if doc_class is not None and doc_class != DocClass.unknown:
        per_class = DOC_CLASS_TOLERANCE_OVERRIDES.get(doc_class)
        if per_class is not None:
            band = per_class.get(attribute_family)
    if band is None:
        band = active_tolerance_band(attribute_family)
    if deviation_pct >= band.rel_critical_pct:
        return "critical"
    if deviation_pct >= band.rel_major_pct:
        return "major"
    if deviation_pct >= band.rel_tolerance_pct:
        return "minor"
    return "info"


def relative_deviation(a: float, b: float) -> float:
    """Relative deviation of two scalar magnitudes, in percent.

    Uses the larger magnitude as the denominator so the metric is symmetric
    and well-defined when one side is zero. Returns 0.0 only when both
    sides are exactly zero.
    """
    if a == 0.0 and b == 0.0:
        return 0.0
    base = max(abs(a), abs(b))
    if base == 0.0:
        return 0.0
    return abs(a - b) / base * 100.0
