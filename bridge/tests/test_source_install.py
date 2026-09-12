"""Source installer tests use isolated fake checkouts; never install into a user's home."""
import importlib.util
import contextlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


SOURCE = Path(__file__).resolve().parents[2] / "scripts/setup.py"


class SourceInstallTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="pm-pet-installer-")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.checkout = self.base / "checkout's $sample `literal`"
        self.prefix = self.base / "prefix with spaces"
        self.skill = self.base / "skills" / "pm-pet"
        for relative in ("scripts", "bridge", "native", "integrations/codex/pm-pet/agents", "integrations/codex/pm-pet/references"):
            (self.checkout / relative).mkdir(parents=True, exist_ok=True)
        shutil.copyfile(SOURCE, self.checkout / "scripts/setup.py")
        (self.checkout / "scripts/pm-pet.py").write_text(
            "import json, sys\nprint(json.dumps({'arguments': sys.argv[1:]}))\n", encoding="utf-8")
        (self.checkout / "bridge/pm_pet_bridge.py").write_text("# synthetic\n")
        (self.checkout / "native/build.sh").write_text("# synthetic; not executed\n")
        for name in ("SKILL.md", "agents/openai.yaml", "references/report-contract.md"):
            (self.checkout / "integrations/codex/pm-pet" / name).write_text("original " + name, encoding="utf-8")
        spec = importlib.util.spec_from_file_location("source_setup", self.checkout / "scripts/setup.py")
        self.setup = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.setup)
        self.command = self.prefix / "bin/pm-pet"

    def cli(self, *args, success=True):
        result = subprocess.run([sys.executable, str(self.checkout / "scripts/setup.py"), *args,
                                 "--prefix", str(self.prefix)], capture_output=True, text=True, cwd=str(self.base))
        if success:
            self.assertEqual(result.returncode, 0, result.stderr)
        else:
            self.assertNotEqual(result.returncode, 0, result.stdout)
        return result

    def installed(self, *args, success=True):
        result = subprocess.run([str(self.command), *args], capture_output=True, text=True, cwd=str(self.base))
        self.assertEqual(result.returncode == 0, success, result.stderr or result.stdout)
        return result

    def with_skill(self):
        return self.cli("install", "--with-skill", "--skill-dir", str(self.skill))

    def runtime(self):
        runtime = self.checkout / ".pm-pet/runtime"
        runtime.mkdir(parents=True)
        (runtime / "state.json").write_text(json.dumps({"schemaVersion": 1, "pets": []}))
        return runtime

    def test_installs_fixed_checkout_command_and_preserves_arguments(self):
        result = self.cli("install")
        self.assertIn("No app was built or started", result.stdout)
        output = self.installed("enable", "--title", "A $title `literal`", "--conversation", "123")
        self.assertEqual(json.loads(output.stdout)["arguments"], ["enable", "--title", "A $title `literal`", "--conversation", "123"])
        self.assertFalse(self.skill.exists())
        self.assertFalse((self.checkout / "build").exists())
        self.assertFalse((self.checkout / ".pm-pet").exists())

    def test_help_includes_lifecycle_and_install_management(self):
        self.cli("install")
        output = self.installed("--help").stdout
        for name in ("enable", "status", "disable", "quit", "doctor", "update", "uninstall"):
            self.assertIn(name, output)

    def test_optional_skill_pins_source_and_installs_no_hooks(self):
        self.with_skill()
        env = dict(os.environ, PM_PET_HOME="/a/different/checkout")
        result = subprocess.run([sys.executable, str(self.skill / "scripts/pm_pet.py"), "status"],
                                capture_output=True, text=True, env=env, cwd=str(self.base))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["arguments"], ["status"])
        self.assertFalse((self.skill / "hooks").exists())
        self.assertEqual({str(p.relative_to(self.skill)) for p in self.skill.rglob("*") if p.is_file()}, set(self.setup.SKILL_FILES))

    def test_installed_contract_link_points_to_existing_checkout_document(self):
        doc = self.checkout / "docs/FEEDBACK-GATE.md"
        doc.parent.mkdir()
        doc.write_text("Feedback gate workflow")
        contract = self.checkout / "integrations/codex/pm-pet/references/report-contract.md"
        contract.write_text("Read [workflow](../../../../docs/FEEDBACK-GATE.md).")
        self.with_skill()
        self.assertIn("(<" + str(doc) + ">)", (self.skill / "references/report-contract.md").read_text())
        self.assertTrue(doc.is_file())

    def test_reinstall_is_idempotent_and_option_change_is_explicit(self):
        self.cli("install")
        before = self.command.read_bytes()
        self.assertIn("Already installed", self.cli("install").stdout)
        self.cli("install", "--with-skill", "--skill-dir", str(self.skill), success=False)
        self.assertEqual(self.command.read_bytes(), before)

    def test_skill_dir_requires_opt_in(self):
        self.cli("install", "--skill-dir", str(self.skill), success=False)
        self.assertFalse(self.prefix.exists())

    def test_unknown_existing_command_is_not_overwritten(self):
        self.command.parent.mkdir(parents=True)
        self.command.write_text("someone else's command")
        self.cli("install", success=False)
        self.assertEqual(self.command.read_text(), "someone else's command")
        self.assertFalse(self.setup.manifest_path(self.prefix).exists())

    def test_existing_skill_directory_is_not_overwritten_even_if_empty(self):
        self.skill.mkdir(parents=True)
        self.cli("install", "--with-skill", "--skill-dir", str(self.skill), success=False)
        self.assertFalse(self.command.exists())

    def test_unknown_metadata_directory_is_not_adopted(self):
        directory = self.setup.manifest_path(self.prefix).parent
        directory.mkdir(parents=True)
        self.cli("install", success=False)
        self.assertTrue(directory.is_dir())
        self.assertFalse(self.command.exists())

    def test_symlink_command_and_managed_ancestor_are_rejected(self):
        self.command.parent.mkdir(parents=True)
        target = self.base / "unrelated"
        target.write_text("keep")
        self.command.symlink_to(target)
        self.cli("install", success=False)
        self.assertEqual(target.read_text(), "keep")
        self.command.unlink()
        self.command.parent.rmdir()
        folder = self.base / "other-bin"
        folder.mkdir()
        self.command.parent.symlink_to(folder)
        self.cli("install", success=False)
        self.assertEqual(list(folder.iterdir()), [])

    def test_updated_skill_is_refreshed_without_fetch_or_build(self):
        self.with_skill()
        (self.checkout / "integrations/codex/pm-pet/SKILL.md").write_text("new source")
        result = self.installed("update")
        self.assertEqual((self.skill / "SKILL.md").read_text(), "new source")
        self.assertIn("did not fetch source, rebuild, or restart", result.stdout)
        self.assertFalse((self.checkout / "build").exists())

    def test_modified_owned_file_blocks_update_and_uninstall_before_any_mutation(self):
        self.with_skill()
        self.command.write_text(self.command.read_text() + "# user modification\n")
        source = self.skill / "SKILL.md"
        before = source.read_text()
        self.cli("update", success=False)
        self.cli("uninstall", success=False)
        self.assertEqual(source.read_text(), before)
        self.assertTrue(self.setup.manifest_path(self.prefix).exists())

    def test_unknown_skill_content_blocks_uninstall(self):
        self.with_skill()
        extra = self.skill / "my-notes.md"
        extra.write_text("keep")
        self.installed("uninstall", success=False)
        self.assertEqual(extra.read_text(), "keep")
        self.assertTrue(self.command.exists())

    def test_update_repairs_missing_owned_file(self):
        self.with_skill()
        (self.skill / "SKILL.md").unlink()
        self.installed("update")
        self.assertTrue((self.skill / "SKILL.md").is_file())

    def test_uninstall_retains_source_runtime_and_unrelated_prefix_files(self):
        self.with_skill()
        runtime = self.runtime()
        other = self.prefix / "bin/unrelated"
        other.write_text("keep")
        self.installed("uninstall")
        self.assertFalse(self.command.exists())
        self.assertFalse(self.skill.exists())
        self.assertFalse(self.setup.manifest_path(self.prefix).parent.exists())
        self.assertTrue((runtime / "state.json").exists())
        self.assertTrue((self.checkout / "scripts/setup.py").exists())
        self.assertEqual(other.read_text(), "keep")

    def test_explicit_purge_removes_only_verified_stopped_default_runtime(self):
        self.cli("install")
        runtime = self.runtime()
        other = self.checkout / ".pm-pet/other"
        other.write_text("keep")
        self.installed("uninstall", "--purge-runtime")
        self.assertFalse(runtime.exists())
        self.assertEqual(other.read_text(), "keep")

    def test_purge_refuses_unknown_runtime_without_removing_install(self):
        self.cli("install")
        runtime = self.runtime()
        (runtime / "state.json").write_text('{}')
        self.installed("uninstall", "--purge-runtime", success=False)
        self.assertTrue(self.command.exists())
        self.assertTrue(runtime.exists())

    def test_purge_refuses_active_heartbeat(self):
        self.cli("install")
        runtime = self.runtime()
        (runtime / "heartbeat.json").write_text('{}')
        self.installed("uninstall", "--purge-runtime", success=False)
        self.assertTrue(self.command.exists())

    def test_purge_refuses_symlink_inside_runtime(self):
        self.cli("install")
        runtime = self.runtime()
        target = self.base / "personal.txt"
        target.write_text("keep")
        (runtime / "linked").symlink_to(target)
        self.installed("uninstall", "--purge-runtime", success=False)
        self.assertEqual(target.read_text(), "keep")
        self.assertTrue(self.command.exists())

    def test_purge_refuses_held_daemon_lock_even_with_stale_heartbeat(self):
        import fcntl
        self.cli("install")
        runtime = self.runtime()
        with (runtime / "daemon.lock").open("w") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.installed("uninstall", "--purge-runtime", success=False)
        self.assertTrue(runtime.exists())

    def test_purge_refuses_held_native_lock_even_without_bridge(self):
        import fcntl
        self.cli("install")
        runtime = self.runtime()
        with (runtime / "native.lock").open("w") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.installed("uninstall", "--purge-runtime", success=False)
        self.assertTrue(runtime.exists())
        self.assertTrue(self.command.exists())

    def test_python_wrapper_keeps_stable_symlink_path(self):
        stable = self.base / "stable-python"
        stable.symlink_to(sys.executable)
        with patch.object(self.setup.sys, "executable", str(stable)), contextlib.redirect_stdout(io.StringIO()):
            self.setup.install(self.prefix)
        self.assertIn(str(stable), self.command.read_text())

    def test_failed_update_restores_files_and_manifest(self):
        self.with_skill()
        owned = [self.command, self.setup.manifest_path(self.prefix)] + [self.skill / name for name in self.setup.SKILL_FILES]
        old = {path: path.read_bytes() for path in owned}
        (self.checkout / "integrations/codex/pm-pet/SKILL.md").write_text("updated source")
        actual_write = self.setup.write_atomic
        for fail_at in (2, 3, len(self.setup.SKILL_FILES) + 2):
            counter = [0]
            def injected(path, data, mode=0o644):
                counter[0] += 1
                if counter[0] == fail_at:
                    raise OSError("synthetic replacement failure")
                return actual_write(path, data, mode)
            with self.subTest(fail_at=fail_at), patch.object(self.setup, "write_atomic", side_effect=injected):
                with self.assertRaises(OSError):
                    self.setup.update(self.prefix)
            self.assertEqual({path: path.read_bytes() for path in owned}, old)
            self.setup.verify_owned(self.prefix, self.setup.read_manifest(self.prefix))
        self.installed("update")

    def test_skill_destination_cannot_overlap_metadata(self):
        self.cli("install", "--with-skill", "--skill-dir", str(self.setup.manifest_path(self.prefix).parent / "skill"), success=False)
        self.assertFalse(self.command.exists())

    def test_interrupt_after_replacement_rolls_back_current_file_too(self):
        self.with_skill()
        old = (self.skill / "SKILL.md").read_bytes()
        (self.checkout / "integrations/codex/pm-pet/SKILL.md").write_text("updated source")
        actual_write = self.setup.write_atomic
        interrupted = [False]
        def interrupt_after_replace(path, data, mode=0o644):
            actual_write(path, data, mode)
            if path == self.skill / "SKILL.md" and not interrupted[0]:
                interrupted[0] = True
                raise KeyboardInterrupt()
        with patch.object(self.setup, "write_atomic", side_effect=interrupt_after_replace):
            with self.assertRaises(KeyboardInterrupt):
                self.setup.update(self.prefix)
        self.assertEqual((self.skill / "SKILL.md").read_bytes(), old)
        self.setup.verify_owned(self.prefix, self.setup.read_manifest(self.prefix))

    def test_checkout_mismatch_cannot_adopt_or_uninstall_installation(self):
        self.cli("install")
        manifest_path = self.setup.manifest_path(self.prefix)
        manifest = json.loads(manifest_path.read_text())
        manifest["checkout"] = "/different/checkout"
        manifest_path.write_text(json.dumps(manifest))
        self.cli("update", success=False)
        self.cli("uninstall", success=False)
        self.assertTrue(self.command.exists())

    def test_failed_fresh_install_rolls_back_only_owned_created_bytes(self):
        def fail_manifest(path, *args, **kwargs):
            raise OSError("synthetic disk failure")
        with patch.object(self.setup, "write_atomic", side_effect=fail_manifest):
            with self.assertRaises(OSError):
                self.setup.install(self.prefix, True, self.skill)
        self.assertFalse(self.command.exists())
        self.assertFalse(self.skill.exists())
        self.assertFalse(self.setup.manifest_path(self.prefix).parent.exists())


if __name__ == "__main__":
    unittest.main()
