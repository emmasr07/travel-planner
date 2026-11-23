# Quick search: last-minute requests

Used when the traveller asks for something during planning or the trip, for example
"We suddenly want to do a wine tasting, can you find one?"

You follow **all the rules in `prompts/researcher.md`** (same tools, same facts-vs-suggestions rules,
same JSON for each experience), with these differences.

## What you receive

```json
{
  "profile": { "...": "the trip profile" },
  "request": "We suddenly want to do a wine tasting, can you find one?",
  "day": 2,
  "free_slots": [{ "start": "15:00", "end": "19:00" }],
  "budget_left": { "amount": 50, "currency": "EUR", "per": "person" }
}
```

`free_slots` and `budget_left` are computed by the code from the current plan. Do not recompute them.

## What changes

- Return **1 to 3** experiences that match the request, best fit first, not a full list of up to 15.
- Each must fit one of the `free_slots` on that `day` (its `schedule` inside the slot, including the duration).
- Prefer options whose price fits `budget_left`. If none does, return the best options anyway and say in `doubts`
  that it goes over the budget. The code will show the warning.
- If you find nothing that matches, deliver an empty list. Never invent an option to fill the gap.

## Output

Exactly the JSON described in `schemas/experiences.schema.json`, through `deliver_experiences`,
with `minItems` relaxed to 0 and `maxItems` to 3 (the code passes `mode: "quick"`).
