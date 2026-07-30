"""Read-only schema probe for DD author details and option endpoints.

Only field names, container types, list counts, and scalar presence are emitted.
No response values, credentials, signed URLs, or author content are persisted.
"""

from __future__ import print_function

import json
import logging

import headless_probe as probe
import isolated_device_test as isolated


SOURCES = {
    "addon": "4fa4eccc254b42b3a6cd33b66aea93a0",
    "share": "88d69576ee314f9a9617f0818ca54574",
    "wa": "0c351632eb3543e583d3ae4c5caeb8a3",
}


def result(payload):
    return payload.get("result") if isinstance(payload, dict) else None


def shape(value, depth=0, max_depth=4):
    if isinstance(value, dict):
        if depth >= max_depth:
            return {"type": "object", "keys": sorted(value.keys())}
        return {
            "type": "object",
            "fields": {
                key: shape(value[key], depth + 1, max_depth)
                for key in sorted(value.keys())
            },
        }
    if isinstance(value, list):
        output = {"type": "array", "count": len(value)}
        if value:
            output["item"] = shape(value[0], depth + 1, max_depth)
        return output
    return {"type": type(value).__name__, "present": value not in (None, "")}


def emit_schema(name, payload):
    value = result(payload)
    probe.emit(
        "author_schema",
        name=name,
        code=payload.get("code") if isinstance(payload, dict) else None,
        schema=shape(value),
    )
    return value


def main():
    probe.bootstrap()
    import datacenter.local_data.machine_data as machine_data

    original_client_no = machine_data.clientNo
    client_no, state_created = isolated.load_or_create_client_no(machine_data)
    machine_data.clientNo = client_no
    session = None
    client = None
    previous_logging_disable = logging.root.manager.disable
    try:
        session = probe.open_native_session(45)
        logging.disable(logging.CRITICAL)
        from components.wow_ui.nep_wrapper import NepWrapper
        from cli_anything.ccvoicehub.core.ui_api_client import UiApiClient

        login_controller = session["container"].get_instance("LoginController")
        client = UiApiClient(
            NepWrapper(None),
            login_cookie=getattr(login_controller, "_cookie", None),
        )
        client._session.headers["User-Agent"] = probe.DD_USER_AGENT
        if not client.login():
            probe.emit("author_schema_probe", ok=False, reason="author_login_failed")
            return 2

        addon = emit_schema(
            "addon_detail_v2",
            client.get("/addon/detail_v2", {"sn": SOURCES["addon"]}),
        )
        if not isinstance(addon, dict):
            emit_schema(
                "addon_detail",
                client.get("/addon/detail", {"sn": SOURCES["addon"]}),
            )
        emit_schema(
            "addon_versions",
            client.get(
                "/addon/addon_versions",
                {"sn": SOURCES["addon"], "game_type": 10001, "page": 1},
            ),
        )
        share = emit_schema(
            "share_detail",
            client.get("/share/detail", {"sn": SOURCES["share"]}),
        )
        emit_schema(
            "wa_detail",
            client.get("/wa/detail", {"sn": SOURCES["wa"]}),
        )

        backup_sn = share.get("backup_sn") if isinstance(share, dict) else None
        if backup_sn:
            emit_schema("backup_detail", client.get("/backup/detail", {"sn": backup_sn}))

        option_calls = (
            ("game_types", "/game_type/list", None),
            ("game_versions", "/game_versions/list", {"game_type": 10001}),
            ("addon_categories", "/addon/category", None),
            ("wa_categories", "/wa/categories", {"game_type": 10001}),
            ("life_types", "/act/life_type_cfgs", {"game_type": 10001}),
            ("vip_levels", "/anchor_vip/level/list", {"enrich_acts": False}),
            ("backup_list", "/backup/list", None),
        )
        for name, path, params in option_calls:
            emit_schema(name, client.get(path, params) if params else client.get(path))

        probe.emit("author_schema_probe", ok=True, state_created=state_created)
        return 0
    finally:
        if client:
            client._token = ""
            client.close()
        logging.disable(previous_logging_disable)
        probe.close_native_session(session)
        machine_data.clientNo = original_client_no


if __name__ == "__main__":
    raise SystemExit(main())
