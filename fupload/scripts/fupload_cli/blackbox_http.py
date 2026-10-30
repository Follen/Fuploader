"""Heybox HTTPS protocol and CurrentUser encrypted session storage.

No browser, SMS, OAuth entry or business mutation runs implicitly. A business
session restores its existing identity once before its first request.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes
from copy import deepcopy
from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import http.cookiejar
import json
import os
from pathlib import Path
import re
import secrets
import time
from typing import Any, Callable, Mapping
import urllib.error
import urllib.parse
import urllib.request

from .blackbox_web import API_ROUTES, _interleave, _n8, _i8, _mix
from .errors import FuploadError

API = "https://api.xiaoheihe.cn"
WORKSHOP = "https://workshopapi.xiaoheihe.cn"
LOGIN_ORIGIN = "https://login.xiaoheihe.cn"
LOGIN = LOGIN_ORIGIN + "/?origin=heybox_open&redirect_url=https%3A%2F%2Fopen.xiaoheihe.cn%2Fzh_cn%2Fworkshop"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/142.0.0.0 Safari/537.36"
SCHEMA = "fupload.blackbox.http-session.v2"
IDENTITY_COOKIES = frozenset({"heybox_id", "user_heybox_id", "pkey", "user_pkey"})
COOKIE_DOMAINS = frozenset({"xiaoheihe.cn", "api.xiaoheihe.cn", "login.xiaoheihe.cn", "open.xiaoheihe.cn", "workshopapi.xiaoheihe.cn", "weixin.qq.com", "open.weixin.qq.com", "long.open.weixin.qq.com"})
AUTH_ROUTES = frozenset({("GET", "/account/restore_login"), ("POST", "/account/get_login_code/"), ("POST", "/account/login_code/"), ("GET", "/account/wechat/state/")})
_RESERVED = frozenset({"app", "os_type", "x_app", "x_client_type", "x_os_type", "version", "web_version", "device_id", "hkey", "nonce", "_time", "x_xhh_tokenid"})
_MAX_BODY = 32 * 1024 * 1024


def _error(message: str, kind: str = "authentication_error", **kwargs: Any) -> FuploadError:
    return FuploadError(message, kind=kind, **kwargs)


def login_required() -> FuploadError:
    return _error("Heybox login is required; use an explicit auth action", "login_required")


def sign(path: str, timestamp: int, nonce: str) -> str:
    """The official native/verified HTTP signer (time + 1, first 20 chars)."""
    normalized = "/" + "/".join(part for part in path.split("/") if part) + "/"
    source = _interleave([_n8(str(timestamp + 1), -2), _i8(normalized), _i8(nonce)])[:20]
    digest = hashlib.md5(source.encode()).hexdigest()
    return _n8(digest[:5], -4) + f"{sum(_mix([ord(c) for c in digest[-6:]])) % 100:02d}"


def _dpapi(data: bytes, decrypt: bool = False) -> bytes:
    if os.name != "nt":
        raise _error("Heybox encrypted storage requires Windows CurrentUser DPAPI")
    class Blob(ctypes.Structure):
        _fields_ = [("size", wintypes.DWORD), ("data", ctypes.POINTER(ctypes.c_ubyte))]
    source_buffer = (ctypes.c_ubyte * len(data)).from_buffer_copy(data)
    source, target = Blob(len(data), source_buffer), Blob()
    crypto = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    if decrypt:
        call = crypto.CryptUnprotectData
        call.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
        args = (ctypes.byref(source), None, None, None, None, 1, ctypes.byref(target))
    else:
        call = crypto.CryptProtectData
        call.argtypes = [ctypes.POINTER(Blob), wintypes.LPCWSTR, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
        args = (ctypes.byref(source), "Fuploader Heybox HTTP session", None, None, None, 1, ctypes.byref(target))
    call.restype = wintypes.BOOL
    if not call(*args):
        raise _error("Heybox encrypted storage could not be accessed by this Windows user")
    try:
        return ctypes.string_at(target.data, target.size)
    finally:
        kernel.LocalFree(target.data)


def protect(data: bytes) -> bytes:
    return _dpapi(data)


def unprotect(data: bytes) -> bytes:
    return _dpapi(data, True)


def _scope_cookie(row: Any) -> dict[str, Any]:
    if not isinstance(row, Mapping):
        raise _error("Invalid Heybox cookie storage")
    name, value = row.get("name"), row.get("value")
    domain, path = row.get("domain"), row.get("path", "/")
    expires = row.get("expires")
    if (not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9_\-]+", name)
            or not isinstance(value, str) or any(ord(c) < 32 or c in ";\x7f" for c in value)
            or not isinstance(domain, str) or domain.lstrip(".") not in COOKIE_DOMAINS
            or not isinstance(path, str) or not path.startswith("/") or any(ord(c) < 32 for c in path)
            or (expires is not None and (type(expires) is not int or expires < 0))):
        raise _error("Invalid Heybox cookie scope")
    return {"name": name, "value": value, "domain": domain, "path": path,
            "secure": bool(row.get("secure", True)), "expires": expires}


def _jar(session: Mapping[str, Any]) -> http.cookiejar.CookieJar:
    jar = http.cookiejar.CookieJar()
    rows = session.get("cookies", [])
    if not isinstance(rows, list) or len(rows) > 256:
        raise _error("Invalid Heybox cookie storage")
    seen = set()
    for item in rows:
        row = _scope_cookie(item)
        key = row["domain"], row["path"], row["name"]
        if key in seen:
            raise _error("Duplicate Heybox cookie scope")
        seen.add(key)
        domain = row["domain"]
        jar.set_cookie(http.cookiejar.Cookie(0, row["name"], row["value"], None, False,
            domain, domain.startswith("."), domain.startswith("."), row["path"], True,
            row["secure"], row["expires"], False, None, None, {}, False))
    return jar


def _rows(jar: http.cookiejar.CookieJar) -> list[dict[str, Any]]:
    return [_scope_cookie({"name": c.name, "value": c.value, "domain": c.domain,
        "path": c.path, "secure": c.secure, "expires": c.expires}) for c in jar]


def identity(session: Mapping[str, Any]) -> str:
    values: dict[str, set[str]] = {"uid": set(), "pkey": set()}
    for row in _rows(_jar(session)):
        if row["name"] not in IDENTITY_COOKIES:
            continue
        if row["domain"].lstrip(".") != "xiaoheihe.cn" or row["path"] != "/":
            raise _error("Identity cookie has an unexpected scope")
        values["uid" if row["name"] in {"heybox_id", "user_heybox_id"} else "pkey"].add(row["value"])
    if len(values["uid"]) != 1 or len(values["pkey"]) != 1 or not all(next(iter(v)) for v in values.values()):
        raise login_required()
    uid = next(iter(values["uid"]))
    if not re.fullmatch(r"[0-9]{1,32}", uid) or session.get("identity", uid) != uid:
        raise _error("Heybox stored identity does not match its session")
    return uid


def apply_session(session: dict[str, Any], result: Mapping[str, Any], *, now: float | None = None, expected_identity: str | None = None) -> dict[str, Any]:
    """Validate server identity and expiry before replacing any login cookies."""
    now = time.time() if now is None else now
    profile, detail = result.get("profile") or {}, result.get("account_detail") or {}
    if not isinstance(profile, Mapping) or not isinstance(detail, Mapping):
        raise _error("Heybox response contained an invalid identity")
    uid = str(profile.get("heybox_id") or detail.get("userid") or "")
    pkey, expiry = result.get("pkey"), result.get("expire_at")
    if (not re.fullmatch(r"[0-9]{1,32}", uid) or not isinstance(pkey, str) or not pkey
            or any(ord(c) < 32 or c in ";\x7f" for c in pkey)):
        raise _error("Heybox response did not contain a complete session")
    if expected_identity is not None and uid != expected_identity:
        raise _error("Heybox restored identity did not match the active session", "identity_mismatch")
    if type(expiry) is not int or not now < expiry <= now + 366 * 86400:
        raise _error("Heybox server did not return a valid session expiry")
    rows = [r for r in _rows(_jar(session)) if r["name"] not in IDENTITY_COOKIES]
    for name, value in {"heybox_id": uid, "user_heybox_id": uid, "pkey": pkey, "user_pkey": pkey}.items():
        rows.append({"name": name, "value": value, "domain": ".xiaoheihe.cn", "path": "/", "secure": True, "expires": expiry})
    session.update(schema=SCHEMA, identity=uid, expire_at=expiry, cookies=rows)
    return session


def load_device_risk_token() -> str | None:
    """Read only the official local device risk field; never borrow account login."""
    try:
        from .trust import _known_folder_roaming
        path = _known_folder_roaming() / "heybox-pc-launcher" / "config.json"
        if path.is_symlink() or path.stat().st_size > 8 * 1024 * 1024:
            return None
        value = json.loads(path.read_text(encoding="utf-8")).get("acc_config", {}).get("xhh_token_id")
        return value if isinstance(value, str) and len(value) == 89 and value.startswith("B") and not any(ord(c) < 33 or c in ";\x7f" for c in value) else None
    except (OSError, ValueError, AttributeError, FuploadError):
        return None


class Store:
    def __init__(self, root: Path | None = None, *, encrypt: Callable[[bytes], bytes] = protect,
                 decrypt: Callable[[bytes], bytes] = unprotect, now: Callable[[], float] = time.time):
        self.root = Path(root) if root is not None else Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData/Local") / "Fuploader"
        self.directory = self.root / "blackbox-http"
        self.encrypt, self.decrypt, self.now = encrypt, decrypt, now
        self._lock_depth = 0

    @contextmanager
    def lock(self):
        """Fail promptly if another CLI process owns the authentication state."""
        if self._lock_depth:
            self._lock_depth += 1
            try:
                yield
            finally:
                self._lock_depth -= 1
            return
        self.directory.mkdir(parents=True, exist_ok=True)
        path = self.directory / "auth.lock"
        if path.is_symlink() or self.directory.is_symlink():
            raise _error("Heybox authentication lock path is invalid")
        handle = path.open("a+b")
        locked = False
        try:
            handle.seek(0, os.SEEK_END)
            if handle.tell() == 0:
                handle.write(b"0")
                handle.flush()
            handle.seek(0)
            try:
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                raise _error("Another Heybox authentication command is active", "authentication_busy") from None
            locked = True
            self._lock_depth = 1
            yield
        finally:
            self._lock_depth = 0
            if locked:
                handle.seek(0)
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            handle.close()

    def _read(self, path: Path) -> dict[str, Any] | None:
        if not path.exists():
            return None
        if path.is_symlink() or path.stat().st_size > 4 * 1024 * 1024:
            raise _error("Invalid Heybox encrypted storage file")
        try:
            value = json.loads(self.decrypt(path.read_bytes()))
            if not isinstance(value, dict):
                raise ValueError()
            return value
        except FuploadError:
            raise
        except Exception:
            raise _error("Heybox encrypted storage is invalid") from None

    def _write(self, path: Path, value: Mapping[str, Any]) -> None:
        data = json.dumps(value, ensure_ascii=True, separators=(",", ":")).encode()
        if len(data) > 2 * 1024 * 1024:
            raise _error("Heybox encrypted storage is too large")
        encrypted = self.encrypt(data)  # never create a plaintext temporary file
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.is_symlink() or path.parent.is_symlink():
            raise _error("Heybox encrypted storage path is invalid")
        temporary = path.with_name(path.name + "." + secrets.token_hex(8) + ".tmp")
        try:
            with temporary.open("xb") as handle:
                handle.write(encrypted)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)

    def save_session(self, session: dict[str, Any], *, activate: bool = True) -> None:
        uid = identity(session)
        method = session.get("method", "sms")
        if method not in {"sms", "wechat"}:
            raise _error("Invalid Heybox session method")
        expiry = session.get("expire_at")
        if type(expiry) is not int or expiry <= 0:
            raise _error("Heybox session lacks its server expiry")
        safe = {"schema": SCHEMA, "identity": uid, "method": method, "expire_at": expiry,
                "device_id": str(session.get("device_id", "")), "web_version": str(session.get("web_version", "")),
                "cookies": [r for r in _rows(_jar(session)) if r["name"] in IDENTITY_COOKIES]}
        self._write(self.directory / (method + ".dpapi"), safe)
        if activate:
            self._write(self.directory / "active.dpapi", {"schema": 1, "active": method})

    def select_active(self, method: str) -> None:
        if method not in {"sms", "wechat"}:
            raise login_required()
        saved = self._read(self.directory / (method + ".dpapi"))
        if saved is None and self._legacy(method) is None:
            raise login_required()
        self._write(self.directory / "active.dpapi", {"schema": 1, "active": method})

    def load_active(self) -> dict[str, Any] | None:
        selected = self._read(self.directory / "active.dpapi")
        if selected is not None:
            method = selected.get("active")
            if selected.get("schema") == 1 and method == "forgotten":
                return None
            if selected.get("schema") != 1 or method not in {"sms", "wechat"}:
                raise _error("Invalid Heybox active session selection")
            value = self._read(self.directory / (method + ".dpapi")) or self._legacy(method)
            if value is None:
                raise login_required()
            if value.get("schema") != SCHEMA or value.get("method") != method:
                raise _error("Invalid Heybox active session")
            identity(value)
            return value
        # Migration deliberately chooses the original SMS principal first.
        return self._legacy("sms")

    def _legacy(self, method: str) -> dict[str, Any] | None:
        name = "blackbox-http-session.dpapi" if method == "sms" else "blackbox-wechat-session.dpapi"
        legacy = self._read(self.root / name)
        if legacy is None:
            return None
        if legacy.get("schema") != "fupload.blackbox.http-session.v1":
            raise _error("Unsupported legacy Heybox session")
        uid = identity(legacy)
        expiries = [r["expires"] for r in _rows(_jar(legacy)) if r["name"] in {"pkey", "user_pkey"}]
        if not expiries or any(type(e) is not int for e in expiries):
            raise _error("Legacy Heybox session has no expiry; explicit login is required")
        # The old cookie deadline is not evidence of a server expiry. Do not
        # migrate ciphertext until restore supplies an authoritative expire_at.
        legacy.update(schema=SCHEMA, identity=uid, method=method)
        legacy.pop("expire_at", None)
        return legacy

    def save_pending(self, pending: dict[str, Any]) -> None:
        value = deepcopy(pending)
        if type(value.get("expires_at")) not in {int, float} or not self.now() < value["expires_at"] <= self.now() + 900:
            raise _error("Invalid Heybox pending login expiry")
        if "cookies" in value:
            value["cookies"] = [r for r in _rows(_jar(value)) if r["name"] != "x_xhh_tokenid"]
        self._write(self.directory / "pending.dpapi", value)

    def load_pending(self) -> dict[str, Any] | None:
        value = self._read(self.directory / "pending.dpapi")
        if value is not None and (type(value.get("expires_at")) not in {int, float} or value["expires_at"] <= self.now()):
            self.delete_pending()
            return None
        return value

    def delete_pending(self) -> None:
        (self.directory / "pending.dpapi").unlink(missing_ok=True)

    def forget_active(self) -> None:
        selected = self._read(self.directory / "active.dpapi")
        if selected and selected.get("active") in {"sms", "wechat"}:
            (self.directory / (selected["active"] + ".dpapi")).unlink(missing_ok=True)
        # A tombstone prevents re-importing an older principal after logout.
        self._write(self.directory / "active.dpapi", {"schema": 1, "active": "forgotten"})


@dataclass
class HttpResponse:
    status: int
    headers: Mapping[str, str]
    body: bytes


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        return None


def _allowed_url(url: str) -> None:
    try:
        p = urllib.parse.urlsplit(url)
        if p.scheme != "https" or p.port not in {None, 443} or p.username or p.password or p.fragment:
            raise ValueError()
        allowed = {
            "api.xiaoheihe.cn": {"/account/wechat/login/v2/web_sso/", "/account/wechat/login_redirect/v2/web_sso/"},
            "login.xiaoheihe.cn": {"/"}, "open.xiaoheihe.cn": {"/zh_cn/workshop"},
            "open.weixin.qq.com": {"/connect/qrconnect"}, "long.open.weixin.qq.com": {"/connect/l/qrconnect"},
        }
        paths = allowed.get(p.hostname or "", set())
        image = p.hostname == "open.weixin.qq.com" and re.fullmatch(r"/connect/qrcode/[A-Za-z0-9_-]{1,200}", p.path)
        if p.path not in paths and not image:
            raise ValueError()
    except ValueError:
        raise _error("Heybox OAuth URL is outside the fixed official routes", "trust_boundary") from None


class HttpClient:
    def __init__(self, *, transport: Callable[..., HttpResponse] | None = None, now: Callable[[], float] = time.time):
        self.transport, self.now = transport, now

    def _send(self, request: urllib.request.Request, session: dict[str, Any], timeout: float) -> HttpResponse:
        jar = _jar(session)
        # Never use environment HTTP proxies for credential-bearing requests.
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), urllib.request.HTTPCookieProcessor(jar), _NoRedirect())
        try:
            if self.transport is not None:
                jar.add_cookie_header(request)
                result = self.transport(request, timeout=timeout)
            else:
                try:
                    response = opener.open(request, timeout=timeout)
                except urllib.error.HTTPError as exc:
                    response = exc
                with response:
                    body = response.read(_MAX_BODY + 1)
                    result = HttpResponse(response.code, response.headers, body)
            if len(result.body) > _MAX_BODY:
                raise _error("Heybox response exceeded the size limit", "protocol_error")
            if self.transport is not None:
                class CookieResponse:
                    def info(self):
                        return result.headers
                # Tests may supply an email Message to exercise Set-Cookie.
                if hasattr(result.headers, "get_all"):
                    jar.extract_cookies(CookieResponse(), request)
            session["cookies"] = _rows(jar)
            return result
        except FuploadError:
            raise
        except Exception:
            raise _error("Heybox HTTPS request failed; it was not retried", "network_error", endpoint=urllib.parse.urlsplit(request.full_url).path,
                         verification_required=request.get_method() == "POST") from None

    def fetch(self, url: str, session: dict[str, Any], timeout: float = 35) -> HttpResponse:
        _allowed_url(url)
        return self._send(urllib.request.Request(url, headers={"User-Agent": UA}), session, timeout)

    def request(self, route: str, method: str = "GET", *, query: Mapping[str, Any] | None = None,
                body: Mapping[str, Any] | None = None, session: dict[str, Any], renew: bool = False,
                timeout: float = 30) -> dict[str, Any]:
        method = method.upper()
        if (method, route) in AUTH_ROUTES:
            origin = API
        elif (method, route) in API_ROUTES:
            origin = WORKSHOP
        else:
            raise _error("Heybox method/path is outside the fixed API routes", "trust_boundary")
        query = dict(query or {})
        if _RESERVED.intersection(query) or ("heybox_id" in query and not (route == "/account/wechat/state/" and query["heybox_id"] == "")):
            raise _error("Heybox platform query fields cannot be overridden", "trust_boundary")
        if method == "GET" and body:
            raise _error("Heybox GET cannot carry a request body", "trust_boundary")
        timestamp = int(self.now())
        nonce = hashlib.md5(secrets.token_bytes(16)).hexdigest().upper()
        cookie_values = {r["name"]: r["value"] for r in _rows(_jar(session)) if r["domain"].lstrip(".") == "xiaoheihe.cn"}
        params = {"app": "heybox", "heybox_id": cookie_values.get("heybox_id", ""), "os_type": "web", "x_app": "heybox_website", "x_client_type": "weboutapp", "x_os_type": "Windows", "web_version": session.get("web_version", ""), "device_id": session.get("device_id", ""), "version": "999.0.4", "hkey": sign(route, timestamp, nonce), "_time": timestamp, "nonce": nonce, **query}
        if cookie_values.get("x_xhh_tokenid"):
            params["x_xhh_tokenid"] = cookie_values["x_xhh_tokenid"]
        request = urllib.request.Request(origin + route + "?" + urllib.parse.urlencode(params, doseq=True),
            data=urllib.parse.urlencode(body or {}, doseq=True).encode() if method == "POST" else None, method=method,
            headers={"User-Agent": UA, "Origin": LOGIN_ORIGIN, "Referer": LOGIN, "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8"})
        response = self._send(request, session, timeout)
        if response.status != 200:
            raise _error("Heybox API returned an unsuccessful HTTP status", "http_error", endpoint=route, http_status=response.status,
                         verification_required=method == "POST")
        try:
            value = json.loads(response.body)
            if not isinstance(value, dict):
                raise ValueError()
        except (ValueError, UnicodeError):
            raise _error("Heybox API returned invalid JSON", "protocol_error", endpoint=route,
                         verification_required=method == "POST") from None
        return value


class BlackboxHttpSession:
    """Business-provider adapter: restore once, never implicitly authenticate."""
    def __init__(self, *, store: Store | None = None, client: HttpClient | None = None):
        self.store, self.client = store or Store(), client or HttpClient()
        self.session: dict[str, Any] | None = None

    def renew(self) -> dict[str, Any]:
        with self.store.lock():
            return self._renew_locked()

    def _renew_locked(self) -> dict[str, Any]:
        current = self.store.load_active()
        if current is None:
            raise login_required()
        expected = identity(current)
        candidate = deepcopy(current)
        result = self.client.request("/account/restore_login", session=candidate)
        if result.get("status") != "ok":
            raise login_required()
        data = result.get("result")
        if not isinstance(data, dict):
            raise _error("Heybox restore returned an incomplete session", "protocol_error")
        apply_session(candidate, data, now=self.client.now(), expected_identity=expected)
        self.store.save_session(candidate)
        self.session = candidate
        return {"authenticated": True, "expires_at": candidate["expire_at"], "method": candidate.get("method", "sms")}

    def request(self, method: str, path: str, *, body: Mapping[str, Any] | None = None, query: Mapping[str, Any] | None = None) -> dict[str, Any]:
        if (method.upper(), path) not in API_ROUTES:
            raise _error("Heybox business route is not allowed", "trust_boundary")
        if self.session is None:
            self.renew()
        result = self.client.request(path, method, body=body, query=query, session=self.session)
        status = result.get("status")
        if status in {"login", "relogin"}:
            self.session = None
            raise login_required()
        if status != "ok":
            raise _error("Heybox API rejected the request; it was not retried", "api_error", endpoint=path,
                         business_code=status if isinstance(status, str) and re.fullmatch(r"[a-z_]{1,64}", status) else None)
        return result

    def close(self) -> None:
        self.session = None
