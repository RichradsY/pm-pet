# Native app development plan

Status: `0.1.0-alpha.1` source preview, 2026-09-12. The repository contains a Swift/AppKit app, local helper/bridge, source installer, and optional Codex skill. The five-Pet browser prototype remains in `prototypes/pm-pet-multi.html`. The historical prototype tag is unchanged. A signed/notarized downloadable app remains future work. See [Installation](INSTALLATION.md) for the current user flow.

## Current implementation

| Area | Available now | Remaining validation or development |
| --- | --- | --- |
| Conversation binding | Explicit enable, exact UUID/session-metadata validation, five-root-Pet limit, idempotent enable | Two simultaneous real root conversations, wider Codex-version compatibility |
| Native UI | Independent owl/progress surfaces, colors, dragging, size presets, per-Pet quota visibility, menu controls | Full-Pet hiding, unread progress, broader display/accessibility checks |
| Progress and decisions | Main-agent roadmap/question reports, generation/sequence validation, matching question resolution | Automatic integration discovery and sustained reporting across sessions |
| Activity | Recorded root/child events; child identity stays with its owning Pet | Broader transcript-format and resumed-child coverage |
| Quota | Shared cached general Codex snapshot, timestamp/age, weekly-only handling | Verified Desktop account binding and automatic live refresh |
| Lifecycle | Acknowledged launch/rendering, disable/re-enable, quit/restart tested on the development Mac | Prebuilt package distribution and other-machine tests |
| Execution control | Explicitly unavailable in the adapter | Confirmed pause/review/resume of the owning build tree |

Run `python3 scripts/pm-pet.py enable --title "My build"` from the owning Codex conversation. The first launch may need macOS/Codex approval. See [Local Codex integration](LOCAL-INTEGRATION.md) for exact commands and the current capability boundary.

## Updated product contract

An explicitly enabled **conversation** owns one main Pet. This replaces the earlier one-Pet-per-project rule. Two enabled conversations in the same project have two independent Pets; the project is descriptive context, not their identity.

Confirmed requirements:

- Enable or disable the Pet from inside the relevant Codex conversation.
- Design for up to five enabled main Pets, including independent conversations in the same project. Actual child-agent chicks do not consume this capacity.
- Use five distinguishable character accents with conversation names or short labels.
- Show shared account quota on only one Pet by default; let users enable it on other Pets individually.
- Refresh account quota at a moderate frequency.

Proposed defaults:

- New conversations are off until explicitly enabled. Installation alone enables none.
- Repeated enable for the same conversation restores its existing Pet without duplication.
- At five enabled main Pets, an already-enabled binding remains an idempotent success. Enabling a sixth, including a previously disabled binding, returns a clear choice to disable one first. Never replace or evict another Pet automatically.
- Switching or closing a Codex tab does not disable a Pet. The user can keep observing a background task.
- Completed conversations retain an idle Pet until hidden or disabled; completion of a turn does not mean the whole product is finished.
- A critical decision pauses only the owning conversation's build and its actual child agents. An unrelated conversation keeps running.
- The menu bar lists all enabled conversations and offers per-conversation controls plus an explicit global disable.
- The first-ever newly enabled Pet starts with quota visible; additional new bindings start with quota hidden. Existing visibility preferences survive disable/re-enable.
- Hiding or disabling a Pet never transfers its quota display to another. All displays may be hidden; restore quota through any Pet's settings or menu entry.

Enable defaults, capacity, and per-Pet quota preferences are implemented in the developer build. Confirmed whole-build pausing and a global-disable menu item remain target behavior; explicit `disable --all` is available through the helper.

## Conversation entry point

The current entry point is the source-checkout helper: `python3 scripts/pm-pet.py enable` or `disable`. A user can ask the assistant to call that helper from the owning conversation. The optional [skill](../integrations/codex/pm-pet/SKILL.md) describes the same flow and can be installed explicitly through the [source installer](INSTALLATION.md). `$pm-pet` is a custom installed skill, not a built-in Codex command.

Codex documents explicit skill invocation and optional `allow_implicit_invocation: false`. Use an explicitly invoked integration for lifecycle changes; do not infer enable/disable requests by searching transcripts for those words. Quoted text, tool output, and historical instructions must not toggle a Pet. [Build skills](https://learn.chatgpt.com/docs/build-skills)

The source skill invokes the checkout helper using the current conversation context. The helper validates that identity, contacts the app, and reports enable success only after the corresponding native views acknowledge rendering. Enabling may build and launch the app; disabling does not launch a closed app.

Installation of the skill or plugin is a separate onboarding action. Document any session restart/new-session requirement and verify how this existing conversation can discover it. Until discovery is confirmed, the same helper can be explicitly called from the current conversation for a local test. Do not promise hot-loading. [Plugins](https://learn.chatgpt.com/docs/plugins)

No verified public extension currently establishes a persistent switch in Codex's native conversation toolbar. The initial implementation uses conversation commands and the Pet's own menu.

### Identity and control

The current adapter supports local Codex only and keys bindings by exact conversation UUID, validated against session metadata. Extend the key to `(provider, host, conversationID)` before adding other providers or remote hosts. Never choose a conversation by its title, shared working directory, or most recently modified transcript alone.

`CODEX_THREAD_ID` binding has been exercised in the current root conversation. The bridge rejects child-session registration and has synthetic isolation/restoration checks; two simultaneous real root conversations and wider restored-session coverage remain acceptance work. If identity is unavailable, the helper requires `--conversation <exact-uuid>` instead of guessing.

The implemented transport uses atomic control files and acknowledgements under the checkout's ignored `.pm-pet/runtime/` directory. One app owns the local bridge. Native rendering is acknowledged separately from accepting a bridge request. Launch permission may be required by macOS/Codex; the integration does not change sandbox configuration.

Implemented source-helper contract:

| Action | Scope |
| --- | --- |
| `enable` / `disable` / `status` | Current validated conversation when invoked through Codex |
| `enable --conversation <id>` | Explicit local Codex binding outside a conversation |
| `disable --all` | All Pet bindings, only when explicitly requested |
| `report --file <path>` | Structured roadmap and decision updates with current binding generation and increasing sequence |
| `quit` | The app process and all its listeners |

Outside Codex, scoped commands without an identity return an actionable error; they never silently become global commands. Explicit `status --all` and `disable --all` are available. Non-launching commands do not restart a stopped app.

## Native architecture

The implemented shell is one Swift/AppKit application with a menu bar controller and separate compact owl/progress surfaces for each enabled conversation. It reuses the character work inside bundled WKWebView content. Web content loads local resources; a narrow native bridge passes state and known UI actions.

The following are logical responsibilities for the architecture. Registry, conversation state, cached quota, and local control currently live together in the Python bridge; the live quota scheduler remains future work.

| Component | Responsibility |
| --- | --- |
| `PetRegistry` | Binding identity, five-main-Pet capacity, enabled state, display name, theme, position, size, and visibility preferences |
| `ConversationStore` | Roadmap, plan revision, completed items, unread progress, decision state, and child-agent ownership for one conversation |
| `CodexAdapter` | Validated events for registered conversations; expose capability availability and source freshness |
| `QuotaStore` | One shared quota snapshot and refresh scheduler for each validated authentication context |
| `PetWindowController` | Render one conversation and its chicks; handle dragging, scaling, and returning to its exact Codex conversation |
| `ControlBridge` | Helper requests, validation, acknowledgements, idempotency, and installation-aware lifecycle operations |

The adapter and data stores must not depend on animation completion. Pet animations reflect state and never advance progress, approve a decision, or resume execution.

### Data boundaries

- `PetBinding`: binding key, workspace reference, name, color, enabled state, window position, scale, panel/usage visibility, and binding generation.
- Persist whether the initial quota default has been assigned. A newly created binding cannot inherit default-visible quota merely because all previous Pets are hidden or disabled.
- Check capacity atomically with enable; concurrent requests cannot create a sixth main Pet. Child-agent records never count toward the limit.
- `BuildSnapshot`: conversation and turn IDs, plan revision, event sequence, step IDs/statuses, pending decision ID, and confirmed execution state.
- `ChildAgent`: provider child ID plus explicit owning parent/build identity. Automatic child discovery does not enable a separate main Pet.
- `QuotaSnapshot`: adapter authentication context, quota limit ID, observed windows, values, reset times, source timestamp, and last successful refresh.
- Every update has an owner. Reject mismatched owners, older revisions, duplicate completion events, and updates from a previous disable/re-enable generation.
- Reconnecting loads the latest snapshot without replaying every missed celebration.
- Disabling A closes A's watchers and prompts; B remains connected. An account quota reader can remain active for B because its data is account-wide.
- A pending decision stays accessible in the original Codex conversation after disable, quit, or a crash. No lifecycle action automatically approves it.

## Distinguishing multiple Pets

Use five calm accent palettes—sage, sky, lilac, rose, and sand—applied to feather accents/accessories. Retain the owl's readable eyes and face. Persist each selection. When a disabled Pet returns, reuse its saved color if still available; if a newer active Pet has taken that color, assign an unused accent to the returning Pet. Do not recolor other active Pets. Names and short labels remain stable. Manual color customization is a later native-app control.

Color is not the only identifier. The overhead panel and menu entry show the conversation title or a user alias. Same-title conversations receive a disambiguating short label. Pet color does not change because the roadmap changes or the app restarts.

Quota red/orange/green and the decision lantern's yellow remain semantic colors, independent of character theme. Chicks inherit a small parent accent. New Pet windows start at separate positions, keep their user-selected positions, and are clamped after monitor changes.

## Shared quota refresh

Quota is account-wide, not consumption attributed to one Pet. All Pets on the same validated authentication context display the same underlying snapshot and may hide it independently. Do not divide the remaining allowance between conversations.

Today, the shared view is a recorded general `codex` snapshot from bound conversations, labeled with its source and real observation age. Model-specific buckets do not replace it. An optional direct CLI quota probe is implemented, but its account is not verified against Desktop, so it is not connected to automatic Pet refresh. The policies below are the next live-adapter target, not current API polling guarantees.

On initial setup, only the first-ever new binding has quota visible. Subsequent new bindings start with it hidden. Save each binding's preference, including across disable/re-enable; never move the display to another Pet when one is hidden or disabled. A menu entry and per-Pet settings always offer a quota toggle, so users can restore it even when none is visible. Enabling several displays adds views of one snapshot, not quota readers.

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

Current: the owning root conversation, native acknowledgement, and app lifecycle have been checked on this Mac. The local observation path is connected; direct CLI quota is diagnostic only. Complete the remaining multi-conversation and compatibility checks below.

- In two root conversations, obtain distinct validated identities even when the workspace is identical.
- Confirm enable/disable reaches the app through the real Codex permission environment and can be retried without duplicates.
- Test restoration and child-agent context so neither creates the wrong main Pet.
- Verify a quota read path and its account context; label a transcript-only fallback accurately.
- Verify deep-link return to each conversation and integration discovery in the existing chat.

Deliverable: recorded capability results for the developer integration, without claiming whole-build execution control.

### 2. Build the native multi-Pet shell

Current: the native shell, capacity enforcement, per-Pet preferences, and menu controls are implemented. Full-Pet hiding, unread indicators, and broader real multi-window acceptance remain.

- One app process, up to five independently colored/positioned windows, and a menu listing the enabled conversations and capacity.
- Per-conversation enable/disable, panel hiding, full-Pet hiding, scale, and persistence.
- A disabled conversation stays disabled after restart; B remains unchanged when A is disabled.
- Double-click A returns to A and double-click B returns to B.
- At five enabled main Pets, retrying enable for an active Pet succeeds; a sixth enable explains how to disable one first. Verify no implicit eviction, including concurrent enable requests and re-enabling a disabled binding.
- Spawn chicks without consuming main-Pet capacity; keep the parent identity explicit.

Deliverable: a locally launchable application with explicit disconnected states where an adapter is unavailable.

### 3. Connect progress, input, and shared quota

Current: explicit roadmap/question reports, observed root/child activity, stale-report rejection, and cached shared quota are connected. Automatic live account refresh and broader cross-conversation acceptance remain.

- Replace demo controls/data with owner-validated snapshots and a single account scheduler.
- A step completion updates only its Pet; plan changes invalidate affected items and do not invent progress.
- A question in A triggers A's lantern; B continues its own state and animations.
- Verify the actual decision answer before clearing waiting state. Do not treat a request cleanup as an answer.
- Verify that enabling five Pets does not multiply quota requests: active refresh remains one per 60 seconds, idle refresh one per 300 seconds, subject to a verified live adapter.
- Verify only the first new Pet starts with quota visible; manually show a second, hide or disable the first, and confirm preferences persist without automatic transfer.
- Hide every quota display, then restore one through settings or the menu; test all-hidden/disabled polling policies.

Deliverable: real multi-conversation observation, five-Pet capacity checks, and a tested cooperative reporting flow. Whole-build pausing remains a separate capability gate.

### 4. Source installation and future app distribution

Current: local launch/disable/quit/restart have been tested on the development Mac. The source installer provides a user command, an optional skill, explicit update, and owned-file uninstall. The public preview requires local developer tools; it does not ship a prebuilt app.

- Extend installation and lifecycle testing to other Macs and Codex versions.
- Test window restoration after display changes, unavailable data, and stale/late events.
- Prepare signed, notarized packages with immutable version metadata and checksums before advertising binary downloads.
- Keep the historical prototype tag unchanged and publish each future preview under a new version.

### 5. Verify execution control

Current: the adapter explicitly exposes no enforced pause/resume capability. The reporting skill instructs the main agent to coordinate real child states through available runtime tools, but Pet itself cannot certify that all work has stopped.

- Add one child agent to conversation A and keep an independent build running in B.
- Confirm an A decision pauses all of A's actual build tree while leaving B running.
- Distinguish pause requested from confirmed paused; stop new dispatches in that build.
- Answer in A, review affected work, update the plan, and resume only A's tree.
- Test disable/quit/crash while waiting so decisions remain answerable independently of Pet.

Do not replace the co-build goal with a permanently read-only companion. If current Codex integration cannot implement the required decision/control path, present the concrete product tradeoff before expanding scope or promising the feature.
