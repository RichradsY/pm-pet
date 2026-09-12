# PM Pet — Product Specification

## Current status
- A native macOS developer app now connects to explicitly enabled local Codex conversations through a source-checkout helper.
- It displays reported roadmaps/questions, observes root and child activity, and shares cached general Codex quota with its source timestamp. It does not enforce agent pause/resume or automatically fetch live Desktop quota.
- The included conversation skill is source only, not installed. A consumer installer and downloadable release remain future work.
- The separate HTML prototypes still use simulated data. The tagged `0.1.0-prototype.1` milestone is unchanged; native work is unreleased.

## Purpose and scope
- PM Pet visualizes a product specification being developed with an agent.
- The intended product is an independent macOS desktop companion.
- One explicitly enabled conversation has one main owl. This supersedes the earlier one-Pet-per-project model.
- Two conversations in the same project can have independent Pets; the project path is not the binding identity.
- Enable/disable can be invoked inside the owning Codex conversation through the local helper; installing a discoverable skill remains a separate step.
- Current bindings use exact conversation UUIDs validated against local Codex session metadata. Provider/host namespaces are a future extension; repeated enable reuses the existing Pet.
- Design for up to five enabled main Pets. Actual child-agent chicks do not consume this capacity.
- At capacity, enabling an already-enabled conversation succeeds without duplication. Enabling a sixth main Pet asks the user to disable one first; never replace or evict a Pet automatically.
- New conversations are off by default; switching/closing a tab does not automatically disable tracking.
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
- Whole-build pausing and resumption are not enforced. The main agent must coordinate any pause using its available tools and confirm actual child states before claiming success.
- The current report path requires a matching pending question ID, current binding generation, and increasing report sequence before clearing a question. These checks reject stale updates; they do not independently verify a user's answer.

## Progress and presentation
- Show delivery items, confirmed completion counts, and the current item.
- A newly observed root user request marks the previous roadmap for review. Keep prior steps available, withhold the old percentage, and restore progress after the main agent reports the reviewed full plan.
- Progress is completed items divided by planned items, not hours, effort, or a time estimate.
- Plan changes preserve still-valid work, reopen affected items for verification, recalculate progress, and explain the update.
- Target behavior: hidden-panel updates leave an unread indicator until the user views progress; the native unread indicator remains to be implemented.
- The progress panel sits above the owl and can be hidden and reopened by clicking it.
- Native double-click/menu navigation opens the exact conversation's Codex deep link; browser prototypes only demonstrate navigation.
- Native size controls are in the Pet menu, with 75%, 100%, 125%, and 150% presets. The prototype also demonstrates collapsible appearance settings.
- The panel, reminder, and quota text retain their readable size when the pet scales.
- Keep the owl silhouette transparent without a pale outline. Use native glass for compact progress/name/quota surfaces; the quota timestamp stays outside its pill as a small unboxed line. Respect Reduce Transparency.

## Pet behavior
- Building: the owl reads a book and turns its pages.
- Newly completed work: briefly show magic, then return to the current work activity.
- Waiting for a person: interrupt magic, raise a yellow lantern, and change expression.
- Appearance changes and elapsed animation time do not advance work or trigger progress feedback.
- Reduced motion retains readable props and states without CSS animation.
- No chicks appear by default; observed child-agent activity causes hatching, then growth and departure. Repeated interaction alone is not proof of resumed work.
- Native chicks follow their own stable child identities. Browser prototypes retain simulated child controls.
- Multiple main Pets have persistent, distinguishable accent colors and conversation names; chicks belong to their actual parent Pet.
- The five default accents are sage, sky, lilac, rose, and sand. Names or short labels provide identification alongside color.
- Character colors do not alter quota warning colors or the yellow human-input signal.

## Quotas and account data
- Display only quota windows actually supplied by the account, including weekly-only accounts.
- Missing data is unavailable, never an inferred zero balance.
- Hidden quota displays have an independent recovery control that restores only available windows.
- Quota values in the browser prototype are examples. Native values come from recorded general Codex snapshots in bound conversations, with model-specific buckets excluded.
- Account quota is shared by all Pets using the same validated authentication context; it is not per-conversation consumption.
- Only the first-ever newly enabled Pet shows quota by default. Additional new Pets start with quota hidden; each Pet can turn its own display on or off.
- Quota visibility preferences persist across disable/re-enable. Hiding or disabling the first Pet never moves quota to another automatically; all displays may remain hidden.
- Quota can be restored from any Pet's settings or its menu entry, including when every display is hidden.
- Proposed refresh defaults: live events promptly, one shared read every 60 seconds during running work, and every 5 minutes while idle. Hide-all stops active quota polling.
- These refresh intervals are future scheduler behavior. An optional direct CLI-account probe works, but its account is not verified against Desktop and it is not an automatic Pet data source.
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
- Per-conversation enable/disable, explicit `disable --all`, app quit, and preference restoration are implemented for the developer build. Installed-package update/uninstall and distribution checks remain future work.

See [Local Codex integration](LOCAL-INTEGRATION.md) for current setup and [Native app development plan](APP-DEVELOPMENT.md) for remaining capability gates.
