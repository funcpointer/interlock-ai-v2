"""Semantic alignment via embeddings.

Injectable ``embed_fn`` returns a dict mapping each text to its vector. Real
implementation in ``align/embed.py`` calls Voyage. Tests inject deterministic
stubs.

Cosine similarity above ``threshold`` emits an AlignedPair. Used as a fallback
for records that exact-name + positional matching could not pair.
"""

from __future__ import annotations

import math
from collections.abc import Callable

from interlock.align.exact import AlignedPair
from interlock.extract.parameters import ParameterRecord
from interlock.extract.units import equivalent, same_dimension

EmbedFn = Callable[[list[str]], dict[str, list[float]]]


# Engineering-domain canonicalization: collapses shorthand and synonyms to a
# shared phrase so the embedding model treats them as the same concept.
# Pure-text alignment alone cannot bridge "%Z" → impedance; this glossary is the
# explicit engineering knowledge baked into InterLock. Extend per fixture family.
_CANONICAL: dict[str, str] = {
    # Impedance family
    "%Z": "transformer impedance percent",
    "%z": "transformer impedance percent",
    "Z%": "transformer impedance percent",
    "Impedance": "transformer impedance percent",
    "Rated Impedance": "transformer impedance percent",
    "Per Unit Impedance": "transformer impedance percent",
    # Rated power family
    "Transformer Rating": "transformer rated apparent power kVA",
    "Rated Power": "transformer rated apparent power kVA",
    "Rated Capacity": "transformer rated apparent power kVA",
    "kVA Rating": "transformer rated apparent power kVA",
    # Voltage families
    "System Voltage": "system voltage kV",
    "Primary Voltage": "transformer primary voltage kV",
    "HV Voltage": "transformer primary voltage kV",
    "Secondary Voltage": "transformer secondary voltage V",
    "LV Voltage": "transformer secondary voltage V",
    # Insulation (conceptually distinct from operating voltage)
    "BIL": "basic insulation level dielectric withstand",
    "Basic Insulation Level": "basic insulation level dielectric withstand",
    # Current
    "Fault Current": "short circuit fault current",
    "Short Circuit Current": "short circuit fault current",
    "IFLA": "full load amperes IFLA",
    "Full Load Amperes": "full load amperes IFLA",
}


def canonical_name(name: str) -> str:
    """Map engineering shorthand to a canonical phrase before embedding."""
    return _CANONICAL.get(name, _CANONICAL.get(name.strip(), name))


def _cos(u: list[float], v: list[float]) -> float:
    if not u or not v:
        return 0.0
    num = sum(x * y for x, y in zip(u, v, strict=False))
    du = math.sqrt(sum(x * x for x in u))
    dv = math.sqrt(sum(y * y for y in v))
    return num / (du * dv) if du and dv else 0.0


def align_semantic(
    a: list[ParameterRecord],
    b: list[ParameterRecord],
    embed_fn: EmbedFn,
    threshold: float = 0.85,
    same_page_only: bool = True,
) -> list[AlignedPair]:
    """Pair unmatched A records to B records by name-embedding similarity.

    ``same_page_only`` (default True): restrict candidates to the same page as
    A. Prevents nonsensical cross-page pairing (e.g., a removed fuse on p7 of A
    matching an unrelated fuse on p2 of B). Disable only for cross-document
    workflows where layout is not shared.
    """
    if not a or not b:
        return []
    # Embed canonicalized names so engineering shorthand aligns (%Z → impedance).
    canon_for: dict[str, str] = {r.name: canonical_name(r.name) for r in a}
    canon_for.update({r.name: canonical_name(r.name) for r in b})
    embed_texts = list(set(canon_for.values()))
    vecs = embed_fn(embed_texts)
    out: list[AlignedPair] = []
    for ra in a:
        va = vecs.get(canon_for[ra.name])
        if not va:
            continue
        best_sim = 0.0
        best_rb: ParameterRecord | None = None
        # Skip string-valued records entirely from semantic matching:
        # part numbers / designations need exact name+value match, not
        # embedding similarity (which conflates LPN-RK-500SP with LPS-RK-225SP).
        if ra.normalized_magnitude is None:
            continue
        for rb in b:
            # Only pair records of compatible value-type: both numeric.
            if rb.normalized_magnitude is None:
                continue
            if same_page_only and ra.page != rb.page:
                continue
            # Reject dimensionally incompatible candidates outright
            # (e.g. "Primary Voltage: 12.47 kV" vs "Fault Current: 20,000 A").
            # This filter is engineering-domain common sense and dramatically
            # cuts false alignments without depending on embedding quality.
            if not same_dimension(ra.raw_value, rb.raw_value):
                continue
            vb = vecs.get(canon_for[rb.name])
            if not vb:
                continue
            sim = _cos(va, vb)
            if sim > best_sim:
                best_sim, best_rb = sim, rb
        if best_rb is not None and best_sim >= threshold:
            out.append(
                AlignedPair(
                    a=ra,
                    b=best_rb,
                    name_match_confidence=best_sim,
                    value_equivalent=equivalent(ra.raw_value, best_rb.raw_value),
                )
            )
    return out
