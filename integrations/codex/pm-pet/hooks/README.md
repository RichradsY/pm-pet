# Optional project feedback guard

Developer integration, not globally installed. `pm_pet_gate.py` reads the selected PM Pet runtime and returns a synchronous Codex `PreToolUse` decision. It never executes tool input, modifies runtime state, reads answer text, or installs/trusts hooks.

For the exact enabled `session_id`, a nonempty `question` or `pendingQuestions` blocks new supported tools, including an `awaiting_review` question. Codex documents that child hooks receive their parent session ID. The working directory, title, and child transcript filename are not identities. Disabled or unregistered IDs in valid state are unaffected.

An enabled Pet with a missing/stale bridge heartbeat also blocks new work. Missing, corrupt, or unsupported configured state returns an explicit denial because the guard cannot establish which bindings are enabled. It does not silently release after an elapsed time. Status and child-stop controls remain available; fix a broken runtime from the app or a normal terminal. Initialize PM Pet before trusting this hook.

## Prepare and review

From the PM Pet checkout:

```sh
python3 integrations/codex/pm-pet/hooks/render_config.py > /tmp/pm-pet-hooks.review.json
```

The generator prints JSON with absolute, shell-quoted Python, script, checkout, and runtime paths, including paths with spaces or apostrophes. It writes nothing itself. `PM_PET_HOME` can identify a stable source checkout; explicit `--home /absolute/checkout` and `--runtime /absolute/runtime` override defaults. Without these, the source checkout and its `.pm-pet/runtime` are used. Moving that checkout requires regenerating and reviewing the definition.

1. Inspect the generated file and scripts. `hooks.sample.json` is illustrative, not a ready-to-run installation.
2. Merge the generated `PreToolUse` and `UserPromptSubmit` groups into the target project's `.codex/hooks.json`, preserving existing hooks. Do not install into user/global configuration by default.
3. In Codex's **Hooks** settings, **Reload hooks**, review the exact command, then **Trust** it. Project trust and hook trust are distinct. Never write `trusted_hash` or bypass review.
4. Verify the current task actually runs the hook. Current local Desktop code requests runtime hot reload when trusting hooks, so restarting the task may not be necessary; a configuration file alone does not establish live coverage.

The generated matcher is `.*` and the command is synchronous (no `async`). Its five-second host execution limit is not a waiting period and cannot release a pending question. If the script cannot start, crashes, or exceeds the host limit, Codex may report a hook failure rather than apply this script's denial. Treat that as an integration failure, not a successful gate.

## Controls allowed while gated

The guard returns no permission override for these controls; Codex's usual approvals still apply:

- `interrupt_agent`, `list_agents`, `wait_agent` (also their `collaboration.` names), with their narrow expected arguments. These are for stopping/checking the current build's actual children, not resuming or creating work. A wait is capped at 60 seconds and never releases the gate.
- One literal `python3 /absolute/checkout/scripts/pm-pet.py status --conversation UUID` command.
- The same launcher with `report --conversation UUID --json '…'`, or `--file /absolute/existing/report.json`. Resolution requires the current question ID, current integer generation, a newer integer sequence, the full `steps`, and `currentStep`. The bridge validates the report and correlated replies; the hook does not resolve a question itself.

`--conversation` must explicitly match the hook's root session ID. If the hook targets a custom runtime, include the identical `--runtime /absolute/runtime`. Paths must identify the actual configured launcher. `python3`, `/usr/bin/python3`, and the hook's own Python interpreter are recognized. Known shell envelopes are `Bash` / `tool_input.command` and `exec_command` or `functions.exec_command` / `tool_input.cmd`.

No shell chaining, redirection, environment assignments, dynamic substitution, Python `-c`, wrapper scripts, relative launcher paths, or management commands such as `disable`/`quit` are allowed as controls. Use a single-quoted JSON argument or serialize arguments with `shlex.join`; escaped JSON `\n` is supported, literal multiline shell commands are not. Inline JSON avoids needing to edit a report file while gated. The source skill wrapper is not an allowed control path; use the fixed launcher directly.

`UserPromptSubmit` only adds a short state reminder. It neither stores the prompt nor marks answers received. New messages, timeout, app exit, and silence cannot release the wait.

## Coverage and acceptance

This hook guards **already registered pending questions**. It does not automatically register an async question: the transcript observer has a polling interval. Stop children and owned commands before asking; explicitly report the question first when needed, or wait for the observer to persist it. An absent reminder during this interval is not permission to continue building.

Per the official [Hooks documentation](https://learn.chatgpt.com/docs/hooks), covered new local calls include shell, patches, MCP, delegation, and nested local calls from code mode. Already-running commands, later `write_stdin` input, hosted tools, and specialized opt-out paths remain outside this guard. It is not a tamper-resistant supervisor or a promise that every agent/process is frozen. Keep `executionControl: false`.

Before calling the integration active, verify in the existing task that a harmless covered tool runs with no pending question; a registered pending question denies a harmless build attempt before effects; status still works; a matching user reply alone remains gated; and only an acknowledged full roadmap review permits work when no queued question remains. Inspect actual hook events/results. Do not infer success from the Pet animation. Live trust and this acceptance test are separate from offline tests.

Offline synthetic checks:

```sh
python3 -m unittest discover -s bridge/tests -p test_gate_hook.py -v
```

To remove the integration, remove only these groups from the project's hook config and reload in Codex, or disable the hooks in its settings. Disabling a hook does not answer a product question or clear Pet state.
