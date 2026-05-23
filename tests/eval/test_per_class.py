"""Sprint 6 — per-class gold load + scoring tests."""

from __future__ import annotations

from pathlib import Path

from interlock.detect.mismatch import Flag
from interlock.eval.per_class import (
    GoldFlag,
    GoldPair,
    flag_matches_gold,
    load_gold_class,
    score_pair,
)
from interlock.extract.parameters import ParameterRecord


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _flag(param: str, a_raw: str, b_raw: str, conf: float = 0.9) -> Flag:
    def _rec(raw: str) -> ParameterRecord:
        return ParameterRecord(
            doc_id="d", page=1, bbox=(0, 0, 100, 10), section=None,
            span_text=raw, name=param, raw_value=raw,
            normalized_magnitude=1.0, normalized_unit="dimensionless",
        )
    return Flag(
        parameter=param,
        a_record=_rec(a_raw), b_record=_rec(b_raw),
        authoritative_doc_id="d", deviating_doc_id="d",
        confidence=conf, rationale="r", authority_rule="MVP",
        severity="major", deviation_pct=10.0,
        attribute_family="impedance_pct",
    )


def test_load_gold_class_returns_parsed(tmp_path: Path) -> None:
    p = tmp_path / "x.yaml"
    _write(p, """\
doc_class: coordination_study
pairs:
  - id: p1
    doc_a: /a.pdf
    doc_b: /b.pdf
    surfaced:
      - id: TP-1
        parameter_substr: "%Z"
        a_value_substr: "5.75"
        b_value_substr: "0.575"
    suppressed: []
""")
    gold = load_gold_class(p)
    assert gold is not None
    assert gold.doc_class == "coordination_study"
    assert len(gold.pairs) == 1
    assert gold.pairs[0].surfaced[0].id == "TP-1"


def test_load_gold_class_missing_returns_none(tmp_path: Path) -> None:
    p = tmp_path / "missing.yaml"
    assert load_gold_class(p) is None


def test_load_gold_class_parse_error_returns_none(tmp_path: Path) -> None:
    p = tmp_path / "bad.yaml"
    _write(p, "doc_class: x\npairs: this: is: not: valid")
    assert load_gold_class(p) is None


def test_flag_matches_gold_positive() -> None:
    g = GoldFlag(
        id="TP", parameter_substr="%Z",
        a_value_substr="5.75", b_value_substr="0.575",
    )
    f = _flag("%Z impedance", "5.75 %", "0.575 %")
    assert flag_matches_gold(f, g) is True


def test_flag_matches_gold_negative_on_param() -> None:
    g = GoldFlag(
        id="TP", parameter_substr="%Z",
        a_value_substr="5.75", b_value_substr="0.575",
    )
    f = _flag("Fault Current", "5.75 %", "0.575 %")
    assert flag_matches_gold(f, g) is False


def test_flag_matches_gold_negative_on_value() -> None:
    g = GoldFlag(
        id="TP", parameter_substr="%Z",
        a_value_substr="5.75", b_value_substr="0.575",
    )
    f = _flag("%Z", "5.75 %", "1.0 %")
    assert flag_matches_gold(f, g) is False


def test_score_pair_all_tp() -> None:
    gp = GoldPair(
        id="p1", doc_a="x", doc_b="y",
        surfaced=[
            GoldFlag(id="TP-1", parameter_substr="%Z",
                     a_value_substr="5.75", b_value_substr="0.575"),
        ],
        suppressed=[],
    )
    flags = [_flag("%Z", "5.75 %", "0.575 %", conf=0.9)]
    r = score_pair(gp, flags)
    assert r.tp_ids == ["TP-1"]
    assert r.fn_ids == []
    assert r.fp_ids == []


def test_score_pair_fn_when_no_match() -> None:
    gp = GoldPair(
        id="p1", doc_a="x", doc_b="y",
        surfaced=[
            GoldFlag(id="TP-1", parameter_substr="%Z",
                     a_value_substr="5.75", b_value_substr="0.575"),
        ],
        suppressed=[],
    )
    r = score_pair(gp, [])
    assert r.tp_ids == []
    assert r.fn_ids == ["TP-1"]


def test_score_pair_fp_when_suppressed_surfaces() -> None:
    gp = GoldPair(
        id="p1", doc_a="x", doc_b="y",
        surfaced=[],
        suppressed=[
            GoldFlag(id="FP-1", parameter_substr="kVA",
                     a_value_substr="150", b_value_substr="0.15"),
        ],
    )
    flags = [_flag("kVA rating", "150 kVA", "0.15 MVA", conf=0.9)]
    r = score_pair(gp, flags)
    assert r.fp_ids == ["FP-1"]


def test_score_pair_threshold_filters_low_confidence() -> None:
    gp = GoldPair(
        id="p1", doc_a="x", doc_b="y",
        surfaced=[
            GoldFlag(id="TP-1", parameter_substr="%Z",
                     a_value_substr="5.75", b_value_substr="0.575"),
        ],
        suppressed=[],
    )
    flags = [_flag("%Z", "5.75 %", "0.575 %", conf=0.4)]
    r = score_pair(gp, flags, threshold=0.6)
    # Low-conf flag is below threshold → not counted as TP → FN.
    assert r.tp_ids == []
    assert r.fn_ids == ["TP-1"]
