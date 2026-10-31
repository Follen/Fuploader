"""Owned Workshop WA records, using the observed JSON configuration protocol."""
from __future__ import annotations

from copy import deepcopy
from contextlib import contextmanager
import hashlib
import json
import re
import time
from typing import Any, Mapping
from urllib.parse import urlsplit

from .errors import FuploadError, ValidationError

WA_LIST = "/wow/get_wa_list/"
WA_DETAIL = "/wow/get_wa_detail/"
WA_STRING = "/wow/get_wa_string/"
WA_TAGS = "/wow/get_wa_tag_list/"
WA_CREATE = "/wow/create_wa/"
WA_UPDATE = "/wow/update_wa/"
WA_USER = "/wow/v2/get_user_info/"
WA_FIELDS = frozenset({"categories", "strappid", "open", "name", "descriptionHeybox", "updateLog", "screens", "encoded", "subscribeLevel"})
WA_EXPLICIT = frozenset({"strappid", "open", "subscribeLevel"})
WA_REQUIRED = WA_EXPLICIT | {"categories", "name", "screens", "encoded"}


def validate_wa_configuration(value: Any, *, create: bool) -> None:
    if not isinstance(value, Mapping):
        raise ValidationError("configuration must be an object", path="$.configuration")
    unknown = set(value) - WA_FIELDS
    if unknown:
        raise ValidationError("unknown WA configuration field(s): " + ", ".join(sorted(unknown)), path="$.configuration")
    missing = (WA_REQUIRED if create else WA_EXPLICIT) - value.keys()
    if missing:
        raise ValidationError("WA configuration requires explicit field(s): " + ", ".join(sorted(missing)), path="$.configuration")
    if "strappid" in value and (not isinstance(value["strappid"], str) or not re.fullmatch(r"wow[a-z0-9_]+", value["strappid"])):
        raise ValidationError("strappid must be a WoW game branch", path="$.configuration.strappid")
    if "open" in value and type(value["open"]) is not bool:
        raise ValidationError("open must be boolean", path="$.configuration.open")
    if "subscribeLevel" in value and (type(value["subscribeLevel"]) is not int or value["subscribeLevel"] < 0):
        raise ValidationError("subscribeLevel must be a nonnegative integer", path="$.configuration.subscribeLevel")
    for key in ("name", "descriptionHeybox", "updateLog", "encoded"):
        if key in value and (not isinstance(value[key], str) or key in {"name", "encoded"} and not value[key].strip()):
            raise ValidationError("expected " + ("nonempty " if key in {"name", "encoded"} else "") + "string", path="$.configuration." + key)
    if "name" in value:
        # Match JavaScript replace(/[^\x00-\xff]/g, "ab").length.
        weighted = sum(1 if ord(char) <= 255 else 2 if ord(char) <= 65535 else 4 for char in value["name"])
        if weighted > 70:
            raise ValidationError("name exceeds the official weighted 70-character limit", path="$.configuration.name")
    if "categories" in value:
        items = value["categories"]
        if not isinstance(items, list) or not items or any(not isinstance(item, str) or not item for item in items) or len(set(items)) != len(items):
            raise ValidationError("categories must contain distinct official tag keys", path="$.configuration.categories")
    if "screens" in value:
        items = value["screens"]
        if not isinstance(items, list) or not items:
            raise ValidationError("screens requires at least one preview image", path="$.configuration.screens")
        for item in items:
            if not isinstance(item, Mapping) or set(item) != {"src", "thumb"}:
                raise ValidationError("screens must contain {src,thumb} image references", path="$.configuration.screens")
            for key in ("src", "thumb"):
                ref = item[key]
                try:
                    parsed = urlsplit(ref) if isinstance(ref, str) else None
                    valid = parsed is not None and parsed.scheme == "https" and parsed.hostname and parsed.port in {None, 443} and not parsed.username and not parsed.password
                except ValueError:
                    valid = False
                if not valid:
                    raise ValidationError("WA image references must be HTTPS URLs", path="$.configuration.screens")


class BlackboxWAMixin:
    @staticmethod
    def _wa_slug(value):
        if not isinstance(value, str) or not value.strip() or len(value) > 256 or any(ord(char) < 33 for char in value):
            raise ValidationError("slug must be a nonempty opaque identifier", path="$.slug")
        return value

    @staticmethod
    def _wa_public(value):
        if isinstance(value, Mapping):
            output = {}
            for key, item in value.items():
                if str(key).lower() == "encoded":
                    raw = str(item or "").encode("utf-8")
                    output[str(key) + "_summary"] = {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
                else:
                    output[key] = BlackboxWAMixin._wa_public(item)
            return output
        if isinstance(value, (list, tuple)):
            return [BlackboxWAMixin._wa_public(item) for item in value]
        if isinstance(value, str) and "!WA:" in value:
            raw = value.encode("utf-8")
            return {"opaque_summary": {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}}
        return value

    def _wa_request(self, route, *, query=None, body=None, write=False):
        try:
            return self._config_request(route, query=query, body=body, write=write)
        except FuploadError as error:
            # Backend errors may echo the submitted import string. Never expose
            # the original message, response details, or exception chain.
            code = error.business_code
            if not isinstance(code, int) and not (isinstance(code, str) and re.fullmatch(r"[a-z_]{1,64}", code)):
                code = None
            raise FuploadError("Workshop WA request failed; it was not retried", kind=error.kind,
                               endpoint=route, http_status=error.http_status, business_code=code,
                               verification_required=write or error.verification_required) from None
        except Exception:
            raise FuploadError("Workshop WA response could not be read; it was not retried", kind="protocol_error",
                               endpoint=route, verification_required=write) from None

    @contextmanager
    def _wa_written(self):
        try:
            yield
        except FuploadError as error:
            error.verification_required = True
            raise
        except Exception:
            # Transport/decoder exceptions can also contain submitted content.
            # A mutation may already have reached the server; never replay it.
            raise FuploadError("Workshop WA write or readback was interrupted; do not repeat it",
                               kind="verification_required", verification_required=True) from None

    def _wa_owner(self):
        owner = self._wa_request(WA_USER).get("heybox_id")
        if isinstance(owner, bool) or not isinstance(owner, (str, int)) or not re.fullmatch(r"[1-9][0-9]*", str(owner)):
            raise FuploadError("Workshop did not identify the current WA author", kind="identity_mismatch")
        session = getattr(getattr(self, "_web_session", None), "session", None)
        if isinstance(session, Mapping) and str(session.get("identity")) != str(owner):
            raise FuploadError("Workshop WA author differs from the restored session", kind="identity_mismatch")
        return str(owner)

    def _wa_rows(self, strappid, *, owner=None):
        if not isinstance(strappid, str) or not re.fullmatch(r"wow[a-z0-9_]+", strappid):
            raise ValidationError("strappid is required", path="$.strappid")
        owner = owner or self._wa_owner()
        limit = int(self.config.get("wa_page_size", 30))
        maximum = int(self.config.get("wa_max_pages", 1000))
        if limit < 1 or maximum < 1:
            raise ValidationError("WA pagination limits must be positive")
        result, seen, offset = [], set(), 0
        for page in range(maximum):
            payload = self._wa_request(WA_LIST, query={"strappid": strappid, "offset": offset,
                                       "limit": limit, "my_publish": 1, "sortBy": "finalScore"})
            rows = payload.get("waList")
            if not isinstance(rows, list):
                raise FuploadError("Owned WA pagination is incomplete", kind="verification_required", verification_required=True)
            if not rows:
                return result
            for row in rows:
                if not isinstance(row, Mapping):
                    raise FuploadError("Owned WA list contains an invalid record", kind="protocol_error")
                slug = self._wa_slug(row.get("Slug"))
                if slug in seen or str(row.get("HeyboxId")) != owner:
                    raise FuploadError("Owned WA list is duplicated or contains another author", kind="identity_mismatch")
                seen.add(slug)
                result.append(dict(row))
            offset += len(rows)
        raise FuploadError("Owned WA pagination exceeded its limit", kind="verification_required", verification_required=True)

    def wa_list(self, strappid):
        rows = self._wa_rows(strappid)
        return {"strappid": strappid, "total_count": len(rows), "complete": True,
                "was": self._redact(self._wa_public(rows))}

    def wa_categories(self):
        rows = self._wa_request(WA_TAGS).get("list")
        if not isinstance(rows, list) or any(not isinstance(row, Mapping) or not isinstance(row.get("TagList"), list) for row in rows):
            raise FuploadError("WA category list is incomplete", kind="protocol_error")
        return {"categories": self._redact(self._wa_public(rows))}

    def _wa_detail(self, summary, *, owner):
        slug = self._wa_slug(summary.get("Slug"))
        version = summary.get("LatestVersion")
        version = version.get("Version") if isinstance(version, Mapping) else None
        if isinstance(version, bool) or not isinstance(version, (str, int)) or not str(version):
            raise FuploadError("WA list lacks the latest version identity", kind="protocol_error")
        row = self._wa_request(WA_DETAIL, query={"slug": slug, "version_id": version})
        if row.get("Slug") != slug or str(row.get("HeyboxId")) != owner:
            raise FuploadError("WA detail identifies another author or slug", kind="identity_mismatch")
        return row

    def _wa_owned(self, slug, strappid):
        slug = self._wa_slug(slug)
        owner = self._wa_owner()
        summary = next((row for row in self._wa_rows(strappid, owner=owner) if row["Slug"] == slug), None)
        if summary is None:
            raise FuploadError("WA was not found in the current author's branch", kind="not_found", details={"slug": slug})
        return summary, self._wa_detail(summary, owner=owner), owner

    def wa_get(self, slug, strappid):
        _, row, _ = self._wa_owned(slug, strappid)
        return {"strappid": strappid, "wa": self._redact(self._wa_public(row))}

    def wa_upsert(self, doc, *, create=False):
        if doc.get("scope") != "public":
            raise ValidationError("WA publishing requires explicit scope public; private WA storage is unsupported", path="$.scope")
        patch = deepcopy(doc.get("configuration"))
        validate_wa_configuration(patch, create=create)
        if doc.get("dry_run"):
            return {"dry_run": True, "operation": "wa.create" if create else "wa.update",
                    "scope": "public", "configuration_patch": self._wa_public(patch), "remote_validation": False}
        branch = patch["strappid"]
        owner = self._wa_owner()
        previous_rows = self._wa_rows(branch, owner=owner)
        previous = {row["Slug"] for row in previous_rows}
        current = None
        if not create:
            slug = self._wa_slug(doc.get("slug"))
            summary = next((row for row in previous_rows if row["Slug"] == slug), None)
            if summary is None:
                raise FuploadError("WA was not found in the current author's branch", kind="not_found")
            current = self._wa_detail(summary, owner=owner)
            required = {"Name", "Description", "UpdateLog", "ThumbList", "Categories", "Encoded"}
            if not required.issubset(current):
                raise FuploadError("WA detail lacks fields required to preserve its content", kind="protocol_error")
            configuration = {"name": current["Name"], "descriptionHeybox": current["Description"], "updateLog": current["UpdateLog"],
                             "categories": deepcopy(current["Categories"]), "encoded": current["Encoded"],
                             "screens": [{"src": item, "thumb": item} for item in current["ThumbList"]]}
            configuration.update(patch)
        else:
            configuration = patch
        validate_wa_configuration(configuration, create=True)
        tags = {item.get("Key") for group in self.wa_categories()["categories"] for item in group["TagList"] if isinstance(item, Mapping)}
        if any(key not in tags for key in configuration["categories"]):
            raise ValidationError("categories must be selected from the current official WA tags", path="$.configuration.categories")
        query = {} if create else {"slug": current["Slug"]}
        with self._wa_written():
            self._wa_request(WA_CREATE if create else WA_UPDATE, query=query,
                             body={"configuration": json.dumps(configuration, ensure_ascii=False, separators=(",", ":"))}, write=True)
            attempts = max(1, int(self.config.get("verify_attempts", 10)))
            for attempt in range(attempts):
                rows = self._wa_rows(branch, owner=owner)
                candidates = [row for row in rows if row["Slug"] == current["Slug"]] if current else [row for row in rows if row["Slug"] not in previous and row.get("Name") == configuration["name"]]
                matches = []
                for summary in candidates:
                    actual = self._wa_detail(summary, owner=owner)
                    expected = {"Name": configuration["name"], "Categories": configuration["categories"], "Encoded": configuration["encoded"],
                                "ThumbList": [item["src"] for item in configuration["screens"]]}
                    for wire, detail in (("descriptionHeybox", "Description"), ("updateLog", "UpdateLog")):
                        if wire in configuration:
                            expected[detail] = configuration[wire]
                    if all(actual.get(key) == value for key, value in expected.items()):
                        matches.append((summary, actual))
                if len(matches) > 1:
                    raise FuploadError("WA creation readback was ambiguous; do not repeat the write", kind="verification_required", verification_required=True)
                if matches:
                    summary, actual = matches[0]
                    # open is an opaque native setting, not a privacy control.
                    visibility = {"anonymous_can_view": None, "verified": False}
                    return {"accepted": True, "verified": True, "slug": actual["Slug"], "strappid": branch,
                            "scope": "public", "requested_open": configuration["open"], "visibility": visibility,
                            "verified_fields": sorted(expected),
                            "unverified_fields": ["subscribeLevel", "screens.thumb", "open"],
                            "readback": self._redact(self._wa_public(actual))}
                if attempt + 1 < attempts:
                    time.sleep(float(self.config.get("verify_interval", 2)))
            raise FuploadError("WA write was not confirmed by readback; do not repeat it", kind="verification_required", verification_required=True,
                               details={"slug": current["Slug"]} if current else {})

    def wa_delete(self, doc):
        if doc.get("confirm_delete") is not True:
            raise ValidationError("confirm_delete must be true", path="$.confirm_delete")
        slug, branch = self._wa_slug(doc.get("slug")), doc.get("strappid")
        if doc.get("dry_run"):
            return {"dry_run": True, "operation": "wa.delete", "slug": slug, "strappid": branch, "remote_validation": False}
        _, current, owner = self._wa_owned(slug, branch)
        if current.get("AuditState") == 1:
            raise FuploadError("The official client disables WA deletion during active review", kind="review_in_progress", details={"slug": slug})
        with self._wa_written():
            self._wa_request(WA_UPDATE, query={"slug": slug, "delete": 1}, body={}, write=True)
            attempts = max(1, int(self.config.get("verify_attempts", 10)))
            for attempt in range(attempts):
                if not any(row["Slug"] == slug for row in self._wa_rows(branch, owner=owner)):
                    return {"accepted": True, "verified": True, "slug": slug, "strappid": branch}
                if attempt + 1 < attempts:
                    time.sleep(float(self.config.get("verify_interval", 2)))
            raise FuploadError("WA delete was not confirmed by readback; do not repeat it", kind="verification_required", verification_required=True, details={"slug": slug})
