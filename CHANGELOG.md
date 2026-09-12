# Changelog

## Unreleased

- Retain bounded reply metadata when replies arrive before their question shard, accept exact reply envelopes alongside other message blocks, and shorten shard discovery while waiting.
- Acknowledge ordinary chat feedback without automatically treating it as an answer. Add scoped main-agent reconciliation, multi-question reply counts, and calm review states so users can see their input arrive before the roadmap changes.

- Clarify waiting for a reply versus a finished Codex turn. Show where to submit an answer and distinguish a received reply awaiting review from a new request for input.

## 0.1.0-alpha.1 — 2026-09-12

First public source preview. Builds locally on macOS; no signed, notarized application download is provided.

- Added the MIT License, visual README, co-build/HITL guidance, and source installation documentation.
- Added an owned user command and optional Codex skill setup, explicit update and uninstall, and isolated lifecycle checks.

- Recover explicitly cancelled or deferred questions without manufacturing answers or permissions. Optional setup offers Not now with scoped acknowledgments, retryable failures, and restart-safe cancellation history; ordinary product decisions remain gated. Slow acknowledgments stay unconfirmed, and new question calls share a serialized payload budget with explicit overflow reminders.

- Automatically mirror observed Codex Desktop async question calls, preserve pending questions across restart, and require correlated replies plus a reviewed full roadmap before resolution. Show Reviewing reply without advancing progress; queue separate questions and support atomic question handoff.
- Added a stop-before-asking agent workflow and an optional project-local PreToolUse feedback guard. The hook needs explicit Codex trust and live validation; it does not cancel in-flight work or establish full runtime pause control.
- Keep pending questions and their reply action above progress and long roadmaps. New question IDs reset the panel to the top; ordinary refreshes preserve reading position. Long question text and expanded roadmaps scroll independently while the reply action stays visible.
- Added a compact overhead roadmap with semantic state dots, current-step focus, overflow counts, and completion-synchronized orbit animation. Prompts remain visible even after a completed roadmap.
- Added red required-information reminders alongside yellow decisions, linked to an optional pending step and original input destination. System password detection remains unavailable; input reminders require explicit agent reports.
- Remove the owl's pale outer halo and use rounded native glass for compact controls, with a Reduce Transparency fallback. Quota freshness remains a small unboxed line below its compact pill.
- Detect new root user requests, mark the previous roadmap for review, and require a full plan report before showing its updated percentage; show reading during planning, building, and checking.

- Added an interactive five-conversation design prototype with separate colors, progress, decision prompts, dragging, size, and remembered visibility settings.
- Account quota appears on the first Pet by default; additional copies are opt-in and hiding the default never moves it elsewhere. The preview demonstrates a shared refresh policy without making network requests.
- Added capacity handling, per-conversation enable/disable, arrangement recovery, and a dependency-free state model with isolation and persistence checks.
- Added a native macOS developer app with up to five explicitly bound local Codex root conversations, separate floating owl/progress surfaces, and a menu for per-Pet size, quota visibility, disable, and quit.
- Added a source-checkout launcher and acknowledged local bridge for enable, status, preferences, structured reports, disable, and quit. Native launch and lifecycle were checked on the development Mac; no global installation or Codex configuration changes are performed.
- Connected observed root/child activity and explicit roadmap/decision reports. Binding generation, increasing report sequence, and matching question IDs reject stale updates. Chicks retain their own lifecycle identity across animation interruptions.
- Added shared cached general Codex quota with source freshness and weekly-only handling; model-specific buckets cannot replace the general allowance. An optional live CLI-account diagnostic is separate from Pet's default source because its Desktop account binding is unverified.
- Added reusable Codex skill source and local integration documentation. The skill now has an explicit source-install path; prebuilt consumer packaging, automatic live Desktop quota refresh, and enforced whole-build pause/resume remain future work.
- Plan updated to one explicitly enabled Pet per conversation, including independent Pets in a shared project.
- Defined conversation-based enable/disable, persistent character colors, parent-owned chicks, and independent build pause scopes.
- Specified shared account quota refresh defaults and a staged implementation/acceptance plan; proposed refresh intervals are not current API polling guarantees.

## 0.1.0-prototype.1 — 2026-09-12

Initial versioned interaction prototype. This is not an installable application release.

- Draggable owl with an overhead, hideable progress panel and 75%–150% sizing.
- Roadmap completion counts, current step, plan revisions, and unread progress feedback.
- Reading and page turning while building; a brief spell on completed steps; a yellow lantern when input is needed.
- Subagent chick hatching and departure demonstrations.
- Optional quota windows, independent hiding/restoration, and remaining-percentage colors.
- English and Chinese interface options and reduced-motion alternatives.
- Local browser checks for progress, animation interruption, quota display, keyboard interaction, and narrow layouts.

All task, quota, pause, and navigation behavior in this version uses demonstration data.
