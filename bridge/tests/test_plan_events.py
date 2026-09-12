"""Synthetic typed plan events keep independent scope and lifecycle ordering."""

import copy
import json
import unittest
import uuid

import test_decisions as fixtures

MODULE = fixtures.MODULE


class PlanEventTests(unittest.TestCase):
    setUp = fixtures.DecisionTests.setUp
    tearDown = fixtures.DecisionTests.tearDown
    at = staticmethod(fixtures.DecisionTests.at)
    call = fixtures.DecisionTests.call
    reply = fixtures.DecisionTests.reply
    observe = fixtures.DecisionTests.observe
    user_message = fixtures.DecisionTests.user_message
    report = fixtures.DecisionTests.report
    reviewed = staticmethod(fixtures.DecisionTests.reviewed)

    def plan(self, seconds, statuses=("in_progress", "pending"), turn="turn-a", kind="plan_updated", owner=None):
        payload = {"type": kind, "plan": [
            {"step": "Delivery %s" % chr(65 + index), "status": status}
            for index, status in enumerate(statuses)
        ]}
        if turn is not None:
            payload["turn_id"] = turn
        if owner is not None:
            payload["thread_id"] = owner
        return {"type": "event_msg", "timestamp": self.at(seconds), "payload": payload}

    def lifecycle(self, kind, seconds, turn="turn-a"):
        return {"type": "event_msg", "timestamp": self.at(seconds),
                "payload": {"type": kind, "turn_id": turn}}

    def append(self, path, *events):
        with path.open("a", encoding="utf-8") as handle:
            for event in events:
                handle.write(json.dumps(event) + "\n")

    def test_delayed_plan_from_new_shard_updates_progress_after_turn_ended(self):
        self.append(self.path, self.lifecycle("task_started", 1), self.plan(2),
                    self.lifecycle("task_complete", 10))
        self.bridge.poll_transcripts(monotonic=0)
        self.assertEqual(self.pet["progress"]["done"], 0)
        ended = copy.deepcopy(self.pet["turnState"])
        phase = self.pet["phase"]
        newer_source = self.pet["sourceUpdatedAt"]
        shard = self.sessions / ("rollout-late-" + self.conversation + ".jsonl")
        self.append(shard, {"type": "session_meta", "payload": {"id": self.conversation, "source": "vscode"}},
                    self.plan(9, ("completed", "completed")))
        self.bridge.poll_transcripts(monotonic=31)
        self.assertEqual(self.pet["progress"], {"done": 2, "total": 2, "percent": 100})
        self.assertEqual(self.pet["planObservedAt"], self.at(9))
        self.assertEqual(self.pet["eventObservedAt"], self.at(10))
        self.assertEqual(self.pet["turnState"], ended)
        self.assertEqual(self.pet["turnState"]["status"], "ended")
        self.assertEqual(self.pet["phase"], phase)
        self.assertEqual(self.pet["sourceUpdatedAt"], newer_source)

    def test_replayed_or_older_plan_does_not_regress_after_restart(self):
        self.observe(self.lifecycle("task_started", 1), self.plan(9, ("completed", "completed")),
                     self.lifecycle("task_complete", 10))
        self.bridge = MODULE.Bridge(self.root / "runtime", self.sessions)
        self.pet = self.bridge.pet(self.conversation)
        before = copy.deepcopy(self.pet)
        self.observe(self.plan(8), self.plan(9), self.plan(9, ("completed", "completed")))
        self.assertEqual(self.pet, before)

    def test_newer_explicit_review_and_equal_time_report_win_over_plan(self):
        self.observe(self.lifecycle("task_started", 1), self.plan(2))
        self.report(self.reviewed(), seconds=8)
        self.observe(self.lifecycle("task_complete", 10))
        before = copy.deepcopy(self.pet)
        self.observe(self.plan(7, ("completed", "completed")), self.plan(8, ("completed", "completed")))
        self.assertEqual(self.pet, before)
        self.assertEqual(self.pet["planObservedAt"], self.at(2))
        self.assertEqual(self.pet["reportObservedAt"], self.at(8))

    def test_new_plan_after_report_is_not_swallowed_by_newer_lifecycle(self):
        self.observe(self.lifecycle("task_started", 1))
        self.report(self.reviewed(), seconds=7)
        self.observe(self.lifecycle("task_complete", 10), self.plan(9, ("completed", "completed")))
        self.assertEqual(self.pet["progress"]["done"], 2)
        self.assertEqual(self.pet["turnState"]["status"], "ended")
        self.assertEqual(self.pet["reportObservedAt"], self.at(7))

    def test_new_request_blocks_old_unscoped_plan_and_new_plan_still_requires_review(self):
        self.observe(self.plan(2, turn=None), self.user_message(seconds=8))
        before = copy.deepcopy(self.pet)
        self.observe(self.plan(7, ("completed", "completed"), turn=None),
                     self.plan(8, ("completed", "completed"), turn=None))
        self.assertEqual(self.pet, before)
        self.assertTrue(self.pet["roadmapNeedsUpdate"])
        self.observe(self.plan(9, ("pending", "in_progress"), turn=None))
        self.assertEqual(self.pet["currentStepId"], "plan-1")
        self.assertTrue(self.pet["roadmapNeedsUpdate"])
        self.assertEqual(self.pet["requestObservedAt"], self.at(8))

    def test_plan_explicitly_owned_by_old_turn_cannot_replace_new_turn_scope(self):
        self.observe(self.lifecycle("task_started", 1), self.plan(2))
        message = self.user_message(seconds=8)
        message["payload"]["turn_id"] = "turn-b"
        self.observe(message, self.lifecycle("task_started", 9, turn="turn-b"))
        before = copy.deepcopy(self.pet)
        self.observe(self.plan(10, ("completed", "completed"), turn="turn-a"))
        self.assertEqual({key: value for key, value in self.pet.items() if key != "pendingPlanEvents"},
                         {key: value for key, value in before.items() if key != "pendingPlanEvents"})
        self.observe(self.plan(11, ("pending", "in_progress"), turn="turn-b"))
        self.assertEqual(self.pet["currentStepId"], "plan-1")
        self.assertEqual(self.pet["turnState"]["turnId"], "turn-b")

    def test_unanswered_and_answered_questions_both_keep_plan_frozen_until_review(self):
        self.observe(self.plan(1), self.call(seconds=2))
        before = copy.deepcopy(self.pet)
        self.observe(self.plan(3, ("completed", "completed")))
        self.assertEqual(self.pet, before)
        self.observe(self.reply(seconds=4))
        self.assertEqual(self.pet["question"]["status"], "awaiting_review")
        before = copy.deepcopy(self.pet)
        self.observe(self.plan(5, ("completed", "completed")))
        self.assertEqual(self.pet, before)
        self.report(self.reviewed(resolveQuestionId="input:call_questionA"), seconds=6)
        before = copy.deepcopy(self.pet)
        self.observe(self.plan(5, ("completed", "completed")))
        self.assertEqual(self.pet, before)

    def test_current_step_moves_from_a_to_b_while_a_is_still_pending(self):
        self.observe(self.plan(1))
        self.assertEqual(self.pet["currentStepId"], "plan-0")
        self.observe(self.plan(2, ("pending", "in_progress")))
        self.assertEqual(self.pet["currentStepId"], "plan-1")
        self.assertEqual(self.pet["currentStep"], "Delivery B")
        self.assertFalse(self.pet["steps"][0]["done"])
        self.assertEqual(self.pet["progress"]["done"], 0)

    def test_plan_without_active_step_clears_old_step_for_pending_and_complete_plans(self):
        self.observe(self.plan(1), self.plan(2, ("pending", "pending")))
        self.assertIsNone(self.pet["currentStepId"])
        self.assertEqual(self.pet["currentStep"], "")
        self.assertEqual(self.pet["progress"]["percent"], 0)
        self.observe(self.plan(3), self.plan(4, ("completed", "completed")))
        self.assertIsNone(self.pet["currentStepId"])
        self.assertEqual(self.pet["currentStep"], "")
        self.assertEqual(self.pet["progress"]["percent"], 100)

    def test_newer_plan_does_not_hide_delayed_lifecycle_evidence(self):
        self.observe(self.lifecycle("task_started", 1), self.plan(9, ("completed", "completed")))
        self.assertEqual(self.pet["eventObservedAt"], self.at(1))
        self.observe(self.lifecycle("task_complete", 8))
        self.assertEqual(self.pet["turnState"]["status"], "ended")
        self.assertEqual(self.pet["turnState"]["observedAt"], self.at(8))
        self.assertEqual(self.pet["planObservedAt"], self.at(9))
        self.assertEqual(self.pet["progress"]["percent"], 100)

    def test_invalid_plan_or_wrong_owner_does_not_advance_plan_watermark(self):
        self.observe(self.plan(1))
        before = copy.deepcopy(self.pet)
        malformed = self.plan(3)
        malformed["payload"]["plan"][0]["status"] = "imagined"
        missing_time = self.plan(3)
        missing_time["timestamp"] = None
        for event in (malformed, missing_time, self.plan(3, owner=str(uuid.uuid4())), self.plan(3, turn="")):
            self.observe(event)
            self.assertEqual(self.pet, before)
        self.observe(self.plan(2, ("completed", "in_progress"), kind="update_plan"))
        self.assertEqual(self.pet["planObservedAt"], self.at(2))
        self.assertEqual(self.pet["progress"]["percent"], 50)

    def test_active_item_outside_retained_plan_cannot_leave_dangling_step_id(self):
        self.observe(self.plan(1))
        self.observe(self.plan(2, ["pending"] * 100 + ["in_progress"]))
        self.assertEqual(len(self.pet["steps"]), 100)
        self.assertIsNone(self.pet["currentStepId"])
        self.assertEqual(self.pet["currentStep"], "")

    def test_new_turn_plan_before_its_start_is_applied_when_identity_arrives(self):
        self.observe(self.lifecycle("task_started", 1), self.lifecycle("task_complete", 2))
        before = copy.deepcopy(self.pet)
        self.observe(self.plan(5, ("completed", "in_progress"), turn="turn-b"))
        self.assertEqual({key: value for key, value in self.pet.items() if key != "pendingPlanEvents"},
                         {key: value for key, value in before.items() if key != "pendingPlanEvents"})
        self.assertEqual(len(self.pet["pendingPlanEvents"]), 1)
        self.observe(self.lifecycle("task_started", 3, turn="turn-b"))
        self.assertEqual(self.pet["progress"]["percent"], 50)
        self.assertEqual(self.pet["currentStepId"], "plan-1")
        self.assertEqual(self.pet["turnState"]["status"], "running")
        self.assertEqual(self.pet["turnState"]["observedAt"], self.at(3))
        self.assertEqual(self.pet["pendingPlanEvents"], [])

    def test_pending_plan_survives_restart_and_keeps_only_latest_for_turn(self):
        self.observe(self.lifecycle("task_started", 1), self.lifecycle("task_complete", 2),
                     self.plan(4, turn="turn-b"), self.plan(5, ("completed", "in_progress"), turn="turn-b"))
        self.assertEqual(len(self.pet["pendingPlanEvents"]), 1)
        self.assertIsNone(self.pet["planObservedAt"])
        self.bridge = MODULE.Bridge(self.root / "runtime", self.sessions)
        self.pet = self.bridge.pet(self.conversation)
        message = self.user_message(seconds=3)
        message["payload"]["turn_id"] = "turn-b"
        self.observe(message)
        self.assertEqual(self.pet["planObservedAt"], self.at(5))
        self.assertEqual(self.pet["progress"]["percent"], 50)
        self.assertEqual(self.pet["pendingPlanEvents"], [])

    def test_pending_plan_is_checked_after_new_user_request_scope(self):
        self.observe(self.lifecycle("task_started", 1), self.plan(2), self.lifecycle("task_complete", 3),
                     self.plan(5, ("completed", "completed"), turn="turn-b"))
        message = self.user_message(seconds=6)
        message["payload"]["turn_id"] = "turn-b"
        self.observe(message)
        self.assertEqual(self.pet["requestObservedAt"], self.at(6))
        self.assertEqual(self.pet["planObservedAt"], self.at(2))
        self.assertEqual(self.pet["progress"]["done"], 0)
        self.assertTrue(self.pet["roadmapNeedsUpdate"])
        self.assertEqual(self.pet["pendingPlanEvents"], [])

    def test_matching_start_drains_plan_before_report_clock_filters_lifecycle(self):
        self.observe(self.lifecycle("task_started", 1), self.lifecycle("task_complete", 2),
                     self.plan(9, ("completed", "in_progress"), turn="turn-b"))
        self.report(self.reviewed(phase="checking"), seconds=8)
        self.observe(self.lifecycle("task_started", 3, turn="turn-b"))
        self.assertEqual(self.pet["planObservedAt"], self.at(9))
        self.assertEqual(self.pet["progress"]["percent"], 50)
        self.assertEqual(self.pet["phase"], "checking")
        self.assertEqual(self.pet["reportObservedAt"], self.at(8))

    def test_pending_old_turn_plan_cannot_cross_new_report(self):
        self.observe(self.lifecycle("task_started", 1), self.plan(2),
                     self.lifecycle("task_started", 3, turn="turn-b"),
                     self.plan(5, ("completed", "completed"), turn="turn-a"))
        self.report(self.reviewed(), seconds=6)
        self.observe(self.lifecycle("task_started", 7, turn="turn-a"))
        self.assertEqual(self.pet["planObservedAt"], self.at(2))
        self.assertEqual(self.pet["steps"][0]["id"], "review")
        self.assertEqual(self.pet["progress"]["done"], 0)
        self.assertEqual(self.pet["pendingPlanEvents"], [])

    def test_pending_plan_cannot_cross_question_or_correlated_reply_gate(self):
        self.observe(self.lifecycle("task_started", 1), self.plan(2), self.lifecycle("task_complete", 3),
                     self.plan(6, ("completed", "completed"), turn="turn-b"), self.call(seconds=4))
        reply = self.reply(seconds=5)
        reply["payload"]["turn_id"] = "turn-b"
        self.observe(reply)
        self.assertEqual(self.pet["question"]["status"], "awaiting_review")
        self.assertEqual(self.pet["phase"], "waiting")
        self.assertEqual(self.pet["progress"]["done"], 0)
        self.assertEqual(self.pet["planObservedAt"], self.at(2))
        self.assertEqual(self.pet["pendingPlanEvents"], [])

    def test_pending_plan_cache_is_bounded_and_validated_before_admission(self):
        self.observe(self.lifecycle("task_started", 1), self.lifecycle("task_complete", 2))
        large = self.plan(3, ["pending"] * 101, turn="turn-b")
        for item in large["payload"]["plan"]:
            item["step"] = "x" * 400
        self.observe(large)
        cached = self.pet["pendingPlanEvents"][0]["plan"]
        self.assertEqual(len(cached), 100)
        self.assertTrue(all(len(item["step"]) == 200 for item in cached))
        self.observe(self.plan(4, turn="turn-c"), self.plan(5, turn="turn-d"))
        self.assertEqual(len(self.pet["pendingPlanEvents"]), MODULE.MAX_PENDING_PLAN_EVENTS)
        self.assertEqual([item["turnId"] for item in self.pet["pendingPlanEvents"]], ["turn-c", "turn-d"])
        invalid = self.plan(6, turn="turn-e")
        invalid["payload"]["plan"][0]["status"] = "imagined"
        before = copy.deepcopy(self.pet)
        self.observe(invalid)
        self.assertEqual(self.pet, before)


if __name__ == "__main__":
    unittest.main()
