from interlock.align.semantic import align_semantic
from interlock.extract.parameters import ParameterRecord


def _p(name: str, doc: str) -> ParameterRecord:
    # Use numeric magnitudes so semantic alignment considers these records
    # (string-valued records are skipped to avoid part-number confusion).
    return ParameterRecord(
        doc_id=doc, page=1, bbox=(0, 0, 100, 10), section=None,
        span_text=name, name=name, raw_value="1 V",
        normalized_magnitude=1.0, normalized_unit="volt",
    )


def test_semantic_uses_provided_embedder() -> None:
    # Use names NOT in the canonical glossary so the embed_fn is called with
    # the raw names. (Glossary names get remapped to canonical phrases.)
    a = [_p("AlphaParam", "A")]
    b = [_p("BetaParam", "B")]

    def fake_embed(texts: list[str]) -> dict[str, list[float]]:
        return {"AlphaParam": [1.0, 0.0], "BetaParam": [0.99, 0.01]}

    pairs = align_semantic(a, b, embed_fn=fake_embed, threshold=0.9)
    assert len(pairs) == 1
    assert pairs[0].name_match_confidence >= 0.9


def test_semantic_below_threshold_does_not_emit_pair() -> None:
    a = [_p("AlphaParam", "A")]
    b = [_p("GammaParam", "B")]

    def fake_embed(texts: list[str]) -> dict[str, list[float]]:
        return {"AlphaParam": [1.0, 0.0], "GammaParam": [0.0, 1.0]}

    pairs = align_semantic(a, b, embed_fn=fake_embed, threshold=0.5)
    assert pairs == []


def test_semantic_picks_best_match_when_multiple_candidates() -> None:
    a = [_p("AlphaParam", "A")]
    b = [_p("GammaParam", "B"), _p("BetaParam", "B")]

    def fake_embed(texts: list[str]) -> dict[str, list[float]]:
        return {"AlphaParam": [1.0, 0.0], "BetaParam": [0.99, 0.01], "GammaParam": [0.0, 1.0]}

    pairs = align_semantic(a, b, embed_fn=fake_embed, threshold=0.5)
    assert len(pairs) == 1
    assert pairs[0].b.name == "BetaParam"


def test_semantic_returns_empty_on_no_a_records() -> None:
    def fake_embed(_: list[str]) -> dict[str, list[float]]:
        return {}

    assert align_semantic([], [_p("X", "B")], embed_fn=fake_embed) == []
