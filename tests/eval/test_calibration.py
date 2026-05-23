"""Sprint 6 — confidence calibration tests."""

from __future__ import annotations

from interlock.detect.mismatch import Flag
from interlock.eval.calibration import calibrate, render_markdown
from interlock.extract.parameters import ParameterRecord


def _flag(conf: float) -> Flag:
    def _rec() -> ParameterRecord:
        return ParameterRecord(
            doc_id="d", page=1, bbox=(0, 0, 100, 10), section=None,
            span_text="x", name="P", raw_value="1 A",
            normalized_magnitude=1.0, normalized_unit="ampere",
        )
    return Flag(
        parameter="P", a_record=_rec(), b_record=_rec(),
        authoritative_doc_id="d", deviating_doc_id="d",
        confidence=conf, rationale="r", authority_rule="MVP",
        severity="major", deviation_pct=0.0,
    )


def test_calibrate_empty_returns_zeros() -> None:
    r = calibrate([])
    assert r.brier_score == 0.0
    assert r.n == 0
    assert r.bins == []


def test_calibrate_perfect_predictions_brier_zero() -> None:
    """Confidence 1.0 + is_tp=True, confidence 0.0 + is_tp=False → Brier=0."""
    labeled = [(_flag(1.0), True), (_flag(0.0), False)]
    r = calibrate(labeled)
    assert r.brier_score == 0.0


def test_calibrate_worst_predictions_brier_one() -> None:
    """Confidence 1.0 + is_tp=False, conf 0.0 + tp=True → Brier=1 (worst)."""
    labeled = [(_flag(1.0), False), (_flag(0.0), True)]
    r = calibrate(labeled)
    assert r.brier_score == 1.0


def test_calibrate_bins_into_deciles() -> None:
    """10 bins; flag at 0.55 lands in bin index 5."""
    labeled = [(_flag(0.55), True), (_flag(0.95), True), (_flag(0.05), False)]
    r = calibrate(labeled, n_bins=10)
    assert len(r.bins) == 10
    # Find bins with non-zero count.
    nonzero = [b for b in r.bins if b.count > 0]
    assert len(nonzero) == 3
    # 0.55 → bin 5 (lo=0.5, hi=0.6)
    bin5 = r.bins[5]
    assert bin5.count == 1
    assert abs(bin5.predicted_avg - 0.55) < 1e-9
    assert bin5.observed_rate == 1.0


def test_calibrate_bin_count_and_observed_rate() -> None:
    """3 flags in same bin: 2 TPs → observed_rate 2/3."""
    labeled = [
        (_flag(0.85), True),
        (_flag(0.88), True),
        (_flag(0.82), False),
    ]
    r = calibrate(labeled)
    bin8 = r.bins[8]  # lo=0.8 hi=0.9
    assert bin8.count == 3
    assert abs(bin8.observed_rate - (2 / 3)) < 1e-9


def test_calibrate_confidence_at_one_lands_in_last_bin() -> None:
    """conf=1.0 → bin 9 (lo=0.9 hi=1.0), not over-flowed."""
    r = calibrate([(_flag(1.0), True)])
    bin9 = r.bins[9]
    assert bin9.count == 1


def test_render_markdown_emits_table() -> None:
    r = calibrate([(_flag(0.95), True), (_flag(0.55), False)])
    md = render_markdown(r)
    assert "# Confidence Calibration" in md
    assert "Brier score" in md
    assert "| Bin | Count |" in md


def test_render_markdown_marks_insufficient_sample() -> None:
    r = calibrate([(_flag(0.55), True)])
    md = render_markdown(r)
    assert "_(insufficient sample)_" in md
