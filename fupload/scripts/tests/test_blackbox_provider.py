from __future__ import annotations

import ast
import importlib.util
import pkgutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fupload_cli.blackbox import API_MISC_BASE, API_BASE, Blackbox
from fupload_cli.blackbox_web import BlackboxWebSession, web_hkey
from fupload_cli.errors import FuploadError

class BlackboxProviderTests(unittest.TestCase):
    def test_game_type_discovery_requires_the_official_dynamic_result(self):
        calls = []
        def transport(method, path, body, query):
            calls.append((method, path, body, query))
            return {"status": "ok", "result": {"strappidInfos": [{"strappid": "wowretail", "name": "Retail"}]}}
        result = Blackbox(transport=transport).execute_read("options", "game-types", {})
        self.assertEqual(result["items"][0]["strappid"], "wowretail")
        self.assertEqual(calls, [("GET", "/wow/v2/dynamic_conf/", {}, {})])
        for malformed in (None, [], {}, ["wowretail"]):
            with self.subTest(result=malformed), self.assertRaises(FuploadError):
                Blackbox(transport=lambda *args: {"result": {"strappidInfos": malformed}}).execute_read("options", "game-types", {})

    def test_web_session_is_the_only_authentication_runtime(self):
        class Session:
            def request(self, method, path, body=None, query=None):
                return {"status": "ok", "result": {"moduleList": []}}
            def close(self):
                pass
        provider = Blackbox(web_session=Session())
        result = provider._request("GET", "/wow/open_platform/module/list/")
        self.assertEqual(result["status"], "ok")

    def test_default_uses_http_and_never_launches_browser_when_login_is_required(self):
        from fupload_cli.blackbox_http import BlackboxHttpSession
        provider = Blackbox()
        self.assertIs(provider._web_session_factory, BlackboxHttpSession)
        with patch.object(BlackboxHttpSession, "request", side_effect=FuploadError("login required", kind="login_required")), patch.object(BlackboxWebSession, "_launch") as browser:
            with self.assertRaises(FuploadError) as raised:
                provider.plugin_list()
        self.assertEqual(raised.exception.kind, "login_required")
        browser.assert_not_called()

    def test_web_hkey_vector_changes_with_inputs(self):
        path = "/wow/open_platform/module_version/list/"
        baseline = web_hkey(path, 1799999999, "0123456789ABCDEF")
        variants = {baseline, web_hkey("/wow/open_platform/module/list/", 1799999999, "0123456789ABCDEF"), web_hkey(path, 1800000000, "0123456789ABCDEF"), web_hkey(path, 1799999999, "ABD")}
        self.assertEqual(baseline, "17UYI91")
        self.assertGreaterEqual(len(variants), 3)

    def test_desktop_api_origin_is_rejected(self):
        with self.assertRaises(FuploadError) as raised:
            Blackbox(web_session=object())._request("POST", "/bbs/app/api/qcloud/cos/upload/info/v2", base=API_MISC_BASE, body={})
        self.assertEqual(raised.exception.kind, "validation_error")

    def test_read_and_mutations_use_workshop_routes(self):
        state = {"module": {"id": 7, "name": "taptool", "logoUrl": "logo", "categoryIds": [2, 1], "type": 1, "desc": "d", "official": "o", "officialUrl": "u", "coreFolders": "A,B"}, "versions": []}
        writes = []
        def transport(method, path, body, query):
            if path.endswith("module/list/"): return {"status":"ok","result":{"moduleList":[state["module"]]}}
            if path.endswith("module/detail/"): return {"status":"ok","result":{"module":state["module"]}}
            if path.endswith("module/update/"): writes.append(dict(body)); state["module"].update(body); return {"status":"ok","result":{}}
            if path.endswith("module_version/list/"): return {"status":"ok","result":{"versionList":state["versions"],"total":len(state["versions"])}}
            if path.endswith("module_version/upsert/"):
                row={**body,"id":body.get("versionId",9),"gameVersions":body["gameVersions"].split(","),"fileUrlHeybox":body["fileUrl"]}; state["versions"]=[row]; return {"status":"ok","result":{}}
            if path.endswith("module_version/delete/"): state["versions"]=[]; return {"status":"ok","result":{}}
            raise AssertionError(path)
        provider = Blackbox({"verify_attempts": 1, "delete_settle_seconds": 0}, transport)
        self.assertEqual(provider.plugin_list()["total_count"], 1)
        self.assertTrue(provider.execute_write("plugin", "edit", {"id":7,"name":"changed","category_ids":[1,2],"core_folders":["A","B"]})["verified"])
        self.assertEqual(writes[-1], {"name":"changed","logoUrl":"logo","id":7,"categoryIds":[1,2],"type":1,"desc":"d","official":"o","officialUrl":"u","coreFolders":"A,B"})
        self.assertTrue(provider.execute_write("version", "create", {"module_id":7,"name":"v","type":3,"game_versions":["1.0"],"file_url":"https://x"})["verified"])
        self.assertTrue(provider.execute_write("version", "delete", {"module_id":7,"version_id":9})["verified"])

    def test_version_delete_does_not_replay_when_deleted_row_reactivates(self):
        state = {"row": {"id": 9, "auditState": 1}, "deletes": 0, "reads": 0}
        def transport(method, path, body, query):
            if path.endswith("module_version/delete/"):
                state["deletes"] += 1
                state["row"]["auditState"] = 4
                return {"status": "ok", "result": {}}
            if path.endswith("module_version/list/"):
                state["reads"] += 1
                if state["deletes"] == 1 and state["reads"] == 2:
                    state["row"]["auditState"] = 1
                return {"status": "ok", "result": {"versionList": [dict(state["row"])], "total":1}}
            raise AssertionError(path)
        provider = Blackbox({"verify_attempts": 1, "delete_settle_seconds": 0.001}, transport)
        with self.assertRaises(FuploadError) as raised:
            provider.version_delete({"module_id": 7, "version_id": 9})
        self.assertTrue(raised.exception.verification_required)
        self.assertEqual(state["deletes"], 1)

    def test_module_edit_waits_for_delayed_field_projection(self):
        state = {"categoryIds": [1], "reads_after_write": 0, "written": False}
        def transport(method, path, body, query):
            if path.endswith("module/detail/"):
                if state["written"]:
                    state["reads_after_write"] += 1
                category_ids = [1] if state["reads_after_write"] < 2 else state["categoryIds"]
                return {"status":"ok","result":{"module":{"id":7,"name":"taptool","logoUrl":"logo","categoryIds":category_ids,"type":1,"desc":"d","official":"o","officialUrl":"u","coreFolders":"A"}}}
            if path.endswith("module/update/"):
                state["written"] = True
                state["categoryIds"] = list(body["categoryIds"])
                return {"status":"ok","result":{}}
            raise AssertionError(path)
        result = Blackbox({"verify_attempts": 2, "verify_interval": 0}, transport).module_edit({"id":7,"category_ids":[2,3]})
        self.assertTrue(result["verified"])
        self.assertEqual(state["reads_after_write"], 2)

    def test_version_delete_stability_failure_requires_readback(self):
        state = {"row": {"id": 9, "auditState": 1}, "deletes": 0, "reads": 0}
        def transport(method, path, body, query):
            if path.endswith("module_version/delete/"):
                state["deletes"] += 1
                state["row"]["auditState"] = 4
                return {"status":"ok","result":{}}
            if path.endswith("module_version/list/"):
                state["reads"] += 1
                if state["deletes"] == 1 and state["reads"] == 2:
                    state["row"]["auditState"] = 1
                if state["deletes"] == 2 and state["reads"] == 4:
                    state["row"]["auditState"] = 1
                return {"status":"ok","result":{"versionList":[dict(state["row"])],"total":1}}
            raise AssertionError(path)
        provider = Blackbox({"verify_attempts":1,"delete_settle_seconds":0.001}, transport)
        with self.assertRaises(FuploadError) as raised:
            provider.version_delete({"module_id":7,"version_id":9})
        self.assertEqual(raised.exception.kind,"verification_required")
        self.assertEqual(state["deletes"],1)

    def test_version_edit_preserves_archive_and_normalizes_readback_types(self):
        calls = []
        row = {"id":"9","name":"old","type":"1","gameVersions":"1.0,2.0","fileUrlHeybox":"https://cdn.example/archive.zip"}
        def transport(method,path,body,query):
            if path.endswith("module_version/list/"): return {"status":"ok","result":{"versionList":[dict(row)],"total":1}}
            if path.endswith("module_version/upsert/"):
                calls.append(dict(body)); row.update(body); row["gameVersions"]=body["gameVersions"].split(","); return {"status":"ok","result":{"versionId":9}}
            raise AssertionError(path)
        result=Blackbox({"verify_attempts":1},transport).version_upsert({"module_id":7,"version_id":9,"name":"new","type":2,"game_versions":["2.0","1.0"]})
        self.assertTrue(result["verified"])
        self.assertEqual(calls[0]["fileUrl"],"https://cdn.example/archive.zip")

    def test_create_readback_excludes_preexisting_same_name(self):
        rows=[{"id":1,"name":"same","type":1,"gameVersions":["1.0"],"fileUrlHeybox":"https://old"}]
        def transport(method,path,body,query):
            if path.endswith("module_version/list/"): return {"status":"ok","result":{"versionList":[dict(x) for x in rows],"total":len(rows)}}
            if path.endswith("module_version/upsert/"):
                rows.append({"id":2,**body,"gameVersions":body["gameVersions"].split(","),"fileUrlHeybox":body["fileUrl"]}); return {"status":"ok","result":{}}
            raise AssertionError(path)
        result=Blackbox({"verify_attempts":1},transport).version_upsert({"module_id":7,"name":"same","type":1,"game_versions":["1.0"],"file_url":"https://new"})
        self.assertEqual(result["version_id"],2)

    def test_recursive_redaction_covers_credentials_devices_and_signed_urls(self):
        value=Blackbox._redact({"nested":[{"user_pkey":"p","device_id":"d","Credentials":{"Token":"t"},"url":"https://cos.example/a.zip?q-signature=s&q-key-time=t"}]})
        row=value["nested"][0]
        self.assertEqual(row["user_pkey"],"<redacted>")
        self.assertEqual(row["device_id"],"<redacted>")
        self.assertEqual(row["Credentials"],"<redacted>")
        self.assertEqual(row["url"],"https://cos.example/a.zip?<redacted>")

    def test_empty_core_folder_projection_matches_an_empty_input_array(self):
        self.assertEqual(
            Blackbox._comparable("coreFolders", [""]),
            Blackbox._comparable("coreFolders", []),
        )

    def test_upload_uses_web_token_route_without_desktop_fallback(self):
        provider=Blackbox()
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / "addon.zip"
            import zipfile
            with zipfile.ZipFile(archive, "w") as output:
                output.writestr("Addon/Addon.toc", "## Interface: 110200")
            with patch.object(provider,"_upload_zip_legacy",return_value={"protocol":"legacy"}) as legacy:
                self.assertEqual(provider.upload_zip(7,str(archive))["protocol"],"legacy")
                legacy.assert_called_once()

    def test_version_readback_requires_the_requested_archive(self):
        row = {"id": 9, "name": "new", "type": 2, "gameVersions": ["1.0"], "fileUrlHeybox": "https://cdn.example/old.zip"}
        def transport(method, path, body, query):
            if path.endswith("module_version/list/"):
                return {"status": "ok", "result": {"versionList": [dict(row)], "total":1}}
            if path.endswith("module_version/upsert/"):
                return {"status": "ok", "result": {"versionId": 9}}
            raise AssertionError(path)
        provider = Blackbox({"verify_attempts": 1}, transport)
        with self.assertRaises(FuploadError) as raised:
            provider.version_upsert({"module_id": 7, "version_id": 9, "name": "new", "type": 2, "game_versions": ["1.0"], "file_url": "https://cdn.example/new.zip"})
        self.assertTrue(raised.exception.verification_required)

    def test_version_pagination_prevents_false_delete_confirmation(self):
        rows = [{"id": index, "auditState": 2} for index in range(1, 102)]
        def transport(method, path, body, query):
            if path.endswith("module_version/delete/"):
                return {"status": "ok", "result": {}}
            if path.endswith("module_version/list/"):
                offset, limit = query["offset"], query["limit"]
                return {"status": "ok", "result": {"versionList": [dict(row) for row in rows[offset:offset + limit]], "totalCount": len(rows)}}
            raise AssertionError(path)
        provider = Blackbox({"verify_attempts": 1, "delete_settle_seconds": 0}, transport)
        with self.assertRaises(FuploadError):
            provider.version_delete({"module_id": 7, "version_id": 101})

class VersionPaginationTests(unittest.TestCase):
    def provider(self, result_for_offset):
        offsets = []
        def transport(method, path, body, query):
            if path.endswith("/delete/"):
                return {"status": "ok", "result": {}}
            offsets.append(query["offset"])
            return {"status": "ok", "result": result_for_offset(query["offset"])}
        return Blackbox({"verify_attempts": 1, "delete_settle_seconds": 0}, transport), offsets

    def test_short_pages_advance_by_actual_rows_with_and_without_total(self):
        rows = [{"id": i} for i in range(1, 7)]
        for with_total in (True, False):
            provider, offsets = self.provider(lambda offset: {
                "versionList": rows[offset:offset + 2], **({"total": 6} if with_total else {})})
            self.assertEqual(provider._version_rows(7), rows)
            self.assertEqual(offsets, [0, 2, 4] if with_total else [0, 2, 4, 6])

    def test_short_page_cannot_hide_undeleted_target(self):
        rows = [{"id": i, "auditState": 2} for i in range(1, 102)]
        provider, offsets = self.provider(lambda offset: {"versionList": rows[offset:offset + 15], "total": 101})
        with self.assertRaises(FuploadError) as caught:
            provider.version_delete({"module_id": 7, "version_id": 101})
        self.assertTrue(caught.exception.verification_required)
        self.assertEqual(offsets, [0, 15, 30, 45, 60, 75, 90])

    def test_incomplete_or_malformed_lists_never_confirm_delete(self):
        for make_result in (
            lambda offset: {"versionList": [{"id": 1}] if not offset else [], "total": 2},
            lambda offset: {"versionList": [{"id": 1}], "total": 2},
            lambda offset: {"versionList": [{"id": 1}], "total": True},
            lambda offset: {"versionList": [{"id": 1}], "total": "2"},
            lambda offset: {"versionList": [{"id": 1}], "total": 2, "totalCount": 3},
            lambda offset: {"versionList": [{"id": 1}, {"id": 2}], "total": 1},
            lambda offset: {"versionList": None},
            lambda offset: {"versionList": [{"id": True}]},
            lambda offset: {"versionList": [None]},
            lambda offset: {"versionList": [{"id": offset + 1}], "total": 3 if not offset else 4},
        ):
            provider, _ = self.provider(make_result)
            with self.subTest(make_result=make_result), self.assertRaises(FuploadError) as caught:
                provider.version_delete({"module_id": 7, "version_id": 99})
            self.assertTrue(caught.exception.verification_required)

    def test_no_total_is_bounded_when_server_never_finishes(self):
        provider, offsets = self.provider(lambda offset: {"versionList": [{"id": offset + 1}]})
        provider.config["version_max_pages"] = 2
        with self.assertRaises(FuploadError):
            provider._version_rows(7)
        self.assertEqual(offsets, [0, 1])

class CanonicalArchiveTests(unittest.TestCase):
    INTAKE = "https://wow.max-c.com/wow/module/Temporary-123.zip"
    CANONICAL = "https://wow.max-c.com/wow/wow_module_file/wowretail/" + "a" * 32 + ".zip"

    def run_upsert(self, *, actual=None, intake=None, infos=None, existing=False, local=True, duplicate=False, returned_old_id=False, bad_id=None,
                   caller_url=False, source_url=None, source_id=None, source_module=None, duplicate_same_id=False, replace_file=False):
        old = {"id": 9, "name": "old", "type": 3, "gameVersions": ["12.1.7"], "fileUrlHeybox": self.CANONICAL}
        if source_url is not None: old["fileUrlHeybox"] = source_url
        if source_id is not None: old["id"] = source_id
        if source_module is not None: old["moduleId"] = source_module
        rows = [dict(old)] if existing or returned_old_id else []
        posts = []
        if infos is None:
            infos = [{"strappid": "wowretail", "gameVersions": ["12.1.7"]},
                     {"strappid": "wowclassicera", "gameVersions": ["1.15.9"]}]
        def transport(method, path, body, query):
            if path.endswith("module_version/list/"):
                return {"status": "ok", "result": {"versionList": [dict(row) for row in rows], "total":len(rows), "strappidInfos": infos}}
            if path.endswith("module_version/upsert/"):
                posts.append(dict(body))
                row = {"id": 9 if existing or returned_old_id else 10, "name": body["name"], "type": body["type"],
                       "gameVersions": body["gameVersions"].split(","), "fileUrlHeybox": actual or self.CANONICAL}
                if bad_id is not None:
                    row["id"] = bad_id
                rows[:] = [row]
                if duplicate:
                    rows.append({**row, "id": 11})
                if duplicate_same_id:
                    rows.append(dict(row))
                return {"status": "ok", "result": {"versionId": row["id"]}}
            raise AssertionError(path)
        provider = Blackbox({"verify_attempts": 1}, transport)
        doc = {"module_id": 7, "name": "new", "type": 3, "game_versions": ["12.1.7"]}
        if existing:
            doc["version_id"] = 9
            if caller_url:
                doc["file_url"] = self.CANONICAL
        elif not local:
            doc["file_url"] = self.INTAKE
        if local and (not existing or replace_file):
            doc["file"] = "/local/synthetic.zip"
        with patch.object(provider, "upload_zip", return_value={"url": intake or self.INTAKE, "protocol": "legacy", "bytes": 10, "sha256": "b" * 64}) as upload:
            try:
                result = provider.version_upsert(doc)
                return result, posts, upload.call_count
            except FuploadError as error:
                self.assertLessEqual(len(posts), 1)
                self.last_posts = posts
                raise error

    def test_local_upload_canonicalization_verifies_only_remote_metadata(self):
        result, posts, uploads = self.run_upsert()
        self.assertTrue(result["verified"])
        self.assertTrue(result["metadata_verified"])
        self.assertEqual(result["verification_scope"], "remote_metadata")
        self.assertEqual(result["archive_verification"]["mode"], "server_canonicalization")
        self.assertFalse(result["archive_verification"]["content_verified"])
        self.assertFalse(result["archive_verification"]["public_download_verified"])
        self.assertEqual(result["unverified_fields"], ["archive_bytes"])
        self.assertEqual(result["version_id"], 10)
        self.assertIn("canonical_branch", result["verified_fields"])
        self.assertEqual((len(posts), uploads), (1, 1))

    def test_existing_version_local_replacement_confirms_changed_official_archive(self):
        changed = self.CANONICAL.replace("a" * 32, "c" * 32)
        result, posts, uploads = self.run_upsert(existing=True, replace_file=True, actual=changed)
        self.assertEqual(result["version_id"], 9)
        self.assertEqual(posts[0]["versionId"], 9)
        self.assertEqual((uploads, len(posts)), (1, 1))
        self.assertEqual(result["archive_verification"]["mode"], "server_replacement_canonicalization")
        self.assertEqual(result["archive_verification"]["source"], "local_upload")
        self.assertEqual(result["archive_verification"]["source_archive_url"], self.CANONICAL)
        self.assertEqual(result["verification_scope"], "remote_metadata")
        self.assertFalse(result["archive_verification"]["content_verified"])
        self.assertEqual(result["unverified_fields"], ["archive_bytes"])

    def test_existing_replacement_rejects_stale_archive_wrong_identity_and_branch(self):
        changed = self.CANONICAL.replace("a" * 32, "c" * 32)
        for overrides in ({"actual": self.CANONICAL}, {"bad_id": 11}, {"duplicate_same_id": True},
                          {"source_id": 8}, {"source_module": 999}, {"infos": []},
                          {"actual": changed.replace("wowretail/", "wowclassicera/")},
                          {"actual": changed + "?sign=opaque"},
                          {"intake": "https://example.invalid/new.zip"},
                          {"source_url": "https://example.invalid/old.zip"}):
            with self.subTest(overrides=overrides), self.assertRaises(FuploadError) as caught:
                self.run_upsert(**{"existing": True, "replace_file": True, "actual": changed, **overrides})
            self.assertTrue(caught.exception.verification_required)

    def test_canonical_exception_never_applies_to_caller_supplied_file_url(self):
        with self.assertRaises(FuploadError) as caught:
            self.run_upsert(local=False)
        self.assertTrue(caught.exception.verification_required)

    def test_canonical_exception_requires_official_upload_intake_source(self):
        for intake in (self.INTAKE.replace("https:", "http:"), self.INTAKE.replace("wow.max-c.com", "example.invalid"),
                       self.INTAKE + "?signature=opaque", self.CANONICAL):
            with self.subTest(intake=intake), self.assertRaises(FuploadError):
                self.run_upsert(intake=intake, actual=self.CANONICAL.replace("a" * 32, "d" * 32))

    def test_new_local_upload_requires_a_positive_concrete_version_id(self):
        for identity in (True, 0, "not-an-id", ""):
            with self.subTest(identity=identity), self.assertRaises(FuploadError):
                self.run_upsert(bad_id=identity)

    def test_existing_caller_file_url_requires_exact_url_even_if_canonical(self):
        changed = self.CANONICAL.replace("a" * 32, "c" * 32)
        with self.assertRaises(FuploadError) as caught:
            self.run_upsert(existing=True, caller_url=True, actual=changed)
        self.assertTrue(caught.exception.verification_required)
        result, _, uploads = self.run_upsert(existing=True)
        self.assertEqual(result["archive_verification"]["mode"], "url_exact")
        self.assertFalse(result["archive_verification"]["content_verified"])
        self.assertEqual(uploads, 0)

    def test_existing_metadata_edit_recanonicalization_has_original_record_provenance(self):
        changed = self.CANONICAL.replace("a" * 32, "c" * 32)
        result, posts, uploads = self.run_upsert(existing=True, actual=changed)
        self.assertEqual(result["archive_verification"]["mode"], "server_recanonicalization")
        self.assertEqual(result["archive_verification"]["source"], "existing_version_record")
        self.assertEqual(result["archive_verification"]["source_module_id"], 7)
        self.assertEqual(result["archive_verification"]["source_version_id"], 9)
        self.assertEqual(result["archive_verification"]["source_archive_url"], self.CANONICAL)
        self.assertEqual(posts[0]["fileUrl"], self.CANONICAL)
        self.assertEqual(result["readback"]["fileUrlHeybox"], changed)
        self.assertTrue(result["metadata_verified"])
        self.assertEqual(result["verification_scope"], "remote_metadata")
        self.assertFalse(result["archive_verification"]["content_verified"])
        self.assertEqual(result["unverified_fields"], ["archive_bytes"])
        self.assertEqual(uploads, 0)

    def test_metadata_recanonicalization_rejects_wrong_identity_source_branch_and_duplicates(self):
        changed = self.CANONICAL.replace("a" * 32, "c" * 32)
        bad = [{"source_id": 8}, {"source_module": 999}, {"bad_id": 11},
               {"source_url": "https://example.invalid/unknown.zip"},
               {"source_url": self.CANONICAL.replace("wowretail/", "wowclassicera/")},
               {"actual": changed.replace("wowretail/", "wowclassicera/")},
               {"actual": changed.replace("wow.max-c.com", "example.invalid")},
               {"duplicate_same_id": True}, {"infos": []}]
        for kwargs in bad:
            params = {"existing": True, "actual": changed, **kwargs}
            with self.subTest(params=params), self.assertRaises(FuploadError):
                self.run_upsert(**params)

    def test_duplicate_original_source_records_prevent_metadata_write(self):
        row = {"id": 9, "name": "old", "gameVersions": ["12.1.7"], "fileUrlHeybox": self.CANONICAL}
        writes = []
        def transport(method, route, body, query):
            if method == "POST": writes.append(body)
            return {"status": "ok", "result": {"versionList": [dict(row), dict(row)]}}
        with self.assertRaises(FuploadError) as caught:
            Blackbox({"verify_attempts": 1}, transport).version_upsert({"module_id": 7, "version_id": 9, "name": "new", "type": 3, "game_versions": ["12.1.7"]})
        self.assertTrue(caught.exception.verification_required)
        self.assertEqual(writes, [])

    def test_canonical_origin_path_and_game_branch_are_strict(self):
        bad = [self.CANONICAL.replace("https:", "http:"), self.CANONICAL.replace("wow.max-c.com", "example.invalid"),
               self.CANONICAL + "?token=opaque", self.CANONICAL.replace("wowretail/", "wowclassicera/"),
               self.CANONICAL.replace("wow.max-c.com", "wow.max-c.com:443"),
               self.CANONICAL.replace("a" * 32, "not-a-digest")]
        for url in bad:
            with self.subTest(url=url), self.assertRaises(FuploadError) as caught:
                self.run_upsert(actual=url)
            self.assertTrue(caught.exception.verification_required)

    def test_canonicalization_requires_unambiguous_current_branch_options(self):
        for infos in ([], [{"strappid": "wowretail", "gameVersions": ["other"]}],
                      [{"strappid": "wowretail", "gameVersions": ["12.1.7"]}, {"strappid": "wowclassicera", "gameVersions": ["12.1.7"]}]):
            with self.subTest(infos=infos), self.assertRaises(FuploadError):
                self.run_upsert(infos=infos)

    def test_canonicalization_rejects_duplicate_matches_and_reused_version_id(self):
        for kwargs in ({"duplicate": True}, {"returned_old_id": True}):
            with self.subTest(kwargs=kwargs), self.assertRaises(FuploadError) as caught:
                self.run_upsert(**kwargs)
            self.assertTrue(caught.exception.verification_required)


if __name__ == "__main__": unittest.main()
