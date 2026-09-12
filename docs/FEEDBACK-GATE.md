# Feedback gate

PM Pet's co-build policy is to wait for the user's answer at consequential product, UX, scope, cost, or time decisions and known required-information prompts. The same build's child tasks wait too; unrelated conversations are unaffected.

## What the user sees

Codex can end its asking turn and appear idle while a decision is still pending. Pet keeps **Waiting for your reply** visible; turn completion is not build completion. **Open Codex to reply** only navigates to the owning conversation. Submit the answer on the original question card or send it in that conversation. Ordinary chat feedback shows **Message received / Awaiting review** until the owning agent identifies which items it answers. Multi-item questions show reply counts and move to the next unanswered item; the next item can reopen a hidden panel once.

## What releases the wait

The Desktop adapter recognizes the locally observed `request_user_input_async` call format. It keeps the call ID, question-item IDs, question text, and answer-arrival metadata. It does not copy answers into Pet state. The tool's `{accepted: true}` response only acknowledges delivery.

A corresponding root `UserMessage` with matching question-call and item IDs automatically marks the observed items answered. A normal user message records a pending feedback candidate, without marking an item answered. The owning agent can explicitly associate that actual message with item indices through `reviewFeedback`; this stores provenance, not the answer text. A tool output, turn completion, app restart, elapsed time, or reminder dismissal never answers a question. The local reply envelope is not a cryptographic attestation: it is correlation evidence for the main agent to review, not independent proof of an approved action.

An explicit request to cancel or defer is a separate outcome. The owning agent can cite the actual latest user-message ID and cancel the exact question with a revised full roadmap. This is not an answer or an approval. It is also the recovery path when the user explicitly asks to fix a stuck waiting mechanism; the agent must not insist that the broken question card be answered first.

After every item in the current question is answered, Pet displays **Reply received / Awaiting review**. The wait remains until the owning agent reviews the actual answers in Codex and submits the matching resolution ID with the complete reviewed roadmap and current step. Other queued questions can still keep the gate closed. The agent resumes work only after reviewing the returned state.

The adapter supports the observed Desktop format, not all possible Codex question tools. Chat answers to observed questions require explicit main-agent verification through the [report contract](../integrations/codex/pm-pet/references/report-contract.md#ordinary-chat-feedback). Plain-text questions and system/terminal prompts still need an explicit report and main-agent verification. Passwords stay in the original input window.

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

## Feedback delivery timing

Already bound transcripts are read on the normal local observer tick. While a question is pending, new source shards are rediscovered every two seconds; the normal discovery interval remains thirty seconds. This is local transcript observation, not model or quota polling, and depends on Codex writing the underlying event.

Exact reply envelopes are accepted in first-class user text blocks even when the message also contains other blocks. If a reply arrives before its question is discovered, a bounded metadata cache retains the call/item identity, question digest, source-message identity, and time for later correlation. No answer content is retained. New question admission reserves space for future answer provenance; oversized legacy state still requires separate recovery.

## Validation status

Validated locally on 2026-09-12:

- 161 Python tests and 64 JavaScript tests pass. Coverage includes ordinary feedback candidates, explicit item reconciliation, partial and unrelated replies, atomic failure, cross-thread and stale-source rejection, restart and replay, multi-block replies, and out-of-order call/reply delivery.
- The real bridge produced six synthetic snapshots for the native HTML preview: waiting, message received, a partial verified answer, an unrelated message reviewed, all answers received, and full-roadmap resolution. The UI distinguishes message arrival from a verified answer, keeps the next question visible, uses calm review animation, and resumes progress only with a reviewed report. Long-question/roadmap layout and light/dark appearances were checked.
- The native Swift developer build and source skill validation pass. The next unanswered item has its own reminder identity; ordinary polling or candidate feedback does not repeatedly reopen the panel.
- The optional hook remains untrusted/unverified on this machine. Its scoped feedback-control compatibility is tested offline; neither this hook nor Pet state proves that every running tool is suspended.

A new real ordinary-chat answer and owning-agent reconciliation round trip remains to be validated. This source preview does not imply global installation, consumer distribution, hard runtime suspension, or coverage of every Codex version.
