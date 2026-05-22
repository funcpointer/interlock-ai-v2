"""Deterministic synthetic coordination-study PDF (2nd variant).

Adds a non-Eaton-style coordination study to the corpus. TCC reference
points + device-coordination table + one-line diagram fragment. Mimics
a Square D / Schneider-Electric style sample layout.
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

OUTPUT = Path(__file__).resolve().parent.parent / "pdfs" / "synth_coordination_study_v2.pdf"


def main() -> None:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(
        str(OUTPUT), pagesize=LETTER,
        title="Selective Coordination Study — Sample TCC1",
        author="InterLock AI synthetic fixture",
    )
    styles = getSampleStyleSheet()
    story = [
        Paragraph("<b>SELECTIVE COORDINATION STUDY — TCC1</b>", styles["Title"]),
        Paragraph(
            "Project: synthetic example · Bus: B-12.47kV · Drawing: E-501 Rev A",
            styles["Normal"],
        ),
        Spacer(1, 10),
        Paragraph(
            "Log-log time-current characteristic curves below cover the primary "
            "fuse, secondary main fuse, 200 A feeder fuse, and 20 A branch "
            "breaker. Coordination is verified at the system fault duty.",
            styles["Normal"],
        ),
        Spacer(1, 14),
    ]

    rows = [
        ["#", "Device", "Type",            "Rating",      "Curve",    "TD"],
        ["①", "Primary Fuse",   "Class L",         "1600 A",      "—",        "—"],
        ["②", "Sec Main Fuse",  "Class K-5",       "400 A",       "—",        "—"],
        ["③", "Feeder Fuse",    "Class RK1",       "200 A",       "—",        "—"],
        ["④", "Branch Breaker", "Thermal-magnetic","20 A",        "Inverse",  "—"],
        ["⑤", "Conductor",      "#6 THWN-2 Cu",    "—",           "—",        "—"],
        ["⑥", "Motor M-101",    "Induction 75 HP", "104 A FLC",   "—",        "—"],
        ["⑦", "MV Relay 51P",   "GE Multilin 750", "600 A",       "U2 IEC VI","0.55"],
        ["⑧", "MV Relay 51N",   "GE Multilin 750", "75 A",        "U2 IEC VI","0.40"],
    ]
    t = Table(rows, repeatRows=1, colWidths=[20, 100, 100, 100, 90, 60])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#dddddd")),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
    ]))
    story.append(t)
    story.append(Spacer(1, 14))

    story.append(Paragraph("<b>TCC1 reference points (per device on log-log axes)</b>", styles["Heading3"]))
    tcc = [
        ["Device", "Pickup (A)", "Time @ Pickup (s)", "Asymptote (s)"],
        ["①", "1600",  "100",   "0.01"],
        ["②", "400",   "60",    "0.05"],
        ["③", "200",   "30",    "0.1"],
        ["④", "20",    "30",    "0.5"],
    ]
    t2 = Table(tcc, repeatRows=1, colWidths=[60, 90, 130, 110])
    t2.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#dddddd")),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
    ]))
    story.append(t2)

    story.append(Spacer(1, 14))
    story.append(Paragraph(
        "<b>References:</b> IEEE Std 242 (Buff Book) §10 · IEEE C37.91 · "
        "Bussmann Coordination Bulletin 201",
        styles["Normal"],
    ))
    doc.build(story)
    print(f"wrote {OUTPUT}")


if __name__ == "__main__":
    main()
