from __future__ import annotations

import sys
import unittest
import json
import tempfile
from unittest.mock import patch
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fupload_cli.blackbox import API_MISC_BASE, Blackbox
from fupload_cli.blackbox_auth import _CONFIG_AES_KEY, _decrypt_user_pkey, hkey, load_session

class BlackboxProviderTests(unittest.TestCase):
    def test_client_request_contains_current_identity_and_signed_timestamp(self):
        captured = {}
        class Response:
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def read(self): return b'{"status":"ok","result":{}}'
        def fake_urlopen(request, timeout):
            from urllib.parse import parse_qs, urlparse
            captured["query"] = parse_qs(urlparse(request.full_url).query)
            captured["method"] = request.method
            captured["body"] = request.data
            return Response()
        provider = Blackbox()
        with patch("fupload_cli.blackbox.load_session", return_value=(
            {"user_heybox_id": "42", "user_pkey": "pkey", "x_xhh_tokenid": "risk"},
            {"x_client_type": "pc", "x_os_type": "Windows", "x_app": "heybox_pc", "version": "1.14.1", "exe_version": "1.14.1", "os_version": "Windows", "device_id": "device", "heybox_id": "42"},
        )), patch("fupload_cli.blackbox.time.time", return_value=100), patch("fupload_cli.blackbox.secrets.token_hex", return_value="N"), patch("fupload_cli.blackbox.urlopen", side_effect=fake_urlopen), patch("fupload_cli.blackbox.hkey", return_value="signed") as sign:
            provider._request("GET", "/wow/open_platform/module/list/")
        self.assertEqual(captured["method"], "GET")
        self.assertEqual(captured["query"]["app"], ["heybox"])
        self.assertEqual(captured["query"]["x_app"], ["heybox_pc"])
        self.assertEqual(captured["query"]["version"], ["1.14.1"])
        sign.assert_called_once_with("/wow/open_platform/module/list/", 101, unittest.mock.ANY)

    def test_config_session_decrypts_encrypted_pkey(self):
        try:
            from Crypto.Cipher import AES
        except ImportError:
            self.skipTest("Crypto is not installed in the test interpreter")
        from Crypto.Util.Padding import pad
        iv = bytes(range(16))
        plaintext = b"fixture-pkey"
        encrypted = AES.new(_CONFIG_AES_KEY, AES.MODE_CBC, iv).encrypt(pad(plaintext, 16))
        encoded = iv.hex() + ":" + encrypted.hex()
        self.assertEqual(_decrypt_user_pkey(encoded), plaintext.decode())
        with tempfile.TemporaryDirectory() as tmp:
            profile = Path(tmp)
            (profile / "sentry").mkdir()
            (profile / "config.json").write_text(json.dumps({
                "cookies": [{"name": "user_pkey", "value": encoded}],
                "account": {"heybox_id": "42"},
                "acc_config": {"xhh_token_id": "risk"},
            }), encoding="utf-8")
            cookies, identity = load_session(profile)
            self.assertEqual(cookies["user_pkey"], "fixture-pkey")
            self.assertEqual(identity["version"], "1.14.1")

    def test_v2_upload_requests_use_json_body(self):
        captured = {}
        class Response:
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def read(self): return b'{"status":"ok","result":{"keys":["k"],"bucket":"b"}}'
        def fake_urlopen(request, timeout):
            captured["content_type"] = request.headers["Content-type"]
            captured["body"] = json.loads(request.data.decode())
            return Response()
        provider = Blackbox()
        with patch("fupload_cli.blackbox.load_session", return_value=(
            {"user_heybox_id": "42", "user_pkey": "pkey", "x_xhh_tokenid": "risk"},
            {"x_client_type": "pc", "x_os_type": "Windows", "x_app": "heybox_pc", "version": "1.14.1", "exe_version": "1.14.1", "os_version": "Windows", "device_id": "device", "heybox_id": "42"},
        )), patch("fupload_cli.blackbox.time.time", return_value=100), patch("fupload_cli.blackbox.secrets.token_hex", return_value="N"), patch("fupload_cli.blackbox.urlopen", side_effect=fake_urlopen):
            provider._request("POST", "/bbs/app/api/qcloud/cos/upload/info/v2", base=API_MISC_BASE, body={"file_infos": "[]", "scope": "any", "need_cache": 0})
        self.assertEqual(captured["content_type"], "application/json;charset=utf-8")
        self.assertEqual(captured["body"], {"file_infos": "[]", "scope": "any", "need_cache": 0})

    def test_read_and_mutations_use_workshop_routes(self):
        state = {"module": {"id": 7, "name": "taptool"}, "versions": []}
        def transport(method, path, body, query):
            if path.endswith("module/list/"): return {"status":"ok","result":{"moduleList":[state["module"]]}}
            if path.endswith("module/detail/"): return {"status":"ok","result":{"module":state["module"]}}
            if path.endswith("module/update/"): state["module"].update(body); return {"status":"ok","result":{}}
            if path.endswith("module_version/list/"): return {"status":"ok","result":{"versionList":state["versions"]}}
            if path.endswith("module_version/upsert/"):
                row={**body,"id":body.get("versionId",9),"gameVersions":body["gameVersions"].split(","),"fileUrlHeybox":body["fileUrl"]}; state["versions"]=[row]; return {"status":"ok","result":{}}
            if path.endswith("module_version/delete/"): state["versions"]=[]; return {"status":"ok","result":{}}
            raise AssertionError(path)
        provider = Blackbox({"verify_attempts": 1, "delete_settle_seconds": 0}, transport)
        self.assertEqual(provider.plugin_list()["total_count"], 1)
        self.assertTrue(provider.execute_write("plugin", "edit", {"id":7,"name":"changed"})["verified"])
        self.assertTrue(provider.execute_write("version", "create", {"module_id":7,"name":"v","type":3,"game_versions":["1.0"],"file_url":"https://x"})["verified"])
        self.assertTrue(provider.execute_write("version", "delete", {"module_id":7,"version_id":9})["verified"])

    def test_version_delete_retries_when_deleted_row_reactivates(self):
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
        result = provider.version_delete({"module_id": 7, "version_id": 9})
        self.assertTrue(result["retry"])
        self.assertEqual(state["deletes"], 2)

if __name__ == "__main__": unittest.main()
