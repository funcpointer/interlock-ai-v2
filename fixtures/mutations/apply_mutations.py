"""Deterministic mutation engine. Reads MUTATIONS list, applies edits to Doc A, writes Doc B.

Re-runnable: regenerates Doc B from Doc A any time. Idempotent given same source PDF.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import fitz

SRC = Path("fixtures/pdfs/doc_a_60pct.pdf")
DST = Path("fixtures/pdfs/doc_b_90pct.pdf")
HASHES = Path("fixtures/pdfs/HASHES.txt")

# (id, page_1indexed, search_text, replace_text, redact_only)
# redact_only=True means erase without replacement (used for FN-1 checklist gap).
MUTATIONS: list[tuple[str, int, str, str, bool]] = [
    ("TP-1", 3, "5.75%Z, liquid", "0.575%Z, liquid", False),
    ("TP-2", 2, "20,000A RMS Sym", "200,000A RMS Sym", False),
    ("TP-3", 7, "1000KVA XFMR", "100KVA XFMR", False),
    ("FP-1", 7, "150 KVA XFMR", "0.15 MVA XFMR", False),
    ("FP-2", 3, "Time Current Curve #1 (TCC1)", "Time Current Curve 1 (TCC1)", False),
    ("FN-1", 7, "LPN-RK-500SP", "", True),
]


def apply() -> None:
    if not SRC.exists():
        raise FileNotFoundError(SRC)
    doc = fitz.open(str(SRC))
    applied: list[str] = []
    for mid, page_num, search, replace, redact_only in MUTATIONS:
        page = doc[page_num - 1]
        rects = page.search_for(search)
        if not rects:
            raise RuntimeError(f"{mid}: text {search!r} not found on page {page_num}")
        for rect in rects:
            if redact_only:
                page.add_redact_annot(rect, text="", fill=(1, 1, 1))
            else:
                page.add_redact_annot(rect, text=replace, fill=(1, 1, 1), text_color=(0, 0, 0))
        applied.append(f"{mid} p{page_num}: {len(rects)} occurrence(s)")
    for page in doc:
        page.apply_redactions()
    DST.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(DST), deflate=True)
    doc.close()
    sha = hashlib.sha256(DST.read_bytes()).hexdigest()
    existing = HASHES.read_text() if HASHES.exists() else ""
    if f"{DST.name}" not in existing:
        with HASHES.open("a") as f:
            f.write(f"{sha}  {DST}\n")
    print(f"wrote {DST} sha256={sha[:16]}...")
    for line in applied:
        print(f"  {line}")


if __name__ == "__main__":
    apply()
