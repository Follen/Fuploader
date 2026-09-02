#!/usr/bin/env python3
"""Explicitly gated, full DD live regression for one persisted login kind.

The default invocation only emits a plan. ``--execute`` starts exactly one DD
task session, discovers current live dependencies, exercises every applicable
non-exploration build, and always attempts cleanup and logout. Evidence is
redacted and never stores the opaque session id or request bodies.
"""

from __future__ import annotations

import argparse
import base64
import copy
import hashlib
import json
import re
import subprocess
import sys
import tempfile
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple


ROOT = Path(__file__).resolve().parents[3]
CLI = ROOT / "fupload" / "scripts" / "fupload.py"
DEFAULT_FIXTURE_DIR = ROOT / "publish" / "20260801-073918-dd-full-alignment-reaudit"
DEFAULT_PACKAGE = ROOT / "publish" / "20260731-191228-cross-platform-contract-test" / "assets" / "FuploadContractTest.zip"
SAFE_CREDENTIAL_KINDS = ("email", "mobile")
CONFIG_NOT_APPLICABLE = "not_applicable_no_usable_current_account_backup"
SECRET_KEY = re.compile(
    r"token|cookie|credential(?!_kind)|signature|password|secret|auth|session[_-]?id|client[_-]?(?:id|no)|device",
    re.I,
)
SENSITIVE_VALUE = re.compile(
    r"(?i)(bearer\s+|x-amz-(?:credential|signature|security-token)=|token[=:]\s*)[^\s&\"']+"
)
PNG_BYTES = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


class RegressionFailure(RuntimeError):
    pass


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _summary(value: Any, key: str = "") -> Any:
    """Keep stable evidence without retaining credentials or private bodies."""
    if key.casefold() in {"credential_kind", "expected_credential_kind", "credential_kind_source"}:
        return value
    if SECRET_KEY.search(key):
        return "[REDACTED]"
    if isinstance(value, Mapping):
        return {str(k): _summary(v, str(k)) for k, v in value.items()}
    if isinstance(value, list):
        if len(value) > 20:
            return {"count": len(value), "sample": [_summary(item) for item in value[:3]]}
        return [_summary(item) for item in value]
    if isinstance(value, str):
        cleaned = SENSITIVE_VALUE.sub(r"\1[REDACTED]", value)
        if key.casefold() in {
            "account", "content", "desc", "html_desc", "file", "file_path", "url", "signed_url", "d_url",
        }:
            return {"bytes": len(cleaned.encode("utf-8")), "sha256": _sha256(cleaned.encode("utf-8"))}
        if len(cleaned) > 256:
            return {"bytes": len(cleaned.encode("utf-8")), "sha256": _sha256(cleaned.encode("utf-8"))}
        return cleaned
    return value


def _payload(output: Mapping[str, Any]) -> Any:
    return output.get("data") if "data" in output else output


def _items(output: Mapping[str, Any]) -> List[Dict[str, Any]]:
    value = _payload(output)
    if isinstance(value, Mapping) and isinstance(value.get("items"), list):
        return [dict(item) for item in value["items"] if isinstance(item, Mapping)]
    return []


def _reference(output: Mapping[str, Any]) -> str:
    value = _payload(output)
    if isinstance(value, Mapping):
        for candidate in (value.get("reference"), value.get("sn"), value.get("share_sn")):
            if candidate:
                return str(candidate)
    raise RegressionFailure("mutation response did not include a reference")


def _choice(items: Sequence[Mapping[str, Any]], keys: Sequence[str], label: str) -> Any:
    for item in items:
        for key in keys:
            if item.get(key) not in (None, ""):
                return item[key]
    raise RegressionFailure("live dependency returned no selectable %s" % label)


def _safe_command(arguments: Sequence[str]) -> List[str]:
    result: List[str] = []
    redact_next = False
    input_next = False
    for argument in arguments:
        if redact_next:
            result.append("[REDACTED]")
            redact_next = False
            continue
        if input_next:
            path = Path(argument)
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
                schema = str(value.get("schema") or "unknown") if isinstance(value, Mapping) else "unknown"
                digest = _sha256(path.read_bytes())
                result.append("<input schema=%s sha256=%s>" % (schema, digest))
            except (OSError, ValueError):
                result.append("<input unreadable>")
            input_next = False
            continue
        result.append(argument)
        if argument == "--session":
            redact_next = True
        elif argument == "--input":
            input_next = True
    return result


@dataclass
class CommandResult:
    output: Dict[str, Any]
    exit_status: int
    success: bool


class CliHarness:
    def __init__(
        self,
        evidence: Dict[str, Any],
        run: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    ) -> None:
        self.evidence = evidence
        self._run = run

    def invoke(self, label: str, arguments: Sequence[str], *, required: bool = True) -> CommandResult:
        completed = self._run(
            [sys.executable, str(CLI), *arguments], cwd=str(ROOT), text=True,
            capture_output=True, encoding="utf-8", errors="replace",
        )
        raw = completed.stdout.strip()
        try:
            parsed = json.loads(raw) if raw else {}
        except ValueError as exc:
            parsed = {"error": "CLI emitted non-JSON output", "stdout_sha256": _sha256(raw.encode("utf-8"))}
            parse_error: Optional[Exception] = exc
        else:
            parse_error = None
        if not isinstance(parsed, dict):
            parsed = {"value": parsed}
        success = completed.returncode == 0 and parsed.get("success", True) is not False and parse_error is None
        self.evidence["steps"].append({
            "label": label, "command": _safe_command(arguments),
            "exit_status": completed.returncode, "success": success,
            "result": _summary(parsed), "stderr": _summary(completed.stderr.strip(), "stderr"),
        })
        if required and not success:
            raise RegressionFailure("%s failed with exit status %d" % (label, completed.returncode))
        return CommandResult(parsed, completed.returncode, success)


def _git_commit() -> str:
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=str(ROOT), text=True,
        capture_output=True, encoding="utf-8", errors="replace",
    )
    return completed.stdout.strip() if completed.returncode == 0 else "unknown"


def _netease_dd_process_count() -> Optional[int]:
    completed = subprocess.run(
        ["tasklist", "/FI", "IMAGENAME eq netease_dd.exe", "/FO", "CSV", "/NH"],
        text=True, capture_output=True, encoding="utf-8", errors="replace",
    )
    if completed.returncode != 0:
        return None
    return sum(1 for line in completed.stdout.splitlines() if line.lstrip().lower().startswith('"netease_dd.exe"'))


def _resource_fingerprint(doctor: Mapping[str, Any]) -> Dict[str, Any]:
    data = _payload(doctor)
    if not isinstance(data, Mapping):
        return {}
    dd_dir = data.get("dd_dir")
    result: Dict[str, Any] = {"dd_dir_name": Path(str(dd_dir)).name if dd_dir else None}
    signature = data.get("signature")
    if isinstance(signature, Mapping):
        result["signature"] = _summary(signature)
    resource = Path(str(dd_dir)) / "ccvoicehub.res" if dd_dir else None
    if resource and resource.is_file():
        result["ccvoicehub_res_sha256"] = _sha256(resource.read_bytes())
    return result


def build_plan(fixture_dir: Path, package: Path) -> Dict[str, Any]:
    templates = {
        "plugin_create": fixture_dir / "01-plugin-create.json",
        "config_create": fixture_dir / "04-config-create.json",
        "wa_create": fixture_dir / "07-wa-create.json",
    }
    missing = [str(path) for path in [*templates.values(), package] if not path.is_file()]
    if missing:
        raise RegressionFailure("missing fixture files: " + ", ".join(missing))
    return {
        "schema": "fupload.dd.full-live-regression-plan.v2", "remote_writes_performed": 0,
        "session_lifecycle": ["doctor", "start", "status", "stop", "post-stop-doctor"],
        "preflight_before_mutation": {
            "global": ["game-types", "plugin-categories", "config-backups", "channels", "life-types", "vip-levels"],
            "every_non_exploration_build": ["game-versions", "wa-categories", "plugin-list", "config-list", "wa-list", "associated-acts"],
            "current_account_backup_builds": ["usable-backup-detail"],
        },
        "per_build_mutations": {
            "plugin": ["create", "update", "edit", "delete"],
            "config": ["create", "update", "edit", "delete"],
            "wa": ["create", "update", "edit", "delete"],
        },
        "six_plugin_batch": True,
        "binary_uploads": ["plugin-zip", "plugin-logo", "plugin-detail-image", "config-image", "wa-image", "wa-material-zip"],
        "cleanup_order": ["wa", "config", "plugin"],
        "template_files": {name: path.name for name, path in templates.items()},
        "package": {"name": package.name, "sha256": _sha256(package.read_bytes())},
    }


def _load(path: Path) -> Dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise RegressionFailure("fixture must contain one JSON object: %s" % path)
    return value


def _write(root: Path, name: str, value: Mapping[str, Any]) -> Path:
    path = root / name
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _session_id(output: Mapping[str, Any]) -> str:
    data = _payload(output)
    if isinstance(data, Mapping) and data.get("session_id"):
        return str(data["session_id"])
    raise RegressionFailure("session start did not return session_id")


def _reported_credential_kind(*outputs: Mapping[str, Any]) -> Optional[str]:
    for output in outputs:
        data = _payload(output)
        if isinstance(data, Mapping) and data.get("credential_kind"):
            return str(data["credential_kind"])
    return None


def _is_exploration(item: Mapping[str, Any]) -> bool:
    text = " ".join(str(item.get(key) or "") for key in ("name", "type", "label")).casefold()
    return "探索" in text or "exploration" in text


def _with_session(arguments: Iterable[str], session_id: str) -> List[str]:
    return [*arguments, "--session", session_id]


def _special_assets(root: Path, package: Path) -> Tuple[Path, Path, Path]:
    plugin_zip = root / "插件 包(回归)+#% ü.zip"
    plugin_zip.write_bytes(package.read_bytes())
    image = root / "展示 图(回归)+#% ü.png"
    image.write_bytes(PNG_BYTES)
    material = root / "WA 材质(回归)+#% ü.zip"
    with zipfile.ZipFile(material, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("Interface/AddOns/FuploadLive/material.txt", "full live regression")
    return plugin_zip, image, material


def _private_fields() -> Dict[str, Any]:
    return {
        "scope": "private", "share_code_life_type": "seven_day", "need_buy": False,
        "jump_room": False, "sync_room": False, "creation_statement": "original",
        "with_associate": False, "associated_acts": [], "need_anchor_vip": False,
        "vip_levels": [],
    }


def _plugin_document(
    template: Mapping[str, Any], game_type: int, version: Any, category: Any,
    name: str, package: Path, image: Path,
) -> Dict[str, Any]:
    return {
        "schema": "fupload.v1.dd.plugin.create", "game_type": game_type,
        **_private_fields(), "addon_type": int(template.get("addon_type", 0)),
        "name": name[:80], "description": "Temporary full login-state regression",
        "logo_file": str(image), "detail_img_files": [str(image)],
        "primary_category_id": int(category), "second_category_ids": [],
        "html_desc": "<p>Temporary full login-state regression.</p>",
        "game_versions": [str(version)], "file": str(package), "release_type": 1,
        "version": "1", "update_desc": "Initial full live regression",
    }


def _wa_document(
    game_type: int, game_version: Any, category: Any, name: str, image: Path, material: Path,
) -> Dict[str, Any]:
    return {
        "schema": "fupload.v1.dd.wa.create", "game_type": game_type,
        **_private_fields(), "name": name[:40], "game_version": str(game_version),
        "brief_desc": "Temporary full live regression", "display_img_files": [str(image)],
        "category_ids": [str(category)], "content": "Fupload temporary full live WA v1",
        "desc": "Temporary full login-state regression.", "update_desc": "Initial full live regression",
        "version": "1", "with_file": True, "file": str(material),
        "file_install_path": "Interface/Addons",
    }


def _backup_selections(detail: Mapping[str, Any]) -> Optional[Dict[str, Any]]:
    roles = list(detail.get("wtf_roles") or [])
    role = str(roles[0].get("selector")) if roles and roles[0].get("selector") else None

    def refs(group: str) -> List[Any]:
        return [
            item["reference"] for item in detail.get(group) or []
            if isinstance(item, Mapping) and item.get("reference") not in (None, "")
        ]

    known_addon = refs("known_addon")[:1] if role else []
    unknown_addon = refs("unknown_addon")[:1] if role and not known_addon else []
    material = refs("material")[:1]
    font = refs("font")[:1]
    if not (known_addon or unknown_addon or material or font):
        return None
    return {
        "known_addon_ids": known_addon, "unknown_addon_ids": unknown_addon,
        "wtf_role_ids": [role] if role and (known_addon or unknown_addon) else [],
        "material_names": material, "font_names": font,
        "known_wa_ids": [], "unknown_wa_ids": [],
    }


def _config_documents(
    detail: Mapping[str, Any], name: str, image: Path,
) -> Optional[Tuple[Dict[str, Any], Dict[str, Any]]]:
    selections = _backup_selections(detail)
    reference = str(detail.get("reference") or "")
    if not selections or not reference:
        return None
    create = {
        "schema": "fupload.v1.dd.config.create", **_private_fields(), "backup_sn": reference,
        "title": name[:40], "brief_desc": "Temporary full live regression",
        "desc": "<p>Temporary full login-state regression.</p>",
        "update_desc": "Initial full live regression", "display_img_files": [str(image)],
        **copy.deepcopy(selections),
    }
    update = {
        "schema": "fupload.v1.dd.config.update", "backup_sn": reference,
        "update_desc": "Updated full live regression", **copy.deepcopy(selections),
        "known_addon_update_ids": list(selections["known_addon_ids"]),
        "unknown_addon_update_ids": list(selections["unknown_addon_ids"]),
        "material_update_names": list(selections["material_names"]),
        "font_update_names": list(selections["font_names"]),
        "known_wa_update_ids": [], "unknown_wa_update_ids": [],
    }
    if int(detail.get("game_type") or 0) == 10001:
        create["retail_ui_config"] = None
        update["retail_ui_config"] = None
    return create, update


def _build_matrix_passed(item: Mapping[str, Any]) -> bool:
    return (
        item.get("plugin") == "passed"
        and item.get("config") in {"passed", CONFIG_NOT_APPLICABLE}
        and item.get("wa") == "passed"
    )


def _invoke_write(
    harness: CliHarness, inputs: Path, session_id: str, label: str,
    resource: str, action: str, document: Mapping[str, Any], *, required: bool = True,
) -> CommandResult:
    path = _write(inputs, label + ".json", document)
    return harness.invoke(
        label, ["dd", resource, action, "--session", session_id, "--input", str(path)],
        required=required,
    )


def _readback(harness: CliHarness, session_id: str, label: str, resource: str, reference: str) -> None:
    harness.invoke(label, _with_session(["dd", resource, "get", "--sn", reference], session_id))


def _create(
    harness: CliHarness, inputs: Path, session_id: str, label: str, resource: str,
    document: Mapping[str, Any], created: List[Dict[str, str]], game_type: int,
) -> str:
    result = _invoke_write(harness, inputs, session_id, label, resource, "create", document, required=False)
    if result.success:
        reference = _reference(result.output)
        created.append({"resource": resource, "reference": reference, "game_type": str(game_type)})
        return reference

    name = str(document.get("name") or document.get("title") or "")
    listing = harness.invoke(
        label + "-uncertain-readback",
        _with_session(["dd", resource, "list", "--keyword", name, "--game-type", str(game_type), "--page-size", "100"], session_id),
        required=False,
    )
    matches = [
        item for item in _items(listing.output)
        if str(item.get("name") or item.get("title") or "") == name and item.get("reference")
    ]
    if len(matches) == 1:
        created.append({"resource": resource, "reference": str(matches[0]["reference"]), "game_type": str(game_type)})
    raise RegressionFailure("%s failed; GET-only recovery found %d matching objects" % (label, len(matches)))


def execute(
    fixture_dir: Path,
    package: Path,
    expected_credential_kind: str,
    evidence_path: Path,
    *,
    run: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> Dict[str, Any]:
    plan = build_plan(fixture_dir, package)
    evidence: Dict[str, Any] = {
        "schema": "fupload.dd.full-live-regression-evidence.v2",
        "generated_at": datetime.now(timezone.utc).isoformat(), "commit": _git_commit(),
        "expected_credential_kind": expected_credential_kind, "credential_kind": None,
        "credential_kind_source": None, "plan": plan, "steps": [], "builds": [],
        "objects": [], "cleanup": [], "six_plugin_batch": [], "completed": False,
    }
    harness = CliHarness(evidence, run)
    session_id: Optional[str] = None
    created: List[Dict[str, str]] = []
    failure: Optional[BaseException] = None
    body_completed = False
    with tempfile.TemporaryDirectory(prefix="fupload-dd-live-") as directory:
        inputs = Path(directory)
        plugin_zip, image, wa_material = _special_assets(inputs, package)
        evidence["asset_hashes"] = {
            "plugin_zip": _sha256(plugin_zip.read_bytes()), "image": _sha256(image.read_bytes()),
            "wa_material_zip": _sha256(wa_material.read_bytes()),
        }
        try:
            doctor = harness.invoke("session-doctor", ["dd", "session", "doctor"]).output
            evidence["dd_resource"] = _resource_fingerprint(doctor)
            evidence["process_count_before"] = _netease_dd_process_count()
            start = harness.invoke("session-start", ["dd", "session", "start", "--confirm-close-gui"]).output
            session_id = _session_id(start)
            status = harness.invoke("session-status", ["dd", "session", "status", "--session", session_id]).output
            reported = _reported_credential_kind(start, status)
            if reported != expected_credential_kind:
                raise RegressionFailure("credential kind mismatch: expected %s, got %s" % (expected_credential_kind, reported))
            evidence["credential_kind"] = reported
            evidence["credential_kind_source"] = "session"
            status_data = _payload(status)
            if isinstance(status_data, Mapping):
                evidence["session_counts"] = {
                    "broker_count": status_data.get("broker_count"),
                    "sidecar_count": status_data.get("sidecar_count"),
                    "native_login_count": status_data.get("native_login_count"),
                }

            game_types = harness.invoke("options-game-types", _with_session(["dd", "options", "game-types"], session_id)).output
            builds = [item for item in _items(game_types) if not _is_exploration(item)]
            if not builds:
                raise RegressionFailure("no non-exploration DD game types were returned")
            categories_output = harness.invoke("plugin-categories", _with_session(["dd", "plugin", "categories"], session_id)).output
            plugin_category = _choice(_items(categories_output), ("id", "category_id", "value"), "plugin category")
            backups_output = harness.invoke("config-backups", _with_session(["dd", "config", "backups"], session_id)).output
            backups = _items(backups_output)
            for label, args in (
                ("options-channels", ["dd", "options", "channels"]),
                ("options-life-types", ["dd", "options", "life-types"]),
                ("options-vip-levels", ["dd", "options", "vip-levels"]),
            ):
                harness.invoke(label, _with_session(args, session_id))

            stamp = datetime.now(timezone.utc).strftime("%m%d%H%M%S")
            contexts: List[Dict[str, Any]] = []
            for item in builds:
                game_type = int(item.get("game_type") or item.get("id"))
                versions = harness.invoke(
                    "build-%s-game-versions" % game_type,
                    _with_session(["dd", "plugin", "game-versions", "--game-type", str(game_type)], session_id),
                ).output
                wa_categories = harness.invoke(
                    "build-%s-wa-categories" % game_type,
                    _with_session(["dd", "wa", "categories", "--game-type", str(game_type)], session_id),
                ).output
                for suffix, args in (
                    ("plugin-list", ["dd", "plugin", "list", "--game-type", str(game_type), "--page-size", "100"]),
                    ("config-list", ["dd", "config", "list", "--game-type", str(game_type), "--page-size", "100"]),
                    ("wa-list", ["dd", "wa", "list", "--game-type", str(game_type), "--page-size", "100"]),
                    ("associated-acts", ["dd", "options", "associated-acts", "--game-type", str(game_type)]),
                ):
                    harness.invoke("build-%s-%s" % (game_type, suffix), _with_session(args, session_id))

                config_docs: Optional[Tuple[Dict[str, Any], Dict[str, Any]]] = None
                for backup in backups:
                    if int(backup.get("game_type") or 0) != game_type:
                        continue
                    backup_ref = str(backup.get("reference") or "")
                    detail_output = harness.invoke(
                        "backup-%s-get" % game_type,
                        _with_session(["dd", "config", "backup-get", "--sn", backup_ref], session_id),
                    ).output
                    detail = _payload(detail_output)
                    if isinstance(detail, Mapping):
                        config_docs = _config_documents(detail, "Fupload C%s %s" % (game_type, stamp), image)
                    if config_docs:
                        break
                contexts.append({
                    "game_type": game_type, "name": item.get("name"),
                    "version": _choice(_items(versions), ("value", "version", "game_version"), "game version"),
                    "wa_category": _choice(_items(wa_categories), ("id", "category_id", "value"), "WA category"),
                    "config_docs": config_docs,
                })
                evidence["builds"].append({
                    "game_type": game_type, "name": item.get("name"),
                    "plugin": "preflight_passed",
                    "config": "preflight_passed" if config_docs else CONFIG_NOT_APPLICABLE,
                    "config_reason": None if config_docs else "current account has no usable cloud backup for this build",
                    "wa": "preflight_passed",
                })

            plugin_template = _load(fixture_dir / "01-plugin-create.json")
            for index, context in enumerate(contexts):
                game_type = context["game_type"]
                record = evidence["builds"][index]
                plugin = _plugin_document(
                    plugin_template, game_type, context["version"], plugin_category,
                    "Fupload Live P%s %s" % (game_type, stamp), plugin_zip, image,
                )
                plugin_ref = _create(
                    harness, inputs, session_id, "plugin-%s-create" % game_type,
                    "plugin", plugin, created, game_type,
                )
                evidence["objects"].append({"resource": "plugin", "game_type": game_type, "reference": plugin_ref})
                _readback(harness, session_id, "plugin-%s-get-created" % game_type, "plugin", plugin_ref)
                _invoke_write(harness, inputs, session_id, "plugin-%s-update" % game_type, "plugin", "update", {
                    "schema": "fupload.v1.dd.plugin.update", "sn": plugin_ref,
                    "game_versions": [str(context["version"])], "file": str(plugin_zip),
                    "release_type": 1, "version": "2", "update_desc": "Updated full live regression",
                })
                _readback(harness, session_id, "plugin-%s-get-updated" % game_type, "plugin", plugin_ref)
                _invoke_write(harness, inputs, session_id, "plugin-%s-edit" % game_type, "plugin", "edit", {
                    "schema": "fupload.v1.dd.plugin.edit", "sn": plugin_ref,
                    "share_code_life_type": "fourteen_day",
                })
                _readback(harness, session_id, "plugin-%s-get-edited" % game_type, "plugin", plugin_ref)
                record["plugin"] = "passed"

                if context["config_docs"]:
                    config, config_update = context["config_docs"]
                    config_ref = _create(
                        harness, inputs, session_id, "config-%s-create" % game_type,
                        "config", config, created, game_type,
                    )
                    evidence["objects"].append({"resource": "config", "game_type": game_type, "reference": config_ref})
                    _readback(harness, session_id, "config-%s-get-created" % game_type, "config", config_ref)
                    config_update["share_sn"] = config_ref
                    _invoke_write(harness, inputs, session_id, "config-%s-update" % game_type, "config", "update", config_update)
                    _readback(harness, session_id, "config-%s-get-updated" % game_type, "config", config_ref)
                    _invoke_write(harness, inputs, session_id, "config-%s-edit" % game_type, "config", "edit", {
                        "schema": "fupload.v1.dd.config.edit", "share_sn": config_ref,
                        "title": (config["title"] + " E")[:40], "brief_desc": "Edited full live regression",
                        "desc": "<p>Edited full login-state regression.</p>",
                        "share_code_life_type": "fourteen_day",
                    })
                    _readback(harness, session_id, "config-%s-get-edited" % game_type, "config", config_ref)
                    record["config"] = "passed"

                wa = _wa_document(
                    game_type, context["version"], context["wa_category"],
                    "Fupload WA%s %s" % (game_type, stamp), image, wa_material,
                )
                wa_ref = _create(
                    harness, inputs, session_id, "wa-%s-create" % game_type,
                    "wa", wa, created, game_type,
                )
                evidence["objects"].append({"resource": "wa", "game_type": game_type, "reference": wa_ref})
                _readback(harness, session_id, "wa-%s-get-created" % game_type, "wa", wa_ref)
                _invoke_write(harness, inputs, session_id, "wa-%s-update" % game_type, "wa", "update", {
                    "schema": "fupload.v1.dd.wa.update", "sn": wa_ref,
                    "content": "Fupload temporary full live WA v2", "update_desc": "Updated full live regression",
                    "version": "2", "with_file": False,
                })
                _readback(harness, session_id, "wa-%s-get-updated" % game_type, "wa", wa_ref)
                _invoke_write(harness, inputs, session_id, "wa-%s-edit" % game_type, "wa", "edit", {
                    "schema": "fupload.v1.dd.wa.edit", "sn": wa_ref,
                    "brief_desc": "Edited full live regression", "share_code_life_type": "fourteen_day",
                })
                _readback(harness, session_id, "wa-%s-get-edited" % game_type, "wa", wa_ref)
                record["wa"] = "passed"

            batch_context = contexts[0]
            for batch_index in range(6):
                batch_doc = _plugin_document(
                    plugin_template, batch_context["game_type"], batch_context["version"], plugin_category,
                    "Fupload Batch %s %s" % (batch_index + 1, stamp), plugin_zip, image,
                )
                batch_ref = _create(
                    harness, inputs, session_id, "batch-plugin-%s-create" % (batch_index + 1),
                    "plugin", batch_doc, created, batch_context["game_type"],
                )
                evidence["six_plugin_batch"].append({"index": batch_index + 1, "reference": batch_ref, "created": True})
            body_completed = True
        except BaseException as exc:
            failure = exc
            evidence["failure"] = {"type": type(exc).__name__, "message": _summary(str(exc), "error")}
        finally:
            if not session_id:
                recovery = harness.invoke("session-status-recovery", ["dd", "session", "status"], required=False).output
                recovery_data = _payload(recovery)
                if isinstance(recovery_data, Mapping) and recovery_data.get("running") and recovery_data.get("session_id"):
                    session_id = str(recovery_data["session_id"])
            if session_id:
                order = {"wa": 0, "config": 1, "plugin": 2}
                for item in sorted(reversed(created), key=lambda value: order[value["resource"]]):
                    resource = item["resource"]
                    reference = item["reference"]
                    document = {
                        "schema": "fupload.v1.dd.%s.delete" % resource,
                        "sn": reference, "confirm_delete": True,
                    }
                    result = _invoke_write(
                        harness, inputs, session_id,
                        "cleanup-%s-%s-%s" % (resource, item["game_type"], len(evidence["cleanup"])),
                        resource, "delete", document, required=False,
                    )
                    evidence["cleanup"].append({
                        "resource": resource, "game_type": int(item["game_type"]), "reference": reference,
                        "exit_status": result.exit_status, "success": result.success,
                    })
                stop = harness.invoke("session-stop", ["dd", "session", "stop", "--session", session_id], required=False)
            else:
                stop = CommandResult({}, 0, True)
            post = harness.invoke("post-stop-doctor", ["dd", "session", "doctor"], required=False).output
            post_data = _payload(post)
            stop_data = _payload(stop.output)
            evidence["residual_process_check"] = {
                "broker_running": post_data.get("broker_running") if isinstance(post_data, Mapping) else None,
                "gui_running": post_data.get("gui_running") if isinstance(post_data, Mapping) else None,
                "gui_process_count": len(post_data.get("gui_processes") or []) if isinstance(post_data, Mapping) else None,
                "netease_dd_process_count": _netease_dd_process_count(),
                "stop_cleanup_complete": stop_data.get("cleanup_complete") if isinstance(stop_data, Mapping) else None,
            }
            cleanup_ok = len(evidence["cleanup"]) == len(created) and all(item["success"] for item in evidence["cleanup"])
            stopped = stop.success and isinstance(stop_data, Mapping) and stop_data.get("cleanup_complete") is True
            broker_stopped = isinstance(post_data, Mapping) and post_data.get("broker_running") is False
            processes_stopped = evidence["residual_process_check"]["netease_dd_process_count"] == 0
            all_builds_passed = all(_build_matrix_passed(item) for item in evidence["builds"])
            evidence["completed"] = (
                body_completed and all_builds_passed and len(evidence["six_plugin_batch"]) == 6
                and cleanup_ok and stopped and broker_stopped and processes_stopped
            )
            if failure is None and not evidence["completed"]:
                failure = RegressionFailure("DD matrix, cleanup, logout, or residual-process verification failed")
                evidence["failure"] = {"type": type(failure).__name__, "message": str(failure)}
            evidence_path.parent.mkdir(parents=True, exist_ok=True)
            evidence_path.write_text(json.dumps(_summary(evidence), ensure_ascii=False, indent=2), encoding="utf-8")
    if failure:
        raise RegressionFailure(str(failure)) from failure
    return evidence


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description=__doc__)
    value.add_argument("--execute", action="store_true", help="Perform real DD reads, uploads, writes, readbacks, and cleanup.")
    value.add_argument("--expected-credential-kind", choices=SAFE_CREDENTIAL_KINDS)
    value.add_argument("--evidence", type=Path)
    value.add_argument("--fixture-dir", type=Path, default=DEFAULT_FIXTURE_DIR)
    value.add_argument("--package", type=Path, default=DEFAULT_PACKAGE)
    return value


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parser().parse_args(argv)
    try:
        plan = build_plan(args.fixture_dir.resolve(), args.package.resolve())
        if not args.execute:
            print(json.dumps(plan, ensure_ascii=False, indent=2))
            return 0
        if not args.evidence:
            raise RegressionFailure("--execute requires --evidence")
        if not args.expected_credential_kind:
            raise RegressionFailure("--execute requires --expected-credential-kind")
        evidence = execute(
            args.fixture_dir.resolve(), args.package.resolve(), args.expected_credential_kind,
            args.evidence.resolve(),
        )
        print(json.dumps(_summary(evidence), ensure_ascii=False, indent=2))
        return 0
    except RegressionFailure as exc:
        print(json.dumps({"success": False, "error": str(exc)}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
