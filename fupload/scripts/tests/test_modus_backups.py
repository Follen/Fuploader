from __future__ import annotations

import hashlib
import io
import json
import sys
import tempfile
import unittest
import urllib.error
import zipfile
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fupload_cli.errors import FuploadError, ValidationError
from fupload_cli.modus import ModUs
from fupload_cli.modus_backup import references, _all_references


class ModUsBackupTests(unittest.TestCase):
    def setUp(self):
        self.client = ModUs(authenticate=False, main_session=True)
        self.client.current_build = 0

    def test_cross_build_share_blocks_delete_even_when_backup_build_matches(self):
        scanned = []
        def request(method, path, body=None, **kwargs):
            self.assertNotEqual(method, "DELETE")
            build = body["server"]
            scanned.append(build)
            return {"rows": [{"id": "cross-build"}] if build == 4 else [], "total": 1 if build == 4 else 0}
        with mock.patch.object(self.client, "cloud_backup_detail", return_value={"id": 7, "serverType": 0}), mock.patch.object(self.client, "_request", side_effect=request), mock.patch.object(self.client, "share_detail", return_value=[{"id": "cross-build", "backupId": 7}]):
            with self.assertRaises(FuploadError) as error:
                self.client.cloud_backup_delete(7, server_type=0)
        self.assertEqual(error.exception.kind, "backup_in_use")
        self.assertEqual(set(scanned), {0, 1, 2, 3, 4})

    def test_missing_or_invalid_backup_build_refuses_delete_before_scanning(self):
        for metadata in ({}, {"serverType": None}, {"serverType": False}, {"serverType": "0"}, {"serverType": 99}):
            with self.subTest(metadata=metadata), mock.patch.object(self.client, "cloud_backup_detail", return_value={"id": 7, **metadata}), mock.patch.object(self.client, "_request") as request:
                with self.assertRaises(FuploadError) as error:
                    self.client.cloud_backup_delete(7, server_type=0)
                self.assertEqual(error.exception.kind, "backup_protection_unknown")
                request.assert_not_called()

    def test_preview_filters_global_list_by_real_backup_build(self):
        listing = [{"id": 7, "serverType": 0, "backupName": "fixture-retail"}, {"id": 8, "serverType": 4, "backupName": "fixture-classic"}]
        def request(method, path, body=None, **kwargs):
            build = body["server"]
            return {"rows": [{"id": "cross-build"}] if build == 3 else [], "total": 1 if build == 3 else 0}
        with mock.patch.object(self.client, "cloud_backups", return_value=listing), mock.patch.object(self.client, "_request", side_effect=request), mock.patch.object(self.client, "share_detail", return_value=[{"id": "cross-build", "backupId": 7}]):
            result = self.client.cloud_backup_preview({"name_contains": "fixture"}, server_type=0)
        self.assertEqual([item["backup_id"] for item in result["items"]], [7])
        self.assertEqual(result["protected_ids"], [7])
        self.assertEqual(result["deletable_ids"], [])

    def test_preview_explicit_wrong_build_and_unknown_build_fail_closed(self):
        for metadata in ({"serverType": 4}, {}):
            with self.subTest(metadata=metadata), mock.patch.object(self.client, "cloud_backups", return_value=[{"id": 7, "backupName": "fixture", **metadata}]), mock.patch.object(self.client, "cloud_backup_detail", return_value={"id": 7}), mock.patch.object(self.client, "_request", return_value={"rows": [], "total": 0}):
                with self.assertRaises(FuploadError):
                    self.client.cloud_backup_preview({"backup_ids": [7]}, server_type=0)

    def test_incomplete_other_build_shares_prevent_delete(self):
        def request(method, path, body=None, **kwargs):
            self.assertNotEqual(method, "DELETE")
            return {"rows": [], "total": 1 if body["server"] == 4 else 0}
        with mock.patch.object(self.client, "cloud_backup_detail", return_value={"id": 7, "serverType": 0}), mock.patch.object(self.client, "_request", side_effect=request):
            with self.assertRaises(FuploadError) as error:
                self.client.cloud_backup_delete(7, server_type=0)
        self.assertEqual(error.exception.kind, "backup_protection_unknown")

    def test_global_share_rows_repeated_across_builds_are_deduplicated(self):
        with mock.patch.object(self.client, "_request", return_value={"rows": [{"id": "same-global-share"}], "total": 1}) as request, mock.patch.object(self.client, "share_detail", return_value=[{"id": "same-global-share", "backupId": 7}]):
            result = _all_references(self.client)
        self.assertEqual(len(result[7]), 1)
        self.assertEqual(request.call_count, 5)

    def test_conflicting_global_share_binding_refuses_delete(self):
        with mock.patch.object(self.client, "cloud_backup_detail", return_value={"id": 7, "serverType": 0}), mock.patch.object(self.client, "_request", return_value={"rows": [{"id": "same-global-share"}], "total": 1}) as request, mock.patch.object(self.client, "share_detail", side_effect=[[{"id": "same-global-share", "backupId": 7}], [{"id": "same-global-share", "backupId": 8}]]):
            with self.assertRaises(FuploadError) as error:
                self.client.cloud_backup_delete(7, server_type=0)
        self.assertEqual(error.exception.kind, "backup_protection_unknown")
        self.assertFalse(any(call.args[0] == "DELETE" for call in request.call_args_list))

    def test_preview_resolves_missing_list_build_from_exact_detail(self):
        with mock.patch.object(self.client, "cloud_backups", return_value=[{"id": 7, "backupName": "fixture"}]), mock.patch.object(self.client, "cloud_backup_detail", return_value={"id": 7, "serverType": 0}) as detail, mock.patch.object(self.client, "_request", return_value={"rows": [], "total": 0}):
            result = self.client.cloud_backup_preview({"backup_ids": [7]}, server_type=0)
        self.assertEqual(result["deletable_ids"], [7])
        detail.assert_called_once_with(7, server_type=0)

    def test_wrong_build_cannot_bypass_reference_protection(self):
        with mock.patch.object(self.client, "cloud_backup_detail", return_value={"id": 7, "serverType": 1}), mock.patch.object(self.client, "_request") as request:
            with self.assertRaisesRegex(FuploadError, "different Build"):
                self.client.cloud_backup_delete(7, server_type=0)
        request.assert_not_called()

    def test_delete_bad_json_and_http_5xx_are_uncertain_without_replay(self):
        self.client.token = "fixture-token"
        original = self.client._request
        for status in (200, 503):
            response = mock.MagicMock()
            response.__enter__.return_value = response
            response.status = 200
            response.read.return_value = b"{"
            failure = urllib.error.HTTPError("https://fixture.invalid/", 503, "unavailable", {}, io.BytesIO(b'{}'))
            def request(method, path, *args, **kwargs):
                if method == "DELETE":
                    return original(method, path, *args, **kwargs)
                return {"rows": [], "total": 0}
            with self.subTest(status=status), mock.patch.object(self.client, "cloud_backup_detail", return_value={"id": 7, "serverType": 0}), mock.patch.object(self.client, "_request", side_effect=request), mock.patch("fupload_cli.modus.urllib.request.urlopen", **({"return_value": response} if status == 200 else {"side_effect": failure})) as network:
                result = self.client.cloud_backup_delete_many({"backup_ids": [7, 8], "confirm_delete": True}, server_type=0)
            self.assertFalse(result["completed"])
            self.assertTrue(result["verification_required"])
            self.assertTrue(result["items"][0]["error"]["verification_required"])
            self.assertEqual(result["unprocessed_ids"], [8])
            self.assertEqual(network.call_count, 1)

    def test_share_pagination_details_and_protection(self):
        pages = [{"rows": [{"id": "11"}], "total": 2}, {"rows": [{"id": "12"}], "total": 2}]
        with mock.patch.object(self.client, "_request", side_effect=pages) as request, mock.patch.object(self.client, "share_detail", side_effect=[[{"id": "11", "backupId": 7}], [{"id": "12", "backupId": 8}]]) as detail:
            result = references(self.client, 0)
        self.assertEqual(set(result), {7, 8})
        self.assertEqual([call.args[2]["pageNum"] for call in request.call_args_list], [1, 2])
        self.assertTrue(all(call.args[2]["mine"] is True for call in request.call_args_list))
        self.assertEqual(detail.call_count, 2)

    def test_unknown_association_and_incomplete_pagination_fail_closed(self):
        cases = [
            ({"rows": [], "total": 1}, []),
            ({"rows": []}, []),
            ({"rows": [{"id": "11"}], "total": 1}, [{"id": "11"}]),
            ({"rows": [{"id": "11"}], "total": 1}, []),
        ]
        for page, details in cases:
            with self.subTest(page=page, details=details), mock.patch.object(self.client, "_request", return_value=page), mock.patch.object(self.client, "share_detail", return_value=details):
                with self.assertRaises(FuploadError):
                    references(self.client, 0)

    def test_single_delete_refuses_used_backup_without_mutation(self):
        with mock.patch.object(self.client, "cloud_backup_detail", return_value={"id": 7, "serverType": 0}), mock.patch.object(self.client, "_request", return_value={"rows": [{"id": "11"}], "total": 1}) as request, mock.patch.object(self.client, "share_detail", return_value=[{"id": "11", "backupId": 7}]):
            with self.assertRaises(FuploadError) as error:
                self.client.cloud_backup_delete(7, server_type=0)
        self.assertEqual(error.exception.kind, "backup_in_use")
        self.assertFalse(any(call.args[0] == "DELETE" for call in request.call_args_list))

    def test_single_delete_reads_back_and_never_deletes_shares(self):
        with mock.patch.object(self.client, "cloud_backup_detail", side_effect=[{"id": 7, "serverType": 0}, None]) as detail, mock.patch.object(self.client, "cloud_backups", return_value=[]), mock.patch.object(self.client, "_request", side_effect=[{"rows": [], "total": 0}] * 5 + [{"code": 200}]) as request:
            result = self.client.cloud_backup_delete(7, server_type=0)
        self.assertTrue(result["verified"])
        self.assertEqual(detail.call_count, 2)
        self.assertEqual([call.args[1] for call in request.call_args_list if call.args[0] == "DELETE"], ["system/user/backup/delete/7"])

    def test_uncertain_delete_is_not_retried_and_stops_batch(self):
        def request(method, path, *args, **kwargs):
            if method == "DELETE":
                raise FuploadError("interrupted", verification_required=True)
            return {"rows": [], "total": 0}
        with mock.patch.object(self.client, "cloud_backup_detail", return_value={"id": 7, "serverType": 0}), mock.patch.object(self.client, "_request", side_effect=request) as remote:
            result = self.client.cloud_backup_delete_many({"backup_ids": [7, 8], "confirm_delete": True}, server_type=0)
        self.assertFalse(result["completed"])
        self.assertTrue(result["verification_required"])
        self.assertEqual(result["unprocessed_ids"], [8])
        self.assertEqual(sum(call.args[0] == "DELETE" for call in remote.call_args_list), 1)

    def test_bulk_skips_protected_target_and_rechecks_next(self):
        protected = FuploadError("linked", kind="backup_in_use")
        with mock.patch("fupload_cli.modus_backup.delete_one", side_effect=[protected, {"backup_id": 8, "deleted": True, "verified": True}]) as delete:
            result = self.client.cloud_backup_delete_many({"backup_ids": [7, 8], "confirm_delete": True}, server_type=0)
        self.assertTrue(result["completed"])
        self.assertEqual(result["items"][0]["status"], "protected")
        self.assertEqual(delete.call_count, 2)

    def test_delete_readback_still_present_is_uncertain(self):
        with mock.patch.object(self.client, "cloud_backup_detail", return_value={"id": 7, "serverType": 0}), mock.patch.object(self.client, "cloud_backups", return_value=[{"id": 7}]), mock.patch.object(self.client, "_request", side_effect=[{"rows": [], "total": 0}] * 5 + [{"code": 200}]) as request:
            with self.assertRaises(FuploadError) as error:
                self.client.cloud_backup_delete(7, server_type=0)
        self.assertTrue(error.exception.verification_required)
        self.assertEqual(sum(call.args[0] == "DELETE" for call in request.call_args_list), 1)

    def test_preview_filters_and_excludes_referenced_backup(self):
        with mock.patch.object(self.client, "cloud_backups", return_value=[{"id": 7, "serverType": 0, "backupName": "test-a"}, {"id": 8, "serverType": 0, "backupName": "test-b"}, {"id": 9, "serverType": 0, "backupName": "other"}]), mock.patch("fupload_cli.modus_backup.references", return_value={7: [{"share_id": "11"}]}):
            result = self.client.cloud_backup_preview({"name_contains": "test"}, server_type=0)
        self.assertEqual(result["protected_ids"], [7])
        self.assertEqual(result["deletable_ids"], [8])

    def _fixture(self, temporary):
        root = Path(temporary) / "game"
        for path, content in {
            "Interface/AddOns/Chosen/main.lua": "addon",
            "Interface/AddOns/Omitted/private.lua": "omitted",
            "Fonts/ARHei.ttf": "font",
            "Interface/Custom/a.blp": "material",
            "WTF/Account/AccountOne/RealmOne/Chosen/config-cache.wtf": "selected",
            "WTF/Account/AccountOne/RealmOne/Omitted/config-cache.wtf": "omitted",
            "WTF/Account/AccountOne/SavedVariables/Chosen.lua": "shared",
            "WTF/Account/AccountOne/SavedVariables/BigFootSync.lua": "excluded",
            "WTF/Config.wtf": "config",
        }.items():
            file = root / path
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_text(content)
        return {"game_root": str(root), "output_dir": str(Path(temporary) / "backup"), "backup_name": "fixture",
                "addon_names": ["Chosen"], "font_names": ["ARHei.ttf"], "material_names": ["Custom"],
                "roles": [{"account": "AccountOne", "server": "RealmOne", "role": "Chosen"}], "server_type": 0}

    def test_generation_has_only_selected_files_and_no_remote_calls(self):
        with tempfile.TemporaryDirectory() as temporary, mock.patch.object(self.client, "_request") as request:
            doc = self._fixture(temporary)
            result = self.client.cloud_backup_generate(doc)
            copied = [path.relative_to(result["output_dir"]).as_posix() for path in Path(result["output_dir"]).rglob("*") if path.is_file()]
            manifest = json.loads(Path(result["manifest_file"]).read_text(encoding="utf-8"))
        request.assert_not_called()
        self.assertTrue(all("Omitted" not in name and "BigFootSync" not in name for name in copied))
        self.assertIn("WTF/Account/AccountOne/RealmOne/Chosen/config-cache.wtf", copied)
        self.assertEqual(manifest["schemaVersion"], "config-backup.v2")
        self.assertNotIn("cloudBackupId", manifest["source"])

    def test_generation_rejects_traversal_and_existing_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            doc = self._fixture(temporary)
            with self.assertRaises(ValidationError):
                self.client.cloud_backup_generate({**doc, "addon_names": ["../Omitted"]})
            self.client.cloud_backup_generate(doc)
            with self.assertRaises(ValidationError):
                self.client.cloud_backup_generate(doc)

    def test_upload_matches_full_official_protocol_and_links_numeric_id(self):
        with tempfile.TemporaryDirectory() as temporary:
            generated = self.client.cloud_backup_generate(self._fixture(temporary))
            requests = []
            archives = []
            def request(method, path, body=None, **kwargs):
                requests.append((method, path, body, kwargs))
                if path.startswith("game/data/file/getSignature?"):
                    from urllib.parse import urlsplit, parse_qs
                    query = parse_qs(urlsplit(path).query)
                    self.assertEqual(query["sign"][0], hashlib.sha256(("123" + query["fileName"][0] + "modus_upload_sign_key_2026").encode()).hexdigest())
                    return {"data": {"signedUrl": "https://store.invalid/upload?temporary=secret", "key": "modus/" + query["fileName"][0]}}
                if path.endswith("check/font"):
                    return {"data": {"notExist": body["fontMd5"]}}
                if path.endswith("backup/create"):
                    return {"data": 77}
                return {"code": 200}
            def binary(url, file, **kwargs):
                if file.endswith(".zip"):
                    with zipfile.ZipFile(file) as archive:
                        archives.extend(archive.namelist())
                return {"etag": hashlib.md5(Path(file).read_bytes()).hexdigest()}
            with mock.patch.object(self.client, "user_info", return_value={"user": {"userId": "123"}}), mock.patch.object(self.client, "_request", side_effect=request), mock.patch.object(self.client, "upload_zip", side_effect=binary), mock.patch.object(self.client, "cloud_backup_detail", return_value={"id": 77, "backupName": "fixture"}), mock.patch.object(self.client, "cloud_backups", return_value=[{"id": 77}]):
                result = self.client.cloud_backup_upload({"manifest_file": generated["manifest_file"], "server_type": 0})
            manifest = json.loads(Path(generated["manifest_file"]).read_text(encoding="utf-8"))
            state = Path(result["transaction_file"]).read_text(encoding="utf-8")
            body = next(item[2] for item in requests if item[1].endswith("backup/create"))
            self.assertEqual(json.loads(body["wtfAccounts"])[0]["roles"], ["RealmOne-Chosen"])
            self.assertEqual(manifest["source"]["cloudBackupId"], "77")
            self.assertEqual(result["backup_id"], 77)
            self.assertNotEqual(result["local_backup_id"], "77")
            self.assertIn("Chosen/RealmOne/Chosen/config-cache.wtf".replace("Chosen/RealmOne", "AccountOne/RealmOne"), archives)
            self.assertTrue(all("Omitted" not in name for name in archives))
            self.assertNotIn("temporary=secret", state)
            self.assertNotIn("signedUrl", state)
            with self.assertRaises(ValidationError):
                self.client.cloud_backup_upload({"manifest_file": generated["manifest_file"], "server_type": 0})

    def _assert_wtf_upload_rejected_before_authentication(self, generated):
        def request(method, path, body=None, **kwargs):
            if "getSignature?" in path:
                return {"data": {"signedUrl": "https://store.invalid/upload", "key": "modus/object"}}
            if path.endswith("backup/create"):
                return {"data": 77}
            return {"code": 200}
        with mock.patch.object(self.client, "user_info", return_value={"id": 123}) as user, mock.patch.object(self.client, "_request", side_effect=request) as remote, mock.patch.object(self.client, "upload_zip", return_value={"etag": "abc"}) as binary, mock.patch.object(self.client, "cloud_backup_detail", return_value={"id": 77, "backupName": "fixture"}), mock.patch.object(self.client, "cloud_backups", return_value=[{"id": 77}]):
            with self.assertRaises(ValidationError):
                self.client.cloud_backup_upload({"manifest_file": generated["manifest_file"], "server_type": 0})
            user.assert_not_called()
            remote.assert_not_called()
            binary.assert_not_called()
        self.assertFalse((Path(generated["output_dir"]) / ".fupload-cloud-upload.json").exists())

    def test_upload_rejects_role_added_after_generation_without_changing_manifest(self):
        with tempfile.TemporaryDirectory() as temporary:
            doc = self._fixture(temporary)
            doc.update({"addon_names": [], "font_names": [], "material_names": []})
            generated = self.client.cloud_backup_generate(doc)
            extra = Path(generated["output_dir"]) / "WTF/Account/AccountOne/RealmOne/Unselected/config-cache.wtf"
            extra.parent.mkdir(parents=True)
            extra.write_text("unselected role")
            self._assert_wtf_upload_rejected_before_authentication(generated)

    def test_upload_rejects_wtf_names_or_paths_that_disagree_with_parent_hierarchy(self):
        mutations = (
            lambda account, server, role: server.update(name="OtherRealm"),
            lambda account, server, role: role.update(name="OtherRole"),
            lambda account, server, role: role["meta"].update(account="OtherAccount"),
            lambda account, server, role: role["meta"].update(server="OtherRealm"),
            lambda account, server, role: role.update(targetRelativePath=account["targetRelativePath"]),
        )
        for mutate in mutations:
            with self.subTest(mutation=mutate), tempfile.TemporaryDirectory() as temporary:
                doc = self._fixture(temporary)
                doc.update({"addon_names": [], "font_names": [], "material_names": []})
                generated = self.client.cloud_backup_generate(doc)
                manifest_file = Path(generated["manifest_file"])
                manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
                wtf = next(section for section in manifest["sections"] if section["key"] == "wtf")
                account = next(item for item in wtf["items"] if item.get("meta", {}).get("type") == "account")
                server = account["children"][0]
                mutate(account, server, server["children"][0])
                manifest_file.write_text(json.dumps(manifest), encoding="utf-8")
                self._assert_wtf_upload_rejected_before_authentication(generated)

    def _capture_wtf_upload(self, generated, on_authenticate=None):
        archives, requests = [], []
        def request(method, path, body=None, **kwargs):
            requests.append((path, body))
            if "getSignature?" in path:
                return {"data": {"signedUrl": "https://store.invalid/upload", "key": "modus/object"}}
            if path.endswith("backup/create"):
                return {"data": 77}
            return {"code": 200}
        def user():
            if on_authenticate is not None:
                on_authenticate()
            return {"user": {"userId": "123"}}
        def binary(url, file, **kwargs):
            if file.endswith(".zip"):
                with zipfile.ZipFile(file) as archive:
                    archives.extend(archive.namelist())
            return {"etag": hashlib.md5(Path(file).read_bytes()).hexdigest()}
        with mock.patch.object(self.client, "user_info", side_effect=user), mock.patch.object(self.client, "_request", side_effect=request), mock.patch.object(self.client, "upload_zip", side_effect=binary), mock.patch.object(self.client, "cloud_backup_detail", return_value={"id": 77, "backupName": "fixture"}), mock.patch.object(self.client, "cloud_backups", return_value=[{"id": 77}]):
            result = self.client.cloud_backup_upload({"manifest_file": generated["manifest_file"], "server_type": 0})
        body = next(body for path, body in requests if path.endswith("backup/create"))
        return result, archives, json.loads(body["wtfAccounts"])

    def test_upload_freezes_wtf_file_selection_before_authentication(self):
        with tempfile.TemporaryDirectory() as temporary:
            doc = self._fixture(temporary)
            doc.update({"addon_names": [], "font_names": [], "material_names": []})
            generated = self.client.cloud_backup_generate(doc)
            def add_role():
                extra = Path(generated["output_dir"]) / "WTF/Account/AccountOne/RealmOne/Unselected/config-cache.wtf"
                extra.parent.mkdir(parents=True)
                extra.write_text("unselected role")
            result, archives, accounts = self._capture_wtf_upload(generated, add_role)
            self.assertTrue(result["verified"])
            self.assertTrue(all("Unselected" not in name for name in archives))
            self.assertIn("AccountOne/RealmOne/Chosen/config-cache.wtf", archives)
            self.assertEqual(accounts[0]["roles"], ["RealmOne-Chosen"])

    def test_upload_includes_only_explicit_wtf_config_and_global_shared_selections(self):
        with tempfile.TemporaryDirectory() as temporary:
            doc = self._fixture(temporary)
            doc.update({"addon_names": [], "font_names": [], "material_names": []})
            generated = self.client.cloud_backup_generate(doc)
            manifest_file = Path(generated["manifest_file"])
            manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
            wtf = next(section for section in manifest["sections"] if section["key"] == "wtf")
            wtf["items"] = [item for item in wtf["items"] if item.get("meta", {}).get("type") != "config"]
            wtf["count"] = len(wtf["items"])
            wtf["sizeBytes"] = sum(item["sizeBytes"] for item in wtf["items"])
            manifest_file.write_text(json.dumps(manifest), encoding="utf-8")
            extra = Path(generated["output_dir"]) / "WTF/Account/SavedVariables/Unselected.lua"
            extra.parent.mkdir(parents=True)
            extra.write_text("unselected shared file")
            result, archives, accounts = self._capture_wtf_upload(generated)
            self.assertTrue(result["verified"])
            self.assertNotIn("Config.wtf", archives)
            self.assertNotIn("SavedVariables/Unselected.lua", archives)
            self.assertIn("AccountOne/SavedVariables/Chosen.lua", archives)
            self.assertEqual(accounts[0]["roles"], ["RealmOne-Chosen"])

    def test_upload_rejects_wtf_paths_hidden_in_another_category(self):
        with tempfile.TemporaryDirectory() as temporary:
            generated = self.client.cloud_backup_generate(self._fixture(temporary))
            manifest_file = Path(generated["manifest_file"])
            manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
            addons = next(section for section in manifest["sections"] if section["key"] == "unknownAddons")
            addons["items"][0]["targetRelativePath"] = "WTF/Account/AccountOne"
            manifest_file.write_text(json.dumps(manifest), encoding="utf-8")
            self._assert_wtf_upload_rejected_before_authentication(generated)

    def test_uncertain_upload_register_is_not_retried(self):
        with tempfile.TemporaryDirectory() as temporary:
            doc = self._fixture(temporary)
            doc.update({"font_names": [], "roles": [], "material_names": []})
            generated = self.client.cloud_backup_generate(doc)
            def request(method, path, body=None, **kwargs):
                if "getSignature?" in path:
                    return {"data": {"signedUrl": "https://store.invalid/upload", "key": "modus/object"}}
                if path.endswith("backup/create"):
                    raise FuploadError("interrupted", verification_required=True)
                return {"code": 200}
            with mock.patch.object(self.client, "user_info", return_value={"id": 123}), mock.patch.object(self.client, "cloud_backups", return_value=[]), mock.patch.object(self.client, "_request", side_effect=request) as remote, mock.patch.object(self.client, "upload_zip", return_value={"etag": "abc"}):
                with self.assertRaises(FuploadError) as error:
                    self.client.cloud_backup_upload({"manifest_file": generated["manifest_file"], "server_type": 0})
                self.assertTrue(error.exception.verification_required)
                self.assertEqual(sum(call.args[1].endswith("backup/create") for call in remote.call_args_list), 1)
                remote.reset_mock()
                with self.assertRaises(FuploadError):
                    self.client.cloud_backup_upload({"manifest_file": generated["manifest_file"], "server_type": 0})
                remote.assert_not_called()

    def test_opaque_share_ids_remain_protected(self):
        share_id = "opaque-share-uuid"
        with mock.patch.object(self.client, "_request", return_value={"rows": [{"id": share_id}], "total": 1}), mock.patch.object(self.client, "share_detail", return_value=[{"id": share_id, "backupId": 7}]):
            self.assertEqual(references(self.client, 0)[7][0]["share_id"], share_id)

    def test_create_without_returned_id_resolves_exact_new_manifest(self):
        with tempfile.TemporaryDirectory() as temporary:
            doc = self._fixture(temporary)
            doc.update({"font_names": [], "roles": [], "material_names": []})
            generated = self.client.cloud_backup_generate(doc)
            def request(method, path, body=None, **kwargs):
                if "getSignature?" in path:
                    return {"data": {"signedUrl": "https://store.invalid/upload", "key": "modus/unique-manifest"}}
                return {"code": 200, "msg": "success"}
            detail = {"id": 77, "backupName": "fixture", "manifestPath": "modus/unique-manifest"}
            with mock.patch.object(self.client, "user_info", return_value={"user": {"userId": "123"}}), mock.patch.object(self.client, "cloud_backups", side_effect=[[], [{"id": 77}], [{"id": 77}]]), mock.patch.object(self.client, "cloud_backup_detail", return_value=detail), mock.patch.object(self.client, "_request", side_effect=request) as remote, mock.patch.object(self.client, "upload_zip", return_value={"etag": "abc"}):
                result = self.client.cloud_backup_upload({"manifest_file": generated["manifest_file"], "server_type": 0})
            self.assertEqual(result["backup_id"], 77)
            self.assertEqual(sum(call.args[1].endswith("backup/create") for call in remote.call_args_list), 1)

    def test_deleted_backup_official_missing_business_error_is_confirmed(self):
        for message, allowed in (("没有备份信息，获取失败", True), ("数据库暂时不可用", False)):
            with self.subTest(message=message), mock.patch.object(self.client, "cloud_backup_detail", side_effect=[{"id": 7, "serverType": 0}, FuploadError(message, business_code=500)]), mock.patch.object(self.client, "cloud_backups", return_value=[]), mock.patch.object(self.client, "_request", side_effect=[{"rows": [], "total": 0}] * 5 + [{"code": 200}]):
                if allowed:
                    self.assertTrue(self.client.cloud_backup_delete(7, server_type=0)["verified"])
                else:
                    with self.assertRaises(FuploadError) as error:
                        self.client.cloud_backup_delete(7, server_type=0)
                    self.assertTrue(error.exception.verification_required)


if __name__ == "__main__":
    unittest.main()
