This page is from a **Bill of Material (BOM)**.

## Priority parameter families

- `Part Number` — manufacturer part designation — e.g., `"VCP-W-1600"`, `"SEL-787-1A"`
- `Manufacturer` — vendor name — e.g., `"Eaton"`, `"Schneider"`, `"GE"`
- `Quantity` — count — e.g., `"12"`
- `Description` — equipment text description — e.g., `"Main Breaker, 1600 A, 38 kV"`
- `Vendor Catalog Number` — e.g., `"C440-1600-VCP"`

## Layout hints

- BOMs are line-item tables. Columns typically: `Item # | Qty | Description | Manufacturer | Part Number | Vendor Cat #`.
- The leftmost `Item #` is the row's BOM line identifier (`1`, `2`, `3`, …) → use it as `entity_tag` for all claims on that row.
- The same row produces multiple claims (one per non-empty column). All share the same `entity_tag` and `span_text`.
- Totals rows (`Total line items: 10`) are NOT claims.
- Approval / revision footers are NOT claims.

## Few-shot example

Input text:
```
Item #  Qty  Description                    Manufacturer  Part Number       Vendor Cat #
1       1    Main Breaker, 1600 A, 38 kV    Eaton         VCP-W-1600        C440-1600-VCP
2       12   Feeder Breaker, 600 A, 5 kV    Eaton         VCP-W-600         C440-600-VCP
6       12   Protective Relay SEL-787       SEL           SEL-787           SEL-787-1A
```

Expected claims (Item 1):
- `parameter_name="Quantity"`, `raw_value="1"`, `entity_tag="1"`, `span_text="1       1    Main Breaker, 1600 A, 38 kV    Eaton         VCP-W-1600        C440-1600-VCP"`, `confidence=0.95`
- `parameter_name="Description"`, `raw_value="Main Breaker, 1600 A, 38 kV"`, `entity_tag="1"`, same span_text, `confidence=0.9`
- `parameter_name="Manufacturer"`, `raw_value="Eaton"`, `entity_tag="1"`, same span_text, `confidence=0.95`
- `parameter_name="Part Number"`, `raw_value="VCP-W-1600"`, `entity_tag="1"`, same span_text, `confidence=0.95`

For Item 2 same structure, `entity_tag="2"`, `Quantity="12"`, etc.
