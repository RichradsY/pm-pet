"""Quota reader tests use synthetic auth documents and an isolated fake server."""

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest import mock


SCRIPT = Path(__file__).resolve().parents[1] / "quota_reader.py"
SPEC = importlib.util.spec_from_file_location("pm_pet_quota_reader", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def fingerprint(value="synthetic-account-a"):
    return hashlib.sha256(("pm-pet-account-v1:" + value).encode()).hexdigest()


def bucket(duration=10080, used=25):
    return {"limitId": "codex", "primary": {
        "usedPercent": used, "windowDurationMins": duration, "resetsAt": 1800000000,
    }, "secondary": None, "credits": {"secret": "DO-NOT-EXPORT-CREDITS"}}


class FakeServer:
    def __init__(self):
        self.calls = []
        self.closed = False
        self.result = {"rateLimitsByLimitId": {"codex": bucket()}}
        self.account = {"type": "chatgpt", "email": "DO-NOT-EXPORT-EMAIL"}
        self.after_limits = None
        self.failure = None

    def request(self, request_id, method, params):
        self.calls.append((request_id, method, params))
        if self.failure is not None and method == self.failure[0]:
            raise MODULE.QuotaReadError(self.failure[1])
        if method == "initialize":
            return {}
        if method == "account/read":
            return {"account": self.account}
        if method == "account/rateLimits/read":
            if self.after_limits:
                self.after_limits()
            return self.result
        raise AssertionError("Unexpected method")

    def send(self, value):
        self.calls.append(value)

    def close(self):
        self.closed = True


class VerifiedQuotaTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name).resolve()
        self.auth = self.home / "auth.json"
        self.write_auth()
        self.server = FakeServer()
        self.launch_patch = mock.patch.object(MODULE, "_ReadOnlyAppServer", return_value=self.server)
        self.launch = self.launch_patch.start()
        self.addCleanup(self.launch_patch.stop)

    def write_auth(self, account="synthetic-account-a", **values):
        document = {"auth_mode": "chatgpt", "tokens": {
            "account_id": account, "access_token": "DO-NOT-EXPORT-TOKEN",
            "refresh_token": "DO-NOT-EXPORT-REFRESH",
        }}
        document.update(values)
        self.auth.write_text(json.dumps(document), encoding="utf-8")

    def read(self, **kwargs):
        values = {"expected_fingerprint": fingerprint(), "codex_binary": "/fake/codex",
                  "codex_home": self.home}
        values.update(kwargs)
        return MODULE.read_verified_codex_quota(**values)

    def unavailable(self, result, code):
        self.assertEqual(result["status"], "unavailable")
        self.assertEqual(result["errorCode"], code)
        self.assertFalse(result["desktopAccountVerified"])
        self.assertNotIn("observedAt", result)
        self.assertNotIn("windows", result)
        self.assertNotIn("accountFingerprint", result)
        self.assertNotIn("DO-NOT-EXPORT", json.dumps(result))
        self.assertNotIn("synthetic-account", json.dumps(result))

    def test_verified_weekly_snapshot_omits_missing_five_and_private_data(self):
        result = self.read()
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["source"], "codex-cli-verified")
        self.assertTrue(result["desktopAccountVerified"])
        self.assertEqual(result["accountFingerprint"], fingerprint())
        self.assertEqual(result["selectedLimitId"], "codex")
        self.assertEqual(set(result["windows"]), {"week"})
        self.assertEqual(result["windows"]["week"]["remainingPercent"], 75)
        self.assertIn("observedAt", result)
        self.assertNotIn("buckets", result)
        self.assertNotIn("DO-NOT-EXPORT", json.dumps(result))
        self.assertNotIn("synthetic-account", json.dumps(result))
        self.assertTrue(self.server.closed)
        self.assertIn((2, "account/read", {"refreshToken": False}), self.server.calls)
        self.assertEqual([value[1] for value in self.server.calls if isinstance(value, tuple)],
                         ["initialize", "account/read", "account/rateLimits/read"])

    def test_process_pins_file_store_and_home_without_changing_parent_environment(self):
        alternate = {key: "DO-NOT-EXPORT-ENV" for key in MODULE.ALTERNATE_AUTH_ENV}
        alternate.update({"CODEX_HOME": "/unrelated/home", "CODEX_CA_CERTIFICATE": "/safe/ca.pem",
                          "CODEX_MANAGED_CONFIG_PATH": "/safe/managed.toml"})
        with mock.patch.dict(os.environ, alternate):
            self.assertEqual(self.read()["status"], "ok")
            child = self.launch.call_args.kwargs
            self.assertEqual(child["extra_args"], ["-c", 'cli_auth_credentials_store="file"'])
            self.assertEqual(child["env"]["CODEX_HOME"], str(self.home))
            self.assertEqual(child["env"]["CODEX_CA_CERTIFICATE"], "/safe/ca.pem")
            self.assertEqual(child["env"]["CODEX_MANAGED_CONFIG_PATH"], "/safe/managed.toml")
            for key in MODULE.ALTERNATE_AUTH_ENV:
                self.assertNotIn(key, child["env"])
                self.assertEqual(os.environ[key], "DO-NOT-EXPORT-ENV")
            self.assertNotIn("forced_chatgpt_workspace_id", str(child["extra_args"]))
            self.assertEqual(os.environ["CODEX_HOME"], "/unrelated/home")

    def test_default_home_uses_environment_and_normalizes_expected_hex(self):
        with mock.patch.dict(os.environ, {"CODEX_HOME": str(self.home)}):
            result = self.read(codex_home=None, expected_fingerprint=fingerprint().upper())
        self.assertEqual(result["accountFingerprint"], fingerprint())

    def test_invalid_binding_and_timeout_never_read_metadata_or_launch(self):
        with mock.patch.object(MODULE, "_account_metadata_snapshot") as metadata:
            for invalid in (None, "", "a" * 63, "z" * 64, "a" * 65, 17):
                with self.subTest(invalid=invalid):
                    self.unavailable(self.read(expected_fingerprint=invalid), "invalid_fingerprint")
            for invalid in (0, -1, True, float("nan"), "15"):
                with self.subTest(timeout=invalid):
                    self.unavailable(self.read(timeout=invalid), "invalid_timeout")
            metadata.assert_not_called()
        self.launch.assert_not_called()

    def test_different_account_before_read_does_not_start_server(self):
        self.write_auth("synthetic-account-b")
        self.unavailable(self.read(), "account_mismatch")
        self.launch.assert_not_called()

    def test_absent_auth_file_or_home_never_falls_back_to_keychain(self):
        self.auth.unlink()
        self.unavailable(self.read(), "auth_metadata_unavailable")
        self.unavailable(self.read(codex_home=self.home / "missing"), "auth_metadata_unavailable")
        self.unavailable(self.read(codex_home=""), "auth_metadata_unavailable")
        self.launch.assert_not_called()

    def test_unusable_auth_metadata_is_sanitized(self):
        documents = [None, [], {}, {"auth_mode": "apikey"},
                     {"auth_mode": "chatgpt", "tokens": []}]
        for account in (None, "", " a ", "a\n", 12, "a" * 513):
            documents.append({"auth_mode": "chatgpt", "tokens": {"account_id": account}})
        for document in documents:
            with self.subTest(document=document):
                self.auth.write_text(json.dumps(document), encoding="utf-8")
                self.unavailable(self.read(), "auth_metadata_unavailable")
        self.auth.write_bytes(b'\xff{"tokens":"DO-NOT-EXPORT"}')
        self.unavailable(self.read(), "auth_metadata_unavailable")
        self.launch.assert_not_called()

    def test_oversized_symlink_and_nonregular_auth_files_are_rejected(self):
        self.auth.write_bytes(b" " * (MODULE.MAX_AUTH_METADATA_BYTES + 1))
        self.unavailable(self.read(), "auth_metadata_unavailable")
        self.auth.unlink()
        target = self.home / "elsewhere.json"
        target.write_text('{}', encoding="utf-8")
        self.auth.symlink_to(target)
        self.unavailable(self.read(), "auth_metadata_unavailable")
        self.auth.unlink()
        os.mkfifo(self.auth)
        started = time.monotonic()
        self.unavailable(self.read(), "auth_metadata_unavailable")
        self.assertLess(time.monotonic() - started, 0.5)
        self.launch.assert_not_called()

    def test_account_switch_during_request_discards_snapshot(self):
        self.server.after_limits = lambda: self.write_auth("synthetic-account-b")
        self.unavailable(self.read(), "account_changed")
        self.assertTrue(self.server.closed)

    def test_same_account_file_refresh_discards_snapshot(self):
        self.server.after_limits = lambda: self.write_auth(last_refresh="new-synthetic-refresh")
        self.unavailable(self.read(), "auth_changed")
        self.assertTrue(self.server.closed)

    def test_account_away_and_back_still_discards_snapshot(self):
        before = self.auth.stat()
        def change_back():
            self.write_auth("synthetic-account-b")
            self.write_auth()
            os.utime(self.auth, ns=(before.st_atime_ns, before.st_mtime_ns + 1_000_000))
        self.server.after_limits = change_back
        self.unavailable(self.read(), "auth_changed")

    def test_auth_replaced_with_identical_bytes_is_detected(self):
        def replace_auth():
            replacement = self.home / "replacement.json"
            replacement.write_bytes(self.auth.read_bytes())
            replacement.replace(self.auth)
        self.server.after_limits = replace_auth
        self.unavailable(self.read(), "auth_changed")

    def test_auth_removed_during_read_discards_snapshot(self):
        self.server.after_limits = self.auth.unlink
        self.unavailable(self.read(), "auth_metadata_unavailable")
        self.assertTrue(self.server.closed)

    def test_api_key_or_missing_account_response_discards_snapshot(self):
        for account, code in ((None, "auth_required"), ({"type": "apiKey"}, "unsupported_account")):
            with self.subTest(account=account):
                self.server.account = account
                self.unavailable(self.read(), code)
                self.assertTrue(self.server.closed)

    def test_server_error_is_sanitized_and_always_closed(self):
        for stage in ("initialize", "account/read", "account/rateLimits/read"):
            with self.subTest(stage=stage):
                self.server.failure = (stage, "read_failed")
                self.unavailable(self.read(), "read_failed")
                self.assertTrue(self.server.closed)

    def test_cleanup_failure_cannot_escape_or_publish_success(self):
        with mock.patch.object(self.server, "close", side_effect=OSError("DO-NOT-EXPORT-CLEANUP")):
            self.unavailable(self.read(), "server_cleanup_failed")

    def test_malformed_maps_buckets_and_windows_cannot_fabricate_fresh_success(self):
        invalid = [None, {}, {"rateLimitsByLimitId": []},
                   {"rateLimitsByLimitId": [], "rateLimits": bucket()},
                   {"rateLimitsByLimitId": {"codex": None}},
                   {"rateLimitsByLimitId": {"codex": {}}},
                   {"rateLimits": {"limitId": []}},
                   {"rateLimitsByLimitId": {"codex": {**bucket(), "limitId": "other"}}}]
        for field, bad in (("usedPercent", True), ("usedPercent", 101), ("usedPercent", -1),
                           ("usedPercent", float("nan")), ("windowDurationMins", "300"),
                           ("windowDurationMins", 0), ("resetsAt", "tomorrow")):
            value = bucket()
            value["primary"][field] = bad
            invalid.append({"rateLimitsByLimitId": {"codex": value}})
        for response in invalid:
            with self.subTest(response=response):
                self.server.result = response
                self.unavailable(self.read(), "invalid_response")
                self.assertTrue(self.server.closed)

    def test_known_empty_limits_are_successful_but_never_invent_windows(self):
        for response, selected in (({"rateLimitsByLimitId": {}}, None),
                                   ({"rateLimitsByLimitId": None, "rateLimits": None}, None),
                                   ({"rateLimitsByLimitId": {"codex": {"primary": None, "secondary": None}}}, "codex")):
            with self.subTest(response=response):
                self.server.result = response
                result = self.read()
                self.assertEqual(result["status"], "ok")
                self.assertEqual(result["windows"], {})
                self.assertEqual(result["selectedLimitId"], selected)

    def test_other_bucket_does_not_add_five_hour_limit_to_general_weekly(self):
        special = bucket(300)
        special["limitId"] = "codex_special"
        self.server.result["rateLimitsByLimitId"]["codex_special"] = special
        result = self.read()
        self.assertEqual(set(result["windows"]), {"week"})
        self.assertNotIn("buckets", result)

    def test_legacy_quota_response_remains_supported(self):
        self.server.result = {"rateLimitsByLimitId": None, "rateLimits": bucket()}
        self.assertEqual(self.read()["windows"]["week"]["remainingPercent"], 75)

    def test_cancellation_before_launch_and_after_response_never_returns_snapshot(self):
        cancellation = threading.Event()
        cancellation.set()
        self.unavailable(self.read(cancel_event=cancellation), "cancelled")
        self.launch.assert_not_called()
        cancellation.clear()
        self.server.after_limits = cancellation.set
        self.unavailable(self.read(cancel_event=cancellation), "cancelled")
        self.assertTrue(self.server.closed)

    def test_unverified_diagnostic_never_reads_auth_metadata(self):
        with mock.patch.object(MODULE, "_account_metadata_snapshot", side_effect=AssertionError("must not read")):
            result = MODULE.read_codex_quota("/fake/codex")
        self.assertEqual(result["status"], "ok")
        self.assertFalse(result["desktopAccountVerified"])
        self.assertEqual(result["source"], "codex-cli-app-server")
        self.assertNotIn("accountFingerprint", result)
        self.assertEqual(self.launch.call_args.kwargs, {})


class QuotaServerCancellationTests(unittest.TestCase):
    def test_cancel_waiting_request_and_stop_only_owned_fake_process(self):
        with tempfile.TemporaryDirectory() as directory:
            binary = Path(directory) / "fake-codex"
            binary.write_text("#!/usr/bin/env python3\nimport sys, time\nfor line in sys.stdin:\n    time.sleep(30)\n", encoding="utf-8")
            binary.chmod(0o700)
            cancel = threading.Event()
            server = MODULE._ReadOnlyAppServer(str(binary), 10, cancel_event=cancel)
            timer = threading.Timer(0.05, cancel.set)
            timer.start()
            started = time.monotonic()
            try:
                with self.assertRaises(MODULE.QuotaReadError) as raised:
                    server.request(1, "initialize", {})
                self.assertEqual(raised.exception.code, "cancelled")
                self.assertLess(time.monotonic() - started, 1)
            finally:
                server.close()
                timer.join()
            self.assertIsNotNone(server.process.poll())
            self.assertLess(time.monotonic() - started, 4)


if __name__ == "__main__":
    unittest.main()
