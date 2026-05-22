This page is from a **protection coordination study**.

## Priority parameter families on this class

- `%Z` (transformer impedance, percent) — e.g., `"5.75 %Z"`, `"5.75%Z"`
- `Transformer Rating` — apparent power in kVA / MVA — e.g., `"1000 KVA XFMR"`, `"0.15 MVA"`
- `Fault Current` — short-circuit duty — e.g., `"Fault X1 20,000A RMS Sym"`
- `Fuse Designation` — part number — e.g., `"LPN-RK-500SP"`, `"KRP-C-1600SP"`, `"LPS-RK-200SP"`
- `Pickup` — relay/breaker pickup value — e.g., `"Pickup: 600 A"`
- `Time Dial` — relay time-dial setting — e.g., `"TD = 0.55"`
- `System Voltage` — primary/secondary voltage — e.g., `"13.8 kV"`, `"480Y/277V"`
- `IFLA` — full-load amps — e.g., `"IFLA = 12A"`
- `Conductor Designation` — wire size + insulation — e.g., `"#6 THWN-2 Cu"`

## Layout hints

- Eaton/Bussmann coordination samples often have a numbered device legend (e.g., `"① 1000KVA XFMR Inrush Point | 12 x FLA @ .1 Seconds"`). The number in front is the row's Device ID → use it as `entity_tag`.
- TCC plot images on these pages carry numeric pickup callouts (`"100 A"`, `"0.5 sec"`) that the page's *text layer* does NOT capture. Extract only what's in the text — never invent values from imagined plot positions.
- Tabular device legends often have columns: `Device | Description | Comments`. Each row is a separate claim.

## Few-shot examples

Input text:
```
① 1000KVA XFMR Inrush Point | 12 x FLA @ .1 Seconds
② 1000KVA XFMR Damage Curves | 5.75%Z, liquid filled (Footnote 1)
③ JCN 80E | E-Rated Fuse
④ #6 Conductor Damage Curve | Copper, XLP Insulation
```

Expected claims:
- `parameter_name="Transformer Rating"`, `raw_value="1000 kVA"`, `entity_tag="1"`, `span_text="① 1000KVA XFMR Inrush Point | 12 x FLA @ .1 Seconds"`, `confidence=0.95`
- `parameter_name="%Z"`, `raw_value="5.75 %"`, `entity_tag="2"`, `span_text="② 1000KVA XFMR Damage Curves | 5.75%Z, liquid filled (Footnote 1)"`, `confidence=0.95`
- `parameter_name="Fuse Designation"`, `raw_value="JCN 80E"`, `entity_tag="3"`, `span_text="③ JCN 80E | E-Rated Fuse"`, `confidence=0.9`
- `parameter_name="Conductor Designation"`, `raw_value="#6 THWN-2 Cu"`, `entity_tag="4"`, `span_text="④ #6 Conductor Damage Curve | Copper, XLP Insulation"`, `confidence=0.85`
