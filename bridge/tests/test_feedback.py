"""Synthetic feedback only; never read user conversations or persist answer values."""
import copy
import json
import unittest
from unittest import mock
import uuid

import test_decisions as fixtures

MODULE = fixtures.MODULE


class FeedbackTests(unittest.TestCase):
    setUp = fixtures.DecisionTests.setUp
    tearDown = fixtures.DecisionTests.tearDown
    at = staticmethod(fixtures.DecisionTests.at)
    call = fixtures.DecisionTests.call
    reply = fixtures.DecisionTests.reply
    observe = fixtures.DecisionTests.observe
    user_message = fixtures.DecisionTests.user_message
    report = fixtures.DecisionTests.report
    reviewed = staticmethod(fixtures.DecisionTests.reviewed)

    def review(self, indexes, source="latest-user-message", question="input:call_questionA"):
        return {"questionId": question, "sourceUserMessageId": source, "answeredItemIndexes": indexes}

    def test_plain_root_message_is_candidate_not_answer_or_progress(self):
        self.observe(self.call(), self.user_message())
        self.assertEqual(self.pet["feedback"], {"questionId": "input:call_questionA", "sourceUserMessageId": "latest-user-message",
                                               "observedAt": self.at(3), "status": "pending_review"})
        self.assertEqual(self.pet["question"]["status"], "awaiting_reply")
        self.assertFalse(self.pet["question"]["items"][0]["answered"])
        self.assertEqual(self.pet["phase"], "waiting")
        self.assertNotIn("Synthetic user direction.", json.dumps(self.bridge.state))
        with self.assertRaisesRegex(MODULE.BridgeError, "reviewFeedback.*ordinary-chat-feedback"):
            self.report(self.reviewed(resolveQuestionId="input:call_questionA"))

    def test_non_answer_review_dismisses_marker_preserves_gate_and_survives_replay(self):
        message = self.user_message()
        self.observe(self.call(), message)
        self.report({"reviewFeedback": self.review([])})
        self.assertIsNone(self.pet["feedback"])
        self.assertEqual(self.pet["question"]["status"], "awaiting_reply")
        restarted = MODULE.Bridge(self.root / "runtime", self.sessions)
        restarted.apply_event(restarted.pet(self.conversation), message)
        self.assertIsNone(restarted.pet(self.conversation)["feedback"])
        self.assertEqual(restarted.pet(self.conversation)["phase"], "waiting")

    def test_latest_candidate_supersedes_old_and_review_does_not_resurface_it(self):
        self.observe(self.call(), self.user_message(message_id="first"), self.user_message(seconds=4, message_id="second"))
        self.assertEqual(self.pet["feedback"]["sourceUserMessageId"], "second")
        with self.assertRaises(MODULE.BridgeError):
            self.report({"reviewFeedback": self.review([0], source="first")})
        self.report({"reviewFeedback": self.review([], source="second")})
        self.assertIsNone(self.pet["feedback"])
        self.observe(self.user_message(message_id="first"))
        self.assertIsNone(self.pet["feedback"])

    def test_wrong_owner_and_pre_question_messages_do_not_offer_review(self):
        self.observe(self.user_message(seconds=0), self.call(), self.user_message(owner=str(uuid.uuid4())))
        self.assertIsNone(self.pet.get("feedback"))
        with self.assertRaises(MODULE.BridgeError):
            self.report({"reviewFeedback": self.review([0])})

    def test_stale_generation_cannot_review_old_candidate_after_reenable(self):
        self.observe(self.call(), self.user_message())
        old_generation = self.pet["generation"]
        self.bridge.handle({"action": "disable", "id": self.conversation})
        with mock.patch.object(MODULE, "now_iso", return_value=self.at(10)):
            self.bridge.handle({"action": "enable", "id": self.conversation})
        self.observe(self.user_message())
        self.assertIsNone(self.pet.get("feedback"))
        with self.assertRaises(MODULE.BridgeError):
            self.report({"generation": old_generation, "reviewFeedback": self.review([0])})
        with self.assertRaises(MODULE.BridgeError):
            self.report({"reviewFeedback": self.review([0])})

    def test_partial_review_marks_only_selected_item_and_requires_remaining_reply(self):
        self.observe(self.call(titles=["First?", "Second?"]), self.user_message())
        self.report({"reviewFeedback": self.review([0])})
        question = self.pet["question"]
        self.assertEqual(question["text"], "Second?")
        self.assertEqual(question["status"], "awaiting_reply")
        self.assertEqual(question["items"][0]["answerSource"], "main-agent-review")
        self.assertEqual(question["items"][0]["sourceUserMessageId"], "latest-user-message")
        self.assertFalse(question["items"][1]["answered"])
        self.assertIsNone(self.pet["feedback"])
        with self.assertRaises(MODULE.BridgeError):
            self.report(self.reviewed(resolveQuestionId=question["id"]))
        self.observe(self.user_message(seconds=5, message_id="answer-two"))
        self.report(self.reviewed(resolveQuestionId=question["id"], reviewFeedback=self.review([1], source="answer-two")))
        self.assertIsNone(self.pet["question"])
        self.assertIsNone(self.pet["feedback"])
        self.assertEqual(self.pet["phase"], "building")
        self.assertEqual(self.pet["inputCallHistory"]["call_questionA"]["resolutionSource"], "main-agent-review")

    def test_all_reviewed_items_still_wait_for_full_plan_resolution(self):
        self.observe(self.call(), self.user_message())
        self.report({"reviewFeedback": self.review([0])})
        self.assertEqual(self.pet["question"]["status"], "awaiting_review")
        self.assertEqual(self.pet["phase"], "waiting")
        with self.assertRaises(MODULE.BridgeError):
            self.report({"resolveQuestionId": "input:call_questionA"})
        self.report(self.reviewed(resolveQuestionId="input:call_questionA"))
        self.assertIsNone(self.pet["question"])

    def test_invalid_review_or_partial_resolve_is_atomic(self):
        self.observe(self.call(titles=["First?", "Second?"]), self.user_message())
        invalid = [self.review([True]), self.review([-1]), self.review([2]), self.review([0, 0]),
                   self.review([0], source="not-observed"), self.review([0], question="other-question"),
                   dict(self.review([0]), answer="Never accepted"), self.review("0")]
        for value in invalid:
            before = copy.deepcopy(self.pet)
            with self.subTest(value=value), self.assertRaises(MODULE.BridgeError):
                self.report({"reviewFeedback": value})
            self.assertEqual(self.pet, before)
        before = copy.deepcopy(self.pet)
        with self.assertRaises(MODULE.BridgeError):
            self.report(self.reviewed(resolveQuestionId="input:call_questionA", reviewFeedback=self.review([0])))
        self.assertEqual(self.pet, before)

    def test_review_only_cannot_change_phase_steps_or_cancel(self):
        self.observe(self.call(), self.user_message())
        for extra in ({"phase": "waiting"}, {"steps": []}, {"currentStep": "Next"}, {"cancelQuestionId": "input:call_questionA"}):
            with self.subTest(extra=extra), self.assertRaises(MODULE.BridgeError):
                self.report(dict({"reviewFeedback": self.review([])}, **extra))
        self.assertIsNotNone(self.pet["feedback"])

    def test_same_feedback_review_cannot_replay_and_claim_more_answers(self):
        self.observe(self.call(titles=["First?", "Second?"]), self.user_message())
        self.report({"reviewFeedback": self.review([0])})
        with self.assertRaises(MODULE.BridgeError):
            self.report({"reviewFeedback": self.review([1])})
        self.assertFalse(self.pet["question"]["items"][1]["answered"])

    def test_manual_question_can_dismiss_candidate_but_has_no_invented_item_index(self):
        self.report({"question": {"id": "manual", "text": "A manual reminder"}}, seconds=1)
        self.observe(self.user_message())
        with self.assertRaises(MODULE.BridgeError):
            self.report({"reviewFeedback": self.review([0], question="manual")})
        self.report({"reviewFeedback": self.review([], question="manual")})
        self.assertEqual(self.pet["question"]["id"], "manual")
        self.assertIsNone(self.pet["feedback"])

    def test_manual_resolution_and_cancellation_clear_its_candidate(self):
        self.report({"question": {"id": "manual", "text": "A manual reminder"}}, seconds=1)
        self.observe(self.user_message())
        self.report({"resolveQuestionId": "manual", "phase": "building"})
        self.assertIsNone(self.pet["feedback"])
        self.observe(self.call(call_id="call_second", seconds=21), self.user_message(seconds=22, message_id="cancel-message"))
        self.report(self.reviewed(cancelQuestionId="input:call_second", cancellationReason="user_cancelled",
                                 sourceUserMessageId="cancel-message"), seconds=23)
        self.assertIsNone(self.pet["feedback"])
        self.assertIsNone(self.pet["question"])

    def test_atomic_review_resolve_can_reveal_next_queued_question(self):
        self.observe(self.call(), self.call(call_id="call_second", seconds=2), self.user_message())
        self.report(self.reviewed(resolveQuestionId="input:call_questionA", reviewFeedback=self.review([0])))
        self.assertEqual(self.pet["question"]["id"], "input:call_second")
        self.assertEqual(self.pet["phase"], "waiting")
        self.assertFalse(self.pet["question"]["items"][0]["answered"])
        self.assertEqual(self.pet["feedback"]["questionId"], "input:call_second")

    def test_card_reply_inside_own_text_block_accepts_other_content_parts(self):
        event = self.reply()
        event["payload"]["item"]["content"].insert(0, {"type": "text", "text": "Extra context"})
        event["payload"]["item"]["content"].append({"type": "image", "url": "synthetic-only"})
        self.observe(self.call(), event)
        self.assertEqual(self.pet["question"]["status"], "awaiting_review")
        self.assertEqual(self.pet["question"]["items"][0]["answerSource"], "question-card")
        self.assertNotIn("SYNTHETIC_ANSWER_NOT_FOR_STATE", json.dumps(self.bridge.state))

    def test_quoted_or_split_envelope_is_not_a_card_reply(self):
        self.observe(self.call())
        event = self.reply()
        text = event["payload"]["item"]["content"][0]["text"]
        event["payload"]["item"]["content"] = [{"type": "text", "text": text[:30]}, {"type": "text", "text": text[30:]}]
        self.observe(event)
        self.assertFalse(self.pet["question"]["items"][0]["answered"])
        event = self.reply(seconds=4)
        event["payload"]["item"]["content"][0]["text"] = "Quoted: " + text
        self.observe(event)
        self.assertFalse(self.pet["question"]["items"][0]["answered"])

    def test_reply_before_call_correlates_after_restart_without_saving_answer(self):
        self.observe(self.reply())
        self.assertEqual(len(self.pet["deferredInputReplies"]), 1)
        self.assertNotIn("SYNTHETIC_ANSWER_NOT_FOR_STATE", json.dumps(self.bridge.state))
        self.bridge = MODULE.Bridge(self.root / "runtime", self.sessions)
        self.pet = self.bridge.pet(self.conversation)
        self.observe(self.call())
        self.assertEqual(self.pet["question"]["status"], "awaiting_review")
        self.assertEqual(self.pet["deferredInputReplies"], [])
        self.assertEqual(self.pet["phase"], "waiting")

    def test_deferred_reply_checks_prompt_index_time_and_owner(self):
        self.observe(self.reply(title="Wrong prompt"), self.reply(index=5), self.reply(seconds=0), self.reply(owner=str(uuid.uuid4())))
        self.observe(self.call())
        self.assertFalse(self.pet["question"]["items"][0]["answered"])
        self.assertEqual(self.pet["deferredInputReplies"], [])

    def test_terminal_call_does_not_reopen_from_late_or_deferred_reply(self):
        self.observe(self.reply(), self.call())
        self.report(self.reviewed(resolveQuestionId="input:call_questionA"))
        self.observe(self.reply(seconds=21), self.call())
        self.assertIsNone(self.pet["question"])
        self.assertIsNone(self.pet.get("feedback"))
        self.assertEqual(self.pet["deferredInputReplies"], [])

    def test_deferred_metadata_limit_is_bounded_and_keeps_reconciliation_gate(self):
        with mock.patch.object(MODULE, "MAX_DEFERRED_INPUT_REPLIES", 2):
            self.observe(self.reply(call_id="call_a"), self.reply(call_id="call_b", seconds=3), self.reply(call_id="call_c", seconds=4))
            self.assertEqual(len(self.pet["deferredInputReplies"]), 2)
            self.assertEqual(self.pet["question"]["status"], "needs_reconciliation")
            self.report(self.reviewed(resolveQuestionId="input-queue-overflow"))
            self.observe(self.reply(call_id="call_c", seconds=4))
            self.assertIsNone(self.pet["question"])

    def test_feedback_history_is_bounded_and_evicted_replays_do_not_reappear(self):
        with mock.patch.object(MODULE, "MAX_FEEDBACK_MESSAGES", 2):
            self.observe(self.call(), self.user_message(seconds=3, message_id="first"),
                         self.user_message(seconds=4, message_id="second"), self.user_message(seconds=5, message_id="third"))
            self.assertEqual(len(self.pet["feedbackMessages"]), 2)
            self.report({"reviewFeedback": self.review([], source="third")})
            self.observe(self.user_message(seconds=3, message_id="first"))
            self.assertIsNone(self.pet["feedback"])

    def test_review_identity_lists_drop_terminal_calls_and_do_not_grow_forever(self):
        self.observe(self.user_message())
        with mock.patch.object(MODULE, "MAX_INPUT_TOMBSTONES", 2):
            for index in range(10):
                question_id = "input:call_delayed%d" % index
                self.observe(self.call(call_id="call_delayed%d" % index, seconds=1 + index // 4))
                # The final group is not after this message, so only the first two
                # timestamp groups qualify; keep this test focused on retained IDs.
                if not self.pet.get("feedback"):
                    break
                self.report(self.reviewed(resolveQuestionId=question_id, reviewFeedback=self.review([0], question=question_id)))
                self.assertTrue(all(not entry["reviewedQuestionIds"] for entry in self.pet["feedbackMessages"]))
            self.observe(self.call(call_id="call_delayed0", seconds=1))
            self.assertNotEqual((self.pet.get("question") or {}).get("id"), "input:call_delayed0")

    def test_deferred_metadata_rejects_unbounded_identity_and_item_index(self):
        long_identity = self.reply()
        long_identity["payload"]["item"]["id"] = "x" * 201
        self.observe(long_identity, self.reply(index=MODULE.MAX_INPUT_ITEMS))
        self.assertEqual(self.pet.get("deferredInputReplies", []), [])

    def test_question_budget_reserves_future_answer_provenance(self):
        budget = 18 * 1024
        with mock.patch.object(MODULE, "MAX_QUESTION_STATE_BYTES", budget):
            for index in range(20):
                self.observe(self.call(call_id="call_budget%d" % index, seconds=1, titles=["Short question"] * 4))
                if self.pet.get("questionOverflow"):
                    break
        self.assertIsNotNone(self.pet.get("questionOverflow"))
        self.assertGreater(len(self.pet["inputCallHistory"]), 0)
        # Filling every admitted item with its maximum supported metadata remains
        # within the admission budget (apart from the compact overflow marker).
        for call in self.pet["inputCallHistory"].values():
            for item in call["items"]:
                item.update({"answered": True, "answeredAt": self.at(2), "answerSource": "main-agent-review",
                             "sourceUserMessageId": "🙂" * 200, "reviewedAt": self.at(3)})
        self.bridge.refresh_input_queue(self.pet)
        encoded = json.dumps(self.bridge.state, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.assertLess(len(encoded), budget + 2048)

    def test_plain_message_before_delayed_call_can_be_reviewed_after_call_arrives(self):
        self.observe(self.user_message(), self.call())
        self.assertEqual(self.pet["feedback"]["sourceUserMessageId"], "latest-user-message")
        self.assertFalse(self.pet["question"]["items"][0]["answered"])

    def test_waiting_discovers_shards_at_two_seconds_without_refreshing_quota(self):
        self.observe(self.call())
        quota = copy.deepcopy(self.bridge.state["quota"])
        self.bridge.last_discovery[self.conversation] = 0
        with mock.patch.object(MODULE, "discover_transcripts", return_value=[self.path]) as discover:
            self.bridge.poll_transcripts(monotonic=1)
            discover.assert_not_called()
            self.bridge.poll_transcripts(monotonic=2)
            discover.assert_called_once()
        self.assertEqual(self.bridge.state["quota"], quota)


if __name__ == "__main__":
    unittest.main()
