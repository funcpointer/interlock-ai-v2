This page is from a **P&ID (Piping & Instrumentation Diagram)**.

## Priority parameter families

- Instrument tag + setpoint pairs (ISA-5.1 notation):
  - `PT-<n>` (pressure transmitter) + setpoint — e.g., `"PT-100 setpoint 50 psig"`
  - `FT-<n>` (flow transmitter) + setpoint
  - `TIC-<n>` (temperature indicating controller)
  - `LIC-<n>` (level indicating controller)
  - `PIC-<n>` (pressure indicating controller)
  - `FIC-<n>` (flow indicating controller)
  - `PSV-<n>` (pressure safety valve)
  - `MOV-<n>` (motor-operated valve)
- `Line tag` — pipe identifier — e.g., `"4\"-FS-101-CS"` (size-service-line#-material)
- `Setpoint` / `Trip Setpoint` — numeric setpoint values
- `Material` (line material code) — `CS` (carbon steel), `SS` (stainless), etc.

## Layout hints

- P&IDs are diagrammatic. Native text extraction from a P&ID PDF often returns sparse text (instrument tag bubbles + line labels + legend text). Extract what's there; don't try to interpret pipe topology.
- ISA tag IDs ARE the `entity_tag` — for `"PT-100 setpoint 50 psig"`, claim is `parameter_name="Setpoint"`, `raw_value="50 psig"`, `entity_tag="PT-100"`.
- Legend entries that DEFINE instrument types (e.g., `"PT = Pressure Transmitter"`) are NOT claims — they're glossary.

## Few-shot example

Input text:
```
P-001 Rev A — Reactor Feed System

PT-100  Pressure Transmitter  Setpoint: 75 psig  Trip: 100 psig
FT-101  Flow Transmitter      Setpoint: 250 GPM
TIC-200 Temperature Controller Setpoint: 180 °F
LIC-200 Level Controller       Setpoint: 60 %
```

Expected claims:
- `parameter_name="Setpoint"`, `raw_value="75 psig"`, `entity_tag="PT-100"`, `span_text="PT-100  Pressure Transmitter  Setpoint: 75 psig  Trip: 100 psig"`, `confidence=0.95`
- `parameter_name="Trip Setpoint"`, `raw_value="100 psig"`, `entity_tag="PT-100"`, same span_text, `confidence=0.9`
- `parameter_name="Setpoint"`, `raw_value="250 GPM"`, `entity_tag="FT-101"`, `span_text="FT-101  Flow Transmitter      Setpoint: 250 GPM"`, `confidence=0.95`
- `parameter_name="Setpoint"`, `raw_value="180 °F"`, `entity_tag="TIC-200"`, `span_text="TIC-200 Temperature Controller Setpoint: 180 °F"`, `confidence=0.95`
- `parameter_name="Setpoint"`, `raw_value="60 %"`, `entity_tag="LIC-200"`, `span_text="LIC-200 Level Controller       Setpoint: 60 %"`, `confidence=0.95`
