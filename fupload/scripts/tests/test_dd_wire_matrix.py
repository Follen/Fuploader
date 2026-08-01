from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fupload_cli.dd import DD, config_form, resolve_retail_ui_config, safe_backup_detail
from fupload_cli.errors import ValidationError
from fupload_cli.schema import Field, get_schema


ACTIONS = tuple(
    (resource, action)
    for resource in ("plugin", "config", "wa")
    for action in ("create", "update", "edit", "delete")
)

ENDPOINTS = {
    ("plugin", "create"): "/addon/create",
    ("plugin", "update"): "/addon/modify",
    ("plugin", "edit"): "/addon/modify",
    ("plugin", "delete"): "/addon/delete",
    ("config", "create"): "/share/create",
    ("config", "update"): "/share/modify",
    ("config", "edit"): "/share/modify",
    ("config", "delete"): "/share/delete",
    ("wa", "create"): "/wa/create",
    ("wa", "update"): "/wa/modify",
    ("wa", "edit"): "/wa/modify",
    ("wa", "delete"): "/wa/delete",
}

CONFIG_SELECTION_TARGETS = {
    "known_addon_ids": "known_addon",
    "known_addon_update_ids": "known_addon",
    "unknown_addon_ids": "unknown_addon",
    "unknown_addon_update_ids": "unknown_addon",
    "wtf_role_ids": "wtf",
    "material_names": "material",
    "material_update_names": "material",
    "font_names": "font",
    "font_update_names": "font",
    "known_wa_ids": "known_wa",
    "known_wa_update_ids": "known_wa",
    "unknown_wa_ids": "unknown_wa",
    "unknown_wa_update_ids": "unknown_wa",
}

LOCAL_TARGETS = {
    ("plugin", "logo_file"): "logo",
    ("plugin", "detail_img_files"): "detail_imgs",
    ("plugin", "file"): "detail_url",
    ("config", "display_img_files"): "display_imgs",
    ("wa", "display_img_files"): "display_imgs",
    ("wa", "file"): "file_path",
}


def wire_target(resource: str, field: str) -> Optional[str]:
    if field == "confirm_delete":
        return None
    if (resource, field) in LOCAL_TARGETS:
        return LOCAL_TARGETS[(resource, field)]
    if resource == "config" and field in CONFIG_SELECTION_TARGETS:
        return CONFIG_SELECTION_TARGETS[field]
    return field


class WireSession:
    """Deterministic DD session that records every dependency and wire mutation."""

    def __init__(self, fixtures: "WireFixtures") -> None:
        self.fixtures = fixtures
        self.calls = []
        self.uploads = []
        self.mutations = []
        self.deleted = set()
        self.current = {
            "plugin": fixtures.plugin_current(),
            "config": fixtures.config_current(),
            "wa": fixtures.wa_current(),
        }

    @staticmethod
    def _result(value: Any) -> Dict[str, Any]:
        return {"code": 0, "result": copy.deepcopy(value)}

    def _plugin_projection(self, value: Mapping[str, Any]) -> Dict[str, Any]:
        projected = copy.deepcopy(dict(value))
        children = list(projected.get("second_category_ids") or [])
        if children and children[-1] != 999:
            projected["second_category_ids"] = children + [999]
        projected["latest_version"] = {
            "file_path": projected.get("detail_url"),
            "release_type": projected.get("release_type"),
            "version": projected.get("version"),
            "game_versions": projected.get("game_versions"),
            "update_desc": projected.get("update_desc"),
        }
        return projected

    def _author_rows(self, resource: str) -> list:
        rows = []
        reference = {"plugin": "plugin-sn", "config": "config-sn", "wa": "wa-sn"}[resource]
        if reference not in self.deleted:
            value = self.current[resource]
            rows.append(self._plugin_projection(value) if resource == "plugin" else copy.deepcopy(value))
        if resource == "plugin":
            rows.append({"sn": "assoc-plugin", "name": "Associated plugin", "game_type": 10001})
        elif resource == "config":
            rows.append({"share_sn": "assoc-config", "title": "Associated config", "game_type": 10001})
        else:
            rows.append({"sn": "assoc-wa", "name": "Associated WA", "game_type": 10001})
        return rows

    def get(self, endpoint: str, params: Mapping[str, Any]) -> Dict[str, Any]:
        self.calls.append(("get", endpoint, copy.deepcopy(dict(params))))
        values = {
            "/game_type/list": [{"game_type": 10001}, {"game_type": 10002}],
            "/game_versions/list": [
                {"game_version": "12.1.0"},
                {"game_version": "12.0.0"},
            ],
            "/addon/category": [{
                "id": 10,
                "children": [{"id": 11}, {"id": 12}],
            }],
            "/wa/categories": [{"c_id": "210"}, {"c_id": "211"}],
            "/anchor_vip/level/list": [{"id": 1}, {"id": 2}],
            "/addon/addon_versions": [],
            "/backup/list": [{"sn": "backup-sn", "game_type": 10001}],
            "/backup/detail": self.fixtures.backup,
            "/share/list": self._author_rows("config"),
            "/wa/list": self._author_rows("wa"),
        }
        if endpoint in ("/addon/detail_v2", "/addon/detail"):
            return self._result(self._plugin_projection(self.current["plugin"]))
        if endpoint == "/share/detail":
            return self._result(self.current["config"])
        if endpoint == "/wa/detail":
            return self._result(self.current["wa"])
        return self._result(values.get(endpoint, []))

    def post_read(self, endpoint: str, body: Mapping[str, Any]) -> Dict[str, Any]:
        self.calls.append(("post_read", endpoint, copy.deepcopy(dict(body))))
        if endpoint == "/addon/addon_list":
            rows = self._author_rows("plugin")
        else:
            rows = []
        return self._result({"items": rows, "total": len(rows)})

    def post(self, endpoint: str, body: Mapping[str, Any]) -> Dict[str, Any]:
        payload = json.loads(json.dumps(dict(body), ensure_ascii=True, separators=(",", ":")))
        self.calls.append(("post", endpoint, payload))
        self.mutations.append((endpoint, payload))
        resource = "plugin" if endpoint.startswith("/addon/") else "config" if endpoint.startswith("/share/") else "wa"
        if endpoint.endswith("/delete"):
            self.deleted.add(str(payload["sn"]))
            return self._result({"sn": payload["sn"]})
        reference_name = "share_sn" if resource == "config" else "sn"
        reference = {"plugin": "plugin-sn", "config": "config-sn", "wa": "wa-sn"}[resource]
        payload[reference_name] = reference
        payload["is_owner"] = True
        if resource == "config":
            payload["game_type"] = 10001
        self.current[resource] = payload
        return self._result({reference_name: reference})

    def cc_get(self, url: str) -> Dict[str, Any]:
        self.calls.append(("cc_get", "/v1/mixteammsgproxy/channelList", {"url": url}))
        return {
            "data": [{
                "teamId": "room-1",
                "teamName": "Room",
                "channelList": [{
                    "channelId": "channel-1",
                    "channelType": "text",
                    "channelName": "General",
                }],
            }],
        }

    def call(self, action: str, **values: Any) -> Dict[str, Any]:
        self.calls.append(("call", action, copy.deepcopy(values)))
        if action == "parse_wa":
            return {"parse_wa_uid": "parsed-uid", "parse_wa_id": "parsed-id"}
        raise AssertionError("unexpected native call: %s" % action)

    def upload(self, file: str, business: str, **kwargs: Any) -> str:
        call = {"file": file, "business": business, **copy.deepcopy(kwargs)}
        self.calls.append(("upload", business, call))
        self.uploads.append(call)
        return "https://cdn.invalid/upload-%d" % len(self.uploads)


class WireFixtures:
    def __init__(self, root: Path) -> None:
        self.plugin_zip = root / "插件 包(1)+#%.zip"
        self.wa_zip = root / "WA 材质(1)+#%.zip"
        self.image = root / "展示 图(1)+#%.png"
        self.image_alt = root / "展示 图(2)+#%.jpg"
        self.plugin_zip.write_bytes(b"plugin-zip-bytes")
        self.wa_zip.write_bytes(b"wa-zip-bytes")
        self.image.write_bytes(b"png-bytes")
        self.image_alt.write_bytes(b"jpg-bytes")
        self.backup = {
            "sn": "backup-sn",
            "game_type": 10001,
            "known_addon": {"items": [{"addon_id": 1, "name": "Known"}]},
            "unknown_addon": {"items": [{"name": "Unknown"}]},
            "material": {"items": [{"name": "Material"}]},
            "font": {"items": [{"name": "Font"}]},
            "wtf": {"accounts": [{
                "name": "account-a",
                "servers": [{"name": "realm", "items": [{"role_id": "role-a"}]}],
            }]},
            "known_wa": {"items": [{"id": "known-id", "uid": "known-uid", "name": "Known WA"}]},
            "unknown_wa": {"items": [{"id": "old-id", "uid": "unknown-uid", "name": "Unknown WA"}]},
            "extra": {"wa_account_info": {"account-a": [
                {"id": "known-live", "uid": "known-uid"},
                {"id": "unknown-live", "uid": "unknown-uid"},
            ]}},
            "retail_ui_config": {
                "editMode": {"account-a": [{"name": "Raid", "import_string": "fixture-edit"}]},
                "coolDown": {"account-a": [{
                    "name": "Fire", "spec_tag": 63, "char": "Mage", "realm": "Realm",
                    "import_string": "fixture-cooldown",
                }]},
            },
        }
        safe = safe_backup_detail(self.backup)
        self.wtf_selector = safe["wtf_roles"][0]["selector"]
        self.edit_selector = safe["retail_ui_config"]["edit_modes"][0]["selector"]
        self.cooldown_selector = safe["retail_ui_config"]["cool_down"][0]["selector"]
        self.retail_selection = {
            "edit_mode_selectors": [self.edit_selector],
            "default_edit_mode_selector": self.edit_selector,
            "cool_down_selectors": [self.cooldown_selector],
            "enable_dd_setup_wizard": False,
        }

    @staticmethod
    def commercial() -> Dict[str, Any]:
        return {
            "scope": "public",
            "share_code_life_type": "seven_day",
            "need_buy": True,
            "price_fen": 10,
            "buy_life_type": "seven_day",
            "jump_room": True,
            "room_id": "room-1",
            "channel_id": "channel-1",
            "channel_type": "text",
            "sync_room": True,
            "creation_statement": "original",
            "with_associate": True,
            "associated_acts": [{"sn": "assoc-plugin", "act_type": "addon"}],
            "need_anchor_vip": True,
            "vip_levels": [1],
        }

    def plugin_current(self) -> Dict[str, Any]:
        current = {
            "sn": "plugin-sn",
            "is_owner": True,
            "game_type": 10001,
            "game_versions": ["12.1.0"],
            "addon_type": 0,
            "name": "Plugin",
            "description": "Description",
            "logo": "https://cdn.invalid/logo.png",
            "detail_imgs": ["https://cdn.invalid/detail.png"],
            "primary_category_id": 10,
            "second_category_ids": [11, 999],
            "detail_url": "https://cdn.invalid/plugin.zip",
            "release_type": 1,
            "version": "1",
            "html_desc": "<p>Plugin</p>",
            "update_desc": "Initial",
            **self.commercial(),
        }
        current["associated_acts"] = [{
            **current["associated_acts"][0],
            "cover": "https://cdn.invalid/cover.png", "mtime": "2026-08-01", "name": "Remote plugin",
        }]
        return current

    def config_selections(self) -> Dict[str, Any]:
        return {
            "known_addon_ids": [1],
            "known_addon_update_ids": [],
            "unknown_addon_ids": ["Unknown"],
            "unknown_addon_update_ids": [],
            "wtf_role_ids": [self.wtf_selector],
            "material_names": ["Material"],
            "material_update_names": [],
            "font_names": ["Font"],
            "font_update_names": [],
            "known_wa_ids": ["known-uid"],
            "known_wa_update_ids": [],
            "unknown_wa_ids": ["unknown-uid"],
            "unknown_wa_update_ids": [],
        }

    def config_current(self) -> Dict[str, Any]:
        base = {
            "scope": "public",
            "backup_sn": "backup-sn",
            "title": "Config",
            "brief_desc": "Brief",
            "desc": "Description",
            "update_desc": "Initial",
            "display_imgs": ["https://cdn.invalid/config.png"],
            **self.commercial(),
        }
        value = config_form({}, self.backup, {**base, **self.config_selections()})
        value["retail_ui_config"] = resolve_retail_ui_config(self.backup, {}, self.retail_selection)
        value.update({"share_sn": "config-sn", "is_owner": True, "game_type": 10001})
        value["associated_acts"] = [{
            **value["associated_acts"][0],
            "cover": "https://cdn.invalid/cover.png", "mtime": "2026-08-01", "name": "Remote config",
        }]
        return value

    def wa_current(self) -> Dict[str, Any]:
        current = {
            "sn": "wa-sn",
            "is_owner": True,
            "game_type": 10001,
            "name": "WA",
            "game_version": "12.1.0",
            "brief_desc": "Brief",
            "display_imgs": ["https://cdn.invalid/wa.png"],
            "category_ids": ["210"],
            "content": "!WA:2!fixture",
            "desc": "Description",
            "update_desc": "Initial",
            "version": "1",
            "with_file": True,
            "file_path": "https://cdn.invalid/wa.zip",
            "file_install_path": "Interface/Addons",
            "parse_wa_uid": "old-uid",
            "parse_wa_id": "old-id",
            **self.commercial(),
        }
        current["associated_acts"] = [{
            **current["associated_acts"][0],
            "cover": "https://cdn.invalid/cover.png", "mtime": "2026-08-01", "name": "Remote WA",
        }]
        return current

    def document(self, resource: str, action: str) -> Dict[str, Any]:
        schema = get_schema("dd", resource, action)
        doc: Dict[str, Any] = {"schema": schema.name}
        if action == "delete":
            return {"schema": schema.name, "sn": "%s-sn" % resource, "confirm_delete": True}
        if resource == "plugin" and action == "create":
            doc.update({
                "game_type": 10001, "addon_type": 0, "name": "Plugin create",
                "description": "Description", "logo": "https://cdn.invalid/logo.png",
                "detail_imgs": ["https://cdn.invalid/detail.png"], "primary_category_id": 10,
                "second_category_ids": [11], "detail_url": "https://cdn.invalid/plugin.zip",
                "game_versions": ["12.1.0"], "release_type": 1, "version": "2",
                "html_desc": "<p>Create</p>", "update_desc": "Create",
                **self.commercial(),
            })
        elif resource == "plugin" and action == "update":
            doc.update({
                "sn": "plugin-sn", "game_versions": ["12.0.0"], "release_type": 2,
                "version": "2", "update_desc": "Update", "detail_url": "https://cdn.invalid/plugin-v2.zip",
            })
        elif resource == "plugin":
            doc["sn"] = "plugin-sn"
        elif resource == "config" and action == "create":
            doc.update({
                "backup_sn": "backup-sn", "title": "Config create", "brief_desc": "Brief",
                "desc": "Description", "update_desc": "Create",
                "display_imgs": ["https://cdn.invalid/config.png"],
                "retail_ui_config": copy.deepcopy(self.retail_selection),
                **self.commercial(), **self.config_selections(),
            })
        elif resource == "config" and action == "update":
            doc.update({"share_sn": "config-sn", "backup_sn": "backup-sn", "update_desc": "Update"})
        elif resource == "config":
            doc["share_sn"] = "config-sn"
        elif resource == "wa" and action == "create":
            doc.update({
                "game_type": 10001, "name": "WA create", "game_version": "12.1.0",
                "brief_desc": "Brief", "display_imgs": ["https://cdn.invalid/wa.png"],
                "category_ids": ["210"], "content": "!WA:2!create", "desc": "Description",
                "update_desc": "Create", "version": "2", "with_file": False,
                **self.commercial(),
            })
        elif resource == "wa" and action == "update":
            doc.update({
                "sn": "wa-sn", "content": "!WA:2!update", "update_desc": "Update",
                "version": "2", "with_file": False,
            })
        else:
            doc["sn"] = "wa-sn"
        return doc

    def normal_value(self, resource: str, action: str, field: str) -> Any:
        update_values = {
            "known_addon_update_ids": [1],
            "unknown_addon_update_ids": ["Unknown"],
            "material_update_names": ["Material"],
            "font_update_names": ["Font"],
            "known_wa_update_ids": ["known-uid"],
            "unknown_wa_update_ids": ["unknown-uid"],
        }
        if field in update_values:
            return copy.deepcopy(update_values[field])
        doc = self.document(resource, action)
        if field in doc:
            return copy.deepcopy(doc[field])
        values = {
            "logo_file": str(self.image),
            "detail_img_files": [str(self.image)],
            "display_img_files": [str(self.image)],
            "file": str(self.plugin_zip if resource == "plugin" else self.wa_zip),
            "logo": "https://cdn.invalid/alternate-logo.png",
            "detail_imgs": ["https://cdn.invalid/alternate-detail.png"],
            "display_imgs": ["https://cdn.invalid/alternate-display.png"],
            "detail_url": "https://cdn.invalid/alternate.zip",
            "scope": "public",
            "share_code_life_type": "fourteen_day",
            "need_buy": True,
            "price_fen": 20,
            "buy_life_type": "fourteen_day",
            "jump_room": True,
            "room_id": "room-1",
            "channel_id": "channel-1",
            "channel_type": "text",
            "sync_room": True,
            "creation_statement": "renovate",
            "with_associate": True,
            "associated_acts": [{"sn": "assoc-plugin", "act_type": "addon"}],
            "need_anchor_vip": True,
            "vip_levels": [1],
            "title": "Changed config",
            "brief_desc": "Changed brief",
            "desc": "Changed description",
            "name": "Changed name",
            "game_type": 10001,
            "game_version": "12.0.0",
            "category_ids": [210],
            "content": "!WA:2!changed",
            "update_desc": "Changed update",
            "version": "2",
            "with_file": False,
            "file_install_path": "Interface/Addons",
            "addon_type": 1,
            "description": "Changed description",
            "primary_category_id": 10,
            "second_category_ids": [12],
            "game_versions": ["12.0.0"],
            "release_type": 2,
            "html_desc": "<p>Changed</p>",
            "retail_ui_config": copy.deepcopy(self.retail_selection),
            **self.config_selections(),
        }
        return copy.deepcopy(values[field])

    def alternate_value(self, resource: str, action: str, field: str, spec: Field) -> Any:
        normal = self.normal_value(resource, action, field)
        explicit = {
            "scope": "private",
            "share_code_life_type": "thirty_day",
            "need_buy": False,
            "price_fen": 20000,
            "buy_life_type": "thirty_day",
            "jump_room": False,
            "room_id": "room-1",
            "channel_id": "",
            "channel_type": "",
            "sync_room": False,
            "creation_statement": "second",
            "with_associate": False,
            "associated_acts": [],
            "need_anchor_vip": False,
            "vip_levels": [],
            "addon_type": 1,
            "release_type": 3,
            "version": "3",
            "game_versions": ["12.1.0", "12.0.0"],
            "category_ids": ["210", "211"],
            "second_category_ids": [11, 12],
            "file_install_path": "Interface",
            "with_file": True,
            "wtf_role_ids": [],
            "retail_ui_config": {**copy.deepcopy(self.retail_selection), "enable_dd_setup_wizard": True},
            "logo_file": str(self.image_alt),
            "detail_img_files": [str(self.image_alt)],
            "display_img_files": [str(self.image_alt)],
            "file": str(self.plugin_zip if resource == "plugin" else self.wa_zip),
        }
        if field in explicit:
            return copy.deepcopy(explicit[field])
        if spec.choices:
            choices = [choice for choice in spec.choices if choice != normal]
            if choices:
                return copy.deepcopy(choices[0])
        if spec.type == "string":
            value = "alternate"
            if field == "sn":
                value = "%s-alt-sn" % resource
            elif field == "share_sn":
                value = "config-alt-sn"
            return value
        if spec.type == "integer":
            return int(normal) + 1
        if spec.type == "boolean":
            return not bool(normal)
        if spec.type == "array":
            return list(normal) + copy.deepcopy(list(normal[:1])) if normal else []
        if spec.type == "object":
            return copy.deepcopy(normal)
        raise AssertionError("no alternate value for %s" % field)


class DDWireMatrixTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.temp = tempfile.TemporaryDirectory()
        cls.fixtures = WireFixtures(Path(cls.temp.name))

    @classmethod
    def tearDownClass(cls) -> None:
        cls.temp.cleanup()

    def _execute(self, resource: str, action: str, doc: Dict[str, Any]) -> Tuple[WireSession, Dict[str, Any]]:
        checked = get_schema("dd", resource, action).validate(doc)
        session = WireSession(self.fixtures)
        DD().execute_write_on(session, resource, action, checked)
        self.assertEqual(len(session.mutations), 1)
        endpoint, body = session.mutations[0]
        self.assertEqual(endpoint, ENDPOINTS[(resource, action)])
        return session, body

    def _field_doc(self, resource: str, action: str, field: str) -> Dict[str, Any]:
        doc = self.fixtures.document(resource, action)
        value = self.fixtures.normal_value(resource, action, field)
        doc[field] = value
        if field == "share_code_life_type" and resource == "config":
            doc.update({"scope": "private", "sync_room": False, "need_anchor_vip": False})
        if field in ("jump_room", "room_id", "channel_id", "channel_type", "sync_room"):
            doc.update({"jump_room": True, "room_id": "room-1", "channel_id": "channel-1", "channel_type": "text"})
        if field in ("with_associate", "associated_acts"):
            doc.update({"with_associate": True, "associated_acts": [{"sn": "assoc-plugin", "act_type": "addon"}]})
        if field == "vip_levels":
            doc["need_anchor_vip"] = True
        if field == "need_buy":
            doc.update({"need_buy": True, "price_fen": 20, "buy_life_type": "fourteen_day"})
        if field == "file" and resource == "wa":
            doc.update({"with_file": True, "file_install_path": "Interface/Addons"})
        return doc

    def test_matrix_catalog_covers_every_action_field(self) -> None:
        for resource, action in ACTIONS:
            schema = get_schema("dd", resource, action)
            catalog = {name: wire_target(resource, name) for name in schema.fields}
            with self.subTest(resource=resource, action=action):
                self.assertEqual(set(catalog), set(schema.fields))
                self.assertEqual(len(catalog), len(schema.fields))

    def test_every_field_rejects_invalid_json_type_at_exact_path(self) -> None:
        wrong = {
            "string": [], "integer": "bad", "number": {},
            "boolean": 1, "array": {}, "object": [],
        }
        for resource, action in ACTIONS:
            schema = get_schema("dd", resource, action)
            for field, spec in schema.fields.items():
                case_id = "%s.%s.%s.invalid_type" % (resource, action, field)
                doc = self.fixtures.document(resource, action)
                doc[field] = copy.deepcopy(wrong[spec.type])
                with self.subTest(case_id=case_id):
                    with self.assertRaises(ValidationError) as caught:
                        schema.validate(doc)
                    self.assertEqual(caught.exception.details.get("path"), "$.%s" % field)

    def test_every_field_accepts_an_alternate_valid_schema_value(self) -> None:
        for resource, action in ACTIONS:
            schema = get_schema("dd", resource, action)
            for field, spec in schema.fields.items():
                if field in ("sn", "share_sn", "confirm_delete"):
                    continue
                case_id = "%s.%s.%s.alternate" % (resource, action, field)
                doc = self._field_doc(resource, action, field)
                value = self.fixtures.alternate_value(resource, action, field, spec)
                doc[field] = value
                if field == "scope" and value == "private":
                    doc.update({
                        "share_code_life_type": "fourteen_day", "sync_room": False,
                        "need_anchor_vip": False,
                    })
                if field == "need_buy" and value is False:
                    doc["need_anchor_vip"] = True
                if field == "jump_room" and value is False:
                    doc.update({"room_id": "", "channel_id": "", "channel_type": "", "sync_room": False})
                if field in ("channel_id", "channel_type") and value == "":
                    doc.update({"channel_id": "", "channel_type": ""})
                if field == "with_associate" and value is False:
                    doc["associated_acts"] = []
                if field == "associated_acts" and value == []:
                    doc["with_associate"] = False
                if field == "with_file" and value is True:
                    doc.update({"file": str(self.fixtures.wa_zip), "file_install_path": "Interface/Addons"})
                with self.subTest(case_id=case_id):
                    schema.validate(doc)

    def test_every_applicable_empty_false_zero_and_boundary_schema_state(self) -> None:
        for resource, action in ACTIONS:
            schema = get_schema("dd", resource, action)
            for field, spec in schema.fields.items():
                states = []
                if spec.type == "string":
                    states.append(("empty", "", not spec.nonempty and (not spec.choices or "" in spec.choices)))
                    if resource == "config" and action == "update" and field == "update_desc":
                        states[-1] = ("empty", "", False)
                    if spec.max_length is not None:
                        character = "1" if field == "version" else "x"
                        states.extend((
                            ("max", character * spec.max_length, True),
                            ("over_max", character * (spec.max_length + 1), False),
                        ))
                    if spec.choices:
                        states.append(("invalid_choice", "not-an-official-choice", False))
                elif spec.type == "integer":
                    accepted_zero = field not in ("game_type", "primary_category_id", "release_type")
                    states.append(("zero", 0, accepted_zero))
                    if spec.choices:
                        states.append(("invalid_choice", 999999, False))
                elif spec.type == "boolean":
                    states.append(("false", False, field != "confirm_delete"))
                elif spec.type == "array":
                    states.append(("empty", [], not spec.nonempty))
                    if spec.max_items is not None:
                        if field in ("detail_img_files", "display_img_files"):
                            value = [str(self.fixtures.image)] * spec.max_items
                        elif field == "category_ids":
                            value = ["210"] * spec.max_items
                        else:
                            value = [self.fixtures.normal_value(resource, action, field)[0]] * spec.max_items
                        states.extend((
                            ("max_items", value, True),
                            ("over_max_items", value + [value[0]], False),
                        ))
                for state, value, accepted in states:
                    case_id = "%s.%s.%s.%s" % (resource, action, field, state)
                    doc = self.fixtures.document(resource, action)
                    doc[field] = copy.deepcopy(value)
                    if field in ("price_fen", "buy_life_type") and state == "empty":
                        doc["need_buy"] = False
                    if field == "jump_room" and state == "false":
                        doc.update({"sync_room": False, "room_id": "", "channel_id": "", "channel_type": ""})
                    if field in ("room_id", "channel_id", "channel_type") and state == "empty":
                        doc.update({"jump_room": False, "sync_room": False, "channel_id": "", "channel_type": ""})
                    if field == "associated_acts" and state == "empty":
                        doc["with_associate"] = False
                    if field in ("detail_img_files", "display_img_files") and state in ("max_items", "over_max_items"):
                        counterpart = "detail_imgs" if field == "detail_img_files" else "display_imgs"
                        doc[counterpart] = []
                    alternatives = {
                        ("plugin", "logo"): ("logo_file", str(self.fixtures.image)),
                        ("plugin", "detail_imgs"): ("detail_img_files", [str(self.fixtures.image)]),
                        ("plugin", "detail_url"): ("file", str(self.fixtures.plugin_zip)),
                        ("config", "display_imgs"): ("display_img_files", [str(self.fixtures.image)]),
                        ("wa", "display_imgs"): ("display_img_files", [str(self.fixtures.image)]),
                    }
                    alternative = alternatives.get((resource, field))
                    if action == "create" and state == "empty" and alternative:
                        doc[alternative[0]] = alternative[1]
                    with self.subTest(case_id=case_id):
                        if accepted:
                            schema.validate(doc)
                        else:
                            with self.assertRaises(ValidationError) as caught:
                                schema.validate(doc)
                            path = caught.exception.details.get("path")
                            self.assertTrue(path == "$.%s" % field or path.startswith("$.%s[" % field), path)

    def test_every_field_null_and_omission_contract(self) -> None:
        for resource, action in ACTIONS:
            schema = get_schema("dd", resource, action)
            for field, spec in schema.fields.items():
                for state in ("null", "omitted"):
                    case_id = "%s.%s.%s.%s" % (resource, action, field, state)
                    doc = self.fixtures.document(resource, action)
                    if state == "null":
                        doc[field] = None
                        accepted = spec.nullable
                    else:
                        doc.pop(field, None)
                        accepted = not spec.required
                        if field in ("price_fen", "buy_life_type"):
                            doc["need_buy"] = False
                        if field in ("room_id", "channel_id", "channel_type"):
                            doc.update({"jump_room": False, "sync_room": False})
                            doc.pop("channel_id", None)
                            doc.pop("channel_type", None)
                        if field == "associated_acts":
                            doc["with_associate"] = False
                        alternatives = {
                            ("plugin", "logo"): ("logo_file", str(self.fixtures.image)),
                            ("plugin", "detail_imgs"): ("detail_img_files", [str(self.fixtures.image)]),
                            ("plugin", "detail_url"): ("file", str(self.fixtures.plugin_zip)),
                            ("config", "display_imgs"): ("display_img_files", [str(self.fixtures.image)]),
                            ("wa", "display_imgs"): ("display_img_files", [str(self.fixtures.image)]),
                        }
                        alternative = alternatives.get((resource, field))
                        if action == "create" and alternative:
                            doc[alternative[0]] = alternative[1]
                    with self.subTest(case_id=case_id):
                        if accepted:
                            schema.validate(doc)
                        else:
                            with self.assertRaises(ValidationError) as caught:
                                schema.validate(doc)
                            self.assertEqual(caught.exception.details.get("path"), "$.%s" % field)

    def test_every_field_normal_value_reaches_exact_wire_target(self) -> None:
        for resource, action in ACTIONS:
            schema = get_schema("dd", resource, action)
            for field in schema.fields:
                case_id = "%s.%s.%s.normal" % (resource, action, field)
                doc = self._field_doc(resource, action, field)
                with self.subTest(case_id=case_id):
                    session, body = self._execute(resource, action, doc)
                    target = wire_target(resource, field)
                    if target is None:
                        self.assertNotIn(field, body)
                        continue
                    self.assertIn(target, body)
                    value = doc[field]
                    if (resource, field) in LOCAL_TARGETS:
                        self.assertTrue(
                            body[target] == "https://cdn.invalid/upload-1"
                            or "https://cdn.invalid/upload-1" in body[target]
                        )
                        self.assertEqual(len(session.uploads), 1)
                    elif resource == "config" and field in CONFIG_SELECTION_TARGETS:
                        self.assertIsInstance(body[target], dict)
                        if field.endswith("_update_ids") or field.endswith("_update_names"):
                            reference = str(value[0])
                            expected_version = 1 if action == "create" else 2
                            self.assertEqual(body[target]["inner_version"][reference], expected_version)
                        elif field == "wtf_role_ids":
                            self.assertEqual(
                                body[target]["accounts"][0]["servers"][0]["items"][0]["role_id"],
                                "role-a",
                            )
                        else:
                            self.assertEqual(len(body[target]["items"]), len(value))
                    elif resource == "wa" and field == "category_ids":
                        self.assertEqual(body[target], [str(item) for item in value])
                    elif resource == "config" and field == "need_buy":
                        self.assertEqual(body[target], 1 if value else 0)
                    elif resource == "config" and field == "retail_ui_config":
                        self.assertEqual(
                            body[target],
                            resolve_retail_ui_config(self.fixtures.backup, {}, value),
                        )
                    elif field == "share_code_life_type" and resource in ("plugin", "wa"):
                        self.assertEqual(body[target], "forever")
                    else:
                        self.assertEqual(body[target], value)

    def test_falsy_and_conditional_wire_states_are_not_collapsed(self) -> None:
        cases = (
            ("plugin", "edit", {"sn": "plugin-sn", "jump_room": False}, {
                "jump_room": False, "room_id": "", "channel_id": "", "channel_type": "", "sync_room": False,
            }),
            ("plugin", "edit", {"sn": "plugin-sn", "with_associate": False}, {
                "with_associate": False, "associated_acts": [],
            }),
            ("plugin", "edit", {"sn": "plugin-sn", "need_buy": False, "need_anchor_vip": True, "price_fen": 0}, {
                "need_buy": False, "price_fen": 0, "need_anchor_vip": True,
            }),
            ("config", "edit", {"share_sn": "config-sn", "need_buy": False, "need_anchor_vip": True, "price_fen": 0}, {
                "need_buy": 0, "price_fen": 0, "need_anchor_vip": True,
            }),
            ("wa", "edit", {"sn": "wa-sn", "with_associate": False, "vip_levels": []}, {
                "with_associate": False, "associated_acts": [], "vip_levels": [],
            }),
        )
        for resource, action, values, expected in cases:
            doc = {"schema": get_schema("dd", resource, action).name, **values}
            case_id = "%s.%s.%s" % (resource, action, "+".join(sorted(values)))
            with self.subTest(case_id=case_id):
                session, body = self._execute(resource, action, doc)
                for name, value in expected.items():
                    self.assertIn(name, body)
                    self.assertEqual(body[name], value)
                if values.get("jump_room") is False:
                    self.assertFalse(any(call[0] == "cc_get" for call in session.calls))

    def test_remote_association_objects_are_projected_to_exact_wire_shape(self) -> None:
        expected = [{"sn": "assoc-plugin", "act_type": "addon"}]
        for resource, action in (
            ("plugin", "update"), ("plugin", "edit"),
            ("config", "update"), ("config", "edit"),
            ("wa", "update"), ("wa", "edit"),
        ):
            with self.subTest(resource=resource, action=action):
                _session, body = self._execute(resource, action, self.fixtures.document(resource, action))
                self.assertEqual(body["associated_acts"], expected)

    def test_preflight_rejections_make_zero_uploads_and_zero_mutations(self) -> None:
        cases = (
            ("plugin", "create", "description", "", "$.description"),
            ("plugin", "create", "primary_category_id", 999, "$.primary_category_id"),
            ("config", "update", "wtf_role_ids", ["stale-selector"], "$.wtf_role_ids"),
            ("wa", "create", "category_ids", ["stale-category"], "$.category_ids"),
        )
        for resource, action, field, value, path in cases:
            doc = self.fixtures.document(resource, action)
            doc[field] = value
            session = WireSession(self.fixtures)
            case_id = "%s.%s.%s.preflight_reject" % (resource, action, field)
            with self.subTest(case_id=case_id):
                try:
                    checked = get_schema("dd", resource, action).validate(doc)
                    with self.assertRaises(ValidationError) as caught:
                        DD().execute_write_on(session, resource, action, checked)
                except ValidationError as caught:
                    self.assertEqual(caught.details.get("path"), path)
                else:
                    self.assertEqual(caught.exception.details.get("path"), path)
                self.assertEqual(session.uploads, [])
                self.assertEqual(session.mutations, [])

    def test_config_update_markers_must_reference_selected_items(self) -> None:
        stale_values = {
            "known_addon_update_ids": [999],
            "unknown_addon_update_ids": ["missing-addon"],
            "material_update_names": ["missing-material"],
            "font_update_names": ["missing-font"],
            "known_wa_update_ids": ["missing-known-wa"],
            "unknown_wa_update_ids": ["missing-unknown-wa"],
        }
        schema = get_schema("dd", "config", "update")
        for field, value in stale_values.items():
            doc = self.fixtures.document("config", "update")
            doc[field] = value
            session = WireSession(self.fixtures)
            case_id = "config.update.%s.stale_child" % field
            with self.subTest(case_id=case_id):
                checked = schema.validate(doc)
                with self.assertRaises(ValidationError) as caught:
                    DD().execute_write_on(session, "config", "update", checked)
                self.assertEqual(caught.exception.details.get("path"), "$.%s" % field)
                self.assertEqual(session.uploads, [])
                self.assertEqual(session.mutations, [])

    def test_local_file_arrays_reject_missing_files_at_index_path(self) -> None:
        for resource, action, field in (
            ("plugin", "create", "detail_img_files"),
            ("config", "create", "display_img_files"),
            ("wa", "create", "display_img_files"),
        ):
            doc = self.fixtures.document(resource, action)
            doc[field] = [str(Path(self.temp.name) / "missing.png")]
            case_id = "%s.%s.%s.missing_file" % (resource, action, field)
            with self.subTest(case_id=case_id):
                with self.assertRaises(ValidationError) as caught:
                    get_schema("dd", resource, action).validate(doc)
                self.assertEqual(caught.exception.details.get("path"), "$.%s[0]" % field)

    def test_upload_wire_filename_states_and_special_local_names(self) -> None:
        cases = (
            ("plugin", "create", "logo_file", "", True, "addon"),
            ("plugin", "create", "detail_img_files", "", True, "addon"),
            ("plugin", "update", "file", "addon.zip", False, "addon"),
            ("config", "create", "display_img_files", "omitted", True, "share"),
            ("wa", "create", "display_img_files", "omitted", True, "wa"),
            ("wa", "update", "file", "wa_materials.zip", False, "wa"),
        )
        for resource, action, field, file_name, media, business in cases:
            doc = self._field_doc(resource, action, field)
            case_id = "%s.%s.%s.upload_descriptor" % (resource, action, field)
            with self.subTest(case_id=case_id):
                session, _body = self._execute(resource, action, doc)
                upload = session.uploads[0]
                self.assertEqual(upload["business"], business)
                self.assertEqual(upload.get("media", False), media)
                if file_name == "omitted":
                    self.assertNotIn("file_name", upload)
                else:
                    self.assertEqual(upload.get("file_name"), file_name)
                self.assertIn("(1)+#%", Path(upload["file"]).name)

    def test_delete_wire_body_contains_only_sn_and_readback_is_get_only(self) -> None:
        for resource in ("plugin", "config", "wa"):
            doc = self.fixtures.document(resource, "delete")
            case_id = "%s.delete.body" % resource
            with self.subTest(case_id=case_id):
                session, body = self._execute(resource, "delete", doc)
                self.assertEqual(body, {"sn": "%s-sn" % resource})
                self.assertEqual(len(session.mutations), 1)
                mutation_index = next(i for i, call in enumerate(session.calls) if call[0] == "post")
                self.assertTrue(all(call[0] != "post" for call in session.calls[mutation_index + 1:]))


if __name__ == "__main__":
    unittest.main()
