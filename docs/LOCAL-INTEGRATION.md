# Local Codex integration

This source preview connects a native macOS Pet to an explicitly selected local Codex conversation. The optional source installer provides a user command and an explicitly requested Codex skill; see [Installation](INSTALLATION.md). It does not register a login item, trust hooks, or upload conversation data. There is no signed/notarized downloadable app yet.

## Start from this checkout

On a Mac with Swift command-line developer tools and Python 3:

```sh
python3 scripts/pm-pet.py enable --title "My build"
```

The first run builds `build/PM Pet.app`, starts its local bridge, validates the current `CODEX_THREAD_ID` against session metadata, and waits for the corresponding native view to acknowledge rendering. Run this from the owning root conversation. From another shell, provide `--conversation <exact-uuid>`; a working directory or conversation title is not a binding.

Runtime preferences, binding metadata, acknowledgements, and minimal state stay under this checkout's ignored `.pm-pet/runtime/`. The bridge observes only registered conversation transcripts. Its automatic quota reader also transiently reads file-based CLI login metadata to verify the account before a direct usage query; see the quota boundary below. The helper can be called by absolute path from another conversation's workspace while retaining the same application/runtime.

After enabling, ask Codex to check current usage once with the Desktop usage-limits tool in that root task. The successful result seeds the account fingerprint required for conditional automatic quota reads. Repeat explicit Pet enable for each new root task you want to follow; starting the app only restores saved, enabled bindings.

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
- Double-click the name beneath the owl or in the progress header to edit the Pet's display name. Enter or leaving the field saves; Esc cancels. Names must contain 1–100 characters. You can also focus the name and press Enter/F2, or choose **Rename Pet…** from its menu. Saving is acknowledged by the local bridge; names persist across restarts and do not rename the Codex conversation.
- With progress hidden, the overhead dots show completed (green), current (deep green), pending (gray), decision (yellow), and required-input (red) states. Click a dot for the full roadmap; `+N` keeps long plans compact. Real completion makes the dots briefly orbit alongside the owl's spell.
- Drag the owl, or use the app menu for size, per-Pet usage display, and disable.
- Up to five main Pets can be enabled. Child agents appear under their parent and do not consume these slots.
- Only the first newly enabled Pet initially shows usage. Explicit visibility choices survive disable/re-enable; usage does not migrate automatically to another Pet.
- Disable stops observing that conversation. Quit stops the native app and its owned bridge. Neither action answers a pending question or stops/resumes Codex work.
- If installed with the source installer, follow [Uninstall](INSTALLATION.md#uninstall) to remove its owned command and optional skill. Quitting alone preserves the source checkout and local preferences.

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
| Account quota | Genuine Desktop checks and general `codex` snapshots, plus direct CLI account reads only after matching the last Desktop check; one shared worker and actual source timestamps; missing 5h remains absent |
| Feedback wait | Persistent question/report gate plus an agent stop-before-asking workflow; optional trusted local-tool hook adds a guard. This observer cannot cancel already-running work |

## Quota sources and automatic refresh

A successful first-class Desktop `get_usage_limits` completion in an enabled root conversation supplies a fresh snapshot and account evidence. The bridge hashes the result's `accountId`; shell output and quoted JSON cannot seed that match. General windows use `rateLimitsByLimitId.codex`, with the legacy general bucket used only when the map is missing/null. Model-specific buckets such as Spark do not replace the general allowance.

The automatic reader uses direct Codex CLI App Server calls, including `account/read` and `account/rateLimits/read`, without a model prompt. Before starting a reader child, it compares a scoped hash of local `auth.json` → `tokens.account_id` with the last genuine Desktop account fingerprint. It pins the child to that verified `CODEX_HOME` and `cli_auth_credentials_store="file"`; it does not change the user's persistent Codex configuration. The account hash and auth-file generation must remain unchanged before and after the read. A replacement or modification, including a token refresh during the read, discards that result.

This establishes **CLI identity matched to the last Desktop account check**, not permanent knowledge of the current Desktop login. The reader does not substitute email, decode tokens, or fall back to keychain-only/unmatched credentials. Ask Codex to check current usage again after an account change or an **Account check needed** status. Pet retains fingerprints and observation metadata, not raw account IDs, tokens, credit balances, auth-file contents, or raw tool responses.

One shared worker serves all visible quota copies. With enabled Pets and at least one visible quota display, a successful read schedules the next check after 60 seconds during confirmed running work, or 300 seconds while idle or awaiting a reply. Running means an observed running turn without a pending question. Requests do not overlap. Hiding every quota display or disabling every Pet stops polling and cancels an in-flight read; progress observation remains separate. There is no Pet manual-refresh button or OS-wake hook.

Transport failures back off and retain the previous value and its observation time. Account mismatch or unavailable authentication metadata makes quota unavailable. A successful read with no supported general windows also clears the display. Successful reads have their actual completion timestamp even when the percentage is unchanged. **Auto**, **Checking**, **Retry**, and **Account check needed** show source or refresh status. After five minutes, an asterisk marks old figures; relative age advances locally without fetching data or pretending the cache is fresh.

An optional live diagnostic is available:

```sh
python3 bridge/quota_reader.py --probe
```

The standalone `--probe` makes direct App Server calls and prints metadata only. It remains an **unverified CLI-account diagnostic**: it does not establish the Desktop match, seed the automatic worker, or prove that its account is the Desktop account. The conditional worker uses the separate verified reader described above.

## Report the real roadmap

The reusable skill source is [PM Pet](../integrations/codex/pm-pet/SKILL.md). Install it explicitly through the [source installer](INSTALLATION.md) to make it discoverable; the source helper also works immediately without installing the skill. Open a new Codex task if a newly installed skill is not discovered in the current one.

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

Codex local transcript formats are not a stable public integration contract. This adapter isolates their parsing so an unsupported format can show unavailable rather than guess. Direct account reads use the [App Server protocol](https://learn.chatgpt.com/docs/app-server); conversation progress still uses the local observation/report path.
