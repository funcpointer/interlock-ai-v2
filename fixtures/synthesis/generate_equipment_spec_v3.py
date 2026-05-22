"""3rd synthetic equipment-spec variant — MV switchgear data sheet.

Extends the equipment_spec corpus beyond transformer (spec_xfmr_001) and
motor (synth_equipment_spec_v2) with a medium-voltage switchgear shape.
"""

from __future__ import annotations

from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

OUTPUT = Path(__file__).resolve().parent.parent / "pdfs" / "synth_equipment_spec_v3.pdf"


def main() -> None:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(
        str(OUTPUT), pagesize=LETTER,
        title="MV Switchgear Equipment Data Sheet",
        author="InterLock AI synthetic fixture",
    )
    styles = getSampleStyleSheet()
    story = [
        Paragraph("<b>MEDIUM-VOLTAGE METAL-CLAD SWITCHGEAR DATA SHEET</b>", styles["Title"]),
        Paragraph(
            "Manufacturer: Eaton VacClad-W · Model: VCP-W-1600 · Serial: SG10243 · "
            "Standards: IEEE C37.20.2, ANSI C37.06, IEC 62271-200",
            styles["Normal"],
        ),
        Spacer(1, 12),
    ]
    nameplate_rows = [
        ["Rated Maximum Voltage", "15 kV"],
        ["Rated Power Frequency", "60 Hz"],
        ["Rated Continuous Current", "1600 A"],
        ["Rated Short-Circuit Current", "40 kA RMS sym"],
        ["Rated Peak Withstand Current", "104 kA"],
        ["Rated Short-Time Withstand", "40 kA / 3 s"],
        ["Rated Lightning Impulse Withstand", "95 kV BIL"],
        ["Rated Power Frequency Withstand", "36 kV / 1 min"],
        ["Rated Closing Time", "75 ms max"],
        ["Rated Opening Time", "50 ms max"],
        ["Rated Total Interrupting Time", "5 cycles (83 ms)"],
        ["Rated Operating Sequence", "O-0.3s-CO-15s-CO"],
        ["Number of Operations (rated load)", "10,000"],
        ["Auxiliary Voltage", "125 VDC"],
        ["Trip Coil Current (125 VDC)", "9.2 A"],
        ["Operating Temperature Range", "-30 to +40 °C"],
    ]
    t = Table([["Parameter", "Value"]] + nameplate_rows, colWidths=[220, 180])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#dddddd")),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
    ]))
    story.append(t)
    story.append(Spacer(1, 20))
    story.append(Paragraph(
        "<b>Compliance:</b> IEEE C37.20.2-2015 (metal-clad), "
        "IEEE C37.04-1999 (rating structure), ANSI C37.06-2009 "
        "(preferred ratings), IEC 62271-200 (metal-enclosed MV switchgear). "
        "Factory tested per ANSI C37.09.",
        styles["Normal"],
    ))
    doc.build(story)
    print(f"wrote {OUTPUT}")


if __name__ == "__main__":
    main()
