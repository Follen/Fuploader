from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


MODULE_PATH = Path(__file__).with_name("run_dd_full_live_regression.py")
SPEC = importlib.util.spec_from_file_location("run_dd_full_live_regression", MODULE_PATH)
assert SPEC and SPEC.loader
runner = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = runner
SPEC.loader.exec_module(runner)


class DDLiveRegressionTests(unittest.TestCase):
    def fixture_tree(self, root: Path) -> tuple[Path, Path]:
        fixture = root / "fixtures"; fixture.mkdir()
        documents = {
            "01-plugin-create.json": {"schema": "fupload.v1.dd.plugin.create"},
            "04-config-create.json": {"schema": "fupload.v1.dd.config.create"},
            "05-config-update.json": {"schema": "fupload.v1.dd.config.update"},
            "07-wa-create.json": {"schema": "fupload.v1.dd.wa.create"},
        }
        for name, value in documents.items():
            (fixture / name).write_text(json.dumps(value), encoding="utf-8")
        package = root / "plugin.zip"; package.write_bytes(b"PK\x03\x04fixture")
        return fixture, package

    def test_default_mode_only_emits_plan(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture, package = self.fixture_tree(Path(directory))
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                code = runner.main(["--fixture-dir", str(fixture), "--package", str(package)])
            plan = json.loads(stdout.getvalue())
        self.assertEqual(code, 0)
        self.assertEqual(plan["remote_writes_performed"], 0)
        self.assertEqual(plan["cleanup_order"], ["wa", "config", "plugin"])
        self.assertEqual(plan["per_build_mutations"]["plugin"], ["create", "update", "edit", "delete"])
        self.assertEqual(plan["per_build_mutations"]["config"], ["create", "update", "edit", "delete"])
        self.assertEqual(plan["per_build_mutations"]["wa"], ["create", "update", "edit", "delete"])
        self.assertTrue(plan["six_plugin_batch"])
        self.assertEqual(len(plan["binary_uploads"]), 6)

    def test_execute_requires_evidence_and_credential_expectation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture, package = self.fixture_tree(Path(directory))
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                code = runner.main(["--execute", "--fixture-dir", str(fixture), "--package", str(package)])
        self.assertEqual(code, 2)
        self.assertIn("--evidence", json.loads(stdout.getvalue())["error"])

    def test_summary_redacts_credentials_and_sensitive_bodies(self) -> None:
        value = runner._summary({
            "credential_kind": "email",
            "credential": "raw-secret",
            "access_token": "token-secret",
            "content": "private WA body",
            "message": "Bearer abcdef",
        })
        wire = json.dumps(value)
        self.assertEqual(value["credential_kind"], "email")
        self.assertEqual(value["credential"], "[REDACTED]")
        self.assertNotIn("raw-secret", wire)
        self.assertNotIn("token-secret", wire)
        self.assertNotIn("private WA body", wire)
        self.assertNotIn("abcdef", wire)
        self.assertEqual(len(value["content"]["sha256"]), 64)

    def test_harness_stops_on_first_required_failure(self) -> None:
        evidence = {"steps": []}
        completed = subprocess.CompletedProcess([], 7, stdout=json.dumps({"success": False}), stderr="failed")
        harness = runner.CliHarness(evidence, mock.Mock(return_value=completed))
        with self.assertRaises(runner.RegressionFailure):
            harness.invoke("broken", ["dd", "plugin", "list"])
        self.assertEqual(len(evidence["steps"]), 1)
        self.assertEqual(evidence["steps"][0]["exit_status"], 7)

    def test_execute_failure_still_cleans_up_and_stops_session(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture, package = self.fixture_tree(root)
            evidence_path = root / "evidence.json"
            calls: list[list[str]] = []

            def fake_run(command, **_kwargs):
                args = command[2:]
                calls.append(args)
                if args[:3] == ["dd", "session", "doctor"]:
                    return subprocess.CompletedProcess(command, 0, json.dumps({"success": True, "data": {"broker_running": False, "gui_running": False, "gui_processes": []}}), "")
                if args[:3] == ["dd", "session", "start"]:
                    return subprocess.CompletedProcess(command, 0, json.dumps({"success": True, "data": {"session_id": "opaque"}}), "")
                if args[:3] == ["dd", "session", "status"]:
                    return subprocess.CompletedProcess(command, 0, json.dumps({"success": True, "data": {"running": True, "credential_kind": "email"}}), "")
                if args[:3] == ["dd", "options", "game-types"]:
                    return subprocess.CompletedProcess(command, 3, json.dumps({"success": False, "error": "boom"}), "")
                if args[:3] == ["dd", "session", "stop"]:
                    return subprocess.CompletedProcess(command, 0, json.dumps({"success": True, "data": {"cleanup_complete": True}}), "")
                raise AssertionError(args)

            with mock.patch.object(runner, "_git_commit", return_value="deadbeef"), self.assertRaises(runner.RegressionFailure):
                runner.execute(fixture, package, "email", evidence_path, run=fake_run)
            evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
        self.assertTrue(any(args[:3] == ["dd", "session", "stop"] for args in calls))
        self.assertEqual(evidence["credential_kind"], "email")
        self.assertFalse(evidence["completed"])
        self.assertEqual(evidence["residual_process_check"]["broker_running"], False)

    def test_dynamic_config_uses_current_safe_backup_selectors(self) -> None:
        detail = {
            "reference": "backup-current",
            "game_type": 10001,
            "known_addon": [{"reference": 77}],
            "unknown_addon": [],
            "material": [{"reference": "Icons"}],
            "font": [],
            "wtf_roles": [{"selector": "wtf-current", "account": "safe-account"}],
        }
        documents = runner._config_documents(detail, "Current backup", Path("image.png"))
        self.assertIsNotNone(documents)
        create, update = documents
        self.assertEqual(create["backup_sn"], "backup-current")
        self.assertEqual(create["known_addon_ids"], [77])
        self.assertEqual(create["wtf_role_ids"], ["wtf-current"])
        self.assertEqual(create["material_names"], ["Icons"])
        self.assertIsNone(create["retail_ui_config"])
        self.assertEqual(update["known_addon_update_ids"], [77])
        self.assertEqual(update["material_update_names"], ["Icons"])

    def test_dynamic_config_rejects_backup_without_usable_content(self) -> None:
        detail = {
            "reference": "backup-current", "game_type": 2,
            "known_addon": [{"reference": 77}], "unknown_addon": [],
            "material": [], "font": [], "wtf_roles": [],
        }
        self.assertIsNone(runner._config_documents(detail, "No content", Path("image.png")))

    def test_special_assets_keep_bytes_and_exercise_special_names(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            package = root / "source.zip"
            package.write_bytes(b"PK\x03\x04fixture")
            plugin, image, material = runner._special_assets(root, package)
            self.assertEqual(plugin.read_bytes(), package.read_bytes())
            self.assertEqual(len(runner._sha256(plugin.read_bytes())), 64)
            self.assertEqual(image.read_bytes(), runner.PNG_BYTES)
            self.assertTrue(material.is_file())
            for value in (plugin.name, image.name, material.name):
                self.assertIn(" ", value)
                self.assertIn("+", value)
                self.assertIn("#", value)
                self.assertIn("%", value)

    def test_safe_command_redacts_session_and_hashes_input(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "private.json"
            path.write_text(json.dumps({"schema": "fupload.v1.dd.plugin.create", "content": "secret"}), encoding="utf-8")
            command = runner._safe_command([
                "dd", "plugin", "create", "--session", "opaque-secret", "--input", str(path),
            ])
        wire = json.dumps(command)
        self.assertNotIn("opaque-secret", wire)
        self.assertNotIn(str(path), wire)
        self.assertIn("fupload.v1.dd.plugin.create", wire)
        self.assertIn("sha256=", wire)


if __name__ == "__main__":
    unittest.main()
