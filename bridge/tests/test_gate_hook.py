"""Offline synthetic hook events; never load or mutate a real Codex runtime."""
import importlib.util
import json
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import unittest


HOOKS = Path(__file__).resolve().parents[2] / "integrations/codex/pm-pet/hooks"


def load(name):
    spec = importlib.util.spec_from_file_location(name, HOOKS / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


GATE = load("pm_pet_gate")
CONFIG = load("render_config")
ROOT_ID = "12345678-1234-1234-1234-123456789abc"
OTHER_ID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"


class GateHookTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name) / "PM Pet 'demo'"
        self.runtime = self.home / ".pm-pet/runtime"
        self.runtime.mkdir(parents=True)
        self.pet = {"id": ROOT_ID, "enabled": True, "question": None, "pendingQuestions": [],
                    "generation": 3, "lastReportSequence": 9}
        self.state = {"schemaVersion": 1, "pets": [self.pet]}
        self.save()
        self.heartbeat(100)

    def save(self):
        (self.runtime / "state.json").write_text(json.dumps(self.state))

    def heartbeat(self, value):
        (self.runtime / "heartbeat.json").write_text(json.dumps({"updatedAt": value}))

    def event(self, name="Bash", values=None, session=ROOT_ID, event="PreToolUse"):
        return {"hook_event_name": event, "session_id": session, "cwd": "/not/the/identity",
                "tool_name": name, "tool_input": {"command": "touch should-not-run"} if values is None else values}

    def evaluate(self, event=None):
        return GATE.evaluate(event or self.event(), self.home, self.runtime, now=103)

    def deny(self, event=None):
        result = self.evaluate(event)
        self.assertEqual(result["hookSpecificOutput"]["hookEventName"], "PreToolUse")
        self.assertEqual(result["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertTrue(result["hookSpecificOutput"]["permissionDecisionReason"])
        self.assertNotIn("continue", result)
        return result

    def pending(self, status="awaiting_reply"):
        question = {"id": "q-one", "status": status}
        self.pet.update(question=question, pendingQuestions=[question.copy()])
        self.save()

    def argv(self, action="status", extra=None):
        return ["python3", str(self.home / "scripts/pm-pet.py"), action,
                "--runtime", str(self.runtime), "--conversation", ROOT_ID, *(extra or [])]

    def command_event(self, args):
        return self.event(values={"command": shlex.join(args)})

    def report(self):
        return {"generation": 3, "sequence": 10, "resolveQuestionId": "q-one", "currentStep": "Review complete",
                "steps": [{"id": "review", "label": "Review user's answer; update scope & plan", "done": True}]}

    def report_event(self, report=None):
        return self.command_event(self.argv("report", ["--json", json.dumps(self.report() if report is None else report)]))

    def test_fresh_enabled_without_pending_defers_to_normal_policy(self):
        self.assertEqual(self.evaluate(), {})

    def test_pending_blocks_supported_build_tool_families(self):
        self.pending()
        for name in ("Bash", "apply_patch", "spawn_agent", "Agent", "mcp__fs__write", "update_plan", "followup_task"):
            with self.subTest(name=name):
                self.deny(self.event(name))

    def test_review_still_blocks_after_answer(self):
        self.pending("awaiting_review")
        self.deny()

    def test_queue_blocks_even_without_visible_head(self):
        self.pending("awaiting_review")
        self.pet["question"] = None
        self.save()
        self.deny()

    def test_manual_question_without_queue_blocks(self):
        self.pet["question"] = {"id": "manual"}
        self.save()
        self.deny()

    def test_exact_other_conversation_unaffected_even_with_same_cwd(self):
        self.pending()
        self.assertEqual(self.evaluate(self.event(session=OTHER_ID)), {})

    def test_child_hook_uses_parent_session_identity(self):
        self.pending()
        event = self.event("apply_patch")
        event["transcript_path"] = "/child/transcript.jsonl"
        self.deny(event)

    def test_disabled_conversation_unaffected(self):
        self.pending()
        self.pet["enabled"] = False
        self.save()
        (self.runtime / "heartbeat.json").unlink()
        self.assertEqual(self.evaluate(), {})

    def test_no_registered_pet_unaffected_by_missing_heartbeat(self):
        self.state["pets"] = []
        self.save()
        (self.runtime / "heartbeat.json").unlink()
        self.assertEqual(self.evaluate(), {})

    def test_missing_or_invalid_identity_fails_closed(self):
        for session in (None, "", "a-project-name", ROOT_ID[:8]):
            with self.subTest(session=session):
                self.deny(self.event(session=session))

    def test_stale_future_and_invalid_heartbeat_fail_closed(self):
        for value in (92, 200, None, "100", True, float("nan")):
            with self.subTest(value=value):
                self.heartbeat(value)
                self.deny()

    def test_missing_heartbeat_fails_closed_for_enabled_pet(self):
        (self.runtime / "heartbeat.json").unlink()
        self.deny()

    def test_missing_state_fails_closed_with_explicit_error(self):
        (self.runtime / "state.json").unlink()
        result = self.deny()
        self.assertIn("Cannot verify configured", result["hookSpecificOutput"]["permissionDecisionReason"])

    def test_malformed_state_fails_closed(self):
        for value in ([], {}, {"schemaVersion": 2, "pets": []}, {"schemaVersion": 1, "pets": [None]},
                      {"schemaVersion": 1, "pets": [self.pet, self.pet]}):
            with self.subTest(value=value):
                (self.runtime / "state.json").write_text(json.dumps(value))
                self.deny()

    def test_malformed_pending_shape_fails_closed(self):
        for value in ({}, "pending", [None]):
            with self.subTest(value=value):
                self.pet["pendingQuestions"] = value
                self.save()
                self.deny()

    def test_status_remains_available_during_pending_and_runtime_error(self):
        self.pending()
        event = self.command_event(self.argv())
        self.assertEqual(self.evaluate(event), {})
        (self.runtime / "state.json").unlink()
        self.assertEqual(self.evaluate(event), {})

    def test_only_exact_target_launcher_and_runtime_allowed(self):
        self.pending()
        for index, value in ((1, "/other/scripts/pm-pet.py"), (1, "scripts/pm-pet.py"),
                             (4, "/other/runtime"), (4, ".pm-pet/runtime"), (6, OTHER_ID), (0, "bash")):
            args = self.argv()
            args[index] = value
            with self.subTest(index=index, value=value):
                self.deny(self.command_event(args))

    def test_implicit_conversation_and_extra_flags_are_not_controls(self):
        self.pending()
        for args in (self.argv()[:5], self.argv(extra=["--all"]), self.argv(extra=["--conversation", ROOT_ID]),
                     self.argv(extra=["--json", "{}"]), self.argv(extra=["--timeout", "999"])):
            self.deny(self.command_event(args))

    def test_mutating_management_is_not_a_release(self):
        self.pending()
        for action in ("enable", "disable", "quit", "preferences", "start", "build"):
            with self.subTest(action=action):
                self.deny(self.command_event(self.argv(action)))

    def test_matching_full_review_report_allowed_without_overriding_approval(self):
        self.pending("awaiting_review")
        self.assertEqual(self.evaluate(self.report_event()), {})

    def test_report_file_path_must_be_absolute_and_existing(self):
        self.pending("awaiting_review")
        path = self.home / "review.json"
        path.write_text(json.dumps(self.report()))
        self.assertEqual(self.evaluate(self.command_event(self.argv("report", ["--file", str(path)]))), {})
        for value in ("review.json", "/missing/review.json"):
            self.deny(self.command_event(self.argv("report", ["--file", value])))

    def test_incomplete_wrong_or_stale_resolution_report_rejected(self):
        self.pending("awaiting_review")
        for key, value in (("resolveQuestionId", "wrong"), ("steps", None), ("currentStep", ""),
                           ("generation", 2), ("generation", True), ("sequence", 9)):
            report = self.report()
            report[key] = value
            with self.subTest(key=key):
                self.deny(self.report_event(report))

    def test_report_does_not_modify_or_resolve_runtime(self):
        self.pending("awaiting_review")
        before = (self.runtime / "state.json").read_bytes()
        self.assertEqual(self.evaluate(self.report_event()), {})
        self.assertEqual((self.runtime / "state.json").read_bytes(), before)
        self.deny()

    def test_shell_composition_and_expansion_rejected(self):
        self.pending()
        safe = shlex.join(self.argv())
        for command in (safe + "; touch BAD", safe + " && touch BAD", safe + " | cat", safe + " > output",
                        safe + "\ntouch BAD", "X=1 " + safe, "env " + safe,
                        safe + " $(touch BAD)", safe + ' "$(touch BAD)"', safe + " `touch BAD`",
                        safe + " ${HOME}", safe + " *", safe + " # comment", safe + " &"):
            with self.subTest(command=command):
                self.deny(self.event(values={"command": command}))

    def test_quoted_json_with_shell_characters_stays_literal(self):
        self.pending("awaiting_review")
        report = self.report()
        report["currentStep"] = "Review literal $(nothing) and `nothing`; no execution"
        self.assertEqual(self.evaluate(self.report_event(report)), {})

    def test_json_escaped_newline_is_literal_and_allowed(self):
        self.pending("awaiting_review")
        report = self.report()
        report["currentStep"] = "Review answer\nUpdate the plan"
        event = self.report_event(report)
        self.assertNotIn("\n", event["tool_input"]["command"])
        self.assertIn("\\n", event["tool_input"]["command"])
        self.assertEqual(self.evaluate(event), {})

    def test_known_exec_transport_command_fields(self):
        self.pending("awaiting_review")
        command = shlex.join(self.argv())
        for name in ("exec_command", "functions.exec_command"):
            with self.subTest(name=name):
                self.assertEqual(self.evaluate(self.event(name, {"cmd": command})), {})
                self.deny(self.event(name, {"command": command, "cmd": "touch BAD"}))
                self.deny(self.event(name, {"cmd": command, "shell": "/tmp/other-program"}))

    def test_only_stop_observation_tools_allowed(self):
        self.pending()
        for name, args in (("interrupt_agent", {"target": "child"}), ("collaboration.interrupt_agent", {"target": "child"}),
                           ("list_agents", {}), ("collaboration.list_agents", {"path_prefix": "/root"}),
                           ("wait_agent", {"timeout_ms": 60000})):
            with self.subTest(name=name):
                self.assertEqual(self.evaluate(self.event(name, args)), {})
        self.deny(self.event("interrupt_agent", {"target": "child", "message": "build"}))
        self.deny(self.event("wait_agent", {"timeout_ms": 60001}))
        self.deny(self.event("mcp__other__interrupt_agent", {"target": "child"}))

    def test_user_prompt_only_adds_metadata_never_resolves(self):
        self.pending("awaiting_review")
        before = (self.runtime / "state.json").read_bytes()
        event = self.event(event="UserPromptSubmit")
        event["prompt"] = "This must not be echoed or treated as an answer"
        result = self.evaluate(event)
        output = result["hookSpecificOutput"]
        self.assertEqual(output["hookEventName"], "UserPromptSubmit")
        self.assertNotIn(event["prompt"], output["additionalContext"])
        self.assertNotIn("permissionDecision", output)
        self.assertEqual((self.runtime / "state.json").read_bytes(), before)

    def test_cli_bad_input_returns_supported_deny_json(self):
        result = subprocess.run([sys.executable, str(HOOKS / "pm_pet_gate.py"), "--home", str(self.home)],
                                input="invalid", text=True, capture_output=True, check=True)
        self.assertEqual(json.loads(result.stdout)["hookSpecificOutput"]["permissionDecision"], "deny")

    def test_generator_quotes_paths_and_does_not_install_or_trust(self):
        config = CONFIG.configuration(self.home, self.runtime, Path(sys.executable))
        handler = config["hooks"]["PreToolUse"][0]["hooks"][0]
        self.assertEqual(shlex.split(handler["command"]), [sys.executable, str(self.home / "integrations/codex/pm-pet/hooks/pm_pet_gate.py"),
                         "--home", str(self.home), "--runtime", str(self.runtime)])
        self.assertNotIn("async", handler)
        self.assertNotIn("trusted_hash", json.dumps(config))
        self.assertFalse((self.home / ".codex").exists())


if __name__ == "__main__":
    unittest.main()
