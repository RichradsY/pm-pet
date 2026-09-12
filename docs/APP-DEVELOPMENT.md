# Native app development plan

Status: planning, 2026-09-12. No native app, helper, skill package, live adapter, or installer has been implemented. The tagged prototype remains `0.1.0-prototype.1`.

## Updated product contract

An explicitly enabled **conversation** owns one main Pet. This replaces the earlier one-Pet-per-project rule. Two enabled conversations in the same project have two independent Pets; the project is descriptive context, not their identity.

Confirmed requirements:

- Enable or disable the Pet from inside the relevant Codex conversation.
- Support multiple independent Pets, including two conversations open at once.
- Use distinguishable character colors.
- Refresh account quota at a moderate frequency.

Proposed defaults:

- New conversations are off until explicitly enabled. Installation alone enables none.
- Repeated enable for the same conversation restores its existing Pet without duplication.
- Switching or closing a Codex tab does not disable a Pet. The user can keep observing a background task.
- Completed conversations retain an idle Pet until hidden or disabled; completion of a turn does not mean the whole product is finished.
- A critical decision pauses only the owning conversation's build and its actual child agents. An unrelated conversation keeps running.
- The menu bar lists all enabled conversations and offers per-conversation controls plus an explicit global disable.

These defaults are implementation proposals, not claims about current Codex behavior.

## Conversation entry point

The intended explicit command is `$pm-pet enable` or `$pm-pet disable` in the current conversation. A user can also ask the assistant in ordinary language to invoke the same installed integration. These are planned custom skill actions, not built-in Codex commands or a skill available today.

Codex documents explicit skill invocation and optional `allow_implicit_invocation: false`. Use an explicitly invoked integration for lifecycle changes; do not infer enable/disable requests by searching transcripts for those words. Quoted text, tool output, and historical instructions must not toggle a Pet. [Build skills](https://learn.chatgpt.com/docs/build-skills)

The skill invokes a small bundled `pm-pet` helper, passing the current conversation context. The helper validates that identity, contacts the app, and reports success only after the app acknowledges the requested state. Enabling may launch the app; disabling must not launch a closed app just to show a Pet.

Installation of the skill or plugin is a separate onboarding action. Document any session restart/new-session requirement and verify how this existing conversation can discover it. Until discovery is confirmed, the same helper can be explicitly called from the current conversation for a local test. Do not promise hot-loading. [Plugins](https://learn.chatgpt.com/docs/plugins)

No verified public extension currently establishes a persistent switch in Codex's native conversation toolbar. The initial implementation uses conversation commands and the Pet's own menu.

### Identity and control

Use `(provider, host, conversationID)` as the binding key. Store project/workspace information separately. Never choose a conversation by its title, shared working directory, or most recently modified transcript alone.

`CODEX_THREAD_ID` has been observed in this runtime. Its behavior still needs checks in a normal root conversation, a second conversation in the same workspace, a restored conversation, and a child agent. A child agent cannot silently create a second main Pet by invoking the helper with its own context. If identity is unavailable or ambiguous, request the exact conversation link instead of guessing.

The first transport candidate is local IPC between the helper and one running app process. Verify that it works from Codex's actual permission environment. A scoped, atomic control file in a registered workspace is a fallback candidate if IPC is unavailable; it must still validate conversation identity and be acknowledged by the app. Do not broaden permissions to hide a failed transport test.

Proposed helper contract:

| Action | Scope |
| --- | --- |
| `enable` / `disable` / `status` | Current validated conversation when invoked through Codex |
| `enable --conversation <id>` | Explicit binding outside a conversation, with provider/host context |
| `disable --all` | All Pet bindings, only when explicitly requested |
| `report` | Structured roadmap and decision updates for one binding and plan version |
| `quit` | The app process and all its listeners |

Outside Codex, commands without a resolvable conversation must ask for one or list choices. They must not silently become global commands. The helper should succeed idempotently on already-enabled/disabled bindings and return actionable errors for missing installation, identity, or connection.

## Native architecture

Use one Swift/AppKit application with a menu bar controller and one floating window per enabled conversation. Reuse the current character and interaction work inside bundled WKWebView content. Window drawing and web content load only local resources; a narrow native bridge passes state and known UI actions.

| Component | Responsibility |
| --- | --- |
| `PetRegistry` | Binding identity, enabled state, display name, theme, position, size, and visibility preferences |
| `ConversationStore` | Roadmap, plan revision, completed items, unread progress, decision state, and child-agent ownership for one conversation |
| `CodexAdapter` | Validated events for registered conversations; expose capability availability and source freshness |
| `QuotaStore` | One shared quota snapshot and refresh scheduler for each validated authentication context |
| `PetWindowController` | Render one conversation and its chicks; handle dragging, scaling, and returning to its exact Codex conversation |
| `ControlBridge` | Helper requests, validation, acknowledgements, idempotency, and installation-aware lifecycle operations |

The adapter and data stores must not depend on animation completion. Pet animations reflect state and never advance progress, approve a decision, or resume execution.

### Data boundaries

- `PetBinding`: binding key, workspace reference, name, color, enabled state, window position, scale, panel/usage visibility, and binding generation.
- `BuildSnapshot`: conversation and turn IDs, plan revision, event sequence, step IDs/statuses, pending decision ID, and confirmed execution state.
- `ChildAgent`: provider child ID plus explicit owning parent/build identity. Automatic child discovery does not enable a separate main Pet.
- `QuotaSnapshot`: adapter authentication context, quota limit ID, observed windows, values, reset times, source timestamp, and last successful refresh.
- Every update has an owner. Reject mismatched owners, older revisions, duplicate completion events, and updates from a previous disable/re-enable generation.
- Reconnecting loads the latest snapshot without replaying every missed celebration.
- Disabling A closes A's watchers and prompts; B remains connected. An account quota reader can remain active for B because its data is account-wide.
- A pending decision stays accessible in the original Codex conversation after disable, quit, or a crash. No lifecycle action automatically approves it.

## Distinguishing multiple Pets

Start with two calm accent palettes, for example sage and blue, applied to feather accents/accessories. Retain the owl's readable eyes and face. Allocate different colors among visible Pets and persist the selection; let the user change it later.

Color is not the only identifier. The overhead panel and menu entry show the conversation title or a user alias. Same-title conversations receive a disambiguating short label. Pet color does not change because the roadmap changes or the app restarts.

Quota red/orange/green and the decision lantern's yellow remain semantic colors, independent of character theme. Chicks inherit a small parent accent. New Pet windows start at separate positions, keep their user-selected positions, and are clamped after monitor changes.

## Shared quota refresh

Quota is account-wide, not consumption attributed to one Pet. All Pets on the same validated authentication context display the same underlying snapshot and may hide it independently. Do not divide the remaining allowance between conversations.

App Server exposes `account/rateLimits/read` and `account/rateLimits/updated`. These are account endpoints, not conversation endpoints. Identify windows by `windowDurationMins` and quota buckets by the supplied limit ID; `primary` is not a guaranteed 5-hour window. [App Server rate limits](https://learn.chatgpt.com/docs/app-server#6-rate-limits-chatgpt)

Proposed balanced defaults, to measure during local testing:

| Trigger / state | Policy |
| --- | --- |
| A genuine quota update event arrives | Apply it promptly to the shared snapshot; coalesce display updates within one second |
| At least one enabled conversation has confirmed running work and at least one quota display is visible | Refresh at most once every 60 seconds |
| Enabled conversations exist, but none has confirmed running work | Refresh at most once every 5 minutes while quota is visible |
| First connection, wake, or opening quota | Refresh once if the cached snapshot is absent or older than 60 seconds |
| Manual refresh | Share the same request with all Pets; enforce a 10-second global minimum interval |
| All quota displays are hidden | Stop active quota polling; continue ordinary progress tracking and accept quota events already delivered by that tracking |
| All Pets are disabled or the app quits | Stop quota listeners and polling |
| Errors or rate limiting | Preserve the last known value, show freshness/error state, honor retry instructions, and back off rather than retry each second |

Active means observed running work in an enabled build, not keyboard focus or an open Codex window. Schedule from the last successful live update; prevent concurrent quota requests. Progress and human-input events remain prompt and are not delayed by the quota timer.

Use direct adapter calls for refresh, not a repeated prompt to an LLM. Updating a timestamp or rereading the same transcript entry does not count as fetching fresh quota. If the first adapter only observes cached transcript values, display their true observation time; the 60-second schedule is not a freshness guarantee until an actual account read path is verified.

The identity returned by a quota connection must be checked against the intended authentication context. The current public account examples do not establish a permanent account ID for every auth mode. Do not key caches by email alone or assume a separately launched CLI uses the desktop account. On authentication changes, clear the old account snapshot and show unavailable until the new context is verified. [App Server authentication](https://learn.chatgpt.com/docs/app-server#auth-endpoints)

## Build sequence and acceptance

### 1. Validate conversation control and data sources

- In two root conversations, obtain distinct validated identities even when the workspace is identical.
- Confirm enable/disable reaches the app through the real Codex permission environment and can be retried without duplicates.
- Test restoration and child-agent context so neither creates the wrong main Pet.
- Verify a quota read path and its account context; label a transcript-only fallback accurately.
- Verify deep-link return to each conversation and integration discovery in the existing chat.

Deliverable: a small technical spike and recorded capability results, without claiming whole-build execution control.

### 2. Build the native multi-Pet shell

- One app process, two independently colored/positioned windows, and a menu listing both conversations.
- Per-conversation enable/disable, panel hiding, full-Pet hiding, scale, and persistence.
- A disabled conversation stays disabled after restart; B remains unchanged when A is disabled.
- Double-click A returns to A and double-click B returns to B.

Deliverable: a locally launchable application with explicit disconnected states where an adapter is unavailable.

### 3. Connect progress, input, and shared quota

- Replace demo controls/data with owner-validated snapshots and a single account scheduler.
- A step completion updates only its Pet; plan changes invalidate affected items and do not invent progress.
- A question in A triggers A's lantern; B continues its own state and animations.
- Verify the actual decision answer before clearing waiting state. Do not treat a request cleanup as an answer.
- Verify that enabling two Pets does not double quota requests and that all-hidden/disabled policies work.

Deliverable: real two-conversation observation and a tested cooperative reporting flow. Whole-build pausing remains a separate capability gate.

### 4. Package the private alpha and lifecycle tests

- Package the app/helper and optional conversation integration with clear installation ownership.
- Test authenticated private installation, upgrade, disable/enable, quit/restart, disconnect, and uninstall.
- Test window restore after display changes, unavailable data, and stale/late events.
- Only after passing these checks, create a new `0.1.0-alpha.N` version and an explicitly published private prerelease. The prototype tag stays unchanged.

### 5. Verify execution control

- Add one child agent to conversation A and keep an independent build running in B.
- Confirm an A decision pauses all of A's actual build tree while leaving B running.
- Distinguish pause requested from confirmed paused; stop new dispatches in that build.
- Answer in A, review affected work, update the plan, and resume only A's tree.
- Test disable/quit/crash while waiting so decisions remain answerable independently of Pet.

Do not replace the co-build goal with a permanently read-only companion. If current Codex integration cannot implement the required decision/control path, present the concrete product tradeoff before expanding scope or promising the feature.
