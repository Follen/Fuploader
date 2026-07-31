from __future__ import annotations

import hashlib
import queue
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fupload_cli.dd import DD, LIFE_TYPES, Sidecar, _option_values, _verify_fields, config_form, created_reference, discover_dd, merge_plugin_version_fields, normalize_commercial, plugin_form, readable_author_list, resolve_retail_ui_config, safe_backup_detail, safe_channels, safe_detail, selected_group, validate_locked_usage_mode
from fupload_cli.errors import FuploadError, ValidationError, redact
from fupload_cli.newbee import NewBee, RELATION_TYPES, _redact_wa, _require_readback, _wa_summary


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


class ValidDDOptions:
    def get(self, endpoint, body):
        values = {
            "/game_type/list": [{"game_type": 10001}],
            "/game_versions/list": [{"game_version": "12.1.0"}],
            "/addon/category": [{"id": 1, "children": [{"id": 2}]}],
            "/anchor_vip/level/list": [],
            "/share/list": [],
            "/wa/list": [],
        }
        return {"code": 0, "result": values.get(endpoint, [])}

    def post(self, endpoint, body):
        return {"code": 0, "result": []}

    def cc_get(self, url):
        return {"data": [{"teamId": "room", "channelList": []}]}


class DeleteDDSession:
    def __init__(self):
        self.calls = []

    def get(self, endpoint, body):
        self.calls.append(("get", endpoint, dict(body)))
        if endpoint == "/addon/detail_v2":
            return {"code": 0, "result": {"sn": "plugin-sn", "name": "Plugin", "game_type": 10001}}
        return {"code": 0, "result": []}

    def post(self, endpoint, body):
        self.calls.append(("post", endpoint, dict(body)))
        return {"code": 0, "result": []}


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
        with mock.patch("fupload_cli.newbee._require_readback"):
            result = provider.edit_plugin({"id": 42, "intro": "After"})
        endpoint, body = provider.calls[-1]
        self.assertEqual(endpoint, "/creator/wow/mod/edit")
        self.assertEqual(body["share_state"], 0)
        self.assertEqual(body["name"], "Before")
        self.assertEqual(body["intro"], "After")

    def test_newbee_commercial_normalization_clears_disabled_children_and_private_channel(self) -> None:
        form = {
            "subscribe_plan_level": 0, "price": 0, "time_range": "seven_day",
            "link_to_channel": True,
        }
        NewBee._normalize_commercial(form, False)
        self.assertEqual(form["subscribe_plan_level"], 0)
        self.assertEqual(form["price"], 0)
        self.assertEqual(form["time_range"], "")
        self.assertFalse(form["link_to_channel"])

    def test_newbee_relationship_replacements_use_web_resource_namespaces_and_readback(self) -> None:
        class RelationNewBee(NewBee):
            def __init__(self):
                self.calls = []

            def post(self, endpoint, body):
                self.calls.append((endpoint, dict(body)))
                if endpoint == "/creator/co_author/list":
                    return {"list": [{"user_id": 9, "share_percent": 0.25}]}
                if endpoint == "/creator/content_reference/list":
                    return {"list": [{"type": 7, "id": 8}]}
                return {}

        for resource, types in RELATION_TYPES.items():
            with self.subTest(resource=resource):
                provider = RelationNewBee()
                relationships = provider._replace_relationships(resource, 42, {
                    "co_authors": [{"user_id": 9, "share_percent": 0.25}],
                    "references": [{"type": 7, "id": 8}],
                })
                self.assertEqual(list(relationships), ["co_authors", "references"])
                self.assertEqual(provider.calls[0], ("/creator/co_author/set", {
                    "content_type": types["co_authors"], "content_id": 42,
                    "co_authors": [{"user_id": 9, "share_percent": 0.25}],
                }))
                self.assertEqual(provider.calls[2], ("/creator/content_reference/set", {
                    "source_type": types["references"], "source_id": 42,
                    "references": [{"type": 7, "id": 8}],
                }))

    def test_newbee_config_create_falls_back_to_unfiltered_author_list(self) -> None:
        provider = DelayedConfigIndexNewBee()
        with mock.patch.object(provider, "_validate_business_options"), mock.patch("fupload_cli.newbee._require_readback"):
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

    def test_dd_plugin_update_confirms_detail_latest_version_without_history(self) -> None:
        before = {
            "sn": "plugin-sn", "game_type": 10001, "name": "Plugin",
            "scope": "public", "need_buy": False, "need_anchor_vip": False,
            "jump_room": False, "with_associate": False,
            "latest_version": {
                "game_versions": ["12.1.0"], "file_path": "old-archive",
                "release_type": 1, "version": "1.0.0",
            },
            "update_desc": "old update",
        }
        after = {
            **before,
            "latest_version": {
                "game_versions": ["12.1.0"], "file_path": "new-archive",
                "release_type": 2, "version": "1.0.1",
            },
            "update_desc": "new update",
        }
        session = mock.MagicMock()
        session.post.return_value = {"code": 0, "result": {"sn": "plugin-sn"}}
        with mock.patch.object(DD, "_fresh_detail", return_value=before), mock.patch(
            "fupload_cli.dd.author_item", side_effect=[{}, after]
        ), mock.patch.object(DD, "_validate_options"), mock.patch(
            "fupload_cli.dd.detail", return_value=before
        ):
            result = DD()._write_plugin(session, "update", {
                "sn": "plugin-sn", "game_versions": ["12.1.0"],
                "detail_url": "new-archive", "release_type": 2,
                "version": "1.0.1", "update_desc": "new update",
            })
        self.assertEqual(result["reference"], "plugin-sn")
        self.assertFalse(any(call.args[0] == "/addon/addon_versions" for call in session.get.call_args_list))

    def test_dd_wa_create_uses_official_form_defaults_and_string_categories(self) -> None:
        session = mock.MagicMock()
        session.post.return_value = {"code": 0, "result": {"sn": "wa-sn"}}
        with mock.patch.object(DD, "_validate_options"), mock.patch(
            "fupload_cli.dd.detail", return_value={}
        ), mock.patch("fupload_cli.dd._verify_fields"):
            DD()._write_wa(session, "create", {
                "game_type": 10001, "scope": "private", "name": "WA", "game_version": "12.0.7",
                "brief_desc": "Brief", "display_imgs": ["image"], "category_ids": [58],
                "content": "plain string", "desc": "Description", "update_desc": "Initial",
                "version": "1", "with_file": False, "need_buy": False, "jump_room": False,
                "creation_statement": "original", "with_associate": False, "need_anchor_vip": False,
            })
        submitted = session.post.call_args.args[1]
        self.assertEqual(submitted["category_ids"], ["58"])
        self.assertEqual(submitted["buy_life_type"], "seven_day")
        self.assertEqual(submitted["file_install_path"], "Interface/Addons")

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
        self.assertEqual(changed["known_wa"], {"items": [], "inner_version": {"known-uid": 1}})
        self.assertEqual(changed["unknown_wa"], {"items": [], "inner_version": {"unknown-uid": 1}})

    def test_dd_wa_selection_requires_wtf_role(self) -> None:
        with self.assertRaisesRegex(ValidationError, "select one WTF role"):
            config_form({}, self.wa_backup(), {"known_wa_ids": ["known-uid"]})

    def test_dd_wtf_selectors_disambiguate_duplicate_role_names(self) -> None:
        backup = {
            "sn": "backup",
            "wtf": {"accounts": [
                {"name": "a", "servers": [{"name": "one", "items": ["Same"]}]},
                {"name": "b", "servers": [{"name": "two", "items": ["Same"]}]},
            ]},
        }
        safe = safe_backup_detail(backup)
        self.assertEqual(len(safe["wtf_roles"]), 2)
        with self.assertRaisesRegex(ValidationError, "ambiguous"):
            config_form({}, backup, {"wtf_role_ids": ["Same"]})
        selected = config_form({}, backup, {"wtf_role_ids": [safe["wtf_roles"][0]["selector"]]})
        self.assertEqual(selected["wtf"]["accounts"][0]["name"], "a")

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
            ), mock.patch(
                "fupload_cli.dd.verify_dd_executable",
                return_value={"status": "Valid", "publisher": "NetEase (Hangzhou) Network Co., Ltd"},
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
            ), mock.patch(
                "fupload_cli.dd.verify_dd_executable",
                return_value={"status": "Valid", "publisher": "NetEase (Hangzhou) Network Co., Ltd"},
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
                provider, "plugin_versions", side_effect=[
                    {"list": []},
                    {"list": [{"t_display_name": "2", "versions": ["3.80.2"]}]},
                ]
            ), mock.patch.object(
                provider, "game_versions", return_value={"items": [{"id": 4, "versions": ["3.80.2"]}]}
            ), mock.patch.object(provider, "upload", return_value={}) as upload, mock.patch.object(
                provider, "get_plugin", return_value={"id": 1}
            ):
                provider.update_plugin({
                    "mod_id": 1,
                    "version": "2",
                    "game_version_list": ["3.80.2"],
                    "file": str(package),
                })
        self.assertEqual(upload.call_args.args[2]["link_to_channel"], "true")

    def test_newbee_dynamic_options_fail_closed(self) -> None:
        provider = NewBee()
        with mock.patch.object(provider, "content_origins", return_value={"total": 0, "items": []}):
            with self.assertRaisesRegex(FuploadError, "no selectable values"):
                provider._validate_business_options({"content_origin": 1})

    def test_newbee_readback_match_completes_without_error(self) -> None:
        _require_readback(
            {"name": "Test", "categories": [2, 1], "picture_urls": ["user_media/image.png"]},
            {
                "name": "Test",
                "categories": [1, 2],
                "picture_urls": ["https://cdn.example/user_media/image.png?resize=1"],
            },
            "/readback",
        )

    def test_newbee_config_readback_normalizes_role_id_to_string(self) -> None:
        provider = NewBee()
        with mock.patch.object(provider, "get_config_raw", return_value={"t_id": 7, "t_roleid": 135676488}):
            self.assertEqual(provider.get_config(7)["roleid"], "135676488")

    def test_newbee_wa_redaction_preserves_non_sensitive_values(self) -> None:
        redacted = _redact_wa({"items": [{"wa_str": "secret", "version": 2}], "total": 1})
        self.assertEqual(redacted["items"][0]["version"], 2)
        self.assertEqual(redacted["items"][0]["wa_str_summary"]["length"], 6)
        self.assertEqual(redacted["total"], 1)

    def test_newbee_wa_readback_projects_one_time_duration(self) -> None:
        self.assertEqual(_wa_summary({"t_time_range": "seven_day"})["time_range"], "seven_day")

    def test_newbee_attachment_parser_ignores_unrelated_nested_values(self) -> None:
        provider = NewBee()
        with mock.patch.object(provider, "attachment_paths", return_value={"metadata": {"value": 7, "extract_base_dir": "Interface"}}):
            with self.assertRaisesRegex(FuploadError, "attachment path response"):
                provider._validate_attachments([{
                    "name": "one.zip", "install_type": 7, "install_path": "Interface",
                    "value": "code", "is_compressed": True,
                }])

    def test_dd_plugin_categories_enforce_parent_child_relationship(self) -> None:
        form = {
            "game_type": 10001, "game_versions": ["12.1.0"],
            "primary_category_id": 1, "second_category_ids": [3],
        }
        with self.assertRaisesRegex(ValidationError, "must belong"):
            DD()._validate_options(ValidDDOptions(), "plugin", form)
        form["second_category_ids"] = [2]
        DD()._validate_options(ValidDDOptions(), "plugin", form)

    def test_dd_wa_category_parser_accepts_live_c_id_shape(self) -> None:
        class WAOptions(ValidDDOptions):
            def get(self, endpoint, body):
                if endpoint == "/wa/categories":
                    return {"code": 0, "result": [{"c_id": "210", "children": [{"c_id": "211"}]}]}
                return super().get(endpoint, body)

        DD()._validate_options(WAOptions(), "wa", {
            "game_type": 10001, "game_version": "12.1.0", "category_ids": ["211"],
        })

    def test_dd_option_parser_accepts_internal_enum_lists(self) -> None:
        self.assertIn("seven_day", _option_values(LIFE_TYPES, ("value",)))

    def test_dd_plugin_readback_normalizes_disabled_commercial_fields(self) -> None:
        form = plugin_form({
            "scope": "private",
            "need_buy": False,
            "jump_room": False,
            "with_associate": False,
            "need_anchor_vip": False,
        })
        self.assertEqual(form["vip_levels"], [])
        self.assertEqual(form["associated_acts"], [])
        self.assertEqual(form["room_id"], "")

    def test_dd_public_lifetime_and_locked_outer_usage_mode_match_resource_contract(self) -> None:
        config = {"scope": "public", "share_code_life_type": "seven_day"}
        normalize_commercial(config, "config")
        self.assertNotIn("share_code_life_type", config)
        plugin = {"scope": "public", "share_code_life_type": "seven_day"}
        normalize_commercial(plugin, "plugin")
        self.assertEqual(plugin["share_code_life_type"], "forever")

        with self.assertRaisesRegex(ValidationError, "outer free/paid"):
            validate_locked_usage_mode(
                {"need_buy": True, "need_anchor_vip": False},
                {"need_buy": False, "need_anchor_vip": False},
                {"need_buy": False},
            )
        validate_locked_usage_mode(
            {"need_buy": True, "need_anchor_vip": False},
            {"need_buy": False, "need_anchor_vip": True},
            {"need_buy": False, "need_anchor_vip": True},
        )

    def test_dd_wa_edit_reparses_unchanged_wa2_and_preserves_material_paths(self) -> None:
        current = {
            "sn": "wa-sn",
            "game_type": 10001,
            "scope": "public",
            "name": "WA",
            "game_version": "12.1.0",
            "brief_desc": "Before",
            "display_imgs": [],
            "category_ids": ["210"],
            "content": "!WA:2!same",
            "desc": "Description",
            "update_desc": "Update",
            "version": "2",
            "with_file": True,
            "file_path": "https://cdn.example/wa.zip",
            "file_install_path": "Interface/Addons",
            "need_buy": False,
            "need_anchor_vip": False,
            "jump_room": False,
            "with_associate": False,
        }
        session = mock.MagicMock()
        session.call.return_value = {"parse_wa_uid": "uid", "parse_wa_id": "id"}
        session.post.return_value = {"code": 0, "result": {"sn": "wa-sn"}}
        with mock.patch.object(DD, "_fresh_detail", return_value=current), mock.patch.object(
            DD, "_validate_options"
        ), mock.patch("fupload_cli.dd.detail", return_value=current), mock.patch(
            "fupload_cli.dd._verify_fields"
        ):
            DD()._write_wa(session, "edit", {"sn": "wa-sn", "brief_desc": "After", "with_file": False})
        session.call.assert_called_once_with("parse_wa", content="!WA:2!same")
        submitted = session.post.call_args.args[1]
        self.assertFalse(submitted["with_file"])
        self.assertEqual(submitted["file_path"], "https://cdn.example/wa.zip")
        self.assertEqual(submitted["file_install_path"], "Interface/Addons")

    def test_dd_post_timeout_preserves_endpoint_and_uncertain_write(self) -> None:
        sidecar = Sidecar.__new__(Sidecar)
        sidecar.counter = 0
        sidecar.process = mock.MagicMock()
        sidecar.process.stdin = mock.MagicMock()
        with mock.patch.object(sidecar, "_next_result", return_value={
            "id": 1,
            "ok": False,
            "error": {"message": "The read operation timed out"},
        }):
            with self.assertRaises(FuploadError) as raised:
                sidecar.call("request", method="POST", path="/share/create", payload={})
        self.assertEqual(raised.exception.endpoint, "/share/create")
        self.assertTrue(raised.exception.verification_required)

    def test_dd_detail_timestamp_skew_does_not_block_owner_write(self) -> None:
        stale = {"sn": "one", "title": "Old", "game_type": 10001, "mtime": "2026-07-31T10:00:00"}
        newer = {"share_sn": "one", "title": "New", "game_type": 10001, "mtime": "2026-07-31T10:01:00"}
        with mock.patch("fupload_cli.dd.detail", return_value=stale), mock.patch(
            "fupload_cli.dd.author_item", return_value=newer
        ):
            self.assertEqual(DD._fresh_detail(mock.MagicMock(), "config", "one")["title"], "Old")

    def test_dd_detail_retries_when_ownership_is_unavailable(self) -> None:
        stale = {"sn": "one", "title": "Old", "game_type": 10001, "mtime": "2026-07-31T10:00:00"}
        fresh = {"sn": "one", "title": "New", "game_type": 10001, "mtime": "2026-07-31T10:01:00"}
        listing = {"share_sn": "one", "title": "New", "game_type": 10001, "mtime": "2026-07-31T10:01:00"}
        with mock.patch("fupload_cli.dd.detail", side_effect=[stale, fresh]), mock.patch(
            "fupload_cli.dd.author_item", side_effect=[{}, listing]
        ), mock.patch("fupload_cli.dd.time.sleep"):
            self.assertEqual(DD._fresh_detail(mock.MagicMock(), "config", "one")["title"], "New")

    def test_dd_content_readback_allows_only_additional_read_only_fields(self) -> None:
        expected = {"material": {"items": [{"name": "Icons"}], "inner_version": {"Icons": 2}}}
        actual = {"material": {
            "items": [{"name": "Icons", "desc": ""}],
            "inner_version": {"Icons": 2},
            "size": 20,
        }}
        _verify_fields(expected, actual, ("material",), "/share/detail")
        actual["material"]["inner_version"]["Icons"] = 1
        with self.assertRaisesRegex(FuploadError, "material"):
            _verify_fields(expected, actual, ("material",), "/share/detail")

    def test_dd_channel_parser_keeps_parent_room_on_nested_channels(self) -> None:
        value = safe_channels({"data": [{
            "teamId": "room", "teamName": "Room",
            "channelList": [{"channelId": "channel", "channelType": "text", "channelName": "General"}],
        }]})
        tuples = {(item["room_id"], item["channel_id"], item["channel_type"]) for item in value["items"]}
        self.assertIn(("room", "", ""), tuples)
        self.assertIn(("room", "channel", "text"), tuples)

    def test_newbee_delete_uses_one_id_and_verifies_author_list(self) -> None:
        provider = NewBee()
        with mock.patch.object(provider, "get_plugin", return_value={"id": 7, "name": "Plugin"}), mock.patch.object(
            provider, "post", return_value={"removed": True}
        ) as post, mock.patch.object(provider, "list_plugins", return_value={"total": 0, "items": []}):
            result = provider.delete("plugin", {"id": 7, "confirm": "DELETE"})
        post.assert_called_once_with("/creator/wow/mod/remove", {"id": 7})
        self.assertTrue(result["deleted"])

    def test_dd_delete_uses_confirmed_sn_body_and_post_readback(self) -> None:
        session = DeleteDDSession()
        result = DD()._delete(session, "plugin", {"sn": "plugin-sn", "confirm": "DELETE"})
        self.assertIn(("post", "/addon/delete", {"sn": "plugin-sn"}), session.calls)
        self.assertTrue(result["deleted"])

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
