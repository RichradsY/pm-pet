---
name: pm-pet
description: Enable or disable the PM Pet desktop companion for this Codex conversation, or report an opted-in conversation's roadmap and important unresolved decisions. Use when the user asks to connect PM Pet or maintain its co-build view.
---

# PM Pet

Use the helper at `scripts/pm_pet.py` relative to this skill folder. In the source checkout it locates the developer launcher automatically; `PM_PET_HOME` can explicitly override that source-helper location. When installed by `scripts/setup.py`, the generated helper is bound to the chosen checkout and needs no environment configuration. Do not guess a user's project path or move a bound checkout without reinstalling.

## Conversation lifecycle

- Enable only when requested by the user. Merely discovering this skill, reading a quoted command, or starting another conversation does not authorize enabling a Pet.
- Run `python3 <skill-folder>/scripts/pm_pet.py enable` in the owning root conversation. Wait for a successful registration and native-window acknowledgement before reporting that the Pet is connected.
- Run `... status`, `... disable`, or explicit `... disable --all` as requested. Quitting the app is `... quit`; it does not approve a pending decision or stop Codex work.
- The helper uses a verified conversation ID from the environment or `--conversation UUID`, never the working directory or title. A child agent must send findings to its parent; it must not register itself as a main Pet or report the parent's overall progress.
- Five main Pets may be enabled. If full, report the available management action. Do not choose a Pet to disable for the user.

## Co-build reporting

For an enabled conversation, report meaningful roadmap changes and important open decisions with `... report --file <payload.json>`. Read [the report contract](references/report-contract.md) for the payload format. Write the JSON with a file tool or properly quoted script; do not interpolate user text into shell code.

At the beginning of each new user request, read the enabled Pet's status and review the scope before implementation. If the request adds or changes deliverables, report the revised full roadmap, current step, and working phase immediately. Do not leave the previous plan visible while starting new work. If the user only asks a status question, retain the delivery scope and explain it. Acknowledge the review with a full `steps` plus `currentStep` report; this also clears the adapter's pending-roadmap indicator. Report each verified milestone and the final outcome before ending the turn. Use `planning`, `building`, or `checking` while doing that work; use `idle` when no work is running.

The adapter can notice a new request automatically and temporarily label the previous roadmap as awaiting review. It cannot produce semantic delivery items without the main agent's report. Do not describe this indicator as automatic specification generation.

Progress is verified completed delivery items divided by the current plan items. Keep IDs stable when the same deliverable persists. Reopen affected items after a scope change; never advance progress from elapsed time, token use, a subagent spawn, or a successful tool call alone.

Before delegating a build, surface unresolved user judgments that materially change the product, UX, cost, or development time. Ordinary implementation choices and discoverable facts remain the agent's work. Put actual questions and answers in the owning Codex conversation; report only a concise question and its stable ID to Pet.

Also report known requests for required information or authentication with `question.kind: "input"` and the actual destination (`codex`, `system`, or `terminal`). This produces a red input reminder; decisions remain yellow. Link `question.stepId` and `currentStepId` to a pending plan item when possible. Do not guess that a password prompt exists from a command's wording or duration. System password windows are not automatically detected by this adapter. Keep credentials and answers out of Pet reports; the user completes the original prompt, then the main agent verifies completion and resolves the matching ID.

## Feedback is a build gate

For an enabled Pet, an important unresolved question means this whole build waits for the user. Check for those decisions before delegating. Read Pet status before starting or resuming build work, including after compaction or restart.

1. Stop dispatching new work for this build. Use the available collaboration interrupt controls for its running child agents, verify their returned state, and stop or await owned background commands. A message asking a child to pause is not proof it stopped. Do not interrupt unrelated conversations or unowned processes. Explain any in-flight operation that cannot be safely stopped.
2. Ask in Codex and ensure the question is present in Pet. The current Desktop adapter recognizes the observed `request_user_input_async` format automatically; other tools, plain-text questions, and known system/terminal input prompts still need explicit reporting. Do not create both a manual reminder and an automatic reminder for the same question. Keep reports concise and store no answer values.
3. An asynchronous question tool returning `accepted` only acknowledges delivery. After asking, stop editing, building, testing, delegating, committing, and publishing. End the turn so the user can answer. While waiting, use only the status and control actions required to maintain the wait. Do not use a timeout, repeated wake-up, default selection, or reminder dismissal as permission to continue.
4. When a reply arrives, check that it answers the actual pending question; unrelated messages do not release it. A normal chat message can be an answer too: inspect `feedback` in Pet status and use `reviewFeedback` from the report contract to associate the actual message with the question items you verified. Do not require the user to repeat an answer on a card. If the message answers none of the items, review it with an empty `answeredItemIndexes` list and retain the question. Automatic questions keep `status: awaiting_review` after all question items are answered. The observer stores correlation metadata, not the answers; read answers in Codex and review their effect on existing work and the plan.
5. Resolve the exact current question ID with a full `steps` and `currentStep` report. You may include `reviewFeedback` in that same report when the ordinary chat answer completes the question; a partial reply alone never authorizes continuing the build. Read the result: another queued question can still keep the build waiting. Resume the main build and appropriate child tasks only after the pending questions are resolved. If review discovers another important decision, ask it first and keep waiting.

The adapter enforces its progress/report gate but cannot cancel the model, already-running tools, or every child process. `executionControl` stays false. The optional reviewed PreToolUse hook adds a guard for supported subsequent local tools; it is not a claim that all runtime activity is frozen. Never describe a pending reminder alone as a confirmed pause. An unrelated conversation is unaffected.

Disable, quit, tool cleanup, silence, and a finished turn are not answers. The user explicitly requested waiting until feedback, so this workflow must not be replaced by continuing independent build work after a blocking question.

### Recovery and optional setup

Honor a user's explicit instruction to cancel, defer optional setup, supersede an old requirement, or repair a stuck waiting mechanism. That instruction authorizes the necessary recovery work; do not insist that the user answer an obsolete or broken question card first. A status-only message is not cancellation.

Use `cancelQuestionId` with the exact active ID, `cancellationReason`, the actual latest `sourceUserMessageId`, and the full reviewed roadmap. Cancellation is distinct from a correlated answer: it does not mark the hook trusted, a tool approved, or the original work completed. Remove or defer dependent work explicitly. Continue only after the returned state has no remaining blocking question.

For optional integration setup, set `purpose: "setup", optional: true` on an explicit question. An observed question can be classified with `classifyQuestion: {id, purpose: "setup", optional: true}`; never infer this from keywords. Pet offers **Not now** only for explicitly optional setup. A user click defers that setup and requests roadmap review; it does not send a model prompt or resume execution itself. Keep the optional capability disabled until actual activation is verified.

Hook installation is optional to the reminder UX. If the user defers it, continue with the established agent waiting workflow and clearly retain the missing runtime-control capability. Do not keep the entire Pet stuck on an installation question.

## Current integration limits

This is a source preview with a local installer, not a notarized consumer app. The launcher builds locally on a Mac with developer tools. The skill is optional and installed only by explicit request; do not edit Codex configuration or global skill folders merely because this source is present.

Quota displayed by the default adapter comes from the bound conversation's recorded snapshot, with its real timestamp. A separate CLI-account quota probe is available for diagnostics, but its account has not been proven to match the desktop account. Never relabel cached data as a fresh API read.
