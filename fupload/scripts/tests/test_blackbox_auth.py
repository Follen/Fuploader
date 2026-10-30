"""All authentication/network operations below are mocked; no SMS/QR is requested."""
from __future__ import annotations

import base64
from contextlib import contextmanager
from copy import deepcopy
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
import urllib.parse

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fupload_cli.blackbox_auth import BlackboxAuth, PENDING_TTL, _rsa_blob, encrypt_phone
from fupload_cli.blackbox_http import API, LOGIN, IDENTITY_COOKIES, HttpResponse, Store
from fupload_cli.errors import FuploadError, ValidationError


def response(status="ok", result=None, **extra):
    return {"status": status, "result": result or {}, **extra}


def login_result(uid="1234", **extra):
    return {"profile": {"heybox_id": uid}, "pkey": "SENSITIVE-PKEY", "expire_at": 2000, **extra}


def verifies():
    return [response(result={"moduleList": []}), response(result={"backupList": []})]


class MemoryStore:
    def __init__(self, directory, now):
        self.directory, self.now = directory, now
        self.pending, self.active, self.saved = None, None, []
        self.forgotten = False
        self.lock_depth = 0

    @contextmanager
    def lock(self):
        self.lock_depth += 1
        try: yield
        finally: self.lock_depth -= 1

    def load_pending(self):
        if self.pending is not None and self.pending["expires_at"] <= self.now():
            self.pending = None
        return deepcopy(self.pending)

    def save_pending(self, value):
        assert self.lock_depth, "pending writes must be serialized"
        self.pending = deepcopy(value)
        assert all(row["name"] != "x_xhh_tokenid" for row in value.get("cookies", [])), "risk token must stay memory-only"

    def delete_pending(self): self.pending = None
    def load_active(self): return deepcopy(self.active)
    def forget_active(self): self.active, self.forgotten = None, True

    def save_session(self, value):
        assert self.lock_depth, "session activation must be serialized"
        value = deepcopy(value)
        value["cookies"] = [row for row in value["cookies"] if row["name"] in IDENTITY_COOKIES]
        self.saved.append(value)
        self.active = value


class FakeClient:
    def __init__(self):
        self.fetches, self.requests, self.calls = [], [], []

    def fetch(self, url, session, timeout=35):
        self.calls.append(("fetch", url, {"timeout": timeout, "session": deepcopy(session)}))
        if not self.fetches: raise AssertionError("unexpected fetch")
        value = self.fetches.pop(0)
        if isinstance(value, Exception): raise value
        return value(url, session) if callable(value) else value

    def request(self, route, method="GET", *, query=None, body=None, session, timeout=30):
        self.calls.append(("request", route, {"method": method, "query": deepcopy(query), "body": deepcopy(body), "session": deepcopy(session), "timeout": timeout}))
        if not self.requests: raise AssertionError("unexpected request")
        value = self.requests.pop(0)
        if isinstance(value, Exception): raise value
        return value(route, method, session) if callable(value) else value


class BlackboxAuthTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.clock = 1000
        self.store = MemoryStore(Path(self.temp.name), lambda: self.clock)
        self.client = FakeClient()
        self.encrypt_calls = []
        def encrypt(phone):
            self.encrypt_calls.append(phone)
            return "ENCRYPTED-PHONE-FIXTURE"
        self.auth = BlackboxAuth(store=self.store, client=self.client, now=lambda: self.clock,
                                 phone_encryptor=encrypt, device_risk_loader=lambda: "B" + "x" * 88)

    def sms(self, sent=None):
        self.client.fetches.append(HttpResponse(200, {}, b'<meta content="test-web" name="web_version">'))
        self.client.requests.append(sent or response())
        return self.auth.login_start({"method": "sms", "phone": "13800000000"})

    def wechat(self, oauth=None, uuid="QR-FIXTURE-123"):
        callback = API + "/account/wechat/login_redirect/v2/web_sso/?source=heybox_open"
        oauth = oauth or "https://open.weixin.qq.com/connect/qrconnect?" + urllib.parse.urlencode({"appid": "official-app", "redirect_uri": callback, "state": "SENSITIVE-OAUTH-STATE"})
        page = ('<img src="/connect/qrcode/' + uuid + '"><script>var fordevtool = "https://long.open.weixin.qq.com/connect/l/qrconnect?uuid=' + uuid + '";</script>').encode()
        self.client.fetches.extend([HttpResponse(200, {}, b"login"), HttpResponse(302, {"Location": oauth}, b""), HttpResponse(200, {}, page), HttpResponse(200, {}, b"\x89PNG\r\n\x1a\nfixture")])
        return self.auth.login_start({"method": "wechat"})

    def prior_session(self):
        self.store.active = {"method": "sms", "identity": "777", "device_id": "old-device", "web_version": "old-web", "expire_at": 1900,
                             "cookies": [{"name": name, "value": "777" if "heybox_id" in name else "OLD-PKEY", "domain": ".xiaoheihe.cn", "path": "/", "secure": True, "expires": 1900} for name in IDENTITY_COOKIES]}
        return deepcopy(self.store.active)

    def test_sms_start_sends_once_reserves_pending_and_never_exposes_phone(self):
        started = self.sms()
        self.assertEqual((started["status"], started["sms_sent"], started["expires_in"]), ("waiting_code", True, PENDING_TTL))
        self.assertRegex(started["login_id"], r"^[a-f0-9]{32}$")
        self.assertEqual(self.store.pending["phone_encrypted"], "ENCRYPTED-PHONE-FIXTURE")
        request = self.client.calls[-1]
        self.assertEqual(request[:2], ("request", "/account/get_login_code/"))
        self.assertEqual(request[2]["body"], {"phone_num": "ENCRYPTED-PHONE-FIXTURE"})
        self.assertEqual(request[2]["session"]["status"], "sms_sending")
        self.assertTrue(any(row["name"] == "x_xhh_tokenid" for row in request[2]["session"]["cookies"]))
        self.assertEqual(self.encrypt_calls, ["13800000000"])
        self.assertNotIn("13800000000", json.dumps(started))
        self.assertNotIn("ENCRYPTED", json.dumps(started))
        with self.assertRaises(FuploadError) as error: self.auth.login_start({"method": "sms", "phone": "13900000000"})
        self.assertEqual(error.exception.kind, "login_in_progress")
        self.assertEqual(len(self.client.calls), 2)

    def test_sms_status_never_sends_or_resubmits(self):
        started = self.sms()
        count = len(self.client.calls)
        self.assertEqual(self.auth.login_status(started["login_id"])["status"], "waiting_code")
        self.assertEqual(len(self.client.calls), count)

    def test_bad_input_caller_credentials_and_wechat_phone_are_rejected_locally(self):
        for doc in ({"method": "sms", "phone": "123"}, {"method": "sms", "phone": "13800000000", "token": "external"}, {"method": "wechat", "phone": "13800000000"}, {"method": "wechat", "url": "https://evil.invalid"}):
            with self.subTest(doc=doc), self.assertRaises(ValidationError): self.auth.login_start(doc)
        self.assertEqual(self.client.calls, [])

    def test_risk_and_captcha_rejection_are_explicit_without_resend(self):
        for status, expected in (("show_captcha", "captcha_required"), ("lack_token", "device_verification_required")):
            with self.subTest(status=status):
                self.store.pending = None
                started = self.sms(response(status, msg="private phone or token diagnostics"))
                self.assertEqual(started["status"], expected)
                self.assertFalse(started["sms_sent"])
                self.assertFalse(started["automatic_retry"])
                self.assertNotIn("private", json.dumps(started))

    def test_missing_local_risk_field_still_makes_only_one_explicit_send(self):
        self.auth.device_risk_loader = lambda: None
        started = self.sms(response("lack_token"))
        self.assertEqual(started["status"], "device_verification_required")
        self.assertFalse(any(row["name"] == "x_xhh_tokenid" for row in self.client.calls[-1][2]["session"]["cookies"]))

    def test_uncertain_send_keeps_one_pending_and_does_not_resend(self):
        self.client.fetches.append(HttpResponse(200, {}, b"login"))
        self.client.requests.append(FuploadError("private URL and phone", kind="network_error"))
        with self.assertRaises(FuploadError) as failure: self.auth.login_start({"method": "sms", "phone": "13800000000"})
        self.assertTrue(failure.exception.verification_required)
        self.assertNotIn("private", json.dumps(failure.exception.as_dict()))
        self.assertEqual(self.store.pending["status"], "sms_send_uncertain")
        with self.assertRaises(FuploadError): self.auth.login_start({"method": "sms", "phone": "13800000000"})
        self.assertEqual(len([c for c in self.client.calls if c[0] == "request"]), 1)

    def test_sms_submit_preserves_leading_zeros_and_activates_only_after_verification(self):
        previous = self.prior_session()
        started = self.sms()
        self.assertEqual(self.store.active, previous)
        self.client.requests.extend([response(result=login_result()), *verifies()])
        completed = self.auth.login_submit({"login_id": started["login_id"], "code": "001234"})
        submit = next(call for call in self.client.calls if call[1] == "/account/login_code/")
        self.assertEqual(submit[2]["query"], {"code": "001234"})
        self.assertTrue(completed["authenticated"])
        self.assertEqual(self.store.active["identity"], "1234")
        self.assertEqual({c["name"] for c in self.store.active["cookies"]}, IDENTITY_COOKIES)
        self.assertIsNone(self.store.pending)
        self.assertNotIn("001234", json.dumps(completed))
        self.assertNotIn("SENSITIVE", json.dumps(completed))
        self.assertEqual(len([c for c in self.client.calls if c[1] == "/account/get_login_code/"]), 1)

    def test_sms_without_expiry_restores_official_expiry_before_persistence(self):
        started = self.sms()
        initial = login_result()
        initial.pop("expire_at")
        self.client.requests.extend([response(result=initial), response(result=login_result()), *verifies()])
        completed = self.auth.login_submit({"login_id": started["login_id"], "code": "001234"})
        self.assertEqual(completed["expires_at"], 2000)
        self.assertEqual([c[1] for c in self.client.calls if c[0] == "request"][1:3], ["/account/login_code/", "/account/restore_login"])

    def test_lost_restore_checkpoints_consumed_otp_credentials_and_never_reposts(self):
        previous = self.prior_session()
        started = self.sms()
        initial = login_result()
        initial.pop("expire_at")
        self.client.requests.extend([response(result=initial), FuploadError("lost restore response", kind="network_error")])
        with self.assertRaises(FuploadError): self.auth.login_submit({"login_id": started["login_id"], "code": "001234"})
        self.assertEqual(self.store.active, previous)
        self.assertEqual(self.store.saved, [])
        candidate = self.store.pending.get("candidate_session", {})
        self.assertEqual(candidate.get("identity"), "1234")
        self.assertEqual({row["name"] for row in candidate.get("cookies", [])}, IDENTITY_COOKIES)
        self.assertEqual(candidate.get("expire_at"), self.clock + PENDING_TTL)
        with self.assertRaises(FuploadError): self.auth.login_submit({"login_id": started["login_id"], "code": "001234"})
        self.assertEqual(len([call for call in self.client.calls if call[1] == "/account/login_code/"]), 1)
        self.client.requests.extend([response(result=login_result(expire_at=2100)), *verifies()])
        completed = self.auth.login_status(started["login_id"])
        self.assertEqual(completed["expires_at"], 2100)
        self.assertEqual(self.store.active["expire_at"], 2100)
        self.assertEqual(len([call for call in self.client.calls if call[1] == "/account/login_code/"]), 1)

    def test_bad_code_and_failed_workshop_verification_preserve_previous_session(self):
        previous = self.prior_session()
        started = self.sms()
        self.client.requests.append(response("failed", msg="private diagnostics"))
        result = self.auth.login_submit({"login_id": started["login_id"], "code": "1234"})
        self.assertEqual(result["status"], "failed")
        self.assertFalse(result["code_accepted"])
        self.assertEqual(self.store.active, previous)
        with self.assertRaises(FuploadError): self.auth.login_submit({"login_id": started["login_id"], "code": "1234"})
        started = self.sms()  # A second SMS requires this explicit new action.
        self.client.requests.extend([response(result=login_result()), response("login")])
        with self.assertRaises(FuploadError): self.auth.login_submit({"login_id": started["login_id"], "code": "1234"})
        self.assertEqual(self.store.active, previous)
        self.assertEqual(self.store.saved, [])

    def test_pending_verified_credentials_resume_via_reads_without_resubmitting_sms(self):
        previous = self.prior_session()
        started = self.sms()
        self.client.requests.extend([response(result=login_result()), FuploadError("verification timeout", kind="network_error")])
        with self.assertRaises(FuploadError): self.auth.login_submit({"login_id": started["login_id"], "code": "1234"})
        self.assertEqual(self.store.active, previous)
        self.assertEqual(self.store.pending["status"], "verification_required")
        self.assertIn("candidate_session", self.store.pending)
        self.client.requests.extend([response(result=login_result()), *verifies()])
        completed = self.auth.login_status(started["login_id"])
        self.assertTrue(completed["authenticated"])
        self.assertEqual(len([c for c in self.client.calls if c[1] == "/account/login_code/"]), 1)
        self.assertEqual(len([c for c in self.client.calls if c[1] == "/account/get_login_code/"]), 1)

    def test_uncertain_otp_without_credentials_is_never_resubmitted(self):
        previous = self.prior_session()
        started = self.sms()
        self.client.requests.append(FuploadError("OTP response lost", kind="network_error"))
        with self.assertRaises(FuploadError): self.auth.login_submit({"login_id": started["login_id"], "code": "1234"})
        with self.assertRaises(FuploadError): self.auth.login_submit({"login_id": started["login_id"], "code": "1234"})
        self.client.requests.append(response("login"))
        with self.assertRaises(FuploadError): self.auth.login_status(started["login_id"])
        self.assertEqual(self.store.active, previous)
        routes = [call[1] for call in self.client.calls if call[0] == "request"]
        self.assertEqual(routes.count("/account/login_code/"), 1)
        self.assertEqual(routes.count("/account/get_login_code/"), 1)
        self.assertEqual(routes[-1], "/account/restore_login")

    def test_ok_otp_without_identity_does_not_fabricate_or_repost_credentials(self):
        previous = self.prior_session()
        started = self.sms()
        self.client.requests.extend([response(result={}), response("login")])
        with self.assertRaises(FuploadError): self.auth.login_submit({"login_id": started["login_id"], "code": "1234"})
        self.assertNotIn("identity", self.store.pending["candidate_session"])
        self.assertFalse(any(row["name"] in IDENTITY_COOKIES for row in self.store.pending["candidate_session"]["cookies"]))
        with self.assertRaises(FuploadError): self.auth.login_submit({"login_id": started["login_id"], "code": "1234"})
        self.assertEqual(self.store.active, previous)
        self.assertEqual(len([call for call in self.client.calls if call[1] == "/account/login_code/"]), 1)

    def test_expired_or_wrong_login_id_never_submits_code(self):
        started = self.sms()
        with self.assertRaises(FuploadError): self.auth.login_submit({"login_id": "a" * 32 if started["login_id"] != "a" * 32 else "b" * 32, "code": "1234"})
        self.clock += PENDING_TTL + 1
        result = self.auth.login_submit({"login_id": started["login_id"], "code": "1234"})
        self.assertEqual(result["status"], "expired")
        self.assertEqual(len([c for c in self.client.calls if c[0] == "request"]), 1)

    def test_wechat_start_returns_local_image_and_opaque_id_only(self):
        previous = self.prior_session()
        started = self.wechat()
        self.assertEqual(started["status"], "waiting_scan")
        self.assertTrue(Path(started["image_file"]).is_absolute())
        self.assertTrue(Path(started["image_file"]).is_file())
        self.assertEqual(self.store.active, previous)
        self.assertNotIn("SENSITIVE", json.dumps(started))
        self.assertNotIn("QR-FIXTURE", json.dumps(started))
        self.assertFalse(self.client.calls[-1][1].startswith("http:"))

    def test_wechat_rejects_unexpected_provider_before_fetching_it(self):
        with self.assertRaises(FuploadError) as failure: self.wechat(oauth="https://evil.invalid/connect/qrconnect")
        self.assertEqual(failure.exception.kind, "trust_boundary")
        self.assertEqual(len(self.client.calls), 2)

    def test_wechat_provider_anchor_is_removed_before_https_fetch(self):
        callback = API + "/account/wechat/login_redirect/v2/web_sso/"
        oauth = "https://open.weixin.qq.com/connect/qrconnect?" + urllib.parse.urlencode({"redirect_uri": callback, "state": "fixture"}) + "#wechat_redirect"
        started = self.wechat(oauth=oauth)
        self.assertEqual(started["status"], "waiting_scan")
        self.assertNotIn("#", self.client.calls[2][1])

    def test_wechat_rejects_cross_origin_callback_redirect(self):
        previous = self.prior_session()
        started = self.wechat()
        self.client.fetches.extend([HttpResponse(200, {}, b'window.wx_errcode=405;window.wx_code="PRIVATE-CODE";'), HttpResponse(302, {"Location": "https://evil.invalid/collect"}, b"")])
        with self.assertRaises(FuploadError) as failure: self.auth.login_status(started["login_id"])
        self.assertEqual(failure.exception.kind, "trust_boundary")
        self.assertFalse(any("evil.invalid" in call[1] for call in self.client.calls))
        self.assertEqual(self.store.active, previous)
        self.assertNotIn("PRIVATE", json.dumps(failure.exception.as_dict()))

    def test_each_wechat_status_performs_one_short_poll_without_new_qr(self):
        started = self.wechat()
        self.client.fetches.extend([HttpResponse(200, {}, b"window.wx_errcode=408;"), HttpResponse(200, {}, b"window.wx_errcode=404;")])
        count = len(self.client.calls)
        self.assertEqual(self.auth.login_status(started["login_id"])["status"], "waiting_scan")
        self.assertEqual(self.auth.login_status(started["login_id"])["status"], "waiting_confirmation")
        calls = self.client.calls[count:]
        self.assertEqual(len(calls), 2)
        self.assertTrue(all(c[2]["timeout"] == 2 and "/connect/l/qrconnect?" in c[1] for c in calls))

    def test_wechat_incomplete_state_uses_official_restore_then_replaces_session(self):
        previous = self.prior_session()
        started = self.wechat()
        self.client.fetches.extend([HttpResponse(200, {}, b'window.wx_errcode=405;window.wx_code="SENSITIVE-OAUTH-CODE";'), HttpResponse(302, {"Location": LOGIN}, b""), HttpResponse(200, {}, b"login")])
        self.client.requests.extend([response(result={}), response(result=login_result()), *verifies()])
        completed = self.auth.login_status(started["login_id"])
        self.assertTrue(completed["authenticated"])
        self.assertEqual(self.store.active["method"], "wechat")
        self.assertNotEqual(self.store.active, previous)
        self.assertEqual([c[1] for c in self.client.calls if c[0] == "request"], ["/account/wechat/state/", "/account/restore_login", "/wow/open_platform/module/list/", "/wow/get_user_configuration_backup_list/"])
        self.assertNotIn("SENSITIVE", json.dumps(completed))
        self.assertEqual({c["name"] for c in self.store.active["cookies"]}, IDENTITY_COOKIES)
        self.assertFalse(Path(started["image_file"]).exists())

    def test_wechat_callback_redirect_budget_is_bounded_and_saved_for_next_status(self):
        started = self.wechat()
        self.client.fetches.append(HttpResponse(200, {}, b'window.wx_errcode=405;window.wx_code="FIXTURE-CODE";'))
        self.client.fetches.extend([HttpResponse(302, {"Location": LOGIN}, b"")] * 4)
        count = len(self.client.calls)
        result = self.auth.login_status(started["login_id"])
        self.assertEqual(result["phase"], "finishing_login")
        self.assertEqual(len(self.client.calls) - count, 5)
        self.assertTrue(self.store.pending["oauth_confirmed"])
        self.assertNotIn("https:", json.dumps(result))

    def test_wechat_expiry_and_cancellation_remove_pending_and_qr(self):
        for status, expected in ((402, "expired"), (403, "cancelled")):
            with self.subTest(status=status):
                started = self.wechat()
                self.client.fetches.append(HttpResponse(200, {}, ("window.wx_errcode=%d;" % status).encode()))
                self.assertEqual(self.auth.login_status(started["login_id"])["status"], expected)
                self.assertIsNone(self.store.pending)
                self.assertFalse(Path(started["image_file"]).exists())

    def test_wechat_poll_timeout_is_one_retryable_read_not_a_new_login(self):
        started = self.wechat()
        self.client.fetches.append(FuploadError("private poll URL", kind="network_error"))
        result = self.auth.login_status(started["login_id"])
        self.assertEqual(result["status"], "waiting_scan")
        self.assertTrue(result["retryable_read"])
        self.assertFalse(result["automatic_retry"])
        self.assertNotIn("private", json.dumps(result))

    def test_wechat_ttl_is_five_minutes_and_status_does_not_fetch_after_expiry(self):
        started = self.wechat()
        count = len(self.client.calls)
        self.clock += 301
        self.assertEqual(self.auth.login_status(started["login_id"])["status"], "expired")
        self.assertEqual(len(self.client.calls), count)
        self.assertFalse(Path(started["image_file"]).exists())

    def test_renew_checks_identity_expiry_and_workshop_before_saving(self):
        previous = self.prior_session()
        self.client.requests.extend([response(result=login_result(uid="777")), *verifies()])
        result = self.auth.renew({})
        self.assertTrue(result["api_ready"])
        self.assertEqual(self.store.active["identity"], previous["identity"])
        self.assertEqual(self.store.active["expire_at"], 2000)
        self.assertEqual(len(self.client.calls), 3)
        self.assertFalse(any("get_login_code" in call[1] or "web_sso" in call[1] for call in self.client.calls))

    def test_renew_never_switches_identity_or_sends_login(self):
        previous = self.prior_session()
        self.client.requests.append(response(result=login_result(uid="999")))
        with self.assertRaises(FuploadError) as error: self.auth.renew({})
        self.assertEqual(error.exception.kind, "identity_mismatch")
        self.assertEqual(self.store.active, previous)
        self.assertEqual(self.store.saved, [])

    def test_login_cannot_replace_session_after_pending_ttl_during_verification(self):
        previous = self.prior_session()
        started = self.sms()
        def final_verify(route, method, session):
            self.clock += 301
            return response(result={"backupList": []})
        self.client.requests.extend([response(result=login_result()), verifies()[0], final_verify])
        result = self.auth.login_submit({"login_id": started["login_id"], "code": "1234"})
        self.assertEqual(result["status"], "expired")
        self.assertEqual(self.store.active, previous)
        self.assertEqual(self.store.saved, [])

    def test_doctor_missing_login_and_forget_are_local_without_remote_logout(self):
        self.assertEqual(self.auth.doctor(), {"status": "login_required", "session_present": False, "authenticated": False, "api_ready": False})
        started = self.wechat()
        self.prior_session()
        count = len(self.client.calls)
        result = self.auth.forget({"confirm_forget": True})
        self.assertTrue(result["forgotten"])
        self.assertFalse(result["remote_logout"])
        self.assertTrue(self.store.forgotten)
        self.assertIsNone(self.store.pending)
        self.assertEqual(len(self.client.calls), count)
        self.assertFalse(Path(started["image_file"]).exists())

    def test_fixed_key_blob_and_windows_crypto_have_no_external_package_dependency(self):
        blob = _rsa_blob()
        self.assertEqual(blob[:4], b"RSA1")
        if os.name == "nt":
            first, second = encrypt_phone("13800000000"), encrypt_phone("13800000000")
            self.assertEqual(len(base64.b64decode(first)), 128)
            self.assertNotEqual(first, second)

    def encrypted_store(self):
        return Store(Path(self.temp.name) / "encrypted", encrypt=lambda value: b"fixture:" + value[::-1], decrypt=lambda value: value[len(b"fixture:"):][::-1], now=lambda: self.clock)

    def test_sms_steps_resume_from_encrypted_store_without_reusing_process_state(self):
        self.auth.store = self.encrypted_store()
        started = self.sms()
        pending_path = self.auth.store.directory / "pending.dpapi"
        self.assertNotIn(b"13800000000", pending_path.read_bytes())
        self.assertNotIn(b"ENCRYPTED-PHONE-FIXTURE", pending_path.read_bytes())
        self.client.requests.extend([response(result=login_result()), *verifies()])
        restarted = BlackboxAuth(store=self.encrypted_store(), client=self.client, now=lambda: self.clock, device_risk_loader=lambda: None)
        completed = restarted.login_submit({"login_id": started["login_id"], "code": "001234"})
        self.assertTrue(completed["authenticated"])
        active = restarted.store.load_active()
        self.assertEqual({row["name"] for row in active["cookies"]}, IDENTITY_COOKIES)
        self.assertFalse(pending_path.exists())
        for path in restarted.store.directory.glob("*.dpapi"):
            self.assertNotIn(b"SENSITIVE-PKEY", path.read_bytes())
            self.assertNotIn(b"001234", path.read_bytes())

    def test_wechat_status_resumes_encrypted_uuid_callback_and_state_after_restart(self):
        self.auth.store = self.encrypted_store()
        started = self.wechat()
        pending_path = self.auth.store.directory / "pending.dpapi"
        raw = pending_path.read_bytes()
        self.assertNotIn(b"SENSITIVE-OAUTH-STATE", raw)
        self.assertNotIn(b"QR-FIXTURE-123", raw)
        self.client.fetches.extend([HttpResponse(200, {}, b'window.wx_errcode=405;window.wx_code="PRIVATE-CODE";'), HttpResponse(200, {}, b"login")])
        self.client.requests.extend([response(result={}), response(result=login_result()), *verifies()])
        restarted = BlackboxAuth(store=self.encrypted_store(), client=self.client, now=lambda: self.clock, device_risk_loader=lambda: None)
        completed = restarted.login_status(started["login_id"])
        self.assertTrue(completed["authenticated"])
        self.assertEqual(restarted.store.load_active()["method"], "wechat")
        self.assertFalse(pending_path.exists())
        self.assertFalse(Path(started["image_file"]).exists())


if __name__ == "__main__": unittest.main()
