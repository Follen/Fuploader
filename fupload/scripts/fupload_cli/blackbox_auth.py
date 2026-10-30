"""Explicit, short-lived Heybox SMS and WeChat login steps over HTTPS only."""
from __future__ import annotations

import base64
from copy import deepcopy
import ctypes
from ctypes import wintypes
import html
from html.parser import HTMLParser
import os
from pathlib import Path
import re
import secrets
import struct
import time
from typing import Any, Callable, Mapping
import urllib.parse

from .blackbox_http import (API, LOGIN, LOGIN_ORIGIN, SCHEMA, WORKSHOP,
                           HttpClient, Store, apply_session, identity,
                           load_device_risk_token)
from .errors import FuploadError, ValidationError


PENDING_SCHEMA = "fupload.blackbox.pending-login.v1"
PENDING_TTL = 300
_ID = re.compile(r"[a-f0-9]{32}")
_UUID = re.compile(r"[A-Za-z0-9_-]{1,200}")
_REDIRECTS = {301, 302, 303, 307, 308}
_CALLBACK_PATH = "/account/wechat/login_redirect/v2/web_sso/"
_TERMINAL = {"expired", "cancelled", "failed", "captcha_required", "device_verification_required", "verification_required"}
_PUBLIC_KEY_DER = base64.b64decode(
    "MIGfMA0GCSqGSIb3DQEBAQUAA4GNADCBiQKBgQDZgjVwAiKTjZ55nG+mW6r3TSU4"
    "ECvNYqDMIS/bhCj2QaH5GI/KZb2TBp+CBvUj9SLFnmJQ0kzHzHoGZCQ88VevCffF7JePGF9cmKQqotlfTKbV4oxV5iLz7JSG6b/Vg7AXtrTolNtWsa8HiB0tI0YClYaQlOXm4UxLeSxQwSFETwIDAQAB"
)


def _der(data: bytes, offset: int, expected: int) -> tuple[bytes, int]:
    if offset + 2 > len(data) or data[offset] != expected:
        raise ValueError("invalid fixed RSA key")
    length, offset = data[offset + 1], offset + 2
    if length & 128:
        size = length & 127
        if not 1 <= size <= 4 or offset + size > len(data):
            raise ValueError("invalid fixed RSA key")
        length, offset = int.from_bytes(data[offset:offset + size], "big"), offset + size
    if offset + length > len(data):
        raise ValueError("invalid fixed RSA key")
    return data[offset:offset + length], offset + length


def _rsa_blob() -> bytes:
    outer, _ = _der(_PUBLIC_KEY_DER, 0, 0x30)
    _, offset = _der(outer, 0, 0x30)
    bits, _ = _der(outer, offset, 0x03)
    key, _ = _der(bits, 1, 0x30)
    modulus, offset = _der(key, 0, 0x02)
    exponent, _ = _der(key, offset, 0x02)
    modulus, exponent = modulus.lstrip(b"\0"), exponent.lstrip(b"\0")
    return struct.pack("<6I", 0x31415352, len(modulus) * 8, len(exponent), len(modulus), 0, 0) + exponent + modulus


def encrypt_phone(phone: str) -> str:
    """Match JSEncrypt's fixed public-key RSAES-PKCS1-v1_5 using Windows CNG."""
    if os.name != "nt":
        raise FuploadError("Heybox SMS encryption requires Windows CNG", kind="environment_error")
    api = ctypes.WinDLL("bcrypt")
    api.BCryptOpenAlgorithmProvider.argtypes = [ctypes.POINTER(wintypes.HANDLE), wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.ULONG]
    api.BCryptImportKeyPair.argtypes = [wintypes.HANDLE, wintypes.HANDLE, wintypes.LPCWSTR, ctypes.POINTER(wintypes.HANDLE), ctypes.c_void_p, wintypes.ULONG, wintypes.ULONG]
    api.BCryptEncrypt.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.ULONG, ctypes.c_void_p, ctypes.c_void_p, wintypes.ULONG, ctypes.c_void_p, wintypes.ULONG, ctypes.POINTER(wintypes.ULONG), wintypes.ULONG]
    api.BCryptDestroyKey.argtypes = [wintypes.HANDLE]
    api.BCryptCloseAlgorithmProvider.argtypes = [wintypes.HANDLE, wintypes.ULONG]
    for name in ("BCryptOpenAlgorithmProvider", "BCryptImportKeyPair", "BCryptEncrypt", "BCryptDestroyKey", "BCryptCloseAlgorithmProvider"):
        getattr(api, name).restype = ctypes.c_long
    algorithm, key = wintypes.HANDLE(), wintypes.HANDLE()
    def checked(status: int) -> None:
        if status:
            raise FuploadError("Heybox SMS public-key encryption failed", kind="environment_error")
    try:
        checked(api.BCryptOpenAlgorithmProvider(ctypes.byref(algorithm), "RSA", None, 0))
        public = ctypes.create_string_buffer(_rsa_blob())
        checked(api.BCryptImportKeyPair(algorithm, None, "RSAPUBLICBLOB", ctypes.byref(key), public, len(public) - 1, 0))
        plaintext = ("+86" + phone).encode("ascii")
        source = ctypes.create_string_buffer(plaintext)
        size = wintypes.ULONG()
        checked(api.BCryptEncrypt(key, source, len(plaintext), None, None, 0, None, 0, ctypes.byref(size), 2))
        ciphertext = ctypes.create_string_buffer(size.value)
        checked(api.BCryptEncrypt(key, source, len(plaintext), None, None, 0, ciphertext, len(ciphertext), ctypes.byref(size), 2))
        return base64.b64encode(ciphertext.raw[:size.value]).decode("ascii")
    finally:
        if key:
            api.BCryptDestroyKey(key)
        if algorithm:
            api.BCryptCloseAlgorithmProvider(algorithm, 0)


class _MetaParser(HTMLParser):
    version = ""
    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag.casefold() == "meta" and values.get("name") == "web_version":
            self.version = str(values.get("content") or "")[:256]


class BlackboxAuth:
    def __init__(self, *, store: Store | None = None, client: HttpClient | None = None,
                 now: Callable[[], float] = time.time, phone_encryptor: Callable[[str], str] = encrypt_phone,
                 device_risk_loader: Callable[[], str | None] = load_device_risk_token):
        self.store, self.client = store or Store(), client or HttpClient()
        self.now, self.phone_encryptor, self.device_risk_loader = now, phone_encryptor, device_risk_loader

    def _public(self, pending: Mapping[str, Any], **extra: Any) -> dict[str, Any]:
        result = {"login_id": pending["login_id"], "method": pending["method"], "status": pending["status"],
                  "authenticated": False, "expires_in": max(0, int(pending["expires_at"] - self.now())), **extra}
        if pending["method"] == "wechat" and pending.get("image_file") and pending["status"] not in _TERMINAL:
            result["image_file"] = pending["image_file"]
        return result

    def _request(self, pending: dict[str, Any], route: str, method: str = "GET", **kwargs: Any) -> dict[str, Any]:
        # The device risk field is explicitly authorized, current-user, and
        # memory-only. OAuth/account cookies are not borrowed from the client.
        pending["cookies"] = [row for row in pending.get("cookies", []) if row.get("name") != "x_xhh_tokenid"]
        token = self.device_risk_loader()
        if token:
            pending["cookies"].append({"name": "x_xhh_tokenid", "value": token, "domain": ".xiaoheihe.cn", "path": "/", "secure": True, "expires": int(self.now()) + 300})
        try:
            return self.client.request(route, method, session=pending, timeout=5, **kwargs)
        finally:
            pending["cookies"] = [row for row in pending.get("cookies", []) if row.get("name") != "x_xhh_tokenid"]

    def _image_directory(self) -> Path:
        directory = self.store.directory / "qr"
        directory.mkdir(parents=True, exist_ok=True)
        if directory.is_symlink() or self.store.directory.is_symlink():
            raise FuploadError("Heybox QR image directory is invalid", kind="trust_boundary")
        return directory

    def _delete_image(self, login_id: str) -> None:
        directory = self.store.directory / "qr"
        if directory.is_symlink():
            raise FuploadError("Heybox QR image directory is invalid", kind="trust_boundary")
        for suffix in (".png", ".jpg"):
            path = directory / ("qr-" + login_id + suffix)
            if path.is_symlink():
                raise FuploadError("Heybox QR image path is invalid", kind="trust_boundary")
            path.unlink(missing_ok=True)

    def _pending(self, login_id: str) -> dict[str, Any] | None:
        if not isinstance(login_id, str) or not _ID.fullmatch(login_id):
            raise ValidationError("login_id must be the opaque ID returned by login-start", path="$.login_id")
        pending = self.store.load_pending()
        if pending is None:
            self._delete_image(login_id)
            return None
        if pending.get("schema") != PENDING_SCHEMA or pending.get("method") not in {"sms", "wechat"} or pending.get("login_id") != login_id:
            raise FuploadError("Heybox pending login does not match login_id", kind="login_id_mismatch")
        if type(pending.get("expires_at")) is not int or type(pending.get("created_at")) is not int or pending["expires_at"] - pending["created_at"] != PENDING_TTL or pending["expires_at"] <= self.now() or pending["created_at"] > self.now() + 5:
            self.store.delete_pending()
            self._delete_image(login_id)
            return None
        return pending

    @staticmethod
    def _failure(response: Mapping[str, Any]) -> str:
        return {"show_captcha": "captcha_required", "lack_token": "device_verification_required", "name_verify": "verification_required", "need_alipay_verify": "verification_required", "need_bind_phone": "verification_required", "need_phone_code": "verification_required"}.get(response.get("status"), "failed")

    def login_start(self, doc: Mapping[str, Any]) -> dict[str, Any]:
        if set(doc) - {"schema", "method", "phone"} or doc.get("method") not in {"sms", "wechat"}:
            raise ValidationError("login-start accepts only method and the SMS phone field")
        method, phone = doc["method"], doc.get("phone")
        if method == "sms" and (not isinstance(phone, str) or not re.fullmatch(r"1[3-9][0-9]{9}", phone)):
            raise ValidationError("phone must be a mainland China mobile number", path="$.phone")
        if method == "wechat" and "phone" in doc:
            raise ValidationError("WeChat login does not accept phone", path="$.phone")
        with self.store.lock():
            active = self.store.load_pending()
            if active is not None and (active.get("schema") != PENDING_SCHEMA or active.get("method") not in {"sms", "wechat"} or not isinstance(active.get("login_id"), str) or not _ID.fullmatch(active["login_id"])):
                raise FuploadError("Heybox pending login state is invalid", kind="login_state_error")
            if active is not None and active.get("status") not in _TERMINAL:
                raise FuploadError("A Heybox login is already pending; continue its returned login_id", kind="login_in_progress", details={"login_id": active.get("login_id"), "automatic_retry": False})
            if active is not None:
                self._delete_image(active["login_id"])
                self.store.delete_pending()
            now = int(self.now())
            pending = {"schema": PENDING_SCHEMA, "login_id": secrets.token_hex(16), "method": method,
                       "created_at": now, "expires_at": now + PENDING_TTL, "status": "starting",
                       "device_id": secrets.token_hex(16), "web_version": "", "cookies": []}
            # Reserve before a network request: a timeout never silently sends
            # another SMS or creates another QR in a later invocation.
            self.store.save_pending(pending)
            try:
                response = self.client.fetch(LOGIN, pending, timeout=5)
                if response.status != 200:
                    raise FuploadError("Heybox login initialization failed", kind="authentication_error")
                parser = _MetaParser()
                parser.feed(response.body.decode("utf-8"))
                pending["web_version"] = parser.version
                if method == "wechat":
                    return self._wechat_start(pending)
                pending.update(status="sms_sending", phone_encrypted=self.phone_encryptor(phone))
                self.store.save_pending(pending)
                sent = self._request(pending, "/account/get_login_code/", "POST", body={"phone_num": pending["phone_encrypted"]})
                pending["status"] = "waiting_code" if sent.get("status") == "ok" else self._failure(sent)
                self.store.save_pending(pending)
                return self._public(pending, sms_sent=sent.get("status") == "ok", automatic_retry=False)
            except FuploadError as exc:
                pending["status"] = "sms_send_uncertain" if pending.get("status") == "sms_sending" else "starting_uncertain"
                self.store.save_pending(pending)
                raise FuploadError("Heybox login start did not finish; no automatic retry was made", kind=exc.kind, stage="login_start", http_status=exc.http_status, verification_required=True, details={"login_id": pending["login_id"], "automatic_retry": False}) from None

    def _wechat_start(self, pending: dict[str, Any]) -> dict[str, Any]:
        entry = API + "/account/wechat/login/v2/web_sso/?" + urllib.parse.urlencode({"redirect_url": LOGIN + "&src=1"})
        response = self.client.fetch(entry, pending, timeout=5)
        if response.status not in _REDIRECTS or not response.headers.get("Location"):
            raise FuploadError("Heybox WeChat entry did not return its OAuth redirect", kind="protocol_error")
        oauth = urllib.parse.urljoin(entry, response.headers["Location"])
        parts = urllib.parse.urlsplit(oauth)
        if parts.scheme != "https" or parts.netloc != "open.weixin.qq.com" or parts.path != "/connect/qrconnect" or parts.fragment not in {"", "wechat_redirect"}:
            raise FuploadError("Heybox OAuth provider was outside its fixed route", kind="trust_boundary")
        oauth = urllib.parse.urlunsplit((parts.scheme, parts.netloc, parts.path, parts.query, ""))
        query = urllib.parse.parse_qs(parts.query, strict_parsing=True)
        if len(query.get("redirect_uri", [])) != 1 or len(query.get("state", [])) != 1:
            raise FuploadError("Heybox OAuth entry was incomplete", kind="protocol_error")
        callback, state = query["redirect_uri"][0], query["state"][0]
        self._callback_url(callback)
        if not state or len(state) > 2048:
            raise FuploadError("Heybox OAuth state was invalid", kind="protocol_error")
        response = self.client.fetch(oauth, pending, timeout=5)
        if response.status != 200:
            raise FuploadError("WeChat QR page was unavailable", kind="authentication_error")
        page = response.body.decode("utf-8")
        images = re.findall(r'<img[^>]+src=["\']([^"\']+)', page)
        qr = next((html.unescape(value) for value in images if re.fullmatch(r"/connect/qrcode/[A-Za-z0-9_-]{1,200}", html.unescape(value))), None)
        polling = re.search(r'var\s+fordevtool\s*=\s*["\'](https://long\.open\.weixin\.qq\.com/connect/l/qrconnect\?uuid=[A-Za-z0-9_-]{1,200})', page)
        if qr is None or polling is None:
            raise FuploadError("WeChat QR page omitted its official session fields", kind="protocol_error")
        uuid = qr.rsplit("/", 1)[-1]
        if urllib.parse.parse_qs(urllib.parse.urlsplit(html.unescape(polling.group(1))).query).get("uuid") != [uuid]:
            raise FuploadError("WeChat QR and polling sessions did not match", kind="protocol_error")
        response = self.client.fetch("https://open.weixin.qq.com" + qr, pending, timeout=5)
        suffix = ".png" if response.body.startswith(b"\x89PNG\r\n\x1a\n") else ".jpg" if response.body.startswith(b"\xff\xd8\xff") else None
        if response.status != 200 or suffix is None or len(response.body) > 1024 * 1024:
            raise FuploadError("WeChat QR image had an unsupported format", kind="protocol_error")
        image = self._image_directory() / ("qr-" + pending["login_id"] + suffix)
        with image.open("xb") as handle:
            handle.write(response.body)
        pending.update(status="waiting_scan", oauth_uuid=uuid, oauth_callback=callback, oauth_state=state, image_file=str(image.resolve()))
        self.store.save_pending(pending)
        return self._public(pending)

    @staticmethod
    def _callback_url(url: str) -> None:
        parsed = urllib.parse.urlsplit(url)
        if parsed.scheme != "https" or parsed.netloc != "api.xiaoheihe.cn" or parsed.path != _CALLBACK_PATH or parsed.fragment:
            raise FuploadError("WeChat callback was outside the fixed official route", kind="trust_boundary")

    def _verify(self, session: dict[str, Any]) -> None:
        for route, method, field in (("/wow/open_platform/module/list/", "GET", "moduleList"), ("/wow/get_user_configuration_backup_list/", "POST", "backupList")):
            response = self._request(session, route, method)
            result = response.get("result")
            if response.get("status") != "ok" or not isinstance(result, dict) or not isinstance(result.get(field), list):
                raise FuploadError("Heybox login could not be verified by Workshop reads", kind="authentication_error", stage="login_verify")

    def _complete(self, pending: dict[str, Any], result: Mapping[str, Any]) -> dict[str, Any]:
        if not isinstance(result, Mapping):
            raise FuploadError("Heybox login response was incomplete", kind="protocol_error")
        candidate = {"schema": SCHEMA, "cookies": deepcopy(pending.get("cookies", [])), "device_id": pending["device_id"], "web_version": pending.get("web_version", ""), "method": pending["method"]}
        profile, detail = result.get("profile") or {}, result.get("account_detail") or {}
        uid = str(profile.get("heybox_id") or detail.get("userid") or "") if isinstance(profile, dict) and isinstance(detail, dict) else ""
        if uid and result.get("pkey") and type(result.get("expire_at")) is not int:
            # Bootstrap only this one exchange in memory. The persisted expiry
            # must still come from the official restore response below.
            temporary = dict(result, expire_at=int(self.now()) + PENDING_TTL)
            apply_session(candidate, temporary, now=self.now())
        elif uid and result.get("pkey"):
            apply_session(candidate, result, now=self.now())
        # Checkpoint the consumed OTP/callback credentials before restore. A
        # missing server expiry must never lose the only new login cookies.
        pending.update(status="verifying", candidate_session=deepcopy(candidate))
        self.store.save_pending(pending)
        if not uid or not result.get("pkey") or type(result.get("expire_at")) is not int:
            restored = self._request(candidate, "/account/restore_login")
            if restored.get("status") != "ok" or not isinstance(restored.get("result"), dict):
                raise FuploadError("Heybox login restore did not return a complete session", kind="authentication_error", stage="login_restore")
            apply_session(candidate, restored["result"], now=self.now(), expected_identity=uid or None)
        pending.update(status="verifying", candidate_session=deepcopy(candidate))
        self.store.save_pending(pending)
        return self._finish_candidate(pending, candidate)

    def _finish_candidate(self, pending: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
        self._verify(candidate)
        if self.now() >= pending["expires_at"]:
            self.store.delete_pending()
            self._delete_image(pending["login_id"])
            return {"status": "expired", "authenticated": False, "login_id": pending["login_id"]}
        self.store.save_session(candidate)
        self.store.delete_pending()
        self._delete_image(pending["login_id"])
        return {"status": "authenticated", "authenticated": True, "api_ready": True, "method": pending["method"], "login_id": pending["login_id"], "expires_at": candidate["expire_at"]}

    def _resume_candidate(self, pending: dict[str, Any]) -> dict[str, Any]:
        candidate = deepcopy(pending["candidate_session"])
        try:
            expected = identity(candidate)
        except FuploadError as exc:
            if exc.kind != "login_required":
                raise
            expected = None
        response = self._request(candidate, "/account/restore_login")
        if response.get("status") != "ok" or not isinstance(response.get("result"), dict):
            raise FuploadError("Heybox pending session could not be restored", kind="authentication_error")
        apply_session(candidate, response["result"], now=self.now(), expected_identity=expected)
        pending["candidate_session"] = deepcopy(candidate)
        self.store.save_pending(pending)
        return self._finish_candidate(pending, candidate)

    def login_submit(self, doc: Mapping[str, Any]) -> dict[str, Any]:
        if set(doc) - {"schema", "login_id", "code"} or not isinstance(doc.get("code"), str) or not re.fullmatch(r"[0-9]{4,8}", doc["code"]):
            raise ValidationError("login-submit requires login_id and a 4 to 8 digit code", path="$.code")
        with self.store.lock():
            pending = self._pending(doc.get("login_id"))
            if pending is None:
                return {"status": "expired", "authenticated": False, "login_id": doc.get("login_id")}
            if pending["method"] != "sms" or pending["status"] != "waiting_code" or pending.get("submit_attempted") is True:
                raise FuploadError("This login is not awaiting an SMS code", kind="login_state_error")
            pending.update(status="verification_required", submit_attempted=True)
            self.store.save_pending(pending)
            try:
                response = self._request(pending, "/account/login_code/", "POST", query={"code": doc["code"]}, body={"phone_num": pending["phone_encrypted"]})
                if response.get("status") != "ok":
                    failure = self._failure(response)
                    pending["status"] = failure
                    self.store.save_pending(pending)
                    return self._public(pending, code_accepted=False, automatic_retry=False)
                self.store.save_pending(pending)
                return self._complete(pending, response.get("result") or {})
            except FuploadError as exc:
                pending["status"] = "verification_required"
                self.store.save_pending(pending)
                raise FuploadError("Heybox SMS submission did not finish; no code or SMS was automatically resent", kind=exc.kind, stage="login_submit", http_status=exc.http_status, verification_required=True, details={"login_id": pending["login_id"], "automatic_retry": False}) from None

    def _wechat_finish(self, pending: dict[str, Any]) -> dict[str, Any]:
        for _ in range(4):
            url = pending.get("oauth_next_url")
            if not url:
                break
            parts = urllib.parse.urlsplit(url)
            allowed = parts.scheme == "https" and not parts.fragment and not parts.username and not parts.password and ((parts.netloc == "api.xiaoheihe.cn" and parts.path == _CALLBACK_PATH) or (parts.netloc == "login.xiaoheihe.cn" and parts.path == "/") or (parts.netloc == "open.xiaoheihe.cn" and parts.path == "/zh_cn/workshop"))
            if not allowed:
                raise FuploadError("WeChat callback redirected outside its official routes", kind="trust_boundary")
            response = self.client.fetch(url, pending, timeout=3)
            if response.status in _REDIRECTS and response.headers.get("Location"):
                pending["oauth_next_url"] = urllib.parse.urljoin(url, response.headers["Location"])
            elif response.status == 200:
                pending.pop("oauth_next_url", None)
            else:
                raise FuploadError("WeChat callback returned an unexpected response", kind="authentication_error")
            self.store.save_pending(pending)
        if pending.get("oauth_next_url"):
            return self._public(pending, phase="finishing_login")
        response = self._request(pending, "/account/wechat/state/", query={"_notip": "true", "heybox_id": ""})
        self.store.save_pending(pending)
        if response.get("status") != "ok":
            pending["status"] = self._failure(response)
            self.store.save_pending(pending)
            return self._public(pending, automatic_retry=False)
        return self._complete(pending, response.get("result") or {})

    def login_status(self, login_id: str) -> dict[str, Any]:
        with self.store.lock():
            pending = self._pending(login_id)
            if pending is None:
                return {"status": "expired", "authenticated": False, "login_id": login_id}
            if isinstance(pending.get("candidate_session"), dict):
                try:
                    return self._resume_candidate(pending)
                except FuploadError as exc:
                    self.store.save_pending(pending)
                    raise FuploadError("Heybox pending login verification did not finish; no login was resubmitted", kind=exc.kind, stage="login_status", http_status=exc.http_status, details={"login_id": login_id, "automatic_retry": False}) from None
            if pending["method"] == "sms" and pending.get("submit_attempted") is True:
                try:
                    # Only an official restore can resolve an uncertain OTP
                    # submission. Neither status nor submit repeats its POST.
                    return self._complete(pending, {})
                except FuploadError as exc:
                    pending["status"] = "verification_required"
                    self.store.save_pending(pending)
                    raise FuploadError("Heybox submitted login requires verification; no code was resent", kind=exc.kind, stage="login_status", http_status=exc.http_status, details={"login_id": login_id, "automatic_retry": False}) from None
            if pending["method"] == "sms" or pending["status"] in _TERMINAL:
                return self._public(pending, automatic_retry=False)
            try:
                if pending.get("oauth_confirmed"):
                    return self._wechat_finish(pending)
                uuid = pending.get("oauth_uuid")
                if not isinstance(uuid, str) or not _UUID.fullmatch(uuid):
                    raise FuploadError("WeChat pending login has no polling session", kind="login_state_error")
                query = {"uuid": uuid, "_": int(self.now() * 1000)}
                if pending.get("oauth_last") in {404, 408}:
                    query["last"] = pending["oauth_last"]
                url = "https://long.open.weixin.qq.com/connect/l/qrconnect?" + urllib.parse.urlencode(query)
                response = self.client.fetch(url, pending, timeout=2)
                match = re.search(r"\bwx_errcode\s*=\s*(\d+)", response.body.decode("utf-8")) if response.status == 200 else None
                if match is None:
                    raise FuploadError("WeChat polling response was not recognized", kind="protocol_error")
                status = int(match.group(1))
                pending["oauth_last"] = status
                if status == 405:
                    code = re.search(r'\bwx_code\s*=\s*["\']([A-Za-z0-9_-]{1,512})["\']', response.body.decode("utf-8"))
                    if code is None:
                        raise FuploadError("WeChat confirmation omitted its OAuth code", kind="protocol_error")
                    self._callback_url(pending["oauth_callback"])
                    base = urllib.parse.urlsplit(pending["oauth_callback"])
                    pairs = urllib.parse.parse_qsl(base.query, keep_blank_values=True)
                    if any(key in {"code", "state"} for key, _ in pairs):
                        raise FuploadError("WeChat callback has conflicting exchange fields", kind="trust_boundary")
                    pairs.extend([("code", code.group(1)), ("state", pending["oauth_state"])])
                    pending.update(oauth_confirmed=True, status="waiting_confirmation", oauth_next_url=urllib.parse.urlunsplit((base.scheme, base.netloc, base.path, urllib.parse.urlencode(pairs), "")))
                    self.store.save_pending(pending)
                    return self._wechat_finish(pending)
                if status == 404:
                    pending["status"] = "waiting_confirmation"
                elif status == 408:
                    pending["status"] = "waiting_scan" if pending["status"] != "waiting_confirmation" else "waiting_confirmation"
                elif status in {402, 403}:
                    pending["status"] = "expired" if status == 402 else "cancelled"
                    self.store.delete_pending()
                    self._delete_image(login_id)
                    return self._public(pending)
                else:
                    pending["status"] = "failed"
                self.store.save_pending(pending)
                return self._public(pending)
            except FuploadError as exc:
                self.store.save_pending(pending)
                if exc.kind in {"network_error", "timeout"}:
                    return self._public(pending, retryable_read=True, automatic_retry=False)
                raise FuploadError("Heybox WeChat status check failed", kind=exc.kind, stage="login_status", http_status=exc.http_status, details={"login_id": login_id, "automatic_retry": False}) from None

    def renew(self, doc: Mapping[str, Any] | None = None) -> dict[str, Any]:
        if set(doc or {}) - {"schema"}:
            raise ValidationError("renew does not accept caller credentials or session fields")
        with self.store.lock():
            session = self.store.load_active()
            if session is None:
                raise FuploadError("Heybox login is required", kind="login_required")
            candidate, expected = deepcopy(session), identity(session)
            response = self._request(candidate, "/account/restore_login")
            if response.get("status") != "ok" or not isinstance(response.get("result"), dict):
                raise FuploadError("Heybox saved session could not be renewed", kind="login_required")
            apply_session(candidate, response["result"], now=self.now(), expected_identity=expected)
            self._verify(candidate)
            self.store.save_session(candidate)
            return {"status": "authenticated", "authenticated": True, "api_ready": True, "method": candidate["method"], "expires_at": candidate["expire_at"]}

    def doctor(self) -> dict[str, Any]:
        result = {"status": "login_required", "session_present": False, "authenticated": False, "api_ready": False}
        try:
            session = self.store.load_active()
            if session is None:
                return result
            result["session_present"] = True
            result.update(self.renew())
        except FuploadError as exc:
            result["status"] = "login_required" if exc.kind in {"authentication_error", "login_required"} else "failed"
        return result

    def forget(self, doc: Mapping[str, Any]) -> dict[str, Any]:
        if set(doc) - {"schema", "confirm_forget"} or doc.get("confirm_forget") is not True:
            raise ValidationError("forget requires confirm_forget true", path="$.confirm_forget")
        with self.store.lock():
            pending = self.store.load_pending()
            if pending is not None and isinstance(pending.get("login_id"), str) and _ID.fullmatch(pending["login_id"]):
                self._delete_image(pending["login_id"])
            self.store.delete_pending()
            self.store.forget_active()
        return {"status": "forgotten", "forgotten": True, "remote_logout": False}

    def execute_read(self, action: str, args: Any) -> dict[str, Any]:
        if action == "doctor": return self.doctor()
        if action == "login-status": return self.login_status(args.get("login_id") if isinstance(args, Mapping) else args.login_id)
        raise ValidationError("unsupported Heybox authentication read action")

    def execute_write(self, action: str, doc: Mapping[str, Any]) -> dict[str, Any]:
        if action == "login-start": return self.login_start(doc)
        if action == "login-submit": return self.login_submit(doc)
        if action == "renew": return self.renew(doc)
        if action == "forget": return self.forget(doc)
        raise ValidationError("unsupported Heybox authentication write action")
