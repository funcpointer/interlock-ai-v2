from interlock.extract.parameters import ParameterRecord, extract_parameters
from interlock.ingest.text import Span


def _s(text: str, page: int = 1, y: float = 0) -> Span:
    return Span(doc_id="d", page=page, bbox=(0, y, 100, y + 10), text=text)


def test_extract_impedance_percent() -> None:
    spans = [_s("5.75%Z, liquid")]
    records = extract_parameters(spans)
    assert any(r.name == "%Z" and "5.75" in r.raw_value for r in records)


def test_extract_transformer_rating_kva() -> None:
    spans = [_s("1000KVA XFMR")]
    records = extract_parameters(spans)
    target = [r for r in records if r.name == "Transformer Rating"]
    assert target
    assert target[0].normalized_magnitude is not None
    # 1000 kVA == 1_000_000 VA in base units
    assert abs(target[0].normalized_magnitude - 1_000_000) < 1


def test_extract_transformer_rating_mva_equivalent_to_kva() -> None:
    spans = [_s("0.15 MVA XFMR")]
    records = extract_parameters(spans)
    target = [r for r in records if r.name == "Transformer Rating"]
    assert target
    # 0.15 MVA == 150 kVA == 150_000 VA
    assert abs(target[0].normalized_magnitude - 150_000) < 1


def test_extract_fault_current() -> None:
    spans = [_s("Fault X1 20,000A RMS Sym")]
    records = extract_parameters(spans)
    target = [r for r in records if r.name == "Fault Current"]
    assert target
    assert abs(target[0].normalized_magnitude - 20_000) < 1


def test_extract_records_carry_citation_tuple() -> None:
    spans = [_s("5.75%Z, liquid", page=3, y=120)]
    records = extract_parameters(spans)
    r = records[0]
    assert isinstance(r, ParameterRecord)
    assert r.doc_id == "d"
    assert r.page == 3
    assert r.bbox == (0, 120, 100, 130)
    assert r.span_text == "5.75%Z, liquid"


def test_extract_ignores_non_parameter_text() -> None:
    spans = [_s("Conclusions"), _s("Notes:")]
    records = extract_parameters(spans)
    assert records == []


def test_extract_handles_ifla() -> None:
    spans = [_s("IFLA=42A")]
    records = extract_parameters(spans)
    target = [r for r in records if r.name == "IFLA"]
    assert target
    assert abs(target[0].normalized_magnitude - 42) < 1


def test_extract_fuse_designation_as_string_value() -> None:
    spans = [_s("LPN-RK-500SP")]
    records = extract_parameters(spans)
    target = [r for r in records if r.name == "Fuse Designation"]
    assert target
    assert target[0].raw_value == "LPN-RK-500SP"
    # No numeric normalization for part numbers.
    assert target[0].normalized_magnitude is None
