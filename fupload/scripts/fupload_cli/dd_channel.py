"""Read DD channel choices from an existing GUI session without a new login.

Only this optional channel operation opens a PROCESS_VM_READ handle. Session
credentials stay inside the calling Python process and are never returned.
Supported runtime: the explicitly hashed official DD 100130 / CPython 3.7.17 x64.
"""
from __future__ import annotations

import base64
import ctypes
from ctypes import wintypes as w
import hashlib
import json
import os
from pathlib import Path
import re
import struct
import time
import urllib.error
import urllib.request
import urllib.parse

from .errors import FuploadError

class SessionReadError(RuntimeError):
    pass


class Memory:
    def __init__(self, pid, directory):
        self.kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        self.kernel.OpenProcess.argtypes = [w.DWORD, w.BOOL, w.DWORD]
        self.kernel.OpenProcess.restype = w.HANDLE
        self.kernel.CloseHandle.argtypes = [w.HANDLE]
        self.kernel.ReadProcessMemory.argtypes = [w.HANDLE, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
        self.kernel.ReadProcessMemory.restype = w.BOOL
        self.handle = self.kernel.OpenProcess(0x1010, False, pid)
        if not self.handle:
            reason = ('process_read_denied_same_windows_integrity_required' if ctypes.get_last_error() == 5
                      else 'GUI_process_open_failed')
            raise SessionReadError(reason)
        self.types = {}
        try:
            self.base = self.module_base(pid, directory)
        except Exception:
            self.close()
            raise

    def close(self):
        if self.handle:
            self.kernel.CloseHandle(self.handle)
            self.handle = None

    def read(self, address, size):
        if not 0x10000 <= address < 0x0000800000000000 or not 0 < size <= 1048576:
            raise SessionReadError('DD runtime layout is invalid')
        buffer = ctypes.create_string_buffer(size)
        count = ctypes.c_size_t()
        if not self.kernel.ReadProcessMemory(self.handle, address, buffer, size, ctypes.byref(count)) or count.value != size:
            raise SessionReadError('DD session changed while it was being read')
        return buffer.raw

    def ptr(self, address):
        return struct.unpack('<Q', self.read(address, 8))[0]

    def integer(self, address):
        return struct.unpack('<q', self.read(address, 8))[0]

    def module_base(self, pid, directory):
        class Module(ctypes.Structure):
            _fields_ = [('size', w.DWORD), ('id', w.DWORD), ('pid', w.DWORD),
                        ('global_count', w.DWORD), ('process_count', w.DWORD),
                        ('base', ctypes.c_void_p), ('base_size', w.DWORD), ('module', w.HMODULE),
                        ('name', w.WCHAR * 256), ('path', w.WCHAR * 260)]
        k = self.kernel
        k.CreateToolhelp32Snapshot.argtypes = [w.DWORD, w.DWORD]
        k.CreateToolhelp32Snapshot.restype = w.HANDLE
        k.Module32FirstW.argtypes = [w.HANDLE, ctypes.POINTER(Module)]
        k.Module32NextW.argtypes = [w.HANDLE, ctypes.POINTER(Module)]
        snapshot = k.CreateToolhelp32Snapshot(0x18, pid)
        if snapshot == ctypes.c_void_p(-1).value:
            raise SessionReadError('Cannot inspect the DD runtime with current Windows permissions')
        expected = os.path.normcase(os.path.abspath(os.path.join(directory, 'python37.dll')))
        try:
            entry = Module()
            entry.size = ctypes.sizeof(entry)
            more = k.Module32FirstW(snapshot, ctypes.byref(entry))
            while more:
                if os.path.normcase(os.path.abspath(entry.path)) == expected:
                    return entry.base
                more = k.Module32NextW(snapshot, ctypes.byref(entry))
        finally:
            k.CloseHandle(snapshot)
        raise SessionReadError('Running DD does not use the expected Python runtime')

    def process_identity(self):
        k = self.kernel
        k.QueryFullProcessImageNameW.argtypes = [w.HANDLE, w.DWORD, w.LPWSTR, ctypes.POINTER(w.DWORD)]
        k.GetProcessTimes.argtypes = [w.HANDLE, ctypes.POINTER(w.FILETIME), ctypes.POINTER(w.FILETIME), ctypes.POINTER(w.FILETIME), ctypes.POINTER(w.FILETIME)]
        size, buffer = w.DWORD(32768), ctypes.create_unicode_buffer(32768)
        created, exited, system, user = w.FILETIME(), w.FILETIME(), w.FILETIME(), w.FILETIME()
        if (not k.QueryFullProcessImageNameW(self.handle, 0, buffer, ctypes.byref(size)) or
                not k.GetProcessTimes(self.handle, ctypes.byref(created), ctypes.byref(exited), ctypes.byref(system), ctypes.byref(user))):
            raise SessionReadError('opened_GUI_process_identity_unreadable')
        return {'executable': buffer.value, 'started': (int(created.dwHighDateTime) << 32) | int(created.dwLowDateTime)}

    def type_name(self, obj):
        typ = self.ptr(obj + 8)
        if typ not in self.types:
            nameptr = self.ptr(typ + 24)
            self.types[typ] = self.read(nameptr, 128).split(b'\0', 1)[0].decode('utf-8', 'replace')
        return self.types[typ]

    def text(self, obj):
        if self.type_name(obj) != 'str':
            raise SessionReadError('Unexpected DD text object')
        header = self.read(obj, 48)
        length = struct.unpack_from('<q', header, 16)[0]
        state = struct.unpack_from('<I', header, 32)[0]
        kind, compact, ascii_only = (state >> 2) & 7, (state >> 5) & 1, (state >> 6) & 1
        if not 0 <= length <= 16384 or kind not in (1, 2, 4):
            raise SessionReadError('Unexpected DD text layout')
        if not length:
            return ''
        data = obj + (48 if ascii_only else 72) if compact else self.ptr(obj + 72)
        return self.read(data, length * kind).decode({1: 'latin-1', 2: 'utf-16-le', 4: 'utf-32-le'}[kind])

    def dict_get(self, obj, wanted):
        if self.type_name(obj) != 'dict':
            raise SessionReadError('Unexpected DD attribute dictionary')
        keys, values = self.ptr(obj + 32), self.ptr(obj + 40)
        size, count = self.integer(keys + 8), self.integer(keys + 32)
        if not 0 < size <= 1048576 or size & (size - 1) or not 0 <= count <= 16384:
            raise SessionReadError('Unexpected DD dictionary layout')
        index_size = 1 if size <= 0xff else 2 if size <= 0xffff else 4
        entries = keys + 40 + size * index_size
        for i in range(count):
            key = self.ptr(entries + i * 24 + 8)
            if key and self.text(key) == wanted:
                return self.ptr(values + i * 8) if values else self.ptr(entries + i * 24 + 16)
        return None

    def attribute(self, obj, wanted):
        typ = self.ptr(obj + 8)
        offset = self.integer(typ + 288)
        if offset < 0:
            basic, item = self.integer(typ + 32), self.integer(typ + 40)
            count = abs(self.integer(obj + 16)) if item else 0
            offset += (basic + count * item + 7) & ~7
        if not 0 < offset < 65536:
            raise SessionReadError('Unexpected DD instance layout')
        dictionary = self.ptr(obj + offset)
        return self.dict_get(dictionary, wanted) if dictionary else None

    def number(self, obj):
        name = self.type_name(obj)
        if name == 'State':
            value = self.attribute(obj, '_value_')
            if not value or self.type_name(value) != 'int':
                raise SessionReadError('Unexpected DD enum state layout')
            obj = value
        elif name not in ('int', 'bool'):
            raise SessionReadError('Unexpected DD state type')
        size = self.integer(obj + 16)
        if not -2 <= size <= 2:
            raise SessionReadError('Unexpected DD state value')
        result = 0
        for i in range(abs(size)):
            result |= struct.unpack('<I', self.read(obj + 24 + i * 4, 4))[0] << (30 * i)
        return -result if size < 0 else result

    def class_module(self, obj):
        dictionary = self.ptr(self.ptr(obj + 8) + 264)
        name = self.dict_get(dictionary, '__module__')
        return self.text(name) if name else ''

    def find_session_objects(self, runtime_rva):
        runtime = self.base + runtime_rva
        if struct.unpack('<i', self.read(runtime, 4))[0] != 1:
            raise SessionReadError('DD Python runtime is not initialized')
        generations = runtime + 336
        if self.ptr(runtime + 432) != generations:
            raise SessionReadError('DD Python GC layout does not match CPython 3.7 x64')
        found = {'LoginController': [], 'JwtHelper': []}
        expected_modules = {'LoginController': 'components.login.login_controller', 'JwtHelper': 'util.cgi.jwt_helper'}
        seen = set()
        deadline = time.monotonic() + 10
        for generation in range(3):
            head = generations + generation * 32
            node = self.ptr(head)
            while node and node != head:
                if node in seen or len(seen) >= 300000 or time.monotonic() > deadline:
                    raise SessionReadError('DD session inspection did not finish consistently')
                seen.add(node)
                next_node = self.ptr(node)
                obj = node + 24
                name = self.type_name(obj)
                if name in found and self.class_module(obj) == expected_modules[name]:
                    found[name].append(obj)
                node = next_node
        if any(len(values) != 1 for values in found.values()):
            raise SessionReadError('expected_one_live_LoginController_and_JwtHelper')
        return {name: values[0] for name, values in found.items()}

    def is_logged_in(self, center):
        if self.type_name(center) != 'MessageCenter' or self.class_module(center) != 'components.net_server.messagecenter':
            raise SessionReadError('message_center_identity_mismatch')
        state = self.attribute(center, 'state')
        if not state or self.class_module(state) != 'components.net_server.messagecenter':
            raise SessionReadError('message_center_enum_identity_mismatch')
        # Bind the actual Enum name and value. The old reader assumed every
        # tp_name was literally State and interpreted other enum types as ints.
        name = self.attribute(state, '_name_')
        value = self.attribute(state, '_value_')
        if not name or not value:
            raise SessionReadError('message_center_enum_layout_mismatch')
        return self.text(name) == 'LoggedIn' and self.number(value) == 3

    def snapshot(self, runtime_rva):
        objects = self.find_session_objects(runtime_rva)
        controller, helper = objects['LoginController'], objects['JwtHelper']
        center = self.attribute(controller, '_messageCenter')
        helper_center = self.attribute(helper, '_msgCenter')
        if not center or helper_center != center:
            raise SessionReadError('GUI_auth_objects_do_not_share_MessageCenter')
        if not self.is_logged_in(center):
            raise SessionReadError('GUI_MessageCenter_not_logged_in')
        session_anchor = self.attribute(controller, '_session')
        if not session_anchor or self.type_name(session_anchor) != 'str' or not self.text(session_anchor):
            raise SessionReadError('GUI_LoginController_session_anchor_unavailable')
        session_value = self.text(session_anchor)
        token_object = self.attribute(helper, '_jwt')
        token = self.text(token_object) if token_object and self.type_name(token_object) != 'NoneType' else ''
        if len(token) > 16384 or any(char in token for char in '\r\n'):
            raise SessionReadError('GUI_cached_jwt_layout_invalid')
        # Official DataCenter.getMyUserInfo returns self._myUserInfo.
        data_center = self.attribute(helper, '_dataCenter')
        user = self.attribute(data_center, '_myUserInfo') if data_center else None
        login_object = self.attribute(helper, '_loginToken')
        delta_object = self.attribute(helper, '_server_time_delta')
        if not user or not login_object or not delta_object:
            raise SessionReadError('GUI_refresh_identity_unavailable')
        login_token = self.text(login_object)
        identity = {key: self.scalar(self.attribute(user, key)) for key in ('uid', 'eid', 'ccid')}
        if (not login_token or any(char in login_token for char in '\r\n') or
                any(not re.fullmatch(r'[0-9]{1,30}', str(value)) for value in identity.values())):
            raise SessionReadError('GUI_refresh_identity_invalid')
        delta = self.scalar(delta_object)
        if type(delta) not in (int, float) or not -86400 <= delta <= 86400:
            raise SessionReadError('GUI_server_clock_delta_invalid')
        # Check the same anchor and token object again; do not use a value read
        # across logout/reconnect or a refresh that replaced its Python string.
        if (self.attribute(controller, '_messageCenter') != center or
                self.attribute(helper, '_msgCenter') != center or
                self.attribute(helper, '_jwt') != token_object or
                self.attribute(controller, '_session') != session_anchor or not self.is_logged_in(center)):
            raise SessionReadError('GUI_session_changed_during_read')
        result = {'token': token, 'token_object': token_object, 'session_anchor': session_anchor,
                  'session_value': session_value, 'controller': controller, 'helper': helper, 'center': center,
                  'data_center': data_center, 'user': user, 'login_object': login_object,
                  'login_token': login_token, 'delta_object': delta_object, 'delta': delta, **identity}
        if not self.still_online(result):
            raise SessionReadError('GUI_session_changed_during_read')
        return result

    def scalar(self, obj):
        if not obj:
            raise SessionReadError('GUI_identity_field_unavailable')
        kind = self.type_name(obj)
        if kind == 'str':
            return self.text(obj)
        if kind == 'float':
            return struct.unpack('<d', self.read(obj + 16, 8))[0]
        if kind == 'int':
            # Native account endpoint IDs can use all uint64 bits (3 Python
            # base-2**30 digits). Keep the narrower Enum reader unchanged.
            size = self.integer(obj + 16)
            if not -4 <= size <= 4:
                raise SessionReadError('GUI_identity_integer_exceeds_limit')
            result = 0
            for index in range(abs(size)):
                digit = struct.unpack('<I', self.read(obj + 24 + index * 4, 4))[0]
                if digit >= 1 << 30:
                    raise SessionReadError('GUI_identity_integer_layout_invalid')
                result |= digit << (30 * index)
            return -result if size < 0 else result
        raise SessionReadError('GUI_identity_field_type_invalid')

    def still_online(self, snapshot):
        return (self.attribute(snapshot['controller'], '_messageCenter') == snapshot['center'] and
                self.attribute(snapshot['helper'], '_msgCenter') == snapshot['center'] and
                self.attribute(snapshot['helper'], '_jwt') == snapshot['token_object'] and
                self.attribute(snapshot['controller'], '_session') == snapshot['session_anchor'] and
                (self.text(snapshot['token_object']) if snapshot['token_object'] and self.type_name(snapshot['token_object']) != 'NoneType' else '') == snapshot['token'] and
                self.text(snapshot['session_anchor']) == snapshot['session_value'] and
                self.is_logged_in(snapshot['center']) and self.refresh_unchanged(snapshot))

    def refresh_unchanged(self, snapshot):
        return (self.attribute(snapshot['helper'], '_dataCenter') == snapshot['data_center'] and
                self.attribute(snapshot['data_center'], '_myUserInfo') == snapshot['user'] and
                self.attribute(snapshot['helper'], '_loginToken') == snapshot['login_object'] and
                self.text(snapshot['login_object']) == snapshot['login_token'] and
                self.attribute(snapshot['helper'], '_server_time_delta') == snapshot['delta_object'] and
                self.scalar(snapshot['delta_object']) == snapshot['delta'] and
                all(self.scalar(self.attribute(snapshot['user'], key)) == snapshot[key] for key in ('uid', 'eid', 'ccid')))


EXPECTED = {
    'python37.dll': '268af469cc5b487d32848142d17f3640adc276bd85935e602cc9a295f8d7703d',
    'netease_dd.exe': '4d6609e58d639f8ea6c513d3806904ae60896251ffbd4d9bc0e2361779dd947f',
    'ccvoicehub.res': '953b1bd893adb53c8b003d490ee219fe4a0e075efbed960fc8bc1bcff2a26892',
}
RUNTIME_RVA = 3639528
VERSION = (3, 7, 17150, 1013)  # PE fixed-file version; display/runtime version is 3.7.17
CHANNEL_URL = 'https://api.cc.163.com/v1/mixteammsgproxy/channelList?source=pluginPublish'


def export_rva(data: bytes, wanted: bytes) -> int:
    if data[:2] != b'MZ':
        raise SessionReadError('DLL_DOS_layout_mismatch')
    pe = struct.unpack_from('<I', data, 60)[0]
    if data[pe:pe + 4] != b'PE\0\0' or struct.unpack_from('<H', data, pe + 4)[0] != 0x8664:
        raise SessionReadError('DLL_must_match_AMD64_PE')
    sections, optional_size = struct.unpack_from('<H', data, pe + 6)[0], struct.unpack_from('<H', data, pe + 20)[0]
    optional = pe + 24
    if struct.unpack_from('<H', data, optional)[0] != 0x20b:
        raise SessionReadError('DLL_PE_optional_header_mismatch')
    table = optional + optional_size

    def offset(rva):
        for index in range(sections):
            section = table + index * 40
            size, address, raw_size, raw = struct.unpack_from('<IIII', data, section + 8)
            if address <= rva < address + max(size, raw_size):
                return raw + rva - address
        raise SessionReadError('DLL_export_RVA_outside_sections')

    exports = offset(struct.unpack_from('<I', data, optional + 112)[0])
    names_count = struct.unpack_from('<I', data, exports + 24)[0]
    functions, names, ordinals = (offset(struct.unpack_from('<I', data, exports + field)[0]) for field in (28, 32, 36))
    if names_count > 65536:
        raise SessionReadError('DLL_export_count_invalid')
    for index in range(names_count):
        name = offset(struct.unpack_from('<I', data, names + index * 4)[0])
        if data[name:name + len(wanted) + 1] == wanted + b'\0':
            ordinal = struct.unpack_from('<H', data, ordinals + index * 2)[0]
            return struct.unpack_from('<I', data, functions + ordinal * 4)[0]
    raise SessionReadError('DLL_required_export_missing')


def file_version(path):
    api = ctypes.WinDLL('version', use_last_error=True)
    api.GetFileVersionInfoSizeW.argtypes = [w.LPCWSTR, ctypes.POINTER(w.DWORD)]
    api.GetFileVersionInfoW.argtypes = [w.LPCWSTR, w.DWORD, w.DWORD, ctypes.c_void_p]
    api.VerQueryValueW.argtypes = [ctypes.c_void_p, w.LPCWSTR, ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(w.UINT)]
    ignored = w.DWORD()
    size = api.GetFileVersionInfoSizeW(str(path), ctypes.byref(ignored))
    if not 0 < size < 1048576:
        raise SessionReadError('DLL_version_resource_unavailable')
    buffer = ctypes.create_string_buffer(size)
    pointer, length = ctypes.c_void_p(), w.UINT()
    if not api.GetFileVersionInfoW(str(path), 0, size, buffer) or not api.VerQueryValueW(buffer, '\\', ctypes.byref(pointer), ctypes.byref(length)) or length.value < 24:
        raise SessionReadError('DLL_version_resource_invalid')
    fields = struct.unpack('<6I', ctypes.string_at(pointer.value, 24))
    if fields[0] != 0xFEEF04BD:
        raise SessionReadError('DLL_version_signature_invalid')
    return (fields[2] >> 16, fields[2] & 65535, fields[3] >> 16, fields[3] & 65535)


def verify_binding(install):
    contents = {}
    for name, expected in EXPECTED.items():
        path = install / name
        contents[name] = path.read_bytes()
        if hashlib.sha256(contents[name]).hexdigest() != expected:
            raise SessionReadError('DD_100130_file_hash_mismatch_' + name)
    if file_version(install / 'python37.dll') != VERSION:
        raise SessionReadError('DD_Python_3_7_17_version_mismatch')
    if export_rva(contents['python37.dll'], b'_PyRuntime') != RUNTIME_RVA:
        raise SessionReadError('DD_PyRuntime_export_RVA_mismatch')


def process_sid(kernel, handle):
    adv = ctypes.WinDLL('advapi32', use_last_error=True)
    adv.OpenProcessToken.argtypes = [w.HANDLE, w.DWORD, ctypes.POINTER(w.HANDLE)]
    adv.GetTokenInformation.argtypes = [w.HANDLE, ctypes.c_int, ctypes.c_void_p, w.DWORD, ctypes.POINTER(w.DWORD)]
    adv.ConvertSidToStringSidW.argtypes = [ctypes.c_void_p, ctypes.POINTER(w.LPWSTR)]
    token = w.HANDLE()
    if not adv.OpenProcessToken(handle, 8, ctypes.byref(token)):
        raise SessionReadError('GUI_process_owner_unreadable')
    try:
        needed = w.DWORD()
        adv.GetTokenInformation(token, 1, None, 0, ctypes.byref(needed))
        if not 0 < needed.value <= 65536:
            raise SessionReadError('GUI_owner_token_layout_invalid')
        data = ctypes.create_string_buffer(needed.value)
        if not adv.GetTokenInformation(token, 1, data, len(data), ctypes.byref(needed)):
            raise SessionReadError('GUI_owner_token_unreadable')
        sid = ctypes.c_void_p.from_buffer(data).value
        text = w.LPWSTR()
        if not adv.ConvertSidToStringSidW(sid, ctypes.byref(text)):
            raise SessionReadError('GUI_owner_SID_invalid')
        try:
            return text.value
        finally:
            kernel.LocalFree(ctypes.cast(text, ctypes.c_void_p))
    finally:
        kernel.CloseHandle(token)


def verify_same_user(memory):
    kernel = memory.kernel
    kernel.GetCurrentProcess.restype = w.HANDLE
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    if process_sid(kernel, memory.handle) != process_sid(kernel, kernel.GetCurrentProcess()):
        raise SessionReadError('GUI_must_belong_to_same_Windows_user')


def validate_cached_jwt(token):
    if not re.fullmatch(r'[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+', token):
        raise SessionReadError('GUI_cached_jwt_is_not_compact_JWT')
    try:
        header, claims = [json.loads(base64.urlsafe_b64decode(part + '=' * (-len(part) % 4))) for part in token.split('.')[:2]]
        if not isinstance(header, dict) or header.get('alg') in (None, 'none') or not isinstance(claims, dict):
            raise ValueError()
        expiry = claims.get('exp')
        if expiry is not None and (type(expiry) not in (int, float) or expiry <= time.time() + 5):
            raise SessionReadError('GUI_cached_jwt_is_expired_no_refresh_was_triggered')
    except SessionReadError:
        raise
    except Exception:
        raise SessionReadError('GUI_cached_jwt_payload_invalid') from None
    return claims


def validate_identity_jwt(token, snapshot):
    claims = validate_cached_jwt(token)
    user = claims.get('user')
    if isinstance(user, str):
        try:
            user = json.loads(user)
        except Exception:
            user = None
    if (claims.get('appid') != 'webcc' or not isinstance(user, dict) or
            any(str(user.get(key)) != str(snapshot[key]) for key in ('uid', 'eid')) or
            type(claims.get('exp')) not in (int, float) or claims['exp'] > time.time() + 1200):
        raise SessionReadError('GUI_JWT_current_identity_mismatch')


def current_channel_token(snapshot):
    if snapshot['token']:
        try:
            validate_identity_jwt(snapshot['token'], snapshot)
            return snapshot['token']
        except SessionReadError as error:
            if str(error) != 'GUI_cached_jwt_is_expired_no_refresh_was_triggered':
                raise
    # JwtHelper._requestJwt / getServerTime, official DD 100130. This GET
    # neither changes the native login nor writes the new JWT into the GUI.
    timestamp = int(time.time() + snapshot['delta'])
    signature = hashlib.md5(('webcc_%s_%s' % (timestamp, snapshot['login_token'])).encode('utf-8')).hexdigest()
    query = urllib.parse.urlencode({'appid': 'webcc', 'uid': snapshot['uid'], 'eid': snapshot['eid'], 'timestamp': timestamp})
    request = urllib.request.Request('https://api.cc.163.com/v1/jwt?' + query, method='GET',
                                     headers={'Authentication': signature, 'Accept': 'application/json'})
    try:
        with urllib.request.build_opener(NoRedirect).open(request, timeout=15) as response:
            raw = response.read(1048577)
        if len(raw) > 1048576:
            raise SessionReadError('JWT_refresh_response_exceeds_limit')
        payload = json.loads(raw)
        token = payload.get('data', {}).get('jwt') if isinstance(payload, dict) and payload.get('code') in ('OK', 0, 200) else None
        if not isinstance(token, str) or len(token) > 16384:
            raise SessionReadError('GUI_login_token_refresh_rejected')
        validate_identity_jwt(token, snapshot)
        return token
    except urllib.error.HTTPError as error:
        raise SessionReadError('JWT_refresh_HTTP_' + str(error.code)) from None
    except SessionReadError:
        raise
    except Exception:
        raise SessionReadError('JWT_refresh_request_or_JSON_failed') from None


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        return None


def read_channels(token):
    request = urllib.request.Request(CHANNEL_URL, method='GET', headers={'Authentication': token, 'Accept': 'application/json', 'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/108.0.0.0 Safari/537.36 app/df_client dfVersion/100130'})
    try:
        with urllib.request.build_opener(NoRedirect).open(request, timeout=20) as response:
            raw = response.read(1048577)
            if len(raw) > 1048576:
                raise SessionReadError('channel_response_exceeds_limit')
        payload = json.loads(raw)
    except urllib.error.HTTPError as error:
        raise SessionReadError('channel_HTTP_' + str(error.code)) from None
    except SessionReadError:
        raise
    except Exception:
        raise SessionReadError('channel_request_or_JSON_failed') from None
    if not isinstance(payload, dict) or payload.get('code') not in ('OK', 0, 200):
        code = payload.get('code') if isinstance(payload, dict) else None
        allowed = str(code) if re.fullmatch(r'[A-Z_0-9]{1,50}', str(code)) else 'UNKNOWN'
        raise SessionReadError('channel_business_' + allowed)
    from .dd import safe_channels
    return safe_channels(payload)



def read_desktop_channels(expected_dd_dir=None, *, task_broker=False, _allow_elevation=True,
                          _expected_gui=None, _profile_anchor=None):
    """Return only channel candidates; never forward a credential to a broker."""
    from .dd_broker import running_dd_processes

    stage, memory, snapshot, token = "verify_GUI", None, None, ''
    try:
        if os.name != "nt" or ctypes.sizeof(ctypes.c_void_p) != 8:
            raise SessionReadError("requires_Windows_64bit_Python")
        before = running_dd_processes()
        if len(before) != 1 or not before[0].get("signature"):
            raise SessionReadError("requires_one_signature_verified_DD_GUI")
        if _expected_gui is not None and any(before[0].get(key) != _expected_gui.get(key) for key in ('pid', 'started', 'dd_dir')):
            raise SessionReadError('GUI_changed_during_UAC')
        install = Path(before[0]["dd_dir"]).resolve()
        if expected_dd_dir is not None and install != Path(expected_dd_dir).resolve():
            raise SessionReadError("GUI_installation_does_not_match_task_session")
        stage = "verify_build"
        verify_binding(install)
        stage = "open_readonly_process"
        try:
            memory = Memory(before[0]["pid"], str(install))
        except SessionReadError as error:
            if _allow_elevation and str(error) == 'process_read_denied_same_windows_integrity_required':
                from .dd_channel_elevated import elevated_channels
                return elevated_channels(before[0])
            raise
        verify_same_user(memory)
        identity = memory.process_identity()
        if (identity['started'] != before[0]['started'] or identity['started'] <= 0 or
                Path(identity['executable']).resolve() != (install / 'netease_dd.exe').resolve()):
            raise SessionReadError('opened_GUI_identity_changed_before_read')
        stage = "locate_runtime_objects"
        snapshot = memory.snapshot(RUNTIME_RVA)
        if _profile_anchor is not None:
            from .dd_desktop import _network_profiles
            actual_profiles = _network_profiles([before[0]['pid']])
            if (len(actual_profiles) != 1 or actual_profiles[0][0] != _profile_anchor['network_pid'] or
                    str(actual_profiles[0][1]) != _profile_anchor['profile'] or
                    str(snapshot['ccid']) != Path(_profile_anchor['profile']).parent.name):
                raise SessionReadError('GUI_account_profile_changed_during_UAC')
        stage = "validate_cached_JWT"
        token = current_channel_token(snapshot)
        if not memory.still_online(snapshot):
            raise SessionReadError('GUI_session_changed_before_channel_query')
        stage = "read_channel_candidates"
        channels = read_channels(token)
        serialized = json.dumps(channels, ensure_ascii=False)
        if any(secret and secret in serialized for secret in (token, snapshot['token'], snapshot.get('login_token'))):
            raise SessionReadError("channel_response_echoed_credential")
        stage = "verify_GUI_session"
        after = running_dd_processes()
        if (not memory.still_online(snapshot) or
                [(p["pid"], p["started"]) for p in before] != [(p["pid"], p["started"]) for p in after]):
            raise SessionReadError("GUI_session_changed_during_channel_query")
        if _profile_anchor is not None and [(pid, str(path)) for pid, path in _network_profiles([before[0]['pid']])] != [(_profile_anchor['network_pid'], _profile_anchor['profile'])]:
            raise SessionReadError('GUI_account_profile_changed_during_channel_query')
        return channels
    except Exception as error:
        reason = str(error) if isinstance(error, SessionReadError) else type(error).__name__
        if snapshot is not None and any(secret and secret in reason for secret in (token, snapshot.get('token'), snapshot.get('login_token'))):
            reason = 'channel_read_failed'
        if isinstance(error, FuploadError):
            raise
        message = "Existing DD GUI channel choices could not be read; no additional login was attempted"
        raise FuploadError(message, kind="desktop_channel_unavailable", stage="dependency_get",
                           details={"channel_stage": stage, "reason": reason}) from None
    finally:
        if snapshot is not None:
            snapshot["token"] = ""
            snapshot['login_token'] = ''
        if memory is not None:
            memory.close()
