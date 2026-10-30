"""Selected local ModUs backup generation and guarded cloud backup operations.

Only selected local files enter an artifact. Cloud writes follow the main
client's signature -> PUT -> storage registration -> backup registration chain.
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import tempfile
import urllib.parse
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from .errors import FuploadError, ValidationError

SECTIONS = ("addons", "modifiedAddons", "unknownAddons", "fonts", "materials", "wtf")


def scan(doc: Mapping[str, Any], server_type: int) -> dict[str, Any]:
    root = Path(str(doc["game_root"])).absolute()
    if not (root / "Interface" / "AddOns").is_dir():
        raise ValidationError("game_root must contain Interface/AddOns", path="game_root")
    def names(parent: Path) -> list[str]:
        return sorted(item.name for item in parent.iterdir() if not item.is_symlink() and not (hasattr(item, "is_junction") and item.is_junction())) if parent.is_dir() else []
    roles = []
    accounts = root / "WTF" / "Account"
    for account in names(accounts):
        for server in names(accounts / account):
            if server == "SavedVariables":
                continue
            for role in names(accounts / account / server):
                if (accounts / account / server / role).is_dir():
                    roles.append({"account": account, "server": server, "role": role})
    return {"server_type": server_type, "game_root": str(root), "addon_names": names(root / "Interface" / "AddOns"),
            "font_names": [name for name in names(root / "Fonts") if (root / "Fonts" / name).is_file()],
            "material_names": [name for name in names(root / "Interface") if name.casefold() != "addons"], "roles": roles}


def rows(value: Any) -> list[Mapping[str, Any]]:
    if isinstance(value, Mapping):
        for key in ("rows", "list", "items", "records", "data"):
            if key in value:
                return rows(value[key])
        if "id" in value:
            return [value]
    if isinstance(value, list) and all(isinstance(item, Mapping) for item in value):
        return value
    raise FuploadError("ModUs returned an unrecognized collection", kind="platform_data_error")


def positive(value: Any, field: str = "backup_id") -> int:
    if isinstance(value, bool) or not re.fullmatch(r"[1-9][0-9]*", str(value)):
        raise ValidationError("%s must be a positive integer" % field, path=field)
    return int(value)


def _share_id(item: Mapping[str, Any]) -> str:
    value = item.get("id", item.get("shareId"))
    if type(value) is int and value > 0:
        return str(value)
    if isinstance(value, str) and value.strip() and len(value) <= 256 and not any(c in value for c in "\r\n\0"):
        return value
    raise FuploadError("Configuration share has an invalid identifier", kind="backup_protection_unknown")


def references(client: Any, server_type: int) -> dict[int, list[dict[str, Any]]]:
    """Read every owned share, then its complete detail; incomplete means unknown."""
    output: dict[int, list[dict[str, Any]]] = {}
    seen: set[str] = set()
    expected = None
    page = 1
    while page <= 10000:
        payload = client._request("POST", "system/user/share/list", {
            "mine": True, "server": server_type, "shareType": 0,
            "pageNum": page, "pageSize": 100, "platform": 0,
        }, headers={"X-Server-Type": str(server_type)})
        collection = rows(payload)
        envelope = payload
        total = None
        for _ in range(3):
            if not isinstance(envelope, Mapping):
                break
            if "total" in envelope:
                total = envelope["total"]
                break
            envelope = envelope.get("data")
        if isinstance(total, bool) or not isinstance(total, int) or total < 0:
            raise FuploadError("Cannot establish complete configuration-share pagination", kind="backup_protection_unknown")
        if expected is not None and expected != total:
            raise FuploadError("Configuration shares changed during protection check", kind="backup_protection_unknown")
        expected = total
        ids = []
        for item in collection:
            share_id = _share_id(item)
            if share_id in seen:
                raise FuploadError("Incomplete or duplicate configuration-share identifiers", kind="backup_protection_unknown")
            seen.add(share_id)
            ids.append(share_id)
        if len(seen) > total or (not ids and len(seen) < total):
            raise FuploadError("Incomplete configuration-share pagination", kind="backup_protection_unknown")
        if ids:
            details = rows(client.share_detail(ids, server_type=server_type))
            found = set()
            for item in details:
                share_id = _share_id(item)
                if share_id not in ids or share_id in found:
                    raise FuploadError("Configuration-share detail does not match list", kind="backup_protection_unknown")
                found.add(share_id)
                try:
                    backup_id = positive(item.get("backupId", item.get("backup_id")))
                except ValidationError as exc:
                    raise FuploadError("Configuration-share backup association is unknown", kind="backup_protection_unknown") from exc
                output.setdefault(backup_id, []).append({"share_id": share_id, "title": item.get("title", "")})
            if found != set(ids):
                raise FuploadError("Configuration-share detail is incomplete", kind="backup_protection_unknown")
        if len(seen) == total:
            return output
        page += 1
    raise FuploadError("Configuration-share pagination exceeds protection limit", kind="backup_protection_unknown")


def _build_ids() -> tuple[int, ...]:
    from .modus import MODUS_BUILDS
    return tuple(item["id"] for item in MODUS_BUILDS)


def _backup_build(item: Mapping[str, Any]) -> int:
    build = item.get("serverType")
    if type(build) is not int or build not in _build_ids():
        raise FuploadError("Backup Build is missing or invalid; reference protection is unknown", kind="backup_protection_unknown")
    return build


def _all_references(client: Any) -> dict[int, list[dict[str, Any]]]:
    # Backup IDs are global and the backup-list header does not filter rows.
    # A historical cross-Build share must protect its backup as well.
    output: dict[int, list[dict[str, Any]]] = {}
    seen: dict[str, int] = {}
    for build in _build_ids():
        for backup_id, linked in references(client, build).items():
            for item in linked:
                share_id = item["share_id"]
                if share_id in seen:
                    if seen[share_id] != backup_id:
                        raise FuploadError("Configuration-share backup association changed across Builds", kind="backup_protection_unknown")
                    continue
                seen[share_id] = backup_id
                output.setdefault(backup_id, []).append({**item, "checked_server_type": build})
    return output


def summary(item: Mapping[str, Any], linked: list[dict[str, Any]]) -> dict[str, Any]:
    return {"backup_id": positive(item.get("id", item.get("backupId"))),
            "backup_name": item.get("backupName", item.get("name", "")),
            "created_at": item.get("createTime", item.get("createdAt")),
            "protected": bool(linked), "references": linked}


def _time(value: Any, field: str) -> datetime:
    try:
        stamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return stamp.replace(tzinfo=timezone.utc) if stamp.tzinfo is None else stamp
    except (ValueError, TypeError) as exc:
        raise ValidationError("%s must be an ISO 8601 date/time" % field, path=field) from exc


def preview(client: Any, doc: Mapping[str, Any], server_type: int) -> dict[str, Any]:
    selected = doc.get("backup_ids")
    if selected is not None and (not isinstance(selected, list) or not selected):
        raise ValidationError("backup_ids must be a nonempty array", path="backup_ids")
    ids = {positive(value) for value in selected} if selected else None
    if ids is None and not any(doc.get(key) for key in ("name_contains", "name_equals", "created_before", "created_after")):
        raise ValidationError("Select explicit backup_ids or a name/date filter")
    candidates = []
    for item in rows(client.cloud_backups(server_type=server_type)):
        backup_id = positive(item.get("id", item.get("backupId")))
        name = str(item.get("backupName", item.get("name", "")))
        if ids is not None and backup_id not in ids:
            continue
        if doc.get("name_contains") and str(doc["name_contains"]) not in name:
            continue
        if doc.get("name_equals") and str(doc["name_equals"]) != name:
            continue
        if doc.get("created_before") or doc.get("created_after"):
            when = _time(item.get("createTime", item.get("createdAt")), "created_at")
            if doc.get("created_before") and when >= _time(doc["created_before"], "created_before"):
                continue
            if doc.get("created_after") and when <= _time(doc["created_after"], "created_after"):
                continue
        actual = item
        if "serverType" not in actual:
            details = rows(client.cloud_backup_detail(backup_id, server_type=server_type))
            if len(details) != 1 or positive(details[0].get("id", details[0].get("backupId"))) != backup_id:
                raise FuploadError("Backup detail does not identify the preview candidate", kind="backup_protection_unknown")
            actual = {**item, **details[0]}
        build = _backup_build(actual)
        if build != server_type:
            if ids is not None:
                raise ValidationError("Backup belongs to a different Build; select its actual server_type", path="server_type")
            continue
        candidates.append(actual)
    linked = _all_references(client) if candidates else {}
    output = [{**summary(item, linked.get(positive(item.get("id", item.get("backupId"))), [])), "server_type": server_type} for item in candidates]
    return {"server_type": server_type, "items": output, "matched_count": len(output),
            "deletable_ids": [item["backup_id"] for item in output if not item["protected"]],
            "protected_ids": [item["backup_id"] for item in output if item["protected"]],
            "protection_complete": True}


def delete_one(client: Any, backup_id: Any, server_type: int) -> dict[str, Any]:
    backup_id = positive(backup_id)
    detail = rows(client.cloud_backup_detail(backup_id, server_type=server_type))
    if len(detail) != 1 or positive(detail[0].get("id", detail[0].get("backupId"))) != backup_id:
        raise FuploadError("Backup detail does not identify the requested backup", kind="platform_data_error")
    if _backup_build(detail[0]) != server_type:
        raise FuploadError("Backup belongs to a different Build; select its actual server_type", kind="validation_error")
    linked = _all_references(client).get(backup_id, [])
    if linked:
        raise FuploadError("Backup is used by a configuration share and cannot be deleted", kind="backup_in_use",
                           details={"backup_id": backup_id, "references": linked})
    try:
        client._request("DELETE", "system/user/backup/delete/%s" % backup_id,
                        headers={"X-Server-Type": str(server_type)})
    except FuploadError as exc:
        # The mutation is sent once. An interrupted DELETE is never retried.
        if exc.verification_required:
            exc.details.update({"backup_id": backup_id, "mutation_attempts": 1})
        raise
    try:
        remaining = rows(client.cloud_backups(server_type=server_type))
        if any(positive(item.get("id", item.get("backupId"))) == backup_id for item in remaining):
            raise FuploadError("Deleted backup remains in cloud list", verification_required=True)
        try:
            after = client.cloud_backup_detail(backup_id, server_type=server_type)
        except FuploadError as exc:
            missing = exc.http_status == 404 or exc.business_code == 404 or (
                exc.business_code == 500 and str(exc) == "没有备份信息，获取失败"
            )
            if not missing:
                raise
            after = None
        if after not in (None, {}, []):
            raise FuploadError("Deleted backup detail is still present", verification_required=True)
    except FuploadError as exc:
        raise FuploadError("Backup deletion requires readback verification", stage="delete_readback",
                           verification_required=True, details={"backup_id": backup_id, "mutation_attempts": 1}) from exc
    return {"backup_id": backup_id, "deleted": True, "verified": True, "mutation_attempts": 1}


def delete_many(client: Any, doc: Mapping[str, Any], server_type: int) -> dict[str, Any]:
    selected = doc.get("backup_ids")
    if doc.get("confirm_delete") is not True:
        raise ValidationError("confirm_delete must be true", path="confirm_delete")
    if not isinstance(selected, list) or not selected:
        raise ValidationError("backup_ids must be a nonempty array", path="backup_ids")
    ids = [positive(value) for value in selected]
    if len(ids) != len(set(ids)):
        raise ValidationError("backup_ids must not contain duplicates", path="backup_ids")
    output = []
    for index, backup_id in enumerate(ids):
        try:
            output.append(delete_one(client, backup_id, server_type))
        except FuploadError as exc:
            output.append({"backup_id": backup_id, "deleted": False, "status": "protected" if exc.kind == "backup_in_use" else "failed", "error": exc.as_dict()})
            if exc.kind != "backup_in_use":
                return {"items": output, "completed": False, "unprocessed_ids": ids[index + 1:], "verification_required": exc.verification_required}
    return {"items": output, "completed": True, "unprocessed_ids": [], "verification_required": False}


def _component(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value or value in (".", "..") or re.search(r'[\\/:*?"<>|,\x00-\x1f]', value):
        raise ValidationError("%s must be a single directory/file name" % field, path=field)
    return value


def _is_link(source: Path) -> bool:
    # Python 3.11 has no Path.is_junction; Windows reparse attributes cover it.
    try:
        return source.is_symlink() or bool(getattr(source.lstat(), "st_file_attributes", 0) & 0x400)
    except FileNotFoundError:
        return False


def _files(source: Path) -> list[Path]:
    if _is_link(source):
        raise ValidationError("Backup source cannot contain symbolic links or junctions")
    if source.is_file():
        return [source]
    if not source.is_dir():
        raise ValidationError("Selected backup source does not exist")
    output = []
    for child in sorted(source.iterdir()):
        output.extend(_files(child))
    return output


def generate(doc: Mapping[str, Any], server_type: int) -> dict[str, Any]:
    root = Path(str(doc["game_root"])).absolute()
    if not (root / "Interface" / "AddOns").is_dir():
        raise ValidationError("game_root must identify the selected game branch containing Interface/AddOns", path="game_root")
    destination = Path(str(doc["output_dir"])).absolute()
    if destination.exists():
        raise ValidationError("output_dir must not already exist", path="output_dir")
    if root == destination or root in destination.parents:
        raise ValidationError("output_dir must be outside game_root", path="output_dir")
    name = str(doc.get("backup_name") or "").strip()
    if not name or len(name) > 80:
        raise ValidationError("backup_name must contain 1-80 characters", path="backup_name")
    plans: list[tuple[str, str, Path, str, dict[str, Any]]] = []
    for field, section, parent, prefix in (
        ("addon_names", "unknownAddons", root / "Interface" / "AddOns", "Interface/AddOns"),
        ("font_names", "fonts", root / "Fonts", "Fonts"),
        ("material_names", "materials", root / "Interface", "Interface"),
    ):
        values = doc.get(field, [])
        if not isinstance(values, list) or any(not isinstance(value, str) for value in values) or len(values) != len({value.casefold() for value in values}):
            raise ValidationError("%s must be an array of unique names" % field, path=field)
        for value in values:
            component = _component(value, field)
            if field == "material_names" and component.casefold() == "addons":
                raise ValidationError("Select addons through addon_names", path=field)
            source = parent / component
            if field == "font_names" and (not source.is_file() or source.suffix.lower() not in (".ttf", ".otf")):
                raise ValidationError("font_names must select .ttf or .otf files", path=field)
            plans.append((section, component, source, prefix + "/" + component, {}))
    accounts: dict[str, list[Mapping[str, Any]]] = {}
    selected_roles = doc.get("roles", [])
    if not isinstance(selected_roles, list):
        raise ValidationError("roles must be an array", path="roles")
    seen_roles = set()
    for role in selected_roles:
        if not isinstance(role, Mapping) or set(role) != {"account", "server", "role"}:
            raise ValidationError("roles require account, server and role names", path="roles")
        account, server, character = (_component(role[key], "roles." + key) for key in ("account", "server", "role"))
        normalized_role = (account.casefold(), server.casefold(), character.casefold())
        if normalized_role in seen_roles:
            raise ValidationError("roles must not contain duplicate selections", path="roles")
        seen_roles.add(normalized_role)
        accounts.setdefault(account, []).append({"server": server, "role": character})
    for account, roles in accounts.items():
        source = root / "WTF" / "Account" / account
        # Only selected roles plus account shared variables are copied, never
        # the full account directory (which would include unselected characters).
        for role in roles:
            relative = "WTF/Account/%s/%s/%s" % (account, role["server"], role["role"])
            plans.append(("wtf", role["role"], root / relative, relative, {"type": "role", "account": account, "server": role["server"]}))
        shared = source / "SavedVariables"
        if shared.is_dir():
            plans.append(("wtf", account + " SavedVariables", shared, "WTF/Account/%s/SavedVariables" % account, {"type": "account-shared", "account": account}))
    if accounts and (root / "WTF" / "Config.wtf").is_file():
        plans.append(("wtf", "Config.wtf", root / "WTF" / "Config.wtf", "WTF/Config.wtf", {"type": "config"}))
    if not plans:
        raise ValidationError("Select at least one addon, font, material or WTF role")
    # Validate every path and enumerate before creating anything.
    copies = []
    for section, item_name, source, relative, meta in plans:
        for ancestor in (source, *source.parents):
            if ancestor == root.parent:
                break
            if _is_link(ancestor):
                raise ValidationError("Backup sources cannot traverse symbolic links or junctions")
        files = _files(source)
        if section == "wtf":
            files = [file for file in files if file.suffix.lower() in (".lua", ".wtf", ".txt") and file.name.lower() != "bigfootsync.lua"]
        copies.append((section, item_name, source, relative, meta, files))
    destination.mkdir(parents=True)
    sections = {key: {"key": key, "title": key, "count": 0, "sizeBytes": 0, "items": []} for key in SECTIONS}
    for section, item_name, source, relative, meta, files in copies:
        size = 0
        for file in files:
            target = destination / relative
            if source.is_dir():
                target /= file.relative_to(source)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(file, target)
            size += target.stat().st_size
        item = {"id": section + ":" + relative, "section": section, "name": item_name, "targetRelativePath": relative,
                "sizeBytes": size, "meta": meta}
        if section == "fonts":
            item["meta"]["md5"] = hashlib.md5((destination / relative).read_bytes()).hexdigest()
        sections[section]["items"].append(item)
    # Group role leaves into the official account/server hierarchy.
    wtf = sections["wtf"]["items"]
    retained = [item for item in wtf if item["meta"].get("type") == "config"]
    for account in accounts:
        leaves = [item for item in wtf if item["meta"].get("account") == account]
        servers = []
        for server in dict.fromkeys(role["server"] for role in accounts[account]):
            children = [item for item in leaves if item["meta"].get("server") == server]
            servers.append({"id": "wtf:server:" + account + ":" + server, "section": "wtf", "name": server,
                            "targetRelativePath": "WTF/Account/" + account + "/" + server,
                            "sizeBytes": sum(item["sizeBytes"] for item in children), "children": children, "meta": {"type": "server"}})
        retained.append({"id": "wtf:account:" + account, "section": "wtf", "name": account,
                         "targetRelativePath": "WTF/Account/" + account,
                         "sizeBytes": sum(item["sizeBytes"] for item in leaves), "children": servers,
                         "meta": {"type": "account"}})
    sections["wtf"]["items"] = retained
    for section in sections.values():
        section["count"] = len(section["items"])
        section["sizeBytes"] = sum(item["sizeBytes"] for item in section["items"])
    now = datetime.now(timezone.utc).isoformat()
    local_id = datetime.now().strftime("%Y%m%d%H%M%S") + "-" + uuid.uuid4().hex[:8]
    manifest = {"schemaVersion": "config-backup.v2", "backupId": local_id, "backupName": name,
                "createdAt": now, "completedAt": now, "storageTargets": ["local"],
                "source": {"origin": "modus", "gameId": server_type}, "sections": list(sections.values()),
                "totals": {key: sections[key]["count"] for key in SECTIONS if key != "wtf"}}
    manifest["totals"].update({"wtfAccounts": len(accounts), "files": sum(section["count"] for section in sections.values()),
                                "sizeBytes": sum(section["sizeBytes"] for section in sections.values())})
    path = destination / "manifest.v2.json"
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"local_backup_id": local_id, "manifest_file": str(path), "output_dir": str(destination), "server_type": server_type,
            "totals": manifest["totals"], "generated": True}


def _local_path(root: Path, relative: Any) -> Path:
    if not isinstance(relative, str) or not relative or "\\" in relative or ":" in relative or relative.startswith("/") or any(part in ("", ".", "..") for part in relative.split("/")):
        raise ValidationError("Invalid manifest targetRelativePath", path="manifest_file")
    path = root.joinpath(*relative.split("/"))
    if not path.resolve().is_relative_to(root.resolve()):
        raise ValidationError("Manifest target escapes backup directory", path="manifest_file")
    for ancestor in (path, *path.parents):
        if ancestor == root.parent:
            break
        if _is_link(ancestor):
            raise ValidationError("Backup cannot contain symbolic links or junctions")
    return path


def _leaves(items: list[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    result = []
    for item in items:
        if item.get("children"):
            result.extend(_leaves(item["children"]))
        else:
            result.append(item)
    return result


def _wtf_upload_plan(root: Path, items: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Bind account/server/role metadata to exact local paths before auth.

    Account common files are part of an account selection, as in the official
    client. Every character directory must instead have a matching role leaf.
    The returned file list is frozen: ZIP creation never walks an account again.
    """
    accounts, extras = [], []
    seen_accounts: set[str] = set()
    seen_extras: set[str] = set()

    def require_path(item: Mapping[str, Any], expected: str) -> Path:
        if item.get("targetRelativePath") != expected:
            raise ValidationError("WTF item path does not match its account/server/role hierarchy", path="manifest_file")
        return _local_path(root, expected)

    def wtf_files(path: Path) -> list[Path]:
        files = _files(path)
        if any(file.suffix.casefold() not in (".lua", ".wtf", ".txt") or file.name.casefold() == "bigfootsync.lua" for file in files):
            raise ValidationError("WTF backup contains files outside the supported configuration formats", path="manifest_file")
        return files

    for item in items:
        kind = item.get("meta", {}).get("type")
        if kind in ("config", "shared-saved-variables"):
            relative = "WTF/Config.wtf" if kind == "config" else "WTF/Account/SavedVariables"
            if kind in seen_extras or item.get("children"):
                raise ValidationError("Duplicate or nested WTF common selection", path="manifest_file")
            seen_extras.add(kind)
            path = require_path(item, relative)
            if kind == "config" and (item.get("name") != "Config.wtf" or not path.is_file()):
                raise ValidationError("WTF config selection must identify Config.wtf", path="manifest_file")
            if kind == "shared-saved-variables" and not path.is_dir():
                raise ValidationError("WTF shared selection must identify a directory", path="manifest_file")
            extras.extend((file, path.name + "/" + file.relative_to(path).as_posix() if path.is_dir() else path.name) for file in wtf_files(path))
            continue
        if kind != "account":
            raise ValidationError("WTF top-level selections must be accounts or explicit common files", path="manifest_file")
        account = _component(item.get("name"), "manifest.account")
        if account.casefold() == "savedvariables" or account.casefold() in seen_accounts or item.get("meta", {}).get("account", account) != account:
            raise ValidationError("Invalid or duplicate WTF account selection", path="manifest_file")
        seen_accounts.add(account.casefold())
        account_path = require_path(item, "WTF/Account/" + account)
        servers = item.get("children", [])
        if not isinstance(servers, list) or not account_path.is_dir():
            raise ValidationError("WTF account must contain an explicit server hierarchy", path="manifest_file")
        selected_roles: set[tuple[str, str]] = set()
        role_names = []
        seen_servers: set[str] = set()
        for server in servers:
            server_name = _component(server.get("name"), "manifest.server")
            server_meta = server.get("meta", {})
            if server_meta.get("type") != "server" or server_name.casefold() == "savedvariables" or server_name.casefold() in seen_servers or server_meta.get("account", account) != account or server_meta.get("server", server_name) != server_name:
                raise ValidationError("Invalid WTF server metadata", path="manifest_file")
            seen_servers.add(server_name.casefold())
            require_path(server, "WTF/Account/" + account + "/" + server_name)
            roles = server.get("children")
            if not isinstance(roles, list):
                raise ValidationError("WTF servers must contain explicit role leaves", path="manifest_file")
            for role in roles:
                role_name = _component(role.get("name"), "manifest.role")
                meta = role.get("meta", {})
                identity = (server_name.casefold(), role_name.casefold())
                if meta.get("type") != "role" or role.get("children") or role_name.casefold() == "savedvariables" or identity in selected_roles or meta.get("account", account) != account or meta.get("server", server_name) != server_name:
                    raise ValidationError("Invalid or inconsistent WTF role metadata", path="manifest_file")
                role_path = require_path(role, "WTF/Account/%s/%s/%s" % (account, server_name, role_name))
                if not role_path.is_dir():
                    raise ValidationError("WTF role selection must identify a character directory", path="manifest_file")
                selected_roles.add(identity)
                role_names.append(server_name + "-" + role_name)
        entries = []
        for file in wtf_files(account_path):
            parts = file.relative_to(account_path).parts
            common = len(parts) == 1 or parts[0].casefold() == "savedvariables"
            server_common = len(parts) >= 2 and parts[0].casefold() in seen_servers and (len(parts) == 2 or parts[1].casefold() == "savedvariables")
            selected_role = len(parts) >= 3 and (parts[0].casefold(), parts[1].casefold()) in selected_roles
            if not common and not server_common and not selected_role:
                raise ValidationError("WTF backup contains an unselected character or server file", path="manifest_file")
            entries.append((file, account + "/" + "/".join(parts)))
        accounts.append({"name": account, "roles": role_names, "entries": entries})
    for account in accounts:
        account["entries"].extend(extras)
    return accounts


def upload(client: Any, doc: Mapping[str, Any], server_type: int) -> dict[str, Any]:
    """Upload through the statically verified main-client protocol, once."""
    manifest_path = Path(str(doc["manifest_file"])).absolute()
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValidationError("manifest_file is not a readable JSON backup manifest", path="manifest_file") from exc
    if not isinstance(manifest, dict) or manifest.get("schemaVersion") != "config-backup.v2":
        raise ValidationError("manifest_file must be a config-backup.v2 manifest", path="manifest_file")
    if not isinstance(manifest.get("source"), Mapping) or manifest["source"].get("gameId") != server_type:
        raise ValidationError("Backup manifest gameId does not match selected server_type", path="server_type")
    if "cloud" in manifest.get("storageTargets", []) or manifest["source"].get("cloudBackupId"):
        raise ValidationError("This local backup is already linked to a cloud backup", path="manifest_file")
    if not isinstance(manifest.get("backupId"), str) or not manifest.get("backupName"):
        raise ValidationError("Backup manifest lacks its local ID or name", path="manifest_file")
    section_rows = manifest.get("sections")
    if not isinstance(section_rows, list) or len(section_rows) != len(SECTIONS) or {item.get("key") for item in section_rows if isinstance(item, Mapping)} != set(SECTIONS):
        raise ValidationError("Backup manifest requires all six sections", path="manifest_file")
    sections = {item["key"]: item.get("items") for item in section_rows}
    root = manifest_path.parent
    state_path = root / ".fupload-cloud-upload.json"
    if state_path.exists():
        raise FuploadError("A previous upload transaction exists; inspect cloud list/detail before starting another upload", kind="upload_recovery_required", verification_required=True)
    # Resolve all local files before the first authenticated request.
    all_paths: dict[str, Path] = {}
    identifiers = set()
    def validate_items(items: Any, section: str, depth: int = 0) -> None:
        if not isinstance(items, list) or depth > 20:
            raise ValidationError("Manifest section items must be finite arrays")
        for item in items:
            if not isinstance(item, Mapping) or item.get("section") != section or not isinstance(item.get("id"), str) or not item["id"] or item["id"] in identifiers or not isinstance(item.get("name"), str):
                raise ValidationError("Invalid or duplicate manifest backup item")
            identifiers.add(item["id"])
            if not isinstance(item.get("meta", {}), Mapping):
                raise ValidationError("Manifest item metadata must be an object")
            if item.get("children") is not None:
                validate_items(item["children"], section, depth + 1)
    for key, items in sections.items():
        validate_items(items, key)
        if key == "addons":
            for item in items:
                positive(item.get("meta", {}).get("projectId"), "manifest.projectId")
        for item in _leaves(items):
            if key == "addons":
                continue
            if key != "wtf":
                name = _component(item.get("name"), "manifest.item.name")
                expected = ("Fonts/" if key == "fonts" else "Interface/" if key == "materials" else "Interface/AddOns/") + name
                if item.get("targetRelativePath") != expected or key == "materials" and name.casefold() == "addons":
                    raise ValidationError("Backup item path does not match its selected category", path="manifest_file")
            path = _local_path(root, item.get("targetRelativePath"))
            _files(path)
            all_paths[item["targetRelativePath"]] = path
            if key == "fonts" and not path.is_file():
                raise ValidationError("Font backup entries must be individual files")
    wtf_plan = _wtf_upload_plan(root, sections["wtf"])
    state: dict[str, Any] = {"local_backup_id": manifest["backupId"], "server_type": server_type,
                             "status": "preparing", "stages": [], "objects": []}
    def save() -> None:
        state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    save()
    stage = "account"
    registration_attempted = False
    try:
        user = client.user_info()
        if isinstance(user, Mapping) and isinstance(user.get("user"), Mapping):
            user = user["user"]
        user_id = positive(user.get("userId", user.get("id")) if isinstance(user, Mapping) else None, "user_id")
        state["status"] = "uploading"
        save()
        def send(path: Path, filename: str, file_type: int, content_type: str = "application/zip") -> dict[str, Any]:
            nonlocal stage
            stage = "signature"
            sign = hashlib.sha256((str(user_id) + filename + "modus_upload_sign_key_2026").encode("utf-8")).hexdigest()
            try:
                signature = client._request("POST", "game/data/file/getSignature?" + urllib.parse.urlencode({"fileName": filename, "fileType": file_type, "sign": sign}))
            except FuploadError as exc:
                raise FuploadError("ModUs backup signature request failed", stage=stage,
                                   endpoint=client._url("game/data/file/getSignature"),
                                   http_status=exc.http_status, business_code=exc.business_code) from exc
            signature = signature.get("data", signature) if isinstance(signature, Mapping) else signature
            if not isinstance(signature, Mapping) or not isinstance(signature.get("signedUrl"), str) or not signature["signedUrl"].startswith("https://") or not isinstance(signature.get("key"), str) or not signature["key"] or any(marker in signature["key"] for marker in ("://", "?", "#")):
                raise FuploadError("ModUs did not return an upload signature and object key", kind="platform_data_error", stage=stage)
            stage = "binary_upload"
            try:
                sent = client.upload_zip(signature["signedUrl"], str(path), content_type=content_type)
            except FuploadError as exc:
                raise FuploadError("ModUs backup binary upload failed", stage=stage,
                                   http_status=exc.http_status, verification_required=True) from exc
            digest = sent.get("etag") or hashlib.md5(path.read_bytes()).hexdigest()
            record = {"fileType": file_type, "cosStoreUrl": signature["key"], "originalFileName": filename,
                      "fileName": filename, "fileSize": path.stat().st_size, "md5": digest}
            state["objects"].append({"key": signature["key"], "bytes": record["fileSize"], "md5": digest})
            save()
            stage = "storage_registration"
            client._request("POST", "game/data/file/upload/data/storage", record)
            state["stages"].append({"stage": "storage_registration", "file_type": file_type, "completed": True})
            save()
            return {"cosPath": signature["key"], "md5": digest, "size": record["fileSize"], "layoutVersion": 1}

        def archive(temp: Path, items: list[Mapping[str, Any]], filename: str, file_type: int, extras: list[Path] | None = None) -> dict[str, Any] | None:
            if not items:
                return None
            paths = [all_paths[item["targetRelativePath"]] for item in _leaves(items)]
            paths.extend(extras or [])
            return archive_paths(temp, paths, filename, file_type)

        def archive_paths(temp: Path, paths: list[Path], filename: str, file_type: int) -> dict[str, Any]:
            entries = []
            for source in paths:
                entries.extend((file, source.name + "/" + file.relative_to(source).as_posix() if source.is_dir() else source.name) for file in _files(source))
            return archive_entries(temp, entries, filename, file_type)

        def archive_entries(temp: Path, entries: list[tuple[Path, str]], filename: str, file_type: int) -> dict[str, Any]:
            path = temp / filename
            names: set[str] = set()
            with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as handle:
                for file, name in entries:
                    _local_path(root, file.relative_to(root).as_posix())
                    if name.casefold() in names:
                        raise ValidationError("Backup archive contains duplicate relative paths")
                    names.add(name.casefold())
                    handle.write(file, name)
            return send(path, filename, file_type)

        with tempfile.TemporaryDirectory(prefix="fupload-modus-backup-") as temporary:
            temp = Path(temporary)
            artifacts = {}
            for key, prefix, file_type in (("modifiedAddons", "modified_addons", 8), ("unknownAddons", "unknown_addons", 9), ("materials", "materials", 4)):
                artifacts[key] = archive(temp, sections[key], prefix + "_" + uuid.uuid4().hex + ".zip", file_type)
            fonts = []
            for item in sections["fonts"]:
                path = all_paths[item["targetRelativePath"]]
                digest = hashlib.md5(path.read_bytes()).hexdigest()
                fonts.append({"name": item["name"], "md5": digest, "size": path.stat().st_size})
            if fonts:
                stage = "font_lookup"
                existence = client._request("POST", "game/data/file/upload/check/font", {"fontMd5": [item["md5"] for item in fonts]})
                existence = existence.get("data", existence) if isinstance(existence, Mapping) else existence
                if not isinstance(existence, Mapping) or not isinstance(existence.get("notExist"), list):
                    raise FuploadError("Font existence response is incomplete", kind="platform_data_error")
                missing = set(existence["notExist"])
                if not missing.issubset({item["md5"] for item in fonts}):
                    raise FuploadError("Font existence response contains unknown hashes", kind="platform_data_error")
                for item, metadata in zip(sections["fonts"], fonts):
                    if metadata["md5"] in missing:
                        send(all_paths[item["targetRelativePath"]], metadata["md5"], 3, "application/octet-stream")
            accounts = []
            for account in wtf_plan:
                artifact = archive_entries(temp, account["entries"], "wtf_" + uuid.uuid4().hex + ".zip", 7)
                accounts.append({"name": account["name"], **artifact, "roles": account["roles"]})
            upload_manifest = json.loads(json.dumps(manifest))
            upload_manifest["storageTargets"] = list(dict.fromkeys([*upload_manifest.get("storageTargets", ["local"]), "cloud"]))
            # Official hO strips source paths recursively before uploading.
            def sanitize(value: Any) -> None:
                if isinstance(value, dict):
                    for key in ("sourcePath", "gamePath", "gameRoot", "backupPath"):
                        value.pop(key, None)
                    for child in value.values():
                        sanitize(child)
                elif isinstance(value, list):
                    for child in value:
                        sanitize(child)
            sanitize(upload_manifest)
            local_manifest = temp / "manifest.v2.json"
            local_manifest.write_text(json.dumps(upload_manifest, ensure_ascii=False, indent=2), encoding="utf-8")
            manifest_object = send(local_manifest, manifest["backupId"] + "_manifest.v2.json", 2, "application/json")
            known = sections["addons"]
            known_info = {"list": [item["name"] for item in known],
                          "displayList": [{"name": item["name"], "icon": item.get("meta", {}).get("icon", ""), "author": item.get("meta", {}).get("author", ""), "isLocked": bool(item.get("meta", {}).get("isLocked"))} for item in known],
                          "fileIds": ",".join(str(item.get("meta", {}).get("fileId", "")) if item.get("meta", {}).get("isLocked") else "" for item in known),
                          "projectIds": ",".join(str(item.get("meta", {}).get("projectId", "")) for item in known)}
            known_info["projectids"] = known_info["projectIds"]
            def info(key: str) -> str:
                artifact = artifacts[key] or {}
                return json.dumps({"list": [item["name"] for item in sections[key]], "zipPath": artifact.get("cosPath", ""), "md5": artifact.get("md5", ""), "size": artifact.get("size", 0), "layoutVersion": 1}, ensure_ascii=False)
            body = {"serverType": server_type, "backupName": manifest["backupName"], "knownAddons": json.dumps(known_info, ensure_ascii=False),
                    "knownAddonsNum": len(known), "modifiedNum": len(sections["modifiedAddons"]), "modifiedCosInfo": info("modifiedAddons"),
                    "unknownAddons": info("unknownAddons"), "unknownAddonsNum": len(sections["unknownAddons"]),
                    "materialNum": len(sections["materials"]), "materialCosInfo": info("materials"), "wtfNum": len(accounts),
                    "wtfAccounts": json.dumps(accounts, ensure_ascii=False), "fonts": json.dumps(fonts, ensure_ascii=False),
                    "fontNum": len(fonts), "manifestPath": manifest_object["cosPath"]}
            stage = "backup_registration"
            before_ids = {positive(item.get("id", item.get("backupId"))) for item in rows(client.cloud_backups(server_type=server_type))}
            registration_attempted = True
            result = client._request("POST", "system/user/backup/create", body, headers={"X-Server-Type": str(server_type)})
            if isinstance(result, Mapping) and result.get("code", 200) != 200:
                raise FuploadError("ModUs backup registration was rejected", business_code=result.get("code"), kind="platform_error")
            result = result.get("data", result) if isinstance(result, Mapping) else result
            if isinstance(result, Mapping):
                result = result.get("id", result.get("backupId"))
            if result is None:
                # Some server versions acknowledge creation without returning an
                # ID. Resolve only our new immutable manifest object, once.
                candidates = []
                for item in rows(client.cloud_backups(server_type=server_type)):
                    ident = positive(item.get("id", item.get("backupId")))
                    if ident in before_ids:
                        continue
                    detail = rows(client.cloud_backup_detail(ident, server_type=server_type))
                    if any(row.get("manifestPath") == body["manifestPath"] and row.get("backupName") == body["backupName"] for row in detail):
                        candidates.append(ident)
                if len(candidates) != 1:
                    raise FuploadError("Created cloud backup could not be resolved uniquely", verification_required=True)
                cloud_id = candidates[0]
            else:
                cloud_id = positive(result)
            state["cloud_backup_id"] = cloud_id
            state["stages"].append({"stage": stage, "completed": True})
            save()
            stage = "backup_readback"
            detail = rows(client.cloud_backup_detail(cloud_id, server_type=server_type))
            listing = rows(client.cloud_backups(server_type=server_type))
            if not any(positive(item.get("id", item.get("backupId"))) == cloud_id and item.get("backupName", item.get("name")) == manifest["backupName"] for item in detail) or not any(positive(item.get("id", item.get("backupId"))) == cloud_id for item in listing):
                raise FuploadError("Cloud backup upload was not confirmed by detail and list", verification_required=True)
            upload_manifest["source"]["cloudBackupId"] = str(cloud_id)
            stage = "local_link"
            manifest_path.write_text(json.dumps(upload_manifest, ensure_ascii=False, indent=2), encoding="utf-8")
            state["status"] = "complete"
            save()
            return {"local_backup_id": manifest["backupId"], "backup_id": cloud_id, "backup_name": manifest["backupName"],
                    "manifest_file": str(manifest_path), "uploaded": True, "verified": True, "transaction_file": str(state_path),
                    "stages": state["stages"]}
    except (FuploadError, OSError, ValueError, KeyError, TypeError) as exc:
        wrapped = exc if isinstance(exc, FuploadError) else FuploadError("ModUs backup upload failed", stage=stage)
        if registration_attempted:
            wrapped.verification_required = True
        wrapped.stage = stage
        wrapped.details.update({"transaction_file": str(state_path), "local_backup_id": manifest["backupId"],
                                "retained_object_count": len(state["objects"]), **({"backup_id": state["cloud_backup_id"]} if "cloud_backup_id" in state else {})})
        state["status"] = "verification_required" if wrapped.verification_required else "failed"
        state["failed_stage"] = stage
        state["error"] = wrapped.as_dict()
        save()
        raise wrapped
