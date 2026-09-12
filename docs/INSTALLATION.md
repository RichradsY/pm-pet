# Install PM Pet from source

PM Pet is a macOS source preview. The installer creates a `pm-pet` command that points to your checkout; the native app builds locally when you first enable a conversation. There is no downloadable, Developer ID signed or notarized binary release yet. The local build uses ad hoc signing.

## Requirements

- macOS 13 deployment target. The native app has been tested on macOS 26.6.2 / Apple silicon; older macOS versions and Intel Macs have not been verified.
- Python 3.9 or later, Git, and Apple's command line developer tools with `swiftc` (`xcode-select --install` if needed).
- Codex desktop for the current conversation adapter. Other agents and iOS are not supported by this preview.

Keep the source checkout in a stable location. Moving or deleting it breaks the installed command and skill until you reinstall from its new location.

## Install

```sh
git clone https://github.com/RichradsY/pm-pet.git
cd pm-pet
python3 scripts/setup.py install --with-skill
export PATH="$HOME/.local/bin:$PATH"
pm-pet doctor
```

The default prefix is `~/.local`: the command is `~/.local/bin/pm-pet`, with its ownership manifest at `~/.local/share/pm-pet/install.json`. `--with-skill` explicitly installs the Codex skill at `~/.codex/skills/pm-pet`. Omit it to install only the command.

The installer prints the PATH command for your chosen prefix. It does not change shell startup files. Add the printed PATH line to your own shell configuration if you want it to persist in future terminals.

For explicit locations, including an isolated trial installation:

```sh
python3 scripts/setup.py install \
  --prefix "$HOME/.local" \
  --with-skill \
  --skill-dir "$HOME/.codex/skills/pm-pet"
```

`--skill-dir` is the complete destination directory and requires `--with-skill`. The installed helper points to the exact checkout; no `PM_PET_HOME` setup is required. The installer refuses to replace an existing command, skill directory, or unknown installation. Repeating the same install is harmless; use `pm-pet update` to refresh owned files.

Installation does not build or start the app, enable a conversation, edit Codex configuration, install a Hook, establish Hook trust, or add a login item. Codex may need to restart before a newly installed skill appears.

## Connect a conversation

In a root Codex conversation, ask:

> Use $pm-pet to enable a Pet for this conversation and keep its roadmap updated.

The skill uses the current conversation's verified ID. On first enable, the helper builds `build/PM Pet.app`, starts the companion, and waits for native-window confirmation before reporting success. Local app launch permissions remain under macOS and Codex control.

You can also use the command inside Codex's terminal context:

```sh
pm-pet enable --title "My build"
pm-pet status
```

Outside that context, provide the exact Codex conversation UUID:

```sh
pm-pet enable --conversation YOUR-CONVERSATION-UUID --title "My build"
pm-pet status --conversation YOUR-CONVERSATION-UUID
```

The launcher never guesses a conversation from the current directory or most recent chat. Enabling the same conversation is idempotent; at most five main Pets can be enabled. Child agents do not become separate main Pets.

## Daily commands

| Command | Effect |
| --- | --- |
| `pm-pet status` | Read this conversation's state; never launches the app. |
| `pm-pet status --all` | Inspect all registered Pets. |
| `pm-pet preferences --json '{"quotaVisible":true}'` | Restore the selected Pet's quota display. |
| `pm-pet disable` | Hide this conversation's Pet and stop observing it; retain its preferences. |
| `pm-pet disable --all` | Explicitly disable all Pets. |
| `pm-pet quit` | Ask the owned companion and bridge to quit; retain bindings. |
| `pm-pet start` | Start the companion using its saved bindings. |
| `pm-pet build` | Compile the native app in this checkout; quit first if it is running. |
| `pm-pet doctor` | Check source binding, owned files, Python, Swift, and app status without starting the app. |
| `pm-pet --help` | Show command guidance. |

Per-conversation commands need `CODEX_THREAD_ID` or `--conversation UUID`. Quitting, disabling, or hiding the Pet does not answer a question or stop Codex itself. `executionControl` remains false; the optional Hook is a separate, reviewed setup outside this installer.

The default runtime is `<checkout>/.pm-pet/runtime/`. It contains local bindings, preferences, roadmap/question metadata, and observed quota snapshots, and is ignored by Git. Quota uses actual recorded timestamps and may be stale. The installer does not read credentials or send runtime data elsewhere. See [Local Codex integration](LOCAL-INTEGRATION.md) for report payloads and limitations.

## Update

Use your existing checkout and stop the app before replacing its compiled files:

```sh
cd /path/to/pm-pet
pm-pet quit
git pull --ff-only
pm-pet build
pm-pet update
pm-pet start
```

`pm-pet update` only refreshes the installed command and optional skill from the local checkout. It does not fetch code, rebuild, or restart the app. Review Git's output before proceeding if it reports local changes or a failed update. Restart Codex if necessary to load updated skill instructions.

If you use a release tag, choose the tag explicitly in Git instead of pulling an unrelated branch. Keep the same checkout path. Switching to another checkout or changing the optional skill destination requires uninstalling the old installation first.

Ordinary update errors and Ctrl-C restore the previous installed files. An uncatchable process kill or power loss during replacement is outside this preview's rollback guarantee; do not force-kill the installer. Modified or inconsistent owned files cause later update/uninstall to stop for inspection.

## Uninstall

To stop using one Pet, `pm-pet disable` is enough; `pm-pet quit` closes the companion.

For a clean command/skill removal:

```sh
pm-pet quit
pm-pet uninstall
```

Uninstall removes only files recorded in its ownership manifest, after verifying their contents. It retains the source checkout, locally built app, runtime, and preferences. It does not terminate an already-running app. If an owned file was edited or an unknown file was added to the installed skill, removal stops before deleting the installation; move your changes somewhere safe and restore the expected owned files before retrying.

To also erase this checkout's default runtime and preferences:

```sh
pm-pet quit
pm-pet uninstall --purge-runtime
```

This opt-in deletion is restricted to the fixed checkout's verified `.pm-pet/runtime` directory. It refuses unknown state, symlinks, a recent running heartbeat, or a held native/daemon lock. It never follows a custom runtime argument or removes other conversation data. Custom `--runtime` directories remain yours to manage. The checkout and built app can be removed separately after the app is stopped and the command uninstalled.

If the installed command is not on PATH, use its full path or the source entry point:

```sh
python3 scripts/setup.py uninstall --prefix "$HOME/.local"
```

## Troubleshooting

- **Command not found:** run the PATH line printed by the installer, or use `<prefix>/bin/pm-pet` directly.
- **Swift missing:** install Apple's command line developer tools, then run `pm-pet doctor` again.
- **Skill missing:** check its destination, restart Codex, and verify that the checkout still exists. Installation does not enable conversations automatically.
- **Existing path refused:** preserve that file or directory; choose another prefix/destination or uninstall its recognized existing installation first.
- **Changed owned file refused:** inspect and save your changes. The installer does not overwrite them during update or uninstall.
- **Moved checkout:** use the original checkout to uninstall before moving it. If it is already gone, restore it temporarily to the recorded path to perform verified removal, then install from the new path.
- **Pet shows an old plan:** the main agent must report a reviewed roadmap. The observer can flag a newer request but cannot invent semantic progress.
- **Question still pending:** answer in the original Codex/system/terminal surface and have the main agent review the result. For explicitly optional setup, **Not now** records deferment; it does not approve or install the integration.

Do not disable Gatekeeper or remove quarantine as an installation shortcut. This preview builds from inspectable local source; distributing a signed, notarized app is a separate release step.

## Validation for this source preview

On macOS 26.6.2 / Apple silicon, a clean staged source snapshot was installed into a temporary prefix with a separate optional skill directory, including paths with spaces. The installed command and skill helper passed diagnostics; the native app compiled with the preview version; update and uninstall completed without changing the source checkout. That isolated test did not launch another app or enable a conversation. Native conversation binding and interaction were checked separately on the development Mac.

The release checks include 127 Python tests (27 for source installation) and 57 JavaScript state tests. Other machines, older macOS releases, Intel builds, and a prebuilt distribution remain unverified.
