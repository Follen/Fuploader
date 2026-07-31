"""Reuse the current user's NewBeeBox desktop authentication state."""

from __future__ import annotations

import base64
import json
import os
import socket
import tempfile
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Dict, Tuple

from .errors import FuploadError
from .transport import json_request


API_BASE = os.environ.get("FUPLOAD_NEWBEE_API_BASE", "https://api.newbeebox.com").rstrip("/")
AUTH_BASE = os.environ.get("FUPLOAD_NEWBEE_AUTH_BASE", "https://api.next.newbeebox.com/auth").rstrip("/")


def _auth_dir() -> Path:
    configured = os.environ.get("FUPLOAD_NEWBEE_AUTH_DIR")
    if configured:
        return Path(configured)
    appdata = os.environ.get("APPDATA")
    if not appdata:
        raise FuploadError("APPDATA is not set; NewBeeBox login state cannot be located", kind="authentication_error")
    return Path(appdata) / "NewBeeBox" / "auth-store"


def _read(name: str, optional: bool = False) -> str:
    try:
        return (_auth_dir() / name).read_text(encoding="utf-8").strip()
    except OSError as exc:
        if optional:
            return ""
        raise FuploadError(
            "NewBeeBox desktop login state is missing; sign in with the desktop client first",
            kind="authentication_error",
        ) from exc


def _jwt_fresh(token: str, leeway: int = 30) -> bool:
    try:
        part = token.split(".")[1]
        part += "=" * ((4 - len(part) % 4) % 4)
        claims = json.loads(base64.urlsafe_b64decode(part.encode()).decode("utf-8"))
        return int(claims["exp"]) > int(time.time()) + leeway
    except (ValueError, KeyError, IndexError, TypeError):
        return False


def _atomic_write(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".fupload-credential-", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(value)
        os.replace(temporary, path)
    finally:
        try:
            os.unlink(temporary)
        except OSError:
            pass


def _refresh(access: str, refresh: str, proof: str) -> Tuple[str, str, str]:
    if not refresh:
        raise FuploadError("NewBeeBox refresh token is missing; sign in again", kind="authentication_error")
    form = {
        "client_id": "nbb-desktop", "grant_type": "refresh_token", "refresh_token": refresh,
        "device_name": socket.gethostname(), "device_type": "desktop",
    }
    if proof:
        form["device_proof"] = proof
    request = urllib.request.Request(
        AUTH_BASE + "/connect/token",
        data=urllib.parse.urlencode(form).encode(),
        method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        raise FuploadError("cannot refresh NewBeeBox desktop session", kind="authentication_error") from exc
    access = str(payload.get("access_token") or "")
    refresh = str(payload.get("refresh_token") or refresh)
    proof = str(payload.get("device_proof") or proof)
    if not access:
        raise FuploadError("NewBeeBox refresh response did not contain an access token", kind="authentication_error")
    for name, value in (("access-token", access), ("refresh-token", refresh), ("device-proof", proof)):
        if value:
            _atomic_write(_auth_dir() / name, value)
    return access, refresh, proof


def creator_headers() -> Dict[str, str]:
    access, refresh, proof = _read("access-token"), _read("refresh-token"), _read("device-proof", True)
    if not _jwt_fresh(access):
        access, refresh, proof = _refresh(access, refresh, proof)
    handoff = json_request(
        API_BASE + "/v3/user/auth2web", method="POST",
        headers={"Authorization": "Bearer " + access, "boxversion": "1.1.17", "Accept-Language": "zh-CN"},
        body={},
    )
    if handoff.get("code") != 1:
        raise FuploadError("NewBeeBox Creator handoff failed", kind="authentication_error")
    web_code = str((handoff.get("data") or {}).get("code") or "")
    exchange = json_request(
        API_BASE + "/v3/user/exchange_web_code", method="POST",
        headers={"appId": "6", "Accept-Language": "zh-CN"}, body={"code": web_code},
    )
    data = exchange.get("data") or {}
    author = str(data.get("token") or "")
    initial = str(data.get("jwtToken") or "")
    if exchange.get("code") != 1 or not author:
        raise FuploadError("NewBeeBox Creator token exchange failed", kind="authentication_error")
    headers = {"appId": "6", "token": author, "Accept-Language": "zh-CN"}
    if initial:
        headers["Authorization"] = "Bearer " + initial
    resource = json_request(API_BASE + "/v3/user/refresh_web_resource_token", method="POST", headers=headers, body={})
    token = str((resource.get("data") or {}).get("resource_token") or "")
    if resource.get("code") != 1 or not token:
        raise FuploadError("NewBeeBox Creator resource token refresh failed", kind="authentication_error")
    return {"appId": "6", "token": author, "Authorization": "Bearer " + token, "Accept-Language": "zh-CN"}
