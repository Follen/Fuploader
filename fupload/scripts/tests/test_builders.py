from __future__ import annotations

import hashlib
import queue
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fupload_cli.dd import DD, LIFE_TYPES, Sidecar, config_form, created_reference, discover_dd, merge_plugin_version_fields, normalize_commercial, plugin_form, readable_author_list, resolve_retail_ui_config, safe_backup_detail, safe_detail, selected_group
from fupload_cli.errors import FuploadError, ValidationError, redact
from fupload_cli.newbee import NewBee


class FakeNewBee(NewBee):
    def __init__(self) -> None:
        self.calls = []

    def get_plugin_raw(self, ident):
        return {
            "t_id": ident, "category_ids": [10], "t_original": 1, "t_content_format": 2,
            "t_name": "Before", "t_description_v2": "Body", "t_description": "Intro",
            "t_logo": "logo", "screenshots": ["shot"], "t_share": 0,
            "t_subscribe_plan_level": 0, "t_link_to_channel": False,
        }

    def post(self, endpoint, body):
        self.calls.append((endpoint, body.copy()))
        return {}


class AtomicNewBee(NewBee):
    def __init__(self) -> None:
        self.calls = []

    def post(self, endpoint, body):
        self.calls.append((endpoint, body.copy()))
        return {}


class DelayedConfigIndexNewBee(NewBee):
    def __init__(self) -> None:
        self.keywords = []

    def get_backup(self, cloud_id):
        return {
            "cloud_id": cloud_id,
            "linked_mods": [],
            "unknown_plugins": [],
            "materials": [],
            "fonts": [],
            "roles": [{"role_id": 7}],
        }

    def _resolve_media(self, endpoint, urls, files):
        return ["image"]

    def post(self, endpoint, body):
        self.assert_release_endpoint = endpoint
        return {}

    def list_configs(self, keyword, offset, size):
        self.keywords.append(keyword)
        if keyword:
            return {"count": 0, "list": []}
        return {
            "count": 1,
            "list": [{"t_id": 91, "t_title": "Delayed", "t_cloudblackid": 12}],
        }

    def get_config(self, ident):
        return {"id": ident, "title": "Delayed"}


class DelayedDDIndex:
    def __init__(self) -> None:
        self.keywords = []

    def post(self, endpoint, body):
        keyword = body["name_or_author_name_or_share_code"]
        self.keywords.append(keyword)
        return {"code": 0, "result": [] if keyword else [{"name": "Delayed", "sn": "abc"}]}


class FailedDDKeywordIndex(DelayedDDIndex):
    def get(self, endpoint, body):
        keyword = body["search_text"]
        self.keywords.append(keyword)
        if keyword:
            raise FuploadError("invalid search", business_code=1210)
        return {"code": 0, "result": [{"title": "Delayed", "share_sn": "cfg"}]}


class EmptyDDOptions:
    def get(self, endpoint, body):
        return {"code": 0, "result": []}

    def post(self, endpoint, body):
        return {"code": 0, "result": []}

    def cc_get(self, url):
        return {}


class BuilderTests(unittest.TestCase):
    @staticmethod
    def retail_backup():
        return {
            "sn": "backup-a",
            "game_type": 10001,
            "retail_ui_config": {
                "editMode": {
                    "account-a": [
                        {"name": "Raid", "import_string": "secret-raid"},
                        {"name": "Dungeon", "import_string": "secret-dungeon"},
                    ],
                },
                "coolDown": {
                    "account-a": [
                        {"name": "Fire", "spec_tag": 63, "char": "Mage", "realm": "Realm", "import_string": "secret-fire"},
                        {"name": "Fire alt", "spec_tag": 63, "char": "Mage2", "realm": "Realm", "import_string": "secret-fire-2"},
                        {"name": "Frost", "spec_tag": 64, "char": "Mage", "realm": "Realm", "import_string": "secret-frost"},
                    ],
                },
            },
        }

    @staticmethod
    def wa_backup():
        return {
            "sn": "backup-wa",
            "wtf": {
                "accounts": [
                    {
                        "name": "account-a",
                        "servers": [{"name": "realm", "items": [{"role_id": "role-a"}]}],
                    },
                    {
                        "name": "account-b",
                        "servers": [{"name": "realm", "items": [{"role_id": "role-b"}]}],
                    },
                ],
            },
            "known_wa": {"items": [{"id": "known-id", "uid": "known-uid", "name": "Known"}]},
            "unknown_wa": {"items": [{"id": "stale-id", "uid": "unknown-uid", "name": "Unknown"}]},
            "extra": {
                "wa_account_info": {
                    "account-a": [
                        {"id": "mapped-known", "uid": "known-uid"},
                        {"id": "mapped-unknown", "uid": "unknown-uid"},
                    ],
                    "account-b": [{"id": "other-known", "uid": "known-uid"}],
                },
            },
        }

    def test_newbee_plugin_edit_preserves_private_state(self) -> None:
        provider = FakeNewBee()
        result = provider.edit_plugin({"id": 42, "intro": "After"})
        endpoint, body = provider.calls[-1]
        self.assertEqual(endpoint, "/creator/wow/mod/edit")
        self.assertEqual(body["share_state"], 0)
        self.assertEqual(body["name"], "Before")
        self.assertEqual(body["intro"], "After")

    def test_newbee_config_create_falls_back_to_unfiltered_author_list(self) -> None:
        provider = DelayedConfigIndexNewBee()
        result = provider.create_config({
            "cloud_id": 12,
            "title": "Delayed",
            "content": "Body",
            "content_format": 2,
            "content_origin": 1,
            "public": False,
            "linked_mods": [],
            "ignored_unknown_mods": [],
            "ignored_materials": [],
            "ignored_fronts": [],
            "roleid": "7",
            "picture_urls": ["image"],
        })
        self.assertEqual(result["id"], 91)
        self.assertEqual(provider.keywords, ["Delayed", ""])

    def test_newbee_wa_edit_form_preserves_category_list_ids(self) -> None:
        provider = FakeNewBee()
        form = provider._wa_form(7, {"category_list": [{"t_id": 210}]})
        self.assertEqual(form["category_id_list"], [210])

    def test_newbee_attachment_upload_uses_md5_wire_fingerprint(self) -> None:
        class Response:
            status = 200

            def read(self):
                return b""

        class Connection:
            def __init__(self):
                self.request_args = None

            def request(self, *args, **kwargs):
                self.request_args = (args, kwargs)

            def getresponse(self):
                return Response()

            def close(self):
                return None

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "attachment.zip"
            path.write_bytes(b"attachment")
            expected = hashlib.md5(b"attachment", usedforsecurity=False).hexdigest()

            def request(url, method="GET", body=None, **_kwargs):
                if url.endswith("/upload/v3/prepare"):
                    self.assertEqual(body["code"], expected)
                    self.assertEqual(body["files"][0]["fullHash"], expected)
                    self.assertEqual(body["files"][0]["chunks"][0]["hash"], expected)
                    return {
                        "code": 1,
                        "data": {
                            "id": expected,
                            "items": {expected: {"exists": False, "url": "https://upload.invalid", "callback": "callback"}},
                        },
                    }
                return {"code": 1, "data": {"code": expected, "fileName": path.name, "totalSize": path.stat().st_size}}

            connection = Connection()
            with mock.patch("fupload_cli.newbee.json_request", side_effect=request), mock.patch(
                "fupload_cli.newbee.http.client.HTTPSConnection", return_value=connection
            ):
                result = NewBee().upload_attachment(str(path))

        self.assertEqual(result["value"], expected)
        self.assertEqual(result["sha256"], hashlib.sha256(b"attachment").hexdigest())
        _, request_kwargs = connection.request_args
        self.assertNotIn("Content-Type", request_kwargs["headers"])

    def test_newbee_wa_changelog_edit_maps_public_fields_to_wire_fields(self) -> None:
        provider = AtomicNewBee()
        provider.execute_write("wa-changelog", "edit", {"id": 101592, "wa_id": 9680, "wa_log": "edited"})
        self.assertEqual(
            provider.calls[0],
            ("/creator/wow/wa_log/edit", {"wa_log_id": 101592, "content": "edited"}),
        )
        self.assertEqual(
            provider.calls[1],
            ("/creator/wow/wa_log/list", {"wa_id": 9680, "pagenum": 1, "pagesize": 20}),
        )

    def test_newbee_wa_share_code_uses_next_api_base(self) -> None:
        provider = AtomicNewBee()
        provider.get_wa = lambda ident: {"id": ident}
        with mock.patch.object(provider, "post_next", return_value={"shareCode": "code"}) as post_next:
            result = provider.execute_write("wa-share-code", "set", {"module_id": 9680})
        post_next.assert_called_once_with(
            "/bannerserver/ShareCode/Set",
            {"gameId": 1, "moduleId": 9680, "moduleType": 3},
        )
        self.assertEqual(result["result"], {"shareCode": "code"})

    def test_dd_inner_version_only_bumps_selected_updates(self) -> None:
        backup = {"known_addon": {"items": [{"addon_id": "a"}, {"addon_id": "b"}]}}
        current = {"known_addon": {"items": [{"addon_id": "a"}], "inner_version": {"a": 3}}}
        group = selected_group(backup, current, "known_addon", "addon_id", ["a", "b"], ["a"])
        self.assertEqual(group["inner_version"], {"a": 4, "b": 1})
        self.assertEqual([item["addon_id"] for item in group["items"]], ["a", "b"])

    def test_dd_commercial_false_clears_dependents(self) -> None:
        form = {
            "scope": "private", "jump_room": False, "room_id": "r", "channel_id": "c",
            "channel_type": "x", "sync_room": True, "with_associate": False,
            "associated_acts": [{"sn": "x"}], "need_anchor_vip": True, "vip_levels": [1],
            "need_buy": False, "price_fen": 100, "buy_life_type": "month",
        }
        normalize_commercial(form)
        self.assertEqual(form["price_fen"], 0)
        self.assertEqual(form["buy_life_type"], "month")
        self.assertEqual(form["room_id"], "")
        self.assertEqual(form["associated_acts"], [])
        self.assertFalse(form["need_anchor_vip"])
        self.assertEqual(form["vip_levels"], [])

    def test_dd_business_error_is_not_treated_as_success(self) -> None:
        with self.assertRaises(FuploadError) as raised:
            Sidecar._business_response("/addon/create", {"code": 500, "msg": "failed"})
        self.assertEqual(raised.exception.endpoint, "/addon/create")
        self.assertEqual(raised.exception.business_code, 500)

    def test_dd_life_types_match_official_client_enum(self) -> None:
        self.assertEqual(
            [item["value"] for item in LIFE_TYPES],
            ["seven_day", "fourteen_day", "thirty_day", "sixty_day", "ninety_day", "forever"],
        )

    def test_dd_create_reference_falls_back_to_unfiltered_author_list(self) -> None:
        session = DelayedDDIndex()
        self.assertEqual(created_reference(session, "plugin", "Delayed", 10001), "abc")
        self.assertEqual(session.keywords, ["Delayed", ""])

    def test_dd_create_reference_ignores_failed_keyword_lookup(self) -> None:
        session = FailedDDKeywordIndex()
        self.assertEqual(created_reference(session, "config", "Delayed", 10001), "cfg")
        self.assertEqual(session.keywords, ["Delayed", ""])

    def test_dd_readable_config_list_filters_after_failed_server_search(self) -> None:
        session = FailedDDKeywordIndex()
        result = readable_author_list(session, "config", "Delayed", 10001, 1, 50)
        self.assertEqual(result["total"], 1)
        self.assertEqual(result["items"][0]["reference"], "cfg")
        self.assertEqual(session.keywords, ["Delayed", ""])

    def test_dd_plugin_form_removes_detail_summary_category(self) -> None:
        form = plugin_form({"game_types": [10001], "second_category_ids": [1037, 999]})
        self.assertEqual(form["second_category_ids"], [1037])

    def test_dd_plugin_form_uses_author_list_pending_version(self) -> None:
        form = plugin_form({"game_types": [10001], "latest_version": {"version": None}})
        merge_plugin_version_fields(form, {
            "game_types": [10001],
            "latest_version": {
                "file_path": "archive",
                "game_versions": ["12.0.7"],
                "release_type": 1,
                "version": "1.0.1",
            },
            "update_desc": "pending update",
        })
        self.assertEqual(form["detail_url"], "archive")
        self.assertEqual(form["version"], "1.0.1")
        self.assertEqual(form["update_desc"], "pending update")

    def test_dd_retail_backup_exposes_only_safe_selectors(self) -> None:
        safe = safe_backup_detail(self.retail_backup())
        encoded = repr(safe)
        self.assertNotIn("secret-", encoded)
        self.assertEqual(len(safe["retail_ui_config"]["edit_modes"]), 2)
        self.assertEqual(len(safe["retail_ui_config"]["cool_down"]), 3)
        self.assertTrue(safe["retail_ui_config"]["edit_modes"][0]["selector"].startswith("em_"))

    def test_dd_backup_safe_references_match_builder_selection_keys(self) -> None:
        safe = safe_backup_detail({
            "sn": "backup",
            "known_addon": {"items": [{"addon_id": 1172, "detail_sn": "content-sn", "name": "Addon"}]},
            "unknown_addon": {"items": ["LooseAddon"]},
            "known_wa": {"items": [{"id": "wa-id", "uid": "private-uid", "name": "WA"}]},
        })
        self.assertEqual(safe["known_addon"][0]["reference"], 1172)
        self.assertEqual(safe["known_addon"][0]["content_reference"], "content-sn")
        self.assertEqual(safe["unknown_addon"][0]["reference"], "LooseAddon")
        self.assertEqual(safe["known_wa"][0]["reference"], "private-uid")

    def test_dd_backup_safe_wa_references_include_available_accounts(self) -> None:
        safe = safe_backup_detail(self.wa_backup())
        self.assertEqual(safe["known_wa"][0]["accounts"], ["account-a", "account-b"])
        self.assertEqual(safe["unknown_wa"][0]["accounts"], ["account-a"])

    def test_dd_unknown_wa_uses_selected_account_mapping(self) -> None:
        form = config_form({}, self.wa_backup(), {
            "wtf_role_ids": ["role-a"],
            "unknown_wa_ids": ["unknown-uid"],
        })
        self.assertEqual(form["unknown_wa"]["items"][0]["id"], "mapped-unknown")

    def test_dd_wa_rejects_selection_unavailable_for_wtf_account(self) -> None:
        with self.assertRaisesRegex(ValidationError, "unavailable"):
            config_form({}, self.wa_backup(), {
                "wtf_role_ids": ["role-b"],
                "unknown_wa_ids": ["unknown-uid"],
            })

    def test_dd_changing_wtf_account_clears_omitted_wa_groups(self) -> None:
        current = config_form({}, self.wa_backup(), {
            "wtf_role_ids": ["role-a"],
            "known_wa_ids": ["known-uid"],
            "unknown_wa_ids": ["unknown-uid"],
        })
        changed = config_form(current, self.wa_backup(), {"wtf_role_ids": ["role-b"]})
        self.assertEqual(changed["known_wa"], {"items": [], "inner_version": {}})
        self.assertEqual(changed["unknown_wa"], {"items": [], "inner_version": {}})

    def test_dd_wa_selection_requires_wtf_role(self) -> None:
        with self.assertRaisesRegex(ValidationError, "select one WTF role"):
            config_form({}, self.wa_backup(), {"known_wa_ids": ["known-uid"]})

    def test_dd_retail_selectors_restore_complete_wire_objects(self) -> None:
        backup = self.retail_backup()
        safe = safe_backup_detail(backup)["retail_ui_config"]
        edit = safe["edit_modes"][0]["selector"]
        cool = safe["cool_down"][0]["selector"]
        wire = resolve_retail_ui_config(backup, {}, {
            "edit_mode_selectors": [edit],
            "default_edit_mode_selector": edit,
            "cool_down_selectors": [cool],
            "enable_dd_setup_wizard": False,
        })
        self.assertEqual(wire["edit_mode"]["account-a"][0]["import_string"], "secret-raid")
        self.assertTrue(wire["edit_mode"]["account-a"][0]["is_default"])
        self.assertEqual(wire["cool_down"]["account-a"][0]["import_string"], "secret-fire")
        self.assertFalse(wire["enable_dd_setup_wizard"])

    def test_dd_retail_rejects_two_cooldowns_for_same_spec(self) -> None:
        backup = self.retail_backup()
        choices = safe_backup_detail(backup)["retail_ui_config"]["cool_down"]
        with self.assertRaisesRegex(ValidationError, "one cooldown"):
            resolve_retail_ui_config(backup, {}, {
                "cool_down_selectors": [choices[0]["selector"], choices[1]["selector"]],
            })

    def test_dd_retail_selector_is_bound_to_backup(self) -> None:
        backup = self.retail_backup()
        selector = safe_backup_detail(backup)["retail_ui_config"]["edit_modes"][0]["selector"]
        other = dict(backup, sn="backup-b")
        with self.assertRaisesRegex(ValidationError, "unavailable"):
            resolve_retail_ui_config(other, {}, {
                "edit_mode_selectors": [selector],
                "default_edit_mode_selector": selector,
            })

    def test_dd_wa_readback_redacts_content_and_temporary_paths(self) -> None:
        safe = safe_detail("wa", {
            "content": "!WA:2!secret",
            "file_path": "https://signed.example/material.zip?token=secret",
            "display_imgs": ["https://public.example/image.png"],
        })
        encoded = repr(safe)
        self.assertNotIn("!WA:2!secret", encoded)
        self.assertNotIn("token=secret", encoded)
        self.assertEqual(safe["content_summary"]["length"], 12)
        self.assertEqual(safe["file_path_summary"]["host"], "signed.example")

    def test_secret_redaction(self) -> None:
        value = redact("Authorization: Bearer abc.def.ghi X-Amz-Signature=secret")
        self.assertNotIn("secret", value)
        self.assertNotIn("abc.def.ghi", value)

    def test_dd_sidecar_timeout_marks_uncertain_write(self) -> None:
        sidecar = Sidecar.__new__(Sidecar)
        sidecar.responses = queue.Queue()
        with self.assertRaises(FuploadError) as caught:
            sidecar._next_result(
                timeout=0.001,
                endpoint="/addon/modify",
                verification_required=True,
            )
        self.assertEqual(caught.exception.kind, "timeout")
        self.assertEqual(caught.exception.endpoint, "/addon/modify")
        self.assertTrue(caught.exception.verification_required)

    def test_dd_discovery_selects_highest_validated_version(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for version in ("100128", "100129"):
                candidate = root / version
                (candidate / "ccsub64").mkdir(parents=True)
                (candidate / "netease_dd.exe").write_bytes(b"exe")
                (candidate / "ccvoicehub.res").write_bytes(b"resource")
            with mock.patch("fupload_cli.dd._discovery_roots", return_value=[root]), mock.patch(
                "fupload_cli.dd.EXPECTED_DD_VERSION", "any"
            ):
                self.assertEqual(discover_dd(), (root / "100129").resolve())

    def test_dd_discovery_honors_explicit_version_pin(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for version in ("100128", "100129"):
                candidate = root / version
                (candidate / "ccsub64").mkdir(parents=True)
                (candidate / "netease_dd.exe").write_bytes(b"exe")
                (candidate / "ccvoicehub.res").write_bytes(b"resource")
            with mock.patch("fupload_cli.dd._discovery_roots", return_value=[root]), mock.patch(
                "fupload_cli.dd.EXPECTED_DD_VERSION", "100128"
            ):
                self.assertEqual(discover_dd(), (root / "100128").resolve())

    def test_dd_enabled_channel_rejects_empty_live_options(self) -> None:
        with self.assertRaisesRegex(FuploadError, "channel response"):
            DD()._validate_options(EmptyDDOptions(), "config", {
                "game_type": 10001,
                "jump_room": True,
                "room_id": "room",
                "channel_id": "channel",
                "channel_type": "text",
            })

    def test_dd_enabled_association_rejects_empty_live_options(self) -> None:
        with self.assertRaisesRegex(FuploadError, "association response"):
            DD()._validate_options(EmptyDDOptions(), "config", {
                "game_type": 10001,
                "with_associate": True,
                "associated_acts": [{"sn": "missing", "act_type": "addon"}],
            })

    def test_newbee_plugin_update_preserves_omitted_channel(self) -> None:
        provider = FakeNewBee()
        current = provider.get_plugin_raw(1)
        current["t_link_to_channel"] = True
        with tempfile.TemporaryDirectory() as directory:
            package = Path(directory) / "plugin.zip"
            package.write_bytes(b"zip")
            with mock.patch.object(provider, "get_plugin_raw", return_value=current), mock.patch.object(
                provider, "plugin_versions", return_value={"list": []}
            ), mock.patch.object(
                provider, "game_versions", return_value={"items": [{"id": 2}]}
            ), mock.patch.object(provider, "upload", return_value={}) as upload, mock.patch.object(
                provider, "get_plugin", return_value={"id": 1}
            ):
                provider.update_plugin({
                    "mod_id": 1,
                    "version": "2",
                    "game_version_list": [2],
                    "file": str(package),
                })
        self.assertEqual(upload.call_args.args[2]["link_to_channel"], "true")

    def test_newbee_wa_update_preserves_omitted_channel_and_titles(self) -> None:
        provider = AtomicNewBee()
        current = {
            "t_version": "1",
            "t_link_to_channel": True,
            "t_wa_str_titles": ["One", "Two"],
        }
        with mock.patch.object(provider, "get_wa_raw", return_value=current), mock.patch.object(
            provider, "latest_wa", return_value={"version": "2"}
        ):
            provider.update_wa({
                "id": 1,
                "version": "2",
                "wa_str": "new",
                "wa_log": "changed",
            })
        payload = next(
            body for endpoint, body in provider.calls
            if endpoint == "/creator/wow/wa/update_wa_str"
        )
        self.assertTrue(payload["link_to_channel"])
        self.assertEqual(payload["wa_str_titles"], ["One", "Two"])


if __name__ == "__main__":
    unittest.main()
