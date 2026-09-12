# Working on PM Pet

PM Pet is a small macOS companion for co-building with Codex. Keep its UI quiet, default to English, and preserve the distinction between observed activity, reported delivery progress, and actual execution control. Do not infer roadmap completion from time or token usage, or claim a pending question has stopped agents without confirmed control.

## Dogfood the enabled Pet

When working as the owning main agent in this checkout, read `python3 scripts/pm-pet.py status` at the start of a user request. This read does not launch the app. If the current conversation has an enabled Pet, follow [the reporting workflow](integrations/codex/pm-pet/SKILL.md) and [report contract](integrations/codex/pm-pet/references/report-contract.md):

- Review new scope and report the full revised roadmap, current step, and working phase before implementation.
- Update the report when a deliverable is verified, a material user decision is needed, or the work ends.
- Keep payloads and real conversation data in ignored `.pm-pet/runtime/` files.
- If the app is stopped or this conversation is not enabled, continue the task without launching or enabling it automatically.

Child agents send findings to their parent and do not register main Pets or write the parent's overall roadmap. This rule applies only to this repository's development; it does not install a global Codex skill or enable other conversations.

## Wait for feedback before building

The user's policy for an enabled Pet is a whole-build wait at important unresolved product, UX, scope, time, or cost decisions and known required-information prompts. Apply it before delegating whenever possible.

- Before asking, stop dispatching work for this build. Interrupt its running child agents using the runtime's collaboration controls, check their state, and stop or await owned background commands. Do not stop unrelated conversations or unowned processes. If an in-flight operation cannot be safely stopped, explain its actual state; do not claim a complete pause.
- Ask the question in Codex and keep its Pet reminder pending. An asynchronous question tool returning `accepted` only means the question was delivered. After asking, do not edit, build, test, delegate, commit, or push while waiting. End the turn to await the user; use only the control/status operations needed to maintain the wait.
- Silence, elapsed time, a tool finishing, a status-only user message, hiding/closing Pet, and restarting the app never count as an answer. Do not schedule an automatic continuation to bypass the wait.
- After the user answers the actual pending question, review the consequences for completed work and future steps. A plain chat answer is valid after semantic verification: use the report contract's `reviewFeedback` with the observed message ID and answered item indices, rather than asking the user to repeat it on the question card. Resolve the matching question with the full reviewed roadmap before resuming or delegating. If another consequential question remains, keep waiting and ask it first.
- An explicit user request to cancel, defer optional setup, or repair the waiting mechanism authorizes that recovery work. Do not trap the user behind the broken question. Record cancellation/deferment separately from an answer, reference the actual user message, and update the scope before resuming. Never mark an untrusted hook or declined tool as approved.
- Optional integration setup must be labeled as optional setup and offer a way to defer it. It must not silently become an indispensable product decision. Ordinary status messages and diagnostics alone do not cancel a pending decision.

This is the agent's workflow obligation. The local observer and a pending UI state do not themselves cancel running tools. The optional reviewed tool hook provides an additional guard only for supported future tool calls; retain honest execution-control capability labels.
