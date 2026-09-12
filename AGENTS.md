# Working on PM Pet

PM Pet is a small macOS companion for co-building with Codex. Keep its UI quiet, default to English, and preserve the distinction between observed activity, reported delivery progress, and actual execution control. Do not infer roadmap completion from time or token usage, or claim a pending question has stopped agents without confirmed control.

## Dogfood the enabled Pet

When working as the owning main agent in this checkout, read `python3 scripts/pm-pet.py status` at the start of a user request. This read does not launch the app. If the current conversation has an enabled Pet, follow [the reporting workflow](integrations/codex/pm-pet/SKILL.md) and [report contract](integrations/codex/pm-pet/references/report-contract.md):

- Review new scope and report the full revised roadmap, current step, and working phase before implementation.
- Update the report when a deliverable is verified, a material user decision is needed, or the work ends.
- Keep payloads and real conversation data in ignored `.pm-pet/runtime/` files.
- If the app is stopped or this conversation is not enabled, continue the task without launching or enabling it automatically.

Child agents send findings to their parent and do not register main Pets or write the parent's overall roadmap. This rule applies only to this repository's development; it does not install a global Codex skill or enable other conversations.
