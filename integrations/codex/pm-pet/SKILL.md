---
name: pm-pet
description: Enable or disable the PM Pet desktop companion for this Codex conversation, or report an opted-in conversation's roadmap and important unresolved decisions. Use when the user asks to connect PM Pet or maintain its co-build view.
---

# PM Pet

Use the helper at `scripts/pm_pet.py` relative to this skill folder. In the source checkout it locates the developer launcher automatically. If installed separately, the launcher checkout must be configured through `PM_PET_HOME`; do not guess a user's project path.

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

The current adapter observes activity but does not enforce execution pause/resume. When a key decision is pending, stop dispatching work in that build and coordinate its child agents using available runtime tools. Do not claim that all agents are paused unless their state confirms it. Report the question even if pause control is unavailable, and state the limitation in the conversation. An unrelated conversation is unaffected.

Resolve a reported question only after the user answers that question in Codex, using its matching question ID. Review the answer's effect on prior work and the roadmap before continuing. If review finds another material unresolved judgment, ask it rather than guessing. Disable, quit, tool cleanup, silence, and a finished turn are not answers.

## Current integration limits

This is a developer integration, not an installed or notarized consumer app. The launcher can build locally on a Mac with developer tools. Installing this skill is separate; do not edit Codex configuration or global skill folders without the user's request.

Quota displayed by the default adapter comes from the bound conversation's recorded snapshot, with its real timestamp. A separate CLI-account quota probe is available for diagnostics, but its account has not been proven to match the desktop account. Never relabel cached data as a fresh API read.
