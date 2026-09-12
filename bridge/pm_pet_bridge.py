#!/usr/bin/env python3
"""Local, explicit PM Pet control and a conservative Codex transcript observer.

Python 3.9+, standard library only. No credentials, network calls, or Codex settings.
Transcript events are observations; this process never pauses or resumes agents.
OS/terminal input prompts have no verified pending event in this adapter. Typed
explicit reminders point back to their original surface; no input values are collected.
"""

import argparse
import copy
from datetime import datetime, timezone
import fcntl
import hashlib
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
MAX_PENDING_INPUT_CALLS = 32
MAX_INPUT_ITEMS = 32
MAX_INPUT_TOMBSTONES = 256
MAX_FEEDBACK_MESSAGES = 32
MAX_DEFERRED_INPUT_REPLIES = 128
MAX_PENDING_TURN_ENDS = 16
# Native state/ack readers accept 4 MiB. New question admission uses half of that
# across the entire registry, leaving room for roadmaps, outcomes, and envelopes.
MAX_QUESTION_STATE_BYTES = 2 * 1024 * 1024
TERMINAL_INPUT_STATUSES = {"resolved", "cancelled"}
CANCELLATION_REASONS = {"setup_deferred", "user_cancelled", "superseded"}
PHASES = {"idle", "planning", "building", "checking", "waiting", "complete", "paused", "error"}
QUESTION_KINDS = {"decision", "input"}
QUESTION_DESTINATIONS = {"codex", "system", "terminal"}
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
            "capabilities": {"executionControl": False, "automaticInputDetection": False, "automaticQuestionDetection": True}, "everEnabled": False}


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
            if isinstance(resets, (int, float)) and not isinstance(resets, bool) and math.isfinite(resets) and resets >= 0:
                windows[name]["resetsAt"] = resets
    if not windows:
        return None
    return {"windows": windows, "observedAt": observed_at, "source": "transcript",
            "limitId": limit_id}


def desktop_quota_snapshot(item, observed_at):
    """Accept only a completed, first-class Desktop account-read result.

    The caller establishes exact root ownership. Do not parse shell output,
    arbitrary tool prose, or an exec wrapper looking for quota-shaped JSON.
    None means failure/invalid; an empty windows mapping is known-unavailable.
    Only normalized usage is retained, never the account ID or credit balance.
    """
    if (not observed_at or not isinstance(item, dict)
            or item.get("type") != "McpToolCall" or item.get("server") != "codex_app"
            or item.get("tool") != "get_usage_limits" or item.get("status") != "completed"):
        return None
    result = item.get("result")
    if not isinstance(result, dict) or result.get("isError") not in (None, False):
        return None
    data = result.get("structuredContent")
    if data is None:
        content = result.get("content")
        if not isinstance(content, list):
            return None
        candidates = []
        for block in content:
            if not isinstance(block, dict) or block.get("type") != "text":
                continue
            text = block.get("text")
            if not isinstance(text, str) or len(text) > MAX_REQUEST_BYTES:
                continue
            try:
                parsed = json.loads(text)
            except ValueError:
                continue
            if isinstance(parsed, dict) and ("rateLimitsByLimitId" in parsed or "rateLimits" in parsed):
                candidates.append(parsed)
        if len(candidates) != 1:
            return None
        data = candidates[0]
    if not isinstance(data, dict) or not any(key in data for key in ("rateLimitsByLimitId", "rateLimits")):
        return None
    mapped = data.get("rateLimitsByLimitId")
    if mapped is not None:
        if not isinstance(mapped, dict):
            return None
        limits = mapped.get("codex")
        if "codex" in mapped and not isinstance(limits, dict):
            return None
    else:
        if "rateLimits" not in data:
            return None
        limits = data["rateLimits"]
        if limits is not None and not isinstance(limits, dict):
            return None
        if limits and limits.get("limitId") not in (None, "codex"):
            limits = None
    snapshot = {"windows": {}, "observedAt": observed_at,
                "source": "codex-desktop-account", "limitId": "codex"}
    if limits is None:
        return snapshot
    if limits.get("limitId") not in (None, "codex") or not any(key in limits for key in ("primary", "secondary")):
        return None
    for slot in ("primary", "secondary"):
        window = limits.get(slot)
        if window is None:
            continue
        if not isinstance(window, dict):
            return None
        minutes, used = window.get("windowDurationMins"), window.get("usedPercent")
        if (isinstance(minutes, bool) or not isinstance(minutes, (int, float))
                or not math.isfinite(minutes) or minutes <= 0 or int(minutes) != minutes
                or isinstance(used, bool) or not isinstance(used, (int, float)) or not math.isfinite(used)):
            return None
    normalized = quota_snapshot(limits, observed_at)
    if normalized:
        snapshot["windows"] = normalized["windows"]
    return snapshot


class Bridge:
    def __init__(self, runtime, sessions_root=None):
        self.runtime = ensure_runtime(runtime)
        self.sessions_root = Path(sessions_root or Path.home() / ".codex" / "sessions")
        self.state_path = self.runtime / "state.json"
        self.bindings_path = self.runtime / "bindings.json"
        self.state = read_json(self.state_path) if self.state_path.exists() else default_state()
        if self.state.get("schemaVersion") != 1:
            raise BridgeError("Unsupported runtime state version; use a separate runtime directory.")
        self.state["capabilities"] = {"executionControl": False, "automaticInputDetection": False, "automaticQuestionDetection": True}
        for pet in self.state["pets"]:
            pet.setdefault("inputCallHistory", {})
            pet.setdefault("pendingQuestions", [])
            pet.setdefault("questionWatchStartedAt", now_iso())
            pet.setdefault("feedback", None)
            pet.setdefault("feedbackMessages", [])
            pet.setdefault("deferredInputReplies", [])
            pet.setdefault("turnState", None)
            pet.setdefault("pendingTurnEnds", [])
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

    def observe_quota(self, pet, snapshot):
        if snapshot is None:
            return
        previous = timestamp(self.state["quota"].get("observedAt"))
        if not previous or snapshot["observedAt"] > previous:
            snapshot["sourceConversationId"] = pet["id"]
            self.state["quota"] = snapshot
            self.changed = True

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
                   "currentStepId": None,
                   "steps": [], "question": None, "sourceUpdatedAt": None, "sourceStatus": "connecting",
                   "children": [], "generation": 0, "lastReportSequence": -1, "planVersion": 0,
                   "roadmapNeedsUpdate": False, "requestObservedAt": None, "planReviewedAt": None,
                   "turnState": None}
            self.state["pets"].append(pet)
        pet["enabled"] = True
        pet["sourceStatus"] = "connecting"
        pet["generation"] += 1
        pet["feedback"] = None
        pet["questionWatchStartedAt"] = now_iso()
        pet.setdefault("inputCallHistory", {})
        pet.setdefault("pendingQuestions", [])
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

    def pending_step_id(self, value, steps, field):
        item_id = self.clean_text(value, field, 100)
        if not any(step["id"] == item_id and not step["done"] for step in steps):
            raise BridgeError("%s must reference an existing pending roadmap step." % field)
        return item_id

    @staticmethod
    def input_question(call):
        pending = next((item for item in call["items"] if not item["answered"]), call["items"][0])
        question = {"id": "input:" + call["callId"], "text": pending["text"], "kind": "decision", "destination": "codex",
                "origin": "codex-input-tool", "callId": call["callId"], "status": call["status"],
                "observedAt": call["observedAt"], "items": copy.deepcopy(call["items"])}
        for field in ("purpose", "optional"):
            if field in call:
                question[field] = call[field]
        return question

    def refresh_input_queue(self, pet):
        history = pet.setdefault("inputCallHistory", {})
        calls = sorted((call for call in history.values() if call["status"] not in TERMINAL_INPUT_STATUSES), key=lambda call: (call["observedAt"], call["callId"]))
        pet["pendingQuestions"] = [self.input_question(call) for call in calls]
        if pet.get("questionOverflow"):
            pet["pendingQuestions"].append(copy.deepcopy(pet["questionOverflow"]))
        current = pet.get("question")
        if current and current.get("origin") == "codex-input-tool":
            call = history.get(current.get("callId"))
            pet["question"] = self.input_question(call) if call and call["status"] not in TERMINAL_INPUT_STATUSES else None
        if not pet.get("question") and pet["pendingQuestions"]:
            pet["question"] = copy.deepcopy(pet["pendingQuestions"][0])
        if pet.get("question"):
            pet["phase"] = "waiting"
        tombstones = sorted((call for call in history.values() if call["status"] in TERMINAL_INPUT_STATUSES), key=lambda call: call["observedAt"])
        for call in tombstones[:-MAX_INPUT_TOMBSTONES]:
            pet["questionHistoryPrunedBefore"] = max(pet.get("questionHistoryPrunedBefore") or "", call["observedAt"])
            del history[call["callId"]]
        self.refresh_feedback(pet)

    @staticmethod
    def refresh_feedback(pet):
        current = pet.get("question")
        observed = (current.get("observedAt") or pet.get("questionObservedAt")) if current else None
        # Terminal automatic calls already have tombstone/watermark replay protection.
        # Keep message review references only for currently pending questions, so the
        # per-message list cannot accumulate an unbounded history of reviewed calls.
        active_ids = {"input:" + call["callId"] for call in pet.get("inputCallHistory", {}).values()
                      if call["status"] not in TERMINAL_INPUT_STATUSES}
        if current:
            active_ids.add(current["id"])
        if pet.get("questionOverflow"):
            active_ids.add(pet["questionOverflow"]["id"])
        for entry in pet.get("feedbackMessages", []):
            entry["reviewedQuestionIds"] = [question_id for question_id in entry.get("reviewedQuestionIds", []) if question_id in active_ids]
        candidates = [entry for entry in pet.get("feedbackMessages", [])
                      if current and observed and entry["observedAt"] > observed
                      and entry.get("generation") == pet["generation"]
                      and current["id"] not in entry.get("reviewedQuestionIds", [])]
        latest = max(candidates, key=lambda entry: (entry["observedAt"], entry["sourceUserMessageId"])) if candidates else None
        pet["feedback"] = {"questionId": current["id"], "sourceUserMessageId": latest["sourceUserMessageId"],
                           "observedAt": latest["observedAt"], "status": "pending_review"} if latest else None

    def observe_feedback_message(self, pet, item, observed):
        """A root user message is a review candidate, never an inferred answer."""
        message_id = item.get("id")
        if not observed or observed < (pet.get("questionWatchStartedAt") or "") or not isinstance(message_id, str) or not 1 <= len(message_id) <= 200:
            return
        messages = pet.setdefault("feedbackMessages", [])
        if any(entry["sourceUserMessageId"] == message_id for entry in messages):
            return
        floor = pet.get("feedbackPrunedBefore") or ""
        if observed <= floor:
            return
        messages.append({"sourceUserMessageId": message_id, "observedAt": observed,
                         "generation": pet["generation"], "reviewedQuestionIds": []})
        messages.sort(key=lambda entry: (entry["observedAt"], entry["sourceUserMessageId"]))
        if len(messages) > MAX_FEEDBACK_MESSAGES:
            pet["feedbackPrunedBefore"] = max(floor, messages[-MAX_FEEDBACK_MESSAGES - 1]["observedAt"])
            del messages[:-MAX_FEEDBACK_MESSAGES]
        self.refresh_feedback(pet)
        self.changed = True

    def review_feedback(self, pet, review):
        if not isinstance(review, dict) or set(review) != {"questionId", "sourceUserMessageId", "answeredItemIndexes"}:
            raise BridgeError("reviewFeedback requires questionId, sourceUserMessageId, and answeredItemIndexes only.")
        current, feedback = pet.get("question"), pet.get("feedback")
        if not current or not feedback or review["questionId"] != current["id"] or feedback["questionId"] != current["id"] or review["sourceUserMessageId"] != feedback["sourceUserMessageId"]:
            raise BridgeError("Feedback review must match the current question and latest observed feedback message.")
        message = next((entry for entry in pet.get("feedbackMessages", []) if entry["sourceUserMessageId"] == review["sourceUserMessageId"]), None)
        question_at = current.get("observedAt") or pet.get("questionObservedAt")
        if not message or message.get("generation") != pet["generation"] or not question_at or message["observedAt"] <= question_at or current["id"] in message["reviewedQuestionIds"]:
            raise BridgeError("Feedback source must be an unreviewed root message after this question in the current binding generation.")
        indexes = review["answeredItemIndexes"]
        if not isinstance(indexes, list) or len(indexes) > MAX_INPUT_ITEMS or any(isinstance(index, bool) or not isinstance(index, int) for index in indexes) or len(set(indexes)) != len(indexes):
            raise BridgeError("answeredItemIndexes must be a bounded list of unique integer item indexes.")
        call = pet.get("inputCallHistory", {}).get(current.get("callId")) if current.get("origin") == "codex-input-tool" else None
        if indexes and (not call or any(not 0 <= index < len(call["items"]) for index in indexes)):
            raise BridgeError("Answered item indexes must reference the current observed question call.")
        for index in indexes:
            item = call["items"][index]
            if item["answered"]:
                continue  # Keep the original evidence; review never replaces a card reply's provenance.
            item.update({"answered": True, "answeredAt": message["observedAt"],
                         "answerSource": "main-agent-review", "sourceUserMessageId": message["sourceUserMessageId"], "reviewedAt": now_iso()})
        if call:
            call["status"] = "awaiting_review" if all(item["answered"] for item in call["items"]) else "awaiting_reply"
        # A review of the newest message also retires older candidate notifications for
        # this question. Older messages must not pop back into the UI after dismissal.
        for entry in pet.get("feedbackMessages", []):
            if entry["observedAt"] <= message["observedAt"] and current["id"] not in entry["reviewedQuestionIds"]:
                entry["reviewedQuestionIds"].append(current["id"])
        self.refresh_input_queue(pet)

    def input_overflow(self, pet, reason, call_id=None, observed=None):
        pet["questionOverflow"] = {"id": "input-queue-overflow", "text": "Review all pending questions in Codex; this question group exceeds the local display limit.",
                                   "kind": "decision", "destination": "codex", "origin": "codex-input-limit", "status": "needs_reconciliation", "items": [], "reason": reason}
        if observed:
            pet["questionOverflow"]["observedAt"] = observed
        if call_id and observed:
            # Keep only identity/provenance for rejected calls, never their prompt
            # bodies or answers. Replaying them must not create a second question.
            history = pet.setdefault("inputOverflowHistory", {})
            history[call_id] = {"callId": call_id, "observedAt": observed, "reason": reason}
            for old_id in sorted(history, key=lambda key: history[key]["observedAt"])[:-MAX_INPUT_TOMBSTONES]:
                pet["questionOverflowPrunedBefore"] = max(pet.get("questionOverflowPrunedBefore") or "", history[old_id]["observedAt"])
                del history[old_id]
        self.refresh_input_queue(pet)
        self.changed = True

    def question_candidate_fits(self, pet, candidate):
        projected = copy.deepcopy(self.state)
        projected["pets"] = [copy.deepcopy(candidate) if item["id"] == pet["id"] else item for item in projected["pets"]]
        # Reserve the largest supported future answer provenance before admitting
        # prompt bodies. Answer arrival must not unexpectedly double a full queue.
        for projected_pet in projected["pets"]:
            for call in projected_pet.get("inputCallHistory", {}).values():
                if call["status"] in TERMINAL_INPUT_STATUSES:
                    continue
                for item in call["items"]:
                    if item["answered"]:
                        continue
                    item.update({"answered": True, "answeredAt": "2000-01-01T00:00:00.000000Z", "answerSource": "main-agent-review",
                                 "sourceUserMessageId": "🙂" * 200, "reviewedAt": "2000-01-01T00:00:00.000000Z"})
            self.refresh_input_queue(projected_pet)
        serialized = json.dumps(projected, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")
        return len(serialized) + 1 <= MAX_QUESTION_STATE_BYTES

    def observe_input_call(self, pet, payload, observed):
        if payload.get("type") != "function_call" or payload.get("name") != "request_user_input_async" or not observed:
            return
        call_id = payload.get("call_id")
        if not isinstance(call_id, str) or not re.fullmatch(r"call_[A-Za-z0-9_-]{1,80}", call_id):
            return
        history = pet.setdefault("inputCallHistory", {})
        if call_id in history or call_id in pet.get("inputOverflowHistory", {}):
            return
        pruned_before = max(pet.get("questionHistoryPrunedBefore") or "", pet.get("questionOverflowPrunedBefore") or "")
        start = max(pet.get("questionWatchStartedAt") or now_iso(), pruned_before)
        if observed < start or (pruned_before and observed <= pruned_before):
            return
        try:
            arguments = json.loads(payload.get("arguments", ""))
        except (ValueError, TypeError):
            return
        questions = arguments.get("questions") if isinstance(arguments, dict) else None
        if not isinstance(questions, list) or not questions:
            return
        if len(questions) > MAX_INPUT_ITEMS:
            self.input_overflow(pet, "too_many_questions", call_id, observed)
            return
        if any(not isinstance(question, dict) or not isinstance(question.get("title"), str) for question in questions):
            return
        if sum(1 for call in history.values() if call["status"] not in TERMINAL_INPUT_STATUSES) >= MAX_PENDING_INPUT_CALLS:
            self.input_overflow(pet, "too_many_calls", call_id, observed)
            return
        items = [{"index": index, "questionItemId": json.dumps(["request_user_input_async", call_id, index], separators=(",", ":")),
                  "text": (question["title"][:1199] + "…" if len(question["title"]) > 1200 else question["title"]) or "A question in Codex needs your reply.",
                  "questionDigest": hashlib.sha256(question["title"].encode("utf-8")).hexdigest(), "answered": False} for index, question in enumerate(questions)]
        candidate = copy.deepcopy(pet)
        candidate["inputCallHistory"][call_id] = {"callId": call_id, "observedAt": observed, "status": "awaiting_reply", "items": items}
        self.refresh_input_queue(candidate)
        if not self.question_candidate_fits(pet, candidate):
            self.input_overflow(pet, "state_payload_budget", call_id, observed)
            return
        pet.update(candidate)
        self.apply_deferred_input_replies(pet, call_id)
        if not pet.get("sourceUpdatedAt") or observed > pet["sourceUpdatedAt"]:
            pet["sourceUpdatedAt"] = observed
            pet["sourceStatus"] = "connected"
        self.changed = True

    def observe_input_reply(self, pet, item, observed):
        """Parse exact envelopes in first-class text blocks, never prose substrings.

        A reply can arrive on another source shard before its question call. Retain
        bounded identity/digest facts for later correlation, never answer contents.
        """
        content = item.get("content")
        if not isinstance(content, list) or not observed or not isinstance(item.get("id"), str) or not 1 <= len(item["id"]) <= 200:
            return False
        if not isinstance(item.get("client_id"), str) or not item["client_id"]:
            return False
        opening, closing = "<send_user_message_question_reply>", "</send_user_message_question_reply>"
        replies = []
        for block in content:
            if not isinstance(block, dict) or block.get("type") != "text":
                continue
            text = block.get("text")
            if not isinstance(text, str) or len(text) > MAX_LINE_BYTES:
                continue
            text = text.strip()
            if not text.startswith(opening) or not text.endswith(closing):
                continue
            try:
                parsed = json.loads(text[len(opening):-len(closing)].strip())
            except ValueError:
                continue
            if isinstance(parsed, list):
                replies.extend(parsed)
            if len(replies) > MAX_INPUT_ITEMS * MAX_PENDING_INPUT_CALLS:
                self.input_overflow(pet, "too_many_reply_items")
                return True
        recognized = False
        for reply in replies:
            if not isinstance(reply, dict) or set(reply) != {"questionItemId", "question", "answer"}:
                continue
            try:
                identity = json.loads(reply["questionItemId"])
            except (ValueError, TypeError):
                continue
            if not isinstance(identity, list) or len(identity) != 3 or identity[0] != "request_user_input_async":
                continue
            call_id, index = identity[1:]
            if not isinstance(call_id, str) or not re.fullmatch(r"call_[A-Za-z0-9_-]{1,80}", call_id) or isinstance(index, bool) or not isinstance(index, int) or not 0 <= index < MAX_INPUT_ITEMS:
                continue
            if not isinstance(reply["question"], str) or not isinstance(reply["answer"], str) or not reply["answer"].strip():
                continue
            recognized = True
            fact = {"callId": call_id, "index": index, "questionDigest": hashlib.sha256(reply["question"].encode("utf-8")).hexdigest(),
                    "observedAt": observed, "sourceUserMessageId": item["id"]}
            if call_id in pet.get("inputOverflowHistory", {}):
                continue
            call = pet.get("inputCallHistory", {}).get(call_id)
            if not call:
                self.defer_input_reply(pet, fact)
                continue
            self.match_input_reply(pet, fact)
        return recognized

    def defer_input_reply(self, pet, fact):
        if fact["observedAt"] < (pet.get("questionWatchStartedAt") or "") or fact["observedAt"] <= (pet.get("inputReplyPrunedBefore") or ""):
            return
        deferred = pet.setdefault("deferredInputReplies", [])
        if any(entry["callId"] == fact["callId"] and entry["index"] == fact["index"] and entry["sourceUserMessageId"] == fact["sourceUserMessageId"] for entry in deferred):
            return
        if len(deferred) >= MAX_DEFERRED_INPUT_REPLIES:
            # Keep a visible reconciliation gate if more delivery metadata arrives
            # than can be retained. Do not pretend those replies were correlated.
            self.input_overflow(pet, "deferred_reply_limit")
            pet["inputReplyPrunedBefore"] = max(pet.get("inputReplyPrunedBefore") or "", fact["observedAt"])
            return
        deferred.append(fact)
        self.changed = True

    def match_input_reply(self, pet, fact):
        call = pet.get("inputCallHistory", {}).get(fact["callId"])
        if not call or call["status"] in TERMINAL_INPUT_STATUSES or fact["observedAt"] < call["observedAt"]:
            return
        index = fact["index"]
        if not 0 <= index < len(call["items"]):
            return
        expected = call["items"][index]
        expected_digest = expected.get("questionDigest") or hashlib.sha256(expected["text"].encode("utf-8")).hexdigest()
        if fact["questionDigest"] != expected_digest or expected["answered"]:
            return
        expected.update({"answered": True, "answeredAt": fact["observedAt"], "answerSource": "question-card",
                         "sourceUserMessageId": fact["sourceUserMessageId"]})
        call["status"] = "awaiting_review" if all(question["answered"] for question in call["items"]) else "awaiting_reply"
        self.refresh_input_queue(pet)
        if not pet.get("sourceUpdatedAt") or fact["observedAt"] > pet["sourceUpdatedAt"]:
            pet["sourceUpdatedAt"] = fact["observedAt"]
            pet["sourceStatus"] = "connected"
        self.changed = True

    def apply_deferred_input_replies(self, pet, call_id):
        remaining = []
        for fact in pet.get("deferredInputReplies", []):
            if fact["callId"] == call_id:
                self.match_input_reply(pet, fact)
            else:
                remaining.append(fact)
        pet["deferredInputReplies"] = remaining

    def classify_question(self, pet, classification):
        if not isinstance(classification, dict) or set(classification) != {"id", "purpose", "optional"} or classification.get("purpose") != "setup" or classification.get("optional") is not True:
            raise BridgeError("classifyQuestion must identify an explicitly optional setup question.")
        current = pet.get("question")
        if not current or current["id"] != classification["id"]:
            raise BridgeError("Classification must match the current question id.")
        current.update({"purpose": "setup", "optional": True})
        if current.get("origin") == "codex-input-tool":
            call = pet.get("inputCallHistory", {}).get(current.get("callId"))
            if not call or call["status"] in TERMINAL_INPUT_STATUSES:
                raise BridgeError("This observed question is no longer pending.")
            call.update({"purpose": "setup", "optional": True})
        self.refresh_input_queue(pet)

    def cancel_question(self, pet, question_id, reason, source_user_message_id=None, from_pet=False, refresh=True):
        current = pet.get("question")
        if not current or current["id"] != question_id:
            raise BridgeError("Cancellation must match the current question id.")
        if not isinstance(reason, str) or reason not in CANCELLATION_REASONS:
            raise BridgeError("Unknown cancellationReason.")
        if reason == "setup_deferred" and not (current.get("purpose") == "setup" and current.get("optional") is True):
            raise BridgeError("Only an explicitly optional setup question can be deferred.")
        observed = current.get("observedAt") or pet.get("questionObservedAt") or pet.get("reportObservedAt")
        if not from_pet:
            latest = pet.get("requestObservedAt")
            if not source_user_message_id or source_user_message_id != pet.get("requestMessageId") or not latest or not observed or latest <= observed:
                raise BridgeError("Cancellation requires the latest root user message id observed after this question.")
        outcome = {"id": question_id, "status": "cancelled", "observedAt": observed, "cancelledAt": now_iso(),
                   "cancellationReason": reason, "source": "pet" if from_pet else "root-user-message"}
        if source_user_message_id:
            outcome["sourceUserMessageId"] = source_user_message_id
        for field in ("purpose", "optional"):
            if field in current:
                outcome[field] = current[field]
        if current.get("origin") == "codex-input-tool":
            call = pet.get("inputCallHistory", {}).get(current.get("callId"))
            if not call or call["status"] in TERMINAL_INPUT_STATUSES:
                raise BridgeError("This observed question is no longer pending.")
            outcome["questionCount"] = len(call["items"])
            outcome["answeredCount"] = sum(1 for item in call["items"] if item["answered"])
            pet["inputCallHistory"][call["callId"]] = dict(outcome, callId=call["callId"], observedAt=call["observedAt"])
        else:
            outcomes = pet.setdefault("questionOutcomes", {})
            outcomes[question_id] = outcome
            for key in sorted(outcomes, key=lambda key: outcomes[key]["cancelledAt"])[:-MAX_INPUT_TOMBSTONES]:
                del outcomes[key]
            if current.get("origin") == "codex-input-limit":
                pet["questionOverflow"] = None
        pet["question"] = None
        if refresh:
            self.refresh_input_queue(pet)

    def defer_setup(self, request):
        pet = self.require_pet(validate_id(request.get("id")))
        generation = request.get("generation")
        if isinstance(generation, bool) or not isinstance(generation, int) or generation != pet["generation"]:
            raise BridgeError("A current Pet generation is required to defer setup.")
        updated = copy.deepcopy(pet)
        self.cancel_question(updated, request.get("questionId"), "setup_deferred", from_pet=True)
        updated["roadmapNeedsUpdate"] = True
        updated["phase"] = "waiting" if updated.get("question") else "planning"
        pet.update(updated)
        self.changed = True

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
        if "resolveQuestionId" in report and "cancelQuestionId" in report:
            raise BridgeError("Choose either resolveQuestionId or cancelQuestionId, not both.")
        if "reviewFeedback" in report:
            if "cancelQuestionId" in report:
                raise BridgeError("Feedback review cannot be combined with cancellation.")
            if "resolveQuestionId" not in report and set(report) - {"generation", "sequence", "reviewFeedback"}:
                raise BridgeError("Feedback-only review cannot change phase, progress, or other report fields.")
            if "resolveQuestionId" in report and not ("steps" in report and "currentStep" in report):
                raise BridgeError("Resolving reviewed feedback requires the complete roadmap and currentStep.")
        if any(field in report for field in ("cancellationReason", "sourceUserMessageId")) and "cancelQuestionId" not in report:
            raise BridgeError("Cancellation metadata requires cancelQuestionId.")
        transition_id = report.get("resolveQuestionId", report.get("cancelQuestionId"))
        if pet["question"] and transition_id != pet["question"]["id"]:
            if any(key in report for key in ("steps", "currentStep", "currentStepId", "planRevision")) or report.get("phase", "waiting") != "waiting":
                raise BridgeError("Resolve the pending question by id before updating progress or continuing work.")
        updated = copy.deepcopy(pet)
        if "reviewFeedback" in report:
            self.review_feedback(updated, report["reviewFeedback"])
        if "classifyQuestion" in report:
            self.classify_question(updated, report["classifyQuestion"])
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
        if "currentStepId" in report:
            updated["currentStepId"] = self.pending_step_id(report["currentStepId"], updated["steps"], "currentStepId")
        elif updated.get("currentStepId") and not any(step["id"] == updated["currentStepId"] and not step["done"] for step in updated["steps"]):
            updated["currentStepId"] = None
        if "phase" in report:
            if report["phase"] not in PHASES:
                raise BridgeError("Unknown phase.")
            updated["phase"] = report["phase"]
        if "cancelQuestionId" in report:
            if not ("steps" in report and "currentStep" in report):
                raise BridgeError("Cancellation requires a complete roadmap review with steps and currentStep.")
            self.cancel_question(updated, report["cancelQuestionId"], report.get("cancellationReason"),
                                 source_user_message_id=report.get("sourceUserMessageId"), refresh=False)
            if "phase" not in report:
                updated["phase"] = "planning"
        if "resolveQuestionId" in report:
            current = updated.get("question")
            if not current or current["id"] != report["resolveQuestionId"]:
                raise BridgeError("Question resolution must match the pending question id.")
            if current.get("origin") in ("codex-input-tool", "codex-input-limit"):
                if not ("steps" in report and "currentStep" in report):
                    raise BridgeError("Review the complete roadmap with steps and currentStep before resolving an observed question.")
                if current["origin"] == "codex-input-tool":
                    call = updated.get("inputCallHistory", {}).get(current.get("callId"))
                    if not call or call["status"] != "awaiting_review" or not all(item["answered"] for item in call["items"]):
                        hint = "Every question in this tool call needs a correlated user reply or an explicitly verified chat answer before resolution."
                        if updated.get("feedback"):
                            hint += (" A user message is awaiting review: read it in Codex, then use reviewFeedback with this questionId, "
                                     "feedback.sourceUserMessageId, and only the answeredItemIndexes you verified ([] for a non-answer). "
                                     "See integrations/codex/pm-pet/references/report-contract.md#ordinary-chat-feedback.")
                        raise BridgeError(hint)
                    outcome = {"callId": call["callId"], "observedAt": call["observedAt"],
                               "status": "resolved", "resolvedAt": now_iso()}
                    reviewed_count = sum(item.get("answerSource") == "main-agent-review" for item in call["items"])
                    if reviewed_count:
                        outcome.update({"resolutionSource": "main-agent-review" if reviewed_count == len(call["items"]) else "mixed",
                                        "reviewedItemCount": reviewed_count})
                    updated["inputCallHistory"][call["callId"]] = outcome
                else:
                    updated["questionOverflow"] = None
            updated["question"] = None
            if "phase" not in report:
                updated["phase"] = "idle"
        if "question" in report:
            question = report["question"]
            if not isinstance(question, dict):
                raise BridgeError("Use resolveQuestionId to clear a question; question must be an object.")
            if set(question) - {"id", "text", "kind", "destination", "stepId", "purpose", "optional"}:
                raise BridgeError("Question accepts reminder metadata only, not input values or answers.")
            question_id = self.clean_text(question.get("id"), "question id", 100)
            if updated["question"] and updated["question"]["id"] != question_id:
                raise BridgeError("Resolve the current question by id before replacing it.")
            if updated["question"] and updated["question"].get("origin") == "codex-input-tool":
                raise BridgeError("Observed tool questions cannot be overwritten by a manual question report.")
            if question_id.startswith("input:") or question_id == "input-queue-overflow":
                raise BridgeError("Observed input question ids are reserved for the transcript adapter.")
            kind = question.get("kind", "decision")
            destination = question.get("destination", "codex")
            if not isinstance(kind, str) or kind not in QUESTION_KINDS:
                raise BridgeError("Question kind must be decision or input.")
            if not isinstance(destination, str) or destination not in QUESTION_DESTINATIONS:
                raise BridgeError("Question destination must be codex, system, or terminal.")
            normalized = {"id": question_id, "text": self.clean_text(question.get("text"), "question text", 1200),
                          "kind": kind, "destination": destination}
            if "purpose" in question or "optional" in question:
                if question.get("purpose") != "setup" or not isinstance(question.get("optional", False), bool):
                    raise BridgeError("Optional setup metadata requires purpose setup and a boolean optional value.")
                normalized.update({"purpose": "setup", "optional": question.get("optional", False)})
            if "stepId" in question:
                normalized["stepId"] = self.pending_step_id(question["stepId"], updated["steps"], "question stepId")
            if not updated["question"] or updated["question"]["id"] != question_id:
                updated["questionObservedAt"] = now_iso()
            updated["question"] = normalized
        self.refresh_input_queue(updated)
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
        elif action == "defer_setup":
            self.defer_setup(request)
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

    def remember_turn_end(self, pet, turn_id, status, observed):
        pending = pet.setdefault("pendingTurnEnds", [])
        old = next((item for item in pending if item["turnId"] == turn_id), None)
        if old and old["observedAt"] >= observed:
            return
        pending[:] = [item for item in pending if item["turnId"] != turn_id]
        pending.append({"turnId": turn_id, "status": status, "observedAt": observed})
        pending.sort(key=lambda item: (item["observedAt"], item["turnId"]))
        del pending[:-MAX_PENDING_TURN_ENDS]
        self.changed = True

    def observe_turn_state(self, pet, event_type, payload, observed):
        """Observe root turn activity separately from the report/question gate.

        Report timestamps cannot hide a delayed lifecycle event. Turn identity and
        this independent event clock keep old completions from overwriting newer
        input or a newer turn; no lifecycle observation resolves a question.
        """
        statuses = {"task_started": "running", "task_complete": "ended",
                    "turn_aborted": "interrupted", "user_message": "input_received"}
        if not observed or event_type not in statuses:
            return False
        turn_id = payload.get("turn_id")
        if turn_id is not None and (not isinstance(turn_id, str) or not turn_id.strip() or len(turn_id) > 200):
            return False
        current = pet.get("turnState") or {}
        current_id, previous_at = current.get("turnId"), current.get("observedAt")
        same_turn = bool(turn_id and current_id == turn_id)
        # A new turn's start may be discovered after its user message on another
        # shard. Matching identity lets that older start fill in running status.
        delayed_start = event_type == "task_started" and same_turn and current.get("status") == "input_received"
        if previous_at and observed < previous_at and not delayed_start:
            return False
        if event_type in ("task_complete", "turn_aborted"):
            if current_id and turn_id != current_id:
                if turn_id:
                    self.remember_turn_end(pet, turn_id, statuses[event_type], observed)
                return False
            if current.get("status") == "input_received" and not same_turn:
                if current_id is None and turn_id is None:
                    # Legacy unscoped lifecycle can retain its existing phase
                    # behavior, but cannot prove this new input's turn has ended.
                    return True
                if turn_id:
                    self.remember_turn_end(pet, turn_id, statuses[event_type], observed)
                return False
        if event_type == "task_started":
            if same_turn and current.get("status") in ("ended", "interrupted") and observed <= previous_at:
                return False
            if current_id and turn_id != current_id and previous_at and observed <= previous_at:
                return False
        if event_type == "user_message" and same_turn and current.get("status") in ("ended", "interrupted") and observed <= (current.get("inputObservedAt") or ""):
            return False
        status = statuses[event_type]
        if event_type == "user_message" and current.get("status") == "running" and (same_turn or (turn_id is None and current_id is None)):
            status = "running"
        result = {"status": status, "observedAt": max(observed, previous_at or "")}
        if turn_id:
            result["turnId"] = turn_id
        if event_type == "user_message":
            result["inputObservedAt"] = observed
        elif same_turn and current.get("inputObservedAt"):
            result["inputObservedAt"] = current["inputObservedAt"]
        # A matching end may already have arrived from another source shard.
        # Apply it only after the current turn's identity is independently known.
        pending = pet.get("pendingTurnEnds", [])
        terminal = next((item for item in pending if item["turnId"] == turn_id and item["observedAt"] >= result["observedAt"]), None) if turn_id else None
        if terminal:
            result.update({"status": terminal["status"], "observedAt": terminal["observedAt"]})
        if pending:
            retained = [item for item in pending if item["observedAt"] > result["observedAt"]]
            if retained != pending:
                pet["pendingTurnEnds"] = retained
                self.changed = True
        if result != current:
            pet["turnState"] = result
            self.changed = True
        return True

    def apply_event(self, pet, event):
        kind = event.get("type")
        payload = event.get("payload") or {}
        if not isinstance(payload, dict):
            return
        event_type = payload.get("type")
        observed = timestamp(event.get("timestamp"))
        event_owner = payload.get("thread_id")
        if event_owner and event_owner != pet["id"]:
            return
        if kind == "response_item":
            self.observe_input_call(pet, payload, observed)
            return
        if kind != "event_msg":
            return
        if event_type in ("task_started", "task_complete", "turn_aborted"):
            if not self.observe_turn_state(pet, event_type, payload, observed):
                return
        if event_type == "token_count":
            self.observe_quota(pet, quota_snapshot(payload.get("rate_limits"), observed))
            return
        if event_type == "item_completed":
            item = payload.get("item") or {}
            if event_owner == pet["id"]:
                self.observe_quota(pet, desktop_quota_snapshot(item, observed))
            if isinstance(item, dict) and item.get("type") == "UserMessage":
                # Only a first-class user item explicitly owned by this root binding qualifies.
                # No message content, quoted tool output, or child message is interpreted.
                request_id = item.get("id")
                if event_owner != pet["id"] or not observed or not isinstance(request_id, str) or not request_id:
                    return
                self.observe_turn_state(pet, "user_message", payload, observed)
                if self.observe_input_reply(pet, item, observed):
                    return
                self.observe_feedback_message(pet, item, observed)
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
                if pet.get("currentStepId") and not any(step["id"] == pet["currentStepId"] and not step["done"] for step in steps):
                    pet["currentStepId"] = None
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
            discovery_interval = 2 if pet.get("question") else 30
            if clock - self.last_discovery.get(conversation_id, -1e9) >= discovery_interval:
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
    parser.add_argument("action", choices=("serve", "enable", "disable", "preferences", "report", "status", "defer_setup"))
    parser.add_argument("--runtime", required=True, type=Path)
    parser.add_argument("--conversation")
    parser.add_argument("--title")
    parser.add_argument("--generation", type=int, help="Current binding generation for an explicit setup deferral")
    parser.add_argument("--question-id", help="Current optional setup question id")
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
        if args.action == "defer_setup":
            if args.generation is None or not args.question_id:
                raise BridgeError("defer_setup requires --generation and --question-id from current status.")
            request["generation"] = args.generation
            request["questionId"] = args.question_id
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
