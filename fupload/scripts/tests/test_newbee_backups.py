"""Local-only Creator WoW backup regression tests; no real sessions or requests."""

import copy
import hashlib
import json
import struct
import subprocess
import sys
import tempfile
import unittest
import warnings
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fupload_cli.errors import FuploadError, ValidationError
from fupload_cli.newbee import NewBee
from fupload_cli.newbee_backup import _extract_nbb_binding, _manifest_matches, generate_backup, scan_backup, upload_fonts


class BackupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.game = self.root / "game"
        for name in (
            "Interface/AddOns/One/One.toc", "Interface/AddOns/Two/Two.toc",
            "Interface/Textures/sample.tga", "Fonts/one.ttf", "Fonts/two.ttf",
            "WTF/Account/A/SavedVariables/One.lua", "WTF/Account/A/SavedVariables/One.lua.bak",
            "WTF/Account/A/config-cache.wtf", "WTF/Account/A/Realm/Chosen/AddOns.txt",
            "WTF/Account/A/Realm/Chosen/SavedVariables/One.lua", "WTF/Account/A/Realm/Other/AddOns.txt",
            "WTF/Account/B/Realm/Private/AddOns.txt",
        ):
            path = self.game / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("local fixture", encoding="utf-8")

    def bundle(self, **kwargs):
        doc = {"game_dir": str(self.game), "game_version_id": 1, "output_dir": str(self.root / "bundle"),
               "unknown_plugins": ["One"], "materials": ["Textures"], "fonts": [], "known_plugins": [],
               "wtf_accounts": [{"account": "A", "include_common": True, "roles": [{"server": "Realm", "name": "Chosen"}]}]}
        doc.update(kwargs)
        return generate_backup(doc)

    def provider(self, configs=None):
        provider = NewBee()
        provider.cloud_backups_raw = Mock(return_value=[{"t_id": 7, "t_name": "Keep", "t_Versionid": 1}, {"t_id": 8, "t_name": "Delete", "t_Versionid": 1}])
        provider.list_configs = Mock(return_value=configs if configs is not None else {"total": 0, "list": []})
        provider.backup_post = Mock()
        return provider

    def assert_bundle_rejected_locally(self, bundle_file):
        provider = NewBee()
        provider.game_versions = Mock(return_value={"items": [{"id": 1}]})
        provider.cloud_backups_raw = Mock(return_value=[])
        provider._upload_backup_zip = Mock(side_effect=AssertionError("ZIP reached remote upload"))
        provider.upload_backup_fonts = Mock(side_effect=AssertionError("fonts reached remote upload"))
        provider.backup_post = Mock(side_effect=AssertionError("manifest reached remote mutation"))
        with patch("fupload_cli.newbee_backup._newbee_archive"), patch("fupload_cli.newbee_backup.shutil.which", return_value="node"):
            with self.assertRaises(ValidationError):
                provider.upload_backup({"bundle_file": str(bundle_file)})
        provider.game_versions.assert_not_called()
        provider.cloud_backups_raw.assert_not_called()
        provider._upload_backup_zip.assert_not_called()
        provider.upload_backup_fonts.assert_not_called()
        provider.backup_post.assert_not_called()

    def add_zip_members(self, bundle_file, file_type, members):
        bundle_file = Path(bundle_file)
        bundle = json.loads(bundle_file.read_text(encoding="utf-8"))
        artifact = next(a for a in bundle["artifacts"] if a["file_type"] == file_type)
        archive_path = bundle_file.parent / artifact["file"]
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            with zipfile.ZipFile(archive_path, "a") as archive:
                for name, content in members:
                    archive.writestr(name, content)
        # ZipInfo normalizes backslashes while writing on Windows. Model an
        # external ZIP by changing both on-disk member headers after writing.
        for name, _content in members:
            if isinstance(name, str) and "\\" in name:
                archive_path.write_bytes(archive_path.read_bytes().replace(name.replace("\\", "/").encode(), name.encode()))
        artifact["size"] = archive_path.stat().st_size
        artifact["sha256"] = hashlib.sha256(archive_path.read_bytes()).hexdigest()
        with zipfile.ZipFile(archive_path) as archive:
            artifact["files"] = sum(not member.is_dir() for member in archive.infolist())
        bundle_file.write_text(json.dumps(bundle), encoding="utf-8")

    def test_manifest_selection_tampering_is_refused_before_any_remote_request(self):
        for selection in ("role", "unknown", "material", "font"):
            with self.subTest(selection=selection):
                generated = self.bundle(output_dir=str(self.root / ("bundle-" + selection)), fonts=["one.ttf"] if selection == "font" else [])
                bundle_file = Path(generated["bundle_file"])
                bundle = json.loads(bundle_file.read_text(encoding="utf-8"))
                if selection == "role": bundle["manifest"]["wtf"][0]["server"][0]["roleList"][0]["name"] = "Other"
                if selection == "unknown": bundle["manifest"]["t_unKnown_list"][0]["name"] = "Two"
                if selection == "material": bundle["manifest"]["t_material_list"][0]["name"] = "OtherTextures"
                if selection == "font": bundle["manifest"]["t_font_list"][0]["name"] = "two.ttf"
                bundle_file.write_text(json.dumps(bundle), encoding="utf-8")
                self.assert_bundle_rejected_locally(bundle_file)

    def test_valid_hash_cannot_authorize_unselected_role_or_common_directories(self):
        for file_type, extra in (("wtfrole", "Other/AddOns.txt"), ("wtfrole", "Chosen"), ("wtfserve", "Other/AddOns.txt"), ("wtfserve", "Other/")):
            with self.subTest(file_type=file_type, extra=extra):
                generated = self.bundle(output_dir=str(self.root / ("layout-%d" % len(list(self.root.glob("layout-*"))))))
                self.add_zip_members(generated["bundle_file"], file_type, [(extra, b"unselected")])
                self.assert_bundle_rejected_locally(generated["bundle_file"])

    def test_zip_member_safety_casefold_duplicates_and_links_are_checked(self):
        unsafe = ["../secret", "/secret", "C:/secret", "Chosen\\secret", "Chosen/./secret", "Chosen/../secret", "Chosen/secret:stream", "Chosen/secret. ", "Chosen/ADDONS.TXT", "Chosen/AddOns.txt"]
        link = zipfile.ZipInfo("Chosen/link")
        link.create_system = 3
        link.external_attr = 0o120777 << 16
        unsafe.append(link)
        for index, member in enumerate(unsafe):
            with self.subTest(member=str(member)):
                generated = self.bundle(output_dir=str(self.root / ("unsafe-%d" % index)), unknown_plugins=[], materials=[])
                self.add_zip_members(generated["bundle_file"], "wtfrole", [(member, b"secret")])
                self.assert_bundle_rejected_locally(generated["bundle_file"])

    def test_readback_rejects_unselected_remote_content(self):
        generated = self.bundle(unknown_plugins=["One"], materials=[], wtf_accounts=[])
        bundle = json.loads(Path(generated["bundle_file"]).read_text(encoding="utf-8"))
        expected = bundle["manifest"]
        expected["unknown_plug"] = "cloud/unknown.zip"
        base = {"t_Versionid": 1, "t_unKnown_list": [{"name": "One"}], "t_unKnown_plug": "cloud/unknown.zip"}
        self.assertTrue(_manifest_matches(expected, base))
        for field, extra in (("t_Known_plug", [{"id": 7}]), ("t_material_list", [{"name": "Unexpected"}]), ("t_font_list", [{"name": "Unexpected.ttf"}]), ("wtflist", [{"account": "Unexpected"}]), ("t_material", "cloud/unselected.zip")):
            with self.subTest(field=field):
                self.assertFalse(_manifest_matches(expected, dict(base, **{field: extra})))

    def test_scan_and_generate_select_exact_sources(self):
        scan = scan_backup(str(self.game))
        self.assertEqual([r["account"] for r in scan["wtf_accounts"]], ["A", "B"])
        generated = self.bundle(fonts=["one.ttf"])
        bundle = json.loads(Path(generated["bundle_file"]).read_text(encoding="utf-8"))
        self.assertEqual([a["file_type"] for a in bundle["artifacts"]], ["unknown_plug", "material", "wtfserve", "wtfrole"])
        names = []
        for artifact in bundle["artifacts"]:
            with zipfile.ZipFile(Path(generated["bundle_file"]).parent / artifact["file"]) as archive:
                names.extend(archive.namelist())
        self.assertIn("One/One.toc", names)
        self.assertIn("SavedVariables/One.lua", names)
        self.assertIn("Chosen/AddOns.txt", names)
        self.assertFalse(any("Other" in n or "Private" in n or "Two" in n or n.endswith(".bak") for n in names))
        self.assertEqual(sorted(p.name for p in (self.root / "bundle" / "Fonts").iterdir()), ["one.ttf"])
        self.assertEqual(bundle["manifest"]["wtf"][0]["server"][0]["roleList"], [{"name": "Chosen", "zip": ""}])

    def test_role_only_omits_account_common(self):
        generated = self.bundle(unknown_plugins=[], materials=[], wtf_accounts=[{"account": "A", "include_common": False, "roles": [{"server": "Realm", "name": "Chosen"}]}])
        bundle = json.loads(Path(generated["bundle_file"]).read_text(encoding="utf-8"))
        self.assertEqual([a["file_type"] for a in bundle["artifacts"]], ["wtfrole"])

    def test_selection_rejects_escape_and_missing_role_before_packaging(self):
        with self.assertRaises(ValidationError):
            self.bundle(unknown_plugins=["../secret"])
        self.assertFalse((self.root / "bundle").exists())
        with self.assertRaises(ValidationError):
            self.bundle(wtf_accounts=[{"account": "A", "include_common": False, "roles": [{"server": "Realm", "name": "Absent"}]}])

    def test_references_detail_fallback_and_all_pages_block_delete(self):
        provider = self.provider()
        provider.list_configs.side_effect = [{"total": 2, "list": [{"t_id": 20}], "next_offset": 1}, {"total": 2, "list": [{"t_id": 21, "cloud_id": 8}]}]
        provider.get_config_raw = Mock(return_value={"t_id": 20, "t_cloudblackid": 7})
        preview = provider.backup_delete_preview([7, 8])
        self.assertFalse(preview["deletable"])
        self.assertEqual([r["references"][0]["id"] for r in preview["items"]], [20, 21])
        self.assertEqual(provider.list_configs.call_args_list[1].args, ("", 1, 100))

    def test_reference_detail_requires_matching_config_id_before_any_delete(self):
        for detail in ({"t_cloudblackid": 8}, {"t_id": 999, "t_cloudblackid": 8}, {"id": 999, "cloud_id": 8}, {"t_id": 20, "id": 999, "cloud_id": 8}, {"id": True, "cloud_id": 8}, {"t_id": 20.0, "cloud_id": 8}):
            with self.subTest(detail=detail):
                provider = self.provider({"total": 1, "list": [{"t_id": 20}]})
                provider.get_config_raw = Mock(return_value=detail)
                with self.assertRaises(FuploadError) as failed:
                    provider.delete_backups({"backup_ids": [7, 8], "confirm_delete": True})
                self.assertEqual(failed.exception.kind, "backup_reference_unknown")
                provider.backup_post.assert_not_called()

    def test_reference_detail_accepts_real_id_aliases_and_numeric_strings(self):
        for key in ("t_id", "id"):
            for ident in (20, "20"):
                provider = self.provider({"total": 1, "list": [{"t_id": 20}]})
                provider.get_config_raw = Mock(return_value={key: ident, "t_cloudblackid": 7})
                self.assertEqual(provider.backup_delete_preview([7])["items"][0]["reason"], "configuration_share_reference")

    def test_referenced_backup_hard_refused_and_share_untouched(self):
        provider = self.provider({"total": 1, "list": [{"id": 20, "cloud_id": 7}]})
        with self.assertRaises(FuploadError) as result:
            provider.delete_backups({"backup_ids": [7], "confirm_delete": True})
        self.assertEqual(result.exception.kind, "backup_delete_blocked")
        provider.backup_post.assert_not_called()

    def test_missing_backup_is_clear_and_blocks_entire_batch_before_delete(self):
        provider = self.provider()
        with self.assertRaises(FuploadError) as missing:
            provider.cloud_backup(999)
        self.assertEqual(missing.exception.kind, "not_found")
        with self.assertRaises(FuploadError) as blocked:
            provider.delete_backups({"backup_ids": [8, 999], "confirm_delete": True})
        self.assertEqual(blocked.exception.kind, "backup_delete_blocked")
        self.assertEqual(blocked.exception.details["items"][1]["reason"], "not_found")
        provider.backup_post.assert_not_called()

    def test_remote_numeric_role_ids_are_exposed_as_config_selector_strings(self):
        row = {"t_id": 7, "t_Versionid": 2, "wtflist": [{"account": "A", "server": [{"serverName": "Realm", "roleList": [{"name": "Chosen", "role_id": 123456}]}]}]}
        provider = NewBee()
        provider.list_backups_raw = Mock(return_value=[row])
        provider.cloud_backups_raw = Mock(return_value=[row])
        self.assertEqual(provider.get_backup(7)["roles"][0]["role_id"], "123456")
        self.assertEqual(provider.cloud_backup(7)["wtf_accounts"][0]["servers"][0]["roles"][0]["role_id"], "123456")

    def test_backup_permission_business_message_is_retained_without_retry(self):
        provider = NewBee()
        with patch("fupload_cli.newbee_backup._read", return_value="fake"), patch("fupload_cli.newbee_backup._jwt_fresh", return_value=True), patch("fupload_cli.newbee_backup.json_request", return_value={"code": 12345, "message": "没有权限操作此备份"}) as request:
            with self.assertRaises(FuploadError) as failed:
                provider.backup_post("/share/update", {"t_id": 7, "t_name": "Changed"})
        self.assertIn("没有权限", str(failed.exception))
        self.assertEqual(failed.exception.business_code, 12345)
        self.assertEqual(failed.exception.endpoint, "/share/update")
        self.assertFalse(failed.exception.verification_required)
        request.assert_called_once()

    def test_incomplete_or_unknown_associations_fail_closed(self):
        for pages in ([{"list": []}], [{"total": 1, "list": []}], [{"total": 2, "list": [{"id": 20, "cloud_id": 7}]}, {"total": 2, "list": []}], [{"total": 1, "list": [{"id": 20}]}]):
            provider = self.provider()
            provider.list_configs.side_effect = pages
            provider.get_config_raw = Mock(return_value={})
            with self.assertRaises(FuploadError) as result:
                provider.delete_backups({"backup_ids": [8], "confirm_delete": True})
            self.assertEqual(result.exception.kind, "backup_reference_unknown")
            provider.backup_post.assert_not_called()

    def test_delete_rechecks_references_immediately_before_mutation(self):
        provider = self.provider()
        provider.list_configs.side_effect = [{"total": 0, "list": []}, {"total": 1, "list": [{"id": 21, "cloud_id": 8}]}]
        with self.assertRaises(FuploadError):
            provider.delete_backups({"backup_ids": [8], "confirm_delete": True})
        provider.backup_post.assert_not_called()

    def test_successful_delete_has_negative_readback_no_share_mutation(self):
        provider = self.provider()
        provider.cloud_backups_raw.side_effect = [[{"t_id": 8}], [{"t_id": 8}], []]
        self.assertEqual(provider.delete_backups({"backup_ids": [8], "confirm_delete": True})["deleted"], 1)
        provider.backup_post.assert_called_once_with("/v3/share/delete", {"t_id": 8})

    def test_uncertain_delete_never_replays_or_continues_batch(self):
        provider = self.provider()
        provider.backup_post.side_effect = FuploadError("uncertain", verification_required=True)
        with self.assertRaises(FuploadError) as result:
            provider.delete_backups({"backup_ids": [7, 8], "confirm_delete": True})
        self.assertTrue(result.exception.verification_required)
        self.assertEqual(provider.backup_post.call_count, 1)
        self.assertFalse(result.exception.details["automatic_retry"])

    def test_upload_protocol_and_create_content_readback(self):
        generated = self.bundle(materials=[], wtf_accounts=[])
        provider = NewBee()
        provider.game_versions = Mock(return_value={"items": [{"id": 1}]})
        provider.cloud_backups_raw = Mock(side_effect=[[], [{"t_id": 9, "t_name": "Auto", "t_Versionid": 1, "t_unKnown_list": '[{"name":"One"}]', "t_unKnown_plug": "cloud/unknown.zip"}], [{"t_id": 9, "t_name": "Auto", "t_Versionid": 1}]])
        provider._upload_backup_zip = Mock(return_value="cloud/unknown.zip")
        provider.backup_post = Mock(return_value={})
        result = provider.upload_backup({"bundle_file": generated["bundle_file"]})
        self.assertEqual(result["id"], 9)
        endpoint, body = provider.backup_post.call_args.args
        self.assertEqual(endpoint, "/v3/share/create")
        self.assertEqual(body["unknown_plug"], "cloud/unknown.zip")
        self.assertEqual(body["wtf"], [])
        self.assertEqual(body["versionid"], 1)

    def test_changed_archive_is_refused_before_any_remote_request(self):
        generated = self.bundle()
        with (self.root / "bundle" / "unknown_plug.zip").open("ab") as file:
            file.write(b"changed")
        provider = NewBee()
        provider.game_versions = Mock(return_value={"items": [{"id": 1}]})
        provider.backup_post = Mock()
        with self.assertRaises(ValidationError):
            provider.upload_backup({"bundle_file": generated["bundle_file"]})
        provider.backup_post.assert_not_called()

    def test_create_with_wrong_remote_content_is_verification_required(self):
        generated = self.bundle(materials=[], wtf_accounts=[])
        provider = NewBee()
        provider.game_versions = Mock(return_value={"items": [{"id": 1}]})
        provider.cloud_backups_raw = Mock(side_effect=[[], [{"t_id": 9, "t_Versionid": 1, "t_unKnown_plug": "wrong"}]])
        provider._upload_backup_zip = Mock(return_value="cloud/unknown.zip")
        provider.backup_post = Mock(return_value={})
        with self.assertRaises(FuploadError) as result:
            provider.upload_backup({"bundle_file": generated["bundle_file"]})
        self.assertTrue(result.exception.verification_required)
        self.assertEqual(provider.backup_post.call_count, 1)

    def test_font_uploader_extracts_only_official_binding_from_asar(self):
        entry = {"files": {"node_modules": {"files": {"nbb-core": {"files": {"dist": {"files": {"nbb-core.win32-x64-msvc.node": {"size": 7, "offset": "0"}}}}}}}}}
        header = json.dumps(entry).encode()
        archive = self.root / "app.asar"
        archive.write_bytes(struct.pack("<4I", 4, 8 + len(header), 4 + len(header), len(header)) + header + b"fixture")
        self.assertEqual(_extract_nbb_binding(archive, self.root).read_bytes(), b"fixture")

    def test_font_uploader_uses_native_folder_api_and_redacts_diagnostics(self):
        result = subprocess.CompletedProcess([], 0, 'sensitive native diagnostic\nFUPLOAD_FONT_RESULT:{"ok":true,"index":"font_index_7"}\n', 'sensitive diagnostic')
        with patch("fupload_cli.newbee_backup._newbee_archive", return_value=self.root / "app.asar"), patch("fupload_cli.newbee_backup.shutil.which", return_value="node"), patch("fupload_cli.newbee_backup._extract_nbb_binding", return_value=self.root / "native.node"), patch("fupload_cli.newbee_backup.subprocess.run", return_value=result) as run:
            self.assertEqual(upload_fonts(self.root), "font_index_7")
            script = run.call_args.args[0][2]
            self.assertIn("uploader.uploadFolder", script)
            self.assertIn("https://api.next.newbeebox.com/uploadserver", script)
            self.assertNotIn("Authorization", script)

    def test_font_failure_does_not_expose_native_output(self):
        result = subprocess.CompletedProcess([], 1, 'private log\nFUPLOAD_FONT_RESULT:{"ok":false}\n', 'private error')
        with patch("fupload_cli.newbee_backup._newbee_archive", return_value=self.root / "app.asar"), patch("fupload_cli.newbee_backup.shutil.which", return_value="node"), patch("fupload_cli.newbee_backup._extract_nbb_binding", return_value=self.root / "native.node"), patch("fupload_cli.newbee_backup.subprocess.run", return_value=result):
            with self.assertRaises(FuploadError) as error:
                upload_fonts(self.root)
        self.assertTrue(error.exception.verification_required)
        self.assertNotIn("private", str(error.exception))

    def test_font_create_manifest_uses_index_and_selected_file_list(self):
        generated = self.bundle(unknown_plugins=[], materials=[], wtf_accounts=[], fonts=["one.ttf"])
        provider = NewBee()
        provider.game_versions = Mock(return_value={"items": [{"id": 1}]})
        provider.cloud_backups_raw = Mock(side_effect=[[], [{"t_id": 9, "t_name": "Auto", "t_Versionid": 1, "t_font_list": [{"name": "one.ttf", "size": 13}], "t_font_ncs_hash": "font_index"}], [{"t_id": 9, "t_Versionid": 1}]])
        provider.upload_backup_fonts = Mock(return_value="font_index")
        provider.backup_post = Mock(return_value={})
        with patch("fupload_cli.newbee_backup._newbee_archive"), patch("fupload_cli.newbee_backup.shutil.which", return_value="node"):
            provider.upload_backup({"bundle_file": generated["bundle_file"]})
        manifest = provider.backup_post.call_args.args[1]
        self.assertEqual(manifest["font_hash"], "font_index")
        self.assertEqual([r["name"] for r in manifest["t_font_list"]], ["one.ttf"])

    def test_backup_desktop_auth_does_not_use_creator_resource_headers(self):
        provider = NewBee()
        with patch("fupload_cli.newbee_backup._read", return_value="fixture-access"), patch("fupload_cli.newbee_backup._jwt_fresh", return_value=True), patch("fupload_cli.newbee_backup.json_request", return_value={"code": 1, "data": []}) as request:
            self.assertEqual(provider.backup_post("/v3/share/list", {}), [])
        self.assertEqual(request.call_args.kwargs["headers"], {"Authorization": "Bearer fixture-access", "boxversion": "1.1.17", "Accept-Language": "zh-CN"})
        self.assertEqual(request.call_args.kwargs["trusted_service"], "creator")
        self.assertIsNone(provider._headers)

    def test_signed_zip_upload_requires_exact_http_200_and_no_creator_auth(self):
        archive = self.root / "component.zip"
        archive.write_bytes(b"archive fixture")
        for status in (200, 201, 302):
            provider = NewBee()
            provider.backup_post = Mock(return_value={"upload_url": "https://storage.example.invalid/a?signature=fixture", "file_path": "cloud/a"})
            response = Mock(status=status)
            connection = Mock()
            connection.getresponse.return_value = response
            with patch("fupload_cli.newbee_backup.http.client.HTTPSConnection", return_value=connection):
                if status == 200:
                    self.assertEqual(provider._upload_backup_zip(archive, "wtfrole"), "cloud/a")
                else:
                    with self.assertRaises(FuploadError):
                        provider._upload_backup_zip(archive, "wtfrole")
            provider.backup_post.assert_called_once_with("/share/generate_upload_url_v2", {"file_type": "wtfrole", "file_size": len(b"archive fixture")})
            headers = connection.request.call_args.kwargs["headers"]
            self.assertEqual(headers, {"Content-Length": str(len(b"archive fixture")), "Content-Type": "application/x-www-form-urlencoded"})
            connection.close.assert_called_once()

    def test_preview_filters_apply_name_and_iso_creation_date(self):
        provider = self.provider()
        provider.cloud_backups_raw.return_value = [{"t_id": 7, "t_name": "old fixture", "t_create_time": "2005-01-01T00:00:00Z"}, {"t_id": 8, "t_name": "new fixture", "t_create_time": "2025-01-01T00:00:00Z"}]
        args = SimpleNamespace(backup_ids=[], name_contains="fixture", name_equals=None, created_before="2010-01-01T00:00:00Z", created_after=None)
        self.assertEqual([r["id"] for r in provider.backup_preview_selection(args)["items"]], [7])

    def test_preview_does_not_treat_unknown_creation_time_as_match(self):
        provider = self.provider()
        args = SimpleNamespace(backup_ids=[], name_contains=None, name_equals=None, created_before="2010-01-01T00:00:00Z", created_after=None)
        with self.assertRaises(ValidationError): provider.backup_preview_selection(args)

    def test_official_http_bucket_uses_tls_and_signed_axios_content_type(self):
        archive = self.root / "component.zip"
        archive.write_bytes(b"archive fixture")
        provider = NewBee()
        provider.backup_post = Mock(return_value={"upload_url": "http://wclboxdata.cn-hangzhou.oss.aliyuncs.com/a?Signature=fixture", "file_path": "cloud/a"})
        connection = Mock()
        connection.getresponse.return_value.status = 200
        with patch("fupload_cli.newbee_backup.http.client.HTTPSConnection", return_value=connection) as factory:
            provider._upload_backup_zip(archive, "unknown_plug")
        self.assertEqual(factory.call_args.args[0], "wclboxdata.cn-hangzhou.oss.aliyuncs.com")
        self.assertEqual(connection.request.call_args.kwargs["headers"]["Content-Type"], "application/x-www-form-urlencoded")

    def test_invalid_json_after_mutation_requires_verification_without_replay(self):
        provider = NewBee()
        with patch("fupload_cli.newbee_backup._read", return_value="fixture"), patch("fupload_cli.newbee_backup._jwt_fresh", return_value=True), patch("fupload_cli.newbee_backup.json_request", side_effect=FuploadError("response was not valid JSON", http_status=200)) as request:
            with self.assertRaises(FuploadError) as raised:
                provider.backup_post("/v3/share/delete", {"t_id": 7})
        self.assertTrue(raised.exception.verification_required)
        request.assert_called_once()


if __name__ == "__main__":
    unittest.main()
