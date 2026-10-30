from __future__ import annotations

import base64
import contextlib
import copy
import ctypes
import json
import os
from pathlib import Path
import subprocess
import struct
import sys
import time
import threading
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fupload_cli import dd_broker, dd_channel as channel, dd_channel_elevated as helper
from fupload_cli.errors import FuploadError

CHOICES = {'total': 1, 'items': [{'room_id': 'room', 'room_name': 'Fixture', 'channel_id': 'channel',
                               'channel_name': 'General', 'channel_type': 'text'}],
           'dependencies': [{'parent': 'room_id', 'children': ['channel_id', 'channel_type']}]}
GUI = {'pid': 101, 'started': 1234, 'dd_dir': str(Path('fixture-install').resolve()), 'signature': True}
ANCHOR = {'network_pid': 202, 'profile': str(Path('123/EBWebView').resolve())}
TASK = 'a' * 32


def jwt(exp, uid='11', eid='22', appid='webcc'):
    def part(value):
        return base64.urlsafe_b64encode(json.dumps(value).encode()).decode().rstrip('=')
    return '.'.join((part({'alg': 'HS256'}), part({'appid': appid, 'user': {'uid': uid, 'eid': eid}, 'exp': exp}), 'SYNTHETIC'))


def transport():
    api = mock.Mock()
    api.k.GetCurrentProcess.return_value = 1
    api.k.GetProcessId.return_value = 42
    api.identity.return_value = {'sid': 'S-1-5-21-1', 'started': 99, 'executable': helper.runtime_python()}
    api.pipe.return_value = 2
    api.launch.return_value = 3
    api.peer.return_value = 42
    api.receive.return_value = {'task': TASK, 'channels': CHOICES}
    return api


class ElevatedChannelTests(unittest.TestCase):
    def setup_parent(self, api):
        stack = contextlib.ExitStack()
        stack.enter_context(mock.patch.object(helper, 'Windows', return_value=api))
        stack.enter_context(mock.patch.object(helper, 'profile_anchor', return_value=ANCHOR))
        stack.enter_context(mock.patch.object(helper.uuid, 'uuid4', return_value=mock.Mock(hex=TASK)))
        stack.enter_context(mock.patch.object(dd_broker, 'running_dd_processes', return_value=[GUI]))
        return stack

    def test_one_shot_parent_sends_only_metadata_and_accepts_only_launched_PID(self):
        api = transport()
        with self.setup_parent(api):
            self.assertEqual(helper.elevated_channels(GUI), CHOICES)
        api.launch.assert_called_once()
        sent = api.send.call_args.args[1]
        self.assertEqual(set(sent), {'task', 'gui', 'profile'})
        self.assertEqual(set(sent['gui']), {'pid', 'started', 'dd_dir'})
        self.assertEqual(sent['profile'], ANCHOR)
        self.assertEqual(api.peer.call_args.args, (2, True))
        api.k.DisconnectNamedPipe.assert_called_once_with(2)
        api.k.CloseHandle.assert_any_call(2); api.k.CloseHandle.assert_any_call(3)
        api = transport(); api.peer.return_value = 999
        with self.setup_parent(api), self.assertRaises(FuploadError) as failed:
            helper.elevated_channels(GUI)
        self.assertEqual(failed.exception.details['reason'], 'helper_client_PID_mismatch')
        api.send.assert_not_called(); api.receive.assert_not_called()

    def test_cancel_timeout_identity_and_new_GUI_fail_without_retry(self):
        for reason in ('UAC_cancelled', 'helper_timeout'):
            api = transport()
            if reason == 'UAC_cancelled': api.launch.side_effect = helper.fail(reason)
            else: api.io.side_effect = helper.fail(reason)
            with self.subTest(reason=reason), self.setup_parent(api), self.assertRaises(FuploadError) as failed:
                helper.elevated_channels(GUI)
            self.assertEqual(failed.exception.details['reason'], reason)
            api.launch.assert_called_once(); api.send.assert_not_called()
        api = transport()
        api.identity.side_effect = [api.identity.return_value, {**api.identity.return_value, 'sid': 'S-1-5-21-OTHER'}]
        with self.setup_parent(api), self.assertRaises(FuploadError): helper.elevated_channels(GUI)
        api.send.assert_not_called()
        api = transport()
        with self.setup_parent(api), mock.patch.object(dd_broker, 'running_dd_processes', return_value=[{**GUI, 'started': 999}]), self.assertRaises(FuploadError) as failed:
            helper.elevated_channels(GUI)
        self.assertEqual(failed.exception.details['reason'], 'GUI_or_account_changed_during_UAC')

    def test_rejects_wrong_task_raw_HTTP_and_credential_fields(self):
        for response in ({'task': 'b'*32, 'channels': CHOICES}, {'task': TASK, 'token': 'synthetic'},
                         {'task': TASK, 'channels': {**CHOICES, 'raw': {}}},
                         {'task': TASK, 'reason': 'unsafe http://example.invalid/?token=synthetic'}):
            api = transport(); api.receive.return_value = response
            with self.subTest(response=response), self.setup_parent(api), self.assertRaises(FuploadError):
                helper.elevated_channels(GUI)
        self.assertEqual(helper.validate_choices({**CHOICES, 'items': [{**CHOICES['items'][0], 'channel_name': None}]} )['total'], 1)

    def test_child_rejects_forged_server_or_different_parent_before_read(self):
        args = ['--pipe', helper.PREFIX+TASK, '--task', TASK, '--parent-pid', '42', '--parent-started', '99']
        for bad in ('server', 'sid', 'started'):
            api = transport(); api.open_peer.return_value = 5; api.k.CreateFileW.return_value = 6
            identity = api.identity.return_value
            if bad == 'server': api.peer.return_value = 88
            if bad == 'sid': api.identity.side_effect = [identity, {**identity, 'sid': 'other'}]
            if bad == 'started': api.identity.return_value = {**identity, 'started': 100}
            with self.subTest(bad=bad), mock.patch.object(helper, 'Windows', return_value=api), mock.patch.object(channel, 'read_desktop_channels') as read:
                self.assertEqual(helper.child_main(args), 1)
            read.assert_not_called(); api.send.assert_not_called()

    def test_child_cannot_re_elevate_and_returns_only_candidates(self):
        api = transport(); api.open_peer.return_value = 5; api.k.CreateFileW.return_value = 6
        api.receive.return_value = {'task': TASK, 'gui': {k: GUI[k] for k in ('pid','started','dd_dir')}, 'profile': ANCHOR}
        args = ['--pipe', helper.PREFIX+TASK, '--task', TASK, '--parent-pid', '42', '--parent-started', '99']
        with mock.patch.object(helper, 'Windows', return_value=api), mock.patch.object(channel, 'read_desktop_channels', return_value=CHOICES) as read:
            self.assertEqual(helper.child_main(args), 0)
        read.assert_called_once_with(expected_dd_dir=GUI['dd_dir'], _allow_elevation=False,
                                     _expected_gui=api.receive.return_value['gui'], _profile_anchor=ANCHOR)
        self.assertEqual(api.send.call_args.args[1], {'task':TASK, 'channels':CHOICES})
        self.assertEqual(api.k.CreateFileW.call_args.args[5], 0x40110000)

    def test_normal_subprocess_invalid_entry_has_no_output_or_permission_request(self):
        result = subprocess.run([sys.executable, '-I', '-S', '-B', str(Path(helper.__file__).resolve()), '--invalid'],
                                capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, b''); self.assertEqual(result.stderr, b'')

    @unittest.skipUnless(os.name == 'nt', 'Windows launch structures')
    def test_launch_uses_fixed_script_base_interpreter_and_runas_only(self):
        api = helper.Windows.__new__(helper.Windows); api.s = mock.Mock()
        def execute(pointer):
            info = pointer._obj
            self.assertEqual(info.lpVerb, 'runas')
            self.assertEqual(info.lpFile, helper.runtime_python())
            self.assertIn('-I -S -B', info.lpParameters)
            self.assertIn(str(Path(helper.__file__).resolve()), info.lpParameters)
            self.assertNotIn('token', info.lpParameters.lower())
            info.hProcess = 123
            return True
        api.s.ShellExecuteExW.side_effect = execute
        self.assertEqual(api.launch(helper.PREFIX+TASK, TASK, {'started':99}), 123)

    @unittest.skipUnless(os.name == 'nt', 'Windows actual pipe; no UAC')
    def test_actual_same_user_overlapped_pipe_roundtrip_without_UAC(self):
        api = helper.Windows()
        name = helper.PREFIX + helper.uuid.uuid4().hex
        parent = api.identity(api.k.GetCurrentProcess())
        pipe = api.pipe(name, parent['sid'])
        errors, received = [], []
        deadline = time.monotonic() + 5
        def client():
            handle = None
            try:
                handle = api.k.CreateFileW(name, 0xC0000000, 0, None, 3, 0x40110000, None)
                self.assertNotEqual(handle, ctypes.c_void_p(-1).value)
                self.assertEqual(api.peer(handle, False), os.getpid())
                received.append(api.receive(handle, deadline))
                api.send(handle, {'task':TASK,'channels':CHOICES}, deadline)
            except BaseException as error:
                errors.append(error)
            finally:
                if handle and handle != ctypes.c_void_p(-1).value: api.k.CloseHandle(handle)
        thread = threading.Thread(target=client, daemon=True)
        try:
            thread.start()
            api.io(pipe, 'connect', 0, deadline)
            self.assertEqual(api.peer(pipe, True), os.getpid())
            api.send(pipe, {'task':TASK}, deadline)
            self.assertEqual(api.receive(pipe, deadline), {'task':TASK,'channels':CHOICES})
            thread.join(5)
            self.assertFalse(thread.is_alive())
            self.assertFalse(errors, [type(error).__name__ for error in errors])
            self.assertEqual(received, [{'task':TASK}])
        finally:
            api.k.DisconnectNamedPipe(pipe); api.k.CloseHandle(pipe)

    @unittest.skipUnless(os.name == 'nt', 'Windows process boundary')
    def test_native_OpenProcess_error_routes_only_ACCESS_DENIED_to_UAC(self):
        for code, reason in ((5, 'process_read_denied_same_windows_integrity_required'), (87, 'GUI_process_open_failed')):
            kernel=mock.Mock();kernel.OpenProcess.return_value=0
            with self.subTest(code=code), mock.patch.object(channel.ctypes,'WinDLL',return_value=kernel), mock.patch.object(channel.ctypes,'get_last_error',return_value=code), self.assertRaises(channel.SessionReadError) as failed:
                channel.Memory(101, 'fixture-install')
            self.assertEqual(str(failed.exception), reason)
            kernel.OpenProcess.assert_called_once_with(0x1010, False, 101)

    @unittest.skipUnless(os.name == 'nt', 'Windows process boundary')
    def test_elevation_is_only_on_access_denied_and_never_recurses(self):
        for reason, enabled, expected in [('process_read_denied_same_windows_integrity_required', True, 1),
                                          ('process_read_denied_same_windows_integrity_required', False, 0),
                                          ('GUI_process_open_failed', True, 0)]:
            with self.subTest(reason=reason, enabled=enabled), mock.patch.object(dd_broker, 'running_dd_processes', return_value=[GUI]), mock.patch.object(channel, 'verify_binding'), mock.patch.object(channel, 'Memory', side_effect=channel.SessionReadError(reason)), mock.patch.object(helper, 'elevated_channels', return_value=CHOICES) as elevate:
                if expected: self.assertEqual(channel.read_desktop_channels(_allow_elevation=enabled), CHOICES)
                else:
                    with self.assertRaises(FuploadError): channel.read_desktop_channels(_allow_elevation=enabled)
                self.assertEqual(elevate.call_count, expected)

    @unittest.skipUnless(os.name == 'nt', 'Windows process boundary')
    def test_GUI_and_profile_change_are_rejected_before_credential_HTTP(self):
        from fupload_cli import dd_desktop
        memory = mock.Mock()
        memory.process_identity.return_value = {'started':GUI['started'], 'executable':str(Path(GUI['dd_dir'])/'netease_dd.exe')}
        memory.snapshot.return_value = {'token':'SYNTHETIC_JWT', 'login_token':'SYNTHETIC_LOGIN', 'ccid':'999'}
        with mock.patch.object(dd_broker,'running_dd_processes',return_value=[GUI]), mock.patch.object(channel,'verify_binding'), mock.patch.object(channel,'verify_same_user'), mock.patch.object(channel,'Memory',return_value=memory), mock.patch.object(dd_desktop,'_network_profiles',return_value=[(ANCHOR['network_pid'],Path(ANCHOR['profile']))]), mock.patch.object(channel,'current_channel_token') as token, self.assertRaises(FuploadError) as failed:
            channel.read_desktop_channels(_allow_elevation=False, _expected_gui=GUI, _profile_anchor=ANCHOR)
        self.assertEqual(failed.exception.details['reason'], 'GUI_account_profile_changed_during_UAC')
        token.assert_not_called()
        with mock.patch.object(dd_broker,'running_dd_processes',return_value=[{**GUI,'started':999}]), mock.patch.object(channel,'Memory') as read, self.assertRaises(FuploadError) as failed:
            channel.read_desktop_channels(_allow_elevation=False, _expected_gui=GUI)
        self.assertEqual(failed.exception.details['reason'], 'GUI_changed_during_UAC')
        read.assert_not_called()

    @unittest.skipUnless(os.name == 'nt', 'Windows process boundary')
    def test_candidates_and_error_codes_cannot_echo_either_secret(self):
        for source in ('candidate', 'error'):
            memory=mock.Mock()
            memory.process_identity.return_value={'started':GUI['started'],'executable':str(Path(GUI['dd_dir'])/'netease_dd.exe')}
            memory.snapshot.return_value={'token':'SYNTHETIC_OLD_JWT', 'login_token':'SYNTHETIC_LOGIN_SECRET'}
            choices=copy.deepcopy(CHOICES);choices['items'][0]['room_name']='SYNTHETIC_LOGIN_SECRET'
            response={'return_value':choices} if source=='candidate' else {'side_effect':channel.SessionReadError('channel_business_SYNTHETIC_LOGIN_SECRET')}
            with self.subTest(source=source), mock.patch.object(dd_broker,'running_dd_processes',return_value=[GUI]), mock.patch.object(channel,'verify_binding'), mock.patch.object(channel,'verify_same_user'), mock.patch.object(channel,'Memory',return_value=memory), mock.patch.object(channel,'current_channel_token',return_value='SYNTHETIC_NEW_JWT'), mock.patch.object(channel,'read_channels',**response), self.assertRaises(FuploadError) as failed:
                channel.read_desktop_channels(_allow_elevation=False)
            self.assertNotIn('SYNTHETIC_LOGIN_SECRET', json.dumps(failed.exception.as_dict()))
            self.assertEqual(memory.snapshot.return_value['login_token'], '')


class RefreshTests(unittest.TestCase):
    def test_uint64_identity_uses_three_digits_without_widening_enum_reader(self):
        memory=channel.Memory.__new__(channel.Memory)
        with mock.patch.object(memory,'type_name',return_value='int'), mock.patch.object(memory,'integer',return_value=3), mock.patch.object(memory,'read',side_effect=lambda address,size:struct.pack('<I',{1024:0,1028:0,1032:8}[address])):
            self.assertEqual(memory.scalar(1000), 2**63)
            with self.assertRaises(channel.SessionReadError): memory.number(1000)
        with mock.patch.object(memory,'type_name',return_value='int'), mock.patch.object(memory,'integer',return_value=5), self.assertRaises(channel.SessionReadError):
            memory.scalar(1000)

    def snapshot(self, expired=False):
        return {'token': jwt(time.time()-1 if expired else time.time()+600), 'uid':'11', 'eid':'22', 'ccid':'123',
                'login_token':'SYNTHETIC_LOGIN_SECRET', 'delta':2.0}

    def test_valid_cached_JWT_needs_no_refresh(self):
        snapshot = self.snapshot()
        with mock.patch.object(channel.urllib.request, 'build_opener') as request:
            self.assertEqual(channel.current_channel_token(snapshot), snapshot['token'])
        request.assert_not_called()

    def test_expired_JWT_uses_exact_official_GET_once_and_correct_signature(self):
        snapshot = self.snapshot(True); token = jwt(time.time()+600)
        response = mock.MagicMock(); response.__enter__.return_value = response
        response.read.return_value = json.dumps({'code':'OK','data':{'jwt':token}}).encode()
        opener = mock.Mock(); opener.open.return_value = response
        with mock.patch.object(channel.urllib.request, 'build_opener', return_value=opener), mock.patch.object(channel.time, 'time', return_value=2000000000):
            token = jwt(2000000600); response.read.return_value=json.dumps({'code':'OK','data':{'jwt':token}}).encode()
            self.assertEqual(channel.current_channel_token(snapshot), token)
        request = opener.open.call_args.args[0]
        self.assertEqual(request.full_url, 'https://api.cc.163.com/v1/jwt?appid=webcc&uid=11&eid=22&timestamp=2000000002')
        self.assertEqual(request.get_method(), 'GET')
        self.assertEqual(request.get_header('Authentication'), channel.hashlib.md5(b'webcc_2000000002_SYNTHETIC_LOGIN_SECRET').hexdigest())
        opener.open.assert_called_once()
        self.assertNotIn(snapshot['login_token'], request.full_url)

    def test_rejected_refresh_does_not_retry_or_query_channels_and_masks_raw_body(self):
        import urllib.error
        snapshot = self.snapshot(True)
        opener = mock.Mock(); opener.open.side_effect = urllib.error.HTTPError('secret-url', 401, 'SYNTHETIC_LOGIN_SECRET', {}, None)
        with mock.patch.object(channel.urllib.request, 'build_opener', return_value=opener), mock.patch.object(channel, 'read_channels') as read, self.assertRaises(channel.SessionReadError) as failed:
            channel.current_channel_token(snapshot)
        self.assertEqual(str(failed.exception), 'JWT_refresh_HTTP_401')
        opener.open.assert_called_once(); read.assert_not_called()

    def test_foreign_UID_EID_app_or_lifetime_is_rejected_without_refresh(self):
        for values in ({'uid':'other'}, {'eid':'other'}, {'appid':'other'}, {'exp':time.time()+5000}):
            snapshot = self.snapshot(); snapshot['token'] = jwt(**{'exp':time.time()+600, **values})
            with self.subTest(values=values), mock.patch.object(channel.urllib.request, 'build_opener') as request, self.assertRaises(channel.SessionReadError):
                channel.current_channel_token(snapshot)
            request.assert_not_called()

    def test_login_secret_and_identity_mutation_invalidate_snapshot(self):
        memory = channel.Memory.__new__(channel.Memory)
        snapshot = {'helper':1,'data_center':2,'user':3,'login_object':4,'login_token':'secret',
                    'delta_object':5,'delta':2.0,'uid':'11','eid':'22','ccid':'123'}
        attrs = {(1,'_dataCenter'):2,(2,'_myUserInfo'):3,(1,'_loginToken'):4,(1,'_server_time_delta'):5,
                 (3,'uid'):6,(3,'eid'):7,(3,'ccid'):8}
        scalars = {5:2.0,6:'11',7:'22',8:'123'}
        with mock.patch.object(memory,'attribute',side_effect=lambda obj,key:attrs[(obj,key)]), mock.patch.object(memory,'text',return_value='secret') as text, mock.patch.object(memory,'scalar',side_effect=lambda obj:scalars[obj]):
            self.assertTrue(memory.refresh_unchanged(snapshot))
            text.return_value = 'replaced'; self.assertFalse(memory.refresh_unchanged(snapshot))
            text.return_value = 'secret'; scalars[7] = 'new_eid'; self.assertFalse(memory.refresh_unchanged(snapshot))


if __name__ == '__main__': unittest.main()
