"""Second synthetic equipment-spec variant — motor data sheet shape.

Differs from spec_xfmr_001.pdf (transformer) by being a motor data
sheet. Exercises the equipment_spec class beyond transformers.
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

OUTPUT = Path(__file__).resolve().parent.parent / "pdfs" / "synth_equipment_spec_v2.pdf"


def main() -> None:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(
        str(OUTPUT), pagesize=LETTER,
        title="Motor Equipment Data Sheet",
        author="InterLock AI synthetic fixture",
    )
    styles = getSampleStyleSheet()
    story = [
        Paragraph("<b>MOTOR EQUIPMENT DATA SHEET</b>", styles["Title"]),
        Paragraph(
            "Manufacturer: ABB · Model: M3BP 280SMB 4 · Serial: AB1234567 · "
            "NEMA MG1 / IEC 60034",
            styles["Normal"],
        ),
        Spacer(1, 12),
    ]
    nameplate_rows = [
        ["Rated Power",       "75 kW (100 HP)"],
        ["Rated Voltage",     "460 V"],
        ["Rated Current",     "120 A"],
        ["Rated Speed",       "1780 RPM"],
        ["Frequency",         "60 Hz"],
        ["Number of Poles",   "4"],
        ["Service Factor",    "1.15"],
        ["Insulation Class",  "F"],
        ["Temperature Rise",  "80 °C"],
        ["Enclosure",         "TEFC IP55"],
        ["Frame Size",        "NEMA 405T"],
        ["Efficiency (75% load)", "95.8 %"],
        ["Power Factor (Full load)", "0.88"],
        ["Starting Current Ratio (LRC/FLC)", "6.5"],
        ["Starting Torque Ratio (LRT/FLT)",  "1.80"],
        ["Breakdown Torque Ratio (BDT/FLT)", "2.80"],
    ]
    t = Table([["Parameter", "Value"]] + nameplate_rows, colWidths=[200, 200])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#dddddd")),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
    ]))
    story.append(t)
    story.append(Spacer(1, 20))
    story.append(Paragraph(
        "<b>Standards compliance:</b> NEMA MG 1-2016, IEC 60034-1, IEEE 841-2009",
        styles["Normal"],
    ))
    doc.build(story)
    print(f"wrote {OUTPUT}")


if __name__ == "__main__":
    main()
