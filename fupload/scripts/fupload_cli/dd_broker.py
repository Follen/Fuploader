"""Task-scoped DD broker owning one native sidecar login."""

from __future__ import annotations

import argparse
import ctypes
import json
import os
import socket
import subprocess
import sys
import time
import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

from .errors import FuploadError, redact
from .trust import verify_dd_executable


STATE_NAME = "broker.json"
STARTUP_NAME = "broker.starting.json"
MAX_REQUEST_BYTES = 64 * 1024 * 1024
IDLE_SECONDS = 10 * 60


def _dd_module():
    from . import dd

    return dd


def _state_dir() -> Path:
    return _dd_module().state_dir()


def _atomic_json(path: Path, value: Dict[str, Any]) -> None:
    temporary = path.with_name(path.name + ".tmp.%d" % os.getpid())
    temporary.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    os.replace(str(temporary), str(path))


def _read_json(path: Path) -> Dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise FuploadError("DD broker state is unreadable", kind="session_error", stage="session") from exc
    if not isinstance(value, dict):
        raise FuploadError("DD broker state is invalid", kind="session_error", stage="session")
    return value


def _pid_running(pid: int) -> bool:
    if os.name != "nt" or pid <= 0:
        return False
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_bool, ctypes.c_ulong]
    kernel32.OpenProcess.restype = ctypes.c_void_p
    kernel32.GetExitCodeProcess.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
    kernel32.GetExitCodeProcess.restype = ctypes.c_bool
    kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
    kernel32.CloseHandle.restype = ctypes.c_bool
    handle = kernel32.OpenProcess(0x1000, False, pid)
    if not handle:
        return False
    try:
        code = ctypes.c_ulong()
        return bool(kernel32.GetExitCodeProcess(handle, ctypes.byref(code))) and code.value == 259
    finally:
        kernel32.CloseHandle(handle)


def _top_level_windows(pid: int) -> List[int]:
    if os.name != "nt":
        return []
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.GetWindowThreadProcessId.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
    user32.GetWindowThreadProcessId.restype = ctypes.c_ulong
    windows: List[int] = []
    callback_type = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

    def visit(hwnd: int, _param: int) -> bool:
        owner = ctypes.c_ulong()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if owner.value == pid:
            windows.append(int(hwnd))
        return True

    callback = callback_type(visit)
    user32.EnumWindows.argtypes = [callback_type, ctypes.c_void_p]
    user32.EnumWindows.restype = ctypes.c_bool
    user32.EnumWindows(callback, 0)
    return windows


def running_dd_processes() -> List[Dict[str, Any]]:
    if os.name != "nt":
        return []
    from ctypes import wintypes

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

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel32.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(ProcessEntry)]
    kernel32.Process32FirstW.restype = wintypes.BOOL
    kernel32.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(ProcessEntry)]
    kernel32.Process32NextW.restype = wintypes.BOOL
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.QueryFullProcessImageNameW.argtypes = [
        wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD),
    ]
    kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
    kernel32.GetProcessTimes.argtypes = [
        wintypes.HANDLE, ctypes.POINTER(wintypes.FILETIME), ctypes.POINTER(wintypes.FILETIME),
        ctypes.POINTER(wintypes.FILETIME), ctypes.POINTER(wintypes.FILETIME),
    ]
    kernel32.GetProcessTimes.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL

    snapshot = kernel32.CreateToolhelp32Snapshot(0x00000002, 0)
    if snapshot == wintypes.HANDLE(-1).value:
        return []
    processes: List[Dict[str, Any]] = []
    entry = ProcessEntry()
    entry.dwSize = ctypes.sizeof(entry)
    try:
        more = bool(kernel32.Process32FirstW(snapshot, ctypes.byref(entry)))
        while more:
            if entry.szExeFile.casefold() == "netease_dd.exe":
                pid = int(entry.th32ProcessID)
                handle = kernel32.OpenProcess(0x1000, False, pid)
                if handle:
                    try:
                        size = wintypes.DWORD(32768)
                        buffer = ctypes.create_unicode_buffer(size.value)
                        creation = wintypes.FILETIME()
                        exit_time = wintypes.FILETIME()
                        kernel = wintypes.FILETIME()
                        user = wintypes.FILETIME()
                        if kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
                            started = 0
                            if kernel32.GetProcessTimes(
                                handle,
                                ctypes.byref(creation),
                                ctypes.byref(exit_time),
                                ctypes.byref(kernel),
                                ctypes.byref(user),
                            ):
                                started = (int(creation.dwHighDateTime) << 32) | int(creation.dwLowDateTime)
                            executable = Path(buffer.value).resolve()
                            signature: Optional[Dict[str, str]] = None
                            signature_error = ""
                            try:
                                signature = verify_dd_executable(executable)
                            except FuploadError as exc:
                                signature_error = str(exc)
                            process = {
                                "pid": pid,
                                "started": started,
                                "executable": str(executable),
                                "dd_dir": str(executable.parent),
                                "windows": _top_level_windows(pid),
                                "signature": signature,
                                "signature_error": signature_error,
                            }
                            if process["windows"]:
                                processes.append(process)
                    finally:
                        kernel32.CloseHandle(handle)
            more = bool(kernel32.Process32NextW(snapshot, ctypes.byref(entry)))
    finally:
        kernel32.CloseHandle(snapshot)
    return processes


def _same_process(expected: Dict[str, Any], actual: Dict[str, Any]) -> bool:
    return (
        int(expected.get("pid") or 0) == int(actual.get("pid") or 0)
        and int(expected.get("started") or 0) == int(actual.get("started") or 0)
        and os.path.normcase(str(expected.get("executable") or ""))
        == os.path.normcase(str(actual.get("executable") or ""))
    )


def _request_normal_close(processes: List[Dict[str, Any]]) -> None:
    if os.name != "nt":
        return
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.PostMessageW.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_void_p, ctypes.c_void_p]
    user32.PostMessageW.restype = ctypes.c_bool
    for process in processes:
        for hwnd in process.get("windows") or []:
            user32.PostMessageW(int(hwnd), 0x0010, 0, 0)


def _terminate_process(process: Dict[str, Any]) -> None:
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_bool, ctypes.c_ulong]
    kernel32.OpenProcess.restype = ctypes.c_void_p
    kernel32.TerminateProcess.argtypes = [ctypes.c_void_p, ctypes.c_uint]
    kernel32.TerminateProcess.restype = ctypes.c_bool
    kernel32.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
    kernel32.WaitForSingleObject.restype = ctypes.c_ulong
    kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
    kernel32.CloseHandle.restype = ctypes.c_bool
    handle = kernel32.OpenProcess(0x0001 | 0x00100000, False, int(process["pid"]))
    if not handle:
        raise FuploadError("verified DD GUI process could not be opened for termination", kind="gui_close_failed", stage="session")
    try:
        if not kernel32.TerminateProcess(handle, 1):
            raise FuploadError("verified DD GUI process could not be terminated", kind="gui_close_failed", stage="session")
        kernel32.WaitForSingleObject(handle, 5000)
    finally:
        kernel32.CloseHandle(handle)


def close_verified_gui(processes: List[Dict[str, Any]]) -> None:
    if any(not process.get("signature") for process in processes):
        raise FuploadError("an untrusted netease_dd.exe process is running", kind="trust_boundary", stage="session")
    if not processes:
        return
    _request_normal_close(processes)
    deadline = time.time() + 5
    while time.time() < deadline:
        live = running_dd_processes()
        if not any(any(_same_process(expected, current) for current in live) for expected in processes):
            break
        time.sleep(0.1)
    live = running_dd_processes()
    original_pids = {int(process["pid"]) for process in processes}
    if any(int(process["pid"]) not in original_pids for process in live):
        raise FuploadError("a new DD GUI process appeared while closing the confirmed instances", kind="gui_identity_changed", stage="session")
    for expected in processes:
        matches = [current for current in live if int(current["pid"]) == int(expected["pid"])]
        if not matches:
            continue
        current = matches[0]
        if not _same_process(expected, current) or not current.get("signature"):
            raise FuploadError("DD GUI process identity changed while closing", kind="gui_identity_changed", stage="session")
        _terminate_process(current)
    if running_dd_processes():
        raise FuploadError("DD GUI did not fully exit", kind="gui_close_failed", stage="session")


def _public_process(process: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "pid": process.get("pid"),
        "dd_dir": process.get("dd_dir"),
        "window_count": len(process.get("windows") or []),
        "signature": process.get("signature"),
    }


def _load_live_state() -> Optional[Dict[str, Any]]:
    path = _state_dir() / STATE_NAME
    if not path.exists():
        return None
    value = _read_json(path)
    if not _pid_running(int(value.get("pid") or 0)):
        try:
            path.unlink()
        except OSError:
            pass
        return None
    return value


def _remove_session_state(path: Path, session_id: str, timeout: float = 5) -> bool:
    deadline = time.monotonic() + timeout
    while True:
        try:
            current = _read_json(path)
        except FuploadError as exc:
            if isinstance(exc.__cause__, FileNotFoundError):
                return True
            if not isinstance(exc.__cause__, OSError):
                return False
        else:
            if current.get("session_id") != session_id:
                return False
            try:
                path.unlink()
                return True
            except FileNotFoundError:
                return True
            except OSError:
                pass
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.05)


def doctor() -> Dict[str, Any]:
    dd_dir, signature = _dd_module().discover_dd_info()
    processes = running_dd_processes()
    state = _load_live_state()
    return {
        "authenticated": False,
        "login_performed": False,
        "dd_dir": str(dd_dir),
        "installation_source": "automatic-discovery",
        "signature": signature,
        "state_directory": str(_state_dir()),
        "state_source": "windows-known-folder",
        "api_origin": "https://uiapi.w.163.com",
        "gui_running": bool(processes),
        "gui_processes": [_public_process(process) for process in processes],
        "untrusted_process_count": sum(1 for process in processes if not process.get("signature")),
        "broker_running": bool(state),
        "session_id": state.get("session_id") if state else None,
    }


def _send(value: Dict[str, Any], timeout: float = 300) -> Dict[str, Any]:
    state = _load_live_state()
    if not state:
        raise FuploadError("DD task session is not running", kind="session_not_running", stage="session")
    payload = dict(value)
    request = {
        "session_id": payload.pop("session_id", None),
        "auth_key": state.get("auth_key"),
        **payload,
    }
    if request["session_id"] != state.get("session_id"):
        raise FuploadError("DD session_id does not match the active task session", kind="session_mismatch", stage="session")
    data = (json.dumps(request, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
    if len(data) > MAX_REQUEST_BYTES:
        raise FuploadError("DD broker request is too large", kind="request_too_large", stage="session")
    write_sent = False
    try:
        with socket.create_connection(("127.0.0.1", int(state["port"])), timeout=10) as connection:
            connection.settimeout(timeout)
            connection.sendall(data)
            write_sent = request.get("command") == "write"
            received = bytearray()
            while b"\n" not in received:
                chunk = connection.recv(65536)
                if not chunk:
                    break
                received.extend(chunk)
                if len(received) > MAX_REQUEST_BYTES:
                    raise FuploadError(
                        "DD broker response is too large",
                        kind="response_too_large",
                        stage="session",
                        verification_required=write_sent,
                    )
    except FuploadError as exc:
        if write_sent and not exc.verification_required:
            raise FuploadError(
                str(exc),
                kind=exc.kind,
                stage=exc.stage or "session",
                endpoint=exc.endpoint,
                http_status=exc.http_status,
                business_code=exc.business_code,
                verification_required=True,
                details=exc.details,
            ) from exc
        raise
    except (OSError, ValueError) as exc:
        raise FuploadError(
            "DD broker connection failed",
            kind="session_connection",
            stage="session",
            verification_required=write_sent,
        ) from exc
    if b"\n" not in received:
        raise FuploadError(
            "DD broker closed without a complete response",
            kind="session_protocol",
            stage="session",
            verification_required=write_sent,
        )
    try:
        response = json.loads(bytes(received).split(b"\n", 1)[0].decode("utf-8"))
    except (UnicodeError, ValueError) as exc:
        raise FuploadError(
            "DD broker returned invalid JSON",
            kind="session_protocol",
            stage="session",
            verification_required=write_sent,
        ) from exc
    if not isinstance(response, dict):
        raise FuploadError("DD broker returned an invalid response", kind="session_protocol", stage="session")
    if not response.get("ok"):
        error = response.get("error") if isinstance(response.get("error"), dict) else {}
        raise FuploadError.from_dict(error)
    return response.get("data")


def start(confirm_close_gui: bool) -> Dict[str, Any]:
    existing = _load_live_state()
    if existing:
        active = status(str(existing["session_id"]))
        return {
            "session_id": existing["session_id"],
            "running": True,
            "reused": True,
            "login_count": active.get("login_count", 1),
            "broker_count": active.get("broker_count", 1),
            "sidecar_count": active.get("sidecar_count", 1),
            "native_login_count": active.get("native_login_count", 1),
            "credential_kind": active.get("credential_kind"),
        }
    processes = running_dd_processes()
    if processes and not confirm_close_gui:
        raise FuploadError(
            "DD GUI is running; explicit close confirmation is required before native login",
            kind="gui_close_confirmation_required",
            stage="session",
            details={"processes": [_public_process(process) for process in processes]},
        )
    close_verified_gui(processes)
    root = _state_dir()
    startup = root / STARTUP_NAME
    startup_id = uuid.uuid4().hex
    _atomic_json(startup, {"startup_id": startup_id, "auth_key": uuid.uuid4().hex + uuid.uuid4().hex})
    scripts_root = Path(__file__).resolve().parents[1]
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(scripts_root) + os.pathsep + environment.get("PYTHONPATH", "")
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    process = subprocess.Popen(
        [sys.executable, "-m", "fupload_cli.dd_broker", "--serve", startup_id],
        cwd=str(scripts_root),
        env=environment,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=flags,
    )
    deadline = time.time() + 90
    last_error = ""
    while time.time() < deadline:
        state = _load_live_state()
        if state and state.get("startup_id") == startup_id:
            return {
                "session_id": state["session_id"],
                "running": True,
                "reused": False,
                "login_count": 1,
                "broker_count": state.get("broker_count", 1),
                "sidecar_count": state.get("sidecar_count", 1),
                "native_login_count": state.get("native_login_count", 1),
                "credential_kind": state.get("credential_kind"),
                "closed_gui_processes": len(processes),
            }
        if startup.exists():
            try:
                pending = _read_json(startup)
                last_error = str(pending.get("error") or "")
            except FuploadError:
                pass
        if process.poll() is not None:
            break
        time.sleep(0.1)
    if process.poll() is None:
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            pass
    try:
        pending = _read_json(startup)
        if pending.get("startup_id") == startup_id:
            startup.unlink()
    except (FuploadError, OSError):
        pass
    raise FuploadError(last_error or "DD task session failed to start", kind="session_start_failed", stage="session")


def status(session_id: Optional[str] = None) -> Dict[str, Any]:
    state = _load_live_state()
    if not state:
        return {"running": False, "login_performed": False}
    chosen = session_id or str(state["session_id"])
    data = _send({"session_id": chosen, "command": "ping"}, timeout=10)
    return data


def stop(session_id: str) -> Dict[str, Any]:
    data = _send({"session_id": session_id, "command": "stop"}, timeout=30)
    deadline = time.monotonic() + 30
    while True:
        try:
            state = _load_live_state()
        except FuploadError as exc:
            if exc.kind != "session_error" or not isinstance(exc.__cause__, OSError):
                raise
        else:
            if not state:
                break
        if time.monotonic() >= deadline:
            raise FuploadError(
                "DD task session acknowledged stop but did not finish cleanup",
                kind="session_stop_failed",
                stage="session",
            )
        time.sleep(0.05)
    result = dict(data or {})
    result["cleanup_complete"] = True
    return result


def execute(session_id: str, kind: str, resource: str, action: str, payload: Dict[str, Any]) -> Any:
    return _send({
        "session_id": session_id,
        "command": kind,
        "resource": resource,
        "action": action,
        "payload": payload,
    })


def _read_request(connection: socket.socket) -> Dict[str, Any]:
    value = bytearray()
    while b"\n" not in value:
        chunk = connection.recv(65536)
        if not chunk:
            break
        value.extend(chunk)
        if len(value) > MAX_REQUEST_BYTES:
            raise FuploadError("DD broker request is too large", kind="request_too_large", stage="session")
    decoded = json.loads(bytes(value).split(b"\n", 1)[0].decode("utf-8"))
    if not isinstance(decoded, dict):
        raise ValueError("request must be an object")
    return decoded


def _serve(startup_id: str) -> int:
    root = _state_dir()
    startup_path = root / STARTUP_NAME
    pending = _read_json(startup_path)
    if pending.get("startup_id") != startup_id:
        return 2
    auth_key = str(pending.get("auth_key") or "")
    session_id = uuid.uuid4().hex
    state_path = root / STATE_NAME
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("127.0.0.1", 0))
    listener.listen(8)
    listener.settimeout(1)
    port = int(listener.getsockname()[1])
    started_at = time.time()
    last_activity = started_at
    state = {
        "schema": "fupload.dd-broker.v1",
        "startup_id": startup_id,
        "session_id": session_id,
        "auth_key": auth_key,
        "pid": os.getpid(),
        "port": port,
        "started_at": started_at,
        "last_activity": last_activity,
    }
    sidecar = None
    try:
        sidecar = _dd_module().Sidecar().__enter__()
        state["dd_dir"] = str(sidecar.dd_dir)
        state["signature"] = sidecar.signature
        state["credential_kind"] = sidecar.credential_kind
        state["broker_count"] = 1
        state["sidecar_count"] = 1
        state["native_login_count"] = 1
        _atomic_json(state_path, state)
        try:
            startup_path.unlink()
        except OSError:
            pass
        should_stop = False
        while not should_stop and time.time() - last_activity < IDLE_SECONDS:
            try:
                connection, _address = listener.accept()
            except socket.timeout:
                continue
            with connection:
                request: Dict[str, Any] = {}
                try:
                    request = _read_request(connection)
                    if request.get("auth_key") != auth_key or request.get("session_id") != session_id:
                        raise FuploadError("DD broker authentication failed", kind="session_mismatch", stage="session")
                    last_activity = time.time()
                    state["last_activity"] = last_activity
                    _atomic_json(state_path, state)
                    command = request.get("command")
                    if command == "ping":
                        data = {
                            "running": True,
                            "session_id": session_id,
                            "started_at": started_at,
                            "last_activity": last_activity,
                            "login_count": 1,
                            "broker_count": state.get("broker_count", 1),
                            "sidecar_count": state.get("sidecar_count", 1),
                            "native_login_count": state.get("native_login_count", 1),
                            "credential_kind": state.get("credential_kind"),
                            "dd_dir": state.get("dd_dir"),
                            "signature": state.get("signature"),
                        }
                    elif command == "stop":
                        data = {"running": False, "session_id": session_id, "logout_requested": True}
                        should_stop = True
                    elif command == "write":
                        data = _dd_module().DD().execute_write_on(
                            sidecar,
                            str(request.get("resource") or ""),
                            str(request.get("action") or ""),
                            request.get("payload") if isinstance(request.get("payload"), dict) else {},
                        )
                    elif command == "read":
                        arguments = request.get("payload") if isinstance(request.get("payload"), dict) else {}
                        data = _dd_module().DD().execute_read_on(
                            sidecar,
                            str(request.get("resource") or ""),
                            str(request.get("action") or ""),
                            SimpleNamespace(**arguments),
                        )
                    else:
                        raise FuploadError("unsupported DD broker command", kind="unsupported_operation", stage="session")
                    response = {"ok": True, "data": data}
                except FuploadError as exc:
                    response = {"ok": False, "error": exc.as_dict()}
                except Exception as exc:
                    response = {"ok": False, "error": FuploadError(
                        "DD broker operation failed (%s)" % type(exc).__name__,
                        kind="broker_error",
                        stage="session",
                        verification_required=request.get("command") == "write",
                    ).as_dict()}
                connection.sendall((json.dumps(response, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8"))
        return 0
    except Exception as exc:
        _atomic_json(startup_path, {
            "startup_id": startup_id,
            "error": redact(str(exc))[:400],
        })
        return 1
    finally:
        listener.close()
        if sidecar is not None:
            sidecar.__exit__(None, None, None)
        _remove_session_state(state_path, session_id)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--serve", required=True)
    args = parser.parse_args(argv)
    return _serve(args.serve)


if __name__ == "__main__":
    raise SystemExit(main())
