"""Configuration shares and backup management using the observed Workshop API.

Backup creation belongs to the desktop IPC implementation. This module only
uses verified web routes; it never treats a module ZIP upload as a backup.
"""
from __future__ import annotations

from copy import deepcopy
import json
import time
from typing import Any, Mapping

from .errors import FuploadError, ValidationError


BACKUP_LIST = "/wow/get_user_configuration_backup_list/"
BACKUP_REMOVE = "/wow/remove_user_configuration_backup/"
BACKUP_RENAME = "/wow/rename_user_configuration_backup/"
SHARE_LIST = "/wow/v2/share/list/"
SHARE_DETAIL = "/wow/v2/share/detail/"
SHARE_CREATE = "/wow/create_config_share/"
SHARE_UPDATE = "/wow/update_config_share/"

CONFIG_FIELDS = frozenset({
    "Open", "Title", "Article", "UpdateLog", "KnownAddons", "UnknownAddons",
    "WTFList", "Materials", "Fonts", "ClearKnownAddons", "ClearUnknownAddons",
    "ClearMaterials", "ClearFonts", "ThumbList", "SubscribeLevel",
    "ChatInviteCode", "NeedsPush",
})
SELECTION_FIELDS = frozenset({"KnownAddons", "UnknownAddons", "WTFList", "Materials", "Fonts"})


class BlackboxConfigMixin:
    """Methods mixed into Blackbox, sharing its fixed transport and redaction."""

    def _config_request(self, path, *, query=None, body=None, write=False):
        try:
            payload = self._request("POST", path, body=body, query=query)
        except FuploadError as exc:
            if write:
                exc.verification_required = True
            raise
        if not isinstance(payload, Mapping) or payload.get("status") != "ok":
            raise FuploadError(
                "Workshop configuration request was rejected",
                endpoint=path, business_code=payload.get("status") if isinstance(payload, Mapping) else None,
                verification_required=write,
            )
        result = payload.get("result")
        if not isinstance(result, Mapping):
            # Write responses may intentionally have an empty result.
            if write and result is None:
                return {}
            raise FuploadError("Workshop configuration response is invalid", endpoint=path,
                               verification_required=write)
        return deepcopy(dict(result))

    @staticmethod
    def _config_id(value, name):
        if isinstance(value, bool) or value is None or not isinstance(value, (str, int)) or not str(value).strip():
            raise ValidationError(f"{name} is required", path=f"$.{name}")
        # Share/backup IDs are opaque. Do not coerce UUIDs or large decimal IDs.
        return str(value)

    @staticmethod
    def _remote_id(value):
        return isinstance(value, (str, int)) and not isinstance(value, bool) and bool(str(value).strip())

    @staticmethod
    def _share_server(row):
        # Same branch used by the official client after publishing a share.
        if row.get("IsClassic") is False:
            return "wowretail"
        server = row.get("Strappid")
        if isinstance(server, str) and server:
            return server
        if row.get("IsClassic") is True:
            return "wowclassicera"
        raise FuploadError("Backup game branch is unknown; references cannot be checked",
                           kind="verification_required", verification_required=True)

    def _backup_rows(self):
        result = self._config_request(BACKUP_LIST)
        rows = result.get("backupList")
        if not isinstance(rows, list) or any(not isinstance(row, dict) or not self._remote_id(row.get("ID")) for row in rows):
            raise FuploadError("Backup list response is incomplete", kind="verification_required", verification_required=True)
        ids = [str(row["ID"]) for row in rows]
        if len(set(ids)) != len(ids):
            raise FuploadError("Backup list contains duplicate IDs", kind="verification_required", verification_required=True)
        return rows

    def backup_list(self):
        rows = self._backup_rows()
        return {"total_count": len(rows), "backups": self._redact(rows), "complete": True}

    def _backup_detail(self, backup_id):
        wanted = self._config_id(backup_id, "backup_id")
        row = next((row for row in self._backup_rows() if str(row["ID"]) == wanted), None)
        if row is None:
            raise FuploadError("Backup was not found", kind="not_found", details={"backup_id": wanted})
        return row

    def backup_get(self, backup_id):
        return {"backup": self._redact(self._backup_detail(backup_id))}

    def _config_rows(self, strappid):
        if not isinstance(strappid, str) or not strappid.strip():
            raise ValidationError("strappid is required for configuration shares", path="$.strappid")
        limit = int(self.config.get("config_page_size", 20))
        max_pages = int(self.config.get("config_max_pages", 1000))
        if limit < 1 or max_pages < 1:
            raise ValidationError("configuration pagination limits must be positive")
        rows, seen = [], set()
        for page in range(max_pages):
            result = self._config_request(SHARE_LIST, query={
                "offset": page * limit, "limit": limit, "strappid": strappid,
                "sort_by": "weekDownloadNum", "my_publish": 1,
            })
            chunk = result.get("shares")
            if not isinstance(chunk, list):
                raise FuploadError("Share list response is incomplete", kind="verification_required", verification_required=True)
            # The client only declares completion on an empty page. A short
            # page alone must never authorize backup deletion.
            if not chunk:
                return rows
            for row in chunk:
                if not isinstance(row, dict) or not self._remote_id(row.get("ShareID")) or str(row["ShareID"]) in seen:
                    raise FuploadError("Share pagination did not advance or contains invalid IDs",
                                       kind="verification_required", verification_required=True)
                seen.add(str(row["ShareID"]))
                rows.append(row)
        raise FuploadError("Share pagination is incomplete", kind="verification_required", verification_required=True)

    def config_list(self, strappid):
        rows = self._config_rows(strappid)
        return {"total_count": len(rows), "configs": self._redact(rows), "complete": True}

    def _config_detail(self, share_id):
        wanted = self._config_id(share_id, "share_id")
        row = self._config_request(SHARE_DETAIL, query={"share_id": wanted})
        if str(row.get("ShareID", "")) != wanted or not self._remote_id(row.get("BackupID")):
            raise FuploadError("Share detail is incomplete or identifies another share",
                               kind="verification_required", verification_required=True)
        return row

    def config_get(self, share_id):
        return {"config": self._redact(self._config_detail(share_id))}

    def _configuration_patch(self, doc):
        patch = doc.get("configuration", {})
        if not isinstance(patch, Mapping):
            raise ValidationError("configuration must be an object", path="$.configuration")
        patch = deepcopy(dict(patch))
        unknown = sorted(set(patch) - CONFIG_FIELDS)
        if unknown:
            raise ValidationError("unsupported configuration fields: " + ", ".join(unknown), path="$.configuration")
        return patch

    @staticmethod
    def _validate_configuration(configuration):
        for field in ("Title", "Article", "UpdateLog", "ChatInviteCode"):
            if field in configuration and not isinstance(configuration[field], str):
                raise ValidationError(f"configuration.{field} must be a string")
        if not configuration.get("Title", "").strip():
            raise ValidationError("configuration.Title is required")
        # Official editor: title.replace(/[^\x00-\xff]/g, "ab").length <= 70.
        # JavaScript counts UTF-16 units, so an astral character weighs four.
        title_width = sum(1 if ord(char) <= 255 else 2 if ord(char) <= 65535 else 4
                          for char in configuration["Title"])
        if title_width > 70:
            raise ValidationError("configuration.Title exceeds the official weighted length limit of 70")
        for field in ("Open", "ClearKnownAddons", "ClearUnknownAddons", "ClearMaterials", "ClearFonts", "NeedsPush"):
            if field in configuration and not isinstance(configuration[field], bool):
                raise ValidationError(f"configuration.{field} must be a boolean")
        for field in ("KnownAddons", "WTFList", "ThumbList"):
            if not isinstance(configuration.get(field), list):
                raise ValidationError(f"configuration.{field} must be an array")
        if any(not isinstance(url, str) for url in configuration["ThumbList"]):
            raise ValidationError("configuration.ThumbList must contain strings")
        if configuration.get("Open") is True and not configuration["ThumbList"]:
            raise ValidationError("public configuration shares require at least one preview image")
        if any(not isinstance(row, Mapping) for field in ("KnownAddons", "WTFList") for row in configuration[field]):
            raise ValidationError("KnownAddons and WTFList must contain objects")
        for field in ("UnknownAddons", "Materials", "Fonts"):
            value = configuration.get(field)
            if field in configuration and (not isinstance(value, Mapping) or not isinstance(value.get("Files"), list)):
                raise ValidationError(f"configuration.{field} must contain a Files array")
        if not (configuration["KnownAddons"] or configuration["WTFList"] or any(
                configuration.get(field, {}).get("Files") for field in ("UnknownAddons", "Materials", "Fonts"))):
            raise ValidationError("configuration must select at least one content item from its backup")
        level = configuration.get("SubscribeLevel")
        if isinstance(level, bool) or not isinstance(level, int) or level < 0:
            raise ValidationError("configuration.SubscribeLevel must be a non-negative integer")

    def config_upsert(self, doc, *, create=False):
        patch = self._configuration_patch(doc)
        current = None if create else self._config_detail(doc.get("share_id"))
        backup_id = doc.get("backup_id", current.get("BackupID") if current else None)
        backup = self._backup_detail(backup_id)
        changed_backup = current and str(current["BackupID"]) != str(backup["ID"])
        if changed_backup:
            missing = sorted(SELECTION_FIELDS - patch.keys())
            if missing:
                raise ValidationError("changing backup_id requires explicit selection field(s): " + ", ".join(missing))
        configuration = deepcopy(backup)
        if current:
            missing = sorted({"Title", "Article", "Open", "KnownAddons", "WTFList", "ThumbList", "SubscribeLevel"} - current.keys())
            if missing:
                raise FuploadError("Share detail is missing fields required to preserve the current configuration",
                                   kind="verification_required", verification_required=True, details={"fields": missing})
            # The editor starts from the whole backup, then restores the share's
            # selection and content. Detail-only metadata is not a write field.
            for key in CONFIG_FIELDS - {"NeedsPush"}:
                if changed_backup and key in SELECTION_FIELDS:
                    continue
                if key in current:
                    self._set_config_field(configuration, key, current[key])
                elif key in {"UnknownAddons", "Materials", "Fonts"}:
                    configuration.pop(key, None)
            level = configuration.get("SubscribeLevel")
            if isinstance(level, Mapping):
                configuration["SubscribeLevel"] = level.get("level")
        else:
            required = {"Title", "Article", "Open", "ThumbList", "SubscribeLevel"} | SELECTION_FIELDS
            missing = sorted(required - patch.keys())
            if missing:
                raise ValidationError("configuration requires explicit field(s): " + ", ".join(missing))
            configuration.update({"UpdateLog": "<p><br></p>", "ClearKnownAddons": False,
                                  "ClearUnknownAddons": False, "ClearMaterials": False, "ClearFonts": False})
        for key, value in patch.items():
            self._set_config_field(configuration, key, value)
        self._validate_configuration(configuration)
        self._validate_selection(configuration, backup)
        # Empty optional file containers are omitted by the official publisher.
        for field in ("UnknownAddons", "Materials", "Fonts"):
            if field in configuration and not configuration[field]["Files"]:
                configuration.pop(field)
        server = self._share_server(backup)
        previous = {str(row["ShareID"]) for row in self._config_rows(server)} if create else set()
        query = {"backup_id": backup["ID"]}
        if current:
            query["share_id"] = current["ShareID"]
        if doc.get("dry_run"):
            return {"dry_run": True, "operation": "config.create" if create else "config.update",
                    "backup_id": str(backup["ID"]), "configuration": self._redact(configuration)}
        response = self._config_request(SHARE_CREATE if create else SHARE_UPDATE, query=query,
            body={"configuration": json.dumps(configuration, ensure_ascii=False, separators=(",", ":"))}, write=True)
        try:
            found = self._verify_config(configuration, server, current, previous)
        except FuploadError as exc:
            exc.verification_required = True
            raise
        return {"accepted": True, "verified": True, "share_id": str(found["ShareID"]),
                "backup_id": str(backup["ID"]), "readback": self._redact(found), "response": self._redact(response)}

    @staticmethod
    def _set_config_field(configuration, key, value):
        # The official editor replaces Files inside the original backup
        # container, retaining its archive URL and other backend metadata.
        if key in {"UnknownAddons", "Materials", "Fonts"} and isinstance(value, Mapping) and isinstance(configuration.get(key), Mapping):
            configuration[key] = {**deepcopy(configuration[key]), **deepcopy(dict(value))}
        else:
            configuration[key] = deepcopy(value)

    def _verify_config(self, expected, server, current, previous):
        attempts = max(1, int(self.config.get("verify_attempts", 10)))
        for attempt in range(attempts):
            if current:
                candidates = [self._config_detail(current["ShareID"])]
            else:
                # Live share summaries omit BackupID. Resolve each new owned
                # share before comparing its binding and full configuration.
                candidates = [self._config_detail(row["ShareID"]) for row in self._config_rows(server)
                              if str(row["ShareID"]) not in previous]
            matched = []
            for row in candidates:
                if str(row.get("BackupID")) != str(expected["ID"]):
                    continue
                actual = dict(row)
                if isinstance(actual.get("SubscribeLevel"), Mapping):
                    actual["SubscribeLevel"] = actual["SubscribeLevel"].get("level")
                fields = CONFIG_FIELDS - {"NeedsPush"}
                if all(actual.get(key) == expected[key] for key in fields if key in expected):
                    matched.append(row)
            if len(matched) == 1:
                return matched[0]
            if len(matched) > 1:
                raise FuploadError("Configuration create readback is ambiguous", kind="verification_required", verification_required=True)
            if attempt + 1 < attempts:
                time.sleep(float(self.config.get("verify_interval", 2)))
        raise FuploadError("Configuration write was not confirmed by readback", kind="verification_required", verification_required=True)

    def config_delete(self, doc):
        if not doc.get("dry_run") and doc.get("confirm_delete") is not True:
            raise ValidationError("confirm_delete must be true for configuration deletion", path="$.confirm_delete")
        current = self._config_detail(doc.get("share_id"))
        server = self._share_server(current)
        # Fetch an entire owned list before a delete, and identify this share.
        if not any(str(row["ShareID"]) == str(current["ShareID"]) for row in self._config_rows(server)):
            raise ValidationError("configuration share is not in the current user's published list")
        if doc.get("dry_run"):
            return {"dry_run": True, "operation": "config.delete", "share_id": str(current["ShareID"]), "backup_id": str(current["BackupID"])}
        self._config_request(SHARE_UPDATE, query={"share_id": current["ShareID"], "backup_id": current["BackupID"], "delete": 1}, write=True)
        try:
            if any(str(row["ShareID"]) == str(current["ShareID"]) for row in self._config_rows(server)):
                raise FuploadError("Configuration delete was not confirmed by readback", kind="verification_required", verification_required=True)
        except FuploadError as exc:
            exc.verification_required = True
            raise
        return {"accepted": True, "verified": True, "share_id": str(current["ShareID"])}

    def backup_rename(self, doc):
        row = self._backup_detail(doc.get("backup_id"))
        name = doc.get("name", doc.get("new_name"))
        if not isinstance(name, str) or not name.strip():
            raise ValidationError("name must be a non-empty string", path="$.name")
        if doc.get("dry_run"):
            return {"dry_run": True, "operation": "backup.rename", "backup_id": str(row["ID"]), "name": name}
        self._config_request(BACKUP_RENAME, query={"backup_id": row["ID"], "new_name": name}, write=True)
        try:
            current = self._backup_detail(row["ID"])
            if current.get("Name") != name:
                raise FuploadError("Backup rename was not confirmed by readback", kind="verification_required", verification_required=True)
        except FuploadError as exc:
            exc.verification_required = True
            raise
        return {"accepted": True, "verified": True, "backup_id": str(row["ID"]), "name": name}

    def _backup_delete_plan(self, doc):
        filter_fields = {"name_contains", "name_equals", "created_before", "created_after"}
        filters = {key: value for key, value in doc.items() if key in filter_fields and value is not None}
        values = doc.get("backup_ids")
        if values is None and doc.get("backup_id") is not None:
            values = [doc.get("backup_id")]
        if values is not None and filters:
            raise ValidationError("backup IDs and selection filters cannot be combined")
        rows = {str(row["ID"]): row for row in self._backup_rows()}
        if values is None and filters:
            for key in ("name_contains", "name_equals"):
                if key in filters and (not isinstance(filters[key], str) or not filters[key]):
                    raise ValidationError(f"{key} must be a non-empty string")
            for key in ("created_before", "created_after"):
                if key in filters and (isinstance(filters[key], bool) or not isinstance(filters[key], int) or filters[key] < 0):
                    raise ValidationError(f"{key} must be a non-negative Unix timestamp")
            values = []
            for backup_id, row in rows.items():
                name = row.get("Name")
                if not isinstance(name, str):
                    raise FuploadError("Backup name is unknown; selection is incomplete", kind="verification_required", verification_required=True)
                if "name_contains" in filters and filters["name_contains"] not in name:
                    continue
                if "name_equals" in filters and filters["name_equals"] != name:
                    continue
                if "created_before" in filters or "created_after" in filters:
                    saved = row.get("SaveTime")
                    if isinstance(saved, bool) or not isinstance(saved, (int, float)):
                        raise FuploadError("Backup creation time is unknown; selection is incomplete", kind="verification_required", verification_required=True)
                    if "created_before" in filters and saved >= filters["created_before"]:
                        continue
                    if "created_after" in filters and saved <= filters["created_after"]:
                        continue
                values.append(backup_id)
        elif not isinstance(values, list) or not values:
            raise ValidationError("backup_ids must be a non-empty array", path="$.backup_ids")
        ids = [self._config_id(value, "backup_id") for value in values]
        if len(set(ids)) != len(ids):
            raise ValidationError("backup_ids must not contain duplicates", path="$.backup_ids")
        missing = sorted(set(ids) - rows.keys())
        if missing:
            raise ValidationError("unknown backup_ids: " + ", ".join(missing))
        references = {backup_id: [] for backup_id in ids}
        for server in sorted({self._share_server(rows[backup_id]) for backup_id in ids}):
            for summary in self._config_rows(server):
                share = summary if summary.get("BackupID") else self._config_detail(summary["ShareID"])
                if not self._remote_id(share.get("BackupID")):
                    raise FuploadError("Share backup reference is unknown", kind="verification_required", verification_required=True)
                target = str(share["BackupID"])
                if target in references:
                    references[target].append(str(share["ShareID"]))
        items = [{"backup_id": backup_id, "name": rows[backup_id].get("Name"),
                  "referenced_by": sorted(set(references[backup_id])), "deletable": not references[backup_id]}
                 for backup_id in ids]
        return {"operation": "backup.delete", "complete": True, "items": items, "filters": filters,
                "allowed": all(item["deletable"] for item in items)}

    def backup_delete_preview(self, doc):
        return self._backup_delete_plan(doc)

    def backup_delete(self, doc):
        if not doc.get("dry_run") and doc.get("confirm_delete") is not True:
            raise ValidationError("confirm_delete must be true for backup deletion", path="$.confirm_delete")
        plan = self._backup_delete_plan(doc)
        if doc.get("dry_run"):
            return {"dry_run": True, **plan}
        if not plan["allowed"]:
            raise FuploadError("Backup deletion is blocked by existing configuration shares",
                               kind="backup_in_use", details=plan)
        deleted = []
        for item in plan["items"]:
            backup_id = item["backup_id"]
            issued = False
            try:
                # Recheck immediately before each request; do not reuse a stale
                # batch preview after an earlier deletion or another publisher.
                fresh = self._backup_delete_plan(plan["filters"] or {"backup_id": backup_id})
                if not any(candidate["backup_id"] == backup_id for candidate in fresh["items"]):
                    raise FuploadError("Backup no longer matches the deletion filters", kind="selection_changed")
                if not fresh["allowed"]:
                    raise FuploadError("Backup deletion is blocked by existing configuration shares", kind="backup_in_use", details=fresh)
                issued = True
                self._config_request(BACKUP_REMOVE, query={"backup_id": backup_id}, write=True)
                # The list can briefly retain a deleted row. Poll only the
                # readback; the mutation above is always issued exactly once.
                attempts = max(1, int(self.config.get("verify_attempts", 10)))
                for attempt in range(attempts):
                    if not any(str(row["ID"]) == backup_id for row in self._backup_rows()):
                        break
                    if attempt + 1 == attempts:
                        raise FuploadError("Backup delete was not confirmed by readback", kind="verification_required", verification_required=True)
                    time.sleep(float(self.config.get("verify_interval", 2)))
                deleted.append(backup_id)
            except FuploadError as exc:
                exc.verification_required = exc.verification_required or issued
                exc.details = {**exc.details, "deleted_backup_ids": deleted, "failed_backup_id": backup_id}
                raise
        return {"accepted": True, "verified": True, "deleted_backup_ids": deleted, "total_count": len(deleted)}

    @staticmethod
    def _validate_selection(configuration, backup):
        known_ids = {str(row.get("ID")) for row in backup.get("KnownAddons", []) if isinstance(row, Mapping) and row.get("ID") is not None}
        if any(str(row.get("ID")) not in known_ids for row in configuration["KnownAddons"]):
            raise ValidationError("KnownAddons must be selected from the bound backup")
        for field in ("UnknownAddons", "Materials", "Fonts"):
            selected = configuration.get(field, {}).get("Files", [])
            container = backup.get(field, {})
            if not isinstance(container, Mapping) or not isinstance(container.get("Files", []), list):
                raise ValidationError(f"bound backup has an invalid {field} container")
            available = container.get("Files", [])
            names = {row.get("Name") for row in available if isinstance(row, Mapping)}
            if any(not isinstance(row, Mapping) or not row.get("Name") or row["Name"] not in names for row in selected):
                raise ValidationError(f"{field}.Files must be selected from the bound backup")
        accounts = {row.get("Name"): row for row in backup.get("WTFList", []) if isinstance(row, Mapping)}
        for selected in configuration["WTFList"]:
            account = accounts.get(selected.get("Name"))
            if account is None:
                raise ValidationError("WTFList accounts must be selected from the bound backup")
            characters = {(row.get("Realm"), row.get("Player")) for row in account.get("RealmCharacters", []) if isinstance(row, Mapping)}
            for value in account.get("Characters", []):
                if isinstance(value, str) and " - " in value:
                    characters.add(tuple(value.split(" - ", 1)))
            selected_characters = selected.get("RealmCharacters")
            if not isinstance(selected_characters, list) or not selected_characters:
                raise ValidationError("each selected WTF account requires explicit RealmCharacters")
            if any(not isinstance(row, Mapping) or (row.get("Realm"), row.get("Player")) not in characters for row in selected_characters):
                raise ValidationError("WTFList characters must be selected from the bound backup")
