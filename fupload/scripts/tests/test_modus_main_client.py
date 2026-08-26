from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fupload_cli.cli import build_parser
from fupload_cli.modus import ModUs, load_main_session
from fupload_cli.schema import get_schema
from fupload_cli.errors import FuploadError, ValidationError


class ModusMainClientTests(unittest.TestCase):
    def test_main_doctor_reuses_main_session_without_creator_token_file(self):
        provider = ModUs(main_session=True, authenticate=False)
        with mock.patch("fupload_cli.modus.load_main_session", return_value={
            "token": "MAIN-TOKEN", "device_id": "MAIN-DEVICE",
        }), mock.patch.object(provider, "user_info", return_value={"id": 1}) as user_info:
            result = provider.doctor()
        self.assertEqual(result, {
            "token_present": True,
            "token_decrypted": True,
            "token_nonempty": True,
            "api_ready": True,
        })
        user_info.assert_called_once_with()
        self.assertEqual(provider.token, "")
        self.assertIsNone(provider.device_id)

    def test_media_upload_uses_main_client_multipart_contract(self):
        provider = ModUs("TOKEN", main_session=True, device_id="DEVICE")
        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory) / "cover.webp"
            image.write_bytes(b"RIFF-fixture-WEBP")
            response = {
                "code": 200,
                "data": {
                    "cosStoreKey": "modus/assets/cover.webp",
                    "cosStoreUrl": "https://cdn.invalid/modus/assets/cover.webp",
                },
            }
            with mock.patch("fupload_cli.modus.multipart_request", return_value=response) as upload:
                result = provider.image_upload(str(image))

        self.assertEqual(result["key"], "modus/assets/cover.webp")
        self.assertEqual(result["reference"], result["key"])
        self.assertEqual(result["bytes"], len(b"RIFF-fixture-WEBP"))
        self.assertEqual(len(result["sha256"]), 64)
        self.assertEqual(upload.call_args.args[0], "https://app.modus.cool/api/game/data/file/upload/file/image")
        self.assertEqual(upload.call_args.args[1], str(image))
        self.assertEqual(upload.call_args.kwargs["file_field"], "file")
        self.assertEqual(upload.call_args.kwargs["headers"], {
            "Accept": "application/json", "Authorization": "TOKEN", "X-Device-Id": "DEVICE",
        })

    def test_media_upload_accepts_official_response_aliases_and_rejects_business_failure(self):
        provider = ModUs("TOKEN", main_session=True)
        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory) / "cover.png"
            image.write_bytes(b"png")
            with mock.patch("fupload_cli.modus.multipart_request", return_value={
                "data": {"downloadUrl": "https://cdn.invalid/path/cover.png"},
            }):
                result = provider.image_upload(str(image))
            self.assertEqual(result["key"], "path/cover.png")
            with mock.patch("fupload_cli.modus.multipart_request", return_value={"code": 500, "msg": "bad image"}):
                with self.assertRaisesRegex(FuploadError, "bad image"):
                    provider.image_upload(str(image))

    def test_media_upload_schema_and_cli_route_are_registered(self):
        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory) / "cover.webp"
            image.write_bytes(b"RIFF-fixture-WEBP")
            schema = get_schema("modus", "media", "upload")
            self.assertEqual(schema.validate({"schema": schema.name, "file": str(image)})["file"], str(image))
        args = build_parser().parse_args(["modus", "media", "upload", "--input", "input.json", "--dry-run"])
        self.assertEqual((args.platform, args.resource, args.action), ("modus", "media", "upload"))

    def test_config_list_cli_envelope_keeps_build_in_body_and_header(self):
        args = build_parser().parse_args(["modus", "config", "list", "--build", "0", "--page-size", "20"])
        provider = ModUs("TOKEN", main_session=True, device_id="DEVICE")
        with mock.patch.object(provider, "_request", return_value={"data": {}}) as request:
            provider.execute_read("config", "list", args)
        body = request.call_args.args[2]
        self.assertEqual(body["server"], 0)
        self.assertEqual(request.call_args.kwargs["headers"]["X-Server-Type"], "0")
        self.assertEqual(body["platform"], 0)

    def test_main_list_tag_filters_use_arrays(self):
        provider = ModUs("TOKEN", main_session=True, device_id="DEVICE")
        with mock.patch.object(provider, "_request", return_value={"data": {}}) as request:
            provider.share_list({"tags": "1, 2"}, server_type=3)
        self.assertEqual(request.call_args.args[2]["tags"], ["1", "2"])
        with mock.patch.object(provider, "_request", return_value={"data": {}}) as request:
            provider.import_list({"tags": "3"}, server_type=4)
        self.assertEqual(request.call_args.args[2]["tags"], ["3"])

    @staticmethod
    def _share_document(**overrides):
        document = {
            "addons_id": "9,11", "backup_id": 11,
            "content": "<p>full rendered body with details</p>", "content_text": "full rendered body with details",
            "image_url": "https://cdn.invalid/cover.webp", "is_paid": 0, "is_public": 1,
            "price": 0, "share_type": 0, "tags": "1,2", "title": "A full title",
            "exclude_wtf": 1, "account_name": "", "role_name": "", "required_tier_id": None,
            "sub_type": 0,
        }
        document.update(overrides)
        return document

    @staticmethod
    def _import_document(**overrides):
        document = {
            "code_text": "SAMPLE", "content": "<p>string article body with details</p>", "addons_id": "7,8",
            "content_text": "string article body with details", "file_path": "", "image_url": "https://cdn.invalid/a.webp",
            "is_paid": 0, "is_public": 1, "price": 0, "share_type": 0,
            "support_addon": "Addon", "tags": "2", "title": "A string title",
            "version": "1.0", "sub_type": 0,
        }
        document.update(overrides)
        return document

    def test_share_schema_covers_full_client_payload_and_exclude_state(self):
        schema = get_schema("modus", "config", "create")
        document = {"schema": schema.name, "addons_id": "9", "backup_id": 11,
                    "content": "<p>full rendered body with details</p>", "content_text": "full rendered body with details",
                    "image_url": "https://cdn.invalid/cover.webp", "is_paid": 0, "is_public": 1,
                    "price": 0, "share_type": 0, "tags": "1,2", "title": "A full title",
                    "exclude_wtf": 1, "account_name": "", "role_name": "", "required_tier_id": None,
                    "sub_type": 0}
        self.assertEqual(schema.validate(document)["backup_id"], 11)
        with self.assertRaises(ValidationError):
            schema.validate({**document, "exclude_wtf": 1, "account_name": "Account"})
        with self.assertRaises(ValidationError):
            schema.validate({**document, "exclude_wtf": 0, "account_name": ""})
        schema.validate({**document, "exclude_wtf": 0, "account_name": "Account"})
        schema.validate({**document, "exclude_wtf": 0, "account_name": "Account", "role_name": "Role"})
        self.assertEqual(schema.validate({**document, "addons_id": ""})["addons_id"], "")
        for required_field in (
            "addons_id", "backup_id", "content", "content_text", "image_url",
            "tags", "title", "exclude_wtf",
        ):
            with self.subTest(required_field=required_field):
                with self.assertRaises(ValidationError):
                    schema.validate({key: value for key, value in document.items() if key != required_field})

    def test_string_schema_covers_version_and_subscription_fields(self):
        schema = get_schema("modus", "wa", "create")
        document = {"schema": schema.name, "code_text": "SAMPLE", "content": "<p>string article body with details</p>",
                    "addons_id": "7", "content_text": "string article body with details", "file_path": "", "image_url": "https://cdn.invalid/a.webp",
                    "is_paid": 0, "is_public": 1, "price": 0, "share_type": 0, "support_addon": "Addon",
                    "tags": "2", "title": "A string title", "version": "1.0", "sub_type": 0}
        self.assertEqual(schema.validate(document)["version"], "1.0")
        schema.validate({**document, "sub_type": 1, "required_tier_id": None})
        schema.validate({key: value for key, value in {**document, "sub_type": 1}.items() if key != "required_tier_id"})

    def test_main_client_ui_field_limits_are_enforced(self):
        for resource, document in (("config", self._share_document()), ("wa", self._import_document())):
            schema = get_schema("modus", resource, "create")
            document["schema"] = schema.name
            schema.validate(document)
            for field, invalid in (
                ("title", "short"),
                ("content_text", "twenty or fewer"),
                ("tags", "1,2,3,4"),
                ("tags", "1,,2"),
            ):
                with self.subTest(resource=resource, field=field, invalid=invalid):
                    with self.assertRaises(ValidationError):
                        schema.validate({**document, field: invalid})
            for overrides in (
                {"tags": "1,1"},
                {"is_paid": 1},
                {"price": 1},
                {"share_type": 1},
                {"platform": 1, "synchronization_type": 3},
                {"platform": 3, "synchronization_type": 1},
                {"platform": 3},
                {"synchronization_type": 3},
            ):
                with self.subTest(resource=resource, overrides=overrides):
                    with self.assertRaises(ValidationError):
                        schema.validate({**document, **overrides})
        config_schema = get_schema("modus", "config", "create")
        self.assertEqual(
            config_schema.validate({**self._share_document(addons_id=""), "schema": config_schema.name})["addons_id"],
            "",
        )
        with self.assertRaises(ValidationError):
            config_schema.validate({**self._share_document(addons_id=7), "schema": config_schema.name})
        wa_schema = get_schema("modus", "wa", "create")
        with self.assertRaises(ValidationError):
            wa_schema.validate({**self._import_document(file_path="unexpected"), "schema": wa_schema.name})
        for required_field in (
            "code_text", "content", "addons_id", "content_text", "image_url",
            "support_addon", "tags", "title", "version",
        ):
            with self.subTest(required_field=required_field):
                with self.assertRaises(ValidationError):
                    schema.validate({key: value for key, value in document.items() if key != required_field})

    def test_subscription_type_enum_and_optional_tier_states(self):
        for resource, document in (
            ("config", self._share_document()),
            ("wa", self._import_document()),
        ):
            schema = get_schema("modus", resource, "create")
            document["schema"] = schema.name
            for sub_type in (0, 1):
                with self.subTest(resource=resource, sub_type=sub_type):
                    self.assertEqual(
                        schema.validate({**document, "sub_type": sub_type})["sub_type"],
                        sub_type,
                    )
            for invalid in (-1, 2, "0"):
                with self.subTest(resource=resource, invalid=invalid):
                    with self.assertRaises(ValidationError):
                        schema.validate({**document, "sub_type": invalid})
            schema.validate({**document, "required_tier_id": None})
            self.assertEqual(
                schema.validate({**document, "required_tier_id": 7})["required_tier_id"],
                7,
            )
            with self.assertRaises(ValidationError):
                schema.validate({
                    **document,
                    "required_tier_id": 7,
                    "platform": 3,
                    "synchronization_type": 3,
                })

    def test_main_image_reference_count_and_csv_shape(self):
        for resource, document in (
            ("config", self._share_document()),
            ("wa", self._import_document()),
        ):
            schema = get_schema("modus", resource, "create")
            document["schema"] = schema.name
            ten = ",".join("modus/image/%d.webp" % index for index in range(10))
            self.assertEqual(schema.validate({**document, "image_url": ten})["image_url"], ten)
            for invalid in (
                "modus/image/1.webp,,modus/image/2.webp",
                ",".join("modus/image/%d.webp" % index for index in range(11)),
            ):
                with self.subTest(resource=resource, invalid=invalid):
                    with self.assertRaises(ValidationError):
                        schema.validate({**document, "image_url": invalid})

    def test_config_and_wa_addons_id_accept_string_and_csv_values(self):
        config_schema = get_schema("modus", "config", "create")
        wa_schema = get_schema("modus", "wa", "create")
        for addons_id in ("9", "9,11"):
            with self.subTest(resource="config", addons_id=addons_id):
                document = self._share_document(addons_id=addons_id)
                document["schema"] = config_schema.name
                self.assertEqual(config_schema.validate(document)["addons_id"], addons_id)
            with self.subTest(resource="wa", addons_id=addons_id):
                document = self._import_document(addons_id=addons_id)
                document["schema"] = wa_schema.name
                self.assertEqual(wa_schema.validate(document)["addons_id"], addons_id)

    def test_main_session_reads_nested_json_without_returning_unrelated_values(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            leveldb = root / "Local Storage" / "leveldb"
            leveldb.mkdir(parents=True)
            (leveldb / "000001.log").write_bytes(b"prefix{\"user\":{\"token\":\"TOKEN\",\"deviceId\":\"DEVICE\"}}suffix")
            session = load_main_session(root)
            self.assertEqual(session, {"token": "TOKEN", "device_id": "DEVICE"})

    def test_config_crud_wire_contract_is_bundle_exact(self):
        provider = ModUs("TOKEN", main_session=True, device_id="DEVICE")
        calls = []
        def request(method, path, body=None, *, headers=None):
            calls.append((method, path, body, headers))
            return {"data": {"ok": True}}
        with mock.patch.object(provider, "_request", side_effect=request):
            provider.share_create(self._share_document(), server_type=4)
            provider.share_update(self._share_document(share_id="share/opaque"), server_type=4)
            provider.share_detail("share/opaque", server_type=4)
            provider.share_delete("share/opaque", server_type=4)

        expected = {
            "addonsId": "9,11", "backupId": 11,
            "content": "<p>full rendered body with details</p>", "contentText": "full rendered body with details",
            "imageUrl": "https://cdn.invalid/cover.webp", "isPaid": 0, "isPublic": 1,
            "price": 0, "shareType": 0, "tags": "1,2", "title": "A full title",
            "excludeWtf": 1, "accountName": "", "roleName": "", "subType": 0,
            "platform": 1,
        }
        self.assertEqual(calls[0][0:3], ("POST", "system/user/share/create", expected))
        update_expected = {"id": "share/opaque", **expected}
        self.assertEqual(calls[1][0:3], (
            "PUT", "system/user/share/update", update_expected,
        ))
        self.assertEqual(calls[2][0:3], (
            "POST", "system/user/share/detail", {"shareIds": ["share/opaque"]},
        ))
        self.assertEqual(calls[3][0:2], ("DELETE", "system/user/share/delete/share%2Fopaque"))
        for call in calls:
            self.assertEqual(call[3], {"X-Server-Type": "4"})
        for body in (calls[0][2], calls[1][2]):
            self.assertNotIn("requiredTierId", body)
            self.assertEqual(body["platform"], 1)

    def test_config_create_normalizes_exclude_wtf_to_integer(self):
        provider = ModUs("TOKEN", main_session=True, device_id="DEVICE")
        calls = []

        def request(method, path, body=None, *, headers=None):
            calls.append((method, path, body, headers))
            return {"data": {"ok": True}}

        cases = ((True, 1), (False, 0), ("true", 1), ("false", 0), ("1", 1), ("0", 0))
        with mock.patch.object(provider, "_request", side_effect=request):
            for source, expected in cases:
                provider.share_create(self._share_document(exclude_wtf=source))
                body = calls[-1][2]
                self.assertEqual(body["excludeWtf"], expected)
                self.assertEqual(body["platform"], 1)

        with mock.patch.object(provider, "_request", side_effect=request):
            provider.share_update(self._share_document(exclude_wtf=None))
        self.assertEqual(calls[-1][2]["excludeWtf"], 0)
        self.assertNotIn("synchronizationType", calls[-1][2])

    def test_default_lists_match_main_client_payloads(self):
        provider = ModUs("TOKEN", main_session=True, device_id="DEVICE")
        with mock.patch.object(provider, "_request", return_value={"data": {}}) as request:
            provider.share_list()
        self.assertEqual(request.call_args.args[2], {
            "pageNum": 1, "pageSize": 20, "server": 0,
            "mine": False, "shareType": 0, "platform": 0,
        })
        self.assertEqual(request.call_args.kwargs["headers"], {"X-Server-Type": "0"})

        with mock.patch.object(provider, "_request", return_value={"data": {}}) as request:
            provider.import_list()
        body = request.call_args.args[2]
        headers = request.call_args.kwargs["headers"]
        self.assertEqual(body, {
            "pageNum": 1, "pageSize": 10, "server": 0, "mine": False, "status": 1,
            "platform": 0,
        })
        self.assertEqual(headers["X-Server-Type"], "0")

    def test_list_filters_and_build_header_body_stay_synchronized(self):
        provider = ModUs("TOKEN", main_session=True, device_id="DEVICE")
        with mock.patch.object(provider, "_request", return_value={"data": {}}) as request:
            provider.share_list({
                "page_num": 3, "page_size": 40, "server": 2, "mine": True,
                "share_type": 0, "keyword": "unit", "tags": "1,2",
                "order_by": "hot", "is_paid": 0,
            })
        self.assertEqual(request.call_args.args[2], {
            "pageNum": 3, "pageSize": 40, "server": 2, "mine": True,
            "shareType": 0, "platform": 0, "keyword": "unit", "tags": ["1", "2"],
            "orderBy": "hot", "isPaid": 0,
        })
        self.assertEqual(request.call_args.kwargs["headers"], {"X-Server-Type": "2"})

        with mock.patch.object(provider, "_request", return_value={"data": {}}) as request:
            provider.import_list({
                "page_num": 2, "page_size": 25, "server": 3, "mine": True,
                "status": 1, "keyword": "aura", "support_addon": "WeakAuras",
                "tags": "4,5", "is_paid": 0, "order_by": "latest",
            })
        self.assertEqual(request.call_args.args[2], {
            "pageNum": 2, "pageSize": 25, "server": 3, "mine": True,
            "status": 1, "platform": 0, "keyword": "aura", "supportAddon": "WeakAuras",
            "tags": ["4", "5"], "isPaid": 0, "orderBy": "latest",
        })
        self.assertEqual(request.call_args.kwargs["headers"], {"X-Server-Type": "3"})

    def test_list_cli_exposes_main_client_filters(self):
        config = build_parser().parse_args([
            "modus", "config", "list", "--keyword", "x", "--status", "1",
            "--share-type", "0", "--order-by", "updateTime", "--mine",
            "--is-public", "1", "--is-paid", "0", "--tags", "1,2",
        ])
        self.assertEqual(config.keyword, "x")
        self.assertTrue(config.mine)
        wa = build_parser().parse_args([
            "modus", "wa", "list", "--support-addon", "WeakAuras",
            "--tags", "1,2", "--no-mine", "--is-paid", "0",
        ])
        self.assertEqual(wa.support_addon, "WeakAuras")
        self.assertFalse(wa.mine)

    def test_static_main_client_options_do_not_send_login_headers(self):
        provider = ModUs("TOKEN", main_session=True, device_id="DEVICE")
        with mock.patch("fupload_cli.modus.json_request", return_value={"data": [{"id": 1}]}) as request:
            result = provider.options("wa-tags")
        self.assertEqual(result, [{"id": 1}])
        self.assertEqual(request.call_args.args[0], "https://cdn.modus.cool/modus/client_static_api/imports_tags.json")
        self.assertNotIn("headers", request.call_args.kwargs)
        with mock.patch("fupload_cli.modus.json_request", return_value={"code": 200, "rows": [{"name": "WeakAuras"}]}) as request:
            result = provider.options("wa-support-addons")
        self.assertEqual(result, [{"name": "WeakAuras"}])

    def test_wa_crud_and_version_wire_contract_is_bundle_exact(self):
        provider = ModUs("TOKEN", main_session=True, device_id="DEVICE")
        calls = []

        def request(method, path, body=None, *, headers=None):
            calls.append((method, path, body, headers))
            return {"data": {"ok": True}}

        with mock.patch.object(provider, "_request", side_effect=request):
            provider.import_create(self._import_document(required_tier_id=None), server_type=1)
            provider.import_update(self._import_document(
                import_id="wa/opaque", required_tier_id=None,
            ), server_type=1)
            provider.import_detail("wa/opaque", server_type=1)
            provider.import_delete("wa/opaque", server_type=1)
            provider.import_version_publish({
                "import_id": "wa/opaque", "version": "2.0", "code_text": "UPDATED",
                "changelog": "changes",
            }, server_type=1)
            provider.import_version_publish({
                "import_id": "wa/opaque", "version": "2.1", "code_text": "UPDATED2",
                "changelog": "   ",
            }, server_type=1)
            provider.import_version_delete("version/opaque", server_type=1)

        expected = {
            "codeText": "SAMPLE", "content": "<p>string article body with details</p>", "addonsId": "7,8",
            "contentText": "string article body with details", "filePath": "", "imageUrl": "https://cdn.invalid/a.webp",
            "isPaid": 0, "isPublic": 1, "price": 0, "shareType": 0,
            "supportAddon": "Addon", "tags": "2", "title": "A string title",
            "version": "1.0", "subType": 0, "platform": 1, "synchronizationType": 1,
        }
        self.assertEqual(calls[0][0:3], ("POST", "system/user/import/create", expected))
        self.assertEqual(calls[1][0:3], (
            "POST", "system/user/import/update", {"id": "wa/opaque", **expected},
        ))
        self.assertEqual(calls[2][0:3], (
            "POST", "system/user/import/detail", {"importIds": ["wa/opaque"]},
        ))
        self.assertEqual(calls[3][0:2], ("DELETE", "system/user/import/delete/wa%2Fopaque"))
        self.assertEqual(calls[4][0:3], (
            "POST", "system/user/import/version/publish",
            {"importId": "wa/opaque", "version": "2.0", "codeText": "UPDATED", "changelog": "changes"},
        ))
        self.assertEqual(calls[5][2], {
            "importId": "wa/opaque", "version": "2.1", "codeText": "UPDATED2",
        })
        self.assertEqual(calls[6][0:2], (
            "DELETE", "system/user/import/version/delete?versionId=version%2Fopaque",
        ))
        for call in calls:
            self.assertEqual(call[3], {"X-Server-Type": "1"})
        for body in (calls[0][2], calls[1][2]):
            self.assertNotIn("requiredTierId", body)
            self.assertEqual(body["platform"], 1)
            self.assertEqual(body["synchronizationType"], 1)

    def test_addons_id_is_stringified_on_main_client_wires(self):
        provider = ModUs("TOKEN", main_session=True, device_id="DEVICE")
        with mock.patch.object(provider, "_request", return_value={"data": {}}) as request:
            provider.share_create(self._share_document(addons_id=1512221))
        self.assertEqual(request.call_args.args[2]["addonsId"], "1512221")
        with mock.patch.object(provider, "_request", return_value={"data": {}}) as request:
            provider.import_create(self._import_document(addons_id=1512221))
        self.assertEqual(request.call_args.args[2]["addonsId"], "1512221")

    def test_selected_subscription_tier_is_sent_but_none_is_omitted(self):
        provider = ModUs("TOKEN", main_session=True, device_id="DEVICE")
        with mock.patch.object(provider, "_request", return_value={"data": {}}) as request:
            provider.share_create(self._share_document(required_tier_id=7))
        self.assertEqual(request.call_args.args[2]["requiredTierId"], 7)
        with mock.patch.object(provider, "_request", return_value={"data": {}}) as request:
            provider.import_create(self._import_document(required_tier_id=9))
        self.assertEqual(request.call_args.args[2]["requiredTierId"], 9)

    def test_every_build_id_is_applied_to_read_and_write_headers(self):
        provider = ModUs("TOKEN", main_session=True, device_id="DEVICE")
        for build in range(5):
            with self.subTest(build=build):
                with mock.patch.object(provider, "_request", return_value={"data": {}}) as request:
                    provider.share_list({"server": build})
                    body = request.call_args.args[2]
                    self.assertEqual(body["server"], build)
                    self.assertEqual(request.call_args.kwargs["headers"], {"X-Server-Type": str(build)})
                with mock.patch.object(provider, "_request", return_value={"data": {}}) as request:
                    provider.import_create(self._import_document(), server_type=build)
                    self.assertEqual(request.call_args.kwargs["headers"], {"X-Server-Type": str(build)})

    def test_opaque_share_and_import_ids_are_preserved_in_detail_and_delete(self):
        provider = ModUs("TOKEN", main_session=True, device_id="DEVICE")
        calls = []

        def request(method, path, body=None, *, headers=None):
            calls.append((method, path, body, headers))
            return {"data": {"ok": True}}

        with mock.patch.object(provider, "_request", side_effect=request):
            provider.share_detail("share/opaque")
            provider.share_delete("share/opaque")
            provider.import_detail("wa/opaque")
            provider.import_delete("wa/opaque")

        self.assertEqual(calls[0][2], {"shareIds": ["share/opaque"]})
        self.assertEqual(calls[1][1], "system/user/share/delete/share%2Fopaque")
        self.assertEqual(calls[2][2], {"importIds": ["wa/opaque"]})
        self.assertEqual(calls[3][1], "system/user/import/delete/wa%2Fopaque")

    def test_dynamic_config_preflight_binds_backup_addons_account_role_and_tags(self):
        provider = ModUs("TOKEN", main_session=True, device_id="DEVICE")
        backup = {
            "id": 11,
            "knownAddons": json.dumps({"projectids": "9,11"}),
            "wtfAccounts": json.dumps([{"name": "Account", "roles": ["Role"]}]),
        }
        document = self._share_document(
            exclude_wtf=0, account_name="Account", role_name="Role", required_tier_id=None,
        )

        with mock.patch.object(provider, "options", return_value=[{"id": 1}, {"id": 2}]), \
                mock.patch.object(provider, "cloud_backups", return_value=[backup]):
            provider._validate_main_write("config", "create", document)
            invalid_cases = (
                ({"tags": "999"}, "tag is not present"),
                ({"addons_id": "999"}, "addons_id does not match"),
                ({"account_name": "Missing"}, "account_name is not present"),
                ({"role_name": ""}, "role_name is required"),
                ({"role_name": "Missing"}, "role_name is not present"),
                ({"backup_id": 99}, "backup_id is not present"),
            )
            for overrides, message in invalid_cases:
                with self.subTest(overrides=overrides):
                    with self.assertRaisesRegex(ValidationError, message):
                        provider._validate_main_write("config", "create", {**document, **overrides})

    def test_dynamic_wa_preflight_binds_tag_addon_and_tier(self):
        provider = ModUs("TOKEN", main_session=True, device_id="DEVICE")
        options = {
            "wa-tags": [{"id": 2}],
            "wa-support-addons": [{"id": 7, "name": "Addon"}],
            "subscription-tiers": [{"id": 5, "isEnabled": 1}],
        }
        document = self._import_document(addons_id="7", required_tier_id=5)
        with mock.patch.object(provider, "options", side_effect=lambda action: options[action]):
            provider._validate_main_write("wa", "create", document)
            for overrides, message in (
                ({"tags": "999"}, "tag is not present"),
                ({"addons_id": "8"}, "support_addon and addons_id"),
                ({"support_addon": "Missing"}, "support_addon and addons_id"),
                ({"required_tier_id": 99}, "required_tier_id is not present"),
            ):
                with self.subTest(overrides=overrides):
                    with self.assertRaisesRegex(ValidationError, message):
                        provider._validate_main_write("wa", "create", {**document, **overrides})

    def test_dynamic_preflight_failure_happens_before_mutation_request(self):
        provider = ModUs("TOKEN", main_session=True, device_id="DEVICE")
        with mock.patch.object(
            provider, "_validate_main_write",
            side_effect=ValidationError("dynamic option rejected", path="$.tags"),
        ), mock.patch.object(provider, "_request") as request:
            with self.assertRaisesRegex(ValidationError, "dynamic option rejected"):
                provider.execute_write("wa", "create", self._import_document())
        request.assert_not_called()


if __name__ == "__main__":
    unittest.main()
