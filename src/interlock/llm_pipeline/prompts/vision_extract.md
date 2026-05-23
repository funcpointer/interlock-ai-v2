<!-- src/interlock/llm_pipeline/prompts/vision_extract.md -->
You are looking at a rendered engineering-document page. Identify every
concrete claim you can extract — value tied to source entity / circuit /
section — with visual evidence the reviewer can audit.

## Output

Return STRICTLY this JSON shape (no prose, no markdown fence):

```
{
  "page": <int matching the page-number you were told>,
  "page_understanding": "<one sentence: what this page is>",
  "page_layout": "<prose | table | diagram | mixed>",
  "claims": [
    {
      "entity_kind": "equipment" | "circuit" | "section" | "row_item",
      "entity_id": "<exact label as shown on the page>",
      "entity_location_hint": "<short visual location>",
      "parameter_name": "<canonicalized, e.g. 'Rated Power'>",
      "raw_value": "<exact text shown>",
      "visual_evidence": "<one sentence tying value to entity from visuals>"
    }
  ]
}
```

## Discipline

- Be conservative. If an entity attribution is ambiguous, omit the claim rather than guess.
- Do not invent values not visible on the page.
- `entity_id` MUST be a string that actually appears in the page text (it will be substring-checked).
- One claim per (entity, parameter) pair. Don't repeat the same claim multiple times.
- `visual_evidence` must reference a specific visual cue (relative position, adjacency to a symbol, label in a callout box). Generic statements like "appears on the page" are insufficient.
