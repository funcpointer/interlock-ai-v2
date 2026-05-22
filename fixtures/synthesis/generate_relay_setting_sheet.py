"""Deterministic synthetic relay-setting sheet PDF.

Project-style protective-relay setting sheet with concrete setting tables
(SEL-787 transformer protection). Real setting sheets are project-NDA'd
and rarely public; this seed gives the classifier a structural exemplar
for the class.
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

OUTPUT = Path(__file__).resolve().parent.parent / "pdfs" / "synth_relay_setting_sheet.pdf"


def main() -> None:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(
        str(OUTPUT), pagesize=LETTER,
        title="Relay Setting Sheet — SEL-787 Transformer Protection",
        author="InterLock AI synthetic fixture",
    )
    styles = getSampleStyleSheet()
    story = [
        Paragraph("<b>RELAY SETTING SHEET — TRANSFORMER PROTECTION</b>", styles["Title"]),
        Paragraph(
            "Relay: <b>SEL-787</b> · Tag: T1-DIFF-87 · Setting Group: 1 · "
            "Project: synthetic example · Engineer: J. Engineer P.E.",
            styles["Normal"],
        ),
        Spacer(1, 10),
    ]

    # Setting-group table
    settings = [
        ["Element", "Function", "Setting", "Units", "Curve"],
        ["87T",  "Differential",            "0.30",   "pu",   "—"],
        ["87HS", "High-Set Differential",   "8.0",    "pu",   "—"],
        ["50P1", "Phase Overcurrent",       "1200",   "A",    "—"],
        ["50P2", "Phase Overcurrent",       "3600",   "A",    "—"],
        ["51P",  "Phase Time-OC",           "600",    "A",    "U2 (IEC VI)"],
        ["51P TD","Time Dial",              "0.55",   "—",    "—"],
        ["50N",  "Neutral Overcurrent",     "150",    "A",    "—"],
        ["51N",  "Neutral Time-OC",         "75",     "A",    "U2 (IEC VI)"],
        ["51N TD","Time Dial",              "0.40",   "—",    "—"],
        ["27P",  "Phase Undervoltage",      "0.85",   "pu",   "—"],
        ["59P",  "Phase Overvoltage",       "1.15",   "pu",   "—"],
        ["81U",  "Underfrequency",          "59.5",   "Hz",   "—"],
        ["81O",  "Overfrequency",           "60.5",   "Hz",   "—"],
    ]
    t = Table(settings, repeatRows=1, colWidths=[60, 160, 80, 50, 100])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#dddddd")),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
    ]))
    story.append(t)
    story.append(Spacer(1, 14))

    # Trip targets + logic equations (additional structural signal)
    story.append(Paragraph("<b>TRIP TARGETS</b>", styles["Heading3"]))
    story.append(Paragraph(
        "TRIP1 = 87T + 87HS<br/>"
        "TRIP2 = 51P + 51N<br/>"
        "TRIP3 = 27P + 59P + 81U + 81O<br/>"
        "ALARM = 50P1 (instantaneous)",
        styles["Code"],
    ))

    story.append(Spacer(1, 14))
    story.append(Paragraph(
        "<b>Reference:</b> IEEE C37.91 — Guide for Protecting Power Transformers · "
        "IEEE Std 242 §11 — Relay coordination",
        styles["Normal"],
    ))
    doc.build(story)
    print(f"wrote {OUTPUT}")


if __name__ == "__main__":
    main()
