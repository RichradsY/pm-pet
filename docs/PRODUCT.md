# PM Pet — Product Specification

## Current status
- The product currently consists of an interactive HTML prototype with simulated data.
- There is no native macOS app, installer, live task connection, or live agent control.
- Demo actions illustrate intended behavior; they do not operate Codex or other agents.

## Purpose and scope
- PM Pet visualizes a product specification being developed with an agent.
- The intended product is an independent macOS desktop companion.
- One explicitly enabled conversation has one main owl. This supersedes the earlier one-Pet-per-project model.
- Two conversations in the same project can have independent Pets; the project path is not the binding identity.
- Enable/disable is intended to be invoked inside the owning Codex conversation through an installed integration.
- Bindings use provider, host, and conversation identity; repeated enable reuses the existing Pet.
- New conversations are off by default in the proposed app; switching/closing a tab does not automatically disable tracking.
- Questions and answers remain in the linked Codex conversation.
- The pet provides a concise view and a route back to that conversation.

## Decisions and human control
- Before delegating work, identify unresolved decisions that materially affect the build.
- Ask about significant product, experience, development-time, or maintenance-cost tradeoffs.
- Distinguish missing facts, unresolved user preferences, and context the agent has not read.
- Resolve ordinary implementation details and discoverable facts without unnecessary interruptions.
- Never automatically approve an action or treat silence as consent.
- Intended behavior: a critical question pauses the owning conversation's main build and all its actual child agents, without pausing an unrelated conversation.
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
- Multiple main Pets have persistent, distinguishable accent colors and conversation names; chicks belong to their actual parent Pet.
- Character colors do not alter quota warning colors or the yellow human-input signal.

## Quotas and account data
- Display only quota windows actually supplied by the account, including weekly-only accounts.
- Missing data is unavailable, never an inferred zero balance.
- Hidden quota displays have an independent recovery control that restores only available windows.
- Quota values in the prototype are examples, not account readings.
- Account quota is shared by all Pets using the same validated authentication context; it is not per-conversation consumption.
- Proposed refresh defaults: live events promptly, one shared read every 60 seconds during running work, and every 5 minutes while idle. Hide-all stops active quota polling.
- Progress and input reminders use their own event path and do not wait for quota polling. Cache repainting does not advance the last-successful-update timestamp.

## Lifecycle and ownership
- Hide: collapse the panel while retaining the pet, tracking, and any pending reminder.
- Disable: suspend only the selected conversation's tracking; a separate explicit global action disables all Pets. Do not silently resume or cancel the underlying build.
- Quit: stop the pet application; do not imply that the build has stopped or resumed.
- Before disable, quit, or uninstall, pending decisions need an accessible handoff in the original conversation.
- A user must be able to resolve a pending decision without the pet running.
- Uninstall: remove only files owned by the installation; explain any retained settings or cache.
- Never remove Codex conversations or project work, or overwrite unrelated configuration.
- Installation must not automatically enable login startup, modify project rules, or grant approvals.
- These lifecycle controls are requirements, not implemented native features.

See [Native app development plan](APP-DEVELOPMENT.md) for the identity model, quota scheduler, proposed defaults, capability gates, and two-conversation acceptance tests.
