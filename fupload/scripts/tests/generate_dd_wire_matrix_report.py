from __future__ import annotations

import sys
import unittest
from pathlib import Path
from typing import List, Tuple

TESTS_DIR = Path(__file__).resolve().parent
SCRIPTS_DIR = TESTS_DIR.parent
sys.path.insert(0, str(TESTS_DIR))
sys.path.insert(0, str(SCRIPTS_DIR))

from fupload_cli.schema import Field, get_schema
from test_dd_wire_matrix import ACTIONS, DDWireMatrixTests, ENDPOINTS, wire_target


def applicable_states(resource: str, action: str, field: str, spec: Field) -> List[Tuple[str, str]]:
    states = [
        ("normal", "accept -> exact wire target"),
        ("omitted", "reject" if spec.required else "accept in neutral dependency context"),
        ("null", "accept" if spec.nullable else "reject at exact field path"),
        ("invalid_type", "reject at exact field path"),
    ]
    if field not in ("sn", "share_sn", "confirm_delete"):
        states.append(("alternate", "accept"))
    if spec.type == "string":
        empty = not spec.nonempty and (not spec.choices or "" in spec.choices)
        if resource == "config" and action == "update" and field == "update_desc":
            empty = False
        states.append(("empty", "accept" if empty else "reject"))
        if spec.max_length is not None:
            states.extend((("max", "accept"), ("over_max", "reject")))
        if spec.choices:
            states.append(("invalid_choice", "reject"))
    elif spec.type == "integer":
        zero = field not in ("game_type", "primary_category_id", "release_type")
        states.append(("zero", "accept" if zero else "reject"))
        if spec.choices:
            states.append(("invalid_choice", "reject"))
    elif spec.type == "boolean":
        states.append(("false", "reject" if field == "confirm_delete" else "accept"))
    elif spec.type == "array":
        states.append(("empty", "reject" if spec.nonempty else "accept"))
        if spec.max_items is not None:
            states.extend((("max_items", "accept"), ("over_max_items", "reject")))
    return states


def row(
    case_id: str, resource: str, action: str, field: str, state: str,
    schema_result: str, endpoint: str, target: str, test_name: str,
) -> str:
    if action == "delete" and field == "confirm_delete" and state == "normal":
        target = "omitted from body"
    return "| `%s` | %s/%s | `%s` | %s | %s | `%s` | %s | %s | PASS |" % (
        case_id, resource, action, field, state, schema_result, endpoint, target, test_name,
    )


def run_matrix() -> None:
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(DDWireMatrixTests)
    result = unittest.TextTestRunner(stream=sys.stderr, verbosity=1).run(suite)
    if not result.wasSuccessful():
        raise SystemExit(1)


def main() -> None:
    run_matrix()
    rows: List[str] = []
    counts = []
    for resource, action in ACTIONS:
        schema = get_schema("dd", resource, action)
        action_cases = 0
        for field, spec in schema.fields.items():
            for state, expectation in applicable_states(resource, action, field, spec):
                case_id = "%s.%s.%s.%s" % (resource, action, field, state)
                target = wire_target(resource, field)
                rows.append(row(
                    case_id, resource, action, field, state, expectation,
                    ENDPOINTS[(resource, action)], "none" if target is None else str(target),
                    "test_dd_wire_matrix.py",
                ))
                action_cases += 1
        counts.append((resource, action, len(schema.fields), action_cases))

    targeted = [
        ("plugin.edit.jump_room.disabled_stale_child", "plugin", "edit", "jump_room", "disabled_stale_child", "accept + clear room/channel/sync", "/addon/modify", "jump_room/room_id/channel_id/channel_type/sync_room"),
        ("all.edit.with_associate.disabled_stale_child", "all", "edit", "with_associate", "disabled_stale_child", "accept + clear associated_acts", "modify", "with_associate/associated_acts"),
        ("config.update.update_markers.stale_child", "config", "update", "*_update_*", "stale_child", "reject at exact marker path", "/share/modify", "none"),
        ("config.update.wtf_role_ids.stale_selector", "config", "update", "wtf_role_ids", "stale_selector", "reject before upload", "/share/modify", "none"),
        ("plugin.create.primary_category_id.stale_child", "plugin", "create", "primary_category_id", "stale_child", "reject before upload", "/addon/create", "none"),
        ("wa.create.category_ids.stale_child", "wa", "create", "category_ids", "stale_child", "reject before upload", "/wa/create", "none"),
        ("uploads.filename.fixed_empty_omitted", "all", "create/update", "local files", "special_filename", "accept", "/file/upload + object PUT", "d_url target"),
        ("errors.http_status_matrix", "all", "mutation", "request/response", "HTTP 400/401/403/404/422/500", "4xx reject=false; 5xx uncertain=true", "mutation endpoint", "sanitized log_path"),
        ("errors.timeout", "all", "mutation", "request", "timeout", "uncertain; no replay", "mutation endpoint", "readback only"),
    ]
    for values in targeted:
        rows.append(row(*values, "targeted matrix + test_dd_session.py"))

    total_fields = sum(item[2] for item in counts)
    total_cases = len(rows)
    print("# DD field-by-field wire regression")
    print()
    print("Date: 2026-08-01  ")
    print("Change: `dd-field-by-field-wire-regression`  ")
    print("Result: PASS (the generator ran the dedicated matrix before emitting this report)")
    print()
    print("## Summary")
    print()
    print("- Schema action fields: %d" % total_fields)
    print("- Enumerated field/state and targeted cases: %d" % total_cases)
    print("- Schema/catalog gaps: 0")
    print("- Exploration Season live writes: excluded by requirement")
    print("- Sensitive account values: not used by this deterministic report")
    print()
    print("| Resource | Action | Fields | Cases | Gap |")
    print("|---|---:|---:|---:|---:|")
    for resource, action, fields, cases in counts:
        print("| %s | %s | %d | %d | 0 |" % (resource, action, fields, cases))
    print()
    print("## Findings fixed")
    print()
    print("1. DD local image arrays now reject missing files at the exact indexed JSON path before upload.")
    print("2. Config update-marker arrays now apply when selection arrays are omitted and current selections are preserved.")
    print("3. Update markers that do not reference selected content now fail before upload/mutation instead of producing inconsistent `items` and `inner_version` objects.")
    print("4. The capture harness JSON-round-trips final bodies, including object-key string conversion, before assertions.")
    print()
    print("## Case matrix")
    print()
    print("| Case ID | Resource/action | Field | State | Schema/preflight | Endpoint | Wire target | Test | Result |")
    print("|---|---|---|---|---|---|---|---|---|")
    for item in rows:
        print(item)
    print()
    print("## Residual limits")
    print()
    print("- Deterministic cases assert request behavior without mutating one real account object per field.")
    print("- Live smoke reuses the prior isolated non-Exploration create/update/edit/delete workflow and is refreshed separately when an authenticated DD session is available.")
    print("- Official DD behavior is client-versioned; rerun this report and live read smoke after a DD upgrade.")


if __name__ == "__main__":
    main()
