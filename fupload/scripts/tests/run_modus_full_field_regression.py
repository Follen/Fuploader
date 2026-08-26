"""Destructive, fixture-driven ModUs full-field regression.

The default mode is local-only: validate the fixture, local artifacts, and the
complete field matrix, then print the planned steps.  Pass ``--execute`` only
from the controlled release verification workflow.  The generated evidence
contains commands, exit statuses, field names, lengths, and SHA-256 digests;
it never stores authentication material, mutable text, binary data, or signed
URLs.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, MutableMapping, Sequence


SCRIPTS_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS_DIR))

from fupload_cli.errors import ValidationError  # noqa: E402
from fupload_cli.schema import get_schema  # noqa: E402


BUILDS = tuple(range(5))
ID_FIELDS = {
    "project": "project_id",
    "release": "file_id",
    "config": "share_id",
    "wa": "import_id",
}
CONTROL_FIELDS = {
    "project": {"project_id", "project_state"},
    "release": {"project_id", "file_id", "file", "transaction_log"},
    "config": {"share_id", "server_type"},
    "wa": {"import_id", "server_type"},
}
SCHEMA_TARGETS = {
    "project": ("project", "edit"),
    "release": ("plugin", "edit"),
    "config": ("config", "update"),
    "wa": ("wa", "update"),
}
READBACK_ALIASES = {
    "alt_name": ("altName",),
    "repo_url": ("repoUrl",),
    "required_tier_id": ("requiredTierId",),
    "publish_platforms": ("publishPlatforms",),
    "supported_game_versions": ("supportedGameVersionsReqs", "supportedGameVersions"),
    "toc_version": ("tocVersion",),
    "zip_size": ("zipSize",),
    "unzip_size": ("unzipSize",),
    "addons_id": ("addonsId",),
    "account_name": ("accountName",),
    "backup_id": ("backupId",),
    "content_text": ("contentText",),
    "image_url": ("imageUrl",),
    "is_paid": ("isPaid",),
    "is_public": ("isPublic",),
    "share_type": ("shareType",),
    "exclude_wtf": ("excludeWtf",),
    "role_name": ("roleName",),
    "sub_type": ("subType",),
    "synchronization_type": ("synchronizationType",),
    "code_text": ("codeText",),
    "file_path": ("filePath",),
    "support_addon": ("supportAddon",),
}
SECRET_MARKERS = (
    "token", "cookie", "authorization", "credential", "signature",
    "signed", "secret", "password", "url",
)
CONTENT_FIELDS = {
    "content", "content_text", "code_text", "description", "summary",
    "changelog", "logo_base64", "screenshot_base64s", "image_ops",
}


class RegressionFailure(RuntimeError):
    pass


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _summary(value: Any, *, key: str = "") -> Any:
    normalized = key.replace("-", "_").lower()
    if any(marker in normalized for marker in SECRET_MARKERS):
        if value in (None, ""):
            return value
        raw = json.dumps(value, ensure_ascii=False, sort_keys=True).encode("utf-8")
        return {"redacted": True, "bytes": len(raw), "sha256": _sha256(raw)}
    if isinstance(value, Mapping):
        return {str(name): _summary(item, key=str(name)) for name, item in value.items()}
    if isinstance(value, list):
        if normalized in CONTENT_FIELDS:
            raw = json.dumps(value, ensure_ascii=False, sort_keys=True).encode("utf-8")
            return {"items": len(value), "bytes": len(raw), "sha256": _sha256(raw)}
        return [_summary(item, key=key) for item in value]
    if isinstance(value, str) and (normalized in CONTENT_FIELDS or len(value) > 120):
        raw = value.encode("utf-8")
        return {"bytes": len(raw), "sha256": _sha256(raw)}
    return value


def _artifact_summary(path: Path) -> Dict[str, Any]:
    raw = path.read_bytes()
    return {"name": path.name, "bytes": len(raw), "sha256": _sha256(raw)}


def _load_object(path: Path) -> Dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise RegressionFailure("fixture must be one JSON object")
    return value


def mutable_fields(resource: str) -> set[str]:
    schema_resource, action = SCHEMA_TARGETS[resource]
    return set(get_schema("modus", schema_resource, action).fields) - CONTROL_FIELDS[resource]


def validate_fixture(fixture: Mapping[str, Any], root: Path) -> Dict[str, Any]:
    resources = fixture.get("resources")
    images = fixture.get("images")
    negatives = fixture.get("negative_cases")
    if not isinstance(resources, Mapping):
        raise RegressionFailure("fixture.resources must be an object")
    if not isinstance(images, Mapping):
        raise RegressionFailure("fixture.images must be an object")
    required_images = {"project_logo", "project_screenshot", "config", "wa"}
    missing_images = sorted(required_images - set(images))
    if missing_images:
        raise RegressionFailure("missing image fixture(s): %s" % ", ".join(missing_images))

    image_summaries: Dict[str, Any] = {}
    distinct = set()
    for name in sorted(required_images):
        image_path = (root / str(images[name])).resolve() if not Path(str(images[name])).is_absolute() else Path(str(images[name]))
        if not image_path.is_file():
            raise RegressionFailure("image fixture is not a file: %s" % name)
        summary = _artifact_summary(image_path)
        image_summaries[name] = summary
        distinct.add(summary["sha256"])
    if len(distinct) < 3:
        raise RegressionFailure("project/config/WA images must contain at least three distinct byte sequences")

    coverage: Dict[str, Any] = {}
    for resource in SCHEMA_TARGETS:
        section = resources.get(resource)
        if not isinstance(section, Mapping):
            raise RegressionFailure("fixture.resources.%s must be an object" % resource)
        if not isinstance(section.get("create"), Mapping):
            raise RegressionFailure("fixture.resources.%s.create must be an object" % resource)
        mutations = section.get("mutations")
        restores = section.get("restores")
        if not isinstance(mutations, Mapping) or not isinstance(restores, Mapping):
            raise RegressionFailure("%s mutations/restores must be objects" % resource)
        for context_name in (
            "mutation_contexts", "restore_contexts", "readback_fields",
            "mutation_readback", "restore_readback",
        ):
            context = section.get(context_name, {})
            if not isinstance(context, Mapping):
                raise RegressionFailure("%s.%s must be an object" % (resource, context_name))
            unknown_context = sorted(set(context) - mutable_fields(resource))
            if unknown_context:
                raise RegressionFailure(
                    "%s.%s contains unknown field(s): %s"
                    % (resource, context_name, ", ".join(unknown_context))
                )
        expected = mutable_fields(resource)
        mutation_fields = set(mutations)
        restore_fields = set(restores)
        missing = sorted(expected - mutation_fields)
        missing_restore = sorted(expected - restore_fields)
        extra = sorted((mutation_fields | restore_fields) - expected)
        if missing or missing_restore or extra:
            raise RegressionFailure(
                "%s field coverage mismatch: missing_mutations=%s missing_restores=%s extra=%s"
                % (resource, missing, missing_restore, extra)
            )
        coverage[resource] = sorted(expected)

    if not isinstance(negatives, list) or not negatives:
        raise RegressionFailure("fixture.negative_cases must be a nonempty array")
    required_negative_kinds = {"enum", "empty_null", "dependency", "build"}
    actual_kinds = {str(item.get("kind")) for item in negatives if isinstance(item, Mapping)}
    if not required_negative_kinds.issubset(actual_kinds):
        raise RegressionFailure("negative cases must cover enum, empty_null, dependency, and build")
    for index, item in enumerate(negatives):
        if not isinstance(item, Mapping) or not all(name in item for name in ("kind", "resource", "action", "document")):
            raise RegressionFailure("negative_cases[%d] is incomplete" % index)
        try:
            schema = get_schema("modus", str(item["resource"]), str(item["action"]))
            schema.validate({"schema": schema.name, **item["document"]})
        except ValidationError:
            pass
        else:
            raise RegressionFailure(
                "negative_cases[%d] must fail local schema validation before authentication" % index
            )

    return {"images": image_summaries, "field_coverage": coverage, "builds": list(BUILDS), "negative_kinds": sorted(actual_kinds)}


def _recursive_find(value: Any, names: Iterable[str]) -> Any:
    wanted = {str(name).lower() for name in names}
    if isinstance(value, Mapping):
        for key, item in value.items():
            if str(key).lower() in wanted and item not in (None, ""):
                return item
        for item in value.values():
            found = _recursive_find(item, wanted)
            if found not in (None, ""):
                return found
    elif isinstance(value, list):
        for item in value:
            found = _recursive_find(item, wanted)
            if found not in (None, ""):
                return found
    return None


def _readback_value(payload: Any, field: str) -> Any:
    aliases = {field, *READBACK_ALIASES.get(field, ())}
    found = _recursive_find(payload, aliases)
    if found is None:
        raise RegressionFailure("readback omitted field %s" % field)
    return found


def _equivalent(actual: Any, expected: Any) -> bool:
    if actual == expected:
        return True
    if isinstance(actual, str) and not isinstance(expected, (dict, list)):
        return actual.strip() == str(expected).strip()
    if isinstance(expected, str) and isinstance(actual, list):
        return ",".join(str(item) for item in actual) == expected
    return False


@dataclass
class CommandResult:
    command: list[str]
    exit_status: int
    payload: Dict[str, Any]


class CliHarness:
    def __init__(self, evidence: MutableMapping[str, Any], work_dir: Path):
        self.evidence = evidence
        self.work_dir = work_dir
        self.python = sys.executable
        self.module = "fupload_cli.cli"
        self.env = dict(os.environ)
        prior = self.env.get("PYTHONPATH")
        self.env["PYTHONPATH"] = str(SCRIPTS_DIR) + (os.pathsep + prior if prior else "")

    def run(self, args: Sequence[str], *, expected_exit: int = 0, input_summary: Any = None) -> CommandResult:
        command = [self.python, "-m", self.module, *args]
        completed = subprocess.run(
            command, cwd=str(self.work_dir), env=self.env, text=True,
            capture_output=True, encoding="utf-8", errors="replace", check=False,
        )
        try:
            payload = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            raise RegressionFailure("command emitted non-JSON output (exit %d)" % completed.returncode) from exc
        record = {
            "command": command,
            "exit_status": completed.returncode,
            "input_summary": input_summary,
            "response_summary": _summary(payload),
        }
        self.evidence["steps"].append(record)
        if completed.returncode != expected_exit:
            raise RegressionFailure("unexpected exit status %d for %s" % (completed.returncode, " ".join(args[:3])))
        return CommandResult(command, completed.returncode, payload)

    def write(self, resource: str, action: str, document: Mapping[str, Any], *, expected_exit: int = 0) -> CommandResult:
        schema = get_schema("modus", resource, action)
        payload = {"schema": schema.name, **document}
        fd, raw_path = tempfile.mkstemp(prefix="modus-regression-", suffix=".json", dir=str(self.work_dir))
        os.close(fd)
        path = Path(raw_path)
        try:
            path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            return self.run(
                ["modus", resource, action, "--input", str(path)],
                expected_exit=expected_exit,
                input_summary=_summary({key: value for key, value in payload.items() if key != "schema"}),
            )
        finally:
            path.unlink(missing_ok=True)

    def read(self, resource: str, action: str, flags: Sequence[str] = ()) -> CommandResult:
        return self.run(["modus", resource, action, *flags])


def _cycle(
    harness: CliHarness,
    resource: str,
    action: str,
    read_resource: str,
    read_flags: Sequence[str],
    identity: Mapping[str, Any],
    controls: Mapping[str, Any],
    mutations: Mapping[str, Any],
    restores: Mapping[str, Any],
    mutation_contexts: Mapping[str, Mapping[str, Any]] | None = None,
    restore_contexts: Mapping[str, Mapping[str, Any]] | None = None,
    readback_fields: Mapping[str, str] | None = None,
    mutation_readback: Mapping[str, Any] | None = None,
    restore_readback: Mapping[str, Any] | None = None,
) -> None:
    mutation_contexts = mutation_contexts or {}
    restore_contexts = restore_contexts or {}
    readback_fields = readback_fields or {}
    mutation_readback = mutation_readback or {}
    restore_readback = restore_readback or {}
    for field in sorted(mutations):
        mutation = {**identity, **controls, **mutation_contexts.get(field, {}), field: mutations[field]}
        harness.write(resource, action, mutation)
        changed = harness.read(read_resource, "get", read_flags).payload
        readback_field = readback_fields.get(field, field)
        actual = _readback_value(changed, readback_field)
        expected_mutation = mutation_readback.get(field, mutations[field])
        if not _equivalent(actual, expected_mutation):
            raise RegressionFailure("%s.%s mutation readback mismatch" % (resource, field))
        restore = {**identity, **controls, **restore_contexts.get(field, {}), field: restores[field]}
        harness.write(resource, action, restore)
        restored = harness.read(read_resource, "get", read_flags).payload
        actual = _readback_value(restored, readback_field)
        expected_restore = restore_readback.get(field, restores[field])
        if not _equivalent(actual, expected_restore):
            raise RegressionFailure("%s.%s restoration readback mismatch" % (resource, field))


def _image_document(path: Path) -> Dict[str, Any]:
    return {"file": str(path)}


def _media_reference(result: CommandResult) -> str:
    value = _recursive_find(result.payload, ("reference", "cosStoreKey", "key"))
    if not isinstance(value, str) or not value.strip():
        raise RegressionFailure("media upload omitted reusable object reference")
    return value.strip()


def _extract_identifier(payload: Any, resource: str) -> Any:
    field = ID_FIELDS[resource]
    aliases = {
        "project": ("project_id", "projectId", "id"),
        "release": ("file_id", "fileId", "id"),
        "config": ("share_id", "shareId", "id"),
        "wa": ("import_id", "importId", "id"),
    }[resource]
    value = _recursive_find(payload, aliases)
    if value in (None, ""):
        raise RegressionFailure("%s create response omitted %s" % (resource, field))
    return value


def _cycle_options(section: Mapping[str, Any]) -> Dict[str, Any]:
    return {
        "mutation_contexts": section.get("mutation_contexts", {}),
        "restore_contexts": section.get("restore_contexts", {}),
        "readback_fields": section.get("readback_fields", {}),
        "mutation_readback": section.get("mutation_readback", {}),
        "restore_readback": section.get("restore_readback", {}),
    }


def execute_regression(fixture: Mapping[str, Any], fixture_root: Path, evidence_path: Path) -> Dict[str, Any]:
    validation = validate_fixture(fixture, fixture_root)
    evidence: Dict[str, Any] = {
        "schema": "fupload.modus.full-field-regression.v1",
        "started_at": int(time.time()),
        "fixture_summary": validation,
        "steps": [],
        "cleanup": [],
    }
    resources = fixture["resources"]
    images = {
        key: ((fixture_root / str(value)).resolve() if not Path(str(value)).is_absolute() else Path(str(value)))
        for key, value in fixture["images"].items()
    }
    harness = CliHarness(evidence, evidence_path.parent)
    ids: Dict[str, Any] = {}
    release_deleted = config_deleted = wa_deleted = project_deleted = False

    def persist() -> None:
        evidence_path.write_text(json.dumps(evidence, ensure_ascii=True, indent=2, sort_keys=True), encoding="utf-8")

    try:
        harness.read("builds", "list")
        for build in BUILDS:
            flags = ["--build", str(build)]
            harness.read("config", "backups", flags)
            harness.read("config", "list", flags)
            harness.read("wa", "list", flags)

        for case in fixture["negative_cases"]:
            harness.write(str(case["resource"]), str(case["action"]), case["document"], expected_exit=2)

        uploaded = {}
        for name in ("config", "wa"):
            uploaded[name] = _media_reference(harness.write("media", "upload", _image_document(images[name])))

        project_create = dict(resources["project"]["create"])
        project_create["logo_base64"] = base64.b64encode(images["project_logo"].read_bytes()).decode("ascii")
        project_create["screenshot_base64s"] = [base64.b64encode(images["project_screenshot"].read_bytes()).decode("ascii")]
        project_result = harness.write("project", "create", project_create)
        ids["project"] = _extract_identifier(project_result.payload, "project")
        harness.read("project", "get", ["--project-id", str(ids["project"])])
        _cycle(
            harness, "project", "edit", "project", ["--project-id", str(ids["project"])],
            {"project_id": ids["project"]},
            {"project_state": resources["project"]["project_state"]},
            resources["project"]["mutations"], resources["project"]["restores"],
            **_cycle_options(resources["project"]),
        )

        release_create = {**resources["release"]["create"], "project_id": ids["project"]}
        release_result = harness.write("plugin", "upload", release_create)
        ids["release"] = _extract_identifier(release_result.payload, "release")
        release_flags = ["--project-id", str(ids["project"]), "--file-id", str(ids["release"])]
        harness.read("plugin", "get", release_flags)
        _cycle(
            harness, "plugin", "edit", "plugin", release_flags,
            {"project_id": ids["project"], "file_id": ids["release"]}, {},
            resources["release"]["mutations"], resources["release"]["restores"],
            **_cycle_options(resources["release"]),
        )

        config_create = {**resources["config"]["create"], "image_url": uploaded["config"]}
        config_result = harness.write("config", "create", config_create)
        ids["config"] = _extract_identifier(config_result.payload, "config")
        config_flags = ["--share-id", str(ids["config"]), "--build", str(config_create.get("server_type", 0))]
        harness.read("config", "get", config_flags)
        config_mutations = dict(resources["config"]["mutations"])
        config_restores = dict(resources["config"]["restores"])
        config_mutations["image_url"] = uploaded["wa"]
        config_restores["image_url"] = uploaded["config"]
        _cycle(
            harness, "config", "update", "config", config_flags,
            {"share_id": ids["config"]}, {"server_type": config_create.get("server_type", 0)},
            config_mutations, config_restores,
            **_cycle_options(resources["config"]),
        )

        wa_create = {**resources["wa"]["create"], "image_url": uploaded["wa"]}
        wa_result = harness.write("wa", "create", wa_create)
        ids["wa"] = _extract_identifier(wa_result.payload, "wa")
        wa_flags = ["--import-id", str(ids["wa"]), "--build", str(wa_create.get("server_type", 0))]
        harness.read("wa", "get", wa_flags)
        wa_mutations = dict(resources["wa"]["mutations"])
        wa_restores = dict(resources["wa"]["restores"])
        wa_mutations["image_url"] = uploaded["config"]
        wa_restores["image_url"] = uploaded["wa"]
        _cycle(
            harness, "wa", "update", "wa", wa_flags,
            {"import_id": ids["wa"]}, {"server_type": wa_create.get("server_type", 0)},
            wa_mutations, wa_restores,
            **_cycle_options(resources["wa"]),
        )

        version = resources["wa"].get("version")
        if not isinstance(version, Mapping):
            raise RegressionFailure("fixture.resources.wa.version must contain publish and delete documents")
        publish = {**version["publish"], "import_id": ids["wa"]}
        version_result = harness.write("wa", "version-publish", publish)
        version_id = _recursive_find(version_result.payload, ("version_id", "versionId", "id"))
        if version_id in (None, ""):
            raise RegressionFailure("WA version publish response omitted version id")
        harness.read("wa", "get", wa_flags)
        harness.write("wa", "version-delete", {"version_id": version_id, "confirm": "DELETE", "server_type": wa_create.get("server_type", 0)})

        evidence["completed"] = True
        return evidence
    finally:
        cleanup = []
        try:
            cleanup_actions = []
            if "wa" in ids and not wa_deleted:
                cleanup_actions.append(("wa", "wa", {"import_id": ids["wa"], "confirm": "DELETE", "server_type": resources["wa"]["create"].get("server_type", 0)}))
            if "config" in ids and not config_deleted:
                cleanup_actions.append(("config", "config", {"share_id": ids["config"], "confirm": "DELETE", "server_type": resources["config"]["create"].get("server_type", 0)}))
            if "release" in ids and not release_deleted:
                cleanup_actions.append(("release", "plugin", {"project_id": ids["project"], "file_id": ids["release"], "confirm": "DELETE"}))
            if "project" in ids and not project_deleted:
                cleanup_actions.append(("project", "project", {"project_id": ids["project"], "confirm": "DELETE"}))
            for name, cli_resource, document in cleanup_actions:
                try:
                    harness.write(cli_resource, "delete", document)
                    cleanup.append({"resource": name, "deleted": True})
                except (OSError, ValueError, RegressionFailure) as exc:
                    cleanup.append({
                        "resource": name,
                        "deleted": False,
                        "error": _summary(str(exc), key="cleanup_error"),
                    })
        finally:
            evidence["cleanup"] = cleanup
            evidence["cleanup_complete"] = bool(cleanup) and all(item["deleted"] for item in cleanup)
            if not cleanup and not ids:
                evidence["cleanup_complete"] = True
            evidence["finished_at"] = int(time.time())
            persist()


def build_plan(fixture: Mapping[str, Any], root: Path) -> Dict[str, Any]:
    validation = validate_fixture(fixture, root)
    cycles = sum(len(fields) for fields in validation["field_coverage"].values())
    return {
        "schema": "fupload.modus.full-field-regression-plan.v1",
        "execute": False,
        "validation": validation,
        "planned_field_cycles": cycles,
        "planned_field_writes": cycles * 2,
        "planned_field_readbacks": cycles * 2,
        "remote_writes_performed": 0,
        "cleanup_order": ["wa", "config", "release", "project"],
    }


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate or execute destructive ModUs full-field regression fixtures.")
    parser.add_argument("--fixture", type=Path, required=True, help="JSON fixture containing create, mutation, restoration, image, and negative-case inputs.")
    parser.add_argument("--evidence", type=Path, help="Redacted evidence JSON path; required with --execute.")
    parser.add_argument("--execute", action="store_true", help="Perform real remote writes and dependency-ordered cleanup.")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        fixture_path = args.fixture.resolve()
        fixture = _load_object(fixture_path)
        if not args.execute:
            print(json.dumps(build_plan(fixture, fixture_path.parent), ensure_ascii=True, sort_keys=True))
            return 0
        if args.evidence is None:
            raise RegressionFailure("--evidence is required with --execute")
        evidence_path = args.evidence.resolve()
        evidence_path.parent.mkdir(parents=True, exist_ok=True)
        execute_regression(fixture, fixture_path.parent, evidence_path)
        print(json.dumps({"success": True, "evidence": str(evidence_path)}, ensure_ascii=True, sort_keys=True))
        return 0
    except (OSError, ValueError, RegressionFailure) as exc:
        print(json.dumps({"success": False, "error": str(exc)}, ensure_ascii=True, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
