"""Deterministic synthetic civil-drawing fixture.

Single-page site plan-style PDF with grading contours, survey
coordinates (Northing/Easting), civil callouts (TOC, BOC, IE, FFE),
and a title block.
"""

from __future__ import annotations

from pathlib import Path

from reportlab.lib.pagesizes import LETTER, landscape
from reportlab.pdfgen import canvas

OUTPUT = Path(__file__).resolve().parent.parent / "pdfs" / "synth_civil_drawing.pdf"


def main() -> None:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    c = canvas.Canvas(str(OUTPUT), pagesize=landscape(LETTER))
    w, h = landscape(LETTER)

    c.setStrokeColorRGB(0, 0, 0)
    c.rect(20, 20, w - 40, h - 40)
    c.setFont("Helvetica-Bold", 14)
    c.drawString(40, h - 50, "SITE GRADING PLAN — SUBSTATION FOUNDATION")
    c.setFont("Helvetica", 9)
    c.drawString(40, h - 66, "Drawing: C-101 · Scale: 1\" = 20' · Civil Engineer: P.E. stamp")

    c.setFont("Helvetica", 7)
    c.setStrokeColorRGB(0.7, 0.7, 0.7)
    c.setLineWidth(0.25)
    for x in range(80, int(w) - 80, 60):
        c.line(x, 100, x, h - 100)
        c.drawString(x - 12, 90, f"E {1000 + x}")
    for y in range(100, int(h) - 100, 60):
        c.line(80, y, w - 80, y)
        c.drawString(40, y - 3, f"N {2000 + y}")

    c.setStrokeColorRGB(0.4, 0.4, 0.4)
    c.setLineWidth(0.6)
    cx, cy = w / 2, h / 2
    for r, elev in [(40, 100.0), (80, 99.5), (120, 99.0), (160, 98.5)]:
        c.circle(cx, cy, r, stroke=1, fill=0)
        c.setFont("Helvetica", 8)
        c.drawString(cx + r + 4, cy, f"EL {elev}")

    c.setStrokeColorRGB(0, 0, 0)
    c.setLineWidth(1.5)
    c.rect(cx - 60, cy - 40, 120, 80)
    c.setFont("Helvetica-Bold", 9)
    c.drawCentredString(cx, cy + 6, "TRANSFORMER PAD")
    c.drawCentredString(cx, cy - 6, "FFE = 100.50")

    c.setFont("Helvetica", 8)
    callouts = [
        (cx - 80,  cy + 60, "TOC = 100.75"),
        (cx + 80,  cy + 60, "BOC = 100.00"),
        (cx - 80,  cy - 60, "IE  =  98.25"),
        (cx + 80,  cy - 60, "IE  =  98.10"),
    ]
    for x, y, label in callouts:
        c.drawString(x, y, label)

    c.setFont("Helvetica", 8)
    c.drawString(40, 60, "LEGEND: TOC = Top of Curb · BOC = Bottom of Curb · IE = Invert Elevation · FFE = Finish Floor Elevation")
    c.drawString(40, 46, "Contour interval: 0.5 ft · Vertical datum: NAVD 88 · Horizontal datum: state plane")

    c.showPage()
    c.save()
    print(f"wrote {OUTPUT}")


if __name__ == "__main__":
    main()
