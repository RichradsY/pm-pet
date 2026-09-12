#!/usr/bin/env python3
"""Print a reviewable project hooks configuration; never install or trust it."""
import argparse
import json
import os
from pathlib import Path
import shlex
import sys


def configuration(home, runtime, python):
    command = shlex.join([str(python), str(home / "integrations/codex/pm-pet/hooks/pm_pet_gate.py"),
                          "--home", str(home), "--runtime", str(runtime)])
    handler = {"type": "command", "command": command, "timeout": 5,
               "statusMessage": "Checking PM Pet feedback gate"}
    return {"description": "Project PM Pet guard: review and trust this exact command in Codex.",
            "hooks": {"PreToolUse": [{"matcher": ".*", "hooks": [handler]}],
                      "UserPromptSubmit": [{"hooks": [dict(handler, additionalContextLimit=500)]}]}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--home", type=Path, default=Path(os.environ.get("PM_PET_HOME", Path(__file__).resolve().parents[4])))
    parser.add_argument("--runtime", type=Path)
    args = parser.parse_args()
    home = args.home.expanduser().resolve()
    runtime = (args.runtime or home / ".pm-pet" / "runtime").expanduser().resolve()
    # Keep the installed interpreter symlink stable across package-manager updates.
    print(json.dumps(configuration(home, runtime, Path(sys.executable).absolute()), indent=2))


if __name__ == "__main__":
    main()
