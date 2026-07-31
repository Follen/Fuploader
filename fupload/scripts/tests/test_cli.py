from __future__ import annotations

import argparse
import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fupload_cli.cli import build_parser, main
from fupload_cli.io import write_error, write_output
from fupload_cli.schema import SCHEMAS


def parser_leaves(parser, prefix=()):
    subparsers = [
        action for action in parser._actions
        if isinstance(action, argparse._SubParsersAction)
    ]
    if not subparsers:
        return [(prefix, parser)]
    leaves = []
    for subparser in subparsers:
        for name, child in subparser.choices.items():
            leaves.extend(parser_leaves(child, prefix + (name,)))
    return leaves


class CLITests(unittest.TestCase):
    def test_root_help_lists_both_platforms(self) -> None:
        text = build_parser().format_help()
        self.assertIn("newbee", text)
        self.assertIn("dd", text)

    def test_dd_life_types_does_not_require_unused_game_type(self) -> None:
        args = build_parser().parse_args(["dd", "options", "life-types"])
        self.assertEqual(args.action, "life-types")

    def test_every_cli_leaf_has_complete_help_and_dispatch(self) -> None:
        leaves = parser_leaves(build_parser())
        self.assertEqual(len(leaves), 88)
        for path, parser in leaves:
            with self.subTest(path=" ".join(path)):
                handler = parser.get_default("handler")
                platform = parser.get_default("platform")
                resource = parser.get_default("resource")
                action = parser.get_default("action")
                self.assertIn(handler, ("read", "write"))
                self.assertIn(platform, ("newbee", "dd"))
                self.assertTrue(resource)
                self.assertTrue(action)
                help_text = parser.format_help()
                if handler == "write":
                    schema = SCHEMAS[(platform, resource, action)]
                    self.assertIn("--input", help_text)
                    self.assertIn("--dry-run", help_text)
                    self.assertIn(schema.name, help_text)
                    for field_name in schema.fields:
                        self.assertIn(field_name, help_text)
                else:
                    self.assertIn("stable JSON", " ".join(help_text.split()))

    def test_every_schema_field_is_in_platform_reference(self) -> None:
        root = Path(__file__).resolve().parents[2]
        references = {
            platform: (root / "references" / (platform + ".md")).read_text(encoding="utf-8")
            for platform in ("newbee", "dd")
        }
        for (platform, resource, action), schema in sorted(SCHEMAS.items()):
            with self.subTest(platform=platform, resource=resource, action=action):
                for field_name in schema.fields:
                    self.assertIn("`%s`" % field_name, references[platform])

    def test_skill_requires_explicit_invocation(self) -> None:
        root = Path(__file__).resolve().parents[2]
        skill = (root / "SKILL.md").read_text(encoding="utf-8")
        agent = (root / "agents" / "openai.yaml").read_text(encoding="utf-8")
        self.assertIn("Use only when the user explicitly invokes `$fupload`", skill)
        self.assertIn("Do not trigger from ordinary mentions", skill)
        self.assertIn("使用 $fupload", agent)

    def test_skill_keeps_versioned_inputs_in_project_publish_directory(self) -> None:
        root = Path(__file__).resolve().parents[2]
        skill = (root / "SKILL.md").read_text(encoding="utf-8")
        workflow = (root / "references" / "workflow.md").read_text(encoding="utf-8")
        for text in (skill, workflow):
            self.assertIn(
                "publish/<YYYYMMDD-HHmmss>-<platform>-<resource>-<action>/",
                text,
            )
            self.assertIn("01-<action>.json", text)
            self.assertIn("target project", text)
        self.assertIn("Keep the directory after execution", skill)

    def test_skill_requires_trusted_authentication_sources(self) -> None:
        root = Path(__file__).resolve().parents[2]
        skill = (root / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("fixed official HTTPS origins", skill)
        self.assertIn("Authenticode-valid executable", skill)
        self.assertIn("Do not set endpoint, credential-directory", skill)

    def test_skill_owns_one_confirmed_dd_task_session(self) -> None:
        root = Path(__file__).resolve().parents[2]
        skill = (root / "SKILL.md").read_text(encoding="utf-8")
        workflow = (root / "references" / "workflow.md").read_text(encoding="utf-8")
        dd_reference = (root / "references" / "dd.md").read_text(encoding="utf-8")
        for text in (skill, workflow, dd_reference):
            self.assertIn("dd session doctor", text)
            self.assertIn("dd session start --confirm-close-gui", text)
            self.assertIn("dd session stop --session <id>", text)
            self.assertIn("finally", text)
        self.assertIn("never start one session per item", skill)
        self.assertIn("one final JSON", skill)
        self.assertIn("backup_sn -> backup detail -> WTF account/server/role", workflow)

    def test_skill_prefers_official_newbee_cli_without_silent_fallback(self) -> None:
        root = Path(__file__).resolve().parents[2]
        skill = (root / "SKILL.md").read_text(encoding="utf-8")
        official = (root / "references" / "newbee-official-cli.md").read_text(encoding="utf-8")
        self.assertIn("Get-Command ncc -ErrorAction SilentlyContinue", skill)
        self.assertIn("If installed, select official `ncc` by default", skill)
        self.assertIn("explicitly requests the third-party Python management tool", skill)
        self.assertIn("Never switch channels silently", skill)
        self.assertIn("npm i -g @newbeebox/newbeebox-creator-center-cli@latest", skill)
        self.assertIn("ncc whoami -o json", skill)
        self.assertIn("https://creator.newbeebox.com/md/cli-docs", official)
        self.assertIn("## 命令参考", official)
        self.assertIn("ncc wow addons push", official)
        self.assertIn("ncc wow wa push", official)
        self.assertIn("ncc wow uipack push", official)
        self.assertIn("ncc community post", official)
        self.assertIn("## ncc.json 配置说明", official)
        self.assertIn("NCC_TOKEN", official)
        self.assertIn("## 错误码参考", official)

    def test_skill_keeps_newbee_token_out_of_agent_commands(self) -> None:
        root = Path(__file__).resolve().parents[2]
        skill = (root / "SKILL.md").read_text(encoding="utf-8")
        workflow = (root / "references" / "workflow.md").read_text(encoding="utf-8")
        for text in (skill, workflow):
            self.assertIn("NCC_TOKEN", text)
            self.assertIn("Never", text)
        self.assertIn("Never place a real token in `--token`", skill)
        self.assertIn("do not repeat or use it", skill)

    def test_dry_run_emits_stable_json(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "input.json"
            path.write_text(json.dumps({
                "schema": "fupload.v1.newbee.plugin.edit", "id": 1, "intro": "updated"
            }), encoding="utf-8")
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                code = main(["newbee", "plugin", "edit", "--input", str(path), "--dry-run"])
            payload = json.loads(output.getvalue())
            self.assertEqual(code, 0)
            self.assertEqual(payload["schema"], "fupload.output.v1")
            self.assertTrue(payload["success"])
            self.assertTrue(payload["dry_run"])

    def test_final_json_output_is_ascii_and_round_trips_chinese(self) -> None:
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            write_output("dd", "plugin.get", {"name": "中文公告"})
        wire = output.getvalue()
        self.assertTrue(wire.isascii())
        self.assertNotIn("中文公告", wire)
        self.assertEqual(json.loads(wire)["data"]["name"], "中文公告")

    def test_error_json_output_is_ascii_and_round_trips_chinese(self) -> None:
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            write_error("dd", "plugin.get", ValueError("中文错误"))
        wire = output.getvalue()
        self.assertTrue(wire.isascii())
        self.assertEqual(json.loads(wire)["error"]["message"], "中文错误")

    def test_wrong_stage_field_is_rejected_before_network(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "input.json"
            path.write_text(json.dumps({
                "schema": "fupload.v1.newbee.plugin.edit", "id": 1, "version": "2.0"
            }), encoding="utf-8")
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                code = main(["newbee", "plugin", "edit", "--input", str(path), "--dry-run"])
            payload = json.loads(output.getvalue())
            self.assertEqual(code, 2)
            self.assertEqual(payload["error"]["kind"], "validation_error")

    def test_duplicate_json_key_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "input.json"
            path.write_text(
                '{"schema":"fupload.v1.newbee.plugin.edit","id":1,"id":2}',
                encoding="utf-8",
            )
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                code = main(["newbee", "plugin", "edit", "--input", str(path), "--dry-run"])
            payload = json.loads(output.getvalue())
            self.assertEqual(code, 2)
            self.assertIn("duplicate key", payload["error"]["message"])

    def test_nonstandard_json_number_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "input.json"
            path.write_text(
                '{"schema":"fupload.v1.newbee.plugin.edit","id":1,"subscribe_plan_level":NaN}',
                encoding="utf-8",
            )
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                code = main(["newbee", "plugin", "edit", "--input", str(path), "--dry-run"])
            payload = json.loads(output.getvalue())
            self.assertEqual(code, 2)
            self.assertIn("non-standard numeric", payload["error"]["message"])

    def test_all_bundled_examples_pass_dry_run(self) -> None:
        root = Path(__file__).resolve().parents[2]
        examples = {
            "newbee-plugin-create.json": ("newbee", "plugin", "create"),
            "newbee-config-update.json": ("newbee", "config", "update"),
            "newbee-wa-update.json": ("newbee", "wa", "update"),
            "dd-plugin-update.json": ("dd", "plugin", "update"),
            "dd-config-update.json": ("dd", "config", "update"),
            "dd-wa-edit.json": ("dd", "wa", "edit"),
            "newbee-plugin-delete.json": ("newbee", "plugin", "delete"),
            "newbee-config-delete.json": ("newbee", "config", "delete"),
            "newbee-wa-delete.json": ("newbee", "wa", "delete"),
            "dd-plugin-delete.json": ("dd", "plugin", "delete"),
            "dd-config-delete.json": ("dd", "config", "delete"),
            "dd-wa-delete.json": ("dd", "wa", "delete"),
        }
        with tempfile.TemporaryDirectory() as directory:
            local_file = Path(directory) / "local.zip"
            local_file.write_bytes(b"example")
            for name, command in examples.items():
                with self.subTest(example=name):
                    document = json.loads((root / "examples" / name).read_text(encoding="utf-8"))
                    for field_name, value in list(document.items()):
                        if field_name == "file" or field_name.endswith("_file"):
                            document[field_name] = str(local_file)
                        elif field_name.endswith("_files") and isinstance(value, list):
                            document[field_name] = [str(local_file) for _ in value]
                    input_path = Path(directory) / ("input-" + name)
                    input_path.write_text(json.dumps(document), encoding="utf-8")
                    output = io.StringIO()
                    with contextlib.redirect_stdout(output):
                        code = main([*command, "--input", str(input_path), "--dry-run"])
                    payload = json.loads(output.getvalue())
                    self.assertEqual(code, 0, payload)
                    self.assertTrue(payload["success"])


if __name__ == "__main__":
    unittest.main()
