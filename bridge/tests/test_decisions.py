"""Question correlation fixtures are synthetic; never save real answers."""

import json
import copy
from pathlib import Path
import tempfile
import unittest
from unittest import mock
import uuid

from test_bridge import MODULE


class DecisionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.sessions = self.root / "sessions"
        self.sessions.mkdir()
        self.conversation = str(uuid.uuid4())
        self.path = self.sessions / ("rollout-" + self.conversation + ".jsonl")
        self.path.write_text(json.dumps({"type": "session_meta", "payload": {"id": self.conversation, "source": "vscode"}}) + "\n")
        with mock.patch.object(MODULE, "now_iso", return_value=self.at(0)):
            self.bridge = MODULE.Bridge(self.root / "runtime", self.sessions)
            self.bridge.handle({"action": "enable", "id": self.conversation})
        self.pet = self.bridge.pet(self.conversation)

    def tearDown(self):
        self.temp.cleanup()

    @staticmethod
    def at(seconds):
        return MODULE.timestamp("2026-01-01T00:%02d:%02dZ" % (seconds // 60, seconds % 60))

    def call(self, call_id="call_questionA", seconds=1, titles=None, name="request_user_input_async"):
        titles = titles or ["Choose a product rule."]
        return {"timestamp": self.at(seconds), "type": "response_item", "payload": {"type": "function_call", "name": name,
                "call_id": call_id, "arguments": json.dumps({"questions": [{"title": title} for title in titles]})}}

    def reply(self, call_id="call_questionA", index=0, seconds=2, title="Choose a product rule.", owner=None, answer="SYNTHETIC_ANSWER_NOT_FOR_STATE"):
        envelope = [{"questionItemId": json.dumps(["request_user_input_async", call_id, index]), "question": title, "answer": answer}]
        content = "<send_user_message_question_reply>\n" + json.dumps(envelope) + "\n</send_user_message_question_reply>"
        return {"timestamp": self.at(seconds), "type": "event_msg", "payload": {"type": "item_completed", "thread_id": owner or self.conversation,
                "item": {"type": "UserMessage", "id": str(uuid.uuid4()), "client_id": str(uuid.uuid4()), "content": [{"type": "text", "text": content}]}}}

    def observe(self, *events):
        for event in events:
            self.bridge.apply_event(self.pet, event)
        self.bridge.publish()

    def user_message(self, seconds=3, message_id="latest-user-message", owner=None):
        return {"timestamp": self.at(seconds), "type": "event_msg", "payload": {"type": "item_completed", "thread_id": owner or self.conversation,
                "item": {"type": "UserMessage", "id": message_id, "client_id": str(uuid.uuid4()), "content": [{"type": "text", "text": "Synthetic user direction."}]}}}

    def report(self, values, seconds=20):
        payload = {"generation": self.pet["generation"], "sequence": self.pet["lastReportSequence"] + 1}
        payload.update(values)
        with mock.patch.object(MODULE, "now_iso", return_value=self.at(seconds)):
            return self.bridge.handle({"action": "report", "id": self.conversation, "report": payload})

    @staticmethod
    def reviewed(**values):
        payload = {"steps": [{"id": "review", "label": "Apply the reviewed decision", "done": False}], "currentStep": "Applying the reviewed decision", "phase": "building"}
        payload.update(values)
        return payload

    def test_real_tool_call_creates_question_but_tool_ack_is_not_answer(self):
        self.observe(self.call())
        self.assertEqual(self.pet["question"]["id"], "input:call_questionA")
        self.assertEqual(self.pet["question"]["origin"], "codex-input-tool")
        self.assertEqual(self.pet["question"]["status"], "awaiting_reply")
        self.observe({"timestamp": self.at(2), "type": "response_item", "payload": {"type": "function_call_output", "call_id": "call_questionA", "output": '{"accepted":true}'}})
        self.assertFalse(self.pet["question"]["items"][0]["answered"])
        with self.assertRaisesRegex(MODULE.BridgeError, "correlated user reply"):
            self.report(self.reviewed(resolveQuestionId="input:call_questionA"))
        self.assertEqual(self.pet["phase"], "waiting")

    def test_multiple_items_show_first_unanswered_and_require_all_replies(self):
        self.observe(self.call(titles=["First question?", "Second question?"]))
        self.observe(self.reply(index=0, title="First question?"))
        self.assertEqual(self.pet["question"]["text"], "Second question?")
        self.assertEqual(self.pet["question"]["status"], "awaiting_reply")
        with self.assertRaises(MODULE.BridgeError):
            self.report(self.reviewed(resolveQuestionId="input:call_questionA"))
        self.observe(self.reply(index=1, seconds=3, title="Second question?"))
        self.assertEqual(self.pet["question"]["status"], "awaiting_review")
        self.assertEqual(self.pet["phase"], "waiting")
        with self.assertRaisesRegex(MODULE.BridgeError, "complete roadmap"):
            self.report({"resolveQuestionId": "input:call_questionA", "phase": "building"})
        self.report(self.reviewed(resolveQuestionId="input:call_questionA"))
        self.assertIsNone(self.pet["question"])
        self.assertEqual(self.pet["phase"], "building")

    def test_no_answer_text_retained_and_duplicate_reply_is_idempotent(self):
        self.observe(self.call(), self.reply())
        answered_at = self.pet["question"]["items"][0]["answeredAt"]
        self.observe(self.reply(seconds=5))
        self.assertEqual(self.pet["question"]["items"][0]["answeredAt"], answered_at)
        self.assertNotIn("SYNTHETIC_ANSWER_NOT_FOR_STATE", json.dumps(self.bridge.state))
        self.assertNotIn('"answer":', json.dumps(self.bridge.state))

    def test_wrong_owner_call_index_title_and_quoted_output_do_not_answer(self):
        self.observe(self.call())
        self.observe(self.reply(owner=str(uuid.uuid4())), self.reply(call_id="call_other"), self.reply(index=1), self.reply(title="A different question"), self.reply(answer=""))
        quoted = self.reply()
        quoted["payload"]["item"]["content"][0]["text"] = "Quoted example: " + quoted["payload"]["item"]["content"][0]["text"]
        self.observe(quoted)
        output = self.reply()
        output["payload"]["item"]["type"] = "CommandExecution"
        self.observe(output)
        self.assertEqual(self.pet["question"]["status"], "awaiting_reply")

    def test_answered_question_stays_gated_through_task_end_and_phase_report(self):
        self.observe(self.call(), self.reply())
        self.observe({"timestamp": self.at(4), "type": "event_msg", "payload": {"type": "task_complete"}})
        self.assertEqual(self.pet["phase"], "waiting")
        with self.assertRaisesRegex(MODULE.BridgeError, "pending question"):
            self.report({"phase": "building"})
        self.assertEqual(self.pet["question"]["status"], "awaiting_review")

    def test_multiple_calls_queue_without_overwriting_current_question(self):
        self.observe(self.call(), self.call(call_id="call_questionB", seconds=2, titles=["Next decision?"]))
        self.assertEqual(self.pet["question"]["callId"], "call_questionA")
        self.assertEqual(len(self.pet["pendingQuestions"]), 2)
        self.observe(self.reply(seconds=3))
        self.report(self.reviewed(resolveQuestionId="input:call_questionA"))
        self.assertEqual(self.pet["question"]["callId"], "call_questionB")
        self.assertEqual(self.pet["phase"], "waiting")
        self.assertEqual(len(self.pet["pendingQuestions"]), 1)

    def test_manual_a_to_b_transition_is_atomic(self):
        self.report({"question": {"id": "manual-a", "text": "First decision?"}})
        self.report({"resolveQuestionId": "manual-a", "question": {"id": "manual-b", "text": "Second decision?"}, "phase": "building"})
        self.assertEqual(self.pet["question"]["id"], "manual-b")
        self.assertEqual(self.pet["phase"], "waiting")

    def test_observed_a_to_manual_b_preserves_gate_and_tombstone(self):
        self.observe(self.call(), self.reply())
        self.report(self.reviewed(resolveQuestionId="input:call_questionA", question={"id": "manual-b", "text": "Another important decision?"}))
        self.assertEqual(self.pet["question"]["id"], "manual-b")
        self.assertEqual(self.pet["phase"], "waiting")
        self.assertEqual(set(self.pet["inputCallHistory"]["call_questionA"]), {"callId", "observedAt", "resolvedAt", "status"})

    def test_restart_preserves_unanswered_gate_and_does_not_resurrect_resolved(self):
        self.observe(self.call())
        restarted = MODULE.Bridge(self.root / "runtime", self.sessions)
        self.assertEqual(restarted.pet(self.conversation)["question"]["status"], "awaiting_reply")
        self.observe(self.reply())
        self.report(self.reviewed(resolveQuestionId="input:call_questionA"))
        restarted = MODULE.Bridge(self.root / "runtime", self.sessions)
        pet = restarted.pet(self.conversation)
        restarted.apply_event(pet, self.call(seconds=25))
        self.assertIsNone(pet["question"])

    def test_first_enable_does_not_replay_old_questions(self):
        self.pet["questionWatchStartedAt"] = self.at(10)
        self.observe(self.call(seconds=9), self.reply(seconds=11))
        self.assertIsNone(self.pet["question"])
        self.assertEqual(self.pet["inputCallHistory"], {})

    def test_reenable_keeps_known_question_but_does_not_hatch_new_old_calls(self):
        self.observe(self.call())
        self.bridge.handle({"action": "disable", "id": self.conversation})
        with mock.patch.object(MODULE, "now_iso", return_value=self.at(10)):
            self.bridge.handle({"action": "enable", "id": self.conversation})
        self.observe(self.call(call_id="call_while_disabled", seconds=5), self.reply(seconds=8))
        self.assertEqual(self.pet["question"]["status"], "awaiting_review")
        self.assertNotIn("call_while_disabled", self.pet["inputCallHistory"])

    def test_cannot_downgrade_observed_question_to_manual_or_forge_origin(self):
        self.observe(self.call())
        with self.assertRaises(MODULE.BridgeError):
            self.report({"question": {"id": "input:call_questionA", "text": "Changed question"}})
        self.assertEqual(self.pet["question"]["origin"], "codex-input-tool")
        with self.assertRaises(MODULE.BridgeError):
            self.report({"question": {"id": "forged", "text": "Changed question", "origin": "codex-input-tool"}})

    def test_unverified_synchronous_tool_and_embedded_call_text_are_ignored(self):
        self.observe(self.call(name="request_user_input"))
        self.observe({"timestamp": self.at(2), "type": "response_item", "payload": {"type": "function_call_output", "output": json.dumps(self.call())}})
        self.assertIsNone(self.pet["question"])

    def test_capacity_limit_keeps_conservative_overflow_gate(self):
        with mock.patch.object(MODULE, "MAX_PENDING_INPUT_CALLS", 2):
            self.observe(self.call("call_a", 1), self.call("call_b", 2), self.call("call_c", 3))
        self.assertEqual(len(self.pet["inputCallHistory"]), 2)
        self.assertEqual(self.pet["pendingQuestions"][-1]["origin"], "codex-input-limit")
        self.assertEqual(self.pet["phase"], "waiting")

    def test_four_question_call_and_batched_replies_are_supported(self):
        titles = ["Question %d?" % index for index in range(4)]
        self.observe(self.call(titles=titles))
        replies = [{"questionItemId": json.dumps(["request_user_input_async", "call_questionA", index]), "question": title, "answer": "Synthetic choice"} for index, title in enumerate(titles)]
        event = self.reply()
        event["payload"]["item"]["content"][0]["text"] = "<send_user_message_question_reply>" + json.dumps(replies) + "</send_user_message_question_reply>"
        self.observe(event)
        self.assertEqual(len(self.pet["question"]["items"]), 4)
        self.assertEqual(self.pet["question"]["status"], "awaiting_review")

    def test_long_prompt_is_display_truncated_but_matches_full_reply_digest(self):
        title = "Long prompt " * 200
        self.observe(self.call(titles=[title]))
        self.assertEqual(len(self.pet["question"]["text"]), 1200)
        self.assertNotIn(title, json.dumps(self.bridge.state))
        self.observe(self.reply(title=title))
        self.assertEqual(self.pet["question"]["status"], "awaiting_review")

    def test_oversize_group_creates_explicit_review_gate_instead_of_disappearing(self):
        with mock.patch.object(MODULE, "MAX_INPUT_ITEMS", 2):
            self.observe(self.call(titles=["First?", "Second?", "Third?"]))
        self.assertEqual(self.pet["question"]["origin"], "codex-input-limit")
        self.assertEqual(self.pet["question"]["reason"], "too_many_questions")
        self.assertEqual(self.pet["phase"], "waiting")

    def test_tombstone_pruning_keeps_replay_watermark(self):
        with mock.patch.object(MODULE, "MAX_INPUT_TOMBSTONES", 1):
            for index in range(2):
                call_id = "call_%d" % index
                self.observe(self.call(call_id, index * 3 + 1), self.reply(call_id, seconds=index * 3 + 2))
                self.report(self.reviewed(resolveQuestionId="input:" + call_id), seconds=index * 3 + 3)
        self.assertEqual(len(self.pet["inputCallHistory"]), 1)
        self.observe(self.call("call_0", 1))
        self.assertIsNone(self.pet["question"])

    def test_explicit_setup_deferral_cancels_unanswered_call_without_approval(self):
        self.observe(self.call(), self.user_message())
        self.report(self.reviewed(cancelQuestionId="input:call_questionA", cancellationReason="setup_deferred",
                                 sourceUserMessageId="latest-user-message", classifyQuestion={"id": "input:call_questionA", "purpose": "setup", "optional": True}))
        self.assertIsNone(self.pet["question"])
        outcome = self.pet["inputCallHistory"]["call_questionA"]
        self.assertEqual(outcome["status"], "cancelled")
        self.assertEqual(outcome["cancellationReason"], "setup_deferred")
        self.assertEqual(outcome["answeredCount"], 0)
        self.assertNotIn("approved", outcome)
        self.assertNotIn("items", outcome)
        self.assertEqual(outcome["sourceUserMessageId"], "latest-user-message")

    def test_cancellation_requires_latest_later_root_user_message_and_full_review(self):
        self.observe(self.call(), self.user_message(seconds=0, message_id="before-question"))
        with self.assertRaisesRegex(MODULE.BridgeError, "latest root user message"):
            self.report(self.reviewed(cancelQuestionId="input:call_questionA", cancellationReason="user_cancelled", sourceUserMessageId="before-question"))
        self.observe(self.user_message(seconds=3), self.user_message(seconds=4, message_id="child-message", owner=str(uuid.uuid4())))
        for supplied in (None, "wrong", "child-message"):
            with self.assertRaises(MODULE.BridgeError):
                self.report(self.reviewed(cancelQuestionId="input:call_questionA", cancellationReason="user_cancelled", sourceUserMessageId=supplied))
        with self.assertRaisesRegex(MODULE.BridgeError, "complete roadmap"):
            self.report({"cancelQuestionId": "input:call_questionA", "cancellationReason": "user_cancelled", "sourceUserMessageId": "latest-user-message"})
        self.observe(self.user_message(seconds=5, message_id="newest"))
        with self.assertRaises(MODULE.BridgeError):
            self.report(self.reviewed(cancelQuestionId="input:call_questionA", cancellationReason="user_cancelled", sourceUserMessageId="latest-user-message"))
        self.assertEqual(self.pet["question"]["status"], "awaiting_reply")

    def test_setup_is_never_inferred_from_question_text(self):
        self.observe(self.call(titles=["Install optional Hook setup?"]), self.user_message())
        with self.assertRaisesRegex(MODULE.BridgeError, "explicitly optional setup"):
            self.report(self.reviewed(cancelQuestionId="input:call_questionA", cancellationReason="setup_deferred", sourceUserMessageId="latest-user-message"))
        self.assertNotIn("purpose", self.pet["question"])
        with self.assertRaises(MODULE.BridgeError):
            self.report({"classifyQuestion": {"id": "input:call_wrong", "purpose": "setup", "optional": True}})

    def test_cancel_and_resolve_are_mutually_exclusive(self):
        self.observe(self.call(), self.user_message())
        with self.assertRaisesRegex(MODULE.BridgeError, "not both"):
            self.report(self.reviewed(cancelQuestionId="input:call_questionA", resolveQuestionId="input:call_questionA",
                                     cancellationReason="user_cancelled", sourceUserMessageId="latest-user-message"))
        self.assertEqual(self.pet["inputCallHistory"]["call_questionA"]["status"], "awaiting_reply")

    def test_pet_not_now_checks_generation_current_id_and_optional_setup(self):
        self.observe(self.call())
        request = {"action": "defer_setup", "id": self.conversation, "generation": self.pet["generation"], "questionId": "input:call_questionA"}
        with self.assertRaises(MODULE.BridgeError):
            self.bridge.handle(request)
        self.report({"classifyQuestion": {"id": "input:call_questionA", "purpose": "setup", "optional": True}})
        with self.assertRaises(MODULE.BridgeError):
            self.bridge.handle(dict(request, generation=self.pet["generation"] - 1))
        with self.assertRaises(MODULE.BridgeError):
            self.bridge.handle(dict(request, questionId="input:call_wrong"))
        self.bridge.handle(request)
        self.assertIsNone(self.pet["question"])
        self.assertEqual(self.pet["phase"], "planning")
        self.assertTrue(self.pet["roadmapNeedsUpdate"])
        self.assertEqual(self.pet["inputCallHistory"]["call_questionA"]["source"], "pet")
        self.assertFalse(self.bridge.state["capabilities"]["executionControl"])

    def test_deferred_question_stays_cancelled_after_restart_and_late_reply(self):
        self.observe(self.call(), self.user_message())
        self.report(self.reviewed(cancelQuestionId="input:call_questionA", cancellationReason="user_cancelled", sourceUserMessageId="latest-user-message"))
        self.bridge = MODULE.Bridge(self.root / "runtime", self.sessions)
        self.pet = self.bridge.pet(self.conversation)
        self.observe(self.call(seconds=25), self.reply(seconds=26))
        self.assertIsNone(self.pet["question"])
        self.assertEqual(self.pet["inputCallHistory"]["call_questionA"]["status"], "cancelled")
        self.assertFalse(self.pet["roadmapNeedsUpdate"])

    def test_deferring_current_setup_keeps_next_question_waiting(self):
        self.observe(self.call(), self.call(call_id="call_questionB", seconds=2))
        self.report({"classifyQuestion": {"id": "input:call_questionA", "purpose": "setup", "optional": True}})
        self.bridge.handle({"action": "defer_setup", "id": self.conversation, "generation": self.pet["generation"], "questionId": "input:call_questionA"})
        self.assertEqual(self.pet["question"]["callId"], "call_questionB")
        self.assertEqual(self.pet["phase"], "waiting")
        self.assertTrue(self.pet["roadmapNeedsUpdate"])

    def test_manual_optional_setup_supports_not_now(self):
        self.report({"question": {"id": "manual-setup", "text": "Optional local setup", "purpose": "setup", "optional": True}})
        self.bridge.handle({"action": "defer_setup", "id": self.conversation, "generation": self.pet["generation"], "questionId": "manual-setup"})
        self.assertIsNone(self.pet["question"])
        self.assertEqual(self.pet["questionOutcomes"]["manual-setup"]["status"], "cancelled")
        self.assertEqual(self.pet["questionOutcomes"]["manual-setup"]["cancellationReason"], "setup_deferred")

    @staticmethod
    def serialized_bytes(value):
        # Match atomic_json, including its final newline and UTF-8 encoding.
        return len(json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")) + 1

    def large_question_fixture(self):
        for _ in range(4):
            conversation = str(uuid.uuid4())
            path = self.sessions / ("rollout-" + conversation + ".jsonl")
            path.write_text(json.dumps({"type": "session_meta", "payload": {"id": conversation, "source": "vscode"}}) + "\n")
            with mock.patch.object(MODULE, "now_iso", return_value=self.at(0)):
                self.bridge.handle({"action": "enable", "id": conversation})
        events = []
        for pet_index, pet in enumerate(self.bridge.state["pets"]):
            for call_index in range(4):
                events.append((pet["id"], self.call("call_bulk_%d_%d" % (pet_index, call_index),
                                                   seconds=pet_index * 4 + call_index + 1, titles=["示" * 1200] * 32)))
        return events

    def test_global_utf8_question_budget_prevents_native_four_mib_overflow(self):
        events = self.large_question_fixture()
        legacy = MODULE.Bridge(self.root / "legacy", self.sessions)
        legacy.state = copy.deepcopy(self.bridge.state)
        with mock.patch.object(MODULE, "MAX_QUESTION_STATE_BYTES", 16 * 1024 * 1024):
            for pet_id, event in events:
                legacy.apply_event(legacy.pet(pet_id), event)
        self.assertGreater(self.serialized_bytes(legacy.state), 4 * 1024 * 1024)
        for pet_id, event in events:
            self.bridge.apply_event(self.bridge.pet(pet_id), event)
        self.assertLess(self.serialized_bytes(self.bridge.state), 4 * 1024 * 1024)
        ack = {"requestId": str(uuid.uuid4()), "ok": True, "state": self.bridge.state}
        self.assertLess(self.serialized_bytes(ack), 4 * 1024 * 1024)
        overflowed = [pet for pet in self.bridge.state["pets"] if pet.get("questionOverflow")]
        self.assertTrue(overflowed)
        self.assertTrue(all(pet["questionOverflow"]["reason"] == "state_payload_budget" for pet in overflowed))
        for pet in self.bridge.state["pets"]:
            self.assertEqual(pet["phase"], "waiting")
            for call in pet["inputCallHistory"].values():
                self.assertEqual(call["status"], "awaiting_reply")
                self.assertEqual(len(call["items"]), 32)
                self.assertFalse(any(item["answered"] for item in call["items"]))

    def test_budget_rejection_stays_recorded_after_reconciliation_restart_and_replay(self):
        with mock.patch.object(MODULE, "MAX_QUESTION_STATE_BYTES", 1):
            self.observe(self.call())
        self.assertEqual(self.pet["question"]["status"], "needs_reconciliation")
        self.report(self.reviewed(resolveQuestionId="input-queue-overflow"))
        self.bridge = MODULE.Bridge(self.root / "runtime", self.sessions)
        self.pet = self.bridge.pet(self.conversation)
        self.observe(self.call(), self.reply(seconds=25))
        self.assertIsNone(self.pet["question"])
        self.assertEqual(self.pet["inputCallHistory"], {})
        self.assertEqual(set(self.pet["inputOverflowHistory"]["call_questionA"]), {"callId", "observedAt", "reason"})
        self.assertEqual(self.pet["phase"], "building")

    def test_pruned_overflow_identity_keeps_a_replay_watermark(self):
        with mock.patch.object(MODULE, "MAX_QUESTION_STATE_BYTES", 1), mock.patch.object(MODULE, "MAX_INPUT_TOMBSTONES", 1):
            self.observe(self.call("call_first", 1), self.call("call_second", 2))
        self.assertEqual(len(self.pet["inputOverflowHistory"]), 1)
        self.report(self.reviewed(resolveQuestionId="input-queue-overflow"))
        self.observe(self.call("call_first", 1))
        self.assertIsNone(self.pet["question"])

    def test_existing_oversize_state_is_preserved_instead_of_silent_migration(self):
        events = self.large_question_fixture()
        with mock.patch.object(MODULE, "MAX_QUESTION_STATE_BYTES", 16 * 1024 * 1024):
            for pet_id, event in events:
                self.bridge.apply_event(self.bridge.pet(pet_id), event)
        self.bridge.publish()
        self.assertGreater(self.serialized_bytes(self.bridge.state), 4 * 1024 * 1024)
        original_calls = sum(len(pet["inputCallHistory"]) for pet in self.bridge.state["pets"])
        restarted = MODULE.Bridge(self.root / "runtime", self.sessions)
        pet = restarted.pet(self.conversation)
        restarted.apply_event(pet, self.call("call_after_restart", 25))
        self.assertEqual(sum(len(item["inputCallHistory"]) for item in restarted.state["pets"]), original_calls)
        self.assertEqual(pet["questionOverflow"]["reason"], "state_payload_budget")
        self.assertGreater(self.serialized_bytes(restarted.state), 4 * 1024 * 1024)


if __name__ == "__main__":
    unittest.main()
