"""Input and stable output helpers."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict

from .errors import FuploadError, ValidationError, redact


OUTPUT_SCHEMA = "fupload.output.v1"


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
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False))


def sanitize_output(value: Any) -> Any:
    sensitive_keys = {
        "token", "access_token", "refresh_token", "resource_token", "jwt", "jwtToken",
        "cookie", "set-cookie", "authorization", "authentication", "clientNo", "client_no",
        "cred", "credential", "signed_url", "upload_url", "presignedUri", "presigned_uri",
    }
    raw_content_keys = {"wa_str", "t_wa_str", "raw_wtf", "wtf_zip", "download_url"}
    if isinstance(value, dict):
        result: Dict[str, Any] = {}
        for key, item in value.items():
            lower = str(key).lower()
            if key in sensitive_keys or lower in {x.lower() for x in sensitive_keys}:
                result[key] = "[REDACTED]"
            elif key in raw_content_keys or lower in {x.lower() for x in raw_content_keys}:
                text = str(item or "")
                result[key + "_summary"] = {"length": len(text)}
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
        detail = error.as_dict()
    else:
        detail = FuploadError(str(error)).as_dict()
    payload = {
        "schema": OUTPUT_SCHEMA,
        "platform": platform,
        "operation": operation,
        "success": False,
        "error": detail,
    }
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False))
