# PM Pet — Product Specification

## Current status
- The product currently consists of an interactive HTML prototype with simulated data.
- There is no native macOS app, installer, live task connection, or live agent control.
- Demo actions illustrate intended behavior; they do not operate Codex or other agents.

## Purpose and scope
- PM Pet visualizes a product specification being developed with an agent.
- The intended product is an independent macOS desktop companion.
- One explicitly bound project has one main owl linked to its main build task.
- Binding must identify the project and task; nearby or unrelated conversations are not implicitly included.
- Questions and answers remain in the linked Codex conversation.
- The pet provides a concise view and a route back to that conversation.

## Decisions and human control
- Before delegating work, identify unresolved decisions that materially affect the build.
- Ask about significant product, experience, development-time, or maintenance-cost tradeoffs.
- Distinguish missing facts, unresolved user preferences, and context the agent has not read.
- Resolve ordinary implementation details and discoverable facts without unnecessary interruptions.
- Never automatically approve an action or treat silence as consent.
- Intended behavior: a critical question pauses the main build and all its child agents.
- After an answer, review existing work and future plans, update the roadmap, and resume automatically.
- Ask again only when a new material decision arises.
- Whole-build pausing and resumption are not connected or verified; the UI must not claim otherwise.

## Progress and presentation
- Show delivery items, confirmed completion counts, and the current item.
- Progress is completed items divided by planned items, not hours, effort, or a time estimate.
- Plan changes preserve still-valid work, reopen affected items for verification, recalculate progress, and explain the update.
- Hidden-panel updates leave an unread indicator until the user views progress.
- The progress panel sits above the owl and can be hidden and reopened by clicking it.
- Double-clicking is intended to return to the linked conversation; the prototype only demonstrates this.
- Appearance settings are collapsible; pet size ranges from 75% to 150%.
- The panel, reminder, and quota text retain their readable size when the pet scales.

## Pet behavior
- Building: the owl reads a book and turns its pages.
- Newly completed work: briefly show magic, then return to the current work activity.
- Waiting for a person: interrupt magic, raise a yellow lantern, and change expression.
- Appearance changes and elapsed animation time do not advance work or trigger progress feedback.
- Reduced motion retains readable props and states without CSS animation.
- No chicks appear by default; intended child-agent activity causes hatching, then growth and departure.
- Chick lifecycle animations are simulated; actual child-agent discovery is not connected.

## Quotas and account data
- Display only quota windows actually supplied by the account, including weekly-only accounts.
- Missing data is unavailable, never an inferred zero balance.
- Hidden quota displays have an independent recovery control that restores only available windows.
- Quota values in the prototype are examples, not account readings.

## Lifecycle and ownership
- Hide: collapse the panel while retaining the pet, tracking, and any pending reminder.
- Disable: suspend tracking; do not silently resume or cancel the underlying build.
- Quit: stop the pet application; do not imply that the build has stopped or resumed.
- Before disable, quit, or uninstall, pending decisions need an accessible handoff in the original conversation.
- A user must be able to resolve a pending decision without the pet running.
- Uninstall: remove only files owned by the installation; explain any retained settings or cache.
- Never remove Codex conversations or project work, or overwrite unrelated configuration.
- Installation must not automatically enable login startup, modify project rules, or grant approvals.
- These lifecycle controls are requirements, not implemented native features.
