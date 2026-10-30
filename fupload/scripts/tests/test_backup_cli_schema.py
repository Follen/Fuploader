from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fupload_cli.cli import build_parser, main
from fupload_cli.errors import ValidationError
from fupload_cli.schema import get_schema


class BackupCliSchemaTests(unittest.TestCase):
    def _generation(self, directory, platform):
        game = Path(directory) / "game"
        (game / "Interface" / "AddOns" / "Chosen").mkdir(parents=True, exist_ok=True)
        (game / "Interface" / "AddOns" / "Chosen" / "main.lua").write_text("selected")
        role = game / "WTF" / "Account" / "Account" / "Realm" / "Role"
        role.mkdir(parents=True, exist_ok=True)
        (role / "config-cache.wtf").write_text("selected")
        common = {"output_dir": str(Path(directory) / ("backup-" + platform))}
        if platform == "modus":
            return {**common, "game_root": str(game), "backup_name": "fixture", "server_type": 0,
                    "addon_names": ["Chosen"], "roles": [{"account": "Account", "server": "Realm", "role": "Role"}]}
        if platform == "blackbox":
            return {**common, "game_dir": str(game), "strappid": "wowretail", "unknown_addons": ["Chosen"],
                    "materials": [], "fonts": [], "wtf_accounts": [{"name": "Account", "characters": [{"realm": "Realm", "player": "Role"}]}]}
        return {**common, "game_dir": str(game), "game_version_id" if platform == "newbee" else "game_type": 1,
                "unknown_plugins" if platform == "newbee" else "addon_names": ["Chosen"],
                "wtf_accounts": [{"account": "Account", "include_common": False, "roles": [{"server": "Realm", "name": "Role"}]}]}

    def test_four_platforms_expose_complete_backup_command_tree(self):
        parser = build_parser()
        for platform in ("newbee", "dd", "modus", "blackbox"):
            for action in ("generate", "upload", "create", "rename", "delete"):
                args = parser.parse_args([platform, "backup", action, "--input", "plan.json", "--dry-run"])
                self.assertEqual((args.platform, args.resource, args.action, args.handler), (platform, "backup", action, "write"))
                self.assertTrue(args.dry_run)
            self.assertEqual(parser.parse_args([platform, "backup", "list"]).resource, "backup")
        self.assertEqual(parser.parse_args(["newbee", "backup", "get", "--id", "7"]).id, 7)
        self.assertEqual(parser.parse_args(["dd", "backup", "get", "--sn", "opaque"]).sn, "opaque")
        self.assertEqual(parser.parse_args(["modus", "backup", "get", "--backup-id", "7", "--build", "0"]).server_type, 0)
        self.assertEqual(parser.parse_args(["blackbox", "backup", "get", "--backup-id", "opaque"]).backup_id, "opaque")

    def test_preview_filters_keep_platform_time_and_id_types(self):
        parser = build_parser()
        selected = parser.parse_args(["modus", "backup", "delete-preview", "--backup-ids", "7", "8", "--build", "0"])
        self.assertEqual(selected.backup_ids, [7, 8])
        for platform in ("newbee", "dd", "modus"):
            args = parser.parse_args([platform, "backup", "delete-preview", "--name-contains", "test", "--created-before", "2026-10-30T00:00:00Z"])
            self.assertEqual(args.created_before, "2026-10-30T00:00:00Z")
        args = parser.parse_args(["blackbox", "backup", "delete-preview", "--name-equals", "test", "--created-before", "123"])
        self.assertEqual(args.created_before, 123)

    def test_local_generate_dry_run_has_no_provider_or_filesystem_write(self):
        with tempfile.TemporaryDirectory() as temporary:
            for platform in ("newbee", "dd", "modus", "blackbox"):
                with self.subTest(platform=platform):
                    doc = self._generation(temporary, platform)
                    schema = get_schema(platform, "backup", "generate")
                    doc["schema"] = schema.name
                    plan = Path(temporary) / (platform + ".json")
                    plan.write_text(json.dumps(doc), encoding="utf-8")
                    with mock.patch("fupload_cli.cli.NewBee") as newbee, mock.patch("fupload_cli.cli.DD") as dd, mock.patch("fupload_cli.cli.Blackbox") as blackbox, mock.patch("fupload_cli.cli._modus_provider") as modus, contextlib.redirect_stdout(io.StringIO()) as output:
                        code = main([platform, "backup", "generate", "--input", str(plan), "--dry-run"])
                    self.assertEqual(code, 0)
                    self.assertTrue(json.loads(output.getvalue())["data"]["schema_valid"])
                    self.assertFalse(Path(doc["output_dir"]).exists())
                    for provider in (newbee, dd, blackbox, modus):
                        provider.assert_not_called()

    def test_delete_schemas_reject_missing_confirmation_and_bypass_fields(self):
        for platform in ("newbee", "dd", "modus", "blackbox"):
            schema = get_schema(platform, "backup", "delete")
            backup_id = 7 if platform in ("newbee", "modus") else "opaque"
            valid = {"schema": schema.name, "backup_ids": [backup_id], "confirm_delete": True}
            self.assertEqual(schema.validate(valid), valid)
            for patch in ({"confirm_delete": False}, {"backup_ids": []}, {"backup_ids": [backup_id, backup_id]}, {"force": True}, {"allow_referenced": True}, {"name_contains": "all"}):
                with self.subTest(platform=platform, patch=patch), self.assertRaises(ValidationError):
                    schema.validate({**valid, **patch})
            with self.assertRaises(ValidationError):
                schema.validate({"schema": schema.name, "backup_ids": [backup_id]})
        schema = get_schema("modus", "backup", "delete")
        with self.assertRaises(ValidationError):
            schema.validate({"schema": schema.name, "backup_ids": [True], "confirm_delete": True})

    def test_generation_rejects_missing_sources_nested_unknowns_and_duplicate_roles(self):
        with tempfile.TemporaryDirectory() as temporary:
            for platform in ("newbee", "dd", "modus", "blackbox"):
                doc = self._generation(temporary, platform)
                schema = get_schema(platform, "backup", "generate")
                doc["schema"] = schema.name
                schema.validate(doc)
                field = "roles" if platform == "modus" else "wtf_accounts"
                invalid = json.loads(json.dumps(doc))
                invalid[field][0]["force"] = True
                with self.subTest(platform=platform), self.assertRaises(ValidationError):
                    schema.validate(invalid)
                names = "addon_names" if platform in ("modus", "dd") else "unknown_plugins" if platform == "newbee" else "unknown_addons"
                with self.assertRaises(ValidationError):
                    schema.validate({**doc, names: ["Missing"]})

    def test_upload_json_packages_are_not_mistaken_for_plugin_zips(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "backup.json"
            for platform, package_schema in (("newbee", "fupload.newbee.backup-bundle.v1"), ("dd", "fupload.dd.backup-bundle.v1"), ("blackbox", "fupload.blackbox.backup-package.v1"), ("modus", "config-backup.v2")):
                path.write_text(json.dumps({"schemaVersion" if platform == "modus" else "schema": package_schema}), encoding="utf-8")
                field = "manifest_file" if platform == "modus" else "file" if platform == "blackbox" else "bundle_file"
                schema = get_schema(platform, "backup", "upload")
                schema.validate({"schema": schema.name, field: str(path)})
                path.write_text("invalid", encoding="utf-8")
                with self.assertRaises(ValidationError):
                    schema.validate({"schema": schema.name, field: str(path)})

    def test_blackbox_configuration_preserves_sparse_html_and_rejects_unknown_wire_fields(self):
        parser = build_parser()
        self.assertEqual(parser.parse_args(["blackbox", "config", "list", "--strappid", "wowretail"]).strappid, "wowretail")
        html = '<p>原始正文<img src="https://example.invalid/pic.webp"></p>'
        schema = get_schema("blackbox", "config", "edit")
        doc = {"schema": schema.name, "share_id": "opaque", "configuration": {"Article": html}}
        self.assertEqual(schema.validate(doc)["configuration"], {"Article": html})
        for configuration in ({"ID": "forged"}, {"IsClassic": True}, {"Open": 1}, {"SubscribeLevel": True}, {"Materials": {"Files": [], "Url": "forged"}}):
            with self.assertRaises(ValidationError):
                schema.validate({**doc, "configuration": configuration})
        with self.assertRaises(ValidationError):
            schema.validate({**doc, "backup_id": "changed"})

    def test_legacy_backup_commands_remain_available(self):
        parser = build_parser()
        for platform in ("newbee", "dd", "modus"):
            self.assertEqual(parser.parse_args([platform, "config", "backups"]).action, "backups")
        self.assertEqual(parser.parse_args(["modus", "config", "backup-delete", "--input", "plan.json"]).action, "backup-delete")
        schema = get_schema("dd", "backup", "rename")
        with self.assertRaises(ValidationError):
            schema.validate({"schema": schema.name, "sn": "opaque", "name": "x" * 15})


if __name__ == "__main__":
    unittest.main()
