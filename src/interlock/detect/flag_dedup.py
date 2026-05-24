"""v2.8.6 — flag-level dedup.

The cross-page-duplication problem: ONE physical anomaly in Doc B
(e.g. "the one-line annotation says 2%Z while the TCC plot annotation
says 5.75%Z" — an intra-doc-B inconsistency caught cross-doc) can pair
against N records in Doc A (every Doc A page that mentions 5.75%Z),
generating N flags that all describe the same underlying mutation.

Strategy: identify each flag by the Doc B record it points to. When
multiple flags share the same Doc B record, keep one — the highest-
confidence; break ties by smallest cross-page distance; final tiebreak
on smallest A page number for determinism.

What we DON'T dedup:
- Flags with different B records, even if values look similar. Two
  separate B-side anomalies should both surface.
- Flags pointing at the same A record across multiple B records.
  (Symmetric case isn't observed in current fixtures; if it appears,
  the inverse keying gets added then.)
"""

from __future__ import annotations

import logging

from interlock.detect.mismatch import Flag

logger = logging.getLogger(__name__)


def dedup_flags_by_b_record(flags: list[Flag]) -> list[Flag]:
    """Collapse flags that share the same Doc B record identity.

    Doc B record identity = ``id(flag.b_record)`` — same Python object
    means same record. Records produced by extraction/dedup are stable
    references through the aligner / detector, so this is exact.
    """
    # Group flags by the B-record they point at + canonical parameter
    # name (different params may legitimately share a B record if the
    # extractor emitted multiple param names for one cell — rare but
    # possible; keep them separate).
    groups: dict[tuple[int, str], list[Flag]] = {}
    for f in flags:
        key = (id(f.b_record), f.parameter)
        groups.setdefault(key, []).append(f)

    out: list[Flag] = []
    dropped = 0
    for key, group in groups.items():
        if len(group) == 1:
            out.append(group[0])
            continue
        # Tiebreakers: confidence desc → cross-page distance asc → A page asc.
        best = sorted(
            group,
            key=lambda f: (
                -f.confidence,
                abs(f.a_record.page - f.b_record.page),
                f.a_record.page,
            ),
        )[0]
        out.append(best)
        dropped += len(group) - 1
        logger.info(
            "flag-dedup: %s collapsed %d → 1 (kept conf=%.2f A=p%d B=p%d; "
            "dropped %d cross-page duplicates)",
            best.parameter, len(group), best.confidence,
            best.a_record.page, best.b_record.page, len(group) - 1,
        )
    if not dropped:
        logger.debug("flag-dedup: no duplicates across %d flags", len(flags))

    # v2.8.7 — magnitude-key near-miss diagnostic. Same physical anomaly
    # can fan out across LANES (regex p3 5.75→0.575 + vision/llm p3
    # 5.75%Z→0.575%Z) with DIFFERENT B records but identical or near-
    # identical magnitudes. The current b-record-id key keeps both.
    # Log clusters of size > 1 so triage can decide whether to add a
    # secondary dedup pass keyed on (canonical_value, page).
    mag_groups: dict[tuple[str, int, str, str], list[Flag]] = {}
    for f in out:
        a_mag = (
            f"{f.a_record.normalized_magnitude:.4g}"
            if f.a_record.normalized_magnitude is not None
            else (f.a_record.raw_value or "").strip().lower()
        )
        b_mag = (
            f"{f.b_record.normalized_magnitude:.4g}"
            if f.b_record.normalized_magnitude is not None
            else (f.b_record.raw_value or "").strip().lower()
        )
        mkey = (f.parameter, f.a_record.page, a_mag, b_mag)
        mag_groups.setdefault(mkey, []).append(f)
    for mkey, mgroup in mag_groups.items():
        if len(mgroup) > 1:
            logger.debug(
                "flag-dedup mag-key near-miss: %s @ A p%d %s↔%s has %d "
                "flags surviving (different B records). Candidates: %s",
                mkey[0], mkey[1], mkey[2], mkey[3], len(mgroup),
                [
                    (
                        getattr(f.a_record, "extraction_lane", "regex"),
                        getattr(f.b_record, "extraction_lane", "regex"),
                        f.confidence,
                    )
                    for f in mgroup
                ],
            )
    return out
