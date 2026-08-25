"""Versioned write schemas with presence-aware validation."""

from __future__ import annotations

import os
import zipfile
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, Mapping, Optional, Sequence, Tuple

from .errors import ValidationError


JSON_TYPES = {
    "string": (str,),
    "integer": (int,),
    "number": (int, float),
    "boolean": (bool,),
    "array": (list,),
    "object": (dict,),
}


@dataclass(frozen=True)
class Field:
    type: str
    required: bool = False
    nullable: bool = False
    choices: Tuple[Any, ...] = ()
    nonempty: bool = False
    max_length: Optional[int] = None
    max_items: Optional[int] = None
    minimum: Optional[float] = None
    maximum: Optional[float] = None
    local_file: bool = False
    description: str = ""


@dataclass(frozen=True)
class Schema:
    name: str
    fields: Mapping[str, Field]
    conditionals: Tuple[str, ...] = field(default_factory=tuple)

    def validate(self, value: Mapping[str, Any]) -> Dict[str, Any]:
        if not isinstance(value, dict):
            raise ValidationError("input document must be an object")
        unknown = sorted(set(value) - set(self.fields) - {"schema"})
        if unknown:
            raise ValidationError("unknown field(s): %s" % ", ".join(unknown), path="$.%s" % unknown[0])
        actual = value.get("schema")
        if actual != self.name:
            raise ValidationError("schema must be %s" % self.name, path="$.schema")
        for name, spec in self.fields.items():
            if spec.required and name not in value:
                raise ValidationError("field is required", path="$.%s" % name)
            if name not in value:
                continue
            item = value[name]
            if item is None:
                if not spec.nullable:
                    raise ValidationError("null is not allowed", path="$.%s" % name)
                continue
            expected = JSON_TYPES[spec.type]
            # Older Fupload documents used the Creator's display-name
            # license string. Keep that input valid while structured license
            # content is preferred for full-field round trips.
            if self.name.startswith("fupload.v1.modus") and name == "license" and isinstance(item, str):
                continue
            if spec.type in ("integer", "number") and isinstance(item, bool):
                raise ValidationError("expected %s" % spec.type, path="$.%s" % name)
            if not isinstance(item, expected):
                raise ValidationError("expected %s" % spec.type, path="$.%s" % name)
            if spec.nonempty and item in ("", [], {}):
                raise ValidationError("must not be empty", path="$.%s" % name)
            if spec.max_length is not None and len(item) > spec.max_length:
                raise ValidationError(
                    "must contain at most %d characters" % spec.max_length,
                    path="$.%s" % name,
                )
            if spec.max_items is not None and len(item) > spec.max_items:
                raise ValidationError(
                    "must contain at most %d items" % spec.max_items,
                    path="$.%s" % name,
                )
            if spec.minimum is not None and item < spec.minimum:
                raise ValidationError("must be at least %s" % spec.minimum, path="$.%s" % name)
            if spec.maximum is not None and item > spec.maximum:
                raise ValidationError("must be at most %s" % spec.maximum, path="$.%s" % name)
            if spec.choices and item not in spec.choices:
                raise ValidationError(
                    "must be one of: %s" % ", ".join(map(str, spec.choices)),
                    path="$.%s" % name,
                )
            if spec.local_file and (not item or not os.path.isfile(item)):
                raise ValidationError("file does not exist or is not a regular file", path="$.%s" % name)
        checked = dict(value)
        self._validate_conditionals(checked)
        return checked

    def _validate_conditionals(self, value: Dict[str, Any]) -> None:
        if self.name in ("fupload.v1.modus.project.create", "fupload.v1.modus.project.edit"):
            snapshot = value.get("project_state")
            if snapshot is None:
                raise ValidationError(
                    "completed project_state is required; submit choose_game, basic_info, then license",
                    path="$.project_state",
                )
            # Keep the persisted form contract in one place. Restoring the
            # snapshot validates every completed prerequisite and its order.
            from .state_machine import COMPLETE, ProjectStateMachine

            machine = ProjectStateMachine.from_snapshot(snapshot)
            if machine.state != COMPLETE:
                raise ValidationError(
                    "project state must be complete before submission",
                    path="$.project_state.state",
                )
        for name in ("id", "project_id", "mod_id", "file_id", "content_id", "source_id", "module_id", "version_id", "game_version_id", "cloud_id"):
            if name in value and isinstance(value[name], int) and value[name] <= 0:
                raise ValidationError("must be greater than zero", path="$.%s" % name)
        if value.get("public") is True and value.get("submit_for_review") is not True:
            raise ValidationError(
                "public=true requires submit_for_review=true",
                path="$.submit_for_review",
            )
        if value.get("submit_for_review") is True and value.get("public") is not True:
            raise ValidationError(
                "submit_for_review=true requires public=true",
                path="$.public",
            )
        if value.get("need_buy") is True:
            for name in ("price_fen", "buy_life_type"):
                if name not in value or value[name] in (None, ""):
                    raise ValidationError("%s is required when need_buy=true" % name, path="$.%s" % name)
        if value.get("jump_room") is True:
            if not value.get("room_id"):
                raise ValidationError("room_id is required when jump_room=true", path="$.room_id")
            has_channel_id = bool(value.get("channel_id"))
            has_channel_type = bool(value.get("channel_type"))
            if has_channel_id != has_channel_type:
                raise ValidationError(
                    "channel_id and channel_type must both be empty or both be nonempty",
                    path="$.channel_id" if not has_channel_id else "$.channel_type",
                )
        if value.get("sync_room") is True:
            if value.get("jump_room") is False:
                raise ValidationError("sync_room=true requires jump_room=true", path="$.jump_room")
            if value.get("scope") == "private":
                raise ValidationError("sync_room=true requires public scope", path="$.scope")
        if value.get("with_associate") is True and not value.get("associated_acts"):
            raise ValidationError("associated_acts must contain at least one item when with_associate=true", path="$.associated_acts")
        if value.get("need_anchor_vip") is True and value.get("scope") == "private":
            raise ValidationError("need_anchor_vip=true requires public scope", path="$.scope")
        if self.name.startswith("fupload.v1.dd.") and self.name.endswith(".create"):
            paid_private_config = self.name == "fupload.v1.dd.config.create" and value.get("need_buy") is True
            if value.get("scope") == "private" and not value.get("share_code_life_type") and not paid_private_config:
                raise ValidationError("share_code_life_type is required when scope=private", path="$.share_code_life_type")
        if self.name in ("fupload.v1.dd.wa.create", "fupload.v1.dd.wa.update") and "version" in value:
            if not value["version"].isdigit():
                raise ValidationError("WA version must contain digits only", path="$.version")
        if value.get("with_file") is True:
            if self.name == "fupload.v1.dd.wa.create" and not value.get("file"):
                raise ValidationError("file is required when with_file=true on create", path="$.file")
            if self.name == "fupload.v1.dd.wa.create" and not value.get("file_install_path"):
                raise ValidationError("required when with_file=true", path="$.file_install_path")
        if value.get("string_mode") == "collection":
            if not value.get("wa_str_titles"):
                raise ValidationError("required for collection mode", path="$.wa_str_titles")
        one_of = []
        if self.name == "fupload.v1.newbee.plugin.create":
            one_of.append(("logo", "logo_file"))
            if not value.get("screenshots") and not value.get("screenshot_files"):
                raise ValidationError("screenshots or screenshot_files must contain at least one image", path="$.screenshots")
        if self.name == "fupload.v1.newbee.config.create":
            one_of.append(("picture_urls", "picture_files"))
        if self.name == "fupload.v1.newbee.wa.create":
            one_of.append(("thumbnail", "thumbnail_file"))
        if self.name == "fupload.v1.dd.plugin.create":
            one_of.extend((("logo", "logo_file"), ("detail_imgs", "detail_img_files"), ("detail_url", "file")))
        if self.name == "fupload.v1.dd.config.create":
            one_of.append(("display_imgs", "display_img_files"))
        if self.name == "fupload.v1.dd.wa.create":
            one_of.append(("display_imgs", "display_img_files"))
        for choices in one_of:
            if not any(value.get(name) for name in choices):
                raise ValidationError("one of %s is required" % ", ".join(choices), path="$.%s" % choices[0])
        if "cloud_id" in value and value.get("cloud_id") is not None and self.name == "fupload.v1.newbee.config.update":
            required = ("linked_mods", "ignored_unknown_mods", "ignored_materials", "ignored_fronts", "roleid")
            for name in required:
                if name not in value:
                    raise ValidationError("%s is required when cloud_id is changed" % name, path="$.%s" % name)
        if self.name == "fupload.v1.dd.config.update" and "backup_sn" in value:
            if not value.get("update_desc"):
                raise ValidationError("update_desc is required for DD config update", path="$.update_desc")
        self._validate_nested(value)

    def _validate_nested(self, value: Mapping[str, Any]) -> None:
        def scalar_array(name: str, expected: Tuple[type, ...], message: str) -> None:
            if name not in value:
                return
            items = value[name]
            if not isinstance(items, list):
                raise ValidationError("expected array", path="$.%s" % name)
            for index, item in enumerate(items):
                if isinstance(item, bool) or not isinstance(item, expected) or (isinstance(item, str) and not item):
                    raise ValidationError(message, path="$.%s[%d]" % (name, index))

        def object_array(name: str, allowed: set[str], required_names: Tuple[str, ...] = ()) -> None:
            if name not in value:
                return
            items = value[name]
            if not isinstance(items, list):
                raise ValidationError("expected array", path="$.%s" % name)
            for index, item in enumerate(items):
                path = "$.%s[%d]" % (name, index)
                if not isinstance(item, dict):
                    raise ValidationError("expected object", path=path)
                unknown = sorted(set(item) - allowed)
                if unknown:
                    raise ValidationError("unknown field(s): %s" % ", ".join(unknown), path=path + "." + unknown[0])
                for required_name in required_names:
                    if required_name not in item:
                        raise ValidationError("field is required", path=path + "." + required_name)

        if self.name.startswith("fupload.v1.newbee"):
            object_array(
                "linked_mods",
                {"mod_id", "mod_name", "mod_file_id", "mod_version", "display_name", "update_type", "updateType"},
                ("mod_id",),
            )
            object_array("attachments", {"name", "install_type", "install_path", "value", "is_compressed", "timestamp"}, ("name", "install_type", "install_path", "value", "is_compressed"))
            object_array("co_authors", {"user_id", "share_percent"}, ("user_id", "share_percent"))
            object_array("references", {"type", "id"}, ("type", "id"))
            if "co_authors" in value:
                total = 0.0
                for index, item in enumerate(value["co_authors"]):
                    share = item["share_percent"]
                    if isinstance(share, bool) or not isinstance(share, (int, float)) or share <= 0 or share > 1:
                        raise ValidationError("share_percent must be in (0,1]", path="$.co_authors[%d].share_percent" % index)
                    if isinstance(item["user_id"], bool) or not isinstance(item["user_id"], int) or item["user_id"] <= 0:
                        raise ValidationError("user_id must be greater than zero", path="$.co_authors[%d].user_id" % index)
                    total += float(share)
                if total > 1.000001:
                    raise ValidationError("co_authors share_percent total may not exceed 1", path="$.co_authors")
            if "references" in value:
                for index, item in enumerate(value["references"]):
                    for name in ("type", "id"):
                        candidate = item[name]
                        if isinstance(candidate, bool) or not isinstance(candidate, int) or candidate <= 0:
                            raise ValidationError("%s must be a positive integer" % name, path="$.references[%d].%s" % (index, name))
            for name in ("mod_categories", "category_id_list"):
                if name in value and any(isinstance(item, bool) or not isinstance(item, int) or item <= 0 for item in value[name]):
                    raise ValidationError("array must contain positive integer IDs", path="$.%s" % name)
            scalar_array("game_version_list", (str,), "array must contain nonempty game-version strings")
            if "game_version_list" in value and any(not item.strip() for item in value["game_version_list"]):
                raise ValidationError("array must contain nonempty game-version strings", path="$.game_version_list")
            for name in (
                "screenshots", "picture_urls", "images", "screenshot_files", "picture_files",
                "image_files", "ignored_unknown_mods", "ignored_materials", "ignored_fronts",
                "wa_str_titles",
            ):
                scalar_array(name, (str,), "array must contain nonempty strings")
        if self.name.startswith("fupload.v1.dd"):
            object_array("associated_acts", {"sn", "act_type"}, ("sn", "act_type"))
            for name in ("second_category_ids", "vip_levels"):
                if name in value and any(isinstance(item, bool) or not isinstance(item, int) for item in value[name]):
                    raise ValidationError("array must contain integer IDs", path="$.%s" % name)
            for name in ("game_type", "primary_category_id"):
                if name in value and value[name] <= 0:
                    raise ValidationError("must be greater than zero", path="$.%s" % name)
            for existing, local in (("detail_imgs", "detail_img_files"), ("display_imgs", "display_img_files")):
                if len(value.get(existing) or []) + len(value.get(local) or []) > 8:
                    raise ValidationError("combined existing and local images may contain at most 8 items", path="$.%s" % local)
            for index, item in enumerate(value.get("associated_acts") or []):
                if not isinstance(item.get("sn"), str) or not item["sn"]:
                    raise ValidationError("expected nonempty string", path="$.associated_acts[%d].sn" % index)
                if item.get("act_type") not in ("addon", "share", "wa"):
                    raise ValidationError("act_type must be addon, share, or wa", path="$.associated_acts[%d].act_type" % index)
            scalar_array("game_versions", (str,), "array must contain nonempty version strings")
            scalar_array("category_ids", (str, int), "array must contain nonempty category IDs")
            for name in ("detail_imgs", "display_imgs", "detail_img_files", "display_img_files"):
                scalar_array(name, (str,), "array must contain nonempty strings")
            for name in ("detail_img_files", "display_img_files"):
                for index, path in enumerate(value.get(name) or []):
                    if not os.path.isfile(path):
                        raise ValidationError(
                            "file does not exist or is not a regular file",
                            path="$.%s[%d]" % (name, index),
                        )
            for name in ("known_addon_ids", "known_addon_update_ids"):
                scalar_array(name, (int,), "array must contain integer addon IDs")
            for name in (
                "unknown_addon_ids", "unknown_addon_update_ids", "wtf_role_ids",
                "material_names", "material_update_names", "font_names", "font_update_names",
                "known_wa_ids", "known_wa_update_ids", "unknown_wa_ids", "unknown_wa_update_ids",
            ):
                scalar_array(name, (str,), "array must contain nonempty strings")
            if len(value.get("wtf_role_ids") or []) > 1:
                raise ValidationError("at most one WTF role may be selected", path="$.wtf_role_ids")
            if "price_fen" in value:
                price = value["price_fen"]
                if price != 0 and not 10 <= price <= 20000:
                    raise ValidationError("price_fen must be 0 or between 10 and 20000", path="$.price_fen")
            if self.name.startswith("fupload.v1.dd.wa") and "version" in value and not value["version"].isdigit():
                raise ValidationError("version must contain digits only", path="$.version")
            if self.name.startswith("fupload.v1.dd.config") and value.get("retail_ui_config") is not None:
                retail = value["retail_ui_config"]
                allowed = {
                    "edit_mode_selectors", "default_edit_mode_selector",
                    "cool_down_selectors", "enable_dd_setup_wizard",
                }
                unknown = sorted(set(retail) - allowed)
                if unknown:
                    raise ValidationError(
                        "unknown field(s): %s" % ", ".join(unknown),
                        path="$.retail_ui_config.%s" % unknown[0],
                    )
                for name in ("edit_mode_selectors", "cool_down_selectors"):
                    if name not in retail:
                        continue
                    if not isinstance(retail[name], list):
                        raise ValidationError("expected array", path="$.retail_ui_config.%s" % name)
                    for index, item in enumerate(retail[name]):
                        if not isinstance(item, str) or not item:
                            raise ValidationError("array must contain nonempty selector strings", path="$.retail_ui_config.%s[%d]" % (name, index))
                if "default_edit_mode_selector" in retail:
                    selector = retail["default_edit_mode_selector"]
                    if selector is not None and (not isinstance(selector, str) or not selector):
                        raise ValidationError("expected nonempty string or null", path="$.retail_ui_config.default_edit_mode_selector")
                if "enable_dd_setup_wizard" in retail and not isinstance(retail["enable_dd_setup_wizard"], bool):
                    raise ValidationError("expected boolean", path="$.retail_ui_config.enable_dd_setup_wizard")
        if self.name == "fupload.v1.curseforge.plugin.upload":
            if not zipfile.is_zipfile(value["file"]):
                raise ValidationError("file must be a valid ZIP archive", path="$.file")
            if "game_versions" in value and any(isinstance(item, bool) or not isinstance(item, int) or item <= 0 for item in value["game_versions"]):
                raise ValidationError("array must contain positive integer IDs", path="$.game_versions")
            if "game_version_names" in value and any(not isinstance(item, str) or not item.strip() for item in value["game_version_names"]):
                raise ValidationError("array must contain nonempty strings", path="$.game_version_names")
            relations = value.get("relations")
            if relations is not None:
                if set(relations) != {"projects"}:
                    unknown = sorted(set(relations) - {"projects"})
                    message = "unknown field(s): %s" % ", ".join(unknown) if unknown else "projects is required"
                    raise ValidationError(message, path="$.relations")
                if not isinstance(relations["projects"], list):
                    raise ValidationError("expected array", path="$.relations.projects")
            for index, relation in enumerate((relations or {}).get("projects") or []):
                if not isinstance(relation, dict):
                    raise ValidationError("expected object", path="$.relations.projects[%d]" % index)
                unknown = sorted(set(relation) - {"slug", "type", "project_id"})
                if unknown:
                    raise ValidationError("unknown field(s): %s" % ", ".join(unknown), path="$.relations.projects[%d].%s" % (index, unknown[0]))
                if not {"slug", "type"}.issubset(relation):
                    raise ValidationError("slug and type are required", path="$.relations.projects[%d]" % index)
                if not isinstance(relation["slug"], str) or not relation["slug"].strip():
                    raise ValidationError("expected nonempty string", path="$.relations.projects[%d].slug" % index)
                if relation["type"] not in ("embeddedLibrary", "incompatible", "optionalDependency", "requiredDependency", "tool"):
                    raise ValidationError("unsupported relation type", path="$.relations.projects[%d].type" % index)
                if "project_id" in relation and (isinstance(relation["project_id"], bool) or not isinstance(relation["project_id"], int) or relation["project_id"] <= 0):
                    raise ValidationError("must be a positive integer", path="$.relations.projects[%d].project_id" % index)
            if "parent_file_id" in value:
                for field_name in ("game_versions", "game_version_names"):
                    if field_name in value:
                        raise ValidationError("must be omitted when parent_file_id is set", path="$.%s" % field_name)
        if self.name.startswith("fupload.v1.blackbox"):
            scalar_array("game_versions", (str,), "array must contain nonempty game-version strings")
            if "game_versions" in value and any(not item.strip() for item in value["game_versions"]):
                raise ValidationError("array must contain nonempty game-version strings", path="$.game_versions")
            if "category_ids" in value and any(isinstance(item, bool) or not isinstance(item, int) or item <= 0 for item in value["category_ids"]):
                raise ValidationError("array must contain positive integer IDs", path="$.category_ids")
            scalar_array("core_folders", (str,), "array must contain nonempty folder names")
            if "core_folders" in value and any(not item.strip() for item in value["core_folders"]):
                raise ValidationError("array must contain nonempty folder names", path="$.core_folders")
            if "file" in value and not zipfile.is_zipfile(value["file"]):
                raise ValidationError("file must be a valid ZIP archive", path="$.file")
        if self.name.startswith("fupload.v1.modus"):
            object_array(
                "supported_game_versions",
                {"gameVersion", "server", "game_version"},
                ("gameVersion", "server"),
            )
            # The Creator UI treats publishing targets as an independent
            # multi-select state: at least one target is required, and ModUs
            # and BigFoot may be selected together.
            if "publish_platforms" in value:
                platforms = value["publish_platforms"]
                if not isinstance(platforms, list):
                    raise ValidationError("expected array", path="$.publish_platforms")
                if not platforms:
                    raise ValidationError("must contain at least one platform", path="$.publish_platforms")
                allowed_platforms = {"modus", "bigfoot"}
                if any(not isinstance(item, str) or item not in allowed_platforms for item in platforms):
                    raise ValidationError("platform must be modus or bigfoot", path="$.publish_platforms")
                if len(set(platforms)) != len(platforms):
                    raise ValidationError("platforms must not contain duplicates", path="$.publish_platforms")
            # A license may be supplied as the desktop client's display name
            # or as its underlying editable content object.
            if "license" in value and isinstance(value["license"], dict):
                license_value = value["license"]
                allowed_license = {"type", "holder", "year", "content"}
                unknown_license = sorted(set(license_value) - allowed_license)
                if unknown_license:
                    raise ValidationError(
                        "unknown field(s): %s" % ", ".join(unknown_license),
                        path="$.license.%s" % unknown_license[0],
                    )
                for name in allowed_license:
                    if name in license_value and license_value[name] is not None:
                        if not isinstance(license_value[name], str):
                            raise ValidationError("expected string or null", path="$.license.%s" % name)
                        if not license_value[name].strip():
                            raise ValidationError("must not be empty", path="$.license.%s" % name)
                # Empty object is the explicit clear/omitted state used by
                # presence-aware edit schemas; non-empty objects are checked
                # field-by-field above.
            if "required_tier_id" in value and value["required_tier_id"] is not None:
                tier = value["required_tier_id"]
                if isinstance(tier, bool) or not isinstance(tier, int) or tier <= 0:
                    raise ValidationError("must be a positive integer", path="$.required_tier_id")
            for name in ("categories", "screenshot_base64s"):
                scalar_array(name, (str, int), "array must contain nonempty values")
                if name in value and any((isinstance(item, str) and not item.strip()) or (isinstance(item, bool)) for item in value[name]):
                    raise ValidationError("array must contain nonempty values", path="$.%s" % name)
            if "categories" in value and len(value["categories"]) > 5:
                raise ValidationError("must contain at most 5 items", path="$.categories")
            if "image_ops" in value:
                object_array("image_ops", {"op", "name", "base64"}, ("op", "name"))
                if "images" not in value:
                    raise ValidationError("images is required when image_ops is supplied", path="$.images")
                for index, operation in enumerate(value["image_ops"]):
                    if operation["op"] not in ("upload", "delete"):
                        raise ValidationError("must be upload or delete", path="$.image_ops[%d].op" % index)
                    if not isinstance(operation["name"], str) or not operation["name"].strip():
                        raise ValidationError("must not be empty", path="$.image_ops[%d].name" % index)
                    if operation["op"] == "upload" and (not isinstance(operation.get("base64"), str) or not operation["base64"].strip()):
                        raise ValidationError("base64 is required for upload", path="$.image_ops[%d].base64" % index)
                    if operation["op"] == "delete" and "base64" in operation:
                        raise ValidationError("base64 is not allowed for delete", path="$.image_ops[%d].base64" % index)
            for name in ("version", "type"):
                if name in value and isinstance(value[name], str) and not value[name].strip():
                    raise ValidationError("must not be empty", path="$.%s" % name)
            if "file" in value and not zipfile.is_zipfile(value["file"]):
                raise ValidationError("file must be a valid ZIP archive", path="$.file")


def f(type_name: str, **kwargs: Any) -> Field:
    return Field(type_name, **kwargs)


NB_PLUGIN_META = {
    "name": f("string", nonempty=True),
    "mod_categories": f("array", nonempty=True, max_items=5),
    "content_origin": f("integer"),
    "content_format": f("integer"),
    "intro": f("string"),
    "description": f("string"),
    "logo": f("string"),
    "logo_file": f("string", local_file=True),
    "screenshots": f("array"),
    "screenshot_files": f("array"),
    "public": f("boolean"),
    "submit_for_review": f("boolean"),
    "subscribe_plan_level": f("integer", minimum=0),
    "link_to_channel": f("boolean"),
    "co_authors": f("array"),
    "references": f("array"),
}

NB_CONFIG_META = {
    "title": f("string", nonempty=True), "content": f("string", nonempty=True),
    "content_format": f("integer"), "intro": f("string"),
    "picture_urls": f("array"), "picture_files": f("array"),
    "content_origin": f("integer"), "public": f("boolean"),
    "submit_for_review": f("boolean"), "link_to_channel": f("boolean"),
    "subscribe_plan_level": f("integer", minimum=0), "price": f("integer", minimum=0),
    "time_range": f("string"),
    "co_authors": f("array"), "references": f("array"),
}
NB_CONFIG_BACKUP = {
    "cloud_id": f("integer"), "linked_mods": f("array"),
    "ignored_unknown_mods": f("array"), "ignored_materials": f("array"),
    "ignored_fronts": f("array"), "roleid": f("string"),
}

NB_WA_META = {
    "game_version_id": f("integer"), "name": f("string", nonempty=True),
    "intro": f("string"), "description": f("string", nonempty=True), "content_format": f("integer"),
    "thumbnail": f("string"), "thumbnail_file": f("string", local_file=True),
    "images": f("array"), "image_files": f("array"),
    "category_id_list": f("array", nonempty=True, max_items=5), "content_origin": f("integer"),
    "subscribe_plan_level": f("integer", minimum=0), "price": f("integer", minimum=0), "time_range": f("string"),
    "public": f("boolean"), "submit_for_review": f("boolean"),
    "link_to_channel": f("boolean"), "attachments": f("array"),
    "co_authors": f("array"), "references": f("array"),
}

DD_COMMERCIAL = {
    "scope": f("string", choices=("public", "private")),
    "share_code_life_type": f("string"), "need_buy": f("boolean"),
    "price_fen": f("integer"), "buy_life_type": f("string"),
    "jump_room": f("boolean"), "room_id": f("string"), "channel_id": f("string"),
    "channel_type": f("string"), "sync_room": f("boolean"),
    "creation_statement": f("string", choices=("original", "chinesize", "renovate", "second")), "with_associate": f("boolean"),
    "associated_acts": f("array"), "need_anchor_vip": f("boolean"),
    "vip_levels": f("array"),
}

DD_PLUGIN_META = {
    "game_type": f("integer"), "scope": DD_COMMERCIAL["scope"], "addon_type": f("integer", choices=(0, 1)),
    "name": f("string", nonempty=True, max_length=80),
    "description": f("string", nonempty=True, max_length=80),
    "logo": f("string"), "logo_file": f("string", local_file=True),
    "detail_imgs": f("array", max_items=8), "detail_img_files": f("array", max_items=8),
    "primary_category_id": f("integer"), "second_category_ids": f("array"),
    "html_desc": f("string", nonempty=True),
    **DD_COMMERCIAL,
}
DD_PLUGIN_EDIT_META = {
    name: DD_COMMERCIAL[name]
    for name in DD_COMMERCIAL
}
DD_PLUGIN_VERSION = {
    "game_versions": f("array", nonempty=True), "detail_url": f("string"),
    "file": f("string", local_file=True), "release_type": f("integer", choices=(1, 2, 3)),
    "version": f("string", nonempty=True, max_length=80),
    "update_desc": f("string", nonempty=True, max_length=1000),
}

DD_CONFIG_META = {
    "scope": DD_COMMERCIAL["scope"], "title": f("string", nonempty=True, max_length=40),
    "brief_desc": f("string", nonempty=True, max_length=50), "desc": f("string", nonempty=True),
    "display_imgs": f("array", max_items=8), "display_img_files": f("array", max_items=8),
    **DD_COMMERCIAL,
}
DD_CONFIG_CONTENT = {
    "backup_sn": f("string", nonempty=True), "update_desc": f("string", max_length=1000),
    "known_addon_ids": f("array"), "known_addon_update_ids": f("array"),
    "unknown_addon_ids": f("array"), "unknown_addon_update_ids": f("array"),
    "wtf_role_ids": f("array"), "material_names": f("array"), "material_update_names": f("array"),
    "font_names": f("array"), "font_update_names": f("array"),
    "known_wa_ids": f("array"), "known_wa_update_ids": f("array"),
    "unknown_wa_ids": f("array"), "unknown_wa_update_ids": f("array"),
    "retail_ui_config": f(
        "object", nullable=True,
        description="safe selector object: edit_mode_selectors, default_edit_mode_selector, cool_down_selectors, enable_dd_setup_wizard",
    ),
}

DD_WA_META = {
    "game_type": f("integer"), "scope": DD_COMMERCIAL["scope"],
    "name": f("string", nonempty=True, max_length=40), "game_version": f("string", nonempty=True),
    "brief_desc": f("string", nonempty=True, max_length=50), "display_imgs": f("array", max_items=8),
    "display_img_files": f("array", max_items=8), "category_ids": f("array", nonempty=True, max_items=5),
    "desc": f("string", nonempty=True), **DD_COMMERCIAL,
}
DD_WA_CONTENT = {
    "content": f("string", nonempty=True), "update_desc": f("string", nonempty=True, max_length=1000),
    "version": f("string", nonempty=True, max_length=80), "with_file": f("boolean"),
    "file": f("string", local_file=True),
    "file_install_path": f("string", choices=("", "Interface", "Interface/Addons")),
}


def required(fields: Mapping[str, Field], names: Iterable[str]) -> Dict[str, Field]:
    result = dict(fields)
    for name in names:
        old = result[name]
        result[name] = Field(
            old.type, required=True, nullable=old.nullable, choices=old.choices,
            nonempty=old.nonempty, max_length=old.max_length, max_items=old.max_items,
            minimum=old.minimum, maximum=old.maximum,
            local_file=old.local_file, description=old.description,
        )
    return result


def with_id(fields: Mapping[str, Field], name: str = "id") -> Dict[str, Field]:
    return {name: f("string" if name in ("sn", "share_sn") else "integer", required=True, nonempty=True), **fields}


SCHEMAS: Dict[Tuple[str, str, str], Schema] = {}


def register(platform: str, resource: str, action: str, fields: Mapping[str, Field]) -> None:
    name = "fupload.v1.%s.%s.%s" % (platform, resource, action)
    SCHEMAS[(platform, resource, action)] = Schema(name, fields)


register("newbee", "plugin", "create", required(NB_PLUGIN_META, ("name", "mod_categories", "content_origin", "content_format", "intro", "description", "public")))
register("newbee", "plugin", "update", required({"mod_id": f("integer"), "version": f("string", nonempty=True), "game_version_list": f("array", nonempty=True), "file": f("string", local_file=True), "changelog": f("string"), "link_to_channel": f("boolean")}, ("mod_id", "version", "game_version_list", "file")))
register("newbee", "plugin", "edit", with_id(NB_PLUGIN_META))
register("newbee", "plugin-changelog", "edit", required({"file_id": f("integer"), "changelog": f("string", nullable=True)}, ("file_id", "changelog")))

register("newbee", "config", "create", required({**NB_CONFIG_META, **NB_CONFIG_BACKUP}, ("cloud_id", "title", "content", "content_format", "content_origin", "public", "linked_mods", "ignored_unknown_mods", "ignored_materials", "ignored_fronts", "roleid")))
register("newbee", "config", "update", with_id(NB_CONFIG_BACKUP))
register("newbee", "config", "edit", with_id(NB_CONFIG_META))

register("newbee", "wa", "create", required({**NB_WA_META, "wa_str": f("string", nonempty=True), "wa_str_titles": f("array"), "wa_log": f("string", nonempty=True), "string_mode": f("string", choices=("single", "collection"))}, ("game_version_id", "name", "description", "content_format", "category_id_list", "content_origin", "public", "wa_str", "wa_log", "string_mode")))
register("newbee", "wa", "update", required({"id": f("integer"), "version": f("string", nonempty=True), "wa_str": f("string", nonempty=True), "wa_str_titles": f("array"), "wa_log": f("string", nonempty=True), "link_to_channel": f("boolean")}, ("id", "wa_str", "wa_log")))
register("newbee", "wa", "edit", with_id(NB_WA_META))
register("newbee", "wa-media", "upload", required({"file": f("string", local_file=True), "kind": f("string", choices=("image", "attachment")), "install_type": f("integer"), "install_path": f("string")}, ("file", "kind")))
register("newbee", "wa-changelog", "edit", required({"id": f("integer"), "wa_id": f("integer"), "wa_log": f("string", nullable=True)}, ("id", "wa_log")))
for _resource in ("plugin", "config", "wa"):
    register("newbee", _resource + "-co-author", "set", required({"content_id": f("integer"), "co_authors": f("array")}, ("content_id", "co_authors")))
    register("newbee", _resource + "-reference", "set", required({"source_id": f("integer"), "references": f("array")}, ("source_id", "references")))
register("newbee", "wa-share-code", "set", required({"module_id": f("integer")}, ("module_id",)))
for _resource in ("plugin", "config", "wa"):
    register("newbee", _resource, "delete", required({"id": f("integer"), "confirm": f("string", choices=("DELETE",))}, ("id", "confirm")))

register("dd", "plugin", "create", required(
    {**DD_PLUGIN_META, **DD_PLUGIN_VERSION},
    ("game_type", "scope", "addon_type", "name", "description",
     "primary_category_id", "game_versions", "release_type", "version",
     "html_desc", "update_desc", "creation_statement", "need_buy", "jump_room",
     "with_associate", "need_anchor_vip"),
))
register("dd", "plugin", "update", with_id(required(DD_PLUGIN_VERSION, ("game_versions", "version", "update_desc")), "sn"))
register("dd", "plugin", "edit", with_id(DD_PLUGIN_EDIT_META, "sn"))
register("dd", "config", "create", required(
    {**DD_CONFIG_META, **DD_CONFIG_CONTENT},
    ("scope", "backup_sn", "title", "brief_desc", "desc",
     "creation_statement", "known_addon_ids", "unknown_addon_ids", "wtf_role_ids",
     "material_names", "font_names", "known_wa_ids", "unknown_wa_ids", "need_buy",
     "jump_room", "with_associate", "need_anchor_vip"),
))
register("dd", "config", "update", with_id(required(DD_CONFIG_CONTENT, ("backup_sn", "update_desc")), "share_sn"))
register("dd", "config", "edit", with_id(DD_CONFIG_META, "share_sn"))
register("dd", "wa", "create", required(
    {**DD_WA_META, **DD_WA_CONTENT},
    ("game_type", "scope", "name", "game_version", "brief_desc",
     "category_ids", "content", "desc", "update_desc", "version", "creation_statement",
     "with_file", "need_buy", "jump_room", "with_associate", "need_anchor_vip"),
))
register("dd", "wa", "update", with_id(required(DD_WA_CONTENT, ("content", "update_desc", "version", "with_file")), "sn"))
register("dd", "wa", "edit", with_id(DD_WA_META, "sn"))
for _resource in ("plugin", "config", "wa"):
    register("dd", _resource, "delete", required({
        "sn": f("string", nonempty=True),
        "confirm_delete": f("boolean", choices=(True,)),
    }, ("sn", "confirm_delete")))

register("curseforge", "plugin", "upload", required({
    "project_id": f("integer", minimum=1),
    "file": f("string", local_file=True),
    "changelog": f("string"),
    "changelog_type": f("string", choices=("text", "html", "markdown")),
    "display_name": f("string", nonempty=True),
    "game_versions": f("array", nonempty=True),
    "game_version_names": f("array"),
    "release_type": f("string", choices=("alpha", "beta", "release")),
    "parent_file_id": f("integer", minimum=1),
    "relations": f("object"),
    "is_marked_for_manual_release": f("boolean"),
}, ("project_id", "file", "changelog", "release_type")))

# ModUs.Creator author project and release contracts.  The provider translates
# snake_case input names to the desktop client's camelCase wire fields.
MODUS_PROJECT_COMMON = {
    "name": f("string", nonempty=True, max_length=120),
    "alt_name": f("string", max_length=120),
    "summary": f("string", nonempty=True, max_length=500),
    "categories": f("array", nonempty=True, max_items=5),
    "license": f("object", nullable=True),
    "repo_url": f("string", max_length=500),
    "required_tier_id": f("integer", nullable=True, minimum=1),
    "publish_platforms": f("array", nonempty=True),
    "project_state": f("object", nonempty=True),
}
MODUS_PROJECT_CREATE = {
    **MODUS_PROJECT_COMMON,
    "logo_base64": f("string", nonempty=True),
    "screenshot_base64s": f("array"),
}
MODUS_PROJECT_EDIT = {
    **MODUS_PROJECT_COMMON,
    "description": f("string", nullable=True, max_length=100000),
    "required_dependencies": f("string", nullable=True, max_length=4000),
    "images": f("integer", minimum=0),
    "image_ops": f("array", nonempty=True),
}
MODUS_RELEASE = {
    "project_id": f("integer", minimum=1),
    "file_id": f("integer", minimum=1),
    "version": f("string", nonempty=True, max_length=120),
    "type": f("string", nonempty=True, max_length=40),
    "supported_game_versions": f("array", nonempty=True),
    "md5": f("string", max_length=64),
    "zip_size": f("integer", minimum=0),
    "unzip_size": f("integer", minimum=0),
    "path": f("string", max_length=500),
    "toc_version": f("string", max_length=80),
    "changelog": f("string", nullable=True, max_length=10000),
    "file": f("string", local_file=True),
    "transaction_log": f("string", max_length=1000),
}
register("modus", "project", "create", required(MODUS_PROJECT_CREATE, ("project_state",)))
register("modus", "project", "edit", required(with_id(MODUS_PROJECT_EDIT, "project_id"), ("project_id", "project_state")))
register("modus", "project", "delete", required({"project_id": f("integer", minimum=1), "confirm": f("string", choices=("DELETE",))}, ("project_id", "confirm")))
register("modus", "plugin", "create", required(MODUS_RELEASE, ("project_id", "file")))
register("modus", "plugin", "upload", required(MODUS_RELEASE, ("project_id", "file")))
register("modus", "plugin", "update", required(MODUS_RELEASE, ("project_id", "file_id")))
register("modus", "plugin", "edit", required(MODUS_RELEASE, ("project_id", "file_id")))
register("modus", "plugin", "delete", required({"project_id": f("integer", minimum=1), "file_id": f("integer", minimum=1), "confirm": f("string", choices=("DELETE",))}, ("project_id", "file_id", "confirm")))

register("blackbox", "plugin", "edit", required({
    "id": f("integer"), "name": f("string"), "logo_url": f("string"), "category_ids": f("array"),
    "type": f("integer", choices=(1, 9)), "desc": f("string"), "official": f("string"),
    "official_url": f("string"), "core_folders": f("array"),
}, ("id",)))
register("blackbox", "plugin", "update", required({
    "module_id": f("integer"), "name": f("string", nonempty=True), "type": f("integer", choices=(1, 2, 3)),
    "game_versions": f("array", nonempty=True), "file": f("string", local_file=True), "file_url": f("string", nonempty=True),
}, ("module_id", "name", "type", "game_versions", "file")))
register("blackbox", "version", "edit", required({
    "version_id": f("integer"), "module_id": f("integer"), "name": f("string", nonempty=True),
    "type": f("integer", choices=(1, 2, 3)), "game_versions": f("array", nonempty=True),
    "file": f("string", local_file=True), "file_url": f("string", nonempty=True),
}, ("version_id", "module_id", "name", "type", "game_versions")))
register("blackbox", "version", "delete", required({
    "version_id": f("integer"), "module_id": f("integer"),
}, ("version_id", "module_id")))


def get_schema(platform: str, resource: str, action: str) -> Schema:
    try:
        return SCHEMAS[(platform, resource, action)]
    except KeyError as exc:
        raise ValidationError("no write schema for %s %s %s" % (platform, resource, action)) from exc


def schema_help(platform: str, resource: str, action: str) -> str:
    schema = get_schema(platform, resource, action)
    rows = ["Input schema: %s" % schema.name, "Fields:"]
    for name, spec in schema.fields.items():
        flags = [spec.type, "required" if spec.required else "optional"]
        if spec.nullable:
            flags.append("nullable/explicit clear")
        if spec.choices:
            flags.append("choices=" + "|".join(map(str, spec.choices)))
        if spec.max_length is not None:
            flags.append("max-length=" + str(spec.max_length))
        if spec.max_items is not None:
            flags.append("max-items=" + str(spec.max_items))
        if spec.local_file:
            flags.append("local file")
        detail = ", ".join(flags)
        if spec.description:
            detail += "; " + spec.description
        rows.append("  %-28s %s" % (name, detail))
    rows.extend([
        "Unknown fields are rejected. On edit/update, omission preserves the remote value.",
        "Frontend preselected values are never used as business defaults.",
        "Use --dry-run for local validation only; it does not validate remote IDs or permissions.",
    ])
    return "\n".join(rows)
