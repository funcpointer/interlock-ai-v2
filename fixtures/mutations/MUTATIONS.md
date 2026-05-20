# Doc B Mutations

Derived from `fixtures/pdfs/doc_a_60pct.pdf` (Eaton sample coordination study) by `fixtures/mutations/apply_mutations.py`. Doc B is framed as a "90% design revision" of Doc A. Authority is hardcoded so Doc A is the baseline; Doc B deviations are flagged.

| ID | Category | Page | Original span | Mutated span | Rationale |
|---|---|---|---|---|---|
| TP-1 | parameter_mismatch | 3 | `5.75%Z, liquid` | `0.575%Z, liquid` | Decimal shift in transformer impedance — mirrors AES anecdote |
| TP-2 | parameter_mismatch | 2 | `Fault X1 20,000A RMS Sym` | `Fault X1 200,000A RMS Sym` | Decimal shift in fault current value |
| TP-3 | parameter_mismatch | 7 | `1000KVA XFMR` | `100KVA XFMR` | Decimal shift in transformer rating; restricted to p7 only |
| FP-1 | unit_normalization | 7 | `150 KVA XFMR` | `0.15 MVA XFMR` | Unit-equivalent value — must NOT flag (Pint should normalize 150 kVA == 0.15 MVA) |
| FP-2 | heading_only | 3 | `Time Current Curve #1 (TCC1)` | `Time Current Curve 1 (TCC1)` | Heading rephrase, no parameter touched — must NOT flag |
| FN-1 | checklist_gap | 7 | `LPN-RK-500SP` | (redacted) | Parameter present in Doc A, removed from Doc B — checklist gap (lower-confidence flag) |

All mutations apply via PyMuPDF redaction with text replacement. Doc B is regeneratable from Doc A by running `apply_mutations.py`.

## Authority for this pair

Doc A (60% baseline) is authoritative. Doc B (90% revision) is the deviation candidate. Any value-level disagreement flags Doc B.
