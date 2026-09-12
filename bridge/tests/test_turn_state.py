"""Observed lifecycle metadata is independent of product decisions and progress."""
import copy
import unittest
import uuid

import test_decisions as fixtures

MODULE = fixtures.MODULE


class TurnStateTests(unittest.TestCase):
    setUp = fixtures.DecisionTests.setUp
    tearDown = fixtures.DecisionTests.tearDown
    at = staticmethod(fixtures.DecisionTests.at)
    call = fixtures.DecisionTests.call
    reply = fixtures.DecisionTests.reply
    observe = fixtures.DecisionTests.observe
    user_message = fixtures.DecisionTests.user_message
    report = fixtures.DecisionTests.report
    reviewed = staticmethod(fixtures.DecisionTests.reviewed)

    def lifecycle(self, kind, seconds, turn="turn-a", owner=None):
        payload = {"type": kind}
        if turn is not None:
            payload["turn_id"] = turn
        if owner:
            payload["thread_id"] = owner
        return {"type": "event_msg", "timestamp": self.at(seconds), "payload": payload}

    def message(self, seconds, turn="turn-a", card=False, owner=None):
        event = self.reply(seconds=seconds, owner=owner) if card else self.user_message(seconds=seconds, message_id="message-%d" % seconds, owner=owner)
        if turn is not None:
            event["payload"]["turn_id"] = turn
        return event

    def test_turn_completion_is_visible_while_question_and_progress_stay_waiting(self):
        self.report(self.reviewed(), seconds=1)
        self.observe(self.lifecycle("task_started", 2), self.call(seconds=3))
        before = {key: copy.deepcopy(self.pet[key]) for key in ("question", "steps", "progress", "currentStep", "phase")}
        self.observe(self.lifecycle("task_complete", 4))
        self.assertEqual(self.pet["turnState"], {"status": "ended", "observedAt": self.at(4), "turnId": "turn-a"})
        self.assertEqual({key: self.pet[key] for key in before}, before)

    def test_report_timestamp_does_not_hide_actual_turn_completion(self):
        self.observe(self.lifecycle("task_started", 1), self.call(seconds=2))
        self.report({"phase": "waiting"}, seconds=20)
        source = self.pet["sourceUpdatedAt"]
        self.observe(self.lifecycle("task_complete", 4))
        self.assertEqual(self.pet["turnState"]["status"], "ended")
        self.assertEqual(self.pet["turnState"]["observedAt"], self.at(4))
        self.assertEqual(self.pet["sourceUpdatedAt"], source)
        self.assertEqual(self.pet["reportObservedAt"], self.at(20))
        self.assertEqual(self.pet["phase"], "waiting")

    def test_newer_report_content_and_phase_are_not_overridden_by_delayed_complete(self):
        self.observe(self.lifecycle("task_started", 1))
        self.report(self.reviewed(), seconds=20)
        plan = copy.deepcopy(self.pet["steps"])
        self.observe(self.lifecycle("task_complete", 4))
        self.assertEqual(self.pet["turnState"]["status"], "ended")
        self.assertEqual(self.pet["phase"], "building")
        self.assertEqual(self.pet["steps"], plan)
        self.assertEqual(self.pet["sourceUpdatedAt"], self.at(20))

    def test_running_turn_first_user_message_stays_running(self):
        self.observe(self.lifecycle("task_started", 1), self.message(2))
        self.assertEqual(self.pet["turnState"], {"status": "running", "observedAt": self.at(2),
                                                "turnId": "turn-a", "inputObservedAt": self.at(2)})

    def test_reply_clears_ended_label_before_next_start_without_resolving_gate(self):
        self.observe(self.lifecycle("task_started", 1), self.call(seconds=2), self.lifecycle("task_complete", 3))
        self.observe(self.message(4, turn="turn-b"))
        self.assertEqual(self.pet["turnState"]["status"], "input_received")
        self.assertEqual(self.pet["turnState"]["turnId"], "turn-b")
        self.assertEqual(self.pet["phase"], "waiting")
        self.assertFalse(self.pet["question"]["items"][0]["answered"])

    def test_correlated_card_reply_updates_turn_metadata_before_parser_returns(self):
        self.observe(self.lifecycle("task_started", 1), self.call(seconds=2), self.lifecycle("task_complete", 3))
        self.observe(self.message(4, turn="turn-b", card=True))
        self.assertEqual(self.pet["turnState"]["status"], "input_received")
        self.assertEqual(self.pet["turnState"]["inputObservedAt"], self.at(4))
        self.assertEqual(self.pet["question"]["status"], "awaiting_review")
        self.assertEqual(self.pet["phase"], "waiting")

    def test_card_reply_after_its_new_turn_started_keeps_running(self):
        self.observe(self.call(), self.lifecycle("task_started", 2, turn="turn-b"), self.message(3, turn="turn-b", card=True))
        self.assertEqual(self.pet["turnState"]["status"], "running")
        self.assertEqual(self.pet["question"]["status"], "awaiting_review")

    def test_delayed_start_for_same_input_turn_fills_in_running_status(self):
        self.observe(self.message(3, turn="turn-b"))
        self.observe(self.lifecycle("task_started", 2, turn="turn-b"))
        self.assertEqual(self.pet["turnState"], {"status": "running", "observedAt": self.at(3),
                                                "turnId": "turn-b", "inputObservedAt": self.at(3)})

    def test_old_turn_completion_cannot_override_new_input_even_with_later_delivery_timestamp(self):
        self.observe(self.lifecycle("task_started", 1), self.message(3, turn="turn-b"))
        before = copy.deepcopy(self.pet)
        self.observe(self.lifecycle("task_complete", 4, turn="turn-a"))
        self.assertEqual(self.pet["turnState"], before["turnState"])
        self.assertEqual(self.pet["phase"], before["phase"])

    def test_old_turn_completion_and_start_cannot_override_new_running_turn(self):
        self.observe(self.lifecycle("task_started", 1), self.lifecycle("task_started", 3, turn="turn-b"))
        before = copy.deepcopy(self.pet["turnState"])
        self.observe(self.lifecycle("task_complete", 4), self.lifecycle("task_started", 2))
        self.assertEqual(self.pet["turnState"], before)
        self.assertEqual(self.pet["phase"], "building")

    def test_unknown_turn_completion_cannot_override_known_new_input(self):
        self.observe(self.message(3, turn="turn-b"))
        self.observe(self.lifecycle("task_complete", 4, turn=None))
        self.assertEqual(self.pet["turnState"]["status"], "input_received")

    def test_legacy_unscoped_completion_keeps_phase_behavior_without_claiming_input_turn_ended(self):
        self.observe(self.message(3, turn=None))
        self.observe(self.lifecycle("task_complete", 4, turn=None))
        self.assertEqual(self.pet["phase"], "idle")
        self.assertEqual(self.pet["turnState"]["status"], "input_received")

    def test_stale_events_other_root_and_malformed_identity_do_not_change_state(self):
        self.observe(self.lifecycle("task_started", 5))
        before = copy.deepcopy(self.pet["turnState"])
        for event in (self.lifecycle("task_complete", 4), self.lifecycle("turn_aborted", 6, owner=str(uuid.uuid4())),
                      self.message(6, owner=str(uuid.uuid4())), self.lifecycle("task_complete", 6, turn="x" * 201)):
            self.observe(event)
            self.assertEqual(self.pet["turnState"], before)

    def test_interruption_persists_across_restart_and_ordinary_reply_clears_label(self):
        self.observe(self.lifecycle("task_started", 1), self.call(seconds=2), self.lifecycle("turn_aborted", 3))
        self.assertEqual(self.pet["turnState"]["status"], "interrupted")
        self.bridge = MODULE.Bridge(self.root / "runtime", self.sessions)
        self.pet = self.bridge.pet(self.conversation)
        self.assertEqual(self.pet["turnState"]["status"], "interrupted")
        self.observe(self.message(4, turn="turn-b"))
        self.assertEqual(self.pet["turnState"]["status"], "input_received")
        self.assertEqual(self.pet["phase"], "waiting")

    def test_tool_output_is_not_user_input_and_cannot_clear_ended_label(self):
        self.observe(self.lifecycle("task_complete", 3))
        event = self.message(4)
        event["payload"]["item"]["type"] = "CommandExecution"
        self.observe(event)
        self.assertEqual(self.pet["turnState"]["status"], "ended")

    def test_equal_time_old_start_and_user_replay_do_not_reopen_ended_turn(self):
        self.observe(self.lifecycle("task_started", 1), self.message(2), self.lifecycle("task_complete", 2))
        self.observe(self.lifecycle("task_started", 2), self.message(2))
        self.assertEqual(self.pet["turnState"]["status"], "ended")

    def test_next_turn_end_arriving_before_its_input_and_start_is_reconciled(self):
        self.observe(self.lifecycle("task_started", 1), self.lifecycle("task_complete", 2),
                     self.lifecycle("task_complete", 5, turn="turn-b"))
        self.assertEqual(self.pet["turnState"]["turnId"], "turn-a")
        self.assertEqual(len(self.pet["pendingTurnEnds"]), 1)
        self.bridge = MODULE.Bridge(self.root / "runtime", self.sessions)
        self.pet = self.bridge.pet(self.conversation)
        self.observe(self.message(4, turn="turn-b"), self.lifecycle("task_started", 3, turn="turn-b"))
        self.assertEqual(self.pet["turnState"], {"status": "ended", "observedAt": self.at(5),
                                                "turnId": "turn-b", "inputObservedAt": self.at(4)})
        self.assertEqual(self.pet["pendingTurnEnds"], [])

    def test_unmatched_old_turn_end_does_not_revive_from_its_stale_start(self):
        self.observe(self.lifecycle("task_started", 3, turn="turn-b"), self.lifecycle("task_complete", 5, turn="turn-a"))
        self.observe(self.lifecycle("task_started", 1, turn="turn-a"))
        self.assertEqual(self.pet["turnState"]["status"], "running")
        self.assertEqual(self.pet["turnState"]["turnId"], "turn-b")
        self.observe(self.lifecycle("task_started", 6, turn="turn-c"))
        self.assertEqual(self.pet["pendingTurnEnds"], [])

    def test_pending_turn_end_cache_is_bounded_and_contains_no_prose(self):
        self.observe(self.lifecycle("task_started", 1))
        for index in range(MODULE.MAX_PENDING_TURN_ENDS + 3):
            event = self.lifecycle("task_complete", index + 2, turn="unknown-%d" % index)
            event["payload"]["last_agent_message"] = "SYNTHETIC_PRIVATE_BODY"
            self.observe(event)
        self.assertEqual(len(self.pet["pendingTurnEnds"]), MODULE.MAX_PENDING_TURN_ENDS)
        self.assertTrue(all(set(item) == {"turnId", "status", "observedAt"} for item in self.pet["pendingTurnEnds"]))
        self.assertEqual(self.pet["turnState"]["status"], "running")


if __name__ == "__main__":
    unittest.main()
