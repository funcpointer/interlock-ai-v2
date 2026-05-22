# Extraction-Prompt Registry

This directory holds per-doc-class extraction prompts used by the LLM
extraction module landing in Sprint 2. Sprint 1 ships **empty stubs only**;
each class gets a markdown file that Sprint 2 will fill.

## Contract

- One file per `DocClass` value (excluding `unknown`).
- File naming: `<class>.md` (e.g. `coordination_study.md`).
- Each prompt defines the per-class extraction schema and constraints
  for the structured LLM call: `messages.parse(output_format=...)`.
- An empty file is interpreted by Sprint 2 as "use the fallback
  generic-extraction prompt" so absent classes degrade gracefully.

## Filling order (Sprint 2 priority)

1. `coordination_study.md` (largest existing test corpus)
2. `equipment_spec.md` (cross-doc fixture pair)
3. `relay_setting_sheet.md` (SEL paper currently yields zero params)
4. `hvac_schedule.md`
5. `pid.md`
6. `bom.md`
7. `civil_drawing.md`
