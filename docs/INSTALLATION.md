# Installation and distribution plan

Status: proposed. There is no native app, installer, CLI, or downloadable application release yet.

## Private development

Keep the repository and its releases private during development. Testers must have repository access and authenticate with their own GitHub account. Do not embed access tokens in scripts or URLs.

Ship prebuilt application archives through GitHub Releases. End users should not need Xcode, Swift, Node.js, or a local source build. Publish only architectures and macOS versions that have been built and tested.

The intended private bootstrap uses GitHub CLI authentication and a pinned prerelease tag. A future installer will download through `gh release download`, verify the release manifest and archive checksum, and install the app and its command-line helper. Do not advertise anonymous `curl` downloads for private releases.

GitHub CLI provides authenticated release asset downloads; each tester needs access to the private repository. [Release download command](https://cli.github.com/manual/gh_release_download)

## Public distribution

Changing repository visibility requires an explicit release decision. Audit tracked files and Git history before that change; deleting a private file in a later commit does not remove it from history. Select a license before public distribution rather than silently choosing one now.

Once a signed, notarized app and tested installer exist, offer a one-command installer backed by GitHub Release assets. Resolve the release once and download all files from that exact version so a concurrent release cannot mix an installer, checksum, and archive. [GitHub release links](https://docs.github.com/en/repositories/releasing-projects-on-github/linking-to-releases)

For existing Homebrew users, a custom tap can later install the same prebuilt app via a cask. Homebrew supports fully qualified `brew install --cask owner/tap/cask` installation. This is a proposed second channel, not an existing package. [Homebrew taps](https://docs.brew.sh/Tap-Trust)

Command-line installation does not replace application signing and notarization. Do not remove quarantine attributes or disable Gatekeeper as part of installation. [Apple Developer ID](https://developer.apple.com/developer-id/)

## Installer behavior

- Script-managed installs target `~/Applications/PM Pet.app` and a helper under `~/.local/bin`; do not require administrator access by default.
- Check the installed app's ownership and identity before updating it. Never overwrite an unrelated app or command with the same name.
- If the helper directory is missing from PATH, show its full command path and setup instructions; do not silently rewrite shell startup files.
- Preserve preferences and project bindings on upgrade. Stage and validate the replacement before switching; retain the working version if any step fails.
- Record the installation channel, version, and owned file paths. Homebrew-managed installs are upgraded and removed through Homebrew; the script must not overwrite them.
- Do not add login items, modify Codex configuration, or enable project integration merely because the app was installed.
- Default uninstall removes only owned application files and helpers. Explicit data removal can also clear Pet preferences and caches; it never removes Codex conversations or project code.
- Installation does not enable any conversation. An installed conversation skill/helper enables individual Pets explicitly; verify integration discovery and any session restart requirements.

## Proposed CLI contract

These commands are not implemented or available on PATH yet.

| Command | Intended behavior |
| --- | --- |
| `pm-pet start` | Open the app and binding interface |
| `pm-pet status` | Show the validated current conversation's binding and tracking state, plus app version/channel |
| `pm-pet disable` | Stop tracking and prompts for the validated current conversation; preserve its disabled preference |
| `pm-pet enable` | Enable the validated current conversation; reuse its existing Pet and never approve pending decisions |
| `pm-pet disable --all` | Explicitly stop tracking for every Pet |
| `pm-pet quit` | Stop all Pet processes and listeners |
| `pm-pet update` | Upgrade a script-managed install; identify the proper command for other channels |
| `pm-pet uninstall` | Remove a script-managed install using its ownership manifest |
| `pm-pet uninstall --purge` | Also remove explicitly listed Pet-owned data |

The menu bar must provide the same lifecycle controls. Disabling or uninstalling Pet does not automatically answer a question or resume a paused build.

Outside Codex, require an explicit conversation identity or a user selection. Do not infer it from the current directory and do not treat a missing identity as a request to control all Pets. See [Native app development plan](APP-DEVELOPMENT.md).
