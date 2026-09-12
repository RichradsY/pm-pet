# PM Pet

A small macOS companion for co-building products with Codex: show progress, surface important decisions, and return to the original conversation.

**Tagged baseline: `0.1.0-prototype.1`. Private development; the five-Pet design is unreleased.**

The current deliverable is an interactive owl prototype. A native app, installer, command-line helper, and live Codex connection have **not** been implemented. There is no installable release yet.

## Explore the prototype

Open `prototypes/pm-pet-multi.html` in a browser for the new five-Pet interaction design. The original single-Pet animation study remains in `prototypes/pm-pet-desktop.html`.

- Five sample conversations have distinct colors and independent progress. Click a named owl to inspect it.
- Only the first Pet shows shared account usage initially. Use **Pet settings** or **Manage pets** to show it on others; hiding it everywhere is remembered.
- **Manage pets** demonstrates enable/disable and the five-Pet limit. A sixth conversation cannot replace an enabled Pet.
- Drag and resize each Pet independently. **Arrange pets** restores accessible starting positions.
- **Needs you**, **Answer received**, and **Subagents** demonstrate only the selected conversation's state. They do not control real agents.

The original single-Pet study also provides:

- **Advance demo** completes an example roadmap step and plays a short spell.
- **Needs you** demonstrates the paused state and yellow lantern.
- Click the owl to hide/show progress, drag to move it, or expand **Appearance** to resize it.
- **Preview subagents** demonstrates chick hatching and departure.

Task progress, quota values, pauses, and navigation are demonstrations. Optional design controls use the host's `Tweak` API when available.

Browser storage, when available, remembers the multi-Pet preview's settings and sample states. The generated preview bundles local sources and requires no network libraries. Rebuild after source changes with `node scripts/build-multi-pet.cjs`; run the state checks with `node --test tests/multi-pet-model.test.cjs`.

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
