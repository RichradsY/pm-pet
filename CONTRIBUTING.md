# Contributing to PM Pet

PM Pet is an early macOS companion for co-building with Codex. Small, reproducible improvements to the interaction, integration, and installation experience are welcome.

## Development

Use macOS 13 or later, Python 3.9 or later, and Apple's command-line developer tools. Node.js is needed for the browser state tests and prototype build, not to run the native app.

```sh
python3 -m unittest discover -s bridge/tests
node --test tests/native-pet-state.test.cjs tests/multi-pet-model.test.cjs
bash native/build.sh
```

See [installation](docs/INSTALLATION.md) for setting up the command and optional Codex skill, and [local integration](docs/LOCAL-INTEGRATION.md) for reporting a roadmap. Use synthetic conversations for automated tests. Only enable a real Pet in a conversation you intend to track.

## Pull requests

Describe the user-visible problem, the resulting behavior, and how you verified it. Keep changes focused. Include a screenshot or short recording when changing the interface, using sample tasks and quota values.

Preserve these product boundaries:

- Progress means verified delivery items, rather than time or tokens consumed.
- Important questions and answers belong in the original Codex conversation.
- A reminder, a report gate, and actual execution control are different capabilities.
- Missing quota windows stay absent; cached observations retain their timestamp.
- Each Pet belongs to its exact conversation, including when two conversations share a project.
- Installation and removal affect only PM Pet's own files. They do not grant tool approvals or delete Codex conversations.

Do not commit runtime state, credentials, real question replies, private conversation IDs, personal paths, generated app bundles, or signing material. `.pm-pet/` and build outputs are intentionally ignored. Run `git diff --check` before opening a pull request.

Contributions are made under the project's [MIT License](LICENSE).
