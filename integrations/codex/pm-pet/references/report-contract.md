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
- `currentStepId` optionally identifies the exact pending step to highlight. It must exist in the reported plan and must not be done. It is cleared when that step completes or leaves the plan.
- A new structured user request sets `roadmapNeedsUpdate`. Review its impact, then send both the full `steps` and `currentStep` to acknowledge the plan. Phase-only reports do not clear this flag. The Pet keeps the previous steps available but withholds their percentage until the plan is reviewed.
- Reported progress remains separate from observed turn activity. A finished Codex turn does not mark unfinished delivery items complete.
- Keep the reported scope clear: a roadmap may cover the current request or a longer project, but its count should use that scope consistently. Before a final reply, report the items actually finished and retain future work as pending. Use `idle` when this turn's work stops with roadmap items remaining; reserve `complete` for a fully completed roadmap.
- If the reply finishes a small part of a longer roadmap, briefly explain what is finished and what remains. Do not turn future items green merely to make the Pet match the end of the reply.

To surface a real question, send the current generation and next sequence with:

```json
{"question":{"id":"signup-capacity","text":"When full, close registration or open a waitlist?"}}
```

The Pet shows its yellow reminder. This does not enforce an execution pause. The question must also be asked in Codex using its normal question interface.

For required information or authentication, set `kind: "input"` to use a red reminder. `destination` is `codex` (default), `system`, or `terminal`; `stepId` may identify the affected pending step. Existing questions default to `kind: "decision"`, shown in yellow.

```json
{"question":{"id":"system-auth","kind":"input","destination":"system","stepId":"local-test","text":"Complete the authentication request in the original macOS window."}}
```

Only report that a prompt is pending when it is actually known. The current transcript adapter cannot automatically detect OS password windows (`automaticInputDetection: false`). Store no passwords, answer values, credentials, or terminal output in this payload. The Pet has no password field; the user enters information in the original destination. Once the owning agent verifies the prompt was completed, resolve its matching ID. A tool returning does not itself prove every pending information request was answered.

After the user answers and the agent reviews the impact, send the current generation and next sequence with `"resolveQuestionId":"signup-capacity"`, the revised steps if needed, and the appropriate phase/currentStep. Only an exact match clears the pending question; no tool cleanup or turn-end event clears it automatically.

Use the same reporting helper from the owning main agent. Child agents send their findings back to that agent instead of updating the overall plan independently.

## Automatically observed Desktop questions

For the supported `request_user_input_async` format, ask in Codex without creating a duplicate manual reminder. The bridge uses the actual tool call ID and queues its question items. Inspect `status` for the generated question ID; do not guess it or manually use the reserved `input:` prefix.

- `question.origin: "codex-input-tool"` identifies an observed input call. `question.items` contains item identity, question text, and whether a correlated reply arrived; it never includes answer values.
- `question.status: "awaiting_reply"` means at least one item still needs a reply. `awaiting_review` means all items have matching replies but the main agent has not reviewed them yet. Both states keep the report gate closed.
- `pendingQuestions` holds unresolved observed calls. Resolving the current one can reveal another. Check the accepted report's resulting state before resuming work.
- To resolve an observed question, provide its exact `resolveQuestionId` plus full `steps` and `currentStep`. Every item must have a correlated card reply or an explicitly verified chat answer through `reviewFeedback`. Read the actual answers in Codex, review their impact, and report the resulting roadmap; merely possessing the ID is insufficient.
- A correct resolution and a newly reported manual question may appear in one atomic report. If validation fails, the old question and state remain intact.
- Restart and disable/re-enable preserve unresolved questions; completed call IDs are retained as replay protection. First adoption starts observing new input calls rather than reopening all historical questions.

Follow the [feedback gate workflow](../../../../docs/FEEDBACK-GATE.md) for stopping child tasks and waiting. This report contract blocks progress updates while unresolved; it does not by itself interrupt runtime execution. Asynchronous delivery acknowledgements, timeout, and turn completion never resolve a question.

## Explicit cancellation and optional setup

The main agent can honor a user's explicit cancellation, deferral, or superseding request without manufacturing a question-card answer. Send `cancelQuestionId`, `cancellationReason` (`setup_deferred`, `user_cancelled`, or `superseded`), and `sourceUserMessageId` with the full reviewed `steps` and `currentStep`. The source ID must match the latest observed root user request and follow the original question. `cancelQuestionId` and `resolveQuestionId` are mutually exclusive. Keep the current generation and increasing sequence protections.

To label optional setup, include `purpose: "setup", optional: true` on a manual question, or report `classifyQuestion: {id, purpose: "setup", optional: true}` for the exact current question. Classification changes metadata only; it does not clear the wait. It can accompany an explicitly requested setup deferral in one transaction.

Pet offers **Not now** only for that optional setup. Its scoped `defer_setup` action checks the current binding generation and question ID. The bridge records a cancelled/deferred outcome and marks the roadmap for review. It does not grant a tool permission, mark a hook trusted, or send a continuation prompt. The main agent must review the deferred work before resuming, and other pending questions stay pending.

Cancelled question calls retain replay protection; a late reply cannot revive them. The original question card may remain in Codex because this local adapter does not own Codex's card lifecycle. Do not ask a duplicate question to clear it.

## Ordinary chat feedback

Users may answer in the original conversation's composer instead of its question card. An observed ordinary user message after an open question creates `pet.feedback` with `questionId`, `sourceUserMessageId`, `observedAt`, and `status: "pending_review"`. This records message arrival only. It does not mark any question answered or allow work to resume, and it copies no message content into Pet state.

Read that actual message in Codex and compare it with each pending question item. Then submit:

```json
{
  "generation": 1,
  "sequence": 4,
  "reviewFeedback": {
    "questionId": "input:call_example",
    "sourceUserMessageId": "the-observed-message-id",
    "answeredItemIndexes": [0]
  }
}
```

Use IDs and counters from fresh status, not these sample values. Indices identify only the items the message actually answers. An empty list records that you checked the message and it does not answer this question. The question stays pending; do not treat a status request, unrelated comment, or silence as an answer.

A review-only report preserves the existing roadmap and waiting state. If the message completes all items, include `resolveQuestionId` and the full reviewed `steps` and `currentStep` in the same report to update the roadmap and continue atomically. Otherwise review the partial answer, leave the build waiting, and ask only for what is still missing. No need to make the user submit the same answer twice.

The bridge validates current question and source-message identity and retains review provenance separately from card correlation. It cannot judge the meaning of a message; semantic verification remains the owning agent's responsibility. Read the returned state before proceeding, because another question may still be pending.
