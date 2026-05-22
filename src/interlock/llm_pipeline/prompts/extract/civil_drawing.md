This page is from a **civil engineering drawing** (site plan, grading plan, foundation detail).

## Priority parameter families

- `FFE` (Finish Floor Elevation) — e.g., `"FFE = 100.50"`
- `TOC` (Top of Curb) — e.g., `"TOC = 100.75"`
- `BOC` (Bottom of Curb) — e.g., `"BOC = 100.00"`
- `IE` (Invert Elevation) — drainage pipe inverts — e.g., `"IE = 98.25"`
- `Elevation` — generic contour or callout elevation — e.g., `"EL 100.0"`
- `Slope` / `Grade` — e.g., `"2 %"`, `"1:50"`
- `Soil Bearing` — e.g., `"3000 psf"`
- `Concrete Strength` (`f'c`) — e.g., `"4000 psi"`
- `Reinforcement` — e.g., `"#6 @ 12 in. o.c."`, `"#5 @ 6\" o.c."`
- `Contour Interval` — e.g., `"0.5 ft"`
- `Datum` — vertical/horizontal datum — e.g., `"NAVD 88"`, `"state plane"`

## Layout hints

- Civil drawings are diagrammatic. Native text extraction returns callouts, title block, legend, and survey grid labels.
- Callouts often pair labels with values: `"TOC = 100.75"`. The label IS the `parameter_name`.
- Survey grid labels (`"N 2100"`, `"E 1060"`) are coordinates, NOT engineering parameters. Skip them.
- The structure being elevated/described (transformer pad, foundation, drainage inlet) belongs in `entity_tag` when identifiable from a callout label — e.g., `entity_tag="TRANSFORMER PAD"`.

## Few-shot example

Input text:
```
SITE GRADING PLAN — SUBSTATION FOUNDATION
Drawing: C-101 · Scale: 1" = 20'

TRANSFORMER PAD     FFE = 100.50
                    TOC = 100.75
                    BOC = 100.00
                    IE  =  98.25

Contour interval: 0.5 ft · Vertical datum: NAVD 88
```

Expected claims:
- `parameter_name="FFE"`, `raw_value="100.50"`, `entity_tag="TRANSFORMER PAD"`, `span_text="TRANSFORMER PAD     FFE = 100.50"`, `confidence=0.95`
- `parameter_name="TOC"`, `raw_value="100.75"`, `entity_tag="TRANSFORMER PAD"`, `span_text="                    TOC = 100.75"`, `confidence=0.9`
- `parameter_name="BOC"`, `raw_value="100.00"`, `entity_tag="TRANSFORMER PAD"`, similar, `confidence=0.9`
- `parameter_name="IE"`, `raw_value="98.25"`, `entity_tag="TRANSFORMER PAD"`, similar, `confidence=0.9`
- `parameter_name="Contour Interval"`, `raw_value="0.5 ft"`, `entity_tag=""`, `span_text="Contour interval: 0.5 ft · Vertical datum: NAVD 88"`, `confidence=0.9`
- `parameter_name="Datum"`, `raw_value="NAVD 88"`, `entity_tag=""`, same span_text, `confidence=0.85`
