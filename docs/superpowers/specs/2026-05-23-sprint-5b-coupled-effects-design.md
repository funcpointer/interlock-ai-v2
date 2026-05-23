# Sprint 5b — Coupled-Effect Graph Traversal Design Spec

**Goal.** When a flag surfaces, also surface the dependent parameter families that should be re-verified — and (when the SQLite claim store is populated) the actual matching claims from other documents. No new LLM call.

**Exit tag:** `v2.6-graph`. **PIVOT_PLAN reference:** Sprint 5 — coupled-effect graph portion.

---

## §1 Approach + Components

Two layers, both deterministic, both surfaced together in the UI:

1. **Static coupled-family map** (`COUPLED_FAMILIES`): canonical parameter-family dependency graph. Hardcoded ~10 entries: `impedance_pct → [fault_current_a, relay_pickup_a, coordination_margin_pct]`, etc. Source of truth: same engineering knowledge encoded in the LLM judge's `_ONTOLOGY_BLOCK`.

2. **Judge's `downstream_effects` list** (already exists since Phase 13 / Sprint 1). Each LLM judgment returns a free-text list of affected parameters. This is the per-flag dynamic graph.

3. **Phase 14 SQLite store query** (`coupled_claims_for(flag, families)`): looks up claims in the persisted `claim` table matching the dependent families. Empty result is the default (store not populated unless `persist_claims=True`).

**Surface.** Each flag's expander adds a "🕸️ Coupled effects" section listing:
- Family names from the union of static map + judge's downstream_effects (deduped).
- For each family, matching claims from the SQLite store (when present). Shows entity_tag + value + doc_id + page.

**Trigger.** Always-on when `use_llm_judge=True` (default per Sprint 4.5). Empty union → section silent.

**No new LLM call. No new cost.**

**New files:**
- `src/interlock/detect/coupled.py` — `COUPLED_FAMILIES` static map + `coupled_families_for(family) → list[str]` + `coupled_claims_for(family) → list[Claim]` (querying Phase 14 store).
- `tests/detect/test_coupled.py` — unit tests for both.

**Modified:**
- `src/interlock/ui/app.py` — "🕸️ Coupled effects" section in each flag expander.
- `docs/AUTHORSHIP.md` + `docs/TDD.md`.

---

## §2 Coupled-family static map

```python
# src/interlock/detect/coupled.py
COUPLED_FAMILIES: dict[str, list[str]] = {
    "impedance_pct": [
        "fault_current_a", "fault_current_ka",
        "relay_pickup_a", "coordination_margin_pct",
        "voltage_regulation_pct",
    ],
    "transformer_rating_va": [
        "cable_ampacity_a", "breaker_interrupting_ka",
        "ct_ratio", "transformer_loading_pct",
    ],
    "voltage_v": [
        "bil_kv", "surge_arrester_rating_kv",
        "clearance_mm", "conductor_amp",
    ],
    "voltage_kv": [
        "bil_kv", "surge_arrester_rating_kv",
        "clearance_mm", "conductor_amp",
    ],
    "fault_current_a": [
        "relay_pickup_a", "breaker_interrupting_ka",
        "ground_grid_size_m2", "arc_flash_cal_cm2",
    ],
    "fault_current_ka": [
        "relay_pickup_a", "breaker_interrupting_ka",
        "ground_grid_size_m2", "arc_flash_cal_cm2",
    ],
    "motor_fla_a": [
        "cable_ampacity_a", "overload_pickup_a",
        "starting_current_a",
    ],
    "relay_pickup_a": [
        "coordination_margin_pct", "trip_curve_time_s",
    ],
    "fuse_amps": [
        "coordination_margin_pct", "trip_curve_time_s",
        "breaker_interrupting_ka",
    ],
    "breaker_interrupting_ka": [
        "fault_current_ka", "arc_flash_cal_cm2",
    ],
}


def coupled_families_for(family: str | None) -> list[str]:
    """Return the dependent parameter families for a given primary family.

    Empty list when family is None / unknown / not in the static map.
    """
    if not family:
        return []
    return list(COUPLED_FAMILIES.get(family, []))


def coupled_claims_for(family: str | None) -> list[Claim]:
    """Return persisted Phase-14 claims whose attribute matches any of the
    dependent families. Empty list when the store has no matching claims
    (default state when persist_claims=False)."""
    families = coupled_families_for(family)
    if not families:
        return []
    out: list[Claim] = []
    for fam in families:
        out.extend(claims_for_attribute(fam))
    return out
```

---

## §3 Schema (no new fields)

`Flag` does NOT gain a new field. Coupled effects are computed at render time from `flag.attribute_family` + `flag.severity_judgment_downstream_effects` (already available via judge integration) + on-demand SQLite query.

This keeps Flag frozen-dataclass minimal and avoids storage of derived data.

**JSON export gains `coupled_effects`** — a list of family names — computed at Accept time so the audit trail captures what was surfaced.

---

## §4 UI Surface

### Per-flag expander — "🕸️ Coupled effects" section

Below the cited-clauses block (Sprint 5a), before the citation columns:

```python
# v2 Sprint 5b: coupled effects (static map ∪ judge downstream_effects)
from interlock.detect.coupled import coupled_families_for

_judge_effects: list[str] = []
# downstream_effects lives on the original SignificanceJudgment when use_llm_judge
# ran; we don't store it on Flag, so for now compute static map only here.
_static = coupled_families_for(getattr(f, "attribute_family", None))
_all_effects = sorted(set(_static))

if _all_effects:
    st.markdown("**🕸️ Coupled effects — also verify:**")
    for fam in _all_effects:
        # If Phase 14 SQLite store has persisted claims, surface them too.
        try:
            from interlock.detect.coupled import coupled_claims_for
            matching = [
                c for c in coupled_claims_for(getattr(f, "attribute_family", None))
                if c.attribute == fam
            ]
        except Exception:
            matching = []
        if matching:
            entries = ", ".join(
                f"`{c.entity.id}:{c.raw_value}` (doc {c.source_record.doc_id} p{c.source_record.page})"
                for c in matching[:3]
            )
            st.markdown(f"- `{fam}` — {len(matching)} record(s): {entries}")
        else:
            st.markdown(f"- `{fam}` — _no persisted claim found in store_")
```

### Header chip

NO new chip. Coupled effects is a per-flag explainer, not a status badge — adding a chip would clutter the header.

### JSON export gains key

```python
"coupled_effects": coupled_families_for(getattr(f, "attribute_family", None)),
```

---

## §5 TDD Phases (4 phases)

### Phase 30.1 — Static map + lookup function

- Tests `tests/detect/test_coupled.py` (~6):
  - `coupled_families_for("impedance_pct")` returns expected list
  - `coupled_families_for("unknown_family")` returns []
  - `coupled_families_for(None)` returns []
  - `COUPLED_FAMILIES` covers all primary families surfaced in seed clauses.yaml
  - Returned list is a copy (caller mutations don't affect the map)
  - Symmetric coverage: `relay_pickup_a` listed as dependent of `impedance_pct` should itself have entries in the map (transitive sanity)
- Implement: `src/interlock/detect/coupled.py` with `COUPLED_FAMILIES` + `coupled_families_for()`.
- **Tag:** `phase-30.1-coupled-map`.

### Phase 30.2 — Phase-14 store query (`coupled_claims_for`)

- Tests (~4):
  - With empty store → returns []
  - With persisted claim matching a dependent family → returns it
  - Multiple matches across families → all returned
  - No flag family (None) → returns []
- Implement: `coupled_claims_for()` in `src/interlock/detect/coupled.py` using `interlock.store.sqlite.claims_for_attribute`.
- **Tag:** `phase-30.2-coupled-claims`.

### Phase 30.3 — UI surface + JSON export

- Sidebar: NO new toggle (always on with judge).
- Flag expander: new "🕸️ Coupled effects" markdown block (silent when family unknown).
- JSON export: append `coupled_effects` list per accepted flag.
- Manual smoke + compile + lint + mypy.
- **Tag:** `phase-30.3-coupled-ui`.

### Phase 30.4 — Docs + sprint exit

- AUTHORSHIP per-phase entry.
- TDD known-limits entry.
- **Exit tag:** `v2.6-graph`.

---

## §6 Cost + Latency

| | Cold | Warm |
|---|---:|---:|
| Static map lookup | <1 μs | <1 μs |
| SQLite query per family | <5 ms | <1 ms |
| Per-flag overhead | <20 ms (3 family lookups) | <5 ms |
| LLM cost added | **$0** | **$0** |

Pure-Python + SQLite; no API calls. Performance noise.

---

## §7 Risks + Mitigations

| Risk | Mitigation |
|---|---|
| Static map gets stale as new parameter families surface | Map is hand-curated, same as clause registry. Updated by same content-curation discipline. |
| Reviewer interprets "coupled effects" as automatic suggestions | UI copy says "**also verify**" — explicit reviewer-driven verification, not auto-action. |
| SQLite store empty by default (persist_claims=False) | UI shows "_no persisted claim found in store_" — honest about gap. Reviewer can enable persist_claims for cross-doc graph queries. |
| Map asymmetric (A→B but not B→A) when real dependency is symmetric | Acknowledged: this is a directed-edges design choice. Symmetric pairs added explicitly (e.g., `fault_current_a ↔ relay_pickup_a` both directions). |
| Adds clutter to flag expander when coupled list is long | Truncate to top 5 families; show "+N more" suffix if list longer. (Phase 30.3 polish.) |

---

## Self-review notes

- All 7 sections trace to user-approved choices during brainstorming (skipped per "just continue building" instruction; design follows PIVOT_PLAN Sprint 5 graph requirements + lessons from Sprint 5a's pragmatic-curation approach).
- No "TBD" / "TODO" strings.
- Identifier consistency: `COUPLED_FAMILIES`, `coupled_families_for`, `coupled_claims_for` used uniformly.
- Phase tags follow `phase-30.<N>-<slug>`.
- Final tag `v2.6-graph`.
- No back-compat regression risk: all changes additive.
