from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Tuple
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fupload_cli.newbee import NewBee, RELATION_TYPES
from fupload_cli.errors import ValidationError
from fupload_cli.schema import get_schema


MAIN_ENDPOINTS = {
    ("plugin", "create"): "/creator/wow/mod/create",
    ("plugin", "edit"): "/creator/wow/mod/edit",
    ("config", "create"): "/creator/wow/share_config/release",
    ("config", "update"): "/creator/wow/share_config/update",
    ("config", "edit"): "/creator/wow/share_config/update",
    ("wa", "create"): "/creator/wow/wa/publish",
    ("wa", "edit"): "/creator/wow/wa/update",
    ("wa", "update"): "/creator/wow/wa/update_wa_str",
}

OFFICIAL_EFFECTIVE_FIELDS = {
    ("plugin", "create"): {
        "mod_categories", "content_origin", "content_format", "name", "description", "intro",
        "logo", "screenshots", "share_state", "subscribe_plan_level", "link_to_channel",
    },
    ("plugin", "edit"): {
        "id", "mod_categories", "content_origin", "content_format", "name", "description", "intro",
        "logo", "screenshots", "share_state", "subscribe_plan_level", "link_to_channel",
    },
    ("plugin", "update"): {
        "mod_id", "version", "game_version_list", "file", "changelog", "link_to_channel",
    },
    ("config", "create"): {
        "cloud_id", "title", "content", "content_format", "intro", "pic_url", "content_origin",
        "sharing", "link_to_channel", "subscribe_plan_level", "price", "time_range", "linked_mods",
        "ignored_unknown_mods", "ignored_materials", "ignored_fronts", "roleid",
    },
    ("config", "update"): {
        "tid", "cloud_id", "title", "content", "content_format", "intro", "pic_url", "content_origin",
        "sharing", "link_to_channel", "subscribe_plan_level", "price", "time_range", "linked_mods",
        "ignored_unknown_mods", "ignored_materials", "ignored_fronts", "roleid",
    },
    ("config", "edit"): {
        "tid", "cloud_id", "title", "content", "content_format", "intro", "pic_url", "content_origin",
        "sharing", "link_to_channel", "subscribe_plan_level", "price", "time_range", "linked_mods",
        "ignored_unknown_mods", "ignored_materials", "ignored_fronts", "roleid",
    },
    ("wa", "create"): {
        "game_version_id", "name", "intro", "description", "content_format", "thumbnail", "images",
        "category_id_list", "content_origin", "subscribe_plan_level", "price", "time_range", "share_state",
        "link_to_channel", "attachments", "wa_str", "wa_str_titles", "wa_log", "string_mode",
    },
    ("wa", "edit"): {
        "id", "game_version_id", "name", "intro", "description", "content_format", "thumbnail", "images",
        "category_id_list", "content_origin", "subscribe_plan_level", "price", "time_range", "share_state",
        "link_to_channel", "attachments", "wa_log",
    },
    ("wa", "update"): {"id", "version", "wa_str", "wa_str_titles", "wa_log", "link_to_channel"},
}

FIELD_ALIASES = {
    ("plugin", "create", "public"): "share_state",
    ("plugin", "edit", "public"): "share_state",
    ("plugin", "create", "logo_file"): "logo",
    ("plugin", "edit", "logo_file"): "logo",
    ("plugin", "create", "screenshot_files"): "screenshots",
    ("plugin", "edit", "screenshot_files"): "screenshots",
    ("config", "create", "id"): "tid",
    ("config", "update", "id"): "tid",
    ("config", "edit", "id"): "tid",
    ("config", "create", "picture_urls"): "pic_url",
    ("config", "edit", "picture_urls"): "pic_url",
    ("config", "create", "picture_files"): "pic_url",
    ("config", "edit", "picture_files"): "pic_url",
    ("config", "create", "public"): "sharing",
    ("config", "edit", "public"): "sharing",
    ("wa", "create", "public"): "share_state",
    ("wa", "edit", "public"): "share_state",
    ("wa", "create", "thumbnail_file"): "thumbnail",
    ("wa", "edit", "thumbnail_file"): "thumbnail",
    ("wa", "create", "image_files"): "images",
    ("wa", "edit", "image_files"): "images",
}

LOCAL_ONLY_FIELDS = {
    ("plugin", "create", "submit_for_review"),
    ("plugin", "edit", "submit_for_review"),
    ("config", "create", "submit_for_review"),
    ("config", "edit", "submit_for_review"),
    ("wa", "create", "submit_for_review"),
    ("wa", "edit", "submit_for_review"),
    ("plugin", "delete", "confirm"),
    ("config", "delete", "confirm"),
    ("wa", "delete", "confirm"),
}


class RecordingNewBee(NewBee):
    def __init__(self, root: Path) -> None:
        self.root = root
        self.posts = []
        self.next_posts = []
        self.multipart = []
        self.media = []
        self.attachment_uploads = []
        self._plugin_version: Optional[Dict[str, Any]] = None
        self._relations: Dict[str, Any] = {"co_authors": [], "references": []}

    def post(self, endpoint: str, body: Mapping[str, Any]) -> Any:
        payload = copy.deepcopy(dict(body))
        self.posts.append((endpoint, payload))
        if endpoint == "/creator/wow/mod/create":
            return {"mod_id": 101}
        if endpoint == "/creator/wow/share_config/release":
            return {"id": 201}
        if endpoint == "/creator/wow/wa/publish":
            return {"wa_id": 301}
        if endpoint == "/creator/wow/wa/get_next_version":
            return {"version": "2"}
        if endpoint == "/creator/co_author/set":
            self._relations["co_authors"] = copy.deepcopy(payload["co_authors"])
        if endpoint == "/creator/co_author/list":
            return {"list": copy.deepcopy(self._relations["co_authors"])}
        if endpoint == "/creator/content_reference/set":
            self._relations["references"] = copy.deepcopy(payload["references"])
        if endpoint == "/creator/content_reference/list":
            return {"list": copy.deepcopy(self._relations["references"])}
        if endpoint == "/creator/wow/wa_log/latest_str_info":
            return {"version": "2"}
        if endpoint == "/creator/wow/wa_log/list":
            return {"list": [{"id": payload.get("wa_id"), "content": "changed"}]}
        return {}

    def post_next(self, endpoint: str, body: Mapping[str, Any]) -> Any:
        payload = copy.deepcopy(dict(body))
        self.next_posts.append((endpoint, payload))
        return {"shareCode": "fixture-code"}

    def upload(self, endpoint: str, path: str, fields: Optional[Mapping[str, str]] = None) -> Any:
        payload = copy.deepcopy(dict(fields or {}))
        self.multipart.append((endpoint, str(path), payload))
        if endpoint == "/creator/wow/mod_file/upload_mod_file":
            self._plugin_version = {
                "t_display_name": payload["version"],
                "versions": json.loads(payload["game_version_list"]),
            }
        return {"uploaded": True}

    def upload_media(self, endpoint: str, path: str) -> str:
        value = "https://cdn.invalid/media-%d" % (len(self.media) + 1)
        self.media.append((endpoint, str(path), value))
        return value

    def upload_attachment(self, path: str) -> Dict[str, Any]:
        value = {
            "file_id": 0,
            "name": Path(path).name,
            "value": "attachment-index",
            "size": Path(path).stat().st_size,
            "type": "application/zip",
            "timestamp": 0,
            "sha256": "fixture",
        }
        self.attachment_uploads.append((str(path), copy.deepcopy(value)))
        return value

    def categories(self) -> Dict[str, Any]:
        return {"items": [{"id": 10}, {"id": 11}]}

    def game_versions(self) -> Dict[str, Any]:
        return {"items": [{"id": 2, "versions": ["12.1.0", "3.80.2"]}]}

    def content_origins(self) -> Dict[str, Any]:
        return {"items": [{"value": 1}, {"value": 2}]}

    def subscribe_plans(self) -> Dict[str, Any]:
        return {"items": [{"value": 1}, {"value": 2}]}

    def time_ranges(self) -> Dict[str, Any]:
        return {"items": [{"value": "seven_day"}, {"value": "forever"}]}

    def get_plugin_raw(self, ident: int) -> Dict[str, Any]:
        return {
            "t_id": ident,
            "category_ids": [10],
            "t_original": 1,
            "t_content_format": 2,
            "t_name": "Plugin",
            "t_description_v2": "Description",
            "t_description": "Intro",
            "t_logo": "https://cdn.invalid/logo.png",
            "screenshots": ["https://cdn.invalid/screenshot.png"],
            "t_share": 0,
            "t_subscribe_plan_level": 0,
            "t_link_to_channel": False,
        }

    def get_plugin(self, ident: int) -> Dict[str, Any]:
        return {"id": ident}

    def plugin_versions(self, ident: int, page: int = 1, size: int = 100) -> Dict[str, Any]:
        value = self._plugin_version or {"t_display_name": "1.0", "versions": ["3.80.2"]}
        return {"list": [copy.deepcopy(value)]}

    def list_plugins(self, keyword: str, page: int, size: int) -> Dict[str, Any]:
        return {"total": 0, "items": []}

    def get_backup(self, cloud_id: int) -> Dict[str, Any]:
        return {
            "cloud_id": cloud_id,
            "linked_mods": [{
                "mod_id": 10,
                "mod_name": "Plugin",
                "mod_file_id": 20,
                "mod_version": "1.0",
                "display_name": "Plugin 1.0",
                "update_type": 1,
            }],
            "unknown_plugins": ["Unknown"],
            "materials": ["Material"],
            "fonts": ["Font"],
            "roles": [{"role_id": "role-1"}],
        }

    def get_config_raw(self, ident: int) -> Dict[str, Any]:
        backup = self.get_backup(5)
        return {
            "t_id": ident,
            "t_cloudblackid": 5,
            "t_title": "Config",
            "t_content": "Content",
            "t_content_format": 2,
            "t_intro": "Intro",
            "pic_url": ["https://cdn.invalid/config.png"],
            "t_content_origin": 1,
            "t_sharing": 0,
            "t_link_to_channel": False,
            "t_subscribe_plan_level": 0,
            "t_price": 0,
            "t_time_range": "",
            "t_linked_mods": backup["linked_mods"],
            "t_ignored_unknown_mods": ["Unknown"],
            "t_ignored_materials": ["Material"],
            "t_ignored_fronts": ["Font"],
            "t_roleid": "role-1",
        }

    def get_config(self, ident: int) -> Dict[str, Any]:
        return {"id": ident}

    def list_configs(self, keyword: str, offset: int, size: int) -> Dict[str, Any]:
        return {"count": 0, "list": []}

    def get_wa_raw(self, ident: int) -> Dict[str, Any]:
        return {
            "id": ident,
            "game_version_id": 2,
            "name": "WA",
            "intro": "Intro",
            "description": "Description",
            "content_format": 2,
            "thumbnail": "https://cdn.invalid/wa.png",
            "images": ["https://cdn.invalid/wa-detail.png"],
            "category_id_list": [10],
            "content_origin": 1,
            "subscribe_plan_level": 0,
            "price": 0,
            "time_range": "",
            "share_state": 2,
            "link_to_channel": False,
            "attachments": [],
            "t_version": "1",
            "t_wa_str_titles": ["One"],
        }

    def get_wa(self, ident: int) -> Dict[str, Any]:
        return {"id": ident}

    def list_was(self, keyword: str, offset: int, size: int) -> Dict[str, Any]:
        return {"total": 0, "items": []}

    def wa_categories(self, game_version_id: int) -> Dict[str, Any]:
        return {"items": [{"id": 10}, {"id": 11}]}

    def attachment_paths(self) -> Dict[str, Any]:
        return {"items": [{"value": 7, "extract_base_dir": "Interface"}]}

    def latest_wa(self, ident: int) -> Dict[str, Any]:
        return {"version": "2"}


class NewBeeFixtures:
    def __init__(self, root: Path) -> None:
        self.image = root / "展示 图(1)+#%.png"
        self.image.write_bytes(b"image")
        self.package = root / "插件 包(1)+#%.zip"
        self.package.write_bytes(b"package")
        self.attachment = root / "WA 材质(1)+#%.zip"
        self.attachment.write_bytes(b"attachment")

    @staticmethod
    def linked_mods() -> list:
        return [{
            "mod_id": 10,
            "mod_name": "Plugin",
            "mod_file_id": 20,
            "mod_version": "1.0",
            "display_name": "Plugin 1.0",
            "update_type": 1,
        }]

    def document(self, resource: str, action: str) -> Dict[str, Any]:
        schema = get_schema("newbee", resource, action)
        docs = {
            ("plugin", "create"): {
                "name": "Plugin", "mod_categories": [10], "content_origin": 1,
                "content_format": 2, "intro": "Intro", "description": "Description",
                "logo": "https://cdn.invalid/logo.png", "screenshots": ["https://cdn.invalid/shot.png"],
                "public": False,
            },
            ("plugin", "update"): {
                "mod_id": 101, "version": "2.0", "game_version_list": ["3.80.2"],
                "file": str(self.package),
            },
            ("plugin", "edit"): {"id": 101},
            ("plugin-changelog", "edit"): {"file_id": 501, "changelog": "Changed"},
            ("config", "create"): {
                "cloud_id": 5, "title": "Config", "content": "Content", "content_format": 2,
                "intro": "Intro", "picture_urls": ["https://cdn.invalid/config.png"],
                "content_origin": 1, "public": False, "linked_mods": self.linked_mods(),
                "ignored_unknown_mods": ["Unknown"], "ignored_materials": ["Material"],
                "ignored_fronts": ["Font"], "roleid": "role-1",
            },
            ("config", "update"): {"id": 201},
            ("config", "edit"): {"id": 201},
            ("wa", "create"): {
                "game_version_id": 2, "name": "WA", "intro": "Intro", "description": "Description",
                "content_format": 2, "thumbnail": "https://cdn.invalid/wa.png", "images": [],
                "category_id_list": [10], "content_origin": 1, "public": False,
                "wa_str": "!WA:2!fixture", "wa_str_titles": [], "wa_log": "Initial", "string_mode": "single",
            },
            ("wa", "update"): {"id": 301, "wa_str": "!WA:2!changed", "wa_log": "Changed"},
            ("wa", "edit"): {"id": 301},
            ("wa-changelog", "edit"): {"id": 601, "wa_id": 301, "wa_log": "Changed"},
            ("wa-media", "upload"): {"file": str(self.image), "kind": "image"},
            ("wa-share-code", "set"): {"module_id": 301},
        }
        if action == "delete":
            docs[(resource, action)] = {"id": {"plugin": 101, "config": 201, "wa": 301}[resource], "confirm": "DELETE"}
        if action == "set" and resource.endswith("-co-author"):
            docs[(resource, action)] = {"content_id": 101, "co_authors": [{"user_id": 9, "share_percent": 0.25}]}
        if action == "set" and resource.endswith("-reference"):
            docs[(resource, action)] = {"source_id": 101, "references": [{"type": 7, "id": 8}]}
        return {"schema": schema.name, **copy.deepcopy(docs[(resource, action)])}

    def normal_value(self, resource: str, action: str, field: str) -> Any:
        values = {
            "id": 101, "mod_id": 101, "file_id": 501, "content_id": 101,
            "source_id": 101, "module_id": 301, "game_version_id": 2,
            "name": "Changed name", "title": "Changed title", "intro": "Changed intro",
            "description": "Changed description", "content": "Changed content",
            "content_format": 2, "content_origin": 1, "mod_categories": [11],
            "logo": "https://cdn.invalid/new-logo.png", "logo_file": str(self.image),
            "screenshots": ["https://cdn.invalid/new-shot.png"], "screenshot_files": [str(self.image)],
            "public": True, "submit_for_review": True, "subscribe_plan_level": 1,
            "link_to_channel": True, "co_authors": [{"user_id": 9, "share_percent": 0.25}],
            "references": [{"type": 7, "id": 8}], "version": "2.0",
            "game_version_list": ["3.80.2"], "file": str(self.package), "changelog": "Changed",
            "picture_urls": ["https://cdn.invalid/new-config.png"], "picture_files": [str(self.image)],
            "price": 100, "time_range": "seven_day", "cloud_id": 5,
            "linked_mods": self.linked_mods(), "ignored_unknown_mods": ["Unknown"],
            "ignored_materials": ["Material"], "ignored_fronts": ["Font"], "roleid": "role-1",
            "thumbnail": "https://cdn.invalid/new-wa.png", "thumbnail_file": str(self.image),
            "images": ["https://cdn.invalid/new-wa-detail.png"], "image_files": [str(self.image)],
            "category_id_list": [11], "attachments": [{
                "name": "material.zip", "install_type": 7, "install_path": "Interface",
                "value": "attachment-index", "is_compressed": True, "timestamp": 0,
            }],
            "wa_str": "!WA:2!changed", "wa_str_titles": ["One"], "wa_log": "Changed",
            "string_mode": "collection", "wa_id": 301, "kind": "attachment",
            "install_type": 7, "install_path": "Interface", "confirm": "DELETE",
        }
        if field == "file" and resource == "wa-media":
            return str(self.attachment)
        if field == "version" and (resource, action) == ("wa", "update"):
            return "2"
        return copy.deepcopy(values[field])


class NewBeeWireMatrixTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.temp = tempfile.TemporaryDirectory()
        cls.fixtures = NewBeeFixtures(Path(cls.temp.name))

    @classmethod
    def tearDownClass(cls) -> None:
        cls.temp.cleanup()

    def _document_for_field(self, resource: str, action: str, field: str) -> Dict[str, Any]:
        doc = self.fixtures.document(resource, action)
        doc[field] = self.fixtures.normal_value(resource, action, field)
        if field == "public":
            doc["submit_for_review"] = True
        if field == "submit_for_review":
            doc["public"] = True
        if field == "link_to_channel" and action in ("create", "edit") and (resource, action) != ("plugin", "create"):
            doc.update({"public": True, "submit_for_review": True})
        if field == "time_range":
            doc["price"] = 100
        if (resource, action, field) == ("config", "update", "cloud_id"):
            doc.update({
                "linked_mods": self.fixtures.linked_mods(),
                "ignored_unknown_mods": ["Unknown"],
                "ignored_materials": ["Material"],
                "ignored_fronts": ["Font"],
                "roleid": "role-1",
            })
        if field == "string_mode":
            doc["wa_str_titles"] = ["One"]
        if field == "kind" and doc[field] == "attachment":
            doc["file"] = str(self.fixtures.attachment)
        if (resource, action) == ("wa-media", "upload") and field in ("install_type", "install_path"):
            doc["kind"] = "attachment"
            doc["file"] = str(self.fixtures.attachment)
        return doc

    def _execute(self, resource: str, action: str, doc: Dict[str, Any]) -> Tuple[RecordingNewBee, Any]:
        checked = get_schema("newbee", resource, action).validate(doc)
        provider = RecordingNewBee(Path(self.temp.name))
        with mock.patch("fupload_cli.newbee._require_readback"):
            result = provider.execute_write(resource, action, checked)
        return provider, result

    @staticmethod
    def _post(provider: RecordingNewBee, endpoint: str) -> Dict[str, Any]:
        matches = [body for actual, body in provider.posts if actual == endpoint]
        if not matches:
            raise AssertionError("endpoint was not called: %s" % endpoint)
        return matches[0]

    def test_every_schema_field_has_an_explicit_wire_or_local_control_classification(self) -> None:
        classified = 0
        for (platform, resource, action), schema in sorted(get_schema_registry().items()):
            if platform != "newbee":
                continue
            for field in schema.fields:
                with self.subTest(resource=resource, action=action, field=field):
                    self.assertTrue(self._classification(resource, action, field))
                    classified += 1
        self.assertEqual(classified, 162)

    def _classification(self, resource: str, action: str, field: str) -> str:
        key = (resource, action, field)
        if key in LOCAL_ONLY_FIELDS:
            return "local_control"
        if field in ("co_authors", "references"):
            return "relationship"
        if action == "delete":
            return "delete"
        if (resource, action) in MAIN_ENDPOINTS:
            return "main"
        if (resource, action) == ("plugin", "update"):
            return "multipart"
        if (resource, action) in (("plugin-changelog", "edit"), ("wa-changelog", "edit")):
            return "changelog"
        if action == "set" and (resource.endswith("-co-author") or resource.endswith("-reference")):
            return "relationship"
        if (resource, action) == ("wa-share-code", "set"):
            return "share_code"
        if (resource, action) == ("wa-media", "upload"):
            return "media"
        return ""

    def test_every_field_reaches_its_exact_wire_target_or_stays_local(self) -> None:
        count = 0
        for (platform, resource, action), schema in sorted(get_schema_registry().items()):
            if platform != "newbee":
                continue
            for field in schema.fields:
                case_id = "%s.%s.%s" % (resource, action, field)
                doc = self._document_for_field(resource, action, field)
                with self.subTest(case_id=case_id):
                    provider, result = self._execute(resource, action, doc)
                    self._assert_target(provider, result, resource, action, field, doc[field])
                count += 1
        self.assertEqual(count, 162)

    def _assert_target(
        self,
        provider: RecordingNewBee,
        result: Any,
        resource: str,
        action: str,
        field: str,
        value: Any,
    ) -> None:
        key = (resource, action, field)
        if key in LOCAL_ONLY_FIELDS:
            for _endpoint, body in provider.posts:
                self.assertNotIn(field, body)
            return
        if field == "co_authors":
            body = self._post(provider, "/creator/co_author/set")
            self.assertEqual(body["co_authors"], value)
            self.assertEqual(body["content_type"], RELATION_TYPES[resource.split("-")[0]]["co_authors"])
            return
        if field == "references":
            body = self._post(provider, "/creator/content_reference/set")
            self.assertEqual(body["references"], value)
            self.assertEqual(body["source_type"], RELATION_TYPES[resource.split("-")[0]]["references"])
            return
        if action == "delete":
            body = self._post(provider, {
                "plugin": "/creator/wow/mod/remove",
                "config": "/creator/wow/share_config/delete",
                "wa": "/creator/wow/wa/delete",
            }[resource])
            if field == "id":
                self.assertEqual(body, {"id": value})
            else:
                self.assertNotIn("confirm", body)
            return
        if (resource, action) == ("plugin", "update"):
            endpoint, path, fields = provider.multipart[0]
            self.assertEqual(endpoint, "/creator/wow/mod_file/upload_mod_file")
            if field == "file":
                self.assertEqual(path, value)
            elif field == "mod_id":
                self.assertEqual(fields[field], str(value))
            elif field == "game_version_list":
                self.assertEqual(json.loads(fields[field]), value)
            elif field == "link_to_channel":
                self.assertEqual(json.loads(fields[field]), value)
            else:
                self.assertEqual(fields[field], value)
            return
        if (resource, action) in MAIN_ENDPOINTS:
            body = self._post(provider, MAIN_ENDPOINTS[(resource, action)])
            target = FIELD_ALIASES.get(key, field)
            self.assertIn(target, body)
            if field in ("logo_file", "thumbnail_file"):
                self.assertEqual(body[target], provider.media[0][2])
            elif field in ("screenshot_files", "picture_files", "image_files"):
                self.assertIn(provider.media[0][2], body[target])
            elif field == "public":
                expected = 0 if (resource, action) == ("plugin", "create") else 1
                self.assertEqual(body[target], expected)
            elif field == "link_to_channel" and (resource, action) == ("plugin", "create"):
                self.assertFalse(body[target])
            elif field == "linked_mods":
                expected = copy.deepcopy(value)
                for item in expected:
                    item["updateType"] = item.pop("update_type", item.get("updateType", 1))
                self.assertEqual(body[target], expected)
            elif field == "id" and resource == "config":
                self.assertEqual(body[target], value)
            else:
                self.assertEqual(body[target], value)
            return
        if (resource, action) == ("plugin-changelog", "edit"):
            body = self._post(provider, "/creator/wow/mod_file/edit_changelog")
            self.assertEqual(body[field], value)
            return
        if (resource, action) == ("wa-changelog", "edit"):
            if field == "wa_id":
                body = self._post(provider, "/creator/wow/wa_log/list")
                self.assertEqual(body["wa_id"], value)
            else:
                body = self._post(provider, "/creator/wow/wa_log/edit")
                target = "wa_log_id" if field == "id" else "content"
                self.assertEqual(body[target], value)
            return
        if action == "set" and resource.endswith("-co-author"):
            body = self._post(provider, "/creator/co_author/set")
            target = "content_id" if field == "content_id" else "co_authors"
            self.assertEqual(body[target], value)
            return
        if action == "set" and resource.endswith("-reference"):
            body = self._post(provider, "/creator/content_reference/set")
            target = "source_id" if field == "source_id" else "references"
            self.assertEqual(body[target], value)
            return
        if (resource, action) == ("wa-share-code", "set"):
            endpoint, body = provider.next_posts[0]
            self.assertEqual(endpoint, "/bannerserver/ShareCode/Set")
            self.assertEqual(body["moduleId"], value)
            self.assertEqual(body["moduleType"], 3)
            return
        if (resource, action) == ("wa-media", "upload"):
            if field == "file":
                if provider.attachment_uploads:
                    self.assertEqual(provider.attachment_uploads[0][0], value)
                else:
                    self.assertEqual(provider.media[0][1], value)
            elif field == "kind":
                self.assertEqual(bool(provider.attachment_uploads), value == "attachment")
            elif field in ("install_type", "install_path"):
                self.assertEqual(result["attachment"][field], value)
            return
        raise AssertionError("unhandled target: %s.%s.%s" % (resource, action, field))

    def test_remote_display_enrichment_never_enters_newbee_mutations(self) -> None:
        provider = RecordingNewBee(Path(self.temp.name))
        plugin = provider._plugin_form(101, {
            **provider.get_plugin_raw(101),
            "category_ids": [{"id": 10, "name": "display", "children": [{"id": 999}]}],
        })
        config = provider._config_form(201, {
            **provider.get_config_raw(201),
            "t_linked_mods": [{
                **provider.get_backup(5)["linked_mods"][0],
                "remote_display_only": "drop-me",
            }],
            "t_ignored_unknown_mods": [{"name": "Unknown", "preview": "drop-me"}],
        })
        wa = provider._wa_form(301, {
            **provider.get_wa_raw(301),
            "category_id_list": [{"id": 10, "name": "display", "children": [{"id": 999}]}],
            "attachments": [{
                "display_name": "material.zip", "url": "attachment-index", "install_type": 7,
                "install_path": "Interface", "is_compressed": True, "preview": "drop-me",
            }],
        })
        encoded = repr({"plugin": plugin, "config": config, "wa": wa})
        self.assertNotIn("remote_display_only", encoded)
        self.assertNotIn("preview", encoded)
        self.assertNotIn("children", encoded)
        self.assertEqual(plugin["mod_categories"], [10])
        self.assertEqual(wa["category_id_list"], [10])

    def test_main_builder_field_sets_match_fresh_official_ast_extraction(self) -> None:
        cases = []
        plugin_create = self.fixtures.document("plugin", "create")
        plugin_create.update({"subscribe_plan_level": 1, "link_to_channel": True, "public": True, "submit_for_review": True})
        cases.append(("plugin", "create", plugin_create))
        plugin_edit = {"schema": get_schema("newbee", "plugin", "edit").name, "id": 101}
        plugin_edit.update({
            "name": "Edited", "mod_categories": [11], "content_origin": 2, "content_format": 3,
            "intro": "Edited intro", "description": "Edited description", "logo": "logo",
            "screenshots": ["shot"], "public": True, "submit_for_review": True,
            "subscribe_plan_level": 1, "link_to_channel": True,
        })
        cases.append(("plugin", "edit", plugin_edit))
        plugin_update = self.fixtures.document("plugin", "update")
        plugin_update.update({"changelog": "Changed", "link_to_channel": True})
        cases.append(("plugin", "update", plugin_update))
        config_create = self.fixtures.document("config", "create")
        config_create.update({
            "link_to_channel": True, "subscribe_plan_level": 1, "price": 100,
            "time_range": "seven_day", "public": True, "submit_for_review": True,
        })
        cases.append(("config", "create", config_create))
        config_update = {"schema": get_schema("newbee", "config", "update").name, "id": 201, "cloud_id": 5}
        config_update.update({
            "linked_mods": self.fixtures.linked_mods(), "ignored_unknown_mods": ["Unknown"],
            "ignored_materials": ["Material"], "ignored_fronts": ["Font"], "roleid": "role-1",
        })
        cases.append(("config", "update", config_update))
        config_edit = {"schema": get_schema("newbee", "config", "edit").name, "id": 201}
        config_edit.update({
            "title": "Edited", "content": "Edited", "content_format": 3, "intro": "Edited",
            "picture_urls": ["image"], "content_origin": 2, "public": True, "submit_for_review": True,
            "link_to_channel": True, "subscribe_plan_level": 1, "price": 100, "time_range": "seven_day",
        })
        cases.append(("config", "edit", config_edit))
        wa_create = self.fixtures.document("wa", "create")
        wa_create.update({
            "subscribe_plan_level": 1, "price": 100, "time_range": "seven_day",
            "public": True, "submit_for_review": True, "link_to_channel": True,
            "attachments": [{
                "name": "material.zip", "install_type": 7, "install_path": "Interface",
                "value": "attachment-index", "is_compressed": True, "timestamp": 0,
            }],
        })
        cases.append(("wa", "create", wa_create))
        wa_edit = {"schema": get_schema("newbee", "wa", "edit").name, "id": 301}
        wa_edit.update({
            "game_version_id": 2, "name": "Edited", "intro": "Edited", "description": "Edited",
            "content_format": 3, "thumbnail": "image", "images": ["image"], "category_id_list": [11],
            "content_origin": 2, "subscribe_plan_level": 1, "price": 100, "time_range": "seven_day",
            "public": True, "submit_for_review": True, "link_to_channel": True, "attachments": [],
        })
        cases.append(("wa", "edit", wa_edit))
        wa_update = self.fixtures.document("wa", "update")
        wa_update.update({"version": "2", "wa_str_titles": ["One"], "link_to_channel": True})
        cases.append(("wa", "update", wa_update))

        for resource, action, doc in cases:
            with self.subTest(resource=resource, action=action):
                provider, _result = self._execute(resource, action, doc)
                expected = OFFICIAL_EFFECTIVE_FIELDS[(resource, action)]
                if (resource, action) == ("plugin", "update"):
                    endpoint, _path, fields = provider.multipart[0]
                    self.assertEqual(endpoint, "/creator/wow/mod_file/upload_mod_file")
                    actual = set(fields) | {"file"}
                else:
                    actual = set(self._post(provider, MAIN_ENDPOINTS[(resource, action)]))
                self.assertEqual(actual, expected)

    def test_changed_config_backup_requires_complete_descendants_before_any_request(self) -> None:
        schema = get_schema("newbee", "config", "update")
        doc = {"schema": schema.name, "id": 201, "cloud_id": 6}
        provider = RecordingNewBee(Path(self.temp.name))
        with self.assertRaises(ValidationError) as raised:
            checked = schema.validate(doc)
            provider.execute_write("config", "update", checked)
        self.assertEqual(raised.exception.details.get("path"), "$.linked_mods")
        self.assertEqual(provider.posts, [])
        self.assertEqual(provider.media, [])
        self.assertEqual(provider.multipart, [])

    def test_changed_config_backup_rejects_complete_but_stale_descendants_before_mutation(self) -> None:
        class ChangedBackup(RecordingNewBee):
            def get_backup(self, cloud_id: int) -> Dict[str, Any]:
                if cloud_id == 6:
                    return {
                        "cloud_id": 6,
                        "linked_mods": [{
                            "mod_id": 99, "mod_name": "Other", "mod_file_id": 199,
                            "mod_version": "1.0", "display_name": "Other 1.0", "update_type": 1,
                        }],
                        "unknown_plugins": [], "materials": [], "fonts": [], "roles": [],
                    }
                return super().get_backup(cloud_id)

        schema = get_schema("newbee", "config", "update")
        doc = schema.validate({
            "schema": schema.name, "id": 201, "cloud_id": 6,
            "linked_mods": self.fixtures.linked_mods(),
            "ignored_unknown_mods": [], "ignored_materials": [], "ignored_fronts": [], "roleid": "",
        })
        provider = ChangedBackup(Path(self.temp.name))
        with self.assertRaises(ValidationError) as raised:
            provider.execute_write("config", "update", doc)
        self.assertEqual(raised.exception.details.get("path"), "$.linked_mods")
        self.assertFalse(any(endpoint == "/creator/wow/share_config/update" for endpoint, _body in provider.posts))
        self.assertEqual(provider.media, [])

    def test_changed_wa_game_version_rejects_stale_omitted_categories_before_mutation(self) -> None:
        class ChangedGameVersion(RecordingNewBee):
            def game_versions(self) -> Dict[str, Any]:
                return {"items": [{"id": 2, "versions": ["12.1.0"]}, {"id": 3, "versions": ["11.2.7"]}]}

            def wa_categories(self, game_version_id: int) -> Dict[str, Any]:
                return {"items": [{"id": 20 if game_version_id == 3 else 10}]}

        schema = get_schema("newbee", "wa", "edit")
        doc = schema.validate({"schema": schema.name, "id": 301, "game_version_id": 3})
        provider = ChangedGameVersion(Path(self.temp.name))
        with self.assertRaises(ValidationError) as raised:
            provider.execute_write("wa", "edit", doc)
        self.assertEqual(raised.exception.details.get("path"), "$.category_id_list")
        self.assertFalse(any(endpoint == "/creator/wow/wa/update" for endpoint, _body in provider.posts))
        self.assertEqual(provider.media, [])

    def test_plugin_update_rejects_stale_build_before_multipart_upload(self) -> None:
        schema = get_schema("newbee", "plugin", "update")
        doc = self.fixtures.document("plugin", "update")
        doc["game_version_list"] = ["missing-build"]
        checked = schema.validate(doc)
        provider = RecordingNewBee(Path(self.temp.name))
        with self.assertRaises(ValidationError) as raised:
            provider.execute_write("plugin", "update", checked)
        self.assertEqual(raised.exception.details.get("path"), "$.game_version_list")
        self.assertEqual(provider.multipart, [])


def get_schema_registry():
    from fupload_cli.schema import SCHEMAS

    return SCHEMAS


if __name__ == "__main__":
    unittest.main()
