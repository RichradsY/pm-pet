# PM Pet

A small macOS companion for co-building products with Codex: show progress, surface important decisions, and return to the original conversation.

**Version: `0.1.0-prototype.1`. Private development.**

The current deliverable is an interactive owl prototype. A native app, installer, command-line helper, and live Codex connection have **not** been implemented. There is no installable release yet.

## Explore the prototype

Open `prototypes/pm-pet-desktop.html` in a browser, or render the fragment in a compatible inline preview.

- **Advance demo** completes an example roadmap step and plays a short spell.
- **Needs you** demonstrates the paused state and yellow lantern.
- Click the owl to hide/show progress, drag to move it, or expand **Appearance** to resize it.
- **Preview subagents** demonstrates chick hatching and departure.

Task progress, quota values, pauses, and navigation are demonstrations. Optional design controls use the host's `Tweak` API when available.

## Product and development

- [Product specification](docs/PRODUCT.md)
- [Native app development plan](docs/APP-DEVELOPMENT.md)
- [Installation and lifecycle plan](docs/INSTALLATION.md)
- [Version and release workflow](docs/VERSIONING.md)
- [Changelog](CHANGELOG.md)

The tracked prototype is the repository source of truth. Keep any conversation preview copy synchronized when editing it.

## Distribution

Development remains private until an explicit decision to make the repository public. Private test releases will require repository access and authenticated downloads. Public one-command installation and a Homebrew cask are planned only after an actual application package exists.

Future end-user installation should use a prebuilt application rather than require a compiler. Installation must not silently change Codex configuration, enable login startup, or approve agent decisions.

No open-source license has been selected yet. Choose the intended license before public distribution.
