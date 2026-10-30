from __future__ import annotations

import hashlib
import importlib
import io
import json
import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fupload_cli import dd_desktop as desktop
from fupload_cli import trust
from fupload_cli.dd import Sidecar
from fupload_cli.errors import FuploadError


class CookieSnapshotTests(unittest.TestCase):
    def test_browser_signature_requires_microsoft_publisher(self):
        executable = Path('msedgewebview2.exe')
        powershell = 'C:/Windows/System32/WindowsPowerShell/v1.0/powershell.exe'
        for status, publisher, accepted in (
            ('Valid', 'Microsoft Corporation', True),
            ('Valid', 'NetEase (Hangzhou) Network Co., Ltd', False),
            ('NotSigned', 'Microsoft Corporation', False),
        ):
            with self.subTest(status=status, publisher=publisher), mock.patch.object(trust, '_powershell_path', return_value=powershell), mock.patch.object(trust.subprocess, 'run', return_value=SimpleNamespace(returncode=0, stdout=json.dumps({'Status': status, 'Subject': 'CN=fixture,O=' + publisher}))):
                if accepted:
                    self.assertEqual(trust.verify_webview_executable(executable)['publisher'], publisher)
                else:
                    with self.assertRaises(FuploadError):
                        trust.verify_webview_executable(executable)

    @unittest.skipUnless(hasattr(sqlite3.Connection, 'deserialize'), 'SQLite image loading requires Python 3.11')
    def test_committed_wal_is_replayed_in_memory(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'fixture.db'
            connection = sqlite3.connect(path)
            try:
                connection.execute('PRAGMA journal_mode=WAL')
                connection.execute('PRAGMA wal_autocheckpoint=0')
                connection.execute('CREATE TABLE fixture(value TEXT)')
                connection.execute("INSERT INTO fixture VALUES ('committed')")
                connection.commit()
                image = desktop._sqlite_image(path.read_bytes(), Path(str(path) + '-wal').read_bytes())
                copy = sqlite3.connect(':memory:')
                try:
                    copy.deserialize(image)
                    self.assertEqual(copy.execute('SELECT value FROM fixture').fetchall(), [('committed',)])
                finally:
                    copy.close()
                wal = bytearray(Path(str(path) + '-wal').read_bytes())
                wal[24] ^= 1
                with self.assertRaises(desktop.CookieSnapshotError):
                    desktop._sqlite_image(path.read_bytes(), bytes(wal))
            finally:
                connection.close()

    @unittest.skipUnless(os.name == 'nt', 'Windows CNG')
    def test_aes_gcm_known_vector_and_tampered_tag(self):
        encrypted = bytes.fromhex('0388dace60b6a392f328c2b971b2fe78ab6e47d42cec13bdf53a67b21257bddf')
        self.assertEqual(desktop._aes_gcm_decrypt(bytes(16), bytes(12), encrypted), bytes(16))
        with self.assertRaises(desktop.CookieSnapshotError):
            desktop._aes_gcm_decrypt(bytes(16), bytes(12), encrypted[:-1] + bytes([encrypted[-1] ^ 1]))

    @unittest.skipUnless(hasattr(sqlite3.Connection, 'deserialize'), 'SQLite image loading requires Python 3.11')
    def test_cookie_domain_binding_and_active_profile_are_required(self):
        with tempfile.TemporaryDirectory() as folder:
            profile = Path(folder) / 'EBWebView'
            profile.mkdir()
            (profile / 'Local State').write_text(json.dumps({'os_crypt': {'encrypted_key': 'RFBBUElmaXh0dXJl'}}))
            path = profile / 'Default' / 'Network' / 'Cookies'
            path.parent.mkdir(parents=True)
            connection = sqlite3.connect(path)
            connection.execute('CREATE TABLE meta(key TEXT,value TEXT)')
            connection.execute("INSERT INTO meta VALUES ('version','24')")
            connection.execute('CREATE TABLE cookies(host_key TEXT,name TEXT,value TEXT,encrypted_value BLOB,expires_utc INTEGER)')
            encrypted = b'v10' + bytes(12) + bytes(16)
            connection.execute('INSERT INTO cookies VALUES (?,?,?,?,?)', ('.163.com', 'NTES_YD_SESS', '', encrypted, 0))
            connection.commit()
            connection.close()
            snapshot = {str(path): path.read_bytes()}
            bound = hashlib.sha256(b'.163.com').digest() + b'non-secret-fixture'
            with mock.patch.object(desktop, '_unprotect', return_value=bytes(16)), mock.patch.object(desktop, '_aes_gcm_decrypt', return_value=bound):
                self.assertEqual(desktop._cookie_from_snapshot(profile, snapshot), ('NTES_YD_SESS', 'non-secret-fixture'))
                with self.assertRaises(desktop.CookieSnapshotError):
                    desktop._cookie_from_snapshot(profile / 'another-profile', snapshot)
            with mock.patch.object(desktop, '_unprotect', return_value=bytes(16)), mock.patch.object(desktop, '_aes_gcm_decrypt', return_value=bytes(32) + b'non-secret-fixture'):
                with self.assertRaises(desktop.CookieSnapshotError):
                    desktop._cookie_from_snapshot(profile, snapshot)

    def test_active_dd_borrow_failure_never_starts_a_native_login(self):
        directory = Path('dd-fixture').resolve()
        gui = [{'pid': 10, 'dd_dir': str(directory), 'signature': {'status': 'Valid'}}]
        with mock.patch('fupload_cli.dd.discover_dd_info', return_value=(directory, {})), mock.patch('fupload_cli.dd_broker.running_dd_processes', return_value=gui), mock.patch.object(desktop, 'borrow_desktop_cookie', side_effect=desktop.CookieSnapshotError('fixture unavailable')), mock.patch('fupload_cli.dd.subprocess.Popen') as spawn:
            with self.assertRaises(desktop.CookieSnapshotError):
                Sidecar().__enter__()
            spawn.assert_not_called()

    def test_desktop_cookie_uses_stdin_and_is_absent_from_process_arguments_and_environment(self):
        directory = Path('dd-fixture').resolve()
        gui = [{'pid': 10, 'dd_dir': str(directory), 'signature': {'status': 'Valid'}}]
        process = mock.Mock()
        process.stdin = io.StringIO()
        with mock.patch('fupload_cli.dd.discover_dd_info', return_value=(directory, {})), mock.patch('fupload_cli.dd_broker.running_dd_processes', return_value=gui), mock.patch.object(desktop, 'borrow_desktop_cookie', return_value=('NTES_YD_SESS', 'non-secret-fixture')), mock.patch.object(Sidecar, '_lock'), mock.patch.object(Sidecar, '_next_result', return_value={'ready': True, 'credential_kind': None}), mock.patch('fupload_cli.dd.threading.Thread'), mock.patch('fupload_cli.dd.subprocess.Popen', return_value=process) as spawn:
            session = Sidecar().__enter__()
            self.assertEqual(session.session_source, 'desktop-cookie')
            self.assertEqual(json.loads(process.stdin.getvalue())['cookie'], ['NTES_YD_SESS', 'non-secret-fixture'])
            self.assertNotIn('non-secret-fixture', repr(spawn.call_args))

    def test_untrusted_gui_is_not_a_cookie_source(self):
        with mock.patch.object(desktop.os, 'name', 'nt'), mock.patch.object(desktop, '_network_profiles') as profiles:
            with self.assertRaises(desktop.CookieSnapshotError):
                desktop.borrow_desktop_cookie([{'pid': 10, 'signature': None}])
            profiles.assert_not_called()


class DesktopAuthorLifecycleTests(unittest.TestCase):
    def test_http_session_cleanup_never_touches_a_message_center(self):
        source = Path(__file__).resolve().parents[1] / 'fupload_cli' / 'dd_sidecar.py'
        spec = importlib.util.spec_from_file_location('dd_sidecar_desktop_fixture', source)
        native = importlib.util.module_from_spec(spec)
        with mock.patch.dict(os.environ, {'NETEASE_DD_DIR': 'dd-fixture', 'FUPLOAD_DD_DEVICE_STATE': 'unused-fixture'}):
            spec.loader.exec_module(native)
        qt = mock.Mock()
        client = mock.Mock()
        client._session.headers = {}
        modules = {}
        for name in ('cli_anything', 'cli_anything.ccvoicehub', 'cli_anything.ccvoicehub.core', 'components', 'components.wow_ui'):
            modules[name] = ModuleType(name)
        runtime = ModuleType('cli_anything.ccvoicehub.core.qt_runtime')
        runtime.QtRuntime = SimpleNamespace(get_instance=lambda: qt)
        modules[runtime.__name__] = runtime
        api = ModuleType('cli_anything.ccvoicehub.core.ui_api_client')
        api.UiApiClient = mock.Mock(return_value=client)
        modules[api.__name__] = api
        signer = ModuleType('components.wow_ui.nep_wrapper')
        signer.NepWrapper = mock.Mock(return_value=SimpleNamespace(isDllInited=lambda: True))
        modules[signer.__name__] = signer
        with mock.patch.dict(sys.modules, modules), mock.patch.object(native, 'install_response_probe'), mock.patch.object(native, 'login_author_client') as login, mock.patch.object(native, 'open_session', side_effect=AssertionError('native login forbidden')):
            session = native.open_desktop_session(('NTES_YD_SESS', 'non-secret-fixture'))
            self.assertIsNone(session[1])
            self.assertIsNone(session[3])
            login.assert_called_once_with(client)
            native.close_session(session)
            client.close.assert_called_once()
            qt.shutdown.assert_called_once()


if __name__ == '__main__':
    unittest.main()
