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
            if path.endswith("module_version/list/"): return {"status":"ok","result":{"versionList":state["versions"]}}
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
                return {"status": "ok", "result": {"versionList": [dict(state["row"])]}}
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
                return {"status":"ok","result":{"versionList":[dict(state["row"])]}}
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
            if path.endswith("module_version/list/"): return {"status":"ok","result":{"versionList":[dict(row)]}}
            if path.endswith("module_version/upsert/"):
                calls.append(dict(body)); row.update(body); row["gameVersions"]=body["gameVersions"].split(","); return {"status":"ok","result":{"versionId":9}}
            raise AssertionError(path)
        result=Blackbox({"verify_attempts":1},transport).version_upsert({"module_id":7,"version_id":9,"name":"new","type":2,"game_versions":["2.0","1.0"]})
        self.assertTrue(result["verified"])
        self.assertEqual(calls[0]["fileUrl"],"https://cdn.example/archive.zip")

    def test_create_readback_excludes_preexisting_same_name(self):
        rows=[{"id":1,"name":"same","type":1,"gameVersions":["1.0"],"fileUrlHeybox":"https://old"}]
        def transport(method,path,body,query):
            if path.endswith("module_version/list/"): return {"status":"ok","result":{"versionList":[dict(x) for x in rows]}}
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
                return {"status": "ok", "result": {"versionList": [dict(row)]}}
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

if __name__ == "__main__": unittest.main()
