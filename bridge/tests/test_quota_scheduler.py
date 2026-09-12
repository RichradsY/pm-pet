"""Deterministic polling tests; no Codex processes, auth files, or network."""
import importlib.util
from pathlib import Path
import threading
import unittest

SPEC = importlib.util.spec_from_file_location("tested_quota_scheduler", Path(__file__).resolve().parents[1] / "quota_scheduler.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class QuotaSchedulerTests(unittest.TestCase):
    def setUp(self):
        self.now = 0
        self.calls = []
        self.binding = {"fingerprint": "a" * 64, "observedAt": "2026-01-01T00:00:00Z"}
        self.pets = [{"enabled": True, "quotaVisible": True, "turnState": {"status": "running"}}]
        self.result = {"status": "ok", "accountFingerprint": "a" * 64,
                       "observedAt": "2026-01-01T00:00:00Z", "windows": {}}
        def reader(fingerprint, cancel_event=None):
            self.calls.append(fingerprint)
            return dict(self.result)
        self.scheduler = MODULE.QuotaScheduler(reader, monotonic=lambda: self.now, wall_clock=lambda: 1767225600 + self.now)
        self.addCleanup(self.scheduler.close)

    def tick(self):
        return self.scheduler.tick(self.pets, self.binding)

    def finish(self):
        if self.scheduler.worker:
            self.scheduler.worker.join(timeout=1)
        return self.tick()

    def test_visible_allowances_poll_once_per_minute_for_all_five_pets(self):
        self.pets = [{"enabled": True, "quotaVisible": True, "phase": phase,
                      "turnState": {"status": turn}, "question": question}
                     for phase, turn, question in (
                         ("building", "running", None), ("idle", "ended", None),
                         ("waiting", "ended", {"id": "q1"}), ("planning", "input_received", None),
                         ("checking", "running", {"id": "q2"}))]
        self.tick()
        value, meta = self.finish()
        self.assertEqual(value["status"], "ok")
        self.assertEqual(meta["intervalSeconds"], 60)
        self.assertEqual(len(self.calls), 1)
        self.now = 59.99
        for _ in range(10):
            self.tick()
        self.assertEqual(len(self.calls), 1)
        self.now = 60
        self.tick()
        self.finish()
        self.assertEqual(len(self.calls), 2)

    def test_only_visible_pet_ended_with_question_still_polls_every_minute(self):
        # Other Codex work can be active without being bound to a Pet. The
        # scheduler cannot rely on unbound task activity, so no active peer is needed.
        self.pets[0].update(phase="waiting", turnState={"status": "ended"}, question={"id": "q1"})
        self.tick()
        _, meta = self.finish()
        self.assertEqual(meta["intervalSeconds"], 60)
        self.now = 30
        self.pets.append({"enabled": False, "quotaVisible": True, "phase": "building",
                          "turnState": {"status": "running"}})
        self.assertEqual(self.tick()[1]["nextAttemptAt"], meta["nextAttemptAt"])
        self.now = 59
        self.tick()
        self.assertEqual(len(self.calls), 1)
        self.now = 60
        self.tick()
        self.finish()
        self.assertEqual(len(self.calls), 2)

    def test_phase_turn_and_question_changes_do_not_move_refresh_deadline(self):
        self.tick()
        self.finish()
        deadline = self.scheduler.meta["nextAttemptAt"]
        changes = ((10, "building", "running", None), (20, "idle", "ended", None),
                   (30, "waiting", "ended", {"id": "synthetic"}),
                   (40, "planning", "input_received", {"id": "synthetic"}),
                   (50, "checking", "running", None), (59, "idle", "interrupted", None))
        for at, phase, turn, question in changes:
            with self.subTest(phase=phase, turn=turn, question=question):
                self.now = at
                self.pets[0].update(phase=phase, turnState={"status": turn}, question=question)
                _, meta = self.tick()
                self.assertEqual(meta["intervalSeconds"], 60)
                self.assertEqual(meta["nextAttemptAt"], deadline)
                self.assertEqual(self.scheduler.next_due, 60)
                self.assertEqual(len(self.calls), 1)
        self.now = 60
        self.tick()
        self.finish()
        self.assertEqual(len(self.calls), 2)
        self.assertEqual(self.scheduler.next_due, 120)

    def test_hidden_disabled_or_unmatched_never_query(self):
        self.pets[0]["quotaVisible"] = False
        self.assertEqual(self.tick()[1]["mode"], "paused")
        self.pets[0].update(enabled=False, quotaVisible=True)
        self.assertEqual(self.tick()[1]["mode"], "paused")
        self.pets[0]["enabled"] = True
        self.binding = None
        self.assertEqual(self.tick()[1]["mode"], "waiting_for_account")
        self.binding = {"fingerprint": "invalid"}
        self.tick()
        self.assertEqual(self.calls, [])

    def test_hide_restore_does_not_allow_fast_repeated_reads(self):
        self.tick()
        self.finish()
        self.now = 1
        self.pets[0]["quotaVisible"] = False
        self.tick()
        self.pets[0]["quotaVisible"] = True
        self.tick()
        self.now = 59
        self.tick()
        self.assertEqual(len(self.calls), 1)
        self.now = 60
        self.tick()
        self.finish()
        self.assertEqual(len(self.calls), 2)

    def test_errors_preserve_last_success_and_back_off(self):
        self.tick()
        self.finish()
        self.result = {"status": "unavailable", "errorCode": "rate_limited"}
        self.now = 60
        self.tick()
        value, meta = self.finish()
        self.assertEqual(meta["mode"], "error")
        self.assertEqual(value["errorCode"], "rate_limited")
        self.assertEqual(meta["lastSuccessAt"], "2026-01-01T00:00:00Z")
        self.assertEqual(self.scheduler.next_due, 120)
        self.now = 120
        self.tick()
        self.finish()
        self.assertEqual(self.scheduler.next_due, 240)

    def test_inflight_account_change_discards_old_success(self):
        started, release = threading.Event(), threading.Event()
        def reader(fingerprint, cancel_event=None):
            self.calls.append(fingerprint)
            started.set()
            release.wait(1)
            return {"status": "ok", "accountFingerprint": fingerprint}
        self.scheduler.reader = reader
        self.tick()
        self.assertTrue(started.wait(1))
        self.binding = {"fingerprint": "b" * 64, "observedAt": "2026-01-01T00:00:01Z"}
        self.tick()
        release.set()
        value, _ = self.finish()
        self.assertIsNone(value)
        self.assertEqual(self.calls, ["a" * 64])
        self.now = 10
        self.tick()
        self.finish()
        self.assertEqual(self.calls, ["a" * 64, "b" * 64])

    def test_hiding_during_read_cancels_and_discards_result(self):
        started = threading.Event()
        def reader(fingerprint, cancel_event=None):
            started.set()
            cancel_event.wait(1)
            return {"status": "unavailable", "errorCode": "account_mismatch"}
        self.scheduler.reader = reader
        self.tick()
        self.assertTrue(started.wait(1))
        self.pets[0]["quotaVisible"] = False
        self.tick()
        result, meta = self.finish()
        self.assertIsNone(result)
        self.assertEqual(meta["mode"], "paused")

    def test_tick_never_waits_on_slow_reader_and_close_cancels(self):
        started = threading.Event()
        def reader(fingerprint, cancel_event=None):
            started.set()
            cancel_event.wait(2)
            return {"status": "unavailable", "errorCode": "cancelled"}
        self.scheduler.reader = reader
        _, meta = self.tick()
        self.assertEqual(meta["mode"], "refreshing")
        self.assertTrue(started.wait(1))
        for _ in range(5):
            self.assertEqual(self.tick()[1]["mode"], "refreshing")
        self.scheduler.close()
        self.assertFalse(self.scheduler.worker.is_alive())

    def test_unchanged_ticks_do_not_rewrite_next_attempt_timestamp(self):
        self.tick()
        self.finish()
        before = dict(self.scheduler.meta)
        self.now = 1.5
        self.assertEqual(self.tick()[1], before)

    def test_moving_visible_allowance_between_pets_keeps_shared_deadline(self):
        self.pets = [{"enabled": True, "quotaVisible": index == 0} for index in range(5)]
        self.tick()
        self.finish()
        deadline = self.scheduler.meta["nextAttemptAt"]
        epoch = self.scheduler.epoch
        for index in range(1, 5):
            self.now = index * 10
            for pet_index, pet in enumerate(self.pets):
                pet["quotaVisible"] = pet_index == index
            self.assertEqual(self.tick()[1]["nextAttemptAt"], deadline)
            self.assertEqual(self.scheduler.epoch, epoch)
        self.assertEqual(len(self.calls), 1)
        self.now = 60
        self.tick()
        self.finish()
        self.assertEqual(len(self.calls), 2)

    def test_minute_interval_starts_after_success_not_request_start(self):
        started, release = threading.Event(), threading.Event()
        def reader(fingerprint, cancel_event=None):
            self.calls.append(fingerprint)
            started.set()
            release.wait(1)
            return dict(self.result)
        self.scheduler.reader = reader
        self.tick()
        self.assertTrue(started.wait(1))
        self.now = 30
        release.set()
        self.finish()
        self.assertEqual(self.scheduler.next_due, 90)
        self.now = 60
        self.tick()
        self.assertEqual(len(self.calls), 1)
        self.now = 90
        self.tick()
        self.finish()
        self.assertEqual(len(self.calls), 2)

    def test_disabling_all_visible_pets_cancels_inflight_and_discards_success(self):
        started = threading.Event()
        def reader(fingerprint, cancel_event=None):
            started.set()
            cancel_event.wait(1)
            return dict(self.result)
        self.scheduler.reader = reader
        self.tick()
        self.assertTrue(started.wait(1))
        self.pets[0]["enabled"] = False
        self.tick()
        value, meta = self.finish()
        self.assertIsNone(value)
        self.assertEqual(meta["mode"], "paused")
        self.assertIsNone(meta["intervalSeconds"])
        self.assertIsNone(meta["nextAttemptAt"])

    def test_hide_restore_during_cancel_keeps_one_worker_and_attempt_minimum(self):
        started, release = threading.Event(), threading.Event()
        cancellation = []
        def reader(fingerprint, cancel_event=None):
            self.calls.append(fingerprint)
            cancellation.append(cancel_event)
            started.set()
            release.wait(1)
            return dict(self.result)
        self.scheduler.reader = reader
        self.tick()
        self.assertTrue(started.wait(1))
        self.pets[0]["quotaVisible"] = False
        self.tick()
        self.assertTrue(cancellation[0].is_set())
        self.now = 1
        self.pets[0]["quotaVisible"] = True
        self.tick()
        self.assertEqual(len(self.calls), 1)
        release.set()
        self.assertIsNone(self.finish()[0])
        self.now = 9.99
        self.tick()
        self.assertEqual(len(self.calls), 1)
        self.now = 10
        self.tick()
        self.finish()
        self.assertEqual(len(self.calls), 2)
        self.assertEqual(self.scheduler.next_due, 70)

    def test_state_changes_do_not_reduce_or_extend_error_backoff(self):
        self.result = {"status": "unavailable", "errorCode": "read_failed"}
        self.tick()
        self.finish()
        for next_due in (60, 180):
            deadline = self.scheduler.meta["nextAttemptAt"]
            self.now += 10
            self.pets[0].update(phase="waiting", turnState={"status": "ended"}, question={"id": "q1"})
            self.assertEqual(self.tick()[1]["nextAttemptAt"], deadline)
            self.assertEqual(self.scheduler.next_due, next_due)
            self.pets[0].update(phase="building", turnState={"status": "running"}, question=None)
            self.assertEqual(self.tick()[1]["nextAttemptAt"], deadline)
            self.now = next_due
            self.tick()
            self.finish()
        self.result = {"status": "ok", "accountFingerprint": "a" * 64, "observedAt": "2026-01-01T00:07:00Z"}
        self.now = self.scheduler.next_due
        self.tick()
        self.finish()
        self.assertEqual(self.scheduler.failures, 0)
        self.assertEqual(self.scheduler.next_due, self.now + 60)

    def test_repeated_failures_are_capped_without_new_success_timestamp(self):
        self.result = {"status": "unavailable", "errorCode": "rate_limited"}
        for delay in (60, 120, 240, 480, 960, 1800, 1800):
            self.tick()
            _, meta = self.finish()
            self.assertEqual(self.scheduler.next_due, self.now + delay)
            self.assertNotIn("lastSuccessAt", meta)
            self.assertEqual(meta["intervalSeconds"], 60)
            self.now = self.scheduler.next_due


if __name__ == "__main__":
    unittest.main()
