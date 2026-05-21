# InterLock AI — PRD

## Problem

Engineering reviewers at energy-infrastructure owner-operators (AES-class utilities, EPC contractors) lose hours every day diff-reading PDFs to catch cross-document parameter mismatches — the kind that turn into multi-million-dollar field errors when a misplaced decimal on a transformer impedance escapes review. The bottleneck is not reading speed; it is the human ability to hold dozens of cross-references in working memory.

## Reviewer user

A senior electrical engineer or discipline lead at an AES-type owner organization (or an EPC reviewer) accountable for cross-checking an engineering submittal at a 30 / 60 / 90 design-review milestone. Technically sophisticated, time-constrained, working in a high-consequence regulated context. **They do not want grammar correction or formatting fixes.** They want potential monetary-loss-grade discrepancies surfaced with one-click verifiable citations.

The reviewer's daily workflow today: download two PDFs from SharePoint / Bentley / Autodesk Docs, open them side by side, manually scan for inconsistent parameters and assumptions, annotate discrepancies in PDF comments, upload the marked-up versions back. The bottleneck is not the reading speed — it's the cognitive load of holding the cross-references across documents while triaging them for consequence.

## Why this fits the workflow

InterLock is a **pre-review layer** on top of existing document-management systems, not a replacement. Three properties keep adoption friction low:

- **No upload-behavior change.** Engineers continue uploading to their existing DMS; InterLock accepts the same PDFs as input.
- **Findings, not assertions.** Every flag reads "potential mismatch, review" with a confidence score and a citation — never "this is wrong."
- **Human in the loop.** Every flag is dismissible, severity-tagged, and exportable as a JSON audit record. The reviewer retains authority.

A typical session: open InterLock, drop two PDFs, run review, triage the severity-grouped flag list, expand any flag to see the source page bbox snippet side by side, accept or dismiss, export the accepted set. Minutes saved per review: roughly the time the reviewer was spending diff-reading by hand, which is most of the review hour.

## The wedge

**Cross-document, semantics-aware, severity-tiered parameter mismatch detection** for energy-infrastructure documents.

| Property | What it means for the reviewer |
|---|---|
| Cross-document | Flags surface only when two PDFs disagree on the same parameter — never on stylistic or formatting differences |
| Semantics-aware | Engineering shorthand like `%Z`, `Rated Impedance`, and `Per Unit Impedance` are recognised as the same concept before values are compared |
| Severity-tiered | Each candidate is classified critical / major / minor / info against standards-aligned tolerance bands per parameter family; info is hidden by default so the reviewer sees what matters |
| Directional | Every flag declares an authoritative side and a deviation candidate — never a symmetric "A vs B" finding that hands the question back to the reviewer |
| Cited | Every flag carries the document, page, section, exact quoted text, and a bounding-box-highlighted snippet of the source page |
| Reviewer-owned tolerance | Shipped tolerance bands are starting defaults sourced from public standards; reviewers can override per project — InterLock never claims to know the right value for every utility |
| Auditable | Accepted-flag decisions export as a JSON audit record that the reviewer attaches back to the submittal |

Today's MVP demonstrates the wedge end-to-end on two fixture pairs that map to two distinct review scenarios:

1. **Revision diff.** A coordination study at the 60 % milestone, then again at the 90 % milestone with a handful of intentional decimal-error mutations. InterLock surfaces every planted error at critical severity with zero false positives. Mirrors the AES transformer-impedance anecdote.
2. **Cross-document.** An equipment data sheet (the authoritative source for a transformer's nameplate parameters) paired with a coordination study that references the same equipment under different parameter names. InterLock recognises the shorthand and surfaces the value-level mismatches that a textual-diff tool would miss entirely.

The brief calls for two real engineering PDFs ingested with structured extraction and source-cited flagging; the locked fixtures deliver against that bar on both scenarios. Real-spec cross-doc curation is the natural next fixture (the equipment data sheet in scenario 2 is currently synthetic, disclosed in the authorship note).

## Wedge to platform

| Stage | What it adds for the reviewer team | Why the team pays for it |
|---|---|---|
| **Today** | Two-PDF severity-tiered review with citation snippets; optional LLM-judged engineering rationale per flag | Replaces serial human pattern-matching across 60 % / 90 % submittals; catches decimal-error class mistakes before construction |
| **Multi-equipment fixtures** | When a spec describes XFMR-001, XFMR-002, P-101 individually, attributes don't get confused across equipment IDs | Unlocks specs that reference more than one piece of equipment in a single document |
| **Per-project tolerance ontology** | A UI for the reviewer team to load AES-STD-XXX-style internal standards, tighten or relax shipped defaults, and log every override | Tolerance bands are inherently project- and risk-posture-specific; the reviewer team must own the values |
| **Revision lineage** | Rev C supersedes Rev B; supersession-aware authority; parameter-evolution timeline per claim | Real review is rarely two documents — it's the latest revision of every artifact for a given asset |
| **Coupled-effect propagation** | When a transformer impedance changes, the system flags the coordination study and the relay settings as suspect — without re-reading either document | Cross-discipline coupling is the single hardest task a senior reviewer does manually today |
| **Standards as authority** | IEEE / IEC / NERC code-edition tracking; project-vs-code compliance pass | Eliminates the slowest senior-reviewer task: standards cross-reference |
| **Multi-document review sessions + DMS** | Whole-project corpora ingested directly from SharePoint / Bentley / Autodesk Docs; triage queue with ownership and comment threads | InterLock runs in-line with existing engineering operations, not as a side tool |
| **CAD geometry layer** | 2D / 3D drawing comparison integrated with the same parameter graph | One consistency engine across drawings and specs, not two siloed tools |
| **Continuous engineering assurance** | Always-on consistency monitor across the project lifecycle (design → procurement → construction → as-built) | Asset operators pay not for a tool but for traceable assurance across years of project deliverables |

## Why now

AES alone is tripling renewables capacity through 2027, with around 5 GW under construction out of an 11.1 GW PPA backlog. Each MW under construction generates hundreds of cross-referenced engineering documents. EPC contractors produce design basis, calcs, specs, vendor packages, IFC drawings, O&M manuals — all flowing into owner-side review at AES-type organizations. Existing tools cover textual diff (Adobe Acrobat), document management (SharePoint, Bentley ProjectWise), and CAD geometry comparison (bananaz.ai). **None do parameter-level, semantics-aware, directionally-cited discrepancy detection across heterogeneous engineering documents.** That is the open field.

## In-scope for the MVP

- Two real engineering PDFs ingested per review session
- Detection categories: parameter value mismatches, conflicting references between documents, inconsistent assumptions where the parameter names line up, checklist-style presence/absence gaps for named parameters
- Source citation per flag: document, page, section heading, exact quoted text span, bounding-box snippet
- Severity tier per flag, from standards-aligned tolerance bands; info-tier flags suppressed by default
- Directional authority per flag (which document is the source-of-truth side)
- Accept / Dismiss per flag; export accepted flags as a JSON audit record
- Optional LLM-judged engineering rationale per flag, including downstream parameters that may be affected
- Reviewer-controlled per-project tolerance overrides

## Out of scope for the MVP

- Grammar, spelling, formatting, or any stylistic-only flag (would destroy signal-to-noise for the target reviewer)
- More than two documents per review session
- Persistent multi-session review state (each session is standalone)
- DMS integration; CAD or drawing-geometry comparison; multi-tenant / multi-reviewer concurrency
- Internationalisation / non-English text
- Tablet or mobile UI

## Success criteria for the MVP

The MVP is complete when every item below holds, each independently checkable through the deployed app on the locked fixtures.

- **Latency.** A review of two PDFs completes in under 90 seconds wall-clock.
- **Recall.** Every planted decimal-error in the demo fixture surfaces at the highest severity tier.
- **Precision.** No false positive surfaces above the default suppression threshold; unit-equivalent values (for example 150 kVA vs 0.15 MVA) and heading-only rephrases are recognised as non-events.
- **Verifiability.** Every surfaced flag is verifiable by the reviewer in a single click via a bounding-box-highlighted snippet of the source page, with the exact quoted text and page reference shown alongside.
- **Reviewer authority.** Every flag is dismissible; the accepted-flag set exports as a JSON audit record the reviewer attaches to the submittal.
- **Honest tolerance posture.** The default tolerance bands are disclosed as starting points sourced from public standards (IEEE C57, IEC 60076, NEMA TR 1, IEEE Std 242); a per-project override mechanism is exposed for reviewer teams to take ownership.
- **No silent failures.** When a PDF can't be parsed or yields no extractable parameters, the UI explains why (empty doc, prose-heavy paper, scanned pages) rather than presenting an empty result with no diagnosis.
