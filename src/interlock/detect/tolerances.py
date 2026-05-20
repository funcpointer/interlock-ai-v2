"""Per-attribute engineering tolerance bands.

These values bridge "values differ" to "this is engineering-meaningful." The
classifier turns a relative deviation percent into a severity tier:

  critical — likely an outright error (decimal shift, units mistake)
  major    — outside design tolerance, requires explanation
  minor    — outside manufacturing tolerance, worth a reviewer's eye
  info     — within typical tolerance; suppressed from the default flag list

Sources are cited inline. Production deployments will override these per-
project from internal engineering standards; the values shipped here are
industry-typical defaults appropriate for a generic transformer + protection-
coordination context.

Citation conventions:
- "IEEE C57.12.00" refers to "IEEE Standard for General Requirements for Liquid-
  Immersed Distribution, Power, and Regulating Transformers" (IEEE C57.12.00-2015).
- "IEC 60076-1" refers to "Power transformers — Part 1: General" (IEC 60076-1:2011).
- Industry-typical defaults are flagged where standards underspecify.
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


def classify(attribute_family: str, deviation_pct: float) -> Severity:
    """Bucket a relative deviation into a severity tier.

    deviation_pct is expected to be the output of ``relative_deviation``
    (i.e. percent, where 50.0 means "half-magnitude difference").
    """
    band = TOLERANCE_TABLE.get(attribute_family, _DEFAULT_BAND)
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
