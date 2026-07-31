"""NetEase DD provider using the official native client as a sidecar."""

from __future__ import annotations

import copy
import hashlib
import json
import mimetypes
import os
import queue
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple
import urllib.parse

from .errors import FuploadError, ValidationError


EXPECTED_DD_VERSION = os.environ.get("FUPLOAD_DD_EXPECTED_VERSION", "any")
LIFE_TYPES = [
    {"name": "7 days", "value": "seven_day"},
    {"name": "14 days", "value": "fourteen_day"},
    {"name": "30 days", "value": "thirty_day"},
    {"name": "60 days", "value": "sixty_day"},
    {"name": "90 days", "value": "ninety_day"},
    {"name": "forever", "value": "forever"},
]


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
    roots = [Path(value) / "CCVoiceHub" for value in (
        os.environ.get("APPDATA", ""), os.environ.get("LOCALAPPDATA", ""),
    ) if value]
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
    configured = os.environ.get("FUPLOAD_DD_DIR") or os.environ.get("NETEASE_DD_DIR")
    if configured:
        roots.append(Path(configured))
    roots.extend(_running_dd_dirs())
    roots.extend(_registry_dd_dirs())
    roots.extend(_user_config_dd_dirs())
    roots.extend((
        Path(os.environ.get("LOCALAPPDATA", "")) / "NetEaseDD",
        Path(os.environ.get("PROGRAMFILES", "")) / "NetEaseDD",
        Path(os.environ.get("PROGRAMFILES(X86)", "")) / "NetEaseDD",
        Path("C:/NetEase/NetEaseDD"), Path("D:/Software/NetEaseDD"), Path("D:/NetEaseDD"),
    ))
    return roots


def discover_dd() -> Path:
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
    valid = []
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
            valid.append(resolved)
    if not valid:
        raise FuploadError(
            "cannot locate a valid NetEase DD installation; set FUPLOAD_DD_DIR to the version directory containing netease_dd.exe",
            kind="installation_not_found",
        )
    return sorted(valid, key=lambda p: p.name)[-1]


def state_dir() -> Path:
    appdata = os.environ.get("APPDATA")
    if not appdata:
        raise FuploadError("APPDATA is not set; DD sidecar state cannot be located")
    result = Path(appdata) / "CCVoiceHub" / "Fupload"
    result.mkdir(parents=True, exist_ok=True)
    return result


class Sidecar:
    def __init__(self) -> None:
        self.dd_dir = discover_dd()
        self.process: Optional[subprocess.Popen[str]] = None
        self.counter = 0
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
            stderr=subprocess.DEVNULL, text=True, encoding="utf-8", errors="replace",
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
            raise FuploadError(str((ready.get("error") or {}).get("message") or "DD sidecar failed to start"), kind="authentication_error")
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
        for line in self.process.stdout:
            if line.startswith("FUPLOAD_RESULT "):
                try:
                    self.responses.put(json.loads(line[len("FUPLOAD_RESULT "):]))
                except ValueError:
                    self.responses.put(FuploadError("DD sidecar returned invalid JSON", kind="sidecar_error"))
        self.responses.put(FuploadError("DD sidecar exited without a result", kind="sidecar_error"))

    def _next_result(
        self, *, timeout: float = 180, endpoint: Optional[str] = None,
        verification_required: bool = False,
    ) -> Dict[str, Any]:
        try:
            value = self.responses.get(timeout=timeout)
        except queue.Empty as exc:
            raise FuploadError(
                "DD sidecar response timed out",
                kind="timeout",
                endpoint=endpoint,
                verification_required=verification_required,
            ) from exc
        if isinstance(value, FuploadError):
            raise value
        if not isinstance(value, dict):
            raise FuploadError("DD sidecar returned an invalid result", kind="sidecar_error")
        return value

    def call(self, action: str, **values: Any) -> Any:
        assert self.process and self.process.stdin
        self.counter += 1
        request = {"id": self.counter, "action": action, **values}
        self.process.stdin.write(json.dumps(request, ensure_ascii=False, separators=(",", ":")) + "\n")
        self.process.stdin.flush()
        method = str(values.get("method") or "").upper()
        endpoint = str(values.get("path") or "") or None
        uncertain = action == "upload" or (action == "request" and method == "POST")
        response = self._next_result(endpoint=endpoint, verification_required=uncertain)
        if response.get("id") != self.counter:
            raise FuploadError("DD sidecar response order was invalid", kind="sidecar_error")
        if not response.get("ok"):
            raise FuploadError(str((response.get("error") or {}).get("message") or "DD operation failed"), kind="platform_error")
        return response.get("data")

    def get(self, path: str, params: Optional[Mapping[str, Any]] = None) -> Any:
        return self._business_response(
            path, self.call("request", method="GET", path=path, payload=dict(params or {}))
        )

    def post(self, path: str, body: Mapping[str, Any]) -> Any:
        return self._business_response(
            path, self.call("request", method="POST", path=path, payload=dict(body))
        )

    @staticmethod
    def _business_response(path: str, payload: Any) -> Any:
        if isinstance(payload, dict) and "code" in payload and payload.get("code") != 0:
            raise FuploadError(
                str(payload.get("msg") or payload.get("message") or "DD operation failed"),
                endpoint=path,
                business_code=payload.get("code"),
            )
        return payload

    def upload(self, file: str, business: str, *, file_name: Optional[str] = None, media: bool = False, max_bytes: Optional[int] = None) -> str:
        name = file_name or Path(file).name
        size = Path(file).stat().st_size
        if max_bytes is not None and size > max_bytes:
            raise ValidationError("file exceeds the platform limit", path="$.file")
        mime = mimetypes.guess_type(name)[0] or "application/octet-stream"
        if media and not mime.startswith("image/"):
            raise ValidationError("media file must have an image MIME type", path="$.file")
        if name.lower().endswith(".zip"):
            mime = "application/x-zip-compressed"
        file_type = "a19-ui-media" if media else "a19-ui-res"
        upload_business = "img" if media else business
        result = self.call("upload", file=file, meta={
            "file_type": file_type, "file_name": name, "business_id": upload_business, "mime_type": mime,
        })
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


def _records(payload: Any) -> List[Dict[str, Any]]:
    records: List[Dict[str, Any]] = []

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            if any(key in value for key in ("id", "_id", "c_id", "sn", "value", "game_version", "game_version_id", "category_id")):
                records.append(value)
            for child in value.values():
                if isinstance(child, (dict, list)):
                    walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)

    walk(payload)
    return records


def _record_values(payload: Any, keys: Sequence[str]) -> set[str]:
    values: set[str] = set()
    raw = result(payload)
    if isinstance(raw, list) and all(not isinstance(item, (dict, list)) for item in raw):
        values.update(str(item) for item in raw if item is not None)
    for record in _records(payload):
        for key in keys:
            if record.get(key) is not None:
                values.add(str(record[key]))
        if "c_id" in record:
            values.add(str(record["c_id"]))
        if "_id" in record:
            values.add(str(record["_id"]))
    return values


def author_listing(session: Sidecar, resource: str, keyword: str, game_type: Any) -> Any:
    common = {"game_type": game_type, "origin": "created", "page": 1, "size": 100}
    if resource == "plugin":
        return session.post("/addon/addon_list", {
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


def readable_author_list(
    session: Sidecar, resource: str, keyword: str, game_type: Any,
    page: int, size: int,
) -> Dict[str, Any]:
    common = {"game_type": game_type, "origin": "created", "page": page, "size": size}
    def load(search: str) -> Any:
        if resource == "plugin":
            return session.post("/addon/addon_list", {
                **common, "category": 0,
                "name_or_author_name_or_share_code": search, "sort_type": 2,
            })
        if resource == "config":
            return session.get("/share/list", {**common, "search_text": search, "sort_type": "mtime"})
        return session.get("/wa/list", {
            **common, "search_text": search, "category_id": "", "sort_type": "mtime",
        })

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
    return {"total": len(result_items), "items": result_items}


def safe_channels(payload: Any) -> Dict[str, Any]:
    raw = payload.get("data") if isinstance(payload, dict) else payload
    if isinstance(raw, dict):
        raw_items = raw.get("list") or raw.get("items") or raw.get("channels") or raw.get("data") or []
    else:
        raw_items = raw if isinstance(raw, list) else []
    result_items = []
    def walk(value: Any) -> None:
        if isinstance(value, dict):
            if value.get("teamId") or value.get("channelId") or value.get("id"):
                result_items.append({
                    "room_id": str(value.get("teamId") or value.get("team_id") or value.get("room_id") or value.get("id") or ""),
                    "room_name": value.get("teamName") or value.get("team_name") or value.get("room_name") or value.get("name"),
                    "channel_id": str(value.get("channelId") or value.get("channel_id") or ""),
                    "channel_name": value.get("channelName") or value.get("channel_name") or value.get("name"),
                    "channel_type": str(value.get("channelType") or value.get("channel_type") or ""),
                })
            for child in value.values():
                if isinstance(child, (list, dict)):
                    walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)
    walk(raw_items)
    unique = []
    seen = set()
    for item in result_items:
        key = (item["room_id"], item["channel_id"], item["channel_type"])
        if key not in seen:
            seen.add(key)
            unique.append(item)
    return {"total": len(unique), "items": unique}


def version_greater(candidate: Any, current: Any) -> bool:
    left = str(candidate or "").strip()
    right = str(current or "").strip()
    if left.isdigit() and right.isdigit():
        return int(left) > int(right)
    def parts(value: str) -> List[int]:
        return [int(part) for part in value.split(".") if part.isdigit()]
    lp, rp = parts(left), parts(right)
    return bool(lp and rp and lp > rp)


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
    for account in (wtf.get("accounts") if isinstance(wtf, dict) else []) or []:
        if not isinstance(account, dict):
            continue
        for server in account.get("servers") or []:
            if isinstance(server, dict):
                role_summary.append({
                    "account": account.get("name"), "server": server.get("name"),
                    "roles": [str(item) for item in server.get("items") or []],
                })
    result_value["wtf_roles"] = role_summary
    retail = value.get("retail_ui_config")
    if isinstance(retail, dict):
        result_value["retail_ui_config"] = safe_retail_catalog(value)
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
    common = {"game_type": game_type, "origin": "created", "page": 1, "size": 100}
    sources = (
        ("addon", session.post("/addon/addon_list", {**common, "category": 0, "name_or_author_name_or_share_code": "", "sort_type": 2})),
        ("share", session.get("/share/list", {**common, "search_text": "", "sort_type": "mtime"})),
        ("wa", session.get("/wa/list", {**common, "search_text": "", "category_id": "", "sort_type": "mtime"})),
    )
    result_items = []
    for kind, payload in sources:
        for item in items(payload):
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


COMMERCIAL = (
    "scope", "share_code_life_type", "need_buy", "price_fen", "buy_life_type",
    "jump_room", "room_id", "channel_id", "channel_type", "sync_room",
    "creation_statement", "with_associate", "associated_acts", "need_anchor_vip", "vip_levels",
)


def normalize_commercial(form: Dict[str, Any]) -> None:
    if not form.get("need_buy"):
        form["price_fen"] = 0
        form["buy_life_type"] = form.get("buy_life_type") or "seven_day"
    if form.get("scope") == "private":
        form["sync_room"] = False
        form["need_anchor_vip"] = False
        form["vip_levels"] = []
    elif form.get("scope") == "public":
        form["share_code_life_type"] = "forever"
    if not form.get("jump_room"):
        form.update({"room_id": "", "channel_id": "", "channel_type": "", "sync_room": False})
    if not form.get("with_associate"):
        form["associated_acts"] = []
    if not form.get("need_anchor_vip"):
        form["vip_levels"] = []


PLUGIN_FIELDS = (
    "game_type", "game_versions", "scope", "addon_type", "name", "description", "logo",
    "detail_imgs", "primary_category_id", "second_category_ids", "detail_url", "release_type",
    "version", "html_desc", "update_desc", *COMMERCIAL,
)


def plugin_form(value: Mapping[str, Any]) -> Dict[str, Any]:
    latest = value.get("latest_version") if isinstance(value.get("latest_version"), dict) else {}
    form = {name: copy.deepcopy(value.get(name)) for name in PLUGIN_FIELDS}
    for name in ("game_versions", "detail_url", "release_type", "version"):
        if latest.get({"detail_url": "file_path"}.get(name, name)) is not None:
            form[name] = copy.deepcopy(latest.get({"detail_url": "file_path"}.get(name, name)))
    form["game_type"] = form.get("game_type") or (value.get("game_types") or [None])[0]
    form["second_category_ids"] = [
        category_id for category_id in (form.get("second_category_ids") or [])
        if str(category_id) != "999"
    ]
    return form


def merge_plugin_version_fields(form: Dict[str, Any], fallback: Mapping[str, Any]) -> None:
    fallback_form = plugin_form(fallback)
    for name in ("game_versions", "detail_url", "release_type", "version", "update_desc"):
        if fallback_form.get(name) not in (None, "", []):
            form[name] = copy.deepcopy(fallback_form[name])


def _key(item: Any, key: Optional[str]) -> Any:
    if key is None:
        return item if not isinstance(item, dict) else item.get("name", item.get("id"))
    return item.get(key) if isinstance(item, dict) else item


def selected_group(backup: Mapping[str, Any], current: Mapping[str, Any], name: str, key: Optional[str], selected: Sequence[Any], updates: Sequence[Any]) -> Dict[str, Any]:
    available = list(((backup.get(name) or {}).get("items") or []))
    by_key = {_key(item, key): item for item in available}
    missing = [value for value in selected if value not in by_key]
    if missing:
        raise ValidationError("selection is absent from the chosen backup: %s" % missing, path="$.%s" % name)
    old_versions = dict(((current.get(name) or {}).get("inner_version") or {}))
    versions = {}
    for value in selected:
        old = int(old_versions.get(str(value), old_versions.get(value, 0)) or 0)
        versions[str(value)] = old + 1 if value in updates and old else (old or 1)
    return {"items": [copy.deepcopy(by_key[value]) for value in selected], "inner_version": versions}


def wtf_tree(backup: Mapping[str, Any], selected_roles: Sequence[str]) -> Dict[str, Any]:
    wanted = set(map(str, selected_roles))
    accounts = []
    raw = (backup.get("wtf") or {}).get("accounts") or backup.get("wtf_accounts") or []
    for account in raw:
        account_copy = {k: copy.deepcopy(v) for k, v in account.items() if k != "servers"}
        servers = []
        for server in account.get("servers", []):
            chosen = []
            for role in server.get("items", []):
                role_id = role.get("role_id") or role.get("id") if isinstance(role, dict) else role
                if str(role_id) in wanted:
                    chosen.append(copy.deepcopy(role))
            if chosen:
                server_copy = {k: copy.deepcopy(v) for k, v in server.items() if k != "items"}
                server_copy["items"] = chosen
                servers.append(server_copy)
        if servers:
            account_copy["servers"] = servers
            accounts.append(account_copy)
    found = {
        str(role.get("role_id") or role.get("id") if isinstance(role, dict) else role)
        for account in accounts for server in account["servers"] for role in server["items"]
    }
    if found != wanted:
        raise ValidationError("one or more WTF roles are absent from the chosen backup", path="$.wtf_role_ids")
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


def selected_wa_group(
    backup: Mapping[str, Any], current: Mapping[str, Any], name: str,
    selected: Sequence[str], updates: Sequence[str], account: str,
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
    chosen = []
    for uid in selected:
        old = int(old_versions.get(uid, 0) or 0)
        versions[uid] = old + 1 if uid in updates and old else (old or 1)
        item = copy.deepcopy(by_uid[uid])
        if name == "unknown_wa":
            item["id"] = mapping[uid]
        chosen.append(item)
    return {"items": chosen, "inner_version": versions}


def config_form(current: Mapping[str, Any], backup: Mapping[str, Any], doc: Mapping[str, Any]) -> Dict[str, Any]:
    form = {name: copy.deepcopy(current.get(name)) for name in (
        "backup_sn", "scope", "title", "brief_desc", "desc", "update_desc", "display_imgs", *COMMERCIAL,
    )}
    apply_present(form, doc, form.keys())
    for group, key, selected_name, update_name in CONFIG_GROUPS:
        if selected_name in doc:
            form[group] = selected_group(backup, current, group, key, doc[selected_name], doc.get(update_name, []))
        else:
            form[group] = copy.deepcopy(current.get(group) or {"items": [], "inner_version": {}})
    form["wtf"] = wtf_tree(backup, doc["wtf_role_ids"]) if "wtf_role_ids" in doc else copy.deepcopy(current.get("wtf") or {"accounts": []})
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
            form[group] = selected_wa_group(backup, current, group, selected, doc.get(update_name, []), account)
        elif account_changed:
            form[group] = {"items": [], "inner_version": {}}
        else:
            form[group] = copy.deepcopy(current.get(group) or {"items": [], "inner_version": {}})
    if current.get("retail_ui_config") is not None:
        form["retail_ui_config"] = copy.deepcopy(current["retail_ui_config"])
    if (form.get("known_addon", {}).get("items") or form.get("unknown_addon", {}).get("items")) and not form.get("wtf", {}).get("accounts"):
        raise ValidationError("select at least one WTF role when selecting addon content", path="$.wtf_role_ids")
    content_groups = ("known_addon", "unknown_addon", "wtf", "material", "font")
    if not any(form.get(name, {}).get("items") or form.get(name, {}).get("accounts") for name in content_groups):
        raise ValidationError("DD configuration content cannot contain only WA selections", path="$.known_addon_ids")
    normalize_commercial(form)
    return form


WA_FIELDS = (
    "game_type", "scope", "name", "game_version", "brief_desc", "display_imgs", "category_ids",
    "content", "desc", "update_desc", "version", "with_file", "file_path", "file_install_path",
    "parse_wa_uid", "parse_wa_id", *COMMERCIAL,
)


class DD:
    platform = "dd"

    @staticmethod
    def _archive(path: str, suffixes: Sequence[str], limit: int) -> None:
        source = Path(path)
        if source.suffix.lower() not in suffixes:
            raise ValidationError("file extension is not supported", path="$.file")
        if source.stat().st_size > limit:
            raise ValidationError("file exceeds the platform limit", path="$.file")

    @staticmethod
    def _validate_choices(payload: Any, selected: Sequence[Any], keys: Sequence[str], path: str) -> None:
        available = _record_values(payload, keys)
        values = [value for value in selected if value not in (None, "")]
        if values and not available:
            raise FuploadError("live option response contained no selectable values", kind="platform_data_error")
        if available and any(str(value) not in available for value in values):
            raise ValidationError("selection contains an unavailable live option", path=path)

    def _validate_options(self, session: Sidecar, resource: str, form: Mapping[str, Any]) -> None:
        game_type = form.get("game_type")
        if resource == "plugin":
            versions = session.get("/game_versions/list", {"game_type": game_type})
            self._validate_choices(versions, form.get("game_versions") or [], ("id", "game_version", "game_version_id", "value"), "$.game_versions")
            categories = session.get("/addon/category", {})
            self._validate_choices(categories, [form.get("primary_category_id")], ("id", "category_id", "value"), "$.primary_category_id")
            self._validate_choices(categories, form.get("second_category_ids") or [], ("id", "category_id", "value"), "$.second_category_ids")
        elif resource == "wa":
            versions = session.get("/game_versions/list", {"game_type": game_type})
            self._validate_choices(versions, [form.get("game_version")], ("id", "game_version", "game_version_id", "value"), "$.game_version")
            categories = session.get("/wa/categories", {"game_type": game_type})
            self._validate_choices(categories, [value for value in (form.get("category_ids") or []) if str(value) != "ui_original"], ("id", "category_id", "value"), "$.category_ids")

        if form.get("buy_life_type"):
            self._validate_choices(LIFE_TYPES, [form.get("buy_life_type")], ("value",), "$.buy_life_type")
        if form.get("share_code_life_type"):
            self._validate_choices(LIFE_TYPES, [form.get("share_code_life_type")], ("value",), "$.share_code_life_type")

        vip_levels = session.get("/anchor_vip/level/list", {"enrich_acts": "false"})
        if form.get("need_anchor_vip"):
            self._validate_choices(vip_levels, form.get("vip_levels") or [], ("id", "level", "value"), "$.vip_levels")

        channels = safe_channels(session.cc_get("https://api.cc.163.com/v1/mixteammsgproxy/channelList?source=pluginPublish"))
        if form.get("jump_room") and not channels["items"]:
            raise FuploadError("live channel response contained no selectable values", kind="platform_data_error")
        if form.get("jump_room"):
            wanted = (str(form.get("room_id")), str(form.get("channel_id")), str(form.get("channel_type")))
            available = {(str(item["room_id"]), str(item["channel_id"]), str(item["channel_type"])) for item in channels["items"]}
            if wanted not in available:
                raise ValidationError("room/channel selection is unavailable", path="$.channel_id")

        if form.get("with_associate"):
            references = self._associated_refs(session, game_type)
            if not references:
                raise FuploadError("live association response contained no selectable values", kind="platform_data_error")
            for item in form.get("associated_acts") or []:
                reference = str(item.get("sn")) if isinstance(item, dict) else str(item)
                if reference not in references:
                    raise ValidationError("associated_acts contains an unavailable author item", path="$.associated_acts")

    @staticmethod
    def _associated_refs(session: Sidecar, game_type: Any) -> set[str]:
        common = {"game_type": game_type, "origin": "created", "page": 1, "size": 100}
        payloads = (
            session.post("/addon/addon_list", {**common, "category": 0, "name_or_author_name_or_share_code": "", "sort_type": 2}),
            session.get("/share/list", {**common, "search_text": "", "sort_type": "mtime"}),
            session.get("/wa/list", {**common, "search_text": "", "category_id": "", "sort_type": "mtime"}),
        )
        references: set[str] = set()
        for payload in payloads:
            for item in items(payload):
                reference = item.get("sn") or item.get("share_sn")
                if reference:
                    references.add(str(reference))
        return references

    def execute_write(self, resource: str, action: str, doc: Dict[str, Any]) -> Any:
        with Sidecar() as session:
            if resource == "plugin":
                return self._write_plugin(session, action, doc)
            if resource == "config":
                return self._write_config(session, action, doc)
            if resource == "wa":
                return self._write_wa(session, action, doc)
        raise FuploadError("unsupported DD write operation", kind="unsupported_operation")

    def _write_plugin(self, session: Sidecar, action: str, doc: Dict[str, Any]) -> Any:
        if action == "create":
            form = {name: copy.deepcopy(doc.get(name)) for name in PLUGIN_FIELDS if name in doc}
        else:
            current = detail(session, "plugin", doc["sn"])
            form = plugin_form(current)
            fallback = author_item(
                session, "plugin", str(doc["sn"]), str(current.get("name") or ""),
                form.get("game_type"),
            )
            if fallback:
                merge_plugin_version_fields(form, fallback)
            allowed = PLUGIN_FIELDS if action == "edit" else ("game_versions", "detail_url", "release_type", "version", "update_desc")
            apply_present(form, doc, allowed)
            form["sn"] = doc["sn"]
            if action == "update":
                versions = items(session.get("/addon/addon_versions", {"sn": doc["sn"], "game_type": form.get("game_type"), "page": 1}))
                for item in versions:
                    if str(item.get("version") or item.get("current_version") or "").strip().lower() == str(form.get("version") or "").strip().lower():
                        raise ValidationError("version already exists; overwrite is not allowed", path="$.version")
        if doc.get("logo_file"):
            form["logo"] = session.upload(doc["logo_file"], "addon", media=True, max_bytes=10 * 1024 * 1024)
        if doc.get("detail_img_files"):
            form["detail_imgs"] = list(form.get("detail_imgs") or []) + [session.upload(path, "addon", media=True, max_bytes=10 * 1024 * 1024) for path in doc["detail_img_files"]]
        if doc.get("file"):
            self._archive(doc["file"], (".zip", ".rar", ".7z"), 300 * 1024 * 1024)
            form["detail_url"] = session.upload(doc["file"], "addon", file_name=Path(doc["file"]).name)
        normalize_commercial(form)
        self._validate_options(session, "plugin", form)
        endpoint = "/addon/create" if action == "create" else "/addon/modify"
        response = session.post(endpoint, form)
        reference = str((result(response) or {}).get("sn") if isinstance(result(response), dict) else result(response) or form.get("sn") or "")
        if action == "create" and not reference:
            reference = created_reference(session, "plugin", str(form.get("name") or ""), form.get("game_type"))
        if action == "create" and not reference:
            raise FuploadError(
                "plugin was submitted but its reference could not be resolved; read the author list before retrying",
                kind="verification_required", verification_required=True,
            )
        return {"result": response, "reference": reference, "readback": safe_detail("plugin", detail(session, "plugin", reference)) if reference else None}

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
            current = detail(session, "config", doc["share_sn"])
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
        if doc.get("display_img_files"):
            form["display_imgs"] = list(form.get("display_imgs") or []) + [session.upload(path, "share", media=True, max_bytes=10 * 1024 * 1024) for path in doc["display_img_files"]]
        if action != "create":
            form["share_sn"] = doc["share_sn"]
        validation_form = dict(form)
        validation_form["game_type"] = current.get("game_type") or backup.get("game_type")
        self._validate_options(session, "config", validation_form)
        endpoint = "/share/create" if action == "create" else "/share/modify"
        response = session.post(endpoint, form)
        reference = str((result(response) or {}).get("share_sn") if isinstance(result(response), dict) else result(response) or form.get("share_sn") or "")
        if action == "create" and not reference:
            reference = created_reference(session, "config", str(form.get("title") or ""), validation_form.get("game_type"))
        if action == "create" and not reference:
            raise FuploadError(
                "configuration was submitted but its reference could not be resolved; read the author list before retrying",
                kind="verification_required", verification_required=True,
            )
        return {"result": response, "reference": reference, "readback": safe_detail("config", detail(session, "config", reference)) if reference else None}

    def _write_wa(self, session: Sidecar, action: str, doc: Dict[str, Any]) -> Any:
        previous_content = ""
        if action == "create":
            form = {name: copy.deepcopy(doc.get(name)) for name in WA_FIELDS if name in doc}
        else:
            current = detail(session, "wa", doc["sn"])
            previous_content = str(current.get("content") or "")
            form = {name: copy.deepcopy(current.get(name)) for name in WA_FIELDS}
            allowed = WA_FIELDS if action == "edit" else ("content", "update_desc", "version", "with_file", "file_path", "file_install_path", "parse_wa_uid", "parse_wa_id")
            apply_present(form, doc, allowed)
            form["sn"] = doc["sn"]
            if action == "update" and not version_greater(form.get("version"), current.get("version")):
                raise ValidationError("version must be greater than the current version", path="$.version")
        if doc.get("display_img_files"):
            form["display_imgs"] = list(form.get("display_imgs") or []) + [session.upload(path, "wa", media=True, max_bytes=10 * 1024 * 1024) for path in doc["display_img_files"]]
        if doc.get("file"):
            self._archive(doc["file"], (".zip",), 50 * 1024 * 1024)
            form["file_path"] = session.upload(doc["file"], "wa", file_name="wa_materials.zip")
            form["with_file"] = True
        if not form.get("with_file"):
            form["file_path"] = ""
            form["file_install_path"] = ""
        content = str(form.get("content") or "")
        if not content.startswith("!WA:2!"):
            form["parse_wa_uid"] = ""
            form["parse_wa_id"] = ""
        elif action == "create" or ("content" in doc and str(doc.get("content")) != previous_content):
            parsed = session.call("parse_wa", content=content)
            if not isinstance(parsed, dict) or not parsed.get("parse_wa_uid") or not parsed.get("parse_wa_id"):
                raise FuploadError("DD native WA parser did not return parse identifiers", kind="native_parser_error")
            form["parse_wa_uid"] = parsed["parse_wa_uid"]
            form["parse_wa_id"] = parsed["parse_wa_id"]
        elif not form.get("parse_wa_uid") or not form.get("parse_wa_id"):
            raise ValidationError("WA2 content requires parse_wa_uid and parse_wa_id from the DD parser", path="$.parse_wa_uid")
        normalize_commercial(form)
        self._validate_options(session, "wa", form)
        endpoint = "/wa/create" if action == "create" else "/wa/modify"
        response = session.post(endpoint, form)
        reference = str((result(response) or {}).get("sn") if isinstance(result(response), dict) else result(response) or form.get("sn") or "")
        if action == "create" and not reference:
            reference = created_reference(session, "wa", str(form.get("name") or ""), form.get("game_type"))
        if action == "create" and not reference:
            raise FuploadError(
                "WA was submitted but its reference could not be resolved; read the author list before retrying",
                kind="verification_required", verification_required=True,
            )
        readback = safe_detail("wa", detail(session, "wa", reference)) if reference else None
        return {"result": response, "reference": reference, "readback": readback}

    def execute_read(self, resource: str, action: str, args: Any) -> Any:
        if resource == "session" and action == "doctor":
            with Sidecar():
                return {"authenticated": True, "dd_dir": str(discover_dd()), "device_state": str(state_dir() / "sidecar-device.json")}
        with Sidecar() as session:
            if resource == "plugin":
                if action == "list": return readable_author_list(session, "plugin", args.keyword, args.game_type, args.page, args.page_size)
                if action == "get": return safe_detail("plugin", detail(session, "plugin", args.sn))
                if action == "categories": return session.get("/addon/category", {})
                if action == "game-versions": return session.get("/game_versions/list", {"game_type": args.game_type})
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
                if action == "categories": return session.get("/wa/categories", {"game_type": args.game_type})
            if resource == "options":
                if action == "game-types": return safe_game_types(session.get("/game_type/list", {}))
                if action == "channels": return safe_channels(session.cc_get("https://api.cc.163.com/v1/mixteammsgproxy/channelList?" + urllib.parse.urlencode({"source": "pluginPublish"})))
                if action == "life-types": return {"total": len(LIFE_TYPES), "items": list(LIFE_TYPES), "source": "NetEase DD official client enum"}
                if action == "vip-levels": return session.get("/anchor_vip/level/list", {"enrich_acts": "false"})
                if action == "associated-acts": return safe_associated_acts(session, args.game_type)
        raise FuploadError("unsupported DD read operation", kind="unsupported_operation")
