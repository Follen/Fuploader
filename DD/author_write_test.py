"""Exploratory request builder for DD author APIs.

This artifact predates the complete resource-specific field model. It may fetch
details and generate signatures, but network writes are intentionally disabled.
Credentials and raw API responses are never printed or persisted.
"""

from __future__ import print_function

import argparse
import datetime
import json
import logging

import author_inventory_probe as inventory
import headless_probe as probe
import isolated_device_test as isolated


SOURCE_CANDIDATES = {
    "addon": (
        "4fa4eccc254b42b3a6cd33b66aea93a0",
        "f64d043a53954815b635305c2545e1b8",
        "7508c19d0fd24b0ba85604c2283efdc7",
        "e12feb6f116e4ce1bad0252846207548",
    ),
    "share": ("88d69576ee314f9a9617f0818ca54574",),
    "wa": ("0c351632eb3543e583d3ae4c5caeb8a3",),
}

ENDPOINTS = {
    "addon": ("/addon/create", "/addon/modify"),
    "share": ("/share/create", "/share/modify"),
    "wa": ("/wa/create", "/wa/modify"),
}

FIELDS = {
    "addon": (
        "game_type", "game_versions", "scope", "addon_type", "name",
        "description", "logo", "detail_imgs", "primary_category_id",
        "second_category_ids", "detail_url", "release_type", "version",
        "html_desc", "update_desc", "share_code_life_type", "need_buy",
        "price_fen", "buy_life_type", "jump_room", "room_id", "channel_id",
        "channel_type", "sync_room", "creation_statement", "with_associate",
        "associated_acts", "need_anchor_vip", "vip_levels",
    ),
    "share": (
        "game_type", "scope", "backup_sn", "desc", "update_desc", "title",
        "brief_desc", "display_imgs", "known_addon_items",
        "known_addon_inner_version", "unknown_addon_items",
        "unknown_addon_inner_version", "wtf_items", "material_items",
        "material_inner_version", "font_items", "font_inner_version",
        "known_wa_items", "known_wa_inner_version", "unknown_wa_items",
        "unknown_wa_inner_version", "share_code_life_type", "need_buy",
        "price_fen", "buy_life_type", "jump_room", "room_id", "channel_id",
        "channel_type", "sync_room", "creation_statement", "with_associate",
        "associated_acts", "need_anchor_vip", "vip_levels",
        "enable_dd_setup_wizard", "retail_config", "retail_ui_config",
    ),
    "wa": (
        "game_type", "scope", "name", "game_version", "brief_desc",
        "display_imgs", "category_ids", "content", "desc", "update_desc",
        "version", "file_install_path", "with_file", "file_path",
        "share_code_life_type", "need_buy", "price_fen", "buy_life_type",
        "jump_room", "room_id", "channel_id", "channel_type", "sync_room",
        "creation_statement", "with_associate", "associated_acts",
        "need_anchor_vip", "vip_levels", "parse_wa_uid", "parse_wa_id",
    ),
}

REQUIRED = {
    "addon": (
        "game_versions", "name", "description", "logo", "detail_imgs",
        "primary_category_id", "detail_url", "release_type", "version",
        "html_desc", "update_desc", "creation_statement",
    ),
    "share": ("title", "brief_desc", "desc", "update_desc", "creation_statement"),
    "wa": (
        "name", "game_version", "brief_desc", "display_imgs", "category_ids",
        "content", "desc", "update_desc", "version", "creation_statement",
    ),
}


def response_result(payload):
    return payload.get("result") if isinstance(payload, dict) else None


def fetch_detail(client, kind, reference):
    if kind == "addon":
        payload = client.get("/addon/detail_v2", {"sn": reference})
        if not isinstance(response_result(payload), dict):
            payload = client.get("/addon/detail", {"sn": reference})
    elif kind == "share":
        payload = client.get("/share/detail", {"sn": reference})
    else:
        payload = client.get("/wa/detail", {"sn": reference})
    result = response_result(payload)
    probe.emit(
        "author_source_detail",
        kind=kind,
        code=payload.get("code") if isinstance(payload, dict) else None,
        ready=isinstance(result, dict),
    )
    if not isinstance(result, dict):
        raise RuntimeError("%s source detail unavailable" % kind)
    return result


def copy_fields(kind, detail):
    source = dict(detail)
    latest = detail.get("latest_version")
    if isinstance(latest, dict):
        if not source.get("detail_url") and latest.get("file_path"):
            source["detail_url"] = latest["file_path"]
        for key in ("file_name", "file_path", "file_url", "release_type", "version"):
            if not source.get(key) and latest.get(key):
                source[key] = latest[key]
    return {key: source[key] for key in FIELDS[kind] if key in source}


def private_defaults(body):
    body.update(
        {
            "scope": "private",
            "share_code_life_type": "seven_day",
            "need_buy": False,
            "price_fen": 0,
            "buy_life_type": "seven_day",
            "jump_room": False,
            "room_id": "",
            "channel_id": "",
            "channel_type": "",
            "sync_room": False,
            "with_associate": False,
            "associated_acts": [],
            "need_anchor_vip": False,
            "vip_levels": [],
        }
    )


def next_version(value):
    text = str(value or "0")
    if text.isdigit():
        return str(int(text) + 1)
    parts = text.split(".")
    if parts and all(part.isdigit() for part in parts):
        parts[-1] = str(int(parts[-1]) + 1)
        return ".".join(parts)
    return text + ".1"


def build_create_body(kind, detail, run_tag):
    body = copy_fields(kind, detail)
    private_defaults(body)
    label_key = "title" if kind == "share" else "name"
    original = str(body.get(label_key) or kind)
    body[label_key] = (original[:80] + " [Fupload API %s]" % run_tag)[:120]
    body["update_desc"] = "Fupload API create test %s" % run_tag
    if kind == "wa" and str(body.get("content", "")).startswith("!WA:2!"):
        body.setdefault("parse_wa_uid", detail.get("parse_wa_uid", ""))
        body.setdefault("parse_wa_id", detail.get("parse_wa_id", ""))
    return body


def build_modify_body(kind, create_body, reference, run_tag):
    body = dict(create_body)
    body["update_desc"] = "Fupload API modify test %s" % run_tag
    if kind == "share":
        body["share_sn"] = reference
    else:
        body["sn"] = reference
    if kind == "wa":
        body["version"] = next_version(body.get("version"))
    return body


def missing_required(kind, body):
    return [key for key in REQUIRED[kind] if body.get(key) in (None, "", [])]


def signed(nep, client, path, body):
    encoded = json.dumps(body, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    code, signed_url = nep.getHttpPostSignedUrl(
        client.base_url + path,
        encoded,
        client._buildExtraArgs(),
    )
    ready = bool(code == 1 and signed_url)
    signed_url = None
    return ready


def response_reference(kind, payload):
    result = response_result(payload)
    if isinstance(result, str):
        return result
    if isinstance(result, dict):
        if kind == "share":
            return str(result.get("share_sn") or result.get("sn") or "")
        return str(result.get("sn") or "")
    return ""


def find_created(client, kind, name, game_type):
    common = {
        "game_type": game_type,
        "origin": "created",
        "page": 1,
        "size": 100,
        "search_text": name,
    }
    if kind == "addon":
        payload = client.post(
            "/addon/addon_list",
            dict(
                common,
                category=0,
                name_or_author_name_or_share_code=name,
                sort_type=2,
            ),
        )
    elif kind == "share":
        payload = client.get("/share/list", dict(common, sort_type="mtime"))
    else:
        payload = client.get(
            "/wa/list",
            dict(common, category_id="", sort_type="mtime"),
        )
    for item in inventory.result_items(payload):
        item_name = str(item.get("title") or item.get("name") or "")
        if item_name == name:
            return str(item.get("share_sn") or item.get("sn") or "")
    return ""


def execute_create(client, kind, create_body):
    create_path, _modify_path = ENDPOINTS[kind]
    try:
        created = client.post(create_path, create_body)
    except Exception as exc:
        probe.emit(
            "author_create_result",
            kind=kind,
            ok=False,
            error_type=type(exc).__name__,
            request_sent=True,
        )
        return False
    create_code = created.get("code") if isinstance(created, dict) else None
    reference = response_reference(kind, created)
    label_key = "title" if kind == "share" else "name"
    if create_code == 0 and not reference:
        reference = find_created(
            client,
            kind,
            create_body[label_key],
            create_body.get("game_type", 10001),
        )
    probe.emit(
        "author_create_result",
        kind=kind,
        code=create_code,
        reference_ready=bool(reference),
        request_sent=True,
    )
    return create_code == 0 and bool(reference)


def execute_existing_modify(client, kind, body, reference, run_tag):
    _create_path, modify_path = ENDPOINTS[kind]
    modify_body = build_modify_body(kind, body, reference, run_tag)
    try:
        modified = client.post(modify_path, modify_body)
    except Exception as exc:
        probe.emit(
            "author_modify_result",
            kind=kind,
            ok=False,
            error_type=type(exc).__name__,
            request_sent=True,
        )
        return False
    modify_code = modified.get("code") if isinstance(modified, dict) else None
    probe.emit(
        "author_modify_result",
        kind=kind,
        code=modify_code,
        request_sent=True,
    )
    return modify_code == 0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute", default="")
    parser.add_argument("--kind", choices=("addon", "share", "wa"), action="append")
    args = parser.parse_args()
    if args.execute:
        print(
            "DDPROBE "
            + json.dumps(
                {
                    "event": "author_write_test",
                    "ok": False,
                    "reason": "execute_disabled_incomplete_resource_builders",
                    "request_sent": False,
                },
                sort_keys=True,
            )
        )
        return 5
    execute = False
    selected_kinds = args.kind or ["addon", "share", "wa"]
    run_tag = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")

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
        nep = NepWrapper(None)
        client = UiApiClient(
            nep,
            login_cookie=getattr(login_controller, "_cookie", None),
        )
        client._session.headers["User-Agent"] = probe.DD_USER_AGENT
        if not client.login():
            probe.emit("author_write_test", ok=False, reason="author_login_failed")
            return 2

        bodies = {}
        existing_bodies = {}
        selected_sources = {}
        dry_run_ok = True
        for kind in selected_kinds:
            detail = None
            body = None
            missing = []
            selected_source = ""
            for candidate in SOURCE_CANDIDATES[kind]:
                candidate_detail = fetch_detail(client, kind, candidate)
                candidate_body = build_create_body(kind, candidate_detail, run_tag)
                candidate_missing = missing_required(kind, candidate_body)
                if body is None or len(candidate_missing) < len(missing):
                    detail = candidate_detail
                    body = candidate_body
                    missing = candidate_missing
                    selected_source = candidate
                if not candidate_missing:
                    break
            bodies[kind] = body
            existing_bodies[kind] = copy_fields(kind, detail)
            selected_sources[kind] = selected_source
            create_path, modify_path = ENDPOINTS[kind]
            create_ready = signed(nep, client, create_path, body)
            modify_ready = signed(
                nep,
                client,
                modify_path,
                build_modify_body(kind, body, selected_source, run_tag),
            )
            dry_run_ok = dry_run_ok and not missing and create_ready and modify_ready
            probe.emit(
                "author_write_dry_run",
                kind=kind,
                field_count=len(body),
                missing_required=missing,
                create_signature_ready=create_ready,
                modify_signature_ready=modify_ready,
                request_sent=False,
            )

        if not execute:
            probe.emit(
                "author_write_test",
                ok=dry_run_ok,
                mode="dry_run",
                state_created=state_created,
            )
            return 0 if dry_run_ok else 3
        if not dry_run_ok:
            probe.emit("author_write_test", ok=False, reason="dry_run_validation_failed")
            return 3

        modify_results = [
            execute_existing_modify(
                client,
                kind,
                existing_bodies[kind],
                selected_sources[kind],
                run_tag,
            )
            for kind in bodies
        ]
        create_results = [execute_create(client, kind, bodies[kind]) for kind in bodies]
        probe.emit(
            "author_write_test",
            ok=all(modify_results) and all(create_results),
            mode="execute",
            created_count=sum(1 for result in create_results if result),
            modified_count=sum(1 for result in modify_results if result),
            state_created=state_created,
        )
        return 0 if all(modify_results) and all(create_results) else 4
    finally:
        if client:
            client._token = ""
            client.close()
        logging.disable(previous_logging_disable)
        probe.close_native_session(session)
        machine_data.clientNo = original_client_no


if __name__ == "__main__":
    raise SystemExit(main())
