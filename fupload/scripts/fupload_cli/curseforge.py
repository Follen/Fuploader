"""CurseForge public project lookup and author upload provider."""

from __future__ import annotations

import json
import os
import urllib.parse
from pathlib import Path
from typing import Any, Dict, Mapping, Optional

from .errors import FuploadError, ValidationError
from .transport import json_request, multipart_request


CORE_BASE = "https://api.curseforge.com"
UPLOAD_BASE = "https://wow.curseforge.com"
CONFIG_KEYS = (
    "CURSEFORGE_AUTHOR_ID",
    "CURSEFORGE_API_KEY",
    "CURSEFORGE_UPLOAD_TOKEN",
)


def config_path() -> Path:
    return Path.home() / ".fupload" / "curseforge.env"


def load_config(path: Optional[Path] = None) -> Dict[str, str]:
    """Load only the fixed CurseForge fields, with process env taking precedence."""
    source = path or config_path()
    values: Dict[str, str] = {}
    if source.is_file():
        try:
            lines = source.read_text(encoding="utf-8-sig").splitlines()
        except OSError as exc:
            raise FuploadError("cannot read CurseForge configuration: %s" % exc, stage="dependency_get") from exc
        for number, raw in enumerate(lines, 1):
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                raise ValidationError("expected NAME=VALUE", path="%s:%d" % (source, number))
            name, value = line.split("=", 1)
            name, value = name.strip(), value.strip()
            if name not in CONFIG_KEYS:
                raise ValidationError("unknown CurseForge configuration field", path="%s:%d" % (source, number))
            if name in values:
                raise ValidationError("duplicate CurseForge configuration field", path="%s:%d" % (source, number))
            values[name] = value
    for name in CONFIG_KEYS:
        environment_value = os.environ.get(name, "").strip()
        if environment_value:
            values[name] = environment_value
    return values


def _required(config: Mapping[str, str], *names: str) -> None:
    missing = [name for name in names if not config.get(name)]
    if missing:
        raise FuploadError(
            "missing CurseForge configuration field(s): %s" % ", ".join(missing),
            kind="authentication_error", stage="dependency_get",
            details={"config_path": str(config_path()), "missing": missing},
        )


def _author_id(value: Any) -> int:
    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise ValidationError("author ID must be a positive integer", path="--author-id") from exc
    if result <= 0:
        raise ValidationError("author ID must be a positive integer", path="--author-id")
    return result


class CurseForge:
    def __init__(self, config: Optional[Mapping[str, str]] = None) -> None:
        self.config = dict(config) if config is not None else load_config()

    def execute_read(self, resource: str, action: str, args: Any) -> Any:
        if resource == "session" and action == "doctor":
            return self.doctor()
        if resource == "project" and action == "list":
            return self.project_list(getattr(args, "author_id", None))
        if resource == "plugin" and action == "game-versions":
            return self.game_versions()
        raise ValidationError("unsupported CurseForge read operation")

    def execute_write(self, resource: str, action: str, doc: Mapping[str, Any]) -> Any:
        if resource == "plugin" and action == "upload":
            return self.upload(doc)
        raise ValidationError("unsupported CurseForge write operation")

    def doctor(self) -> Dict[str, Any]:
        fields = [{"name": name, "present": bool(self.config.get(name))} for name in CONFIG_KEYS]
        return {
            "config_path": str(config_path()),
            "fields": fields,
            "ready": all(field["present"] for field in fields),
        }

    def project_list(self, author_id: Optional[int]) -> Dict[str, Any]:
        _required(self.config, "CURSEFORGE_API_KEY")
        selected = _author_id(author_id if author_id is not None else self.config.get("CURSEFORGE_AUTHOR_ID"))
        query = urllib.parse.urlencode({"gameId": 1, "authorId": selected, "index": 0, "pageSize": 50})
        url = CORE_BASE + "/v1/mods/search?" + query
        payload = json_request(url, headers={"x-api-key": self.config["CURSEFORGE_API_KEY"]})
        if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
            raise FuploadError("CurseForge project response did not contain a data array", kind="platform_data_error", endpoint=url)
        pagination = payload.get("pagination") if isinstance(payload.get("pagination"), dict) else {}
        projects = []
        for item in payload["data"]:
            if not isinstance(item, dict):
                raise FuploadError("CurseForge project response contained a non-object item", kind="platform_data_error", endpoint=url)
            projects.append({
                "id": item.get("id"),
                "name": item.get("name"),
                "slug": item.get("slug"),
                "status": item.get("status"),
                "dateCreated": item.get("dateCreated"),
                "dateModified": item.get("dateModified"),
            })
        total_count = pagination.get("totalCount")
        if isinstance(total_count, bool) or not isinstance(total_count, int) or total_count < 0:
            total_count = len(projects)
        return {
            "author_id": selected,
            "game_id": 1,
            "total_count": total_count,
            "projects": projects,
            "pagination": pagination,
        }

    def game_versions(self) -> Any:
        _required(self.config, "CURSEFORGE_UPLOAD_TOKEN")
        return json_request(
            UPLOAD_BASE + "/api/game/versions",
            headers={"X-Api-Token": self.config["CURSEFORGE_UPLOAD_TOKEN"]},
        )

    def upload(self, doc: Mapping[str, Any]) -> Dict[str, Any]:
        _required(self.config, "CURSEFORGE_UPLOAD_TOKEN")
        project_id = int(doc["project_id"])
        file_path = str(doc["file"])
        field_names = {
            "changelog": "changelog",
            "changelog_type": "changelogType",
            "display_name": "displayName",
            "game_versions": "gameVersions",
            "game_version_names": "gameVersionNames",
            "release_type": "releaseType",
            "parent_file_id": "parentFileID",
            "is_marked_for_manual_release": "isMarkedForManualRelease",
        }
        metadata = {wire: doc[name] for name, wire in field_names.items() if name in doc}
        if "relations" in doc:
            projects = []
            for item in doc["relations"]["projects"]:
                relation = {"slug": item["slug"], "type": item["type"]}
                if "project_id" in item:
                    relation["projectID"] = item["project_id"]
                projects.append(relation)
            metadata["relations"] = {"projects": projects}
        url = UPLOAD_BASE + "/api/projects/%d/upload-file" % project_id
        response = multipart_request(
            url, file_path, file_field="file",
            fields={"metadata": json.dumps(metadata, ensure_ascii=False, separators=(",", ":"))},
            headers={"X-Api-Token": self.config["CURSEFORGE_UPLOAD_TOKEN"]},
        )
        if (
            not isinstance(response, dict)
            or isinstance(response.get("id"), bool)
            or not isinstance(response.get("id"), int)
            or response["id"] <= 0
        ):
            raise FuploadError(
                "CurseForge upload response did not contain a positive integer id",
                kind="platform_data_error", endpoint=url,
            )
        return {
            "file_id": response["id"],
            "project_id": project_id,
            "archive": Path(file_path).name,
            "status": "uploaded",
        }
