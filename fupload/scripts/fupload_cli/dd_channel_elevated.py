"""One-shot, same-user UAC transport for DD's optional channel read.

The pipe carries process/profile metadata and channel choices only. All runtime
credentials and HTTP authentication remain inside the process doing the read.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes as w
import json
import os
from pathlib import Path
import re
import struct
import subprocess
import sys
import time
import uuid


def runtime_python():
    # A venv redirector can spawn another PID; launch the real interpreter so
    # ShellExecuteEx's process handle remains the pipe client's exact PID.
    return str(Path(getattr(sys, '_base_executable', sys.executable)).resolve())

if __package__ in (None, ''):
    # Invoked with -I -S and an absolute, fixed script path; ignore cwd/PYTHONPATH.
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    __package__ = 'fupload_cli'

from .errors import FuploadError

LIMIT = 1048576
PREFIX = r'\\.\pipe\Fupload-DD-channels-'
TIMEOUT = 55


def fail(reason):
    messages = {'UAC_cancelled': 'DD channel access was cancelled in the Windows permission prompt.',
                'helper_timeout': 'DD channel helper timed out; retry this channel operation.'}
    return FuploadError(messages.get(reason, 'The one-time DD channel helper could not complete.'),
                        kind='desktop_channel_unavailable', stage='dependency_get',
                        details={'channel_stage': 'one_time_UAC', 'reason': reason})


class OVERLAPPED(ctypes.Structure):
    _fields_ = [('Internal', ctypes.c_size_t), ('InternalHigh', ctypes.c_size_t),
                ('Offset', w.DWORD), ('OffsetHigh', w.DWORD), ('hEvent', w.HANDLE)]


class SECURITY_ATTRIBUTES(ctypes.Structure):
    _fields_ = [('nLength', w.DWORD), ('lpSecurityDescriptor', ctypes.c_void_p), ('bInheritHandle', w.BOOL)]


class SHELLEXECUTEINFO(ctypes.Structure):
    _fields_ = [('cbSize', w.DWORD), ('fMask', w.ULONG), ('hwnd', w.HWND), ('lpVerb', w.LPCWSTR),
                ('lpFile', w.LPCWSTR), ('lpParameters', w.LPCWSTR), ('lpDirectory', w.LPCWSTR),
                ('nShow', ctypes.c_int), ('hInstApp', w.HINSTANCE), ('lpIDList', ctypes.c_void_p),
                ('lpClass', w.LPCWSTR), ('hkeyClass', w.HKEY), ('dwHotKey', w.DWORD),
                ('hIcon', w.HANDLE), ('hProcess', w.HANDLE)]


class Windows:
    def __init__(self):
        self.k = ctypes.WinDLL('kernel32', use_last_error=True)
        self.a = ctypes.WinDLL('advapi32', use_last_error=True)
        self.s = ctypes.WinDLL('shell32', use_last_error=True)
        definitions = {
            'GetCurrentProcess': ([], w.HANDLE), 'OpenProcess': ([w.DWORD, w.BOOL, w.DWORD], w.HANDLE),
            'CloseHandle': ([w.HANDLE], w.BOOL), 'LocalFree': ([ctypes.c_void_p], ctypes.c_void_p),
            'GetProcessId': ([w.HANDLE], w.DWORD),
            'GetProcessTimes': ([w.HANDLE] + [ctypes.POINTER(w.FILETIME)] * 4, w.BOOL),
            'QueryFullProcessImageNameW': ([w.HANDLE, w.DWORD, w.LPWSTR, ctypes.POINTER(w.DWORD)], w.BOOL),
            'CreateNamedPipeW': ([w.LPCWSTR, w.DWORD, w.DWORD, w.DWORD, w.DWORD, w.DWORD, w.DWORD, ctypes.POINTER(SECURITY_ATTRIBUTES)], w.HANDLE),
            'CreateFileW': ([w.LPCWSTR, w.DWORD, w.DWORD, ctypes.c_void_p, w.DWORD, w.DWORD, w.HANDLE], w.HANDLE),
            'ConnectNamedPipe': ([w.HANDLE, ctypes.POINTER(OVERLAPPED)], w.BOOL),
            'DisconnectNamedPipe': ([w.HANDLE], w.BOOL),
            'GetNamedPipeClientProcessId': ([w.HANDLE, ctypes.POINTER(w.ULONG)], w.BOOL),
            'GetNamedPipeServerProcessId': ([w.HANDLE, ctypes.POINTER(w.ULONG)], w.BOOL),
            'CreateEventW': ([ctypes.c_void_p, w.BOOL, w.BOOL, w.LPCWSTR], w.HANDLE),
            'WaitForSingleObject': ([w.HANDLE, w.DWORD], w.DWORD),
            'GetOverlappedResult': ([w.HANDLE, ctypes.POINTER(OVERLAPPED), ctypes.POINTER(w.DWORD), w.BOOL], w.BOOL),
            'CancelIoEx': ([w.HANDLE, ctypes.POINTER(OVERLAPPED)], w.BOOL),
            'ReadFile': ([w.HANDLE, ctypes.c_void_p, w.DWORD, ctypes.POINTER(w.DWORD), ctypes.POINTER(OVERLAPPED)], w.BOOL),
            'WriteFile': ([w.HANDLE, ctypes.c_void_p, w.DWORD, ctypes.POINTER(w.DWORD), ctypes.POINTER(OVERLAPPED)], w.BOOL),
        }
        for name, (args, result) in definitions.items():
            function = getattr(self.k, name); function.argtypes = args; function.restype = result
        self.a.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = [w.LPCWSTR, w.DWORD, ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(w.ULONG)]
        self.a.ConvertStringSecurityDescriptorToSecurityDescriptorW.restype = w.BOOL
        self.s.ShellExecuteExW.argtypes = [ctypes.POINTER(SHELLEXECUTEINFO)]
        self.s.ShellExecuteExW.restype = w.BOOL

    def identity(self, handle):
        from .dd_channel import process_sid
        created, exited, kernel, user = [w.FILETIME() for _ in range(4)]
        size, path = w.DWORD(32768), ctypes.create_unicode_buffer(32768)
        if (not self.k.GetProcessTimes(handle, ctypes.byref(created), ctypes.byref(exited), ctypes.byref(kernel), ctypes.byref(user)) or
                not self.k.QueryFullProcessImageNameW(handle, 0, path, ctypes.byref(size))):
            raise fail('helper_process_identity_unreadable')
        return {'sid': process_sid(self.k, handle), 'started': (created.dwHighDateTime << 32) | created.dwLowDateTime,
                'executable': str(Path(path.value).resolve())}

    def open_peer(self, pid):
        handle = self.k.OpenProcess(0x1000, False, pid)
        if not handle:
            raise fail('helper_peer_identity_unreadable')
        return handle

    def pipe(self, name, sid):
        descriptor = ctypes.c_void_p()
        # Protected DACL: only this Windows user (filtered/elevated token).
        if not self.a.ConvertStringSecurityDescriptorToSecurityDescriptorW('D:P(A;;GA;;;' + sid + ')', 1, ctypes.byref(descriptor), None):
            raise fail('helper_pipe_security_failed')
        try:
            security = SECURITY_ATTRIBUTES(ctypes.sizeof(SECURITY_ATTRIBUTES), descriptor, False)
            handle = self.k.CreateNamedPipeW(name, 0x40080003, 0x8, 1, LIMIT + 4, LIMIT + 4, 0, ctypes.byref(security))
            if handle == ctypes.c_void_p(-1).value:
                raise fail('helper_pipe_create_failed')
            return handle
        finally:
            self.k.LocalFree(descriptor)

    def launch(self, pipe, task, parent):
        args = ['-I', '-S', '-B', str(Path(__file__).resolve()), '--pipe', pipe, '--task', task,
                '--parent-pid', str(os.getpid()), '--parent-started', str(parent['started'])]
        info = SHELLEXECUTEINFO()
        info.cbSize, info.fMask, info.lpVerb = ctypes.sizeof(info), 0x40 | 0x100, 'runas'
        info.lpFile, info.lpParameters = runtime_python(), subprocess.list2cmdline(args)
        info.lpDirectory, info.nShow = str(Path(__file__).resolve().parent), 0
        if not self.s.ShellExecuteExW(ctypes.byref(info)):
            raise fail('UAC_cancelled' if ctypes.get_last_error() == 1223 else 'helper_launch_failed')
        if not info.hProcess:
            raise fail('helper_launch_process_missing')
        return info.hProcess

    def peer(self, pipe, client):
        pid = w.ULONG()
        function = self.k.GetNamedPipeClientProcessId if client else self.k.GetNamedPipeServerProcessId
        if not function(pipe, ctypes.byref(pid)):
            raise fail('helper_pipe_peer_unreadable')
        return pid.value

    def io(self, handle, kind, data, deadline):
        event = self.k.CreateEventW(None, True, False, None)
        if not event:
            raise fail('helper_pipe_event_failed')
        operation = OVERLAPPED(); operation.hEvent = event
        count = w.DWORD()
        buffer = ctypes.create_string_buffer(data if isinstance(data, bytes) else data)
        try:
            if kind == 'connect':
                ok = self.k.ConnectNamedPipe(handle, ctypes.byref(operation))
            else:
                function = self.k.ReadFile if kind == 'read' else self.k.WriteFile
                size = data if isinstance(data, int) else len(data)
                ok = function(handle, buffer, size, ctypes.byref(count), ctypes.byref(operation))
            error = ctypes.get_last_error()
            if not ok and kind == 'connect' and error == 535:
                return b''
            if not ok:
                if error != 997:
                    raise fail('helper_pipe_IO_failed')
                remaining = max(0, int((deadline - time.monotonic()) * 1000))
                if self.k.WaitForSingleObject(event, remaining) != 0:
                    self.k.CancelIoEx(handle, ctypes.byref(operation))
                    self.k.GetOverlappedResult(handle, ctypes.byref(operation), ctypes.byref(count), True)
                    raise fail('helper_timeout')
                if not self.k.GetOverlappedResult(handle, ctypes.byref(operation), ctypes.byref(count), False):
                    raise fail('helper_pipe_IO_failed')
            return buffer.raw[:count.value] if kind == 'read' else count.value
        finally:
            self.k.CloseHandle(event)

    def receive(self, handle, deadline):
        def exact(size):
            chunks = bytearray()
            while len(chunks) < size:
                block = self.io(handle, 'read', size - len(chunks), deadline)
                if not block:
                    raise fail('helper_pipe_closed')
                chunks.extend(block)
            return bytes(chunks)
        size = struct.unpack('<I', exact(4))[0]
        if not 0 < size <= LIMIT:
            raise fail('helper_response_exceeds_limit')
        try:
            return json.loads(exact(size))
        except (ValueError, UnicodeError):
            raise fail('helper_response_invalid_JSON') from None

    def send(self, handle, value, deadline):
        raw = json.dumps(value, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
        if not 0 < len(raw) <= LIMIT:
            raise fail('helper_response_exceeds_limit')
        raw = struct.pack('<I', len(raw)) + raw
        while raw:
            count = self.io(handle, 'write', raw, deadline)
            if not count:
                raise fail('helper_pipe_closed')
            raw = raw[count:]


def validate_choices(value):
    # An explicit allowlist also prevents future provider fields from turning
    # the pipe into a route for credentials/raw HTTP responses.
    fields = {'room_id', 'room_name', 'channel_id', 'channel_name', 'channel_type'}
    if not isinstance(value, dict) or set(value) != {'total', 'items', 'dependencies'} or not isinstance(value['items'], list):
        raise fail('helper_channel_response_invalid')
    if type(value['total']) is not int or value['total'] != len(value['items']) or value['total'] > 10000:
        raise fail('helper_channel_response_invalid')
    for item in value['items']:
        if (not isinstance(item, dict) or set(item) != fields or
                any(not isinstance(item[key], str) or len(item[key]) > 4096 for key in ('room_id', 'channel_id', 'channel_type')) or
                any(item[key] is not None and (not isinstance(item[key], str) or len(item[key]) > 4096) for key in ('room_name', 'channel_name'))):
            raise fail('helper_channel_response_invalid')
    if value['dependencies'] != [{'parent': 'room_id', 'children': ['channel_id', 'channel_type']}]:
        raise fail('helper_channel_response_invalid')
    return value


def profile_anchor(gui):
    from .dd_desktop import _network_profiles
    profiles = _network_profiles([gui['pid']])
    pid, profile = profiles[0]
    if not re.fullmatch(r'[0-9]{1,30}', profile.parent.name):
        raise fail('helper_current_account_profile_invalid')
    return {'network_pid': pid, 'profile': str(profile)}


def elevated_channels(gui):
    """At most one runas launch for this call; never reuse results globally."""
    api = Windows()
    anchor = profile_anchor(gui)
    parent = api.identity(api.k.GetCurrentProcess())
    if Path(parent['executable']) != Path(runtime_python()):
        raise fail('helper_parent_Python_mismatch')
    task = uuid.uuid4().hex
    name = PREFIX + task
    pipe, child = None, None
    try:
        pipe = api.pipe(name, parent['sid'])
        child = api.launch(name, task, parent)
        deadline = time.monotonic() + TIMEOUT  # Permission prompt time is excluded.
        api.io(pipe, 'connect', 0, deadline)
        if api.peer(pipe, True) != api.k.GetProcessId(child):
            raise fail('helper_client_PID_mismatch')
        identity = api.identity(child)
        if identity['sid'] != parent['sid'] or identity['executable'] != runtime_python():
            raise fail('helper_client_user_or_Python_mismatch')
        api.send(pipe, {'task': task, 'gui': {key: gui[key] for key in ('pid', 'started', 'dd_dir')}, 'profile': anchor}, deadline)
        result = api.receive(pipe, deadline)
        if not isinstance(result, dict) or result.get('task') != task:
            raise fail('helper_task_mismatch')
        if set(result) == {'task', 'reason'} and re.fullmatch(r'[A-Za-z_0-9]{1,100}', str(result['reason'])):
            raise fail(result['reason'])
        if set(result) != {'task', 'channels'}:
            raise fail('helper_response_fields_invalid')
        from .dd_broker import running_dd_processes
        after = running_dd_processes()
        if (len(after) != 1 or any(after[0].get(key) != gui[key] for key in ('pid', 'started', 'dd_dir')) or
                profile_anchor(gui) != anchor):
            raise fail('GUI_or_account_changed_during_UAC')
        return validate_choices(result['channels'])
    except FuploadError:
        raise
    except Exception:
        raise fail('helper_transport_failed') from None
    finally:
        if pipe is not None:
            api.k.DisconnectNamedPipe(pipe)
            api.k.CloseHandle(pipe)
        if child:
            api.k.CloseHandle(child)


def child_main(argv):
    # No optional/custom command, executable, URL, script or output path.
    if (len(argv) != 8 or argv[::2] != ['--pipe', '--task', '--parent-pid', '--parent-started'] or
            not re.fullmatch(r'[a-f0-9]{32}', argv[3]) or argv[1] != PREFIX + argv[3] or
            not re.fullmatch(r'[1-9][0-9]{0,9}', argv[5]) or not re.fullmatch(r'[1-9][0-9]{0,19}', argv[7])):
        return 2
    api, pipe, parent, watchdog = Windows(), None, None, None
    task, parent_pid, started = argv[3], int(argv[5]), int(argv[7])
    deadline = time.monotonic() + TIMEOUT
    try:
        parent = api.open_peer(parent_pid)
        theirs, mine = api.identity(parent), api.identity(api.k.GetCurrentProcess())
        if theirs['started'] != started or theirs['sid'] != mine['sid'] or theirs['executable'] != mine['executable']:
            raise fail('helper_parent_identity_mismatch')
        # Identification-only SQOS prevents a medium-integrity pipe server
        # from impersonating this elevated client's token.
        pipe = api.k.CreateFileW(argv[1], 0xC0000000, 0, None, 3, 0x40110000, None)
        if pipe == ctypes.c_void_p(-1).value:
            pipe = None
            raise fail('helper_pipe_open_failed')
        if api.peer(pipe, False) != parent_pid:
            raise fail('helper_server_PID_mismatch')
        request = api.receive(pipe, deadline)
        if (not isinstance(request, dict) or set(request) != {'task', 'gui', 'profile'} or request['task'] != task or
                not isinstance(request['gui'], dict) or set(request['gui']) != {'pid', 'started', 'dd_dir'} or
                not isinstance(request['profile'], dict) or set(request['profile']) != {'network_pid', 'profile'}):
            raise fail('helper_request_invalid')
        # Hard lifetime bound even if an OS/network call stalls. This exits only
        # this auxiliary process, never the caller or the DD GUI.
        import threading
        watchdog = threading.Timer(max(0, deadline - time.monotonic()), lambda: os._exit(124))
        watchdog.daemon = True
        watchdog.start()
        from .dd_channel import read_desktop_channels
        try:
            channels = read_desktop_channels(expected_dd_dir=request['gui']['dd_dir'], _allow_elevation=False,
                                             _expected_gui=request['gui'], _profile_anchor=request['profile'])
            response = {'task': task, 'channels': validate_choices(channels)}
        except FuploadError as error:
            reason = error.details.get('reason', 'helper_read_failed')
            if not re.fullmatch(r'[A-Za-z_0-9]{1,100}', str(reason)):
                reason = 'helper_read_failed'
            response = {'task': task, 'reason': reason}
        # Verify the parent is still the original process before delivery.
        if api.identity(parent) != theirs or api.peer(pipe, False) != parent_pid:
            raise fail('helper_parent_changed')
        api.send(pipe, response, deadline)
        return 0
    except Exception:
        # Never print exception text, argv, HTTP objects or a traceback.
        return 1
    finally:
        if watchdog is not None:
            watchdog.cancel()
        if pipe is not None:
            api.k.CloseHandle(pipe)
        if parent:
            api.k.CloseHandle(parent)


if __name__ == '__main__':
    raise SystemExit(child_main(sys.argv[1:]))
