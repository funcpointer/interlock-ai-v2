# Prototype results — multi-modal redesign validation

**Date:** 2026-05-23
**Spend:** ~$0.05 (3 prototype runs)
**Outputs:** `/tmp/proto1_vision_extraction.md`, `/tmp/proto2_per_token_bbox.md`, `/tmp/proto3_cross_doc_resolution.md`

## Summary

Three core assumptions of the multi-modal redesign (`docs/superpowers/specs/2026-05-23-multimodal-extraction-redesign.md`) tested:

| Assumption | Result | Source |
|---|---|---|
| Sonnet 4.5 Vision extracts structured `(entity, parameter, value)` from real engineering diagrams | **PASS** | proto1 |
| Sonnet 4.5 Vision returns reliable per-token bboxes for OCR-modality lane | **PARTIAL** (returned 68 tokens; script bug truncated dump — need re-run with fix) | proto2 |
| Cross-doc LLM resolution correctly maps `T-1 → XFMR-001` style different-conventions pairs | **PASS** (5/5 expected mappings) | proto3 |

**Verdict.** Two of three core assumptions verified. The remaining one (per-token bbox reliability) is unblocking only for Sprint 10 (OCR-modality lane, P1). Sprint 7 + 8 + 9 can proceed.

## Proto 1 — Vision extraction on Option 1 doc_a p6 (the LPS-RK demo bug page)

Sent rendered PNG of the failing page to Sonnet 4.5 Vision with structured-output prompt.

**Returned for both docs:** 23 claims, identical structure, correct grounding:
- `KRP-C-1600SP`, `LPS-RK-400SP`, `LPS-RK-100SP`, `JCN 80E` all recognized as `equipment`
- `400A Feeder` recognized as `circuit` (correct — NOT `equipment`)
- `5.75 %Z` bound to the `1000KVA 5.75%Z` transformer entity (NOT a fuse — correct)
- `13.8 KV` bound to source voltage (NOT a fuse)
- Each claim carries `visual_evidence` text like "Label appears next to a fuse symbol immediately below the transformer secondary in the one-line diagram" — reviewer can audit

**Critical:** Doc A's `LPS-RK-400SP` and Doc B's `LPS-RK-100SP` are CORRECTLY separated as distinct entities with distinct values. The bad cross-pair from v2.7 would not form because the vision lane returns:
- Doc A: `LPS-RK-400SP` (equipment) — value `LPS-RK-400SP`
- Doc A: `LPS-RK-100SP` (equipment) — value `LPS-RK-100SP`
- Doc B: same two entities, same values

Cross-doc pairing would match Doc A's `LPS-RK-400SP` to Doc B's `LPS-RK-400SP` (same canonical_id, same value → no mismatch flag). Likewise for `LPS-RK-100SP`. The demo bug dies at vision extraction.

**Cost:** ~$0.02 per page (2 pages tested = ~$0.04).

## Proto 2 — Per-token bbox extraction (partial)

Sent rendered PNG with a "return per-token bboxes" prompt.

Sonnet returned **68 tokens** with `(text, x_top_left, y_top_left, x_bottom_right, y_bottom_right, confidence)` for each. First 20 tokens visible in the dump are axis labels (`Example`, `Time`, `Current`, `Curve`, `1000`, `800`, ...) with plausible coords and confidence 0.95-0.99.

**Script bug:** the prototype only wrote first 20 tokens to markdown. Need to re-run with a script fix to verify if `LPS-RK-100SP`, `LPS-RK-400SP`, `KRP-C-1600SP` tokens are present + have distinguishable y-coords.

**Provisional verdict:** Sonnet WILL return per-token bboxes for this kind of page. Reliability for the specific tokens we care about is **not yet verified**.

**Implication for Sprint 10:** Plan proceeds, but re-run proto2 (with script fix) before Sprint 10 spec lock. Even if per-token bboxes for fuse labels prove unreliable on densely-labelled diagrams, the OCR-modality lane still works for scanned PROSE / TABLE pages (which are the more common scanned-doc-review case). Only scanned DIAGRAMS would degrade to whole-page-bbox fallback.

**Cost:** ~$0.01.

## Proto 3 — Cross-doc entity resolution (T-1 ↔ XFMR-001)

Synthetic test: 5 Doc A entities (T-1, T-2, M-3, F-12, T-3) vs 5 Doc B entities (XFMR-001, XFMR-002, MOTOR-003, FUSE-012, RELAY-045).

**Results:** 5/5 expected mappings correct:
- T-1 → XFMR-001 (conf 0.95): "Both equipment/T-1 and equipment/XFMR-001 are described as main transformers with identical specifications of 1500 kVA 13.8/0.48 kV."
- T-2 → XFMR-002 (conf 0.95)
- M-3 → MOTOR-003 (conf 0.90): "with numeric suffixes matching"
- F-12 → FUSE-012 (conf 0.90): "with matching numeric suffixes (12/012)"
- T-3 → (unmatched, conf 1.00): "explicitly noted as NOT ON DOC B"

**Hallucination guard candidate works:** every rationale cites both IDs by name. Doc B's RELAY-045 (with no Doc A counterpart) correctly omitted — not invented.

**Cost:** ~$0.01.

## Implications for the rollout plan

### Sprint 7 (instrumentation) — proceeds as designed

No assumption depends on the prototypes. Ships first.

### Sprint 8 (vision lane for diagrams, P0) — proceeds; can be MORE aggressive

Proto 1 result is so clean that the Sprint 8 spec can:
- Skip the proposed "fallback to current text path" complexity for born-digital diagrams. Vision lane IS the path; no fallback needed unless API outage (which is a separate concern handled at higher layer).
- Lock the prompt template from proto 1's confirmed-good shape (claim list with `entity_kind`, `entity_id`, `entity_location_hint`, `visual_evidence`).
- Use existing diskcache (`llm-entities` namespace pattern) keyed on (PDF hash, page, prompt_version, model).

### Sprint 9 (cross-doc resolution + aliases, P0) — proceeds; cheaper than budgeted

Proto 3 confirms a single-prompt resolver works for the 5-entity case. Sprint 9 spec can:
- Skip the proposed embedding-shortlist optimization (§9 attack #4 in design doc) until corpus size exceeds 20-30 entities per doc. Cheap inline LLM call suffices for smaller doc-pairs.
- Use proto 3's prompt shape verbatim as the Sprint 9 starting template.

### Sprint 10 (OCR-modality, P1) — proceeds, with proto 2 re-run as a prerequisite

Before Sprint 10 spec lock:
1. Fix proto 2 script to dump ALL tokens (not just 20).
2. Re-run on same page + a scanned-no-text fixture (synthesized if needed).
3. Verify: are `LPS-RK-*` token bboxes distinguishable? Are confidence values per-token meaningful?
4. If reliable → Sprint 10 vision-OCR lane works as designed.
5. If unreliable on diagrams but reliable on prose/tables → Sprint 10 scope narrows: OCR-modality lane handles prose + table; scanned diagrams stay on Sprint 8's vision-lane (which works regardless of bbox availability).

### Anti-overfitting check

Prototypes were on the Option 1 fixture (the failing case). Sprint 8 + 9 specs should explicitly require additional fixtures from the §10 matrix before exit:
- Sprint 8 vision lane: ALSO validate on a NON-Option-1 diagram fixture (synthesize a 1-page schematic with 3 fuses + 1 transformer).
- Sprint 9 cross-doc: ALSO validate on a real spec ↔ study pair (existing `spec_xfmr_001.pdf` ↔ `doc_a_60pct.pdf` already in `fixtures/eval/gold_cross_doc.yaml` covers this).

## Next steps

1. Sprint 7 spec + plan + execute (audit chain + structure classifier).
2. In parallel: 100-line LPS-RK hotfix (drop nearest-fallback in `entity_bind.py`) — kills the demo bug NOW; Sprint 8 vision lane is the proper long-term fix.
3. After Sprint 7 ships: re-run proto 2 with script fix.
4. Sprint 8 spec + plan + execute (vision lane).
5. Sprint 9 spec + plan + execute (cross-doc resolution + aliases).
6. Sprint 10 spec + plan + execute (OCR-modality lane) — only if proto 2 re-run confirms per-token bbox reliability.
7. Sprint 11 spec + plan + execute (CI matrix gates).
