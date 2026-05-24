# Codex Adversarial Review — v2.8.x + Sprint 9

**Date:** 2026-05-24
**Reviewer:** Codex (GPT-5, static review only — codex-companion.mjs unavailable)
**Subject:** v2.8.x patch series + `docs/superpowers/specs/2026-05-24-sprint-9-cross-doc-entity-resolution.md`

Reproduced verbatim from Codex's response. Companion to `2026-05-24-v2.8.x-adversarial-review.md` (session-internal self-critique).

---

## A. Patch Series

**FOR:** v2.8.x fixes real observed defects. The patches are locally rational: strict-tag fallback, page-window tightening, row-marker priority, rerank override, page-scoped gaps. Each protects a known failure mode.

**AGAINST:** System is now policy hidden in scattered heuristics. Same concept, **equipment identity**, is re-derived in `exact.py`, `dedup.py`, `checklist.py`, `pair.py`, and vision guard. That is architectural debt, not iteration. Class C remains because no patch owns "same physical equipment."

**CALL:** Sprint 9 should have started earlier. Keep v2.8.8 only as demo stabilization. Do not add v2.8.9 unless it is a kill-switch or telemetry patch.

---

## B. `_string_family`

**FOR:** Cheap, deterministic, testable. It blocks obvious bad fuse-family pairings without LLM cost.

**AGAINST:** Regex family is fake ontology. "JCN 80E" proves the treadmill. It encodes surface spelling, not equipment kind. It will miss vendor variants and overtrust prefixes.

**CALL:** Replace with structured `equipment_kind` plus `designation_family`. A small LLM extraction call can help, but only if constrained to schema + evidence spans. **Do not let it free-classify silently.**

---

## C. `_PAGE_WINDOW = 0`

**FOR:** Correct for the demo failure. Cross-page dedup was deleting real repeated equipment slots. Dedup should collapse extraction duplicates, not infer physical identity across pages.

**AGAINST:** It punts legitimate same-equipment multi-page references. One-line schedule on p2 plus TCC on p5 now survive as separate records, causing duplicate flags or missed consolidation.

**CALL:** Same-page dedup is right. Cross-page identity belongs in inventory, not dedup. **Fixtures broken:** schedules plus plots, one-line summaries plus detail sheets, repeated transformer callouts across coordination pages.

---

## D. Gold Fixtures

**FOR:** Regression gold is necessary. Without it, FE-mode changes become anecdote-driven.

**AGAINST:** Gold is now an oracle for **symptoms, not truth**. If p2 `5.75% ↔ 2%` is a real mutation but absent from gold, tests train the system to suppress reality.

**CALL:** Current gold is insufficient. **Add equipment-level gold** with explicit "expected match / expected mutation / expected gap." Keep record-level gold only as diagnostic, not final truth.

---

## E. Sprint 9 Matcher

**FOR:** Inventory plus cross-doc matcher is the right spine. It attacks the root: entity identity before parameter comparison.

**AGAINST:** Spec is under-specified. Jaccard descriptors fail when one side is richer: `1000KVA XFMR liquid 5.75%` vs `1000kVA XFMR`. Embeddings risk collapsing distinct same-rating transformers. Page locality fails when revisions reflow. **No conflict policy for one-to-many, many-to-one, duplicate names, or descriptor disagreement.**

**CALL:** Direction wins, spec not ready. Add **deterministic blocking keys, bipartite matching, contradiction penalties, evidence spans, and abstain states**. Embeddings should only propose candidates, never decide.

---

## F. Vision Guard

**FOR:** Grounding vision claims against text layer blocks hallucinated entity IDs. Good default for high-precision extraction.

**AGAINST:** It rejects the exact cases vision is meant to rescue: rotated labels, rasterized schedules, embedded image text, bad PDF text order. Per-word fallback also accepts weak bags of words.

**CALL:** Guard is **too strict as a hard drop**. Use OCR/render evidence as alternate grounding: image crop + coordinates + OCR tokens. If PyMuPDF text misses it, mark `vision_grounded_image_only`, not discard.

---

## G. Page-Scoped Checklist Gap

**FOR:** Same-page strictness catches real removals from TCC/checklist context. Document-wide suppression was too blunt.

**AGAINST:** **Page equality is not context.** It flags KRP-C/LPS-RK when the value exists elsewhere but the local table changed shape. It confuses "removed from this table" with "equipment removed."

**CALL:** Add row-context/table-context. Flag only when Doc A and Doc B have matched table structures or matched equipment row context and B lacks that fuse. Page-scope alone is crude. Good stopgap, bad final rule.
