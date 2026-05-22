"""Sprint 3 — flag-level provenance annotation.

Derives the per-flag provenance label from the records that contributed
to it. This is a thin post-processing layer; no flag is added, removed,
or reordered.

Provenance taxonomy (3-state + unknown):
  - "rule_only"   : both records are Track 1 (regex extraction)
  - "llm_only"    : both records are Track 2 (LLM extraction)
  - "mixed_track" : one record from each track — different tracks
                    contributed to the same cross-doc comparison
  - "unknown"     : either record's provenance is unset (defensive;
                    shouldn't happen in pipeline flow but covers
                    hand-constructed Flags in tests)
"""

from __future__ import annotations

from dataclasses import replace
from typing import Literal

from interlock.detect.mismatch import Flag

Provenance = Literal["rule_only", "llm_only", "mixed_track", "unknown"]


def adjudicate_flags(flags: list[Flag]) -> list[Flag]:
    """Return new Flag list with provenance annotated per flag.

    Order preserved; all other Flag fields pass through unchanged.
    Empty list → empty list.
    """
    out: list[Flag] = []
    for f in flags:
        a_prov = getattr(f.a_record, "provenance", None)
        b_prov = getattr(f.b_record, "provenance", None)
        provenance = _classify_provenance(a_prov, b_prov)
        out.append(replace(f, provenance=provenance))
    return out


def _classify_provenance(
    a_prov: str | None, b_prov: str | None,
) -> Provenance:
    """Classify a flag's provenance from its two record provenances.

    Returns one of: rule_only, llm_only, mixed_track, unknown.
    """
    if a_prov is None or b_prov is None:
        return "unknown"
    if a_prov == "regex" and b_prov == "regex":
        return "rule_only"
    if a_prov == "llm" and b_prov == "llm":
        return "llm_only"
    return "mixed_track"
