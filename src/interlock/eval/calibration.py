"""Sprint 6 — confidence calibration.

Bins flags by predicted confidence into deciles; computes the observed
true-positive rate per bin. Brier score = mean((conf - is_tp)^2). Lower
is better; 0 = perfect calibration; 0.25 = no-better-than-random on a
50/50 base rate.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from interlock.detect.mismatch import Flag


@dataclass(frozen=True)
class CalibrationBin:
    lo: float
    hi: float
    count: int
    predicted_avg: float
    observed_rate: float


@dataclass(frozen=True)
class CalibrationReport:
    brier_score: float
    n: int
    bins: list[CalibrationBin] = field(default_factory=list)


def calibrate(
    labeled: list[tuple[Flag, bool]],
    *,
    n_bins: int = 10,
) -> CalibrationReport:
    """Compute Brier + reliability bins.

    Each tuple is (flag, is_true_positive). Empty input → zeros + no bins.
    """
    if not labeled:
        return CalibrationReport(brier_score=0.0, n=0, bins=[])

    # Brier
    brier = sum(
        (f.confidence - (1.0 if tp else 0.0)) ** 2 for f, tp in labeled
    ) / len(labeled)

    # Bin
    bin_data: dict[int, list[tuple[float, bool]]] = {i: [] for i in range(n_bins)}
    for f, tp in labeled:
        c = max(0.0, min(1.0, f.confidence))
        idx = min(n_bins - 1, int(c * n_bins))
        bin_data[idx].append((c, tp))

    bins: list[CalibrationBin] = []
    for i in range(n_bins):
        lo = i / n_bins
        hi = (i + 1) / n_bins
        entries = bin_data[i]
        if not entries:
            bins.append(CalibrationBin(
                lo=lo, hi=hi, count=0,
                predicted_avg=0.0, observed_rate=0.0,
            ))
            continue
        predicted_avg = sum(c for c, _ in entries) / len(entries)
        observed_rate = sum(1 for _, tp in entries if tp) / len(entries)
        bins.append(CalibrationBin(
            lo=lo, hi=hi, count=len(entries),
            predicted_avg=predicted_avg, observed_rate=observed_rate,
        ))

    return CalibrationReport(brier_score=brier, n=len(labeled), bins=bins)


def render_markdown(report: CalibrationReport) -> str:
    """Render the report as a human-readable Markdown table."""
    lines = [
        "# Confidence Calibration",
        "",
        f"**Sample size:** {report.n}",
        f"**Brier score:** {report.brier_score:.4f} "
        f"(lower = better; 0 = perfect, 0.25 = random)",
        "",
        "| Bin | Count | Predicted (avg) | Observed (TP rate) | Diff |",
        "|---|---:|---:|---:|---:|",
    ]
    for b in report.bins:
        bin_label = f"{b.lo:.1f}–{b.hi:.1f}"
        if b.count == 0:
            lines.append(f"| {bin_label} | 0 | — | — | — |")
            continue
        diff = b.observed_rate - b.predicted_avg
        sign = "+" if diff >= 0 else ""
        flag = ""
        if b.count < 5:
            flag = " _(insufficient sample)_"
        lines.append(
            f"| {bin_label} | {b.count} | {b.predicted_avg:.2f} | "
            f"{b.observed_rate:.2f} | {sign}{diff:+.2f}{flag} |"
        )
    return "\n".join(lines) + "\n"
