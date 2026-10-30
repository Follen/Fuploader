from __future__ import annotations

import ctypes
import json
import os
from pathlib import Path
import struct
import sys
from types import SimpleNamespace
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fupload_cli import dd_broker, dd_channel
from fupload_cli.dd import DD, Sidecar, safe_channels
from fupload_cli.errors import FuploadError


CHOICES = {"total": 1, "items": [{"room_id": "room", "room_name": "Fixture", "channel_id": "channel",
                                 "channel_name": "General", "channel_type": "text"}],
           "dependencies": [{"parent": "room_id", "children": ["channel_id", "channel_type"]}]}


class DDChannelTests(unittest.TestCase):
    def test_borrowed_read_runs_in_authenticated_CLI_parent_not_broker(self):
        status = {"running": True, "session_id": "task", "session_source": "desktop-cookie", "dd_dir": "fixture-install"}
        with mock.patch.object(dd_broker, "status", return_value=status) as ping, mock.patch.object(dd_broker, "execute") as execute, mock.patch.object(dd_channel, "read_desktop_channels", return_value=CHOICES) as read:
            actual = DD().execute_read("options", "channels", SimpleNamespace(), "task")
        ping.assert_called_once_with("task")
        read.assert_called_once_with(expected_dd_dir="fixture-install")
        execute.assert_not_called()
        self.assertEqual(actual, CHOICES)

    def test_parent_rejects_missing_mismatched_or_unknown_session_without_read(self):
        for status in ({"running": False}, {"running": True, "session_id": "other", "session_source": "desktop-cookie"},
                       {"running": True, "session_id": "task", "session_source": "unknown"}):
            with self.subTest(status=status), mock.patch.object(dd_broker, "status", return_value=status), mock.patch.object(dd_broker, "execute") as execute, mock.patch.object(dd_channel, "read_desktop_channels") as read:
                with self.assertRaises(FuploadError):
                    DD().execute_read("options", "channels", SimpleNamespace(), "task")
                read.assert_not_called(); execute.assert_not_called()

    def test_native_channel_read_keeps_existing_broker_route(self):
        with mock.patch.object(dd_broker, "status", return_value={"running": True, "session_id": "task", "session_source": "native-login"}), mock.patch.object(dd_broker, "execute", return_value=CHOICES) as execute, mock.patch.object(dd_channel, "read_desktop_channels") as read:
            self.assertEqual(DD().execute_read("options", "channels", SimpleNamespace(), "task"), CHOICES)
        execute.assert_called_once_with("task", "read", "options", "channels", {})
        read.assert_not_called()

    def test_unrelated_read_does_not_open_GUI_memory_or_ping_session(self):
        with mock.patch.object(dd_broker, "status") as ping, mock.patch.object(dd_broker, "execute", return_value={"items": []}), mock.patch.object(dd_channel, "read_desktop_channels") as read:
            DD().execute_read("options", "game-types", SimpleNamespace(), "task")
        ping.assert_not_called(); read.assert_not_called()

    def test_borrowed_sidecar_only_allows_exact_fixed_read_and_keeps_credentials_local(self):
        sidecar = Sidecar.__new__(Sidecar)
        sidecar.session_source, sidecar.dd_dir = "desktop-cookie", Path("fixture-install")
        with mock.patch.object(sidecar, "call") as call, mock.patch.object(dd_channel, "read_desktop_channels", return_value=CHOICES) as read:
            payload = sidecar.cc_get(dd_channel.CHANNEL_URL)
            self.assertEqual(safe_channels(payload), CHOICES)
            for url in ("https://example.invalid", dd_channel.CHANNEL_URL + "&extra=1"):
                with self.assertRaises(FuploadError):
                    sidecar.cc_get(url)
            call.assert_not_called()
        read.assert_called_once_with(expected_dd_dir=sidecar.dd_dir, task_broker=True)

    def test_native_sidecar_cc_get_does_not_change(self):
        sidecar = Sidecar.__new__(Sidecar)
        sidecar.session_source = "native-login"
        with mock.patch.object(sidecar, "call", return_value={"data": []}) as call, mock.patch.object(dd_channel, "read_desktop_channels") as read:
            sidecar.cc_get(dd_channel.CHANNEL_URL)
        call.assert_called_once_with("cc_get", url=dd_channel.CHANNEL_URL)
        read.assert_not_called()

    def test_read_on_borrowed_route_uses_same_helper(self):
        sidecar = SimpleNamespace(session_source="desktop-cookie", dd_dir=Path("fixture-install"), cc_get=mock.Mock())
        with mock.patch.object(dd_channel, "read_desktop_channels", return_value=CHOICES) as read:
            self.assertEqual(DD().execute_read_on(sidecar, "options", "channels", SimpleNamespace()), CHOICES)
        read.assert_called_once_with(expected_dd_dir=sidecar.dd_dir)
        sidecar.cc_get.assert_not_called()

    def test_post_read_detects_JWT_replacement_and_new_login_session(self):
        memory = dd_channel.Memory.__new__(dd_channel.Memory)
        values = {(1, "_messageCenter"): 3, (2, "_msgCenter"): 3, (2, "_jwt"): 4, (1, "_session"): 5}
        snapshot = {"controller": 1, "helper": 2, "center": 3, "token_object": 4, "session_anchor": 5, "token": "synthetic", "session_value": "anchor"}
        texts = {4: "synthetic", 5: "anchor"}
        with mock.patch.object(memory, "attribute", side_effect=lambda obj, key: values[(obj,key)]), mock.patch.object(memory, "text", side_effect=lambda obj:texts[obj]), mock.patch.object(memory, 'type_name', return_value='str'), mock.patch.object(memory, "is_logged_in", return_value=True), mock.patch.object(memory, 'refresh_unchanged', return_value=True):
            self.assertTrue(memory.still_online(snapshot))
            values[(2, "_jwt")] = 6
            self.assertFalse(memory.still_online(snapshot))
            values[(2, "_jwt")] = 4
            values[(1, "_session")] = 7
            self.assertFalse(memory.still_online(snapshot))
            values[(1, "_session")] = 5
            texts[4] = "new-value-at-reused-object-address"
            self.assertFalse(memory.still_online(snapshot))
            texts[4] = "synthetic"
            texts[5] = "new-login-at-reused-object-address"
            self.assertFalse(memory.still_online(snapshot))

    def test_enum_read_uses_module_and_members_instead_of_type_name_literal(self):
        memory = dd_channel.Memory.__new__(dd_channel.Memory)
        attributes = {(1,"state"):2,(2,"_name_"):3,(2,"_value_"):4}
        with mock.patch.object(memory,"type_name",return_value="MessageCenter"), mock.patch.object(memory,"class_module",return_value="components.net_server.messagecenter"), mock.patch.object(memory,"attribute",side_effect=lambda obj,key:attributes[(obj,key)]), mock.patch.object(memory,"text",return_value="LoggedIn"), mock.patch.object(memory,"number",return_value=3):
            self.assertTrue(memory.is_logged_in(1))
        with mock.patch.object(memory,"type_name",return_value="MessageCenter"), mock.patch.object(memory,"class_module",return_value="unrelated.module"):
            with self.assertRaises(dd_channel.SessionReadError): memory.is_logged_in(1)

    def test_HTTP_is_single_fixed_GET_no_redirect_or_raw_server_error_output(self):
        response = mock.MagicMock()
        response.__enter__.return_value = response
        response.read.return_value = json.dumps({"code":"OK","data":[{"teamId":"room"}]}).encode()
        opener = mock.Mock(); opener.open.return_value = response
        with mock.patch.object(dd_channel.urllib.request, "build_opener", return_value=opener) as build:
            self.assertEqual(dd_channel.read_channels("synthetic_private_value")["total"], 1)
        request = opener.open.call_args.args[0]
        self.assertEqual((request.get_method(), request.full_url), ("GET", dd_channel.CHANNEL_URL))
        self.assertEqual(request.get_header("Authentication"), "synthetic_private_value")
        build.assert_called_once_with(dd_channel.NoRedirect)
        self.assertEqual(opener.open.call_count, 1)
        self.assertIsNone(dd_channel.NoRedirect().redirect_request(None,None,302,"",{},"https://example.invalid"))
        response.read.return_value = json.dumps({"code":"UNAUTHORIZED","message":"synthetic_private_value"}).encode()
        with mock.patch.object(dd_channel.urllib.request, "build_opener", return_value=opener), self.assertRaises(dd_channel.SessionReadError) as failed:
            dd_channel.read_channels("synthetic_private_value")
        self.assertNotIn("synthetic_private_value", str(failed.exception))

    @unittest.skipUnless(os.name == "nt", "Windows process ownership and integrity boundary")
    def test_permissions_and_opened_process_identity_fail_before_runtime_HTTP(self):
        from fupload_cli import dd_channel_elevated
        gui = {"pid": 1, "started": 10, "signature": {"status":"Valid"}, "dd_dir": str(Path("fixture-install").resolve())}
        with mock.patch.object(dd_broker,"running_dd_processes",return_value=[gui]), mock.patch.object(dd_channel,"verify_binding"), mock.patch.object(dd_channel,"Memory",side_effect=dd_channel.SessionReadError("process_read_denied_same_windows_integrity_required")), mock.patch.object(dd_channel,"read_channels") as request, mock.patch.object(dd_channel_elevated, 'elevated_channels', return_value=CHOICES) as elevate:
            self.assertEqual(dd_channel.read_desktop_channels(task_broker=True), CHOICES)
        elevate.assert_called_once_with(gui)
        request.assert_not_called()
        memory = mock.Mock()
        memory.process_identity.return_value = {"started":11,"executable":str(Path("fixture-install/netease_dd.exe").resolve())}
        with mock.patch.object(dd_broker,"running_dd_processes",return_value=[gui]), mock.patch.object(dd_channel,"verify_binding"), mock.patch.object(dd_channel,"verify_same_user"), mock.patch.object(dd_channel,"Memory",return_value=memory), mock.patch.object(dd_channel,"read_channels") as request:
            with self.assertRaises(FuploadError) as failed: dd_channel.read_desktop_channels()
        self.assertEqual(failed.exception.details["reason"],"opened_GUI_identity_changed_before_read")
        memory.snapshot.assert_not_called(); request.assert_not_called(); memory.close.assert_called_once()


if __name__ == "__main__": unittest.main()
