# InterLock AI — TDD

## Context

The system surfaces directional, cited, severity-tiered parameter mismatches across two engineering PDFs for a reviewer at an AES-class owner-operator. Product framing in `PRD.md`; component diagrams + control/data flow + cache hierarchy in `ARCHITECTURE.md`; risk register in `RISK_REGISTER.md`. This document is the design-decisions companion: what we chose, what we rejected, and why.

## Goals + non-goals

**Goals:** deterministic runtime critical path; reproducible flags; auditable citations; standards-aligned severity; LLM as second-opinion only; reviewer-owned tolerance.

**Non-goals (v1.5):** entity-graph traversal, revision-lineage tracking, multi-document sessions, persistent reviewer state, scanned-PDF OCR at scale, real-time collaboration. All on the roadmap; none in critical path.

## Architecture overview

Five layers (Ingestion, Knowledge extraction, Persistence, Discrepancy + significance, Workflow). Default runtime path is rule-based and deterministic. Two opt-in extensions: an entity-claim layer that adds same-entity filtering for multi-equipment fixtures, and an LLM significance judge that enriches each flag with engineering rationale. Layer breakdown, sequence + data-flow diagrams, and cache hierarchy in `ARCHITECTURE.md`.

---

## 1. Ingestion and extraction architecture

**What we built.** Two-stage native-text pipeline (PyMuPDF spans + Camelot tables) with line-aggregation, plus a vision fallback for low-coverage pages.

| Decision | Rationale | Rejected alternative |
|---|---|---|
| PyMuPDF as primary span extractor | Speed (~10× pdfplumber); native Unicode round-trip for engineering symbols (Ω, μF, Δ, cos φ); bbox per span enables bbox-anchored citations | `pdfplumber` (slower, less precise bbox); `unstructured.io` (SaaS dependency, slower) |
| Camelot lattice first, stream fallback | Lattice handles bordered tables; stream catches whitespace-aligned ones. Together cover what's possible without LLM. | `Tabula` (needs JVM); `Docling` (newer, less validated on engineering PDFs); pure LLM table extraction (non-deterministic) |
| Camelot capped at first 20 pages by default | A 56-page PDF on a cloud runner takes 90–120 s otherwise; reviewer can't tell if it's hung. Override via `pages="all"` or `max_pages=None`. | Scan-all default (stalled the deployed UI on real-world inputs); page-skip heuristic on coordination-curve pages (too brittle) |
| Line-aggregation pass (same-y spans within 2 pt → one logical line) | PyMuPDF yields one span per visual run. Labels like `Rated\nVoltage: 132 kV` split across spans; regex matchers expect logical lines. | Multi-line regex (brittle, layout-dependent); post-hoc cleanup of failed matches (false-negative-prone) |
| Domain regex set yielding `ParameterRecord` | Deterministic, reproducible, cheap. Matches fixture shapes (`1000KVA XFMR`, `5.75%Z`, `Fault X1 20,000A RMS Sym`, generic `Label: value unit`). | LLM extraction with `messages.parse(output_format=Claim)` — drops determinism, adds per-doc cost, surfaces output drift between runs; documented as platform-path |
| Pint with custom `percent = 0.01 = %` alias | Industry-standard unit library; handles Greek prefixes (μ, Ω) via prefix resolution. Custom percent alias because Pint doesn't treat `%` as a unit by default. | Hand-rolled normalization (brittle); SymPy units (heavier dep, weaker engineering coverage) |
| Section-heading attribution per page via nearest-preceding-heading | Sufficient for the locked fixtures; cheap. | LLM-based section parsing (overkill); cross-page heading propagation (no fixture demands it) |

**Tradeoffs accepted.** Camelot detects log-log coordination-curve gridlines on the Eaton fixture as 50×38 "tables." We retain Camelot for future fixtures with native tables (data sheets, equipment schedules); current parameter extraction is span-driven. Prose-heavy PDFs (e.g. SEL field-case papers) yield zero parameters from the regex set — documented limitation; NLP-based extraction is the future option.

## 2. OCR and layout parsing

**What we built.** A coverage router: any page with under 80 characters of native text is flagged in `IngestResult.low_coverage_pages`. An opt-in vision fallback renders such pages at 200 DPI and prompts Claude Sonnet 4.5 for `{text, confidence}` JSON.

| Decision | Rationale | Rejected alternative |
|---|---|---|
| Anthropic vision over Tesseract for OCR | Engineering documents are heavy in domain symbols and small fonts where Tesseract degrades; vision models read those reliably. One LLM dep instead of language-pack management. | Tesseract (Greek/electrical glyph fidelity inconsistent, language-pack ops overhead); GCP / AWS document AI (vendor lock-in, latency) |
| 80-character threshold for low-coverage | Empirically: any genuine engineering page has well over 80 native chars; below that signals scanned-image-only or extracted-text failure. | Image-area heuristic (false positives on charts); page-by-page model invocation always (latency + cost) |
| Vision is opt-in only | Locked fixtures have zero low-coverage pages; mandatory vision adds cost without value. | Always-vision (cost), heuristic-vision-on-every-page (latency) |

**Tradeoffs accepted.** No tesseract integration — a fully offline / no-LLM OCR path is not in scope. A user pointing the system at a fully scanned PDF requires the Anthropic API key.

## 3. Comparison logic

**What we built.** Three composed signals over `ParameterRecord` pairs: exact-name layout-anchored matching, Pint dimensional equivalence on values, Voyage semantic alignment for unmatched A records. A canonical glossary collapses engineering shorthand before embedding. An opt-in Entity + Claim layer adds same-entity filtering when both sides carry equipment tags.

| Decision | Rationale | Rejected alternative |
|---|---|---|
| Three-signal composition over LLM-only comparison | Determinism, reproducibility, audit. Each signal is independently testable; LLM-only conflates failure modes. | Full LLM comparison (non-deterministic, expensive, harder to audit) |
| Layout-anchored greedy 1-to-1 matching for exact pairs | Eaton has nine `5.75%Z` records; naïve name-matching would generate 81 candidate pairs. Greedy nearest-y on the same page reduces this to a deterministic 9. | Cross-product all candidates (combinatorial blow-up); first-match (loses positional alignment) |
| Canonical glossary (`align/semantic.py::_CANONICAL`) in front of Voyage | Voyage `voyage-3` cosine on `%Z` ↔ `Impedance` is 0.44; below our 0.85 threshold. After mapping to canonical phrase `"transformer impedance percent"` the cosine jumps to ≈ 1.0. This is the engineering knowledge that distinguishes us from textual diff. | Lower the embedding threshold (cascades into false matches elsewhere); fine-tune an embedding model (premature, no labeled corpus) |
| `same_page_only=True` default for semantic alignment | Revision-diff fixtures share layout; cross-page matches in that mode are almost always wrong. Cross-doc mode lifts the constraint via UI toggle. | Always cross-page (false positives in revision diff); always same-page (kills cross-doc) |
| `same_dimension` filter on semantic candidates | An over-eager embedder reporting cosine 1.0 on voltage ↔ current must not produce a flag. Pint dimensionality check is the canonical gate. | Trust the embedding model (will produce noise); cosine threshold tuning (lossy) |
| Entity + Claim as additive opt-in (`use_claim_layer=True`) | Phase 14 needed an entity model for multi-equipment fixtures, but a hard refactor would break 159 existing tests. Wrapping `ParameterRecord` in `Claim` preserves the v1.3 path bit-for-bit; same-entity filtering activates only when both sides have explicit tags. | Replace `ParameterRecord` with `Claim` everywhere (regression risk); skip entities (no multi-equipment story) |
| Implicit entities treated as wildcards under `same_entity_only=True` | Revision-diff fixtures have no equipment tags in spans; treating their implicit entities as wildcards keeps the v1.3 path working. Two implicit entities can pair; an explicit ↔ implicit pair is rejected (documented limitation; Phase 14b adds fingerprint-based binding). | Strict same-id only (breaks Option 1); allow all cross-pairings (multi-equipment becomes useless) |

## 4. Citation and confidence

**What we built.** Every `Flag` carries `(doc_id, page, section, bbox, quoted_text, snippet_png)`. Confidence is a three-factor product. Severity is computed separately from per-attribute tolerance bands. The LLM significance judge is an opt-in second opinion.

| Decision | Rationale | Rejected alternative |
|---|---|---|
| Bounding-box-highlighted PNG snippet at 200 DPI | Reviewers verify findings visually; a textual quote alone doesn't show the layout context. 200 DPI balances clarity vs. payload size. | Text quote only (low trust); full page rasterization (oversized) |
| Three-factor multiplicative confidence (`extraction × match × authority`) | Multiplicative ensures any zero factor suppresses the flag entirely; the reviewer sees a single 0–1 score and the suppression threshold is a slider. | Weighted sum (any factor can dominate if poorly weighted); LLM-derived single score (opaque) |
| Severity as a separate axis from confidence | Confidence answers "how sure are we this is a real pair." Severity answers "how engineering-meaningful is this difference." Folding them conflates "high confidence in a minor change" with "low confidence in a major one." | Single combined score (loses the distinction reviewers need to triage) |
| Per-attribute tolerance bands sourced from public standards | Reviewer must be able to argue with the numbers. Each band cites its source (IEEE C57, IEC 60076, NEMA TR 1, IEEE Std 242). Defaults conservative; runtime override hook lets a project tighten or relax. | Hard-coded thresholds with no citation (lose credibility); per-project config from day 1 (premature without product-tested override UX) |
| LLM significance judge as opt-in | Severity comes from rules; LLM rationale is enrichment, not authority. Keeps the audit trail short and the runtime deterministic by default. | LLM-in-critical-path for severity classification (non-deterministic, opaque, audit-hostile) |
| Authority hardcoded per fixture pair | MVP fixtures have a clear authority story (60 % baseline beats 90 % revision; spec beats study). Configurable authority needs a UX (Phase 15). | Configurable from day 1 (premature) |

## 5. Evaluation design

**What we built.** Two locked gold sets (one per fixture pair) with documented mutations driving expected outcomes. A harness runs the full pipeline against each set and writes per-id results. Pytest gates enforce thresholds.

| Decision | Rationale | Rejected alternative |
|---|---|---|
| Gold set derived directly from the mutation log | Single source of truth: the mutation script writes the ground truth; the gold YAML references the same IDs. Drift is impossible. | Hand-curated gold (drift, double-bookkeeping) |
| Hard recall + FP gates (recall = 1.0 on TPs, FP rate = 0.0 on traps) | Six labeled cases is too small a sample for meaningful precision/recall curves. Binary pass/fail is honest about the sample size. | Precision / recall / F1 thresholds (statistically misleading at n = 6) |
| One gold set per fixture pair (Option 1 + Option 2) | The two pairs exercise different code paths — exact alignment vs semantic + glossary. Separate gold sets keep failures localized. | Single combined gold (failures hard to attribute) |
| Acceptance thresholds in pytest, not just docs | A doc threshold drifts; a CI gate doesn't. Any regression that surfaces an FP trap or drops a TP fails CI immediately. | Documentation-only thresholds (drift) |
| A/B comparison harness writes per-pair metrics | Demonstrates that Option 2 surfaces flags via semantic alignment that Option 1 has zero exact-name matches for — the cross-document wedge claim is independently verifiable. | Implicit claim in PRD (unverifiable) |

**Known evaluation limitations.** FN-1 (parameter-removal detection) is documented as a system limitation; explicit-removal detection requires the Phase 17 coupled-effect graph traversal. SEL prose-heavy paper yields zero extractable parameters and is pinned as a known limit by `tests/real_world/test_real_pdf_extraction.py::test_sel_paper_known_prose_extraction_limit`.

---

## Failure modes + mitigations

| Failure mode | Detection | Mitigation |
|---|---|---|
| Anthropic rate-limit / 5xx | SDK exception | SDK auto-retry with exponential backoff |
| Voyage rate-limit / non-determinism | Cosine drift across runs | Per-text vector caching; tests assert flag-parameter *set* stability, not absolute confidence |
| Cache silent invalidator (LLM judge) | `cache_read_input_tokens == 0` on the second call with identical prefix | Canary pytest with a large cacheable prefix |
| Camelot stalls on long PDFs | Wall-clock over budget | Default 20-page cap; override per call |
| Streamlit Cloud cold start | First request > 30 s | Pre-warm tab before demo; explicit cold-start note in README |
| PDF parse failure | Exception in `ingest` | Surface to UI with per-doc diagnostic counts (spans / tables / extractable params / low-coverage pages) explaining why no flags surfaced |
| Empty result on otherwise valid PDFs | Surfaced via the diagnostic-counts panel | Concrete branches for both-zero, one-zero, both-nonzero-no-pairs, each with a named likely cause |

## Known limits (Phase 19 honesty disclosure)

The current alignment is correct and conservative for the documents we tested against (Eaton fuse coordination study + mutated revision + OCR derivative). The architecture generalises; several specific heuristics do not. Reviewers and future engineers deserve to know exactly where.

**Architecture pieces that generalise across domains:**
- `ParameterRecord.entity_tag` as a first-class identity field
- Ambiguity gates (count mismatch, OCR y-degeneracy) — structural, not domain-specific
- `pairing_confidence` per pairing rule and the `⚠️ weak pair` UI badge
- Unpaired-records surface — right answer regardless of pipeline

**Heuristics that are overfit to fuse-coordination-style documents:**

| Component | What it handles well | Where it breaks |
|---|---|---|
| `_LEADING_DEVICE_ID` regex | Circled digits ①-㉟, "21.", "A1", "T-200" | Misses `XFMR-001` (prefix too long), `P-101A`, `T200` (no hyphen), bullets / brackets `(1)` / `[1]`, Roman numerals, IDs not in column 1 |
| `_string_family` regex | Bussmann part numbers (KRP-C, LPS-RK, LPN-RK) | `#6 AWG` (no alpha prefix), `XHHW-2` (over-broad family), `T-1000-A` (collapses to "T") |
| OCR v3 prompt's Device-ID directive | Numbered/circled-digit table rows | Schedules where IDs sit in rightmost column or below the value; sidebar callouts; equipment named in prose |
| Asymmetric "tagged never pairs with untagged" rule | Both docs cleanly tagged, or both cleanly untagged | One side tagged + other side OCR-stripped → everything goes to unpaired, no flags surface |
| `pairing_confidence` values (1.0 / 0.9 / 0.75 / 0.5) | Order is defensible; coarse score for UI gating | Spacing is opinion, not calibrated against ground truth |

**Untested document classes** (no fixtures, no gold flags):
- HVAC equipment schedules (`AHU-1`, `FCU-5`)
- Process P&ID with instrument tags (`PV-1`, `FT-1`, `LIC-100`)
- Pipe / cable schedules
- Spec sheets / BOMs with right-aligned ID columns
- Documents containing no Device IDs at all — current behaviour falls back to positional/family heuristics, which were the very rules Phase 19 was trying to back off of. We don't know how many real engineering docs that describes.

**Generalisation plan** (post-MVP, ranked by leverage):
1. Pluggable entity-tag detector — register multiple regex banks per doc class, keyed off ingest-time classification
2. Camelot-row binding — every parameter in row R of a Camelot-extracted table inherits row-R identity, even without a leading marker
3. Diverse fixture suite — HVAC schedule, P&ID, BOM-style spec; gold flags on each
4. Calibration of `pairing_confidence` magnitudes against labelled ground truth

## Open questions + future work

- **Entity fingerprinting** (Phase 14b): binding an implicit equipment in one doc to a tagged equipment on the other via attribute fingerprint. Required for cross-doc multi-equipment demos.
- **Per-project tolerance ontology UI** (Phase 15): the override hook ships; the UI for reviewer teams to own per-project bands does not.
- **Revision lineage** (Phase 16): the claim graph schema supports it; supersession-aware authority needs the UI + ingestion-side metadata.
- **Coupled-effect propagation** (Phase 17): the deferred-flag pattern when claim X changes and dependent claims become suspect.
- **Prose extraction** (open): SEL-style prose-heavy papers are a documented zero-yield case for the regex extractor. NLP / LLM-assisted extraction is the platform option.

Further detail and full roadmap in `BACKLOG.md`. Risk register and abort-gate outcomes in `RISK_REGISTER.md`.
