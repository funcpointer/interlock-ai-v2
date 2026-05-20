# InterLock AI — PRD

## 1. Reviewer user

A senior electrical engineer or discipline lead at an AES-type owner organization (or an EPC reviewer) accountable for cross-checking an engineering submittal at a 30/60/90 design-review milestone. Technically sophisticated, time-constrained, regulated context. Currently downloads PDFs from SharePoint, opens them side by side, manually checks for inconsistent parameters, annotates discrepancies in PDF comments, uploads back. The bottleneck is **their** time — they are the only ones who can judge whether a cross-document mismatch is real, but most of their review hour is spent **finding** mismatches, not adjudicating them.

InterLock targets the finding step. Adjudication stays human.

## 2. Why this fits the existing workflow

InterLock is a **pre-review layer** on top of SharePoint/DMS, not a replacement. Three workflow facts that keep adoption low-friction:

- **No behavior change in upload.** Engineers continue uploading to SharePoint. InterLock pulls (or accepts uploads of) the same files.
- **Pre-marked PDFs are respected.** Annotated and highlighted PDFs round-trip without losing the annotation layer.
- **Flagging is suggestive, not assertive.** Every finding reads "potential mismatch, review" — never "this is wrong." Confidence-scored, dismissible, exportable. Engineers retain authority.

A typical reviewer session: open InterLock, drop two PDFs, run review (~30–90 s), triage flag list (typical case: ≤ 10 high-confidence candidates), click through to bbox-highlighted source for any flag of interest, accept or dismiss, export the accepted-flag JSON for audit. Total minutes saved per review: roughly the time the reviewer was spending diff-reading by hand.

## 3. The wedge

**Cross-document parameter discrepancy detection with directional citations for energy infrastructure documents.**

- **Cross-document:** flags surface only when two documents disagree on the same parameter (not stylistic, not formatting).
- **Directional:** every flag declares which document is authoritative for that parameter family and which is deviating. Symmetric "conflict between A and B" findings are explicitly forbidden — they push the cognitive load back to the reviewer.
- **Cited:** every flag carries a tuple of (document, page, section, exact quoted text, bbox). The reviewer can verify in one click.
- **Consequential errors only:** the bar is "would a senior engineer care during a design review?" Grammar, formatting, headings-only changes are suppressed by construction.

The canonical MVP scenario is the 60% → 90% phase-revision review: a coordination study revised between milestones, where the reviewer needs to know what changed and whether the changes are justified. The system surfaces value-level deviations with confidence, anchored to source text. The MVP fixture (Eaton sample coordination study + 6 documented mutations) shows TP-1 (decimal-shifted transformer impedance), TP-2 (decimal-shifted fault current), and TP-3 (decimal-shifted transformer rating) being flagged at confidence 1.0, while the FP-1 unit-equivalent trap (150 kVA vs 0.15 MVA) is correctly suppressed by Pint unit normalization.

## 4. Wedge-to-platform path

The reframing: InterLock is not a "document QA tool" or a "PDF chatbot." It is the seed of an **engineering consistency operating system** — a layer that externalizes and scales the cross-document memory that senior reviewers carry in their heads today. The product evolves through five architectural layers; the MVP lives in layers 1, 2, 4 (partial), and 5 (basic). Layers 3 and the expansion of 4 are the platform.

### The five-layer architecture

| # | Layer | What it does | MVP state |
|---|---|---|---|
| 1 | **Ingestion** | PDFs (scanned, native, annotated), CAD, sheets, contracts, revisions, markups → text + tables + bboxes + metadata | ✅ PDFs (PyMuPDF + Camelot + vision fallback). CAD/sheets/contracts: platform. |
| 2 | **Knowledge extraction** | Convert documents into typed claims with engineering ontology, entity resolution, unit normalization | ⚠️ Parameter records with unit normalization + small canonical glossary. **Entity model and ontology expansion are platform.** |
| 3 | **Project knowledge graph** | Entities (equipment, lines, systems, requirements) + claims about entities + relationships (depends_on, supersedes, derived_from, governed_by, conflicts_with) | ❌ Not in MVP. **This is the heart of the platform.** |
| 4 | **Discrepancy + risk engine** | Detect conflicts, score material significance, propagate coupled effects (impedance change → fault current → protection coordination invalid), severity tiers | ⚠️ Value-mismatch detection with directional authority and confidence scoring. Material-significance bands, coupled-effect propagation, and cross-claim reasoning are platform. |
| 5 | **Review workflow** | Triage queue, assignment, severity tiers, comment threads, audit trail, status lifecycle, revision-aware comparison | ⚠️ Single-session Accept/Dismiss with JSON export. Triage/ownership/threading: platform. |

### Wedge-to-platform concrete progression

| Phase | What ships | Why review teams pay for it |
|---|---|---|
| **Today (MVP)** | Cross-document parameter mismatch detection with directional citations on energy-infrastructure PDFs | Replaces serial human pattern-matching across 60% / 90% submittals; catches AES-anecdote-class decimal errors before construction |
| **Phase 13 — Entity + Claim graph** | Refactor `ParameterRecord` into `Entity` + `Claim(entity, attribute, value, source)`; pair on (entity, attribute) instead of parameter name | Multi-equipment scenes ("Pump P-101 flowrate" vs "Pump P-102 flowrate"); precondition for everything below |
| **Phase 14 — Material significance + tolerance bands** | Per-attribute engineering tolerances (transformer impedance ±5% is normal; 10% requires explanation); risk-scored flags | Drops noise rate further; reviewers see *what matters* not *what differs* |
| **Phase 15 — Revision lineage** | First-class lineage (Rev C supersedes Rev B); supersession-aware authority; parameter-evolution timelines | Real review is rarely 2-doc; it's "the latest revision of every artifact for this asset" |
| **Phase 16 — Coupled-effect propagation** | Graph traversal: when claim X changes, what derived claims become suspect? | "If transformer impedance changes, recheck the coordination study and the relay settings — both downstream" |
| **Phase 17 — Standards-as-authority** | IEEE / IEC / NERC code-edition tracking; project-vs-code compliance pass | Eliminates the slowest senior-reviewer task: standards cross-reference |
| **Phase 18 — Multi-doc review sessions + DMS** | Whole-project corpora; SharePoint/Bentley/Autodesk Docs ingest; triage queue with ownership | InterLock runs in-line with existing engineering operations, not as a side tool |
| **Phase 19 — CAD geometry layer** | 2D/3D drawing comparison (bananaz.ai-class) integrated with the same claim graph | One consistency engine across drawings + specs, not two siloed tools |
| **Phase 20 — Continuous engineering assurance** | Always-on consistency monitor across project lifecycle (design → procurement → construction → as-built) | Asset operators pay not for a tool but for traceable assurance across years of project deliverables |

### Why this framing is honest

Most "AI for engineering" products attack drafting, generation, or copilots. Those markets commoditize on model quality. **Review is structurally different**: higher ROI, less regulated, easier to insert without behavior change, and closer to measurable cost savings. The defensibility is not the model — it is the **project knowledge graph**: accumulated entity mappings, discrepancy patterns, review decisions, engineering heuristics, revision histories. That graph compounds with every reviewer interaction. The MVP is the first edge of that graph.

## 5. Why now

AES alone has 5 GW under construction out of an 11.1 GW PPA backlog, tripling renewables capacity through 2027, and a full coal exit by end of 2025. Each MW in construction generates hundreds of cross-referenced engineering documents. EPC contractors produce design basis, calcs, specs, vendor packages, IFC drawing sets, O&M manuals — all flowing to owner-side reviewers at AES-like organizations. A misplaced decimal in a transformer spec almost cost a multi-million-dollar loss in the example the AES engineer shared with us. Industry-documented patterns confirm: cross-discipline coordination failures, decimal errors in load calcs, and missing/superseded standards references are the leading sources of costly design-review misses. The market has plenty of CAD comparison tools (bananaz.ai), plenty of textual diff tools (Adobe Acrobat), and plenty of DMS (SharePoint, Bentley). None do parameter-level, semantics-aware, directionally-cited discrepancy detection across heterogeneous engineering documents. **That is the open field.**
