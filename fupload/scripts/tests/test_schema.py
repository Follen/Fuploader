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
            logo.write_bytes(b"png")
            value = {
                "schema": schema.name, "name": "Demo", "mod_categories": [1],
                "content_origin": 1, "content_format": 2, "intro": "i", "description": "d",
                "logo_file": str(logo), "public": False,
            }
            self.assertEqual(schema.validate(value)["logo_file"], str(logo))

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
