from __future__ import annotations

import base64
from copy import deepcopy
from email.message import Message
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fupload_cli.blackbox_http import (
    API, WORKSHOP, LOGIN, SCHEMA, BlackboxHttpSession, HttpClient, HttpResponse,
    Store, apply_session, identity, sign, load_device_risk_token, protect, unprotect,
)
from fupload_cli.errors import FuploadError


def session(method="sms", uid="123", pkey="test-key"):
    now = int(time.time())
    result = {"profile": {"heybox_id": uid}, "pkey": pkey, "expire_at": now + 3600}
    value = {"cookies": [], "method": method, "device_id": "device-fixture", "web_version": "fixture"}
    return apply_session(value, result, now=now)


def seal(value):
    return b"SEALED:" + base64.b64encode(value)


def unseal(value):
    if not value.startswith(b"SEALED:"):
        raise ValueError("bad ciphertext")
    return base64.b64decode(value[7:])


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.store = Store(self.root, encrypt=seal, decrypt=unseal)

    def tearDown(self):
        self.temp.cleanup()

    def test_roundtrip_strips_risk_and_oauth_secrets(self):
        value = session()
        value["cookies"].append({"name": "x_xhh_tokenid", "value": "risk", "domain": ".xiaoheihe.cn", "path": "/", "secure": True, "expires": None})
        value["oauth_code"] = "must-not-save"
        self.store.save_session(value)
        saved = self.store.load_active()
        self.assertEqual(identity(saved), "123")
        self.assertEqual(len(saved["cookies"]), 4)
        self.assertNotIn("oauth_code", saved)
        for p in self.root.rglob("*.dpapi"):
            self.assertTrue(p.read_bytes().startswith(b"SEALED:"))
            self.assertNotIn(b"test-key", p.read_bytes())
        self.assertFalse(list(self.root.rglob("*.tmp")))

    def test_legacy_sms_wins_and_migration_waits_for_server_expiry(self):
        for name, method in [("blackbox-http-session.dpapi", "sms"), ("blackbox-wechat-session.dpapi", "wechat")]:
            value = session(method, "123" if method == "sms" else "456")
            value.update(schema="fupload.blackbox.http-session.v1")
            value.pop("expire_at")
            (self.root / name).write_bytes(seal(json.dumps(value).encode()))
        value = self.store.load_active()
        self.assertEqual(identity(value), "123")
        self.assertNotIn("expire_at", value)
        self.assertFalse((self.store.directory / "sms.dpapi").exists())
        self.store.select_active("wechat")
        self.assertEqual(identity(self.store.load_active()), "456")

    def test_pending_is_separate_expires_and_does_not_overwrite_active(self):
        self.store.save_session(session())
        pending = {"login_id": "pending", "method": "wechat", "expires_at": time.time() + 60,
                   "cookies": [], "state": "private-state"}
        self.store.save_pending(pending)
        self.assertEqual(self.store.load_pending()["state"], "private-state")
        self.assertEqual(identity(self.store.load_active()), "123")
        self.store.now = lambda: time.time() + 120
        self.assertIsNone(self.store.load_pending())
        self.assertFalse((self.store.directory / "pending.dpapi").exists())

    def test_forget_never_reimports_legacy(self):
        value = session()
        value["schema"] = "fupload.blackbox.http-session.v1"
        (self.root / "blackbox-http-session.dpapi").write_bytes(seal(json.dumps(value).encode()))
        self.store.forget_active()
        self.assertIsNone(self.store.load_active())

    def test_corrupt_ciphertext_fails_without_plaintext_or_ciphertext_in_error(self):
        self.store.directory.mkdir()
        (self.store.directory / "active.dpapi").write_bytes(b"credential-leak-fixture")
        with self.assertRaises(FuploadError) as caught:
            self.store.load_active()
        self.assertNotIn("credential-leak-fixture", str(caught.exception))

    def test_lock_is_reentrant_and_excludes_other_commands(self):
        other = Store(self.root, encrypt=seal, decrypt=unseal)
        with self.store.lock():
            with self.store.lock():
                with self.assertRaises(FuploadError) as caught:
                    with other.lock():
                        self.fail("concurrent auth acquired lock")
                self.assertEqual(caught.exception.kind, "authentication_busy")
        with other.lock():
            pass

    def test_atomic_replace_failure_preserves_previous_ciphertext(self):
        self.store.save_session(session())
        target = self.store.directory / "sms.dpapi"
        before = target.read_bytes()
        with patch("fupload_cli.blackbox_http.os.replace", side_effect=OSError("disk error")):
            with self.assertRaises(OSError):
                self.store.save_session(session(pkey="new-value"))
        self.assertEqual(target.read_bytes(), before)
        self.assertFalse(list(target.parent.glob("*.tmp")))


class ProtocolTests(unittest.TestCase):
    def test_signature_matches_installed_21019_js_vectors(self):
        # Computed by executing Wrn from the shipped client JS, not this module.
        self.assertEqual(sign("/account/restore_login", 1700000000, "A" * 32), "T3IS037")
        self.assertEqual(sign("/wow/v2/share/list/", 1700000000, "A" * 32), "3VXIS16")

    def test_json_wire_origin_query_form_and_cookie_scope(self):
        seen = []
        def transport(request, **kw):
            seen.append(request)
            return HttpResponse(200, {}, b'{"status":"ok","result":{}}')
        client, value = HttpClient(transport=transport), session()
        client.request("/account/login_code/", "POST", query={"code": "1234"}, body={"phone_num": "rsa+/="}, session=value)
        req = seen[-1]
        self.assertEqual(urlsplit(req.full_url).netloc, "api.xiaoheihe.cn")
        self.assertEqual(parse_qs(urlsplit(req.full_url).query)["code"], ["1234"])
        self.assertEqual(req.data, b"phone_num=rsa%2B%2F%3D")
        self.assertIn("pkey=test-key", req.get_header("Cookie"))
        client.request("/wow/v2/share/list/", "POST", session=value)
        self.assertTrue(seen[-1].full_url.startswith(WORKSHOP + "/"))

    def test_oauth_fixed_paths_redirect_not_followed_and_cross_domain_cookie_isolated(self):
        requests = []
        def transport(request, **kw):
            requests.append(request)
            return HttpResponse(302, {"Location": "https://attacker.invalid/steal"}, b"")
        client = HttpClient(transport=transport)
        response = client.fetch("https://open.weixin.qq.com/connect/qrconnect?state=test", session())
        self.assertEqual(response.status, 302)
        self.assertEqual(len(requests), 1)
        self.assertIsNone(requests[0].get_header("Cookie"))
        for url in ["http://open.weixin.qq.com/connect/qrconnect", "https://open.weixin.qq.com:444/connect/qrconnect",
                    "https://api.xiaoheihe.cn/anything", "https://open.weixin.qq.com/connect/qrcode/../private",
                    "https://open.weixin.qq.com.attacker.invalid/connect/qrconnect"]:
            with self.subTest(url=url), self.assertRaises(FuploadError):
                client.fetch(url, session())
        self.assertEqual(len(requests), 1)

    def test_refuses_platform_override_and_unknown_route_before_send(self):
        client = HttpClient(transport=lambda *a, **k: self.fail("request sent"))
        for kwargs in [{"route": "/account/logout"}, {"route": "/account/restore_login", "query": {"hkey": "custom"}},
                       {"route": "/wow/v2/share/list/", "method": "GET"}]:
            with self.assertRaises(FuploadError):
                client.request(session=session(), **kwargs)

    def test_cookie_tampering_duplicate_alias_scope_and_crlf_rejected(self):
        for mutate in [lambda v: v["cookies"].append(deepcopy(v["cookies"][0])),
                       lambda v: v["cookies"][0].update(value="456"),
                       lambda v: v["cookies"][0].update(value="header\r\ninject"),
                       lambda v: v["cookies"][0].update(domain="attacker.invalid")]:
            v = session()
            mutate(v)
            with self.assertRaises(FuploadError):
                identity(v)

    def test_transport_set_cookie_is_carried_to_next_request(self):
        headers = Message()
        headers.add_header("Set-Cookie", "oauth=fixture; Domain=.xiaoheihe.cn; Path=/; Secure")
        client = HttpClient(transport=lambda *a, **k: HttpResponse(200, headers, b'{"status":"ok"}'))
        value = {"cookies": []}
        client.request("/account/restore_login", session=value)
        self.assertEqual(value["cookies"][0]["name"], "oauth")

    def test_failed_post_is_never_retried_and_url_is_not_exposed(self):
        count = 0
        def transport(*a, **k):
            nonlocal count
            count += 1
            raise OSError("https://api.xiaoheihe.cn/?code=otp-secret&pkey=private-key")
        with self.assertRaises(FuploadError) as caught:
            HttpClient(transport=transport).request("/account/login_code/", "POST", query={"code": "otp-secret"}, session={"cookies": []})
        self.assertEqual(count, 1)
        self.assertTrue(caught.exception.verification_required)
        self.assertNotIn("otp-secret", str(caught.exception))
        self.assertNotIn("private-key", str(caught.exception))


class RenewalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.temp.name), encrypt=seal, decrypt=unseal)
        self.store.save_session(session())
        self.before = (self.store.directory / "sms.dpapi").read_bytes()

    def tearDown(self):
        self.temp.cleanup()

    def adapter(self, result, business_status="ok"):
        calls = []
        def transport(req, **kw):
            path = urlsplit(req.full_url).path
            calls.append(path)
            payload = result if path == "/account/restore_login" else {"status": business_status, "result": {"items": []}}
            return HttpResponse(200, {}, json.dumps(payload).encode())
        return BlackboxHttpSession(store=self.store, client=HttpClient(transport=transport)), calls

    def test_restore_once_before_business_and_persist_server_expiry(self):
        expiry = int(time.time()) + 7200
        adapter, calls = self.adapter({"status": "ok", "result": {"profile": {"heybox_id": "123"}, "pkey": "rotated", "expire_at": expiry}})
        for _ in range(2):
            adapter.request("GET", "/wow/open_platform/module/list/")
        self.assertEqual(calls.count("/account/restore_login"), 1)
        saved = self.store.load_active()
        self.assertEqual(saved["expire_at"], expiry)
        self.assertEqual({r["value"] for r in saved["cookies"] if r["name"] == "pkey"}, {"rotated"})

    def test_identity_change_or_missing_expiry_blocks_all_business_and_preserves_store(self):
        for result in [{"profile": {"heybox_id": "456"}, "pkey": "other", "expire_at": int(time.time()) + 1000},
                       {"profile": {"heybox_id": "123"}, "pkey": "same"}]:
            adapter, calls = self.adapter({"status": "ok", "result": result})
            with self.assertRaises(FuploadError):
                adapter.request("POST", "/wow/create_backup/")
            self.assertEqual(calls, ["/account/restore_login"])
            self.assertEqual((self.store.directory / "sms.dpapi").read_bytes(), self.before)

    def test_expired_restore_returns_login_required_never_sends_sms_or_business(self):
        adapter, calls = self.adapter({"status": "relogin"})
        with self.assertRaises(FuploadError) as caught:
            adapter.request("POST", "/wow/create_backup/")
        self.assertEqual(caught.exception.kind, "login_required")
        self.assertEqual(calls, ["/account/restore_login"])

    def test_malformed_identity_payload_is_protocol_error_without_session_mutation(self):
        for malformed in ({"profile": "not-an-object"}, {"account_detail": ["not-an-object"]}):
            value = session()
            before = deepcopy(value)
            with self.assertRaises(FuploadError):
                apply_session(value, {**malformed, "pkey": "server-key", "expire_at": int(time.time()) + 1000})
            self.assertEqual(value, before)

    def test_business_relogin_does_not_replay_the_post(self):
        adapter, calls = self.adapter({"status": "ok", "result": {"profile": {"heybox_id": "123"}, "pkey": "new", "expire_at": int(time.time()) + 1000}}, "relogin")
        with self.assertRaises(FuploadError) as caught:
            adapter.request("POST", "/wow/create_backup/")
        self.assertEqual(caught.exception.kind, "login_required")
        self.assertEqual(calls, ["/account/restore_login", "/wow/create_backup/"])


class DeviceTests(unittest.TestCase):
    def test_only_fixed_device_field_is_used(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "heybox-pc-launcher").mkdir()
            path = root / "heybox-pc-launcher/config.json"
            for value, expected in [("B" + "a" * 88, True), ("D" + "a" * 88, False), ("B" + "a" * 87 + "\n", False)]:
                path.write_text(json.dumps({"acc_config": {"xhh_token_id": value}, "account": "must-ignore", "cookies": []}))
                with patch("fupload_cli.trust._known_folder_roaming", return_value=root):
                    self.assertEqual(load_device_risk_token() is not None, expected)

    @unittest.skipUnless(os.name == "nt", "CurrentUser DPAPI is Windows-only")
    def test_real_current_user_dpapi_local_roundtrip(self):
        value = b"public-fixture-not-a-credential"
        ciphertext = protect(value)
        self.assertNotEqual(ciphertext, value)
        self.assertEqual(unprotect(ciphertext), value)


if __name__ == "__main__":
    unittest.main()
