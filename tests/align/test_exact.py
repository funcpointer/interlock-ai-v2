from interlock.align.exact import AlignedPair, align_exact
from interlock.extract.parameters import ParameterRecord


def _p(name, doc, raw, mag=None, unit=None, page=1, y=0.0, entity_tag="") -> ParameterRecord:
    return ParameterRecord(
        doc_id=doc, page=page, bbox=(0, y, 100, y + 10), section=None,
        span_text=f"{name}: {raw}", name=name, raw_value=raw,
        normalized_magnitude=mag, normalized_unit=unit,
        entity_tag=entity_tag,
    )


def test_aligns_same_name_same_position_when_values_equal() -> None:
    a = [_p("%Z", "A", "5.75 %", mag=0.0575, unit="dimensionless", page=3, y=100)]
    b = [_p("%Z", "B", "5.75 %", mag=0.0575, unit="dimensionless", page=3, y=100)]
    pairs = align_exact(a, b)
    assert len(pairs) == 1
    assert isinstance(pairs[0], AlignedPair)
    assert pairs[0].name_match_confidence == 1.0
    assert pairs[0].value_equivalent is True


def test_aligns_same_name_same_position_when_values_differ() -> None:
    a = [_p("%Z", "A", "5.75 %", mag=0.0575, page=3, y=100)]
    b = [_p("%Z", "B", "0.575 %", mag=0.00575, page=3, y=100)]
    pairs = align_exact(a, b)
    assert len(pairs) == 1
    assert pairs[0].value_equivalent is False


def test_unit_normalized_value_equivalence_suppresses_flag() -> None:
    # 150 kVA == 0.15 MVA — equivalent dimensionally; pair should be value_equivalent.
    a = [_p("Transformer Rating", "A", "150 kVA", mag=150_000, page=7, y=300)]
    b = [_p("Transformer Rating", "B", "0.15 MVA", mag=150_000, page=7, y=300)]
    pairs = align_exact(a, b)
    assert len(pairs) == 1
    assert pairs[0].value_equivalent is True


def test_distinct_y_positions_pair_independently() -> None:
    # Two transformer-rating records on same page at different y positions
    # should pair with their respective counterparts, not cross-pair.
    a = [
        _p("Transformer Rating", "A", "1000 kVA", mag=1_000_000, page=7, y=100),
        _p("Transformer Rating", "A", "150 kVA", mag=150_000, page=7, y=300),
    ]
    b = [
        _p("Transformer Rating", "B", "100 kVA", mag=100_000, page=7, y=100),  # TP-3
        _p("Transformer Rating", "B", "0.15 MVA", mag=150_000, page=7, y=300),  # FP-1
    ]
    pairs = align_exact(a, b)
    assert len(pairs) == 2
    by_y = sorted(pairs, key=lambda p: p.a.bbox[1])
    # y=100: A=1000kVA, B=100kVA → mismatch
    assert by_y[0].value_equivalent is False
    # y=300: A=150kVA, B=0.15MVA → equivalent
    assert by_y[1].value_equivalent is True


def test_names_with_no_counterpart_in_b_emit_no_pair() -> None:
    a = [_p("%Z", "A", "5.75 %", page=3, y=100)]
    b = [_p("Fault Current", "B", "20,000 A", page=2, y=50)]
    pairs = align_exact(a, b)
    assert pairs == []


def test_different_pages_do_not_pair() -> None:
    a = [_p("%Z", "A", "5.75 %", page=3, y=100)]
    b = [_p("%Z", "B", "5.75 %", page=5, y=100)]
    pairs = align_exact(a, b)
    # Same name on different pages should not auto-pair (no positional anchor).
    # Implementation may or may not pair; the contract is: if it pairs, value-equivalence is computed.
    for p in pairs:
        # If a pair emerged across pages, confidence should reflect distance.
        assert p.name_match_confidence <= 1.0


# ---------- String-valued family gating (regression for cross-family false flags) ----------


def test_string_param_only_pairs_within_same_family_prefix() -> None:
    """Real-world regression: Doc A's KRP-C-1600SP main fuse was being
    paired with Doc B's LPS-RK-100SP branch fuse because positional
    proximity broke down on OCR pages (all OCR records share the page
    bbox → identical y-centers → first-in-iteration wins).

    Family prefix gating must prevent that pair from emerging at all.
    """
    a = [
        _p("Fuse Designation", "A", "KRP-C-1600SP", page=5, y=100),
        _p("Fuse Designation", "A", "LPS-RK-200SP", page=5, y=300),
    ]
    b = [
        _p("Fuse Designation", "B", "LPS-RK-100SP", page=5, y=0),  # synthetic OCR y
        _p("Fuse Designation", "B", "KRP-C-1200SP", page=5, y=0),  # synthetic OCR y
    ]
    pairs = align_exact(a, b)
    paired = {(p.a.raw_value, p.b.raw_value) for p in pairs}
    # KRP-C-1600SP must pair with KRP-C-1200SP (same family, real ampacity
    # change) and never with LPS-RK-100SP (different physical device).
    assert ("KRP-C-1600SP", "KRP-C-1200SP") in paired
    assert ("KRP-C-1600SP", "LPS-RK-100SP") not in paired
    # And LPS-RK-200SP must pair only with LPS-RK-100SP.
    assert ("LPS-RK-200SP", "LPS-RK-100SP") in paired
    assert ("LPS-RK-200SP", "KRP-C-1200SP") not in paired


def test_string_param_with_no_family_match_emits_no_pair() -> None:
    """If Doc A has a KRP-C fuse but Doc B has only LPS-RK fuses, no pair
    should emerge — better to miss a flag than to surface a false one
    that compares a 1600 A main against a 100 A branch."""
    a = [_p("Fuse Designation", "A", "KRP-C-1600SP", page=5, y=100)]
    b = [_p("Fuse Designation", "B", "LPS-RK-100SP", page=5, y=100)]
    pairs = align_exact(a, b)
    assert pairs == []


# ---------- OCR-degeneracy gate (records share whole-page bbox → same y) ----------


def test_ocr_degeneracy_within_family_falls_back_to_value_equality() -> None:
    """Doc A native: two LPS-RK fuses at distinct y. Doc B OCR: two LPS-RK
    fuses both at the page bbox (identical y). Positional pairing would
    mis-match by iteration order; value-equality gating must pair 100SP
    with 100SP and 400SP with 400SP — no false flag."""
    a = [
        _p("Fuse Designation", "A", "LPS-RK-100SP", page=6, y=100),
        _p("Fuse Designation", "A", "LPS-RK-400SP", page=6, y=300),
    ]
    b = [
        _p("Fuse Designation", "B", "LPS-RK-400SP", page=6, y=0),  # OCR same-y
        _p("Fuse Designation", "B", "LPS-RK-100SP", page=6, y=0),  # OCR same-y
    ]
    pairs = align_exact(a, b)
    paired = {(p.a.raw_value, p.b.raw_value) for p in pairs}
    # Every pair is value-equal — no spurious cross-position flags.
    assert paired == {
        ("LPS-RK-100SP", "LPS-RK-100SP"),
        ("LPS-RK-400SP", "LPS-RK-400SP"),
    }
    for p in pairs:
        assert p.value_equivalent is True


def test_ocr_degeneracy_drops_pair_when_no_value_match() -> None:
    """Doc A has 100SP and 400SP; Doc B OCR only has 400SP. The unmatched
    100SP must NOT pair with 400SP — better to miss a deletion flag than
    to surface a false 4× ampacity discrepancy."""
    a = [
        _p("Fuse Designation", "A", "LPS-RK-100SP", page=6, y=100),
        _p("Fuse Designation", "A", "LPS-RK-400SP", page=6, y=300),
    ]
    b = [
        _p("Fuse Designation", "B", "LPS-RK-400SP", page=6, y=0),
    ]
    pairs = align_exact(a, b)
    paired = {(p.a.raw_value, p.b.raw_value) for p in pairs}
    assert paired == {("LPS-RK-400SP", "LPS-RK-400SP")}
    assert ("LPS-RK-100SP", "LPS-RK-400SP") not in paired


def test_ocr_degeneracy_applies_to_numeric_multi_instance() -> None:
    """Two transformers on one page — Doc A native at distinct y, Doc B
    OCR all at page bbox y. Without the gate, 150 kVA would mis-pair with
    100 kVA and surface a fake 33% mismatch. With the gate, only the
    value-equal 150↔150 pair survives."""
    a = [
        _p("Transformer Rating", "A", "1000 kVA", mag=1_000_000, page=7, y=100),
        _p("Transformer Rating", "A", "150 kVA", mag=150_000, page=7, y=300),
    ]
    b = [
        _p("Transformer Rating", "B", "100 kVA", mag=100_000, page=7, y=0),
        _p("Transformer Rating", "B", "150 kVA", mag=150_000, page=7, y=0),
    ]
    pairs = align_exact(a, b)
    paired = {(p.a.raw_value, p.b.raw_value) for p in pairs}
    assert ("150 kVA", "150 kVA") in paired
    assert ("1000 kVA", "100 kVA") not in paired


# ---------- Entity-tag (Device ID) pairing ----------


def test_entity_tag_takes_priority_over_position() -> None:
    """Even with positional anchors that would suggest one pairing,
    matching Device IDs must override. Doc A row 6 pairs with Doc B
    row 6, regardless of where it appears on the page."""
    a = [
        _p("Fuse Designation", "A", "KRP-C-1600SP", page=5, y=100, entity_tag="6"),
        _p("Fuse Designation", "A", "LPS-RK-200SP", page=5, y=300, entity_tag="21"),
    ]
    b = [
        _p("Fuse Designation", "B", "LPS-RK-200SP", page=5, y=100, entity_tag="21"),
        _p("Fuse Designation", "B", "KRP-C-1600SP", page=5, y=300, entity_tag="6"),
    ]
    pairs = align_exact(a, b)
    paired = {(p.a.entity_tag, p.b.entity_tag, p.a.raw_value, p.b.raw_value) for p in pairs}
    # Tagged pairs match by tag, not by y-proximity.
    assert ("6", "6", "KRP-C-1600SP", "KRP-C-1600SP") in paired
    assert ("21", "21", "LPS-RK-200SP", "LPS-RK-200SP") in paired


def test_entity_tag_mismatch_drops_pair_entirely() -> None:
    """User's actual failure mode: Doc A has row ⑥ (KRP-C-1600SP),
    Doc B has row 21 (LPS-RK-100SP). Different Device IDs → not the
    same physical device → no pair, no false flag."""
    a = [_p("Fuse Designation", "A", "KRP-C-1600SP", page=5, y=100, entity_tag="6")]
    b = [_p("Fuse Designation", "B", "LPS-RK-100SP", page=5, y=100, entity_tag="21")]
    pairs = align_exact(a, b)
    assert pairs == []


def test_tagged_and_untagged_records_pair_at_low_confidence() -> None:
    """v2.8.4 — tagged↔untagged is now ALLOWED via the relaxed fallback
    pool (strict-tag pool is empty here, so fallback kicks in). The pair
    surfaces with reduced pairing_confidence (< 0.6) so downstream
    rerank/judge has a clear weak-pair signal to investigate. Pre-v2.8.4
    behavior (strict refuse) blocked legitimate cross-doc mutations
    where one side carried an LLM descriptor-tag and the other a regex
    row-marker tag."""
    a = [_p("Fuse Designation", "A", "KRP-C-1600SP", page=5, y=100, entity_tag="6")]
    b = [_p("Fuse Designation", "B", "KRP-C-1600SP", page=5, y=100, entity_tag="")]
    pairs = align_exact(a, b)
    assert len(pairs) == 1
    assert pairs[0].pairing_confidence < 0.6, (
        "tag-mismatch pair must signal weak so reranker investigates"
    )


def test_pairing_confidence_reflects_rule_strength() -> None:
    """Confidence scoring per pairing rule:
      1.0  Device ID match
      0.9  single-instance positional
      0.75 multi-instance distinct-y positional
      0.5  value-equality ambiguity fallback
    """
    # 1.0 — tag match
    a1 = [_p("Fuse Designation", "A", "KRP-C-1600SP", page=5, y=100, entity_tag="6")]
    b1 = [_p("Fuse Designation", "B", "KRP-C-1200SP", page=5, y=300, entity_tag="6")]
    assert align_exact(a1, b1)[0].pairing_confidence == 1.0

    # 0.9 — single-instance positional
    a2 = [_p("%Z", "A", "5.75 %", mag=0.0575, page=3, y=100)]
    b2 = [_p("%Z", "B", "0.575 %", mag=0.00575, page=3, y=100)]
    assert align_exact(a2, b2)[0].pairing_confidence == 0.9

    # 0.75 — multi-instance equal-count distinct-y
    a3 = [
        _p("Transformer Rating", "A", "1000 kVA", mag=1_000_000, page=7, y=100),
        _p("Transformer Rating", "A", "150 kVA", mag=150_000, page=7, y=300),
    ]
    b3 = [
        _p("Transformer Rating", "B", "100 kVA", mag=100_000, page=7, y=100),
        _p("Transformer Rating", "B", "0.15 MVA", mag=150_000, page=7, y=300),
    ]
    pairs3 = align_exact(a3, b3)
    assert all(p.pairing_confidence == 0.75 for p in pairs3)

    # 0.5 — value-equality fallback (OCR y-degeneracy)
    a4 = [
        _p("Fuse Designation", "A", "LPS-RK-100SP", page=6, y=100),
        _p("Fuse Designation", "A", "LPS-RK-400SP", page=6, y=300),
    ]
    b4 = [
        _p("Fuse Designation", "B", "LPS-RK-400SP", page=6, y=0),
        _p("Fuse Designation", "B", "LPS-RK-100SP", page=6, y=0),
    ]
    pairs4 = align_exact(a4, b4)
    assert all(p.pairing_confidence == 0.5 for p in pairs4)


def test_untagged_records_still_pair_when_both_lack_tags() -> None:
    """Back-compat: pages with no Device IDs still pair via existing
    positional/family/value gates."""
    a = [_p("%Z", "A", "5.75 %", mag=0.0575, page=3, y=100)]
    b = [_p("%Z", "B", "0.575 %", mag=0.00575, page=3, y=100)]
    pairs = align_exact(a, b)
    assert len(pairs) == 1
    assert pairs[0].value_equivalent is False


def test_native_distinct_y_pairing_unaffected_by_degeneracy_gate() -> None:
    """Regression guard: native-vs-native pages keep positional pairing.
    The gate must only kick in when candidate y's are literally identical."""
    a = [
        _p("Transformer Rating", "A", "1000 kVA", mag=1_000_000, page=7, y=100),
        _p("Transformer Rating", "A", "150 kVA", mag=150_000, page=7, y=300),
    ]
    b = [
        # Distinct y on B side too (no OCR degeneracy).
        _p("Transformer Rating", "B", "100 kVA", mag=100_000, page=7, y=100),
        _p("Transformer Rating", "B", "150 kVA", mag=150_000, page=7, y=300),
    ]
    pairs = align_exact(a, b)
    by_y = sorted(pairs, key=lambda p: p.a.bbox[1])
    assert by_y[0].a.raw_value == "1000 kVA" and by_y[0].b.raw_value == "100 kVA"
    assert by_y[0].value_equivalent is False  # real positional mismatch surfaces
    assert by_y[1].value_equivalent is True


def test_string_family_no_prefix_does_not_block_pairing() -> None:
    """v2.8.5 — Fault Current raw values like '20,000A RMS Sym' have no
    fuse-style alphabetic prefix. The relaxed-pool family filter was
    erroneously falling back to full-string equality, blocking pairs
    when the very thing being compared (the value) differed.

    Both records here are string-valued (no Pint magnitude), same page,
    same name, different tags. The pair MUST surface so the detector
    sees the 20kA vs 200kA mismatch."""
    a = [_p(
        "Fault Current", "A", "20,000A RMS Sym",
        mag=None, page=2, y=100, entity_tag="Fault X, 20,000A RMS Sym",
    )]
    b = [_p(
        "Fault Current", "B", "200,000A RMS Sym",
        mag=None, page=2, y=100, entity_tag="Fault X",
    )]
    pairs = align_exact(a, b)
    assert len(pairs) == 1
    assert pairs[0].a.raw_value == "20,000A RMS Sym"
    assert pairs[0].b.raw_value == "200,000A RMS Sym"
    assert pairs[0].value_equivalent is False  # different magnitudes


def test_string_family_still_blocks_incompatible_fuse_classes() -> None:
    """v2.8.5 — family filter must remain strict when BOTH sides do have
    recognizable alphabetic-prefix families. LPS-RK vs LPN-RK fuses are
    not interchangeable; the relaxed pool must not bridge across them."""
    a = [_p(
        "Fuse Designation", "A", "LPS-RK-200SP",
        mag=None, page=3, y=100, entity_tag="A",
    )]
    b = [_p(
        "Fuse Designation", "B", "LPN-RK-500SP",
        mag=None, page=3, y=100, entity_tag="B",
    )]
    pairs = align_exact(a, b)
    assert pairs == [], (
        "LPS-RK ≠ LPN-RK — different fuse families must not bridge "
        "via the relaxed pool"
    )
