from __future__ import annotations

import importlib
import io
import json
import os
import queue
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fupload_cli.dd import DD, Sidecar, _readback
from fupload_cli.errors import FuploadError
import fupload_cli.dd_broker as dd_broker


class DDSessionTests(unittest.TestCase):

    @staticmethod
    def _native_sidecar_module():
        with mock.patch.dict(os.environ, {
            "NETEASE_DD_DIR": "D:/Software/NetEaseDD/100128",
            "FUPLOAD_DD_DEVICE_STATE": "D:/state/sidecar-device.json",
        }):
            return importlib.import_module("fupload_cli.dd_sidecar")

    @staticmethod
    def _persisted_login(method, credential_type, modifier):
        account = SimpleNamespace(
            method=SimpleNamespace(name=method),
            name="private-account@example.invalid",
        )
        credential = SimpleNamespace(
            type=SimpleNamespace(name=credential_type),
            modifier=SimpleNamespace(name=modifier),
            value="private-persisted-token",
        )
        return account, credential

    def test_native_relogin_uses_urs_flow_for_email_credential(self) -> None:
        module = self._native_sidecar_module()
        account, credential = self._persisted_login("urs", "urs_token", "normal")
        urs_flow = mock.Mock(return_value=object())
        mobile_flow = mock.Mock(side_effect=AssertionError("mobile flow must not run"))
        dependencies = [object() for _ in range(4)]

        result = module._create_relogin_flow(
            account, credential, *dependencies, urs_flow, mobile_flow,
        )

        self.assertIs(result, urs_flow.return_value)
        urs_flow.assert_called_once_with(
            dependencies[0], dependencies[1], credential.value, account.name,
        )
        mobile_flow.assert_not_called()

    def test_native_relogin_supports_both_mobile_credential_modifiers(self) -> None:
        module = self._native_sidecar_module()
        for modifier, is_password in (("mobile_password", True), ("mobile_uplink", False)):
            with self.subTest(modifier=modifier):
                account, credential = self._persisted_login(
                    "mobile", "urs_mobile_token", modifier,
                )
                urs_flow = mock.Mock(side_effect=AssertionError("URS flow must not run"))
                mobile_flow = mock.Mock(return_value=object())
                dependencies = [object() for _ in range(4)]

                result = module._create_relogin_flow(
                    account, credential, *dependencies, urs_flow, mobile_flow,
                )

                self.assertIs(result, mobile_flow.return_value)
                mobile_flow.assert_called_once_with(
                    *dependencies, credential.value, is_password, account.name,
                )
                urs_flow.assert_not_called()

    def test_native_relogin_reports_only_safe_credential_kind(self) -> None:
        module = self._native_sidecar_module()
        email = self._persisted_login("urs", "urs_token", "normal")
        mobile_password = self._persisted_login(
            "mobile", "urs_mobile_token", "mobile_password",
        )
        mobile_uplink = self._persisted_login(
            "mobile", "urs_mobile_token", "mobile_uplink",
        )

        self.assertEqual(module._credential_kind(*email), "email")
        self.assertEqual(module._credential_kind(*mobile_password), "mobile")
        self.assertEqual(module._credential_kind(*mobile_uplink), "mobile")

    def test_native_relogin_rejects_unknown_or_conflicting_state_before_flow(self) -> None:
        module = self._native_sidecar_module()
        combinations = (
            ("urs", "urs_mobile_token", "normal"),
            ("mobile", "urs_token", "mobile_password"),
            ("urs", "urs_token", "mobile_password"),
            ("mobile", "urs_mobile_token", "normal"),
            ("private-method", "private-type", "private-modifier"),
        )
        for method, credential_type, modifier in combinations:
            with self.subTest(
                method=method, credential_type=credential_type, modifier=modifier,
            ):
                account, credential = self._persisted_login(method, credential_type, modifier)
                urs_flow = mock.Mock()
                mobile_flow = mock.Mock()

                with self.assertRaisesRegex(RuntimeError, "unsupported credential combination") as raised:
                    module._create_relogin_flow(
                        account, credential, object(), object(), object(), object(),
                        urs_flow, mobile_flow,
                    )

                message = str(raised.exception)
                for private_value in (
                    account.name, credential.value, method, credential_type, modifier,
                ):
                    self.assertNotIn(private_value, message)
                urs_flow.assert_not_called()
                mobile_flow.assert_not_called()

    def test_sidecar_requests_use_encoding_neutral_ascii_json(self) -> None:
        sidecar = Sidecar.__new__(Sidecar)
        sidecar.counter = 0
        sidecar.process = mock.MagicMock()
        sidecar.process.stdin = mock.MagicMock()
        with mock.patch.object(sidecar, "_next_result", return_value={
            "id": 1,
            "ok": True,
            "data": {"name": "中文公告"},
        }):
            result = sidecar.call(
                "request", method="POST", path="/addon/modify",
                payload={"name": "中文公告"},
            )
        wire = sidecar.process.stdin.write.call_args.args[0]
        self.assertTrue(wire.isascii())
        self.assertNotIn("中文公告", wire)
        self.assertEqual(json.loads(wire)["payload"]["name"], "中文公告")
        self.assertEqual(result["name"], "中文公告")

    def test_native_sidecar_results_use_encoding_neutral_ascii_json(self) -> None:
        with mock.patch.dict(os.environ, {
            "NETEASE_DD_DIR": "D:/Software/NetEaseDD/100128",
            "FUPLOAD_DD_DEVICE_STATE": "D:/state/sidecar-device.json",
        }):
            module = importlib.import_module("fupload_cli.dd_sidecar")
        output = io.StringIO()
        with mock.patch.object(module.sys, "stdout", output):
            module.output({"ok": True, "data": {"name": "中文公告"}})
        wire = output.getvalue()
        self.assertTrue(wire.isascii())
        self.assertNotIn("中文公告", wire)
        payload = json.loads(wire.removeprefix("FUPLOAD_RESULT "))
        self.assertEqual(payload["data"]["name"], "中文公告")

    def test_sidecar_non_utf8_output_fails_without_replacement_text(self) -> None:
        sidecar = Sidecar.__new__(Sidecar)
        sidecar.responses = queue.Queue()
        sidecar.process = mock.MagicMock()
        sidecar.process.stdout = io.TextIOWrapper(io.BytesIO(bytes([0xff])), encoding="utf-8", errors="strict")
        sidecar._read_results()
        with self.assertRaises(FuploadError) as raised:
            sidecar._next_result(timeout=0)
        self.assertEqual(str(raised.exception), "DD sidecar returned non-UTF-8 output")

    def test_native_failure_keeps_message_and_business_code(self) -> None:
        class UiApiError(Exception):
            code = 4312

            def __str__(self) -> str:
                return "WA category is invalid"

        with mock.patch.dict(os.environ, {
            "NETEASE_DD_DIR": "D:/Software/NetEaseDD/100128",
            "FUPLOAD_DD_DEVICE_STATE": "D:/state/sidecar-device.json",
        }):
            sidecar = importlib.import_module("fupload_cli.dd_sidecar")
        error = sidecar.failure_from_exception(UiApiError(), "mutation").as_dict()
        self.assertEqual(error["business_code"], 4312)
        self.assertIn("WA category is invalid", error["message"])
    @unittest.skipUnless(os.name == "nt", "Windows process liveness contract")
    def test_broker_process_liveness_accepts_current_process(self) -> None:
        self.assertTrue(dd_broker._pid_running(os.getpid()))

    def test_live_operations_require_session_before_broker_dispatch(self) -> None:
        provider = DD()
        with self.assertRaises(FuploadError) as write_error:
            provider.execute_write("plugin", "create", {})
        with self.assertRaises(FuploadError) as read_error:
            provider.execute_read("plugin", "list", SimpleNamespace())
        self.assertEqual(write_error.exception.kind, "session_required")
        self.assertEqual(read_error.exception.kind, "session_required")

    def test_doctor_only_discovers_installation_and_local_state(self) -> None:
        sidecar = mock.Mock(side_effect=AssertionError("doctor must not create Sidecar"))
        module = SimpleNamespace(
            Sidecar=sidecar,
            discover_dd_info=lambda: (
                Path("D:/Software/NetEaseDD/100128"),
                {"status": "Valid", "publisher": "NetEase"},
            ),
        )
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(
            dd_broker, "_dd_module", return_value=module
        ), mock.patch.object(
            dd_broker, "_state_dir", return_value=Path(directory)
        ), mock.patch.object(
            dd_broker, "running_dd_processes", return_value=[]
        ), mock.patch.object(
            dd_broker, "_load_live_state", return_value=None
        ):
            result = dd_broker.doctor()
        self.assertFalse(result["authenticated"])
        self.assertFalse(result["login_performed"])
        self.assertFalse(result["broker_running"])
        sidecar.assert_not_called()

    def test_start_requires_confirmation_before_closing_running_gui(self) -> None:
        process = {
            "pid": 42,
            "dd_dir": "D:/Software/NetEaseDD/100128",
            "windows": [100],
            "signature": {"status": "Valid", "publisher": "NetEase"},
        }
        with mock.patch.object(
            dd_broker, "_load_live_state", return_value=None
        ), mock.patch.object(
            dd_broker, "running_dd_processes", return_value=[process]
        ), mock.patch.object(
            dd_broker, "close_verified_gui"
        ) as close, mock.patch.object(dd_broker.subprocess, "Popen") as popen:
            with self.assertRaises(FuploadError) as raised:
                dd_broker.start(False)
        self.assertEqual(raised.exception.kind, "gui_close_confirmation_required")
        close.assert_not_called()
        popen.assert_not_called()

    def test_broker_disconnect_after_write_send_requires_readback(self) -> None:
        state = {"session_id": "session", "auth_key": "auth", "port": 1234}

        class BrokenConnection:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def settimeout(self, _timeout):
                pass

            def sendall(self, _data):
                pass

            def recv(self, _size):
                raise ConnectionResetError("closed")

        with mock.patch.object(dd_broker, "_load_live_state", return_value=state), mock.patch.object(
            dd_broker.socket, "create_connection", return_value=BrokenConnection()
        ):
            with self.assertRaises(FuploadError) as write_error:
                dd_broker.execute("session", "write", "plugin", "create", {})
            with self.assertRaises(FuploadError) as read_error:
                dd_broker.execute("session", "read", "plugin", "list", {})
        self.assertEqual(write_error.exception.stage, "session")
        self.assertTrue(write_error.exception.verification_required)
        self.assertFalse(read_error.exception.verification_required)

    def test_broker_stop_retries_transient_state_read_lock(self) -> None:
        locked = FuploadError(
            "DD broker state is unreadable",
            kind="session_error",
            stage="session",
        )
        locked.__cause__ = PermissionError("locked")
        with mock.patch.object(
            dd_broker, "_send", return_value={"running": False}
        ), mock.patch.object(
            dd_broker,
            "_load_live_state",
            side_effect=[locked, {"session_id": "session"}, None],
        ), mock.patch.object(dd_broker.time, "sleep"):
            stopped = dd_broker.stop("session")
        self.assertTrue(stopped["cleanup_complete"])

    def test_broker_cleanup_retries_transient_state_file_locks(self) -> None:
        locked = FuploadError(
            "DD broker state is unreadable",
            kind="session_error",
            stage="session",
        )
        locked.__cause__ = PermissionError("locked")
        state_path = mock.Mock()
        state_path.unlink.side_effect = [PermissionError("locked"), None]
        with mock.patch.object(dd_broker, "_read_json", side_effect=[
            locked,
            {"session_id": "session"},
            {"session_id": "session"},
        ]) as read, mock.patch.object(dd_broker.time, "sleep"):
            removed = dd_broker._remove_session_state(state_path, "session")
        self.assertTrue(removed)
        self.assertEqual(read.call_count, 3)
        self.assertEqual(state_path.unlink.call_count, 2)

    def test_broker_reuses_one_sidecar_and_preserves_structured_errors(self) -> None:
        counters = {"enter": 0, "exit": 0}
        operations = []

        class FakeSidecar:
            dd_dir = Path("D:/Software/NetEaseDD/100128")
            signature = {"status": "Valid", "publisher": "NetEase"}
            credential_kind = "email"

            def __enter__(self):
                counters["enter"] += 1
                return self

            def __exit__(self, *_args):
                counters["exit"] += 1

        class FakeDD:
            def execute_write_on(self, sidecar, resource, action, payload):
                operations.append(("write", id(sidecar), resource, action, payload))
                if resource == "error":
                    raise FuploadError(
                        "explicit object rejection",
                        kind="platform_error",
                        stage="object_put",
                        endpoint="object-store-put",
                        http_status=403,
                        verification_required=False,
                    )
                return {"written": resource}

            def execute_read_on(self, sidecar, resource, action, args):
                operations.append(("read", id(sidecar), resource, action, vars(args)))
                return {"read": resource}

        module = SimpleNamespace(Sidecar=FakeSidecar, DD=FakeDD)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            dd_broker._atomic_json(
                root / dd_broker.STARTUP_NAME,
                {"startup_id": "startup", "auth_key": "auth"},
            )
            with mock.patch.object(
                dd_broker, "_state_dir", return_value=root
            ), mock.patch.object(
                dd_broker, "_dd_module", return_value=module
            ), mock.patch.object(dd_broker, "_pid_running", return_value=True):
                thread = threading.Thread(target=dd_broker._serve, args=("startup",), daemon=True)
                thread.start()
                state_path = root / dd_broker.STATE_NAME
                deadline = time.time() + 5
                while time.time() < deadline and not state_path.exists():
                    time.sleep(0.01)
                self.assertTrue(state_path.exists())
                state = dd_broker._read_json(state_path)
                session_id = state["session_id"]

                broker_status = dd_broker.status(session_id)
                self.assertTrue(broker_status["running"])
                self.assertEqual(broker_status["credential_kind"], "email")
                self.assertEqual(broker_status["broker_count"], 1)
                self.assertEqual(broker_status["sidecar_count"], 1)
                self.assertEqual(broker_status["native_login_count"], 1)
                self.assertEqual(
                    dd_broker.execute(session_id, "read", "plugin", "list", {"page": 1}),
                    {"read": "plugin"},
                )
                for index in range(6):
                    self.assertEqual(
                        dd_broker.execute(
                            session_id, "write", "plugin", "create", {"name": "Plugin %d" % index}
                        ),
                        {"written": "plugin"},
                    )
                with self.assertRaises(FuploadError) as raised:
                    dd_broker.execute(session_id, "write", "error", "create", {})
                self.assertEqual(raised.exception.stage, "object_put")
                self.assertEqual(raised.exception.http_status, 403)
                self.assertFalse(raised.exception.verification_required)

                stopped = dd_broker.stop(session_id)
                self.assertTrue(stopped["cleanup_complete"])
                thread.join(timeout=5)

        self.assertFalse(thread.is_alive())
        self.assertEqual(counters, {"enter": 1, "exit": 1})
        self.assertEqual(len({operation[1] for operation in operations}), 1)
        self.assertEqual([operation[0] for operation in operations], ["read"] + ["write"] * 7)

    def test_upload_wire_names_ignore_special_local_basenames(self) -> None:
        sidecar = Sidecar.__new__(Sidecar)
        sidecar.call = mock.Mock(return_value={"d_url": "https://cdn.example/object"})
        names = ["space name.zip", "中文.zip", "a(b)+c#d%.zip"]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in names:
                path = root / name
                path.write_bytes(b"zip")
                sidecar.upload(str(path), "addon", file_name="addon.zip")
                meta = sidecar.call.call_args.kwargs["meta"]
                self.assertEqual(meta, {
                    "file_type": "a19-ui-res",
                    "business_id": "addon",
                    "mime_type": "application/x-zip-compressed",
                    "file_name": "addon.zip",
                })

            wa = root / "WA 材质(+).zip"
            wa.write_bytes(b"zip")
            sidecar.upload(str(wa), "wa", file_name="wa_materials.zip")
            self.assertEqual(sidecar.call.call_args.kwargs["meta"]["file_name"], "wa_materials.zip")

            image = root / "展示 图+#%.png"
            image.write_bytes(b"png")
            sidecar.upload(str(image), "addon", file_name="", media=True)
            plugin_media = sidecar.call.call_args.kwargs["meta"]
            self.assertEqual(plugin_media["file_name"], "")
            self.assertEqual(plugin_media["business_id"], "img")
            self.assertEqual(plugin_media["mime_type"], "image/png")

            sidecar.upload(str(image), "share", media=True)
            config_media = sidecar.call.call_args.kwargs["meta"]
            self.assertNotIn("file_name", config_media)
            sidecar.upload(str(image), "wa", media=True)
            self.assertNotIn("file_name", sidecar.call.call_args.kwargs["meta"])

    def test_read_only_post_and_write_readback_have_distinct_uncertainty(self) -> None:
        sidecar = Sidecar.__new__(Sidecar)
        sidecar.counter = 0
        sidecar.process = mock.MagicMock()
        sidecar.process.stdin = mock.MagicMock()
        with mock.patch.object(sidecar, "_next_result", return_value={
            "id": 1,
            "ok": False,
            "error": {"message": "request timed out", "stage": "dependency_get"},
        }):
            with self.assertRaises(FuploadError) as dependency_error:
                sidecar.post_read("/addon/addon_list", {})
        self.assertEqual(dependency_error.exception.stage, "dependency_get")
        self.assertFalse(dependency_error.exception.verification_required)

        original = FuploadError(
            "read unavailable", stage="dependency_get", endpoint="/addon/detail_v2", http_status=503
        )
        with self.assertRaises(FuploadError) as readback_error:
            _readback(lambda: (_ for _ in ()).throw(original), "/addon/detail_v2")
        self.assertEqual(readback_error.exception.stage, "readback")
        self.assertEqual(readback_error.exception.http_status, 503)
        self.assertTrue(readback_error.exception.verification_required)

    def test_native_failure_uncertainty_depends_on_completed_stage(self) -> None:
        with mock.patch.dict(os.environ, {
            "NETEASE_DD_DIR": "D:/Software/NetEaseDD/100128",
            "FUPLOAD_DD_DEVICE_STATE": "D:/state/sidecar-device.json",
        }):
            module = importlib.import_module("fupload_cli.dd_sidecar")

        forbidden = urllib.error.HTTPError("https://object.invalid", 403, "Forbidden", {}, None)
        rejected = module.failure_from_exception(forbidden, "object_put")
        self.assertEqual(rejected.http_status, 403)
        self.assertFalse(rejected.verification_required)
        self.assertFalse(module.failure_from_exception(TimeoutError(), "upload_authorize").verification_required)
        self.assertTrue(module.failure_from_exception(TimeoutError(), "object_put").verification_required)
        self.assertTrue(module.failure_from_exception(RuntimeError(), "mutation").verification_required)

    def test_native_http_rejection_status_matrix_is_deterministic(self) -> None:
        with mock.patch.dict(os.environ, {
            "NETEASE_DD_DIR": "D:/Software/NetEaseDD/100128",
            "FUPLOAD_DD_DEVICE_STATE": "D:/state/sidecar-device.json",
        }):
            module = importlib.import_module("fupload_cli.dd_sidecar")
        for status in (400, 401, 403, 404, 422, 500):
            body = json.dumps({"code": status * 10, "message": "field rejected", "field": "version"}).encode("utf-8")
            error = urllib.error.HTTPError(
                "https://uiapi.w.163.com/addon/modify", status, "rejected", {}, io.BytesIO(body)
            )
            with self.subTest(status=status):
                failure = module.failure_from_exception(error, "mutation")
                self.assertEqual(failure.http_status, status)
                self.assertEqual(failure.business_code, status * 10)
                self.assertEqual(failure.details["server_field"], "version")
                self.assertEqual(failure.verification_required, status >= 500)

    def test_native_http_error_body_keeps_business_code_and_validation_hint(self) -> None:
        with mock.patch.dict(os.environ, {
            "NETEASE_DD_DIR": "D:/Software/NetEaseDD/100128",
            "FUPLOAD_DD_DEVICE_STATE": "D:/state/sidecar-device.json",
        }):
            module = importlib.import_module("fupload_cli.dd_sidecar")
        body = json.dumps({"code": 42201, "message": "invalid field", "field": "version"}).encode("utf-8")
        error = urllib.error.HTTPError("https://object.invalid", 422, "invalid", {}, io.BytesIO(body))
        failure = module.failure_from_exception(error, "object_put")
        self.assertEqual(failure.http_status, 422)
        self.assertEqual(failure.business_code, 42201)
        self.assertEqual(failure.details["server_field"], "version")
        self.assertFalse(failure.verification_required)

    def test_native_explicit_http_422_is_rejected_without_verification_required(self) -> None:
        with mock.patch.dict(os.environ, {
            "NETEASE_DD_DIR": "D:/Software/NetEaseDD/100128",
            "FUPLOAD_DD_DEVICE_STATE": "D:/state/sidecar-device.json",
        }):
            module = importlib.import_module("fupload_cli.dd_sidecar")
        error = module.failure_from_exception(
            RuntimeError("请求失败 HTTP 422: UNPROCESSABLE ENTITY"), "mutation",
            {"status": 422, "body": '{"detail":[{"loc":["body","version"],"msg":"invalid"}]}'},
        )
        self.assertEqual(error.http_status, 422)
        self.assertFalse(error.verification_required)
        self.assertEqual(error.details["server_detail"][0]["loc"], "['body', 'version']")

    def test_native_response_probe_captures_rejected_post_without_changing_response(self) -> None:
        with mock.patch.dict(os.environ, {
            "NETEASE_DD_DIR": "D:/Software/NetEaseDD/100128",
            "FUPLOAD_DD_DEVICE_STATE": "D:/state/sidecar-device.json",
        }):
            module = importlib.import_module("fupload_cli.dd_sidecar")

        response = SimpleNamespace(status_code=422, text='{"message":"invalid version"}')
        client = SimpleNamespace(_session=SimpleNamespace(post=lambda *_args, **_kwargs: response))
        module.install_response_probe(client)
        actual = client._session.post("/addon/modify", json_data={})
        self.assertIs(actual, response)
        self.assertEqual(client._fupload_last_response_error, {
            "status": 422,
            "body": '{"message":"invalid version"}',
            "body_bytes": 29,
            "body_truncated": False,
        })
        client._fupload_restore_response_probe()

    def test_native_response_probe_captures_http_error_read_and_restores_opener(self) -> None:
        with mock.patch.dict(os.environ, {
            "NETEASE_DD_DIR": "D:/Software/NetEaseDD/100128",
            "FUPLOAD_DD_DEVICE_STATE": "D:/state/sidecar-device.json",
        }):
            module = importlib.import_module("fupload_cli.dd_sidecar")

        body = b'{"code":4312,"field":"version"}'
        error = urllib.error.HTTPError("https://object.invalid", 422, "invalid", {}, io.BytesIO(body))
        original_open = urllib.request.OpenerDirector.open
        client = SimpleNamespace(_session=SimpleNamespace())
        with mock.patch.object(urllib.request.OpenerDirector, "open", side_effect=error):
            module.install_response_probe(client)
            installed_open = urllib.request.OpenerDirector.open
            with self.assertRaises(urllib.error.HTTPError) as raised:
                urllib.request.OpenerDirector().open("https://object.invalid")
            self.assertEqual(raised.exception.read(), body)
            self.assertEqual(client._fupload_last_response_error["status"], 422)
            self.assertEqual(client._fupload_last_response_error["body"], body.decode("utf-8"))
            client._fupload_restore_response_probe()
            self.assertIsNot(urllib.request.OpenerDirector.open, installed_open)
        self.assertIs(urllib.request.OpenerDirector.open, original_open)

    def test_native_validation_details_redact_json_credentials(self) -> None:
        with mock.patch.dict(os.environ, {
            "NETEASE_DD_DIR": "D:/Software/NetEaseDD/100128",
            "FUPLOAD_DD_DEVICE_STATE": "D:/state/sidecar-device.json",
        }):
            module = importlib.import_module("fupload_cli.dd_sidecar")
        details = module._validation_details({
            "body": '{"message":"token: secret-value is invalid"}',
        })
        self.assertNotIn("secret-value", repr(details))

    def test_native_error_log_preserves_diagnostics_and_redacts_values(self) -> None:
        with mock.patch.dict(os.environ, {
            "NETEASE_DD_DIR": "D:/Software/NetEaseDD/100128",
            "FUPLOAD_DD_DEVICE_STATE": "D:/state/sidecar-device.json",
        }):
            module = importlib.import_module("fupload_cli.dd_sidecar")
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(module, "DD_DIR", directory):
            failure = module.SidecarFailure(
                "invalid version", "mutation", http_status=422, business_code=4312,
                details={"server_field": "version"},
            )
            path = module.write_error_log(
                failure,
                {
                    "action": "request", "method": "POST", "path": "/addon/modify",
                    "payload": {"version": "1.3.6", "token": "request-secret"},
                },
                {"status": 422, "body": json.dumps({
                    "code": 4312,
                    "message": "invalid version",
                    "token": "response-secret",
                    "signed_url": "https://object.invalid/?X-Amz-Signature=secret",
                })},
            )
            record = json.loads(Path(path).read_text(encoding="utf-8").strip())
        self.assertTrue(path.endswith(os.path.join("Fupload", "logs", Path(path).name)))
        self.assertEqual(record["http_status"], 422)
        self.assertEqual(record["business_code"], 4312)
        self.assertEqual(record["request_fields"], ["token", "version"])
        self.assertEqual(record["request_json"]["version"], "1.3.6")
        self.assertEqual(record["request_json"]["token"], "[REDACTED]")
        self.assertEqual(record["request_shape"]["fields"]["version"]["type"], "string")
        self.assertEqual(record["request_shape"]["fields"]["token"]["type"], "string")
        self.assertEqual(record["response_json"]["token"], "[REDACTED]")
        self.assertEqual(record["response_json"]["signed_url"], "[REDACTED]")
        self.assertNotIn("request-secret", repr(record))
        self.assertNotIn("response-secret", repr(record))

    def test_native_error_log_summarizes_raw_wa_content_in_request_and_response(self) -> None:
        with mock.patch.dict(os.environ, {
            "NETEASE_DD_DIR": "D:/Software/NetEaseDD/100128",
            "FUPLOAD_DD_DEVICE_STATE": "D:/state/sidecar-device.json",
        }):
            module = importlib.import_module("fupload_cli.dd_sidecar")
        raw = "!WA:2!private-payload"
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(module, "DD_DIR", directory):
            path = module.write_error_log(
                module.SidecarFailure("invalid content", "mutation", http_status=422),
                {
                    "action": "request", "method": "POST", "path": "/wa/modify",
                    "payload": {"sn": "wa-sn", "content": raw, "version": "2"},
                },
                payload={"code": 42201, "field": "content", "content": raw},
            )
            record = json.loads(Path(path).read_text(encoding="utf-8").strip())
        self.assertEqual(record["request_fields"], ["content", "sn", "version"])
        self.assertTrue(record["request_json"]["content"]["redacted"])
        self.assertTrue(record["request_json"]["sn"]["redacted"])
        self.assertEqual(record["request_json"]["version"], "2")
        self.assertEqual(record["request_shape"]["fields"]["content"]["type"], "string")
        self.assertTrue(record["response_json"]["content"]["redacted"])
        self.assertEqual(record["response_json"]["field"], "content")
        self.assertNotIn(raw, repr(record))

    def test_native_error_log_summarizes_config_backup_groups_but_keeps_field_hints(self) -> None:
        with mock.patch.dict(os.environ, {
            "NETEASE_DD_DIR": "D:/Software/NetEaseDD/100128",
            "FUPLOAD_DD_DEVICE_STATE": "D:/state/sidecar-device.json",
        }):
            module = importlib.import_module("fupload_cli.dd_sidecar")
        request = {
            "share_sn": "config-sn",
            "known_addon": {"items": [{"addon_id": 1, "name": "private-addon"}]},
            "wtf": {"accounts": [{"name": "private-account"}]},
            "retail_ui_config": {"edit_mode": {"account": [{"import_string": "private-import"}]}},
        }
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(module, "DD_DIR", directory):
            path = module.write_error_log(
                module.SidecarFailure("invalid group", "mutation", http_status=422),
                {
                    "action": "request", "method": "POST", "path": "/share/modify",
                    "payload": request,
                },
                payload={"code": 42202, "field": "known_addon", "known_addon": request["known_addon"]},
            )
            record = json.loads(Path(path).read_text(encoding="utf-8").strip())
        self.assertEqual(record["response_json"]["field"], "known_addon")
        for name in ("known_addon", "wtf", "retail_ui_config"):
            self.assertEqual(record["request_shape"]["fields"][name]["type"], "object")
            self.assertTrue(record["request_json"][name]["redacted"])
        self.assertTrue(record["response_json"]["known_addon"]["redacted"])
        self.assertNotIn("private-addon", repr(record))
        self.assertNotIn("private-account", repr(record))
        self.assertNotIn("private-import", repr(record))

    def test_native_error_log_keeps_safe_plugin_diagnostics_and_redacts_private_values(self) -> None:
        with mock.patch.dict(os.environ, {
            "NETEASE_DD_DIR": "D:/Software/NetEaseDD/100128",
            "FUPLOAD_DD_DEVICE_STATE": "D:/state/sidecar-device.json",
        }):
            module = importlib.import_module("fupload_cli.dd_sidecar")
        request = {
            "sn": "private-sn", "name": "private-name", "description": "private-description",
            "html_desc": "<p>private-html</p>", "channel_id": "private-channel",
            "game_type": 10001, "version": "1.3.6", "game_versions": ["12.0.0"],
            "scope": "public", "primary_category_id": 1002, "need_buy": False,
            "associated_acts": [{
                "sn": "private-related", "name": "private-related-name", "act_type": "addon",
            }],
        }
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(module, "DD_DIR", directory):
            path = module.write_error_log(
                module.SidecarFailure("invalid plugin", "mutation", http_status=422),
                {"action": "request", "method": "POST", "path": "/addon/modify", "payload": request},
                payload={"code": 42201, "field": "description", "description": "private-description"},
            )
            record = json.loads(Path(path).read_text(encoding="utf-8").strip())
        self.assertEqual(record["response_json"]["field"], "description")
        self.assertTrue(record["response_json"]["description"]["redacted"])
        logged = record["request_json"]
        self.assertEqual(logged["game_type"], 10001)
        self.assertEqual(logged["version"], "1.3.6")
        self.assertEqual(logged["game_versions"], ["12.0.0"])
        self.assertEqual(logged["scope"], "public")
        self.assertEqual(logged["primary_category_id"], 1002)
        self.assertIs(logged["need_buy"], False)
        self.assertEqual(logged["associated_acts"][0]["act_type"], "addon")
        for name in ("sn", "name", "description", "html_desc", "channel_id"):
            self.assertTrue(logged[name]["redacted"])
        self.assertTrue(logged["associated_acts"][0]["sn"]["redacted"])
        self.assertTrue(logged["associated_acts"][0]["name"]["redacted"])
        for value in (
            "private-sn", "private-name", "private-description", "private-html",
            "private-channel", "private-related",
        ):
            self.assertNotIn(value, repr(record))

    def test_native_log_text_redacts_unlabelled_jwt_and_wa_payload(self) -> None:
        with mock.patch.dict(os.environ, {
            "NETEASE_DD_DIR": "D:/Software/NetEaseDD/100128",
            "FUPLOAD_DD_DEVICE_STATE": "D:/state/sidecar-device.json",
        }):
            module = importlib.import_module("fupload_cli.dd_sidecar")
        jwt = "eyJabcdefghijk.abcdefghijk.abcdefghijk"
        raw = "!WA:2!private-payload"
        sanitized = module.safe_exception_message("values %s %s" % (jwt, raw))
        self.assertNotIn(jwt, sanitized)
        self.assertNotIn(raw, sanitized)

    def test_native_error_log_bounds_multibyte_response_by_utf8_bytes(self) -> None:
        with mock.patch.dict(os.environ, {
            "NETEASE_DD_DIR": "D:/Software/NetEaseDD/100128",
            "FUPLOAD_DD_DEVICE_STATE": "D:/state/sidecar-device.json",
        }):
            module = importlib.import_module("fupload_cli.dd_sidecar")
        body = "错" * (module._MAX_LOG_BODY // 2)
        fields = module._response_log_content({
            "body": body,
            "body_bytes": len(body.encode("utf-8")),
            "body_truncated": True,
        })
        self.assertTrue(fields["response_truncated"])
        self.assertEqual(fields["response_bytes"], len(body.encode("utf-8")))
        self.assertLessEqual(len(fields["response_body"].encode("utf-8")), module._MAX_LOG_BODY)

    def test_native_truncated_text_redacts_device_and_client_credentials(self) -> None:
        with mock.patch.dict(os.environ, {
            "NETEASE_DD_DIR": "D:/Software/NetEaseDD/100128",
            "FUPLOAD_DD_DEVICE_STATE": "D:/state/sidecar-device.json",
        }):
            module = importlib.import_module("fupload_cli.dd_sidecar")
        body = (
            'clientNo: client-secret client_id=client-id-secret '
            'device_proof: device-secret signature=signature-secret token: token-secret'
        )
        fields = module._response_log_content({
            "body": body,
            "body_bytes": len(body.encode("utf-8")),
            "body_truncated": True,
        })
        self.assertNotIn("client-secret", fields["response_body"])
        self.assertNotIn("client-id-secret", fields["response_body"])
        self.assertNotIn("device-secret", fields["response_body"])
        self.assertNotIn("signature-secret", fields["response_body"])
        self.assertNotIn("token-secret", fields["response_body"])

    def test_native_upload_error_log_uses_sanitized_stage_endpoint(self) -> None:
        with mock.patch.dict(os.environ, {
            "NETEASE_DD_DIR": "D:/Software/NetEaseDD/100128",
            "FUPLOAD_DD_DEVICE_STATE": "D:/state/sidecar-device.json",
        }):
            module = importlib.import_module("fupload_cli.dd_sidecar")
        command = {"action": "upload", "meta": {"business_id": "addon"}}
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(module, "DD_DIR", directory):
            authorize_path = module.write_error_log(
                module.SidecarFailure("rejected", "upload_authorize", http_status=422), command,
            )
            put_path = module.write_error_log(
                module.SidecarFailure("rejected", "object_put", http_status=403), command,
            )
            records = [json.loads(line) for line in Path(put_path).read_text(encoding="utf-8").splitlines()]
        self.assertEqual(authorize_path, put_path)
        self.assertEqual(records[-2]["endpoint"], "/file/upload")
        self.assertEqual(records[-1]["endpoint"], "object-store-put")

    def test_native_failure_preserves_falsy_business_code(self) -> None:
        with mock.patch.dict(os.environ, {
            "NETEASE_DD_DIR": "D:/Software/NetEaseDD/100128",
            "FUPLOAD_DD_DEVICE_STATE": "D:/state/sidecar-device.json",
        }):
            module = importlib.import_module("fupload_cli.dd_sidecar")

        class NativeFailure(Exception):
            code = 0
            error_code = 4312

        self.assertEqual(module.failure_from_exception(NativeFailure("failed"), "mutation").business_code, 0)

    def test_native_business_rejection_keeps_status_from_parsed_response(self) -> None:
        with mock.patch.dict(os.environ, {
            "NETEASE_DD_DIR": "D:/Software/NetEaseDD/100128",
            "FUPLOAD_DD_DEVICE_STATE": "D:/state/sidecar-device.json",
        }):
            module = importlib.import_module("fupload_cli.dd_sidecar")
        client = SimpleNamespace(
            _fupload_last_response_error=None,
            post=lambda *_args, **_kwargs: {
                "code": 42201,
                "status_code": 422,
                "message": "invalid field",
                "field": "version",
            },
        )
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(module, "DD_DIR", directory):
            with self.assertRaises(module.SidecarFailure) as raised:
                module.run_command((None, None, None, None, client), {
                    "action": "request", "method": "POST", "path": "/addon/modify",
                    "payload": {"version": "1.3.6"},
                })
            record = json.loads(Path(raised.exception.details["log_path"]).read_text(encoding="utf-8").strip())
        self.assertEqual(raised.exception.http_status, 422)
        self.assertEqual(record["http_status"], 422)
        self.assertEqual(record["business_code"], 42201)

    def test_native_wa_parser_uses_official_bridge_and_nested_result(self) -> None:
        with mock.patch.dict(os.environ, {
            "NETEASE_DD_DIR": "D:/Software/NetEaseDD/100128",
            "FUPLOAD_DD_DEVICE_STATE": "D:/state/sidecar-device.json",
        }):
            module = importlib.import_module("fupload_cli.dd_sidecar")

        class NativeResult:
            def toJson(self):
                return json.dumps({"code": 200, "result": {"uid": "wa-uid", "id": "wa-id"}})

        interface = mock.MagicMock()
        interface.parseWa.return_value = NativeResult()
        container = mock.MagicMock()
        container.get_instance.return_value = interface
        result = module.parse_native_wa((None, container, None, None, None), "!WA:2!content")
        interface.parseWa.assert_called_once_with({"waStr": "!WA:2!content"})
        self.assertEqual(result, {"parse_wa_uid": "wa-uid", "parse_wa_id": "wa-id"})

    def test_native_business_error_is_logged_and_returns_log_path(self) -> None:
        with mock.patch.dict(os.environ, {
            "NETEASE_DD_DIR": "D:/Software/NetEaseDD/100128",
            "FUPLOAD_DD_DEVICE_STATE": "D:/state/sidecar-device.json",
        }):
            module = importlib.import_module("fupload_cli.dd_sidecar")
        client = SimpleNamespace(
            _fupload_last_response_error=None,
            post=lambda *_args, **_kwargs: {"code": 4312, "msg": "invalid version", "field": "version"},
        )
        session = (None, None, None, None, client)
        with mock.patch.object(module, "write_error_log", return_value="D:/DD/Fupload/logs/error.jsonl") as logged:
            with self.assertRaises(module.SidecarFailure) as raised:
                module.run_command(session, {
                    "action": "request", "method": "POST", "path": "/addon/modify",
                    "payload": {"sn": "target", "version": "1.3.6"},
                })
        self.assertEqual(raised.exception.business_code, 4312)
        self.assertFalse(raised.exception.verification_required)
        self.assertEqual(raised.exception.details["log_path"], "D:/DD/Fupload/logs/error.jsonl")
        self.assertEqual(logged.call_args.args[3]["field"], "version")

    def test_native_get_retries_one_exact_invalid_signature_rejection(self) -> None:
        module = self._native_sidecar_module()
        client = SimpleNamespace(
            _fupload_last_response_error=None,
            get=mock.Mock(side_effect=[
                {"code": 409, "msg": "签名无效"},
                {"code": 0, "result": [{"game_version": "12.1.0"}]},
            ]),
        )

        result = module.run_command((None, None, None, None, client), {
            "action": "request", "method": "GET", "path": "/game_versions/list",
            "payload": {"game_type": 10001},
        })

        self.assertEqual(result["code"], 0)
        self.assertEqual(client.get.call_count, 2)

    def test_native_post_never_retries_invalid_signature_rejection(self) -> None:
        module = self._native_sidecar_module()
        client = SimpleNamespace(
            _fupload_last_response_error=None,
            post=mock.Mock(return_value={"code": 409, "msg": "签名无效"}),
        )
        with mock.patch.object(module, "write_error_log", return_value="error.jsonl"):
            with self.assertRaises(module.SidecarFailure):
                module.run_command((None, None, None, None, client), {
                    "action": "request", "method": "POST", "path": "/share/create",
                    "payload": {"title": "temporary"},
                })
        client.post.assert_called_once()

    def test_native_get_retries_invalid_signature_only_once(self) -> None:
        module = self._native_sidecar_module()
        client = SimpleNamespace(
            _fupload_last_response_error=None,
            get=mock.Mock(return_value={"code": 409, "msg": "签名无效"}),
        )
        with mock.patch.object(module, "write_error_log", return_value="error.jsonl"):
            with self.assertRaises(module.SidecarFailure):
                module.run_command((None, None, None, None, client), {
                    "action": "request", "method": "GET", "path": "/game_versions/list",
                    "payload": {"game_type": 10001},
                })
        self.assertEqual(client.get.call_count, 2)

    def test_native_get_does_not_retry_other_409_rejections(self) -> None:
        module = self._native_sidecar_module()
        client = SimpleNamespace(
            _fupload_last_response_error=None,
            get=mock.Mock(return_value={"code": 409, "msg": "other conflict"}),
        )
        with mock.patch.object(module, "write_error_log", return_value="error.jsonl"):
            with self.assertRaises(module.SidecarFailure):
                module.run_command((None, None, None, None, client), {
                    "action": "request", "method": "GET", "path": "/game_versions/list",
                    "payload": {"game_type": 10001},
                })
        client.get.assert_called_once()

    def test_native_rejected_post_writes_sanitized_request_and_response_to_log_path(self) -> None:
        with mock.patch.dict(os.environ, {
            "NETEASE_DD_DIR": "D:/Software/NetEaseDD/100128",
            "FUPLOAD_DD_DEVICE_STATE": "D:/state/sidecar-device.json",
        }):
            module = importlib.import_module("fupload_cli.dd_sidecar")
        client = SimpleNamespace(
            _fupload_last_response_error=None,
            post=lambda *_args, **_kwargs: {
                "code": 42201,
                "message": "invalid version",
                "field": "version",
            },
        )
        session = (None, None, None, None, client)
        command = {
            "action": "request",
            "method": "POST",
            "path": "/addon/modify",
            "payload": {"sn": "target", "version": "1.3.6"},
        }
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(module, "DD_DIR", directory):
            with self.assertRaises(module.SidecarFailure) as raised:
                module.run_command(session, command)
            log_path = raised.exception.details["log_path"]
            record = json.loads(Path(log_path).read_text(encoding="utf-8").strip())
        self.assertEqual(record["endpoint"], "/addon/modify")
        self.assertEqual(record["stage"], "mutation")
        self.assertEqual(record["http_status"], None)
        self.assertEqual(record["business_code"], 42201)
        self.assertTrue(record["request_json"]["sn"]["redacted"])
        self.assertEqual(record["request_json"]["version"], "1.3.6")
        self.assertEqual(record["request_shape"]["fields"]["version"]["type"], "string")
        self.assertEqual(record["request_shape"]["fields"]["version"]["bytes"], 5)
        self.assertEqual(record["response_json"]["field"], "version")
        self.assertEqual(record["validation"]["server_field"], "version")
        self.assertEqual(raised.exception.details["server_field"], "version")

    def test_native_upload_authorization_rejection_logs_request_response_and_field(self) -> None:
        with mock.patch.dict(os.environ, {
            "NETEASE_DD_DIR": "D:/Software/NetEaseDD/100128",
            "FUPLOAD_DD_DEVICE_STATE": "D:/state/sidecar-device.json",
        }):
            module = importlib.import_module("fupload_cli.dd_sidecar")
        client = SimpleNamespace(
            _fupload_last_response_error=None,
            get=lambda *_args, **_kwargs: {
                "code": 42202,
                "message": "invalid mime",
                "field": "mime_type",
            },
        )
        session = (None, None, None, None, client)
        command = {
            "action": "upload",
            "file": "D:/missing.zip",
            "meta": {
                "file_type": "a19-ui-res",
                "business_id": "addon",
                "mime_type": "application/x-zip-compressed",
            },
        }
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(module, "DD_DIR", directory):
            with self.assertRaises(module.SidecarFailure) as raised:
                module.run_command(session, command)
            record = json.loads(Path(raised.exception.details["log_path"]).read_text(encoding="utf-8").strip())
        self.assertEqual(record["endpoint"], "/file/upload")
        self.assertEqual(record["business_code"], 42202)
        self.assertEqual(record["request_json"]["upload_authorize"]["business_id"], "addon")
        self.assertEqual(
            record["request_json"]["upload_authorize"]["mime_type"],
            "application/x-zip-compressed",
        )
        self.assertEqual(record["request_shape"]["fields"]["upload_authorize"]["type"], "object")
        self.assertEqual(record["response_json"]["field"], "mime_type")
        self.assertEqual(record["validation"]["server_field"], "mime_type")

    def test_native_object_put_http_error_logs_response_and_wire_descriptor(self) -> None:
        with mock.patch.dict(os.environ, {
            "NETEASE_DD_DIR": "D:/Software/NetEaseDD/100128",
            "FUPLOAD_DD_DEVICE_STATE": "D:/state/sidecar-device.json",
        }):
            module = importlib.import_module("fupload_cli.dd_sidecar")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "payload.zip"
            path.write_bytes(b"zip-payload")
            body = b'{"code":40301,"message":"signature rejected","field":"signature"}'
            client = SimpleNamespace(
                _fupload_last_response_error=None,
                get=lambda *_args, **_kwargs: {
                    "code": 0,
                    "result": {
                        "url": "https://object.invalid/signed",
                        "d_url": "https://cdn.invalid/object",
                        "maxSize": 1000,
                    },
                },
            )
            error = urllib.error.HTTPError(
                "https://object.invalid/signed", 403, "Forbidden", {}, io.BytesIO(body)
            )
            with mock.patch.object(module, "DD_DIR", directory), mock.patch.object(
                module.urllib.request, "urlopen", side_effect=error
            ):
                with self.assertRaises(module.SidecarFailure) as raised:
                    module.run_command((None, None, None, None, client), {
                        "action": "upload",
                        "file": str(path),
                        "meta": {
                            "file_type": "a19-ui-res",
                            "business_id": "addon",
                            "mime_type": "application/x-zip-compressed",
                            "file_name": "addon.zip",
                        },
                    })
                record = json.loads(Path(raised.exception.details["log_path"]).read_text(encoding="utf-8").strip())
        self.assertEqual(record["endpoint"], "object-store-put")
        self.assertEqual(record["http_status"], 403)
        self.assertEqual(record["request_json"]["object_put"]["body_bytes"], len(b"zip-payload"))
        self.assertEqual(record["request_json"]["object_put"]["headers"]["X-Amz-Acl"], "public-read")
        self.assertEqual(record["request_shape"]["fields"]["object_put"]["type"], "object")
        self.assertEqual(
            record["request_shape"]["fields"]["object_put"]["fields"]["body_bytes"]["type"],
            "int",
        )
        self.assertEqual(record["response_json"]["field"], "signature")
        self.assertEqual(record["validation"]["server_field"], "signature")

    def test_native_object_put_preserves_signed_url_headers_and_literal_status(self) -> None:
        with mock.patch.dict(os.environ, {
            "NETEASE_DD_DIR": "D:/Software/NetEaseDD/100128",
            "FUPLOAD_DD_DEVICE_STATE": "D:/state/sidecar-device.json",
        }):
            module = importlib.import_module("fupload_cli.dd_sidecar")

        signed_url = "https://object.invalid/key+part?X-Amz-Credential=a%2Fb&X-Amz-Signature=c%23d%25e"

        class Client:
            def __init__(self, maximum=100):
                self.maximum = maximum

            def get(self, path, meta):
                self.path = path
                self.meta = meta
                return {
                    "code": 0,
                    "result": {"url": signed_url, "d_url": "https://cdn.invalid/object", "maxSize": self.maximum},
                }

        class Response:
            def __init__(self, status):
                self.status = status

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

        command = {
            "action": "upload",
            "meta": {
                "file_type": "a19-ui-res",
                "business_id": "addon",
                "file_name": "addon.zip",
                "mime_type": "application/x-zip-compressed",
            },
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "a b+中#%.zip"
            path.write_bytes(b"payload")
            command["file"] = str(path)
            session = (None, None, None, None, Client())
            with mock.patch.object(module.urllib.request, "urlopen", return_value=Response(200)) as opened:
                result = module.run_command(session, command)
            request = opened.call_args.args[0]
            self.assertEqual(request.full_url, signed_url)
            self.assertEqual(request.get_header("Content-type"), "application/x-zip-compressed")
            self.assertEqual(request.get_header("X-amz-acl"), "public-read")
            self.assertEqual(result["size"], len(b"payload"))

            with mock.patch.object(module.urllib.request, "urlopen", return_value=Response(201)):
                with self.assertRaises(module.SidecarFailure) as wrong_status:
                    module.run_command(session, command)
            self.assertEqual(wrong_status.exception.stage, "object_put")
            self.assertEqual(wrong_status.exception.http_status, 201)
            self.assertFalse(wrong_status.exception.verification_required)

            too_small = (None, None, None, None, Client(maximum=1))
            with mock.patch.object(module.urllib.request, "urlopen") as unopened:
                with self.assertRaises(module.SidecarFailure) as oversized:
                    module.run_command(too_small, command)
            unopened.assert_not_called()
            self.assertEqual(oversized.exception.stage, "upload_authorize")

            leak = urllib.error.URLError("X-Amz-Signature=secret")
            redacted = module.failure_from_exception(leak, "object_put")
            self.assertNotIn("secret", str(redacted))


if __name__ == "__main__":
    unittest.main()
