This page is from a **manufacturer equipment data sheet / nameplate spec**.

## Priority parameter families

- `Rated Power` — kVA / MVA / HP / kW — e.g., `"1100 kVA"`, `"75 kW"`, `"100 HP"`
- `Primary Voltage` — e.g., `"12.47 kV"`, `"13.8 kV"`
- `Secondary Voltage` — e.g., `"480 V"`, `"480Y/277V"`
- `Rated Current` — e.g., `"120 A"`
- `Rated Impedance` — percent — e.g., `"4.5 %"`, `"5.75 %"`
- `BIL` (basic insulation level) — kV — e.g., `"95 kV"`
- `Frequency` — Hz — e.g., `"60 Hz"`
- `Insulation Class` — letter or temperature — e.g., `"F"`, `"55 °C"`
- `Temperature Rise` — °C — e.g., `"80 °C"`
- `Enclosure` — e.g., `"TEFC IP55"`, `"NEMA 4X"`
- `Service Factor` — e.g., `"1.15"`
- `Frame Size` — e.g., `"NEMA 405T"`
- `Efficiency` — percent at named load — e.g., `"95.8 %"` (at 75% load)
- `Power Factor` — e.g., `"0.88"`

## Layout hints

- Nameplate tables are typically `Parameter | Value` two-column lists. Each row → one claim.
- The manufacturer + model + serial appears in the header. Use the model number as `entity_tag` when extracting parameters that bind to a specific unit (e.g., `entity_tag="VCP-W-1600"`, `entity_tag="M3BP 280SMB 4"`).
- Standards-compliance footers ("Per IEEE C57.12.00-2015") are NOT claims — they're document metadata.

## Few-shot example

Input text:
```
MOTOR EQUIPMENT DATA SHEET
Manufacturer: ABB · Model: M3BP 280SMB 4 · Serial: AB1234567
Parameter           Value
Rated Power         75 kW (100 HP)
Rated Voltage       460 V
Rated Current       120 A
Frequency           60 Hz
Insulation Class    F
```

Expected claims:
- `parameter_name="Rated Power"`, `raw_value="75 kW"`, `entity_tag="M3BP 280SMB 4"`, `span_text="Rated Power         75 kW (100 HP)"`, `confidence=0.95`
- `parameter_name="Rated Voltage"`, `raw_value="460 V"`, `entity_tag="M3BP 280SMB 4"`, `span_text="Rated Voltage       460 V"`, `confidence=0.95`
- `parameter_name="Rated Current"`, `raw_value="120 A"`, `entity_tag="M3BP 280SMB 4"`, `span_text="Rated Current       120 A"`, `confidence=0.95`
- `parameter_name="Frequency"`, `raw_value="60 Hz"`, `entity_tag="M3BP 280SMB 4"`, `span_text="Frequency           60 Hz"`, `confidence=0.95`
- `parameter_name="Insulation Class"`, `raw_value="F"`, `entity_tag="M3BP 280SMB 4"`, `span_text="Insulation Class    F"`, `confidence=0.9`
