"""WoW Creator cloud backups: selective local bundles and guarded mutations.

Wire shapes are checked against desktop 1.1.29 chunks 8761 and 29474/97155.
This module never accepts credentials or API origins from input documents.
"""

from __future__ import annotations

import copy
from datetime import datetime, timezone
import hashlib
import http.client
import json
import os
import re
import shutil
import stat
import struct
import subprocess
import tempfile
import urllib.parse
import zipfile
import zlib
from pathlib import Path
from typing import Any, Dict, List, Mapping, Sequence

from .errors import FuploadError, ValidationError
from .newbee_auth import API_BASE, API_ORIGIN, _jwt_fresh, _read, _refresh
from .transport import json_request
from .trust import NEWBEE_ORIGINS, _verify_executable


BUNDLE_SCHEMA = "fupload.newbee.backup-bundle.v1"
ROLE_MARKERS = {"AddOns.txt", "bindings-cache.wtf", "config-cache.wtf"}
MANIFEST_KEYS = {
    "knowplug_list", "t_unKnown_list", "t_font_list", "t_material_list", "t_WTF_list",
    "versionid", "wtfconfig", "unknown_plug", "material", "font", "font_hash", "wtf",
}


def _array(value: Any) -> List[Any]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return []
    return value if isinstance(value, list) else []


def _positive(value: Any, path: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValidationError("expected a positive integer", path=path)
    return value


def _name(value: Any, path: str) -> str:
    if not isinstance(value, str) or not value or value in (".", "..") or value.endswith((" ", ".")) or any(c in value for c in '/\\:\0<>"|?*') or any(ord(c) < 32 for c in value) or re.fullmatch(r"(?i)(?:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?", value):
        raise ValidationError("expected one local file or directory name", path=path)
    return value


def _local(root: Path, *parts: str) -> Path:
    path = root.joinpath(*parts)
    for parent in (path, *path.parents):
        if parent == root.parent:
            break
        if parent.is_symlink() or parent.exists() and bool(getattr(parent.stat(follow_symlinks=False), "st_file_attributes", 0) & 0x400):
            raise ValidationError("backup source contains a symlink or reparse point", path="$.game_dir")
    resolved = path.resolve()
    if resolved != root and root not in resolved.parents:
        raise ValidationError("backup source escaped game directory", path="$.game_dir")
    return path


def _entries(path: Path) -> List[Path]:
    return sorted(path.iterdir(), key=lambda p: p.name.casefold()) if path.is_dir() else []


def _contains(expected: Any, actual: Any) -> bool:
    if isinstance(actual, str):
        try:
            actual = json.loads(actual)
        except ValueError:
            pass
    if isinstance(expected, dict):
        return isinstance(actual, dict) and all(key in actual and _contains(value, actual[key]) for key, value in expected.items() if key not in {"select", "size", "editModeLayouts"})
    if isinstance(expected, list):
        return isinstance(actual, list) and len(expected) == len(actual) and all(any(_contains(value, candidate) for candidate in actual) for value in expected)
    if expected is None:
        return actual in (None, "")
    if isinstance(expected, str) and expected and isinstance(actual, str):
        return expected == actual or urllib.parse.urlsplit(actual).path.lstrip("/") == urllib.parse.urlsplit(expected).path.lstrip("/")
    return expected == actual


def _manifest_matches(manifest: Mapping[str, Any], row: Mapping[str, Any]) -> bool:
    mapping = {"knowplug_list": "t_Known_plug", "t_unKnown_list": "t_unKnown_list", "t_material_list": "t_material_list", "t_font_list": "t_font_list", "unknown_plug": "t_unKnown_plug", "material": "t_material", "font_hash": "t_font_ncs_hash"}
    for source, target in mapping.items():
        expected, actual = manifest[source], row.get(target)
        if expected == []:
            if actual not in (None, "", "null", "[]", []):
                return False
        elif expected in (None, ""):
            if actual not in (None, "", "null"):
                return False
        elif target not in row or not _contains(expected, actual):
            return False
    if manifest["wtf"]:
        accounts = [{key: value for key, value in account.items() if key != "id"} for account in manifest["wtf"]]
        if not _contains(accounts, row.get("wtflist", row.get("t_WTF_list"))):
            return False
    elif any(row.get(field) not in (None, "", "null", "[]", []) for field in ("wtflist", "t_WTF_list")):
        return False
    return str(row.get("t_Versionid")) == str(manifest["versionid"])


def scan_backup(game_dir: str) -> Dict[str, Any]:
    root = Path(game_dir).resolve()
    if not root.is_dir():
        raise ValidationError("game directory does not exist", path="$.game_dir")
    addons = _local(root, "Interface", "AddOns") if (root / "Interface" / "AddOns").exists() else None
    interface = _local(root, "Interface") if (root / "Interface").exists() else None
    fonts = _local(root, "Fonts") if (root / "Fonts").exists() else None
    accounts = []
    account_root = root / "WTF" / "Account"
    if account_root.exists():
        _local(root, "WTF", "Account")
        for account in _entries(account_root):
            _local(root, "WTF", "Account", account.name)
            if not account.is_dir():
                continue
            roles = []
            for server in _entries(account):
                if not server.is_dir() or server.name.casefold() == "savedvariables":
                    continue
                for role in _entries(server):
                    _local(root, "WTF", "Account", account.name, server.name, role.name)
                    if role.is_dir() and ROLE_MARKERS.intersection(p.name for p in _entries(role)):
                        roles.append({"server": server.name, "name": role.name})
            if roles:
                accounts.append({"account": account.name, "roles": roles, "has_common": any(p.is_file() or p.name.casefold() == "savedvariables" for p in _entries(account))})
    return {
        "game_dir": str(root),
        "unknown_plugins": [{"name": p.name} for p in _entries(addons) if p.is_dir()] if addons else [],
        "materials": [{"name": p.name} for p in _entries(interface) if p.name.casefold() != "addons" and (p.is_dir() and any(p.iterdir()) or p.suffix.casefold() in {".blp", ".tga", ".dds", ".png", ".jpeg", ".bmp", ".tex"})] if interface else [],
        "fonts": [{"name": p.name, "size": p.stat().st_size} for p in _entries(fonts) if p.is_file() and p.suffix.casefold() == ".ttf"] if fonts else [],
        "wtf_accounts": accounts,
    }


def _zip(root: Path, sources: Sequence[Path], destination: Path, *, exclude_bak: bool = False) -> Dict[str, Any]:
    """Archive each selected source by basename, matching compressWithArchives."""
    count = 0
    with zipfile.ZipFile(destination, "x", compression=zipfile.ZIP_DEFLATED) as archive:
        for source in sources:
            candidates = [source] if source.is_file() else sorted(source.rglob("*"))
            for item in candidates:
                _local(root, *item.relative_to(root).parts)
                if item.is_file() and not (exclude_bak and item.name.casefold().endswith(".bak")):
                    archive.write(item, item.relative_to(source.parent).as_posix())
                    count += 1
    return {"file": destination.name, "size": destination.stat().st_size, "sha256": hashlib.sha256(destination.read_bytes()).hexdigest(), "files": count}


def _selection_names(rows: List[Any], field: str) -> List[str]:
    names = []
    for row in rows:
        if not isinstance(row, dict):
            raise ValidationError("backup selection must contain named objects", path="$.bundle_file.manifest." + field)
        names.append(_name(row.get("name"), "$.bundle_file.manifest." + field))
    if len({name.casefold() for name in names}) != len(names):
        raise ValidationError("backup selection repeats a name", path="$.bundle_file.manifest." + field)
    if field == "t_material_list" and any(name.casefold() == "addons" for name in names):
        raise ValidationError("material selection cannot contain AddOns", path="$.bundle_file.manifest." + field)
    return names


def _validate_zip_selection(path: Path, artifact: Mapping[str, Any], manifest: Mapping[str, Any]) -> None:
    """Bind a ZIP's actual Windows directory tree to its pending manifest target."""
    category, target = artifact["file_type"], artifact["target"]
    roots = None
    if category in ("unknown_plug", "material"):
        field = "t_unKnown_list" if category == "unknown_plug" else "t_material_list"
        roots = set(_selection_names(manifest[field], field))
    elif category == "wtfrole":
        account = manifest["wtf"][target[1]]
        role = account["server"][target[3]]["roleList"][target[5]]
        roots = {_name(role.get("name"), "$.bundle_file.manifest.wtf.role.name")}
    seen_entries, tree, actual_roots = set(), {}, set()
    file_count = 0
    try:
        with zipfile.ZipFile(path) as archive:
            for member in archive.infolist():
                raw_name = member.orig_filename
                directory = member.is_dir()
                name = raw_name[:-1] if directory else raw_name
                if raw_name != member.filename or not name or "\\" in name:
                    raise ValidationError("backup ZIP contains an unsafe member name", path="$.bundle_file.artifacts")
                parts = tuple(_name(part, "$.bundle_file.artifacts.member") for part in name.split("/"))
                folded = tuple(part.casefold() for part in parts)
                if folded in seen_entries:
                    raise ValidationError("backup ZIP repeats a case-insensitive member path", path="$.bundle_file.artifacts")
                seen_entries.add(folded)
                mode = stat.S_IFMT(member.external_attr >> 16)
                if member.flag_bits & 1 or member.external_attr & 0x400 or mode not in (0, stat.S_IFREG, stat.S_IFDIR) or mode == stat.S_IFDIR and not directory or mode == stat.S_IFREG and directory:
                    raise ValidationError("backup ZIP contains a link or unsupported member type", path="$.bundle_file.artifacts")
                for length in range(1, len(parts) + 1):
                    identity = folded[:length]
                    spelling = parts[:length]
                    is_directory = length < len(parts) or directory
                    previous = tree.get(identity)
                    if previous is not None and previous != (spelling, is_directory):
                        raise ValidationError("backup ZIP contains conflicting Windows paths", path="$.bundle_file.artifacts")
                    tree[identity] = (spelling, is_directory)
                top = parts[0]
                if category == "wtfserve":
                    allowed = not directory and len(parts) == 1 or top.casefold() == "savedvariables" and (directory or len(parts) > 1)
                else:
                    allowed = top in roots
                    if category in ("unknown_plug", "wtfrole"):
                        allowed = allowed and (directory or len(parts) > 1)
                if not allowed or category.startswith("wtf") and not directory and parts[-1].casefold().endswith(".bak"):
                    raise ValidationError("backup ZIP contains an unselected component or WTF role", path="$.bundle_file.artifacts")
                actual_roots.add(top)
                if not directory:
                    file_count += 1
            if archive.testzip() is not None:
                raise ValidationError("backup ZIP member checksum failed", path="$.bundle_file.artifacts")
    except (OSError, zipfile.BadZipFile, NotImplementedError, RuntimeError, zlib.error) as exc:
        raise ValidationError("backup archive cannot be read as a supported ZIP", path="$.bundle_file.artifacts") from exc
    if roots is not None and actual_roots != roots:
        raise ValidationError("backup ZIP roots do not match the selected manifest names", path="$.bundle_file.artifacts")
    if type(artifact.get("files")) is not int or artifact["files"] != file_count:
        raise ValidationError("backup ZIP file count changed", path="$.bundle_file.artifacts")


def generate_backup(doc: Mapping[str, Any]) -> Dict[str, Any]:
    root = Path(doc["game_dir"]).resolve()
    available = scan_backup(str(root))
    version = _positive(doc.get("game_version_id"), "$.game_version_id")
    output = Path(doc["output_dir"]).resolve()
    if output == root or root in output.parents:
        raise ValidationError("output directory must be outside the game directory", path="$.output_dir")
    if output.exists() and any(output.iterdir()):
        raise ValidationError("output directory must be empty", path="$.output_dir")
    selections: Dict[str, List[str]] = {}
    for field in ("unknown_plugins", "materials", "fonts"):
        values = doc.get(field, [])
        if not isinstance(values, list):
            raise ValidationError("expected an array", path="$." + field)
        selected = [_name(value, "$." + field) for value in values]
        allowed = {row["name"] for row in available[field]}
        if len(selected) != len(set(selected)) or set(selected) - allowed:
            raise ValidationError("selection contains a duplicate or unavailable item", path="$." + field)
        selections[field] = selected
    # Font folder upload uses the native uploadserver content-index protocol. It is
    # intentionally independent from the signed ZIP categories below.
    known = doc.get("known_plugins", [])
    if not isinstance(known, list):
        raise ValidationError("expected an array", path="$.known_plugins")
    known_fields = {"name", "id", "fileName", "fileUrl", "mod_file_id", "mod_version", "display_name", "updateType"}
    for item in known:
        if not isinstance(item, dict) or set(item) - known_fields or not {"name", "id", "fileName", "fileUrl", "mod_file_id", "mod_version", "display_name", "updateType"}.issubset(item):
            raise ValidationError("known plugin must contain the desktop manifest fields", path="$.known_plugins")
        _positive(item["id"], "$.known_plugins.id")
        _positive(item["updateType"], "$.known_plugins.updateType")
        if item["mod_file_id"] is not None:
            _positive(item["mod_file_id"], "$.known_plugins.mod_file_id")
        if not isinstance(item["name"], str) or not item["name"] or any(item[field] is not None and not isinstance(item[field], str) for field in ("fileName", "fileUrl", "mod_version", "display_name")):
            raise ValidationError("known plugin names and file metadata must be strings or null", path="$.known_plugins")
    if len({item["id"] for item in known}) != len(known):
        raise ValidationError("duplicate known plugin", path="$.known_plugins")
    selected_accounts = []
    sources_by_account = []
    seen_accounts = set()
    choices = doc.get("wtf_accounts", [])
    if not isinstance(choices, list):
        raise ValidationError("expected an array", path="$.wtf_accounts")
    for choice in choices:
        if not isinstance(choice, dict) or set(choice) != {"account", "include_common", "roles"} or not isinstance(choice["roles"], list):
            raise ValidationError("account selection requires account, include_common, and roles only", path="$.wtf_accounts")
        account_name = _name(choice.get("account"), "$.wtf_accounts.account")
        if account_name in seen_accounts:
            raise ValidationError("duplicate account selection", path="$.wtf_accounts")
        seen_accounts.add(account_name)
        existing = next((a for a in available["wtf_accounts"] if a["account"] == account_name), None)
        if existing is None:
            raise ValidationError("unknown WTF account", path="$.wtf_accounts.account")
        if not isinstance(choice.get("include_common"), bool):
            raise ValidationError("include_common must be explicit", path="$.wtf_accounts.include_common")
        account_path = _local(root, "WTF", "Account", account_name)
        common = [p for p in _entries(account_path) if p.is_file() or p.name.casefold() == "savedvariables"] if choice["include_common"] else []
        selected_roles = []
        servers = []
        seen_roles = set()
        for role in choice.get("roles", []):
            if not isinstance(role, dict) or set(role) != {"server", "name"}:
                raise ValidationError("role selection requires server and name only", path="$.wtf_accounts.roles")
            server, name = _name(role.get("server"), "$.wtf_accounts.roles.server"), _name(role.get("name"), "$.wtf_accounts.roles.name")
            if (server, name) in seen_roles or {"server": server, "name": name} not in existing["roles"]:
                raise ValidationError("duplicate or unavailable WTF role", path="$.wtf_accounts.roles")
            seen_roles.add((server, name))
            selected_roles.append(_local(root, "WTF", "Account", account_name, server, name))
            row = next((s for s in servers if s["serverName"] == server), None)
            if row is None:
                row = {"serverName": server, "roleList": []}
                servers.append(row)
            row["roleList"].append({"name": name, "zip": ""})
        if not common and not selected_roles:
            raise ValidationError("WTF account selection is empty", path="$.wtf_accounts")
        selected_accounts.append({"id": len(selected_accounts) + 1, "account": account_name, "server": servers, "commonConfig": ""})
        sources_by_account.append((common, selected_roles))
    if not any((known, *selections.values(), selected_accounts)):
        raise ValidationError("select at least one backup component", path="$")
    output.mkdir(parents=True, exist_ok=True)
    manifest: Dict[str, Any] = {key: None for key in MANIFEST_KEYS}
    manifest.update({"knowplug_list": copy.deepcopy(known), "t_unKnown_list": [], "t_font_list": [], "t_material_list": [], "t_WTF_list": [], "versionid": version, "wtf": selected_accounts})
    artifacts = []
    for field, base_parts, category, target, list_key in (
        ("unknown_plugins", ("Interface", "AddOns"), "unknown_plug", "unknown_plug", "t_unKnown_list"),
        ("materials", ("Interface",), "material", "material", "t_material_list"),
    ):
        if selections[field]:
            artifact = _zip(root, [_local(root, *base_parts, name) for name in selections[field]], output / (category + ".zip"))
            artifacts.append(dict(artifact, file_type=category, target=[target]))
            manifest[list_key] = [{"name": name} for name in selections[field]]
    for index, (common, roles) in enumerate(sources_by_account):
        if common:
            artifact = _zip(root, common, output / ("wtf-%d-common.zip" % index), exclude_bak=True)
            artifacts.append(dict(artifact, file_type="wtfserve", target=["wtf", index, "commonConfig"]))
        for role_index, source in enumerate(roles):
            account = selected_accounts[index]
            server_index = next(i for i, s in enumerate(account["server"]) if s["serverName"] == source.parent.name)
            list_index = next(i for i, r in enumerate(account["server"][server_index]["roleList"]) if r["name"] == source.name)
            artifact = _zip(root, [source], output / ("wtf-%d-role-%d.zip" % (index, role_index)), exclude_bak=True)
            artifacts.append(dict(artifact, file_type="wtfrole", target=["wtf", index, "server", server_index, "roleList", list_index, "zip"]))
    if selections["fonts"]:
        font_dir = output / "Fonts"
        font_dir.mkdir()
        for name in selections["fonts"]:
            source = _local(root, "Fonts", name)
            (font_dir / name).write_bytes(source.read_bytes())
        manifest["t_font_list"] = [{"name": name, "size": (font_dir / name).stat().st_size} for name in selections["fonts"]]
    bundle = {"schema": BUNDLE_SCHEMA, "manifest": manifest, "artifacts": artifacts, "font_directory": "Fonts" if selections["fonts"] else None,
              "font_files": [{"name": name, "sha256": hashlib.sha256((output / "Fonts" / name).read_bytes()).hexdigest()} for name in selections["fonts"]]}
    bundle_file = output / "backup-bundle.json"
    bundle_file.write_text(json.dumps(bundle, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"bundle_file": str(bundle_file), "game_version_id": version, "archives": [{k: v for k, v in a.items() if k != "target"} for a in artifacts], "known_plugins": len(known), "fonts": len(selections["fonts"]), "wtf_accounts": len(selected_accounts)}


def _newbee_archive() -> Path:
    """Find the installed, publisher-verified client without reading user state."""
    if os.name != "nt":
        raise FuploadError("NewBeeBox native font upload requires Windows", kind="dependency_missing")
    import winreg
    candidates = set()
    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        for view in (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
            try:
                with winreg.OpenKey(hive, r"Software\Microsoft\Windows\CurrentVersion\Uninstall", 0, winreg.KEY_READ | view) as uninstall:
                    for index in range(winreg.QueryInfoKey(uninstall)[0]):
                        try:
                            with winreg.OpenKey(uninstall, winreg.EnumKey(uninstall, index)) as key:
                                display = str(winreg.QueryValueEx(key, "DisplayName")[0])
                                if not display.startswith("NewBeeBox"):
                                    continue
                                for field in ("InstallLocation", "DisplayIcon", "UninstallString"):
                                    try:
                                        value = str(winreg.QueryValueEx(key, field)[0]).strip()
                                    except OSError:
                                        continue
                                    if value.startswith('"'):
                                        value = value.split('"', 2)[1]
                                    else:
                                        value = re.split(r"\.exe(?:\s|,)", value, maxsplit=1, flags=re.IGNORECASE)[0] + (".exe" if re.search(r"\.exe(?:\s|,)", value, re.IGNORECASE) else "")
                                    path = Path(value)
                                    candidates.add(path if field == "InstallLocation" else path.parent)
                        except OSError:
                            continue
            except OSError:
                continue
    for directory in sorted(candidates):
        executable, archive = directory / "NewBeeBox.exe", directory / "resources" / "app.asar"
        if not executable.is_file() or not archive.is_file():
            continue
        resolved = directory.resolve()
        _local(resolved, "NewBeeBox.exe")
        _local(resolved, "resources", "app.asar")
        _verify_executable(executable, ("南宁新手村科技有限公司",), "NewBeeBox")
        return archive
    raise FuploadError("a publisher-verified NewBeeBox installation was not found", kind="dependency_missing")


def _extract_nbb_binding(archive: Path, destination: Path) -> Path:
    """Extract only the official N-API binding, never a caller-selected module."""
    try:
        with archive.open("rb") as source:
            raw = source.read(16)
            _, header_size, _, json_size = struct.unpack("<4I", raw)
            if json_size < 2 or json_size > 16 * 1024 * 1024:
                raise ValueError()
            header = json.loads(source.read(json_size))
            base = header["files"]["node_modules"]["files"]["nbb-core"]["files"]
            if "dist" in base:
                base = base["dist"]["files"]
            entry = base["nbb-core.win32-x64-msvc.node"]
            if entry.get("unpacked") or not 0 < int(entry["size"]) < 128 * 1024 * 1024:
                raise ValueError()
            source.seek(8 + header_size + int(entry["offset"]))
            data = source.read(int(entry["size"]))
            if len(data) != int(entry["size"]):
                raise ValueError()
            binding = destination / "nbb-core.win32-x64-msvc.node"
            binding.write_bytes(data)
            return binding
    except (OSError, ValueError, KeyError, TypeError, struct.error) as exc:
        raise FuploadError("installed NewBeeBox native module is unavailable", kind="dependency_missing") from exc


_FONT_SCRIPT = r"""
const fs = require('node:fs');
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
const send = value => process.stdout.write('\nFUPLOAD_FONT_RESULT:' + JSON.stringify(value) + '\n');
(async () => {
  try {
    const core = require(input.binding);
    if (typeof core.OssUploader !== 'function') throw new Error('missing uploader');
    if (typeof core.setLogCallback === 'function') core.setLogCallback(() => {});
    const uploader = new core.OssUploader(JSON.stringify({apiBase: 'https://api.next.newbeebox.com/uploadserver'}));
    const result = await uploader.uploadFolder(JSON.stringify({path: input.path}));
    if (!result || result.code !== 1 || typeof result.data !== 'string') {
      send({ok: false}); process.exitCode = 1; return;
    }
    send({ok: true, index: result.data});
  } catch (_) { send({ok: false}); process.exitCode = 1; }
})();
"""


def upload_fonts(directory: Path) -> str:
    archive = _newbee_archive()
    node = shutil.which("node")
    if not node:
        raise FuploadError("Node.js is required for the official font uploader", kind="dependency_missing")
    with tempfile.TemporaryDirectory(prefix="fupload-newbee-font-") as temporary:
        binding = _extract_nbb_binding(archive, Path(temporary))
        try:
            result = subprocess.run([node, "-e", _FONT_SCRIPT], input=json.dumps({"binding": str(binding), "path": str(directory)}),
                                    capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=600,
                                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), check=False)
        except (OSError, subprocess.SubprocessError) as exc:
            raise FuploadError("native font upload result is uncertain", stage="font_upload", verification_required=True) from exc
        # Native diagnostics stay in captured memory and are never surfaced. Only
        # the bounded non-secret upload index is consumed by the create manifest.
        records = [line.partition("FUPLOAD_FONT_RESULT:")[2] for line in result.stdout.splitlines() if line.startswith("FUPLOAD_FONT_RESULT:")]
        try:
            response = json.loads(records[-1])
            value = response["index"]
            if result.returncode != 0 or response.get("ok") is not True or not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,256}", value):
                raise ValueError()
            return value
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise FuploadError("native font upload failed; inspect the selected backup before retrying", stage="font_upload", verification_required=True) from exc


class NewBeeBackupMixin:
    @staticmethod
    def upload_backup_fonts(directory: Path) -> str:
        return upload_fonts(directory)

    def backup_post(self, endpoint: str, body: Mapping[str, Any]) -> Any:
        access = _read("access-token")
        if not _jwt_fresh(access):
            access, _, _ = _refresh(access, _read("refresh-token"), _read("device-proof", True))
        mutation = endpoint in {"/v3/share/create", "/v3/share/delete", "/share/update"}
        try:
            envelope = json_request(API_BASE + endpoint, method="POST", body=body,
                                    headers={"Authorization": "Bearer " + access, "boxversion": "1.1.17", "Accept-Language": "zh-CN"}, trusted_service=API_ORIGIN)
        except FuploadError as exc:
            if mutation and exc.business_code is None and (exc.http_status is None or 200 <= exc.http_status < 300 or exc.http_status >= 500):
                exc.verification_required = True
                exc.details["automatic_retry"] = False
            raise
        if not isinstance(envelope, dict) or envelope.get("code") != 1:
            code = envelope.get("code") if isinstance(envelope, dict) else None
            message = envelope.get("message") if isinstance(envelope, dict) else None
            message = "NewBeeBox backup request failed" + (": " + message if isinstance(message, str) and message else "")
            raise FuploadError(message, endpoint=endpoint, business_code=code,
                               verification_required=mutation and code is None)
        return envelope.get("data")

    def cloud_backups_raw(self) -> List[Dict[str, Any]]:
        value = self.backup_post("/v3/share/list", {})
        if isinstance(value, list) and value and isinstance(value[0], list):
            value = value[0]
        if not isinstance(value, list) or any(not isinstance(row, dict) or not row.get("t_id") for row in value):
            raise FuploadError("cloud backup list was incomplete or malformed", kind="platform_data_error")
        return value

    @staticmethod
    def cloud_backup_summary(row: Mapping[str, Any]) -> Dict[str, Any]:
        return {"id": int(row["t_id"]), "cloud_id": int(row["t_id"]), "name": row.get("t_name"), "game_version_id": row.get("t_Versionid"), "created_at": row.get("t_create_time"), "known_plugins": len(_array(row.get("t_Known_plug"))), "unknown_plugins": len(_array(row.get("t_unKnown_list"))), "materials": len(_array(row.get("t_material_list"))), "fonts": len(_array(row.get("t_font_list")))}

    def cloud_backups(self) -> Dict[str, Any]:
        rows = self.cloud_backups_raw()
        return {"total": len(rows), "items": [self.cloud_backup_summary(row) for row in rows]}

    def cloud_backup(self, ident: int) -> Dict[str, Any]:
        for row in self.cloud_backups_raw():
            if int(row["t_id"]) == ident:
                result = self.cloud_backup_summary(row)
                result["known_plugins"] = [{"id": mod.get("id"), "name": mod.get("name"), "mod_file_id": mod.get("mod_file_id"), "mod_version": mod.get("mod_version"), "display_name": mod.get("display_name"), "updateType": mod.get("updateType")} for mod in _array(row.get("t_Known_plug")) if isinstance(mod, dict)]
                result.update({"unknown_plugins": [{"name": r.get("name")} for r in _array(row.get("t_unKnown_list")) if isinstance(r, dict)], "materials": [{"name": r.get("name")} for r in _array(row.get("t_material_list")) if isinstance(r, dict)], "fonts": [{"name": r.get("name")} for r in _array(row.get("t_font_list")) if isinstance(r, dict)], "wtf_accounts": [{"account": a.get("account"), "servers": [{"server": s.get("serverName"), "roles": [{"name": r.get("name"), "role_id": str(r.get("role_id") or "")} for r in _array(s.get("roleList")) if isinstance(r, dict)]} for s in _array(a.get("server")) if isinstance(s, dict)]} for a in _array(row.get("wtflist") or row.get("t_WTF_list")) if isinstance(a, dict)]})
                return result
        raise FuploadError("cloud backup %d was not found" % ident, kind="not_found")

    def backup_references(self) -> Dict[int, List[Dict[str, Any]]]:
        result: Dict[int, List[Dict[str, Any]]] = {}
        offset, seen, total = 0, set(), None
        while True:
            raw = self.list_configs("", offset, 100)
            if not isinstance(raw, dict):
                raise FuploadError("configuration reference list has no pagination metadata", kind="backup_reference_unknown")
            rows = raw.get("list", raw.get("items"))
            count = raw.get("total", raw.get("count"))
            if not isinstance(rows, list) or isinstance(count, bool) or not isinstance(count, int) or count < 0 or total is not None and count != total:
                raise FuploadError("configuration reference pagination is incomplete", kind="backup_reference_unknown")
            total = count
            for row in rows:
                if not isinstance(row, dict):
                    raise FuploadError("configuration reference row is malformed", kind="backup_reference_unknown")
                ident = row.get("t_id", row.get("id"))
                if isinstance(ident, str) and ident.isdigit():
                    ident = int(ident)
                if isinstance(ident, bool) or not isinstance(ident, int) or ident <= 0 or ident in seen:
                    raise FuploadError("configuration reference list repeats or omits IDs", kind="backup_reference_unknown")
                seen.add(ident)
                cloud_id = row.get("t_cloudblackid", row.get("cloud_id"))
                if cloud_id is None:
                    detail = self.get_config_raw(ident)
                    detail_ids = [detail[key] for key in ("t_id", "id") if key in detail and detail[key] is not None] if isinstance(detail, dict) else []
                    normalized_ids = [int(value) if isinstance(value, str) and value.isdigit() else value for value in detail_ids]
                    if not normalized_ids or any(type(value) is not int or value != ident for value in normalized_ids):
                        raise FuploadError("configuration reference detail does not identify the requested configuration", kind="backup_reference_unknown", details={"config_id": ident})
                    cloud_id = detail.get("t_cloudblackid", detail.get("cloud_id"))
                if isinstance(cloud_id, str) and cloud_id.isdigit():
                    cloud_id = int(cloud_id)
                if isinstance(cloud_id, bool) or not isinstance(cloud_id, int) or cloud_id <= 0:
                    raise FuploadError("configuration backup association is unknown", kind="backup_reference_unknown", details={"config_id": ident})
                result.setdefault(cloud_id, []).append({"id": ident, "title": row.get("t_title", row.get("title", ""))})
            if len(seen) == total:
                return result
            if not rows or len(seen) > total:
                raise FuploadError("configuration reference pagination ended early", kind="backup_reference_unknown")
            next_offset = raw.get("next_offset")
            if next_offset is None:
                next_offset = offset + len(rows)
            if isinstance(next_offset, bool) or not isinstance(next_offset, int) or next_offset <= offset:
                raise FuploadError("configuration reference cursor did not advance", kind="backup_reference_unknown")
            offset = next_offset

    def backup_delete_preview(self, ids: Sequence[int]) -> Dict[str, Any]:
        ids = [_positive(i, "$.ids") for i in ids]
        if not ids or len(ids) != len(set(ids)):
            raise ValidationError("ids must be nonempty and unique", path="$.ids")
        backups = {int(row["t_id"]): self.cloud_backup_summary(row) for row in self.cloud_backups_raw()}
        references = self.backup_references()
        items = []
        for ident in ids:
            linked = references.get(ident, [])
            items.append({"id": ident, "name": backups.get(ident, {}).get("name"), "present": ident in backups, "references": linked, "deletable": ident in backups and not linked, "reason": "configuration_share_reference" if linked else "not_found" if ident not in backups else None})
        return {"items": items, "deletable": all(row["deletable"] for row in items), "references_complete": True}

    def backup_preview_selection(self, args: Any) -> Dict[str, Any]:
        ids = list(getattr(args, "backup_ids", None) or [])
        filters = {key: getattr(args, key, None) for key in ("name_contains", "name_equals", "created_before", "created_after")}
        if not any(value is not None for value in filters.values()):
            return self.backup_delete_preview(ids)
        def timestamp(value: Any) -> datetime:
            try:
                if isinstance(value, (int, float)):
                    return datetime.fromtimestamp(value / 1000 if value > 100000000000 else value, timezone.utc)
                parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
                return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)
            except (ValueError, TypeError, OverflowError, OSError) as exc:
                raise ValidationError("backup preview requires valid ISO creation dates", path="$.created_before") from exc
        before = timestamp(filters["created_before"]) if filters["created_before"] is not None else None
        after = timestamp(filters["created_after"]) if filters["created_after"] is not None else None
        selected = []
        for row in self.cloud_backups_raw():
            ident, name = int(row["t_id"]), str(row.get("t_name") or "")
            if ids and ident not in ids or filters["name_contains"] is not None and filters["name_contains"] not in name or filters["name_equals"] is not None and filters["name_equals"] != name:
                continue
            created = timestamp(row.get("t_create_time")) if before or after else None
            if before and not created < before or after and not created > after:
                continue
            selected.append(ident)
        if not selected:
            return {"items": [], "deletable": False, "references_complete": True, "matched": 0}
        return self.backup_delete_preview(selected)

    def delete_backups(self, doc: Mapping[str, Any]) -> Dict[str, Any]:
        if doc.get("confirm_delete") is not True and doc.get("confirm") != "DELETE":
            raise ValidationError("confirm_delete must be true", path="$.confirm_delete")
        preview = self.backup_delete_preview(doc.get("backup_ids", doc.get("ids", [doc["id"]] if "id" in doc else [])))
        if not preview["deletable"]:
            raise FuploadError("cloud backup deletion is blocked", kind="backup_delete_blocked", details=preview)
        completed = []
        for row in preview["items"]:
            ident = row["id"]
            # A reference can be created after preview or after the preceding item.
            current = self.backup_delete_preview([ident])
            if not current["deletable"]:
                raise FuploadError("cloud backup deletion is blocked", kind="backup_delete_blocked", details={"completed": completed, "preview": current})
            accepted = False
            try:
                self.backup_post("/v3/share/delete", {"t_id": ident})
                accepted = True
                if any(int(item["t_id"]) == ident for item in self.cloud_backups_raw()):
                    raise FuploadError("deleted backup remains in readback", kind="verification_required", verification_required=True)
            except FuploadError as exc:
                if accepted:
                    exc.verification_required = True
                exc.details.update({"completed": completed, "id": ident, "automatic_retry": False})
                raise
            completed.append({"id": ident, "deleted": True, "readback": {"present": False}})
        return {"items": completed, "deleted": len(completed)}

    def rename_backup(self, doc: Mapping[str, Any]) -> Dict[str, Any]:
        ident = _positive(doc.get("id"), "$.id")
        name = doc.get("name")
        if not isinstance(name, str) or not name.strip():
            raise ValidationError("expected a nonempty name", path="$.name")
        self.cloud_backup(ident)
        self.backup_post("/share/update", {"t_id": ident, "t_name": name})
        try:
            readback = self.cloud_backup(ident)
        except FuploadError as exc:
            exc.verification_required = True
            exc.details.update({"id": ident, "automatic_retry": False})
            raise
        if readback["name"] != name:
            raise FuploadError("backup rename did not match readback", kind="verification_required", verification_required=True)
        return {"id": ident, "readback": readback}

    def _upload_backup_zip(self, path: Path, file_type: str) -> str:
        prepared = self.backup_post("/share/generate_upload_url_v2", {"file_type": file_type, "file_size": path.stat().st_size})
        if not isinstance(prepared, dict) or not isinstance(prepared.get("file_path"), str) or not prepared["file_path"] or not isinstance(prepared.get("upload_url"), str):
            raise FuploadError("backup upload preparation omitted required values", kind="platform_data_error")
        parsed = urllib.parse.urlsplit(prepared["upload_url"])
        # The desktop API still returns this OSS bucket with an http scheme.
        # OSS signs host/path/query, so use the same signed object over TLS.
        if parsed.scheme.casefold() == "http" and parsed.hostname == "wclboxdata.cn-hangzhou.oss.aliyuncs.com" and parsed.port in (None, 80):
            parsed = parsed._replace(scheme="https", netloc=parsed.hostname)
        if parsed.scheme.casefold() != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
            raise FuploadError("backup object URL was not HTTPS", kind="trust_boundary")
        connection = http.client.HTTPSConnection(parsed.hostname, parsed.port, timeout=600)
        try:
            target = parsed.path + (("?" + parsed.query) if parsed.query else "")
            with path.open("rb") as handle:
                # Axios' default PUT content type is part of this OSS signature.
                connection.request("PUT", target, body=handle, headers={"Content-Length": str(path.stat().st_size),
                                                                         "Content-Type": "application/x-www-form-urlencoded"})
                response = connection.getresponse()
                response.read()
            if response.status != 200:
                raise FuploadError("backup object upload failed", stage="binary_upload", http_status=response.status)
        except (OSError, http.client.HTTPException) as exc:
            raise FuploadError("backup object upload result is uncertain", stage="binary_upload", verification_required=True) from exc
        finally:
            connection.close()
        return prepared["file_path"]

    def upload_backup(self, doc: Mapping[str, Any]) -> Dict[str, Any]:
        if "name" in doc and (not isinstance(doc["name"], str) or not doc["name"].strip()):
            raise ValidationError("expected a nonempty name", path="$.name")
        bundle_file = Path(doc["bundle_file"]).resolve()
        try:
            bundle = json.loads(bundle_file.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise ValidationError("backup bundle cannot be read", path="$.bundle_file") from exc
        if not isinstance(bundle, dict) or bundle.get("schema") != BUNDLE_SCHEMA or not isinstance(bundle.get("manifest"), dict) or set(bundle["manifest"]) != MANIFEST_KEYS:
            raise ValidationError("unsupported backup bundle", path="$.bundle_file")
        manifest = copy.deepcopy(bundle["manifest"])
        _positive(manifest["versionid"], "$.bundle_file.manifest.versionid")
        for field in ("knowplug_list", "t_unKnown_list", "t_font_list", "t_material_list", "t_WTF_list", "wtf"):
            if not isinstance(manifest[field], list):
                raise ValidationError("backup manifest lists must be arrays", path="$.bundle_file.manifest." + field)
        if any(manifest[field] is not None for field in ("wtfconfig", "unknown_plug", "material", "font", "font_hash")) or manifest["t_WTF_list"]:
            raise ValidationError("bundle must contain local pending uploads, not existing object references", path="$.bundle_file.manifest")
        account_names = set()
        for account in manifest["wtf"]:
            if not isinstance(account, dict) or account.get("commonConfig") != "" or not isinstance(account.get("server"), list):
                raise ValidationError("invalid pending WTF account", path="$.bundle_file.manifest.wtf")
            account_name = _name(account.get("account"), "$.bundle_file.manifest.wtf.account").casefold()
            if account_name in account_names:
                raise ValidationError("duplicate WTF account", path="$.bundle_file.manifest.wtf")
            account_names.add(account_name)
            server_names = set()
            for server in account["server"]:
                if not isinstance(server, dict) or not isinstance(server.get("roleList"), list) or any(not isinstance(role, dict) or role.get("zip") != "" for role in server["roleList"]):
                    raise ValidationError("invalid pending WTF role", path="$.bundle_file.manifest.wtf")
                server_name = _name(server.get("serverName"), "$.bundle_file.manifest.wtf.serverName").casefold()
                if server_name in server_names:
                    raise ValidationError("duplicate WTF server", path="$.bundle_file.manifest.wtf")
                server_names.add(server_name)
                _selection_names(server["roleList"], "wtf.roleList")
        files = []
        targets = set()
        artifact_names = set()
        allowed_categories = {"unknown_plug", "material", "wtfserve", "wtfrole"}
        if not isinstance(bundle.get("artifacts"), list):
            raise ValidationError("backup artifacts must be an array", path="$.bundle_file.artifacts")
        for artifact in bundle.get("artifacts", []):
            if not isinstance(artifact, dict):
                raise ValidationError("backup artifact must be an object", path="$.bundle_file.artifacts")
            path = _local(bundle_file.parent, _name(artifact.get("file"), "$.bundle_file.artifacts.file"))
            if path.name.casefold() in artifact_names:
                raise ValidationError("backup artifact repeats a filename", path="$.bundle_file.artifacts")
            artifact_names.add(path.name.casefold())
            if artifact.get("file_type") not in allowed_categories or not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != artifact.get("sha256") or path.stat().st_size != artifact.get("size"):
                raise ValidationError("backup archive changed or has an invalid type", path="$.bundle_file.artifacts")
            target = artifact.get("target")
            valid = target == ["unknown_plug"] and artifact["file_type"] == "unknown_plug" or target == ["material"] and artifact["file_type"] == "material"
            if artifact["file_type"] == "wtfserve":
                valid = isinstance(target, list) and len(target) == 3 and target[0] == "wtf" and type(target[1]) is int and target[1] >= 0 and target[2] == "commonConfig"
            if artifact["file_type"] == "wtfrole":
                valid = isinstance(target, list) and len(target) == 7 and target[0] == "wtf" and target[2] == "server" and target[4] == "roleList" and target[6] == "zip" and all(type(target[i]) is int and target[i] >= 0 for i in (1, 3, 5))
            if not valid:
                raise ValidationError("invalid backup artifact target", path="$.bundle_file.artifacts.target")
            target_key = tuple(target)
            if target_key in targets:
                raise ValidationError("duplicate backup artifact target", path="$.bundle_file.artifacts.target")
            targets.add(target_key)
            try:
                parent = manifest
                for key in target[:-1]:
                    parent = parent[key]
                if parent[target[-1]] not in (None, ""):
                    raise ValueError()
            except (KeyError, IndexError, TypeError, ValueError) as exc:
                raise ValidationError("invalid backup artifact target", path="$.bundle_file.artifacts.target") from exc
            _validate_zip_selection(path, artifact, manifest)
            files.append((artifact, path))
        for field, manifest_field in (("unknown_plug", "t_unKnown_list"), ("material", "t_material_list")):
            if bool(manifest[manifest_field]) != ((field,) in targets):
                raise ValidationError("component selection has no matching archive", path="$.bundle_file.artifacts")
        for ai, account in enumerate(manifest["wtf"]):
            for si, server in enumerate(account["server"]):
                for ri, _role in enumerate(server["roleList"]):
                    if ("wtf", ai, "server", si, "roleList", ri, "zip") not in targets:
                        raise ValidationError("selected WTF role has no archive", path="$.bundle_file.artifacts")
        if bool(bundle.get("font_directory")) != bool(manifest["t_font_list"]):
            raise ValidationError("font selection has no matching local files", path="$.bundle_file.font_directory")
        if not files and not manifest["knowplug_list"] and not bundle.get("font_directory"):
            raise ValidationError("backup bundle has no selected content", path="$.bundle_file")
        if bundle.get("font_directory"):
            font_directory = _local(bundle_file.parent, _name(bundle["font_directory"], "$.bundle_file.font_directory"))
            if not font_directory.is_dir():
                raise ValidationError("font directory is missing", path="$.bundle_file.font_directory")
            font_files = bundle.get("font_files", [])
            selected_fonts = _selection_names(manifest["t_font_list"], "t_font_list")
            if any(not name.casefold().endswith(".ttf") for name in selected_fonts) or not isinstance(font_files, list) or any(not isinstance(font, dict) for font in font_files):
                raise ValidationError("font selection is invalid", path="$.bundle_file.font_files")
            listed_fonts = _selection_names(font_files, "font_files")
            if not font_files or set(listed_fonts) != set(selected_fonts) or {p.name for p in font_directory.iterdir()} != set(selected_fonts):
                raise ValidationError("font selection changed", path="$.bundle_file.font_files")
            for font in font_files:
                path = _local(font_directory, _name(font.get("name"), "$.bundle_file.font_files.name"))
                metadata = next(row for row in manifest["t_font_list"] if row["name"] == font["name"])
                if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != font.get("sha256") or type(metadata.get("size")) is not int or path.stat().st_size != metadata["size"]:
                    raise ValidationError("font selection changed", path="$.bundle_file.font_files")
            _newbee_archive()
            if not shutil.which("node"):
                raise FuploadError("Node.js is required for the official font uploader", kind="dependency_missing")
            # Reuse the provider's production uploadserver v3 content-index path;
            # folder index support is supplied by upload_backup_fonts below.
        if manifest["versionid"] not in {row["id"] for row in self.game_versions()["items"]}:
            raise ValidationError("game version is unavailable", path="$.bundle_file.manifest.versionid")
        before = {int(row["t_id"]) for row in self.cloud_backups_raw()}
        retained = []
        submitted = False
        ident = None
        try:
            for artifact, path in files:
                value = self._upload_backup_zip(path, artifact["file_type"])
                parent = manifest
                for key in artifact["target"][:-1]:
                    parent = parent[key]
                parent[artifact["target"][-1]] = value
                retained.append({"file_type": artifact["file_type"], "file_path": value})
            if bundle.get("font_directory"):
                manifest["font_hash"] = self.upload_backup_fonts(font_directory)
            self.backup_post("/v3/share/create", manifest)
            submitted = True
            rows = [row for row in self.cloud_backups_raw() if int(row["t_id"]) not in before and _manifest_matches(manifest, row)]
            if len(rows) != 1:
                raise FuploadError("created backup ID could not be resolved uniquely", kind="verification_required", verification_required=True)
            ident = int(rows[0]["t_id"])
            readback = self.cloud_backup(ident)
            if "name" in doc:
                readback = self.rename_backup({"id": ident, "name": doc["name"]})["readback"]
            return {"id": ident, "uploaded": len(retained), "readback": readback}
        except FuploadError as exc:
            if submitted:
                exc.verification_required = True
            exc.details.update({"retained_uploads": retained, "automatic_retry": False})
            if ident is not None:
                exc.details["id"] = ident
            raise
