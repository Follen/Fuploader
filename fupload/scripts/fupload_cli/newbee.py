"""NewBeeBox Creator provider."""

from __future__ import annotations

import hashlib
import http.client
import json
import mimetypes
import os
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from .errors import FuploadError, ValidationError
from .transport import json_request, multipart_request
from .newbee_auth import API_BASE, API_ORIGIN, auth_store_dir, creator_headers
from .trust import NEWBEE_ORIGINS


METADATA_URL = NEWBEE_ORIGINS["metadata"] + "/modconfig.json"
UPLOAD_SERVER = NEWBEE_ORIGINS["upload"] + "/uploadserver"
NEXT_API_BASE = NEWBEE_ORIGINS["next"]
NEXT_ORIGIN = "next"
METADATA_ORIGIN = "metadata"
UPLOAD_ORIGIN = "upload"


# Creator Center uses different numeric namespaces for each main record type.
RELATION_TYPES = {
    "plugin": {"co_authors": 1, "references": 1},
    "config": {"co_authors": 4, "references": 3},
    "wa": {"co_authors": 3, "references": 2},
}


def _first_object(value: Any) -> Dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, list) and value and isinstance(value[0], dict):
        return value[0]
    return {}


def _decode(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except ValueError:
            return value
    return value


def _pick(value: Mapping[str, Any], *names: str, default: Any = None) -> Any:
    for name in names:
        if name in value and value[name] is not None:
            return value[name]
    return default


def _list(value: Any) -> List[Any]:
    value = _decode(value)
    return list(value) if isinstance(value, list) else []


def _urls(value: Any) -> List[str]:
    result = []
    for item in _list(value):
        if isinstance(item, str):
            result.append(item)
        elif isinstance(item, dict):
            url = _pick(item, "media_url", "url", "name", default="")
            if url:
                result.append(str(url))
    return result


def _numeric_ids(value: Any) -> List[int]:
    found: List[int] = []
    def walk(node: Any) -> None:
        if isinstance(node, dict):
            for key in ("id", "t_id", "category_id", "t_category_id", "value"):
                candidate = node.get(key)
                if isinstance(candidate, int) and candidate > 0:
                    found.append(candidate)
                elif isinstance(candidate, str) and candidate.isdigit() and int(candidate) > 0:
                    found.append(int(candidate))
            for child in node.values():
                if isinstance(child, (dict, list)):
                    walk(child)
        elif isinstance(node, list):
            for child in node:
                walk(child)
        elif isinstance(node, int) and node > 0:
            found.append(node)
    walk(value)
    return found


def _version_greater(candidate: Any, current: Any) -> bool:
    left = str(candidate or "").strip()
    right = str(current or "").strip()
    if not left or not right:
        return False
    if left.isdigit() and right.isdigit():
        return int(left) > int(right)
    def parts(value: str) -> List[int]:
        return [int(part) for part in value.split(".") if part.isdigit()]
    left_parts, right_parts = parts(left), parts(right)
    return bool(left_parts and right_parts and left_parts > right_parts)


def _redact_wa(value: Any) -> Any:
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            if key.lower() in ("wa_str", "t_wa_str") and isinstance(item, str):
                result[key + "_summary"] = {
                    "length": len(item), "sha256": hashlib.sha256(item.encode("utf-8")).hexdigest()
                }
            else:
                result[key] = _redact_wa(item)
        return result
    if isinstance(value, list):
        return [_redact_wa(item) for item in value]
    return value


def _option_rows(value: Any) -> List[Dict[str, Any]]:
    """Read only documented top-level option containers."""
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    if not isinstance(value, dict):
        return []
    for key in ("list", "items", "rows", "options"):
        if isinstance(value.get(key), list):
            return [item for item in value[key] if isinstance(item, dict)]
    data = value.get("data")
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    return []


def _same_value(expected: Any, actual: Any) -> bool:
    if isinstance(expected, bool):
        return actual is expected
    if isinstance(expected, (int, float)) and not isinstance(expected, bool):
        try:
            return float(actual) == float(expected)
        except (TypeError, ValueError):
            return False
    if isinstance(expected, list):
        if not isinstance(actual, list):
            return False
        unmatched = list(actual)
        for wanted in expected:
            match = next((index for index, candidate in enumerate(unmatched) if _same_value(wanted, candidate)), None)
            if match is None:
                return False
            unmatched.pop(match)
        return len(unmatched) == 0
    if isinstance(expected, dict):
        if not isinstance(actual, dict):
            return False
        for name, wanted in expected.items():
            actual_name = "updateType" if name == "update_type" and "updateType" in actual else name
            if actual_name not in actual or not _same_value(wanted, actual[actual_name]):
                return False
        return True
    if isinstance(expected, str) and isinstance(actual, str):
        if expected.startswith(("http://", "https://")) or actual.startswith(("http://", "https://")):
            expected_path = urllib.parse.urlsplit(expected).path.lstrip("/")
            actual_path = urllib.parse.urlsplit(actual).path.lstrip("/")
            return bool(expected_path and expected_path == actual_path)
    return actual == expected


def _require_readback(expected: Mapping[str, Any], actual: Mapping[str, Any], endpoint: str) -> None:
    mismatches = []
    for name, wanted in expected.items():
        if name not in actual or not _same_value(wanted, actual[name]):
            mismatches.append(name)
    if mismatches:
        raise FuploadError(
            "write readback did not match field(s): %s" % ", ".join(sorted(mismatches)),
            kind="verification_required", endpoint=endpoint, verification_required=True,
            details={"fields": sorted(mismatches)},
        )


def _paged_items(value: Any) -> Tuple[int, List[Dict[str, Any]], Dict[str, Any]]:
    obj = _first_object(value)
    raw_items = _list(_pick(obj, "list", "items", default=[]))
    return int(_pick(obj, "total", "count", default=len(raw_items)) or len(raw_items)), [x for x in raw_items if isinstance(x, dict)], obj


def _plugin_summary(item: Mapping[str, Any]) -> Dict[str, Any]:
    versions = []
    for version in _list(item.get("game_versions")):
        if isinstance(version, dict):
            versions.append({
                "id": version.get("id"), "name": version.get("name"),
                "support_version": version.get("support_version"), "tag": version.get("tag"),
            })
    return {
        "id": int(_pick(item, "t_id", "id", default=0) or 0),
        "name": str(_pick(item, "t_name", "name", default="")),
        "public": int(_pick(item, "t_share", "share_state", default=0) or 0) == 1,
        "review_status": _pick(item, "t_check", "review_status"),
        "content_format": _pick(item, "t_content_format", "content_format"),
        "content_origin": _pick(item, "t_original", "content_origin"),
        "logo": _pick(item, "t_logo", "logo"),
        "screenshots": _urls(item.get("screenshots")),
        "game_versions": versions,
        "subscribe_plan_level": _pick(item, "t_subscribe_plan_level", "subscribe_plan_level"),
        "link_to_channel": bool(_pick(item, "t_link_to_channel", "link_to_channel", default=False)),
        "updated_at": _pick(item, "t_last_update", "updated_at"),
    }


def _wa_summary(item: Mapping[str, Any]) -> Dict[str, Any]:
    categories = []
    for category in _list(item.get("category_list")):
        if isinstance(category, dict):
            categories.append({"id": category.get("t_id"), "name": category.get("t_show_name") or category.get("t_name")})
    return {
        "id": int(_pick(item, "t_id", "id", default=0) or 0),
        "name": str(_pick(item, "t_name", "name", default="")),
        "version": str(_pick(item, "t_version", "version", default="")),
        "public": int(_pick(item, "t_share_state", "share_state", default=2) or 2) == 1,
        "review_status": _pick(item, "t_check_status", "review_status"),
        "game_version_id": _pick(item, "t_game_version_id", "game_version_id"),
        "thumbnail": _pick(item, "t_thumbnail", "thumbnail"),
        "images": _urls(_pick(item, "t_images", "images", default=[])),
        "categories": categories,
        "attachments": _list(_pick(item, "t_attachments", "attachments", default=[])),
        "content_format": _pick(item, "t_content_format", "content_format"),
        "content_origin": _pick(item, "t_content_origin", "content_origin"),
        "subscribe_plan_level": _pick(item, "t_subscribe_plan_level", "subscribe_plan_level"),
        "price": _pick(item, "price", "t_price"),
        "time_range": _pick(item, "t_time_range", "time_range", default=""),
        "link_to_channel": bool(_pick(item, "t_link_to_channel", "link_to_channel", default=False)),
        "updated_at": _pick(item, "t_update_time", "updated_at"),
    }


class NewBee:
    platform = "newbee"

    def __init__(self) -> None:
        self.base = API_BASE.rstrip("/")
        self._headers: Optional[Dict[str, str]] = None

    @property
    def headers(self) -> Dict[str, str]:
        if self._headers is None:
            self._headers = creator_headers()
        return self._headers

    def post(self, endpoint: str, body: Mapping[str, Any]) -> Any:
        envelope = json_request(
            self.base + endpoint, method="POST", headers=self.headers, body=body,
            trusted_service=API_ORIGIN,
        )
        if not isinstance(envelope, dict) or envelope.get("code") != 1:
            raise FuploadError(
                str((envelope or {}).get("message") or "NewBeeBox request failed"),
                endpoint=endpoint,
                business_code=(envelope or {}).get("code"),
            )
        return envelope.get("data")

    def post_next(self, endpoint: str, body: Mapping[str, Any]) -> Any:
        envelope = json_request(
            NEXT_API_BASE + endpoint, method="POST", headers=self.headers, body=body,
            trusted_service=NEXT_ORIGIN,
        )
        if not isinstance(envelope, dict) or envelope.get("code") != 1:
            raise FuploadError(
                str((envelope or {}).get("message") or "NewBeeBox next request failed"),
                endpoint=endpoint,
                business_code=(envelope or {}).get("code"),
            )
        return envelope.get("data")

    def upload(self, endpoint: str, path: str, fields: Optional[Mapping[str, str]] = None) -> Any:
        envelope = multipart_request(
            self.base + endpoint, path, headers=self.headers, fields=fields,
            trusted_service=API_ORIGIN,
        )
        if not isinstance(envelope, dict) or envelope.get("code") != 1:
            raise FuploadError(
                str((envelope or {}).get("message") or "NewBeeBox upload failed"),
                endpoint=endpoint,
                business_code=(envelope or {}).get("code"),
            )
        return envelope.get("data")

    def metadata(self) -> Dict[str, Any]:
        value = json_request(METADATA_URL, trusted_service=METADATA_ORIGIN)
        if not isinstance(value, dict):
            raise FuploadError("NewBeeBox metadata had an unexpected shape", endpoint=METADATA_URL)
        return value

    def categories(self) -> Dict[str, Any]:
        items = []
        for item in _list(self.metadata().get("mod_category")):
            if isinstance(item, dict):
                items.append({
                    "id": int(item.get("t_id") or 0), "name": str(item.get("t_name") or ""),
                    "parent_id": int(item.get("t_parent_category_id") or 0),
                    "sort_index": int(item.get("t_show_index") or 0),
                })
        return {"total": len(items), "items": items}

    def game_versions(self) -> Dict[str, Any]:
        items = []
        for item in _list(self.metadata().get("game_version")):
            if isinstance(item, dict):
                items.append({
                    "id": int(item.get("id") or 0), "name": str(item.get("name") or ""),
                    "search_enabled": bool(item.get("search_enable")), "versions": _list(item.get("version")),
                })
        return {"total": len(items), "items": items}

    def list_plugins(self, keyword: str, page: int, size: int) -> Any:
        raw = self.post("/creator/wow/mod/publish_list", {
            "keyword": keyword, "game_version_id": 0, "sort_by": "t_last_update",
            "sort_order": "DESC", "pagenum": page, "pagesize": size,
        })
        total, items, obj = _paged_items(raw)
        return {"total": total, "items": [_plugin_summary(item) for item in items], "page": obj.get("pagenum", page), "page_size": obj.get("pagesize", size)}

    def get_plugin_raw(self, ident: int) -> Dict[str, Any]:
        return _first_object(self.post("/creator/wow/mod/publish_detail", {"id": ident}))

    def get_plugin(self, ident: int) -> Dict[str, Any]:
        raw = self.get_plugin_raw(ident)
        summary = _plugin_summary(raw)
        summary.update({
            "intro": str(_pick(raw, "t_description", "intro", default="")),
            "description": str(_pick(raw, "t_description_v2", "description", default="")),
            "category_ids": _list(_pick(raw, "category_ids", "mod_categories", default=[])),
        })
        return summary

    def plugin_versions(self, ident: int, page: int = 1, size: int = 100) -> Any:
        return self.post("/creator/wow/mod_file/mod_file_list", {
            "mod_id": ident, "game_version_id": 0, "pagenum": page, "pagesize": size,
        })

    def list_backups_raw(self) -> List[Dict[str, Any]]:
        raw = self.post("/creator/wow/share/list", {})
        result: List[Dict[str, Any]] = []
        def walk(value: Any) -> None:
            if isinstance(value, list):
                for item in value:
                    walk(item)
            elif isinstance(value, dict):
                result.append(value)
        walk(raw)
        return result

    def list_backups(self) -> Dict[str, Any]:
        items = []
        for item in self.list_backups_raw():
            if "t_id" not in item:
                continue
            items.append({
                "cloud_id": int(item.get("t_id") or 0), "name": item.get("t_name"),
                "game_version_id": item.get("t_Versionid"), "created_at": item.get("t_create_time"),
                "known_plugins": len(_list(item.get("t_Known_plug"))),
                "unknown_plugins": len(_list(item.get("t_unKnown_list"))),
                "materials": len(_list(item.get("t_material_list"))),
                "fonts": len(_list(item.get("t_font_list"))),
            })
        return {"total": len(items), "items": items}

    def get_backup(self, cloud_id: int) -> Dict[str, Any]:
        for item in self.list_backups_raw():
            if int(item.get("t_id") or 0) == cloud_id:
                linked = []
                for mod in _list(item.get("t_Known_plug")):
                    if isinstance(mod, dict):
                        linked.append({
                            "mod_id": int(mod.get("id") or 0), "mod_name": str(mod.get("name") or ""),
                            "mod_file_id": mod.get("mod_file_id"), "mod_version": mod.get("mod_version"),
                            "display_name": mod.get("display_name"),
                            "update_type": int(mod.get("updateType") or 1),
                        })
                roles = []
                for account in _list(item.get("wtflist")):
                    for server in _list((account or {}).get("server")):
                        for role in _list((server or {}).get("roleList")):
                            roles.append({
                                "account": (account or {}).get("account"), "server": (server or {}).get("serverName"),
                                "name": (role or {}).get("name"), "role_id": (role or {}).get("role_id"),
                            })
                return {
                    "cloud_id": cloud_id, "name": item.get("t_name"), "linked_mods": linked,
                    "unknown_plugins": [str(x.get("name") or "") for x in _list(item.get("t_unKnown_list")) if isinstance(x, dict)],
                    "materials": [str(x.get("name") or "") for x in _list(item.get("t_material_list")) if isinstance(x, dict)],
                    "fonts": [str(x.get("name") or "") if isinstance(x, dict) else str(x) for x in _list(item.get("t_font_list"))],
                    "roles": roles,
                }
        raise FuploadError("cloud backup %d was not found" % cloud_id, kind="not_found")

    @staticmethod
    def _validate_backup_selection(backup: Mapping[str, Any], doc: Mapping[str, Any]) -> None:
        linked = {str(item.get("mod_id")) for item in _list(backup.get("linked_mods")) if isinstance(item, dict)}
        selected = {str(item.get("mod_id")) for item in _list(doc.get("linked_mods")) if isinstance(item, dict)}
        if selected - linked:
            raise ValidationError("linked_mods contains an item absent from the selected cloud backup", path="$.linked_mods")
        for field, source in (("ignored_unknown_mods", "unknown_plugins"), ("ignored_materials", "materials"), ("ignored_fronts", "fonts")):
            available = {str(item) for item in _list(backup.get(source))}
            selected = {str(item) for item in _list(doc.get(field))}
            if selected - available:
                raise ValidationError("%s contains an item absent from the selected cloud backup" % field, path="$.%s" % field)
        roles = {str(item.get("role_id")) for item in _list(backup.get("roles")) if isinstance(item, dict)}
        roleid = str(doc.get("roleid") or "")
        if roleid and roleid not in roles:
            raise ValidationError("roleid is absent from the selected cloud backup", path="$.roleid")

    @staticmethod
    def _created_id(value: Any, title: str, secondary: Optional[Any] = None) -> int:
        direct = _pick(_first_object(value), "id", "t_id", "mod_id", "wa_id", default=0)
        try:
            if int(direct or 0) > 0:
                return int(direct)
        except (TypeError, ValueError):
            pass
        matches: List[int] = []
        def walk(node: Any) -> None:
            if isinstance(node, dict):
                name = _pick(node, "name", "title", "t_name", "t_title", default=None)
                if name == title:
                    candidate = _pick(node, "id", "t_id", "mod_id", "wa_id", default=0)
                    try:
                        candidate_id = int(candidate or 0)
                    except (TypeError, ValueError):
                        candidate_id = 0
                    if candidate_id > 0 and (secondary is None or str(_pick(node, "cloud_id", "t_cloudblackid", default="")) == str(secondary)):
                        matches.append(candidate_id)
                for child in node.values():
                    if isinstance(child, (dict, list)):
                        walk(child)
            elif isinstance(node, list):
                for child in node:
                    walk(child)
        walk(value)
        return matches[0] if len(set(matches)) == 1 else 0

    def list_configs(self, keyword: str, offset: int, size: int) -> Any:
        return self.post("/creator/wow/share_config/publish_list", {
            "keyword": keyword, "game_version_id": 0, "sort": 3,
            "offset": offset, "pagesize": size,
        })

    def get_config_raw(self, ident: int) -> Dict[str, Any]:
        return _first_object(self.post("/creator/wow/share_config/details_aps", {"id": ident}))

    def get_config(self, ident: int) -> Dict[str, Any]:
        detail = self.get_config_raw(ident)
        return {
            "id": int(_pick(detail, "t_id", "id", default=ident) or ident),
            "title": _pick(detail, "t_title", "title", default=""),
            "cloud_id": int(_pick(detail, "t_cloudblackid", "cloud_id", default=0) or 0),
            "public": int(_pick(detail, "t_sharing", "sharing", default=0) or 0) != 0,
            "review_status": _pick(detail, "t_check", "review_status"),
            "content": _pick(detail, "t_content", "content", default=""),
            "content_format": int(_pick(detail, "t_content_format", "content_format", default=0) or 0),
            "intro": _pick(detail, "t_intro", "intro", default=""),
            "picture_urls": _urls(_pick(detail, "pic_url", "picture_urls", "piclist", default=[])),
            "content_origin": int(_pick(detail, "t_content_origin", "content_origin", default=0) or 0),
            "link_to_channel": bool(_pick(detail, "t_link_to_channel", "link_to_channel", default=False)),
            "subscribe_plan_level": int(_pick(detail, "t_subscribe_plan_level", "subscribe_plan_level", default=0) or 0),
            "price": int(_pick(detail, "t_price", "price", default=0) or 0),
            "time_range": _pick(detail, "t_time_range", "time_range", default=""),
            "linked_mods": _list(_pick(detail, "t_linked_mods", "linked_mods", default=[])),
            "ignored_unknown_mods": _list(_pick(detail, "t_ignored_unknown_mods", "ignored_unknown_mods", default=[])),
            "ignored_materials": _list(_pick(detail, "t_ignored_materials", "ignored_materials", default=[])),
            "ignored_fronts": _list(_pick(detail, "t_ignored_fronts", "ignored_fronts", default=[])),
            "roleid": str(_pick(detail, "t_roleid", "roleid", "role_id", default="")),
        }

    def list_was(self, keyword: str, offset: int, size: int) -> Any:
        raw = self.post("/creator/wow/wa/mtg_uc_publish_list", {
            "keyword": keyword, "game_version_id": 0, "sort": 3,
            "offset": offset, "pagesize": size,
        })
        total, items, obj = _paged_items(raw)
        return {"total": total, "items": [_wa_summary(item) for item in items], "next_offset": obj.get("next_offset"), "offset": offset, "page_size": size}

    def get_wa_raw(self, ident: int) -> Dict[str, Any]:
        return _first_object(self.post("/creator/wow/wa/detail_aps", {"id": ident}))

    def get_wa(self, ident: int) -> Dict[str, Any]:
        raw = self.get_wa_raw(ident)
        summary = _wa_summary(raw)
        summary.update({
            "intro": str(_pick(raw, "t_intro", "intro", default="")),
            "description": str(_pick(raw, "t_description", "description", default="")),
            "wa_str_titles": _list(_pick(raw, "t_wa_str_titles", "wa_str_titles", default=[])),
        })
        return _redact_wa(summary)

    def wa_categories(self, game_version_id: int) -> Any:
        return self.post("/creator/wow/wa/category", {"game_version": game_version_id})

    def attachment_paths(self) -> Any:
        return self.post("/creator/wow/wa/attachment_install_path_list", {})

    def content_origins(self) -> Dict[str, Any]:
        rows = _option_rows(self.post("/v3/sys/content_origin_list", {}))
        return {"total": len(rows), "items": [{"label": row.get("label"), "value": row.get("value")} for row in rows if row.get("value") is not None]}

    def subscribe_plans(self) -> Dict[str, Any]:
        rows = _option_rows(self.post("/creator/author_subscribe/plan_level_preset", {}))
        return {"total": len(rows), "items": [{"label": row.get("label") or row.get("name"), "value": row.get("value")} for row in rows if row.get("value") is not None]}

    def time_ranges(self) -> Dict[str, Any]:
        rows = _option_rows(self.post_next("/cloudsaveserver/GameCloudSavePublish/GetTimeRangeList", {}))
        return {"total": len(rows), "items": [{"label": row.get("label") or row.get("name"), "value": row.get("value")} for row in rows if row.get("value") is not None]}

    @staticmethod
    def _option_values(payload: Mapping[str, Any], path: str) -> set[str]:
        values = {str(item["value"]) for item in payload.get("items", []) if isinstance(item, dict) and item.get("value") is not None}
        if not values:
            raise FuploadError("live option response contained no selectable values", kind="platform_data_error", details={"path": path})
        return values

    def _validate_business_options(self, doc: Mapping[str, Any]) -> None:
        if "content_origin" in doc:
            allowed = self._option_values(self.content_origins(), "$.content_origin")
            if str(doc["content_origin"]) not in allowed:
                raise ValidationError("content_origin is unavailable", path="$.content_origin")
        if int(doc.get("subscribe_plan_level") or 0):
            allowed = self._option_values(self.subscribe_plans(), "$.subscribe_plan_level")
            if str(doc["subscribe_plan_level"]) not in allowed:
                raise ValidationError("subscribe_plan_level is unavailable", path="$.subscribe_plan_level")
        if doc.get("time_range"):
            allowed = self._option_values(self.time_ranges(), "$.time_range")
            if str(doc["time_range"]) not in allowed:
                raise ValidationError("time_range is unavailable", path="$.time_range")

    def _validate_changed_business_options(self, form: Mapping[str, Any], doc: Mapping[str, Any]) -> None:
        fields = ("content_origin", "subscribe_plan_level", "time_range")
        self._validate_business_options({name: form[name] for name in fields if name in doc})

    @staticmethod
    def _normalize_commercial(form: Dict[str, Any], public: bool) -> None:
        """Apply the Creator Center's submitted, not intermediate, payment state."""
        subscription = int(form.get("subscribe_plan_level") or 0)
        if subscription < 0:
            raise ValidationError("subscribe_plan_level must not be negative", path="$.subscribe_plan_level")
        form["subscribe_plan_level"] = subscription
        if "price" in form:
            price = int(form.get("price") or 0)
            if price < 0:
                raise ValidationError("price must not be negative", path="$.price")
            form["price"] = price
            # A one-time duration has no wire meaning without a one-time price.
            if price == 0:
                form["time_range"] = ""
        if not public:
            form["link_to_channel"] = False

    @staticmethod
    def _relation_rows(value: Any, name: str) -> Optional[List[Dict[str, Any]]]:
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
        if not isinstance(value, dict):
            return None
        for key in (name, "list", "items", "data"):
            candidate = value.get(key)
            if isinstance(candidate, list):
                return [item for item in candidate if isinstance(item, dict)]
        return None

    @staticmethod
    def _require_relation_readback(name: str, expected: Sequence[Mapping[str, Any]], actual: Any, endpoint: str) -> None:
        rows = NewBee._relation_rows(actual, name)
        if rows is None:
            raise FuploadError(
                "relationship write succeeded but its readback had an unexpected shape",
                kind="verification_required", endpoint=endpoint, verification_required=True,
            )
        if name == "co_authors":
            wanted = {(int(item["user_id"]), float(item["share_percent"])) for item in expected}
            observed = {
                (int(_pick(item, "user_id", "t_user_id", "id", default=0) or 0),
                 float(_pick(item, "share_percent", "t_share_percent", "ratio", default=-1) or -1))
                for item in rows
            }
        else:
            wanted = {(int(item["type"]), int(item["id"])) for item in expected}
            observed = {
                (int(_pick(item, "type", "content_type", "t_type", default=0) or 0),
                 int(_pick(item, "id", "content_id", "t_id", default=0) or 0))
                for item in rows
            }
        if wanted != observed:
            raise FuploadError(
                "relationship write readback did not match the complete replacement",
                kind="verification_required", endpoint=endpoint, verification_required=True,
            )

    def _replace_relationships(self, resource: str, ident: int, doc: Mapping[str, Any]) -> Dict[str, Any]:
        types = RELATION_TYPES[resource]
        result: Dict[str, Any] = {}
        if "co_authors" in doc:
            body = {"content_type": types["co_authors"], "content_id": ident, "co_authors": doc["co_authors"]}
            mutation = self.post("/creator/co_author/set", body)
            readback = self.post("/creator/co_author/list", {"content_type": types["co_authors"], "content_id": ident})
            self._require_relation_readback("co_authors", doc["co_authors"], readback, "/creator/co_author/list")
            result["co_authors"] = {"result": mutation, "readback": readback}
        if "references" in doc:
            body = {"source_type": types["references"], "source_id": ident, "references": doc["references"]}
            mutation = self.post("/creator/content_reference/set", body)
            readback = self.post("/creator/content_reference/list", {"content_type": types["references"], "content_id": ident})
            self._require_relation_readback("references", doc["references"], readback, "/creator/content_reference/list")
            result["references"] = {"result": mutation, "readback": readback}
        return result

    @staticmethod
    def _wa_category_values(payload: Any) -> set[int]:
        values: set[int] = set()
        rows = _option_rows(payload)
        def visit(row: Mapping[str, Any]) -> None:
            raw = _pick(row, "id", "t_id", "category_id", "value", default=None)
            if raw is not None and not isinstance(raw, bool):
                try:
                    values.add(int(raw))
                except (TypeError, ValueError):
                    pass
            for key in ("children", "items", "options"):
                for child in _list(row.get(key)):
                    if isinstance(child, dict):
                        visit(child)
        for row in rows:
            visit(row)
        return values

    def _validate_wa_categories(self, game_version_id: int, selected: Sequence[int]) -> None:
        values = self._wa_category_values(self.wa_categories(game_version_id))
        if not values:
            raise FuploadError("live WA category response contained no selectable values", kind="platform_data_error")
        invalid = sorted(set(map(int, selected)) - values)
        if invalid:
            raise ValidationError("category_id_list contains an unavailable live category", path="$.category_id_list")

    @staticmethod
    def _media_url(value: Any) -> str:
        if isinstance(value, str):
            return value
        obj = _first_object(value)
        result = _pick(obj, "media_url", "url", "name", default="")
        if not result and isinstance(value, list) and value:
            result = value[0] if isinstance(value[0], str) else ""
        if not result:
            raise FuploadError("media upload response did not contain a reusable URL")
        return str(result)

    def upload_media(self, endpoint: str, path: str) -> str:
        if not os.path.isfile(path):
            raise ValidationError("media file does not exist", path=path)
        return self._media_url(self.upload(endpoint, path))

    def upload_attachment(self, path: str) -> Dict[str, Any]:
        if not os.path.isfile(path):
            raise ValidationError("attachment file does not exist", path="$.file")
        data = Path(path).read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        upload_code = hashlib.md5(data, usedforsecurity=False).hexdigest()
        name = Path(path).name
        prepare = json_request(
            UPLOAD_SERVER + "/upload/v3/prepare", method="POST",
            trusted_service=UPLOAD_ORIGIN,
            body={
                "code": upload_code, "indexType": 2, "fileName": name,
                "files": [{"fullHash": upload_code, "totalSize": len(data), "chunks": [{"hash": upload_code, "size": len(data)}]}],
                "checksumAlgorithm": 1,
            },
        )
        if not isinstance(prepare, dict) or prepare.get("code") != 1:
            raise FuploadError(str((prepare or {}).get("message") or "attachment upload preparation failed"), endpoint="/upload/v3/prepare")
        prepared = prepare.get("data") or {}
        item = (prepared.get("items") or {}).get(upload_code) or {}
        if not item.get("exists"):
            if not item.get("url") or not item.get("callback"):
                raise FuploadError("attachment upload preparation omitted object credentials", endpoint="/upload/v3/prepare")
            parsed = urllib.parse.urlsplit(item["url"])
            if parsed.scheme.casefold() != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
                raise FuploadError("attachment object URL was not HTTPS", kind="trust_boundary")
            connection = http.client.HTTPSConnection(parsed.hostname, parsed.port, timeout=600)
            try:
                target = parsed.path + (("?" + parsed.query) if parsed.query else "")
                connection.request(
                    "PUT", target, body=data,
                    headers={"x-oss-callback": item["callback"], "Content-Length": str(len(data))},
                )
                response = connection.getresponse()
                response.read()
                if response.status < 200 or response.status >= 300:
                    raise FuploadError(
                        "attachment object upload returned HTTP %d" % response.status,
                        endpoint="object-storage PUT", http_status=response.status,
                    )
            except (OSError, http.client.HTTPException) as exc:
                raise FuploadError("attachment upload result is uncertain", verification_required=True) from exc
            finally:
                connection.close()
        index_code = str(prepared.get("id") or "")
        index = json_request(
            UPLOAD_SERVER + "/upload/v3/index/get", method="POST", body={"code": index_code},
            trusted_service=UPLOAD_ORIGIN,
        )
        index_data = (index or {}).get("data") or {}
        if (index or {}).get("code") != 1 or not index_data.get("code"):
            raise FuploadError("attachment upload index could not be read back", endpoint="/upload/v3/index/get")
        return {
            "file_id": 0, "name": str(index_data.get("fileName") or name),
            "value": str(index_data["code"]), "size": int(index_data.get("totalSize") or len(data)),
            "type": mimetypes.guess_type(name)[0] or "application/zip", "timestamp": 0,
            "sha256": digest,
        }

    def _resolve_media(self, endpoint: str, urls: Sequence[str], files: Sequence[str]) -> List[str]:
        result = list(urls)
        for path in files:
            result.append(self.upload_media(endpoint, path))
        return result

    def _validate_ids(self, selected: Iterable[int], available: Iterable[int], path: str) -> None:
        allowed = {int(value) for value in available}
        invalid = sorted({int(value) for value in selected} - allowed)
        if invalid:
            raise ValidationError("unknown or unavailable ID(s): %s" % invalid, path=path)

    def _validate_game_versions(self, selected: Iterable[str], path: str) -> None:
        available = {
            str(version).strip()
            for item in self.game_versions()["items"]
            for version in _list(item.get("versions"))
            if str(version).strip()
        }
        invalid = sorted({str(value).strip() for value in selected} - available)
        if invalid:
            raise ValidationError("unknown or unavailable game version(s): %s" % invalid, path=path)

    def create_plugin(self, doc: Dict[str, Any]) -> Any:
        self.post("/creator/wow/mod/permission_check", {})
        self._validate_ids(doc["mod_categories"], [x["id"] for x in self.categories()["items"]], "$.mod_categories")
        self._validate_business_options(doc)
        logo = doc.get("logo", "")
        if doc.get("logo_file"):
            logo = self.upload_media("/creator/wow/mod/upload_media", doc["logo_file"])
        screenshots = self._resolve_media("/creator/wow/mod/upload_media", doc.get("screenshots", []), doc.get("screenshot_files", []))
        if not logo:
            raise ValidationError("logo or logo_file is required", path="$.logo")
        payload = {
            "mod_categories": doc["mod_categories"], "content_origin": doc["content_origin"],
            "content_format": doc["content_format"], "name": doc["name"],
            "description": doc["description"], "intro": doc["intro"], "logo": logo,
            "screenshots": screenshots, "share_state": 0,
            "subscribe_plan_level": doc.get("subscribe_plan_level", 0),
            "link_to_channel": False,
        }
        self._normalize_commercial(payload, False)
        result = self.post("/creator/wow/mod/create", payload)
        ident = self._created_id(result, doc["name"])
        if ident <= 0:
            ident = self._created_id(self.list_plugins(doc["name"], 1, 100), doc["name"])
        if ident <= 0:
            ident = self._created_id(self.list_plugins("", 1, 100), doc["name"])
        if ident <= 0:
            raise FuploadError(
                "plugin was submitted but its ID could not be resolved; read the author list before retrying",
                kind="verification_required", verification_required=True,
            )
        readback = self.get_plugin(ident)
        _require_readback({
            "name": doc["name"], "category_ids": doc["mod_categories"],
            "content_origin": doc["content_origin"], "content_format": doc["content_format"],
            "intro": doc["intro"], "description": doc["description"], "logo": logo,
            "screenshots": screenshots, "public": False,
            "subscribe_plan_level": doc.get("subscribe_plan_level", 0), "link_to_channel": False,
        }, readback, "/creator/wow/mod/publish_detail")
        relationships = self._replace_relationships("plugin", ident, doc)
        return {
            "result": result, "id": ident,
            "review_intent": bool(doc.get("public") and doc.get("submit_for_review")),
            "public_after_first_version": bool(doc.get("public")),
            "readback": readback, "relationships": relationships,
        }

    def _plugin_form(self, ident: int, detail: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "id": ident,
            "mod_categories": _list(_pick(detail, "category_ids", "mod_categories", default=[])),
            "content_origin": int(_pick(detail, "t_original", "content_origin", default=0) or 0),
            "content_format": int(_pick(detail, "t_content_format", "content_format", default=0) or 0),
            "name": str(_pick(detail, "t_name", "name", default="")),
            "description": str(_pick(detail, "t_description_v2", "description", "t_description", default="")),
            "intro": str(_pick(detail, "t_description", "intro", default="")),
            "logo": str(_pick(detail, "t_logo", "logo", default="")),
            "screenshots": _urls(_pick(detail, "screenshots", default=[])),
            "share_state": int(_pick(detail, "t_share", "share_state", default=0) or 0),
            "subscribe_plan_level": int(_pick(detail, "t_subscribe_plan_level", "subscribe_plan_level", default=0) or 0),
            "link_to_channel": bool(_pick(detail, "t_link_to_channel", "link_to_channel", default=False)),
        }

    def edit_plugin(self, doc: Dict[str, Any]) -> Any:
        ident = int(doc["id"])
        form = self._plugin_form(ident, self.get_plugin_raw(ident))
        simple = ("name", "mod_categories", "content_origin", "content_format", "intro", "description", "logo", "screenshots", "subscribe_plan_level", "link_to_channel")
        for name in simple:
            if name in doc:
                form[name] = doc[name]
        if doc.get("logo_file"):
            form["logo"] = self.upload_media("/creator/wow/mod/upload_media", doc["logo_file"])
        if doc.get("screenshot_files"):
            form["screenshots"] = self._resolve_media("/creator/wow/mod/upload_media", form["screenshots"], doc["screenshot_files"])
        if "public" in doc:
            if doc["public"] and not _list(_first_object(self.plugin_versions(ident)).get("list")):
                raise ValidationError("a plugin must have a version before it can be submitted for public review", path="$.public")
            form["share_state"] = 1 if doc["public"] else 0
        if "mod_categories" in doc:
            self._validate_ids(form["mod_categories"], [x["id"] for x in self.categories()["items"]], "$.mod_categories")
        self._normalize_commercial(form, form["share_state"] == 1)
        self._validate_changed_business_options(form, doc)
        result = self.post("/creator/wow/mod/edit", form)
        readback = self.get_plugin(ident)
        mapping = {"mod_categories": "category_ids"}
        expected = {mapping.get(name, name): form[name] for name in doc if name != "public" and name in {
            "name", "mod_categories", "content_origin", "content_format", "intro", "description",
            "logo", "screenshots", "subscribe_plan_level", "link_to_channel", "public",
        }}
        if "public" in doc:
            expected["public"] = form["share_state"] == 1
        _require_readback(expected, readback, "/creator/wow/mod/publish_detail")
        relationships = self._replace_relationships("plugin", ident, doc)
        return {"result": result, "review_intent": bool(doc.get("public") and doc.get("submit_for_review")), "readback": readback, "relationships": relationships}

    def update_plugin(self, doc: Dict[str, Any]) -> Any:
        ident = int(doc["mod_id"])
        current = self.get_plugin_raw(ident)
        versions = _list(_first_object(self.plugin_versions(ident)).get("list"))
        for item in versions:
            remote = str(_pick(item, "t_display_name", "display_name", "version", "t_version", default="")).strip()
            if remote.lower() == str(doc["version"]).strip().lower():
                raise ValidationError("version already exists; overwrite is not allowed", path="$.version")
        self._validate_game_versions(doc["game_version_list"], "$.game_version_list")
        size = Path(doc["file"]).stat().st_size
        if size > 300 * 1024 * 1024 or Path(doc["file"]).suffix.lower() not in (".zip", ".rar", ".7z"):
            raise ValidationError("plugin package must be .zip/.rar/.7z and no larger than 300 MB", path="$.file")
        fields = {
            "mod_id": str(ident), "version": str(doc["version"]),
            "game_version_list": json.dumps(doc["game_version_list"], separators=(",", ":")),
            "link_to_channel": json.dumps(
                bool(doc["link_to_channel"])
                if "link_to_channel" in doc
                else bool(_pick(current, "t_link_to_channel", "link_to_channel", default=False))
            ),
        }
        if "changelog" in doc:
            fields["changelog"] = str(doc["changelog"])
        result = self.upload("/creator/wow/mod_file/upload_mod_file", doc["file"], fields)
        readback = {"plugin": self.get_plugin(ident), "versions": self.plugin_versions(ident)}
        version_items = _list(_first_object(readback["versions"]).get("list"))
        uploaded = next(
            (
                item for item in version_items
                if str(_pick(item, "t_display_name", "display_name", "version", "t_version", default="")).strip().lower()
                == str(doc["version"]).strip().lower()
            ),
            None,
        )
        if uploaded is None:
            raise FuploadError(
                "upload returned success but the new plugin version was not present in readback",
                endpoint="/creator/wow/mod_file/mod_file_list",
            )
        bound_versions = _list(_pick(uploaded, "versions", "game_version_list", "t_game_version_list", default=[]))
        bound_values = {
            str(_pick(item, "version", "build", "support_version", "value", default=""))
            if isinstance(item, dict) else str(item)
            for item in bound_versions
        }
        missing_bindings = sorted(set(map(str, doc["game_version_list"])) - bound_values)
        if not bound_versions or missing_bindings:
            raise FuploadError(
                "upload returned success but requested game-version bindings were not recorded",
                endpoint="/creator/wow/mod_file/mod_file_list",
                kind="verification_required", verification_required=True,
                details={"missing_builds": missing_bindings},
            )
        return {
            "result": result, "sha256": hashlib.sha256(Path(doc["file"]).read_bytes()).hexdigest(),
            "readback": readback,
        }

    @staticmethod
    def _linked_mods(value: Any) -> List[Dict[str, Any]]:
        result = []
        for item in _list(value):
            if not isinstance(item, dict):
                raise ValidationError("each linked_mods item must be an object", path="$.linked_mods")
            allowed = {"mod_id", "mod_name", "mod_file_id", "mod_version", "display_name", "update_type", "updateType"}
            unknown = set(item) - allowed
            if unknown:
                raise ValidationError("unknown linked_mods field: %s" % sorted(unknown)[0], path="$.linked_mods")
            result.append({
                "mod_id": item.get("mod_id"), "mod_name": item.get("mod_name"),
                "mod_file_id": item.get("mod_file_id"), "mod_version": item.get("mod_version") or None,
                "display_name": item.get("display_name") or None,
                "updateType": item.get("update_type", item.get("updateType", 1)),
            })
        return result

    def _config_form(self, ident: int, detail: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "tid": ident, "cloud_id": int(_pick(detail, "t_cloudblackid", "cloud_id", default=0) or 0),
            "title": str(_pick(detail, "t_title", "title", default="")),
            "content": str(_pick(detail, "t_content", "content", default="")),
            "content_format": int(_pick(detail, "t_content_format", "content_format", default=0) or 0),
            "intro": str(_pick(detail, "t_intro", "intro", default="")),
            "pic_url": _urls(_pick(detail, "pic_url", "picture_urls", "piclist", default=[])),
            "content_origin": int(_pick(detail, "t_content_origin", "content_origin", default=0) or 0),
            "sharing": int(_pick(detail, "t_sharing", "sharing", default=0) or 0),
            "link_to_channel": bool(_pick(detail, "t_link_to_channel", "link_to_channel", default=False)),
            "subscribe_plan_level": int(_pick(detail, "t_subscribe_plan_level", "subscribe_plan_level", default=0) or 0),
            "price": int(_pick(detail, "t_price", "price", default=0) or 0),
            "time_range": str(_pick(detail, "t_time_range", "time_range", default="")),
            "linked_mods": self._linked_mods(_pick(detail, "t_linked_mods", "linked_mods", default=[])),
            "ignored_unknown_mods": _list(_pick(detail, "t_ignored_unknown_mods", "ignored_unknown_mods", default=[])),
            "ignored_materials": _list(_pick(detail, "t_ignored_materials", "ignored_materials", default=[])),
            "ignored_fronts": _list(_pick(detail, "t_ignored_fronts", "ignored_fronts", default=[])),
            "roleid": str(_pick(detail, "t_roleid", "roleid", "role_id", default="")),
        }

    def create_config(self, doc: Dict[str, Any]) -> Any:
        backup = self.get_backup(int(doc["cloud_id"]))
        self._validate_backup_selection(backup, doc)
        pictures = self._resolve_media("/creator/wow/share_config/upload", doc.get("picture_urls", []), doc.get("picture_files", []))
        if not pictures:
            raise ValidationError("picture_urls or picture_files must contain at least one image", path="$.picture_urls")
        payload = {
            "cloud_id": doc["cloud_id"], "title": doc["title"], "content": doc["content"],
            "content_format": doc["content_format"], "intro": doc.get("intro", ""), "pic_url": pictures,
            "content_origin": doc["content_origin"], "sharing": 1 if doc["public"] else 0,
            "link_to_channel": bool(doc.get("link_to_channel", False)) if doc["public"] else False,
            "subscribe_plan_level": doc.get("subscribe_plan_level", 0), "price": doc.get("price", 0),
            "time_range": doc.get("time_range", ""), "linked_mods": self._linked_mods(doc["linked_mods"]),
            "ignored_unknown_mods": doc["ignored_unknown_mods"], "ignored_materials": doc["ignored_materials"],
            "ignored_fronts": doc["ignored_fronts"], "roleid": doc["roleid"],
        }
        self._normalize_commercial(payload, bool(doc["public"]))
        self._validate_business_options(payload)
        result = self.post("/creator/wow/share_config/release", payload)
        ident = self._created_id(result, doc["title"], doc["cloud_id"])
        if ident <= 0:
            ident = self._created_id(self.list_configs(doc["title"], 0, 100), doc["title"], doc["cloud_id"])
        if ident <= 0:
            ident = self._created_id(self.list_configs("", 0, 100), doc["title"], doc["cloud_id"])
        if ident <= 0:
            raise FuploadError("configuration was submitted but its ID could not be resolved; read the author list before retrying", kind="verification_required", verification_required=True)
        readback = self.get_config(ident)
        expected = {name: payload[name] for name in (
            "title", "content", "content_format", "intro", "content_origin", "subscribe_plan_level", "price", "time_range",
            "linked_mods", "ignored_unknown_mods", "ignored_materials", "ignored_fronts", "roleid",
        )}
        expected["public"] = bool(payload["sharing"])
        expected["picture_urls"] = pictures
        expected["link_to_channel"] = payload["link_to_channel"]
        _require_readback(expected, readback, "/creator/wow/share_config/details_aps")
        relationships = self._replace_relationships("config", ident, doc)
        return {"result": result, "id": ident, "review_intent": bool(doc.get("public") and doc.get("submit_for_review")), "readback": readback, "relationships": relationships}

    def update_config(self, doc: Dict[str, Any], metadata_only: bool) -> Any:
        ident = int(doc["id"])
        form = self._config_form(ident, self.get_config_raw(ident))
        if metadata_only:
            mapping = {
                "title": "title", "content": "content", "content_format": "content_format", "intro": "intro",
                "picture_urls": "pic_url", "content_origin": "content_origin", "link_to_channel": "link_to_channel",
                "subscribe_plan_level": "subscribe_plan_level", "price": "price", "time_range": "time_range",
            }
            for source, target in mapping.items():
                if source in doc:
                    form[target] = doc[source]
            if doc.get("picture_files"):
                form["pic_url"] = self._resolve_media("/creator/wow/share_config/upload", form["pic_url"], doc["picture_files"])
            if "public" in doc:
                form["sharing"] = 1 if doc["public"] else 0
        else:
            mapping = {
                "cloud_id": "cloud_id", "linked_mods": "linked_mods", "ignored_unknown_mods": "ignored_unknown_mods",
                "ignored_materials": "ignored_materials", "ignored_fronts": "ignored_fronts", "roleid": "roleid",
            }
            for source, target in mapping.items():
                if source in doc:
                    form[target] = self._linked_mods(doc[source]) if source == "linked_mods" else doc[source]
            backup = self.get_backup(int(form["cloud_id"]))
            selection = {name: form[name] for name in ("linked_mods", "ignored_unknown_mods", "ignored_materials", "ignored_fronts", "roleid")}
            self._validate_backup_selection(backup, selection)
        self._normalize_commercial(form, bool(form["sharing"]))
        self._validate_changed_business_options(form, doc)
        result = self.post("/creator/wow/share_config/update", form)
        readback = self.get_config(ident)
        expected = {}
        mapping = {"picture_urls": "pic_url", "public": "sharing"}
        for name in {
            "cloud_id", "title", "content", "content_format", "intro", "picture_urls", "content_origin",
            "link_to_channel", "subscribe_plan_level", "price", "time_range", "linked_mods",
            "ignored_unknown_mods", "ignored_materials", "ignored_fronts", "roleid",
        }:
            if name in doc:
                expected[name] = form[mapping.get(name, name)]
        if "public" in doc:
            expected["public"] = bool(form["sharing"])
        if doc.get("picture_files"):
            expected["picture_urls"] = form["pic_url"]
        _require_readback(expected, readback, "/creator/wow/share_config/details_aps")
        relationships = self._replace_relationships("config", ident, doc)
        return {"result": result, "review_intent": bool(doc.get("public") and doc.get("submit_for_review")), "readback": readback, "relationships": relationships}

    def _wa_form(self, ident: int, detail: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "id": ident,
            "game_version_id": int(_pick(detail, "game_version_id", "t_game_version_id", default=0) or 0),
            "name": str(_pick(detail, "name", "t_name", default="")), "intro": str(_pick(detail, "intro", "t_intro", default="")),
            "description": str(_pick(detail, "description", "t_description", default="")),
            "content_format": int(_pick(detail, "content_format", "t_content_format", default=0) or 0),
            "thumbnail": str(_pick(detail, "thumbnail", "t_thumbnail", default="")),
            "images": _urls(_pick(detail, "images", "t_images", default=[])),
            "category_id_list": _numeric_ids(
                _pick(detail, "category_id_list", "category_ids", "category_list", default=[])
            ),
            "content_origin": int(_pick(detail, "content_origin", "t_content_origin", default=0) or 0),
            "subscribe_plan_level": int(_pick(detail, "subscribe_plan_level", "t_subscribe_plan_level", default=0) or 0),
            "price": int(_pick(detail, "price", "t_price", default=0) or 0),
            "time_range": str(_pick(detail, "time_range", "t_time_range", default="")),
            "share_state": int(_pick(detail, "share_state", "t_share_state", default=2) or 2),
            "link_to_channel": bool(_pick(detail, "link_to_channel", "t_link_to_channel", default=False)),
            "attachments": _list(_pick(detail, "attachments", default=[])), "wa_log": "",
        }

    def create_wa(self, doc: Dict[str, Any]) -> Any:
        self._validate_ids([doc["game_version_id"]], [x["id"] for x in self.game_versions()["items"]], "$.game_version_id")
        self._validate_wa_categories(int(doc["game_version_id"]), doc["category_id_list"])
        self._validate_attachments(doc.get("attachments", []))
        thumbnail = doc.get("thumbnail", "")
        if doc.get("thumbnail_file"):
            thumbnail = self.upload_media("/creator/wow/wa/upload_media", doc["thumbnail_file"])
        if not thumbnail:
            raise ValidationError("thumbnail or thumbnail_file is required", path="$.thumbnail")
        images = self._resolve_media("/creator/wow/wa/upload_media", doc.get("images", []), doc.get("image_files", []))
        payload = {
            "game_version_id": doc["game_version_id"], "name": doc["name"], "intro": doc.get("intro", ""),
            "description": doc.get("description", ""), "content_format": doc["content_format"],
            "thumbnail": thumbnail, "images": images, "category_id_list": doc["category_id_list"],
            "content_origin": doc["content_origin"], "subscribe_plan_level": doc.get("subscribe_plan_level", 0),
            "price": doc.get("price", 0), "time_range": doc.get("time_range", ""),
            "share_state": 1 if doc["public"] else 2,
            "link_to_channel": bool(doc.get("link_to_channel", False)) if doc["public"] else False,
            "attachments": doc.get("attachments", []), "wa_str": doc["wa_str"],
            "wa_str_titles": doc.get("wa_str_titles", []), "wa_log": doc["wa_log"],
            "string_mode": doc["string_mode"],
        }
        self._normalize_commercial(payload, bool(doc["public"]))
        self._validate_business_options(payload)
        result = self.post("/creator/wow/wa/publish", payload)
        ident = self._created_id(result, doc["name"])
        if ident <= 0:
            ident = self._created_id(self.list_was(doc["name"], 0, 100), doc["name"])
        if ident <= 0:
            ident = self._created_id(self.list_was("", 0, 100), doc["name"])
        if ident <= 0:
            raise FuploadError("WA was submitted but its ID could not be resolved; read the author list before retrying", kind="verification_required", verification_required=True)
        readback = self.get_wa(ident)
        expected = {name: doc[name] for name in (
            "game_version_id", "name", "intro", "description", "content_format", "content_origin",
            "subscribe_plan_level", "price", "time_range", "link_to_channel", "attachments",
        ) if name in payload}
        expected = {name: payload[name] for name in expected}
        expected.update({"thumbnail": thumbnail, "images": images, "public": doc["public"], "categories": [{"id": value, "name": None} for value in doc["category_id_list"]]})
        actual_for_compare = dict(readback)
        actual_for_compare["categories"] = [{"id": item.get("id"), "name": None} for item in readback.get("categories", [])]
        _require_readback(expected, actual_for_compare, "/creator/wow/wa/detail_aps")
        relationships = self._replace_relationships("wa", ident, doc)
        return {"result": result, "id": ident, "review_intent": bool(doc.get("public") and doc.get("submit_for_review")), "readback": readback, "relationships": relationships}

    def edit_wa(self, doc: Dict[str, Any]) -> Any:
        ident = int(doc["id"])
        form = self._wa_form(ident, self.get_wa_raw(ident))
        mapping = {
            "game_version_id": "game_version_id", "name": "name", "intro": "intro", "description": "description",
            "content_format": "content_format", "thumbnail": "thumbnail", "images": "images",
            "category_id_list": "category_id_list", "content_origin": "content_origin",
            "subscribe_plan_level": "subscribe_plan_level", "price": "price", "time_range": "time_range",
            "link_to_channel": "link_to_channel", "attachments": "attachments",
        }
        for source, target in mapping.items():
            if source in doc:
                form[target] = doc[source]
        if doc.get("thumbnail_file"):
            form["thumbnail"] = self.upload_media("/creator/wow/wa/upload_media", doc["thumbnail_file"])
        if doc.get("image_files"):
            form["images"] = self._resolve_media("/creator/wow/wa/upload_media", form["images"], doc["image_files"])
        if "public" in doc:
            form["share_state"] = 1 if doc["public"] else 2
        self._validate_ids([form["game_version_id"]], [x["id"] for x in self.game_versions()["items"]], "$.game_version_id")
        self._validate_wa_categories(int(form["game_version_id"]), form["category_id_list"])
        self._normalize_commercial(form, form["share_state"] == 1)
        self._validate_changed_business_options(form, doc)
        self._validate_attachments(form.get("attachments", []))
        result = self.post("/creator/wow/wa/update", form)
        readback = self.get_wa(ident)
        mapping = {"category_id_list": "categories"}
        expected = {mapping.get(name, name): form[mapping.get(name, name)] for name in doc if name in {
            "game_version_id", "name", "intro", "description", "content_format", "thumbnail", "images",
            "category_id_list", "content_origin", "subscribe_plan_level", "price", "time_range",
            "link_to_channel", "attachments",
        }}
        if "public" in doc:
            expected["public"] = form["share_state"] == 1
        if "categories" in expected:
            expected["categories"] = [{"id": value, "name": None} for value in expected["categories"]]
        actual_for_compare = dict(readback)
        actual_for_compare["categories"] = [{"id": item.get("id"), "name": None} for item in readback.get("categories", [])]
        _require_readback(expected, actual_for_compare, "/creator/wow/wa/detail_aps")
        relationships = self._replace_relationships("wa", ident, doc)
        return {"result": result, "review_intent": bool(doc.get("public") and doc.get("submit_for_review")), "readback": readback, "relationships": relationships}

    def update_wa(self, doc: Dict[str, Any]) -> Any:
        ident = int(doc["id"])
        current = self.get_wa_raw(ident)
        next_value = self.post("/creator/wow/wa/get_next_version", {"id": ident})
        version = str(doc.get("version") or _pick(_first_object(next_value), "version", "next_version", "t_version", default=next_value if isinstance(next_value, str) else ""))
        if not version:
            raise FuploadError("NewBeeBox did not return a next WA version")
        if not _version_greater(version, _pick(current, "t_version", "version", default="")):
            raise ValidationError("version must be greater than the current WA version", path="$.version")
        payload = {
            "id": ident, "version": version, "wa_str": doc["wa_str"],
            "wa_str_titles": (
                doc["wa_str_titles"] if "wa_str_titles" in doc
                else _list(_pick(current, "t_wa_str_titles", "wa_str_titles", default=[]))
            ),
            "wa_log": doc["wa_log"],
            "link_to_channel": (
                bool(doc["link_to_channel"])
                if "link_to_channel" in doc
                else bool(_pick(current, "t_link_to_channel", "link_to_channel", default=False))
            ),
        }
        result = self.post("/creator/wow/wa/update_wa_str", payload)
        readback = self.latest_wa(ident)
        actual_version = str(_pick(_first_object(readback), "version", "t_version", default=""))
        if actual_version != version:
            raise FuploadError("WA update version was not present in readback", kind="verification_required", verification_required=True, endpoint="/creator/wow/wa_log/latest_str_info")
        return {"result": result, "version": version, "readback": readback}

    def latest_wa(self, ident: int) -> Any:
        return _redact_wa(self.post("/creator/wow/wa_log/latest_str_info", {"wa_id": ident}))

    def _validate_attachments(self, attachments: Any) -> None:
        allowed = {"name", "install_type", "install_path", "value", "is_compressed", "timestamp"}
        paths = self.attachment_paths()
        candidates = []
        def walk_rows(rows: Sequence[Any]) -> None:
            for value in rows:
                if not isinstance(value, dict):
                    continue
                if "value" in value and ("extract_base_dir" in value or "install_path" in value):
                    candidates.append(value)
                for key in ("children", "items", "options"):
                    walk_rows(_list(value.get(key)))
        walk_rows(_option_rows(paths))
        if attachments and not candidates:
            raise FuploadError("live attachment path response contained no selectable values", kind="platform_data_error")
        for index, item in enumerate(attachments):
            path = "$.attachments[%d]" % index
            if not isinstance(item, dict):
                raise ValidationError("attachment must be an object", path=path)
            unknown = set(item) - allowed
            if unknown:
                raise ValidationError("unknown attachment field: %s" % sorted(unknown)[0], path=path)
            for name in ("name", "install_type", "install_path", "value", "is_compressed"):
                if name not in item:
                    raise ValidationError("field is required", path=path + "." + name)
            if candidates and not any(
                str(option.get("value")) == str(item["install_type"])
                and str(option.get("extract_base_dir") or item["install_path"]) == str(item["install_path"])
                for option in candidates
            ):
                raise ValidationError("install type/path is not in the current platform options", path=path + ".install_path")

    def execute_write(self, resource: str, action: str, doc: Dict[str, Any]) -> Any:
        if action == "delete" and resource in ("plugin", "config", "wa"):
            return self.delete(resource, doc)
        if (resource, action) == ("plugin", "create"): return self.create_plugin(doc)
        if (resource, action) == ("plugin", "update"): return self.update_plugin(doc)
        if (resource, action) == ("plugin", "edit"): return self.edit_plugin(doc)
        if (resource, action) == ("config", "create"): return self.create_config(doc)
        if (resource, action) == ("config", "update"): return self.update_config(doc, False)
        if (resource, action) == ("config", "edit"): return self.update_config(doc, True)
        if (resource, action) == ("wa", "create"): return self.create_wa(doc)
        if (resource, action) == ("wa", "update"): return self.update_wa(doc)
        if (resource, action) == ("wa", "edit"): return self.edit_wa(doc)
        if (resource, action) == ("plugin-changelog", "edit"):
            result = self.post("/creator/wow/mod_file/edit_changelog", {"file_id": doc["file_id"], "changelog": doc["changelog"] or ""})
            return {"result": result, "readback": self.post("/creator/wow/mod_file/get_changelog", {"file_id": doc["file_id"]})}
        if (resource, action) == ("wa-changelog", "edit"):
            result = self.post("/creator/wow/wa_log/edit", {"wa_log_id": doc["id"], "content": doc["wa_log"] or ""})
            readback = None
            if doc.get("wa_id"):
                readback = self.post("/creator/wow/wa_log/list", {"wa_id": doc["wa_id"], "pagenum": 1, "pagesize": 20})
            return {"result": result, "readback": readback}
        if action == "set" and resource.endswith("-co-author"):
            base = resource[:-len("-co-author")]
            if base in RELATION_TYPES:
                relationships = self._replace_relationships(base, int(doc["content_id"]), {"co_authors": doc["co_authors"]})
                return relationships["co_authors"]
        if action == "set" and resource.endswith("-reference"):
            base = resource[:-len("-reference")]
            if base in RELATION_TYPES:
                relationships = self._replace_relationships(base, int(doc["source_id"]), {"references": doc["references"]})
                return relationships["references"]
        if (resource, action) == ("wa-share-code", "set"):
            result = self.post_next("/bannerserver/ShareCode/Set", {"gameId": 1, "moduleId": doc["module_id"], "moduleType": 3})
            return {"result": result, "readback": self.get_wa(int(doc["module_id"]))}
        if (resource, action) == ("wa-media", "upload"):
            if doc["kind"] == "attachment":
                uploaded = self.upload_attachment(doc["file"])
                attachment = {
                    "name": uploaded["name"], "value": uploaded["value"],
                    "is_compressed": True, "timestamp": uploaded.get("timestamp", 0),
                }
                if "install_type" in doc:
                    attachment["install_type"] = doc["install_type"]
                if "install_path" in doc:
                    attachment["install_path"] = doc["install_path"]
                return {"upload": uploaded, "attachment": attachment}
            return {"url": self.upload_media("/creator/wow/wa/upload_media", doc["file"])}
        raise FuploadError("unsupported NewBeeBox write operation", kind="unsupported_operation")

    def delete(self, resource: str, doc: Mapping[str, Any]) -> Dict[str, Any]:
        ident = int(doc["id"])
        getters = {"plugin": self.get_plugin, "config": self.get_config, "wa": self.get_wa}
        listers = {
            "plugin": lambda keyword: self.list_plugins(keyword, 1, 100),
            "config": lambda keyword: self.list_configs(keyword, 0, 100),
            "wa": lambda keyword: self.list_was(keyword, 0, 100),
        }
        endpoints = {
            "plugin": "/creator/wow/mod/remove",
            "config": "/creator/wow/share_config/delete",
            "wa": "/creator/wow/wa/delete",
        }
        before = getters[resource](ident)
        name = str(before.get("name") or before.get("title") or "")
        response = self.post(endpoints[resource], {"id": ident})
        listing = listers[resource](name)
        _total, rows, _obj = _paged_items(listing)
        if any(int(_pick(row, "id", "t_id", "mod_id", "wa_id", default=0) or 0) == ident for row in rows):
            raise FuploadError(
                "delete response succeeded but the target remains in the author list",
                kind="verification_required", endpoint=endpoints[resource], verification_required=True,
            )
        return {"result": response, "deleted": True, "id": ident, "before": before, "readback": {"present": False}}

    def execute_read(self, resource: str, action: str, args: Any) -> Any:
        if resource == "session" and action == "doctor":
            self.headers
            return {
                "authenticated": True,
                "source": "NewBeeBox desktop auth-store",
                "auth_store": str(auth_store_dir()),
                "auth_store_source": "windows-known-folder",
                "api_origins": dict(NEWBEE_ORIGINS),
                "trusted": True,
            }
        if resource in RELATION_TYPES:
            types = RELATION_TYPES[resource]
            if action == "co-author-search": return self.post("/creator/co_author/search_user", {"keyword": args.keyword})
            if action == "co-author-list": return self.post("/creator/co_author/list", {"content_type": types["co_authors"], "content_id": args.id})
            if action == "reference-search": return self.post("/creator/content_reference/search", {"keyword": args.keyword, "limit": 20, "target_types": [types["references"]]})
            if action == "reference-list": return self.post("/creator/content_reference/list", {"content_type": types["references"], "content_id": args.id})
        if resource == "plugin":
            if action == "list": return self.list_plugins(args.keyword, args.page, args.page_size)
            if action == "get": return self.get_plugin(args.id)
            if action == "categories": return self.categories()
            if action == "game-versions": return self.game_versions()
            if action == "versions": return self.plugin_versions(args.id, args.page, args.page_size)
            if action == "changelog-list": return self.post("/creator/wow/mod_file/changelog_list", {"mod_id": args.id, "pagenum": args.page, "pagesize": args.page_size})
            if action == "changelog-get": return self.post("/creator/wow/mod_file/get_changelog", {"file_id": args.id})
        if resource == "config":
            if action == "list": return self.list_configs(args.keyword, args.offset, args.page_size)
            if action == "get": return self.get_config(args.id)
            if action == "backups": return self.list_backups()
            if action == "backup-get": return self.get_backup(args.id)
        if resource == "wa":
            if action == "list": return self.list_was(args.keyword, args.offset, args.page_size)
            if action == "get": return self.get_wa(args.id)
            if action == "categories": return self.wa_categories(args.game_version_id)
            if action == "attachment-paths": return self.attachment_paths()
            if action == "changelog-latest": return self.latest_wa(args.id)
            if action == "changelog-list": return _redact_wa(self.post("/creator/wow/wa_log/list", {"wa_id": args.id, "pagenum": args.page, "pagesize": args.page_size}))
        if resource == "options":
            if action == "content-origins": return self.content_origins()
            if action == "subscribe-plans": return self.subscribe_plans()
            if action == "time-ranges": return self.time_ranges()
        raise FuploadError("unsupported NewBeeBox read operation", kind="unsupported_operation")
