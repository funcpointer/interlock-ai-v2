"""Deterministic synthetic HVAC equipment schedule PDF.

Produces a single-page schedule with rows like:
    AHU-1 | Roof Top | 5000 CFM | 12.5 tons | ASHRAE 90.1
    FCU-3 | Office  | 800 CFM   | 2.5 tons  | ASHRAE 90.1
    EF-2  | Restroom| 200 CFM   | -         | -

Output: fixtures/pdfs/synth_hvac_schedule.pdf.
Deterministic — same input → same SHA-256 — so the fixture is committable.
"""

from __future__ import annotations

from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import LETTER, landscape
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

OUTPUT = Path(__file__).resolve().parent.parent / "pdfs" / "synth_hvac_schedule.pdf"


def main() -> None:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(
        str(OUTPUT),
        pagesize=landscape(LETTER),
        title="HVAC Equipment Schedule",
        author="InterLock AI synthetic fixture",
    )
    styles = getSampleStyleSheet()
    story = [
        Paragraph("<b>HVAC EQUIPMENT SCHEDULE</b>", styles["Title"]),
        Paragraph("Project: synthetic example · Drawing: M-001", styles["Normal"]),
        Spacer(1, 12),
    ]
    header = ["Tag", "Type", "Location", "CFM", "Tonnage", "GPM", "ASHRAE Ref"]
    rows = [
        ["AHU-1", "Air Handling Unit",   "Roof Top",     "5000",  "12.5", "—",   "90.1-2019"],
        ["AHU-2", "Air Handling Unit",   "Mechanical 2", "3200",  "8.0",  "—",   "90.1-2019"],
        ["FCU-1", "Fan Coil Unit",       "Office 101",   "400",   "1.0",  "2.5", "62.1-2019"],
        ["FCU-2", "Fan Coil Unit",       "Office 102",   "400",   "1.0",  "2.5", "62.1-2019"],
        ["FCU-3", "Fan Coil Unit",       "Conf Room A",  "800",   "2.5",  "5.0", "62.1-2019"],
        ["RTU-1", "Rooftop Unit",        "Roof Top",     "2400",  "6.0",  "—",   "90.1-2019"],
        ["EF-1",  "Exhaust Fan",         "Restroom 1",   "150",   "—",    "—",   "62.1-2019"],
        ["EF-2",  "Exhaust Fan",         "Restroom 2",   "200",   "—",    "—",   "62.1-2019"],
        ["CHWP-1","Chilled Water Pump",  "Mechanical 1", "—",     "—",    "120", "90.1-2019"],
        ["CT-1",  "Cooling Tower",       "Roof Top",     "—",     "200",  "600", "90.1-2019"],
    ]
    table = Table([header] + rows, repeatRows=1)
    table.setStyle(
        TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#dddddd")),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
        ])
    )
    story.append(table)
    doc.build(story)
    print(f"wrote {OUTPUT}")


if __name__ == "__main__":
    main()
