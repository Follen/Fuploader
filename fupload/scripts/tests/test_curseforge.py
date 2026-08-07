from __future__ import annotations

import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fupload_cli.cli import build_parser, main
from fupload_cli.curseforge import CurseForge, load_config
from fupload_cli.errors import FuploadError, ValidationError
from fupload_cli.schema import get_schema


def write_zip(path: Path) -> None:
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("Addon/Addon.toc", "## Interface: 110000\n")


class CurseForgeTests(unittest.TestCase):
    def test_parser_exposes_all_commands(self) -> None:
        parser = build_parser()
        self.assertEqual(parser.parse_args(["curseforge", "session", "doctor"]).action, "doctor")
        self.assertEqual(parser.parse_args(["curseforge", "project", "list"]).action, "list")
        self.assertEqual(parser.parse_args(["curseforge", "plugin", "game-versions"]).action, "game-versions")
        args = parser.parse_args(["curseforge", "plugin", "upload", "--input", "x.json", "--dry-run"])
        self.assertEqual(args.action, "upload")
        self.assertTrue(args.dry_run)

    def test_config_loader_accepts_fixed_fields_and_env_overrides(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "curseforge.env"
            path.write_text(
                "CURSEFORGE_AUTHOR_ID=12\nCURSEFORGE_API_KEY=file-key\nCURSEFORGE_UPLOAD_TOKEN=file-token\n",
                encoding="utf-8",
            )
            with mock.patch.dict(os.environ, {"CURSEFORGE_API_KEY": "env-key"}, clear=True):
                config = load_config(path)
        self.assertEqual(config["CURSEFORGE_AUTHOR_ID"], "12")
        self.assertEqual(config["CURSEFORGE_API_KEY"], "env-key")
        self.assertEqual(config["CURSEFORGE_UPLOAD_TOKEN"], "file-token")

    def test_blank_environment_value_does_not_override_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "curseforge.env"
            path.write_text("CURSEFORGE_API_KEY=file-key\n", encoding="utf-8")
            with mock.patch.dict(os.environ, {"CURSEFORGE_API_KEY": "   "}, clear=True):
                config = load_config(path)
        self.assertEqual(config["CURSEFORGE_API_KEY"], "file-key")

    def test_config_loader_rejects_unknown_and_duplicate_fields(self) -> None:
        for text in ("OTHER=value\n", "CURSEFORGE_API_KEY=a\nCURSEFORGE_API_KEY=b\n"):
            with self.subTest(text=text), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "curseforge.env"
                path.write_text(text, encoding="utf-8")
                with self.assertRaises(ValidationError), mock.patch.dict(os.environ, {}, clear=True):
                    load_config(path)

    def test_doctor_reports_presence_without_values(self) -> None:
        secret = "secret-token-value"
        provider = CurseForge({
            "CURSEFORGE_AUTHOR_ID": "138844367",
            "CURSEFORGE_API_KEY": secret,
            "CURSEFORGE_UPLOAD_TOKEN": secret,
        })
        result = provider.doctor()
        self.assertTrue(result["ready"])
        self.assertNotIn(secret, json.dumps(result))
        presence = {field["name"]: field["present"] for field in result["fields"]}
        self.assertEqual(presence["CURSEFORGE_API_KEY"], True)
        self.assertEqual(presence["CURSEFORGE_UPLOAD_TOKEN"], True)

    def test_doctor_cli_emits_stable_json_without_secret_values(self) -> None:
        secret = "never-print-this-value"
        output = io.StringIO()
        with mock.patch("fupload_cli.cli.CurseForge", return_value=CurseForge({
            "CURSEFORGE_AUTHOR_ID": "1",
            "CURSEFORGE_API_KEY": secret,
            "CURSEFORGE_UPLOAD_TOKEN": secret,
        })), contextlib.redirect_stdout(output):
            code = main(["curseforge", "session", "doctor"])
        wire = output.getvalue()
        self.assertEqual(code, 0)
        self.assertNotIn(secret, wire)
        payload = json.loads(wire)
        self.assertEqual(payload["platform"], "curseforge")
        self.assertTrue(payload["data"]["ready"])
        presence = {field["name"]: field["present"] for field in payload["data"]["fields"]}
        self.assertEqual(presence["CURSEFORGE_UPLOAD_TOKEN"], True)

    def test_project_list_uses_default_author_and_core_key(self) -> None:
        provider = CurseForge({"CURSEFORGE_AUTHOR_ID": "138844367", "CURSEFORGE_API_KEY": "core-secret"})
        response = {"data": [{
            "id": 1487219, "name": "TAP", "slug": "tap", "status": 4,
            "dateCreated": "2026-01-01", "dateModified": "2026-01-02",
            "downloadCount": 99, "sensitiveRemoteField": "omit-me",
        }], "pagination": {"totalCount": 1}}
        with mock.patch("fupload_cli.curseforge.json_request", return_value=response) as request:
            result = provider.project_list(None)
        url = request.call_args.args[0]
        self.assertIn("gameId=1", url)
        self.assertIn("authorId=138844367", url)
        self.assertEqual(request.call_args.kwargs["headers"], {"x-api-key": "core-secret"})
        self.assertEqual(result["total_count"], 1)
        self.assertEqual(result["pagination"]["totalCount"], 1)
        self.assertEqual(set(result["projects"][0]), {"id", "name", "slug", "status", "dateCreated", "dateModified"})
        self.assertNotIn("omit-me", json.dumps(result))

    def test_project_list_override_does_not_require_configured_author(self) -> None:
        provider = CurseForge({"CURSEFORGE_API_KEY": "core-secret"})
        with mock.patch("fupload_cli.curseforge.json_request", return_value={"data": [], "pagination": {}}) as request:
            provider.project_list(42)
        self.assertIn("authorId=42", request.call_args.args[0])

    def test_game_versions_uses_upload_token(self) -> None:
        provider = CurseForge({"CURSEFORGE_UPLOAD_TOKEN": "upload-secret"})
        with mock.patch("fupload_cli.curseforge.json_request", return_value=[{"id": 1}]) as request:
            self.assertEqual(provider.game_versions(), [{"id": 1}])
        self.assertEqual(request.call_args.args[0], "https://wow.curseforge.com/api/game/versions")
        self.assertEqual(request.call_args.kwargs["headers"], {"X-Api-Token": "upload-secret"})

    def test_upload_builds_documented_multipart_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / "addon.zip"
            write_zip(archive)
            doc = get_schema("curseforge", "plugin", "upload").validate({
                "schema": "fupload.v1.curseforge.plugin.upload",
                "project_id": 1487219,
                "file": str(archive),
                "changelog": "release notes",
                "changelog_type": "markdown",
                "display_name": "TAP 1.0.0",
                "game_versions": [12345],
                "game_version_names": ["Retail"],
                "release_type": "release",
                "relations": {"projects": [{"slug": "dependency", "type": "requiredDependency", "project_id": 77}]},
                "is_marked_for_manual_release": False,
            })
            provider = CurseForge({"CURSEFORGE_UPLOAD_TOKEN": "upload-secret"})
            with mock.patch("fupload_cli.curseforge.multipart_request", return_value={"id": 99, "token": "remote-secret"}) as request:
                result = provider.upload(doc)
        self.assertEqual(result, {"file_id": 99, "project_id": 1487219, "archive": "addon.zip", "status": "uploaded"})
        self.assertEqual(request.call_args.args[:2], (
            "https://wow.curseforge.com/api/projects/1487219/upload-file", str(archive)
        ))
        metadata = json.loads(request.call_args.kwargs["fields"]["metadata"])
        self.assertEqual(metadata["gameVersions"], [12345])
        self.assertEqual(metadata["changelogType"], "markdown")
        self.assertEqual(metadata["gameVersionNames"], ["Retail"])
        self.assertEqual(metadata["relations"], {"projects": [{"slug": "dependency", "type": "requiredDependency", "projectID": 77}]})
        self.assertNotIn("project_id", metadata)
        self.assertEqual(request.call_args.kwargs["headers"], {"X-Api-Token": "upload-secret"})

    def test_upload_schema_rejects_unknown_relation_and_bad_version(self) -> None:
        schema = get_schema("curseforge", "plugin", "upload")
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / "addon.zip"
            write_zip(archive)
            base = {
                "schema": schema.name, "project_id": 1, "file": str(archive),
                "changelog": "notes", "game_versions": [1], "release_type": "release",
            }
            with self.assertRaises(ValidationError):
                schema.validate({**base, "relations": {"projects": [{"slug": "x", "type": "requiredDependency", "extra": 1}]}})
            with self.assertRaises(ValidationError):
                schema.validate({**base, "game_versions": [True]})

    def test_upload_schema_requires_changelog_but_allows_no_game_versions(self) -> None:
        schema = get_schema("curseforge", "plugin", "upload")
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / "addon.zip"
            write_zip(archive)
            base = {"schema": schema.name, "project_id": 1, "file": str(archive), "release_type": "release"}
            with self.assertRaises(ValidationError):
                schema.validate(base)
            result = schema.validate({**base, "changelog": "notes"})
        self.assertNotIn("game_versions", result)

    def test_parent_file_id_rejects_both_game_version_fields(self) -> None:
        schema = get_schema("curseforge", "plugin", "upload")
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / "addon.zip"
            write_zip(archive)
            base = {
                "schema": schema.name, "project_id": 1, "file": str(archive),
                "changelog": "notes", "release_type": "release", "parent_file_id": 9,
            }
            validated = schema.validate(base)
            provider = CurseForge({"CURSEFORGE_UPLOAD_TOKEN": "upload-secret"})
            with mock.patch("fupload_cli.curseforge.multipart_request", return_value={"id": 10}) as request:
                provider.upload(validated)
            metadata = json.loads(request.call_args.kwargs["fields"]["metadata"])
            self.assertEqual(metadata["parentFileID"], 9)
            self.assertNotIn("gameVersions", metadata)
            self.assertNotIn("gameVersionNames", metadata)
            for field, value in (("game_versions", [1]), ("game_version_names", ["Retail"])):
                with self.subTest(field=field), self.assertRaises(ValidationError) as raised:
                    schema.validate({**base, field: value})
                self.assertEqual(raised.exception.details["path"], "$.%s" % field)

    def test_dry_run_rejects_non_zip_file(self) -> None:
        schema = get_schema("curseforge", "plugin", "upload")
        with tempfile.TemporaryDirectory() as directory:
            fake = Path(directory) / "fake.zip"
            fake.write_bytes(b"not a zip")
            with self.assertRaises(ValidationError) as raised:
                schema.validate({
                    "schema": schema.name, "project_id": 1, "file": str(fake),
                    "changelog": "notes", "release_type": "release",
                })
        self.assertEqual(raised.exception.details["path"], "$.file")

    def test_upload_dry_run_never_loads_config_or_calls_network(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / "addon.zip"
            write_zip(archive)
            input_path = Path(directory) / "upload.json"
            input_path.write_text(json.dumps({
                "schema": "fupload.v1.curseforge.plugin.upload",
                "project_id": 1, "file": str(archive),
                "changelog": "notes", "game_versions": [2], "release_type": "beta",
            }), encoding="utf-8")
            output = io.StringIO()
            with mock.patch("fupload_cli.cli.CurseForge") as provider, contextlib.redirect_stdout(output):
                code = main(["curseforge", "plugin", "upload", "--input", str(input_path), "--dry-run"])
        self.assertEqual(code, 0)
        self.assertTrue(json.loads(output.getvalue())["dry_run"])
        provider.assert_not_called()

    def test_uncertain_upload_error_is_preserved(self) -> None:
        provider = CurseForge({"CURSEFORGE_UPLOAD_TOKEN": "upload-secret"})
        error = FuploadError("upload result is uncertain", verification_required=True)
        with mock.patch("fupload_cli.curseforge.multipart_request", side_effect=error):
            with self.assertRaises(FuploadError) as raised:
                provider.upload({"project_id": 1, "file": __file__, "game_versions": [1], "release_type": "release"})
        self.assertTrue(raised.exception.verification_required)

    def test_upload_rejects_missing_or_invalid_file_id(self) -> None:
        provider = CurseForge({"CURSEFORGE_UPLOAD_TOKEN": "upload-secret"})
        doc = {"project_id": 1, "file": __file__, "changelog": "notes", "release_type": "release"}
        for response in ({}, {"id": 0}, {"id": True}, {"id": "9"}, []):
            with self.subTest(response=response), mock.patch("fupload_cli.curseforge.multipart_request", return_value=response):
                with self.assertRaises(FuploadError) as raised:
                    provider.upload(doc)
                self.assertEqual(raised.exception.kind, "platform_data_error")


if __name__ == "__main__":
    unittest.main()
