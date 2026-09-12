#!/usr/bin/env python3
"""Read-only synchronous PreToolUse guard; never executes tool input or edits state."""
import argparse
import json
import math
import os
from pathlib import Path
import shlex
import stat
import sys
import time
import uuid

MAX_INPUT = 256 * 1024
MAX_STATE = 4 * 1024 * 1024
HEARTBEAT_MAX_AGE = 10


class GateError(ValueError):
    pass


def read_object(path, limit=MAX_STATE):
    if not stat.S_ISREG(path.stat().st_mode):
        raise GateError("Expected a regular JSON file: " + str(path))
    with path.open("rb") as handle:
        raw = handle.read(limit + 1)
    if len(raw) > limit:
        raise GateError("JSON file exceeds the guard size limit: " + str(path))
    result = json.loads(raw)
    if not isinstance(result, dict):
        raise GateError("Expected a JSON object: " + str(path))
    return result


def exact_id(value):
    if not isinstance(value, str) or str(uuid.UUID(value)) != value.lower():
        raise GateError("Missing or invalid exact Codex session_id.")
    return value.lower()


def literal_argv(command):
    """Accept one literal shell command, including quoted JSON, but no expansions.

    This deliberately supports less syntax than a shell. Nothing is evaluated.
    Single quotes may contain punctuation; double quotes cannot expand variables.
    """
    if not isinstance(command, str) or len(command) > MAX_INPUT:
        raise GateError("Expected a bounded literal command.")
    quote, index = None, 0
    while index < len(command):
        char = command[index]
        if char in "\n\r\x00":
            raise GateError("Multiline commands are not control commands.")
        if quote == "'":
            if char == "'":
                quote = None
        elif char == "\\":
            index += 1
            if index >= len(command) or command[index] in "\n\r\x00":
                raise GateError("Invalid command escape.")
        elif quote == '"':
            if char == '"':
                quote = None
            elif char in "$`!":
                raise GateError("Shell expansion is not a control command.")
        elif char in "'\"":
            quote = char
        elif char in ";&|<>(){}[]*?~$`#!":
            raise GateError("Shell operators and expansions are not control commands.")
        index += 1
    if quote:
        raise GateError("Unclosed command quote.")
    return shlex.split(command, comments=False, posix=True)


def control_command(event, home, runtime, session_id, pet):
    name, values = event.get("tool_name"), event.get("tool_input")
    if not isinstance(values, dict):
        return False
    for prefix in ("", "collaboration."):
        if name == prefix + "list_agents":
            return set(values) <= {"path_prefix"} and all(isinstance(v, str) for v in values.values())
        if name == prefix + "interrupt_agent":
            return set(values) == {"target"} and isinstance(values["target"], str) and bool(values["target"])
        if name == prefix + "wait_agent":
            return set(values) <= {"timeout_ms"} and (not values or type(values["timeout_ms"]) is int and 0 <= values["timeout_ms"] <= 60000)
    command_key = {"Bash": "command", "exec_command": "cmd", "functions.exec_command": "cmd"}.get(name)
    if not command_key or values.get("shell") not in (None, "/bin/bash", "/bin/zsh", "/bin/sh"):
        return False
    try:
        args = literal_argv(values.get(command_key))
        interpreters = {"python3", "/usr/bin/python3", sys.executable}
        if len(args) < 3 or args[0] not in interpreters:
            return False
        # Only the actual launcher, not a same-named helper in another checkout.
        if not Path(args[1]).is_absolute() or Path(args[1]).resolve() != home / "scripts" / "pm-pet.py":
            return False
        action = args[2]
        if action not in {"status", "report"}:
            return False
        options = {}
        for index in range(3, len(args), 2):
            key = args[index]
            if index + 1 >= len(args) or key not in {"--runtime", "--conversation", "--json", "--file", "--json-file"} or key in options:
                return False
            options[key] = args[index + 1]
        if exact_id(options.get("--conversation")) != session_id:
            return False
        if "--runtime" in options and not Path(options["--runtime"]).is_absolute():
            return False
        target_runtime = Path(options["--runtime"]).resolve() if "--runtime" in options else home / ".pm-pet" / "runtime"
        if target_runtime != runtime:
            return False
        payload_keys = set(options) & {"--json", "--file", "--json-file"}
        if action == "status":
            return not payload_keys
        if not pet or len(payload_keys) != 1:
            return False
        key = next(iter(payload_keys))
        if key == "--json":
            report = json.loads(options[key])
        else:
            path = Path(options[key])
            if not path.is_absolute():
                return False
            report = read_object(path, MAX_INPUT)
        question = pet.get("question") or next(iter(pet.get("pendingQuestions", [])), None)
        if not isinstance(report, dict) or not isinstance(question, dict):
            return False
        # The bridge validates and acknowledges recovery; this read-only hook
        # must not prevent an explicitly requested cancellation from reaching it.
        current = (bool(question.get("id")) and type(report.get("generation")) is int
                and report["generation"] == pet.get("generation")
                and type(report.get("sequence")) is int
                and report["sequence"] > pet.get("lastReportSequence", -1))
        if not current:
            return False
        classification = report.get("classifyQuestion")
        if (current and isinstance(classification, dict)
                and classification == {"id": question["id"], "purpose": "setup", "optional": True}
                and set(report) <= {"generation", "sequence", "classifyQuestion"}):
            return True  # Metadata only: cannot answer or release the wait.
        resolving = "resolveQuestionId" in report
        cancelling = "cancelQuestionId" in report
        if resolving == cancelling:
            return False
        action_valid = report.get("resolveQuestionId") == question["id"] if resolving else (
            report.get("cancelQuestionId") == question["id"]
            and report.get("cancellationReason") in {"setup_deferred", "user_cancelled", "superseded"}
            and bool(pet.get("requestMessageId"))
            and report.get("sourceUserMessageId") == pet.get("requestMessageId"))
        return (current and action_valid and isinstance(report.get("steps"), list)
                and isinstance(report.get("currentStep"), str)
                and bool(report["currentStep"].strip()))
    except (OSError, ValueError, TypeError):
        return False


def pending_pet(runtime, session_id, now):
    state = read_object(runtime / "state.json")
    if state.get("schemaVersion") != 1 or not isinstance(state.get("pets"), list):
        raise GateError("Unsupported PM Pet state schema.")
    identities = set()
    pet = None
    for candidate in state["pets"]:
        if not isinstance(candidate, dict) or type(candidate.get("enabled")) is not bool:
            raise GateError("Invalid Pet binding in runtime state.")
        identity = exact_id(candidate.get("id"))
        if identity in identities:
            raise GateError("Duplicate Pet identity in runtime state.")
        identities.add(identity)
        if identity == session_id and candidate["enabled"]:
            pet = candidate
    if pet is None:
        return None, None
    if pet.get("question") is not None:
        if not isinstance(pet["question"], dict) or not isinstance(pet["question"].get("id"), str) or not pet["question"]["id"]:
            raise GateError("Invalid pending question in runtime state.")
    pending = pet.get("pendingQuestions", [])
    if not isinstance(pending, list) or any(not isinstance(q, dict) for q in pending):
        raise GateError("Invalid pending question queue in runtime state.")
    # Check the queue as well as its visible head, including awaiting_review.
    if pet.get("question") or pending:
        return pet, "A PM Pet question or answer review is pending. Read status, review the answer in Codex, then submit the full roadmap with the matching resolveQuestionId. Do not build or delegate."
    try:
        heartbeat = read_object(runtime / "heartbeat.json")
        observed = heartbeat.get("updatedAt")
        if type(observed) not in (int, float) or not math.isfinite(observed) or not 0 <= now - observed < HEARTBEAT_MAX_AGE:
            raise GateError("PM Pet bridge heartbeat is stale or invalid.")
    except (OSError, ValueError, TypeError) as error:
        return pet, "Cannot verify PM Pet question state: " + str(error)
    return pet, None


def evaluate(event, home, runtime, now=None):
    home, runtime = home.expanduser().resolve(), runtime.expanduser().resolve()
    event_name = event.get("hook_event_name") if isinstance(event, dict) else None
    if event_name not in {"PreToolUse", "UserPromptSubmit", None}:
        return {}
    pet, reason, session_id = None, None, None
    try:
        if not isinstance(event, dict):
            raise GateError("Hook input must be a JSON object.")
        session_id = exact_id(event.get("session_id"))
        pet, reason = pending_pet(runtime, session_id, time.time() if now is None else now)
    except (OSError, ValueError, TypeError) as error:
        reason = "Cannot verify configured PM Pet runtime; build tools remain gated: " + str(error)
    if not reason:
        return {}
    if event_name == "UserPromptSubmit":
        return {"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": reason + " A new message is not an automatic answer or release."}}
    if session_id and control_command(event, home, runtime, session_id, pet):
        return {}  # Do not override Codex's normal approval policy with allow.
    return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny", "permissionDecisionReason": reason}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--home", type=Path, default=Path(os.environ.get("PM_PET_HOME", Path(__file__).resolve().parents[4])))
    parser.add_argument("--runtime", type=Path)
    args = parser.parse_args()
    home = args.home.expanduser().resolve()
    runtime = (args.runtime or home / ".pm-pet" / "runtime").expanduser().resolve()
    try:
        raw = sys.stdin.buffer.read(MAX_INPUT + 1)
        if len(raw) > MAX_INPUT:
            raise GateError("Hook input exceeds the size limit.")
        result = evaluate(json.loads(raw), home, runtime)
    except (OSError, ValueError, TypeError) as error:
        result = {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny", "permissionDecisionReason": "PM Pet guard input error: " + str(error)}}
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
