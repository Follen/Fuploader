"""Input and stable output helpers."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Dict

from .errors import FuploadError, ValidationError, redact


OUTPUT_SCHEMA = "fupload.output.v1"
_SENSITIVE_KEYS = {
    "token", "access_token", "refresh_token", "resource_token", "jwt", "jwttoken",
    "cookie", "set_cookie", "authorization", "authentication", "clientno", "client_no",
    "clientid", "client_id", "client_secret", "device_id", "device_proof", "cred",
    "credential", "signature", "x_amz_credential", "x_amz_signature",
    "x_amz_security_token", "signed_url", "upload_url", "presigneduri", "presigned_uri",
    "api_key", "auth_key", "password", "secret",
}
_RAW_CONTENT_KEYS = {
    "content", "wa_str", "t_wa_str", "raw_wtf", "wtf_zip", "download_url",
    "import_string",
}


class _DuplicateKey(ValueError):
    pass


def _strict_object(pairs: Any) -> Dict[str, Any]:
    result: Dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateKey(str(key))
        result[key] = value
    return result


def _reject_constant(value: str) -> Any:
    raise ValueError(value)


def read_json(path: str) -> Dict[str, Any]:
    if not path:
        raise ValidationError("--input is required", path="--input")
    try:
        text = sys.stdin.read() if path == "-" else Path(path).read_text(encoding="utf-8-sig")
        text = text.lstrip("\ufeff")
    except OSError as exc:
        raise ValidationError("cannot read input: %s" % exc, path="--input") from exc
    try:
        value = json.loads(
            text,
            object_pairs_hook=_strict_object,
            parse_constant=_reject_constant,
        )
    except _DuplicateKey as exc:
        raise ValidationError("input contains duplicate key: %s" % exc, path="--input") from exc
    except json.JSONDecodeError as exc:
        raise ValidationError(
            "input must be valid JSON: line %d column %d" % (exc.lineno, exc.colno),
            path="--input",
        ) from exc
    except ValueError as exc:
        raise ValidationError("input contains a non-standard numeric value", path="--input") from exc
    if not isinstance(value, dict):
        raise ValidationError("input document must be a JSON object")
    return value


def write_output(platform: str, operation: str, data: Any, *, dry_run: bool = False) -> None:
    payload = {
        "schema": OUTPUT_SCHEMA,
        "platform": platform,
        "operation": operation,
        "success": True,
        "dry_run": bool(dry_run),
        "data": sanitize_output(data),
    }
    # Stable ASCII JSON avoids inheriting a Windows console code-page contract.
    print(json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False))


def sanitize_output(value: Any) -> Any:
    if isinstance(value, dict):
        result: Dict[str, Any] = {}
        for key, item in value.items():
            normalized = str(key).replace("-", "_").lower()
            if normalized in {"token_present", "token_decrypted", "token_nonempty", "api_ready"} and isinstance(item, bool):
                result[key] = item
            elif normalized in _SENSITIVE_KEYS or any(
                marker in normalized
                for marker in ("token", "cookie", "credential", "signature", "password", "secret")
            ):
                result[key] = "[REDACTED]"
            elif normalized in _RAW_CONTENT_KEYS:
                text = str(item or "").encode("utf-8")
                result[str(key) + "_summary"] = {
                    "bytes": len(text),
                    "sha256": hashlib.sha256(text).hexdigest(),
                }
            else:
                result[key] = sanitize_output(item)
        return result
    if isinstance(value, list):
        return [sanitize_output(item) for item in value]
    if isinstance(value, str):
        return redact(value)
    return value


def write_error(platform: str, operation: str, error: BaseException) -> None:
    if isinstance(error, FuploadError):
        detail = sanitize_output(error.as_dict())
    else:
        detail = sanitize_output(FuploadError(str(error)).as_dict())
    payload = {
        "schema": OUTPUT_SCHEMA,
        "platform": platform,
        "operation": operation,
        "success": False,
        "error": detail,
    }
    print(json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False))
