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

    def test_active_polls_once_per_minute_for_all_five_pets(self):
        self.pets *= 5
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

    def test_idle_polls_every_five_minutes(self):
        self.pets[0]["turnState"]["status"] = "ended"
        self.tick()
        _, meta = self.finish()
        self.assertEqual(meta["intervalSeconds"], 300)
        self.now = 299
        self.tick()
        self.assertEqual(len(self.calls), 1)
        self.now = 300
        self.tick()
        self.finish()
        self.assertEqual(len(self.calls), 2)

    def test_actual_turn_activity_changes_cadence_and_questions_are_idle(self):
        self.tick()
        self.finish()
        self.pets[0]["question"] = {"id": "synthetic"}
        _, meta = self.tick()
        self.assertEqual(meta["intervalSeconds"], 300)
        self.now = 70
        self.pets[0]["question"] = None
        self.tick()
        self.finish()
        self.assertEqual(len(self.calls), 2)
        self.pets[0].update(phase="building", turnState={"status": "ended"})
        _, meta = self.tick()
        self.assertEqual(meta["intervalSeconds"], 300)

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


if __name__ == "__main__":
    unittest.main()
