#!/usr/bin/env python3
"""Install a checkout-bound PM Pet command. No downloads or host configuration edits."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile
import time


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PREFIX = Path.home() / ".local"
DEFAULT_SKILL = Path.home() / ".codex" / "skills" / "pm-pet"
SKILL_FILES = ("SKILL.md", "agents/openai.yaml", "references/report-contract.md", "scripts/pm_pet.py")
OWNER = "pm-pet-source-install-v1"


class SetupError(Exception):
    pass


def normalized(value):
    return Path(value).expanduser().absolute()


def no_symlinks(path):
    # Canonicalize the user-selected prefix once; never follow links within managed paths.
    for part in (path, *path.parents):
        if part.is_symlink():
            raise SetupError("Refusing a symlink in managed path: " + str(part))


def digest(data):
    return hashlib.sha256(data).hexdigest()


def command_path(prefix):
    return prefix / "bin" / "pm-pet"


def manifest_path(prefix):
    return prefix / "share" / "pm-pet" / "install.json"


def read_manifest(prefix):
    path = manifest_path(prefix)
    no_symlinks(path)
    if not path.is_file() or path.stat().st_size > 128 * 1024:
        raise SetupError("No valid PM Pet installation manifest at " + str(path))
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        raise SetupError("Cannot read the installation manifest: " + str(path))
    if (not isinstance(manifest, dict) or manifest.get("owner") != OWNER
            or manifest.get("prefix") != str(prefix) or manifest.get("checkout") != str(ROOT)
            or not isinstance(manifest.get("files"), dict)):
        raise SetupError("Installation belongs to another checkout or is not recognized; leave it unchanged.")
    skill = manifest.get("skillDir")
    if skill is not None and (not isinstance(skill, str) or not Path(skill).is_absolute()):
        raise SetupError("Invalid skill directory in installation manifest.")
    expected = {str(command_path(prefix))}
    if skill:
        expected.update(str(Path(skill) / name) for name in SKILL_FILES)
    if set(manifest["files"]) != expected:
        raise SetupError("Installation manifest lists unexpected files; leave it unchanged.")
    return manifest


def payloads(prefix, skill_dir):
    for required in ("scripts/pm-pet.py", "bridge/pm_pet_bridge.py", "native/build.sh"):
        if not (ROOT / required).is_file():
            raise SetupError("Source checkout is incomplete: " + required)
    python = str(Path(sys.executable).absolute())
    wrapper = "#!/bin/sh\n# Owned by PM Pet source installer.\nexec {} {} run --prefix {} -- \"$@\"\n".format(
        shlex.quote(python), shlex.quote(str(ROOT / "scripts/setup.py")), shlex.quote(str(prefix)))
    files = {command_path(prefix): wrapper.encode("utf-8")}
    if skill_dir:
        source = ROOT / "integrations/codex/pm-pet"
        for name in SKILL_FILES:
            if name == "scripts/pm_pet.py":
                # This explicit installed binding is independent of the caller's working directory.
                helper = ("#!/usr/bin/env python3\n# Owned by PM Pet source installer.\n"
                          "import os, sys\n"
                          "launcher = {!r}\n"
                          "if not os.path.isfile(launcher):\n"
                          "    sys.exit('PM Pet checkout moved or was removed. Reinstall from its new location.')\n"
                          "os.execv(sys.executable, [sys.executable, launcher, *sys.argv[1:]])\n").format(
                              str(ROOT / "scripts/pm-pet.py"))
                files[skill_dir / name] = helper.encode("utf-8")
            else:
                content = (source / name).read_bytes()
                if name == "references/report-contract.md":
                    relative = b"(../../../../docs/FEEDBACK-GATE.md)"
                    if relative in content:
                        target = ROOT / "docs/FEEDBACK-GATE.md"
                        if not target.is_file():
                            raise SetupError("Source checkout is incomplete: docs/FEEDBACK-GATE.md")
                        content = content.replace(relative, ("(<" + str(target) + ">)").encode("utf-8"))
                files[skill_dir / name] = content
    return files


def verify_owned(prefix, manifest):
    """Validate every path before any removal/update; tolerate an already-missing owned file."""
    files = {Path(name): checksum for name, checksum in manifest["files"].items()}
    for path, checksum in files.items():
        no_symlinks(path)
        if path.exists() and (not path.is_file() or digest(path.read_bytes()) != checksum):
            raise SetupError("Owned file was changed; refusing to overwrite or remove it: " + str(path))
    own_dir = manifest_path(prefix).parent
    if any(path.name != "install.json" for path in own_dir.iterdir()):
        raise SetupError("Unknown content in installation metadata directory; leave it unchanged.")
    if manifest.get("skillDir"):
        skill = Path(manifest["skillDir"])
        allowed_dirs = {skill}
        for path in files:
            if skill in path.parents:
                allowed_dirs.update(parent for parent in path.parents if parent == skill or skill in parent.parents)
        if skill.exists():
            for path in skill.rglob("*"):
                if path.is_symlink() or (path.is_dir() and path not in allowed_dirs) or (not path.is_dir() and path not in files):
                    raise SetupError("Unknown content in installed skill; leave it unchanged: " + str(path))


def write_atomic(path, data, mode=0o644):
    path.parent.mkdir(parents=True, exist_ok=True)
    no_symlinks(path)
    fd, temporary = tempfile.mkstemp(prefix=".pm-pet-", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def persist_install(prefix, skill_dir, files, fresh=False):
    manifest = {"owner": OWNER, "prefix": str(prefix), "checkout": str(ROOT),
                "python": str(Path(sys.executable).absolute()), "skillDir": str(skill_dir) if skill_dir else None,
                "files": {str(path): digest(data) for path, data in files.items()}}
    created = []
    previous = {path: (path.read_bytes(), path.stat().st_mode & 0o777) if path.exists() else None
                for path in files} if not fresh else {}
    old_manifest = manifest_path(prefix).read_bytes() if not fresh else None
    replaced = []
    try:
        for path, data in files.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            no_symlinks(path)
            if fresh:
                # Exclusive creation does not replace a file created since preflight.
                with path.open("xb") as stream:
                    stream.write(data)
                created.append(path)
                os.chmod(path, 0o755 if path == command_path(prefix) else 0o644)
            else:
                replaced.append(path)
                write_atomic(path, data, 0o755 if path == command_path(prefix) else 0o644)
        write_atomic(manifest_path(prefix), (json.dumps(manifest, indent=2) + "\n").encode("utf-8"))
    except BaseException:
        # Keep the previous installation usable after ordinary I/O errors or Ctrl-C.
        # An uncatchable process kill/power loss is outside this small installer's transaction guarantee.
        for path in reversed(replaced):
            no_symlinks(path)
            if not path.exists() or digest(path.read_bytes()) == digest(files[path]):
                original = previous[path]
                if original is None:
                    path.unlink(missing_ok=True)
                else:
                    write_atomic(path, original[0], original[1])
        if old_manifest is not None:
            write_atomic(manifest_path(prefix), old_manifest)
        # On a first install, undo only bytes that we created and can still recognize.
        for path in reversed(created):
            if not path.is_symlink() and path.is_file() and digest(path.read_bytes()) == digest(files[path]):
                path.unlink()
        if fresh:
            roots = [manifest_path(prefix).parent] + ([skill_dir] if skill_dir else [])
            for directory in roots:
                remove_empty_tree(directory)
        raise
    return manifest


def remove_empty_tree(root):
    if root and root.is_dir() and not root.is_symlink():
        for directory in sorted((p for p in root.rglob("*") if p.is_dir()), key=lambda p: len(p.parts), reverse=True):
            try:
                directory.rmdir()
            except OSError:
                pass
        try:
            root.rmdir()
        except OSError:
            pass


def install(prefix, with_skill=False, skill_dir=None):
    prefix = normalized(prefix).resolve()
    if skill_dir is not None and not with_skill:
        raise SetupError("--skill-dir requires --with-skill.")
    skill_dir = normalized(skill_dir or DEFAULT_SKILL) if with_skill else None
    if skill_dir:
        # Resolve only the chosen parent, retaining a symlink at the owned leaf for rejection.
        skill_dir = skill_dir.parent.resolve() / skill_dir.name
        managed = manifest_path(prefix).parent
        command = command_path(prefix)
        if skill_dir == managed or managed in skill_dir.parents or skill_dir in managed.parents or skill_dir == command or command in skill_dir.parents:
            raise SetupError("Skill destination must not overlap the installed command or metadata directory.")
    no_symlinks(command_path(prefix))
    no_symlinks(manifest_path(prefix))
    if manifest_path(prefix).exists():
        manifest = read_manifest(prefix)
        verify_owned(prefix, manifest)
        if (manifest.get("skillDir") or None) != (str(skill_dir) if skill_dir else None):
            raise SetupError("Installation options changed. Uninstall first; then install with the desired skill option.")
        print("Already installed. Run pm-pet update to refresh this checkout's installation.")
        return
    for path in (command_path(prefix), manifest_path(prefix).parent, skill_dir):
        if path is not None:
            no_symlinks(path)
            if path.exists():
                raise SetupError("Refusing to replace an existing path: " + str(path))
    files = payloads(prefix, skill_dir)
    manifest_path(prefix).parent.mkdir(parents=True, exist_ok=False)
    persist_install(prefix, skill_dir, files, fresh=True)
    print("Installed: " + str(command_path(prefix)))
    print("Source checkout: " + str(ROOT))
    print("Add to this shell if needed: export PATH={}:\"$PATH\"".format(shlex.quote(str(prefix / "bin"))))
    print("No app was built or started. First enable builds locally; pm-pet build builds explicitly.")
    print("Next: pm-pet doctor; pm-pet enable --conversation UUID; pm-pet status")
    print("Manage: pm-pet disable; pm-pet quit; pm-pet update; pm-pet uninstall")
    if skill_dir:
        print("Skill installed: " + str(skill_dir) + ". Restart Codex if needed, then ask $pm-pet to enable this conversation.")
    print("No shell configuration, Codex config, hook trust, or startup items were changed.")


def update(prefix):
    manifest = read_manifest(prefix)
    verify_owned(prefix, manifest)
    skill_dir = Path(manifest["skillDir"]) if manifest.get("skillDir") else None
    persist_install(prefix, skill_dir, payloads(prefix, skill_dir))
    print("Refreshed command and optional skill from " + str(ROOT))
    print("This did not fetch source, rebuild, or restart the app.")
    print("For a source update: pm-pet quit; git pull --ff-only; pm-pet build; pm-pet update; pm-pet start")


def runtime_purge_guard():
    runtime = ROOT / ".pm-pet" / "runtime"
    no_symlinks(runtime)
    if not runtime.exists():
        return runtime, []
    if not runtime.is_dir() or any(path.is_symlink() for path in runtime.rglob("*")):
        raise SetupError("Refusing to purge an unexpected runtime path or symlink.")
    try:
        state_path = runtime / "state.json"
        if state_path.stat().st_size > 4 * 1024 * 1024:
            raise ValueError("oversized state")
        state = json.loads(state_path.read_text(encoding="utf-8"))
        if not isinstance(state, dict) or state.get("schemaVersion") != 1 or not isinstance(state.get("pets"), list):
            raise ValueError("unknown runtime")
    except (OSError, ValueError):
        raise SetupError("Cannot verify this directory as a PM Pet runtime; leave it unchanged.")
    for name in ("heartbeat.json", "native-status.json"):
        path = runtime / name
        if path.exists() and time.time() - path.stat().st_mtime < 15:
            raise SetupError("PM Pet may still be running. Run pm-pet quit before --purge-runtime.")
    # The daemon's held lock is stronger evidence than a delayed heartbeat.
    import fcntl
    locks = []
    try:
        for name in ("daemon.lock", "native.lock"):
            lock_path = runtime / name
            if not lock_path.exists():
                continue
            lock = lock_path.open("r+")
            locks.append(lock)
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        for lock in locks:
            lock.close()
        raise SetupError("The app or bridge is running. Quit PM Pet before purging runtime data.")
    return runtime, locks


def uninstall(prefix, purge_runtime=False):
    manifest = read_manifest(prefix)
    verify_owned(prefix, manifest)
    runtime, locks = runtime_purge_guard() if purge_runtime else (None, [])
    try:
        if runtime and runtime.exists():
            shutil.rmtree(runtime)
        for name in manifest["files"]:
            path = Path(name)
            if path.exists():
                path.unlink()
        manifest_path(prefix).unlink()
        remove_empty_tree(manifest_path(prefix).parent)
        if manifest.get("skillDir"):
            remove_empty_tree(Path(manifest["skillDir"]))
    finally:
        for lock in locks:
            lock.close()
    print("Removed the installed command and its optional skill. Source checkout and built app are retained.")
    print("Default runtime removed." if purge_runtime else "Runtime and preferences are preserved. This does not quit an already-running app.")


def doctor(prefix):
    manifest = read_manifest(prefix)
    verify_owned(prefix, manifest)
    result = {"sourceCheckout": str(ROOT), "installedCommand": str(command_path(prefix)),
              "skillDirectory": manifest.get("skillDir"), "python": sys.executable,
              "pythonSupported": sys.version_info >= (3, 9), "macOS": sys.platform == "darwin",
              "sourceBuild": True, "prebuiltRelease": False}
    if sys.platform == "darwin":
        swift = subprocess.run(["/usr/bin/xcrun", "--find", "swiftc"], capture_output=True, text=True)
        result["swiftCompilerAvailable"] = swift.returncode == 0
    checked = subprocess.run([sys.executable, str(ROOT / "scripts/pm-pet.py"), "doctor"], capture_output=True, text=True)
    try:
        result["app"] = json.loads(checked.stdout) if checked.returncode == 0 else {"error": checked.stderr.strip()}
    except ValueError:
        result["app"] = {"error": "Source launcher doctor returned an unexpected response."}
    print(json.dumps(result, indent=2))
    return 0 if result["macOS"] and result["pythonSupported"] and result.get("swiftCompilerAvailable") and checked.returncode == 0 else 1


def run(prefix, arguments):
    arguments = arguments[1:] if arguments[:1] == ["--"] else arguments
    if not arguments or arguments[0] in ("-h", "--help", "help"):
        print("PM Pet source preview\nUsage: pm-pet COMMAND [OPTIONS]\n"
              "  enable/status/disable   Connect, inspect, or disable a conversation\n"
              "  preferences/report      Update Pet preferences or reviewed progress\n"
              "  build/start/quit        Build locally, start, or quit the companion\n"
              "  doctor                  Check installation and local prerequisites\n"
              "  update                  Refresh this install; no fetch or app rebuild\n"
              "  uninstall [--purge-runtime]  Remove owned install; preserve data by default\n"
              "Conversation identity: --conversation UUID, or CODEX_THREAD_ID in Codex.\n"
              "Use pm-pet COMMAND --help for launcher options.")
        return 0
    if arguments[0] in ("update", "uninstall", "doctor"):
        return main([arguments[0], "--prefix", str(prefix), *arguments[1:]])
    read_manifest(prefix)
    return subprocess.call([sys.executable, str(ROOT / "scripts/pm-pet.py"), *arguments])


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("install", "update", "uninstall", "doctor", "run"):
        command = commands.add_parser(name)
        command.add_argument("--prefix", type=Path, default=DEFAULT_PREFIX)
        if name == "install":
            command.add_argument("--with-skill", action="store_true")
            command.add_argument("--skill-dir", type=Path, help="Complete destination skill directory; requires --with-skill")
        elif name == "uninstall":
            command.add_argument("--purge-runtime", action="store_true", help="Delete only this checkout's verified, stopped default runtime")
        elif name == "run":
            command.add_argument("arguments", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    prefix = normalized(args.prefix).resolve()
    try:
        if args.command == "install":
            install(prefix, args.with_skill, args.skill_dir)
        elif args.command == "update":
            update(prefix)
        elif args.command == "uninstall":
            uninstall(prefix, args.purge_runtime)
        elif args.command == "doctor":
            return doctor(prefix)
        elif args.command == "run":
            return run(prefix, args.arguments)
        return 0
    except (SetupError, OSError, ValueError) as error:
        print("PM Pet setup: " + str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
