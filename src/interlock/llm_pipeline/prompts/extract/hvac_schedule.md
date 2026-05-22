This page is from an **HVAC equipment schedule**.

## Priority parameter families

- `CFM` (cubic feet per minute, airflow) — e.g., `"5000 CFM"`, `"5000"`
- `GPM` (gallons per minute, water flow) — e.g., `"120 GPM"`
- `Tonnage` (cooling capacity, refrigeration tons) — e.g., `"12.5 tons"`
- `kW` (electrical power) — e.g., `"50 kW"`
- `EWT/LWT` (entering/leaving water temp) — e.g., `"55/45 °F"`, `"140/180 °F"`
- `Pressure` (static head, psig, ft H₂O) — e.g., `"100 ft"`, `"60 psig"`
- `COP/EER` (coefficient of performance / energy efficiency) — e.g., `"0.55 kW/ton"`, `"3.5 COP"`
- `Capacity` (boiler MBH, etc.) — e.g., `"2000 MBH"`
- `ASHRAE Compliance` — e.g., `"90.1-2019"`, `"62.1-2019"`

## Layout hints

- HVAC schedules are dense tabular layouts. Header row defines column meaning; subsequent rows are equipment instances.
- Equipment ID in the leftmost column (`AHU-1`, `FCU-3`, `RTU-2`, `EF-1`, `CHWP-1`, `CT-1`, `B-1`) IS the `entity_tag`. ALWAYS populate it for schedule rows.
- Each row produces multiple claims — one per non-empty column value. Tag prefix conventions: `AHU` air handler, `FCU` fan coil, `RTU` rooftop unit, `EF` exhaust fan, `CHWP` chilled-water pump, `HWP` hot-water pump, `CT` cooling tower, `B` boiler, `CHWR` reheat.
- Skip dashes (`—`) — they mean "not applicable" for that column.

## Few-shot example

Input text:
```
Tag    Type                  Location    CFM   Tonnage  GPM  ASHRAE Ref
AHU-1  Air Handling Unit     Roof Top    5000  12.5     —    90.1-2019
FCU-3  Fan Coil Unit         Conf Room A 800   2.5      5.0  62.1-2019
B-1    Condensing Boiler     Mech 1      —     —        200  —
```

Expected claims (AHU-1 row):
- `parameter_name="CFM"`, `raw_value="5000 CFM"`, `entity_tag="AHU-1"`, `span_text="AHU-1  Air Handling Unit     Roof Top    5000  12.5     —    90.1-2019"`, `confidence=0.9`
- `parameter_name="Tonnage"`, `raw_value="12.5 tons"`, `entity_tag="AHU-1"`, same span_text, `confidence=0.9`
- `parameter_name="ASHRAE Compliance"`, `raw_value="90.1-2019"`, `entity_tag="AHU-1"`, same span_text, `confidence=0.85`
