"""DD backup tests use local fixtures and mock task sessions only."""

import copy
import hashlib
import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fupload_cli.dd import DD
from fupload_cli.dd_backup import _load_bundle, _put_backup, generate_backup, scan_backup
from fupload_cli.errors import FuploadError, ValidationError


def response(value):
    return {"code": 0, "result": value}


class BackupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.game = self.root / "game"
        for name in (
            "Interface/AddOns/One/One.toc", "Interface/AddOns/Two/Two.toc", "Interface/AddOns/Other/Other.toc",
            "Interface/Textures/a.tga", "Fonts/one.ttf", "Fonts/two.ttf", "WTF/Config.wtf",
            "WTF/Account/A/SavedVariables/One.lua", "WTF/Account/A/config-cache.wtf",
            "WTF/Account/A/Realm/Chosen/config-cache.wtf", "WTF/Account/A/Realm/Chosen/SavedVariables/Role.lua",
            "WTF/Account/A/Realm/Other/config-cache.wtf", "WTF/Account/A/OtherRealm/Private/config-cache.wtf",
            "WTF/Account/B/Realm/Private/config-cache.wtf",
        ):
            path = self.game / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("fixture", encoding="utf-8")

    def bundle(self, **changes):
        doc = {"game_dir": str(self.game), "game_type": 10001, "output_dir": str(self.root / "bundle"),
               "addon_names": ["One"], "unknown_addons": ["Two"], "materials": ["Textures"], "fonts": ["one.ttf"],
               "include_wtf_root": True, "wtf_accounts": [{"account": "A", "include_common": True, "roles": [{"server": "Realm", "name": "Chosen"}]}]}
        doc.update(changes)
        return generate_backup(doc)

    def session(self, shares=None):
        session = Mock()
        backups = [{"sn": "backup-a", "name": "A", "game_type": 10001}, {"sn": "backup-b", "name": "B", "game_type": 10002}]
        def get(path, params):
            if path == "/backup/list": return response(backups)
            if path == "/game_type/list": return response([{"game_type": 10001}, {"game_type": 10002}])
            if path == "/share/list": return response({"total": len(shares or []), "items": shares or []})
            if path == "/share/detail": return response({"sn": params["sn"], "backup_sn": "backup-a"})
            self.fail("unexpected read " + path)
        session.get.side_effect = get
        session.post.return_value = response({})
        return session

    def test_five_component_archives_match_native_roots_and_selections(self):
        generated = self.bundle()
        manifest, files = _load_bundle(generated["bundle_file"])
        self.assertEqual(set(group for group, _ in files), {"known_addon", "unknown_addon", "material", "font", "wtf"})
        all_names = {}
        for group, path in files:
            with zipfile.ZipFile(path) as archive:
                all_names[group] = archive.namelist()
        self.assertEqual(all_names["known_addon"], ["One/One.toc"])
        self.assertEqual(all_names["unknown_addon"], ["Two/Two.toc"])
        self.assertEqual(all_names["material"], ["Textures/a.tga"])
        self.assertEqual(all_names["font"], ["Fonts/one.ttf"])
        self.assertIn("WTF/Config.wtf", all_names["wtf"])
        self.assertIn("WTF/Account/A/SavedVariables/One.lua", all_names["wtf"])
        self.assertIn("WTF/Account/A/Realm/Chosen/config-cache.wtf", all_names["wtf"])
        self.assertFalse(any("Private" in n or "/Other/" in n or "/B/" in n for n in all_names["wtf"]))
        self.assertEqual(manifest["wtf"]["accounts"], [{"name": "A", "servers": [{"name": "Realm", "items": ["Chosen"]}], "wa_list": []}])
        self.assertEqual(manifest["known_addon"]["items"], [{"name": "One", "modified": True, "dirs": ["One"]}])

    def test_role_only_does_not_capture_common_or_root_files(self):
        result = self.bundle(addon_names=[], unknown_addons=[], materials=[], fonts=[], include_wtf_root=False, wtf_accounts=[{"account": "A", "include_common": False, "roles": [{"server": "Realm", "name": "Chosen"}]}])
        _, files = _load_bundle(result["bundle_file"])
        with zipfile.ZipFile(files[0][1]) as archive:
            self.assertTrue(all(n.startswith("WTF/Account/A/Realm/Chosen/") for n in archive.namelist()))

    def _rewrite_component(self, bundle_file, group, *, extra=None, rename=None):
        path = Path(bundle_file)
        bundle = json.loads(path.read_text(encoding="utf-8"))
        artifact = next(item for item in bundle["artifacts"] if item["group"] == group)
        archive_path = path.parent / artifact["file"]
        with zipfile.ZipFile(archive_path) as archive:
            rows = [(item.filename, archive.read(item)) for item in archive.infolist()]
        with zipfile.ZipFile(archive_path, "w") as archive:
            for name, content in rows:
                archive.writestr(rename(name) if rename else name, content)
            for name in extra or []:
                archive.writestr(name, "added-after-selection")
        data = archive_path.read_bytes()
        digest = hashlib.md5(data).hexdigest()
        artifact.update(size=len(data), md5=digest, sha256=hashlib.sha256(data).hexdigest())
        bundle["manifest"][group].update(size=len(data), md5=digest)
        path.write_text(json.dumps(bundle), encoding="utf-8")

    def test_rehashed_unselected_wtf_root_account_and_server_common_are_rejected(self):
        extras = ["WTF/Extra.wtf", "WTF/Account/A/Extra.wtf", "WTF/Account/A/SavedVariables/Extra.lua",
                  "WTF/Account/A/Realm/Extra.wtf", "WTF/Account/A/Realm/SavedVariables/Extra.lua"]
        for index, extra in enumerate(extras):
            with self.subTest(extra=extra):
                generated = self.bundle(output_dir=str(self.root / ("bundle-" + str(index))), include_wtf_root=False,
                    wtf_accounts=[{"account": "A", "include_common": False, "roles": [{"server": "Realm", "name": "Chosen"}]}])
                self._rewrite_component(generated["bundle_file"], "wtf", extra=[extra])
                remote = Mock()
                with self.assertRaises(ValidationError):
                    DD().upload_backup(remote, {"bundle_file": generated["bundle_file"]})
                remote.get.assert_not_called()
                remote.post.assert_not_called()

    def test_local_selection_is_required_and_must_match_native_role_manifest(self):
        generated = self.bundle()
        path = Path(generated["bundle_file"])
        original = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(original["selection"]["wtf_accounts"][0]["include_common"], True)
        for mutate in (lambda b: b.pop("selection"),
                       lambda b: b["selection"]["wtf_accounts"][0]["roles"][0].update(name="Other"),
                       lambda b: b["manifest"]["wtf"]["accounts"][0]["servers"][0]["items"].append("Other")):
            value = copy.deepcopy(original)
            mutate(value)
            path.write_text(json.dumps(value), encoding="utf-8")
            with self.assertRaises(ValidationError):
                _load_bundle(str(path))

    def test_rehashed_zip_rejects_ads_case_duplicates_and_unselected_role(self):
        for index, extra in enumerate(["One/One.toc:stream", "One/ONE.TOC", "One/../Private.lua", "One//Private.lua"]):
            with self.subTest(extra=extra):
                generated = self.bundle(output_dir=str(self.root / ("unsafe-" + str(index))))
                self._rewrite_component(generated["bundle_file"], "known_addon", extra=[extra])
                with self.assertRaises(ValidationError):
                    _load_bundle(generated["bundle_file"])

    def test_common_false_excludes_server_shared_settings_in_generation(self):
        for relative in ("WTF/Account/A/Realm/config-cache.wtf", "WTF/Account/A/Realm/SavedVariables/Shared.lua"):
            path = self.game / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("server-shared", encoding="utf-8")
        generated = self.bundle(include_wtf_root=False, wtf_accounts=[{"account": "A", "include_common": False,
            "roles": [{"server": "Realm", "name": "Chosen"}]}])
        _, files = _load_bundle(generated["bundle_file"])
        wtf = next(path for group, path in files if group == "wtf")
        with zipfile.ZipFile(wtf) as archive:
            self.assertTrue(all(name.startswith("WTF/Account/A/Realm/Chosen/") for name in archive.namelist()))

    def test_common_true_includes_only_selected_server_shared_settings(self):
        for relative in ("WTF/Account/A/Realm/SavedVariables/Shared.lua", "WTF/Account/A/OtherRealm/SavedVariables/Private.lua"):
            path = self.game / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("shared", encoding="utf-8")
        generated = self.bundle()
        _, files = _load_bundle(generated["bundle_file"])
        with zipfile.ZipFile(next(path for group, path in files if group == "wtf")) as archive:
            self.assertIn("WTF/Account/A/Realm/SavedVariables/Shared.lua", archive.namelist())
            self.assertNotIn("WTF/Account/A/OtherRealm/SavedVariables/Private.lua", archive.namelist())

    def test_rehashed_zip_missing_selected_role_or_containing_unselected_directory_is_rejected(self):
        generated = self.bundle()
        self._rewrite_component(generated["bundle_file"], "wtf", rename=lambda name: name.replace("/Chosen/", "/SavedVariables/"))
        with self.assertRaises(ValidationError):
            _load_bundle(generated["bundle_file"])
        generated = self.bundle(output_dir=str(self.root / "dir-bundle"))
        self._rewrite_component(generated["bundle_file"], "wtf", extra=["WTF/Account/A/Realm/Unselected/"])
        with self.assertRaises(ValidationError):
            _load_bundle(generated["bundle_file"])

    def test_common_only_account_is_available(self):
        result = self.bundle(addon_names=[], unknown_addons=[], materials=[], fonts=[], include_wtf_root=False, wtf_accounts=[{"account": "A", "include_common": True, "roles": []}])
        _, files = _load_bundle(result["bundle_file"])
        with zipfile.ZipFile(files[0][1]) as archive:
            self.assertEqual(set(archive.namelist()), {"WTF/Account/A/SavedVariables/One.lua", "WTF/Account/A/config-cache.wtf"})

    def test_generate_rejects_invalid_roles_and_overlapping_addons(self):
        for changes in ({"addon_names": ["One"], "unknown_addons": ["One"]}, {"unknown_addons": ["../private"]}, {"wtf_accounts": [{"account": "A", "include_common": False, "roles": [{"server": "Realm", "name": "Missing"}]}]}):
            with self.assertRaises(ValidationError): self.bundle(**changes)
        self.assertFalse((self.root / "bundle").exists())

    def test_generate_and_scan_do_not_start_or_require_session(self):
        provider = DD()
        with patch("fupload_cli.dd_broker.execute") as remote:
            self.assertTrue(provider.execute_read("backup", "scan", SimpleNamespace(game_dir=str(self.game)))["wtf_accounts"])
            result = provider.execute_write("backup", "generate", {"game_dir": str(self.game), "game_type": 10001, "output_dir": str(self.root / "local"), "unknown_addons": ["One"]})
            self.assertTrue(Path(result["bundle_file"]).is_file())
            remote.assert_not_called()

    def test_changed_archive_is_refused_before_remote_request(self):
        generated = self.bundle()
        with (self.root / "bundle" / "known_addon.zip").open("ab") as handle: handle.write(b"changed")
        session = Mock()
        with self.assertRaises(ValidationError): DD().upload_backup(session, {"bundle_file": generated["bundle_file"]})
        session.get.assert_not_called()
        session.post.assert_not_called()

    def test_upload_follows_precreate_components_finish_and_both_readbacks(self):
        generated = self.bundle()
        manifest, files = _load_bundle(generated["bundle_file"])
        session = Mock()
        detail = copy.deepcopy(manifest)
        detail.update({"sn": "new-backup", "name": "Created"})
        def get(path, params):
            if path == "/game_type/list": return response([{"game_type": 10001}])
            if path == "/backup/detail": return response(detail)
            if path == "/backup/list": return response([detail])
            self.fail("unexpected read " + path)
        session.get.side_effect = get
        session.post.side_effect = [response({"sn": "new-backup", **{group: {"u_url": "https://storage.example.invalid/" + group} for group, _ in files}}), response({})]
        with patch("fupload_cli.dd_backup._put_backup") as put:
            result = DD().upload_backup(session, {"bundle_file": generated["bundle_file"]})
        self.assertEqual(put.call_count, 5)
        self.assertEqual(result["sn"], "new-backup")
        self.assertEqual(session.post.call_args_list[0].args, ("/backup/pre_create", manifest))
        self.assertEqual(set(manifest), {"game_type", "known_addon", "unknown_addon", "material", "font", "wtf"})
        self.assertNotIn("selection", session.post.call_args_list[0].args[1])
        self.assertEqual(session.post.call_args_list[1].args, ("/backup/finish_create", {"sn": "new-backup"}))
        self.assertNotIn("u_url", json.dumps(result))
        self.assertNotIn("fixture", json.dumps(result))

    def test_prepared_objects_without_put_url_are_reused(self):
        generated = self.bundle(addon_names=[], materials=[], fonts=[], wtf_accounts=[], include_wtf_root=False)
        manifest, _ = _load_bundle(generated["bundle_file"])
        detail = dict(manifest, sn="new", name="New")
        session = Mock()
        session.post.side_effect = [response({"sn": "new", "unknown_addon": {}}), response({})]
        session.get.side_effect = [response([{"game_type": 10001}]), response(detail), response([detail])]
        with patch("fupload_cli.dd_backup._put_backup") as put:
            result = DD().upload_backup(session, {"bundle_file": generated["bundle_file"]})
        put.assert_not_called()
        self.assertEqual(result["reused_components"], ["unknown_addon"])

    def test_failed_put_keeps_sn_and_never_finishes_or_replays(self):
        generated = self.bundle()
        session = Mock()
        session.get.return_value = response([{"game_type": 10001}])
        session.post.return_value = response({"sn": "retained", "known_addon": {"u_url": "https://storage.example.invalid/a"}})
        with patch("fupload_cli.dd_backup._put_backup", side_effect=FuploadError("uncertain", verification_required=True)) as put:
            with self.assertRaises(FuploadError) as failure: DD().upload_backup(session, {"bundle_file": generated["bundle_file"]})
        self.assertEqual(session.post.call_count, 1)
        self.assertEqual(put.call_count, 1)
        self.assertEqual(failure.exception.details["sn"], "retained")
        self.assertTrue(failure.exception.verification_required)

    def test_wrong_content_readback_requires_verification_without_replay(self):
        generated = self.bundle(addon_names=[], materials=[], fonts=[], wtf_accounts=[], include_wtf_root=False)
        session = Mock()
        session.get.side_effect = [response([{"game_type": 10001}]), response({"sn": "new", "game_type": 10001, "unknown_addon": {"items": ["wrong"]}})]
        session.post.side_effect = [response({"sn": "new", "unknown_addon": {}}), response({})]
        with self.assertRaises(FuploadError) as failure: DD().upload_backup(session, {"bundle_file": generated["bundle_file"]})
        self.assertTrue(failure.exception.verification_required)
        self.assertEqual(session.post.call_count, 2)

    def test_upload_accepts_null_readback_for_unselected_empty_component(self):
        generated = self.bundle(addon_names=[], materials=[], fonts=[], wtf_accounts=[], include_wtf_root=False)
        manifest, _ = _load_bundle(generated["bundle_file"])
        detail = copy.deepcopy(manifest)
        detail.update({"sn": "new", "name": "Created", "known_addon": None})
        session = Mock()
        def get(path, params):
            if path == "/game_type/list": return response([{"game_type": 10001}])
            if path == "/backup/detail": return response(detail)
            if path == "/backup/list": return response([detail])
            self.fail("unexpected request " + path)
        session.get.side_effect = get
        session.post.side_effect = [response({"sn": "new", "unknown_addon": {}}), response({})]
        result = DD().upload_backup(session, {"bundle_file": generated["bundle_file"]})
        self.assertEqual(result["sn"], "new")
        self.assertEqual(result["reused_components"], ["unknown_addon"])

    def test_reference_in_any_game_type_blocks_backup_deletion(self):
        session = self.session()
        original = session.get.side_effect
        def get(path, params):
            if path == "/share/list" and params["game_type"] == 10002: return response({"total": 1, "items": [{"sn": "share", "backup_sn": "backup-a"}]})
            return original(path, params)
        session.get.side_effect = get
        with self.assertRaises(FuploadError) as failure: DD().delete_backups(session, {"backup_ids": ["backup-a"], "confirm_delete": True})
        self.assertEqual(failure.exception.kind, "backup_delete_blocked")
        session.post.assert_not_called()

    def test_reference_pagination_and_missing_association_detail(self):
        session = self.session()
        original = session.get.side_effect
        def get(path, params):
            if path == "/share/list" and params["game_type"] == 10001:
                return response({"total": 2, "items": [{"sn": "one"}] if params["page"] == 1 else [{"sn": "two", "backup_sn": "backup-b"}]})
            return original(path, params)
        session.get.side_effect = get
        preview = DD().backup_delete_preview(session, ["backup-a", "backup-b"])
        self.assertEqual([r["references"][0]["sn"] for r in preview["items"]], ["one", "two"])
        self.assertFalse(preview["deletable"])

    def test_reference_detail_missing_or_wrong_identity_blocks_all_deletes(self):
        for detail in ({"backup_sn": "backup-b"}, {"sn": "other", "backup_sn": "backup-b"}, {"share_sn": "other", "backup_sn": "backup-b"}, {"sn": "share", "share_sn": "other", "backup_sn": "backup-b"}, {"sn": 123, "backup_sn": "backup-b"}):
            with self.subTest(detail=detail):
                session = self.session([{"sn": "share"}])
                original = session.get.side_effect
                def get(path, params):
                    if path == "/share/detail": return response(detail)
                    return original(path, params)
                session.get.side_effect = get
                with self.assertRaises(FuploadError) as failed:
                    DD().delete_backups(session, {"backup_ids": ["backup-a", "backup-b"], "confirm_delete": True})
                self.assertEqual(failed.exception.kind, "backup_reference_unknown")
                session.post.assert_not_called()

    def test_reference_detail_accepts_matching_official_sn_aliases(self):
        for key in ("sn", "share_sn"):
            session = self.session([{"sn": "share"}])
            original = session.get.side_effect
            def get(path, params):
                if path == "/share/detail": return response({key: params["sn"], "backup_sn": "backup-a"})
                return original(path, params)
            session.get.side_effect = get
            self.assertEqual(DD().backup_delete_preview(session, ["backup-a"])["items"][0]["reason"], "configuration_share_reference")

    def test_unknown_reference_state_and_incomplete_pages_refuse_delete(self):
        for payload in (response({"items": []}), response({"total": 1, "items": []}), response({"total": 1, "items": [{"sn": "share"}]})):
            session = self.session()
            original = session.get.side_effect
            def get(path, params):
                if path == "/share/list": return payload
                if path == "/share/detail": return response({})
                return original(path, params)
            session.get.side_effect = get
            with self.assertRaises(FuploadError) as failure: DD().delete_backups(session, {"backup_ids": ["backup-a"], "confirm_delete": True})
            self.assertEqual(failure.exception.kind, "backup_reference_unknown")
            session.post.assert_not_called()

    def test_delete_rechecks_late_reference_and_preserves_share(self):
        provider = DD()
        provider.backup_delete_preview = Mock(side_effect=[{"deletable": True, "items": [{"sn": "backup-a"}]}, {"deletable": False, "items": [{"sn": "backup-a", "references": [{"sn": "late-share"}]}]}])
        session = Mock()
        with self.assertRaises(FuploadError): provider.delete_backups(session, {"backup_ids": ["backup-a"], "confirm_delete": True})
        session.post.assert_not_called()

    def test_successful_delete_reads_back_absence(self):
        provider, session = DD(), self.session()
        original = session.get.side_effect
        deleted = False
        def get(path, params):
            if path == "/backup/list" and deleted: return response([{ "sn": "backup-b", "game_type": 10002}])
            return original(path, params)
        def post(path, payload):
            nonlocal deleted
            self.assertEqual((path, payload), ("/backup/delete", {"sn": "backup-a"}))
            deleted = True
            return response({})
        session.get.side_effect, session.post.side_effect = get, post
        self.assertEqual(provider.delete_backups(session, {"backup_ids": ["backup-a"], "confirm_delete": True})["deleted"], 1)
        session.post.assert_called_once()

    def test_uncertain_batch_delete_does_not_continue(self):
        session = self.session()
        session.post.side_effect = FuploadError("uncertain", verification_required=True)
        with self.assertRaises(FuploadError) as failure: DD().delete_backups(session, {"backup_ids": ["backup-a", "backup-b"], "confirm_delete": True})
        self.assertTrue(failure.exception.verification_required)
        self.assertEqual(session.post.call_count, 1)
        self.assertEqual(failure.exception.details["completed"], [])

    def test_rename_uses_verified_endpoint_and_name_readback(self):
        session = Mock()
        session.get.side_effect = [response({"sn": "a", "name": "old"}), response({"sn": "a", "name": "new"})]
        self.assertEqual(DD().rename_backup(session, {"sn": "a", "name": "new"})["readback"]["name"], "new")
        session.post.assert_called_once_with("/backup/modify_name", {"sn": "a", "name": "new"})

    def test_put_uses_exact_native_headers_and_no_cookie(self):
        source = self.root / "zip.zip"
        source.write_bytes(b"fixture")
        for status in (200, 201, 302):
            connection = Mock()
            connection.getresponse.return_value.status = status
            with patch("fupload_cli.dd_backup.http.client.HTTPSConnection", return_value=connection):
                if status in (200, 201): _put_backup(source, "https://storage.example.invalid/a?signature=fixture")
                else:
                    with self.assertRaises(FuploadError): _put_backup(source, "https://storage.example.invalid/a")
            self.assertEqual(connection.request.call_args.kwargs["headers"], {"x-amz-acl": "public-read", "Content-Type": "application/x-zip-compressed", "Content-Length": "7"})
            connection.close.assert_called_once()

    def test_put_upgrades_only_official_http_host_and_preserves_signed_headers(self):
        source = self.root / "backup.zip"
        source.write_bytes(b"fixture")
        connection = Mock()
        connection.getresponse.return_value.status = 200
        query = "AWSAccessKeyId=fixture&Signature=fixture&x-amz-acl=private&content-type=application%2Foctet-stream&Expires=1"
        with patch("fupload_cli.dd_backup.http.client.HTTPSConnection", return_value=connection) as https:
            _put_backup(source, "http://a19-ui-res.s3v2.nie.netease.com/object.zip?" + query)
        https.assert_called_once_with("a19-ui-res.s3v2.nie.netease.com", None, timeout=600)
        self.assertEqual(connection.request.call_args.args[:2], ("PUT", "/object.zip?" + query))
        self.assertEqual(connection.request.call_args.kwargs["headers"], {"x-amz-acl": "private", "Content-Type": "application/octet-stream", "Content-Length": "7"})
        connection.close.assert_called_once()

    def test_put_rejects_untrusted_http_hosts_and_ambiguous_signed_headers(self):
        source = self.root / "backup.zip"
        source.write_bytes(b"fixture")
        urls = (
            "http://untrusted.invalid/object.zip",
            "http://a19-ui-res.s3v2.nie.netease.com:8080/object.zip",
            "https://storage.invalid/object.zip?content-type=a&content-type=b",
            "https://storage.invalid/object.zip?content-type=bad%0D%0AInjected%3Avalue",
        )
        for url in urls:
            with self.subTest(url=url), patch("fupload_cli.dd_backup.http.client.HTTPSConnection") as https:
                with self.assertRaises(FuploadError):
                    _put_backup(source, url)
                https.assert_not_called()

    def test_preview_filters_apply_name_and_iso_dates(self):
        provider, session = DD(), self.session()
        original = session.get.side_effect
        def get(path, params):
            if path == "/backup/list": return response([{"sn": "backup-a", "name": "old fixture", "game_type": 10001, "ctime": 1000000000}, {"sn": "backup-b", "name": "new fixture", "game_type": 10002, "ctime": 1700000000}])
            return original(path, params)
        session.get.side_effect = get
        args = SimpleNamespace(backup_ids=[], name_contains="fixture", name_equals=None, created_before="2010-01-01T00:00:00Z", created_after=None)
        preview = provider.backup_preview_selection(session, args)
        self.assertEqual([r["sn"] for r in preview["items"]], ["backup-a"])


if __name__ == "__main__": unittest.main()
