"""Inspect only DD WebView2 cookie-file handles, with read-only mappings."""
import ctypes
import os
import base64
import hashlib
import json
import sqlite3
import struct
import time
from pathlib import Path
from .errors import FuploadError
from .trust import trusted_roaming_dir, verify_webview_executable
from ctypes import wintypes as w


class CookieSnapshotError(FuploadError):
    def __init__(self, message):
        super().__init__(message, kind='desktop_session_unavailable', stage='session')


def _snapshot_cookie_files(pid, allowed_root):
    k = ctypes.WinDLL('kernel32', use_last_error=True)
    nt = ctypes.WinDLL('ntdll')
    k.OpenProcess.argtypes = [w.DWORD, w.BOOL, w.DWORD]
    k.OpenProcess.restype = w.HANDLE
    k.CloseHandle.argtypes = [w.HANDLE]
    k.GetCurrentProcess.restype = w.HANDLE
    k.DuplicateHandle.argtypes = [w.HANDLE, w.HANDLE, w.HANDLE, ctypes.POINTER(w.HANDLE), w.DWORD, w.BOOL, w.DWORD]
    k.GetFileType.argtypes = [w.HANDLE]
    k.GetFinalPathNameByHandleW.argtypes = [w.HANDLE, w.LPWSTR, w.DWORD, w.DWORD]
    k.GetFileSizeEx.argtypes = [w.HANDLE, ctypes.POINTER(ctypes.c_longlong)]
    k.CreateFileMappingW.argtypes = [w.HANDLE, ctypes.c_void_p, w.DWORD, w.DWORD, w.DWORD, w.LPCWSTR]
    k.CreateFileMappingW.restype = w.HANDLE
    k.MapViewOfFile.argtypes = [w.HANDLE, w.DWORD, w.DWORD, w.DWORD, ctypes.c_size_t]
    k.MapViewOfFile.restype = ctypes.c_void_p
    k.UnmapViewOfFile.argtypes = [ctypes.c_void_p]
    nt.NtQueryInformationProcess.argtypes = [w.HANDLE, w.ULONG, ctypes.c_void_p, w.ULONG, ctypes.POINTER(w.ULONG)]
    nt.NtQueryInformationProcess.restype = ctypes.c_long

    class HandleEntry(ctypes.Structure):
        _fields_ = [('handle', ctypes.c_size_t), ('handle_count', ctypes.c_size_t),
                    ('pointer_count', ctypes.c_size_t), ('access', w.ULONG), ('type', w.ULONG),
                    ('attributes', w.ULONG), ('reserved', w.ULONG)]

    source = k.OpenProcess(0x440, False, pid)
    if not source:
        raise CookieSnapshotError('DD network process is not accessible')
    files = {}
    allowed_root = os.path.normcase(os.path.abspath(allowed_root)) + os.sep
    try:
        needed = w.ULONG()
        size = 65536
        for _ in range(3):
            buffer = ctypes.create_string_buffer(size)
            status = nt.NtQueryInformationProcess(source, 51, buffer, size, ctypes.byref(needed))
            if status == 0:
                break
            size = max(size * 2, needed.value)
            if size > 8 * 1024 * 1024:
                raise CookieSnapshotError('DD network handle table exceeds inspection limit')
        else:
            raise CookieSnapshotError('Cannot inspect DD network file handles')
        count = ctypes.c_size_t.from_buffer(buffer).value
        if count > (size - 16) // ctypes.sizeof(HandleEntry):
            raise CookieSnapshotError('DD network handle table is invalid')
        current = k.GetCurrentProcess()
        for index in range(count):
            entry = HandleEntry.from_buffer(buffer, 16 + index * ctypes.sizeof(HandleEntry))
            if not entry.access & 1:
                continue
            duplicate = w.HANDLE()
            if not k.DuplicateHandle(source, entry.handle, current, ctypes.byref(duplicate), 0, False, 2):
                continue
            try:
                if k.GetFileType(duplicate) != 1:
                    continue
                path_buffer = ctypes.create_unicode_buffer(32768)
                length = k.GetFinalPathNameByHandleW(duplicate, path_buffer, len(path_buffer), 0)
                if not 0 < length < len(path_buffer):
                    continue
                path = path_buffer.value
                if path.startswith('\\\\?\\'):
                    path = path[4:]
                normalized = os.path.normcase(os.path.abspath(path))
                if not normalized.startswith(allowed_root) or os.path.basename(normalized) not in ('cookies', 'cookies-wal'):
                    continue
                length = ctypes.c_longlong()
                if not k.GetFileSizeEx(duplicate, ctypes.byref(length)) or not 0 < length.value <= 16 * 1024 * 1024:
                    continue
                mapping = k.CreateFileMappingW(duplicate, None, 2, 0, 0, None)
                if not mapping:
                    continue
                try:
                    view = k.MapViewOfFile(mapping, 4, 0, 0, length.value)
                    if not view:
                        continue
                    try:
                        files[path] = ctypes.string_at(view, length.value)
                    finally:
                        k.UnmapViewOfFile(view)
                finally:
                    k.CloseHandle(mapping)
            finally:
                k.CloseHandle(duplicate)
    finally:
        k.CloseHandle(source)
    return files


def _unprotect(data):
    class Blob(ctypes.Structure):
        _fields_ = [('length', w.DWORD), ('data', ctypes.POINTER(ctypes.c_ubyte))]
    source_bytes = (ctypes.c_ubyte * len(data)).from_buffer_copy(data)
    source = Blob(len(data), source_bytes)
    result = Blob()
    crypto = ctypes.WinDLL('crypt32', use_last_error=True)
    crypto.CryptUnprotectData.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, w.DWORD, ctypes.POINTER(Blob)]
    kernel = ctypes.WinDLL('kernel32')
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    if not crypto.CryptUnprotectData(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(result)):
        raise CookieSnapshotError('DD browser key cannot be decrypted by the current Windows user')
    try:
        return ctypes.string_at(result.data, result.length)
    finally:
        kernel.LocalFree(result.data)


def _aes_gcm_decrypt(key, nonce, encrypted):
    """Use Windows CNG, without adding a Python crypto dependency."""
    if len(key) not in (16, 24, 32) or len(nonce) != 12 or len(encrypted) < 16:
        raise CookieSnapshotError('Invalid DD browser encryption parameters')
    class AuthInfo(ctypes.Structure):
        _fields_ = [('size', w.ULONG), ('version', w.ULONG), ('nonce', ctypes.c_void_p),
                    ('nonce_size', w.ULONG), ('aad', ctypes.c_void_p), ('aad_size', w.ULONG),
                    ('tag', ctypes.c_void_p), ('tag_size', w.ULONG), ('mac', ctypes.c_void_p),
                    ('mac_size', w.ULONG), ('aad_count', w.ULONG), ('data_count', ctypes.c_ulonglong),
                    ('flags', w.ULONG)]
    api = ctypes.WinDLL('bcrypt')
    api.BCryptOpenAlgorithmProvider.argtypes = [ctypes.POINTER(w.HANDLE), w.LPCWSTR, w.LPCWSTR, w.ULONG]
    api.BCryptSetProperty.argtypes = [w.HANDLE, w.LPCWSTR, ctypes.c_void_p, w.ULONG, w.ULONG]
    api.BCryptGetProperty.argtypes = [w.HANDLE, w.LPCWSTR, ctypes.c_void_p, w.ULONG, ctypes.POINTER(w.ULONG), w.ULONG]
    api.BCryptGenerateSymmetricKey.argtypes = [w.HANDLE, ctypes.POINTER(w.HANDLE), ctypes.c_void_p, w.ULONG, ctypes.c_void_p, w.ULONG, w.ULONG]
    api.BCryptDecrypt.argtypes = [w.HANDLE, ctypes.c_void_p, w.ULONG, ctypes.c_void_p, ctypes.c_void_p, w.ULONG, ctypes.c_void_p, w.ULONG, ctypes.POINTER(w.ULONG), w.ULONG]
    api.BCryptDestroyKey.argtypes = [w.HANDLE]
    api.BCryptCloseAlgorithmProvider.argtypes = [w.HANDLE, w.ULONG]
    algorithm, key_handle = w.HANDLE(), w.HANDLE()
    def checked(status):
        if status != 0:
            error = CookieSnapshotError('DD browser cookie authentication failed')
            error.details['windows_status'] = hex(status & 0xffffffff)
            raise error
    try:
        checked(api.BCryptOpenAlgorithmProvider(ctypes.byref(algorithm), 'AES', None, 0))
        mode = ctypes.create_unicode_buffer('ChainingModeGCM')
        checked(api.BCryptSetProperty(algorithm, 'ChainingMode', mode, ctypes.sizeof(mode), 0))
        object_size, returned = w.ULONG(), w.ULONG()
        checked(api.BCryptGetProperty(algorithm, 'ObjectLength', ctypes.byref(object_size), ctypes.sizeof(object_size), ctypes.byref(returned), 0))
        if not 0 < object_size.value <= 65536:
            raise CookieSnapshotError('Unsupported Windows AES key layout')
        key_object = ctypes.create_string_buffer(object_size.value)
        secret = ctypes.create_string_buffer(key)
        checked(api.BCryptGenerateSymmetricKey(algorithm, ctypes.byref(key_handle), key_object, len(key_object), secret, len(key), 0))
        nonce_buffer = ctypes.create_string_buffer(nonce)
        tag = ctypes.create_string_buffer(encrypted[-16:])
        ciphertext = ctypes.create_string_buffer(encrypted[:-16])
        plaintext = ctypes.create_string_buffer(max(1, len(encrypted) - 16))
        info = AuthInfo()
        info.size, info.version = ctypes.sizeof(info), 1
        info.nonce, info.nonce_size = ctypes.addressof(nonce_buffer), len(nonce)
        info.tag, info.tag_size = ctypes.addressof(tag), 16
        checked(api.BCryptDecrypt(key_handle, ciphertext, len(encrypted) - 16, ctypes.byref(info), None, 0, plaintext, len(plaintext), ctypes.byref(returned), 0))
        return plaintext.raw[:returned.value]
    finally:
        if key_handle:
            api.BCryptDestroyKey(key_handle)
        if algorithm:
            api.BCryptCloseAlgorithmProvider(algorithm, 0)


def _wal_checksum(data, previous, endian):
    if len(data) % 8:
        raise CookieSnapshotError('DD cookie WAL checksum input is invalid')
    first, second = previous
    for index in range(0, len(data), 8):
        a, b = struct.unpack_from(endian + 'II', data, index)
        first = (first + a + second) & 0xffffffff
        second = (second + b + first) & 0xffffffff
    return first, second


def _sqlite_image(database, wal=b''):
    """Apply only complete, checksum-verified committed WAL frames in memory."""
    if len(database) < 100 or database[:16] != b'SQLite format 3\x00':
        raise CookieSnapshotError('DD cookie database is invalid')
    page_size = struct.unpack_from('>H', database, 16)[0]
    page_size = 65536 if page_size == 1 else page_size
    if page_size < 512 or page_size > 65536 or page_size & (page_size - 1):
        raise CookieSnapshotError('DD cookie database page size is invalid')
    result = bytearray(database)
    if wal:
        if len(wal) < 32:
            raise CookieSnapshotError('DD cookie WAL is incomplete')
        magic, version, wal_page_size = struct.unpack_from('>III', wal)
        if magic not in (0x377f0682, 0x377f0683) or version != 3007000 or wal_page_size != page_size:
            raise CookieSnapshotError('DD cookie WAL format is unsupported')
        endian = '<' if magic == 0x377f0682 else '>'
        checksum = _wal_checksum(wal[:24], (0, 0), endian)
        if checksum != struct.unpack_from('>II', wal, 24):
            raise CookieSnapshotError('DD cookie WAL header checksum failed')
        frames, committed, final_size = [], 0, 0
        for offset in range(32, len(wal) - page_size - 23, page_size + 24):
            page, size = struct.unpack_from('>II', wal, offset)
            if wal[offset + 8:offset + 16] != wal[16:24]:
                break
            content = wal[offset + 24:offset + 24 + page_size]
            candidate = _wal_checksum(wal[offset:offset + 8] + content, checksum, endian)
            if candidate != struct.unpack_from('>II', wal, offset + 16):
                break
            if not 1 <= page <= 32768 or size > 32768:
                raise CookieSnapshotError('DD cookie WAL exceeds snapshot limits')
            checksum = candidate
            frames.append((page, content))
            if size:
                committed, final_size = len(frames), size
        if committed:
            if final_size * page_size > 16 * 1024 * 1024:
                raise CookieSnapshotError('DD cookie image exceeds snapshot limits')
            for page, content in frames[:committed]:
                start = (page - 1) * page_size
                if start + page_size > len(result):
                    result.extend(b'\x00' * (start + page_size - len(result)))
                result[start:start + page_size] = content
            result = result[:final_size * page_size]
    result[18:20] = b'\x01\x01'
    return bytes(result)


def _cookie_from_snapshot(profile, files):
    database = profile / 'Default' / 'Network' / 'Cookies'
    by_name = {os.path.normcase(os.path.abspath(name)): data for name, data in files.items()}
    key_name = os.path.normcase(os.path.abspath(database))
    if key_name not in by_name:
        raise CookieSnapshotError('The active DD browser has no readable session database')
    image = _sqlite_image(by_name[key_name], by_name.get(key_name + '-wal', b''))
    state = json.loads((profile / 'Local State').read_text(encoding='utf-8'))
    encrypted_key = base64.b64decode(state.get('os_crypt', {}).get('encrypted_key', ''), validate=True)
    if not encrypted_key.startswith(b'DPAPI'):
        raise CookieSnapshotError('DD browser encryption scheme is unsupported')
    key = _unprotect(encrypted_key[5:])
    connection = sqlite3.connect(':memory:')
    try:
        if not hasattr(connection, 'deserialize'):
            raise CookieSnapshotError('DD desktop session reuse requires Python 3.11 or later')
        connection.deserialize(image)
        version_row = connection.execute("SELECT value FROM meta WHERE key='version'").fetchone()
        if not version_row:
            raise CookieSnapshotError('DD cookie database has no version')
        version = int(version_row[0])
        rows = connection.execute("SELECT host_key,name,value,encrypted_value,expires_utc FROM cookies WHERE host_key='.163.com' AND name='NTES_YD_SESS'").fetchall()
        candidates = []
        now = int((time.time() + 11644473600) * 1000000)
        for host, name, plaintext, encrypted, expiry in rows:
            if expiry and expiry <= now:
                continue
            if encrypted.startswith(b'v10'):
                value = _aes_gcm_decrypt(key, encrypted[3:15], encrypted[15:])
                if version >= 24:
                    if value[:32] != hashlib.sha256(host.encode('utf-8')).digest():
                        raise CookieSnapshotError('DD cookie domain binding failed')
                    value = value[32:]
                plaintext = value.decode('utf-8')
            elif encrypted.startswith(b'v20'):
                raise CookieSnapshotError('DD browser uses an unsupported application-bound cookie')
            elif encrypted:
                plaintext = _unprotect(encrypted).decode('utf-8')
            if plaintext and len(plaintext) <= 16384 and not any(char in plaintext for char in '\r\n;'):
                candidates.append((name, plaintext))
        if len(candidates) != 1:
            raise CookieSnapshotError('The active DD browser has no unique live session cookie; sign in with DD first')
        return candidates[0]
    finally:
        connection.close()


def _process_rows():
    class Entry(ctypes.Structure):
        _fields_ = [('size', w.DWORD), ('usage', w.DWORD), ('pid', w.DWORD),
                    ('heap', ctypes.c_size_t), ('module', w.DWORD), ('threads', w.DWORD),
                    ('parent', w.DWORD), ('priority', w.LONG), ('flags', w.DWORD),
                    ('name', w.WCHAR * 260)]
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateToolhelp32Snapshot.argtypes = [w.DWORD, w.DWORD]
    kernel.CreateToolhelp32Snapshot.restype = w.HANDLE
    kernel.Process32FirstW.argtypes = [w.HANDLE, ctypes.POINTER(Entry)]
    kernel.Process32NextW.argtypes = [w.HANDLE, ctypes.POINTER(Entry)]
    kernel.CloseHandle.argtypes = [w.HANDLE]
    snapshot = kernel.CreateToolhelp32Snapshot(2, 0)
    if snapshot == ctypes.c_void_p(-1).value:
        raise CookieSnapshotError('Cannot discover the DD browser process')
    rows = []
    try:
        entry = Entry()
        entry.size = ctypes.sizeof(entry)
        more = kernel.Process32FirstW(snapshot, ctypes.byref(entry))
        while more:
            rows.append((int(entry.pid), int(entry.parent), entry.name))
            more = kernel.Process32NextW(snapshot, ctypes.byref(entry))
    finally:
        kernel.CloseHandle(snapshot)
    return rows


def _process_metadata(pid):
    class UnicodeString(ctypes.Structure):
        _fields_ = [('length', w.USHORT), ('capacity', w.USHORT), ('buffer', ctypes.c_void_p)]
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenProcess.argtypes = [w.DWORD, w.BOOL, w.DWORD]
    kernel.OpenProcess.restype = w.HANDLE
    kernel.QueryFullProcessImageNameW.argtypes = [w.HANDLE, w.DWORD, w.LPWSTR, ctypes.POINTER(w.DWORD)]
    kernel.CloseHandle.argtypes = [w.HANDLE]
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    native = ctypes.WinDLL('ntdll')
    native.NtQueryInformationProcess.argtypes = [w.HANDLE, w.ULONG, ctypes.c_void_p, w.ULONG, ctypes.POINTER(w.ULONG)]
    native.NtQueryInformationProcess.restype = ctypes.c_long
    shell = ctypes.WinDLL('shell32')
    shell.CommandLineToArgvW.argtypes = [w.LPCWSTR, ctypes.POINTER(ctypes.c_int)]
    shell.CommandLineToArgvW.restype = ctypes.POINTER(w.LPWSTR)
    handle = kernel.OpenProcess(0x1000, False, pid)
    if not handle:
        raise CookieSnapshotError('Cannot inspect the DD browser process')
    try:
        size = w.DWORD(32768)
        path = ctypes.create_unicode_buffer(size.value)
        if not kernel.QueryFullProcessImageNameW(handle, 0, path, ctypes.byref(size)):
            raise CookieSnapshotError('Cannot verify the DD browser executable')
        needed = w.ULONG()
        native.NtQueryInformationProcess(handle, 60, None, 0, ctypes.byref(needed))
        if not ctypes.sizeof(UnicodeString) <= needed.value <= 131072:
            raise CookieSnapshotError('DD browser command line is unavailable')
        buffer = ctypes.create_string_buffer(needed.value)
        if native.NtQueryInformationProcess(handle, 60, buffer, len(buffer), ctypes.byref(needed)) != 0:
            raise CookieSnapshotError('DD browser command line could not be inspected')
        text = UnicodeString.from_buffer(buffer)
        start = ctypes.addressof(buffer)
        if text.length % 2 or not start <= text.buffer <= start + len(buffer) - text.length:
            raise CookieSnapshotError('DD browser command line layout is invalid')
        command_line = ctypes.wstring_at(text.buffer, text.length // 2)
        count = ctypes.c_int()
        argv = shell.CommandLineToArgvW(command_line, ctypes.byref(count))
        if not argv:
            raise CookieSnapshotError('DD browser arguments could not be parsed')
        try:
            return Path(path.value), [argv[index] for index in range(count.value)]
        finally:
            kernel.LocalFree(argv)
    finally:
        kernel.CloseHandle(handle)


def _network_profiles(gui_pids):
    rows = _process_rows()
    descendants = set(gui_pids)
    for _ in range(8):
        updated = descendants | {pid for pid, parent, _name in rows if parent in descendants}
        if updated == descendants:
            break
        descendants = updated
    root = trusted_roaming_dir('CCVoiceHub', 'web_cache')
    profiles = []
    for pid, _parent, name in rows:
        if pid not in descendants or name.casefold() != 'msedgewebview2.exe':
            continue
        try:
            executable, args = _process_metadata(pid)
        except CookieSnapshotError:
            continue
        if '--utility-sub-type=network.mojom.NetworkService' not in args:
            continue
        directories = [arg.split('=', 1)[1] for arg in args if arg.startswith('--user-data-dir=')]
        if len(directories) != 1:
            raise CookieSnapshotError('DD network process has no unique browser profile')
        profile = Path(directories[0]).resolve()
        if profile.name != 'EBWebView' or root not in profile.parents:
            raise CookieSnapshotError('DD browser profile is outside its product state directory')
        relative = profile.relative_to(root)
        profile = trusted_roaming_dir('CCVoiceHub', 'web_cache', *relative.parts)
        verify_webview_executable(executable)
        profiles.append((pid, profile))
    if len(profiles) != 1:
        raise CookieSnapshotError('DD does not expose one unique active browser session; open DD and sign in first')
    return profiles


def borrow_desktop_cookie(gui_processes):
    """Use only the verified DD GUI's own, currently running WebView2 profile."""
    if os.name != 'nt':
        raise CookieSnapshotError('DD desktop session reuse is available only on Windows')
    if ctypes.sizeof(ctypes.c_void_p) != 8:
        raise CookieSnapshotError('DD desktop session reuse requires 64-bit Python')
    if len(gui_processes) != 1 or not gui_processes[0].get('signature'):
        raise CookieSnapshotError('Expected one signature-verified DD desktop process')
    try:
        pid, profile = _network_profiles([int(gui_processes[0]['pid'])])[0]
        files = _snapshot_cookie_files(pid, str(profile))
        return _cookie_from_snapshot(profile, files)
    except FuploadError:
        raise
    except (OSError, ValueError, KeyError, TypeError, sqlite3.Error) as exc:
        raise CookieSnapshotError('DD desktop session could not be reused (%s); no additional login was attempted' % type(exc).__name__) from exc
