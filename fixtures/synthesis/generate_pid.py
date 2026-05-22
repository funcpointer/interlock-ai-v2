"""Deterministic synthetic P&ID PDF.

Single-page diagrammatic example with ISA-5.1 instrument bubble notation:
    PT-100  (Pressure Transmitter)
    FT-101  (Flow Transmitter)
    LIC-200 (Level Indicating Controller)
    PV-300  (Pressure Valve)

Process flow: feed → reactor → heat exchanger → storage. Each unit
labeled with line numbers and tag IDs.
"""

from __future__ import annotations

from pathlib import Path

from reportlab.lib.pagesizes import LETTER, landscape
from reportlab.pdfgen import canvas

OUTPUT = Path(__file__).resolve().parent.parent / "pdfs" / "synth_pid.pdf"


def main() -> None:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    c = canvas.Canvas(str(OUTPUT), pagesize=landscape(LETTER))
    _width, height = landscape(LETTER)

    c.setFont("Helvetica-Bold", 16)
    c.drawString(36, height - 40, "PIPING & INSTRUMENTATION DIAGRAM — REACTOR FEED SYSTEM")
    c.setFont("Helvetica", 9)
    c.drawString(36, height - 56, "ISA-5.1 notation · Drawing: P-001 Rev A · Synthetic fixture")

    units = [
        (80,  340, "FEED\nTANK\nT-101"),
        (260, 340, "REACTOR\nR-201"),
        (440, 340, "HEAT EXCH\nE-301"),
        (620, 340, "STORAGE\nTK-401"),
    ]
    c.setFont("Helvetica", 10)
    for x, y, label in units:
        c.rect(x, y, 90, 90)
        text_lines = label.split("\n")
        for i, line in enumerate(text_lines):
            c.drawCentredString(x + 45, y + 60 - i * 14, line)

    c.setLineWidth(1.5)
    line_segments = [
        (170, 385, 260, 385, "4\"-FS-101-CS"),
        (350, 385, 440, 385, "6\"-PR-201-SS"),
        (530, 385, 620, 385, "6\"-PR-301-SS"),
    ]
    for x1, y1, x2, y2, label in line_segments:
        c.line(x1, y1, x2, y2)
        c.line(x2 - 10, y2 - 4, x2, y2)
        c.line(x2 - 10, y2 + 4, x2, y2)
        c.setFont("Helvetica", 8)
        c.drawString(x1 + 5, y1 + 6, label)

    c.setFont("Helvetica-Bold", 9)
    bubbles = [
        (215, 440, "PT-100"),
        (215, 280, "FT-101"),
        (395, 440, "TIC-200"),
        (395, 280, "LIC-200"),
        (575, 440, "PIC-300"),
        (575, 280, "FV-300"),
    ]
    for x, y, tag in bubbles:
        c.circle(x, y, 16, stroke=1, fill=0)
        c.drawCentredString(x, y - 3, tag)

    c.setFont("Helvetica", 8)
    c.drawString(36, 80, "LEGEND:")
    c.drawString(36, 66, "PT = Pressure Transmitter · FT = Flow Transmitter · TIC = Temperature Indicating Controller")
    c.drawString(36, 52, "LIC = Level Indicating Controller · PIC = Pressure Indicating Controller · FV = Flow Valve")
    c.drawString(36, 38, "Line code format: <size>\"-<service>-<line#>-<material>")

    c.showPage()
    c.save()
    print(f"wrote {OUTPUT}")


if __name__ == "__main__":
    main()
