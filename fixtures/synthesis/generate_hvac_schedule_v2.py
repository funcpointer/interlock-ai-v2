"""Deterministic synthetic HVAC schedule (2nd variant) — chiller/boiler plant.

Differs from synth_hvac_schedule.pdf (office air-side) by being a
mechanical-room chilled-water / hot-water plant schedule. Exercises the
hvac_schedule class with different equipment families.
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

OUTPUT = Path(__file__).resolve().parent.parent / "pdfs" / "synth_hvac_schedule_v2.pdf"


def main() -> None:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(
        str(OUTPUT), pagesize=landscape(LETTER),
        title="HVAC Schedule v2 — Chilled / Hot Water Plant",
        author="InterLock AI synthetic fixture",
    )
    styles = getSampleStyleSheet()
    story = [
        Paragraph("<b>MECHANICAL EQUIPMENT SCHEDULE — CENTRAL PLANT</b>", styles["Title"]),
        Paragraph(
            "Project: synthetic example · Drawing: M-201 · Per ASHRAE 90.1-2019",
            styles["Normal"],
        ),
        Spacer(1, 12),
    ]
    header = ["Tag", "Type", "Capacity", "GPM", "EWT/LWT", "Pressure", "kW", "COP/EER"]
    rows = [
        ["CH-1", "Centrifugal Chiller",   "500 tons",  "1200", "55/45 °F", "—",       "275",  "0.55 kW/ton"],
        ["CH-2", "Centrifugal Chiller",   "500 tons",  "1200", "55/45 °F", "—",       "275",  "0.55 kW/ton"],
        ["B-1",  "Condensing Boiler",     "2000 MBH",  "200",  "140/180 °F","60 psig", "—",   "95 %"],
        ["B-2",  "Condensing Boiler",     "2000 MBH",  "200",  "140/180 °F","60 psig", "—",   "95 %"],
        ["CHWP-1","Chilled Water Pump",   "—",         "1200", "—",        "100 ft",  "50",  "—"],
        ["CHWP-2","Chilled Water Pump",   "—",         "1200", "—",        "100 ft",  "50",  "—"],
        ["HWP-1","Hot Water Pump",        "—",         "200",  "—",        "80 ft",   "15",  "—"],
        ["HWP-2","Hot Water Pump",        "—",         "200",  "—",        "80 ft",   "15",  "—"],
        ["CT-1", "Cooling Tower",         "500 tons",  "1500", "85/95 °F", "—",       "40",  "—"],
        ["CT-2", "Cooling Tower",         "500 tons",  "1500", "85/95 °F", "—",       "40",  "—"],
        ["CWP-1","Condenser Water Pump",  "—",         "1500", "—",        "60 ft",   "30",  "—"],
        ["EXP-1","Expansion Tank",        "200 gal",   "—",    "—",        "30 psig", "—",   "—"],
    ]
    table = Table([header] + rows, repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#dddddd")),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
    ]))
    story.append(table)
    doc.build(story)
    print(f"wrote {OUTPUT}")


if __name__ == "__main__":
    main()
