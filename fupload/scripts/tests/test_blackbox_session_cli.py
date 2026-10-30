from __future__ import annotations

import contextlib
import io
import json
from pathlib import Path
import sys
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fupload_cli.cli import build_parser, main
from fupload_cli.errors import ValidationError
from fupload_cli.schema import get_schema


class BlackboxSessionCliTests(unittest.TestCase):
    login_id = "a" * 32

    def document(self, action, **fields):
        return {"schema": get_schema("blackbox", "session", action).name, **fields}

    def test_authentication_steps_are_explicit_json_commands(self):
        parser = build_parser()
        for action in ("login-start", "login-submit", "renew", "forget"):
            args = parser.parse_args(["blackbox", "session", action, "--input", "-", "--dry-run"])
            self.assertEqual((args.handler, args.platform, args.resource, args.action), ("write", "blackbox", "session", action))
            self.assertEqual(args.input, "-")
            self.assertTrue(args.dry_run)
            self.assertFalse(hasattr(args, "phone"))
            self.assertFalse(hasattr(args, "code"))
        args = parser.parse_args(["blackbox", "session", "login-status", "--login-id", self.login_id])
        self.assertEqual((args.handler, args.login_id), ("read", self.login_id))
        self.assertEqual(parser.parse_args(["blackbox", "session", "doctor"]).handler, "read")

    def test_sms_requires_json_phone_and_wechat_forbids_it(self):
        schema = get_schema("blackbox", "session", "login-start")
        sms = self.document("login-start", method="sms", phone="13800000000")
        self.assertEqual(schema.validate(sms), sms)
        wechat = self.document("login-start", method="wechat")
        self.assertEqual(schema.validate(wechat), wechat)
        for doc in (
            self.document("login-start", method="sms"),
            self.document("login-start", method="sms", phone="+8613800000000"),
            self.document("login-start", method="sms", phone="13800000000 "),
            self.document("login-start", method="sms", phone=13800000000),
            self.document("login-start", method="wechat", phone="13800000000"),
            self.document("login-start", method="automatic"),
            self.document("login-start", method="sms", phone="13800000000", send_sms=True),
        ):
            with self.subTest(doc=doc), self.assertRaises(ValidationError):
                schema.validate(doc)

    def test_code_remains_a_string_and_login_id_is_opaque(self):
        schema = get_schema("blackbox", "session", "login-submit")
        for code in ("0123", "123456", "12345678"):
            doc = self.document("login-submit", login_id=self.login_id, code=code)
            self.assertEqual(schema.validate(doc)["code"], code)
        for code in (123456, True, "123", "123456789", "12a456", " 123456", None):
            with self.subTest(code=code), self.assertRaises(ValidationError):
                schema.validate(self.document("login-submit", login_id=self.login_id, code=code))
        for login_id in ("", "../pending", "A" * 32, "a" * 31, "a" * 33):
            with self.subTest(login_id=login_id), self.assertRaises(ValidationError):
                schema.validate(self.document("login-submit", login_id=login_id, code="123456"))

    def test_renew_has_no_login_inputs_and_forget_requires_local_confirmation(self):
        renew = get_schema("blackbox", "session", "renew")
        self.assertEqual(renew.validate(self.document("renew")), self.document("renew"))
        for field, value in (("phone", "13800000000"), ("code", "123456"), ("cookie", "fixture"), ("token", "fixture"), ("open_browser", True), ("interval", 60)):
            with self.subTest(field=field), self.assertRaises(ValidationError):
                renew.validate(self.document("renew", **{field: value}))
        forget = get_schema("blackbox", "session", "forget")
        forget.validate(self.document("forget", confirm_forget=True))
        for fields in ({}, {"confirm_forget": False}, {"confirm_forget": 1}, {"confirm_forget": True, "remote_logout": True}):
            with self.subTest(fields=fields), self.assertRaises(ValidationError):
                forget.validate(self.document("forget", **fields))

    def test_stdin_dry_run_does_not_construct_provider_or_echo_phone_and_code(self):
        documents = (
            ("login-start", self.document("login-start", method="sms", phone="13800000000")),
            ("login-start", self.document("login-start", method="wechat")),
            ("login-submit", self.document("login-submit", login_id=self.login_id, code="012345")),
            ("renew", self.document("renew")),
            ("forget", self.document("forget", confirm_forget=True)),
        )
        for action, doc in documents:
            with self.subTest(action=action), mock.patch("fupload_cli.cli.Blackbox") as provider, mock.patch("sys.stdin", io.StringIO(json.dumps(doc))), contextlib.redirect_stdout(io.StringIO()) as output:
                status = main(["blackbox", "session", action, "--input", "-", "--dry-run"])
            self.assertEqual(status, 0)
            provider.assert_not_called()
            raw = output.getvalue()
            self.assertNotIn("13800000000", raw)
            self.assertNotIn("012345", raw)
            result = json.loads(raw)
            self.assertTrue(result["dry_run"])
            self.assertTrue(result["data"]["schema_valid"])
            self.assertNotIn("values", result["data"])

    def test_submit_dispatches_one_stdin_document_without_replay(self):
        doc = self.document("login-submit", login_id=self.login_id, code="012345")
        with mock.patch("fupload_cli.cli.Blackbox") as constructor, mock.patch("sys.stdin", io.StringIO(json.dumps(doc))), contextlib.redirect_stdout(io.StringIO()) as output:
            provider = constructor.return_value
            provider.execute_write.return_value = {"status": "authenticated", "login_id": self.login_id}
            status = main(["blackbox", "session", "login-submit", "--input", "-"])
        self.assertEqual(status, 0)
        provider.execute_write.assert_called_once_with("session", "login-submit", doc)
        provider.close.assert_called_once()
        self.assertNotIn("012345", output.getvalue())
        self.assertEqual(json.loads(output.getvalue())["data"]["status"], "authenticated")

    def test_doctor_and_login_status_dispatch_only_explicit_read_steps(self):
        for action, flags in (("doctor", []), ("login-status", ["--login-id", self.login_id])):
            with self.subTest(action=action), mock.patch("fupload_cli.cli.Blackbox") as constructor, contextlib.redirect_stdout(io.StringIO()):
                provider = constructor.return_value
                provider.execute_read.return_value = {"status": "waiting_scan"}
                status = main(["blackbox", "session", action, *flags])
            self.assertEqual(status, 0)
            provider.execute_read.assert_called_once()
            self.assertEqual(provider.execute_read.call_args.args[:2], ("session", action))
            provider.execute_write.assert_not_called()
            provider.close.assert_called_once()

    def test_invalid_json_inputs_do_not_echo_secret_values(self):
        for action, doc in (
            ("login-start", self.document("login-start", method="sms", phone="13800000000 invalid")),
            ("login-submit", self.document("login-submit", login_id=self.login_id, code="012345 invalid")),
        ):
            with self.subTest(action=action), mock.patch("fupload_cli.cli.Blackbox") as provider, mock.patch("sys.stdin", io.StringIO(json.dumps(doc))), contextlib.redirect_stdout(io.StringIO()) as output:
                status = main(["blackbox", "session", action, "--input", "-", "--dry-run"])
            self.assertEqual(status, 2)
            provider.assert_not_called()
            self.assertNotIn("13800000000", output.getvalue())
            self.assertNotIn("012345", output.getvalue())
            self.assertFalse(json.loads(output.getvalue())["success"])


if __name__ == "__main__":
    unittest.main()
