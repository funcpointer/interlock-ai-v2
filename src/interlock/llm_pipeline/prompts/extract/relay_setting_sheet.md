This page is from a **protection relay setting sheet** with concrete pickup / time-dial setting tables.

## Priority parameter families

ANSI device-number elements are the canonical parameter names. Common ones:
- `87T` (transformer differential) — pickup in pu — e.g., `"0.30 pu"`
- `87HS` (high-set differential) — e.g., `"8.0 pu"`
- `50P1`, `50P2` (instantaneous phase OC) — pickup in A
- `51P` (phase time-OC) — pickup in A
- `51P TD` (time dial) — dimensionless — e.g., `"0.55"`
- `51P Curve` — curve type — e.g., `"U2 (IEC VI)"`
- `50N` (instantaneous neutral OC) — pickup in A
- `51N` (neutral time-OC) — pickup in A
- `51N TD`, `51N Curve`
- `27P` (phase undervoltage) — e.g., `"0.85 pu"`
- `59P` (phase overvoltage) — e.g., `"1.15 pu"`
- `81U` (underfrequency) — Hz — e.g., `"59.5 Hz"`
- `81O` (overfrequency) — Hz — e.g., `"60.5 Hz"`

Prose-embedded settings (common in field-application notes — these are the prose-paper case Sprint 2 specifically targets):
- `PCT2` (2nd-harmonic percentage block) — e.g., `"PCT2 = 30 %"` → `parameter_name="PCT2"`, `raw_value="30 %"`
- `PCT5` (5th-harmonic block) — similar shape
- `O87P` (operate threshold) — e.g., `"O87P = 0.30"`
- `SLP1`, `SLP2` (differential slope settings)

## Layout hints

- Setting-group tables have columns: `Element | Function | Setting | Units | Curve`. Each populated row → one claim.
- The relay model identifier (SEL-787, ABB REF-630, GE Multilin 750) is the right `entity_tag` for all settings on this sheet.
- "TRIP1 = 87T + 87HS" style logic equations are NOT individual claims — they're logic, not parameters.
- "Setting Group: 1" is metadata, not a parameter.

## Few-shot example

Input text:
```
Relay: SEL-787 · Tag: T1-DIFF-87 · Setting Group: 1
Element  Function                Setting  Units  Curve
87T      Differential            0.30     pu     —
51P      Phase Time-OC           600      A      U2 (IEC VI)
51P TD   Time Dial               0.55     —      —
```

Expected claims:
- `parameter_name="87T"`, `raw_value="0.30 pu"`, `entity_tag="SEL-787"`, `span_text="87T      Differential            0.30     pu     —"`, `confidence=0.95`
- `parameter_name="51P"`, `raw_value="600 A"`, `entity_tag="SEL-787"`, `span_text="51P      Phase Time-OC           600      A      U2 (IEC VI)"`, `confidence=0.95`
- `parameter_name="51P Curve"`, `raw_value="U2 (IEC VI)"`, `entity_tag="SEL-787"`, same span_text, `confidence=0.9`
- `parameter_name="51P TD"`, `raw_value="0.55"`, `entity_tag="SEL-787"`, `span_text="51P TD   Time Dial               0.55     —      —"`, `confidence=0.95`
