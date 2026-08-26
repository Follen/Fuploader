from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from fupload_cli.schema import get_schema
from run_modus_full_field_regression import (
    CliHarness,
    RegressionFailure,
    _summary,
    build_plan,
    main,
    mutable_fields,
    validate_fixture,
)


def _value(field: str):
    schema_resource = {"project": "project", "release": "plugin", "config": "config", "wa": "wa"}
    return field


def fixture_for(root: Path):
    images = {}
    for index, name in enumerate(("project_logo", "project_screenshot", "config", "wa"), start=1):
        path = root / (name + ".png")
        path.write_bytes(b"\x89PNG\r\n\x1a\n" + bytes([index]) * 32)
        images[name] = path.name
    resources = {}
    for resource in ("project", "release", "config", "wa"):
        fields = mutable_fields(resource)
        resources[resource] = {
            "create": {},
            "mutations": {field: _value(field) + "-mutated" for field in fields},
            "restores": {field: _value(field) + "-restored" for field in fields},
        }
    resources["project"]["project_state"] = {"step": "complete"}
    resources["wa"]["version"] = {"publish": {}, "delete": {}}
    negatives = [
        {"kind": kind, "resource": "config", "action": "update", "document": {}}
        for kind in ("enum", "empty_null", "dependency", "build")
    ]
    return {"images": images, "resources": resources, "negative_cases": negatives}


class FullFieldRegressionTests(unittest.TestCase):
    def test_mutable_matrix_is_derived_from_every_current_schema_field(self):
        controls = {
            "project": {"project_id", "project_state"},
            "release": {"project_id", "file_id", "file", "transaction_log"},
            "config": {"share_id", "server_type"},
            "wa": {"import_id", "server_type"},
        }
        targets = {
            "project": ("project", "edit"),
            "release": ("plugin", "edit"),
            "config": ("config", "update"),
            "wa": ("wa", "update"),
        }
        for resource, (schema_resource, action) in targets.items():
            self.assertEqual(
                mutable_fields(resource),
                set(get_schema("modus", schema_resource, action).fields) - controls[resource],
            )

    def test_fixture_requires_every_mutation_and_restoration_field(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = fixture_for(root)
            field = next(iter(mutable_fields("config")))
            fixture["resources"]["config"]["mutations"].pop(field)
            with self.assertRaisesRegex(RegressionFailure, "missing_mutations"):
                validate_fixture(fixture, root)

    def test_fixture_requires_distinct_project_config_and_wa_image_content(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = fixture_for(root)
            repeated = root / fixture["images"]["project_logo"]
            for name in fixture["images"]:
                (root / fixture["images"][name]).write_bytes(repeated.read_bytes())
            with self.assertRaisesRegex(RegressionFailure, "three distinct"):
                validate_fixture(fixture, root)

    def test_plan_covers_builds_negative_kinds_and_two_readbacks_per_field(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan = build_plan(fixture_for(root), root)
            expected = sum(len(mutable_fields(resource)) for resource in ("project", "release", "config", "wa"))
            self.assertEqual(plan["validation"]["builds"], [0, 1, 2, 3, 4])
            self.assertEqual(plan["planned_field_cycles"], expected)
            self.assertEqual(plan["planned_field_writes"], expected * 2)
            self.assertEqual(plan["planned_field_readbacks"], expected * 2)
            self.assertEqual(plan["cleanup_order"], ["wa", "config", "release", "project"])
            self.assertEqual(plan["remote_writes_performed"], 0)

    def test_evidence_summary_never_contains_raw_content_urls_or_signatures(self):
        raw = {
            "content": "private body text",
            "signedUrl": "https://example.invalid/upload?token=secret",
            "image_url": "https://example.invalid/private.webp",
            "title": "visible title",
        }
        summarized = _summary(raw)
        wire = json.dumps(summarized)
        self.assertNotIn("private body text", wire)
        self.assertNotIn("example.invalid", wire)
        self.assertNotIn("token=secret", wire)
        self.assertEqual(summarized["title"], "visible title")
        self.assertEqual(len(summarized["content"]["sha256"]), 64)

    def test_default_main_is_local_only_and_execute_requires_evidence_path(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture_path = root / "fixture.json"
            fixture_path.write_text(json.dumps(fixture_for(root)), encoding="utf-8")
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                code = main(["--fixture", str(fixture_path)])
            self.assertEqual(code, 0)
            self.assertEqual(json.loads(stdout.getvalue())["remote_writes_performed"], 0)
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                code = main(["--fixture", str(fixture_path), "--execute"])
            self.assertEqual(code, 2)
            self.assertIn("--evidence", json.loads(stdout.getvalue())["error"])

    def test_harness_records_literal_exit_status_and_redacted_response(self):
        with tempfile.TemporaryDirectory() as directory:
            evidence = {"steps": []}
            harness = CliHarness(evidence, Path(directory))
            completed = subprocess_result = mock.Mock(
                returncode=2,
                stdout=json.dumps({"success": False, "error": {"content": "raw", "signedUrl": "secret"}}),
                stderr="",
            )
            with mock.patch("run_modus_full_field_regression.subprocess.run", return_value=completed):
                result = harness.run(["modus", "config", "update"], expected_exit=2, input_summary={})
            self.assertEqual(result.exit_status, 2)
            record = evidence["steps"][0]
            self.assertEqual(record["exit_status"], 2)
            wire = json.dumps(record)
            self.assertNotIn('"raw"', wire)
            self.assertNotIn('"secret"', wire)


if __name__ == "__main__":
    unittest.main()
