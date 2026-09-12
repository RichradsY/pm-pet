# Feedback gate

PM Pet's co-build policy is to wait for the user's answer at consequential product, UX, scope, cost, or time decisions and known required-information prompts. The same build's child tasks wait too; unrelated conversations are unaffected.

## What releases the wait

The Desktop adapter recognizes the locally observed `request_user_input_async` call format. It keeps the call ID, question-item IDs, question text, and answer-arrival metadata. It does not copy answers into Pet state. The tool's `{accepted: true}` response only acknowledges delivery.

Only a corresponding root `UserMessage` with matching question-call and item IDs marks the observed items answered. A normal user message, tool output, turn completion, app restart, elapsed time, or reminder dismissal never does. The local reply envelope is not a cryptographic attestation: it is correlation evidence for the main agent to review, not independent proof of an approved action.

An explicit request to cancel or defer is a separate outcome. The owning agent can cite the actual latest user-message ID and cancel the exact question with a revised full roadmap. This is not an answer or an approval. It is also the recovery path when the user explicitly asks to fix a stuck waiting mechanism; the agent must not insist that the broken question card be answered first.

After every item in the current question is answered, Pet displays **Reviewing reply**. The wait remains until the owning agent reviews the actual answers in Codex and submits the matching resolution ID with the complete reviewed roadmap and current step. Other queued questions can still keep the gate closed. The agent resumes work only after reviewing the returned state.

The adapter supports the observed Desktop format, not all possible Codex question tools. Plain-text questions and system/terminal prompts still need an explicit report and main-agent verification. Passwords stay in the original input window.

## Stopping work is separate from displaying a question

Before asking, the main agent must stop dispatching tasks, interrupt the same build's active child agents through collaboration controls, verify their state, and stop or await its owned background commands. It must disclose any operation that cannot be safely stopped. After asking, it ends the turn and waits rather than continuing independent build work.

This policy is in the repository's [AGENTS.md](../AGENTS.md) and reusable [PM Pet skill](../integrations/codex/pm-pet/SKILL.md). It is not a process supervisor. The bridge keeps `executionControl: false`: it cannot cancel the running model, revoke a tool already executing, or freeze arbitrary descendant processes. The runtime's `turn/interrupt` operation cancels a turn; it is not a universal pause-and-resume switch for a separate app's existing connection. See the official [App Server protocol](https://learn.chatgpt.com/docs/app-server).

## Optional local tool guard

The reviewed [PreToolUse hook](../integrations/codex/pm-pet/hooks/README.md) supplies an additional check before supported new local tool calls. It reads the persisted gate for the exact owning conversation. Waiting and awaiting-review states both block build work; a narrow set of status and resolution controls remains available.

Codex requires new non-managed hooks to be reviewed and trusted. Project trust alone is insufficient. Do not write a `trusted_hash` or bypass hook trust. Follow the hook's setup instructions and use Codex's Hooks settings to reload, review, and trust the exact source. A configured file is not evidence that the hook ran in the current conversation.

Official [Hooks documentation](https://learn.chatgpt.com/docs/hooks) describes the relevant boundaries:

- Supported local paths include shell commands, edits, MCP tools, and delegation tools, including nested local calls in code mode.
- `write_stdin` does not run the pre-tool hook again, and hosted tools are outside this hook path. Other specialized paths may opt out.
- A pre-tool denial prevents that supported call; it does not cancel work already in progress.
- Hooks need their own trust review. Their coverage is a guardrail rather than a complete execution boundary.

Question observation is asynchronous, so a tool guard cannot close the interval before a question reaches the local bridge. The main agent's stop-before-asking rule is required even with the hook enabled. The agent must not use an absent reminder during this observation interval as permission to keep building.

## Optional setup must remain optional

Hook trust is an optional integration step. Label it **Optional setup**, explain what it enables, and offer **Not now**. Explicit `purpose: setup` and `optional: true` metadata controls that affordance; the adapter does not guess from question wording. Ordinary product decisions and tool approvals have no generic dismiss-to-continue button.

Deferring setup records a cancellation outcome, keeps the capability unverified, and requests roadmap review. It does not report successful installation or tool approval. If the user asks to continue without this optional feature, remove its activation test from the active delivery scope and keep it in the documented backlog instead of leaving the whole Pet waiting forever.

The local adapter does not own the original Codex question-card lifecycle. A cancelled card may remain visible there; late replies cannot restore the cancelled Pet gate. The Pet's Not now action does not send a new model prompt, so continuing an idle Codex turn still occurs in Codex.

## Computer Use approval reminders

The inspected Desktop transcript records Computer Use calls after completion but does not expose a reliable pending approval lifecycle to this observer. The local macOS Computer Use implementation requests consent through an internal MCP elicitation, carrying the connector and tool-call identity. Tool start, elapsed time, the word “approval” in output, and an automatic approval review are not evidence that a human confirmation is pending.

A reliable future adapter needs the owning Desktop server's actual `mcpServer/elicitation/request` event, its thread and request identity, and the correlated response or cancellation. `serverRequest/resolved` alone has no decision value. A new, unrelated App Server connection does not establish access to the existing Desktop conversation. A PermissionRequest hook is a candidate only after live evidence confirms that this internal Computer Use path reaches it.

These permission reminders must remain separate from roadmap decisions. Deferring Pet setup never approves a tool. Automatic Computer Use approval reminders are not connected in this version.

## Question queue capacity

New automatically observed question calls are admitted under a 2 MiB serialized registry budget, leaving room below the native 4 MiB reader limit. Excess calls create an explicit reconciliation reminder without discarding already queued questions; bounded overflow identities prevent replay. This prevents newly admitted question bodies from exhausting the reader, but does not migrate an already oversized legacy state file.

## Validation status

Validated locally on 2026-09-12:

- 67 bridge/question tests and 33 hook tests pass. Coverage includes multi-item queues, explicit cancellation with root-message provenance, optional setup classification, binding isolation, failure atomicity, shared serialized payload budget, restart, replay, late replies, full-roadmap review, literal control commands, and fail-closed state errors.
- 45 native-state tests pass. The actual native HTML browser preview keeps Optional setup, Open Codex, and Not now above a long roadmap; a failed deferral restores the button and reports the failure. Stale responses and timeouts cannot clear a different question. A native acknowledgment timeout is shown as unconfirmed, distinct from a definite rejection, and later authoritative state remains decisive.
- The native Swift developer build passes, including an independently compiled version of the recovery change.
- In the real owning conversation, the obsolete hook-setup question was cancelled as `setup_deferred` with zero answered items, based on the user's explicit recovery request. The Pet returned to Building and its reading animation with the revised roadmap. The deferred hook activation was removed from the active scope, not marked completed.
- The machine-specific hook configuration remains ignored by Git. Its trust and live execution coverage remain unverified; optional activation is deferred.

The real correlated answer/review flow and trusted-hook execution test still need separate live validation. Global installation, consumer distribution, hard runtime suspension, and coverage of all Codex versions are not implied by this integration.
