"""Local backup packages and the official Workshop backup upload protocol.

Protocol source: installed @heybox/hb-pc-workshop-sdk 1.1.1,
dist/index.esm.js:130608-131205. No desktop login state is imported.
"""
from __future__ import annotations

import base64
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from pathlib import PurePosixPath
import re
import time
from typing import Mapping
from urllib.parse import urlsplit
import zipfile

from .errors import FuploadError, ValidationError

BACKUP_CREATE = "/wow/create_backup/"
BACKUP_CREDENTIAL = "/wow/get_user_backup_credential/"
BACKUP_SAVE = "/wow/save_user_configuration/"
PACKAGE_SCHEMA = "fupload.blackbox.backup-package.v1"
_CATEGORIES = {
    "unknown_addons": ("UnknownAddons", "unknownModules", ("Interface", "AddOns"), "unknown.zip"),
    "materials": ("Materials", "materials", ("Interface",), "materials.zip"),
    "fonts": ("Fonts", "fonts", ("Fonts",), "fonts.zip"),
}
_SKIP_FILES = {"heyboxplayerinfo.lua", "heyboxplayerinfo.lua.bak"}
_PLAYER_FILES = {"addons.txt", "cache.md5", "chat-cache.txt", "config-cache.wtf", "layout-local.txt"}


def _json(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _hash(path, algorithm):
    digest = hashlib.new(algorithm)
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _name(value):
    if not isinstance(value, str) or not value or value in {".", ".."} or value.endswith((" ", ".")) or any(char in value for char in '/\\:<>"|?*\r\n\0'):
        raise ValidationError("backup selections must be plain file or directory names")
    return value


def _safe_path(path, root):
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError as exc:
        raise ValidationError("backup path escapes its selected root") from exc
    # Reject links/junctions at every level, including a selected parent.
    current = path
    while True:
        try:
            stat = current.lstat()
        except OSError as exc:
            raise ValidationError("selected backup path is unavailable") from exc
        if current.is_symlink() or getattr(stat, "st_file_attributes", 0) & 0x400:
            raise ValidationError("backup paths must not contain links or junctions")
        if current == root:
            break
        if current.parent == current:
            raise ValidationError("backup path is outside its selected root")
        current = current.parent
    return path


def _source_files(source, root):
    _safe_path(source, root)
    if source.is_file():
        return [] if source.name.lower() in _SKIP_FILES else [source]
    if not source.is_dir():
        raise ValidationError("selected backup source is not a directory or file")
    files = []
    for path in sorted(source.rglob("*")):
        _safe_path(path, root)
        if path.is_file() and path.name.lower() not in _SKIP_FILES:
            files.append(path)
    return files


def _characters(account):
    rows = []
    for realm in sorted(account.iterdir()):
        if realm.name.lower() == "savedvariables" or not realm.is_dir():
            continue
        _safe_path(realm, account)
        for player in sorted(realm.iterdir()):
            if not player.is_dir():
                continue
            _safe_path(player, account)
            if any(path.is_file() and path.name.lower() in _PLAYER_FILES for path in player.iterdir()):
                rows.append({"Realm": realm.name, "Player": player.name})
    return rows


def _known_addons(value):
    if not isinstance(value, list) or any(not isinstance(row, Mapping) or not row.get("ID") or not isinstance(row.get("Name"), str) or not row.get("VersionID") or isinstance(row.get("Strategy"), bool) or row.get("Strategy") not in {1, 2, 3, 4, 5} for row in value):
        raise ValidationError("known_addons must contain official backup briefs with ID,Name,Strategy,VersionID")
    if len({str(row["ID"]) for row in value}) != len(value):
        raise ValidationError("known_addons contains duplicate IDs")
    return value


class BlackboxBackupMixin:
    def backup_scan(self, doc):
        root_value, server = doc.get("game_dir"), doc.get("strappid")
        if not isinstance(root_value, str) or not isinstance(server, str) or not re.fullmatch(r"wow[a-z0-9_]+", server):
            raise ValidationError("game_dir and strappid are required")
        root = Path(root_value).absolute()
        if not root.is_dir():
            raise ValidationError("game_dir must be an existing game branch directory")
        _safe_path(root, root)
        def children(parts, *, files=False):
            directory = root.joinpath(*parts)
            if not directory.exists():
                return []
            _safe_path(directory, root)
            result = []
            for child in sorted(directory.iterdir()):
                _safe_path(child, root)
                if (child.is_file() and files) or (child.is_dir() and not files):
                    result.append(child)
            return result
        accounts = []
        for account in children(("WTF", "Account")):
            if account.name.lower() == "savedvariables":
                continue
            characters = _characters(account)
            if characters:
                accounts.append({"name": account.name, "characters": [{"realm": row["Realm"], "player": row["Player"]} for row in characters]})
        return {"strappid": server, "game_dir": str(root),
                "unknown_addons": [row.name for row in children(("Interface", "AddOns")) if row.name.lower() != "heyboxplayerinfo"],
                "materials": [row.name for row in children(("Interface",)) if row.name.lower() != "addons"],
                "fonts": [row.name for row in children(("Fonts",), files=True) if row.suffix.lower() == ".ttf"],
                "wtf_accounts": accounts, "addon_classification": "folder_candidates_without_remote_module_identification"}

    def backup_create(self, doc):
        if doc.get("file"):
            if any(key in doc for key in ("game_dir", "output_dir", "strappid", "unknown_addons", "wtf_accounts", "materials", "fonts", "known_addons", "strategies")):
                raise ValidationError("file cannot be combined with local backup generation fields")
            return self.backup_upload(doc)
        generated = self.backup_generate(doc)
        if doc.get("dry_run"):
            return {**generated, "operation": "backup.create"}
        try:
            result = self.backup_upload({"file": generated["file"]})
        except FuploadError as exc:
            exc.details = {**exc.details, "file": generated["file"]}
            raise
        return {**result, "file": generated["file"]}

    def backup_generate(self, doc):
        root_value, output_value = doc.get("game_dir"), doc.get("output_dir")
        if not isinstance(root_value, str) or not isinstance(output_value, str):
            raise ValidationError("game_dir and output_dir are required")
        root, output = Path(root_value).absolute(), Path(output_value).absolute()
        if not root.is_dir():
            raise ValidationError("game_dir must be an existing game branch directory", path="$.game_dir")
        _safe_path(root, root)
        server = doc.get("strappid")
        if not isinstance(server, str) or not re.fullmatch(r"wow[a-z0-9_]+", server):
            raise ValidationError("strappid must be a WoW game branch identifier", path="$.strappid")
        known = deepcopy(_known_addons(doc.get("known_addons", [])))
        jobs = []
        for key, (field, file_type, parts, filename) in _CATEGORIES.items():
            names = doc.get(key)
            if not isinstance(names, list) or any(not isinstance(value, str) for value in names):
                raise ValidationError(f"{key} must be an explicit array of selected names", path=f"$.{key}")
            if len({value.lower() for value in names}) != len(names):
                raise ValidationError(f"{key} contains duplicate names")
            sources = []
            for name in names:
                name = _name(name)
                if key == "materials" and name.lower() == "addons":
                    raise ValidationError("Interface/AddOns must use unknown_addons, not materials")
                source = root.joinpath(*parts, name)
                if not source.exists() or (key == "fonts" and (not source.is_file() or source.suffix.lower() != ".ttf")) or (key != "fonts" and not source.is_dir()):
                    raise ValidationError(f"selected {key} source does not exist or has the wrong type")
                sources.append(source)
            if sources:
                jobs.append({"field": field, "file_type": file_type, "filename": filename, "base": root.joinpath(*parts), "sources": sources})
        accounts = doc.get("wtf_accounts")
        if not isinstance(accounts, list) or any(not isinstance(value, Mapping) or set(value) != {"name", "characters"} for value in accounts):
            raise ValidationError("wtf_accounts must contain explicit {name,characters:[{realm,player}]} selections", path="$.wtf_accounts")
        if any(not isinstance(value.get("name"), str) for value in accounts):
            raise ValidationError("each WTF account requires a name")
        if len({value["name"].lower() for value in accounts}) != len(accounts):
            raise ValidationError("wtf_accounts contains duplicate names")
        for account_selection in accounts:
            account_name = _name(account_selection["name"])
            source = root / "WTF" / "Account" / account_name
            if not source.is_dir():
                raise ValidationError("selected WTF account does not exist")
            _safe_path(source, root)
            available = {(row["Realm"], row["Player"]) for row in _characters(source)}
            selected = account_selection["characters"]
            if not isinstance(selected, list) or not selected:
                raise ValidationError("each WTF account requires at least one explicit character")
            characters, seen_characters = [], set()
            for character in selected:
                if not isinstance(character, Mapping) or set(character) != {"realm", "player"}:
                    raise ValidationError("WTF characters must contain exactly realm and player")
                realm, player = _name(character["realm"]), _name(character["player"])
                identity = (realm, player)
                if identity not in available or identity in seen_characters:
                    raise ValidationError("selected WTF character is unavailable or duplicated")
                seen_characters.add(identity)
                characters.append({"Realm": realm, "Player": player})
            # Account-level settings and SavedVariables are shared by selected
            # characters. Other character directories never enter the archive.
            entries = []
            for child in sorted(source.iterdir()):
                _safe_path(child, root)
                if child.is_file() or (child.is_dir() and child.name.lower() == "savedvariables"):
                    entries.extend(_source_files(child, root))
            for character in characters:
                entries.extend(_source_files(source / character["Realm"] / character["Player"], root))
            jobs.append({"field": "WTFList", "file_type": "wtf", "filename": f"account_{account_name}.zip",
                         "account_name": account_name, "characters": characters, "base": source.parent, "sources": [source], "selected_files": entries})
        if not known and not jobs:
            raise ValidationError("at least one addon, account, material or font must be selected")
        for job in jobs:
            job["entries"] = []
            job["files"] = []
            for source in job["sources"]:
                files = job.get("selected_files") if "selected_files" in job else _source_files(source, root)
                job["files"].append({"Name": source.name, "Size": sum(path.stat().st_size for path in files)})
                job["entries"].extend((path, path.relative_to(job["base"]).as_posix()) for path in files)
            if not job["entries"]:
                raise ValidationError("a selected backup category contains no files")
        try:
            output.resolve().relative_to(root.resolve())
        except ValueError:
            pass
        else:
            raise ValidationError("output_dir must be outside game_dir")
        if output.exists():
            raise ValidationError("output_dir must not already exist", path="$.output_dir")
        strategies = doc.get("strategies", [])
        if not isinstance(strategies, list) or any(not isinstance(item, Mapping) for item in strategies):
            raise ValidationError("strategies must be an array of official strategy objects")
        summary = {"strappid": server, "archive_count": len(jobs), "known_addon_count": len(known),
                   "source_bytes": sum(item["Size"] for job in jobs for item in job["files"])}
        if doc.get("dry_run"):
            return {"dry_run": True, "operation": "backup.generate", **summary}
        output.mkdir(parents=True)
        archives = []
        configuration = {"HeyboxID": 0, "Name": "", "SaveTime": int(time.time()), "IsClassic": server != "wowretail",
                         "Strappid": server, "KnownAddons": known, "WTFList": []}
        if strategies:
            configuration["Strategies"] = deepcopy(strategies)
        for job in jobs:
            archive_path = output / job["filename"]
            with zipfile.ZipFile(archive_path, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
                for path, name_in_zip in job["entries"]:
                    before = path.stat()
                    archive.write(path, name_in_zip)
                    after = path.stat()
                    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                        raise FuploadError("backup source changed while packaging", kind="verification_required", verification_required=True)
            descriptor = {"Files": job["files"], "Size": archive_path.stat().st_size,
                          "MD5": _hash(archive_path, "md5"), "Host": "", "Path": ""}
            if job["field"] == "WTFList":
                descriptor.update({"Name": job["account_name"], "Characters": [f'{row["Realm"]} - {row["Player"]}' for row in job["characters"]],
                                   "RealmCharacters": job["characters"]})
                configuration["WTFList"].append(descriptor)
            else:
                configuration[job["field"]] = descriptor
            archives.append({"field": job["field"], "account_name": job.get("account_name"),
                             "file_type": job["file_type"], "file": job["filename"],
                             "bytes": descriptor["Size"], "md5": descriptor["MD5"], "sha256": _hash(archive_path, "sha256")})
        manifest = {"schema": PACKAGE_SCHEMA, "configuration": configuration, "archives": archives, "source_bytes": summary["source_bytes"]}
        manifest_path = output / "backup.json"
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return {"created": True, "file": str(manifest_path), **summary}

    def _load_backup_package(self, file_path):
        if not isinstance(file_path, str) or not Path(file_path).is_file():
            raise ValidationError("file must identify a generated backup.json package", path="$.file")
        path = Path(file_path).absolute()
        try:
            manifest = json.loads(path.read_text(encoding="utf-8"))
        except (ValueError, OSError) as exc:
            raise ValidationError("backup package manifest is invalid") from exc
        if not isinstance(manifest, Mapping) or manifest.get("schema") != PACKAGE_SCHEMA or not isinstance(manifest.get("configuration"), dict) or not isinstance(manifest.get("archives"), list):
            raise ValidationError("backup package schema is invalid")
        configuration = manifest["configuration"]
        allowed_fields = {"HeyboxID", "Name", "SaveTime", "IsClassic", "Strappid", "KnownAddons", "WTFList", "Strategies", "UnknownAddons", "Materials", "Fonts"}
        server = configuration.get("Strappid")
        if set(configuration) - allowed_fields or isinstance(configuration.get("HeyboxID"), bool) or configuration.get("HeyboxID") != 0 or not isinstance(server, str) or not re.fullmatch(r"wow[a-z0-9_]+", server) or configuration.get("IsClassic") is not (server != "wowretail"):
            raise ValidationError("backup package identity is invalid")
        _known_addons(configuration.get("KnownAddons"))
        accounts = configuration.get("WTFList")
        if not isinstance(accounts, list) or any(not isinstance(row, Mapping) or not isinstance(row.get("Name"), str) for row in accounts):
            raise ValidationError("backup package WTF descriptors are invalid")
        if len({row["Name"].lower() for row in accounts}) != len(accounts):
            raise ValidationError("backup package contains duplicate WTF accounts")
        seen, categories = set(), set()
        total_source_bytes = 0
        for item in manifest["archives"]:
            if not isinstance(item, Mapping):
                raise ValidationError("backup package archive descriptor is invalid")
            name = _name(item.get("file"))
            archive_path = _safe_path(path.parent / name, path.parent)
            if name.lower() in seen or not archive_path.is_file() or not zipfile.is_zipfile(archive_path):
                raise ValidationError("backup package archive is invalid or duplicated")
            seen.add(name.lower())
            if archive_path.stat().st_size != item.get("bytes") or _hash(archive_path, "md5") != item.get("md5") or _hash(archive_path, "sha256") != item.get("sha256"):
                raise ValidationError("backup package archive hash or size does not match")
            descriptor = self._package_descriptor(configuration, item)
            if descriptor.get("Size") != item["bytes"] or descriptor.get("MD5") != item["md5"] or descriptor.get("Host") or descriptor.get("Path"):
                raise ValidationError("backup package configuration does not match its archives")
            identity = (item["field"], item.get("account_name") if item["field"] == "WTFList" else None)
            if identity in categories:
                raise ValidationError("backup package repeats an archive category")
            categories.add(identity)
            files = descriptor.get("Files")
            if not isinstance(files, list) or not files:
                raise ValidationError("backup package archive file list is invalid")
            expected_sizes = {}
            for entry in files:
                if not isinstance(entry, Mapping):
                    raise ValidationError("backup package file entry is invalid")
                source_name, size = _name(entry.get("Name")), entry.get("Size")
                if source_name in expected_sizes or isinstance(size, bool) or not isinstance(size, int) or size < 0:
                    raise ValidationError("backup package source size or name is invalid")
                expected_sizes[source_name] = size
            selected_characters = None
            if item["field"] == "WTFList":
                pairs = descriptor.get("RealmCharacters")
                if not isinstance(pairs, list) or not pairs or any(not isinstance(row, Mapping) or set(row) != {"Realm", "Player"} for row in pairs):
                    raise ValidationError("backup package requires explicit WTF RealmCharacters")
                selected_characters = {(_name(row["Realm"]), _name(row["Player"])) for row in pairs}
                if len(selected_characters) != len(pairs) or descriptor.get("Characters") != [f'{row["Realm"]} - {row["Player"]}' for row in pairs]:
                    raise ValidationError("backup package WTF character metadata is inconsistent")
                if set(expected_sizes) != {descriptor["Name"]}:
                    raise ValidationError("backup package WTF archive must identify exactly its selected account")
            actual_sizes, seen_paths = {}, set()
            with zipfile.ZipFile(archive_path) as archive:
                for info in archive.infolist():
                    name_in_zip = PurePosixPath(info.filename)
                    if name_in_zip.is_absolute() or not name_in_zip.parts or any(part in {".", ".."} for part in name_in_zip.parts) or "\\" in info.filename or ":" in info.filename or info.filename.lower() in seen_paths or ((info.external_attr >> 16) & 0o170000) == 0o120000:
                        raise ValidationError("backup package ZIP contains an invalid entry")
                    seen_paths.add(info.filename.lower())
                    if name_in_zip.name.lower() in _SKIP_FILES:
                        raise ValidationError("backup package includes excluded player telemetry files")
                    if selected_characters is not None and len(name_in_zip.parts) > 2 and name_in_zip.parts[1].lower() != "savedvariables":
                        if len(name_in_zip.parts) < 4 or (name_in_zip.parts[1], name_in_zip.parts[2]) not in selected_characters:
                            raise ValidationError("backup package contains an unselected WTF character")
                    top = name_in_zip.parts[0]
                    actual_sizes[top] = actual_sizes.get(top, 0) + info.file_size
            if actual_sizes != expected_sizes:
                raise ValidationError("backup package ZIP layout or source sizes do not match")
            total_source_bytes += sum(expected_sizes.values())
            item["local_path"] = archive_path
        expected_categories = {(key, None) for key in ("UnknownAddons", "Materials", "Fonts") if key in configuration}
        expected_categories.update(("WTFList", row["Name"]) for row in accounts)
        if categories != expected_categories or (not categories and not configuration.get("KnownAddons")):
            raise ValidationError("backup package is missing archive descriptors")
        if isinstance(manifest.get("source_bytes"), bool) or not isinstance(manifest.get("source_bytes"), int) or manifest["source_bytes"] != total_source_bytes:
            raise ValidationError("backup package source_bytes is invalid")
        return manifest

    @staticmethod
    def _package_descriptor(configuration, item):
        field = item.get("field")
        expected_type = {"UnknownAddons": "unknownModules", "Materials": "materials", "Fonts": "fonts", "WTFList": "wtf"}.get(field)
        if expected_type is None or item.get("file_type") != expected_type:
            raise ValidationError("backup package category is invalid")
        if field == "WTFList":
            rows = [row for row in configuration.get("WTFList", []) if row.get("Name") == item.get("account_name")]
            if len(rows) != 1:
                raise ValidationError("backup package WTF account descriptor is ambiguous")
            return rows[0]
        value = configuration.get(field)
        if not isinstance(value, dict):
            raise ValidationError("backup package file category descriptor is missing")
        return value

    def backup_upload(self, doc):
        manifest = self._load_backup_package(doc.get("file"))
        if doc.get("dry_run"):
            return {"dry_run": True, "operation": "backup.upload", "archive_count": len(manifest["archives"]),
                    "source_bytes": manifest["source_bytes"], "strappid": manifest["configuration"]["Strappid"]}
        created = self._config_request(BACKUP_CREATE, write=True)
        backup_id = created.get("ID")
        if not backup_id:
            raise FuploadError("Backup allocation did not return an ID", kind="verification_required", verification_required=True)
        try:
            maximum = created.get("MaxSize")
            if isinstance(maximum, bool) or not isinstance(maximum, (int, float)) or maximum < 0:
                raise FuploadError("Backup allocation did not return a valid size limit", kind="verification_required", verification_required=True)
            if manifest["source_bytes"] > maximum:
                raise ValidationError("selected backup files exceed the server's maximum size")
            configuration = deepcopy(manifest["configuration"])
            configuration["ID"] = backup_id
            configuration["SaveTime"] = int(time.time())
            for item in manifest["archives"]:
                descriptor = self._package_descriptor(configuration, item)
                context = self._config_request(BACKUP_CREDENTIAL, query={"backup_id": str(backup_id), "file_type": item["file_type"]})
                host, remote_path = self._upload_backup_archive(item["local_path"], context, item["md5"])
                descriptor.update(Host=host, Path=remote_path)
            encoded = base64.b64encode(_json(configuration).encode("utf-8")).decode("ascii")
            self._config_request(BACKUP_SAVE, query={"backup_id": backup_id}, body={"configuration": encoded}, write=True)
            current = self._backup_detail(backup_id)
            expected_fields = {key: value for key, value in configuration.items() if key not in {"HeyboxID", "Name", "SaveTime"}}
            if any(current.get(key) != value for key, value in expected_fields.items()):
                raise FuploadError("Backup upload was not confirmed by readback", kind="verification_required", verification_required=True)
            return {"accepted": True, "verified": True, "backup_id": str(backup_id), "archive_count": len(manifest["archives"]),
                    "readback": self._redact(current)}
        except FuploadError as exc:
            exc.verification_required = True
            exc.details = {**exc.details, "backup_id": str(backup_id)}
            raise

    @staticmethod
    def _upload_backup_archive(path, context, expected_md5):
        cos_url = urlsplit(str(context.get("cos") or ""))
        hostname = cos_url.hostname or ""
        if cos_url.scheme != "https" or not re.fullmatch(r"[a-z0-9-]+\.cos\.ap-(?:shanghai|beijing)\.myqcloud\.com", hostname) or cos_url.username or cos_url.password:
            raise FuploadError("Backup upload returned an invalid COS origin", kind="verification_required", verification_required=True)
        credential_group = context.get("Credentials")
        credentials = credential_group.get("Credentials") if isinstance(credential_group, Mapping) else None
        if not isinstance(credentials, Mapping) or not all(credentials.get(key) for key in ("TmpSecretID", "TmpSecretKey", "Token")) or not isinstance(context.get("path"), str) or not context["path"] or not isinstance(context.get("host"), str) or not context["host"]:
            raise FuploadError("Backup upload credentials are incomplete", kind="verification_required", verification_required=True)
        try:
            from qcloud_cos import CosConfig, CosS3Client
        except ImportError as exc:
            raise FuploadError("The managed runtime is missing the COS SDK", kind="environment_error", details={"repair_command": "fupload update"}) from exc
        try:
            client = CosS3Client(CosConfig(Region="ap-shanghai" if ".ap-shanghai." in hostname else "ap-beijing",
                SecretId=credentials["TmpSecretID"], SecretKey=credentials["TmpSecretKey"], Token=credentials["Token"], Scheme="https"), retry=0)
            with path.open("rb") as stream:
                # The Python SDK passes ContentLength directly into requests headers.
                response = client.put_object(Bucket=hostname.split(".")[0], Key=context["path"], Body=stream,
                                             ContentLength=str(path.stat().st_size), StorageClass="STANDARD", EnableMD5=True)
        except Exception as exc:
            raise FuploadError("Backup COS upload was interrupted", verification_required=True) from exc
        etag = next((str(value).strip('"').lower() for key, value in response.items() if key.lower() == "etag"), None) if isinstance(response, Mapping) else None
        if etag != expected_md5:
            raise FuploadError("Backup COS upload checksum was not confirmed", kind="verification_required", verification_required=True)
        return context["host"], context["path"]
