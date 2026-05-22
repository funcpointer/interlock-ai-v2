"""Deterministic synthetic P&ID (2nd variant) — heat-exchanger train.

Differs from synth_pid.pdf (reactor feed) by being a parallel heat-
exchanger train with bypass loops. ISA-5.1 instrument bubbles + control
valves with safety interlocks.
"""

from __future__ import annotations

from pathlib import Path

from reportlab.lib.pagesizes import LETTER, landscape
from reportlab.pdfgen import canvas

OUTPUT = Path(__file__).resolve().parent.parent / "pdfs" / "synth_pid_v2.pdf"


def main() -> None:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    c = canvas.Canvas(str(OUTPUT), pagesize=landscape(LETTER))
    _width, height = landscape(LETTER)

    c.setFont("Helvetica-Bold", 16)
    c.drawString(36, height - 40, "PIPING & INSTRUMENTATION DIAGRAM — HEAT-EXCHANGER TRAIN")
    c.setFont("Helvetica", 9)
    c.drawString(36, height - 56, "ISA-5.1 notation · Drawing: P-002 Rev B · Synthetic fixture")

    # Parallel HX trains (upper + lower flow path)
    units_upper = [
        (100, 420, "FILTER\nF-101"),
        (260, 420, "HX-A\nE-201"),
        (420, 420, "COOLER\nC-301"),
        (580, 420, "PUMP\nP-401"),
    ]
    units_lower = [
        (260, 260, "HX-B\nE-202"),
        (420, 260, "BYPASS\nMOV-220"),
    ]
    c.setFont("Helvetica", 10)
    for x, y, label in units_upper + units_lower:
        c.rect(x, y, 80, 80)
        for i, line in enumerate(label.split("\n")):
            c.drawCentredString(x + 40, y + 50 - i * 14, line)

    # Connecting lines with line tags
    c.setLineWidth(1.5)
    segments = [
        (180, 460, 260, 460, "6\"-PR-101-CS"),
        (340, 460, 420, 460, "6\"-PR-201-SS"),
        (500, 460, 580, 460, "6\"-PR-301-SS"),
        (300, 420, 300, 340, "6\"-PR-101-CS (bypass)"),
        (340, 300, 420, 300, "6\"-PR-220-SS"),
        (460, 340, 460, 420, "6\"-PR-220-SS"),
    ]
    for x1, y1, x2, y2, label in segments:
        c.line(x1, y1, x2, y2)
        c.setFont("Helvetica", 7)
        c.drawString(min(x1, x2) + 4, max(y1, y2) - 9, label)

    # ISA bubbles with safety interlocks
    c.setFont("Helvetica-Bold", 9)
    bubbles = [
        (140, 510, "PT-101"),
        (140, 380, "FT-101"),
        (300, 510, "TIC-201"),
        (300, 380, "TI-202"),
        (460, 510, "PSV-301"),  # pressure safety valve
        (460, 380, "FT-302"),
        (620, 510, "FIC-401"),  # flow controller
        (300, 200, "MOV-220"),  # motorized valve
    ]
    for x, y, tag in bubbles:
        c.circle(x, y, 18, stroke=1, fill=0)
        c.drawCentredString(x, y - 3, tag)

    # Safety interlock callout
    c.setFont("Helvetica-Bold", 10)
    c.drawString(36, 160, "SAFETY INTERLOCKS:")
    c.setFont("Helvetica", 8)
    c.drawString(36, 144, "I-1: PSV-301 (high pressure) → trip P-401 + open MOV-220")
    c.drawString(36, 130, "I-2: FT-302 (low flow) → close FIC-401 + alarm")
    c.drawString(36, 116, "I-3: TIC-201 (high temp) → modulate COOLER C-301 flow")

    c.setFont("Helvetica", 8)
    c.drawString(36, 80, "LEGEND: PT = Pressure Tx · FT = Flow Tx · TIC = Temp Indicating Controller")
    c.drawString(36, 66, "PSV = Pressure Safety Valve · MOV = Motorized Operated Valve · FIC = Flow Indicating Controller")
    c.drawString(36, 52, "Line tag format: <size>\"-<service>-<line#>-<material> · CS = carbon steel · SS = stainless")

    c.showPage()
    c.save()
    print(f"wrote {OUTPUT}")


if __name__ == "__main__":
    main()
