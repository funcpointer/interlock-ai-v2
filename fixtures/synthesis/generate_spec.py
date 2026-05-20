"""Deterministic generator for Option 2 cross-doc fixture.

Emits a 1-page synthetic transformer Equipment Data Sheet shaped like a
real IEEE C57.12.00 / ANSI C57.12.10 style nameplate spec. Used to demonstrate
cross-document parameter alignment against the Eaton coordination study.

This is a SYNTHETIC document, disclosed in docs/AUTHORSHIP.md. Real spec
curation is platform-path (Option 4).

Run:
    uv run python fixtures/synthesis/generate_spec.py
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import fitz

OUT = Path("fixtures/pdfs/spec_xfmr_001.pdf")
HASHES = Path("fixtures/pdfs/HASHES.txt")

HEADER = "Equipment Data Sheet — Power Transformer XFMR-001"
SUBHEADER = "Manufacturer: ACME Power Equipment Co.    |    Standard: IEEE C57.12.00, ANSI C57.12.10"

LINES: list[tuple[str, str]] = [
    ("Equipment ID", "XFMR-001"),
    ("Service", "Indoor Substation, 3-phase"),
    ("Rated Power", "1100 kVA"),  # TP-CD-2: 9% deviation from Eaton 1000 kVA → minor
    ("Primary Voltage", "12.47 kV"),  # TP-CD-3: 9.6% deviation from Eaton 13.8 kV → major
    ("Secondary Voltage", "480 V"),  # FP-CD-1: matches Eaton
    ("Rated Impedance", "4.5 %"),  # TP-CD-1: 22% deviation from Eaton 5.75% → major
    # Note: changed from 5.7 % (only 0.9% deviation, within IEEE C57.12.00 ±7.5%
    # tolerance band — would correctly suppress as info under Phase 13 tolerance
    # classification). 4.5% provides a real out-of-tolerance mismatch that
    # exercises the cross-doc semantic-alignment + tolerance-aware-flagging path.
    ("Frequency", "60 Hz"),  # FP-CD-2: no counterpart in Eaton
    ("BIL", "95 kV"),  # FP-CD-3: no counterpart in Eaton
    ("Vector Group", "Dyn1"),
    ("Cooling Class", "ONAN"),
    ("Insulation Class", "55 °C"),
    ("Connection", "Three-phase, 60 Hz, Delta-Wye"),
]

FOOTER = "Issued: 2026-04-15    Document: SPEC-XFMR-001-Rev-A"


def main() -> None:
    doc = fitz.open()
    page = doc.new_page()  # default US Letter

    # Spec uses only ASCII + degree sign (°), all covered by helv (Helvetica).
    fontname = "helv"

    x_label = 72
    x_value = 280
    y = 72

    page.insert_text((x_label, y), HEADER, fontname=fontname, fontsize=14)
    y += 24
    page.insert_text((x_label, y), SUBHEADER, fontname=fontname, fontsize=9)
    y += 30

    page.insert_text((x_label, y), "1. Nameplate Parameters", fontname=fontname, fontsize=12)
    y += 22

    for label, value in LINES:
        page.insert_text((x_label, y), f"{label}:", fontname=fontname, fontsize=11)
        page.insert_text((x_value, y), value, fontname=fontname, fontsize=11)
        y += 18

    y += 24
    page.insert_text((x_label, y), FOOTER, fontname=fontname, fontsize=8)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(OUT))
    doc.close()

    sha = hashlib.sha256(OUT.read_bytes()).hexdigest()
    with HASHES.open("a") as f:
        f.write(f"{sha}  fixtures/pdfs/spec_xfmr_001.pdf\n")
    print(f"wrote {OUT} sha256={sha}")


if __name__ == "__main__":
    main()
