"""Small standard-library JSON and multipart HTTP client."""

from __future__ import annotations

import json
import mimetypes
import os
import secrets
import urllib.error
import urllib.request
from typing import Any, Dict, Mapping, Optional

from .errors import FuploadError
from .trust import official_opener, require_official_url


_IMAGE_CONTENT_TYPES = {
    ".bmp": "image/bmp",
    ".gif": "image/gif",
    ".jpeg": "image/jpeg",
    ".jpg": "image/jpeg",
    ".png": "image/png",
    ".svg": "image/svg+xml",
    ".webp": "image/webp",
}


def _http_error_details(raw: bytes, fallback: str) -> tuple[str, Any]:
    """Extract a server error only from a conforming UTF-8 JSON object."""
    try:
        parsed = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return fallback, None
    if not isinstance(parsed, dict):
        return fallback, None
    message = parsed.get("message") or parsed.get("msg") or fallback
    return str(message), parsed.get("code")


def json_request(
    url: str,
    *,
    method: str = "GET",
    headers: Optional[Mapping[str, str]] = None,
    body: Any = None,
    timeout: int = 60,
    trusted_service: Optional[str] = None,
) -> Any:
    data = None
    request_headers = dict(headers or {})
    if body is not None:
        data = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        request_headers.setdefault("Content-Type", "application/json")
    request = urllib.request.Request(url, data=data, method=method, headers=request_headers)
    try:
        response_context = (
            official_opener(require_official_url(url, trusted_service)).open(request, timeout=timeout)
            if trusted_service else urllib.request.urlopen(request, timeout=timeout)
        )
        with response_context as response:
            raw = response.read()
            status = response.status
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        message, code = _http_error_details(raw, "HTTP %d" % exc.code)
        raise FuploadError(message, endpoint=url, http_status=exc.code, business_code=code) from exc
    except (OSError, urllib.error.URLError) as exc:
        raise FuploadError(
            "network result is uncertain: %s" % exc,
            endpoint=url,
            verification_required=method not in ("GET", "HEAD"),
        ) from exc
    if status < 200 or status >= 300:
        raise FuploadError("HTTP %d" % status, endpoint=url, http_status=status)
    if not raw:
        return {}
    try:
        return json.loads(raw.decode("utf-8"))
    except ValueError as exc:
        raise FuploadError("response was not valid JSON", endpoint=url, http_status=status) from exc


def multipart_request(
    url: str,
    file_path: str,
    *,
    file_field: str = "file",
    fields: Optional[Mapping[str, str]] = None,
    headers: Optional[Mapping[str, str]] = None,
    timeout: int = 600,
    trusted_service: Optional[str] = None,
) -> Any:
    boundary = "----fupload-%s" % secrets.token_hex(16)
    chunks = []
    for key, value in (fields or {}).items():
        chunks.extend([
            ("--%s\r\n" % boundary).encode(),
            ('Content-Disposition: form-data; name="%s"\r\n\r\n' % key).encode(),
            str(value).encode("utf-8"), b"\r\n",
        ])
    filename = os.path.basename(file_path)
    suffix = os.path.splitext(filename)[1].lower()
    content_type = _IMAGE_CONTENT_TYPES.get(suffix) or mimetypes.guess_type(filename)[0] or "application/octet-stream"
    chunks.extend([
        ("--%s\r\n" % boundary).encode(),
        ('Content-Disposition: form-data; name="%s"; filename="%s"\r\n' % (file_field, filename)).encode("utf-8"),
        ("Content-Type: %s\r\n\r\n" % content_type).encode(),
    ])
    with open(file_path, "rb") as handle:
        chunks.append(handle.read())
    chunks.extend([b"\r\n", ("--%s--\r\n" % boundary).encode()])
    body = b"".join(chunks)
    request_headers = dict(headers or {})
    request_headers["Content-Type"] = "multipart/form-data; boundary=%s" % boundary
    request = urllib.request.Request(url, data=body, method="POST", headers=request_headers)
    try:
        response_context = (
            official_opener(require_official_url(url, trusted_service)).open(request, timeout=timeout)
            if trusted_service else urllib.request.urlopen(request, timeout=timeout)
        )
        with response_context as response:
            raw = response.read()
            status = response.status
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        message, code = _http_error_details(raw, "HTTP %d" % exc.code)
        raise FuploadError(message, endpoint=url, http_status=exc.code, business_code=code) from exc
    except (OSError, urllib.error.URLError) as exc:
        raise FuploadError(
            "upload result is uncertain: %s" % exc,
            endpoint=url,
            verification_required=True,
        ) from exc
    try:
        return json.loads(raw.decode("utf-8")) if raw else {}
    except ValueError as exc:
        raise FuploadError("upload response was not valid JSON", endpoint=url, http_status=status) from exc
