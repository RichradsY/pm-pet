# Feedback gate

PM Pet's co-build policy is to wait for the user's answer at consequential product, UX, scope, cost, or time decisions and known required-information prompts. The same build's child tasks wait too; unrelated conversations are unaffected.

## What releases the wait

The Desktop adapter recognizes the locally observed `request_user_input_async` call format. It keeps the call ID, question-item IDs, question text, and answer-arrival metadata. It does not copy answers into Pet state. The tool's `{accepted: true}` response only acknowledges delivery.

Only a corresponding root `UserMessage` with matching question-call and item IDs marks the observed items answered. A normal user message, tool output, turn completion, app restart, elapsed time, or reminder dismissal never does. The local reply envelope is not a cryptographic attestation: it is correlation evidence for the main agent to review, not independent proof of an approved action.

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

## Validation status

Validated locally on 2026-09-12:

- 55 bridge/question tests and 31 hook tests pass. Coverage includes multi-item and multi-call queues, unrelated messages and conversations, persistence and replay, premature resolution rejection, complete-roadmap review, literal control commands, and fail-closed state errors.
- 35 native-state tests pass. A browser preview using the actual native HTML confirms that **Reviewing reply** keeps the question action in the first viewport, preserves the completion count, and resets the next question's scroll position.
- The native Swift developer build and reusable skill validation pass.
- A machine-specific project hook configuration was prepared locally. It is ignored by Git, contains no answers or trust hashes, and still needs the user's **Reload hooks → Review/Trust** plus live hook-result verification in Codex.

The real-conversation wait/reply test and trusted-hook execution test remain pending. Do not describe the optional guard as active before those checks succeed. Global installation, consumer distribution, hard runtime suspension, and coverage of all Codex versions are not implied by this integration.
