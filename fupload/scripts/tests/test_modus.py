from __future__ import annotations

import contextlib
import hashlib
import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fupload_cli.cli import main
from fupload_cli.errors import FuploadError, ValidationError
from fupload_cli.modus import ModUs, _dependency_query_wire
from fupload_cli.schema import get_schema


def write_zip(path: Path) -> bytes:
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("Demo/Demo.toc", "## Interface: 110000\n## Version: 1.0.0\n")
        archive.writestr("Demo/init.lua", "print('demo')\n")
    return path.read_bytes()


class _UploadResponse:
    status = 200

    def read(self, _limit=None):
        return b""


class _FakeConnection:
    instances = []

    def __init__(self, host, port=None, **kwargs):
        self.host = host
        self.port = port
        self.kwargs = kwargs
        self.calls = []
        self.body = bytearray()
        self.__class__.instances.append(self)

    def putrequest(self, *args):
        self.calls.append(("putrequest", args))

    def putheader(self, *args):
        self.calls.append(("putheader", args))

    def endheaders(self):
        self.calls.append(("endheaders", ()))

    def send(self, data):
        self.body.extend(data)

    def getresponse(self):
        self.calls.append(("getresponse", ()))
        return _UploadResponse()

    def close(self):
        self.calls.append(("close", ()))


class ModusTests(unittest.TestCase):
    def test_dependency_query_uses_creator_name_and_project_id_shapes(self):
        self.assertEqual(_dependency_query_wire(" Details! "), {"name": "Details!"})
        self.assertEqual(_dependency_query_wire(42), {"projectIds": [42]})
        self.assertEqual(_dependency_query_wire([42, 43]), {"projectIds": [42, 43]})
        self.assertEqual(
            _dependency_query_wire('{"projectIds":[42,43]}'),
            {"projectIds": [42, 43]},
        )
        self.assertEqual(
            _dependency_query_wire({"project_ids": [42]}),
            {"projectIds": [42]},
        )

    def test_dependency_query_rejects_ambiguous_or_invalid_payloads_before_request(self):
        invalid = (
            None,
            "",
            "{invalid",
            2147483648,
            {"name": "x", "projectIds": [42]},
            {"unknown": 42},
            {"name": " "},
            {"projectIds": []},
            {"projectIds": [0]},
            {"projectIds": [True]},
            {"projectIds": [2147483648]},
        )
        for value in invalid:
            with self.subTest(value=value), self.assertRaises(ValidationError):
                _dependency_query_wire(value)

    def test_project_dependencies_posts_exact_creator_request_body(self):
        provider = ModUs("token-fixture")
        with mock.patch.object(
            provider,
            "_request",
            return_value={"data": [{"projectId": 42, "name": "Details!"}]},
        ) as request:
            result = provider.project_dependencies({"name": "Details!"})
        request.assert_called_once_with(
            "POST",
            "game/data/author/project/dependency/query",
            {"name": "Details!"},
        )
        self.assertEqual(result, [{"projectId": 42, "name": "Details!"}])

    def test_upload_schema_accepts_zip_and_rejects_unknown_or_invalid_fields(self):
        schema = get_schema("modus", "plugin", "upload")
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / "demo.zip"
            write_zip(archive)
            document = {
                "schema": schema.name,
                "project_id": 42,
                "file": str(archive),
                "version": "1.0.0",
                "type": "release",
                "supported_game_versions": [{"gameVersion": "11.0.0", "server": "wow_retail"}],
                "toc_version": "110000",
                "changelog": "first release",
                "path": "Demo-1.0.0.zip",
            }
            validated = schema.validate(document)
            self.assertEqual(validated["project_id"], 42)
            self.assertEqual(validated["file"], str(archive))
            with self.assertRaises(ValidationError):
                schema.validate({**document, "unexpected": True})
            invalid = Path(directory) / "invalid.zip"
            invalid.write_bytes(b"not a zip")
            with self.assertRaises(ValidationError) as raised:
                schema.validate({**document, "file": str(invalid)})
            self.assertEqual(raised.exception.details["path"], "$.file")

    def test_doctor_does_not_return_token_or_ciphertext(self):
        with tempfile.TemporaryDirectory() as directory:
            token_path = Path(directory) / "token.dat"
            token_path.write_bytes(b"encrypted-fixture")
            secret = "modus-bearer-secret-fixture"
            provider = ModUs("placeholder", token_path=token_path)
            with mock.patch("fupload_cli.modus.TOKEN_PATH", token_path), mock.patch(
                "fupload_cli.modus._dpapi_unprotect", return_value=secret.encode("utf-8")
            ), mock.patch.object(
                provider, "user_info", return_value={"id": 1}
            ):
                result = provider.doctor()
            wire = json.dumps(result)
            self.assertTrue(result["token_present"])
            self.assertTrue(result["token_decrypted"])
            self.assertTrue(result["token_nonempty"])
            self.assertTrue(result["api_ready"])
            self.assertEqual(set(result), {"token_present", "token_decrypted", "token_nonempty", "api_ready"})
            self.assertNotIn(secret, wire)
            self.assertNotIn("encrypted-fixture", wire)

    def test_doctor_distinguishes_local_and_api_readiness(self):
        with tempfile.TemporaryDirectory() as directory:
            token_path = Path(directory) / "token.dat"
            token_path.write_bytes(b"encrypted-fixture")
            provider = ModUs("placeholder", token_path=token_path)
            with mock.patch(
                "fupload_cli.modus._dpapi_unprotect", return_value=b"local-token"
            ), mock.patch.object(
                provider, "user_info", side_effect=FuploadError("API unavailable")
            ):
                result = provider.doctor()
            self.assertEqual(result, {
                "token_present": True,
                "token_decrypted": True,
                "token_nonempty": True,
                "api_ready": False,
            })

    def test_doctor_reports_missing_and_decryption_failure_without_api_call(self):
        with tempfile.TemporaryDirectory() as directory:
            token_path = Path(directory) / "token.dat"
            provider = ModUs("placeholder", token_path=token_path)
            with mock.patch.object(provider, "user_info") as user_info:
                self.assertEqual(provider.doctor(), {
                    "token_present": False,
                    "token_decrypted": False,
                    "token_nonempty": False,
                    "api_ready": False,
                })
                user_info.assert_not_called()

            token_path.write_bytes(b"invalid-ciphertext")
            with mock.patch(
                "fupload_cli.modus._dpapi_unprotect",
                side_effect=FuploadError("decryption failed"),
            ), mock.patch.object(provider, "user_info") as user_info:
                self.assertEqual(provider.doctor(), {
                    "token_present": True,
                    "token_decrypted": False,
                    "token_nonempty": False,
                    "api_ready": False,
                })
                user_info.assert_not_called()

            with mock.patch(
                "fupload_cli.modus._dpapi_unprotect", return_value=b"  "
            ), mock.patch.object(provider, "user_info") as user_info:
                self.assertEqual(provider.doctor(), {
                    "token_present": True,
                    "token_decrypted": True,
                    "token_nonempty": False,
                    "api_ready": False,
                })
                user_info.assert_not_called()

    def test_doctor_cli_does_not_require_eager_authentication(self):
        with tempfile.TemporaryDirectory() as directory:
            token_path = Path(directory) / "token.dat"
            stdout = io.StringIO()
            with mock.patch("fupload_cli.modus.TOKEN_PATH", token_path), contextlib.redirect_stdout(stdout):
                code = main(["modus", "session", "doctor"])
            payload = json.loads(stdout.getvalue())
            self.assertEqual(code, 0)
            self.assertEqual(payload["data"], {
                "api_ready": False,
                "token_decrypted": False,
                "token_nonempty": False,
                "token_present": False,
            })

    def test_publish_sequences_metadata_signature_and_binary_upload(self):
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / "demo.zip"
            raw = write_zip(archive)
            provider = ModUs("token-fixture", base_url="https://app.modus.cool/api/")
            requests = []

            def fake_request(method, path, body=None):
                requests.append((method, path, body))
                if path == "game/data/author/project/fileId/42":
                    return {"data": {"fileId": 9}}
                if path == "game/data/author/project/upload":
                    return {"data": {"fileId": 9, "status": "pending"}}
                if path == "game/data/author/project/file/upload/signature/42/9":
                    return {"data": {"signedUrl": "https://upload.modus.test/signed?token=fixture"}}
                raise AssertionError("unexpected request: %r" % (method, path))

            _FakeConnection.instances = []
            with mock.patch.object(provider, "_request", side_effect=fake_request), mock.patch(
                "fupload_cli.modus.http.client.HTTPSConnection", _FakeConnection
            ):
                result = provider.publish(
                    {
                        "project_id": 42,
                        "file": str(archive),
                        "version": "1.0.0",
                        "type": "release",
                        "supported_game_versions": [{"gameVersion": "11.0.0", "server": "wow_retail"}],
                        "toc_version": "110000",
                        "changelog": "first release",
                        "path": "Demo-1.0.0.zip",
                        "transaction_log": str(Path(directory) / "transaction.json"),
                    }
                )

            self.assertEqual([item[:2] for item in requests], [
                ("GET", "game/data/author/project/fileId/42"),
                ("POST", "game/data/author/project/upload"),
                ("GET", "game/data/author/project/file/upload/signature/42/9"),
            ])
            metadata = requests[1][2]
            self.assertEqual(metadata["projectId"], 42)
            self.assertNotIn("fileId", metadata)
            self.assertEqual(metadata["supportedGameVersionsReqs"], [{"gameVersion": "11.0.0", "server": "wow_retail"}])
            self.assertEqual(metadata["md5"], hashlib.md5(raw).hexdigest())
            self.assertEqual(metadata["zipSize"], len(raw))
            self.assertEqual(metadata["path"], "Demo-1.0.0.zip")
            connection = _FakeConnection.instances[0]
            self.assertEqual(bytes(connection.body), raw)
            self.assertEqual(result["upload"]["bytes"], len(raw))
            self.assertTrue(result["transaction"]["completed"])
            self.assertEqual(result["transaction"]["stages"], [
                "file_id", "release_metadata", "signature", "binary_upload",
            ])
            transaction = json.loads((Path(directory) / "transaction.json").read_text(encoding="utf-8"))
            self.assertTrue(transaction["completed"])
            self.assertEqual(transaction["stages"], result["transaction"]["stages"])

    def test_publish_records_file_id_and_zip_preflight_failures(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / "invalid.zip"
            archive.write_bytes(b"not a zip")
            transaction_path = root / "transaction.json"
            provider = ModUs("token-fixture")

            with mock.patch.object(
                provider,
                "release_file_id",
                side_effect=FuploadError("allocation failed", endpoint="https://app.modus.cool/api/fileId", stage="file_id"),
            ), self.assertRaises(FuploadError):
                provider.publish({
                    "project_id": 42,
                    "file": str(archive),
                    "transaction_log": str(transaction_path),
                })
            transaction = json.loads(transaction_path.read_text(encoding="utf-8"))
            self.assertEqual(transaction["file_id"], None)
            self.assertEqual(transaction["stages"], ["file_id"])
            self.assertEqual(transaction["failed_stage"], "file_id")
            self.assertEqual(transaction["active_stage"], "file_id")
            self.assertTrue(transaction["retained_archive"])

            with mock.patch.object(provider, "release_file_id", return_value=9), self.assertRaises(ValidationError) as raised:
                provider.publish({
                    "project_id": 42,
                    "file": str(archive),
                    "transaction_log": str(transaction_path),
                })
            self.assertEqual(raised.exception.stage, "zip_preflight")
            transaction = json.loads(transaction_path.read_text(encoding="utf-8"))
            self.assertEqual(transaction["file_id"], 9)
            self.assertEqual(transaction["stages"], ["file_id"])
            self.assertEqual(transaction["failed_stage"], "zip_preflight")
            self.assertEqual(transaction["active_stage"], "zip_preflight")
            self.assertTrue(transaction["retained_archive"])

    def test_binary_upload_http_error_has_safe_endpoint_and_response_summary(self):
        class FailedResponse:
            status = 403

            def read(self, _limit=None):
                return b'{"token":"secret-value","message":"denied"}'

        class FailedConnection(_FakeConnection):
            def getresponse(self):
                return FailedResponse()

        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / "demo.zip"
            write_zip(archive)
            provider = ModUs("token-fixture")
            signed_url = "https://user-info-secret@upload.modus.test/signed/path?X-Amz-Signature=secret&token=also-secret"
            with mock.patch("fupload_cli.modus.http.client.HTTPSConnection", FailedConnection), self.assertRaises(FuploadError) as raised:
                provider.upload_zip(signed_url, str(archive))
            error = raised.exception.as_dict()
            self.assertEqual(error["stage"], "binary_upload")
            self.assertEqual(error["endpoint"], "https://upload.modus.test/signed/path")
            self.assertEqual(error["http_status"], 403)
            self.assertIn("response_summary", error["details"])
            self.assertNotIn("secret-value", json.dumps(error))
            self.assertNotIn("also-secret", json.dumps(error))
            self.assertNotIn("user-info-secret", json.dumps(error))

    def test_binary_upload_network_error_has_safe_endpoint_and_response_summary(self):
        class FailedConnection(_FakeConnection):
            def __init__(self, *_args, **_kwargs):
                raise OSError("connection reset token=network-secret")

        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / "demo.zip"
            write_zip(archive)
            provider = ModUs("token-fixture")
            signed_url = "https://upload.modus.test/signed/path?token=query-secret"
            with mock.patch("fupload_cli.modus.http.client.HTTPSConnection", FailedConnection), self.assertRaises(FuploadError) as raised:
                provider.upload_zip(signed_url, str(archive))
            error = raised.exception.as_dict()
            self.assertEqual(error["stage"], "binary_upload")
            self.assertEqual(error["endpoint"], "https://upload.modus.test/signed/path")
            self.assertIn("response_summary", error["details"])
            self.assertNotIn("network-secret", json.dumps(error))
            self.assertNotIn("query-secret", json.dumps(error))

    def test_cli_plugin_upload_dry_run_does_not_construct_provider(self):
        from fupload_cli.cli import main

        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / "demo.zip"
            write_zip(archive)
            input_path = Path(directory) / "upload.json"
            input_path.write_text(
                json.dumps({
                    "schema": "fupload.v1.modus.plugin.upload",
                    "project_id": 42,
                    "file": str(archive),
                    "version": "1.0.0",
                    "type": "release",
                    "supported_game_versions": [{"gameVersion": "11.0.0", "server": "wow_retail"}],
                    "toc_version": "110000",
                    "changelog": "first release",
                    "path": "Demo-1.0.0.zip",
                }),
                encoding="utf-8",
            )
            output = io.StringIO()
            with mock.patch("fupload_cli.cli._modus_provider") as provider, contextlib.redirect_stdout(output):
                code = main(["modus", "plugin", "upload", "--input", str(input_path), "--dry-run"])
            self.assertEqual(code, 0, output.getvalue())
            self.assertTrue(json.loads(output.getvalue())["dry_run"])
            provider.assert_not_called()


if __name__ == "__main__":
    unittest.main()
