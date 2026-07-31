"""Stable, redacted CLI errors."""

from __future__ import annotations

import re
from typing import Any, Dict, Optional


_BEARER = re.compile(r"(?i)Bearer\s+[A-Za-z0-9._~+/=-]+")
_JWT = re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]+\b")
_SIGNED = re.compile(r"(?i)(X-Amz-(?:Credential|Signature)=)[^&\s]+")
_SIGNED_TOKEN = re.compile(r"(?i)(X-Amz-(?:Security-Token|Date|Expires)=)[^&\s]+")
_URL_TOKEN = re.compile(r"(?i)([?&](?:token|jwt|clientNo|client_no|signature|credential)=)[^&\s]+")
_COOKIE = re.compile(r"(?i)(Cookie|Set-Cookie|Authentication|Authorization)(\s*[:=]\s*)[^\s;]+")
_TOKEN_PAIR = re.compile(r"(?i)(token|clientNo|client_no|login[_-]?code|jwt|credential)(\s*[:=]\s*)[A-Za-z0-9._~+/=-]{6,}")


def redact(value: str) -> str:
    value = _BEARER.sub("Bearer [REDACTED]", str(value))
    value = _JWT.sub("[REDACTED_JWT]", value)
    value = _SIGNED.sub(r"\1[REDACTED]", value)
    value = _SIGNED_TOKEN.sub(r"\1[REDACTED]", value)
    value = _URL_TOKEN.sub(r"\1[REDACTED]", value)
    value = _COOKIE.sub(r"\1\2[REDACTED]", value)
    return _TOKEN_PAIR.sub(r"\1\2[REDACTED]", value)[:1000]


class FuploadError(Exception):
    def __init__(
        self,
        message: str,
        *,
        kind: str = "operation_failed",
        stage: Optional[str] = None,
        endpoint: Optional[str] = None,
        http_status: Optional[int] = None,
        business_code: Optional[Any] = None,
        verification_required: bool = False,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(redact(message))
        self.kind = kind
        self.stage = stage
        self.endpoint = endpoint
        self.http_status = http_status
        self.business_code = business_code
        self.verification_required = verification_required
        self.details = details or {}

    def as_dict(self) -> Dict[str, Any]:
        result: Dict[str, Any] = {
            "kind": self.kind,
            "message": redact(str(self)),
            "verification_required": bool(self.verification_required),
        }
        if self.stage:
            result["stage"] = self.stage
        if self.endpoint:
            result["endpoint"] = self.endpoint
        if self.http_status is not None:
            result["http_status"] = self.http_status
        if self.business_code is not None:
            result["business_code"] = self.business_code
        if self.details:
            result["details"] = self.details
        return result

    @classmethod
    def from_dict(cls, value: Dict[str, Any]) -> "FuploadError":
        return cls(
            str(value.get("message") or "operation failed"),
            kind=str(value.get("kind") or "operation_failed"),
            stage=str(value.get("stage")) if value.get("stage") else None,
            endpoint=str(value.get("endpoint")) if value.get("endpoint") else None,
            http_status=value.get("http_status"),
            business_code=value.get("business_code"),
            verification_required=bool(value.get("verification_required")),
            details=value.get("details") if isinstance(value.get("details"), dict) else None,
        )


class ValidationError(FuploadError):
    def __init__(self, message: str, *, path: str = "$") -> None:
        super().__init__(message, kind="validation_error", stage="dependency_get", details={"path": path})
