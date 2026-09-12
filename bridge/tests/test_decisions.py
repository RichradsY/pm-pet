"""Question correlation fixtures are synthetic; never save real answers."""

import json
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


if __name__ == "__main__":
    unittest.main()
