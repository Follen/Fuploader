from __future__ import annotations

import tempfile
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fupload_cli.errors import ValidationError
from fupload_cli.schema import SCHEMAS, Field, Schema, get_schema


class SchemaTests(unittest.TestCase):
    def test_all_primary_write_actions_exist(self) -> None:
        for platform in ("newbee", "dd"):
            for resource in ("plugin", "config", "wa"):
                for action in ("create", "update", "edit"):
                    self.assertIn((platform, resource, action), SCHEMAS)

    def test_dd_action_field_matrix_matches_official_form_surfaces(self) -> None:
        commercial = {
            "scope", "share_code_life_type", "need_buy", "price_fen", "buy_life_type",
            "jump_room", "room_id", "channel_id", "channel_type", "sync_room",
            "creation_statement", "with_associate", "associated_acts", "need_anchor_vip", "vip_levels",
        }
        plugin_meta = {
            "game_type", "addon_type", "name", "description", "logo", "logo_file",
            "detail_imgs", "detail_img_files", "primary_category_id", "second_category_ids", "html_desc",
        } | commercial
        plugin_version = {"game_versions", "detail_url", "file", "release_type", "version", "update_desc"}
        config_meta = {"title", "brief_desc", "desc", "display_imgs", "display_img_files"} | commercial
        config_content = {
            "backup_sn", "update_desc", "known_addon_ids", "known_addon_update_ids",
            "unknown_addon_ids", "unknown_addon_update_ids", "wtf_role_ids",
            "material_names", "material_update_names", "font_names", "font_update_names",
            "known_wa_ids", "known_wa_update_ids", "unknown_wa_ids", "unknown_wa_update_ids",
            "retail_ui_config",
        }
        wa_meta = {
            "game_type", "name", "game_version", "brief_desc", "display_imgs",
            "display_img_files", "category_ids", "desc",
        } | commercial
        wa_content = {"content", "update_desc", "version", "with_file", "file", "file_install_path"}
        expected = {
            ("plugin", "create"): plugin_meta | plugin_version,
            ("plugin", "update"): {"sn"} | plugin_version,
            ("plugin", "edit"): {"sn"} | commercial,
            ("config", "create"): config_meta | config_content,
            ("config", "update"): {"share_sn"} | config_content,
            ("config", "edit"): {"share_sn"} | config_meta,
            ("wa", "create"): wa_meta | wa_content,
            ("wa", "update"): {"sn"} | wa_content,
            ("wa", "edit"): {"sn"} | wa_meta,
        }
        for key, fields in expected.items():
            with self.subTest(resource=key[0], action=key[1]):
                self.assertEqual(set(get_schema("dd", *key).fields), fields)
        for resource in ("plugin", "config", "wa"):
            self.assertEqual(
                set(get_schema("dd", resource, "delete").fields),
                {"sn", "confirm_delete"},
            )

    def test_unknown_field_is_rejected(self) -> None:
        schema = get_schema("newbee", "plugin", "edit")
        with self.assertRaisesRegex(ValidationError, "unknown field"):
            schema.validate({"schema": schema.name, "id": 1, "surprise": True})

    def test_omission_and_false_are_distinct(self) -> None:
        schema = get_schema("newbee", "plugin", "edit")
        omitted = schema.validate({"schema": schema.name, "id": 1})
        explicit = schema.validate({"schema": schema.name, "id": 1, "link_to_channel": False})
        self.assertNotIn("link_to_channel", omitted)
        self.assertIs(explicit["link_to_channel"], False)

    def test_newbee_main_records_accept_complete_relationship_replacements(self) -> None:
        for resource, action, identifier in (("plugin", "edit", "id"), ("config", "edit", "id"), ("wa", "edit", "id")):
            with self.subTest(resource=resource):
                schema = get_schema("newbee", resource, action)
                value = schema.validate({
                    "schema": schema.name, identifier: 1,
                    "co_authors": [{"user_id": 2, "share_percent": 0.5}],
                    "references": [{"type": 3, "id": 4}],
                })
                self.assertEqual(value["references"][0]["id"], 4)
                with self.assertRaisesRegex(ValidationError, "positive integer"):
                    schema.validate({
                        "schema": schema.name, identifier: 1,
                        "references": [{"type": 3, "id": 0}],
                    })

    def test_public_requires_explicit_review_intent(self) -> None:
        schema = get_schema("newbee", "plugin", "edit")
        with self.assertRaisesRegex(ValidationError, "submit_for_review"):
            schema.validate({"schema": schema.name, "id": 1, "public": True})

    def test_config_backup_change_requires_all_selections(self) -> None:
        schema = get_schema("newbee", "config", "update")
        with self.assertRaisesRegex(ValidationError, "linked_mods"):
            schema.validate({"schema": schema.name, "id": 1, "cloud_id": 2})

    def test_local_file_alternative(self) -> None:
        schema = get_schema("newbee", "plugin", "create")
        with tempfile.TemporaryDirectory() as directory:
            logo = Path(directory) / "logo.png"
            screenshot = Path(directory) / "screenshot.png"
            logo.write_bytes(b"png")
            screenshot.write_bytes(b"png")
            value = {
                "schema": schema.name, "name": "Demo", "mod_categories": [1],
                "content_origin": 1, "content_format": 2, "intro": "i", "description": "d",
                "logo_file": str(logo), "screenshot_files": [str(screenshot)], "public": False,
            }
            self.assertEqual(schema.validate(value)["logo_file"], str(logo))

    def test_present_local_file_controls_reject_empty_paths(self) -> None:
        cases = (
            ("newbee", "plugin", "update", {
                "mod_id": 1, "version": "2", "game_version_list": ["3.80.2"], "file": "",
            }),
            ("newbee", "wa-media", "upload", {"file": "", "kind": "image"}),
            ("dd", "wa", "update", {
                "sn": "wa", "content": "plain", "update_desc": "update",
                "version": "2", "with_file": False, "file": "",
            }),
        )
        for platform, resource, action, fields in cases:
            with self.subTest(platform=platform, resource=resource, action=action):
                schema = get_schema(platform, resource, action)
                with self.assertRaises(ValidationError) as raised:
                    schema.validate({"schema": schema.name, **fields})
                self.assertEqual(raised.exception.details.get("path"), "$.file")

    def test_newbee_cloud_id_must_be_positive(self) -> None:
        schema = get_schema("newbee", "config", "create")
        with self.assertRaises(ValidationError) as raised:
            schema.validate({
                "schema": schema.name,
                "cloud_id": 0,
                "title": "Config",
                "content": "Content",
                "content_format": 2,
                "content_origin": 1,
                "public": False,
                "linked_mods": [],
                "ignored_unknown_mods": [],
                "ignored_materials": [],
                "ignored_fronts": [],
                "roleid": "",
                "picture_urls": ["image"],
            })
        self.assertEqual(raised.exception.details.get("path"), "$.cloud_id")

    def test_newbee_plugin_create_requires_a_screenshot(self) -> None:
        schema = get_schema("newbee", "plugin", "create")
        with self.assertRaisesRegex(ValidationError, "screenshots"):
            schema.validate({
                "schema": schema.name, "name": "Demo", "mod_categories": [1],
                "content_origin": 1, "content_format": 2, "intro": "i", "description": "d",
                "logo": "image", "public": False,
            })

    def test_newbee_plugin_update_uses_build_strings(self) -> None:
        schema = get_schema("newbee", "plugin", "update")
        with tempfile.TemporaryDirectory() as directory:
            package = Path(directory) / "package.zip"
            package.write_bytes(b"zip")
            value = {
                "schema": schema.name, "mod_id": 1, "version": "2",
                "game_version_list": ["3.80.2"], "file": str(package),
            }
            self.assertEqual(schema.validate(value)["game_version_list"], ["3.80.2"])
            value["game_version_list"] = [4]
            with self.assertRaisesRegex(ValidationError, "game-version strings"):
                schema.validate(value)

    def test_delete_requires_literal_confirmation(self) -> None:
        for platform, identifier in (("newbee", {"id": 1}), ("dd", {"sn": "one"})):
            for resource in ("plugin", "config", "wa"):
                schema = get_schema(platform, resource, "delete")
                if platform == "dd":
                    value = {"schema": schema.name, **identifier, "confirm_delete": True}
                    self.assertTrue(schema.validate(value)["confirm_delete"])
                    value["confirm_delete"] = False
                else:
                    value = {"schema": schema.name, **identifier, "confirm": "DELETE"}
                    self.assertEqual(schema.validate(value)["confirm"], "DELETE")
                    value["confirm"] = "yes"
                with self.assertRaises(ValidationError):
                    schema.validate(value)

    def test_dd_room_only_channel_is_valid(self) -> None:
        schema = get_schema("dd", "wa", "edit")
        value = {
            "schema": schema.name, "sn": "wa", "jump_room": True,
            "room_id": "room", "channel_id": "", "channel_type": "",
        }
        self.assertEqual(schema.validate(value)["room_id"], "room")
        value["channel_id"] = "channel"
        with self.assertRaisesRegex(ValidationError, "both be empty or both be nonempty"):
            schema.validate(value)

    def test_dd_contract_enums_limits_and_counts(self) -> None:
        plugin = get_schema("dd", "plugin", "edit")
        base = {"schema": plugin.name, "sn": "plugin"}
        for field, invalid in (("addon_type", 2), ("creation_statement", "translated")):
            with self.subTest(field=field), self.assertRaises(ValidationError):
                plugin.validate({**base, field: invalid})
        with self.assertRaisesRegex(ValidationError, "unknown field"):
            plugin.validate({**base, "description": "create-only"})
        self.assertEqual(
            plugin.validate({**base, "scope": "private", "creation_statement": "original"})["scope"],
            "private",
        )
        config = get_schema("dd", "config", "edit")
        with self.assertRaisesRegex(ValidationError, "0 or between"):
            config.validate({"schema": config.name, "share_sn": "config", "price_fen": 9})
        wa = get_schema("dd", "wa", "edit")
        with self.assertRaisesRegex(ValidationError, "at most 5"):
            wa.validate({"schema": wa.name, "sn": "wa", "category_ids": [1, 2, 3, 4, 5, 6]})

    def test_dd_commercial_conditionals(self) -> None:
        schema = get_schema("dd", "wa", "edit")
        with self.assertRaisesRegex(ValidationError, "room_id"):
            schema.validate({"schema": schema.name, "sn": "abc", "jump_room": True})

    def test_dd_paid_zero_price_and_empty_vip_levels_match_official_submit_validation(self) -> None:
        schema = get_schema("dd", "wa", "edit")
        value = schema.validate({
            "schema": schema.name,
            "sn": "wa",
            "scope": "public",
            "need_buy": True,
            "price_fen": 0,
            "buy_life_type": "seven_day",
            "need_anchor_vip": True,
            "vip_levels": [],
        })
        self.assertEqual(value["price_fen"], 0)
        self.assertEqual(value["vip_levels"], [])

    def test_newbee_wa_create_requires_nonempty_description(self) -> None:
        schema = get_schema("newbee", "wa", "create")
        value = {
            "schema": schema.name,
            "game_version_id": 2,
            "name": "WA",
            "description": "",
            "content_format": 2,
            "thumbnail": "image",
            "category_id_list": [1],
            "content_origin": 1,
            "public": False,
            "wa_str": "!WA:2!demo",
            "wa_log": "initial",
            "string_mode": "single",
        }
        with self.assertRaises(ValidationError) as raised:
            schema.validate(value)
        self.assertEqual(raised.exception.details.get("path"), "$.description")

    def test_dd_private_create_requires_explicit_lifetime(self) -> None:
        schema = get_schema("dd", "wa", "create")
        value = {
            "schema": schema.name, "game_type": 10001, "scope": "private",
            "name": "WA", "game_version": "12.0.7", "brief_desc": "brief",
            "category_ids": [1], "content": "!WA:2!demo", "desc": "desc",
            "update_desc": "log", "version": "1", "creation_statement": "original",
            "with_file": False, "need_buy": False, "jump_room": False,
            "with_associate": False, "need_anchor_vip": False,
            "display_imgs": ["img"],
        }
        with self.assertRaisesRegex(ValidationError, "share_code_life_type"):
            schema.validate(value)
        value["share_code_life_type"] = "forever"
        self.assertEqual(schema.validate(value)["share_code_life_type"], "forever")

    def test_dd_private_paid_config_create_allows_omitted_lifetime(self) -> None:
        schema = get_schema("dd", "config", "create")
        value = {
            "schema": schema.name, "scope": "private", "backup_sn": "backup",
            "title": "Config", "brief_desc": "brief", "desc": "description",
            "display_imgs": ["image"],
            "creation_statement": "original", "known_addon_ids": [],
            "unknown_addon_ids": [], "wtf_role_ids": [], "material_names": [],
            "font_names": [], "known_wa_ids": [], "unknown_wa_ids": [],
            "need_buy": True, "price_fen": 10, "buy_life_type": "seven_day",
            "jump_room": False, "with_associate": False, "need_anchor_vip": False,
        }
        self.assertNotIn("share_code_life_type", schema.validate(value))

    def test_dd_wa_versions_require_digits_only(self) -> None:
        schema = get_schema("dd", "wa", "update")
        base = {
            "schema": schema.name, "sn": "wa", "content": "!WA:2!demo",
            "update_desc": "update", "version": "12", "with_file": False,
        }
        self.assertEqual(schema.validate(base)["version"], "12")
        for invalid in ("1.2", "v2", "2-beta"):
            with self.subTest(version=invalid), self.assertRaisesRegex(ValidationError, "digits only"):
                schema.validate({**base, "version": invalid})

    def test_dd_retail_config_rejects_raw_objects(self) -> None:
        schema = get_schema("dd", "config", "update")
        value = {
            "schema": schema.name,
            "share_sn": "config",
            "backup_sn": "backup",
            "update_desc": "update",
            "retail_ui_config": {"edit_mode": {"account": [{"import_string": "secret"}]}},
        }
        with self.assertRaises(ValidationError) as raised:
            schema.validate(value)
        self.assertEqual(raised.exception.details.get("path"), "$.retail_ui_config.edit_mode")

    def test_dd_retail_config_validates_selector_types(self) -> None:
        schema = get_schema("dd", "config", "update")
        value = {
            "schema": schema.name,
            "share_sn": "config",
            "backup_sn": "backup",
            "update_desc": "update",
            "retail_ui_config": {"edit_mode_selectors": [1]},
        }
        with self.assertRaises(ValidationError) as raised:
            schema.validate(value)
        self.assertEqual(raised.exception.details.get("path"), "$.retail_ui_config.edit_mode_selectors[0]")

    def test_dd_config_rejects_non_scalar_selection_items(self) -> None:
        schema = get_schema("dd", "config", "update")
        value = {
            "schema": schema.name,
            "share_sn": "config",
            "backup_sn": "backup",
            "update_desc": "update",
            "known_addon_ids": [{"addon_id": 1}],
        }
        with self.assertRaises(ValidationError) as raised:
            schema.validate(value)
        self.assertEqual(raised.exception.details.get("path"), "$.known_addon_ids[0]")

    def test_dd_config_allows_only_one_wtf_role(self) -> None:
        schema = get_schema("dd", "config", "update")
        value = {
            "schema": schema.name,
            "share_sn": "config",
            "backup_sn": "backup",
            "update_desc": "update",
            "wtf_role_ids": ["role-a", "role-b"],
        }
        with self.assertRaises(ValidationError) as raised:
            schema.validate(value)
        self.assertEqual(raised.exception.details.get("path"), "$.wtf_role_ids")

    def test_dd_text_limits_match_the_official_forms(self) -> None:
        cases = (
            ("config", "create", "title", 40),
            ("config", "edit", "brief_desc", 50),
            ("plugin", "create", "name", 80),
            ("plugin", "update", "update_desc", 1000),
            ("wa", "create", "name", 40),
            ("wa", "update", "version", 80),
        )
        for resource, action, field, limit in cases:
            with self.subTest(resource=resource, action=action, field=field):
                schema = get_schema("dd", resource, action)
                self.assertEqual(schema.fields[field].max_length, limit)

        schema = Schema("limit-test", {"value": Field("string", max_length=3)})
        with self.assertRaises(ValidationError) as raised:
            schema.validate({"schema": "limit-test", "value": "xxxx"})
        self.assertEqual(raised.exception.details.get("path"), "$.value")

    def test_dd_wa_version_is_numeric(self) -> None:
        schema = get_schema("dd", "wa", "update")
        value = {
            "schema": schema.name,
            "sn": "wa",
            "content": "plain",
            "update_desc": "update",
            "version": "1.2",
            "with_file": False,
        }
        with self.assertRaises(ValidationError) as raised:
            schema.validate(value)
        self.assertEqual(raised.exception.details.get("path"), "$.version")


if __name__ == "__main__":
    unittest.main()
