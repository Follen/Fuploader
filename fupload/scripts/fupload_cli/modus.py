"""ModUs Creator plugin/project provider.

The Creator desktop client stores its bearer token in a DPAPI CurrentUser
file.  This module deliberately keeps the token and presigned URL out of
returned documents and exception messages.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import hashlib
import http.client
import json
import os
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path
from typing import Any, Dict, Mapping, Optional

from .errors import FuploadError, ValidationError, redact
from .state_machine import COMPLETE, ProjectStateMachine
from .modus_zip import parse_modus_zip


API_BASE = "https://app.modus.cool/api/"
TOKEN_PATH = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local")) / "ModUs.Creator" / "auth" / "token.dat"
TOKEN_ENTROPY = b"ModUs.Creator.TokenStore.v1"
MAX_PACKAGE_BYTES = 200 * 1024 * 1024
_SECRET_KEYS = {"token", "access_token", "authorization", "cookie", "signedurl", "signed_url", "upload_url"}
_WIRE_NAMES = {
    "project_id": "projectId", "file_id": "fileId", "alt_name": "altName",
    "synchronization_type": "synchronizationType", "required_tier_id": "requiredTierId",
    "repo_url": "repoUrl", "supported_game_versions": "supportedGameVersionsReqs",
    "zip_size": "zipSize", "unzip_size": "unzipSize", "toc_version": "tocVersion",
}


def _license_json(value: Any, document: Mapping[str, Any]) -> str:
    """Build the JSON string emitted by Creator's BuildLicenseJson helper.

    The desktop client receives a ProjectLicenseContent object and only adds
    non-empty ``type``, ``holder``, ``year`` and ``content`` properties.  CLI
    callers may provide either that object, a JSON object string, or the
    compact license name shown by the UI.
    """
    source: Dict[str, Any] = {}
    if isinstance(value, Mapping):
        source.update(value)
    elif isinstance(value, str):
        text = value.strip()
        if text.startswith("{"):
            try:
                parsed = json.loads(text)
            except (TypeError, ValueError):
                parsed = None
            if isinstance(parsed, Mapping):
                source.update(parsed)
            else:
                source["type"] = value
        elif text:
            source["type"] = value
    # These aliases are used by the project detail reader and the Creator UI.
    aliases = {
        "type": ("type", "license_name", "licenseName"),
        "holder": ("holder", "copyright_holder", "copyrightHolder"),
        "year": ("year", "copyright_year", "copyrightYear"),
        "content": ("content", "license_content", "licenseContent"),
    }
    result: Dict[str, str] = {}
    for target, names in aliases.items():
        candidate = next((source.get(name) for name in names if source.get(name) is not None), None)
        if candidate is None:
            candidate = next((document.get(name) for name in names if document.get(name) is not None), None)
        if candidate is not None and str(candidate).strip():
            result[target] = str(candidate)
    return json.dumps(result, ensure_ascii=False, separators=(",", ":"))


def _category_ids(value: Any) -> Any:
    """Project category selections to the integer IDs accepted by the API."""
    if value is None:
        return []
    values = value if isinstance(value, (list, tuple, set)) else str(value).split(",")
    output = []
    for item in values:
        if isinstance(item, Mapping):
            item = item.get("id") or item.get("categoryId") or item.get("value")
        if item is None or str(item).strip() == "":
            continue
        text = str(item).strip()
        try:
            output.append(int(text))
        except ValueError:
            output.append(text)
    return output


def _sync_type(value: Any) -> Any:
    if value is None:
        return 0
    text = str(value).strip()
    try:
        return int(text)
    except ValueError:
        return value


def _null_marker(value: Any) -> str:
    if value is None or (isinstance(value, str) and not value.strip()):
        return "<null>"
    return str(value).strip() if isinstance(value, str) else str(value)


def _image_ops(value: Any) -> list[Dict[str, str]]:
    if not isinstance(value, list) or not value:
        raise ValidationError("image_ops must be a non-empty list", path="image_ops")
    result: list[Dict[str, str]] = []
    for index, item in enumerate(value):
        path = "image_ops[%d]" % index
        if not isinstance(item, Mapping):
            raise ValidationError("image operation must be an object", path=path)
        unknown = sorted(set(item) - {"op", "name", "base64"})
        if unknown:
            raise ValidationError("unknown image operation field(s): %s" % ", ".join(unknown), path=path + "." + unknown[0])
        op = item.get("op")
        name = item.get("name")
        if op not in ("upload", "delete"):
            raise ValidationError("image operation must be upload or delete", path=path + ".op")
        if not isinstance(name, str) or not name.strip():
            raise ValidationError("image operation name must be non-empty", path=path + ".name")
        operation = {"op": op, "name": name.strip()}
        if op == "upload":
            payload = item.get("base64")
            if not isinstance(payload, str) or not payload.strip():
                raise ValidationError("upload image operation requires base64", path=path + ".base64")
            operation["base64"] = payload
        elif "base64" in item:
            raise ValidationError("delete image operation must not include base64", path=path + ".base64")
        result.append(operation)
    return result


def _positive_id(value: Any, *, field: str) -> int:
    """Coerce an API identifier and reject ambiguous/non-positive targets."""
    if isinstance(value, bool):
        raise ValidationError("%s must be a positive integer" % field, path=field)
    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise ValidationError("%s must be a positive integer" % field, path=field) from exc
    if result <= 0:
        raise ValidationError("%s must be a positive integer" % field, path=field)
    return result


def _supported_game_versions(value: Any) -> list[Dict[str, str]]:
    """Map CLI aliases to Creator's anonymous {gameVersion, server} objects.

    ``server`` is intentionally required: the Creator client sends it as a
    string and no safe default can be inferred from a display game version.
    """
    if value is None:
        return []
    if not isinstance(value, (list, tuple)):
        raise ValidationError("supported_game_versions must be a list", path="supported_game_versions")
    result: list[Dict[str, str]] = []
    for index, item in enumerate(value):
        if not isinstance(item, Mapping):
            raise ValidationError(
                "each supported game version must include game_version and server",
                path="supported_game_versions[%d]" % index,
            )
        game_version = item.get("gameVersion", item.get("game_version"))
        server = item.get("server")
        if not str(game_version or "").strip() or not str(server or "").strip():
            raise ValidationError(
                "each supported game version must include game_version and server",
                path="supported_game_versions[%d]" % index,
            )
        result.append({"gameVersion": str(game_version), "server": str(server)})
    return result


def _release_wire(value: Mapping[str, Any]) -> Dict[str, Any]:
    """Build the exact create/update release request shape from CLI fields."""
    result: Dict[str, Any] = {}
    aliases = {
        "project_id": "projectId", "file_id": "fileId", "zip_size": "zipSize",
        "unzip_size": "unzipSize", "toc_version": "tocVersion",
    }
    for key, wire_name in aliases.items():
        if key in value and value[key] is not None:
            result[wire_name] = _positive_id(value[key], field=key) if key in ("project_id", "file_id") else value[key]
    for key in ("md5", "type", "version", "path", "changelog"):
        if key in value and value[key] is not None:
            result[key] = value[key]
    if "supported_game_versions" in value:
        result["supportedGameVersionsReqs"] = _supported_game_versions(value["supported_game_versions"])
    elif "supportedGameVersionsReqs" in value:
        result["supportedGameVersionsReqs"] = _supported_game_versions(value["supportedGameVersionsReqs"])
    return result


def _dependency_query_wire(value: Any) -> Dict[str, Any]:
    """Build one of Creator's two dependency-query request objects.

    The desktop client exposes overloads for a name search and for resolving
    project IDs. Both delegate to the same object-payload POST overload.
    """
    if isinstance(value, str):
        text = value.strip()
        if not text:
            raise ValidationError("dependency query must not be empty", path="$.query")
        if text.startswith(("{", "[")):
            try:
                value = json.loads(text)
            except ValueError as exc:
                raise ValidationError("dependency query JSON is invalid", path="$.query") from exc
        else:
            return {"name": text}
    if isinstance(value, bool) or value is None:
        raise ValidationError("dependency query requires a name or project IDs", path="$.query")
    if isinstance(value, int):
        project_id = _positive_id(value, field="$.project_id")
        if project_id > 2147483647:
            raise ValidationError("project ID exceeds Int32 range", path="$.project_id")
        return {"projectIds": [project_id]}
    if isinstance(value, (list, tuple)):
        values = value
        path = "$.project_ids"
    elif isinstance(value, Mapping):
        unknown = sorted(set(value) - {"name", "projectIds", "project_ids"})
        if unknown:
            raise ValidationError("unknown dependency query field", path="$.query.%s" % unknown[0])
        modes = [key for key in ("name", "projectIds", "project_ids") if key in value]
        if len(modes) != 1:
            raise ValidationError("dependency query requires exactly one mode", path="$.query")
        if modes[0] == "name":
            name = value["name"]
            if not isinstance(name, str) or not name.strip():
                raise ValidationError("dependency name must be a nonempty string", path="$.query.name")
            return {"name": name.strip()}
        values = value[modes[0]]
        path = "$.query.%s" % modes[0]
    else:
        raise ValidationError("dependency query requires a name or project IDs", path="$.query")
    if not isinstance(values, (list, tuple)) or not values:
        raise ValidationError("project IDs must be a nonempty array", path=path)
    project_ids = []
    for index, item in enumerate(values):
        item_path = "%s[%d]" % (path, index)
        project_id = _positive_id(item, field=item_path)
        if project_id > 2147483647:
            raise ValidationError("project ID exceeds Int32 range", path=item_path)
        project_ids.append(project_id)
    return {"projectIds": project_ids}


def _wire(value: Mapping[str, Any]) -> Dict[str, Any]:
    result = {_WIRE_NAMES.get(str(key), str(key)): item for key, item in value.items()
            if key not in ("schema", "file")}
    if "screenshot_base64s" in value:
        result["images"] = int(value.get("images") or 0)
        result["screenshotBase64sReqs"] = {"name": "logo.webp", "screenshotBase64s": value["screenshot_base64s"]}
    return result


def _project_wire(value: Mapping[str, Any], *, create: bool = False) -> Dict[str, Any]:
    """Project project create/update fields to Creator's request shape."""
    result: Dict[str, Any] = {}
    for key in ("name", "alt_name", "summary", "repo_url"):
        if key in value and value[key] is not None:
            wire_name = _WIRE_NAMES.get(key, key)
            if create:
                if key == "repo_url" and not str(value[key]).strip():
                    continue
                result[wire_name] = value[key]
            else:
                result[wire_name] = value[key] if key == "name" else _null_marker(value[key])
    if "project_id" in value and value["project_id"] is not None:
        result["projectId"] = int(value["project_id"])
    if create or "categories" in value:
        category_ids = _category_ids(value.get("categories"))
        result["categories"] = ",".join(str(item) for item in category_ids)
    if create or "synchronization_type" in value:
        result["synchronizationType"] = _sync_type(value.get("synchronization_type"))
    if create or "license" in value:
        result["license"] = _license_json(value.get("license"), value)
    if create:
        logo_base64 = value.get("logo_base64")
        if logo_base64 is None:
            screenshots = value.get("screenshot_base64s") or []
            logo_base64 = screenshots[0] if isinstance(screenshots, (list, tuple)) and screenshots else ""
        result["images"] = 0
        result["screenshotBase64sReqs"] = {"name": "logo.webp", "screenshotBase64s": logo_base64 or ""}
    elif "image_ops" in value:
        if "images" not in value:
            raise ValidationError("images is required when image_ops is supplied", path="images")
        result["images"] = int(value["images"])
        result["imagesOps"] = _image_ops(value["image_ops"])
    if "required_tier_id" in value:
        if value["required_tier_id"] is not None:
            result["requiredTierId"] = int(value["required_tier_id"]) if create else str(int(value["required_tier_id"]))
        elif not create:
            result["requiredTierId"] = "<null>"
    if not create and "description" in value:
        result["description"] = _null_marker(value["description"])
    if not create and "required_dependencies" in value:
        result["requiredDependencies"] = _null_marker(value["required_dependencies"])
    return result


def _project_document(value: Mapping[str, Any]) -> Dict[str, Any]:
    """Resolve a persisted Creator form snapshot before building request JSON."""
    document = dict(value)
    snapshot = document.get("project_state")
    if snapshot is None:
        raise ValidationError(
            "completed project_state is required; submit choose_game, basic_info, then license",
            path="$.project_state",
        )
    machine = ProjectStateMachine.from_snapshot(snapshot)
    if machine.state != COMPLETE:
        raise ValidationError("project state must be complete before submission", path="$.project_state.state")
    merged = dict(machine.basic_info)
    merged.update({key: item for key, item in document.items() if key not in {"project_state", "basic_info", "license"}})
    merged["license"] = machine.license
    return merged


def _business_code(payload: Mapping[str, Any]) -> Optional[int]:
    code = payload.get("code")
    if isinstance(code, bool) or code is None:
        return None
    try:
        return int(str(code).strip())
    except (TypeError, ValueError):
        return None


def _safe(value: Any) -> Any:
    """Recursively redact credentials and presigned URLs in API results."""
    if isinstance(value, Mapping):
        result = {}
        for key, item in value.items():
            normalized = str(key).replace("-", "_").lower()
            result[str(key)] = "[REDACTED]" if normalized in _SECRET_KEYS else _safe(item)
        return result
    if isinstance(value, list):
        return [_safe(item) for item in value]
    if isinstance(value, str):
        return redact(value)
    return value


def _dpapi_unprotect(cipher: bytes) -> bytes:
    if os.name != "nt":
        raise FuploadError("ModUs Creator token reuse requires Windows DPAPI", kind="authentication_error")
    class DATA_BLOB(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte))]

    def blob(data: bytes):
        buf = ctypes.create_string_buffer(data)
        return DATA_BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_byte))), buf

    inp, inp_buf = blob(cipher)
    ent, ent_buf = blob(TOKEN_ENTROPY)
    out = DATA_BLOB()
    crypt = ctypes.windll.crypt32.CryptUnprotectData
    crypt.argtypes = [ctypes.POINTER(DATA_BLOB), ctypes.c_void_p, ctypes.POINTER(DATA_BLOB), ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(DATA_BLOB)]
    crypt.restype = wintypes.BOOL
    if not crypt(ctypes.byref(inp), None, ctypes.byref(ent), None, None, 0, ctypes.byref(out)):
        raise FuploadError("ModUs Creator token decryption failed for the current Windows user", kind="authentication_error")
    try:
        return ctypes.string_at(out.pbData, out.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(out.pbData)


def load_token(path: Optional[Path] = None) -> str:
    """Read and decrypt the local Creator token without printing it."""
    selected = path or TOKEN_PATH
    if not selected.is_file():
        legacy = selected.with_name("token.json")
        if legacy.is_file():
            selected = legacy
        else:
            raise FuploadError("ModUs Creator login token was not found", kind="authentication_error", details={"path": str(selected)})
    try:
        raw = selected.read_bytes()
        plain = _dpapi_unprotect(raw) if selected.name.endswith(".dat") else raw
        if selected.name == "token.json":
            parsed = json.loads(plain.decode("utf-8"))
            plain = str(parsed.get("token") or parsed.get("accessToken") or "").encode()
        token = plain.decode("utf-8").strip()
    except FuploadError:
        raise
    except Exception as exc:
        raise FuploadError("ModUs Creator login token could not be read", kind="authentication_error") from exc
    if not token:
        raise FuploadError("ModUs Creator login token is empty", kind="authentication_error")
    return token


def _unwrap(payload: Any) -> Any:
    if isinstance(payload, Mapping) and "data" in payload:
        return payload["data"]
    return payload


class ModUs:
    """Authenticated ModUs Creator API client for WoW plugin publishing."""

    def __init__(
        self,
        token: Optional[str] = None,
        *,
        base_url: str = API_BASE,
        timeout: int = 60,
        token_path: Optional[Path] = None,
        authenticate: bool = True,
    ) -> None:
        self.base_url = base_url.rstrip("/") + "/"
        self.timeout = timeout
        self.token_path = token_path or TOKEN_PATH
        self.token = token if token is not None else (load_token(self.token_path) if authenticate else "")

    def _url(self, path: str) -> str:
        return urllib.parse.urljoin(self.base_url, path.lstrip("/"))

    @staticmethod
    def _request_stage(method: str, path: str) -> str:
        if "file/upload/signature" in path:
            return "signature"
        if path.endswith("/fileId/") or "/fileId/" in path:
            return "file_id"
        if "/project/file/upload" in path or path.endswith("/project/upload"):
            return "release_metadata"
        if "/project/file/update" in path:
            return "release_metadata_update"
        if "/project/delete" in path:
            return "delete"
        if path.endswith("/project/release"):
            return "project_create"
        if path.endswith("/project/update"):
            return "project_update"
        return "request"

    def _request(self, method: str, path: str, body: Any = None, *, headers: Optional[Mapping[str, str]] = None) -> Any:
        url = self._url(path)
        stage = self._request_stage(method, path)
        request_headers = {"Accept": "application/json", "Authorization": "Bearer " + self.token}
        if headers:
            request_headers.update(headers)
        data = None
        if body is not None:
            data = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            request_headers["Content-Type"] = "application/json"
        request = urllib.request.Request(url, data=data, method=method, headers=request_headers)
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                raw, status = response.read(), response.status
        except urllib.error.HTTPError as exc:
            raw = exc.read()
            try:
                detail = json.loads(raw.decode("utf-8"))
            except Exception:
                detail = "HTTP %d" % exc.code
            raise FuploadError(redact(str(detail)), endpoint=url, http_status=exc.code, kind="platform_error", stage=stage) from exc
        except (OSError, urllib.error.URLError) as exc:
            raise FuploadError("ModUs request failed: %s" % exc, endpoint=url, verification_required=method != "GET", stage=stage) from exc
        if status < 200 or status >= 300:
            raise FuploadError("ModUs returned HTTP %d" % status, endpoint=url, http_status=status, stage=stage)
        if not raw:
            return {}
        try:
            payload = json.loads(raw.decode("utf-8"))
        except ValueError as exc:
            raise FuploadError("ModUs response was not valid JSON", endpoint=url, http_status=status, stage=stage) from exc
        if isinstance(payload, Mapping) and payload.get("success") is False:
            raise FuploadError(str(payload.get("message") or "ModUs API rejected the request"), endpoint=url, business_code=payload.get("code"), kind="platform_error", stage=stage)
        if isinstance(payload, Mapping):
            business_code = _business_code(payload)
            if business_code is not None and business_code >= 400:
                raise FuploadError(
                    str(payload.get("msg") or payload.get("message") or "ModUs API rejected the request"),
                    endpoint=url, business_code=business_code, kind="platform_error", stage=stage,
                )
        return payload

    def doctor(self) -> Dict[str, Any]:
        selected = self.token_path
        if not selected.is_file() and selected.with_name("token.json").is_file():
            selected = selected.with_name("token.json")
        present = selected.is_file()
        result = {
            "token_present": present,
            "token_decrypted": False,
            "token_nonempty": False,
            "api_ready": False,
        }
        if not present:
            return result
        try:
            raw = selected.read_bytes()
            plain = _dpapi_unprotect(raw) if selected.name.endswith(".dat") else raw
            result["token_decrypted"] = True
            if selected.name == "token.json":
                parsed = json.loads(plain.decode("utf-8"))
                plain = str(parsed.get("token") or parsed.get("accessToken") or "").encode()
            token = plain.decode("utf-8").strip()
        except (FuploadError, OSError, UnicodeError, ValueError, TypeError):
            return result
        result["token_nonempty"] = bool(token)
        if not token:
            return result
        previous_token = self.token
        self.token = token
        try:
            self.user_info()
            result["api_ready"] = True
        except FuploadError:
            pass
        finally:
            self.token = previous_token
        return result

    def project_list(self, *, page_num: int = 1, page_size: int = 50, **extra: Any) -> Any:
        body = {"pageNum": page_num, "pageSize": page_size, **extra}
        return _safe(_unwrap(self._request("POST", "game/data/author/project/list", body)))

    def project_detail(self, project_id: int) -> Any:
        return _safe(_unwrap(self._request("GET", "game/data/author/project/detail/%s" % _positive_id(project_id, field="project_id"))))

    def project_create(self, doc: Mapping[str, Any]) -> Any:
        document = _project_document(doc)
        return _safe(_unwrap(self._request("POST", "game/data/author/project/release", _project_wire(document, create=True))))

    def project_update(self, doc: Mapping[str, Any]) -> Any:
        document = _project_document(doc)
        return _safe(_unwrap(self._request("POST", "game/data/author/project/update", _project_wire(document, create=False))))

    def project_delete(self, project_id: int) -> Any:
        return _safe(_unwrap(self._request("POST", "game/data/author/project/delete/project/%s" % _positive_id(project_id, field="project_id"))))

    def release_file_id(self, project_id: int) -> Any:
        project_id = _positive_id(project_id, field="project_id")
        value = _unwrap(self._request("GET", "game/data/author/project/fileId/%s" % project_id))
        if isinstance(value, Mapping):
            value = value.get("fileId") or value.get("id") or value.get("data")
        if not value:
            raise FuploadError("ModUs did not return a release file ID", kind="platform_data_error")
        return _positive_id(value, field="file_id")

    def release_list(self, project_id: int, *, page_num: int = 1, page_size: int = 50) -> Any:
        return _safe(_unwrap(self._request("POST", "game/data/author/project/file/list", {"projectId": _positive_id(project_id, field="project_id"), "pageNum": page_num, "pageSize": page_size})))

    def release_detail(self, project_id: int, file_id: int) -> Any:
        # Creator's GetReleaseFileDetailAsync accepts only the reserved file ID.
        return _safe(_unwrap(self._request("GET", "game/data/author/project/file/detail/%s" % _positive_id(file_id, field="file_id"))))

    def release_metadata(self, doc: Mapping[str, Any], *, update: bool = False) -> Any:
        route = "game/data/author/project/file/update" if update else "game/data/author/project/upload"
        wire = _release_wire(doc)
        if not update:
            # UploadReleaseAsync's create payload has no fileId. The ID is
            # reserved by GetReleaseFileIdAsync and is consumed by signing.
            wire.pop("fileId", None)
        return _safe(_unwrap(self._request("POST", route, wire)))

    def user_info(self) -> Any:
        return _safe(_unwrap(self._request("GET", "system/user/getInfo")))

    def active_subscription_count(self) -> Any:
        return _safe(_unwrap(self._request("GET", "user/author/subscription/active/count")))

    def project_statistics(self) -> Any:
        return _safe(_unwrap(self._request("GET", "game/data/author/project/statistics")))

    def addon_info(self, directories: Any, *, server_type: int = 1) -> Any:
        values = directories if isinstance(directories, (list, tuple)) else [directories]
        body = {"pluginList": [str(value) for value in values]}
        return _safe(_unwrap(self._request("POST", "plugin/list/info", body, headers={"X-Server-Type": str(int(server_type))})))

    def addon_project_info(self, project_ids: Any, *, server_type: int = 1) -> Any:
        values = project_ids if isinstance(project_ids, (list, tuple)) else [project_ids]
        body = {"projectIds": [int(value) for value in values]}
        return _safe(_unwrap(self._request("POST", "plugin/list/detail", body, headers={"X-Server-Type": str(int(server_type))})))

    def addon_history(self, project_id: int, *, page_num: int = 1, page_size: int = 5, server_type: int = 1) -> Any:
        body = {"projectIds": [int(project_id)], "pageNum": int(page_num), "pageSize": int(page_size)}
        return _safe(_unwrap(self._request("POST", "plugin/project/history", body, headers={"X-Server-Type": str(int(server_type))})))

    def project_dependencies(self, query: Any) -> Any:
        body = _dependency_query_wire(query)
        return _safe(_unwrap(self._request("POST", "game/data/author/project/dependency/query", body)))

    def options(self, action: str, *, keys: Optional[Any] = None) -> Any:
        routes = {
            # These paths are the routes used by ModUs.Creator's ApiService.
            "categories": "plugin/list/Categories",
            "subscription-tiers": "user/author/subscription/tiers",
        }
        if action == "game-versions":
            # Creator posts the requested config keys.  An empty list asks for
            # no valid request on the live service, so require an explicit key.
            requested = keys if isinstance(keys, list) else ([] if keys is None else [keys])
            requested = [str(item).strip() for item in requested if str(item).strip()]
            if not requested:
                raise ValidationError("at least one game config key is required", path="$.keys")
            return _safe(_unwrap(self._request("POST", "game/data/config/detail", {"keys": requested})))
        if action not in routes:
            raise ValidationError("unsupported ModUs options operation")
        return _safe(_unwrap(self._request("GET", routes[action])))

    def release_signature(self, project_id: int, file_id: int) -> str:
        result = _unwrap(self._request("GET", "game/data/author/project/file/upload/signature/%s/%s" % (_positive_id(project_id, field="project_id"), _positive_id(file_id, field="file_id"))))
        url = result.get("signedUrl") if isinstance(result, Mapping) else result
        if not isinstance(url, str) or not url.startswith(("https://", "http://")):
            raise FuploadError("ModUs did not return a valid release upload URL", kind="platform_data_error")
        return url

    def upload_zip(self, signed_url: str, file_path: str) -> Dict[str, Any]:
        path = Path(file_path)
        if not path.is_file():
            raise ValidationError("release ZIP file does not exist", path=file_path)
        size = path.stat().st_size
        if size > MAX_PACKAGE_BYTES:
            raise ValidationError("release ZIP exceeds the 200 MB upload limit", path=file_path)
        parsed = urllib.parse.urlsplit(signed_url)
        conn_cls = http.client.HTTPSConnection if parsed.scheme == "https" else http.client.HTTPConnection
        if parsed.scheme == "https":
            conn = conn_cls(parsed.hostname, parsed.port, timeout=max(self.timeout, 600), context=ssl.create_default_context())
        else:
            conn = conn_cls(parsed.hostname, parsed.port, timeout=max(self.timeout, 600))
        try:
            conn.putrequest("PUT", urllib.parse.urlunsplit(("", "", parsed.path or "/", parsed.query, "")))
            conn.putheader("Content-Type", "application/zip")
            conn.putheader("Content-Length", str(size))
            conn.endheaders()
            with path.open("rb") as handle:
                while True:
                    chunk = handle.read(1024 * 1024)
                    if not chunk:
                        break
                    conn.send(chunk)
            response = conn.getresponse()
            response.read()
            if response.status < 200 or response.status >= 300:
                raise FuploadError("ModUs binary upload returned HTTP %d" % response.status, http_status=response.status, verification_required=True, stage="binary_upload")
        except FuploadError:
            raise
        except OSError as exc:
            raise FuploadError("ModUs binary upload failed: %s" % exc, verification_required=True, stage="binary_upload") from exc
        finally:
            conn.close()
        return {"status": "uploaded", "archive": path.name, "bytes": size}

    def release_delete(self, project_id: int, file_id: int) -> Any:
        return _safe(_unwrap(self._request("POST", "game/data/author/project/delete", {"projectId": _positive_id(project_id, field="project_id"), "fileId": _positive_id(file_id, field="file_id")})))

    def publish(self, doc: Mapping[str, Any], *, update: bool = False) -> Dict[str, Any]:
        project_id = _positive_id(doc["project_id"], field="project_id")
        allocated_file_id = not bool(doc.get("file_id"))
        file_id = _positive_id(doc.get("file_id") or self.release_file_id(project_id), field="file_id")
        metadata = {k: doc[k] for k in ("project_id", "version", "type", "supported_game_versions", "toc_version", "changelog", "path") if k in doc}
        metadata["file_id"] = file_id
        file_path = doc.get("file")
        if file_path is None and not update:
            raise ValidationError("release ZIP file is required", path="file")
        archive = Path(str(file_path)) if file_path is not None else None
        if archive is not None:
            if not archive.is_file():
                raise ValidationError("release ZIP file does not exist", path=str(file_path))
            size = archive.stat().st_size
            if size > MAX_PACKAGE_BYTES:
                raise ValidationError("release ZIP exceeds the 200 MB upload limit", path=str(file_path))
            md5 = hashlib.md5(archive.read_bytes()).hexdigest()
            try:
                unzip_size = sum(info.file_size for info in zipfile.ZipFile(str(archive)).infolist())
            except (OSError, zipfile.BadZipFile) as exc:
                raise ValidationError("release file is not a valid ZIP", path=str(file_path)) from exc
            derived = parse_modus_zip(archive)
            supplied_toc = doc.get("toc_version")
            supplied_games = doc.get("supported_game_versions")
            if supplied_toc is not None and str(supplied_toc) != derived["toc_version"]:
                raise ValidationError("toc_version does not match the ZIP Interface field", path="$.toc_version")
            if supplied_games is not None and _supported_game_versions(supplied_games) != derived["supported_game_versions"]:
                raise ValidationError("supported_game_versions does not match the ZIP Interface field", path="$.supported_game_versions")
            metadata.update({
                "md5": md5,
                "zip_size": size,
                "unzip_size": unzip_size,
                "toc_version": derived["toc_version"],
                "supported_game_versions": derived["supported_game_versions"],
                "path": doc.get("path") or archive.name,
            })
        transaction: Dict[str, Any] = {
            "schema": "fupload.v1.modus.upload-transaction",
            "created_at": int(time.time()),
            "project_id": project_id,
            "file_id": file_id,
            "update": bool(update),
            "archive": str(archive) if archive is not None else None,
            "stages": ["file_id"] if allocated_file_id else [],
        }
        transaction_path = Path(str(doc.get("transaction_log") or ((str(archive) + ".modus-transaction.json") if archive else "modus-transaction.json")))

        def save_transaction() -> None:
            transaction_path.write_text(json.dumps(transaction, ensure_ascii=False, indent=2), encoding="utf-8")

        try:
            transaction["stages"].append("release_metadata_update" if update else "release_metadata")
            result = self.release_metadata(metadata, update=update)
            if archive is None:
                transaction.update({"completed": True, "upload": None})
                save_transaction()
                return {"project_id": project_id, "file_id": file_id, "metadata": result, "upload": None, "transaction": _safe(transaction)}
            transaction["stages"].append("signature")
            signed = self.release_signature(project_id, file_id)
            transaction["stages"].append("binary_upload")
            uploaded = self.upload_zip(signed, str(archive))
            transaction.update({"completed": True, "upload": uploaded})
            save_transaction()
            return {"project_id": project_id, "file_id": file_id, "metadata": result, "upload": uploaded, "transaction": _safe(transaction)}
        except FuploadError as exc:
            transaction["failed_stage"] = exc.stage or transaction["stages"][-1] if transaction["stages"] else "prepare"
            transaction["error"] = exc.as_dict()
            transaction["retained_archive"] = bool(archive and archive.is_file())
            try:
                save_transaction()
            except OSError:
                pass
            raise

    def execute_read(self, resource: str, action: str, args: Any = None) -> Any:
        if resource == "session" and action == "doctor": return self.doctor()
        doc = vars(args) if args is not None and hasattr(args, "__dict__") else (args or {})
        if resource == "account" and action == "info": return self.user_info()
        if resource == "account" and action == "subscription-count": return self.active_subscription_count()
        if resource == "account" and action == "statistics": return self.project_statistics()
        if resource == "addon" and action == "info": return self.addon_info(doc.get("directories", []), server_type=doc.get("server_type", 1))
        if resource == "addon" and action == "project-info": return self.addon_project_info(doc.get("project_ids", []), server_type=doc.get("server_type", 1))
        if resource == "addon" and action == "history": return self.addon_history(doc["project_id"], page_num=doc.get("page_num", 1), page_size=doc.get("page_size", 5), server_type=doc.get("server_type", 1))
        if resource == "project" and action == "dependencies": return self.project_dependencies(doc.get("query") or doc.get("project_ids") or doc.get("project_id"))
        if resource == "options": return self.options(action, keys=doc.get("keys"))
        if resource == "project" and action == "list": return self.project_list(**doc)
        if resource == "project" and action in ("get", "detail"): return self.project_detail(doc["project_id"])
        if resource in ("plugin", "release") and action in ("list", "versions"): return self.release_list(doc["project_id"], page_num=doc.get("page_num", 1), page_size=doc.get("page_size", 50))
        if resource in ("plugin", "release") and action == "get": return self.release_detail(doc["project_id"], doc["file_id"])
        raise ValidationError("unsupported ModUs read operation")

    def execute_write(self, resource: str, action: str, doc: Mapping[str, Any]) -> Any:
        if resource == "project" and action in ("create", "release"): return self.project_create(doc)
        if resource == "project" and action in ("update", "edit"): return self.project_update(doc)
        if resource == "project" and action == "delete": return self.project_delete(int(doc["project_id"]))
        if resource in ("plugin", "release") and action in ("upload", "create"): return self.publish(doc)
        if resource in ("plugin", "release") and action in ("update", "edit"): return self.publish(doc, update=True)
        if resource in ("plugin", "release") and action == "delete": return self.release_delete(doc["project_id"], doc["file_id"])
        raise ValidationError("unsupported ModUs write operation")


Modus = ModUs
