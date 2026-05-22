"""Attempt to source real public engineering PDFs for the Sprint 1 corpus.

Tries a curated list of candidate URLs per doc class. For each URL:
  1. curl with reasonable timeout
  2. Validate with fitz (must open, ≥1 page, ≥200 chars of text)
  3. If valid → save to fixtures/pdfs/real_<class>_<short>.pdf
  4. If invalid → log + try next candidate
  5. After last candidate fails → log "consider synthetic fallback"

Run with:
    uv run python scripts/source_real_pdfs.py

Expected hit rate: ~30-50%. Engineering PDFs publicly hosted on stable
URLs are rare; many real deliverables are proprietary or behind portals.
The script is honest about failures and the user can pick which classes
need synthetic-substitute generators.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
from pathlib import Path

import fitz

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "pdfs"

# (filename_suffix, url) per class — try in order until one succeeds.
CANDIDATES: dict[str, list[tuple[str, str]]] = {
    "coordination_study": [
        # Eaton / Cooper / Bussmann library — sample studies + tech papers.
        ("eaton_coord_sample2",
         "https://www.eaton.com/content/dam/eaton/products/electrical-circuit-protection/fuses/literature/bus-ele-tech-lib-system-coordination-studies-ta1001005e.pdf"),
        ("schneider_coord",
         "https://download.schneider-electric.com/files?p_Doc_Ref=0100DB1101"),
        ("cooper_selective_coord",
         "https://www.eaton.com/content/dam/eaton/products/electrical-circuit-protection/fuses/literature/bus-ele-tech-lib-bulletin-no-201-selective-coordination.pdf"),
    ],
    "equipment_spec": [
        # Manufacturer transformer / motor data sheets.
        ("eaton_xfmr_spec",
         "https://www.eaton.com/content/dam/eaton/products/medium-voltage-power-distribution-control-systems/transformers/cooper-power-pad-mounted-transformer/cooper-power-pad-mount-three-phase-energy-efficient-distribution-transformer-data-sheet-ca202003en.pdf"),
        ("abb_transformer",
         "https://library.e.abb.com/public/d3a82d22a2734c5895049c4d5a25bc14/Distribution_Transformers_BR_EN.pdf"),
        ("siemens_geafol",
         "https://assets.new.siemens.com/siemens/assets/api/uuid:d3aedb2b-c826-4b03-8efc-7df37cf2dd25/version:1610981988/dip-transformers-geafol-cast-resin-en-2020.pdf"),
    ],
    "relay_setting_sheet": [
        # SEL / GE / ABB application notes that include setting tables.
        ("sel_setting_calc",
         "https://selinc.com/api/download/8267/"),
        ("ge_multilin_setting",
         "https://www.gegridsolutions.com/products/applications/protectionAndControl/PRO_QL_Multilin_369.pdf"),
        ("abb_relay_setting",
         "https://library.e.abb.com/public/95dac9efe7e74c8c8b9a8c1d2f4b9c1d/setting_guide.pdf"),
    ],
    "hvac_schedule": [
        # Public building project HVAC schedules — GSA / federal / university.
        ("gsa_hvac_example",
         "https://www.gsa.gov/cdnstatic/HVAC_equipment_schedule_sample.pdf"),
        ("doe_btb_hvac",
         "https://www.energy.gov/sites/default/files/2017/03/f34/HVAC_Equipment_Schedule_Example.pdf"),
        ("ashrae_sample",
         "https://www.ashrae.org/file%20library/standards/standard_90.1-2019_sample_compliance_doc.pdf"),
    ],
    "pid": [
        # P&ID samples from chemical / process industry.
        ("isa_pid_example",
         "https://www.isa.org/getmedia/9ec43e0f-2f64-4e2c-8aa9-fde22cdb2826/PID-example.pdf"),
        ("doe_process_pid",
         "https://www.energy.gov/sites/default/files/PID_example.pdf"),
        ("api_pid_sample",
         "https://www.api.org/~/media/Files/Publications/Standards/PID-sample.pdf"),
    ],
    "bom": [
        # Bills of material from public engineering / equipment submittals.
        ("nrc_adams_bom",
         "https://www.nrc.gov/docs/ML1334/ML13345A573.pdf"),
        ("doe_genmaterial_bom",
         "https://www.energy.gov/sites/default/files/2019/06/f63/Generator_BOM_sample.pdf"),
        ("ferc_intercon_bom",
         "https://www.ferc.gov/sites/default/files/2020-04/generator-interconnect-bom.pdf"),
    ],
    "civil_drawing": [
        # State DOT public submittals + municipal CIP.
        ("caltrans_civil",
         "https://dot.ca.gov/-/media/dot-media/programs/engineering/documents/site-grading-plan-sample.pdf"),
        ("nycdot_civil",
         "https://www.nyc.gov/assets/dot/downloads/pdf/site-grading-example.pdf"),
        ("usace_civil",
         "https://www.usace.army.mil/Portals/2/docs/civilworks/grading-plan-example.pdf"),
    ],
}


def try_download(url: str, timeout_sec: int = 20) -> Path | None:
    """curl --max-time → tmpfile. Return path on HTTP 200 + non-empty body, else None."""
    tmp = Path(tempfile.mkstemp(suffix=".pdf")[1])
    try:
        result = subprocess.run(
            [
                "curl", "-sS", "-L",
                "--max-time", str(timeout_sec),
                "-o", str(tmp), "-w", "%{http_code}",
                url,
            ],
            capture_output=True, text=True, timeout=timeout_sec + 5,
        )
        http_code = result.stdout.strip()
        if http_code != "200" or tmp.stat().st_size < 1024:
            tmp.unlink(missing_ok=True)
            return None
        return tmp
    except Exception:
        tmp.unlink(missing_ok=True)
        return None


_HTML_MASQUERADE_SIGNALS = [
    "404", "Page Not Found", "Content Not Available", "JavaScript required",
    "Sign in to your account", "Cookie Policy", "<!DOCTYPE html",
    "redirected", "<html", "</html>",
]


def validate_pdf(path: Path) -> tuple[bool, str]:
    """Open with fitz, require ≥1 page, ≥200 chars, NOT an HTML 404 disguised as PDF."""
    try:
        doc = fitz.open(str(path))
        try:
            pages = doc.page_count
            if pages < 1:
                return False, "0 pages"
            sample_text = "".join(doc[i].get_text() for i in range(min(pages, 3)))
            if len(sample_text) < 200:
                return False, f"only {len(sample_text)} chars of text (likely image-only)"
            # Reject HTML-masquerading-as-PDF (servers return 200 + HTML 404 page).
            for signal in _HTML_MASQUERADE_SIGNALS:
                if signal in sample_text:
                    return False, f"HTML error page detected (signal: {signal!r})"
            return True, f"{pages} pages, {len(sample_text)} chars on first 3"
        finally:
            doc.close()
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--dry-run", action="store_true",
        help="List candidates without downloading.",
    )
    args = parser.parse_args()

    FIXTURES.mkdir(parents=True, exist_ok=True)

    results: dict[str, dict] = {}
    for cls, candidates in CANDIDATES.items():
        results[cls] = {"landed": None, "attempts": []}
        if args.dry_run:
            print(f"\n[{cls}] would try {len(candidates)} URLs:")
            for suffix, url in candidates:
                print(f"  - {url}")
            continue
        print(f"\n[{cls}] trying {len(candidates)} candidates …")
        for suffix, url in candidates:
            print(f"  curl {url} …", end=" ", flush=True)
            tmp = try_download(url)
            if tmp is None:
                print("FAIL (no 200 or empty body)")
                results[cls]["attempts"].append({"url": url, "result": "download_failed"})
                continue
            ok, reason = validate_pdf(tmp)
            if not ok:
                print(f"INVALID ({reason})")
                tmp.unlink(missing_ok=True)
                results[cls]["attempts"].append({"url": url, "result": f"invalid: {reason}"})
                continue
            dest = FIXTURES / f"real_{cls}_{suffix}.pdf"
            tmp.rename(dest)
            print(f"OK → {dest.name} ({reason})")
            results[cls]["landed"] = {"url": url, "path": str(dest), "validation": reason}
            results[cls]["attempts"].append({"url": url, "result": "ok"})
            break
        if results[cls]["landed"] is None and not args.dry_run:
            print(f"  ⚠️ all candidates failed for {cls} — consider synthetic fallback")

    # Summary
    if not args.dry_run:
        print("\n" + "=" * 60)
        print("SUMMARY")
        print("=" * 60)
        landed_classes = [c for c, r in results.items() if r["landed"] is not None]
        failed_classes = [c for c, r in results.items() if r["landed"] is None]
        print(f"Landed ({len(landed_classes)}/{len(results)}):")
        for c in landed_classes:
            print(f"  ✅ {c} ← {Path(results[c]['landed']['path']).name}")
        print(f"Failed ({len(failed_classes)}):")
        for c in failed_classes:
            print(f"  ❌ {c} — try alternative URL or use synthetic fallback")
    return 0


if __name__ == "__main__":
    sys.exit(main())
