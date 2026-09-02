"""NetEase DD provider using the official native client as a sidecar."""

from __future__ import annotations

import copy
from decimal import Decimal, InvalidOperation
import hashlib
import json
import os
import queue
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple
import urllib.parse

from .errors import FuploadError, ValidationError
from .trust import trusted_local_dir, trusted_roaming_dir, verify_dd_executable


EXPECTED_DD_VERSION = os.environ.get("FUPLOAD_DD_EXPECTED_VERSION", "any")
LIFE_TYPES = [
    {"name": "7 days", "value": "seven_day"},
    {"name": "14 days", "value": "fourteen_day"},
    {"name": "30 days", "value": "thirty_day"},
    {"name": "60 days", "value": "sixty_day"},
    {"name": "90 days", "value": "ninety_day"},
    {"name": "forever", "value": "forever"},
]

_OMIT_FILE_NAME = object()
_IMAGE_MIME = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
}
def _running_dd_dirs() -> List[Path]:
    if os.name != "nt":
        return []
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    snapshot = kernel32.CreateToolhelp32Snapshot(0x00000002, 0)
    invalid_handle = wintypes.HANDLE(-1).value
    if snapshot == invalid_handle:
        return []

    class ProcessEntry(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD),
            ("cntUsage", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD),
            ("th32DefaultHeapID", ctypes.c_size_t),
            ("th32ModuleID", wintypes.DWORD),
            ("cntThreads", wintypes.DWORD),
            ("th32ParentProcessID", wintypes.DWORD),
            ("pcPriClassBase", ctypes.c_long),
            ("dwFlags", wintypes.DWORD),
            ("szExeFile", ctypes.c_wchar * 260),
        ]

    kernel32.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(ProcessEntry)]
    kernel32.Process32FirstW.restype = wintypes.BOOL
    kernel32.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(ProcessEntry)]
    kernel32.Process32NextW.restype = wintypes.BOOL
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.QueryFullProcessImageNameW.argtypes = [
        wintypes.HANDLE, wintypes.DWORD,
        wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD),
    ]
    kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
    paths: List[Path] = []
    entry = ProcessEntry()
    entry.dwSize = ctypes.sizeof(entry)
    try:
        more = bool(kernel32.Process32FirstW(snapshot, ctypes.byref(entry)))
        while more:
            if entry.szExeFile.casefold() == "netease_dd.exe":
                process = kernel32.OpenProcess(0x1000, False, entry.th32ProcessID)
                if process:
                    try:
                        size = wintypes.DWORD(32768)
                        buffer = ctypes.create_unicode_buffer(size.value)
                        if kernel32.QueryFullProcessImageNameW(process, 0, buffer, ctypes.byref(size)):
                            paths.append(Path(buffer.value).parent)
                    finally:
                        kernel32.CloseHandle(process)
            more = bool(kernel32.Process32NextW(snapshot, ctypes.byref(entry)))
    finally:
        kernel32.CloseHandle(snapshot)
    return paths


def _registry_dd_dirs() -> List[Path]:
    if os.name != "nt":
        return []
    import winreg

    paths: List[Path] = []
    locations = (
        (winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_LOCAL_MACHINE, r"Software\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_LOCAL_MACHINE, r"Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
    )
    for hive, key_name in locations:
        try:
            root = winreg.OpenKey(hive, key_name)
        except OSError:
            continue
        with root:
            for index in range(4096):
                try:
                    child_name = winreg.EnumKey(root, index)
                except OSError:
                    break
                try:
                    child = winreg.OpenKey(root, child_name)
                except OSError:
                    continue
                with child:
                    try:
                        display_name = str(winreg.QueryValueEx(child, "DisplayName")[0])
                    except OSError:
                        display_name = ""
                    normalized = display_name.casefold().replace(" ", "")
                    if not any(name in normalized for name in ("neteasedd", "网易dd", "ccvoicehub")):
                        continue
                    for value_name in ("InstallLocation", "DisplayIcon"):
                        try:
                            raw = str(winreg.QueryValueEx(child, value_name)[0]).strip().strip('"')
                        except OSError:
                            continue
                        raw = raw.rsplit(",", 1)[0].strip().strip('"')
                        path = Path(raw)
                        paths.append(path.parent if path.suffix.lower() == ".exe" else path)
    return paths


def _user_config_dd_dirs() -> List[Path]:
    paths: List[Path] = []
    roots: List[Path] = []
    for resolver in (trusted_roaming_dir, trusted_local_dir):
        try:
            roots.append(resolver("CCVoiceHub"))
        except FuploadError:
            continue
    for root in roots:
        for name in ("appconfig.json", "localGameConfig.json"):
            source = root / name
            try:
                if source.stat().st_size > 1024 * 1024:
                    continue
                value = json.loads(source.read_text(encoding="utf-8-sig"))
            except (OSError, ValueError):
                continue
            pending = [value]
            visited = 0
            while pending and visited < 10000:
                item = pending.pop()
                visited += 1
                if isinstance(item, dict):
                    pending.extend(item.values())
                elif isinstance(item, list):
                    pending.extend(item)
                elif isinstance(item, str) and ("netease_dd" in item.casefold() or "neteasedd" in item.casefold()):
                    path = Path(item.strip().strip('"'))
                    paths.append(path.parent if path.suffix.lower() == ".exe" else path)
    return paths


def _discovery_roots() -> List[Path]:
    roots: List[Path] = []
    roots.extend(_running_dd_dirs())
    roots.extend(_registry_dd_dirs())
    roots.extend(_user_config_dd_dirs())
    try:
        roots.append(trusted_local_dir("NetEaseDD"))
    except FuploadError:
        pass
    roots.extend((
        Path(os.environ.get("PROGRAMFILES", "")) / "NetEaseDD",
        Path(os.environ.get("PROGRAMFILES(X86)", "")) / "NetEaseDD",
        Path("C:/NetEase/NetEaseDD"), Path("D:/Software/NetEaseDD"), Path("D:/NetEaseDD"),
    ))
    return roots


def discover_dd_info() -> Tuple[Path, Dict[str, str]]:
    candidates: List[Path] = []
    for root in _discovery_roots():
        if str(root) in (".", "") or not root.exists():
            continue
        candidates.append(root)
        try:
            candidates.extend(path.parent for path in root.glob("*/netease_dd.exe"))
        except OSError:
            pass
    seen = set()
    valid: List[Tuple[Path, Dict[str, str]]] = []
    for candidate in candidates:
        try:
            resolved = candidate.resolve()
        except OSError:
            continue
        if resolved in seen:
            continue
        seen.add(resolved)
        version = resolved.name
        if (resolved / "netease_dd.exe").is_file() and (resolved / "ccvoicehub.res").exists() and (resolved / "ccsub64").is_dir():
            if EXPECTED_DD_VERSION and EXPECTED_DD_VERSION != "any" and version != EXPECTED_DD_VERSION:
                continue
            try:
                signature = verify_dd_executable(resolved / "netease_dd.exe")
            except FuploadError:
                continue
            valid.append((resolved, signature))
    if not valid:
        raise FuploadError(
            "cannot locate a valid, officially signed NetEase DD installation",
            kind="installation_not_found",
        )
    return sorted(valid, key=lambda item: item[0].name)[-1]


def discover_dd() -> Path:
    return discover_dd_info()[0]


def state_dir() -> Path:
    result = trusted_roaming_dir("CCVoiceHub", "Fupload")
    result.mkdir(parents=True, exist_ok=True)
    return result


class Sidecar:
    def __init__(self) -> None:
        self.dd_dir, self.signature = discover_dd_info()
        self.process: Optional[subprocess.Popen[str]] = None
        self.counter = 0
        self.credential_kind: Optional[str] = None
        self.lock_handle = None
        self.responses: queue.Queue[Any] = queue.Queue()
        self.reader_thread: Optional[threading.Thread] = None

    def __enter__(self) -> "Sidecar":
        self._lock()
        executable = self.dd_dir / "netease_dd.exe"
        script = Path(__file__).with_name("dd_sidecar.py")
        environment = os.environ.copy()
        environment["NETEASE_DD_DIR"] = str(self.dd_dir)
        environment["FUPLOAD_DD_DEVICE_STATE"] = str(state_dir() / "sidecar-device.json")
        self.process = subprocess.Popen(
            [str(executable), str(script)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, text=True, encoding="utf-8", errors="strict",
            env=environment, cwd=str(self.dd_dir),
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        self.reader_thread = threading.Thread(target=self._read_results, daemon=True)
        self.reader_thread.start()
        try:
            ready = self._next_result(timeout=60)
        except Exception:
            self.close()
            raise
        if not ready.get("ready"):
            self.close()
            raise FuploadError(
                str((ready.get("error") or {}).get("message") or "DD sidecar failed to start"),
                kind="authentication_error",
                stage="session",
            )
        credential_kind = ready.get("credential_kind")
        if credential_kind not in ("email", "mobile"):
            self.close()
            raise FuploadError(
                "DD sidecar returned an invalid credential kind",
                kind="sidecar_error",
                stage="session",
            )
        self.credential_kind = credential_kind
        return self

    def _lock(self) -> None:
        import msvcrt
        path = state_dir() / "sidecar.lock"
        self.lock_handle = open(path, "a+b")
        try:
            self.lock_handle.seek(0)
            msvcrt.locking(self.lock_handle.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError as exc:
            self.lock_handle.close()
            self.lock_handle = None
            raise FuploadError("another Fupload DD sidecar is already running", kind="concurrent_session") from exc

    def _read_results(self) -> None:
        assert self.process and self.process.stdout
        try:
            for line in self.process.stdout:
                if line.startswith("FUPLOAD_RESULT "):
                    try:
                        self.responses.put(json.loads(line[len("FUPLOAD_RESULT "):]))
                    except ValueError:
                        self.responses.put(FuploadError("DD sidecar returned invalid JSON", kind="sidecar_error"))
        except UnicodeDecodeError:
            self.responses.put(FuploadError("DD sidecar returned non-UTF-8 output", kind="sidecar_error"))
        else:
            self.responses.put(FuploadError("DD sidecar exited without a result", kind="sidecar_error"))

    def _next_result(
        self, *, timeout: float = 180, endpoint: Optional[str] = None,
        stage: Optional[str] = None,
        verification_required: bool = False,
    ) -> Dict[str, Any]:
        try:
            value = self.responses.get(timeout=timeout)
        except queue.Empty as exc:
            raise FuploadError(
                "DD sidecar response timed out",
                kind="timeout",
                stage=stage,
                endpoint=endpoint,
                verification_required=verification_required,
            ) from exc
        if isinstance(value, FuploadError):
            raise FuploadError(
                str(value),
                kind=value.kind,
                stage=stage or value.stage,
                endpoint=endpoint or value.endpoint,
                http_status=value.http_status,
                business_code=value.business_code,
                verification_required=verification_required or value.verification_required,
                details=dict(value.details),
            )
        if not isinstance(value, dict):
            raise FuploadError("DD sidecar returned an invalid result", kind="sidecar_error")
        return value

    def call(self, action: str, **values: Any) -> Any:
        assert self.process and self.process.stdin
        self.counter += 1
        request = {"id": self.counter, "action": action, **values}
        self.process.stdin.write(json.dumps(request, ensure_ascii=True, separators=(",", ":")) + "\n")
        self.process.stdin.flush()
        method = str(values.get("method") or "").upper()
        endpoint = str(values.get("path") or "") or None
        if action == "cc_get":
            endpoint = urllib.parse.urlsplit(str(values.get("url") or "")).path or None
        request_stage = str(values.get("request_stage") or "")
        if action == "request" and request_stage == "dependency_get":
            expected_stage, uncertain = "dependency_get", False
        elif action == "request" and method == "POST":
            expected_stage, uncertain = "mutation", True
        elif action == "upload":
            expected_stage, uncertain = "object_put", True
        elif action == "parse_wa":
            expected_stage, uncertain = "native_parser", False
        else:
            expected_stage, uncertain = "dependency_get", False
        response = self._next_result(
            endpoint=endpoint,
            stage=expected_stage,
            verification_required=uncertain,
        )
        if response.get("id") != self.counter:
            raise FuploadError("DD sidecar response order was invalid", kind="sidecar_error")
        if not response.get("ok"):
            error = response.get("error") if isinstance(response.get("error"), dict) else {}
            message = str(error.get("message") or "DD operation failed")
            timed_out = "timed out" in message.casefold() or "timeout" in message.casefold()
            stage = str(error.get("stage") or expected_stage)
            if stage == "object_put":
                endpoint = "object-store-put"
            elif stage == "upload_authorize":
                endpoint = "/file/upload"
            raise FuploadError(
                message,
                kind=str(error.get("kind") or ("timeout" if timed_out else "platform_error")),
                stage=stage,
                endpoint=endpoint,
                http_status=error.get("http_status"),
                business_code=error.get("business_code"),
                verification_required=bool(error.get("verification_required")) or (uncertain and timed_out),
                details=error.get("details") if isinstance(error.get("details"), dict) else None,
            )
        return response.get("data")

    def get(self, path: str, params: Optional[Mapping[str, Any]] = None) -> Any:
        return self._business_response(
            path, self.call("request", method="GET", path=path, payload=dict(params or {})), "dependency_get"
        )

    def post(self, path: str, body: Mapping[str, Any]) -> Any:
        return self._business_response(
            path, self.call("request", method="POST", path=path, payload=dict(body)), "mutation"
        )

    def post_read(self, path: str, body: Mapping[str, Any]) -> Any:
        return self._business_response(
            path,
            self.call(
                "request", method="POST", path=path, payload=dict(body),
                request_stage="dependency_get",
            ),
            "dependency_get",
        )

    @staticmethod
    def _business_response(path: str, payload: Any, stage: str = "mutation") -> Any:
        if isinstance(payload, dict) and "code" in payload and payload.get("code") != 0:
            raise FuploadError(
                str(payload.get("msg") or payload.get("message") or "DD operation failed"),
                kind="platform_error",
                stage=stage,
                endpoint=path,
                business_code=payload.get("code"),
            )
        return payload

    def upload(
        self,
        file: str,
        business: str,
        *,
        file_name: Any = _OMIT_FILE_NAME,
        media: bool = False,
        max_bytes: Optional[int] = None,
    ) -> str:
        suffix = Path(file).suffix.casefold()
        size = Path(file).stat().st_size
        if max_bytes is not None and size > max_bytes:
            raise ValidationError("file exceeds the platform limit", path="$.file")
        if media:
            mime = _IMAGE_MIME.get(suffix)
            if not mime:
                raise ValidationError("media file extension must be .png, .jpg, .jpeg, or .gif", path="$.file")
        else:
            if suffix != ".zip":
                raise ValidationError("resource file extension must be .zip", path="$.file")
            mime = "application/x-zip-compressed"
        file_type = "a19-ui-media" if media else "a19-ui-res"
        upload_business = "img" if media else business
        meta = {"file_type": file_type, "business_id": upload_business, "mime_type": mime}
        if file_name is not _OMIT_FILE_NAME:
            meta["file_name"] = str(file_name)
        result = self.call("upload", file=file, meta=meta)
        return str(result["d_url"])

    def cc_get(self, url: str) -> Any:
        return self.call("cc_get", url=url)

    def close(self) -> None:
        if self.process:
            try:
                if self.process.stdin:
                    self.process.stdin.close()
                self.process.wait(timeout=15)
            except Exception:
                self.process.kill()
            self.process = None
        if self.lock_handle:
            try:
                import msvcrt
                self.lock_handle.seek(0)
                msvcrt.locking(self.lock_handle.fileno(), msvcrt.LK_UNLCK, 1)
            except OSError:
                pass
            self.lock_handle.close()
            self.lock_handle = None

    def __exit__(self, *_args: Any) -> None:
        self.close()


def result(payload: Any) -> Any:
    return payload.get("result") if isinstance(payload, dict) else None


def items(payload: Any) -> List[Dict[str, Any]]:
    value = result(payload)
    if isinstance(value, list):
        return [x for x in value if isinstance(x, dict)]
    if isinstance(value, dict):
        for key in ("data_list", "list", "rows", "items", "wa_list", "shares"):
            if isinstance(value.get(key), list):
                return [x for x in value[key] if isinstance(x, dict)]
    return []


def _option_items(payload: Any) -> List[Any]:
    """Read only documented result-level option containers."""
    if isinstance(payload, list):
        return list(payload)
    raw = result(payload)
    if isinstance(raw, list):
        return list(raw)
    if isinstance(raw, dict):
        for key in ("data_list", "list", "rows", "items", "categories", "versions"):
            if isinstance(raw.get(key), list):
                return list(raw[key])
    return []


def _option_values(payload: Any, keys: Sequence[str]) -> set[str]:
    values: set[str] = set()
    for item in _option_items(payload):
        if not isinstance(item, dict):
            if item not in (None, ""):
                values.add(str(item))
            continue
        for key in keys:
            if item.get(key) not in (None, ""):
                values.add(str(item[key]))
    return values


def _category_id(item: Mapping[str, Any]) -> Optional[str]:
    for key in ("id", "c_id", "category_id", "value"):
        if item.get(key) not in (None, ""):
            return str(item[key])
    return None


def _addon_category_tree(payload: Any) -> Dict[str, set[str]]:
    tree: Dict[str, set[str]] = {}
    for item in _option_items(payload):
        if not isinstance(item, dict):
            continue
        parent = _category_id(item)
        if parent is None:
            continue
        children = set()
        for child in item.get("children") or []:
            if isinstance(child, dict):
                child_id = _category_id(child)
                if child_id is not None:
                    children.add(child_id)
        tree[parent] = children
    return tree


def _wa_category_values(payload: Any) -> set[str]:
    values: set[str] = set()
    def visit(rows: Sequence[Any]) -> None:
        for item in rows:
            if not isinstance(item, dict):
                continue
            ident = _category_id(item)
            if ident is not None:
                values.add(ident)
            for key in ("children", "items", "options"):
                child_rows = item.get(key)
                if isinstance(child_rows, list):
                    visit(child_rows)
    visit(_option_items(payload))
    return values


def _normalized(value: Any) -> Any:
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, (int, float, str)):
        return str(value)
    if isinstance(value, list):
        return sorted((_normalized(item) for item in value), key=repr)
    if isinstance(value, dict):
        return {key: _normalized(item) for key, item in sorted(value.items())}
    return str(value)


def _same_readback(expected: Any, actual: Any) -> bool:
    if isinstance(expected, dict):
        return isinstance(actual, dict) and all(
            key in actual and _same_readback(value, actual[key])
            for key, value in expected.items()
        )
    if isinstance(expected, list):
        if not isinstance(actual, list):
            return False
        unmatched = list(actual)
        for wanted in expected:
            match = next(
                (index for index, candidate in enumerate(unmatched) if _same_readback(wanted, candidate)),
                None,
            )
            if match is None:
                return False
            unmatched.pop(match)
        return not unmatched
    return _normalized(expected) == _normalized(actual)


def _verify_fields(expected: Mapping[str, Any], actual: Mapping[str, Any], fields: Sequence[str], endpoint: str) -> None:
    mismatches = [
        name for name in fields
        if name in expected and (name not in actual or not _same_readback(expected[name], actual[name]))
    ]
    if mismatches:
        raise FuploadError(
            "write readback did not match field(s): %s" % ", ".join(sorted(mismatches)),
            kind="verification_required", stage="readback", endpoint=endpoint, verification_required=True,
            details={"fields": sorted(mismatches)},
        )


def _readback(getter: Any, endpoint: str) -> Any:
    try:
        return getter()
    except FuploadError as exc:
        if exc.stage == "readback" and exc.verification_required:
            raise
        raise FuploadError(
            str(exc),
            kind=exc.kind,
            stage="readback",
            endpoint=exc.endpoint or endpoint,
            http_status=exc.http_status,
            business_code=exc.business_code,
            verification_required=True,
            details=exc.details,
        ) from exc


def _readback_until_fields(
    getter: Any,
    projector: Any,
    expected: Mapping[str, Any],
    fields: Sequence[str],
    endpoint: str,
    *,
    attempts: int = 6,
    delay: float = 1.0,
) -> Tuple[Any, Mapping[str, Any]]:
    raw: Any = {}
    actual: Mapping[str, Any] = {}
    for attempt in range(attempts):
        raw = _readback(getter, endpoint)
        projected = projector(raw)
        actual = projected if isinstance(projected, Mapping) else {}
        mismatches = [
            name for name in fields
            if name in expected and (name not in actual or not _same_readback(expected[name], actual[name]))
        ]
        if not mismatches:
            return raw, actual
        if attempt + 1 < attempts:
            time.sleep(delay)
    _verify_fields(expected, actual, fields, endpoint)
    return raw, actual


def _dependency_post(session: Any, path: str, body: Mapping[str, Any]) -> Any:
    method = getattr(session, "post_read", None)
    if callable(method):
        return method(path, body)
    return session.post(path, body)


def _author_page(
    session: Sidecar, resource: str, keyword: str, game_type: Any, page: int, size: int,
) -> Any:
    common = {"game_type": game_type, "origin": "created", "page": page, "size": size}
    if resource == "plugin":
        return _dependency_post(session, "/addon/addon_list", {
            **common, "category": 0,
            "name_or_author_name_or_share_code": keyword,
            "sort_type": 2,
        })
    if resource == "config":
        return session.get("/share/list", {
            **common, "search_text": keyword, "sort_type": "mtime",
        })
    return session.get("/wa/list", {
        **common, "search_text": keyword, "category_id": "", "sort_type": "mtime",
    })


def _author_total(payload: Any) -> Optional[int]:
    for value in (payload, result(payload)):
        if not isinstance(value, dict):
            continue
        for key in ("total", "total_count", "count"):
            try:
                if value.get(key) is not None:
                    return max(0, int(value[key]))
            except (TypeError, ValueError):
                continue
    return None


def _author_items(
    session: Sidecar, resource: str, keyword: str, game_type: Any, *, size: int = 100,
) -> List[Dict[str, Any]]:
    collected: List[Dict[str, Any]] = []
    seen_pages: set[Tuple[str, ...]] = set()
    for page in range(1, 1001):
        payload = _author_page(session, resource, keyword, game_type, page, size)
        page_items = items(payload)
        if not page_items:
            return collected
        signature = tuple(
            str(item.get("sn") or item.get("share_sn") or item.get("id") or "")
            for item in page_items
        )
        if signature in seen_pages:
            raise FuploadError(
                "DD author list pagination repeated a page",
                kind="platform_data_error", stage="dependency_get",
            )
        seen_pages.add(signature)
        collected.extend(page_items)
        total = _author_total(payload)
        if total is not None and len(collected) >= total:
            return collected
        if total is None and len(page_items) < size:
            return collected
    raise FuploadError(
        "DD author list pagination exceeded the bounded page limit",
        kind="platform_data_error", stage="dependency_get",
    )


def author_listing(session: Sidecar, resource: str, keyword: str, game_type: Any) -> Any:
    author_items = _author_items(session, resource, keyword, game_type)
    return {"code": 0, "result": {"items": author_items, "total": len(author_items)}}


def readable_author_list(
    session: Sidecar, resource: str, keyword: str, game_type: Any,
    page: int, size: int,
) -> Dict[str, Any]:
    def load(search: str) -> Any:
        return _author_page(session, resource, search, game_type, page, size)

    fallback = False
    try:
        payload = load(keyword)
    except FuploadError:
        if not keyword:
            raise
        payload = load("")
        fallback = True
    safe = safe_author_list(resource, payload)
    if fallback:
        needle = keyword.casefold()
        safe["items"] = [
            item for item in safe["items"]
            if needle in str(item.get("name") or "").casefold()
            or needle in str(item.get("reference") or "").casefold()
        ]
        safe["total"] = len(safe["items"])
    return safe


def created_reference(session: Sidecar, resource: str, name: str, game_type: Any) -> str:

    for keyword in (name, ""):
        try:
            payload = author_listing(session, resource, keyword, game_type)
        except FuploadError:
            continue
        references = {
            str(item.get("sn") or item.get("share_sn") or "")
            for item in items(payload)
            if str(item.get("name") or item.get("title") or "") == name
        } - {""}
        if len(references) == 1:
            return next(iter(references))
    return ""


def author_item(session: Sidecar, resource: str, reference: str, name: str, game_type: Any) -> Dict[str, Any]:
    for keyword in (name, ""):
        try:
            payload = author_listing(session, resource, keyword, game_type)
        except FuploadError:
            continue
        matches = [
            item for item in items(payload)
            if str(item.get("sn") or item.get("share_sn") or "") == reference
        ]
        if len(matches) == 1:
            return matches[0]
    return {}


def safe_game_types(payload: Any) -> Dict[str, Any]:
    result_items = []
    for item in items(payload):
        result_items.append({
            "game_type": item.get("game_type"), "name": item.get("name"),
            "type": item.get("type"), "def_game_version": item.get("def_game_version"),
        })
    return {
        "total": len(result_items),
        "items": result_items,
        "dependencies": [
            {"parent": "game_type", "children": ["game_versions", "associated_acts", "category_ids"]},
        ],
    }


def safe_game_versions(payload: Any, game_type: Any) -> Dict[str, Any]:
    result_items = []
    seen = set()
    for item in _option_items(payload):
        if isinstance(item, dict):
            value = item.get("game_version") or item.get("version") or item.get("value") or item.get("id")
            name = item.get("name") or item.get("label") or value
        else:
            value = item
            name = item
        if value in (None, "") or str(value) in seen:
            continue
        seen.add(str(value))
        result_items.append({"value": value, "name": name, "game_type": game_type})
    return {
        "parent": {"game_type": game_type},
        "total": len(result_items),
        "items": result_items,
    }


def safe_plugin_categories(payload: Any) -> Dict[str, Any]:
    result_items = []
    for item in _option_items(payload):
        if not isinstance(item, dict):
            continue
        primary = _category_id(item)
        if primary is None:
            continue
        children = []
        for child in item.get("children") or []:
            if not isinstance(child, dict):
                continue
            child_id = _category_id(child)
            if child_id is not None:
                children.append({
                    "id": child_id,
                    "name": child.get("name") or child.get("label"),
                    "primary_category_id": primary,
                })
        result_items.append({
            "id": primary,
            "name": item.get("name") or item.get("label"),
            "children": children,
        })
    return {
        "total": len(result_items),
        "items": result_items,
        "dependencies": [{"parent": "primary_category_id", "child": "second_category_ids"}],
    }


def safe_wa_categories(payload: Any, game_type: Any) -> Dict[str, Any]:
    result_items = []

    def visit(rows: Sequence[Any], parent: Optional[str] = None) -> None:
        for item in rows:
            if not isinstance(item, dict):
                continue
            value = _category_id(item)
            if value is not None:
                result_items.append({
                    "id": value,
                    "name": item.get("name") or item.get("label"),
                    "parent_id": parent,
                    "game_type": game_type,
                })
            for key in ("children", "items", "options"):
                children = item.get(key)
                if isinstance(children, list):
                    visit(children, value or parent)

    visit(_option_items(payload))
    return {"parent": {"game_type": game_type}, "total": len(result_items), "items": result_items}


def safe_channels(payload: Any) -> Dict[str, Any]:
    raw = payload.get("data") if isinstance(payload, dict) else payload
    if isinstance(raw, dict):
        raw_items = raw.get("list") or raw.get("items") or raw.get("channels") or raw.get("data") or []
    else:
        raw_items = raw if isinstance(raw, list) else []
    result_items = []
    def walk(rows: Sequence[Any], inherited_room_id: str = "", inherited_room_name: Any = None) -> None:
        for value in rows:
            if not isinstance(value, dict):
                continue
            room_id = str(value.get("teamId") or value.get("team_id") or value.get("room_id") or inherited_room_id or "")
            room_name = value.get("teamName") or value.get("team_name") or value.get("room_name") or inherited_room_name
            channel_id = str(value.get("channelId") or value.get("channel_id") or "")
            channel_type = str(value.get("channelType") or value.get("channel_type") or "")
            if room_id and (value.get("teamId") or value.get("team_id") or value.get("room_id") or channel_id):
                result_items.append({
                    "room_id": room_id,
                    "room_name": room_name,
                    "channel_id": channel_id,
                    "channel_name": value.get("channelName") or value.get("channel_name") or (value.get("name") if channel_id else None),
                    "channel_type": channel_type,
                })
            for key in ("channelList", "channels", "children", "items"):
                children = value.get(key)
                if isinstance(children, list):
                    walk(children, room_id, room_name)
    walk(raw_items)
    unique = []
    seen = set()
    for item in result_items:
        key = (item["room_id"], item["channel_id"], item["channel_type"])
        if key not in seen:
            seen.add(key)
            unique.append(item)
    return {
        "total": len(unique),
        "items": unique,
        "dependencies": [{"parent": "room_id", "children": ["channel_id", "channel_type"]}],
    }


def version_greater(candidate: Any, current: Any) -> bool:
    left = str(candidate or "").strip()
    right = str(current or "").strip()
    if not left.isdigit():
        return False
    try:
        return Decimal(left) > Decimal(right)
    except InvalidOperation:
        return False


def response_reference(payload: Any, *names: str) -> str:
    value = result(payload)
    if isinstance(value, Mapping):
        for name in names:
            candidate = value.get(name)
            if candidate not in (None, ""):
                return str(candidate)
        return ""
    return "" if value in (None, "") else str(value)


def safe_author_list(kind: str, payload: Any) -> Dict[str, Any]:
    result_items = []
    for item in items(payload):
        reference = item.get("share_sn") or item.get("sn") or ""
        latest = item.get("latest_version")
        if isinstance(latest, dict):
            latest_version = latest.get("version") or ""
        else:
            latest_version = latest or ""
        result_items.append({
            "kind": kind, "reference": str(reference),
            "name": str(item.get("title") or item.get("name") or ""),
            "version": str(item.get("version") or item.get("current_version") or latest_version),
            "scope": item.get("scope"), "status": item.get("status") or item.get("audit_status") or item.get("state"),
            "game_type": item.get("game_type"), "updated_at": item.get("mtime") or item.get("update_time"),
        })
    return {"total": len(result_items), "items": result_items}


def _backup_group_counts(value: Mapping[str, Any]) -> Dict[str, int]:
    result_value = result(value)
    if isinstance(result_value, list):
        result_value = result_value[0] if result_value and isinstance(result_value[0], dict) else {}
    if not isinstance(result_value, dict):
        result_value = {}
    counts = {}
    for name in ("known_addon", "unknown_addon", "material", "font", "known_wa", "unknown_wa"):
        group = result_value.get(name) or {}
        counts[name] = len(group.get("items") or []) if isinstance(group, dict) else 0
    wtf = result_value.get("wtf") or {}
    accounts = wtf.get("accounts") if isinstance(wtf, dict) else []
    counts["wtf_accounts"] = len(accounts) if isinstance(accounts, list) else 0
    return counts


def safe_backup_list(payload: Any) -> Dict[str, Any]:
    result_items = []
    for item in items(payload):
        result_items.append({
            "reference": str(item.get("sn") or item.get("backup_sn") or ""),
            "name": item.get("name"), "game_type": item.get("game_type"),
            "counts": _backup_group_counts({"result": item}),
        })
    return {"total": len(result_items), "items": result_items}


def safe_backup_detail(value: Any) -> Dict[str, Any]:
    if isinstance(value, dict) and "result" in value:
        value = result(value)
    if isinstance(value, list):
        value = value[0] if value and isinstance(value[0], dict) else {}
    if not isinstance(value, dict):
        return {}
    result_value: Dict[str, Any] = {
        "reference": str(value.get("sn") or value.get("backup_sn") or ""),
        "name": value.get("name"), "game_type": value.get("game_type"),
        "counts": _backup_group_counts({"result": value}),
    }
    selection_keys = {
        "known_addon": "addon_id", "unknown_addon": "name",
        "material": "name", "font": "name", "known_wa": "uid", "unknown_wa": "uid",
    }
    wa_accounts: Dict[str, List[str]] = {}
    account_info = ((value.get("extra") or {}).get("wa_account_info") or {}) if isinstance(value.get("extra"), dict) else {}
    if isinstance(account_info, dict):
        for account, entries in account_info.items():
            if not isinstance(entries, list):
                continue
            for entry in entries:
                if isinstance(entry, dict) and entry.get("uid") is not None:
                    wa_accounts.setdefault(str(entry["uid"]), []).append(str(account))
    for name in ("known_addon", "unknown_addon", "material", "font", "known_wa", "unknown_wa"):
        group = value.get(name) or {}
        raw_items = group.get("items") if isinstance(group, dict) else []
        if not isinstance(raw_items, list):
            raw_items = []
        summaries = []
        for item in raw_items:
            if isinstance(item, dict):
                selection = item.get(selection_keys[name])
                summaries.append({
                    "reference": selection,
                    "name": item.get("name"),
                    "content_reference": item.get("detail_sn") if name == "known_addon" else None,
                    "accounts": sorted(wa_accounts.get(str(selection), [])) if name in ("known_wa", "unknown_wa") else None,
                    "release_type": item.get("release_type"),
                    "entry_count": len(item.get("dirs") or item.get("items") or []),
                })
            else:
                summaries.append({"reference": item, "name": str(item)})
        result_value[name] = summaries
    wtf = value.get("wtf") or {}
    role_summary = []
    backup_reference = str(value.get("sn") or value.get("backup_sn") or "")
    for account in (wtf.get("accounts") if isinstance(wtf, dict) else []) or []:
        if not isinstance(account, dict):
            continue
        for server in account.get("servers") or []:
            if isinstance(server, dict):
                for index, role in enumerate(server.get("items") or []):
                    role_id = role.get("role_id") or role.get("id") or role.get("name") if isinstance(role, dict) else role
                    selector_source = "%s\0%s\0%s\0%d\0%s" % (
                        backup_reference, account.get("name"), server.get("name"), index, role_id,
                    )
                    role_summary.append({
                        "selector": "wtf_" + hashlib.sha256(selector_source.encode("utf-8")).hexdigest()[:20],
                        "account": account.get("name"), "server": server.get("name"),
                        "name": role.get("name") if isinstance(role, dict) else str(role),
                        "role_id": role_id if isinstance(role, dict) and (role.get("role_id") is not None or role.get("id") is not None) else None,
                    })
    result_value["wtf_roles"] = role_summary
    retail = value.get("retail_ui_config")
    if isinstance(retail, dict):
        result_value["retail_ui_config"] = safe_retail_catalog(value)
    result_value["dependencies"] = [
        {"parent": "backup_sn", "children": ["wtf_role_ids", "content_groups", "retail_ui_config"]},
        {"parent": "wtf_role_ids.account", "children": ["known_wa_ids", "unknown_wa_ids"]},
    ]
    return result_value


def _retail_selector(reference: str, section: str, account: str, index: int) -> str:
    digest = hashlib.sha256(
        ("%s\0%s\0%s\0%d" % (reference, section, account, index)).encode("utf-8")
    ).hexdigest()[:20]
    return ("em_" if section == "editMode" else "cd_") + digest


def retail_catalog(backup: Mapping[str, Any]) -> Dict[str, List[Dict[str, Any]]]:
    reference = str(backup.get("sn") or backup.get("backup_sn") or "")
    retail = backup.get("retail_ui_config") or {}
    if not isinstance(retail, dict):
        retail = {}
    catalog: Dict[str, List[Dict[str, Any]]] = {"edit_mode": [], "cool_down": []}
    for section, public_name in (("editMode", "edit_mode"), ("coolDown", "cool_down")):
        accounts = retail.get(section) or {}
        if not isinstance(accounts, dict):
            continue
        for account, entries in accounts.items():
            if not isinstance(entries, list):
                continue
            for index, item in enumerate(entries):
                if not isinstance(item, dict):
                    continue
                catalog[public_name].append({
                    "selector": _retail_selector(reference, section, str(account), index),
                    "account": str(account),
                    "item": item,
                })
    return catalog


def safe_retail_catalog(backup: Mapping[str, Any]) -> Dict[str, Any]:
    catalog = retail_catalog(backup)
    edit_modes = [
        {"selector": entry["selector"], "account": entry["account"], "name": entry["item"].get("name")}
        for entry in catalog["edit_mode"]
    ]
    cool_down = [
        {
            "selector": entry["selector"], "account": entry["account"],
            "name": entry["item"].get("name"), "character": entry["item"].get("char"),
            "realm": entry["item"].get("realm"), "class_name": entry["item"].get("class_name"),
            "spec_name": entry["item"].get("spec_name"), "spec_tag": entry["item"].get("spec_tag"),
        }
        for entry in catalog["cool_down"]
    ]
    return {
        "edit_modes": edit_modes,
        "cool_down": cool_down,
        "constraints": {
            "edit_mode_max": 5,
            "edit_mode_default_required_when_selected": True,
            "cool_down_max_per_spec_tag": 1,
        },
    }


def safe_current_retail(value: Any) -> Dict[str, Any]:
    retail = value if isinstance(value, dict) else {}
    edit_modes = []
    for account, entries in (retail.get("edit_mode") or {}).items():
        if isinstance(entries, list):
            edit_modes.extend({
                "account": str(account), "name": item.get("name"),
                "is_default": bool(item.get("is_default")),
            } for item in entries if isinstance(item, dict))
    cool_down = []
    for account, entries in (retail.get("cool_down") or {}).items():
        if isinstance(entries, list):
            cool_down.extend({
                "account": str(account), "name": item.get("name"),
                "character": item.get("char"), "realm": item.get("realm"),
                "class_name": item.get("class_name"), "spec_name": item.get("spec_name"),
                "spec_tag": item.get("spec_tag"),
            } for item in entries if isinstance(item, dict))
    return {
        "edit_modes": edit_modes,
        "cool_down": cool_down,
        "enable_dd_setup_wizard": retail.get("enable_dd_setup_wizard"),
    }


def resolve_retail_ui_config(
    backup: Mapping[str, Any], current: Mapping[str, Any], selection: Any,
) -> Any:
    if selection is None:
        return None
    if int(backup.get("game_type") or 0) != 10001:
        raise ValidationError("retail_ui_config is only available for retail backups", path="$.retail_ui_config")
    catalog = retail_catalog(backup)
    maps = {
        name: {entry["selector"]: entry for entry in entries}
        for name, entries in catalog.items()
    }
    existing = current.get("retail_ui_config") if isinstance(current, dict) else None
    wire = copy.deepcopy(existing) if isinstance(existing, dict) else {}

    if "edit_mode_selectors" in selection:
        selectors = selection["edit_mode_selectors"]
        if len(selectors) != len(set(selectors)):
            raise ValidationError("duplicate selector", path="$.retail_ui_config.edit_mode_selectors")
        if len(selectors) > 5:
            raise ValidationError("at most five edit modes may be selected", path="$.retail_ui_config.edit_mode_selectors")
        default = selection.get("default_edit_mode_selector")
        if selectors and not default:
            raise ValidationError("a default edit mode is required", path="$.retail_ui_config.default_edit_mode_selector")
        if default and default not in selectors:
            raise ValidationError("default edit mode must be selected", path="$.retail_ui_config.default_edit_mode_selector")
        grouped: Dict[str, List[Dict[str, Any]]] = {}
        for index, selector in enumerate(selectors):
            entry = maps["edit_mode"].get(selector)
            if not entry:
                raise ValidationError("selector is unavailable for this backup", path="$.retail_ui_config.edit_mode_selectors[%d]" % index)
            item = copy.deepcopy(entry["item"])
            item["is_default"] = selector == default
            grouped.setdefault(entry["account"], []).append(item)
        wire["edit_mode"] = grouped
    elif "default_edit_mode_selector" in selection:
        raise ValidationError("default selector requires edit_mode_selectors", path="$.retail_ui_config.default_edit_mode_selector")

    if "cool_down_selectors" in selection:
        selectors = selection["cool_down_selectors"]
        if len(selectors) != len(set(selectors)):
            raise ValidationError("duplicate selector", path="$.retail_ui_config.cool_down_selectors")
        grouped = {}
        selected_specs = set()
        for index, selector in enumerate(selectors):
            entry = maps["cool_down"].get(selector)
            if not entry:
                raise ValidationError("selector is unavailable for this backup", path="$.retail_ui_config.cool_down_selectors[%d]" % index)
            spec_tag = entry["item"].get("spec_tag")
            if spec_tag in selected_specs:
                raise ValidationError("only one cooldown configuration may be selected per spec_tag", path="$.retail_ui_config.cool_down_selectors[%d]" % index)
            selected_specs.add(spec_tag)
            grouped.setdefault(entry["account"], []).append(copy.deepcopy(entry["item"]))
        wire["cool_down"] = grouped
    if "enable_dd_setup_wizard" in selection:
        wire["enable_dd_setup_wizard"] = selection["enable_dd_setup_wizard"]
    return wire


def safe_associated_acts(session: Sidecar, game_type: Any) -> Dict[str, Any]:
    sources = (
        ("addon", _author_items(session, "plugin", "", game_type)),
        ("share", _author_items(session, "config", "", game_type)),
        ("wa", _author_items(session, "wa", "", game_type)),
    )
    result_items = []
    for kind, source_items in sources:
        for item in source_items:
            reference = item.get("sn") or item.get("share_sn")
            if reference:
                result_items.append({
                    "sn": str(reference), "act_type": kind,
                    "name": item.get("name") or item.get("title"),
                    "version": item.get("version") or item.get("current_version"),
                })
    return {"total": len(result_items), "items": result_items}


def safe_detail(kind: str, value: Dict[str, Any]) -> Dict[str, Any]:
    result_value = copy.deepcopy(value)
    if kind == "config" and "retail_ui_config" in result_value:
        result_value["retail_ui_config"] = safe_current_retail(result_value["retail_ui_config"])
    sensitive_keys = {"content", "raw_content", "wa_str", "roleobj", "wtflist", "file_url", "upload_url", "url", "u_url", "md5", "hash", "dir_md5", "import_string"}
    def scrub(node: Any) -> Any:
        if isinstance(node, dict):
            cleaned: Dict[str, Any] = {}
            for key, item in node.items():
                if key.lower() in sensitive_keys:
                    if isinstance(item, str):
                        cleaned[key + "_summary"] = {"length": len(item)}
                    elif isinstance(item, list):
                        cleaned[key + "_summary"] = {"items": len(item)}
                    else:
                        cleaned[key + "_summary"] = {"present": item is not None}
                elif key in {"file_path", "d_url"} and isinstance(item, str):
                    cleaned[key + "_summary"] = {"host": urllib.parse.urlsplit(item).netloc}
                else:
                    cleaned[key] = scrub(item)
            return cleaned
        if isinstance(node, list):
            return [scrub(item) for item in node]
        return node
    result_value = scrub(result_value)
    return result_value


def detail(session: Sidecar, kind: str, reference: str) -> Dict[str, Any]:
    if kind == "plugin":
        payload = session.get("/addon/detail_v2", {"sn": reference})
        if not isinstance(result(payload), dict):
            payload = session.get("/addon/detail", {"sn": reference})
    elif kind == "config":
        payload = session.get("/share/detail", {"sn": reference})
    else:
        payload = session.get("/wa/detail", {"sn": reference})
    value = result(payload)
    if not isinstance(value, dict):
        raise FuploadError("DD %s detail was not found" % kind, kind="not_found")
    return value


def apply_present(form: Dict[str, Any], doc: Mapping[str, Any], names: Iterable[str]) -> None:
    for name in names:
        if name in doc:
            form[name] = copy.deepcopy(doc[name])


def _remote_rows(value: Any, path: str) -> List[Any]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise FuploadError("DD remote %s field was not an array" % path, kind="platform_data_error")
    return value


def _remote_candidate(item: Any, aliases: Sequence[str]) -> Any:
    if not isinstance(item, Mapping):
        return item
    for name in aliases:
        if item.get(name) is not None:
            return item[name]
    return None


def _remote_strings(value: Any, aliases: Sequence[str], path: str, *, allow_int: bool = False) -> List[str]:
    projected: List[str] = []
    for item in _remote_rows(value, path):
        candidate = _remote_candidate(item, aliases)
        if isinstance(candidate, str) and candidate:
            projected.append(candidate)
            continue
        if allow_int and not isinstance(candidate, bool) and isinstance(candidate, int):
            projected.append(str(candidate))
            continue
        raise FuploadError("DD remote %s item was not a scalar string" % path, kind="platform_data_error")
    return projected


def _remote_ints(value: Any, aliases: Sequence[str], path: str) -> List[int]:
    projected: List[int] = []
    for item in _remote_rows(value, path):
        candidate = _remote_candidate(item, aliases)
        if isinstance(candidate, bool):
            raise FuploadError("DD remote %s item was not an integer ID" % path, kind="platform_data_error")
        try:
            projected.append(int(candidate))
        except (TypeError, ValueError) as exc:
            raise FuploadError("DD remote %s item was not an integer ID" % path, kind="platform_data_error") from exc
    return projected


def _remote_urls(value: Any, path: str) -> List[str]:
    return _remote_strings(value, ("d_url", "url", "media_url", "value"), path)


def _remote_int(value: Any, aliases: Sequence[str], path: str) -> Any:
    candidate = _remote_candidate(value, aliases)
    if candidate is None:
        return None
    if isinstance(candidate, bool):
        raise FuploadError("DD remote %s field was not an integer ID" % path, kind="platform_data_error")
    try:
        return int(candidate)
    except (TypeError, ValueError) as exc:
        raise FuploadError("DD remote %s field was not an integer ID" % path, kind="platform_data_error") from exc


def validate_no_display_objects(form: Mapping[str, Any], resource: str) -> None:
    allowed_objects = {"associated_acts"}
    if resource == "config":
        allowed_objects.update({
            "known_addon", "unknown_addon", "wtf", "material", "font",
            "known_wa", "unknown_wa", "retail_ui_config",
        })
    for name, value in form.items():
        if isinstance(value, Mapping) and name not in allowed_objects:
            raise FuploadError(
                "DD %s mutation field %s contained an unexpected object" % (resource, name),
                kind="platform_data_error", stage="mutation_projection",
            )
        if isinstance(value, list) and name not in allowed_objects and any(isinstance(item, Mapping) for item in value):
            raise FuploadError(
                "DD %s mutation field %s contained an unexpected object item" % (resource, name),
                kind="platform_data_error", stage="mutation_projection",
            )


COMMERCIAL = (
    "scope", "share_code_life_type", "need_buy", "price_fen", "buy_life_type",
    "jump_room", "room_id", "channel_id", "channel_type", "sync_room",
    "creation_statement", "with_associate", "associated_acts", "need_anchor_vip", "vip_levels",
)


def normalize_commercial(
    form: Dict[str, Any], resource: Optional[str] = None, *, create: bool = False,
) -> None:
    """Apply the resource's official submit-time conditionals.

    The three DD editors share controls but do not share one wire builder.
    In particular, only the configuration builder always defaults
    buy_life_type, while plugin/WA create defaults must not leak into legacy
    modify payloads.
    """
    if resource == "config":
        form["need_buy"] = 1 if form.get("need_buy") else 0
        form["buy_life_type"] = form.get("buy_life_type") or "seven_day"
    elif create and not form.get("buy_life_type"):
        form["buy_life_type"] = "seven_day"
    if "price_fen" not in form or form.get("price_fen") is None:
        form["price_fen"] = 0
    if create and not form.get("need_buy"):
        form["price_fen"] = 0
    if form.get("scope") == "private":
        form["sync_room"] = False
        form["need_anchor_vip"] = False
        form["vip_levels"] = []
    elif form.get("scope") == "public":
        if resource in ("plugin", "wa"):
            form["share_code_life_type"] = "forever"
        elif resource == "config":
            form.pop("share_code_life_type", None)
    if not form.get("jump_room"):
        form.update({"room_id": "", "channel_id": "", "channel_type": "", "sync_room": False})
    if form.get("with_associate"):
        associated_acts = []
        for index, item in enumerate(form.get("associated_acts") or []):
            if not isinstance(item, Mapping) or not item.get("sn") or not item.get("act_type"):
                raise ValidationError(
                    "associated item must contain sn and act_type",
                    path="$.associated_acts[%d]" % index,
                )
            associated_acts.append({
                "sn": copy.deepcopy(item["sn"]),
                "act_type": copy.deepcopy(item["act_type"]),
            })
        form["associated_acts"] = associated_acts
    else:
        form["associated_acts"] = []


def validate_locked_usage_mode(current: Mapping[str, Any], form: Mapping[str, Any], doc: Mapping[str, Any]) -> None:
    if not current or not any(name in doc for name in ("need_buy", "need_anchor_vip")):
        return
    current_paid = bool(current.get("need_buy") or current.get("need_anchor_vip"))
    requested_paid = bool(form.get("need_buy") or form.get("need_anchor_vip"))
    if current_paid != requested_paid:
        path = "$.need_buy" if "need_buy" in doc else "$.need_anchor_vip"
        raise ValidationError("the outer free/paid usage mode is locked after creation", path=path)


PLUGIN_FIELDS = (
    "game_type", "game_versions", "scope", "addon_type", "name", "description", "logo",
    "detail_imgs", "primary_category_id", "second_category_ids", "detail_url", "release_type",
    "version", "html_desc", "update_desc", *COMMERCIAL,
)

PLUGIN_OPEN_FIELDS = (
    "game_type", "game_versions", "description", "addon_type", "name", "logo",
    "detail_imgs", "primary_category_id", "second_category_ids", "detail_url",
    "release_type", "version", "html_desc", "update_desc", "share_code_life_type",
    "need_buy", "buy_life_type", "jump_room", "room_id", "channel_id",
    "channel_type", "sync_room", "creation_statement", "with_associate",
    "associated_acts", "need_anchor_vip",
)

PLUGIN_CREATE_DEFAULTS = {
    "share_code_life_type": "seven_day",
    "addon_type": 0,
    "buy_life_type": "seven_day",
    "need_buy": False,
    "with_associate": False,
}

# DD's modify form is not a second create form.  The official edit page
# rebuilds the payload from the existing commercial/association controls;
# first-publication metadata and version fields belong to create/update.
PLUGIN_EDIT_FIELDS = (
    "scope", "share_code_life_type", "need_buy", "price_fen", "buy_life_type",
    "jump_room", "room_id", "channel_id", "channel_type", "sync_room",
    "creation_statement", "with_associate", "associated_acts", "need_anchor_vip",
    "vip_levels",
)


def plugin_form(
    value: Mapping[str, Any], author_value: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    latest = value.get("latest_version") if isinstance(value.get("latest_version"), dict) else {}
    author_latest = (
        author_value.get("latest_version")
        if isinstance(author_value, Mapping) and isinstance(author_value.get("latest_version"), dict)
        else {}
    )
    # Official detail dialog projection followed by the editor's pick list.
    source = {name: copy.deepcopy(value[name]) for name in PLUGIN_FIELDS if name in value}
    for name in ("detail_url", "release_type", "version"):
        latest_name = {"detail_url": "file_path"}.get(name, name)
        projected = latest.get(latest_name)
        if projected is None:
            projected = author_latest.get(latest_name)
        if projected is None:
            source.pop(name, None)
        else:
            source[name] = copy.deepcopy(projected)
    source["game_type"] = _remote_int(
        source.get("game_type") or (value.get("game_types") or [None])[0],
        ("game_type", "id", "value"), "plugin.game_type",
    )
    form = {name: copy.deepcopy(source[name]) for name in PLUGIN_OPEN_FIELDS if name in source}
    form["scope"] = copy.deepcopy(source.get("scope") or "public")
    form["price_fen"] = copy.deepcopy(source.get("price_fen") or 0)
    form["vip_levels"] = _remote_ints(source.get("vip_levels") or [], ("level", "id", "value"), "plugin.vip_levels")
    if "game_versions" in form:
        form["game_versions"] = _remote_strings(form["game_versions"], ("version", "build", "value"), "plugin.game_versions")
    if "detail_imgs" in form:
        form["detail_imgs"] = _remote_urls(form["detail_imgs"], "plugin.detail_imgs")
    if "primary_category_id" in form:
        form["primary_category_id"] = _remote_int(form["primary_category_id"], ("c_id", "category_id", "id", "value"), "plugin.primary_category_id")
    categories = _remote_ints(form.get("second_category_ids") or [], ("c_id", "category_id", "id", "value"), "plugin.second_category_ids")
    form["second_category_ids"] = categories[:-1] if categories else []
    normalize_commercial(form, "plugin")
    return form


def plugin_version_projection(value: Mapping[str, Any]) -> Dict[str, Any]:
    """Project version fields for readback without feeding them into modify."""
    latest = value.get("latest_version") if isinstance(value.get("latest_version"), dict) else {}
    projection: Dict[str, Any] = {}
    sources = {
        "game_versions": (latest, "game_versions", value, "game_versions"),
        "detail_url": (latest, "file_path", value, "detail_url"),
        "release_type": (latest, "release_type", value, "release_type"),
        "version": (latest, "version", value, "version"),
        "update_desc": (latest, "update_desc", value, "update_desc"),
    }
    for name, (preferred, preferred_name, fallback, fallback_name) in sources.items():
        if preferred.get(preferred_name) is not None:
            projection[name] = copy.deepcopy(preferred[preferred_name])
        elif fallback.get(fallback_name) is not None:
            projection[name] = copy.deepcopy(fallback[fallback_name])
    return projection


def plugin_history_versions(payload: Any) -> set[str]:
    versions: set[str] = set()

    def visit(node: Any) -> None:
        if isinstance(node, dict):
            if node.get("version") not in (None, ""):
                versions.add(str(node["version"]).strip().casefold())
            for child in node.values():
                visit(child)
        elif isinstance(node, list):
            for child in node:
                visit(child)

    visit(result(payload))
    return versions


def load_plugin_history_versions(
    session: Sidecar, reference: str, game_type: Any, *, page_limit: int = 1000,
) -> set[str]:
    versions: set[str] = set()
    seen_pages: set[Tuple[str, ...]] = set()
    for page in range(1, page_limit + 1):
        payload = session.get("/addon/addon_versions", {
            "sn": reference, "game_type": game_type, "page": page,
        })
        page_items = items(payload)
        if not page_items:
            return versions
        signature = tuple(
            str(item.get("sn") or item.get("version") or item.get("id") or "")
            for item in page_items
        )
        if signature in seen_pages:
            return versions
        seen_pages.add(signature)
        versions.update(plugin_history_versions(payload))
        total = _author_total(payload)
        if total is not None and len(versions) >= total:
            return versions
    raise FuploadError(
        "DD plugin version pagination exceeded the bounded page limit",
        kind="platform_data_error", stage="dependency_get",
    )


def _key(item: Any, key: Optional[str]) -> Any:
    if key is None:
        return item if not isinstance(item, dict) else item.get("name", item.get("id"))
    return item.get(key) if isinstance(item, dict) else item


def selected_group(
    backup: Mapping[str, Any], current: Mapping[str, Any], name: str, key: Optional[str],
    selected: Sequence[Any], updates: Sequence[Any], update_path: Optional[str] = None,
) -> Dict[str, Any]:
    available = list(((backup.get(name) or {}).get("items") or []))
    by_key = {_key(item, key): item for item in available}
    missing = [value for value in selected if value not in by_key]
    if missing:
        raise ValidationError("selection is absent from the chosen backup: %s" % missing, path="$.%s" % name)
    old_versions = dict(((current.get(name) or {}).get("inner_version") or {}))
    versions = {}
    update_keys = {str(value) for value in updates}
    selected_keys = {str(value) for value in selected}
    if update_keys - selected_keys:
        raise ValidationError(
            "update markers must refer to selected content",
            path="$.%s" % (update_path or name),
        )
    for item in available:
        value = _key(item, key)
        lookup = str(value)
        old = int(old_versions.get(lookup, old_versions.get(value, 0)) or 0)
        versions[lookup] = old + 1 if lookup in update_keys and old else (old or 1)
    return {"items": [copy.deepcopy(by_key[value]) for value in selected], "inner_version": versions}


def wtf_tree(backup: Mapping[str, Any], selected_roles: Sequence[str]) -> Dict[str, Any]:
    wanted = list(map(str, selected_roles))
    accounts = []
    raw = (backup.get("wtf") or {}).get("accounts") or backup.get("wtf_accounts") or []
    candidates: List[Tuple[str, str, str, int, Any, str]] = []
    backup_reference = str(backup.get("sn") or backup.get("backup_sn") or "")
    for account in raw:
        account_name = str(account.get("name") or "")
        for server in account.get("servers", []):
            server_name = str(server.get("name") or "")
            for index, role in enumerate(server.get("items", [])):
                role_id = role.get("role_id") or role.get("id") or role.get("name") if isinstance(role, dict) else role
                selector_source = "%s\0%s\0%s\0%d\0%s" % (backup_reference, account_name, server_name, index, role_id)
                selector = "wtf_" + hashlib.sha256(selector_source.encode("utf-8")).hexdigest()[:20]
                candidates.append((account_name, server_name, str(role_id), index, role, selector))
    selected_positions: set[Tuple[str, str, int]] = set()
    for selected in wanted:
        exact = [(account, server, index) for account, server, _role_id, index, _role, selector in candidates if selector == selected]
        legacy = [(account, server, index) for account, server, role_id, index, _role, _selector in candidates if role_id == selected]
        matches = exact or legacy
        if len(matches) != 1:
            message = "WTF role selector is absent" if not matches else "legacy WTF role value is ambiguous; use the backup selector"
            raise ValidationError(message, path="$.wtf_role_ids")
        selected_positions.add(matches[0])
    for account in raw:
        account_copy = {k: copy.deepcopy(v) for k, v in account.items() if k != "servers"}
        servers = []
        for server in account.get("servers", []):
            chosen = []
            for index, role in enumerate(server.get("items", [])):
                if (str(account.get("name") or ""), str(server.get("name") or ""), index) in selected_positions:
                    chosen.append(copy.deepcopy(role))
            if chosen:
                server_copy = {k: copy.deepcopy(v) for k, v in server.items() if k != "items"}
                server_copy["items"] = chosen
                servers.append(server_copy)
        if servers:
            account_copy["servers"] = servers
            accounts.append(account_copy)
    return {"accounts": accounts}


CONFIG_GROUPS = (
    ("known_addon", "addon_id", "known_addon_ids", "known_addon_update_ids"),
    ("unknown_addon", None, "unknown_addon_ids", "unknown_addon_update_ids"),
    ("material", "name", "material_names", "material_update_names"),
    ("font", None, "font_names", "font_update_names"),
)


def selected_wtf_account(value: Mapping[str, Any]) -> str:
    accounts = ((value.get("wtf") or {}).get("accounts") or []) if isinstance(value.get("wtf"), dict) else []
    selected = [str(account.get("name") or "") for account in accounts if isinstance(account, dict)]
    selected = [account for account in selected if account]
    return selected[0] if len(selected) == 1 else ""


def current_wtf_selectors(backup: Mapping[str, Any], current: Mapping[str, Any]) -> List[str]:
    available = safe_backup_detail(backup).get("wtf_roles") or []
    selected = []
    accounts = ((current.get("wtf") or {}).get("accounts") or []) if isinstance(current.get("wtf"), dict) else []
    for account in accounts:
        if not isinstance(account, dict):
            continue
        for server in account.get("servers") or []:
            if not isinstance(server, dict):
                continue
            for role in server.get("items") or []:
                role_id = role.get("role_id") or role.get("id") or role.get("name") if isinstance(role, dict) else role
                matches = [item for item in available if (
                    str(item.get("account") or "") == str(account.get("name") or "")
                    and str(item.get("server") or "") == str(server.get("name") or "")
                    and str(item.get("role_id") or item.get("name") or "") == str(role_id or "")
                )]
                if len(matches) != 1:
                    raise ValidationError("current WTF role is absent from the live backup", path="$.wtf_role_ids")
                selected.append(str(matches[0]["selector"]))
    return selected


def selected_wa_group(
    backup: Mapping[str, Any], current: Mapping[str, Any], name: str,
    selected: Sequence[str], updates: Sequence[str], account: str,
    update_path: Optional[str] = None,
) -> Dict[str, Any]:
    available = list(((backup.get(name) or {}).get("items") or []))
    by_uid = {
        str(item.get("uid")): item for item in available
        if isinstance(item, dict) and item.get("uid") is not None
    }
    missing = [uid for uid in selected if uid not in by_uid]
    if missing:
        raise ValidationError("selection is absent from the chosen backup: %s" % missing, path="$.%s_ids" % name)
    account_info = ((backup.get("extra") or {}).get("wa_account_info") or {}) if isinstance(backup.get("extra"), dict) else {}
    mapping = {
        str(item.get("uid")): item.get("id")
        for item in (account_info.get(account) or [])
        if isinstance(item, dict) and item.get("uid") is not None
    } if isinstance(account_info, dict) else {}
    unavailable = [uid for uid in selected if uid not in mapping]
    if unavailable:
        raise ValidationError("WA selection is unavailable for the selected WTF account", path="$.%s_ids" % name)
    old_versions = dict(((current.get(name) or {}).get("inner_version") or {}))
    versions: Dict[str, int] = {}
    update_keys = {str(value) for value in updates}
    selected_keys = {str(value) for value in selected}
    if update_keys - selected_keys:
        raise ValidationError(
            "update markers must refer to selected content",
            path="$.%s" % (update_path or (name + "_ids")),
        )
    for item in available:
        uid = str(item.get("uid"))
        old = int(old_versions.get(uid, 0) or 0)
        versions[uid] = old + 1 if uid in update_keys and old else (old or 1)
    chosen = []
    for uid in selected:
        item = copy.deepcopy(by_uid[uid])
        if name == "unknown_wa":
            item["id"] = mapping[uid]
        chosen.append(item)
    return {"items": chosen, "inner_version": versions}


def config_form(current: Mapping[str, Any], backup: Mapping[str, Any], doc: Mapping[str, Any]) -> Dict[str, Any]:
    defaults = {
        "scope": "public", "backup_sn": "", "desc": "", "update_desc": "", "title": "",
        "display_imgs": [], "share_code_life_type": "seven_day", "brief_desc": "",
        "price_fen": 0, "need_buy": 0, "buy_life_type": "seven_day",
        "jump_room": False, "room_id": "", "channel_id": "", "channel_type": "",
        "sync_room": False, "creation_statement": "", "with_associate": False,
        "associated_acts": [], "need_anchor_vip": False, "vip_levels": [],
    }
    form = {
        name: copy.deepcopy(current[name] if name in current and current[name] is not None else default)
        for name, default in defaults.items()
    }
    apply_present(form, doc, form.keys())
    for group, key, selected_name, update_name in CONFIG_GROUPS:
        if selected_name in doc:
            form[group] = selected_group(
                backup, current, group, key, doc[selected_name], doc.get(update_name, []), update_name,
            )
        else:
            current_selected = [
                _key(item, key) for item in ((current.get(group) or {}).get("items") or [])
            ]
            form[group] = selected_group(
                backup, current, group, key, current_selected, doc.get(update_name, []), update_name,
            )
    if "wtf_role_ids" in doc:
        form["wtf"] = wtf_tree(backup, doc["wtf_role_ids"])
    else:
        form["wtf"] = wtf_tree(backup, current_wtf_selectors(backup, current))
    account = selected_wtf_account(form)
    current_account = selected_wtf_account(current)
    account_changed = "wtf_role_ids" in doc and account != current_account
    for group, selected_name, update_name in (
        ("known_wa", "known_wa_ids", "known_wa_update_ids"),
        ("unknown_wa", "unknown_wa_ids", "unknown_wa_update_ids"),
    ):
        if selected_name in doc:
            selected = doc[selected_name]
            if selected and not account:
                raise ValidationError("select one WTF role before selecting WA content", path="$.wtf_role_ids")
            form[group] = selected_wa_group(
                backup, current, group, selected, doc.get(update_name, []), account, update_name,
            )
        elif account_changed:
            form[group] = selected_wa_group(backup, current, group, [], [], account)
        else:
            current_selected = [
                str(item.get("uid")) for item in ((current.get(group) or {}).get("items") or [])
                if isinstance(item, dict) and item.get("uid") is not None
            ]
            form[group] = selected_wa_group(
                backup, current, group, current_selected, doc.get(update_name, []), account, update_name,
            )
    if current.get("retail_ui_config") is not None:
        form["retail_ui_config"] = copy.deepcopy(current["retail_ui_config"])
    form["display_imgs"] = _remote_urls(form.get("display_imgs") or [], "config.display_imgs")
    form["vip_levels"] = _remote_ints(form.get("vip_levels") or [], ("level", "id", "value"), "config.vip_levels")
    if (form.get("known_addon", {}).get("items") or form.get("unknown_addon", {}).get("items")) and not form.get("wtf", {}).get("accounts"):
        raise ValidationError("select at least one WTF role when selecting addon content", path="$.wtf_role_ids")
    content_groups = ("known_addon", "unknown_addon", "wtf", "material", "font")
    if not any(form.get(name, {}).get("items") or form.get(name, {}).get("accounts") for name in content_groups):
        raise ValidationError("DD configuration content cannot contain only WA selections", path="$.known_addon_ids")
    validate_locked_usage_mode(current, form, doc)
    normalize_commercial(form, "config", create=not bool(current))
    return form


def config_readback_projection(value: Any) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        return {}
    projected = dict(value)
    if "need_buy" in projected:
        projected["need_buy"] = 1 if projected["need_buy"] else 0
    for name in ("known_addon", "unknown_addon", "material", "font", "known_wa", "unknown_wa"):
        if projected.get(name) is None:
            projected[name] = {"items": [], "inner_version": {}}
    if projected.get("wtf") is None:
        projected["wtf"] = {"accounts": []}
    if projected.get("vip_levels") is None:
        projected["vip_levels"] = []
    return projected


WA_FIELDS = (
    "game_type", "scope", "name", "game_version", "brief_desc", "display_imgs", "category_ids",
    "content", "desc", "update_desc", "version", "with_file", "file_path", "file_install_path",
    "parse_wa_uid", "parse_wa_id", *COMMERCIAL,
)

WA_CREATE_DEFAULTS = {
    "share_code_life_type": "seven_day",
    "need_buy": False,
    "buy_life_type": "seven_day",
    "category_ids": ["ui_original"],
    "file_install_path": "Interface/Addons",
    "vip_levels": [],
    "version": "0",
}


def wa_form(value: Mapping[str, Any]) -> Dict[str, Any]:
    form = {name: copy.deepcopy(value[name]) for name in WA_FIELDS if name in value}
    form["scope"] = copy.deepcopy(value.get("scope") or "public")
    form["price_fen"] = copy.deepcopy(value.get("price_fen") or 0)
    form["vip_levels"] = _remote_ints(value.get("vip_levels") or [], ("level", "id", "value"), "wa.vip_levels")
    form["version"] = copy.deepcopy(value.get("version") or "0")
    if "game_type" in form:
        form["game_type"] = _remote_int(form["game_type"], ("game_type", "id", "value"), "wa.game_type")
    if "display_imgs" in form:
        form["display_imgs"] = _remote_urls(form["display_imgs"], "wa.display_imgs")
    if "category_ids" in form:
        form["category_ids"] = _remote_strings(
            form["category_ids"], ("c_id", "category_id", "id", "value"),
            "wa.category_ids", allow_int=True,
        )
    normalize_commercial(form, "wa")
    return form


def validate_commercial_submission(form: Mapping[str, Any], resource: str) -> None:
    if form.get("scope") == "private" and not form.get("share_code_life_type"):
        if resource != "config" or not form.get("need_buy"):
            raise ValidationError("private publication requires share_code_life_type", path="$.share_code_life_type")
    if form.get("need_buy"):
        if form.get("price_fen") is None:
            raise ValidationError("paid publication requires price_fen", path="$.price_fen")
        price = int(form.get("price_fen") or 0)
        if price != 0 and not 10 <= price <= 20000:
            raise ValidationError("price_fen must be zero or between 10 and 20000", path="$.price_fen")
        if not form.get("buy_life_type"):
            raise ValidationError("paid publication requires buy_life_type", path="$.buy_life_type")
    if form.get("jump_room") and not form.get("room_id"):
        raise ValidationError("room association requires room_id", path="$.room_id")
    if not form.get("creation_statement"):
        raise ValidationError("creation_statement is required by the DD editor", path="$.creation_statement")
    if form.get("with_associate") and not form.get("associated_acts"):
        raise ValidationError("content association requires associated_acts", path="$.associated_acts")


def validate_plugin_submission(form: Mapping[str, Any], doc: Mapping[str, Any]) -> None:
    required = (
        "game_versions", "name", "description", "primary_category_id", "release_type",
        "version", "html_desc", "update_desc",
    )
    for name in required:
        if not form.get(name):
            raise ValidationError("field is required by the DD plugin editor", path="$.%s" % name)
    if not (form.get("logo") or doc.get("logo_file")):
        raise ValidationError("plugin logo is required", path="$.logo")
    if not ((form.get("detail_imgs") or []) or doc.get("detail_img_files")):
        raise ValidationError("at least one plugin detail image is required", path="$.detail_imgs")
    if not (form.get("detail_url") or doc.get("file")):
        raise ValidationError("plugin archive is required", path="$.file")
    validate_commercial_submission(form, "plugin")


def validate_config_submission(form: Mapping[str, Any], doc: Mapping[str, Any]) -> None:
    for name in ("backup_sn", "title", "brief_desc", "desc"):
        if not form.get(name):
            raise ValidationError("field is required by the DD configuration editor", path="$.%s" % name)
    if not ((form.get("display_imgs") or []) or doc.get("display_img_files")):
        raise ValidationError("at least one configuration display image is required", path="$.display_imgs")
    validate_commercial_submission(form, "config")


def validate_wa_submission(form: Mapping[str, Any], doc: Mapping[str, Any]) -> None:
    for name in ("name", "game_version", "brief_desc", "category_ids", "content", "desc", "update_desc"):
        if not form.get(name):
            raise ValidationError("field is required by the DD WA editor", path="$.%s" % name)
    if not ((form.get("display_imgs") or []) or doc.get("display_img_files")):
        raise ValidationError("at least one WA display image is required", path="$.display_imgs")
    validate_commercial_submission(form, "wa")


class DD:
    platform = "dd"

    @staticmethod
    def _fresh_detail(session: Sidecar, resource: str, reference: str) -> Dict[str, Any]:
        endpoint = {"plugin": "/addon/detail_v2", "config": "/share/detail", "wa": "/wa/detail"}[resource]
        for attempt in range(2):
            current = detail(session, resource, reference)
            if current.get("is_owner") is False:
                raise FuploadError(
                    "DD target is not owned by the current author",
                    kind="ownership_error", stage="dependency_get", endpoint=endpoint,
                )
            game_type = current.get("game_type") or (current.get("game_types") or [None])[0]
            name = str(current.get("name") or current.get("title") or "")
            listing = author_item(session, resource, reference, name, game_type)
            # DD detail and author-list timestamps come from independent read
            # models. Detail is authoritative for the form; list only
            # cross-checks ownership when detail omits is_owner.
            if current.get("is_owner") is True or listing:
                return current
            if attempt == 0:
                time.sleep(1)
        raise FuploadError(
            "DD target ownership could not be verified from detail or author list",
            kind="ownership_error",
            stage="dependency_get",
            endpoint=endpoint,
        )

    @staticmethod
    def _archive(path: str, suffixes: Sequence[str], limit: Optional[int] = None) -> None:
        source = Path(path)
        if source.suffix.lower() not in suffixes:
            raise ValidationError("file extension is not supported", path="$.file")
        if limit is not None and source.stat().st_size > limit:
            raise ValidationError("file exceeds the platform limit", path="$.file")

    @staticmethod
    def _validate_choices(payload: Any, selected: Sequence[Any], keys: Sequence[str], path: str) -> None:
        available = _option_values(payload, keys)
        values = [value for value in selected if value not in (None, "")]
        if values and not available:
            raise FuploadError("live option response contained no selectable values", kind="platform_data_error")
        if available and any(str(value) not in available for value in values):
            raise ValidationError("selection contains an unavailable live option", path=path)

    def _validate_options(self, session: Sidecar, resource: str, form: Mapping[str, Any]) -> None:
        game_type = form.get("game_type")
        if resource == "plugin":
            versions = session.get("/game_versions/list", {"game_type": game_type})
            self._validate_choices(versions, form.get("game_versions") or [], ("game_version", "version", "value"), "$.game_versions")
            categories = session.get("/addon/category", {})
            tree = _addon_category_tree(categories)
            if not tree:
                raise FuploadError("live plugin category response contained no selectable values", kind="platform_data_error")
            primary = str(form.get("primary_category_id") or "")
            if primary not in tree:
                raise ValidationError("primary_category_id must be a live top-level category", path="$.primary_category_id")
            selected_children = {str(value) for value in form.get("second_category_ids") or []}
            if selected_children - tree[primary]:
                raise ValidationError("second_category_ids must belong to primary_category_id", path="$.second_category_ids")
            if tree[primary] and not selected_children:
                raise ValidationError("select at least one child category", path="$.second_category_ids")
        elif resource == "wa":
            versions = session.get("/game_versions/list", {"game_type": game_type})
            self._validate_choices(versions, [form.get("game_version")], ("game_version", "version", "value"), "$.game_version")
            categories = session.get("/wa/categories", {"game_type": game_type})
            available_categories = _wa_category_values(categories)
            selected_categories = {str(value) for value in (form.get("category_ids") or []) if str(value) != "ui_original"}
            if selected_categories and not available_categories:
                raise FuploadError("live WA category response contained no selectable values", kind="platform_data_error")
            if selected_categories - available_categories:
                raise ValidationError("category_ids contains an unavailable live option", path="$.category_ids")

        if form.get("buy_life_type"):
            self._validate_choices(LIFE_TYPES, [form.get("buy_life_type")], ("value",), "$.buy_life_type")
        if form.get("share_code_life_type"):
            self._validate_choices(LIFE_TYPES, [form.get("share_code_life_type")], ("value",), "$.share_code_life_type")

        if form.get("need_anchor_vip"):
            vip_levels = session.get("/anchor_vip/level/list", {"enrich_acts": "false"})
            self._validate_choices(vip_levels, form.get("vip_levels") or [], ("id", "level", "value"), "$.vip_levels")

        if form.get("jump_room"):
            channels = safe_channels(session.cc_get("https://api.cc.163.com/v1/mixteammsgproxy/channelList?source=pluginPublish"))
            if not channels["items"]:
                raise FuploadError("live channel response contained no selectable values", kind="platform_data_error")
            wanted = (str(form.get("room_id")), str(form.get("channel_id")), str(form.get("channel_type")))
            available = {(str(item["room_id"]), str(item["channel_id"]), str(item["channel_type"])) for item in channels["items"]}
            if wanted not in available:
                raise ValidationError("room/channel selection is unavailable", path="$.channel_id")

        if form.get("with_associate"):
            references = self._associated_refs(session, game_type)
            if not references:
                raise FuploadError("live association response contained no selectable values", kind="platform_data_error")
            for item in form.get("associated_acts") or []:
                reference = (str(item.get("act_type")), str(item.get("sn"))) if isinstance(item, dict) else ("", str(item))
                if reference not in references:
                    raise ValidationError("associated_acts contains an unavailable author item", path="$.associated_acts")

        game_types = session.get("/game_type/list", {})
        self._validate_choices(game_types, [game_type], ("game_type",), "$.game_type")

    @staticmethod
    def _associated_refs(session: Sidecar, game_type: Any) -> set[Tuple[str, str]]:
        payloads = (
            ("addon", _author_items(session, "plugin", "", game_type)),
            ("share", _author_items(session, "config", "", game_type)),
            ("wa", _author_items(session, "wa", "", game_type)),
        )
        references: set[Tuple[str, str]] = set()
        for kind, source_items in payloads:
            for item in source_items:
                reference = item.get("sn") or item.get("share_sn")
                if reference:
                    references.add((kind, str(reference)))
        return references

    def execute_write(self, resource: str, action: str, doc: Dict[str, Any], session_id: Optional[str] = None) -> Any:
        if not session_id:
            raise FuploadError("DD live writes require --session from `dd session start`", kind="session_required", stage="session")
        from .dd_broker import execute

        return execute(session_id, "write", resource, action, doc)

    def execute_write_on(self, session: Sidecar, resource: str, action: str, doc: Dict[str, Any]) -> Any:
        if action == "delete" and resource in ("plugin", "config", "wa"):
            return self._delete(session, resource, doc)
        if resource == "plugin":
            return self._write_plugin(session, action, doc)
        if resource == "config":
            return self._write_config(session, action, doc)
        if resource == "wa":
            return self._write_wa(session, action, doc)
        raise FuploadError("unsupported DD write operation", kind="unsupported_operation")

    def _delete(self, session: Sidecar, resource: str, doc: Mapping[str, Any]) -> Dict[str, Any]:
        reference = str(doc["sn"])
        before = self._fresh_detail(session, resource, reference)
        endpoints = {"plugin": "/addon/delete", "config": "/share/delete", "wa": "/wa/delete"}
        game_type = before.get("game_type") or (before.get("game_types") or [None])[0]
        if not game_type and resource == "config" and before.get("backup_sn"):
            backup = result(session.get("/backup/detail", {"sn": before["backup_sn"]}))
            if isinstance(backup, dict):
                game_type = backup.get("game_type")
        if not game_type:
            raise FuploadError(
                "DD target game type could not be resolved before delete",
                kind="dependency_error",
                stage="dependency_get",
            )
        response = session.post(endpoints[resource], {"sn": reference})
        name = str(before.get("name") or before.get("title") or "")
        remaining = _readback(
            lambda: author_item(session, resource, reference, name, game_type), endpoints[resource]
        )
        if remaining:
            raise FuploadError(
                "delete response succeeded but the target remains in the author list",
                kind="verification_required", stage="readback", endpoint=endpoints[resource], verification_required=True,
            )
        return {"result": response, "deleted": True, "sn": reference, "before": safe_detail(resource, before), "readback": {"present": False}}

    def _write_plugin(self, session: Sidecar, action: str, doc: Dict[str, Any]) -> Any:
        if action == "create":
            current: Dict[str, Any] = {}
            form = copy.deepcopy(PLUGIN_CREATE_DEFAULTS)
            apply_present(form, doc, PLUGIN_FIELDS)
        else:
            current = self._fresh_detail(session, "plugin", doc["sn"])
            game_type = current.get("game_type") or (current.get("game_types") or [None])[0]
            listing = author_item(
                session, "plugin", str(doc["sn"]), str(current.get("name") or ""), game_type,
            )
            form = plugin_form(current, listing)
            allowed = PLUGIN_EDIT_FIELDS if action == "edit" else ("game_versions", "detail_url", "release_type", "version", "update_desc")
            current_version = str(form.get("version") or "").strip()
            apply_present(form, doc, allowed)
            if current.get("assign_user_sn") and form.get("scope", "public") != "public":
                raise ValidationError("assigned plugins can only use public scope", path="$.scope")
            if "game_type" in doc and str(doc["game_type"]) != str(current.get("game_type") or (current.get("game_types") or [None])[0]):
                raise ValidationError("game_type is locked after plugin creation", path="$.game_type")
            form["sn"] = doc["sn"]
            if action == "update" and current_version and str(form.get("version") or "").strip().casefold() == current_version.casefold():
                raise ValidationError("version already exists; overwrite is not allowed", path="$.version")
            if action == "update":
                try:
                    history_versions = load_plugin_history_versions(
                        session, str(doc["sn"]), form.get("game_type"),
                    )
                except FuploadError:
                    history_versions = set()
                candidate = str(form.get("version") or "").strip().casefold()
                if candidate and candidate in history_versions:
                    raise ValidationError("version already exists; overwrite is not allowed", path="$.version")
        if doc.get("file"):
            self._archive(doc["file"], (".zip",))
        validate_locked_usage_mode(current, form, doc)
        normalize_commercial(form, "plugin", create=action == "create")
        validate_plugin_submission(form, doc)
        self._validate_options(session, "plugin", form)
        validate_no_display_objects(form, "plugin")
        if doc.get("logo_file"):
            form["logo"] = session.upload(doc["logo_file"], "addon", file_name="", media=True, max_bytes=10 * 1024 * 1024)
        if doc.get("detail_img_files"):
            existing_images = list(form.get("detail_imgs") or [])
            if len(existing_images) + len(doc["detail_img_files"]) > 8:
                raise ValidationError("plugin detail images cannot exceed eight", path="$.detail_img_files")
            form["detail_imgs"] = existing_images + [session.upload(path, "addon", file_name="", media=True, max_bytes=10 * 1024 * 1024) for path in doc["detail_img_files"]]
        if doc.get("file"):
            form["detail_url"] = session.upload(doc["file"], "addon", file_name="addon.zip")
        endpoint = "/addon/create" if action == "create" else "/addon/modify"
        response = session.post(endpoint, form)
        reference = response_reference(response, "sn") or str(form.get("sn") or "")
        if action == "create" and not reference:
            reference = created_reference(session, "plugin", str(form.get("name") or ""), form.get("game_type"))
        if action == "create" and not reference:
            raise FuploadError(
                "plugin was submitted but its reference could not be resolved; read the author list before retrying",
                kind="verification_required", stage="readback", verification_required=True,
            )
        stable_fields = (
            "game_type", "scope", "addon_type", "name", "description", "logo", "detail_imgs",
            "primary_category_id", "second_category_ids", "html_desc", "update_desc", "share_code_life_type",
            "creation_statement", "need_buy",
            "price_fen", "buy_life_type", "jump_room", "room_id", "channel_id", "channel_type",
            "sync_room", "with_associate", "associated_acts", "need_anchor_vip", "vip_levels",
        )
        if action != "update":
            raw_readback: Any = {}
            actual: Mapping[str, Any] = {}
            unresolved: set[str] = set()
            author = {}
            for attempt in range(6):
                raw_readback = _readback(
                    lambda: detail(session, "plugin", reference), "/addon/detail_v2"
                )
                actual = plugin_form(raw_readback)
                author = author_item(
                    session, "plugin", reference, str(form.get("name") or ""), form.get("game_type")
                )
                author_actual = plugin_form(author) if author else {}
                detail_mismatches = {
                    name for name in stable_fields
                    if name in form and (name not in actual or not _same_readback(form[name], actual[name]))
                }
                author_mismatches = {
                    name for name in stable_fields
                    if name in form and (name not in author_actual or not _same_readback(form[name], author_actual[name]))
                }
                unresolved = detail_mismatches & author_mismatches
                if not unresolved:
                    break
                if attempt < 5:
                    time.sleep(1)
            if unresolved:
                raise FuploadError(
                    "write readback did not match field(s): %s" % ", ".join(sorted(unresolved)),
                    kind="verification_required",
                    stage="readback",
                    endpoint="/addon/detail_v2",
                    verification_required=True,
                    details={
                        "fields": sorted(unresolved),
                        "projections": {
                            "detail_v2": "mismatch",
                            "author_list": "mismatch" if author else "missing",
                        },
                    },
                )
        else:
            raw_readback = _readback(
                lambda: detail(session, "plugin", reference), "/addon/detail_v2"
            ) if reference else {}
            actual = plugin_form(raw_readback) if raw_readback else {}
        if action in ("create", "update"):
            # addon_versions can remain empty for private plugins, so version
            # confirmation uses the two projections the official author UI exposes.
            # Those projections can lag an accepted mutation briefly, so poll
            # with GET-only reads and never replay the mutation.
            update_fields = ("game_versions", "detail_url", "release_type", "version", "update_desc")
            detail_mismatches: List[str] = []
            author_mismatches: List[str] = []
            author: Mapping[str, Any] = {}
            for attempt in range(6):
                if attempt:
                    raw_readback = _readback(
                        lambda: detail(session, "plugin", reference), "/addon/detail_v2"
                    )
                detail_version = plugin_version_projection(raw_readback)
                detail_mismatches = [
                    name for name in update_fields
                    if name in form and (name not in detail_version or not _same_readback(form[name], detail_version[name]))
                ]
                author = author_item(
                    session, "plugin", reference, str(form.get("name") or ""), form.get("game_type")
                )
                author_actual = plugin_version_projection(author) if author else {}
                author_mismatches = [
                    name for name in update_fields
                    if name in form and (name not in author_actual or not _same_readback(form[name], author_actual[name]))
                ]
                if not (detail_mismatches and author_mismatches):
                    break
                if attempt < 5:
                    time.sleep(1)
            if detail_mismatches and author_mismatches:
                raise FuploadError(
                    "submitted plugin version is not visible in official readback projections",
                    kind="verification_required",
                    stage="readback",
                    endpoint="/addon/detail_v2",
                    verification_required=True,
                    details={
                        "fields": sorted(set(detail_mismatches) | set(author_mismatches)),
                        "projections": {
                            "detail_v2": "mismatch",
                            "author_list": "mismatch" if author else "missing",
                        },
                    },
                )
        return {"result": response, "reference": reference, "readback": safe_detail("plugin", raw_readback) if reference else None}

    def _backup(self, session: Sidecar, backup_sn: str) -> Dict[str, Any]:
        listing = session.get("/backup/list", {})
        if backup_sn and not any(str(x.get("sn") or x.get("backup_sn")) == str(backup_sn) for x in items(listing)):
            raise ValidationError("backup_sn is not present in the current DD backup list", path="$.backup_sn")
        payload = session.get("/backup/detail", {"sn": backup_sn})
        value = result(payload)
        if not isinstance(value, dict):
            raise FuploadError("DD backup detail was not found", kind="not_found")
        return value

    def _write_config(self, session: Sidecar, action: str, doc: Dict[str, Any]) -> Any:
        backup_changed = False
        if action == "create":
            current: Dict[str, Any] = {}
            backup_sn = doc["backup_sn"]
            backup_changed = True
        else:
            current = self._fresh_detail(session, "config", doc["share_sn"])
            if not current.get("backup_sn"):
                time.sleep(1)
                current = detail(session, "config", doc["share_sn"])
            backup_sn = str(doc.get("backup_sn") or current.get("backup_sn") or "")
            if backup_sn != str(current.get("backup_sn") or ""):
                backup_changed = True
                required = ("known_addon_ids", "unknown_addon_ids", "wtf_role_ids", "material_names", "font_names", "known_wa_ids", "unknown_wa_ids")
                missing = [name for name in required if name not in doc]
                if missing:
                    raise ValidationError("changing backup_sn requires complete reselection", path="$.%s" % missing[0])
        backup = self._backup(session, backup_sn)
        form = config_form(current, backup, doc)
        form["backup_sn"] = backup_sn
        game_type = int(backup.get("game_type") or 0)
        if game_type == 10001 and backup_changed and "retail_ui_config" not in doc:
            raise ValidationError("retail_ui_config must be explicitly selected for a retail backup", path="$.retail_ui_config")
        if "retail_ui_config" in doc:
            retail_current = {} if backup_changed else current
            form["retail_ui_config"] = resolve_retail_ui_config(backup, retail_current, doc["retail_ui_config"])
        elif game_type != 10001:
            form.pop("retail_ui_config", None)
        if action != "create":
            form["share_sn"] = doc["share_sn"]
        validation_form = dict(form)
        validation_form["game_type"] = current.get("game_type") or backup.get("game_type")
        validate_config_submission(form, doc)
        self._validate_options(session, "config", validation_form)
        validate_no_display_objects(form, "config")
        if doc.get("display_img_files"):
            existing_images = list(form.get("display_imgs") or [])
            if len(existing_images) + len(doc["display_img_files"]) > 8:
                raise ValidationError("configuration display images cannot exceed eight", path="$.display_img_files")
            form["display_imgs"] = existing_images + [session.upload(path, "share", media=True, max_bytes=10 * 1024 * 1024) for path in doc["display_img_files"]]
        endpoint = "/share/create" if action == "create" else "/share/modify"
        response = session.post(endpoint, form)
        reference = response_reference(response, "share_sn", "sn") or str(form.get("share_sn") or "")
        if action == "create" and not reference:
            reference = created_reference(session, "config", str(form.get("title") or ""), validation_form.get("game_type"))
        if action == "create" and not reference:
            raise FuploadError(
                "configuration was submitted but its reference could not be resolved; read the author list before retrying",
                kind="verification_required", stage="readback", verification_required=True,
            )
        stable_fields = (
            "backup_sn", "scope", "title", "brief_desc", "desc", "update_desc", "display_imgs",
            "share_code_life_type", "creation_statement", "need_buy", "price_fen", "buy_life_type",
            "jump_room", "room_id", "channel_id", "channel_type", "sync_room", "with_associate",
            "associated_acts", "need_anchor_vip", "vip_levels", "known_addon", "unknown_addon", "wtf",
            "material", "font", "known_wa", "unknown_wa", "retail_ui_config",
        )
        raw_readback, _actual = _readback_until_fields(
            lambda: detail(session, "config", reference),
            config_readback_projection,
            form,
            stable_fields,
            "/share/detail",
        )
        return {"result": response, "reference": reference, "readback": safe_detail("config", raw_readback) if reference else None}

    def _write_wa(self, session: Sidecar, action: str, doc: Dict[str, Any]) -> Any:
        if action == "create":
            current: Dict[str, Any] = {}
            form = copy.deepcopy(WA_CREATE_DEFAULTS)
            apply_present(form, doc, WA_FIELDS)
        else:
            current = self._fresh_detail(session, "wa", doc["sn"])
            form = wa_form(current)
            allowed = WA_FIELDS if action == "edit" else ("content", "update_desc", "version", "with_file", "file_path", "file_install_path", "parse_wa_uid", "parse_wa_id")
            apply_present(form, doc, allowed)
            if current.get("assign_user_sn") and form.get("scope", "public") != "public":
                raise ValidationError("assigned WA records can only use public scope", path="$.scope")
            if "game_type" in doc and str(doc["game_type"]) != str(current.get("game_type")):
                raise ValidationError("game_type is locked after WA creation", path="$.game_type")
            form["sn"] = doc["sn"]
            if action == "update" and not version_greater(form.get("version"), current.get("version")):
                raise ValidationError("version must be greater than the current version", path="$.version")
        if doc.get("file"):
            self._archive(doc["file"], (".zip",), 50 * 1024 * 1024)
            form["with_file"] = True
        if form.get("with_file") and not (doc.get("file") or form.get("file_path")):
            raise ValidationError("with_file=true requires an existing or new WA material ZIP", path="$.file")
        if form.get("with_file") and not form.get("file_install_path"):
            raise ValidationError("with_file=true requires file_install_path", path="$.file_install_path")
        content = str(form.get("content") or "")
        if not content.startswith("!WA:2!"):
            form["parse_wa_uid"] = ""
            form["parse_wa_id"] = ""
        else:
            parsed = session.call("parse_wa", content=content)
            if not isinstance(parsed, dict) or not parsed.get("parse_wa_uid") or not parsed.get("parse_wa_id"):
                raise FuploadError(
                    "DD native WA parser did not return parse identifiers",
                    kind="native_parser_error",
                    stage="native_parser",
                )
            form["parse_wa_uid"] = parsed["parse_wa_uid"]
            form["parse_wa_id"] = parsed["parse_wa_id"]
        validate_locked_usage_mode(current, form, doc)
        normalize_commercial(form, "wa", create=action == "create")
        form["category_ids"] = [str(category_id) for category_id in (form.get("category_ids") or [])]
        validate_wa_submission(form, doc)
        self._validate_options(session, "wa", form)
        validate_no_display_objects(form, "wa")
        if doc.get("display_img_files"):
            existing_images = list(form.get("display_imgs") or [])
            if len(existing_images) + len(doc["display_img_files"]) > 8:
                raise ValidationError("WA display images cannot exceed eight", path="$.display_img_files")
            form["display_imgs"] = existing_images + [session.upload(path, "wa", media=True, max_bytes=10 * 1024 * 1024) for path in doc["display_img_files"]]
        if doc.get("file"):
            form["file_path"] = session.upload(doc["file"], "wa", file_name="wa_materials.zip", max_bytes=50 * 1024 * 1024)
        endpoint = "/wa/create" if action == "create" else "/wa/modify"
        response = session.post(endpoint, form)
        reference = response_reference(response, "sn") or str(form.get("sn") or "")
        if action == "create" and not reference:
            reference = created_reference(session, "wa", str(form.get("name") or ""), form.get("game_type"))
        if action == "create" and not reference:
            raise FuploadError(
                "WA was submitted but its reference could not be resolved; read the author list before retrying",
                kind="verification_required", stage="readback", verification_required=True,
            )
        stable_fields = (
            "game_type", "scope", "name", "game_version", "brief_desc", "display_imgs", "category_ids",
            "content", "desc", "update_desc", "version", "with_file", "file_path", "file_install_path",
            "parse_wa_uid", "parse_wa_id", "share_code_life_type", "creation_statement", "need_buy",
            "price_fen", "buy_life_type", "jump_room", "room_id", "channel_id", "channel_type",
            "sync_room", "with_associate", "associated_acts", "need_anchor_vip", "vip_levels",
        )
        raw_readback, _actual = _readback_until_fields(
            lambda: detail(session, "wa", reference),
            lambda value: value,
            form,
            stable_fields,
            "/wa/detail",
        )
        readback = safe_detail("wa", raw_readback) if reference else None
        return {"result": response, "reference": reference, "readback": readback}

    def execute_read(self, resource: str, action: str, args: Any, session_id: Optional[str] = None) -> Any:
        if resource == "session":
            from . import dd_broker

            if action == "doctor":
                return dd_broker.doctor()
            if action == "start":
                return dd_broker.start(bool(getattr(args, "confirm_close_gui", False)))
            if action == "status":
                return dd_broker.status(session_id)
            if action == "stop":
                if not session_id:
                    raise FuploadError("dd session stop requires --session", kind="session_required", stage="session")
                return dd_broker.stop(session_id)
        if not session_id:
            raise FuploadError("DD live reads require --session from `dd session start`", kind="session_required", stage="session")
        from .dd_broker import execute

        payload = {
            key: value for key, value in vars(args).items()
            if key not in {"handler", "platform", "resource", "action", "input", "dry_run", "session"}
        }
        return execute(session_id, "read", resource, action, payload)

    def execute_read_on(self, session: Sidecar, resource: str, action: str, args: Any) -> Any:
        if resource == "plugin":
            if action == "list": return readable_author_list(session, "plugin", args.keyword, args.game_type, args.page, args.page_size)
            if action == "get": return safe_detail("plugin", detail(session, "plugin", args.sn))
            if action == "categories": return safe_plugin_categories(session.get("/addon/category", {}))
            if action == "game-versions": return safe_game_versions(session.get("/game_versions/list", {"game_type": args.game_type}), args.game_type)
            if action == "versions": return session.get("/addon/addon_versions", {"sn": args.sn, "game_type": args.game_type, "page": args.page})
        if resource == "config":
            if action == "list": return readable_author_list(session, "config", args.keyword, args.game_type, args.page, args.page_size)
            if action == "get": return safe_detail("config", detail(session, "config", args.sn))
            if action == "backups": return safe_backup_list(session.get("/backup/list", {}))
            if action == "backup-get":
                payload = session.get("/backup/detail", {"sn": args.sn})
                return safe_backup_detail(result(payload))
        if resource == "wa":
            if action == "list": return readable_author_list(session, "wa", args.keyword, args.game_type, args.page, args.page_size)
            if action == "get": return safe_detail("wa", detail(session, "wa", args.sn))
            if action == "categories": return safe_wa_categories(session.get("/wa/categories", {"game_type": args.game_type}), args.game_type)
        if resource == "options":
            if action == "game-types": return safe_game_types(session.get("/game_type/list", {}))
            if action == "channels": return safe_channels(session.cc_get("https://api.cc.163.com/v1/mixteammsgproxy/channelList?" + urllib.parse.urlencode({"source": "pluginPublish"})))
            if action == "life-types": return {"total": len(LIFE_TYPES), "items": list(LIFE_TYPES), "source": "NetEase DD official client enum"}
            if action == "vip-levels": return session.get("/anchor_vip/level/list", {"enrich_acts": "false"})
            if action == "associated-acts": return safe_associated_acts(session, args.game_type)
        raise FuploadError("unsupported DD read operation", kind="unsupported_operation")
