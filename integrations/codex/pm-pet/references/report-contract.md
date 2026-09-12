# Report contract

Run `status` first to obtain the enabled Pet's `generation`, `lastReportSequence`, and `planVersion`. These values belong to the exact conversation ID. Write a payload file and run `python3 <skill-folder>/scripts/pm_pet.py report --file <payload.json>`.

Example structure (replace the example items and counters with the actual current plan):

```json
{
  "generation": 1,
  "sequence": 1,
  "planRevision": 1,
  "phase": "building",
  "currentStep": "Connect the native window",
  "steps": [
    {"id": "identity", "label": "Verify the conversation identity", "done": true},
    {"id": "window", "label": "Connect the native window", "done": false},
    {"id": "lifecycle", "label": "Verify disable and restart", "done": false}
  ]
}
```

- `generation` must equal the current enabled binding. Re-enabling a disabled Pet changes it.
- `sequence` must increase beyond the last accepted report. Check `status` after an uncertain response before retrying.
- `planRevision` is an integer no older than the current plan; increment for scope or structure changes.
- `steps` is a full snapshot of 1–100 actual delivery items, with stable unique IDs and explicit boolean `done`. Percentages are computed by the bridge.
- `currentStep` is concise human-readable text. `phase` may be `idle`, `planning`, `building`, `checking`, `complete`, or `error`. A waiting phase requires a question.
- A new structured user request sets `roadmapNeedsUpdate`. Review its impact, then send both the full `steps` and `currentStep` to acknowledge the plan. Phase-only reports do not clear this flag. The Pet keeps the previous steps available but withholds their percentage until the plan is reviewed.
- Reported progress remains separate from observed turn activity. A finished Codex turn does not mark unfinished delivery items complete.

To surface a real question, send the current generation and next sequence with:

```json
{"question":{"id":"signup-capacity","text":"When full, close registration or open a waitlist?"}}
```

The Pet shows its yellow reminder. This does not enforce an execution pause. The question must also be asked in Codex using its normal question interface.

After the user answers and the agent reviews the impact, send the current generation and next sequence with `"resolveQuestionId":"signup-capacity"`, the revised steps if needed, and the appropriate phase/currentStep. Only an exact match clears the pending question; no tool cleanup or turn-end event clears it automatically.

Use the same reporting helper from the owning main agent. Child agents send their findings back to that agent instead of updating the overall plan independently.
