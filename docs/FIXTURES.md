# InterLock AI MVP — Locked Fixtures and Evaluation Gold Set

**Status:** Locked on 2026-05-19. Companion to `docs/SCOPE.md`. Any change requires a dated entry in the Change Log section at the bottom.

This document defines the exact PDFs, mutations, authority declarations, and labeled flags the MVP is built against. The plan in `docs/superpowers/plans/2026-05-19-interlock-mvp.md` references this file by section number. If a test or piece of code needs ground truth, the answer is in this file or the file does not satisfy the MVP success criteria.

---

## 1. Fixture pair selection rationale

The MVP demonstrates the wedge by surfacing one or more directional, consequential parameter mismatches between two engineering PDFs from a notionally shared project. Three options were considered. The choice and rejected alternatives are recorded here so the decision is not relitigated.

**Considered options**

- **Option A — two unrelated real PDFs, find naturally divergent value.** Pros: maximally honest. Cons: parameters do not actually overlap, so any "found" mismatch is contrived in a different way.
- **Option B — real Doc A unchanged, real Doc B with documented mutation.** Pros: real source provenance, ground truth is exact, mutation maps directly to AES's transformer-decimal anecdote. Cons: Doc B is technically derived.
- **Option C — two real PDFs with no mutation, surface a real semantic ambiguity (e.g., unit convention difference).** Pros: maximally honest. Cons: depends on a specific naturally occurring discrepancy in chosen docs; hard to find under time pressure; eval ground truth is fuzzy.

**Chosen: Option B**, framed as a phase-revision diff between a 60% and 90% design submittal of the same coordination study. This framing maps cleanly to the 30/60/90 lifecycle the platform path targets and produces an unambiguous ground truth for the evaluation harness. The authorship note will disclose the mutation in full.

---

## 2. Locked fixture documents

### Doc A — "60% Design Package, Coordination Study Excerpt"

- **Role:** Authoritative (frozen baseline reviewers compare against)
- **Source:** Eaton sample coordination study, public PDF, used as-is, no mutation
- **URL:** https://www.eaton.com/content/dam/eaton/products/electrical-circuit-protection/fuses/selective-coordination-ii/bus-ele-sample-coordination-study.pdf
- **Local path:** `fixtures/pdfs/doc_a_60pct.pdf`
- **Provenance recording:** SHA-256 hash captured in `fixtures/pdfs/HASHES.txt` at download time
- **Pages used in demo:** to be confirmed in Phase 1 page-scan task; pages containing fuse/breaker coordination tables and transformer-side fault current tables

### Doc B — "90% Design Package, Coordination Study Revision"

- **Role:** Downstream (revision under review against Doc A)
- **Source:** Derived from Doc A via documented mutations
- **Local path:** `fixtures/pdfs/doc_b_90pct.pdf`
- **Mutation set:** see `fixtures/mutations/MUTATIONS.md` (created in Phase 1)
- **Provenance recording:** SHA-256 hash of the mutated PDF captured alongside the mutation log

### Doc C — reference standard (out of MVP scope, recorded for platform path)

The IEEE Guide for Preparation of Transformer Specifications was considered as a third document for standards-cross-check. **Excluded from MVP** per `SCOPE.md` anti-scope item 2 (no more than two documents per session). Referenced here only so the platform-path conversation in the PRD has a concrete example.

---

## 2B. Option 2 — cross-doc fixture pair (added 2026-05-20)

A second fixture pair built to exercise the cross-document semantic alignment path that Option 1's revision-diff fixture leaves dormant.

### Spec — `fixtures/pdfs/spec_xfmr_001.pdf`

- **Role:** Authoritative (equipment data sheet supersedes downstream studies per `CLAUDE.md` authority hierarchy)
- **Source:** **Synthetic** — generated deterministically by `fixtures/synthesis/generate_spec.py`. One page, IEEE C57.12.00 nameplate-style layout.
- **Disclosure:** disclosed in `docs/AUTHORSHIP.md`. Real-spec curation is Option 4 (BACKLOG).
- **Provenance:** SHA-256 in `fixtures/pdfs/HASHES.txt`.

### Study — `fixtures/pdfs/doc_a_60pct.pdf`

The same Eaton coordination study used as Doc A in Option 1, here reused as the downstream document. Unmodified.

### Gold set — `fixtures/eval/gold_cross_doc.yaml`

6 labeled cases:
| ID | Expected | Tests |
|---|---|---|
| TP-CD-1 | surfaced ≥ 0.5 | Rated Impedance 5.7 % vs %Z 5.75 % (semantic-aligned via canonical glossary) |
| TP-CD-2 | surfaced ≥ 0.5 | Rated Power 1100 kVA vs Transformer Rating 1000 kVA |
| TP-CD-3 | surfaced ≥ 0.5 | Primary Voltage 12.47 kV vs System Voltage 13.8 kV |
| FP-CD-1 | suppressed | Secondary Voltage 480 V — equal in both, no flag |
| FP-CD-2 | suppressed | Frequency 60 Hz — no counterpart, no flag |
| FP-CD-3 | suppressed | BIL 95 kV — no counterpart, dim-distinct from system voltage, no flag |

### Authority rule for this pair

Doc A (spec) authoritative for transformer physical parameters; Doc B (study) is the downstream reference. Hardcoded in `detect/authority.py` for MVP; configurable in platform path.

### A/B verification

`scripts/run_ab.py` runs the same pipeline against both pairs and asserts:
- Option 1 produces flags via layout-anchored exact matching (`n_pairs_exact > 0`, all flags exact-derived).
- Option 2 requires semantic alignment (`n_pairs_exact == 0`, all 3 flags semantic-derived).
- Option 2 demonstrates a capability Option 1 cannot — cross-document flag surfacing.

Result file: `eval/results/ab_comparison.json`.

---

## 3. Mutation policy

Mutations to Doc B are governed by these rules. Any mutation that violates them must not be added to the fixture.

1. Every mutation is recorded in `fixtures/mutations/MUTATIONS.md` with: original value, mutated value, page, section, locator (text span before/after), category (TP planted, FP trap, FN risk), rationale, and SHA-256 of the resulting PDF.
2. Mutations must be realistic engineering errors. A decimal shift in an impedance value is realistic. Replacing every number on a page is not.
3. No mutation may change document structure, page count, or section ordering. Mutations are value-level edits only.
4. Mutations are applied by a deterministic script (`fixtures/mutations/apply_mutations.py`) so the fixture can be regenerated from Doc A at any time. The script is committed.
5. The authorship note discloses the full mutation list and links to `MUTATIONS.md`.

---

## 4. Authority declaration for this fixture pair (hardcoded for MVP)

For the locked fixture pair, the hardcoded authority rule is:

> **Doc A is authoritative for all parameters that appear in both documents. Doc B is the deviation candidate.**

Rationale: in a 60% → 90% review context, the 60% baseline is the prior approved state. A 90% revision that changes a value must justify the change. In MVP, any value-level deviation flags Doc B as deviating from Doc A.

Beyond MVP, authority is per-parameter and per-document-type (data sheet beats study beats one-line diagram). The MVP hardcodes a single rule because `SCOPE.md` anti-scope item 3 forbids the configurable authority UI.

---

## 5. Planned mutations (target set for Phase 1)

These mutations will be applied to Doc B in Phase 1. The exact page numbers and text spans are filled in during the page-scan task; the **types and categories** are locked now.

| # | Category | Mutation type | Realistic class | Expected gold-set label |
|---|---|---|---|---|
| 1 | TP — must flag | Decimal shift in transformer impedance value (e.g., 5.75% → 0.575%) | Mirrors AES anecdote | TP-1 |
| 2 | TP — must flag | Unit-class change in a fault current value (e.g., kA → A without rescaling) | Common units-typo error | TP-2 |
| 3 | TP — must flag | CT ratio change (e.g., 1200:5 → 120:5) | Protection-setting misconfiguration | TP-3 |
| 4 | FP trap — must NOT flag | Reformat a value without changing its meaning (e.g., 132 kV → 132,000 V on same row) | System must recognize unit-normalized equivalence | FP-1 |
| 5 | FP trap — must NOT flag | Section heading rephrase only, no parameter change | System must not flag headings | FP-2 |
| 6 | FN risk — should flag at lower confidence | Parameter present in Doc A, removed from Doc B | Checklist-gap pattern | FN-1 |

Total: 6 planned. Phase 1 may add up to 2 more after the page scan if additional realistic mutation sites are obviously present. The cap is 8.

---

## 6. Evaluation gold set

The gold set lives at `fixtures/eval/gold.yaml`, generated in Phase 1 directly from the mutation log. Schema:

```yaml
flags:
  - id: TP-1
    category: parameter_mismatch
    expected: surfaced
    min_confidence: 0.7
    doc_a:
      page: <int>
      section: <str>
      span_text: <str>
      value: <str>
    doc_b:
      page: <int>
      section: <str>
      span_text: <str>
      value: <str>
    authority: doc_a
    notes: "Planted decimal shift mirroring AES transformer anecdote."
  - id: FP-1
    category: unit_normalization
    expected: suppressed
    max_confidence: 0.4
    doc_a: { ... }
    doc_b: { ... }
    notes: "132 kV vs 132,000 V — unit-equivalent, must not be flagged."
```

The evaluation harness in Phase 8 reads this file, runs a review, and computes:

- precision = TP / (TP + FP)
- recall = TP / (TP + FN)
- F1 = harmonic mean
- per-category breakdown

Acceptance threshold for MVP (locked, ties into `SCOPE.md` section 6):

- Recall on TP items: 100% (all three planted mismatches surfaced at confidence ≥ 0.6).
- FP rate on FP trap items: 0 (no trap surfaced at confidence ≥ 0.6).
- FN-1 may be surfaced at lower confidence (≥ 0.4); not required for MVP pass.

---

## 7. Symbol fidelity probe (locked test set for Phase 1)

Before parameter extraction is built, the ingestion pipeline must round-trip these characters from a probe PDF without mangling. The probe is generated in Phase 1.

Required: Ω, μ, μF, kV, MVA, θ, Δ, cos φ, °C, ±, ≤, ≥

Acceptance: every character above appears intact in the extracted text. If any does not, Phase 1 must not be marked complete.

---

## 8. Change log

- 2026-05-19: Initial lock. Doc A selected (Eaton coordination study). Doc B derivation strategy approved. Six planned mutations defined. Authority rule hardcoded to "Doc A authoritative."
