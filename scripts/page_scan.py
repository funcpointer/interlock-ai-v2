"""Dump per-page text from Doc A so mutation sites can be selected."""
from __future__ import annotations
from pathlib import Path
import fitz

DOC_A = Path("fixtures/pdfs/doc_a_60pct.pdf")
OUT = Path("fixtures/mutations/PAGE_SCAN.md")


def main() -> None:
    doc = fitz.open(str(DOC_A))
    lines: list[str] = ["# Doc A Page Scan", ""]
    for i, page in enumerate(doc, start=1):
        lines.append(f"## Page {i}")
        lines.append("```")
        lines.append(page.get_text("text"))
        lines.append("```")
        lines.append("")
    doc.close()
    OUT.write_text("\n".join(lines))
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
