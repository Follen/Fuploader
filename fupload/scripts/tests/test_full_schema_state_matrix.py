from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from typing import Any, Dict, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fupload_cli.errors import ValidationError
from fupload_cli.schema import SCHEMAS, Field
from fupload_cli.state_machine import ProjectStateMachine
from tests.test_dd_wire_matrix import WireFixtures
from tests.test_newbee_wire_matrix import NewBeeFixtures


WRONG_TYPES = {
    "string": [],
    "integer": "wrong",
    "number": {},
    "boolean": 1,
    "array": {},
    "object": [],
    "identifier": [],
}

POSITIVE_IDS = {
    "id", "mod_id", "file_id", "content_id", "source_id", "module_id",
    "game_version_id", "cloud_id", "game_type", "primary_category_id",
    "project_id", "parent_file_id", "version_id",
}

NESTED_OBJECT_FIELDS = {
    "linked_mods": {"unknown": True},
    "attachments": {"unknown": True},
    "co_authors": {"unknown": True},
    "references": {"unknown": True},
    "associated_acts": {"unknown": True},
}

SCALAR_ARRAY_FIELDS = {
    "mod_categories", "category_id_list", "game_version_list", "screenshots",
    "picture_urls", "images", "screenshot_files", "picture_files", "image_files",
    "ignored_unknown_mods", "ignored_materials", "ignored_fronts", "wa_str_titles",
    "second_category_ids", "vip_levels", "game_versions", "category_ids",
    "detail_imgs", "display_imgs", "detail_img_files", "display_img_files",
    "known_addon_ids", "known_addon_update_ids", "unknown_addon_ids",
    "unknown_addon_update_ids", "wtf_role_ids", "material_names",
    "material_update_names", "font_names", "font_update_names", "known_wa_ids",
    "known_wa_update_ids", "unknown_wa_ids", "unknown_wa_update_ids",
    "game_version_names",
}


class FullSchemaStateMatrixTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.temp = tempfile.TemporaryDirectory()
        root = Path(cls.temp.name)
        (root / "dd").mkdir()
        (root / "newbee").mkdir()
        (root / "curseforge").mkdir()
        (root / "blackbox").mkdir()
        (root / "modus").mkdir()
        cls.dd = WireFixtures(root / "dd")
        cls.newbee = NewBeeFixtures(root / "newbee")
        cls.curseforge_archive = root / "curseforge" / "addon.zip"
        with zipfile.ZipFile(cls.curseforge_archive, "w") as archive:
            archive.writestr("Addon/Addon.toc", "## Interface: 110000\n")
        cls.blackbox_archive = root / "blackbox" / "addon.zip"
        with zipfile.ZipFile(cls.blackbox_archive, "w") as archive:
            archive.writestr("Addon/Addon.toc", "## Interface: 110000\n")
        cls.modus_archive = root / "modus" / "addon.zip"
        with zipfile.ZipFile(cls.modus_archive, "w") as archive:
            archive.writestr("Addon/Addon.toc", "## Interface: 110000\n")
        cls.backup_game = root / "backup-game"
        for relative in ("Interface/AddOns/Chosen", "Interface/Textures", "Fonts", "WTF/Account/Account/Realm/Role"):
            (cls.backup_game / relative).mkdir(parents=True, exist_ok=True)
        (cls.backup_game / "Fonts/font.ttf").write_bytes(b"font")
        cls.backup_packages = {}
        for platform, package_schema in (("newbee", "fupload.newbee.backup-bundle.v1"), ("dd", "fupload.dd.backup-bundle.v1"), ("modus", "config-backup.v2"), ("blackbox", "fupload.blackbox.backup-package.v1")):
            path = root / (platform + "-backup.json")
            path.write_text(json.dumps({"schemaVersion" if platform == "modus" else "schema": package_schema}), encoding="utf-8")
            cls.backup_packages[platform] = str(path)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.temp.cleanup()

    def _document(self, key: Tuple[str, str, str]) -> Dict[str, Any]:
        platform, resource, action = key
        if resource == "backup":
            return self._backup_document(platform, action)
        if platform == "dd":
            return self.dd.document(resource, action)
        if platform == "curseforge":
            return {
                "schema": "fupload.v1.curseforge.plugin.upload",
                "project_id": 1,
                "file": str(self.curseforge_archive),
                "changelog": "notes",
                "game_versions": [1],
                "release_type": "release",
            }
        if platform == "blackbox":
            base = {"schema": "fupload.v1.blackbox.%s.%s" % (resource, action)}
            if resource == "session":
                if action == "login-start":
                    base["method"] = "wechat"
                elif action == "login-submit":
                    base.update({"login_id": "a" * 32, "code": "123456"})
                elif action == "forget":
                    base["confirm_forget"] = True
            elif resource == "plugin" and action == "edit":
                base.update({"id": 101149612})
            elif resource == "plugin" and action == "update":
                base.update({"module_id": 101149612, "name": "TapTool", "type": 1,
                             "game_versions": ["11.2.0"], "file": str(self.blackbox_archive)})
            elif resource == "version" and action == "edit":
                base.update({"version_id": 191150996, "module_id": 101149612, "name": "TapTool",
                             "type": 1, "game_versions": ["11.2.0"]})
            elif resource == "version" and action == "delete":
                base.update({"version_id": 191150996, "module_id": 101149612})
            elif resource == "config":
                if action == "delete":
                    base.update({"share_id": "share", "confirm_delete": True})
                elif action == "create":
                    base.update({"backup_id": "backup", "configuration": {"Title": "Fixture", "Article": "<p>Original</p>", "Open": False,
                                 "KnownAddons": [], "UnknownAddons": {"Files": []}, "WTFList": [], "Materials": {"Files": []},
                                 "Fonts": {"Files": []}, "ThumbList": [], "SubscribeLevel": 0}})
                else:
                    base.update({"share_id": "share", "configuration": {"Article": "<p>Changed</p>", "KnownAddons": [],
                                 "UnknownAddons": {"Files": []}, "WTFList": [], "Materials": {"Files": []}, "Fonts": {"Files": []}}})
            elif resource == "wa":
                if action == "delete":
                    base.update({"slug": "fixture-slug", "strappid": "wowretail", "confirm_delete": True})
                else:
                    base["scope"] = "public"
                    base["configuration"] = {"strappid": "wowretail", "open": True, "subscribeLevel": 0}
                    if action == "create":
                        base["configuration"].update({"name": "Fixture", "categories": ["gen0"],
                            "screens": [{"src": "https://cdn.invalid/fixture.png", "thumb": "https://cdn.invalid/fixture.png"}],
                            "encoded": "!WA:2!synthetic-schema-fixture"})
                    else:
                        base["slug"] = "fixture-slug"
            return base
        if platform == "modus":
            base = {"schema": "fupload.v1.modus.%s.%s" % (resource, action)}
            if resource == "project" and action == "create":
                base["project_state"] = self._modus_project_state()
            elif resource == "project" and action == "edit":
                base.update({"project_id": 200000001, "project_state": self._modus_project_state()})
            elif resource == "project" and action == "delete":
                base.update({"project_id": 200000001, "confirm": "DELETE"})
            elif resource == "plugin" and action in ("create", "upload"):
                base.update({"project_id": 200000001, "file": str(self.modus_archive), "version": "1.0.0",
                             "type": "release", "supported_game_versions": [
                                 {"gameVersion": "12.1.0", "server": "wow_retail"}
                             ]})
            elif resource == "plugin" and action in ("update", "edit"):
                base.update({"project_id": 200000001, "file_id": 2, "version": "1.0.1",
                             "type": "release", "supported_game_versions": [
                                 {"gameVersion": "12.1.0", "server": "wow_retail"}
                             ]})
            elif resource == "plugin" and action == "delete":
                base.update({"project_id": 200000001, "file_id": 2, "confirm": "DELETE"})
            elif resource == "config":
                if action in ("create", "update", "edit"):
                    base.update({"share_id": "1000000000000001", "addons_id": "1,2", "backup_id": 1,
                                 "content": "<p>fixture content with enough detail</p>", "content_text": "fixture content with enough detail",
                                 "image_url": "https://cdn.invalid/cover.webp", "is_paid": 0,
                                 "is_public": 1, "price": 0, "share_type": 0, "tags": "1",
                                 "title": "Fixture share", "exclude_wtf": 1, "account_name": "",
                                 "role_name": "", "sub_type": 0})
                elif action == "delete":
                    base.update({"share_id": 1, "confirm": "DELETE"})
                elif action == "backup-edit":
                    base.update({"backup_id": 1, "backup_name": "Fixture backup"})
                elif action == "backup-delete":
                    base.update({"backup_id": 1, "confirm": "DELETE"})
            elif resource == "wa":
                if action in ("create", "update", "edit"):
                    base.update({"import_id": 1, "code_text": "SAMPLE", "content": "<p>fixture content with enough detail</p>",
                                 "addons_id": "1512221", "content_text": "fixture content with enough detail", "file_path": "",
                                 "image_url": "https://cdn.invalid/cover.webp", "is_paid": 0, "is_public": 1,
                                 "price": 0, "share_type": 0, "support_addon": "FixtureAddon",
                                 "tags": "1", "title": "Fixture string", "version": "1.0", "sub_type": 0})
                elif action == "delete":
                    base.update({"import_id": 1, "confirm": "DELETE"})
                elif action == "version-publish":
                    base.update({"import_id": 1, "version": "2.0", "code_text": "SAMPLE", "changelog": "notes"})
                elif action == "version-delete":
                    base.update({"version_id": 1, "confirm": "DELETE"})
            if action == "create" and resource in {"config", "wa"}:
                base.pop("share_id" if resource == "config" else "import_id", None)
            return base
        return self.newbee.document(resource, action)

    def _backup_document(self, platform: str, action: str) -> Dict[str, Any]:
        base = {"schema": "fupload.v1.%s.backup.%s" % (platform, action)}
        package_field = "manifest_file" if platform == "modus" else "file" if platform == "blackbox" else "bundle_file"
        if action == "upload":
            return {**base, package_field: self.backup_packages[platform]}
        if action == "delete":
            return {**base, "backup_ids": [1 if platform in ("newbee", "modus") else "opaque"], "confirm_delete": True}
        if action == "rename":
            identity = {"newbee": "id", "dd": "sn", "modus": "backup_id", "blackbox": "backup_id"}[platform]
            return {**base, identity: 1 if platform in ("newbee", "modus") else "opaque", "backup_name" if platform == "modus" else "name": "Fixture"}
        base["output_dir"] = str(Path(self.temp.name) / (platform + "-output"))
        if platform == "modus":
            return {**base, "game_root": str(self.backup_game), "backup_name": "Fixture", "server_type": 0,
                    "addon_names": ["Chosen"], "font_names": ["font.ttf"], "material_names": ["Textures"],
                    "roles": [{"account": "Account", "server": "Realm", "role": "Role"}]}
        if platform == "blackbox":
            return {**base, "game_dir": str(self.backup_game), "strappid": "wowretail", "unknown_addons": ["Chosen"],
                    "fonts": ["font.ttf"], "materials": ["Textures"],
                    "wtf_accounts": [{"name": "Account", "characters": [{"realm": "Realm", "player": "Role"}]}]}
        return {**base, "game_dir": str(self.backup_game), "game_version_id" if platform == "newbee" else "game_type": 1,
                "unknown_plugins" if platform == "newbee" else "addon_names": ["Chosen"], "fonts": ["font.ttf"], "materials": ["Textures"],
                "wtf_accounts": [{"account": "Account", "include_common": False, "roles": [{"server": "Realm", "name": "Role"}]}]}

    @staticmethod
    def _modus_project_state() -> Dict[str, Any]:
        machine = ProjectStateMachine()
        machine.select_game({"id": "wow_retail"})
        machine.submit_basic_info({
            "name": "Fixture",
            "summary": "Schema state matrix fixture",
            "categories": [1800],
            "publish_platforms": ["modus"],
            "required_tier_id": 1,
        })
        machine.submit_license({"type": "All Rights Reserved"})
        return machine.snapshot()

    @staticmethod
    def _path_matches(error: ValidationError, field: str) -> bool:
        path = error.details.get("path") or ""
        return path == "$.%s" % field or path.startswith("$.%s[" % field) or path.startswith("$.%s." % field)

    @staticmethod
    def _adjust(doc: Dict[str, Any], field: str, state: str) -> None:
        if field == "exclude_wtf" and state == "falsy":
            doc["account_name"] = "FixtureAccount"
        if field == "public":
            doc["submit_for_review"] = False
            if state != "omitted":
                doc["public"] = False
        if field == "submit_for_review":
            doc["public"] = False
            if state != "omitted":
                doc["submit_for_review"] = False
        if field in ("price_fen", "buy_life_type") and state == "omitted":
            doc["need_buy"] = False
        if field == "share_code_life_type":
            doc["scope"] = "public"
        if field in ("jump_room", "room_id", "channel_id", "channel_type"):
            doc.update({"sync_room": False, "room_id": "", "channel_id": "", "channel_type": ""})
            if field != "jump_room" or state != "omitted":
                doc["jump_room"] = False
            if state == "omitted":
                doc.pop(field, None)
        if field == "associated_acts":
            doc["with_associate"] = False
        if field == "with_associate" and state == "falsy":
            doc["associated_acts"] = []
        if field == "buy_life_type" and state == "falsy":
            doc["need_buy"] = False
        if field == "cloud_id" and state != "falsy" and "cloud_id" in doc:
            doc.update({
                "linked_mods": [], "ignored_unknown_mods": [], "ignored_materials": [],
                "ignored_fronts": [], "roleid": "",
            })

    @staticmethod
    def _falsy_value(spec: Field) -> Any:
        return {
            "string": "",
            "integer": 0,
            "number": 0,
            "boolean": False,
            "array": [],
            "object": {},
            "identifier": "",
        }[spec.type]

    @staticmethod
    def _falsy_accepted(field: str, spec: Field, schema_name: str) -> bool:
        if spec.type == "string":
            accepted = not spec.nonempty and not spec.local_file and (not spec.choices or "" in spec.choices)
            if schema_name == "fupload.v1.dd.config.update" and field == "update_desc":
                accepted = False
            return accepted
        if spec.type in ("integer", "number"):
            if field in POSITIVE_IDS:
                return False
            if spec.minimum is not None and 0 < spec.minimum:
                return False
            return not spec.choices or 0 in spec.choices
        if spec.type == "boolean":
            return not spec.choices or False in spec.choices
        if spec.type == "array":
            return not spec.nonempty
        if schema_name == "fupload.v1.curseforge.plugin.upload" and field == "relations":
            return False
        return not spec.nonempty

    def test_every_schema_rejects_an_unknown_top_level_field(self) -> None:
        count = 0
        for key, schema in sorted(SCHEMAS.items()):
            doc = self._document(key)
            doc["unexpected_remote_display"] = {"id": 999}
            with self.subTest(schema=schema.name):
                with self.assertRaises(ValidationError) as raised:
                    schema.validate(doc)
                self.assertEqual(raised.exception.details.get("path"), "$.unexpected_remote_display")
            count += 1
        self.assertEqual(count, len(SCHEMAS))

    def test_every_field_rejects_the_wrong_json_type_at_its_own_path(self) -> None:
        count = 0
        for key, schema in sorted(SCHEMAS.items()):
            for field, spec in schema.fields.items():
                doc = self._document(key)
                doc[field] = copy.deepcopy(WRONG_TYPES[spec.type])
                with self.subTest(schema=schema.name, field=field):
                    with self.assertRaises(ValidationError) as raised:
                        schema.validate(doc)
                    self.assertTrue(self._path_matches(raised.exception, field), raised.exception.details)
                count += 1
        self.assertEqual(count, sum(len(schema.fields) for schema in SCHEMAS.values()))

    def test_every_field_has_an_explicit_null_contract(self) -> None:
        count = 0
        for key, schema in sorted(SCHEMAS.items()):
            for field, spec in schema.fields.items():
                doc = self._document(key)
                doc[field] = None
                with self.subTest(schema=schema.name, field=field):
                    if spec.nullable:
                        schema.validate(doc)
                    else:
                        with self.assertRaises(ValidationError) as raised:
                            schema.validate(doc)
                        self.assertTrue(self._path_matches(raised.exception, field), raised.exception.details)
                count += 1
        self.assertEqual(count, sum(len(schema.fields) for schema in SCHEMAS.values()))

    def test_every_field_has_an_explicit_omission_contract(self) -> None:
        count = 0
        for key, schema in sorted(SCHEMAS.items()):
            for field, spec in schema.fields.items():
                doc = self._document(key)
                doc.pop(field, None)
                self._adjust(doc, field, "omitted")
                self._add_alternative(key, doc, field)
                with self.subTest(schema=schema.name, field=field):
                    if spec.required:
                        with self.assertRaises(ValidationError) as raised:
                            schema.validate(doc)
                        self.assertTrue(self._path_matches(raised.exception, field), raised.exception.details)
                    else:
                        schema.validate(doc)
                count += 1
        self.assertEqual(count, sum(len(schema.fields) for schema in SCHEMAS.values()))

    def test_every_field_has_an_explicit_falsy_contract(self) -> None:
        count = 0
        for key, schema in sorted(SCHEMAS.items()):
            for field, spec in schema.fields.items():
                doc = self._document(key)
                doc[field] = copy.deepcopy(self._falsy_value(spec))
                self._adjust(doc, field, "falsy")
                self._add_alternative(key, doc, field)
                accepted = self._falsy_accepted(field, spec, schema.name)
                with self.subTest(schema=schema.name, field=field):
                    if accepted:
                        schema.validate(doc)
                    else:
                        with self.assertRaises(ValidationError) as raised:
                            schema.validate(doc)
                        self.assertTrue(self._path_matches(raised.exception, field), raised.exception.details)
                count += 1
        self.assertEqual(count, sum(len(schema.fields) for schema in SCHEMAS.values()))

    def test_every_nested_object_or_scalar_array_rejects_display_enrichment(self) -> None:
        count = 0
        for key, schema in sorted(SCHEMAS.items()):
            for field in schema.fields:
                if schema.name.startswith("fupload.v1.blackbox."):
                    continue
                if field not in NESTED_OBJECT_FIELDS and field not in SCALAR_ARRAY_FIELDS and field != "retail_ui_config":
                    continue
                doc = self._document(key)
                if field in NESTED_OBJECT_FIELDS:
                    current = copy.deepcopy(doc.get(field) or self._nested_minimum(field))
                    current[0].update(NESTED_OBJECT_FIELDS[field])
                    doc[field] = current
                elif field == "retail_ui_config":
                    doc[field] = {"edit_mode": {"account": [{"import_string": "private"}]}}
                else:
                    doc[field] = [{"id": 999, "name": "display"}]
                with self.subTest(schema=schema.name, field=field):
                    with self.assertRaises(ValidationError) as raised:
                        schema.validate(doc)
                    self.assertTrue(self._path_matches(raised.exception, field), raised.exception.details)
                count += 1
        self.assertEqual(count, nested_case_count())

    @staticmethod
    def _nested_minimum(field: str) -> list:
        return {
            "linked_mods": [{"mod_id": 1}],
            "attachments": [{
                "name": "one.zip", "install_type": 1, "install_path": "Interface",
                "value": "code", "is_compressed": True,
            }],
            "co_authors": [{"user_id": 2, "share_percent": 0.5}],
            "references": [{"type": 1, "id": 2}],
            "associated_acts": [{"sn": "one", "act_type": "addon"}],
        }[field]

    def _add_alternative(self, key: Tuple[str, str, str], doc: Dict[str, Any], field: str) -> None:
        platform, resource, action = key
        if action != "create":
            return
        if resource == "backup" and platform != "modus" and field not in doc and field not in ("bundle_file", "file"):
            # Create has two explicit input modes. An optional generation field
            # may be omitted when an already generated package is selected.
            for generation_field in tuple(doc):
                if generation_field not in ("schema", "name"):
                    doc.pop(generation_field)
            doc["file" if platform == "blackbox" else "bundle_file"] = self.backup_packages[platform]
            return
        alternatives = {
            ("newbee", "plugin", "logo"): ("logo_file", str(self.newbee.image)),
            ("newbee", "plugin", "screenshots"): ("screenshot_files", [str(self.newbee.image)]),
            ("newbee", "config", "picture_urls"): ("picture_files", [str(self.newbee.image)]),
            ("newbee", "wa", "thumbnail"): ("thumbnail_file", str(self.newbee.image)),
            ("dd", "plugin", "logo"): ("logo_file", str(self.dd.image)),
            ("dd", "plugin", "detail_imgs"): ("detail_img_files", [str(self.dd.image)]),
            ("dd", "plugin", "detail_url"): ("file", str(self.dd.plugin_zip)),
            ("dd", "config", "display_imgs"): ("display_img_files", [str(self.dd.image)]),
            ("dd", "wa", "display_imgs"): ("display_img_files", [str(self.dd.image)]),
        }
        alternative = alternatives.get((platform, resource, field))
        if alternative:
            doc[alternative[0]] = alternative[1]


def nested_case_count() -> int:
    return sum(
        1
        for schema in SCHEMAS.values()
        for field in schema.fields
        if not schema.name.startswith("fupload.v1.blackbox.")
        if field in NESTED_OBJECT_FIELDS or field in SCALAR_ARRAY_FIELDS or field == "retail_ui_config"
    )


def generated_case_count() -> int:
    schema_count = len(SCHEMAS)
    field_count = sum(len(schema.fields) for schema in SCHEMAS.values())
    return schema_count + field_count * 4 + nested_case_count()


if __name__ == "__main__":
    unittest.main()
