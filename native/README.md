# Native developer shell

This is a local macOS development build, not a notarized distribution. It is a menu-bar AppKit application with bundled WKWebView owl art reused from the existing prototype. All conversation data and preferences come from the local bridge. The UI does not infer a roadmap or claim execution control.

Build with Apple's command-line tools:

```sh
bash native/build.sh
```

The optional first argument is an output `.app` directory. Build caches stay in the repository's ignored `.build/` directory. The generated app is ad hoc signed and targets macOS 13 or later on the build machine's architecture.

The executable takes an explicit runtime directory:

```text
PMPet --runtime /absolute/runtime/directory
PMPet --runtime /absolute/runtime/directory --bridge /absolute/pm_pet_bridge.py --python /absolute/python3
```

The bridge, when provided, is launched as `python3 pm_pet_bridge.py serve --runtime DIR`. The app owns that process and terminates it on normal app exit. No system-wide installation, launch agent, login item, or Codex configuration change is performed by this build script.

## Local interface

- `state.json`: bridge-owned snapshot. The app reads file metadata every 500 ms and parses only changed snapshots. At most five enabled conversations produce owl windows.
- `inbox/<requestId>.json`: atomic UI commands. The app emits `preferences` and `disable`, always with an exact Pet ID. Position uses macOS global screen coordinates; size is an integer percentage from 75 through 150.
- `native-status.json`: app-owned health acknowledgment with `pid`, `runtime`, `appliedRevision`, `enabledIds`, `uiReady`, `running`, `updatedAt`, and `heartbeatAt`. It changes at least once per second while the app is alive. A Pet appears in `enabledIds` only after both of its bundled views have applied the current snapshot. `uiReady` is true only after all enabled views have rendered.
- `quit-request.json`: a fresh request containing a UUID `requestId` and the current native `pid`. The app accepts requests written within the last 30 seconds, exits through AppKit, and acknowledges `quitRequestId` with `uiReady: false` before stopping its bridge child.
- `native.lock`: advisory lock preventing two app instances from owning the same runtime.
- `bridge.log`: stderr from the owned bridge process. It contains no deliberate transcript logging in the native shell.

The compact owl window contains its conversation name and optional account quota. Its progress panel is a separate compact window, shown above the owl by default and moved below when screen bounds require it. Transparent desktop-sized windows are not used. Click shows or hides the panel; drag moves the Pet; double-click opens a validated conversation UUID through the Codex deep link. Right-click or the menu-bar menu restores usage, changes size, disables a Pet, or quits the app.

Double-clicking the name (beneath the owl or in the progress header) opens an inline editor in the owl window. Enter or blur saves, Esc cancels, and the **Rename Pet…** menu item provides another entry point. The editor keeps its draft during state refreshes and IME composition, validates 1–100 Unicode code points, and waits for the exact bridge request acknowledgement before closing. A failed or unconfirmed save keeps the draft available. Only the Pet's persisted display name changes; its conversation UUID and Codex title remain separate.

Before allowing a retry after a save timeout, the native app removes its exact queued request or confirms that file is absent. Other removal errors leave the save pending. The bridge's single-consumer lock and serial inbox processing ensure a previously read request completes before a retry is processed, so an old name cannot overwrite a newer retry. The UI still calls a timed-out save **unconfirmed**, since removing the request cannot prove whether it was already applied.

No quota values or progress metrics are seeded by the native UI. Missing five-hour quota remains absent. Missing quota is shown as unavailable when its display is enabled. Quota retains its actual observation timestamp and shows its source and relative age outside the glass pill. Values older than five minutes are marked cached with an asterisk; aging runs locally while visible and does not fetch data. A completed Desktop account-usage query can provide a newer snapshot through the bridge.

The owl silhouette has no pale outer stroke or full-window backing. Rounded `NSVisualEffectView` islands sit below transparent WebKit only where the name, quota, attention badge, or progress panel is visible. The renderer reports bounded local rectangles with `glassRegions`; those messages never reach the conversation bridge. Materials follow the system appearance, with an opaque system-color fallback when Reduce Transparency is enabled.

The owl surface reserves a fixed 24-point top band (`topInset`) for the collapsed roadmap. Dots remain legible when the owl scales, and at most seven focus steps plus overflow counts are shown. Opening progress hides the dots; explicit input and decision reports select red/yellow reminders. The native shell never opens or inspects password fields. Its only navigation action remains the validated Codex conversation link.
