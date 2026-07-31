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

    def test_broker_reuses_one_sidecar_and_preserves_structured_errors(self) -> None:
        counters = {"enter": 0, "exit": 0}
        operations = []

        class FakeSidecar:
            dd_dir = Path("D:/Software/NetEaseDD/100128")
            signature = {"status": "Valid", "publisher": "NetEase"}

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

                self.assertTrue(dd_broker.status(session_id)["running"])
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
        self.assertEqual(record["response_json"]["token"], "[REDACTED]")
        self.assertEqual(record["response_json"]["signed_url"], "[REDACTED]")
        self.assertNotIn("request-secret", repr(record))
        self.assertNotIn("response-secret", repr(record))

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
