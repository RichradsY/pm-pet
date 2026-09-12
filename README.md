# PM Pet

A small macOS companion for co-building products with Codex: show progress, surface important decisions, and return to the original conversation.

**Tagged baseline: `0.1.0-prototype.1`. The native developer integration and five-Pet design are unreleased. Development remains private.**

The repository now includes a native macOS app and a local command-line helper. It can bind up to five explicitly selected Codex root conversations, display reported roadmaps and important questions, and observe conversation/child activity. Quota comes from recorded general Codex snapshots with their actual timestamps. Full-build pause/resume and automatic live Desktop quota reads are not connected.

## Try the developer integration

From the owning Codex conversation, on a Mac with Swift command-line developer tools and Python 3:

```sh
python3 scripts/pm-pet.py enable --title "My build"
python3 scripts/pm-pet.py status
```

The first run builds and opens the local app; macOS or Codex may request launch permission. Each Pet requires an exact, verified conversation identity. Only the first new Pet shows shared quota by default; other displays are opt-in. Click an owl for progress, double-click to return to its conversation, and use the menu for size, quota visibility, or disable.

Use `python3 scripts/pm-pet.py disable` for the current Pet or `python3 scripts/pm-pet.py quit` for the app. Neither stops Codex work or answers pending questions. There is no consumer installer or downloadable application release, and the included skill source is not globally installed. See [Local Codex integration](docs/LOCAL-INTEGRATION.md) for setup, reporting, controls, and current limitations.

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

In these browser prototypes, task progress, quota values, pauses, and navigation are demonstrations. Optional design controls use the host's `Tweak` API when available.

Browser storage, when available, remembers the multi-Pet preview's settings and sample states. The generated preview bundles local sources and requires no network libraries. Rebuild after source changes with `node scripts/build-multi-pet.cjs`; run the state checks with `node --test tests/multi-pet-model.test.cjs`.

## Product and development

- [Product specification](docs/PRODUCT.md)
- [Local Codex integration](docs/LOCAL-INTEGRATION.md)
- [Native app development plan](docs/APP-DEVELOPMENT.md)
- [Installation and lifecycle plan](docs/INSTALLATION.md)
- [Version and release workflow](docs/VERSIONING.md)
- [Changelog](CHANGELOG.md)

Tracked source files are the repository source of truth. Keep any conversation preview copy synchronized when editing its prototype.

## Distribution

Development remains private until an explicit decision to make the repository public. Private test releases will require repository access and authenticated downloads. Public one-command installation and a Homebrew cask are planned only after an actual application package exists.

Future end-user installation should use a prebuilt application rather than require a compiler. Installation must not silently change Codex configuration, enable login startup, or approve agent decisions.

No open-source license has been selected yet. Choose the intended license before public distribution.
