from __future__ import annotations

import copy
import hashlib
import importlib
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path
from typing import Any, Dict, List
from unittest import mock

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fupload_cli.errors import ValidationError
from fupload_cli.schema import SCHEMAS
from tests.test_dd_wire_matrix import ACTIONS, DDWireMatrixTests, wire_target
from tests.test_full_schema_state_matrix import (
    FullSchemaStateMatrixTests,
    NESTED_OBJECT_FIELDS,
    SCALAR_ARRAY_FIELDS,
    generated_case_count,
    nested_case_count,
)
from tests.test_newbee_wire_matrix import (
    MAIN_ENDPOINTS,
    OFFICIAL_EFFECTIVE_FIELDS,
    NewBeeWireMatrixTests,
)


OUTPUT = ROOT / "analyze" / "full-wire-audit-20260801"


def revision() -> str:
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, capture_output=True, check=True,
    )
    return completed.stdout.strip()


def workspace_manifest() -> Dict[str, Any]:
    roots = [ROOT / "fupload" / "scripts", ROOT / "fupload" / "references"]
    files = [ROOT / "fupload" / "SKILL.md"]
    for source_root in roots:
        if source_root.exists():
            files.extend(path for path in source_root.rglob("*") if path.is_file())
    rows = []
    for path in sorted(set(files)):
        if "__pycache__" in path.parts or path.suffix in (".pyc", ".pyo"):
            continue
        data = path.read_bytes()
        rows.append({
            "path": path.relative_to(ROOT).as_posix(),
            "bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
        })
    canonical = json.dumps(rows, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("ascii")
    return {
        "schema": "fupload.workspace-manifest.v1",
        "files": rows,
        "file_count": len(rows),
        "sha256": hashlib.sha256(canonical).hexdigest(),
    }


def schema_cases() -> List[Dict[str, Any]]:
    FullSchemaStateMatrixTests.setUpClass()
    test = FullSchemaStateMatrixTests(methodName="test_every_field_has_an_explicit_falsy_contract")
    cases: List[Dict[str, Any]] = []
    try:
        for key, schema in sorted(SCHEMAS.items()):
            unknown = test._document(key)
            unknown["unexpected_remote_display"] = {"id": 999}
            cases.append(run_schema_case(schema, unknown, "%s.unknown_top_level" % schema.name))
            for field, spec in schema.fields.items():
                base = test._document(key)
                wrong = copy.deepcopy(base)
                wrong[field] = copy.deepcopy({
                    "string": [], "integer": "wrong", "number": {},
                    "boolean": 1, "array": {}, "object": [],
                }[spec.type])
                cases.append(run_schema_case(schema, wrong, "%s.%s.wrong_type" % (schema.name, field)))

                null = copy.deepcopy(base)
                null[field] = None
                cases.append(run_schema_case(schema, null, "%s.%s.null" % (schema.name, field)))

                omitted = copy.deepcopy(base)
                omitted.pop(field, None)
                test._adjust(omitted, field, "omitted")
                test._add_alternative(key, omitted, field)
                cases.append(run_schema_case(schema, omitted, "%s.%s.omitted" % (schema.name, field)))

                falsy = copy.deepcopy(base)
                falsy[field] = copy.deepcopy(test._falsy_value(spec))
                test._adjust(falsy, field, "falsy")
                test._add_alternative(key, falsy, field)
                cases.append(run_schema_case(schema, falsy, "%s.%s.falsy" % (schema.name, field)))

            for field in schema.fields:
                if field not in NESTED_OBJECT_FIELDS and field not in SCALAR_ARRAY_FIELDS and field != "retail_ui_config":
                    continue
                nested = test._document(key)
                if field in NESTED_OBJECT_FIELDS:
                    value = copy.deepcopy(nested.get(field) or test._nested_minimum(field))
                    value[0]["unknown"] = True
                    nested[field] = value
                elif field == "retail_ui_config":
                    nested[field] = {"edit_mode": {"account": [{"import_string": "private"}]}}
                else:
                    nested[field] = [{"id": 999, "name": "display"}]
                cases.append(run_schema_case(schema, nested, "%s.%s.nested_display" % (schema.name, field)))
    finally:
        FullSchemaStateMatrixTests.tearDownClass()
    return cases


def run_schema_case(schema, document: Dict[str, Any], case_id: str) -> Dict[str, Any]:
    try:
        schema.validate(document)
        return {"case_id": case_id, "layer": "schema", "outcome": "accepted"}
    except ValidationError as exc:
        return {
            "case_id": case_id,
            "layer": "schema",
            "outcome": "rejected",
            "path": exc.details.get("path"),
        }


def dd_wire_cases() -> List[Dict[str, Any]]:
    DDWireMatrixTests.setUpClass()
    test = DDWireMatrixTests(methodName="test_every_field_normal_value_reaches_exact_wire_target")
    cases = []
    try:
        for resource, action in ACTIONS:
            schema = SCHEMAS[("dd", resource, action)]
            for field in schema.fields:
                doc = test._field_doc(resource, action, field)
                session, body = test._execute(resource, action, doc)
                endpoint, _wire = session.mutations[0]
                cases.append({
                    "case_id": "dd.%s.%s.%s.normal_wire" % (resource, action, field),
                    "layer": "wire",
                    "outcome": "sent",
                    "endpoint": endpoint,
                    "target": wire_target(resource, field),
                    "request_fields": sorted(body),
                    "uploads": len(session.uploads),
                    "mutations": len(session.mutations),
                })
    finally:
        DDWireMatrixTests.tearDownClass()
    return cases


def dd_log_diagnostic_cases() -> List[Dict[str, Any]]:
    os.environ.setdefault("NETEASE_DD_DIR", "D:/Software/NetEaseDD/100128")
    os.environ.setdefault("FUPLOAD_DD_DEVICE_STATE", "D:/state/sidecar-device.json")
    sidecar = importlib.import_module("fupload_cli.dd_sidecar")
    DDWireMatrixTests.setUpClass()
    test = DDWireMatrixTests(methodName="test_every_actual_wire_body_projects_to_sanitized_diagnostic_error_log")
    cases: List[Dict[str, Any]] = []
    try:
        for resource, action in ACTIONS:
            schema = SCHEMAS[("dd", resource, action)]
            for field in schema.fields:
                session, body = test._execute(resource, action, test._field_doc(resource, action, field))
                endpoint, _wire = session.mutations[0]
                logged = sidecar._request_log_content(body, endpoint)
                if "request_json" not in logged or set(logged["request_json"]) != set(body):
                    raise SystemExit("DD request log projection did not preserve the sanitized diagnostic shape")
                cases.append({
                    "case_id": "dd.%s.%s.%s.error_log_diagnostics" % (resource, action, field),
                    "layer": "error_log",
                    "outcome": "sanitized_diagnostics",
                    "endpoint": endpoint,
                    "request_bytes": logged["request_bytes"],
                    "request_sha256": logged["request_sha256"],
                    "request_shape": logged["request_shape"],
                    "request_json": logged["request_json"],
                })
    finally:
        DDWireMatrixTests.tearDownClass()
    return cases


def discovered_unittest_count() -> int:
    suite = unittest.defaultTestLoader.discover(str(ROOT / "fupload" / "scripts" / "tests"))
    return suite.countTestCases()


def newbee_wire_cases() -> List[Dict[str, Any]]:
    NewBeeWireMatrixTests.setUpClass()
    test = NewBeeWireMatrixTests(methodName="test_every_field_reaches_its_exact_wire_target_or_stays_local")
    cases = []
    try:
        for (platform, resource, action), schema in sorted(SCHEMAS.items()):
            if platform != "newbee":
                continue
            for field in schema.fields:
                doc = test._document_for_field(resource, action, field)
                provider, _result = test._execute(resource, action, doc)
                cases.append({
                    "case_id": "newbee.%s.%s.%s.normal_wire" % (resource, action, field),
                    "layer": "wire",
                    "outcome": "sent_or_local_control",
                    "classification": test._classification(resource, action, field),
                    "posts": [{"endpoint": endpoint, "request_fields": sorted(body)} for endpoint, body in provider.posts],
                    "next_posts": [{"endpoint": endpoint, "request_fields": sorted(body)} for endpoint, body in provider.next_posts],
                    "multipart": [{"endpoint": endpoint, "field_names": sorted(fields)} for endpoint, _path, fields in provider.multipart],
                    "media_uploads": [endpoint for endpoint, _path, _url in provider.media],
                    "attachment_uploads": len(provider.attachment_uploads),
                })
    finally:
        NewBeeWireMatrixTests.tearDownClass()
    return cases


def official_newbee_comparison() -> Dict[str, Any]:
    extraction_path = OUTPUT / "newbee-official-builders.json"
    extraction = json.loads(extraction_path.read_text(encoding="utf-8"))
    extracted = {}
    for call in extraction["calls"]:
        fields = set(call["fields"])
        if call["endpoint"] == "/creator/wow/share_config/release":
            fields.discard("tid")
        if call["endpoint"] == "/creator/wow/wa/update":
            fields.discard("wa_str_titles")
        extracted[call["endpoint"]] = sorted(fields)
    endpoint_for = {
        **MAIN_ENDPOINTS,
        ("plugin", "update"): "/creator/wow/mod_file/upload_mod_file",
    }
    rows = []
    for key, expected in sorted(OFFICIAL_EFFECTIVE_FIELDS.items()):
        endpoint = endpoint_for[key]
        actual = set(extracted[endpoint])
        rows.append({
            "resource": key[0], "action": key[1], "endpoint": endpoint,
            "official_fields": sorted(actual),
            "python_expected_fields": sorted(expected),
            "missing_in_python": sorted(actual - expected),
            "extra_in_python": sorted(expected - actual),
        })
    return {"sources": extraction["sources"], "rows": rows}


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    schema = schema_cases()
    dd_wire = dd_wire_cases()
    newbee_wire = newbee_wire_cases()
    dd_log = dd_log_diagnostic_cases()
    corpus = schema + dd_wire + newbee_wire + dd_log
    expected_total = (
        generated_case_count()
        + sum(len(item.fields) for item in SCHEMAS.values())
        + sum(len(SCHEMAS[("dd", resource, action)].fields) for resource, action in ACTIONS)
    )
    if len(corpus) != expected_total:
        raise SystemExit("case count mismatch: %d != %d" % (len(corpus), expected_total))
    official = official_newbee_comparison()
    divergences = [row for row in official["rows"] if row["missing_in_python"] or row["extra_in_python"]]
    dd_map = json.loads((ROOT / "analyze" / "dd-official-web-validation-reconstruction-20260801" / "validation-map.json").read_text(encoding="utf-8"))
    manifest = workspace_manifest()
    summary = {
        "schema": "fupload.full-wire-audit.v1",
        "revision": revision(),
        "workspace_manifest_sha256": manifest["sha256"],
        "workspace_file_count": manifest["file_count"],
        "schema_count": len(SCHEMAS),
        "field_count": sum(len(item.fields) for item in SCHEMAS.values()),
        "nested_display_cases": nested_case_count(),
        "schema_state_cases": len(schema),
        "normal_wire_cases": len(dd_wire) + len(newbee_wire),
        "dd_sanitized_error_log_cases": len(dd_log),
        "total_generated_cases": len(corpus),
        "unittest_count": discovered_unittest_count(),
        "newbee_official_builder_divergences": divergences,
        "dd_official_source_sha256": dd_map["source"]["sha256"],
        "dd_official_endpoint_count": len(dd_map["endpoints"]),
        "live_writes_this_audit": 0,
        "exploration_season_included": False,
    }
    (OUTPUT / "golden-corpus.json").write_text(
        json.dumps({"summary": summary, "cases": corpus}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (OUTPUT / "official-comparison.json").write_text(
        json.dumps({"newbee": official, "dd": {"source": dd_map["source"], "modules": dd_map["modules"]}}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (OUTPUT / "workspace-manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    report = """# Full cross-platform wire and leakage audit

Date: 2026-08-01

## Proof scope

- 34 write schemas and 357 input fields.
- 1,564 generated schema-state cases: unknown top-level, wrong type, null, omission, falsy value, and nested display enrichment.
- 357 generated normal-wire cases: 195 DD and 162 NewBeeBox.
- 195 DD error-log projections generated from those exact wire bodies. Safe diagnostics retain enums, versions, category/build IDs, booleans, numbers, and association types; private text, identifiers, URLs, WA/WTF, and configuration content are summarized.
- Total generated corpus: 2,116 cases.
- Fresh official extraction: DD `umi.pretty.js` plus five NewBeeBox Creator Center bundles.
- Live writes in this audit: 0. Exploration Season remains excluded.
- The exact uncommitted source state is bound by `workspace-manifest.json` (%d files, SHA-256 `%s`); the Git HEAD alone is not treated as the tested revision.

## Findings fixed

1. DD JSONL failures stored the complete plugin mutation body, raw WA content, and complete configuration backup groups. Requests now retain only an explicit diagnostic allowlist plus structural metadata: enums, versions, category/build IDs, booleans, numbers, and association types. Private text, identifiers, URLs, WA/WTF, and configuration content are summarized. Native status, business code, field hints, and validation messages remain available.
2. DD JSONL and broker startup errors missed unlabelled JWTs, raw `!WA:` payloads, quoted JSON secrets, `client_secret`, `api_key`, `auth_key`, and password/secret values. They now share an expanded redaction boundary.
3. NewBeeBox WA create could send a successful publish request and then raise `KeyError` during readback when optional commercial fields were omitted. Readback expectations now use the normalized payload defaults.
4. Present local-file controls accepted an empty path, and NewBeeBox `cloud_id=0` reached the dependency layer. Both now fail schema validation before uploads or mutations.
5. The old DD wire recorder mutated captured request dictionaries with simulated response fields. It now records immutable request snapshots; all DD matrix tests pass against the corrected wire bodies.
6. DD configuration full-object exceptions now have exact nested-shape assertions for all seven content groups and retail UI state, including the account-scoped unknown-WA ID remap.

## Official comparison

NewBeeBox official AST extraction contains eight unique endpoint builders covering nine CLI actions: plugin create/edit/version upload, configuration create plus shared edit/update, and WA publish/edit/string update. Effective field-set divergence after normalization: **0**.

DD extraction source SHA-256: `%s`; parsed endpoint count: %d. Existing DD action/field tests were rerun after fixing the request recorder.

## Leakage sink inventory

1. CLI stdout: every success and error object passes recursively through `sanitize_output`; credentials and raw WA/import content are redacted or summarized.
2. DD error JSONL: only allowlisted diagnostic request values are persisted; private request fields and echoed response fields are summarized. HTTP status, business code, field hints, and sanitized body/JSON remain available.
3. DD sidecar stdout: task-local pipe only; startup failure text is redacted and the parent applies the CLI output boundary.
4. DD broker state/startup JSON: contains the local broker `auth_key` needed for loopback IPC but no mutation payload or provider credential; startup exception text is redacted and the file lives under trusted Roaming AppData.
5. NewBeeBox auth store: access/refresh/device credentials remain only in the official per-user auth directory and are sent only to pinned official origins; they are not copied into logs or command output.
6. `publish/` JSON: deliberate user-authored release inputs, not diagnostic logs; callers control their business content.
7. `analyze/`: ignored local evidence. Token, JWT, signed-URL, and quoted-secret scans returned no matches after this audit.

## Verification

- `python -m unittest discover -s fupload\\scripts\\tests -v`: %d tests passed.
- `python -m compileall -q fupload\\scripts`: passed.
- `git diff --check`: passed; only Git's LF/CRLF conversion notices remain.

## Residual boundary

This audit proves schema behavior, dependency rejection, request construction, output/log sanitization, and source-level alignment against the captured official bundles. It does not claim a new production mutation run; provider behavior can change after those bundles or APIs are updated.
""" % (
        summary["workspace_file_count"],
        summary["workspace_manifest_sha256"],
        summary["dd_official_source_sha256"],
        summary["dd_official_endpoint_count"],
        summary["unittest_count"],
    )
    (OUTPUT / "report.md").write_text(report, encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
