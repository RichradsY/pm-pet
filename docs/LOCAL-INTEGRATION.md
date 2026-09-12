# Local Codex integration

This developer build connects a native macOS Pet to an explicitly selected local Codex conversation. It does not install globally, change Codex settings, register a login item, or upload conversation data. The repository remains private. There is no signed/notarized downloadable release yet.

## Start from this checkout

On a Mac with Swift command-line developer tools and Python 3:

```sh
python3 scripts/pm-pet.py enable --title "My build"
```

The first run builds `build/PM Pet.app`, starts its local bridge, validates the current `CODEX_THREAD_ID` against session metadata, and waits for the corresponding native view to acknowledge rendering. Run this from the owning root conversation. From another shell, provide `--conversation <exact-uuid>`; a working directory or conversation title is not a binding.

Runtime preferences, binding metadata, acknowledgements, and minimal state stay under this checkout's ignored `.pm-pet/runtime/`. The app reads only registered conversation transcripts through its bridge. It does not read authentication files. The helper can be called by absolute path from another conversation's workspace while retaining the same application/runtime.

The operating system may require permission to launch the app from an agent sandbox. This is separate from changing the Codex sandbox configuration. After the app starts, helper commands use scoped local files and acknowledgements; they do not need process-list access.

## Controls

```sh
python3 scripts/pm-pet.py status
python3 scripts/pm-pet.py status --all
python3 scripts/pm-pet.py disable
python3 scripts/pm-pet.py enable
python3 scripts/pm-pet.py quit
python3 scripts/pm-pet.py doctor
```

- Click the owl to show/hide progress. Double-click or use its menu to return to the exact Codex conversation.
- With progress hidden, the overhead dots show completed (green), current (deep green), pending (gray), decision (yellow), and required-input (red) states. Click a dot for the full roadmap; `+N` keeps long plans compact. Real completion makes the dots briefly orbit alongside the owl's spell.
- Drag the owl, or use the app menu for size, per-Pet usage display, and disable.
- Up to five main Pets can be enabled. Child agents appear under their parent and do not consume these slots.
- Only the first newly enabled Pet initially shows usage. Explicit visibility choices survive disable/re-enable; usage does not migrate automatically to another Pet.
- Disable stops observing that conversation. Quit stops the native app and its owned bridge. Neither action answers a pending question or stops/resumes Codex work.
- There is no global installation to uninstall at this stage. Quit the app to disable the running integration; source files and local preferences remain in this checkout.

## What is connected

| Data or action | Developer build behavior |
| --- | --- |
| Conversation ownership | Exact UUID plus validated session metadata; child sessions cannot create main Pets |
| Run/turn activity | Read from that conversation's structured local events |
| Roadmap and completion | Main-agent reports; a newly observed user request marks the previous roadmap as awaiting review until a full plan report arrives |
| Important question | Observed Desktop async input-tool calls are queued automatically; other question formats use explicit main-agent reports. Answers stay in Codex |
| Required information | Explicit red input reminder with its original Codex/system/terminal destination; no password field or automatic OS-prompt detection |
| Question resolution | Automatic questions require matching replies to every item, then main-agent resolution with a full reviewed roadmap; explicit prompts require owner verification and matching resolution ID |
| Child activity | Observed start/completion events; repeated interaction alone is not proof of a resumed child |
| Account quota | Recorded general `codex` snapshot from a bound conversation, with source timestamp; missing 5h remains absent |
| Feedback wait | Persistent question/report gate plus an agent stop-before-asking workflow; optional trusted local-tool hook adds a guard. This observer cannot cancel already-running work |

The default quota source is a cached observation. Reading the transcript again does not make the quota fresh. General account windows are kept separate from model-specific quota buckets.

An optional live diagnostic is available:

```sh
python3 bridge/quota_reader.py --probe
```

It makes direct App Server calls without a model prompt and prints metadata only. Live reads were verified for the local CLI account, but that account cannot yet be reliably matched to the Desktop account from the available fields. Therefore this reader is not enabled as the Pet's automatic quota source. The proposed shared 60-second active / 5-minute idle refresh policy applies once that account binding is verified. No API polling is currently advertised as live Desktop usage.

## Report the real roadmap

The reusable developer skill source is [PM Pet](../integrations/codex/pm-pet/SKILL.md). It has not been installed into a global or project skill directory. Existing conversations can explicitly call the local helper immediately; skill discovery in a newly configured Codex session is a separate step.

Read `status`, write a payload using that Pet's generation and next sequence, then run:

```sh
python3 scripts/pm-pet.py report --file /absolute/path/report.json
```

The [report contract](../integrations/codex/pm-pet/references/report-contract.md) defines the fields. Only verified completion changes `done`; ordinary transcript activity never advances a roadmap item. Follow the [feedback gate](FEEDBACK-GATE.md): stop the same build's work before asking, wait for the actual answer, review its impact, and resolve the pending question before resuming. The current observer cannot independently certify that every agent has stopped.

## Validation and limits

```sh
python3 -m unittest discover -s bridge/tests -v
node --test tests/multi-pet-model.test.cjs
bash native/build.sh
```

The native view is bundled locally and tested separately from the original browser design. The owl has a transparent silhouette; compact native glass surfaces hold its name, quota, and progress. Reduce Transparency uses an opaque system-color fallback. Planning, building, and checking show the reading animation. Integration was checked on this development Mac; distribution to other machines, two simultaneous real root conversations, skill hot-loading, restart behavior across Codex upgrades, and hard pause/resume require further validation before a consumer alpha release.

Codex local transcript formats are not a stable public integration contract. This adapter isolates their parsing so an unsupported format can show unavailable rather than guess. See the official [App Server protocol](https://learn.chatgpt.com/docs/app-server) for the future direct event/account transport.
