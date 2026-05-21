# InterLock AI MVP — Demo Script

Target length: **3 minutes** (hard cap 5 per brief). Plain screen recording, voice-over.

The script below is structured as **three short segments** the reviewer can mix-and-match: revision-diff (Option 1), cross-document (Option 2), and scanned-PDF OCR. A 2-minute video covers Option 1 only; a 4-minute video covers all three.

---

## Segment A — Revision-diff (Option 1) · 0:00–1:30

### 0:00–0:15 — Frame the problem

> "Engineering teams at companies like AES review hundreds of cross-referenced documents on every project. A misplaced decimal in a transformer spec almost cost them a multi-million-dollar loss — caught only because a senior engineer happened to spot it during a 60% review. InterLock AI is a review assistant that catches that kind of cross-document discrepancy automatically, with citations and honest confidence."

Visual: README title block.

### 0:15–0:30 — Upload

> "Reviewer uploads two PDFs from the same project. Doc A is the 60% baseline coordination study. Doc B is the 90% revision under review."

Action: drag `doc_a_60pct.pdf` and `doc_b_90pct.pdf` onto the Streamlit page. Click **Run review**.

Visual: the live `st.status` block — each pipeline stage (Ingesting Doc A → Ingesting Doc B → Extracting parameters → Aligning → Detecting → optional LLM judge) ticks ⏸️ → ⏳ → ✅ in real time with per-stage elapsed.

> "The status panel shows each pipeline stage live, not a frozen checklist. Total wall-clock around 30 seconds on a cold cache."

### 0:30–0:55 — Flag list

> "Four critical flags surface, all decimal-shift class — the canonical AES failure mode. Each flag declares which document is authoritative and which is the deviation candidate."

Visual: the flag list, severity-grouped with red 🔴 chips.

Read out:
- `%Z: 5.75 % → 0.575 %` — decimal slip on transformer impedance
- `Fault Current: 20,000 A → 200,000 A` — order-of-magnitude grouped-digit slip
- `Transformer Rating: 1000 kVA → 100 kVA` (two instances on different pages)

> "Severity comes from per-attribute tolerance bands sourced from IEEE C57.12.00, IEC 60076-1, and NEMA TR 1 — every band cites its source. A 5.75% impedance drifting to 5.77% would classify as `info` and be suppressed by default; that's the noise reduction that keeps reviewer trust."

### 0:55–1:15 — Click into a citation

Action: expand the impedance flag.

> "Both sides show a bounding-box-highlighted snippet of the source page. The reviewer verifies in seconds without leaving InterLock. Below each snippet, the exact text excerpt for that record."

Visual: side-by-side snippet PNGs, red boxes on the spans, text excerpts below.

> "Notice the caption: `pairing confidence 1.00`. The system tracks not just how sure it is about the values, but how sure it is the two records describe the same thing. Weak pairings get a `⚠️ weak pair` badge and are collapsed by default — the reviewer is told when to verify the correspondence itself."

### 1:15–1:30 — Accept, dismiss, export

Action: Accept on the impedance flag. Dismiss one of the transformer-rating duplicates.

> "Reviewer triages. Accepted flags export as JSON for the audit log."

Action: click **Export accepted flags**. Show the file briefly.

Visual: glance at the JSON record (severity, deviation_pct, citation tuple).

---

## Segment B — Cross-document (Option 2) · 1:30–2:30 (optional)

> "Same pipeline, different fixture. Now Doc A is an equipment data sheet — a transformer nameplate spec. Doc B is the coordination study. Different document types, different layouts, different parameter naming."

Action: clear, upload `spec_xfmr_001.pdf` and `doc_a_60pct.pdf`. Click **Run review**.

> "Three real engineering discrepancies surface."

Visual: flag list.

- `Rated Power: 1100 kVA → 1000 kVA` — minor (9% deviation, within IEEE C57 ±10% manufacturing tolerance bracket but worth surfacing)
- `Primary Voltage: 12.47 kV → 13.8 kV` — major (10.7% deviation; pairing confidence 0.90 because it's a semantic match `Primary Voltage` ↔ `System Voltage`)
- `Rated Impedance: 4.5 % → 5.75 %` — major (28% deviation; the coordination is computed against the wrong impedance — protection tuning will be off)

> "The canonical engineering glossary maps `%Z`, `Rated Impedance`, `Per Unit Impedance` to the same concept before values are compared. Adobe Acrobat's textual diff can't do this. Voyage embeddings + the glossary carry the cross-document wedge."

Action: scroll to the **📋 Unpaired records** expander.

> "The system is honest about what it didn't compare. The spec mentions Secondary Voltage 480 V, Frequency 60 Hz, BIL 95 kV, and Insulation Class 55°C — the coordination study doesn't restate any of those, so they're surfaced as unpaired for the reviewer to verify separately. Silent gaps would look like clean runs; explicit gaps trigger manual review."

---

## Segment C — Scanned-PDF OCR · 2:30–3:30 (optional, demonstrates rubric depth)

> "What if a document only exists as a scanned image? The locked fixture `doc_a_scanned.pdf` is a JPEG-encoded raster of the same coordination study — zero native text."

Action: toggle **Enable vision OCR** in the sidebar. Upload `doc_a_scanned.pdf` paired with `doc_a_60pct.pdf` (or another revision).

Visual: the live OCR progress bar — `OCR: 4/9 pages complete (last: page 6)` ticking up as parallel API calls (5-worker pool) complete.

> "Vision OCR routes only the low-coverage pages — pages with under 80 characters of native text. Claude Sonnet 4.5 transcribes each at 300 DPI. The output is split per-line so downstream snippet excerpts read cleanly. A two-pass plausibility loop catches numeric hallucinations: if any extracted engineering value falls outside its family's plausibility range, the page is re-OCR'd at 400 DPI with a verification prompt. Only the suspect pages pay the extra cost."

> "All 9 pages re-rendered to text, 54 parameters recovered against 52 from the native baseline — 104% yield. Cached, so re-runs are free."

Action: scroll to a flag with `🔍 OCR (whole-page snippet)` caption.

> "OCR-derived flags are marked because vision models lack per-line bounding boxes; the snippet image shows the whole page rather than the exact line. The text excerpt below the image scopes down to the relevant row."

---

## Optional 10-second LLM judge segment

Use only if the recording has budget after the three segments.

Action: toggle **Use LLM significance judge** in the sidebar. Re-run.

> "Each flag gets an engineering rationale plus downstream-effect propagation, computed by Claude Opus 4.7 with prompt-cached ontology. Disk-cached per flag, so the second run costs effectively zero."

Visual: expand one flag, point at the LLM-generated rationale paragraph.

---

## Pre-recording checklist

- [ ] Decide: record against local `streamlit run` or the **deployed URL** https://interlock-ai-re8mb948inkerzmkn5zpgv.streamlit.app/ ? Deployed is more honest (shows reviewers what they'll see); local is faster and avoids cold-start risk.
- [ ] If deployed: pre-warm the URL 10 minutes before recording so the first interactive click is fast.
- [ ] `.env` populated: `VOYAGE_API_KEY`, `ANTHROPIC_API_KEY` (local runs only — deployed instance has them server-side).
- [ ] `uv run streamlit run src/interlock/ui/app.py` opens without errors (fallback path if cloud flakes).
- [ ] All four demo PDFs accessible from the desktop:
  - `fixtures/pdfs/doc_a_60pct.pdf`
  - `fixtures/pdfs/doc_b_90pct.pdf`
  - `fixtures/pdfs/spec_xfmr_001.pdf`
  - `fixtures/pdfs/doc_a_scanned.pdf` (only if doing Segment C)
- [ ] Browser zoom set so the flag list is visible without scrolling on a 1080p screen.
- [ ] Mic test, audio level checked.
- [ ] One dry-run end-to-end before recording (Segment A at minimum).
- [ ] Vision-OCR cache pre-warmed (run once before recording so the progress bar fills predictably).

## Recording URL

(Add the YouTube / Loom / direct-file link after recording.)
