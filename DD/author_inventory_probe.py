"""Read-only inventory probe for the current DD author account.

Run with DD's version-matched ``netease_dd.exe``. Authentication material and
raw API responses are intentionally never printed or persisted.
"""

from __future__ import print_function

import json
import logging

import headless_probe as probe
import isolated_device_test as isolated


def result_items(payload):
    result = payload.get("result") if isinstance(payload, dict) else None
    if isinstance(result, list):
        return result
    if isinstance(result, dict):
        for key in ("data_list", "list", "rows", "items", "wa_list", "shares"):
            value = result.get(key)
            if isinstance(value, list):
                return value
    return []


def game_type_ids(client):
    payload = client.get("/game_type/list")
    values = []
    for item in result_items(payload):
        if not isinstance(item, dict):
            continue
        value = item.get("game_type", item.get("id"))
        try:
            values.append(int(value))
        except (TypeError, ValueError):
            pass
    return sorted(set(values)) or [1, 2, 10001]


def safe_item(kind, item, fallback_game_type):
    reference = item.get("share_sn") or item.get("sn") or ""
    version = item.get("version") or item.get("current_version") or ""
    latest_version = item.get("latest_version")
    if not version and isinstance(latest_version, dict):
        version = latest_version.get("version") or ""
    elif not version and latest_version:
        version = latest_version
    return {
        "kind": kind,
        "reference": str(reference),
        "name": str(item.get("name") or item.get("title") or "")[:160],
        "version": str(version)[:80],
        "status": str(
            item.get("status")
            or item.get("audit_status")
            or item.get("state")
            or ""
        )[:80],
        "game_type": item.get("game_type", fallback_game_type),
        "scope": str(item.get("scope") or "")[:40],
        "is_owner": bool(item.get("is_owner", True)),
    }


def collect(client, game_type):
    common = {
        "game_type": game_type,
        "origin": "created",
        "page": 1,
        "size": 100,
    }
    output = []
    addon_payload = client.post(
        "/addon/addon_list",
        dict(
            common,
            category=0,
            name_or_author_name_or_share_code="",
            sort_type=2,
        ),
    )
    addon_items = result_items(addon_payload)
    probe.emit(
        "author_inventory_page",
        kind="addon",
        game_type=game_type,
        code=addon_payload.get("code"),
        count=len(addon_items),
    )
    output.extend(safe_item("addon", item, game_type) for item in addon_items)

    calls = (
        (
            "share",
            lambda: client.get(
                "/share/list",
                dict(common, search_text="", sort_type="mtime"),
            ),
        ),
        (
            "wa",
            lambda: client.get(
                "/wa/list",
                dict(common, search_text="", category_id="", sort_type="mtime"),
            ),
        ),
    )
    for kind, call in calls:
        try:
            payload = call()
            code = payload.get("code") if isinstance(payload, dict) else None
            items = result_items(payload)
            probe.emit(
                "author_inventory_page",
                kind=kind,
                game_type=game_type,
                code=code,
                count=len(items),
            )
            output.extend(safe_item(kind, item, game_type) for item in items)
        except Exception as exc:
            probe.emit(
                "author_inventory_page",
                kind=kind,
                game_type=game_type,
                ok=False,
                error_type=type(exc).__name__,
            )
    return output


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
            probe.emit("author_inventory", ok=False, reason="author_login_failed")
            return 2

        items = []
        for game_type in game_type_ids(client):
            items.extend(collect(client, game_type))

        deduplicated = {}
        for item in items:
            key = (item["kind"], item["reference"] or item["name"])
            deduplicated[key] = item
        ordered = sorted(
            deduplicated.values(),
            key=lambda item: (item["kind"], str(item["game_type"]), item["name"]),
        )
        probe.emit(
            "author_inventory",
            ok=True,
            count=len(ordered),
            state_created=state_created,
        )
        for item in ordered:
            print("DDPROBE " + json.dumps(item, ensure_ascii=False, sort_keys=True))
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
