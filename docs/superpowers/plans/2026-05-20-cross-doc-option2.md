# Phase 11 — Cross-doc fixture (Option 2)

**Goal:** Add a second fixture pair (synthetic transformer spec ↔ real Eaton study) that exercises the cross-document semantic-alignment path Option 1's revision-diff fixture cannot. Verify via A/B test that Option 2 is strictly stronger demonstration.

**Approach:** Surgical, TDD, checkpointed. Iterate from failing test to green per task. One commit per task. Tag `phase-11-cross-doc` at end.

---

## First-principles framing

**What is Option 2 proving?** That the pipeline handles cross-document parameter overlap with semantic alignment + dimensional equivalence + directional authority — the **full wedge** per `CLAUDE.md`. Option 1 (revision-diff) demonstrates value-level diff with citations but uses layout-anchored matching; the embedding semantic path is dormant.

**Why "better"?** Better means:
1. Exercises a code path Option 1 does not (`align/semantic.py` Voyage embedding alignment).
2. Demonstrates a use case (spec ↔ study) judges expect when they read "cross-document."
3. Maintains 100 % recall on planted TPs and 0 % FP rate (same quality bar as Option 1).
4. Maps to the canonical AES authority hierarchy: equipment data sheet authoritative over downstream study.

**A/B test:** Both fixtures run through the same pipeline. Report per pair: flags surfaced, code path exercised, latency, recall on TPs, FP rate. Conclusion: Option 2 surfaces flags Option 1 cannot, via semantic alignment, while Option 1's layout-anchored path stays unused.

---

## Locked Option 2 fixture pair

- **Doc A (authoritative):** Synthetic transformer equipment data sheet `fixtures/pdfs/spec_xfmr_001.pdf`. One page. Real IEEE C57 style. Generated deterministically by `fixtures/synthesis/generate_spec.py`. Disclosed in AUTHORSHIP.
- **Doc B (downstream):** Existing real Eaton sample coordination study `fixtures/pdfs/doc_a_60pct.pdf`. Unmodified.

**Authority rule for this pair (hardcoded in `detect/authority.py`):** spec (Doc A) is authoritative for transformer physical parameters; coordination study (Doc B) is the downstream reference.

---

## Locked gold set for Option 2

Six labeled cases in `fixtures/eval/gold_cross_doc.yaml`.

| ID | Category | Expected | Spec value | Eaton value | What it tests |
|---|---|---|---|---|---|
| TP-CD-1 | parameter_mismatch | surfaced ≥ 0.5 | Rated Impedance: 5.7 % | 5.75 % Z | Semantic alignment + value mismatch |
| TP-CD-2 | parameter_mismatch | surfaced ≥ 0.5 | Rated Power: 1100 kVA | 1000 KVA | Different naming, value mismatch |
| TP-CD-3 | parameter_mismatch | surfaced ≥ 0.5 | Primary Voltage: 12.47 kV | 13.8 kV | Different naming, value mismatch |
| FP-CD-1 | unit_normalization | suppressed | Secondary Voltage: 480 V | 480 V | Equal values, no flag |
| FP-CD-2 | unrelated_param | suppressed | Frequency: 60 Hz | (not present) | No counterpart, no flag |
| FP-CD-3 | unrelated_param | suppressed | BIL: 95 kV | (not present) | No counterpart, no flag |

Acceptance threshold:
- Recall on TPs: 100 % (all three surfaced above 0.5).
- FP rate on traps: 0 %.

---

## Implementation surgical edits

The existing pipeline already handles most of this. Anticipated surgical changes:

1. `align/semantic.py` — `same_page_only` parameter default may need to be `False` for cross-doc (spec is 1 page, Eaton is 9). If currently hardcoded True, lift to a pipeline-level toggle.
2. `extract/parameters.py` — may need 1–2 new patterns to catch spec key:value layouts.
3. `detect/authority.py` — extend `authority_for` to recognize the new fixture pair (or pass authority hint through pipeline).
4. `pipeline.py` — accept `cross_doc=True` toggle that disables same-page constraint.
5. `src/interlock/ui/app.py` — checkbox "Cross-document mode (allow alignment across pages)".

If a change touches a file outside this list, surface it in the plan before making it.

---

## Tasks (TDD)

### Task 11.1 — Synthetic spec content brainstorm + design

Captured above. No code yet. Move on.

### Task 11.2 — Deterministic spec generator

**Files:**
- Create: `fixtures/synthesis/generate_spec.py`
- Create: `fixtures/pdfs/spec_xfmr_001.pdf` (output)
- Modify: `fixtures/pdfs/HASHES.txt`

- [ ] Write generator script: emits 1-page PDF with header, 8–12 parameters (key: value lines), realistic IEEE C57 layout.
- [ ] Generate the PDF.
- [ ] Append SHA-256 to HASHES.txt.
- [ ] Commit.

### Task 11.3 — Gold set YAML

**Files:**
- Create: `fixtures/eval/gold_cross_doc.yaml`

- [ ] Write gold set per table above.
- [ ] Commit.

### Task 11.4 — Failing eval test for cross-doc pair

**Files:**
- Create: `tests/eval/test_harness_cross_doc.py`

- [ ] Write test that runs pipeline against (spec, eaton) and asserts recall/FP thresholds.
- [ ] Run test, expect FAIL.

### Task 11.5 — Iterate pipeline to pass

- [ ] Run pipeline, inspect surfaced flags vs gold.
- [ ] Surgical edits per the list above until gold passes.
- [ ] Each iteration: commit before the next.

### Task 11.6 — A/B comparison script

**Files:**
- Create: `scripts/run_ab.py`
- Create: `eval/results/ab_comparison.json`

- [ ] Script runs both gold sets sequentially, records: flag count, code paths exercised (exact_pair / semantic_pair), latency, recall, FP rate.
- [ ] Write JSON summary.
- [ ] Acceptance: Option 2 surfaces ≥ 1 flag via semantic path; Option 1 surfaces 0 via semantic path.
- [ ] Commit.

### Task 11.7 — UI cross-doc mode toggle

**Files:**
- Modify: `src/interlock/ui/app.py`

- [ ] Add "Cross-document mode" checkbox that toggles `same_page_only=False`.
- [ ] Smoke test locally.
- [ ] Commit.

### Task 11.8 — Documentation update

**Files:**
- Modify: `docs/FIXTURES.md` (add §1B Option 2 fixture)
- Modify: `docs/AUTHORSHIP.md` (disclose synthetic spec)
- Modify: `docs/DEMO_SCRIPT.md` (add cross-doc demo segment)
- Modify: `docs/TDD.md` (note Option 2 exercises semantic path)
- Modify: `docs/BACKLOG.md` (mark Option 2 done; Option 4 still open)
- Modify: `README.md` (mention both demos)

- [ ] Update each.
- [ ] Commit.

### Task 11.9 — Phase 11 checkpoint

- [ ] Full test suite green.
- [ ] mypy strict clean.
- [ ] ruff clean.
- [ ] A/B comparison verifies Option 2 strictly stronger.
- [ ] Merge phase branch into main.
- [ ] Tag `phase-11-cross-doc`.
- [ ] Push.

---

## Out of scope for Phase 11

- Real spec curation (Option 4 — a follow-up phase).
- Standards-as-authority (BACKLOG).
- Multi-page spec.
- Scanned-PDF spec (BACKLOG).
