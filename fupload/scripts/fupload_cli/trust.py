"""Platform trust primitives for credential and executable boundaries."""

from __future__ import annotations

import ctypes
import json
import os
import re
import subprocess
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Tuple

from .errors import FuploadError


NEWBEE_ORIGINS = {
    "creator": "https://api.newbeebox.com",
    "auth": "https://api.next.newbeebox.com",
    "next": "https://api.next.newbeebox.com",
    "metadata": "https://cdn2.newbeebox.com",
    "upload": "https://api.next.newbeebox.com",
}
ALLOWED_DD_PUBLISHERS = (
    "netease (hangzhou) network co., ltd",
)
_SUBJECT_ORGANIZATION = re.compile(r"(?:^|,\s*)O=(?:\"([^\"]+)\"|([^,]+))", re.IGNORECASE)


def _origin(value: str) -> Tuple[str, str, int]:
    parsed = urllib.parse.urlsplit(value)
    if parsed.scheme.casefold() != "https" or not parsed.hostname:
        raise FuploadError("untrusted HTTPS origin", kind="trust_boundary")
    host = parsed.hostname.casefold().rstrip(".")
    try:
        port = parsed.port or 443
    except ValueError as exc:
        raise FuploadError("origin contains an invalid port", kind="trust_boundary") from exc
    if parsed.username or parsed.password or parsed.fragment:
        raise FuploadError("origin contains unsupported URL components", kind="trust_boundary")
    return parsed.scheme.casefold(), host, port


def require_official_url(value: str, service: str, *, path_prefix: str = "") -> str:
    expected = _origin(NEWBEE_ORIGINS[service])
    actual = _origin(value)
    if actual != expected:
        raise FuploadError(
            "untrusted %s origin" % service,
            kind="trust_boundary",
            endpoint="%s://%s:%d" % actual,
        )
    parsed = urllib.parse.urlsplit(value)
    if path_prefix and not parsed.path.startswith(path_prefix):
        raise FuploadError("untrusted %s path" % service, kind="trust_boundary")
    return value.rstrip("/")


def same_origin_redirect(original: str, redirected: str) -> bool:
    try:
        return _origin(original) == _origin(redirected)
    except (FuploadError, ValueError):
        return False


class SameOriginRedirectHandler(urllib.request.HTTPRedirectHandler):
    def __init__(self, allowed_origin: str) -> None:
        super().__init__()
        self.allowed_origin = allowed_origin

    def redirect_request(self, req: urllib.request.Request, fp: Any, code: int, msg: str, headers: Mapping[str, str], newurl: str) -> Optional[urllib.request.Request]:
        if not same_origin_redirect(req.full_url, newurl) or not same_origin_redirect(self.allowed_origin, newurl):
            raise FuploadError("cross-origin redirect rejected", kind="trust_boundary")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def official_opener(origin: str) -> urllib.request.OpenerDirector:
    return urllib.request.build_opener(SameOriginRedirectHandler(origin))


def _known_folder_roaming() -> Path:
    if os.name != "nt":
        raise FuploadError("Windows Roaming AppData is unavailable", kind="authentication_error")
    try:
        shell32 = ctypes.WinDLL("shell32", use_last_error=True)
        ole32 = ctypes.WinDLL("ole32", use_last_error=True)
        folder_id = ctypes.c_ubyte * 16
        # FOLDERID_RoamingAppData: 3EB685DB-65F9-4CF6-A03A-E3EF65729F3D.
        guid = folder_id(0xDB, 0x85, 0xB6, 0x3E, 0xF9, 0x65, 0xF6, 0x4C,
                         0xA0, 0x3A, 0xE3, 0xEF, 0x65, 0x72, 0x9F, 0x3D)
        shell32.SHGetKnownFolderPath.argtypes = [ctypes.POINTER(folder_id), ctypes.c_uint32, ctypes.c_void_p, ctypes.POINTER(ctypes.c_wchar_p)]
        shell32.SHGetKnownFolderPath.restype = ctypes.c_long
        value = ctypes.c_wchar_p()
        result = shell32.SHGetKnownFolderPath(ctypes.byref(guid), 0, None, ctypes.byref(value))
        if result != 0:
            raise OSError(result, "SHGetKnownFolderPath failed")
        path = Path(value.value)
        ole32.CoTaskMemFree(value)
        return path
    except (AttributeError, OSError, TypeError, ValueError) as exc:
        raise FuploadError("Windows Roaming AppData could not be resolved", kind="authentication_error") from exc


def _known_folder_local() -> Path:
    if os.name != "nt":
        raise FuploadError("Windows Local AppData is unavailable", kind="trust_boundary")
    try:
        shell32 = ctypes.WinDLL("shell32", use_last_error=True)
        ole32 = ctypes.WinDLL("ole32", use_last_error=True)
        folder_id = ctypes.c_ubyte * 16
        # FOLDERID_LocalAppData: F1B32785-6FBA-4FCF-9D55-7B8E7F157091.
        guid = folder_id(0x85, 0x27, 0xB3, 0xF1, 0xBA, 0x6F, 0xCF, 0x4F,
                         0x9D, 0x55, 0x7B, 0x8E, 0x7F, 0x15, 0x70, 0x91)
        shell32.SHGetKnownFolderPath.argtypes = [ctypes.POINTER(folder_id), ctypes.c_uint32, ctypes.c_void_p, ctypes.POINTER(ctypes.c_wchar_p)]
        shell32.SHGetKnownFolderPath.restype = ctypes.c_long
        value = ctypes.c_wchar_p()
        result = shell32.SHGetKnownFolderPath(ctypes.byref(guid), 0, None, ctypes.byref(value))
        if result != 0:
            raise OSError(result, "SHGetKnownFolderPath failed")
        path = Path(value.value)
        ole32.CoTaskMemFree(value)
        return path
    except (AttributeError, OSError, TypeError, ValueError) as exc:
        raise FuploadError("Windows Local AppData could not be resolved", kind="trust_boundary") from exc


def trusted_roaming_dir(*parts: str) -> Path:
    root = _known_folder_roaming().resolve()
    current = root
    for part in parts:
        current = current / part
        if current.exists() and _is_reparse_point(current):
            raise FuploadError("trusted application path contains a reparse point", kind="trust_boundary")
    resolved = current.resolve(strict=False)
    if resolved != root and root not in resolved.parents:
        raise FuploadError("trusted application path escaped Known Folder", kind="trust_boundary")
    return resolved


def trusted_local_dir(*parts: str) -> Path:
    root = _known_folder_local().resolve()
    current = root
    for part in parts:
        current = current / part
        if current.exists() and _is_reparse_point(current):
            raise FuploadError("trusted application path contains a reparse point", kind="trust_boundary")
    resolved = current.resolve(strict=False)
    if resolved != root and root not in resolved.parents:
        raise FuploadError("trusted application path escaped Known Folder", kind="trust_boundary")
    return resolved


def _is_reparse_point(path: Path) -> bool:
    if path.is_symlink():
        return True
    try:
        attributes = os.stat(str(path), follow_symlinks=False).st_file_attributes
    except (AttributeError, OSError):
        return False
    return bool(attributes & 0x400)


def _powershell_path() -> str:
    if os.name != "nt":
        raise FuploadError("DD executable signature validation requires Windows", kind="trust_boundary")
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.GetWindowsDirectoryW.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32]
    kernel32.GetWindowsDirectoryW.restype = ctypes.c_uint32
    buffer = ctypes.create_unicode_buffer(32768)
    length = kernel32.GetWindowsDirectoryW(buffer, len(buffer))
    if not length:
        raise FuploadError("Windows system directory could not be resolved", kind="trust_boundary")
    return str(Path(buffer.value) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe")


def verify_dd_executable(executable: Path) -> Dict[str, str]:
    powershell = _powershell_path()
    script = (
        "Import-Module Microsoft.PowerShell.Security -ErrorAction Stop; "
        "$OutputEncoding = [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false); "
        "$s=Get-AuthenticodeSignature -LiteralPath '%s'; "
        "[pscustomobject]@{Status=[string]$s.Status;Subject=[string]$s.SignerCertificate.Subject} "
        "| ConvertTo-Json -Compress"
    ) % str(executable).replace("'", "''")
    try:
        environment = os.environ.copy()
        windows_root = str(Path(powershell).parents[3])
        environment["PSModulePath"] = windows_root + "\\System32\\WindowsPowerShell\\v1.0\\Modules"
        completed = subprocess.run(
            [powershell, "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True, text=True, encoding="utf-8", errors="strict",
            timeout=20, check=False, env=environment,
        )
        if completed.returncode != 0:
            raise FuploadError("DD Authenticode verification process failed", kind="trust_boundary")
        payload = json.loads((completed.stdout or "").strip() or "{}")
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        raise FuploadError("DD Authenticode verification failed", kind="trust_boundary") from exc
    status = str(payload.get("Status") or "")
    subject = str(payload.get("Subject") or "")
    match = _SUBJECT_ORGANIZATION.search(subject)
    publisher = (match.group(1) or match.group(2)).strip() if match else ""
    normalized_publisher = publisher.casefold()
    if status.casefold() != "valid" or normalized_publisher not in ALLOWED_DD_PUBLISHERS:
        raise FuploadError("DD executable has no trusted official signature", kind="trust_boundary")
    return {"status": status, "publisher": publisher}
