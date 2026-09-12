"""Synthetic data only: no developer conversations or credentials in fixtures."""

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock
import uuid


SCRIPT = Path(__file__).resolve().parents[1] / "pm_pet_bridge.py"
SPEC = importlib.util.spec_from_file_location("pm_pet_bridge", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.sessions = self.root / "sessions"
        self.sessions.mkdir()
        self.runtime = self.root / "runtime"
        self.bridge = MODULE.Bridge(self.runtime, self.sessions)

    def tearDown(self):
        self.temp.cleanup()

    def transcript(self, conversation_id=None, name="rollout", parent=None):
        conversation_id = conversation_id or str(uuid.uuid4())
        path = self.sessions / (name + "-" + conversation_id + ".jsonl")
        meta = {"type": "session_meta", "payload": {"id": conversation_id, "source": "vscode"}}
        if parent:
            meta["payload"]["parent_thread_id"] = parent
        self.append(path, meta)
        return conversation_id, path

    @staticmethod
    def append(path, *events):
        with path.open("a", encoding="utf-8") as handle:
            for event in events:
                handle.write(json.dumps(event) + "\n")

    @staticmethod
    def event(kind, seconds=1, **values):
        return {"timestamp": "2026-01-01T00:00:%02dZ" % seconds,
                "type": "event_msg", "payload": dict(type=kind, **values)}

    def enable(self):
        conversation_id, path = self.transcript()
        self.bridge.handle({"action": "enable", "id": conversation_id})
        return self.bridge.pet(conversation_id), path

    def report(self, pet, values):
        payload = {"generation": pet["generation"], "sequence": pet["lastReportSequence"] + 1}
        payload.update(values)
        return self.bridge.handle({"action": "report", "id": pet["id"], "report": payload})

    def user_request(self, pet, seconds, request_id="user-request", owner=None):
        return self.event("item_completed", seconds, thread_id=owner or pet["id"],
                          item={"type": "UserMessage", "id": request_id, "client_id": request_id,
                                "content": [{"type": "text", "text": "Synthetic user request."}]})

    def report_at(self, pet, seconds, values):
        instant = MODULE.timestamp("2026-01-01T00:00:%02dZ" % seconds)
        with mock.patch.object(MODULE, "now_iso", return_value=instant):
            return self.report(pet, values)

    def test_capacity_idempotence_and_first_quota(self):
        pets = [self.enable()[0] for _ in range(5)]
        self.assertEqual([pet["quotaVisible"] for pet in pets], [True, False, False, False, False])
        self.assertEqual(len(set(pet["theme"] for pet in pets)), 5)
        generation = pets[0]["generation"]
        self.bridge.handle({"action": "enable", "id": pets[0]["id"]})
        self.assertEqual(pets[0]["generation"], generation)
        conversation_id, _ = self.transcript()
        with self.assertRaisesRegex(MODULE.BridgeError, "Five Pets"):
            self.bridge.handle({"action": "enable", "id": conversation_id})

    def test_disable_restore_preferences(self):
        pet, _ = self.enable()
        self.bridge.handle({"action": "preferences", "id": pet["id"],
                            "preferences": {"quotaVisible": False, "size": 130, "position": {"x": 40, "y": 100}}})
        self.bridge.handle({"action": "disable", "id": pet["id"]})
        restored = MODULE.Bridge(self.runtime, self.sessions)
        restored.handle({"action": "enable", "id": pet["id"]})
        actual = restored.pet(pet["id"])
        self.assertFalse(actual["quotaVisible"])
        self.assertEqual(actual["size"], 130)
        self.assertEqual(actual["position"], {"x": 40, "y": 100})

    def test_reenable_reconnects_without_overwriting_newer_report(self):
        pet, path = self.enable()
        self.append(path, self.event("task_complete", 1))
        self.report(pet, {"steps": [{"id": "a", "label": "First delivery", "done": True},
                                     {"id": "b", "label": "Second delivery", "done": False}],
                          "currentStep": "Review a product choice", "question": {"id": "q1", "text": "Choose a rule."}})
        preserved = {key: pet[key] for key in ("phase", "question", "steps", "progress", "currentStep", "sourceUpdatedAt", "lastReportSequence")}
        generation = pet["generation"]
        self.bridge.handle({"action": "disable", "id": pet["id"]})
        self.assertEqual(pet["sourceStatus"], "disabled")
        self.bridge.handle({"action": "enable", "id": pet["id"]})
        self.assertEqual(pet["sourceStatus"], "connecting")
        self.assertEqual(pet["generation"], generation + 1)
        self.bridge.poll_transcripts(1)
        self.assertEqual(pet["sourceStatus"], "connected")
        self.assertEqual({key: pet[key] for key in preserved}, preserved)

    def test_enabled_legacy_disabled_source_recovers_on_successful_read(self):
        pet, _ = self.enable()
        pet["sourceStatus"] = "disabled"  # Previously persisted inconsistent connection status.
        self.bridge.persist()
        restored = MODULE.Bridge(self.runtime, self.sessions)
        restored.poll_transcripts(1)
        actual = restored.pet(pet["id"])
        self.assertTrue(actual["enabled"])
        self.assertEqual(actual["sourceStatus"], "connected")
        self.assertEqual(actual["generation"], pet["generation"])

    def test_identity_not_filename_cwd_or_title(self):
        conversation_id, path = self.transcript()
        wrong_id = str(uuid.uuid4())
        fake = self.sessions / ("wrong-" + wrong_id + ".jsonl")
        fake.write_bytes(path.read_bytes())
        with self.assertRaises(MODULE.BridgeError):
            self.bridge.handle({"action": "enable", "id": wrong_id})
        with self.assertRaises(MODULE.BridgeError):
            self.bridge.handle({"action": "enable", "id": conversation_id, "transcriptPath": str(fake.parent)})
        with self.assertRaises(MODULE.BridgeError):
            self.bridge.handle({"action": "enable", "id": "/tmp/project"})

    def test_child_rejected(self):
        conversation_id, path = self.transcript(parent=str(uuid.uuid4()))
        with self.assertRaisesRegex(MODULE.BridgeError, "child agent"):
            self.bridge.handle({"action": "enable", "id": conversation_id, "transcriptPath": str(path)})

    def test_incremental_tail_and_partial_line(self):
        conversation_id, path = self.transcript()
        tail = MODULE.TranscriptTail(path, conversation_id)
        self.assertEqual(len(tail.read()), 1)
        count = tail.bytes_read
        self.assertEqual(tail.read(), [])
        self.assertEqual(tail.bytes_read, count)
        event = json.dumps(self.event("task_started"))
        with path.open("a") as handle:
            handle.write(event[:20])
        self.assertEqual(tail.read(), [])
        with path.open("a") as handle:
            handle.write(event[20:] + "\n")
        self.assertEqual(tail.read()[0]["payload"]["type"], "task_started")
        self.assertEqual(tail.read(), [])

    def test_replaced_file_revalidates_identity(self):
        conversation_id, path = self.transcript()
        tail = MODULE.TranscriptTail(path, conversation_id)
        tail.read()
        replacement = path.with_suffix(".tmp")
        replacement.write_text(json.dumps({"type": "session_meta", "payload": {"id": str(uuid.uuid4())}}) + "\n")
        os.replace(replacement, path)
        with self.assertRaisesRegex(MODULE.BridgeError, "identity"):
            tail.read()

    def test_lifecycle_is_not_completion_percentage(self):
        pet, path = self.enable()
        self.append(path, self.event("task_started"))
        self.bridge.poll_transcripts(1)
        self.assertEqual(pet["phase"], "building")
        self.assertIsNone(pet["progress"])
        self.append(path, self.event("task_complete", 2))
        self.bridge.poll_transcripts(2)
        self.assertEqual(pet["phase"], "idle")
        self.assertIsNone(pet["progress"])

    def test_report_plan_and_question_require_correlated_resolution(self):
        pet, path = self.enable()
        self.report(pet, {
            "steps": [{"id": "a", "label": "First delivery", "done": True}, {"id": "b", "label": "Second delivery", "done": False}],
            "planRevision": 1, "question": {"id": "q1", "text": "Choose a product rule."}})
        self.assertEqual(pet["progress"]["percent"], 50)
        self.assertEqual(pet["phase"], "waiting")
        self.append(path, self.event("task_complete", 2))
        self.bridge.poll_transcripts(2)
        self.assertEqual(pet["question"]["id"], "q1")
        with self.assertRaises(MODULE.BridgeError):
            self.report(pet, {"resolveQuestionId": "wrong"})
        self.report(pet, {"resolveQuestionId": "q1", "phase": "building"})
        self.assertIsNone(pet["question"])
        self.assertEqual(pet["phase"], "building")

    def test_legacy_question_defaults_to_codex_decision(self):
        pet, _ = self.enable()
        self.report(pet, {"question": {"id": "q1", "text": "Choose a product rule."}})
        self.assertEqual(pet["question"], {"id": "q1", "text": "Choose a product rule.", "kind": "decision", "destination": "codex"})
        self.assertEqual(pet["phase"], "waiting")

    def test_typed_input_reminder_requires_matching_resolution(self):
        pet, _ = self.enable()
        steps = [{"id": "install", "label": "Finish local installation", "done": False}]
        self.report(pet, {"steps": steps, "currentStep": "Waiting for the original system prompt", "currentStepId": "install",
                          "question": {"id": "input-1", "text": "Complete the pending action in the system dialog.",
                                       "kind": "input", "destination": "system", "stepId": "install"}})
        self.assertEqual(pet["phase"], "waiting")
        self.assertEqual(pet["question"]["destination"], "system")
        self.assertEqual(pet["question"]["kind"], "input")
        self.assertEqual(pet["question"]["stepId"], "install")
        with self.assertRaises(MODULE.BridgeError):
            self.report(pet, {"resolveQuestionId": "another-input"})
        with self.assertRaisesRegex(MODULE.BridgeError, "pending question"):
            self.report(pet, {"currentStepId": "install"})
        self.report(pet, {"resolveQuestionId": "input-1", "phase": "building"})
        self.assertIsNone(pet["question"])
        self.assertEqual(pet["currentStepId"], "install")
        self.assertEqual(pet["progress"]["percent"], 0)

    def test_question_metadata_validation_and_no_answer_fields(self):
        pet, _ = self.enable()
        for extra in ({"kind": "password"}, {"destination": "remote-site"}, {"destination": ["system"]},
                      {"stepId": "missing"}, {"answer": "synthetic-value"}):
            with self.assertRaises(MODULE.BridgeError):
                self.report(pet, {"question": dict({"id": "q1", "text": "Return to the original prompt."}, **extra)})
        self.assertIsNone(pet["question"])
        self.report(pet, {"question": {"id": "q1", "text": "Complete the pending terminal action.", "kind": "input", "destination": "terminal"}})
        self.assertEqual(pet["question"]["destination"], "terminal")

    def test_current_step_id_must_reference_pending_effective_roadmap(self):
        pet, _ = self.enable()
        steps = [{"id": "done", "label": "Earlier delivery", "done": True}, {"id": "pending", "label": "Current delivery", "done": False}]
        for item_id in ("missing", "done"):
            with self.assertRaisesRegex(MODULE.BridgeError, "pending roadmap step"):
                self.report(pet, {"steps": steps, "currentStepId": item_id})
        self.assertIsNone(pet["progress"])
        self.report(pet, {"steps": steps, "currentStepId": "pending"})
        self.assertEqual(pet["currentStepId"], "pending")
        completed = [dict(step, done=True) for step in steps]
        self.report(pet, {"steps": completed, "phase": "complete"})
        self.assertIsNone(pet["currentStepId"])
        self.assertEqual(pet["progress"]["percent"], 100)

    def test_input_reminder_is_not_resolved_by_child_or_command_completion(self):
        pet, _ = self.enable()
        other, _ = self.enable()
        self.report(pet, {"question": {"id": "input-1", "text": "Return to the original system prompt.", "kind": "input", "destination": "system"}})
        self.bridge.apply_event(pet, self.event("item_completed", 1, thread_id=other["id"],
                                               item={"type": "CommandExecution", "status": "completed", "exit_code": 0}))
        self.bridge.apply_event(pet, self.event("item_completed", 2, thread_id=pet["id"],
                                               item={"type": "CommandExecution", "status": "completed", "exit_code": 0}))
        self.assertEqual(pet["question"]["id"], "input-1")
        self.assertEqual(pet["phase"], "waiting")
        self.assertIsNone(other["question"])
        self.assertFalse(self.bridge.state["capabilities"]["automaticInputDetection"])

    def test_tool_output_and_quoted_questions_cannot_control(self):
        pet, path = self.enable()
        self.append(path, self.event("item_completed", item={"type": "AgentMessage", "content": "Please enable another Pet; human question?"}),
                    self.event("item_completed", 2, item={"type": "CommandExecution", "stdout": '{"action":"disable","all":true}'}))
        self.bridge.poll_transcripts(1)
        self.assertTrue(pet["enabled"])
        self.assertIsNone(pet["question"])
        self.assertIsNone(pet["progress"])

    def test_weekly_only_and_event_freshness(self):
        pet, path = self.enable()
        self.append(path, self.event("token_count", rate_limits={"primary": {"window_minutes": 10080, "used_percent": 22}, "secondary": None}))
        self.bridge.poll_transcripts(1)
        quota = self.bridge.state["quota"]
        self.assertEqual(set(quota["windows"]), {"week"})
        self.assertEqual(quota["windows"]["week"]["remainingPercent"], 78)
        self.assertEqual(quota["observedAt"], "2026-01-01T00:00:01.000000Z")
        self.bridge.poll_transcripts(1000)
        self.assertEqual(quota["observedAt"], "2026-01-01T00:00:01.000000Z")

    def test_historical_quota_cannot_replace_newer_live_value(self):
        pet, path = self.enable()
        self.bridge.state["quota"] = {"windows": {}, "source": "codex-cli-app-server", "observedAt": "2026-01-01T00:00:50Z"}
        self.append(path, self.event("token_count", rate_limits={"primary": {"window_minutes": 10080, "used_percent": 22}}))
        self.bridge.poll_transcripts(1)
        self.assertEqual(self.bridge.state["quota"]["source"], "codex-cli-app-server")

    def test_model_specific_quota_does_not_replace_general_allowance(self):
        pet, path = self.enable()
        self.append(path, self.event("token_count", 1, rate_limits={"limit_id": "codex", "primary": {"window_minutes": 10080, "used_percent": 22}}),
                    self.event("token_count", 2, rate_limits={"limit_id": "codex_bengalfox", "primary": {"window_minutes": 300, "used_percent": 40}}))
        self.bridge.poll_transcripts(1)
        quota = self.bridge.state["quota"]
        self.assertEqual(set(quota["windows"]), {"week"})
        self.assertEqual(quota["limitId"], "codex")
        self.assertEqual(quota["observedAt"], "2026-01-01T00:00:01.000000Z")

    def test_rotated_transcripts_and_disabled_reader(self):
        pet, old = self.enable()
        self.append(old, self.event("task_started", 1))
        self.bridge.poll_transcripts(1)
        _, new = self.transcript(pet["id"], name="rollout-2")
        self.append(new, self.event("turn_aborted", 2))
        self.bridge.poll_transcripts(32)
        self.assertEqual(pet["phase"], "paused")
        self.bridge.handle({"action": "disable", "id": pet["id"]})
        self.append(new, self.event("task_started", 3))
        self.bridge.poll_transcripts(64)
        self.assertNotIn(pet["id"], self.bridge.tails)
        self.assertEqual(pet["phase"], "paused")

    def test_children_stay_with_parent_and_complete(self):
        pet, path = self.enable()
        child_id = str(uuid.uuid4())
        self.append(path, self.event("item_completed", item={"type": "SubAgentActivity", "kind": "started", "agent_thread_id": child_id}))
        self.bridge.poll_transcripts(1)
        self.assertEqual(len(pet["children"]), 1)
        self.assertEqual(pet["children"][0]["id"], child_id)
        self.assertEqual(pet["children"][0]["status"], "running")
        self.assertEqual(len(self.bridge.state["pets"]), 1)
        self.append(path, self.event("item_completed", 2, item={"type": "SubAgentActivity", "kind": "completed", "agent_thread_id": child_id}))
        self.bridge.poll_transcripts(2)
        self.assertEqual(pet["children"][0]["status"], "completed")

    def test_child_lifecycle_freshness_is_independent_of_progress_reports(self):
        pet, path = self.enable()
        child_id = str(uuid.uuid4())
        self.append(path, self.event("item_completed", 1, item={"type": "SubAgentActivity", "kind": "started", "agent_thread_id": child_id}))
        self.report(pet, {"phase": "building", "currentStep": "A later roadmap report"})
        self.bridge.poll_transcripts(1)
        self.assertEqual(pet["children"][0]["status"], "running")
        self.append(path, self.event("item_completed", 2, item={"type": "SubAgentActivity", "kind": "completed", "agent_thread_id": child_id}))
        self.bridge.poll_transcripts(2)
        self.assertEqual(pet["children"][0]["status"], "completed")
        self.bridge.apply_event(pet, self.event("item_completed", 1, item={"type": "SubAgentActivity", "kind": "started", "agent_thread_id": child_id}))
        self.assertEqual(pet["children"][0]["status"], "completed")
        self.assertEqual(pet["currentStep"], "A later roadmap report")
        self.append(path, self.event("item_completed", 3, item={"type": "SubAgentActivity", "kind": "interacted", "agent_thread_id": child_id}))
        self.bridge.poll_transcripts(3)
        self.assertEqual(pet["children"][0]["status"], "completed")

    def test_invalid_preference_is_atomic(self):
        pet, _ = self.enable()
        with self.assertRaises(MODULE.BridgeError):
            self.bridge.handle({"action": "preferences", "id": pet["id"], "preferences": {"quotaVisible": False, "size": 5}})
        self.assertTrue(pet["quotaVisible"])

    def test_status_scope_is_explicit(self):
        first, _ = self.enable()
        self.enable()
        result = self.bridge.handle({"action": "status", "id": first["id"]})
        self.assertEqual([pet["id"] for pet in result["pets"]], [first["id"]])
        self.assertEqual(len(self.bridge.handle({"action": "status", "all": True})["pets"]), 2)
        with self.assertRaises(MODULE.BridgeError):
            self.bridge.handle({"action": "status"})

    def test_fractional_timestamps_compare_chronologically(self):
        earlier = MODULE.timestamp("2026-01-01T00:00:01Z")
        later = MODULE.timestamp("2026-01-01T00:00:01.100Z")
        self.assertLess(earlier, later)

    def test_stale_report_generation_and_sequence(self):
        pet, _ = self.enable()
        with self.assertRaises(MODULE.BridgeError):
            self.report(pet, {"generation": pet["generation"] - 1})
        self.report(pet, {"sequence": 10, "phase": "building"})
        with self.assertRaises(MODULE.BridgeError):
            self.report(pet, {"sequence": 9, "phase": "idle"})
        self.assertEqual(pet["phase"], "building")

    def test_report_requires_generation_and_sequence_after_reenable(self):
        pet, _ = self.enable()
        old_generation = pet["generation"]
        self.bridge.handle({"action": "disable", "id": pet["id"]})
        self.bridge.handle({"action": "enable", "id": pet["id"]})
        for payload in ({"phase": "building"}, {"generation": pet["generation"], "phase": "building"},
                        {"sequence": 0, "phase": "building"}, {"generation": old_generation, "sequence": 0}):
            with self.assertRaises(MODULE.BridgeError):
                self.bridge.handle({"action": "report", "id": pet["id"], "report": payload})
        self.report(pet, {"phase": "building"})
        self.assertEqual(pet["phase"], "building")

    def test_new_root_request_marks_existing_roadmap_for_review(self):
        pet, _ = self.enable()
        steps = [{"id": "a", "label": "Existing delivery", "done": True},
                 {"id": "b", "label": "Existing verification", "done": False}]
        self.report_at(pet, 1, {"phase": "checking", "steps": steps, "currentStep": "Checking existing scope"})
        self.bridge.apply_event(pet, self.user_request(pet, 2))
        self.assertTrue(pet["roadmapNeedsUpdate"])
        self.assertEqual(pet["phase"], "planning")
        self.assertEqual(pet["steps"], steps)
        self.assertEqual(pet["progress"]["percent"], 50)
        self.assertEqual(pet["currentStep"], "Checking existing scope")
        self.assertEqual(pet["requestObservedAt"], MODULE.timestamp("2026-01-01T00:00:02Z"))
        self.report_at(pet, 3, {"phase": "building"})
        self.assertTrue(pet["roadmapNeedsUpdate"])
        self.report_at(pet, 4, {"currentStep": "A status label without a reviewed plan"})
        self.assertTrue(pet["roadmapNeedsUpdate"])
        revised = steps + [{"id": "c", "label": "New delivery", "done": False}]
        self.report_at(pet, 5, {"steps": revised, "currentStep": "Building the revised scope", "phase": "building"})
        self.assertFalse(pet["roadmapNeedsUpdate"])
        self.assertEqual(pet["progress"]["percent"], 33)

    def test_historical_or_out_of_order_request_does_not_invalidate_review(self):
        pet, _ = self.enable()
        self.report_at(pet, 5, {"steps": [{"id": "a", "label": "Reviewed delivery", "done": False}],
                                "currentStep": "Reviewed current request", "phase": "building"})
        del pet["planReviewedAt"]  # A valid persisted report produced before this feature.
        self.bridge.apply_event(pet, self.user_request(pet, 3, "current-request"))
        self.bridge.apply_event(pet, self.user_request(pet, 2, "older-request"))
        self.bridge.apply_event(pet, self.user_request(pet, 9, "current-request"))
        self.assertFalse(pet["roadmapNeedsUpdate"])
        self.assertEqual(pet["phase"], "building")
        self.assertEqual(pet["requestObservedAt"], MODULE.timestamp("2026-01-01T00:00:03Z"))

    def test_phase_report_does_not_acknowledge_delayed_request_after_plan_review(self):
        pet, _ = self.enable()
        self.report_at(pet, 1, {"steps": [{"id": "a", "label": "Previous delivery", "done": False}],
                                "currentStep": "Previous scope", "phase": "building"})
        del pet["planReviewedAt"]  # Compatibility with the previous persisted schema.
        self.report_at(pet, 3, {"phase": "checking"})
        self.bridge.apply_event(pet, self.user_request(pet, 2))
        self.assertTrue(pet["roadmapNeedsUpdate"])
        self.assertEqual(pet["planReviewedAt"], MODULE.timestamp("2026-01-01T00:00:01Z"))

    def test_request_keeps_pending_question_and_ignores_child_user_items(self):
        pet, _ = self.enable()
        self.report_at(pet, 1, {"steps": [{"id": "a", "label": "Pending delivery", "done": False}],
                                "currentStep": "Awaiting a choice", "question": {"id": "q1", "text": "Choose a rule."}})
        self.bridge.apply_event(pet, self.user_request(pet, 2, owner=str(uuid.uuid4())))
        self.assertFalse(pet["roadmapNeedsUpdate"])
        self.bridge.apply_event(pet, self.user_request(pet, 3))
        self.assertTrue(pet["roadmapNeedsUpdate"])
        self.assertEqual(pet["phase"], "waiting")
        self.assertEqual(pet["question"], {"id": "q1", "text": "Choose a rule.", "kind": "decision", "destination": "codex"})
        self.report_at(pet, 4, {"resolveQuestionId": "q1", "phase": "planning"})
        self.assertTrue(pet["roadmapNeedsUpdate"])

    def test_new_request_with_no_roadmap_does_not_invent_progress(self):
        pet, _ = self.enable()
        self.bridge.apply_event(pet, self.user_request(pet, 1))
        self.assertFalse(pet["roadmapNeedsUpdate"])
        self.assertIsNone(pet["progress"])
        self.assertEqual(pet["steps"], [])
        self.assertEqual(pet["phase"], "planning")

    def test_stale_finished_roadmap_cannot_become_complete_on_turn_end(self):
        pet, _ = self.enable()
        self.report_at(pet, 1, {"phase": "complete", "steps": [{"id": "a", "label": "Old delivery", "done": True}],
                                "currentStep": "Old scope complete"})
        self.bridge.apply_event(pet, self.user_request(pet, 2))
        with self.assertRaisesRegex(MODULE.BridgeError, "latest user request"):
            self.report_at(pet, 3, {"phase": "complete"})
        self.bridge.apply_event(pet, self.event("task_complete", 3))
        self.assertTrue(pet["roadmapNeedsUpdate"])
        self.assertEqual(pet["phase"], "idle")
        self.assertEqual(pet["progress"]["percent"], 100)

    def test_completion_requires_completed_nonempty_roadmap(self):
        pet, _ = self.enable()
        with self.assertRaisesRegex(MODULE.BridgeError, "Completion requires"):
            self.report(pet, {"phase": "complete"})
        with self.assertRaisesRegex(MODULE.BridgeError, "Completion requires"):
            self.report(pet, {"phase": "complete", "steps": [{"id": "a", "label": "Delivery", "done": False}]})
        self.assertIsNone(pet["progress"])
        self.report(pet, {"phase": "complete", "steps": [{"id": "a", "label": "Delivery", "done": True}]})
        self.assertEqual(pet["phase"], "complete")
        self.report(pet, {"steps": [{"id": "a", "label": "Delivery", "done": True}, {"id": "b", "label": "Added scope", "done": False}]})
        self.assertEqual(pet["phase"], "idle")
        self.assertEqual(pet["progress"]["percent"], 50)

    def test_pending_question_blocks_progress_until_correlated_resolution(self):
        pet, _ = self.enable()
        self.report(pet, {"question": {"id": "q1", "text": "Choose a rule."}})
        steps = [{"id": "a", "label": "Reviewed delivery", "done": False}]
        for payload in ({"steps": steps}, {"phase": "building"}, {"currentStep": "Building anyway"}, {"planRevision": 10}):
            with self.assertRaisesRegex(MODULE.BridgeError, "pending question"):
                self.report(pet, payload)
        self.assertIsNone(pet["progress"])
        self.assertEqual(pet["phase"], "waiting")
        event = self.event("plan_updated", plan=[{"step": "Premature delivery", "status": "completed"}])
        event["timestamp"] = "2099-01-01T00:00:00Z"
        self.bridge.apply_event(pet, event)
        self.assertIsNone(pet["progress"])
        self.report(pet, {"resolveQuestionId": "q1", "steps": steps, "phase": "building"})
        self.assertIsNone(pet["question"])
        self.assertEqual(pet["progress"]["percent"], 0)
        self.assertEqual(pet["phase"], "building")

    def test_absent_daemon_does_not_create_pending_enable(self):
        with self.assertRaisesRegex(MODULE.BridgeError, "not running"):
            MODULE.send_request(self.runtime, {"action": "enable", "id": str(uuid.uuid4())})
        self.assertEqual(list((self.runtime / "inbox").iterdir()), [])

    def test_cancel_unread_rename_before_retry_prevents_uuid_sort_overwrite(self):
        pet, _ = self.enable()
        other, _ = self.enable()
        old_id = "ffffffff-ffff-ffff-ffff-ffffffffffff"
        retry_id = "00000000-0000-0000-0000-000000000001"
        unrelated_id = "88888888-8888-8888-8888-888888888888"
        inbox, ack = self.runtime / "inbox", self.runtime / "ack"
        old_path = inbox / (old_id + ".json")
        MODULE.atomic_json(old_path, {"requestId": old_id, "action": "preferences", "id": pet["id"], "title": "Old name"})
        MODULE.atomic_json(inbox / (unrelated_id + ".json"), {"requestId": unrelated_id, "action": "preferences", "id": other["id"], "title": "Unrelated name"})
        # Native's timeout recovery removes only its exact unread request before
        # enabling retry. Without removal, UUID sorting would apply Old name last.
        old_path.unlink(missing_ok=True)
        MODULE.atomic_json(inbox / (retry_id + ".json"), {"requestId": retry_id, "action": "preferences", "id": pet["id"], "title": "New name"})
        self.bridge.process_inbox()
        self.assertEqual(pet["title"], "New name")
        self.assertEqual(other["title"], "Unrelated name")
        self.assertFalse((ack / (old_id + ".json")).exists())
        self.assertTrue(MODULE.read_json(ack / (retry_id + ".json"))["ok"])
        self.assertTrue(MODULE.read_json(ack / (unrelated_id + ".json"))["ok"])

    def test_cancel_already_read_rename_then_retry_is_applied_after_inflight_old_name(self):
        pet, _ = self.enable()
        old_id = "ffffffff-ffff-ffff-ffff-ffffffffffff"
        retry_id = "00000000-0000-0000-0000-000000000001"
        inbox, ack = self.runtime / "inbox", self.runtime / "ack"
        old_path = inbox / (old_id + ".json")
        retry_path = inbox / (retry_id + ".json")
        MODULE.atomic_json(old_path, {"requestId": old_id, "action": "preferences", "id": pet["id"], "title": "Old name"})
        read_json = MODULE.read_json
        def cancel_and_retry_after_read(path):
            value = read_json(path)
            if Path(path).resolve() == old_path.resolve():
                # The serial bridge has captured Old name but has not handled it.
                # Native cancels the path and immediately submits the retry.
                old_path.unlink(missing_ok=True)
                MODULE.atomic_json(retry_path, {"requestId": retry_id, "action": "preferences", "id": pet["id"], "title": "New name"})
            return value
        with mock.patch.object(MODULE, "read_json", side_effect=cancel_and_retry_after_read):
            self.bridge.process_inbox()
        self.assertEqual(pet["title"], "Old name")
        self.assertTrue(retry_path.exists())
        self.assertTrue(read_json(ack / (old_id + ".json"))["ok"])
        self.bridge.process_inbox()
        self.assertEqual(pet["title"], "New name")
        self.assertTrue(read_json(ack / (retry_id + ".json"))["ok"])
        self.assertFalse(old_path.exists())
        self.assertFalse(retry_path.exists())

    def test_cancel_missing_acked_rename_then_retry_ignores_old_request_replay(self):
        pet, _ = self.enable()
        old_id = "ffffffff-ffff-ffff-ffff-ffffffffffff"
        retry_id = "00000000-0000-0000-0000-000000000001"
        inbox, ack = self.runtime / "inbox", self.runtime / "ack"
        old_path = inbox / (old_id + ".json")
        old_request = {"requestId": old_id, "action": "preferences", "id": pet["id"], "title": "Old name"}
        MODULE.atomic_json(old_path, old_request)
        self.bridge.process_inbox()
        self.assertFalse(old_path.exists())
        self.assertTrue(MODULE.read_json(ack / (old_id + ".json"))["ok"])
        # Missing is successful cancellation for retry purposes; it need not mean
        # the previous edit was prevented. Its existing ack preserves idempotence.
        old_path.unlink(missing_ok=True)
        MODULE.atomic_json(inbox / (retry_id + ".json"), {"requestId": retry_id, "action": "preferences", "id": pet["id"], "title": "New name"})
        MODULE.atomic_json(old_path, old_request)
        self.bridge.process_inbox()
        self.assertEqual(pet["title"], "New name")
        self.assertFalse(old_path.exists())
        self.assertTrue(MODULE.read_json(ack / (retry_id + ".json"))["ok"])

    def test_real_daemon_handshake(self):
        conversation_id, path = self.transcript()
        process = subprocess.Popen([sys.executable, str(SCRIPT), "serve", "--runtime", str(self.runtime), "--sessions-root", str(self.sessions)], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            for _ in range(100):
                if (self.runtime / "heartbeat.json").exists():
                    break
                time.sleep(0.02)
            ack = MODULE.send_request(self.runtime, {"action": "enable", "id": conversation_id})
            self.assertTrue(ack["ok"])
            self.assertTrue(ack["state"]["pets"][0]["enabled"])
            result = subprocess.run([sys.executable, str(SCRIPT), "status", "--all", "--runtime", str(self.runtime), "--timeout", "0.5"], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout)
            self.assertTrue(json.loads(result.stdout)["ok"])
        finally:
            process.terminate()
            process.communicate(timeout=5)
        self.assertFalse((self.runtime / "heartbeat.json").exists())


if __name__ == "__main__":
    unittest.main()
