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
    def test_publish_post_write_transaction_IO_failure_requires_verification_without_replay(self):
        for binary in (False, True):
            with self.subTest(binary=binary), tempfile.TemporaryDirectory() as temporary:
                archive=Path(temporary)/'demo.zip';write_zip(archive)
                provider=ModUs('fixture');log=Path(temporary)/'transaction.json'
                document={'project_id':200000042,'file_id':9,'path':'custom.zip','transaction_log':str(log)}
                if binary:document['file']=str(archive)
                original=Path.write_text
                def save(path,text,*args,**kwargs):
                    if json.loads(text).get('active_stage')=='release_readback':raise OSError('synthetic disk failure')
                    return original(path,text,*args,**kwargs)
                with mock.patch.object(Path,'write_text',autospec=True,side_effect=save), mock.patch.object(provider,'release_metadata',return_value={}) as metadata, mock.patch.object(provider,'release_signature',return_value='https://upload.modus.test/object'), mock.patch.object(provider,'upload_zip',return_value={'status':'uploaded'}) as upload, mock.patch.object(provider,'_verify_release_download') as readback, mock.patch.object(provider,'options',return_value=[{'key':'wow_builds','value':'{"wow_retail":{"versions":["11.0.0"]}}'}]), self.assertRaises(FuploadError) as failed:
                    provider.publish(document,update=True)
                self.assertTrue(failed.exception.verification_required)
                self.assertEqual(failed.exception.stage,'release_readback')
                self.assertTrue(failed.exception.details['remote_write_attempted'])
                self.assertTrue(failed.exception.details['remote_write_accepted'])
                self.assertFalse(failed.exception.details['automatic_retry'])
                metadata.assert_called_once();self.assertEqual(upload.call_count,int(binary));readback.assert_not_called()

    def test_publish_completion_log_failure_is_not_persisted_as_completed(self):
        with tempfile.TemporaryDirectory() as temporary:
            provider=ModUs('fixture');log=Path(temporary)/'transaction.json';original=Path.write_text
            def save(path,text,*args,**kwargs):
                if json.loads(text).get('completed'):raise OSError('synthetic final log failure')
                return original(path,text,*args,**kwargs)
            with mock.patch.object(Path,'write_text',autospec=True,side_effect=save), mock.patch.object(provider,'release_metadata',return_value={}) as metadata, self.assertRaises(FuploadError) as failed:
                provider.publish({'project_id':200000042,'file_id':9,'version':'new','transaction_log':str(log)},update=True)
            self.assertTrue(failed.exception.verification_required);metadata.assert_called_once()
            saved=json.loads(log.read_text());self.assertNotEqual(saved.get('completed'),True)

    def test_publish_before_write_log_IO_failure_and_business_rejection_remain_known(self):
        for failure_stage in (None,'release_metadata_update'):
            with self.subTest(stage=failure_stage), tempfile.TemporaryDirectory() as temporary:
                provider=ModUs('fixture');original=Path.write_text
                def save(path,text,*args,**kwargs):
                    if json.loads(text).get('active_stage')==failure_stage:raise OSError('synthetic pre-write failure')
                    return original(path,text,*args,**kwargs)
                with mock.patch.object(Path,'write_text',autospec=True,side_effect=save), mock.patch.object(provider,'release_metadata') as metadata, self.assertRaises(FuploadError) as failed:
                    provider.publish({'project_id':200000042,'file_id':9,'version':'new','transaction_log':str(Path(temporary)/'transaction.json')},update=True)
                self.assertFalse(failed.exception.verification_required);metadata.assert_not_called()
        with tempfile.TemporaryDirectory() as temporary:
            provider=ModUs('fixture');rejected=FuploadError('explicit business rejection',kind='platform_error',business_code=500)
            with mock.patch.object(provider,'release_metadata',side_effect=rejected) as metadata, self.assertRaises(FuploadError) as failed:
                provider.publish({'project_id':200000042,'file_id':9,'transaction_log':str(Path(temporary)/'transaction.json')},update=True)
            self.assertIs(failed.exception,rejected);self.assertFalse(failed.exception.verification_required);metadata.assert_called_once()

    def test_release_download_does_not_verify_a_rewritten_http_port_or_noncanonical_URL(self):
        provider=ModUs('fixture');raw=b'synthetic'
        invalid=('http://cdn.modus.cool/custom.zip','https://cdn.modus.cool:80/custom.zip',
                 ' https://cdn.modus.cool/custom.zip','https:custom.zip')
        for path in invalid:
            record={'fileId':9,'path':path,'md5':hashlib.md5(raw).hexdigest(),'zipSize':len(raw)}
            with self.subTest(path=path):
                with mock.patch.object(provider,'release_detail',return_value=record), mock.patch('fupload_cli.modus.urllib.request.build_opener') as opener, mock.patch('fupload_cli.modus.time.sleep'), self.assertRaises(FuploadError) as failed:
                    opener.return_value.open.side_effect=lambda *a,**kw:io.BytesIO(raw)
                    provider._verify_release_download(200000042,9,{'path':path})
                self.assertTrue(failed.exception.verification_required);opener.assert_not_called()
                self.assertEqual(record['path'],path)
        for path in ('custom.zip','https://cdn.modus.cool/custom.zip','https://cdn.modus.cool:443/custom.zip'):
            record={'fileId':9,'path':path,'md5':hashlib.md5(raw).hexdigest(),'zipSize':len(raw)}
            with self.subTest(path=path), mock.patch.object(provider,'release_detail',return_value=record), mock.patch('fupload_cli.modus.urllib.request.build_opener') as opener:
                opener.return_value.open.side_effect=lambda *a,**kw:io.BytesIO(raw)
                self.assertTrue(provider._verify_release_download(200000042,9,{'path':path})['verified'])
            self.assertEqual(opener.return_value.open.call_args.args[0].full_url,path if path.startswith('https://') else 'https://cdn.modus.cool/'+path)

    def test_binary_publish_default_path_matches_official_reserved_object_key(self):
        for update in (False, True):
            with self.subTest(update=update), tempfile.TemporaryDirectory() as temporary:
                archive = Path(temporary) / 'unrelated-local-filename.zip'
                write_zip(archive)
                provider = ModUs('fixture')
                captured = []
                def request(method, path, body=None):
                    if path.endswith('/fileId/200000042'): return {'data': 9}
                    if path.endswith('/upload/signature/200000042/9'): return {'data': {'signedUrl':'https://upload.modus.test/object'}}
                    captured.append(body)
                    return {'data': {'fileId':9}}
                document = {'project_id':200000042,'file':str(archive),'version':'1.0.0','type':'Alpha',
                            'transaction_log':str(Path(temporary)/'transaction.json')}
                if update: document['file_id'] = 9
                with mock.patch.object(provider,'_request',side_effect=request), mock.patch.object(provider,'options',return_value=[{'key':'wow_builds','value':'{"wow_retail":{"versions":["11.0.0"]}}'}]), mock.patch.object(provider,'upload_zip',return_value={'status':'uploaded'}), mock.patch.object(provider,'_verify_release_download',return_value={'verified':True},create=True):
                    provider.publish(document, update=update)
                self.assertEqual(captured[0]['path'], 'modus/wow/addons/200000042/files/9.zip')

    def test_creator_auth_matches_official_bearer_header_without_duplicate_prefix(self):
        cases = ((False, "fixture", "Bearer fixture"), (False, "Bearer fixture", "Bearer fixture"),
                 (False, "bEaReR fixture", "bEaReR fixture"), (True, "fixture", "fixture"))
        for main_session, token, expected in cases:
            with self.subTest(main_session=main_session, token=token):
                provider = ModUs(token, main_session=main_session)
                response = mock.MagicMock()
                response.__enter__.return_value = response
                response.status = 200
                response.read.return_value = b'{"code":200,"data":{}}'
                with mock.patch("fupload_cli.modus.urllib.request.urlopen", return_value=response) as request:
                    provider._request("GET", "system/user/getInfo")
                self.assertEqual(request.call_args.args[0].get_header("Authorization"), expected)

    def test_metadata_only_release_update_preserves_all_supplied_wire_fields_and_null_clear(self):
        with tempfile.TemporaryDirectory() as temporary:
            provider = ModUs("fixture")
            doc = {"project_id": 200000042, "file_id": 9, "md5": "a" * 32, "zip_size": 12, "unzip_size": 24,
                   "changelog": None, "transaction_log": str(Path(temporary) / "transaction.json")}
            with mock.patch.object(provider, "_request", return_value={"code": 200}) as request:
                result = provider.publish(doc, update=True)
            self.assertIsNone(result["upload"])
            self.assertEqual(request.call_args.args[:2], ("POST", "game/data/author/project/file/update"))
            self.assertEqual(request.call_args.args[2], {"projectId": 200000042, "fileId": 9, "md5": "a" * 32,
                                                       "zipSize": 12, "unzipSize": 24, "changelog": "<null>"})

    def test_release_changelog_update_clear_marker_preserves_nonempty_original_text(self):
        provider=ModUs('fixture')
        for value in (None,'',' \r\n','\n<p>Full original HTML</p>\n'):
            with self.subTest(value=value), mock.patch.object(provider,'_request',return_value={'code':200}) as request:
                provider.release_metadata({'project_id':200000042,'file_id':9,'changelog':value},update=True)
            self.assertEqual(request.call_args.args[2]['changelog'], '<null>' if value is None or not value.strip() else value)
        with mock.patch.object(provider,'_request',return_value={'code':200}) as request:
            provider.release_metadata({'project_id':200000042,'file_id':9},update=True)
        self.assertNotIn('changelog',request.call_args.args[2])

    def test_release_zip_rejects_conflicting_supplied_digest_and_sizes_before_metadata(self):
        with tempfile.TemporaryDirectory() as temporary:
            archive = Path(temporary) / "addon.zip"
            write_zip(archive)
            for field, value in (("md5", "0" * 32), ("zip_size", 0), ("unzip_size", 0)):
                with self.subTest(field=field):
                    provider = ModUs("fixture")
                    doc = {"project_id": 200000042, "file_id": 9, "file": str(archive), field: value,
                           "transaction_log": str(Path(temporary) / (field + ".json"))}
                    with mock.patch.object(provider, "_request") as request, self.assertRaises(ValidationError) as failure:
                        provider.publish(doc, update=True)
                    self.assertEqual(failure.exception.details["path"], "$." + field)
                    request.assert_not_called()

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
                "project_id": 200000042,
                "file": str(archive),
                "version": "1.0.0",
                "type": "release",
                "supported_game_versions": [{"gameVersion": "11.0.0", "server": "wow_retail"}],
                "toc_version": "110000",
                "changelog": "first release",
                "path": "Demo-1.0.0.zip",
            }
            validated = schema.validate(document)
            self.assertEqual(validated["project_id"], 200000042)
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
                if path == "game/data/author/project/fileId/200000042":
                    return {"data": {"fileId": 9}}
                if path == "game/data/author/project/upload":
                    return {"data": {"fileId": 9, "status": "pending"}}
                if path == "game/data/author/project/file/upload/signature/200000042/9":
                    return {"data": {"signedUrl": "https://upload.modus.test/signed?token=fixture"}}
                if path == "game/data/author/project/file/detail/9":
                    return {"data": {"fileId":9,"path":"Demo-1.0.0.zip","md5":hashlib.md5(raw).hexdigest(),"zipSize":len(raw)}}
                raise AssertionError("unexpected request: %r" % (method, path))

            _FakeConnection.instances = []
            with mock.patch.object(provider, "_request", side_effect=fake_request), mock.patch(
                "fupload_cli.modus.http.client.HTTPSConnection", _FakeConnection
            ), mock.patch.object(provider, "options", return_value=[{
                "key": "wow_builds", "value": '{"wow_retail":{"versions":["11.0.0"]}}'
            }]), mock.patch('fupload_cli.modus.urllib.request.build_opener') as opener:
                opener.return_value.open.side_effect = lambda *args,**kwargs: io.BytesIO(raw)
                result = provider.publish(
                    {
                        "project_id": 200000042,
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
                ("GET", "game/data/author/project/fileId/200000042"),
                ("POST", "game/data/author/project/upload"),
                ("GET", "game/data/author/project/file/upload/signature/200000042/9"),
                ("GET", "game/data/author/project/file/detail/9"),
            ])
            metadata = requests[1][2]
            self.assertEqual(metadata["projectId"], 200000042)
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
                "file_id", "release_metadata", "signature", "binary_upload", "release_readback",
            ])
            self.assertTrue(result['readback']['verified'])
            download = opener.return_value.open.call_args.args[0]
            self.assertEqual(download.full_url, 'https://cdn.modus.cool/Demo-1.0.0.zip')
            self.assertIsNone(download.get_header('Authorization'))
            transaction = json.loads((Path(directory) / "transaction.json").read_text(encoding="utf-8"))
            self.assertTrue(transaction["completed"])
            self.assertEqual(transaction["stages"], result["transaction"]["stages"])

    def test_release_download_readback_rejects_wrong_ID_without_fetching_CDN(self):
        provider=ModUs('fixture')
        with mock.patch.object(provider,'release_detail',return_value={'fileId':999,'path':'custom.zip','md5':'a'*32,'zipSize':1}) as read, mock.patch('fupload_cli.modus.urllib.request.build_opener') as opener, mock.patch('fupload_cli.modus.time.sleep'), self.assertRaises(FuploadError) as failed:
            provider._verify_release_download(200000042,9,{'path':'custom.zip'})
        self.assertTrue(failed.exception.verification_required)
        self.assertEqual(failed.exception.details['readback_reason'],'identity_mismatch')
        self.assertEqual(read.call_count,4)
        opener.assert_not_called()

    def test_release_download_readback_resamples_only_reads_and_checks_complete_bytes(self):
        provider=ModUs('fixture');raw=b'synthetic-complete-package'
        actual={'fileId':9,'path':'custom.zip','md5':hashlib.md5(raw).hexdigest(),'zipSize':len(raw)}
        with mock.patch.object(provider,'release_detail',side_effect=[{**actual,'fileId':999},actual]) as read, mock.patch('fupload_cli.modus.urllib.request.build_opener') as build, mock.patch('fupload_cli.modus.time.sleep'):
            build.return_value.open.side_effect=lambda *a,**kw:io.BytesIO(raw)
            result=provider._verify_release_download(200000042,9,{'path':'custom.zip','md5':actual['md5'],'zip_size':len(raw)})
        self.assertEqual(result,{'verified':True,'bytes':len(raw),'md5':actual['md5'],'read_attempts':2})
        self.assertEqual(read.call_count,2)
        self.assertEqual(build.return_value.open.call_count,1)
        request=build.return_value.open.call_args.args[0]
        self.assertEqual(request.get_method(),'GET')
        self.assertIsNone(request.get_header('Authorization'));self.assertIsNone(request.get_header('Cookie'))

    def test_explicit_unavailable_path_is_preserved_but_never_reported_as_published(self):
        import urllib.error
        with tempfile.TemporaryDirectory() as temporary:
            archive=Path(temporary)/'demo.zip';raw=write_zip(archive);provider=ModUs('fixture')
            transaction=Path(temporary)/'transaction.json'
            doc={'project_id':200000042,'file_id':9,'file':str(archive),'version':'1.0.0','type':'Alpha','path':'custom.zip','transaction_log':str(transaction)}
            detail={'fileId':9,'path':'custom.zip','md5':hashlib.md5(raw).hexdigest(),'zipSize':len(raw)}
            with mock.patch.object(provider,'release_metadata',return_value={}) as metadata, mock.patch.object(provider,'release_signature',return_value='https://upload.modus.test/object'), mock.patch.object(provider,'upload_zip',return_value={'status':'uploaded'}) as upload, mock.patch.object(provider,'options',return_value=[{'key':'wow_builds','value':'{"wow_retail":{"versions":["11.0.0"]}}'}]), mock.patch.object(provider,'release_detail',return_value=detail), mock.patch('fupload_cli.modus.urllib.request.build_opener') as opener, mock.patch('fupload_cli.modus.time.sleep'), self.assertRaises(FuploadError) as failed:
                opener.return_value.open.side_effect=urllib.error.HTTPError('https://cdn.modus.cool/custom.zip?token=synthetic-private',404,'not found',{},None)
                provider.publish(doc,update=True)
            metadata.assert_called_once();upload.assert_called_once()
            self.assertEqual(metadata.call_args.args[0]['path'],'custom.zip')
            self.assertTrue(failed.exception.verification_required)
            self.assertEqual(failed.exception.http_status,404)
            self.assertEqual(failed.exception.stage,'release_readback')
            self.assertEqual(opener.return_value.open.call_count,4)
            record=json.loads(transaction.read_text())
            self.assertNotIn('completed',record)
            self.assertNotIn('synthetic-private',json.dumps(record))

    def test_metadata_only_explicit_path_requires_download_verification_without_upload(self):
        with tempfile.TemporaryDirectory() as temporary:
            provider=ModUs('fixture')
            with mock.patch.object(provider,'release_metadata',return_value={}) as metadata, mock.patch.object(provider,'_verify_release_download',return_value={'verified':True}) as verify, mock.patch.object(provider,'upload_zip') as upload:
                result=provider.publish({'project_id':200000042,'file_id':9,'path':'custom.zip','transaction_log':str(Path(temporary)/'transaction.json')},update=True)
            self.assertIsNone(result['upload']);upload.assert_not_called();metadata.assert_called_once()
            verify.assert_called_once_with(200000042,9,{'project_id':200000042,'file_id':9,'path':'custom.zip'})
            self.assertTrue(result['readback']['verified'])

    def test_release_download_rejects_partial_corrupt_oversized_and_foreign_package_URLs(self):
        provider=ModUs('fixture');expected=b'expected-package'
        record={'fileId':9,'path':'custom.zip','md5':hashlib.md5(expected).hexdigest(),'zipSize':len(expected)}
        for body in (expected[:-1],b'x'*len(expected),expected+b'extra'):
            with self.subTest(body_length=len(body)), mock.patch.object(provider,'release_detail',return_value=record), mock.patch('fupload_cli.modus.urllib.request.build_opener') as opener, mock.patch('fupload_cli.modus.time.sleep'), self.assertRaises(FuploadError) as failed:
                opener.return_value.open.side_effect=lambda *a,**kw:io.BytesIO(body)
                provider._verify_release_download(200000042,9,{'path':'custom.zip'})
            self.assertTrue(failed.exception.verification_required)
        foreign={**record,'path':'https://example.invalid/custom.zip'}
        with mock.patch.object(provider,'release_detail',return_value=foreign), mock.patch('fupload_cli.modus.urllib.request.build_opener') as opener, mock.patch('fupload_cli.modus.time.sleep'), self.assertRaises(FuploadError) as failed:
            provider._verify_release_download(200000042,9,{'path':foreign['path']})
        opener.assert_not_called();self.assertTrue(failed.exception.verification_required)

    def test_release_download_encodes_custom_Unicode_path_without_rewriting_saved_path(self):
        provider=ModUs('fixture');raw=b'synthetic';path='目录/发布 包.zip'
        detail={'fileId':9,'path':path,'md5':hashlib.md5(raw).hexdigest(),'zipSize':len(raw)}
        with mock.patch.object(provider,'release_detail',return_value=detail), mock.patch('fupload_cli.modus.urllib.request.build_opener') as opener:
            opener.return_value.open.side_effect=lambda *a,**kw:io.BytesIO(raw)
            result=provider._verify_release_download(200000042,9,{'path':path})
        self.assertTrue(result['verified'])
        self.assertEqual(detail['path'],path)
        self.assertEqual(opener.return_value.open.call_args.args[0].full_url,'https://cdn.modus.cool/%E7%9B%AE%E5%BD%95/%E5%8F%91%E5%B8%83%20%E5%8C%85.zip')

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
                    "project_id": 200000042,
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
                    "project_id": 200000042,
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
                    "project_id": 200000042,
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

    def test_creator_release_reads_do_not_require_main_client_login(self):
        for argv in (["modus", "plugin", "versions", "--project-id", "42"],
                     ["modus", "plugin", "get", "--project-id", "42", "--file-id", "9"]):
            with mock.patch("fupload_cli.cli._modus_provider") as provider, contextlib.redirect_stdout(io.StringIO()):
                provider.return_value.execute_read.return_value = {}
                self.assertEqual(main(argv), 0)
                self.assertFalse(provider.call_args.kwargs["main_session"])


if __name__ == "__main__":
    unittest.main()
