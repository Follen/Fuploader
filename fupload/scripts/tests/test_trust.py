from __future__ import annotations

import json
import io
import os
import subprocess
import sys
import unittest
import urllib.request
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fupload_cli.errors import FuploadError
from fupload_cli.transport import json_request
import fupload_cli.trust as trust
from fupload_cli.trust import (
    NEWBEE_ORIGINS,
    SameOriginRedirectHandler,
    require_official_url,
    verify_dd_executable,
)


class TrustBoundaryTests(unittest.TestCase):
    def test_generic_transport_keeps_standard_urlopen_path(self) -> None:
        response = mock.MagicMock()
        response.__enter__.return_value.status = 200
        response.__enter__.return_value.read.return_value = b'{"ok":true}'
        with mock.patch("fupload_cli.transport.urllib.request.urlopen", return_value=response) as opened:
            self.assertEqual(json_request("https://example.test/read"), {"ok": True})
        opened.assert_called_once()

    def test_http_error_keeps_valid_utf8_chinese_message(self) -> None:
        error = urllib.error.HTTPError(
            "https://example.test/write", 403, "Forbidden", {},
            io.BytesIO(json.dumps({"message": "权限不足", "code": 4031}, ensure_ascii=False).encode("utf-8")),
        )
        with mock.patch("fupload_cli.transport.urllib.request.urlopen", side_effect=error):
            with self.assertRaises(FuploadError) as raised:
                json_request("https://example.test/write", method="POST")
        self.assertEqual(str(raised.exception), "权限不足")
        self.assertEqual(raised.exception.business_code, 4031)

    def test_http_error_invalid_utf8_does_not_inject_replacement_text(self) -> None:
        error = urllib.error.HTTPError(
            "https://example.test/write", 403, "Forbidden", {},
            io.BytesIO(b'{"message":"' + bytes([0xff]) + b'"}'),
        )
        with mock.patch("fupload_cli.transport.urllib.request.urlopen", side_effect=error):
            with self.assertRaises(FuploadError) as raised:
                json_request("https://example.test/write", method="POST")
        self.assertEqual(str(raised.exception), "HTTP 403")

    def test_environment_overrides_do_not_change_newbee_targets(self) -> None:
        script = (
            "from fupload_cli.newbee_auth import API_BASE, AUTH_BASE, auth_store_dir; "
            "from fupload_cli.newbee import METADATA_URL, NEXT_API_BASE, UPLOAD_SERVER; "
            "print(API_BASE); print(AUTH_BASE); print(METADATA_URL); "
            "print(NEXT_API_BASE); print(UPLOAD_SERVER); print(auth_store_dir())"
        )
        environment = os.environ.copy()
        environment.update({
            "FUPLOAD_NEWBEE_API_BASE": "http://attacker.invalid/api",
            "FUPLOAD_NEWBEE_AUTH_BASE": "http://attacker.invalid/auth",
            "FUPLOAD_NEWBEE_AUTH_DIR": str(Path.cwd() / "attacker-auth"),
            "APPDATA": str(Path.cwd() / "attacker-appdata"),
            "FUPLOAD_NEWBEE_METADATA_URL": "http://attacker.invalid/metadata",
            "FUPLOAD_NEWBEE_NEXT_API_BASE": "http://attacker.invalid/next",
            "FUPLOAD_NEWBEE_UPLOAD_SERVER": "http://attacker.invalid/upload",
        })
        result = subprocess.run(
            [sys.executable, "-c", script], cwd=str(Path(__file__).resolve().parents[1]),
            env=environment, capture_output=True, text=True, check=True,
        )
        values = result.stdout.splitlines()
        self.assertEqual(values[0], NEWBEE_ORIGINS["creator"])
        self.assertEqual(values[1], NEWBEE_ORIGINS["auth"] + "/auth")
        self.assertEqual(values[2], NEWBEE_ORIGINS["metadata"] + "/modconfig.json")
        self.assertEqual(values[3], NEWBEE_ORIGINS["next"])
        self.assertEqual(values[4], NEWBEE_ORIGINS["upload"] + "/uploadserver")
        self.assertTrue(values[5].endswith(os.path.join("NewBeeBox", "auth-store")))
        self.assertNotIn("attacker", result.stdout)

    def test_untrusted_http_and_host_are_rejected(self) -> None:
        with self.assertRaises(FuploadError):
            require_official_url("http://api.newbeebox.com/v3/user/auth2web", "creator")
        with self.assertRaises(FuploadError):
            require_official_url("https://attacker.invalid/v3/user/auth2web", "creator")
        with self.assertRaises(FuploadError):
            require_official_url("https://api.newbeebox.com:8443/v3/user/auth2web", "creator")

    def test_cross_origin_redirect_is_rejected_before_request(self) -> None:
        handler = SameOriginRedirectHandler(NEWBEE_ORIGINS["creator"])
        request = urllib.request.Request(NEWBEE_ORIGINS["creator"] + "/v3/user/auth2web")
        with self.assertRaises(FuploadError):
            handler.redirect_request(
                request, None, 302, "Found", {}, "https://attacker.invalid/collect"
            )

    def test_unknown_dd_publisher_is_rejected(self) -> None:
        completed = subprocess.CompletedProcess(
            args=[], returncode=0,
            stdout=json.dumps({
                "Status": "Valid",
                "Subject": 'CN="NetEase (Hangzhou) Network Co., Ltd", O="Evil Publisher"',
            }),
            stderr="",
        )
        with mock.patch("fupload_cli.trust.subprocess.run", return_value=completed):
            with self.assertRaisesRegex(FuploadError, "trusted official signature"):
                verify_dd_executable(Path("C:/fake/netease_dd.exe"))

    def test_dd_signature_output_keeps_only_publisher_organization(self) -> None:
        completed = subprocess.CompletedProcess(
            args=[], returncode=0,
            stdout=json.dumps({
                "Status": "Valid",
                "Subject": (
                    'CN="NetEase (Hangzhou) Network Co., Ltd", '
                    'O="NetEase (Hangzhou) Network Co., Ltd", SERIALNUMBER=secret'
                ),
            }),
            stderr="",
        )
        with mock.patch("fupload_cli.trust.subprocess.run", return_value=completed) as run:
            result = verify_dd_executable(Path("C:/official/netease_dd.exe"))
        self.assertEqual(result, {
            "status": "Valid",
            "publisher": "NetEase (Hangzhou) Network Co., Ltd",
        })
        self.assertEqual(run.call_args.kwargs["encoding"], "utf-8")
        self.assertEqual(run.call_args.kwargs["errors"], "strict")
        self.assertIn("$OutputEncoding", run.call_args.args[0][-1])

    def test_dd_signature_none_stdout_fails_closed(self) -> None:
        completed = subprocess.CompletedProcess(args=[], returncode=1, stdout=None, stderr=None)
        with mock.patch("fupload_cli.trust.subprocess.run", return_value=completed):
            with self.assertRaisesRegex(FuploadError, "Authenticode verification process"):
                verify_dd_executable(Path("C:/official/netease_dd.exe"))

    def test_reparse_point_attribute_is_rejected(self) -> None:
        stat_result = mock.Mock(st_file_attributes=0x400)
        with mock.patch("fupload_cli.trust.Path.is_symlink", return_value=False), mock.patch(
            "fupload_cli.trust.os.stat", return_value=stat_result
        ):
            self.assertTrue(trust._is_reparse_point(Path("C:/junction")))


if __name__ == "__main__":
    unittest.main()
