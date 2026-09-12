"""Synthetic Desktop account events; never fixtures from a real conversation."""
import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
import uuid

SPEC = importlib.util.spec_from_file_location("quota_event_bridge", Path(__file__).resolve().parents[1] / "pm_pet_bridge.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class DesktopQuotaTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.sessions = self.root / "sessions"
        self.sessions.mkdir()
        self.identity = str(uuid.uuid4())
        self.path = self.sessions / (self.identity + ".jsonl")
        self.path.write_text(json.dumps({"type": "session_meta", "payload": {"id": self.identity}}) + "\n")
        self.bridge = MODULE.Bridge(self.root / "runtime", self.sessions)
        self.bridge.handle({"action": "enable", "id": self.identity})
        self.pet = self.bridge.pet(self.identity)
        self.initial = {"windows": {"week": {"remainingPercent": 47, "windowDurationMins": 10080}},
                        "source": "transcript", "observedAt": "2026-01-01T00:00:01.000000Z"}
        self.bridge.state["quota"] = copy.deepcopy(self.initial)

    def tearDown(self):
        self.temp.cleanup()

    @staticmethod
    def general(used=58):
        return {"limitId": "codex", "primary": {"usedPercent": used, "windowDurationMins": 10080, "resetsAt": 1800000000}, "secondary": None}

    def event(self, data=None, seconds=2):
        if data is None:
            data = {"rateLimits": self.general(53), "rateLimitsByLimitId": {"codex": self.general(),
                    "spark": {"primary": {"usedPercent": 0, "windowDurationMins": 300}}},
                    "accountId": "synthetic-account", "credits": {"balance": "synthetic-credit-value"}}
        return {"type": "event_msg", "timestamp": "2026-01-01T00:00:%02dZ" % seconds,
                "payload": {"type": "item_completed", "thread_id": self.identity,
                            "item": {"type": "McpToolCall", "server": "codex_app", "tool": "get_usage_limits", "status": "completed",
                                     "result": {"content": [{"type": "text", "text": json.dumps(data)}], "isError": False}}}}

    def apply(self, event):
        self.bridge.apply_event(self.pet, event)

    def assert_unchanged(self):
        self.assertEqual(self.bridge.state["quota"], self.initial)

    def test_desktop_weekly_read_updates_one_shared_snapshot(self):
        self.apply(self.event())
        quota = self.bridge.state["quota"]
        self.assertEqual(quota["windows"], {"week": {"remainingPercent": 42, "windowDurationMins": 10080, "resetsAt": 1800000000}})
        self.assertEqual(quota["source"], "codex-desktop-account")
        self.assertEqual(quota["sourceConversationId"], self.identity)
        self.assertEqual(quota["observedAt"], "2026-01-01T00:00:02.000000Z")
        self.assertNotIn("synthetic-account", json.dumps(self.bridge.state))
        self.assertNotIn("synthetic-credit-value", json.dumps(self.bridge.state))
        self.assertNotIn("quota", self.pet)

    def test_valid_map_without_general_clears_old_windows(self):
        for mapped in ({}, {"spark": {"primary": {"usedPercent": 0, "windowDurationMins": 300}}}):
            with self.subTest(mapped=mapped):
                self.bridge.state["quota"] = copy.deepcopy(self.initial)
                self.apply(self.event({"rateLimitsByLimitId": mapped, "rateLimits": self.general()}))
                self.assertEqual(self.bridge.state["quota"]["windows"], {})
                self.assertEqual(self.bridge.state["quota"]["source"], "codex-desktop-account")

    def test_missing_or_null_map_uses_legacy(self):
        for data in ({"rateLimits": self.general()}, {"rateLimitsByLimitId": None, "rateLimits": self.general()}):
            with self.subTest(data=data):
                self.bridge.state["quota"] = copy.deepcopy(self.initial)
                self.apply(self.event(data))
                self.assertEqual(self.bridge.state["quota"]["windows"]["week"]["remainingPercent"], 42)

    def test_known_unavailable_clears_old_windows(self):
        for limits in (None, {"primary": None, "secondary": None},
                       {"primary": {"windowDurationMins": 1440, "usedPercent": 10}},
                       {"limitId": "spark", "primary": {"windowDurationMins": 300, "usedPercent": 0}}):
            with self.subTest(limits=limits):
                self.bridge.state["quota"] = copy.deepcopy(self.initial)
                self.apply(self.event({"rateLimits": limits}))
                self.assertEqual(self.bridge.state["quota"]["windows"], {})

    def test_malformed_payload_does_not_refresh_last_good(self):
        cases = [{}, {"rateLimitsByLimitId": None}, {"rateLimitsByLimitId": []},
                 {"rateLimitsByLimitId": {"codex": None}}, {"rateLimits": []}, {"rateLimits": {}},
                 {"rateLimits": {"primary": "invalid"}},
                 {"rateLimitsByLimitId": {"codex": {"limitId": "spark", "primary": None}}}]
        for value in (True, None, "58", float("nan"), float("inf")):
            limits = self.general(value)
            cases.append({"rateLimits": limits})
        for duration in (True, None, 0, -300, 300.5, "10080", float("inf")):
            limits = self.general()
            limits["primary"]["windowDurationMins"] = duration
            cases.append({"rateLimits": limits})
        for data in cases:
            with self.subTest(data=data):
                self.apply(self.event(data))
                self.assert_unchanged()

    def test_failed_or_unproven_tool_cannot_write_quota(self):
        mutations = [("type", "CommandExecution"), ("server", "another_server"), ("tool", "another_tool"),
                     ("status", "failed"), ("status", "running")]
        for key, value in mutations:
            with self.subTest(key=key, value=value):
                event = self.event()
                event["payload"]["item"][key] = value
                self.apply(event)
                self.assert_unchanged()
        event = self.event()
        event["payload"]["item"]["result"]["isError"] = True
        self.apply(event)
        self.assert_unchanged()

    def test_exact_root_ownership_is_required(self):
        for owner in (None, "", str(uuid.uuid4())):
            event = self.event()
            event["payload"]["thread_id"] = owner
            self.apply(event)
            self.assert_unchanged()

    def test_prose_and_exec_output_cannot_impersonate_account_read(self):
        event = self.event()
        content = event["payload"]["item"]["result"]
        for item in ({"type": "UserMessage", "id": "example", "content": json.dumps(content)},
                     {"type": "CommandExecution", "stdout": json.dumps(content)},
                     {"type": "McpToolCall", "server": "functions", "tool": "exec", "status": "completed", "result": content}):
            event["payload"]["item"] = item
            self.apply(event)
            self.assert_unchanged()

    def test_structured_content_is_supported(self):
        event = self.event()
        event["payload"]["item"]["result"] = {"structuredContent": {"rateLimits": self.general()}, "isError": False}
        self.apply(event)
        self.assertEqual(self.bridge.state["quota"]["windows"]["week"]["remainingPercent"], 42)

    def test_invalid_reset_time_cannot_break_state_serialization(self):
        for reset in (float("nan"), float("inf"), -1, True, "tomorrow"):
            limits = self.general()
            limits["primary"]["resetsAt"] = reset
            self.bridge.state["quota"] = copy.deepcopy(self.initial)
            self.apply(self.event({"rateLimits": limits}))
            self.assertNotIn("resetsAt", self.bridge.state["quota"]["windows"]["week"])
            self.bridge.publish()

    def test_unparseable_or_ambiguous_content_is_not_fresh(self):
        for content in (None, {}, [{"type": "text", "text": "not JSON"}],
                        [{"type": "text", "text": json.dumps({"rateLimits": self.general()})}] * 2):
            event = self.event()
            event["payload"]["item"]["result"]["content"] = content
            self.apply(event)
            self.assert_unchanged()

    def test_older_or_replayed_read_does_not_regress_or_refresh(self):
        self.apply(self.event(seconds=3))
        expected = copy.deepcopy(self.bridge.state["quota"])
        self.apply(self.event({"rateLimits": self.general(10)}, seconds=2))
        self.apply(self.event({"rateLimits": self.general(10)}, seconds=3))
        self.assertEqual(self.bridge.state["quota"], expected)

    def test_waiting_question_and_newer_roadmap_do_not_block_usage(self):
        self.pet.update(question={"id": "q1", "text": "A synthetic choice"}, phase="waiting", reportObservedAt="2026-01-01T00:00:05Z")
        before = copy.deepcopy(self.pet)
        self.apply(self.event())
        self.assertEqual(self.bridge.state["quota"]["windows"]["week"]["remainingPercent"], 42)
        self.assertEqual(self.pet, before)

    def test_replay_from_bound_transcript_survives_restart_without_refreshed_time(self):
        with self.path.open("a") as handle:
            handle.write(json.dumps(self.event()) + "\n")
        self.bridge.poll_transcripts(1)
        expected = copy.deepcopy(self.bridge.state["quota"])
        restored = MODULE.Bridge(self.root / "runtime", self.sessions)
        restored.poll_transcripts(99)
        self.assertEqual(restored.state["quota"], expected)

    def test_no_event_timestamp_is_not_a_fresh_read(self):
        event = self.event()
        del event["timestamp"]
        self.apply(event)
        self.assert_unchanged()


    def poll_result(self, result):
        class Scheduler:
            def tick(inner, pets, binding):
                return result, {"mode": "error" if result.get("errorCode") else "automatic"}
        self.bridge.poll_quota(Scheduler())

    def test_delayed_desktop_switch_has_independent_clock(self):
        self.apply(self.event())
        fingerprint = self.bridge.state["quotaBinding"]["fingerprint"]
        self.poll_result({"status": "ok", "accountFingerprint": fingerprint,
                          "observedAt": "2026-01-01T00:00:10Z", "windows": {}})
        self.apply(self.event({"rateLimits": self.general(75), "accountId": "account-B"}, seconds=3))
        self.assertEqual(self.bridge.state["quota"]["windows"]["week"]["remainingPercent"], 25)
        self.assertNotEqual(self.bridge.state["quotaBinding"]["fingerprint"], fingerprint)
        before = copy.deepcopy(self.bridge.state["quota"])
        self.apply(self.event())
        self.assertEqual(self.bridge.state["quota"], before)

    def test_unknown_transcript_account_cannot_replace_binding(self):
        self.apply(self.event())
        before = copy.deepcopy(self.bridge.state["quota"])
        self.bridge.observe_quota(self.pet, {"source": "transcript", "observedAt": "2026-01-01T00:00:10Z", "windows": {}})
        self.assertEqual(self.bridge.state["quota"], before)

    def test_transient_failure_preserves_real_age_and_pet_state(self):
        self.apply(self.event())
        before = copy.deepcopy(self.bridge.state["quota"])
        pet = copy.deepcopy(self.pet)
        self.poll_result({"status": "unavailable", "errorCode": "read_failed"})
        for key, value in before.items():
            self.assertEqual(self.bridge.state["quota"][key], value)
        self.assertEqual(self.pet, pet)

    def test_auth_failure_replay_cannot_resurrect_cleared_snapshot(self):
        self.apply(self.event())
        self.poll_result({"status": "unavailable", "errorCode": "account_mismatch"})
        self.assertEqual(self.bridge.state["quota"]["windows"], {})
        self.assertIsNone(self.bridge.state["quota"]["observedAt"])
        self.apply(self.event())
        self.assertEqual(self.bridge.state["quota"]["windows"], {})
        restored = MODULE.Bridge(self.root / "runtime", self.sessions)
        restored.apply_event(restored.pet(self.identity), self.event())
        self.assertEqual(restored.state["quota"]["windows"], {})
        self.apply(self.event(seconds=3))
        self.assertEqual(self.bridge.state["quota"]["windows"]["week"]["remainingPercent"], 42)


if __name__ == "__main__":
    unittest.main()
