# PM Pet

**A small desktop companion for co-building with Codex.**

Keep the plan visible, return to the decisions that need you, and see your available quota—all through a little owl at the corner of your Mac.

![PM Pet: an owl companion with a visual roadmap, a human decision prompt, and sample account quota.](docs/assets/pm-pet-hero.svg)

[Install](#install) · [How it works](#how-it-works) · [Controls](#controls) · [Current limits](#current-limits) · [Contribute](CONTRIBUTING.md)

**Source preview · 0.1.0-alpha.1 · macOS 13+ · Codex Desktop · [MIT](LICENSE)**

## Why PM Pet?

Building with an agent is still a collaboration. You bring the context, priorities, and judgments that determine whether the result fits your needs. PM Pet keeps that collaboration visible without turning your desktop into another dashboard.

- **A roadmap you can glance at.** See completed steps, current work, and what comes next. Collapse the panel into a small row of dots.
- **Human input at meaningful moments.** A yellow lantern draws attention to an important decision. A red reminder points to required information. Answer in the original Codex conversation or input window.
- **A little life on your desktop.** The owl reads while work is underway, casts a spell when a step completes, and gains chicks when child agents appear.
- **Quota within reach.** Optional usage pills show the remaining quota windows your account actually supplies, including weekly-only accounts.
- **One conversation, one Pet.** Enable up to five independent Pets, with different colors, editable names, and their own roadmaps. Two tasks in the same project stay separate.

## How it works

![Co-build loop: clarify the goal, build against a visible roadmap, ask for a consequential human decision, review the answer and continue.](docs/assets/co-build-loop.svg)

1. **Clarify.** Enable PM Pet in a Codex task. The included skill asks Codex to clarify consequential uncertainties before building or delegating.
2. **Build.** Codex reports the roadmap and verified milestones. Pet shows progress; ordinary tool activity alone does not complete a step.
3. **Bring you in.** When an important choice needs your judgment, Codex asks and Pet calls attention to it. For example: “When registration fills up, close it or start a waitlist?”
4. **Review and continue.** After your answer, Codex reviews the impact, updates the plan, and continues. Optional setup can be deferred with **Not now**.

This is a **human-in-the-loop (HITL)** workflow. The skill instructs Codex to stop this build's work before asking and wait for your reply. The Pet keeps the question pending until the reply is correlated and the plan reviewed. **The companion itself does not forcibly suspend every running agent or tool.** See [the feedback mechanism](docs/FEEDBACK-GATE.md) for the distinction and the optional tool guard.

The illustrations above use sample tasks and quota values.

## Install

You need **macOS 13 or later**, **Python 3.9+**, **Git**, Apple's command-line developer tools, and **Codex Desktop with local conversations**. This version builds on your Mac; there is no signed, notarized app download yet. The native interface has been tested on macOS 26.6.2 / Apple silicon. macOS 13 is the deployment target; earlier macOS releases and Intel have not been verified.

If Apple's developer tools are missing, install them with `xcode-select --install`. Then:

```sh
git clone https://github.com/RichradsY/pm-pet.git
cd pm-pet
python3 scripts/setup.py install --with-skill
```

The installer creates `~/.local/bin/pm-pet` and, because you explicitly supplied `--with-skill`, installs the PM Pet skill. Keep this checkout: the installed command uses it. Installation does not enable a conversation, trust hooks, or add a login item. The first enable builds and opens the app.

For another command prefix, installation without the skill, removal, and diagnostics, see the [installation guide](docs/INSTALLATION.md).

### Enable it in Codex

Open the task you want to co-build in. If the newly installed skill is not listed, open a new task. Ask:

> Use $pm-pet to enable a Pet for this conversation, named “My build”. Keep its roadmap updated as we work. Before building, ask me about any unresolved choice that would materially change the product, experience, time, or cost. Wait for my answer at those points, then review the plan and continue.

You can also ask Codex to run this in the owning task:

```sh
~/.local/bin/pm-pet enable --title "My build"
```

A terminal outside Codex needs an explicit `--conversation <exact-uuid>`. A project path or conversation title is not an identity. The [integration guide](docs/LOCAL-INTEGRATION.md) explains direct use and the [report contract](integrations/codex/pm-pet/references/report-contract.md).

### Update or remove

To update a Git checkout installation, quit the app before rebuilding:

```sh
~/.local/bin/pm-pet quit
cd /path/to/pm-pet
git pull --ff-only
~/.local/bin/pm-pet build
~/.local/bin/pm-pet update
~/.local/bin/pm-pet start
```

`update` refreshes the installed command and optional skill from your checkout. It does not fetch Git changes. The commands above rebuild the native app as well.

```sh
~/.local/bin/pm-pet disable       # Stop tracking this conversation
~/.local/bin/pm-pet quit          # Close Pet and its local bridge
~/.local/bin/pm-pet uninstall     # Remove owned installation files
```

Uninstall preserves the checkout and Pet's local data by default. See [removal options](docs/INSTALLATION.md#uninstall) for explicitly removing runtime data. Disabling, quitting, and uninstalling Pet do not answer questions or stop Codex work.

## Controls

| Interaction | Result |
| --- | --- |
| Click the owl | Show or hide its progress panel |
| Double-click the owl | Return to its exact Codex conversation |
| Double-click the Pet name or progress header name | Edit the Pet's display name |
| Drag the owl | Move it on your desktop |
| Click a roadmap dot | Open the full roadmap |
| Pet menu | Rename, resize, restore hidden quota, or disable this Pet |
| **Open Codex to reply** | Return to the conversation to answer |
| **Not now** | Defer an explicitly optional setup step |

Roadmap dots use **green** for completed, **deep green** for current, **gray** for pending, **yellow** for a decision, and **red** for required information. Labels identify the states too. Pet supports 75%–150% size presets and respects reduced motion and reduced transparency.

To rename a Pet, double-click its name or choose **Rename Pet…** from its menu. You can also focus the name and press Enter or F2. Enter or leaving the field saves; Esc cancels. Names must contain 1–100 characters and persist across restarts. Renaming a Pet does not change the Codex conversation's title or identity. If saving fails or cannot be confirmed, the editor keeps your draft and shows a message.

### When Codex stops to ask

When Codex finishes its current turn, the panel says **Turn ended**. An unanswered question stays visible with **This turn has ended. Reply in Codex to continue.** The conversation remains available for your next message. Open the matching conversation and submit your answer on its question card or send it as a normal chat message. Opening the conversation alone does not submit a reply.

A normal chat message first shows **Message received / Awaiting review**. Codex checks which question it answers; unrelated messages leave the question open. A correlated card reply, or an explicitly verified chat answer, advances the question count. Partial answers show which question is still waiting.

After all items are answered, Pet shows **Reply received / Awaiting review** with a calm owl. Codex reviews the answer's effect and updates the roadmap before continuing. The Pet reports message arrival and verified progress separately; receiving a message never means an automatic approval.

### About quota

The display shows **remaining**, shared account quota—not consumption attributable to one Pet. Only the first newly enabled Pet shows it by default; enable extra copies from each Pet's menu.

- Five-hour and weekly windows appear only when supplied. A missing five-hour limit is not displayed as zero.
- Hidden quota can be restored from the menu.
- The **From chat** timestamp tells you when Codex last recorded that snapshot. Repainting does not make it fresh.

The default source is a recorded Codex snapshot, **not a live polling API**. There is no extra model call to calculate the displayed quota.

## Current limits

This is an experimental source preview, intended for people comfortable building a small macOS app.

| Area | Current boundary |
| --- | --- |
| Agent support | Local Codex Desktop conversations. Claude Code, Hermes, and Pi are not connected yet. |
| Roadmap | The owning agent must report meaningful steps and completion. Pet does not infer a finished feature from tokens or elapsed time. |
| Human questions | The observed Desktop async-question format is automatic; other question formats need explicit agent reports. |
| Approvals and passwords | Computer Use approvals and OS password prompts are not detected automatically. Required-information reminders need a known prompt. Enter sensitive information only in its original window. |
| Execution control | Cooperative skill workflow and a persistent report gate. The optional reviewed hook guards supported future calls; it cannot cancel in-flight work. |
| Compatibility | Local transcript formats can change across Codex versions. Unsupported data must remain unavailable rather than be guessed. |
| Distribution | Source installation, local compilation, and ad hoc signing. No notarized binary, Homebrew cask, iOS app, or auto-updater. |

Pet's bridge reads the conversations you explicitly bind and keeps local state in this checkout's ignored `.pm-pet/runtime/` folder. It does not upload those records or copy answer values into Pet state. Question text, conversation IDs, and timestamps are still local data: do not attach that folder to a public issue.

## Explore and contribute

No Mac available? Open [`prototypes/pm-pet-multi.html`](prototypes/pm-pet-multi.html) locally in a browser to explore the five-Pet design. Its tasks, quota, and agent activity are simulated. The original [single-Pet animation study](prototypes/pm-pet-desktop.html) is also included.

- [Contributing and checks](CONTRIBUTING.md)
- [Product specification](docs/PRODUCT.md)
- [Local integration](docs/LOCAL-INTEGRATION.md)
- [Feedback and cancellation](docs/FEEDBACK-GATE.md)
- [Development roadmap](docs/APP-DEVELOPMENT.md)
- [Versioning](docs/VERSIONING.md) · [Changelog](CHANGELOG.md)

## License

[MIT](LICENSE). You can use, modify, and share PM Pet under its license terms. PM Pet is an independent project and is not affiliated with or endorsed by OpenAI.
