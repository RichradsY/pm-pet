#!/usr/bin/env python3
"""Developer launcher. Does not install files or change Codex configuration."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "build" / "PM Pet.app"
BRIDGE = ROOT / "bridge" / "pm_pet_bridge.py"


def read_json(path):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return {}


def native_owner(runtime):
    info = read_json(runtime / "native-status.json")
    pid = info.get("pid")
    if not isinstance(pid, int) or pid <= 1 or str(runtime) != info.get("runtime"):
        return None
    try:
        age = time.time() - (runtime / "native-status.json").stat().st_mtime
    except OSError:
        return None
    if not 0 <= age < 5 or info.get("running") is False or (info.get("quitRequestId") and not info.get("uiReady")):
        return None
    return info


def build():
    subprocess.run(["/bin/bash", str(ROOT / "native" / "build.sh"), str(APP)], check=True)


def wait_native(runtime, conversation=None, timeout=12):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        info = native_owner(runtime)
        heartbeat = read_json(runtime / "heartbeat.json")
        updated = heartbeat.get("updatedAt", 0)
        bridge_ready = isinstance(updated, (int, float)) and 0 <= time.time() - updated < 8
        if info and bridge_ready and info.get("uiReady") and (not conversation or conversation in info.get("enabledIds", [])):
            return info
        time.sleep(.15)
    raise RuntimeError("PM Pet did not confirm its native window. Check the app menu and runtime/bridge.log.")


def start(runtime):
    if sys.platform != "darwin":
        raise RuntimeError("This developer app currently runs on macOS only.")
    if native_owner(runtime):
        return wait_native(runtime)
    if not (APP / "Contents" / "MacOS" / "PMPet").exists():
        build()
    runtime.mkdir(parents=True, exist_ok=True)
    subprocess.run([
        "/usr/bin/open", "-a", str(APP), "--args", "--runtime", str(runtime),
        "--bridge", str(BRIDGE), "--python", sys.executable
    ], check=True)
    return wait_native(runtime)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["build", "start", "enable", "disable", "preferences", "report", "status", "quit", "doctor"])
    parser.add_argument("--runtime", type=Path, default=ROOT / ".pm-pet" / "runtime")
    parser.add_argument("--conversation", help="Exact Codex conversation UUID; otherwise use the current context")
    args, forwarded = parser.parse_known_args()
    identity = args.conversation or os.environ.get("CODEX_THREAD_ID")
    if identity:
        identity = str(uuid.UUID(identity))
    if args.conversation:
        forwarded = ["--conversation", identity, *forwarded]
    runtime = args.runtime.expanduser().resolve()
    if runtime == Path("/"):
        raise RuntimeError("Choose a dedicated PM Pet runtime directory.")
    if args.command == "build":
        build()
        return 0
    if args.command == "doctor":
        info = native_owner(runtime)
        print(json.dumps({"macOS": sys.platform == "darwin", "built": APP.exists(),
            "nativeRunning": bool(info), "runtime": str(runtime),
            "conversationContextAvailable": bool(os.environ.get("CODEX_THREAD_ID")),
            "native": info, "executionControl": False}, indent=2))
        return 0
    if args.command == "quit":
        info = native_owner(runtime)
        if info:
            request_id = str(uuid.uuid4())
            pending = runtime / ("quit-" + request_id + ".tmp")
            pending.write_text(json.dumps({"requestId": request_id, "pid": info["pid"]}))
            pending.replace(runtime / "quit-request.json")
            deadline = time.monotonic() + 5
            confirmed = False
            while time.monotonic() < deadline:
                closed = read_json(runtime / "native-status.json")
                if closed.get("quitRequestId") == request_id and closed.get("uiReady") is False:
                    confirmed = True
                    break
                time.sleep(.1)
            if not confirmed:
                raise RuntimeError("The app has not exited. Use Quit PM Pet from its menu.")
        print(json.dumps({"ok": True, "nativeRunning": False, "bindingsPreserved": True}))
        return 0
    if args.command in ("start", "enable"):
        if args.command == "enable" and not identity:
            raise RuntimeError("Enable needs a Codex conversation or an explicit --conversation UUID.")
        info = start(runtime)
        if args.command == "start":
            print(json.dumps({"ok": True, "native": info}, indent=2))
            return 0
    elif not native_owner(runtime):
        if args.command == "status":
            print(json.dumps({"ok": True, "nativeRunning": False, "message": "PM Pet is stopped. Start or enable it explicitly."}))
            return 0
        raise RuntimeError("PM Pet is stopped. Start it before changing a binding; this command did not launch it.")

    result = subprocess.run([sys.executable, str(BRIDGE), args.command, "--runtime", str(runtime), *forwarded], text=True, capture_output=True)
    if result.stderr:
        sys.stderr.write(result.stderr)
    if result.returncode:
        sys.stdout.write(result.stdout)
        return result.returncode
    response = json.loads(result.stdout)
    if args.command == "enable" and response.get("ok"):
        info = wait_native(runtime, identity)
        response["nativeConfirmed"] = identity in info.get("enabledIds", [])
    print(json.dumps(response, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (RuntimeError, OSError, ValueError, subprocess.CalledProcessError) as error:
        print(json.dumps({"ok": False, "error": str(error)}, ensure_ascii=False), file=sys.stderr)
        raise SystemExit(1)
