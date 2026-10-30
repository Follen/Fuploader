"""ModUs Creator plugin/project provider.

The Creator desktop client stores its bearer token in a DPAPI CurrentUser
file.  This module deliberately keeps the token and presigned URL out of
returned documents and exception messages.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import base64
import hashlib
from html.parser import HTMLParser
import http.client
import json
import os
import re
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
from .modus_zip import parse_modus_zip, select_game_versions
from .transport import json_request, multipart_request


def _main_plaintext(content: str) -> str:
    """Mirror the official Q2 DOM textContent projection, without changing HTML."""
    if not isinstance(content, str):
        raise FuploadError("Current main-client content is malformed", kind="platform_data_error")
    if "<" not in content:
        try:
            content = base64.b64decode(content, validate=True).decode("utf-8")
        except (ValueError, UnicodeError):
            pass
    content = re.sub(r'\[\[wa:data="[^"]*"\]\]', "", content, flags=re.I)
    content = re.sub(r'\[\[?img:key=(?:"[^"]+"|[^\]]+)\]\]?', "", content)
    class Text(HTMLParser):
        def __init__(self):
            super().__init__(convert_charrefs=True)
            self.parts, self.hidden = [], []
        def handle_starttag(self, tag, attrs):
            if tag in {"script", "style", "iframe", "object"}:
                self.hidden.append(tag)
        def handle_endtag(self, tag):
            if tag in self.hidden:
                self.hidden = self.hidden[:self.hidden.index(tag)]
        def handle_data(self, data):
            if not self.hidden:
                self.parts.append(data)
    parser = Text()
    parser.feed(content)
    parser.close()
    return "".join(parser.parts).replace("\u00a0", " ")


API_BASE = "https://app.modus.cool/api/"
STATIC_API_BASE = "https://cdn.modus.cool/modus/client_static_api/"
RESOURCE_BASE = "https://cdn.modus.cool/"
TOKEN_PATH = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local")) / "ModUs.Creator" / "auth" / "token.dat"
TOKEN_ENTROPY = b"ModUs.Creator.TokenStore.v1"
MODUS_APPDATA = Path(os.environ.get("APPDATA", Path.home() / "AppData/Roaming")) / "modus"
MAX_PACKAGE_BYTES = 200 * 1024 * 1024
MODUS_BUILDS = (
    {"id": 0, "code": "retail", "name": "至暗之夜", "label": "正式服-至暗之夜"},
    {"id": 1, "code": "classic_era", "name": "经典旧世", "label": "怀旧服-经典旧世"},
    {"id": 2, "code": "classic", "name": "熊猫人之谜", "label": "怀旧服-熊猫人之谜"},
    {"id": 3, "code": "classic_titan", "name": "泰坦重铸", "label": "时光服-泰坦重铸"},
    {"id": 4, "code": "anniversary", "name": "燃烧的远征", "label": "周年服-燃烧的远征"},
)
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


def _tag_filter(value: Any) -> list[str]:
    values = value if isinstance(value, (list, tuple, set)) else str(value).split(",")
    result = [str(item).strip() for item in values if str(item).strip()]
    if not result:
        raise ValidationError("tag filter must contain at least one ID", path="tags")
    return result


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
        op = item.get("op")
        if op not in ("upload", "delete", "rename"):
            raise ValidationError("image operation must be upload, delete, or rename", path=path + ".op")
        allowed = {"op", "from", "to"} if op == "rename" else {"op", "name", "base64"}
        unknown = sorted(set(item) - allowed)
        if unknown:
            raise ValidationError("unknown image operation field(s): %s" % ", ".join(unknown), path=path + "." + unknown[0])
        if op == "rename":
            source, target = item.get("from"), item.get("to")
            if not isinstance(source, str) or not source.strip():
                raise ValidationError("rename image operation requires from", path=path + ".from")
            if not isinstance(target, str) or not target.strip():
                raise ValidationError("rename image operation requires to", path=path + ".to")
            result.append({"op": op, "from": source.strip(), "to": target.strip()})
            continue
        name = item.get("name")
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


def _resource_id(value: Any, *, field: str) -> str:
    """ModUs share/import IDs are opaque positive decimal strings."""
    if isinstance(value, bool) or value is None:
        raise ValidationError("%s must be a non-empty identifier" % field, path=field)
    text = str(value).strip()
    if not text or (text.isdigit() and int(text) <= 0):
        raise ValidationError("%s must be a non-empty identifier" % field, path=field)
    return text


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
        if key in value and (value[key] is not None or key == "changelog"):
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
        if key in value and (value[key] is not None or not create):
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
    canonical = machine.snapshot()
    if "license" in document:
        supplied = ProjectStateMachine.from_snapshot({**canonical, "license": document["license"]})
        if supplied.license != machine.license:
            raise ValidationError("license conflicts with project_state.license", path="$.license")
    if "publish_platforms" in document:
        platforms = document["publish_platforms"]
        if (not isinstance(platforms, (list, tuple)) or
                not all(isinstance(item, str) for item in platforms) or
                sorted(platforms) != sorted(machine.basic_info["publish_platforms"])):
            raise ValidationError("publish_platforms conflicts with project_state.basic_info.publish_platforms", path="$.publish_platforms")

    # The completed snapshot owns license/platform selection. Other explicit
    # metadata retains its override semantics, but the effective form must pass
    # the same completed-state validation as the original snapshot.
    effective_basic = machine.basic_info
    effective_basic.update({key: item for key, item in document.items()
                            if key not in {"project_state", "basic_info", "license", "publish_platforms", "project_id"}})
    effective = ProjectStateMachine.from_snapshot({**canonical, "basic_info": effective_basic})
    merged = effective.basic_info
    if "project_id" in document:
        merged["project_id"] = document["project_id"]
    merged["license"] = effective.license
    return merged


def _full_project_id(value: Any) -> int:
    project_id = _positive_id(value, field="project_id")
    if project_id < 200000000:
        raise ValidationError("restricted Creator projects do not allow project deletion or release mutations", path="$.project_id")
    return project_id


def _business_code(payload: Mapping[str, Any]) -> Optional[int]:
    code = payload.get("code")
    if isinstance(code, bool) or code is None:
        return None
    try:
        return int(str(code).strip())
    except (TypeError, ValueError):
        return None


def _image_upload_record(payload: Any) -> Dict[str, str]:
    """Extract the reusable key and display URL used by the main client."""
    data = _unwrap(payload)
    if not isinstance(data, Mapping):
        raise FuploadError(
            "ModUs image upload returned no media record",
            kind="platform_data_error",
            stage="media_upload",
        )

    download_url = data.get("downloadUrl") or data.get("url") or data.get("fileUrl")
    reference = data.get("cosStoreKey") or data.get("cosStoreUrl") or data.get("key")
    if not reference and isinstance(download_url, str) and download_url.strip():
        parsed = urllib.parse.urlsplit(download_url.strip())
        reference = urllib.parse.unquote(parsed.path.lstrip("/"))
    if not isinstance(reference, str) or not reference.strip():
        raise FuploadError(
            "ModUs image upload omitted its object key",
            kind="platform_data_error",
            stage="media_upload",
        )

    reference = reference.strip()
    if isinstance(download_url, str) and download_url.strip():
        display_url = download_url.strip()
    elif reference.startswith(("https://", "http://")):
        display_url = reference
    else:
        display_url = urllib.parse.urljoin(RESOURCE_BASE, reference.lstrip("/"))
    return {"key": reference, "url": display_url, "reference": reference}


def _safe(value: Any) -> Any:
    """Recursively redact credentials and presigned URLs in API results."""
    if isinstance(value, Mapping):
        result = {}
        for key, item in value.items():
            normalized = str(key).replace("-", "_").lower()
            if normalized in _SECRET_KEYS:
                result[str(key)] = "[REDACTED]"
            elif normalized in {
                "content", "contenttext", "codetext", "changelog",
                "description", "licensecontent",
            }:
                # write_output() hashes these fields before serializing JSON.
                # Preserve the original here so the digest represents the
                # service value instead of a generic redaction placeholder.
                result[str(key)] = item
            else:
                result[str(key)] = _safe(item)
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


def load_main_session(root: Optional[Path] = None) -> Dict[str, str]:
    """Read the current official renderer's user/app keys, respecting tombstones."""
    from .chromium_leveldb import read_local_storage
    base = root or MODUS_APPDATA
    leveldb = base / "Local Storage" / "leveldb"
    if not leveldb.is_dir():
        raise FuploadError("ModUs main-client local storage was not found", kind="authentication_error")
    try:
        # The official main process assigns this fixed virtual renderer origin;
        # API origins, unrelated websites, and development profiles are excluded.
        storage = read_local_storage(leveldb, "http://tongji.modus.cool", ("user", "app"))
        user = json.loads(storage.get("user", "{}"))
        app = json.loads(storage.get("app", "{}"))
        if not isinstance(user, dict) or not isinstance(app, dict):
            raise ValueError()
        token = user.get("token")
        device = app.get("deviceId")
    except (OSError, UnicodeError, ValueError, TypeError) as exc:
        raise FuploadError("ModUs current main-client session could not be read", kind="authentication_error") from exc
    token = token.strip() if isinstance(token, str) else ""
    device = device.strip() if isinstance(device, str) else ""
    if not token:
        raise FuploadError("ModUs main-client login token was not found", kind="authentication_error")
    return {"token": token, **({"device_id": device} if device else {})}


def load_current_build(root: Optional[Path] = None) -> Optional[int]:
    """Read the live wow storage key; obsolete tables and deleted keys are ignored."""
    from .chromium_leveldb import read_local_storage
    base = root or MODUS_APPDATA
    leveldb = base / "Local Storage" / "leveldb"
    if not leveldb.is_dir():
        return None
    try:
        storage = read_local_storage(leveldb, "http://tongji.modus.cool", ("wow",))
        wow = json.loads(storage.get("wow", "{}"))
        selected = wow.get("currentGameWow") if isinstance(wow, dict) else None
        value = selected.get("id") if isinstance(selected, dict) else None
        if type(value) is int and 0 <= value <= 4:
            return value
    except (OSError, UnicodeError, ValueError, TypeError):
        pass
    return None


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
        device_id: Optional[str] = None,
        main_session: bool = False,
        authenticate: bool = True,
    ) -> None:
        self.base_url = base_url.rstrip("/") + "/"
        self.timeout = timeout
        self.token_path = token_path or TOKEN_PATH
        self.device_id = device_id
        self.main_session = main_session
        self.current_build = load_current_build() if main_session else None
        self.authorization_scheme = "" if main_session else "Bearer "
        if token is not None:
            self.token = token
        elif authenticate:
            if main_session:
                session = load_main_session()
                self.token, self.device_id = session["token"], session.get("device_id")
                self.authorization_scheme = ""
            else:
                self.token = load_token(self.token_path)
        else:
            self.token = ""

    def _url(self, path: str) -> str:
        return urllib.parse.urljoin(self.base_url, path.lstrip("/"))

    def _authorization_value(self) -> str:
        # Creator's SetAuthHeader preserves an existing Bearer prefix and adds
        # it otherwise. The Electron main client sends its stored token as-is.
        if self.authorization_scheme and not self.token.casefold().startswith(self.authorization_scheme.casefold()):
            return self.authorization_scheme + self.token
        return self.token

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
        authorization = self._authorization_value()
        request_headers = {"Accept": "application/json", "Authorization": authorization}
        if self.device_id:
            request_headers["X-Device-Id"] = self.device_id
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
            raise FuploadError(redact(str(detail)), endpoint=url, http_status=exc.code, kind="platform_error", stage=stage,
                               verification_required=method != "GET" and exc.code >= 500) from exc
        except (OSError, urllib.error.URLError, http.client.IncompleteRead) as exc:
            raise FuploadError("ModUs request failed: %s" % exc, endpoint=url, verification_required=method != "GET", stage=stage) from exc
        if status < 200 or status >= 300:
            raise FuploadError("ModUs returned HTTP %d" % status, endpoint=url, http_status=status, stage=stage,
                               verification_required=method != "GET" and status >= 500)
        if not raw:
            return {}
        try:
            payload = json.loads(raw.decode("utf-8"))
        except ValueError as exc:
            raise FuploadError("ModUs response was not valid JSON", endpoint=url, http_status=status, stage=stage,
                               verification_required=method != "GET") from exc
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
        if self.main_session:
            result = {
                "token_present": False,
                "token_decrypted": False,
                "token_nonempty": False,
                "api_ready": False,
            }
            try:
                session = load_main_session()
                token = str(session.get("token") or "").strip()
                result["token_present"] = bool(token)
                result["token_decrypted"] = bool(token)
                result["token_nonempty"] = bool(token)
                if not token:
                    return result
                previous_token, previous_device = self.token, self.device_id
                self.token = token
                self.device_id = session.get("device_id")
                try:
                    self.user_info()
                    result["api_ready"] = True
                finally:
                    self.token, self.device_id = previous_token, previous_device
            except (FuploadError, OSError, UnicodeError, ValueError, TypeError):
                pass
            return result
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
        body = {"pageNum": page_num, "pageSize": page_size}
        for key in ("keyword", "orderByColumn", "isAsc"):
            if key in extra and extra[key] is not None:
                body[key] = extra[key]
        return _safe(_unwrap(self._request("POST", "game/data/author/project/list", body)))

    def project_detail(self, project_id: int) -> Any:
        return _safe(_unwrap(self._request("GET", "game/data/author/project/detail/%s" % _positive_id(project_id, field="project_id"))))

    def project_create(self, doc: Mapping[str, Any]) -> Any:
        document = _project_document(doc)
        return _safe(_unwrap(self._request("POST", "game/data/author/project/release", _project_wire(document, create=True))))

    def project_update(self, doc: Mapping[str, Any]) -> Any:
        document = _project_document(doc)
        wire = _project_wire(document, create=False)
        if _positive_id(document["project_id"], field="project_id") < 200000000:
            wire = self._restricted_project_wire(document, wire)
        return _safe(_unwrap(self._request("POST", "game/data/author/project/update", wire)))

    def _restricted_project_wire(self, document: Mapping[str, Any], wire: Mapping[str, Any]) -> Dict[str, Any]:
        project_id = _positive_id(document["project_id"], field="project_id")
        detail = self.project_detail(project_id)
        if (not isinstance(detail, Mapping) or str(detail.get("projectId", detail.get("id"))) != str(project_id) or
                not {"name", "synchronizationType"}.issubset(detail) or
                not ("categories" in detail or "categorieStrings" in detail)):
            raise FuploadError("Restricted project detail cannot verify immutable fields", kind="platform_data_error", stage="dependency_get")
        license_value = detail.get("license") or detail.get("licenseContent")
        if license_value is None:
            license_value = {"type": detail.get("licenseName")}
        categories = _category_ids(detail.get("categories", detail.get("categorieStrings")))
        if any(type(item) is not int or item <= 0 for item in categories):
            raise FuploadError("Restricted project categories are not valid IDs", kind="platform_data_error", stage="dependency_get")
        current = {
            "name": detail["name"], "repoUrl": _null_marker(detail.get("repoUrl")),
            "requiredTierId": None if detail.get("requiredTierId") is None else str(detail["requiredTierId"]),
            "synchronizationType": _sync_type(detail["synchronizationType"]),
            "categories": sorted(categories),
            "license": json.loads(_license_json(license_value, {})),
            "requiredDependencies": _null_marker(detail.get("requiredDependencies")),
        }
        for key in current:
            if key not in wire:
                continue
            actual = wire[key]
            if key == "categories":
                actual = sorted(_category_ids(actual))
            elif key == "license":
                actual = json.loads(actual)
            elif key == "requiredTierId":
                actual = None if actual == "<null>" else str(actual)
            if actual != current[key]:
                raise ValidationError("restricted Creator project field cannot be edited: " + key, path="$." + next((name for name, target in _WIRE_NAMES.items() if target == key), key))
        if "imagesOps" in wire or "images" in document and document["images"] != detail.get("images", 0):
            raise ValidationError("restricted Creator project images cannot be edited", path="$.image_ops")
        # Official BuildProjectChanges emits only these three editable fields
        # for imported/restricted projects, even when the snapshot is complete.
        return {key: value for key, value in wire.items() if key in {"projectId", "summary", "description", "altName"}}

    def project_delete(self, project_id: int) -> Any:
        return _safe(_unwrap(self._request("POST", "game/data/author/project/delete/project/%s" % _full_project_id(project_id))))

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
        _full_project_id(doc["project_id"])
        route = "game/data/author/project/file/update" if update else "game/data/author/project/upload"
        wire = _release_wire(doc)
        if not update:
            # UploadReleaseAsync's create payload has no fileId. The ID is
            # reserved by GetReleaseFileIdAsync and is consumed by signing.
            wire.pop("fileId", None)
        return _safe(_unwrap(self._request("POST", route, wire)))

    def user_info(self) -> Any:
        return _safe(_unwrap(self._request("GET", "system/user/getInfo")))

    def builds(self) -> Any:
        """Return the fixed WoW Build choices used by the ModUs main client."""
        current = self.current_build
        return {"current": current, "builds": [dict(item) for item in MODUS_BUILDS]}

    def _build(self, value: Optional[int]) -> int:
        selected = self.current_build if value is None else value
        if selected is None:
            # The desktop wrapper uses getCurrentWow?.id || 0.
            selected = 0
        selected = int(selected)
        if selected < 0 or selected > 4:
            raise ValidationError("server_type must be a known ModUs Build id", path="server_type")
        return selected

    def active_subscription_count(self) -> Any:
        return _safe(_unwrap(self._request("GET", "user/author/subscription/active/count")))

    def project_statistics(self) -> Any:
        return _safe(_unwrap(self._request("GET", "game/data/author/project/statistics")))

    def addon_info(self, directories: Any, *, server_type: Optional[int] = None) -> Any:
        values = directories if isinstance(directories, (list, tuple)) else [directories]
        body = {"pluginList": [str(value) for value in values]}
        return _safe(_unwrap(self._request("POST", "plugin/list/info", body, headers={"X-Server-Type": str(self._build(server_type))})))

    def addon_project_info(self, project_ids: Any, *, server_type: Optional[int] = None) -> Any:
        values = project_ids if isinstance(project_ids, (list, tuple)) else [project_ids]
        body = {"projectIds": [int(value) for value in values]}
        return _safe(_unwrap(self._request("POST", "plugin/list/detail", body, headers={"X-Server-Type": str(self._build(server_type))})))

    def addon_history(self, project_id: int, *, page_num: int = 1, page_size: int = 5, server_type: Optional[int] = None) -> Any:
        body = {"projectIds": [int(project_id)], "pageNum": int(page_num), "pageSize": int(page_size)}
        return _safe(_unwrap(self._request("POST", "plugin/project/history", body, headers={"X-Server-Type": str(self._build(server_type))})))

    def project_dependencies(self, query: Any) -> Any:
        body = _dependency_query_wire(query)
        return _safe(_unwrap(self._request("POST", "game/data/author/project/dependency/query", body)))

    def options(self, action: str, *, keys: Optional[Any] = None, author_id: Optional[int] = None,
                game_type: Optional[str] = None, server_type: Optional[int] = None) -> Any:
        if action == "season-subscription":
            return self.author_season_subscription(author_id=author_id, game_type=game_type, server_type=server_type)
        static_files = {
            "config-tags": "share_tags.json",
            "wa-tags": "imports_tags.json",
            "wa-support-addons": "imports_support_addons.json",
        }
        if action in static_files:
            url = urllib.parse.urljoin(STATIC_API_BASE, static_files[action])
            payload = json_request(url)
            if isinstance(payload, Mapping) and "rows" in payload:
                payload = payload["rows"]
            return _safe(_unwrap(payload))
        routes = {
            # These paths are the routes used by ModUs.Creator's ApiService.
            "categories": "plugin/list/Categories",
            "subscription-tiers": "user/author/subscription/tiers",
            "subscription-game-types": "user/game-type/list",
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

    def author_season_subscription(self, *, author_id: Optional[int] = None, game_type: Optional[str] = None,
                                   server_type: Optional[int] = None) -> Any:
        if author_id is None:
            user = self.user_info()
            if isinstance(user, Mapping) and isinstance(user.get("user"), Mapping):
                user = user["user"]
            author_id = user.get("userId", user.get("id")) if isinstance(user, Mapping) else None
        selected_author = _positive_id(author_id, field="author_id")
        if game_type is None:
            code = "wow_" + MODUS_BUILDS[self._build(server_type)]["code"]
            games = self._option_rows(self.options("subscription-game-types"))
            found = next((item.get("gameCode") for item in games if item.get("gameCode") == code), None)
            if found is None:
                raise FuploadError("Current WoW build has no subscription game-type choice", kind="platform_data_error", stage="dependency_get")
            game_type = found
        if not isinstance(game_type, str) or not game_type.strip():
            raise ValidationError("game_type must be a nonempty gameCode from subscription-game-types", path="$.game_type")
        query = urllib.parse.urlencode({"authorId": selected_author, "gameType": game_type})
        # GET_AUTHOR_SEASON_SUB_DETAIL explicitly omits X-Server-Type.
        payload = self._request("GET", "user/author/season-sub/detail?" + query)
        # The official form uses response.data ?? null, including a successful
        # envelope with no data when this author has no season subscription.
        return _safe(payload.get("data") if isinstance(payload, Mapping) else None)

    @staticmethod
    def _option_rows(value: Any) -> list[Mapping[str, Any]]:
        if isinstance(value, Mapping):
            value = value.get("rows", value.get("data", []))
        return [item for item in value if isinstance(item, Mapping)] if isinstance(value, list) else []

    @classmethod
    def _nested_option_rows(cls, value: Any) -> list[Mapping[str, Any]]:
        rows: list[Mapping[str, Any]] = []
        pending = list(cls._option_rows(value))
        while pending:
            item = pending.pop(0)
            rows.append(item)
            pending.extend(cls._option_rows(item.get("children", [])))
        return rows

    @staticmethod
    def _csv_values(value: Any) -> list[str]:
        return [item.strip() for item in str(value or "").split(",") if item.strip()]

    @staticmethod
    def _account_rows(backup: Mapping[str, Any]) -> list[Mapping[str, Any]]:
        value = backup.get("wtfAccounts") or []
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except (TypeError, ValueError):
                value = []
        return [item for item in value if isinstance(item, Mapping)] if isinstance(value, list) else []

    @staticmethod
    def _backup_addons_id(backup: Mapping[str, Any]) -> Optional[str]:
        value = backup.get("knownAddons")
        if not isinstance(value, str) or not value.strip():
            return None
        try:
            parsed = json.loads(value)
        except (TypeError, ValueError):
            return None
        project_ids = parsed.get("projectids") if isinstance(parsed, Mapping) else None
        return None if project_ids is None else str(project_ids)

    def _validate_project_write(self, action: str, doc: Mapping[str, Any]) -> None:
        if action not in {"create", "release", "update", "edit"}:
            return
        document = _project_document(doc)
        allowed_categories = {
            int(item["id"])
            for item in self._nested_option_rows(self.options("categories"))
            if item.get("id") is not None
        }
        unknown = [item for item in document.get("categories", []) if item not in allowed_categories]
        if unknown:
            raise ValidationError(
                "category is not present in current Creator options",
                path="$.project_state.basic_info.categories",
            )

    def _validate_main_write(self, resource: str, action: str, doc: Mapping[str, Any]) -> None:
        if resource not in {"config", "wa"} or action not in {"create", "update", "edit"}:
            return

        if action == "create" and (("share_id" if resource == "config" else "import_id") in doc or "id" in doc):
            raise ValidationError("create does not accept an existing record ID", path="$." + ("share_id" if resource == "config" else "import_id"))

        if "tags" in doc:
            option_name = "config-tags" if resource == "config" else "wa-tags"
            allowed_tags = {str(item.get("id")) for item in self._option_rows(self.options(option_name)) if item.get("id") is not None}
            unknown = [item for item in self._csv_values(doc.get("tags")) if item not in allowed_tags]
            if unknown:
                raise ValidationError("tag is not present in current %s options" % option_name, path="$.tags")

        selection = dict(doc)
        if action in {"update", "edit"} and {"sub_type", "required_tier_id"}.intersection(doc) and not {"sub_type", "required_tier_id"}.issubset(doc):
            identity = "share_id" if resource == "config" else "import_id"
            current = self.share_detail(doc[identity], server_type=doc.get("server_type")) if resource == "config" else self.import_detail(doc[identity], server_type=doc.get("server_type"))
            current = current[0] if isinstance(current, list) and len(current) == 1 else current
            if not isinstance(current, Mapping) or str(current.get("id")) != str(doc[identity]):
                raise FuploadError("Current subscription selection cannot be read", kind="platform_data_error", stage="dependency_get")
            selection.setdefault("sub_type", current.get("subType", 0))
            selection.setdefault("required_tier_id", current.get("requiredTierId"))
        tier_id = selection.get("required_tier_id")
        if tier_id is not None:
            if selection.get("sub_type", 0) == 1:
                season = self.options("season-subscription", server_type=doc.get("server_type"))
                if (not isinstance(season, Mapping) or str(season.get("id")) != str(tier_id) or
                        season.get("isEnabled") != 1 or str(season.get("platformSeasonStatus")) == "2"):
                    raise ValidationError("required_tier_id is not an enabled, unfinished season subscription for this author and game", path="$.required_tier_id")
            else:
                tiers = self._option_rows(self.options("subscription-tiers"))
                allowed_tiers = {
                    str(item.get("id")) for item in tiers
                    if item.get("id") is not None and item.get("isEnabled", item.get("is_enabled", 1)) not in (0, False)
                }
                if str(tier_id) not in allowed_tiers:
                    raise ValidationError("required_tier_id is not present in current tier options", path="$.required_tier_id")

        if resource == "wa" and ("support_addon" in doc or "addons_id" in doc):
            selected_doc = dict(doc)
            if action in {"update", "edit"} and (
                "support_addon" not in selected_doc or "addons_id" not in selected_doc
            ):
                current = self.import_detail(doc["import_id"], server_type=doc.get("server_type"))
                current = current[0] if isinstance(current, list) and current else current
                if isinstance(current, Mapping):
                    selected_doc.setdefault("support_addon", current.get("supportAddon"))
                    selected_doc.setdefault("addons_id", current.get("addonsId"))
            support_rows = self._option_rows(self.options("wa-support-addons"))
            selected = next((item for item in support_rows if str(item.get("name")) == str(selected_doc.get("support_addon"))), None)
            if selected is None or str(selected.get("id")) != str(selected_doc.get("addons_id")):
                raise ValidationError("support_addon and addons_id must match current options", path="$.support_addon")
            return

        if resource != "config":
            return
        linkage_fields = {"backup_id", "addons_id", "account_name", "role_name", "exclude_wtf"}
        if not linkage_fields.intersection(doc):
            return
        merged = dict(doc)
        if action in {"update", "edit"} and "backup_id" not in merged:
            current = self.share_detail(doc["share_id"], server_type=doc.get("server_type"))
            current = current[0] if isinstance(current, list) and current else current
            if isinstance(current, Mapping):
                aliases = {
                    "backupId": "backup_id", "addonsId": "addons_id", "accountName": "account_name",
                    "roleName": "role_name", "excludeWtf": "exclude_wtf",
                }
                for wire, local in aliases.items():
                    if local not in merged and wire in current:
                        merged[local] = current[wire]
        backup_id = merged.get("backup_id")
        backups = self._option_rows(self.cloud_backups(server_type=merged.get("server_type")))
        backup = next((item for item in backups if str(item.get("id")) == str(backup_id)), None)
        if backup is None:
            raise ValidationError("backup_id is not present in the selected Build", path="$.backup_id")
        from .modus_backup import _backup_build
        if _backup_build(backup) != self._build(merged.get("server_type")):
            raise ValidationError("backup_id belongs to a different Build", path="$.backup_id")
        expected_addons = self._backup_addons_id(backup)
        if expected_addons is not None and "addons_id" in merged and str(merged.get("addons_id")) != expected_addons:
            raise ValidationError("addons_id does not match selected backup knownAddons.projectids", path="$.addons_id")
        if int(merged.get("exclude_wtf") or 0) == 1:
            return
        account_name = str(merged.get("account_name") or "")
        account = next((item for item in self._account_rows(backup) if account_name in {
            str(item.get("id") or ""), str(item.get("accountId") or ""),
            str(item.get("name") or ""), str(item.get("characterName") or ""),
        }), None)
        if account is None:
            raise ValidationError("account_name is not present in selected backup", path="$.account_name")
        roles = [str(item) for item in account.get("roles") or [] if str(item)]
        role_name = str(merged.get("role_name") or "")
        if roles and not role_name:
            raise ValidationError("role_name is required for selected account", path="$.role_name")
        if role_name and role_name not in roles:
            raise ValidationError("role_name is not present in selected account", path="$.role_name")

    # Main ModUs client: configuration shares and string articles.
    def cloud_backups(self, *, server_type: Optional[int] = None) -> Any:
        return _safe(_unwrap(self._request("GET", "system/user/backup/list", headers={"X-Server-Type": str(self._build(server_type))})))

    def cloud_backup_detail(self, backup_id: int, *, server_type: Optional[int] = None) -> Any:
        return _safe(_unwrap(self._request("GET", "system/user/backup/detail/%s" % _positive_id(backup_id, field="backup_id"), headers={"X-Server-Type": str(self._build(server_type))})))

    def cloud_backup_update(self, doc: Mapping[str, Any], *, server_type: Optional[int] = None) -> Any:
        body = {"id": _positive_id(doc["backup_id"], field="backup_id"), "backupName": doc["backup_name"]}
        self._request("POST", "system/user/backup/update", body, headers={"X-Server-Type": str(self._build(server_type))})
        try:
            from .modus_backup import rows
            detail = rows(self.cloud_backup_detail(body["id"], server_type=server_type))
            if not any(str(item.get("id", item.get("backupId"))) == str(body["id"]) and item.get("backupName", item.get("name")) == body["backupName"] for item in detail):
                raise FuploadError("Renamed backup was not confirmed")
        except FuploadError as exc:
            raise FuploadError("Backup rename requires readback verification", stage="backup_readback", verification_required=True,
                               details={"backup_id": body["id"]}) from exc
        return {"backup_id": body["id"], "backup_name": body["backupName"], "renamed": True, "verified": True}

    def cloud_backup_delete(self, backup_id: int, *, server_type: Optional[int] = None) -> Any:
        from .modus_backup import delete_one
        return delete_one(self, backup_id, self._build(server_type))

    def cloud_backup_preview(self, doc: Mapping[str, Any], *, server_type: Optional[int] = None) -> Any:
        from .modus_backup import preview
        return preview(self, doc, self._build(doc.get("server_type", server_type)))

    def cloud_backup_delete_many(self, doc: Mapping[str, Any], *, server_type: Optional[int] = None) -> Any:
        from .modus_backup import delete_many
        return delete_many(self, doc, self._build(doc.get("server_type", server_type)))

    def cloud_backup_generate(self, doc: Mapping[str, Any], *, server_type: Optional[int] = None) -> Any:
        from .modus_backup import generate
        return generate(doc, self._build(doc.get("server_type", server_type)))

    def cloud_backup_scan(self, doc: Mapping[str, Any], *, server_type: Optional[int] = None) -> Any:
        from .modus_backup import scan
        return scan(doc, self._build(doc.get("server_type", server_type)))

    def cloud_backup_upload(self, doc: Mapping[str, Any], *, server_type: Optional[int] = None) -> Any:
        from .modus_backup import upload
        return upload(self, doc, self._build(doc.get("server_type", server_type)))

    def image_upload(self, file_path: str) -> Dict[str, Any]:
        """Upload an image through the exact ModUs main-client multipart API."""
        path = Path(file_path)
        if not path.is_file():
            raise ValidationError("image file does not exist", path="$.file")
        authorization = self._authorization_value()
        headers = {"Accept": "application/json", "Authorization": authorization}
        if self.device_id:
            headers["X-Device-Id"] = self.device_id
        payload = multipart_request(
            self._url("game/data/file/upload/file/image"),
            str(path),
            file_field="file",
            headers=headers,
            timeout=max(self.timeout, 600),
        )
        if isinstance(payload, Mapping):
            business_code = _business_code(payload)
            if payload.get("success") is False or (business_code is not None and business_code != 200):
                raise FuploadError(
                    str(payload.get("msg") or payload.get("message") or "ModUs image upload was rejected"),
                    endpoint=self._url("game/data/file/upload/file/image"),
                    business_code=business_code,
                    kind="platform_error",
                    stage="media_upload",
                )
        record = _image_upload_record(payload)
        content = path.read_bytes()
        return {
            **record,
            "bytes": len(content),
            "sha256": hashlib.sha256(content).hexdigest(),
        }

    @staticmethod
    def _share_wire(doc: Mapping[str, Any], *, create: bool = True) -> Dict[str, Any]:
        aliases = {"share_id": "id", "addons_id": "addonsId", "backup_id": "backupId", "account_name": "accountName", "content_text": "contentText", "image_url": "imageUrl", "is_paid": "isPaid", "is_public": "isPublic", "share_type": "shareType", "exclude_wtf": "excludeWtf", "role_name": "roleName", "required_tier_id": "requiredTierId", "sub_type": "subType", "synchronization_type": "synchronizationType"}
        allowed = {"id", "addonsId", "backupId", "accountName", "content", "contentText", "imageUrl", "isPaid", "isPublic", "price", "shareType", "tags", "title", "excludeWtf", "roleName", "requiredTierId", "subType", "platform", "synchronizationType"}
        result = {}
        for key, value in doc.items():
            wire = aliases.get(key, key)
            if wire in allowed and value is None and wire != "requiredTierId":
                raise ValidationError("null clearing is not supported for this main-client field; use an explicit valid value", path="$." + str(key))
            if wire in allowed and value is not None:
                result[wire] = str(value) if wire == "addonsId" else value
        if create:
            result.setdefault("platform", 1)
        if create or "excludeWtf" in result:
            exclude = result.get("excludeWtf", 0)
            result["excludeWtf"] = 1 if str(exclude).strip().lower() in {"1", "true"} else 0
        return result

    def _main_update_wire(self, resource: str, doc: Mapping[str, Any], *, server_type: Optional[int] = None) -> Dict[str, Any]:
        config = resource == "config"
        identity = "share_id" if config else "import_id"
        target = _resource_id(doc.get(identity), field=identity)
        builder = self._share_wire if config else self._import_wire
        patch = builder(doc, create=False)
        detail = self.share_detail(target, server_type=server_type) if config else self.import_detail(target, server_type=server_type)
        if isinstance(detail, list):
            detail = detail[0] if len(detail) == 1 else None
        if not isinstance(detail, Mapping) or str(detail.get("id")) != target:
            raise FuploadError("Current main-client detail does not identify the requested record", kind="platform_data_error", stage="dependency_get")
        current = builder({key: value for key, value in detail.items() if value is not None}, create=False)
        if config and "backup_id" in doc and str(doc["backup_id"]) != str(current.get("backupId")):
            required = {"addons_id", "exclude_wtf", "account_name", "role_name"}
            if not required.issubset(doc):
                raise ValidationError("changing backup_id requires explicit addon, WTF account and role selections", path="$.backup_id")
        current.update(patch)
        current["id"] = target
        # The live detail API omits contentText. Official Q2 reconstructs it
        # from editor HTML; retaining old text after a content edit is also wrong.
        if not {"content_text", "contentText"}.intersection(doc) and ("content" in doc or "contentText" not in current):
            current["contentText"] = _main_plaintext(current.get("content"))
        if "required_tier_id" in doc and doc["required_tier_id"] is None:
            # Official buildSubscriptionPayload omits requiredTierId after the
            # user selects "none". Rebuild the full form without the old key.
            current.pop("requiredTierId", None)
        if config and "exclude_wtf" in doc and patch.get("excludeWtf") == 1:
            if doc.get("account_name") or doc.get("role_name"):
                raise ValidationError("excluded WTF cannot retain an explicit account or role", path="$.account_name")
            current.update({"accountName": "", "roleName": ""})
        required_wire = {"addonsId", "content", "contentText", "imageUrl", "isPaid", "isPublic", "price", "shareType", "tags", "title"}
        required_wire.update({"backupId", "excludeWtf"} if config else {"filePath", "supportAddon", "version"})
        if required_wire - current.keys():
            raise FuploadError("Current main-client detail lacks fields needed to preserve omitted values", kind="platform_data_error", stage="dependency_get", details={"fields": sorted(required_wire - current.keys())})
        if current.get("requiredTierId") is not None and (current.get("platform") == 3 or current.get("synchronizationType") == 3):
            raise ValidationError("a required tier cannot be combined with BigFoot synchronization", path="$.required_tier_id")
        return current

    def share_list(self, body: Optional[Mapping[str, Any]] = None, *, server_type: Optional[int] = None) -> Any:
        source = body or {}
        selected_build = self._build(source.get("server", server_type))
        mine = source.get("mine")
        share_type = source.get("share_type")
        wire = {
            "pageNum": int(source.get("page_num") or 1),
            "pageSize": int(source.get("page_size") or 20),
            "server": selected_build,
            "mine": False if mine is None else bool(mine),
            "shareType": 0 if share_type is None else share_type,
        }
        platform = source.get("platform")
        wire["platform"] = int(platform) if isinstance(platform, (int, float)) and not isinstance(platform, bool) else 0
        for key in ("keyword", "status", "tags", "order_by", "is_public", "is_paid"):
            if key in source and source[key] is not None:
                wire[{"order_by": "orderBy", "is_public": "isPublic", "is_paid": "isPaid"}.get(key, key)] = (
                    _tag_filter(source[key]) if key == "tags" else source[key]
                )
        return _safe(_unwrap(self._request("POST", "system/user/share/list", wire, headers={"X-Server-Type": str(selected_build)})))

    def share_detail(self, share_ids: Any, *, server_type: Optional[int] = None) -> Any:
        ids = share_ids if isinstance(share_ids, list) else [share_ids]
        return _safe(_unwrap(self._request("POST", "system/user/share/detail", {"shareIds": [_resource_id(x, field="share_id") for x in ids]}, headers={"X-Server-Type": str(self._build(server_type))})))

    def share_create(self, doc: Mapping[str, Any], *, server_type: Optional[int] = None) -> Any:
        if "share_id" in doc or "id" in doc:
            raise ValidationError("create does not accept an existing record ID", path="$.share_id")
        return _safe(_unwrap(self._request("POST", "system/user/share/create", self._share_wire(doc), headers={"X-Server-Type": str(self._build(server_type))})))

    def share_update(self, doc: Mapping[str, Any], *, server_type: Optional[int] = None) -> Any:
        wire = self._main_update_wire("config", doc, server_type=server_type)
        return _safe(_unwrap(self._request("PUT", "system/user/share/update", wire, headers={"X-Server-Type": str(self._build(server_type))})))

    def share_delete(self, share_id: Any, *, server_type: Optional[int] = None) -> Any:
        return _safe(_unwrap(self._request("DELETE", "system/user/share/delete/%s" % urllib.parse.quote(_resource_id(share_id, field="share_id"), safe=""), headers={"X-Server-Type": str(self._build(server_type))})))

    @staticmethod
    def _import_wire(doc: Mapping[str, Any], *, create: bool = True) -> Dict[str, Any]:
        aliases = {"import_id": "id", "code_text": "codeText", "addons_id": "addonsId", "content_text": "contentText", "file_path": "filePath", "image_url": "imageUrl", "is_paid": "isPaid", "is_public": "isPublic", "share_type": "shareType", "support_addon": "supportAddon", "required_tier_id": "requiredTierId", "sub_type": "subType", "synchronization_type": "synchronizationType"}
        allowed = {"id", "codeText", "content", "addonsId", "contentText", "filePath", "imageUrl", "isPaid", "isPublic", "price", "shareType", "supportAddon", "tags", "title", "version", "requiredTierId", "subType", "platform", "synchronizationType"}
        for key, value in doc.items():
            if aliases.get(key, key) in allowed and value is None and aliases.get(key, key) != "requiredTierId":
                raise ValidationError("null clearing is not supported for this main-client field; use an explicit valid value", path="$." + str(key))
        result = {aliases.get(key, key): value for key, value in doc.items() if aliases.get(key, key) in allowed and value is not None}
        if "addonsId" in result:
            result["addonsId"] = str(result["addonsId"])
        if create:
            result.setdefault("platform", 1)
            result.setdefault("synchronizationType", 3 if result["platform"] == 3 else 1)
        return result

    def import_list(self, body: Optional[Mapping[str, Any]] = None, *, server_type: Optional[int] = None) -> Any:
        source = body or {}
        selected_build = self._build(source.get("server", server_type))
        mine = source.get("mine")
        status = source.get("status")
        wire = {
            "pageNum": int(source.get("page_num") or 1),
            "pageSize": int(source.get("page_size") or 10),
            "server": selected_build,
            "mine": False if mine is None else bool(mine),
            "status": 1 if status is None else status,
        }
        platform = source.get("platform")
        wire["platform"] = int(platform) if isinstance(platform, (int, float)) and not isinstance(platform, bool) else 0
        for key in ("keyword", "support_addon", "tags", "is_paid", "order_by"):
            if key in source and source[key] is not None:
                wire[{"support_addon": "supportAddon", "is_paid": "isPaid", "order_by": "orderBy"}.get(key, key)] = (
                    _tag_filter(source[key]) if key == "tags" else source[key]
                )
        return _safe(_unwrap(self._request("POST", "system/user/import/list", wire, headers={"X-Server-Type": str(selected_build)})))

    def import_detail(self, import_ids: Any, *, server_type: Optional[int] = None) -> Any:
        ids = import_ids if isinstance(import_ids, list) else [import_ids]
        return _safe(_unwrap(self._request("POST", "system/user/import/detail", {"importIds": [_resource_id(x, field="import_id") for x in ids]}, headers={"X-Server-Type": str(self._build(server_type))})))

    def import_create(self, doc: Mapping[str, Any], *, server_type: Optional[int] = None) -> Any:
        if "import_id" in doc or "id" in doc:
            raise ValidationError("create does not accept an existing record ID", path="$.import_id")
        return _safe(_unwrap(self._request("POST", "system/user/import/create", self._import_wire(doc), headers={"X-Server-Type": str(self._build(server_type))})))

    def import_update(self, doc: Mapping[str, Any], *, server_type: Optional[int] = None) -> Any:
        wire = self._main_update_wire("wa", doc, server_type=server_type)
        return _safe(_unwrap(self._request("POST", "system/user/import/update", wire, headers={"X-Server-Type": str(self._build(server_type))})))

    def import_delete(self, import_id: Any, *, server_type: Optional[int] = None) -> Any:
        return _safe(_unwrap(self._request("DELETE", "system/user/import/delete/%s" % urllib.parse.quote(_resource_id(import_id, field="import_id"), safe=""), headers={"X-Server-Type": str(self._build(server_type))})))

    def import_version_publish(self, doc: Mapping[str, Any], *, server_type: Optional[int] = None) -> Any:
        body = {
            "importId": _resource_id(doc["import_id"], field="import_id"),
            "version": str(doc["version"]).strip(),
            "codeText": str(doc["code_text"]).strip(),
        }
        changelog = str(doc.get("changelog") or "").strip()
        if changelog:
            body["changelog"] = changelog
        return _safe(_unwrap(self._request("POST", "system/user/import/version/publish", body, headers={"X-Server-Type": str(self._build(server_type))})))

    def import_version_delete(self, version_id: Any, *, server_type: Optional[int] = None) -> Any:
        return _safe(_unwrap(self._request("DELETE", "system/user/import/version/delete?versionId=%s" % urllib.parse.quote(str(version_id), safe=""), headers={"X-Server-Type": str(self._build(server_type))})))

    def release_signature(self, project_id: int, file_id: int) -> str:
        result = _unwrap(self._request("GET", "game/data/author/project/file/upload/signature/%s/%s" % (_positive_id(project_id, field="project_id"), _positive_id(file_id, field="file_id"))))
        url = result.get("signedUrl") if isinstance(result, Mapping) else result
        if not isinstance(url, str) or not url.startswith(("https://", "http://")):
            raise FuploadError("ModUs did not return a valid release upload URL", kind="platform_data_error")
        return url

    def upload_zip(self, signed_url: str, file_path: str, *, content_type: str = "application/zip") -> Dict[str, Any]:
        path = Path(file_path)
        if not path.is_file():
            raise ValidationError("release ZIP file does not exist", path=file_path)
        size = path.stat().st_size
        if size > MAX_PACKAGE_BYTES:
            raise ValidationError("release ZIP exceeds the 200 MB upload limit", path=file_path)
        parsed = urllib.parse.urlsplit(signed_url)
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            raise ValidationError("release upload URL must be HTTP(S)", path="signed_url")
        # The query carries the object-store signature.  Keep a useful endpoint
        # in errors without ever persisting that credential material.
        endpoint_host = parsed.hostname
        if parsed.port is not None:
            endpoint_host = "%s:%d" % (endpoint_host, parsed.port)
        endpoint = urllib.parse.urlunsplit((parsed.scheme, endpoint_host, parsed.path or "/", "", ""))
        conn_cls = http.client.HTTPSConnection if parsed.scheme == "https" else http.client.HTTPConnection
        conn = None
        try:
            if parsed.scheme == "https":
                conn = conn_cls(parsed.hostname, parsed.port, timeout=max(self.timeout, 600), context=ssl.create_default_context())
            else:
                conn = conn_cls(parsed.hostname, parsed.port, timeout=max(self.timeout, 600))
            conn.putrequest("PUT", urllib.parse.urlunsplit(("", "", parsed.path or "/", parsed.query, "")))
            conn.putheader("Content-Type", content_type)
            conn.putheader("Content-Length", str(size))
            conn.endheaders()
            with path.open("rb") as handle:
                while True:
                    chunk = handle.read(1024 * 1024)
                    if not chunk:
                        break
                    conn.send(chunk)
            response = conn.getresponse()
            etag = response.getheader("ETag") if hasattr(response, "getheader") else None
            raw = response.read(4096)
            if response.status < 200 or response.status >= 300:
                summary = redact(raw.decode("utf-8", errors="replace")) if raw else "<empty>"
                raise FuploadError(
                    "ModUs binary upload returned HTTP %d" % response.status,
                    endpoint=endpoint,
                    http_status=response.status,
                    verification_required=True,
                    stage="binary_upload",
                    details={"response_summary": summary},
                )
        except FuploadError:
            raise
        except (OSError, http.client.HTTPException) as exc:
            raise FuploadError(
                "ModUs binary upload failed",
                endpoint=endpoint,
                verification_required=True,
                stage="binary_upload",
                details={"response_summary": redact(str(exc)) or exc.__class__.__name__},
            ) from exc
        finally:
            if conn is not None:
                try:
                    conn.close()
                except OSError:
                    pass
        return {"status": "uploaded", "archive": path.name, "bytes": size, **({"etag": str(etag).strip('"')} if etag else {})}

    def release_delete(self, project_id: int, file_id: int) -> Any:
        return _safe(_unwrap(self._request("POST", "game/data/author/project/delete", {"projectId": _full_project_id(project_id), "fileId": _positive_id(file_id, field="file_id")})))

    def publish(self, doc: Mapping[str, Any], *, update: bool = False) -> Dict[str, Any]:
        project_id = _full_project_id(doc["project_id"])
        file_path = doc.get("file")
        archive = Path(str(file_path)) if file_path is not None else None
        supplied_file_id = doc.get("file_id")
        transaction: Dict[str, Any] = {
            "schema": "fupload.v1.modus.upload-transaction",
            "created_at": int(time.time()),
            "project_id": project_id,
            "file_id": None,
            "update": bool(update),
            "archive": str(archive) if archive is not None else None,
            "stages": [],
        }
        transaction_path = Path(str(doc.get("transaction_log") or ((str(archive) + ".modus-transaction.json") if archive else "modus-transaction.json")))

        def save_transaction() -> None:
            transaction_path.write_text(json.dumps(transaction, ensure_ascii=False, indent=2), encoding="utf-8")

        # Establish the audit record before reserving a file ID or validating
        # the archive so every publish failure has a durable transaction.
        try:
            save_transaction()
        except OSError as exc:
            raise FuploadError(
                "ModUs upload transaction could not be written",
                stage="transaction_log",
                details={"path": str(transaction_path)},
            ) from exc

        current_stage = "prepare"
        try:
            allocated_file_id = not bool(supplied_file_id)
            current_stage = "file_id"
            transaction["active_stage"] = current_stage
            save_transaction()
            if allocated_file_id:
                transaction["stages"].append("file_id")
                file_id = _positive_id(self.release_file_id(project_id), field="file_id")
            else:
                file_id = _positive_id(supplied_file_id, field="file_id")
            transaction["file_id"] = file_id

            metadata = {k: doc[k] for k in ("project_id", "version", "type", "supported_game_versions", "toc_version", "changelog", "path", "md5", "zip_size", "unzip_size") if k in doc}
            metadata["file_id"] = file_id
            current_stage = "zip_preflight"
            transaction["active_stage"] = current_stage
            save_transaction()
            if archive is None and not update:
                raise ValidationError("release ZIP file is required", path="file")
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
                for field, expected in (("md5", md5), ("zip_size", size), ("unzip_size", unzip_size)):
                    if field in doc and (str(doc[field]).casefold() != expected if field == "md5" else doc[field] != expected):
                        raise ValidationError("%s does not match the release ZIP" % field, path="$." + field)
                derived = parse_modus_zip(archive)
                supplied_toc = doc.get("toc_version")
                supplied_games = doc.get("supported_game_versions")
                if supplied_toc is not None and str(supplied_toc) != derived["toc_version"]:
                    raise ValidationError("toc_version does not match the ZIP Interface field", path="$.toc_version")
                selected_games = select_game_versions(
                    derived["supported_game_versions"],
                    self.options("game-versions", keys=["wow_builds"]),
                    _supported_game_versions(supplied_games) if supplied_games is not None else None,
                )
                metadata.update({
                    "md5": md5,
                    "zip_size": size,
                    "unzip_size": unzip_size,
                    "toc_version": derived["toc_version"],
                    "supported_game_versions": selected_games,
                    "path": doc.get("path") or archive.name,
                })
            current_stage = "release_metadata_update" if update else "release_metadata"
            transaction["stages"].append(current_stage)
            transaction["active_stage"] = current_stage
            save_transaction()
            result = self.release_metadata(metadata, update=update)
            if archive is None:
                transaction.pop("active_stage", None)
                transaction.update({"completed": True, "upload": None})
                save_transaction()
                return {"project_id": project_id, "file_id": file_id, "metadata": result, "upload": None, "transaction": _safe(transaction)}
            current_stage = "signature"
            transaction["stages"].append(current_stage)
            transaction["active_stage"] = current_stage
            save_transaction()
            signed = self.release_signature(project_id, file_id)
            current_stage = "binary_upload"
            transaction["stages"].append(current_stage)
            transaction["active_stage"] = current_stage
            save_transaction()
            uploaded = self.upload_zip(signed, str(archive))
            transaction.pop("active_stage", None)
            transaction.update({"completed": True, "upload": uploaded})
            save_transaction()
            return {"project_id": project_id, "file_id": file_id, "metadata": result, "upload": uploaded, "transaction": _safe(transaction)}
        except FuploadError as exc:
            if exc.stage in (None, "dependency_get"):
                exc.stage = current_stage
            transaction["failed_stage"] = exc.stage or current_stage
            transaction["error"] = exc.as_dict()
            transaction["retained_archive"] = bool(archive and archive.is_file())
            try:
                save_transaction()
            except OSError:
                pass
            raise
        except OSError as exc:
            wrapped = FuploadError(
                "ModUs upload preparation failed",
                stage=current_stage,
                details={"response_summary": redact(str(exc)) or exc.__class__.__name__},
            )
            transaction["failed_stage"] = current_stage
            transaction["error"] = wrapped.as_dict()
            transaction["retained_archive"] = bool(archive and archive.is_file())
            try:
                save_transaction()
            except OSError:
                pass
            raise wrapped from exc

    def execute_read(self, resource: str, action: str, args: Any = None) -> Any:
        if resource == "session" and action == "doctor": return self.doctor()
        if resource == "options" and action == "builds": return self.builds()
        if resource == "builds" and action == "list": return self.builds()
        doc = vars(args) if args is not None and hasattr(args, "__dict__") else (args or {})
        if resource == "backup":
            if action == "list": return self.cloud_backups(server_type=doc.get("server_type"))
            if action == "get": return self.cloud_backup_detail(doc["backup_id"], server_type=doc.get("server_type"))
            if action == "scan": return self.cloud_backup_scan(doc, server_type=doc.get("server_type"))
            if action == "delete-preview": return self.cloud_backup_preview(doc, server_type=doc.get("server_type"))
        if resource == "account" and action == "info": return self.user_info()
        if resource == "account" and action == "subscription-count": return self.active_subscription_count()
        if resource == "account" and action == "statistics": return self.project_statistics()
        if resource == "addon" and action == "info": return self.addon_info(doc.get("directories", []), server_type=doc.get("server_type"))
        if resource == "addon" and action == "project-info": return self.addon_project_info(doc.get("project_ids", []), server_type=doc.get("server_type"))
        if resource == "addon" and action == "history": return self.addon_history(doc["project_id"], page_num=doc.get("page_num") or doc.get("page", 1), page_size=doc.get("page_size", 5), server_type=doc.get("server_type"))
        if resource == "project" and action == "dependencies": return self.project_dependencies(doc.get("query") or doc.get("project_ids") or doc.get("project_id"))
        if resource == "options":
            if action == "season-subscription":
                return self.options(action, author_id=doc.get("author_id"), game_type=doc.get("game_type"))
            return self.options(action, keys=doc.get("keys"))
        if resource == "config" and action == "backups": return self.cloud_backups(server_type=doc.get("server_type"))
        if resource == "config" and action == "backup-get": return self.cloud_backup_detail(doc["backup_id"], server_type=doc.get("server_type"))
        if resource == "config" and action == "backup-delete-preview": return self.cloud_backup_preview(doc, server_type=doc.get("server_type"))
        if resource == "config" and action == "list": return self.share_list(doc, server_type=doc.get("server_type"))
        if resource == "config" and action == "get": return self.share_detail(doc["share_id"], server_type=doc.get("server_type"))
        if resource == "wa" and action == "list": return self.import_list(doc, server_type=doc.get("server_type"))
        if resource == "wa" and action == "get": return self.import_detail(doc["import_id"], server_type=doc.get("server_type"))
        if resource == "project" and action == "list": return self.project_list(page_num=doc.get("page_num") or doc.get("page", 1), page_size=doc.get("page_size", 50), **({"keyword": doc["keyword"]} if doc.get("keyword") is not None else {}))
        if resource == "project" and action in ("get", "detail"): return self.project_detail(doc["project_id"])
        if resource in ("plugin", "release") and action in ("list", "versions"): return self.release_list(doc["project_id"], page_num=doc.get("page_num") or doc.get("page", 1), page_size=doc.get("page_size", 50))
        if resource in ("plugin", "release") and action == "get": return self.release_detail(doc["project_id"], doc["file_id"])
        raise ValidationError("unsupported ModUs read operation")

    def execute_write(self, resource: str, action: str, doc: Mapping[str, Any]) -> Any:
        if resource == "backup":
            if action == "generate": return self.cloud_backup_generate(doc, server_type=doc.get("server_type"))
            if action == "upload": return self.cloud_backup_upload(doc, server_type=doc.get("server_type"))
            if action == "create":
                generated = self.cloud_backup_generate(doc, server_type=doc.get("server_type"))
                try:
                    uploaded = self.cloud_backup_upload({**doc, "manifest_file": generated["manifest_file"]}, server_type=doc.get("server_type"))
                except FuploadError as exc:
                    exc.details["generated_backup"] = generated
                    raise
                return {"generated_backup": generated, "cloud_backup": uploaded}
            if action == "rename": return self.cloud_backup_update(doc, server_type=doc.get("server_type"))
            if action == "delete": return self.cloud_backup_delete_many(doc, server_type=doc.get("server_type"))
        if resource == "media" and action == "upload": return self.image_upload(str(doc["file"]))
        if resource == "config" and action == "backup-generate": return self.cloud_backup_generate(doc, server_type=doc.get("server_type"))
        if resource == "config" and action == "backup-upload": return self.cloud_backup_upload(doc, server_type=doc.get("server_type"))
        if resource == "config" and action == "backup-delete-many": return self.cloud_backup_delete_many(doc, server_type=doc.get("server_type"))
        if resource == "project": self._validate_project_write(action, doc)
        self._validate_main_write(resource, action, doc)
        if resource == "config" and action == "create": return self.share_create(doc, server_type=doc.get("server_type"))
        if resource == "config" and action in ("update", "edit"): return self.share_update(doc, server_type=doc.get("server_type"))
        if resource == "config" and action == "delete": return self.share_delete(doc["share_id"], server_type=doc.get("server_type"))
        if resource == "config" and action == "backup-edit": return self.cloud_backup_update(doc, server_type=doc.get("server_type"))
        if resource == "config" and action == "backup-delete": return self.cloud_backup_delete(doc["backup_id"], server_type=doc.get("server_type"))
        if resource == "wa" and action == "create": return self.import_create(doc, server_type=doc.get("server_type"))
        if resource == "wa" and action in ("update", "edit"): return self.import_update(doc, server_type=doc.get("server_type"))
        if resource == "wa" and action == "delete": return self.import_delete(doc["import_id"], server_type=doc.get("server_type"))
        if resource == "wa" and action == "version-publish": return self.import_version_publish(doc, server_type=doc.get("server_type"))
        if resource == "wa" and action == "version-delete": return self.import_version_delete(doc["version_id"], server_type=doc.get("server_type"))
        if resource == "project" and action in ("create", "release"): return self.project_create(doc)
        if resource == "project" and action in ("update", "edit"): return self.project_update(doc)
        if resource == "project" and action == "delete": return self.project_delete(int(doc["project_id"]))
        if resource in ("plugin", "release") and action in ("upload", "create"): return self.publish(doc)
        if resource in ("plugin", "release") and action in ("update", "edit"): return self.publish(doc, update=True)
        if resource in ("plugin", "release") and action == "delete": return self.release_delete(doc["project_id"], doc["file_id"])
        raise ValidationError("unsupported ModUs write operation")


Modus = ModUs
