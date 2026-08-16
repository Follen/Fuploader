"""Persistent browser session and protocol for Heybox Workshop."""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import sys
import time
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Mapping
from urllib.parse import parse_qs, urlencode, urlsplit

from .errors import FuploadError, redact


WORKSHOP_URL = "https://open.xiaoheihe.cn/zh_cn/workshop"
LOGIN_ORIGIN = "https://login.xiaoheihe.cn"
API_ORIGIN = "https://workshopapi.xiaoheihe.cn"
API_ROUTES = frozenset({
    ("GET", "/wow/open_platform/module/list/"),
    ("GET", "/wow/open_platform/module/detail/"),
    ("POST", "/wow/open_platform/module/update/"),
    ("GET", "/wow/open_platform/module_version/list/"),
    ("POST", "/wow/open_platform/module_version/upsert/"),
    ("POST", "/wow/open_platform/module_version/delete/"),
    ("POST", "/wow/cos/upload/token/"),
})
API_PATHS = frozenset(path for _method, path in API_ROUTES)
WEB_QUERY_KEYS = frozenset({
    "_time", "app", "device_id", "heybox_id", "hkey", "nonce", "os_type",
    "version", "web_version", "x_app", "x_client_type", "x_os_type",
    "x_xhh_tokenid",
})
_ALPHABET = "AB45STUVWZEFGJ6CH01D237IXYPQRKLMN89"
_INTERACTIVE_STATUSES = frozenset({
    "lack_token", "show_captcha", "name_verify", "need_alipay_verify",
    "need_bind_phone", "need_phone_code",
})
_SECRET_MARKERS = (
    "token", "secret", "cookie", "nonce", "hkey", "pkey", "credential",
    "signature", "authorization", "authentication", "password", "device_id",
    "signed_url", "upload_url", "presigned",
)


class WebSessionState(str, Enum):
    HEADLESS_PROBE = "headless_probe"
    HEADED_LOGIN = "headed_login"
    READY = "ready"
    EXPIRED = "expired"
    FAILED = "failed"


def managed_profile_path() -> Path:
    """Return the private browser profile owned by Fuploader."""
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData/Local"))
        return base / "Fuploader" / "blackbox-chromium"
    return Path.home() / ".fupload" / "blackbox-chromium"


def managed_state_path() -> Path:
    return managed_profile_path().parent / "blackbox-web-state.json"


def _n8(value: str, limit: int) -> str:
    table = _ALPHABET[:limit]
    return "".join(table[ord(char) % len(table)] for char in value)


def _i8(value: str) -> str:
    return "".join(_ALPHABET[ord(char) % len(_ALPHABET)] for char in value)


def _interleave(parts: list[str]) -> str:
    width = max(map(len, parts))
    return "".join(part[index] for index in range(width) for part in parts if index < len(part))


def _mix(values: list[int]) -> list[int]:
    def p(value: int) -> int:
        return ((value << 1) ^ 27) & 255 if value & 128 else (value << 1) & 255

    def hm(value: int) -> int:
        return p(value) ^ value

    def qg(value: int) -> int:
        return hm(p(value))

    def dx(value: int) -> int:
        return qg(hm(p(value)))

    def mw(value: int) -> int:
        return dx(value) ^ qg(value) ^ hm(value)

    a, b, c, d, *rest = values
    return [
        mw(a) ^ dx(b) ^ qg(c) ^ hm(d),
        hm(a) ^ mw(b) ^ dx(c) ^ qg(d),
        qg(a) ^ hm(b) ^ mw(c) ^ dx(d),
        dx(a) ^ qg(b) ^ hm(c) ^ mw(d),
        *rest,
    ]


def web_hkey(path: str, timestamp: int, nonce: str) -> str:
    normalized = "/" + "/".join(part for part in path.split("/") if part) + "/"
    source = _interleave([_n8(str(timestamp), -2), _i8(normalized), _i8(nonce)])
    digest = hashlib.md5(source.encode()).hexdigest()
    return _n8(digest[:5], -4) + f"{sum(_mix([ord(char) for char in digest[-6:]])) % 100:02d}"


def redact_recursive(value: Any) -> Any:
    """Remove browser credentials and signed query strings from diagnostics."""
    if isinstance(value, Mapping):
        result = {}
        for key, item in value.items():
            if any(marker in str(key).lower() for marker in _SECRET_MARKERS):
                result[key] = "<redacted>"
            else:
                result[key] = redact_recursive(item)
        return result
    if isinstance(value, (list, tuple, set)):
        return [redact_recursive(item) for item in value]
    if isinstance(value, str):
        parsed = urlsplit(value)
        if parsed.scheme in {"http", "https"} and parsed.netloc and parsed.query:
            return f"{parsed.scheme}://{parsed.netloc}{parsed.path}?<redacted>"
        return redact(value)
    return value


class BlackboxWebSession:
    """Own a persistent Chromium profile and expose the Workshop protocol."""

    def __init__(
        self,
        *,
        login_timeout: float = 300,
        poll_interval: float = 1,
        browser_launcher: Callable[[bool, Path], Any] | None = None,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self.state = WebSessionState.HEADLESS_PROBE
        self.login_timeout = max(0.0, float(login_timeout))
        self.poll_interval = max(0.0, float(poll_interval))
        self._browser_launcher = browser_launcher
        self._sleep = sleep
        self._monotonic = monotonic
        self._context = None
        self._playwright = None

    @property
    def profile_path(self) -> Path:
        return managed_profile_path()

    def close(self) -> None:
        self._close_context()

    def __enter__(self) -> "BlackboxWebSession":
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

    def ensure_ready(self) -> None:
        if self.state == WebSessionState.READY and self._context is not None:
            return
        self._close_context()
        self._set_state(WebSessionState.HEADLESS_PROBE)
        try:
            self._context = self._launch(headless=True)
            self._open_workshop(self._context)
            if self._probe(self._context):
                self._set_state(WebSessionState.READY)
                return
            self._set_state(WebSessionState.EXPIRED, "web session requires login")
            self._login()
        except FuploadError:
            if self.state not in {WebSessionState.EXPIRED, WebSessionState.HEADED_LOGIN}:
                self._set_state(WebSessionState.FAILED, "browser session failed")
            raise
        except Exception as exc:
            self._set_state(WebSessionState.FAILED, "browser session failed")
            raise self._error("Workshop browser session failed", exc) from exc

    def request(
        self,
        method: str,
        path: str,
        body: Mapping[str, Any] | None = None,
        query: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        method, path = self._validate_request(method, path)
        self.ensure_ready()
        payload, response = self._protocol(self._context, method, path, body, query)
        if self._authenticated(payload, response):
            return payload
        if not self._needs_interaction(payload, response):
            raise self._response_error(path, payload, response, verification_required=method == "POST")

        self._set_state(WebSessionState.EXPIRED, "web session expired")
        if method == "POST":
            raise self._response_error(path, payload, response, verification_required=True)
        self._login()
        payload, response = self._protocol(self._context, method, path, body, query)
        if self._authenticated(payload, response):
            return payload
        if self._needs_interaction(payload, response):
            self._set_state(WebSessionState.EXPIRED, "web session remained expired")
        raise self._response_error(path, payload, response)

    def _login(self) -> None:
        self._close_context()
        self._set_state(WebSessionState.HEADED_LOGIN)
        try:
            context = self._launch(headless=False)
            self._context = context
            self._open_workshop(context)
            deadline = self._monotonic() + self.login_timeout
            while True:
                if self._headed_window_closed(context):
                    self._set_state(WebSessionState.EXPIRED, "headed login window closed")
                    raise FuploadError(
                        "Workshop login window was closed",
                        kind="authentication_error",
                        stage="headed_login",
                    )
                try:
                    ready = self._probe(context)
                except FuploadError as exc:
                    if exc.business_code != "network_error":
                        raise
                    ready = False
                if ready:
                    break
                if self._monotonic() >= deadline:
                    self._set_state(WebSessionState.EXPIRED, "headed login timed out")
                    raise FuploadError(
                        "Workshop web login timed out",
                        kind="authentication_error",
                        stage="headed_login",
                    )
                self._sleep(self.poll_interval)

            self._close_context()
            self._set_state(WebSessionState.HEADLESS_PROBE)
            self._context = self._launch(headless=True)
            self._open_workshop(self._context)
            if not self._probe(self._context):
                self._set_state(WebSessionState.EXPIRED, "web login did not persist")
                raise FuploadError(
                    "Workshop web login did not persist",
                    kind="authentication_error",
                    stage="headless_probe",
                )
            self._set_state(WebSessionState.READY)
        except FuploadError:
            self._close_context()
            raise
        except Exception as exc:
            self._set_state(WebSessionState.FAILED, "headed login failed")
            self._close_context()
            raise self._error("Workshop headed login failed", exc) from exc

    def _launch(self, *, headless: bool) -> Any:
        profile = self.profile_path
        profile.mkdir(parents=True, exist_ok=True)
        if self._browser_launcher is not None:
            return self._browser_launcher(headless, profile)
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise FuploadError(
                "Playwright is required for Workshop web login",
                kind="environment_error",
                stage="browser_launch",
                details={"dependency": "playwright"},
            ) from exc
        try:
            self._playwright = sync_playwright().start()
            return self._playwright.chromium.launch_persistent_context(
                user_data_dir=str(profile),
                headless=headless,
            )
        except Exception:
            if self._playwright is not None:
                self._playwright.stop()
                self._playwright = None
            raise

    @staticmethod
    def _open_workshop(context: Any) -> None:
        page = context.pages[0] if getattr(context, "pages", None) else context.new_page()
        page.goto(WORKSHOP_URL, wait_until="domcontentloaded")
        current = str(getattr(page, "url", "") or "")
        if current and not BlackboxWebSession._allowed_navigation(current):
            raise FuploadError(
                "Workshop browser navigated outside the fixed login flow",
                kind="authentication_error",
                stage="browser_navigation",
            )

    def _probe(self, context: Any) -> bool:
        payload, response = self._protocol(
            context, "GET", "/wow/open_platform/module/list/", None, None,
        )
        if self._authenticated(payload, response):
            modules = (payload.get("result") or {}).get("moduleList")
            if isinstance(modules, list):
                return True
            raise self._response_error(
                "/wow/open_platform/module/list/", payload, response,
                message="Workshop readiness response is invalid",
            )
        if self._needs_interaction(payload, response):
            return False
        raise self._response_error("/wow/open_platform/module/list/", payload, response)

    @staticmethod
    def _protocol(
        context: Any,
        method: str,
        path: str,
        body: Mapping[str, Any] | None,
        query: Mapping[str, Any] | None,
    ) -> tuple[dict[str, Any], Any]:
        caller_query = dict(query or {})
        reserved = sorted(WEB_QUERY_KEYS.intersection(caller_query))
        if reserved:
            raise FuploadError(
                "Workshop query overrides a managed protocol field",
                kind="validation_error",
                stage="protocol_validation",
                details={"fields": reserved},
            )
        cookie_rows = context.cookies([WORKSHOP_URL, API_ORIGIN])
        cookies = {str(item.get("name")): str(item.get("value") or "") for item in cookie_rows}
        heybox_id = cookies.get("user_heybox_id") or cookies.get("heybox_id") or ""
        risk_token = cookies.get("x_xhh_tokenid") or ""
        timestamp = int(time.time())
        nonce = hashlib.md5(
            f"{timestamp}{time.time_ns()}{secrets.token_hex(8)}".encode(),
        ).hexdigest().upper()
        params = {
            "app": "heybox",
            "heybox_id": heybox_id,
            "os_type": "web",
            "x_app": "heybox_website",
            "x_client_type": "weboutapp",
            "x_os_type": BlackboxWebSession._platform_name(),
            "web_version": "",
            "device_id": risk_token,
            "version": "999.0.4",
            "hkey": web_hkey(path, timestamp + 1, nonce),
            "_time": timestamp,
            "nonce": nonce,
            "x_xhh_tokenid": risk_token,
            **caller_query,
        }
        url = API_ORIGIN + path
        headers = {"Referer": WORKSHOP_URL}
        try:
            if method == "GET":
                response = context.request.get(url, params=params, headers=headers)
            else:
                response = context.request.post(
                    url,
                    params=params,
                    data=urlencode(dict(body or {}), doseq=True),
                    headers={
                        **headers,
                        "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
                    },
                )
        except Exception as exc:
            raise FuploadError(
                "Workshop web request failed",
                kind="operation_failed",
                stage="web_protocol",
                endpoint=path,
                business_code="network_error",
                verification_required=method == "POST",
                details=redact_recursive({"error": str(exc)}),
            ) from exc
        try:
            payload = response.json()
        except Exception:
            payload = {"status": "network_error"}
        return (payload if isinstance(payload, dict) else {}), response

    @staticmethod
    def _authenticated(payload: Mapping[str, Any], response: Any) -> bool:
        return bool(getattr(response, "ok", False)) and payload.get("status") == "ok"

    @staticmethod
    def _needs_interaction(payload: Mapping[str, Any], response: Any) -> bool:
        return (
            payload.get("status") in {"login", "relogin", "unauthorized", *_INTERACTIVE_STATUSES}
            or getattr(response, "status", 0) in {401, 403}
        )

    @staticmethod
    def _validate_request(method: str, path: str) -> tuple[str, str]:
        normalized_method = str(method).upper()
        if not isinstance(path, str) or (normalized_method, path) not in API_ROUTES:
            raise FuploadError(
                "Workshop protocol route is not allowed",
                kind="validation_error",
                stage="protocol_validation",
            )
        return normalized_method, path

    @staticmethod
    def _allowed_navigation(url: str) -> bool:
        parsed = urlsplit(url)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        if origin == "https://open.xiaoheihe.cn":
            return parsed.path in {"/zh_cn/workshop", "/zh_cn/workshop/"}
        if origin != LOGIN_ORIGIN or parsed.path != "/":
            return False
        query = parse_qs(parsed.query)
        return (
            query.get("origin") == ["heybox_open"]
            and query.get("redirect_url") in ([WORKSHOP_URL], [WORKSHOP_URL + "/"])
        )

    @staticmethod
    def _headed_window_closed(context: Any) -> bool:
        pages = getattr(context, "pages", None)
        if pages is None:
            return False
        if not pages:
            return True
        return all(callable(getattr(page, "is_closed", None)) and page.is_closed() for page in pages)

    @staticmethod
    def _platform_name() -> str:
        if os.name == "nt":
            return "Windows"
        if sys.platform == "darwin":
            return "macOS"
        return "Linux"

    def _set_state(self, state: WebSessionState, reason: str | None = None) -> None:
        self.state = state
        path = managed_state_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema": "fupload.blackbox.web-state.v1",
            "state": state.value,
            "updated_at": int(time.time()),
        }
        if reason:
            payload["reason"] = redact(reason)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
        temporary.replace(path)

    def _close_context(self) -> None:
        context, self._context = self._context, None
        if context is not None:
            try:
                context.close()
            except Exception:
                pass
        playwright, self._playwright = self._playwright, None
        if playwright is not None:
            try:
                playwright.stop()
            except Exception:
                pass

    @staticmethod
    def _response_error(
        path: str,
        payload: Mapping[str, Any],
        response: Any,
        *,
        message: str = "Workshop web request was rejected",
        verification_required: bool = False,
    ) -> FuploadError:
        status = payload.get("status")
        is_auth = BlackboxWebSession._needs_interaction(payload, response)
        return FuploadError(
            message,
            kind="authentication_error" if is_auth else "operation_failed",
            stage="web_protocol",
            endpoint=path,
            http_status=getattr(response, "status", None),
            business_code=status,
            verification_required=verification_required,
            details=redact_recursive({"response": payload}),
        )

    @staticmethod
    def _error(message: str, exc: Exception) -> FuploadError:
        return FuploadError(
            message,
            kind="environment_error",
            stage="browser_session",
            details=redact_recursive({"error": str(exc)}),
        )


__all__ = [
    "API_ORIGIN",
    "API_PATHS",
    "API_ROUTES",
    "WEB_QUERY_KEYS",
    "WORKSHOP_URL",
    "BlackboxWebSession",
    "WebSessionState",
    "managed_profile_path",
    "managed_state_path",
    "redact_recursive",
    "web_hkey",
]
