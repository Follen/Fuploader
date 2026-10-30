"""Selective DD cloud backup bundles and configuration-reference deletion guards.

Protocol: official WowUIInterface backup methods, cloud_backup.pyc, and the
Creator frontend modules 51154/58778. All authenticated work uses one task session.
"""

from __future__ import annotations

import copy
import hashlib
import http.client
import json
import os
import re
import urllib.parse
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Sequence

from .errors import FuploadError, ValidationError


BUNDLE_SCHEMA = "fupload.dd.backup-bundle.v1"
GROUPS = ("known_addon", "unknown_addon", "wtf", "material", "font")


def _name(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value or value in (".", "..") or any(c in value for c in "/\\:\0"):
        raise ValidationError("expected one file or directory name", path=field)
    return value


def _path(root: Path, *parts: str) -> Path:
    path = root.joinpath(*parts)
    for current in (path, *path.parents):
        if current == root.parent:
            break
        if current.is_symlink() or current.exists() and bool(getattr(current.stat(follow_symlinks=False), "st_file_attributes", 0) & 0x400):
            raise ValidationError("backup source contains a symlink or reparse point", path="$.game_dir")
    resolved = path.resolve()
    if resolved != root and root not in resolved.parents:
        raise ValidationError("backup source escaped its root", path="$.game_dir")
    return path


def _entries(path: Path) -> List[Path]:
    return sorted(path.iterdir(), key=lambda p: p.name.casefold()) if path.is_dir() else []


def _result(payload: Any) -> Any:
    if isinstance(payload, dict) and "code" in payload and payload["code"] != 0:
        raise FuploadError("DD cloud backup request failed", kind="platform_error", business_code=payload["code"])
    return payload.get("result") if isinstance(payload, dict) else None


def _rows(payload: Any) -> List[Dict[str, Any]]:
    value = _result(payload)
    if isinstance(value, dict):
        value = next((value[k] for k in ("items", "list", "data_list", "shares") if isinstance(value.get(k), list)), None)
    if not isinstance(value, list) or any(not isinstance(row, dict) for row in value):
        raise FuploadError("DD backup or author list was malformed", kind="platform_data_error", stage="dependency_get")
    return value


def _positive(value: Any, path: str) -> int:
    if type(value) is not int or value <= 0:
        raise ValidationError("expected a positive integer", path=path)
    return value


def scan_backup(game_dir: str) -> Dict[str, Any]:
    root = Path(game_dir).resolve()
    if not root.is_dir():
        raise ValidationError("game directory does not exist", path="$.game_dir")
    accounts = []
    account_root = root / "WTF" / "Account"
    if account_root.exists():
        _path(root, "WTF", "Account")
    for account in _entries(account_root):
        _path(root, "WTF", "Account", account.name)
        if not account.is_dir():
            continue
        roles = []
        for server in _entries(account):
            _path(root, "WTF", "Account", account.name, server.name)
            if server.is_dir() and server.name.casefold() != "savedvariables":
                for role in _entries(server):
                    _path(root, "WTF", "Account", account.name, server.name, role.name)
                    if role.is_dir() and role.name.casefold() != "savedvariables":
                        roles.append({"server": server.name, "name": role.name})
        accounts.append({"account": account.name, "roles": roles, "has_common": any(p.is_file() or p.name.casefold() == "savedvariables" for p in _entries(account))})
    addons = []
    for addon in _entries(root / "Interface" / "AddOns"):
        _path(root, "Interface", "AddOns", addon.name)
        if addon.is_dir():
            addons.append({"name": addon.name})
    materials = []
    for material in _entries(root / "Interface"):
        _path(root, "Interface", material.name)
        if material.name.casefold() != "addons" and (material.is_dir() or material.suffix.casefold() in {".blp", ".tga", ".dds", ".png", ".jpg", ".jpeg", ".bmp", ".tex"}):
            materials.append({"name": material.name})
    fonts = []
    for font in _entries(root / "Fonts"):
        _path(root, "Fonts", font.name)
        if font.is_file() and font.suffix.casefold() == ".ttf":
            fonts.append({"name": font.name, "size": font.stat().st_size})
    return {"game_dir": str(root), "addon_names": addons, "unknown_addons": addons, "materials": materials, "fonts": fonts, "wtf_accounts": accounts, "wtf_root_files": [p.name for p in _entries(root / "WTF") if p.is_file()]}


def _zip(root: Path, sources: Sequence[Path], base: Path, destination: Path) -> Dict[str, Any]:
    count = 0
    with zipfile.ZipFile(destination, "x", compression=zipfile.ZIP_DEFLATED) as archive:
        seen = set()
        for source in sources:
            for path in ([source] if source.is_file() else sorted(source.rglob("*"))):
                _path(root, *path.relative_to(root).parts)
                if not path.is_file():
                    continue
                member = path.relative_to(base).as_posix()
                if member not in seen:
                    archive.write(path, member)
                    seen.add(member)
                    count += 1
    data = destination.read_bytes()
    return {"file": destination.name, "size": len(data), "md5": hashlib.md5(data, usedforsecurity=False).hexdigest(), "sha256": hashlib.sha256(data).hexdigest(), "files": count}


def generate_backup(doc: Mapping[str, Any]) -> Dict[str, Any]:
    root = Path(doc["game_dir"]).resolve()
    available = scan_backup(str(root))
    game_type = _positive(doc.get("game_type"), "$.game_type")
    output = Path(doc["output_dir"]).resolve()
    if output == root or root in output.parents:
        raise ValidationError("output directory must be outside the game directory", path="$.output_dir")
    if output.exists() and (not output.is_dir() or any(output.iterdir())):
        raise ValidationError("output directory must be empty", path="$.output_dir")
    selections = {}
    for field in ("addon_names", "unknown_addons", "materials", "fonts"):
        values = doc.get(field, [])
        if not isinstance(values, list):
            raise ValidationError("expected an array", path="$." + field)
        values = [_name(value, "$." + field) for value in values]
        if len(values) != len(set(values)) or set(values) - {r["name"] for r in available[field]}:
            raise ValidationError("selection contains duplicate or unavailable items", path="$." + field)
        selections[field] = values
    if set(selections["addon_names"]) & set(selections["unknown_addons"]):
        raise ValidationError("addon folders cannot be in both upload groups", path="$.unknown_addons")
    if "include_wtf_root" in doc and type(doc["include_wtf_root"]) is not bool:
        raise ValidationError("expected a boolean", path="$.include_wtf_root")
    wtf_sources = [p for p in _entries(root / "WTF") if p.is_file()] if doc.get("include_wtf_root") else []
    choices = doc.get("wtf_accounts", [])
    if not isinstance(choices, list):
        raise ValidationError("expected an array", path="$.wtf_accounts")
    account_metadata = []
    seen = set()
    for choice in choices:
        if not isinstance(choice, dict) or set(choice) != {"account", "include_common", "roles"} or type(choice["include_common"]) is not bool or not isinstance(choice["roles"], list):
            raise ValidationError("account requires account, include_common, and roles only", path="$.wtf_accounts")
        name = _name(choice["account"], "$.wtf_accounts.account")
        option = next((a for a in available["wtf_accounts"] if a["account"] == name), None)
        if not option or name in seen:
            raise ValidationError("duplicate or unavailable WTF account", path="$.wtf_accounts.account")
        seen.add(name)
        account = _path(root, "WTF", "Account", name)
        common = [p for p in _entries(account) if p.is_file() or p.name.casefold() == "savedvariables"] if choice["include_common"] else []
        wtf_sources.extend(common)
        servers = []
        role_seen = set()
        for role in choice["roles"]:
            if not isinstance(role, dict) or set(role) != {"server", "name"}:
                raise ValidationError("role requires server and name only", path="$.wtf_accounts.roles")
            server, role_name = _name(role["server"], "$.wtf_accounts.roles.server"), _name(role["name"], "$.wtf_accounts.roles.name")
            if role not in option["roles"] or (server, role_name) in role_seen:
                raise ValidationError("duplicate or unavailable WTF role", path="$.wtf_accounts.roles")
            role_seen.add((server, role_name))
            wtf_sources.append(_path(root, "WTF", "Account", name, server, role_name))
            row = next((s for s in servers if s["name"] == server), None)
            if row is None:
                row = {"name": server, "items": []}
                servers.append(row)
                if choice["include_common"]:
                    wtf_sources.extend(p for p in _entries(account / server) if p.is_file() or p.name.casefold() == "savedvariables")
            row["items"].append(role_name)
        if not common and not role_seen:
            raise ValidationError("WTF account selection contains no files or roles", path="$.wtf_accounts")
        account_metadata.append({"name": name, "servers": servers, "wa_list": []})
    if not any((*selections.values(), wtf_sources)):
        raise ValidationError("select at least one backup component", path="$")
    output.mkdir(parents=True, exist_ok=True)
    manifest = {"game_type": game_type}
    for group in GROUPS:
        manifest[group] = {"md5": "", "size": 0, "accounts" if group == "wtf" else "items": []}
    manifest["known_addon"]["items"] = [{"name": name, "modified": True, "dirs": [name]} for name in selections["addon_names"]]
    manifest["unknown_addon"]["items"] = selections["unknown_addons"]
    manifest["wtf"]["accounts"] = account_metadata
    manifest["material"]["items"] = [{"name": name, "desc": ""} for name in selections["materials"]]
    manifest["font"]["items"] = selections["fonts"]
    artifacts = []
    for group, names, base in (
        ("known_addon", selections["addon_names"], root / "Interface" / "AddOns"),
        ("unknown_addon", selections["unknown_addons"], root / "Interface" / "AddOns"),
        ("material", selections["materials"], root / "Interface"),
        ("font", selections["fonts"], root / "Fonts"),
    ):
        if names:
            sources = [_path(root, *base.relative_to(root).parts, name) for name in names]
            artifact = _zip(root, sources, root if group == "font" else base, output / (group + ".zip"))
            artifacts.append(dict(artifact, group=group))
            manifest[group].update({"md5": artifact["md5"], "size": artifact["size"]})
    if wtf_sources:
        artifact = _zip(root, wtf_sources, root, output / "wtf.zip")
        artifacts.append(dict(artifact, group="wtf"))
        manifest["wtf"].update({"md5": artifact["md5"], "size": artifact["size"]})
    bundle = {"schema": BUNDLE_SCHEMA, "manifest": manifest, "artifacts": artifacts,
              "selection": {"include_wtf_root": bool(doc.get("include_wtf_root", False)),
                            "wtf_accounts": copy.deepcopy(choices)}}
    bundle_file = output / "backup-bundle.json"
    bundle_file.write_text(json.dumps(bundle, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"bundle_file": str(bundle_file), "game_type": game_type, "archives": artifacts, "wtf_accounts": len(account_metadata)}


def _wtf_selection(bundle: Mapping[str, Any], manifest: Mapping[str, Any]) -> tuple[bool, Dict[str, Any]]:
    """Bind local inclusion flags to the native role tree, without adding wire keys."""
    selection = bundle.get("selection")
    error_path = "$.bundle_file.selection"
    if (not isinstance(selection, dict) or set(selection) != {"include_wtf_root", "wtf_accounts"}
            or type(selection["include_wtf_root"]) is not bool or not isinstance(selection["wtf_accounts"], list)):
        raise ValidationError("backup bundle requires its explicit local WTF selection; regenerate legacy bundles", path=error_path)
    accounts = {}
    account_names = set()
    for row in selection["wtf_accounts"]:
        if (not isinstance(row, dict) or set(row) != {"account", "include_common", "roles"}
                or type(row["include_common"]) is not bool or not isinstance(row["roles"], list)):
            raise ValidationError("invalid local WTF account selection", path=error_path)
        account = _name(row["account"], error_path)
        if account.casefold() in account_names:
            raise ValidationError("duplicate local WTF account selection", path=error_path)
        account_names.add(account.casefold())
        roles, seen, server_names = {}, set(), {}
        for role in row["roles"]:
            if not isinstance(role, dict) or set(role) != {"server", "name"}:
                raise ValidationError("invalid local WTF role selection", path=error_path)
            server, name = _name(role["server"], error_path), _name(role["name"], error_path)
            if server.casefold() == "savedvariables" or name.casefold() == "savedvariables":
                raise ValidationError("shared settings cannot be declared as a WTF role", path=error_path)
            key = server.casefold(), name.casefold()
            if key in seen or server_names.get(server.casefold(), server) != server:
                raise ValidationError("duplicate or ambiguous local WTF role selection", path=error_path)
            server_names[server.casefold()] = server
            seen.add(key)
            roles.setdefault(server, set()).add(name)
        if not row["include_common"] and not roles:
            raise ValidationError("local WTF account selects neither common files nor roles", path=error_path)
        accounts[account] = {"include_common": row["include_common"], "roles": roles}
    wire_accounts = {}
    seen_accounts = set()
    for row in manifest["wtf"]["accounts"]:
        if not isinstance(row, dict) or set(row) != {"name", "servers", "wa_list"} or not isinstance(row["servers"], list) or not isinstance(row["wa_list"], list):
            raise ValidationError("invalid native WTF account metadata", path=error_path)
        account = _name(row["name"], error_path)
        if account.casefold() in seen_accounts:
            raise ValidationError("duplicate native WTF account metadata", path=error_path)
        seen_accounts.add(account.casefold())
        servers, seen_servers = {}, set()
        for server in row["servers"]:
            if not isinstance(server, dict) or set(server) != {"name", "items"} or not isinstance(server["items"], list):
                raise ValidationError("invalid native WTF server metadata", path=error_path)
            name = _name(server["name"], error_path)
            names = [_name(role, error_path) for role in server["items"]]
            if name.casefold() in seen_servers or len({r.casefold() for r in names}) != len(names) or not names:
                raise ValidationError("duplicate or empty native WTF server metadata", path=error_path)
            seen_servers.add(name.casefold())
            servers[name] = set(names)
        wire_accounts[account] = servers
    if wire_accounts != {name: row["roles"] for name, row in accounts.items()}:
        raise ValidationError("local WTF selection does not match native account/server/role metadata", path=error_path)
    return selection["include_wtf_root"], accounts


def _zip_parts(member: zipfile.ZipInfo) -> List[str]:
    name = member.filename
    stripped = name[:-1] if member.is_dir() else name
    parts = stripped.split("/")
    mode = (member.external_attr >> 16) & 0o170000
    if ("\\" in name or name.startswith("/") or not parts or mode not in {0, 0o100000, 0o040000}
            or any(not part or part in {".", ".."} or part.endswith((".", " "))
                   or any(ord(c) < 32 or c in ':<>"|?*\x7f' for c in part)
                   or re.fullmatch(r"(?:con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\..*)?", part, re.IGNORECASE)
                   for part in parts)):
        raise ValidationError("backup ZIP contains unsafe Windows paths or links", path="$.bundle_file.artifacts")
    return parts


def _selected_wtf_member(parts: List[str], include_root: bool, accounts: Mapping[str, Any]) -> bool:
    if len(parts) == 2 and parts[0] == "WTF":
        return include_root and parts[1].casefold() != "account"
    if len(parts) < 4 or parts[:2] != ["WTF", "Account"] or parts[2] not in accounts:
        return False
    account = accounts[parts[2]]
    servers, common = account["roles"], account["include_common"]
    if len(parts) == 4:
        return common and parts[3].casefold() != "savedvariables" and parts[3] not in servers
    if parts[3].casefold() == "savedvariables":
        return common
    if parts[3] not in servers:
        return False
    if len(parts) == 5:
        return common and parts[4].casefold() != "savedvariables" and parts[4] not in servers[parts[3]]
    return ((common and parts[4].casefold() == "savedvariables")
            or parts[4] in servers[parts[3]])


def _selected_wtf_directory(parts: List[str], include_root: bool, accounts: Mapping[str, Any]) -> bool:
    if parts == ["WTF"]:
        return include_root or bool(accounts)
    if parts == ["WTF", "Account"]:
        return bool(accounts)
    if parts[:2] == ["WTF", "Account"] and len(parts) >= 3 and parts[2] in accounts:
        if len(parts) == 3:
            return True
        if len(parts) == 4 and parts[3] in accounts[parts[2]]["roles"]:
            return True
    return _selected_wtf_member(parts + ["__selected_directory_probe__"], include_root, accounts)


def _load_bundle(file: str) -> tuple[Dict[str, Any], List[tuple[str, Path]]]:
    path = Path(file).resolve()
    try:
        bundle = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValidationError("backup bundle cannot be read", path="$.bundle_file") from exc
    if not isinstance(bundle, dict) or bundle.get("schema") != BUNDLE_SCHEMA or not isinstance(bundle.get("manifest"), dict) or set(bundle["manifest"]) != {"game_type", *GROUPS}:
        raise ValidationError("unsupported DD backup bundle", path="$.bundle_file")
    manifest = copy.deepcopy(bundle["manifest"])
    _positive(manifest["game_type"], "$.bundle_file.game_type")
    for group in GROUPS:
        item = manifest[group]
        field = "accounts" if group == "wtf" else "items"
        if not isinstance(item, dict) or set(item) != {"md5", "size", field} or not isinstance(item[field], list) or not isinstance(item["md5"], str) or type(item["size"]) is not int or item["size"] < 0:
            raise ValidationError("invalid backup component metadata", path="$.bundle_file.manifest")
    try:
        roots = {
            "known_addon": {name for item in manifest["known_addon"]["items"] for name in item["dirs"]},
            "unknown_addon": set(manifest["unknown_addon"]["items"]),
            "material": {item["name"] for item in manifest["material"]["items"]},
            "font": set(manifest["font"]["items"]),
        }
        for names in roots.values():
            for name in names:
                _name(name, "$.bundle_file.manifest")
    except (KeyError, TypeError) as exc:
        raise ValidationError("invalid backup selection metadata", path="$.bundle_file.manifest") from exc
    include_root, accounts = _wtf_selection(bundle, manifest)
    if not isinstance(bundle.get("artifacts"), list):
        raise ValidationError("backup artifacts must be an array", path="$.bundle_file.artifacts")
    files = []
    groups = set()
    for artifact in bundle.get("artifacts", []):
        if not isinstance(artifact, dict):
            raise ValidationError("backup artifact must be an object", path="$.bundle_file.artifacts")
        group = artifact.get("group")
        if group not in GROUPS or group in groups:
            raise ValidationError("duplicate or invalid backup component", path="$.bundle_file.artifacts")
        groups.add(group)
        source = _path(path.parent, _name(artifact.get("file"), "$.bundle_file.artifacts.file"))
        if not source.is_file():
            raise ValidationError("backup component is missing", path="$.bundle_file.artifacts")
        data = source.read_bytes()
        md5 = hashlib.md5(data, usedforsecurity=False).hexdigest()
        if len(data) != artifact.get("size") or md5 != artifact.get("md5") or hashlib.sha256(data).hexdigest() != artifact.get("sha256") or manifest[group].get("md5") != md5 or manifest[group].get("size") != len(data):
            raise ValidationError("backup archive changed after generation", path="$.bundle_file.artifacts")
        if not zipfile.is_zipfile(source):
            raise ValidationError("backup component is not a ZIP", path="$.bundle_file.artifacts")
        with zipfile.ZipFile(source) as archive:
            seen_members = set()
            role_files = set()
            for member in archive.infolist():
                parts = _zip_parts(member)
                member_key = "/".join(parts).casefold()
                if member_key in seen_members:
                    raise ValidationError("backup ZIP contains duplicate Windows paths", path="$.bundle_file.artifacts")
                seen_members.add(member_key)
                selected = parts[0] in roots.get(group, set())
                if group == "font":
                    selected = parts == ["Fonts"] if member.is_dir() else len(parts) == 2 and parts[0] == "Fonts" and parts[1] in roots["font"]
                if group == "wtf":
                    selected = (_selected_wtf_directory(parts, include_root, accounts) if member.is_dir()
                                else _selected_wtf_member(parts, include_root, accounts))
                    if not member.is_dir() and len(parts) >= 6 and parts[:2] == ["WTF", "Account"]:
                        role_files.add((parts[2], parts[3], parts[4]))
                if not selected:
                    raise ValidationError("backup ZIP contains an unselected component or WTF role", path="$.bundle_file.artifacts")
            if group == "wtf" and any((name, server, role) not in role_files
                    for name, row in accounts.items() for server, roles in row["roles"].items() for role in roles):
                raise ValidationError("backup ZIP is missing a selected WTF role", path="$.bundle_file.artifacts")
        files.append((group, source))
    if not files:
        raise ValidationError("backup bundle has no components", path="$.bundle_file")
    for group in GROUPS:
        item = manifest[group]
        field = "accounts" if group == "wtf" else "items"
        if not isinstance(item, dict) or set(item) != {"md5", "size", field} or not isinstance(item[field], list):
            raise ValidationError("invalid backup component metadata", path="$.bundle_file.manifest")
        if group not in groups and (item["md5"] != "" or item["size"] != 0 or item[field]):
            raise ValidationError("selected component has no local archive", path="$.bundle_file.artifacts")
    return manifest, files


def _put_backup(path: Path, url: str) -> None:
    parsed = urllib.parse.urlsplit(url)
    # The live DD pre_create endpoint still emits this official S3 host with
    # an HTTP scheme. SigV2 signs the host/path/query and content headers, so
    # retain those bytes while upgrading this observed endpoint to TLS.
    if parsed.scheme.casefold() == "http" and parsed.hostname == "a19-ui-res.s3v2.nie.netease.com" and parsed.port in (None, 80) and not parsed.username and not parsed.password:
        parsed = parsed._replace(scheme="https", netloc=parsed.hostname)
    if parsed.scheme.casefold() != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
        raise FuploadError("DD backup upload URL is not HTTPS", kind="trust_boundary", stage="object_put")
    signed_headers = {}
    for key, value in urllib.parse.parse_qsl(parsed.query, keep_blank_values=True):
        key = key.casefold()
        if key not in {"content-type", "x-amz-acl"}:
            continue
        if key in signed_headers or not value or "\r" in value or "\n" in value:
            raise FuploadError("DD backup upload headers are ambiguous or invalid", kind="trust_boundary", stage="object_put")
        signed_headers[key] = value
    headers = {"x-amz-acl": signed_headers.get("x-amz-acl", "public-read"),
               "Content-Type": signed_headers.get("content-type", "application/x-zip-compressed"),
               "Content-Length": str(path.stat().st_size)}
    connection = http.client.HTTPSConnection(parsed.hostname, parsed.port, timeout=600)
    try:
        target = parsed.path + (("?" + parsed.query) if parsed.query else "")
        with path.open("rb") as data:
            connection.request("PUT", target, body=data, headers=headers)
            response = connection.getresponse()
            response.read()
        if response.status not in (200, 201):
            raise FuploadError("DD backup object upload failed", stage="object_put", http_status=response.status)
    except (OSError, http.client.HTTPException) as exc:
        raise FuploadError("DD backup object upload result is uncertain", stage="object_put", verification_required=True) from exc
    finally:
        connection.close()


def _subset(expected: Any, actual: Any) -> bool:
    if isinstance(expected, dict):
        return isinstance(actual, dict) and all(key in actual and _subset(value, actual[key]) for key, value in expected.items())
    if isinstance(expected, list):
        if not isinstance(actual, list) or len(expected) != len(actual):
            return False
        candidates = list(actual)
        for item in expected:
            match = next((i for i, candidate in enumerate(candidates) if _subset(item, candidate)), None)
            if match is None:
                return False
            candidates.pop(match)
        return True
    return expected == actual or isinstance(expected, (int, str)) and str(expected) == str(actual)


class DDBackupMixin:
    @staticmethod
    def backup_list(session: Any) -> Dict[str, Any]:
        from .dd import safe_backup_list
        payload = session.get("/backup/list", {})
        rows = _rows(payload)
        summaries = safe_backup_list(payload)
        for raw, summary in zip(rows, summaries["items"]):
            summary.update({"sn": summary["reference"], "created_at": raw.get("ctime")})
        return summaries

    @staticmethod
    def backup_get(session: Any, sn: str) -> Dict[str, Any]:
        from .dd import safe_backup_detail
        value = _result(session.get("/backup/detail", {"sn": sn}))
        if not isinstance(value, dict) or str(value.get("sn") or value.get("backup_sn") or "") != sn:
            raise FuploadError("DD backup detail was not found", kind="not_found", stage="dependency_get")
        return dict(safe_backup_detail(value), sn=sn, created_at=value.get("ctime"))

    @staticmethod
    def backup_references(session: Any, backup_rows: Sequence[Mapping[str, Any]]) -> Dict[str, List[Dict[str, str]]]:
        options = _rows(session.get("/game_type/list", {}))
        game_types = {int(row["game_type"]) for row in options if type(row.get("game_type")) is int and row["game_type"] > 0}
        if not game_types:
            raise FuploadError("DD game types are unavailable for reference checks", kind="backup_reference_unknown")
        game_types.update(int(row["game_type"]) for row in backup_rows if row.get("game_type"))
        references: Dict[str, List[Dict[str, str]]] = {}
        for game_type in sorted(game_types):
            seen, total = set(), None
            for page in range(1, 1001):
                payload = session.get("/share/list", {"game_type": game_type, "origin": "created", "page": page, "size": 100, "search_text": "", "sort_type": "mtime"})
                rows = _rows(payload)
                raw = _result(payload)
                count = next((container[key] for container in (raw, payload) if isinstance(container, dict) for key in ("total", "total_count", "count") if key in container), None)
                if type(count) is not int or count < 0 or total is not None and count != total:
                    raise FuploadError("DD configuration reference pagination is incomplete", kind="backup_reference_unknown")
                total = count
                for row in rows:
                    sn = str(row.get("sn") or row.get("share_sn") or "")
                    if not sn or sn in seen:
                        raise FuploadError("DD configuration reference list repeats or omits IDs", kind="backup_reference_unknown")
                    seen.add(sn)
                    backup_sn = row.get("backup_sn")
                    if not isinstance(backup_sn, str) or not backup_sn:
                        detail = _result(session.get("/share/detail", {"sn": sn}))
                        detail_ids = [detail[key] for key in ("sn", "share_sn") if key in detail and detail[key] is not None] if isinstance(detail, dict) else []
                        if not detail_ids or any(not isinstance(value, str) or value != sn for value in detail_ids):
                            raise FuploadError("DD configuration reference detail does not identify the requested configuration", kind="backup_reference_unknown", details={"config_sn": sn})
                        backup_sn = detail.get("backup_sn") if isinstance(detail, dict) else None
                    if not isinstance(backup_sn, str) or not backup_sn:
                        raise FuploadError("DD configuration backup association is unknown", kind="backup_reference_unknown", details={"config_sn": sn})
                    references.setdefault(backup_sn, []).append({"sn": sn, "title": str(row.get("title") or row.get("name") or "")})
                if len(seen) == total:
                    break
                if not rows or len(seen) > total:
                    raise FuploadError("DD configuration reference pagination ended early", kind="backup_reference_unknown")
            else:
                raise FuploadError("DD configuration reference pagination exceeded the limit", kind="backup_reference_unknown")
        return references

    def backup_delete_preview(self, session: Any, backup_ids: Sequence[str]) -> Dict[str, Any]:
        ids = list(backup_ids)
        if not ids or any(not isinstance(sn, str) or not sn for sn in ids) or len(ids) != len(set(ids)):
            raise ValidationError("backup_ids must contain unique nonempty strings", path="$.backup_ids")
        rows = _rows(session.get("/backup/list", {}))
        backups = {str(row.get("sn") or ""): row for row in rows}
        if "" in backups or len(backups) != len(rows):
            raise FuploadError("DD backup list was incomplete", kind="platform_data_error")
        references = self.backup_references(session, rows)
        preview = [{"sn": sn, "name": backups.get(sn, {}).get("name"), "present": sn in backups, "references": references.get(sn, []), "deletable": sn in backups and not references.get(sn), "reason": "configuration_share_reference" if references.get(sn) else "not_found" if sn not in backups else None} for sn in ids]
        return {"items": preview, "deletable": all(row["deletable"] for row in preview), "references_complete": True}

    def backup_preview_selection(self, session: Any, args: Any) -> Dict[str, Any]:
        ids = list(getattr(args, "backup_ids", None) or [])
        filters = {key: getattr(args, key, None) for key in ("name_contains", "name_equals", "created_before", "created_after")}
        if not any(value is not None for value in filters.values()):
            return self.backup_delete_preview(session, ids)
        def bound(value: Any) -> float | None:
            if value is None:
                return None
            try:
                parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
                return (parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed).timestamp()
            except (ValueError, TypeError, OverflowError) as exc:
                raise ValidationError("expected an ISO creation date", path="$.created_before") from exc
        before, after = bound(filters["created_before"]), bound(filters["created_after"])
        selected = []
        for row in _rows(session.get("/backup/list", {})):
            sn, name = str(row.get("sn") or ""), str(row.get("name") or "")
            if ids and sn not in ids or filters["name_contains"] is not None and filters["name_contains"] not in name or filters["name_equals"] is not None and filters["name_equals"] != name:
                continue
            if before is not None or after is not None:
                created = row.get("ctime")
                if isinstance(created, str) and created.isdigit():
                    created = int(created)
                if type(created) not in (int, float):
                    raise FuploadError("DD backup creation time is unavailable", kind="platform_data_error")
                if before is not None and not created < before or after is not None and not created > after:
                    continue
            selected.append(sn)
        return self.backup_delete_preview(session, selected) if selected else {"items": [], "deletable": False, "references_complete": True, "matched": 0}

    def delete_backups(self, session: Any, doc: Mapping[str, Any]) -> Dict[str, Any]:
        if doc.get("confirm_delete") is not True:
            raise ValidationError("confirm_delete must be true", path="$.confirm_delete")
        preview = self.backup_delete_preview(session, doc["backup_ids"])
        if not preview["deletable"]:
            raise FuploadError("DD cloud backup deletion is blocked", kind="backup_delete_blocked", details=preview)
        completed = []
        for row in preview["items"]:
            sn = row["sn"]
            current = self.backup_delete_preview(session, [sn])
            if not current["deletable"]:
                raise FuploadError("DD cloud backup deletion is blocked", kind="backup_delete_blocked", details={"completed": completed, "preview": current})
            accepted = False
            try:
                session.post("/backup/delete", {"sn": sn})
                accepted = True
                if any(str(r.get("sn")) == sn for r in _rows(session.get("/backup/list", {}))):
                    raise FuploadError("deleted DD backup remains in readback", kind="verification_required", stage="readback", verification_required=True)
            except FuploadError as exc:
                exc.verification_required = exc.verification_required or accepted
                exc.details.update({"completed": completed, "sn": sn, "automatic_retry": False})
                raise
            completed.append({"sn": sn, "deleted": True, "readback": {"present": False}})
        return {"items": completed, "deleted": len(completed)}

    def rename_backup(self, session: Any, doc: Mapping[str, Any]) -> Dict[str, Any]:
        sn, name = doc.get("sn"), doc.get("name")
        if not isinstance(sn, str) or not sn or not isinstance(name, str) or not name.strip() or len(name) > 14:
            raise ValidationError("sn and name are required; name is at most 14 characters", path="$.name")
        self.backup_get(session, sn)
        session.post("/backup/modify_name", {"sn": sn, "name": name})
        try:
            readback = self.backup_get(session, sn)
            if readback.get("name") != name:
                raise FuploadError("DD backup rename did not match readback", kind="verification_required", stage="readback", verification_required=True)
        except FuploadError as exc:
            exc.verification_required = True
            exc.details.update({"sn": sn, "automatic_retry": False})
            raise
        return {"sn": sn, "readback": readback}

    def upload_backup(self, session: Any, doc: Mapping[str, Any]) -> Dict[str, Any]:
        if "name" in doc and (not isinstance(doc["name"], str) or not doc["name"].strip() or len(doc["name"]) > 14):
            raise ValidationError("name must contain 1 to 14 characters", path="$.name")
        manifest, files = _load_bundle(doc["bundle_file"])
        options = _rows(session.get("/game_type/list", {}))
        if manifest["game_type"] not in {row.get("game_type") for row in options}:
            raise ValidationError("game_type is unavailable", path="$.game_type")
        prepared = _result(session.post("/backup/pre_create", manifest))
        if not isinstance(prepared, dict) or not isinstance(prepared.get("sn"), str) or not prepared["sn"]:
            raise FuploadError("DD backup creation returned no reference", kind="verification_required", verification_required=True, details={"automatic_retry": False})
        sn = prepared["sn"]
        completed, reused, finished = [], [], False
        try:
            for group, source in files:
                upload = prepared.get(group)
                if not isinstance(upload, dict):
                    raise FuploadError("DD backup preparation omitted a selected component upload URL", kind="platform_data_error", stage="upload_authorize")
                if upload.get("u_url") in (None, ""):
                    reused.append(group)
                    continue
                if not isinstance(upload["u_url"], str):
                    raise FuploadError("DD backup upload URL had an invalid shape", kind="platform_data_error", stage="upload_authorize")
                _put_backup(source, upload["u_url"])
                completed.append(group)
            session.post("/backup/finish_create", {"sn": sn})
            finished = True
            raw = _result(session.get("/backup/detail", {"sn": sn}))
            if not isinstance(raw, dict) or str(raw.get("sn") or "") != sn or str(raw.get("game_type")) != str(manifest["game_type"]):
                raise FuploadError("DD created backup detail did not match", kind="verification_required", stage="readback", verification_required=True)
            for group in GROUPS:
                field = "accounts" if group == "wtf" else "items"
                expected = manifest[group][field]
                value = raw.get(group)
                # DD normalizes an unselected known_addon group to null.
                # Selected groups still require their complete item metadata.
                actual = [] if value is None and not expected else (value.get(field, []) if isinstance(value, dict) else None)
                if not _subset(expected, actual):
                    raise FuploadError("DD created backup selection did not match", kind="verification_required", stage="readback", verification_required=True, details={"group": group})
            if not any(str(row.get("sn")) == sn for row in _rows(session.get("/backup/list", {}))):
                raise FuploadError("DD created backup is absent from list readback", kind="verification_required", stage="readback", verification_required=True)
            from .dd import safe_backup_detail
            readback = dict(safe_backup_detail(raw), sn=sn, created_at=raw.get("ctime"))
            if "name" in doc:
                readback = self.rename_backup(session, {"sn": sn, "name": doc["name"]})["readback"]
            return {"sn": sn, "uploaded_components": completed, "reused_components": reused, "readback": readback}
        except FuploadError as exc:
            exc.verification_required = exc.verification_required or finished
            exc.details.update({"sn": sn, "uploaded_components": completed, "reused_components": reused, "automatic_retry": False, "incomplete_backup_retained": True})
            raise
