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
from .newbee_auth import API_BASE, creator_headers


METADATA_URL = os.environ.get("FUPLOAD_NEWBEE_METADATA_URL", "https://cdn2.newbeebox.com/modconfig.json")
UPLOAD_SERVER = os.environ.get("FUPLOAD_NEWBEE_UPLOAD_SERVER", "https://api.next.newbeebox.com/uploadserver").rstrip("/")
NEXT_API_BASE = os.environ.get("FUPLOAD_NEWBEE_NEXT_API_BASE", "https://api.next.newbeebox.com").rstrip("/")


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
        envelope = json_request(self.base + endpoint, method="POST", headers=self.headers, body=body)
        if not isinstance(envelope, dict) or envelope.get("code") != 1:
            raise FuploadError(
                str((envelope or {}).get("message") or "NewBeeBox request failed"),
                endpoint=endpoint,
                business_code=(envelope or {}).get("code"),
            )
        return envelope.get("data")

    def post_next(self, endpoint: str, body: Mapping[str, Any]) -> Any:
        envelope = json_request(NEXT_API_BASE + endpoint, method="POST", headers=self.headers, body=body)
        if not isinstance(envelope, dict) or envelope.get("code") != 1:
            raise FuploadError(
                str((envelope or {}).get("message") or "NewBeeBox next request failed"),
                endpoint=endpoint,
                business_code=(envelope or {}).get("code"),
            )
        return envelope.get("data")

    def upload(self, endpoint: str, path: str, fields: Optional[Mapping[str, str]] = None) -> Any:
        envelope = multipart_request(self.base + endpoint, path, headers=self.headers, fields=fields)
        if not isinstance(envelope, dict) or envelope.get("code") != 1:
            raise FuploadError(
                str((envelope or {}).get("message") or "NewBeeBox upload failed"),
                endpoint=endpoint,
                business_code=(envelope or {}).get("code"),
            )
        return envelope.get("data")

    def metadata(self) -> Dict[str, Any]:
        value = json_request(METADATA_URL)
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
            "roleid": _pick(detail, "t_roleid", "roleid", "role_id", default=""),
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
            connection_type = http.client.HTTPSConnection if parsed.scheme == "https" else http.client.HTTPConnection
            connection = connection_type(parsed.hostname, parsed.port, timeout=600)
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
        index = json_request(UPLOAD_SERVER + "/upload/v3/index/get", method="POST", body={"code": index_code})
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

    def create_plugin(self, doc: Dict[str, Any]) -> Any:
        self.post("/creator/wow/mod/permission_check", {})
        self._validate_ids(doc["mod_categories"], [x["id"] for x in self.categories()["items"]], "$.mod_categories")
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
            "screenshots": screenshots, "share_state": 1 if doc["public"] else 0,
            "subscribe_plan_level": doc.get("subscribe_plan_level", 0),
            "link_to_channel": bool(doc.get("link_to_channel", False)) if doc["public"] else False,
        }
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
        return {
            "result": result, "id": ident,
            "review_intent": bool(doc.get("public") and doc.get("submit_for_review")),
            "readback": self.get_plugin(ident),
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
        result = self.post("/creator/wow/mod/edit", form)
        return {"result": result, "review_intent": bool(doc.get("public") and doc.get("submit_for_review")), "readback": self.get_plugin(ident)}

    def update_plugin(self, doc: Dict[str, Any]) -> Any:
        ident = int(doc["mod_id"])
        current = self.get_plugin_raw(ident)
        versions = _list(_first_object(self.plugin_versions(ident)).get("list"))
        for item in versions:
            remote = str(_pick(item, "t_display_name", "display_name", "version", "t_version", default="")).strip()
            if remote.lower() == str(doc["version"]).strip().lower():
                raise ValidationError("version already exists; overwrite is not allowed", path="$.version")
        self._validate_ids(doc["game_version_list"], [x["id"] for x in self.game_versions()["items"]], "$.game_version_list")
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
        return {
            "result": result, "sha256": hashlib.sha256(Path(doc["file"]).read_bytes()).hexdigest(),
            "readback": {"plugin": self.get_plugin(ident), "versions": self.plugin_versions(ident)},
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
        result = self.post("/creator/wow/share_config/release", payload)
        ident = self._created_id(result, doc["title"], doc["cloud_id"])
        if ident <= 0:
            ident = self._created_id(self.list_configs(doc["title"], 0, 100), doc["title"], doc["cloud_id"])
        if ident <= 0:
            ident = self._created_id(self.list_configs("", 0, 100), doc["title"], doc["cloud_id"])
        if ident <= 0:
            raise FuploadError("configuration was submitted but its ID could not be resolved; read the author list before retrying", kind="verification_required", verification_required=True)
        return {"result": result, "id": ident, "review_intent": bool(doc.get("public") and doc.get("submit_for_review")), "readback": self.get_config(ident)}

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
        result = self.post("/creator/wow/share_config/update", form)
        return {"result": result, "review_intent": bool(doc.get("public") and doc.get("submit_for_review")), "readback": self.get_config(ident)}

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
        categories = self.wa_categories(int(doc["game_version_id"]))
        available = set(_numeric_ids(categories))
        selected = set(_numeric_ids(doc["category_id_list"]))
        if available and not selected.issubset(available):
            raise ValidationError("category_id_list contains an unavailable live category", path="$.category_id_list")
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
        result = self.post("/creator/wow/wa/publish", payload)
        ident = self._created_id(result, doc["name"])
        if ident <= 0:
            ident = self._created_id(self.list_was(doc["name"], 0, 100), doc["name"])
        if ident <= 0:
            ident = self._created_id(self.list_was("", 0, 100), doc["name"])
        if ident <= 0:
            raise FuploadError("WA was submitted but its ID could not be resolved; read the author list before retrying", kind="verification_required", verification_required=True)
        return {"result": result, "id": ident, "review_intent": bool(doc.get("public") and doc.get("submit_for_review")), "readback": self.get_wa(ident)}

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
        categories = self.wa_categories(int(form["game_version_id"]))
        available = set(_numeric_ids(categories))
        selected = set(_numeric_ids(form["category_id_list"]))
        if available and not selected.issubset(available):
            raise ValidationError("category_id_list contains an unavailable live category", path="$.category_id_list")
        self._validate_attachments(form.get("attachments", []))
        result = self.post("/creator/wow/wa/update", form)
        return {"result": result, "review_intent": bool(doc.get("public") and doc.get("submit_for_review")), "readback": self.get_wa(ident)}

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
        return {"result": result, "version": version, "readback": self.latest_wa(ident)}

    def latest_wa(self, ident: int) -> Any:
        return _redact_wa(self.post("/creator/wow/wa_log/latest_str_info", {"wa_id": ident}))

    def _validate_attachments(self, attachments: Any) -> None:
        allowed = {"name", "install_type", "install_path", "value", "is_compressed", "timestamp"}
        paths = self.attachment_paths()
        candidates = []
        def walk(value: Any) -> None:
            if isinstance(value, dict):
                if "value" in value or "extract_base_dir" in value:
                    candidates.append(value)
                for child in value.values():
                    walk(child)
            elif isinstance(value, list):
                for child in value:
                    walk(child)
        walk(paths)
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
        if (resource, action) == ("wa-co-author", "set"):
            total = sum(float(x.get("share_percent", 0)) for x in doc["co_authors"])
            if total > 1.000001:
                raise ValidationError("co-author share_percent total may not exceed 1", path="$.co_authors")
            result = self.post("/creator/co_author/set", {"content_type": 3, "content_id": doc["content_id"], "co_authors": doc["co_authors"]})
            return {"result": result, "readback": self.post("/creator/co_author/list", {"content_type": 3, "content_id": doc["content_id"]})}
        if (resource, action) == ("wa-reference", "set"):
            result = self.post("/creator/content_reference/set", {"source_type": 2, "source_id": doc["source_id"], "references": doc["references"]})
            return {"result": result, "readback": self.post("/creator/content_reference/list", {"content_type": 2, "content_id": doc["source_id"]})}
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

    def execute_read(self, resource: str, action: str, args: Any) -> Any:
        if resource == "session" and action == "doctor":
            self.headers
            return {"authenticated": True, "source": "NewBeeBox desktop auth-store"}
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
            if action == "co-author-search": return self.post("/creator/co_author/search_user", {"keyword": args.keyword})
            if action == "co-author-list": return self.post("/creator/co_author/list", {"content_type": 3, "content_id": args.id})
            if action == "reference-search": return self.post("/creator/content_reference/search", {"keyword": args.keyword, "limit": 20, "target_types": [2]})
            if action == "reference-list": return self.post("/creator/content_reference/list", {"content_type": 2, "content_id": args.id})
        raise FuploadError("unsupported NewBeeBox read operation", kind="unsupported_operation")
