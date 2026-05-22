"""Deterministic synthetic Bill of Material PDF.

Single-page tabular item list with quantities, manufacturers, part numbers.
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

OUTPUT = Path(__file__).resolve().parent.parent / "pdfs" / "synth_bom.pdf"


def main() -> None:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(
        str(OUTPUT), pagesize=LETTER,
        title="Bill of Material — Switchgear Assembly",
        author="InterLock AI synthetic fixture",
    )
    styles = getSampleStyleSheet()
    story = [
        Paragraph("<b>BILL OF MATERIAL — SWITCHGEAR ASSEMBLY SG-101</b>", styles["Title"]),
        Paragraph("Drawing: E-104 Rev B · Project: synthetic example", styles["Normal"]),
        Spacer(1, 12),
    ]
    header = ["Item #", "Qty", "Description", "Manufacturer", "Part Number", "Vendor Cat #"]
    rows = [
        ["1",  "1",  "Main Breaker, 1600 A, 38 kV",   "Eaton",       "VCP-W-1600",     "C440-1600-VCP"],
        ["2",  "12", "Feeder Breaker, 600 A, 5 kV",   "Eaton",       "VCP-W-600",      "C440-600-VCP"],
        ["3",  "1",  "Bus Tie Breaker, 1200 A",       "Schneider",   "VR-1200-15",     "S-VR1200-15"],
        ["4",  "4",  "Current Transformer 600:5",     "GE",          "CTW-600-5",      "GE-CTW600"],
        ["5",  "4",  "Voltage Transformer 14.4 kV/120 V","GE",       "JVM-150-14.4",   "GE-JVM150"],
        ["6",  "12", "Protective Relay SEL-787",      "SEL",         "SEL-787",        "SEL-787-1A"],
        ["7",  "1",  "Auxiliary Power Supply 125 VDC","ABB",         "BWR-125-50",     "ABB-BWR125"],
        ["8",  "24", "Control Wire 14 AWG (1000 ft)", "Belden",      "9939-1000",      "BEL-9939"],
        ["9",  "1",  "Annunciator Panel 16-pt",       "Rochester",   "RAN-16",         "ROC-RAN16"],
        ["10", "1",  "Ground Bus 1/4 x 2 x 84 in",    "Erico",       "GB-2-84",        "ERI-GB284"],
    ]
    table = Table([header] + rows, repeatRows=1, colWidths=[40, 30, 180, 80, 100, 100])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#dddddd")),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    story.append(table)
    story.append(Spacer(1, 20))
    story.append(Paragraph(
        "<b>Total line items:</b> 10 · <b>Approval:</b> J. Engineer (signed) · "
        "<b>Revision:</b> B",
        styles["Normal"],
    ))
    doc.build(story)
    print(f"wrote {OUTPUT}")


if __name__ == "__main__":
    main()
