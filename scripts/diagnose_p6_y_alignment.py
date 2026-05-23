"""Diagnostic — dump full (entity, y) + (record, y) tables for p6 to see
WHERE the detector + binder go wrong relative to PyMuPDF text-layer
positions.
"""

from __future__ import annotations

from dotenv import load_dotenv

load_dotenv(override=True)

import fitz

from interlock.cache import disk as disk_cache
from interlock.extract.parameters import extract_parameters
from interlock.ingest.pdf import ingest
from interlock.llm_pipeline.entity_detect import detect_entities_on_page


def main() -> int:
    for label, path in [
        ("doc_a", "fixtures/pdfs/doc_a_60pct.pdf"),
        ("doc_b", "fixtures/pdfs/doc_b_90pct.pdf"),
    ]:
        print(f"\n=== {label} p6 ===")
        # Bust + rerun detector
        disk_cache.clear_namespace("llm-entities")
        ents = detect_entities_on_page(path, 6)
        print(f"\nDetector returned {len(ents)} entities:")
        for e in sorted(ents, key=lambda x: x.y_top):
            print(
                f"  y=[{e.y_top:7.1f}..{e.y_bottom:7.1f}] "
                f"range={e.y_bottom - e.y_top:6.1f} "
                f"kind={e.kind:11s} label={e.label!r}"
            )

        # Track 1 record y-coords
        ing = ingest(path, doc_id=label, table_max_pages=20)
        recs = extract_parameters(ing.spans)
        p6_recs = [r for r in recs if r.page == 6]
        print(f"\nTrack 1 records on p6 ({len(p6_recs)}):")
        for r in p6_recs:
            yc = (r.bbox[1] + r.bbox[3]) / 2
            # Which entity encloses this y_center?
            encl = [e for e in ents if e.y_top <= yc <= e.y_bottom]
            note = ""
            if encl:
                tightest = min(encl, key=lambda e: e.y_bottom - e.y_top)
                note = f" ENCLOSED-BY [{tightest.label!r}] (of {len(encl)} encl)"
            elif ents:
                near = min(
                    ents,
                    key=lambda e: abs((e.y_top + e.y_bottom) / 2 - yc),
                )
                note = f" NEAREST [{near.label!r}] (dist {abs((near.y_top+near.y_bottom)/2 - yc):.1f})"
            print(f"  y={yc:7.1f} name={r.name:20s} raw={r.raw_value!r:30s}{note}")

        # Page text raw
        doc = fitz.open(path)
        text = doc[5].get_text("text")
        doc.close()
        print(f"\nPyMuPDF text-layer lines (numbered):")
        for i, ln in enumerate(text.splitlines()):
            if ln.strip():
                print(f"  L{i:3d}: {ln.strip()!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
