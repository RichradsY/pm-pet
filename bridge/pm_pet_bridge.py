#!/usr/bin/env python3
"""Local, explicit PM Pet control and a conservative Codex transcript observer.

Python 3.9+, standard library only. No credentials, network calls, or Codex settings.
Transcript events are observations; this process never pauses or resumes agents.
"""

import argparse
import copy
from datetime import datetime, timezone
import fcntl
import json
import math
import os
from pathlib import Path
import re
import signal
import sys
import time
import uuid


THEMES = ("sage", "sky", "lilac", "rose", "sand")
MAX_PETS = 5
MAX_REQUEST_BYTES = 128 * 1024
MAX_LINE_BYTES = 16 * 1024 * 1024
PHASES = {"idle", "planning", "building", "checking", "waiting", "complete", "paused", "error"}
UUID_PATTERN = re.compile(r"^[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}$")


class BridgeError(ValueError):
    pass


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def timestamp(value):
    """Only event timestamps are valid freshness evidence, never file mtime."""
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            return None
        return parsed.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")
    except ValueError:
        return None


def validate_id(value):
    if not isinstance(value, str) or not UUID_PATTERN.fullmatch(value):
        raise BridgeError("An exact conversation UUID is required; a project path or title is not an identity.")
    return str(uuid.UUID(value))


def atomic_json(path, data):
    path = Path(path)
    temp = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    fd = os.open(str(temp), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
            handle.write("\n")
        os.replace(str(temp), str(path))
    finally:
        if temp.exists():
            temp.unlink()


def read_json(path):
    with Path(path).open(encoding="utf-8") as handle:
        return json.load(handle)


def ensure_runtime(runtime):
    runtime = Path(runtime).expanduser().resolve()
    runtime.mkdir(mode=0o700, parents=True, exist_ok=True)
    for name in ("inbox", "ack"):
        (runtime / name).mkdir(mode=0o700, exist_ok=True)
    return runtime


def default_state():
    return {"schemaVersion": 1, "revision": 0, "pets": [],
            "quota": {"windows": {}, "observedAt": None, "source": "unavailable"},
            "capabilities": {"executionControl": False}, "everEnabled": False}


def checked_transcript(path, conversation_id):
    path = Path(path).expanduser().resolve()
    if not path.is_file() or path.suffix != ".jsonl":
        raise BridgeError("Transcript must be an existing .jsonl file.")
    with path.open("rb") as handle:
        # The first record must establish ownership. Never follow a filename alone.
        raw = handle.readline(MAX_LINE_BYTES + 1)
    if len(raw) > MAX_LINE_BYTES:
        raise BridgeError("Transcript metadata record is too large.")
    try:
        record = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        raise BridgeError("Transcript metadata is unreadable.")
    if not isinstance(record, dict) or record.get("type") != "session_meta":
        raise BridgeError("Transcript must begin with session_meta.")
    meta = record.get("payload") or {}
    if str(meta.get("id", "")).lower() != conversation_id:
        raise BridgeError("Transcript identity does not match this conversation.")
    source = meta.get("source")
    thread_source = meta.get("thread_source")
    child_source = any(isinstance(item, dict) and "subagent" in item for item in (source, thread_source))
    if meta.get("parent_thread_id") or child_source or (meta.get("agent_path") not in (None, "", "/root")):
        raise BridgeError("A child agent cannot register an independent main Pet.")
    return path


def discover_transcripts(conversation_id, sessions_root):
    root = Path(sessions_root).expanduser()
    paths = []
    if root.is_dir():
        for path in root.rglob("*" + conversation_id + "*.jsonl"):
            try:
                paths.append(checked_transcript(path, conversation_id))
            except (BridgeError, OSError):
                continue
    return sorted(set(paths), key=lambda path: path.name)


class TranscriptTail:
    """Read only appended, complete JSONL records; retries a partial final line."""

    def __init__(self, path, conversation_id=None):
        self.path = Path(path)
        self.conversation_id = conversation_id
        self.offset = 0
        self.identity = None
        self.bytes_read = 0

    def read(self):
        stat = self.path.stat()
        identity = (stat.st_dev, stat.st_ino)
        if identity != self.identity or stat.st_size < self.offset:
            if self.conversation_id:
                checked_transcript(self.path, self.conversation_id)
            self.identity, self.offset = identity, 0
        if stat.st_size == self.offset:
            return []
        events = []
        with self.path.open("rb") as handle:
            handle.seek(self.offset)
            while True:
                start = handle.tell()
                line = handle.readline(MAX_LINE_BYTES + 1)
                self.bytes_read += len(line)
                if not line:
                    break
                if len(line) > MAX_LINE_BYTES:
                    raise BridgeError("A transcript record exceeds the supported size.")
                if not line.endswith(b"\n"):
                    handle.seek(start)
                    break
                self.offset = handle.tell()
                try:
                    event = json.loads(line)
                except (ValueError, UnicodeDecodeError):
                    continue
                if isinstance(event, dict):
                    events.append(event)
        return events


def quota_snapshot(limits, observed_at):
    if not isinstance(limits, dict) or not observed_at:
        return None
    limit_id = limits.get("limit_id", limits.get("limitId"))
    if limit_id not in (None, "codex"):
        # A model-specific quota is not the account's general Codex allowance.
        return None
    windows = {}
    for key in ("primary", "secondary"):
        window = limits.get(key)
        if not isinstance(window, dict):
            continue
        minutes = window.get("window_minutes", window.get("windowDurationMins"))
        used = window.get("used_percent", window.get("usedPercent"))
        if isinstance(used, bool) or not isinstance(used, (float, int)) or not math.isfinite(used):
            continue
        name = "week" if minutes == 10080 else "five" if minutes == 300 else None
        if name:
            windows[name] = {"remainingPercent": max(0, min(100, 100 - used)),
                             "windowDurationMins": minutes}
            resets = window.get("resets_at", window.get("resetsAt"))
            if isinstance(resets, (int, float)) and not isinstance(resets, bool):
                windows[name]["resetsAt"] = resets
    if not windows:
        return None
    return {"windows": windows, "observedAt": observed_at, "source": "transcript",
            "limitId": limit_id}


class Bridge:
    def __init__(self, runtime, sessions_root=None):
        self.runtime = ensure_runtime(runtime)
        self.sessions_root = Path(sessions_root or Path.home() / ".codex" / "sessions")
        self.state_path = self.runtime / "state.json"
        self.bindings_path = self.runtime / "bindings.json"
        self.state = read_json(self.state_path) if self.state_path.exists() else default_state()
        if self.state.get("schemaVersion") != 1:
            raise BridgeError("Unsupported runtime state version; use a separate runtime directory.")
        self.state["capabilities"] = {"executionControl": False}
        self.bindings = read_json(self.bindings_path) if self.bindings_path.exists() else {}
        self.tails = {}
        self.last_discovery = {}
        self.changed = False
        self.persist()

    def persist(self):
        atomic_json(self.bindings_path, self.bindings)
        atomic_json(self.state_path, self.state)
        self.changed = False

    def publish(self):
        if self.changed:
            self.state["revision"] += 1
            self.persist()

    def pet(self, conversation_id):
        return next((pet for pet in self.state["pets"] if pet["id"] == conversation_id), None)

    def require_pet(self, conversation_id):
        pet = self.pet(conversation_id)
        if pet is None or not pet["enabled"]:
            raise BridgeError("This conversation has no enabled Pet.")
        return pet

    def enable(self, request):
        conversation_id = validate_id(request.get("id"))
        pet = self.pet(conversation_id)
        if pet and pet["enabled"]:
            return  # idempotent, including quota preference and generation
        if sum(1 for candidate in self.state["pets"] if candidate["enabled"]) >= MAX_PETS:
            raise BridgeError("Five Pets are already enabled. Disable one before enabling another conversation.")
        explicit = request.get("transcriptPath")
        paths = [checked_transcript(explicit, conversation_id)] if explicit else discover_transcripts(conversation_id, self.sessions_root)
        if not paths:
            raise BridgeError("No verified local transcript was found for this exact conversation UUID.")
        title = self.clean_text(request["title"], "title", 100) if "title" in request else None
        if not pet:
            used = {item["theme"] for item in self.state["pets"] if item["enabled"]}
            theme = next((candidate for candidate in THEMES if candidate not in used), THEMES[0])
            pet = {"id": conversation_id, "title": "Conversation " + conversation_id[-6:], "theme": theme,
                   "enabled": True, "quotaVisible": not self.state.get("everEnabled", False), "size": 100,
                   "position": None, "phase": "idle", "progress": None, "currentStep": "Waiting for task activity",
                   "steps": [], "question": None, "sourceUpdatedAt": None, "sourceStatus": "connecting",
                   "children": [], "generation": 0, "lastReportSequence": -1, "planVersion": 0,
                   "roadmapNeedsUpdate": False, "requestObservedAt": None, "planReviewedAt": None}
            self.state["pets"].append(pet)
        pet["enabled"] = True
        pet["sourceStatus"] = "connecting"
        pet["generation"] += 1
        used = {item["theme"] for item in self.state["pets"] if item["enabled"] and item["id"] != conversation_id}
        if pet["theme"] in used:
            pet["theme"] = next(candidate for candidate in THEMES if candidate not in used)
        if title:
            pet["title"] = title
        self.state["everEnabled"] = True
        self.bindings[conversation_id] = {"paths": [str(path) for path in paths], "explicit": bool(explicit)}
        self.last_discovery.pop(conversation_id, None)
        self.changed = True

    @staticmethod
    def clean_text(value, name, max_length):
        if not isinstance(value, str) or not value.strip() or len(value) > max_length:
            raise BridgeError("%s must be non-empty text, at most %d characters." % (name, max_length))
        return value.strip()

    def preferences(self, request):
        pet = self.require_pet(validate_id(request.get("id")))
        values = request.get("preferences", request)
        if not isinstance(values, dict):
            raise BridgeError("preferences must be an object.")
        updated = copy.deepcopy(pet)
        if "quotaVisible" in values:
            if not isinstance(values["quotaVisible"], bool):
                raise BridgeError("quotaVisible must be true or false.")
            updated["quotaVisible"] = values["quotaVisible"]
        if "size" in values:
            size = values["size"]
            if isinstance(size, bool) or not isinstance(size, int) or not 75 <= size <= 150:
                raise BridgeError("size must be an integer percentage between 75 and 150.")
            updated["size"] = size
        if "position" in values:
            position = values["position"]
            if position is not None and (not isinstance(position, dict) or set(position) != {"x", "y"} or
                    any(isinstance(n, bool) or not isinstance(n, (int, float)) or not math.isfinite(n) for n in position.values())):
                raise BridgeError("position must be null or finite screen coordinates {x,y}.")
            updated["position"] = position
        if "title" in values:
            updated["title"] = self.clean_text(values["title"], "title", 100)
        pet.update(updated)
        self.changed = True

    def report(self, request):
        pet = self.require_pet(validate_id(request.get("id")))
        report = request.get("report", request)
        if not isinstance(report, dict):
            raise BridgeError("report must be an object.")
        generation = report.get("generation")
        if isinstance(generation, bool) or not isinstance(generation, int) or generation != pet["generation"]:
            raise BridgeError("A current integer Pet generation is required; read status before reporting.")
        sequence = report.get("sequence")
        if isinstance(sequence, bool) or not isinstance(sequence, int) or sequence <= pet["lastReportSequence"]:
            raise BridgeError("A new integer report sequence is required; read status before reporting.")
        if pet["question"] and report.get("resolveQuestionId") != pet["question"]["id"]:
            if any(key in report for key in ("steps", "currentStep", "planRevision")) or report.get("phase", "waiting") != "waiting":
                raise BridgeError("Resolve the pending question by id before updating progress or continuing work.")
        updated = copy.deepcopy(pet)
        # Preserve the last actual plan review across later phase-only reports.
        if pet["steps"] and not pet.get("planReviewedAt"):
            updated["planReviewedAt"] = pet.get("reportObservedAt")
        if "planRevision" in report:
            revision = report["planRevision"]
            if isinstance(revision, bool) or not isinstance(revision, int) or revision < pet["planVersion"]:
                raise BridgeError("planRevision must be an integer at least as new as the current plan.")
            updated["planVersion"] = revision
        if "steps" in report:
            steps = report["steps"]
            if not isinstance(steps, list) or not 1 <= len(steps) <= 100:
                raise BridgeError("steps must contain between 1 and 100 delivery items.")
            clean, seen = [], set()
            for step in steps:
                if not isinstance(step, dict):
                    raise BridgeError("Each step must be an object.")
                item_id = self.clean_text(step.get("id"), "step id", 100)
                if item_id in seen or not isinstance(step.get("done"), bool):
                    raise BridgeError("Step ids must be unique, with explicit boolean done values.")
                seen.add(item_id)
                clean.append({"id": item_id, "label": self.clean_text(step.get("label"), "step label", 200), "done": step["done"]})
            done = sum(1 for step in clean if step["done"])
            updated["steps"] = clean
            updated["progress"] = {"done": done, "total": len(clean), "percent": round(100 * done / len(clean))}
            if "planRevision" not in report:
                updated["planVersion"] += 1
        if "currentStep" in report:
            updated["currentStep"] = self.clean_text(report["currentStep"], "currentStep", 200)
        if "phase" in report:
            if report["phase"] not in PHASES:
                raise BridgeError("Unknown phase.")
            updated["phase"] = report["phase"]
        if "question" in report:
            question = report["question"]
            if not isinstance(question, dict):
                raise BridgeError("Use resolveQuestionId to clear a question; question must be an object.")
            question_id = self.clean_text(question.get("id"), "question id", 100)
            if updated["question"] and updated["question"]["id"] != question_id:
                raise BridgeError("Resolve the current question by id before replacing it.")
            updated["question"] = {"id": question_id, "text": self.clean_text(question.get("text"), "question text", 1200)}
        if "resolveQuestionId" in report:
            if not updated["question"] or updated["question"]["id"] != report["resolveQuestionId"]:
                raise BridgeError("Question resolution must match the pending question id.")
            updated["question"] = None
            if "phase" not in report:
                updated["phase"] = "idle"
        all_deliveries_done = bool(updated["steps"]) and all(step["done"] for step in updated["steps"])
        if report.get("phase") == "complete" and not all_deliveries_done:
            raise BridgeError("Completion requires a non-empty roadmap with every delivery item done.")
        if report.get("phase") == "complete" and pet.get("roadmapNeedsUpdate") and not ("steps" in report and "currentStep" in report):
            raise BridgeError("Review the latest user request with steps and currentStep before reporting completion.")
        if updated["question"]:
            updated["phase"] = "waiting"
        elif updated["phase"] == "waiting":
            raise BridgeError("A waiting report requires an explicit question.")
        if updated["phase"] == "complete" and not all_deliveries_done:
            updated["phase"] = "idle"  # A revised scope can reopen a completed roadmap.
        updated["lastReportSequence"] = sequence
        updated["sourceUpdatedAt"] = now_iso()
        updated["reportObservedAt"] = updated["sourceUpdatedAt"]
        if "steps" in report and ("currentStep" in report or not pet["steps"]):
            updated["planReviewedAt"] = updated["reportObservedAt"]
            latest_request = updated.get("requestObservedAt")
            if not latest_request or latest_request <= updated["planReviewedAt"]:
                updated["roadmapNeedsUpdate"] = False
        updated["sourceStatus"] = "reported"
        pet.update(updated)
        self.changed = True

    def handle(self, request):
        if not isinstance(request, dict):
            raise BridgeError("Request must be an object.")
        action = request.get("action")
        if action == "enable":
            self.enable(request)
        elif action == "disable":
            if request.get("all") is True:
                selected = self.state["pets"]
            else:
                pet = self.pet(validate_id(request.get("id")))
                selected = [pet] if pet else []
            for pet in selected:
                pet["enabled"] = False
                pet["sourceStatus"] = "disabled"
                self.tails.pop(pet["id"], None)
            self.changed = True
        elif action == "preferences":
            self.preferences(request)
        elif action == "report":
            self.report(request)
        elif action == "status":
            if request.get("all") is not True:
                validate_id(request.get("id"))
        else:
            raise BridgeError("Unknown action.")
        self.publish()
        result = copy.deepcopy(self.state)
        if action == "status" and request.get("all") is not True:
            result["pets"] = [pet for pet in result["pets"] if pet["id"] == validate_id(request.get("id"))]
        return result

    def apply_event(self, pet, event):
        kind = event.get("type")
        payload = event.get("payload") or {}
        if not isinstance(payload, dict) or kind != "event_msg":
            return
        event_type = payload.get("type")
        observed = timestamp(event.get("timestamp"))
        event_owner = payload.get("thread_id")
        if event_owner and event_owner != pet["id"]:
            return
        if event_type == "token_count":
            quota = quota_snapshot(payload.get("rate_limits"), observed)
            if quota:
                quota["sourceConversationId"] = pet["id"]
            previous = timestamp(self.state["quota"].get("observedAt"))
            if quota and (not previous or quota["observedAt"] > previous):
                self.state["quota"] = quota
                self.changed = True
            return
        if event_type == "item_completed":
            item = payload.get("item") or {}
            if isinstance(item, dict) and item.get("type") == "UserMessage":
                # Only a first-class user item explicitly owned by this root binding qualifies.
                # No message content, quoted tool output, or child message is interpreted.
                request_id = item.get("id")
                if event_owner != pet["id"] or not observed or not isinstance(request_id, str) or not request_id:
                    return
                previous_request = pet.get("requestObservedAt")
                if request_id == pet.get("requestMessageId") or (previous_request and observed <= previous_request):
                    return
                pet["requestObservedAt"] = observed
                pet["requestMessageId"] = request_id
                reviewed = pet.get("planReviewedAt") or pet.get("reportObservedAt")
                if pet["steps"] and (not reviewed or observed > reviewed):
                    pet["roadmapNeedsUpdate"] = True
                activity_floor = max(pet.get("eventObservedAt") or "", pet.get("reportObservedAt") or "")
                if not pet["question"] and observed >= activity_floor:
                    pet["phase"] = "planning"
                    pet["eventObservedAt"] = observed
                if not pet.get("sourceUpdatedAt") or observed > pet["sourceUpdatedAt"]:
                    pet["sourceUpdatedAt"] = observed
                    pet["sourceStatus"] = "connected"
                self.changed = True
                return
            if isinstance(item, dict) and item.get("type") == "SubAgentActivity":
                child_id, activity = item.get("agent_thread_id"), item.get("kind")
                if observed and child_id and UUID_PATTERN.fullmatch(str(child_id)) and activity in ("started", "completed"):
                    child = next((child for child in pet["children"] if child["id"] == child_id), None)
                    if child and child.get("observedAt") and observed < child["observedAt"]:
                        return
                    if child is None:
                        child = {"id": child_id, "status": "running"}
                        pet["children"].append(child)
                    child["status"] = "completed" if activity == "completed" else "running"
                    child["observedAt"] = observed
                    if not pet.get("sourceUpdatedAt") or observed > pet["sourceUpdatedAt"]:
                        pet["sourceUpdatedAt"] = observed
                        pet["sourceStatus"] = "connected"
                    self.changed = True
                # "interacted" alone does not prove a finished child has resumed work.
            # Tool outputs and prose cannot create questions/plans; child freshness is independent.
            return
        if pet.get("reportObservedAt") and observed and observed < pet["reportObservedAt"]:
            return
        if not observed or (pet.get("eventObservedAt") and observed < pet["eventObservedAt"]):
            return
        touched = False
        if event_type in ("task_started", "task_complete", "turn_aborted"):
            if not pet["question"]:
                pet["phase"] = {"task_started": "building", "task_complete": "idle", "turn_aborted": "paused"}[event_type]
                # A completed turn does not prove that every delivery item is complete.
                if event_type == "task_complete" and not pet.get("roadmapNeedsUpdate") and pet["progress"] and pet["progress"]["done"] == pet["progress"]["total"]:
                    pet["phase"] = "complete"
            touched = True
        elif event_type in ("plan_updated", "update_plan") and not pet["question"]:
            plan = payload.get("plan")
            if isinstance(plan, list) and plan and all(isinstance(item, dict) and isinstance(item.get("step"), str) and item.get("status") in ("pending", "in_progress", "completed") for item in plan):
                steps = [{"id": "plan-%d" % index, "label": item["step"][:200], "done": item["status"] == "completed"} for index, item in enumerate(plan[:100])]
                pet["steps"] = steps
                done = sum(1 for item in steps if item["done"])
                pet["progress"] = {"done": done, "total": len(steps), "percent": round(100 * done / len(steps))}
                current = next((item["step"] for item in plan if item["status"] == "in_progress"), None)
                if current:
                    pet["currentStep"] = current[:200]
                pet["planVersion"] += 1
                touched = True
        if touched:
            pet["eventObservedAt"] = observed
            if not pet.get("sourceUpdatedAt") or observed > pet["sourceUpdatedAt"]:
                pet["sourceUpdatedAt"] = observed
                pet["sourceStatus"] = "connected"
            self.changed = True

    def poll_transcripts(self, monotonic=None):
        clock = time.monotonic() if monotonic is None else monotonic
        for pet in self.state["pets"]:
            if not pet["enabled"]:
                continue
            conversation_id = pet["id"]
            binding = self.bindings.get(conversation_id, {})
            paths = [Path(path) for path in binding.get("paths", [])]
            if clock - self.last_discovery.get(conversation_id, -1e9) >= 30:
                discovered = discover_transcripts(conversation_id, self.sessions_root)
                paths = sorted(set(paths + discovered), key=lambda path: path.name)
                self.last_discovery[conversation_id] = clock
                if paths:
                    binding["paths"] = [str(path) for path in paths]
                    self.bindings[conversation_id] = binding
            readers = self.tails.setdefault(conversation_id, {})
            events = []
            failed = False
            for path in paths:
                try:
                    if str(path) not in readers:
                        readers[str(path)] = TranscriptTail(checked_transcript(path, conversation_id), conversation_id)
                    events.extend(readers[str(path)].read())
                except (OSError, BridgeError):
                    failed = True
            events.sort(key=lambda event: timestamp(event.get("timestamp")) or "")
            for event in events:
                self.apply_event(pet, event)
            if failed or not paths:
                if pet["sourceStatus"] != "unavailable":
                    pet["sourceStatus"] = "unavailable"
                    self.changed = True
            elif pet["sourceStatus"] in ("connecting", "unavailable", "disabled"):
                pet["sourceStatus"] = "connected"
                self.changed = True
        self.publish()

    def process_inbox(self):
        for path in sorted((self.runtime / "inbox").glob("*.json")):
            request_id = path.stem
            if not UUID_PATTERN.fullmatch(request_id):
                continue
            ack_path = self.runtime / "ack" / (request_id + ".json")
            if ack_path.exists():
                path.unlink(missing_ok=True)
                continue
            try:
                if path.stat().st_size > MAX_REQUEST_BYTES:
                    raise BridgeError("Request is too large.")
                request = read_json(path)
                if not isinstance(request, dict) or request.get("requestId") != request_id:
                    raise BridgeError("Request id must match its inbox filename.")
                state = self.handle(request)
                ack = {"requestId": request_id, "ok": True, "state": state}
            except (BridgeError, OSError, ValueError, TypeError) as error:
                ack = {"requestId": request_id, "ok": False, "error": str(error)}
            atomic_json(ack_path, ack)
            path.unlink(missing_ok=True)


def serve(runtime, sessions_root=None):
    runtime = ensure_runtime(runtime)
    with (runtime / "daemon.lock").open("a+") as lock:
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise BridgeError("A bridge is already running for this runtime.")
        bridge = Bridge(runtime, sessions_root)
        running = [True]
        def stop(_signal, _frame):
            running[0] = False
        signal.signal(signal.SIGTERM, stop)
        signal.signal(signal.SIGINT, stop)
        last_heartbeat, last_poll = -1e9, -1e9
        try:
            while running[0]:
                current = time.monotonic()
                if current - last_heartbeat >= 2:
                    atomic_json(runtime / "heartbeat.json", {"pid": os.getpid(), "updatedAt": time.time()})
                    last_heartbeat = current
                bridge.process_inbox()
                if current - last_poll >= 1:
                    bridge.poll_transcripts(current)
                    last_poll = current
                time.sleep(0.1)
        finally:
            (runtime / "heartbeat.json").unlink(missing_ok=True)


def send_request(runtime, request, timeout=8):
    runtime = Path(runtime).expanduser().resolve()
    try:
        heartbeat = read_json(runtime / "heartbeat.json")
        fresh = 0 <= time.time() - float(heartbeat["updatedAt"]) < 10
    except (OSError, ValueError, KeyError, TypeError):
        fresh = False
    if not fresh:
        raise BridgeError("PM Pet is not running. Launch the app before sending this command.")
    request = dict(request)
    request_id = str(uuid.uuid4())
    request["requestId"] = request_id
    encoded = json.dumps(request, allow_nan=False).encode()
    if len(encoded) > MAX_REQUEST_BYTES:
        raise BridgeError("Request is too large.")
    inbox = runtime / "inbox" / (request_id + ".json")
    ack_path = runtime / "ack" / (request_id + ".json")
    atomic_json(inbox, request)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if ack_path.exists():
            ack = read_json(ack_path)
            ack_path.unlink(missing_ok=True)
            return ack
        time.sleep(0.05)
    # Do not delete an uncertain request and claim that it did not execute.
    raise BridgeError("No acknowledgement received. The result is unknown; run status before retrying.")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("serve", "enable", "disable", "preferences", "report", "status"))
    parser.add_argument("--runtime", required=True, type=Path)
    parser.add_argument("--conversation")
    parser.add_argument("--title")
    parser.add_argument("--transcript", type=Path)
    parser.add_argument("--sessions-root", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--all", action="store_true", help="Explicitly disable every Pet")
    parser.add_argument("--json", help="Structured preferences/report JSON object")
    parser.add_argument("--json-file", "--file", type=Path, help="Read structured preferences/report JSON object")
    parser.add_argument("--timeout", type=float, default=8)
    args = parser.parse_args(argv)
    try:
        if args.action == "serve":
            serve(args.runtime, args.sessions_root)
            return 0
        if args.all and args.action not in ("disable", "status"):
            raise BridgeError("--all is only available for disable or status.")
        if args.all and args.conversation:
            raise BridgeError("Choose either --conversation or --all, not both.")
        request = {"action": args.action}
        if not args.all:
            request["id"] = validate_id(args.conversation or os.environ.get("CODEX_THREAD_ID"))
        if args.all:
            request["all"] = True
        if args.title:
            request["title"] = args.title
        if args.transcript:
            request["transcriptPath"] = str(args.transcript.expanduser().resolve())
        if args.action in ("preferences", "report"):
            if bool(args.json) == bool(args.json_file):
                raise BridgeError("Supply exactly one of --json or --json-file.")
            value = json.loads(args.json) if args.json else read_json(args.json_file)
            if not isinstance(value, dict):
                raise BridgeError("Structured payload must be an object.")
            request[args.action] = value
        ack = send_request(args.runtime, request, args.timeout)
        print(json.dumps(ack, ensure_ascii=False))
        return 0 if ack.get("ok") else 1
    except (BridgeError, OSError, ValueError) as error:
        print(json.dumps({"ok": False, "error": str(error)}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    sys.exit(main())
