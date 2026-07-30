"""Controlled end-to-end CRUD probe for DD author APIs.

The probe uses resource-specific allowlisted builders, creates clearly named
public test entries, modifies only those entries, and verifies them with GET.
Credentials, complete payloads, author content, and signed URLs are never
printed or persisted.
"""

from __future__ import print_function

import argparse
import copy
import datetime
import json
import logging
import time
import urllib.request

import author_inventory_probe as inventory
import headless_probe as probe
import isolated_device_test as isolated


EXECUTE_PHRASE = "EXECUTE_DD_AUTHOR_CRUD"
GAME_TYPE = 10001
SOURCES = {
    "addon": "4fa4eccc254b42b3a6cd33b66aea93a0",
    "share": "88d69576ee314f9a9617f0818ca54574",
    "wa": "0c351632eb3543e583d3ae4c5caeb8a3",
}
ENDPOINTS = {
    "addon": ("/addon/create", "/addon/modify"),
    "share": ("/share/create", "/share/modify"),
    "wa": ("/wa/create", "/wa/modify"),
}


def api_result(payload):
    return payload.get("result") if isinstance(payload, dict) else None


def clone(value):
    return copy.deepcopy(value)


def safe_http_error(exc):
    response = getattr(exc, "response", None)
    status = getattr(response, "status_code", None)
    code = None
    message = ""
    result_keys = []
    if response is not None:
        try:
            payload = response.json()
        except Exception:
            payload = None
        if isinstance(payload, dict):
            code = payload.get("code")
            message = str(payload.get("msg") or payload.get("message") or "")[:240]
            result = payload.get("result")
            if isinstance(result, dict):
                result_keys = sorted(result.keys())[:40]
    return {
        "error_type": type(exc).__name__,
        "http_status": status,
        "response_code": code,
        "message": message,
        "result_keys": result_keys,
    }


def post(client, kind, action, path, body):
    try:
        payload = client.post(path, body)
    except Exception as exc:
        probe.emit(
            "author_crud_post",
            kind=kind,
            action=action,
            path=path,
            ok=False,
            request_sent=True,
            field_count=len(body),
            **safe_http_error(exc)
        )
        return None
    code = payload.get("code") if isinstance(payload, dict) else None
    probe.emit(
        "author_crud_post",
        kind=kind,
        action=action,
        path=path,
        ok=code == 0,
        code=code,
        message=str(payload.get("msg") or "")[:240] if isinstance(payload, dict) else "",
        request_sent=True,
        field_count=len(body),
    )
    return payload


def get_detail(client, kind, reference):
    if kind == "addon":
        payload = client.get("/addon/detail_v2", {"sn": reference})
        if not isinstance(api_result(payload), dict):
            payload = client.get("/addon/detail", {"sn": reference})
    elif kind == "share":
        payload = client.get("/share/detail", {"sn": reference})
    else:
        payload = client.get("/wa/detail", {"sn": reference})
    value = api_result(payload)
    probe.emit(
        "author_crud_get_detail",
        kind=kind,
        code=payload.get("code") if isinstance(payload, dict) else None,
        ready=isinstance(value, dict),
    )
    return value if isinstance(value, dict) else None


def public_defaults(body, include_share_life):
    body.update(
        {
            "scope": "public",
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
    if include_share_life:
        body["share_code_life_type"] = "forever"
    else:
        body.pop("share_code_life_type", None)


def tagged_name(original, prefix, tag, limit):
    suffix = " [%s-%s]" % (prefix, tag)
    return (str(original)[: max(1, limit - len(suffix))] + suffix)[:limit]


def next_version(value):
    text = str(value or "0")
    if text.isdigit():
        return str(int(text) + 1)
    parts = text.split(".")
    if parts and all(part.isdigit() for part in parts):
        parts[-1] = str(int(parts[-1]) + 1)
        return ".".join(parts)
    return text + ".1"


def build_addon(detail, categories, tag, for_create):
    latest = detail.get("latest_version") or {}
    second = list(detail.get("second_category_ids") or [])
    if second:
        second = second[:-1]
    primary = detail.get("primary_category_id")
    category = next((item for item in categories if item.get("id") == primary), None)
    children = list((category or {}).get("children") or [])
    child_ids = {item.get("id") for item in children}
    second = [item for item in second if item in child_ids]
    if children and not second:
        second = [children[0].get("id")]

    body = {
        "game_type": (detail.get("game_types") or [GAME_TYPE])[0],
        "game_versions": clone(latest.get("game_versions") or detail.get("game_versions") or []),
        "addon_type": detail.get("addon_type", 0),
        "name": detail.get("name") or "Fupload addon test",
        "description": detail.get("description") or "Fupload DD author API test",
        "logo": detail.get("logo") or "",
        "detail_imgs": clone(detail.get("detail_imgs") or []),
        "primary_category_id": primary,
        "second_category_ids": second,
        "detail_url": latest.get("file_path") or detail.get("detail_url") or "",
        "release_type": latest.get("release_type") or detail.get("release_type") or 1,
        "version": latest.get("version") or detail.get("version") or "1.0.0",
        "html_desc": detail.get("html_desc") or "Fupload DD author API test",
        "update_desc": "Fupload addon create verification %s" % tag,
        "creation_statement": detail.get("creation_statement") or "original",
    }
    public_defaults(body, include_share_life=True)
    if for_create:
        body["name"] = tagged_name(body["name"], "Fupload-addon", tag, 80)
    return body


def item_key(item, id_field):
    return item.get(id_field) if isinstance(item, dict) else item


def selected_content(backup, detail, key, id_field):
    available = list(((backup.get(key) or {}).get("items") or []))
    selected = list(((detail.get(key) or {}).get("items") or []))
    selected_keys = {item_key(item, id_field) for item in selected}
    items = [clone(item) for item in available if item_key(item, id_field) in selected_keys]
    inner_version = {
        str(item_key(item, id_field)): 1
        for item in available
        if item_key(item, id_field) not in (None, "")
    }
    return {"items": items, "inner_version": inner_version}


def default_retail_config(backup):
    raw = backup.get("retail_ui_config") or {}
    edit_mode = {}
    selected_count = 0
    default_assigned = False
    for account, entries in (raw.get("editMode") or {}).items():
        selected = []
        for entry in entries or []:
            if selected_count >= 5:
                break
            value = clone(entry)
            value["is_default"] = not default_assigned
            default_assigned = True
            selected.append(value)
            selected_count += 1
        if selected:
            edit_mode[account] = selected
        if selected_count >= 5:
            break

    cool_down = {}
    seen_specs = set()
    for account, entries in (raw.get("coolDown") or {}).items():
        selected = []
        for entry in entries or []:
            spec_tag = entry.get("spec_tag")
            if spec_tag in seen_specs:
                continue
            seen_specs.add(spec_tag)
            selected.append(clone(entry))
        if selected:
            cool_down[account] = selected
    return {
        "edit_mode": edit_mode,
        "cool_down": cool_down,
        "enable_dd_setup_wizard": True,
    }


def build_share(detail, backup, tag, for_create):
    body = {
        "backup_sn": detail.get("backup_sn"),
        "desc": detail.get("desc") or "Fupload DD author API test",
        "display_imgs": clone(detail.get("display_imgs") or []),
        "title": detail.get("title") or "Fupload config test",
        "brief_desc": detail.get("brief_desc") or "Fupload DD author API test",
        "update_desc": "Fupload config create verification %s" % tag,
        "known_addon": selected_content(backup, detail, "known_addon", "addon_id"),
        "unknown_addon": selected_content(backup, detail, "unknown_addon", None),
        "wtf": {"accounts": clone(((detail.get("wtf") or {}).get("accounts") or []))},
        "material": selected_content(backup, detail, "material", "name"),
        "font": selected_content(backup, detail, "font", None),
        "known_wa": {"items": [], "inner_version": {}},
        "unknown_wa": {"items": [], "inner_version": {}},
        "retail_ui_config": default_retail_config(backup),
        "creation_statement": detail.get("creation_statement") or "original",
    }
    public_defaults(body, include_share_life=False)
    if for_create:
        body["title"] = tagged_name(body["title"], "Fupload-config", tag, 40)
    return body


WA_FIELDS = (
    "game_type",
    "game_version",
    "brief_desc",
    "display_imgs",
    "category_ids",
    "content",
    "desc",
    "version",
    "file_install_path",
    "with_file",
    "file_path",
    "creation_statement",
    "parse_wa_uid",
    "parse_wa_id",
)


def build_wa(detail, tag, for_create):
    body = {key: clone(detail.get(key)) for key in WA_FIELDS}
    body["name"] = detail.get("name") or "Fupload WA test"
    body["update_desc"] = "Fupload WA create verification %s" % tag
    body["game_type"] = body.get("game_type") or GAME_TYPE
    body["creation_statement"] = body.get("creation_statement") or "original"
    body["with_file"] = bool(body.get("with_file"))
    body["file_path"] = body.get("file_path") or ""
    body["file_install_path"] = body.get("file_install_path") or ""
    public_defaults(body, include_share_life=True)
    if for_create:
        body["name"] = tagged_name(body["name"], "Fupload-WA", tag, 40)
    return body


def required_missing(kind, body):
    required = {
        "addon": (
            "game_versions", "name", "description", "logo", "detail_imgs",
            "primary_category_id", "detail_url", "release_type", "version",
            "html_desc", "update_desc", "creation_statement",
        ),
        "share": (
            "backup_sn", "title", "brief_desc", "desc", "display_imgs",
            "known_addon", "unknown_addon", "wtf", "material", "font",
            "known_wa", "unknown_wa", "update_desc", "creation_statement",
        ),
        "wa": (
            "name", "game_version", "brief_desc", "display_imgs", "category_ids",
            "content", "desc", "update_desc", "version", "creation_statement",
        ),
    }[kind]
    return [key for key in required if body.get(key) in (None, "", [])]


def sign_ready(nep, client, path, body):
    encoded = json.dumps(body, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    code, signed_url = nep.getHttpPostSignedUrl(
        client.base_url + path, encoded, client._buildExtraArgs()
    )
    ready = bool(code == 1 and signed_url)
    signed_url = None
    return ready


def response_reference(kind, payload):
    value = api_result(payload)
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return str(value.get("share_sn") or value.get("sn") or "")
    return ""


def find_reference(client, kind, name, game_type):
    common = {"game_type": game_type, "origin": "created", "page": 1, "size": 100}
    if kind == "addon":
        payload = client.post(
            "/addon/addon_list",
            dict(common, category=0, name_or_author_name_or_share_code=name, sort_type=2),
        )
    elif kind == "share":
        payload = client.get(
            "/share/list", dict(common, search_text=name, sort_type="mtime")
        )
    else:
        payload = client.get(
            "/wa/list",
            dict(common, search_text=name, category_id="", sort_type="mtime"),
        )
    for item in inventory.result_items(payload):
        item_name = str(item.get("title") or item.get("name") or "")
        if item_name == name:
            return str(item.get("share_sn") or item.get("sn") or "")
    return ""


def wait_reference(client, kind, name, game_type, payload):
    reference = response_reference(kind, payload)
    for _attempt in range(30):
        if reference:
            return reference
        reference = find_reference(client, kind, name, game_type)
        if reference:
            return reference
        time.sleep(2)
    return ""


def wait_detail(client, kind, reference):
    for _attempt in range(12):
        detail = get_detail(client, kind, reference)
        if detail:
            return detail
        time.sleep(2)
    return None


def upload_plugin_zip(client, source_url):
    with urllib.request.urlopen(source_url, timeout=60) as response:
        data = response.read()
    auth = client.get(
        "/file/upload",
        {
            "file_type": "a19-ui-res",
            "file_name": "addon.zip",
            "business_id": "addon",
            "mime_type": "application/x-zip-compressed",
        },
    )
    info = api_result(auth)
    if not isinstance(info, dict) or not info.get("url") or not info.get("d_url"):
        probe.emit("author_upload", ok=False, stage="authorization", code=auth.get("code"))
        return ""
    max_size = int(info.get("maxSize") or 0)
    if max_size and len(data) > max_size:
        probe.emit(
            "author_upload", ok=False, stage="size_check", size=len(data), max_size=max_size
        )
        return ""
    request = urllib.request.Request(
        info["url"],
        data=data,
        method="PUT",
        headers={
            "Content-Type": "application/x-zip-compressed",
            "X-Amz-Acl": "public-read",
        },
    )
    with urllib.request.urlopen(request, timeout=120) as response:
        status = response.getcode()
    probe.emit(
        "author_upload",
        ok=status == 200,
        stage="put",
        status=status,
        size=len(data),
        d_url_ready=bool(info.get("d_url")),
    )
    return info.get("d_url") if status == 200 else ""


def create_and_modify(client, kind, create_body, build_modify, tag):
    create_path, modify_path = ENDPOINTS[kind]
    created = post(client, kind, "create", create_path, create_body)
    if not isinstance(created, dict) or created.get("code") != 0:
        return False, ""
    name_key = "title" if kind == "share" else "name"
    reference = wait_reference(
        client, kind, create_body[name_key], create_body.get("game_type", GAME_TYPE), created
    )
    probe.emit("author_crud_reference", kind=kind, ready=bool(reference), reference=reference)
    if not reference:
        return False, ""
    detail = wait_detail(client, kind, reference)
    if not detail:
        return False, reference
    modify_body, marker = build_modify(detail, reference, tag)
    modified = post(client, kind, "modify", modify_path, modify_body)
    if not isinstance(modified, dict) or modified.get("code") != 0:
        return False, reference
    verified = None
    marker_match = False
    for _attempt in range(12):
        verified = get_detail(client, kind, reference)
        marker_match = bool(verified and verified.get("update_desc") == marker)
        if marker_match:
            break
        time.sleep(2)
    version_visible = None
    if kind in ("addon", "wa") and verified:
        visible_version = verified.get("version") or (verified.get("latest_version") or {}).get("version")
        version_visible = str(visible_version) == str(modify_body["version"])
    ok = marker_match
    probe.emit(
        "author_crud_verify",
        kind=kind,
        ok=ok,
        marker_match=marker_match,
        version_visible=version_visible,
        reference=reference,
    )
    return ok, reference


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute", default="")
    parser.add_argument("--kind", choices=("addon", "share", "wa"), action="append")
    parser.add_argument("--skip-upload", action="store_true")
    parser.add_argument("--verify-reference", default="")
    parser.add_argument("--modify-reference", default="")
    args = parser.parse_args()
    execute = args.execute == EXECUTE_PHRASE
    if args.execute and not execute:
        probe.emit("author_crud", ok=False, reason="invalid_execute_phrase", request_sent=False)
        return 5
    kinds = args.kind or ["addon", "share", "wa"]
    tag = datetime.datetime.now().strftime("%m%d%H%M%S")

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
            nep, login_cookie=getattr(login_controller, "_cookie", None)
        )
        client._session.headers["User-Agent"] = probe.DD_USER_AGENT
        if not client.login():
            probe.emit("author_crud", ok=False, reason="author_login_failed")
            return 2

        if args.verify_reference:
            if len(kinds) != 1:
                probe.emit("author_crud", ok=False, reason="verify_requires_one_kind")
                return 3
            kind = kinds[0]
            detail = wait_detail(client, kind, args.verify_reference)
            prefix = {
                "addon": "Fupload addon modify verification ",
                "share": "Fupload config modify verification ",
                "wa": "Fupload WA modify verification ",
            }[kind]
            marker_match = bool(
                detail and str(detail.get("update_desc") or "").startswith(prefix)
            )
            version_count = None
            version_marker_match = None
            version_states = []
            if kind == "addon":
                try:
                    versions_payload = client.get(
                        "/addon/addon_versions",
                        {
                            "sn": args.verify_reference,
                            "game_type": GAME_TYPE,
                            "page": 1,
                        },
                    )
                    versions = inventory.result_items(versions_payload)
                except Exception as exc:
                    versions = []
                    probe.emit(
                        "author_crud_version_get",
                        kind=kind,
                        ok=False,
                        **safe_http_error(exc)
                    )
                version_count = len(versions)
                version_marker_match = any(
                    str(item.get("update_desc") or "").startswith(prefix)
                    for item in versions
                    if isinstance(item, dict)
                )
                version_states = sorted(
                    {
                        str(
                            item.get("status")
                            or item.get("audit_state")
                            or item.get("state")
                            or ""
                        )
                        for item in versions
                        if isinstance(item, dict)
                    }
                )
                marker_match = marker_match or version_marker_match
            probe.emit(
                "author_crud_verify_existing",
                kind=kind,
                ok=marker_match,
                marker_match=marker_match,
                version_count=version_count,
                version_marker_match=version_marker_match,
                version_states=version_states,
                reference=args.verify_reference,
                request_sent=False,
            )
            return 0 if marker_match else 8

        categories = api_result(client.get("/addon/category")) or []
        source_details = {
            kind: get_detail(client, kind, SOURCES[kind]) for kind in kinds
        }
        if any(not source_details[kind] for kind in kinds):
            probe.emit("author_crud", ok=False, reason="source_detail_missing")
            return 3

        backup = None
        if "share" in kinds:
            backup_sn = source_details["share"].get("backup_sn")
            backup = api_result(client.get("/backup/detail", {"sn": backup_sn}))
            if not isinstance(backup, dict):
                probe.emit("author_crud", ok=False, reason="backup_detail_missing")
                return 3

        if args.modify_reference:
            if not execute or len(kinds) != 1:
                probe.emit(
                    "author_crud",
                    ok=False,
                    reason="modify_resume_requires_execute_and_one_kind",
                    request_sent=False,
                )
                return 3
            kind = kinds[0]
            detail = wait_detail(client, kind, args.modify_reference)
            if not detail:
                probe.emit("author_crud", ok=False, reason="modify_target_missing")
                return 3
            if kind == "addon":
                body = build_addon(detail, categories, tag, False)
                marker = "Fupload addon modify verification %s" % tag
                body.update(
                    {
                        "sn": args.modify_reference,
                        "update_desc": marker,
                        "version": next_version(body["version"]),
                    }
                )
            elif kind == "share":
                target_backup = api_result(
                    client.get("/backup/detail", {"sn": detail.get("backup_sn")})
                )
                body = build_share(detail, target_backup, tag, False)
                marker = "Fupload config modify verification %s" % tag
                body.update(
                    {"share_sn": args.modify_reference, "update_desc": marker}
                )
            else:
                body = build_wa(detail, tag, False)
                marker = "Fupload WA modify verification %s" % tag
                body.update(
                    {
                        "sn": args.modify_reference,
                        "update_desc": marker,
                        "version": next_version(body["version"]),
                    }
                )
            _create_path, modify_path = ENDPOINTS[kind]
            modified = post(client, kind, "modify_resume", modify_path, body)
            accepted = bool(isinstance(modified, dict) and modified.get("code") == 0)
            marker_match = False
            if accepted:
                for _attempt in range(12):
                    verified = get_detail(client, kind, args.modify_reference)
                    marker_match = bool(
                        verified and verified.get("update_desc") == marker
                    )
                    if marker_match:
                        break
                    time.sleep(2)
            probe.emit(
                "author_crud_modify_resume",
                kind=kind,
                accepted=accepted,
                detail_marker_visible=marker_match,
                ok=accepted,
                reference=args.modify_reference,
            )
            return 0 if accepted else 7

        builders = {}
        if "addon" in kinds:
            builders["addon"] = build_addon(source_details["addon"], categories, tag, True)
        if "share" in kinds:
            builders["share"] = build_share(source_details["share"], backup, tag, True)
        if "wa" in kinds:
            builders["wa"] = build_wa(source_details["wa"], tag, True)

        dry_ok = True
        for kind, body in builders.items():
            create_path, modify_path = ENDPOINTS[kind]
            missing = required_missing(kind, body)
            create_ready = sign_ready(nep, client, create_path, body)
            probe_body = clone(body)
            probe_body["share_sn" if kind == "share" else "sn"] = SOURCES[kind]
            modify_ready = sign_ready(nep, client, modify_path, probe_body)
            ready = not missing and create_ready and modify_ready
            dry_ok = dry_ok and ready
            probe.emit(
                "author_crud_dry_run",
                kind=kind,
                ok=ready,
                field_count=len(body),
                missing=missing,
                create_signature_ready=create_ready,
                modify_signature_ready=modify_ready,
                request_sent=False,
            )
        if not execute:
            probe.emit(
                "author_crud", ok=dry_ok, mode="dry_run", state_created=state_created
            )
            return 0 if dry_ok else 4
        if not dry_ok:
            probe.emit("author_crud", ok=False, reason="dry_run_failed")
            return 4

        if "addon" in builders and not args.skip_upload:
            uploaded = upload_plugin_zip(client, builders["addon"]["detail_url"])
            if not uploaded:
                probe.emit("author_crud", ok=False, reason="plugin_upload_failed")
                return 6
            builders["addon"]["detail_url"] = uploaded

        results = {}
        references = {}
        for kind in kinds:
            if kind == "addon":
                def build_modify(detail, reference, current_tag):
                    body = build_addon(detail, categories, current_tag, False)
                    marker = "Fupload addon modify verification %s" % current_tag
                    body.update(
                        {"sn": reference, "update_desc": marker, "version": next_version(body["version"])}
                    )
                    return body, marker
            elif kind == "share":
                def build_modify(detail, reference, current_tag):
                    current_backup = api_result(
                        client.get("/backup/detail", {"sn": detail.get("backup_sn")})
                    )
                    body = build_share(detail, current_backup, current_tag, False)
                    marker = "Fupload config modify verification %s" % current_tag
                    body.update({"share_sn": reference, "update_desc": marker})
                    return body, marker
            else:
                def build_modify(detail, reference, current_tag):
                    body = build_wa(detail, current_tag, False)
                    marker = "Fupload WA modify verification %s" % current_tag
                    body.update(
                        {"sn": reference, "update_desc": marker, "version": next_version(body["version"])}
                    )
                    return body, marker
            ok, reference = create_and_modify(
                client, kind, builders[kind], build_modify, tag
            )
            results[kind] = ok
            references[kind] = reference

        probe.emit(
            "author_crud",
            ok=all(results.values()),
            mode="execute",
            results=results,
            references=references,
            state_created=state_created,
        )
        return 0 if all(results.values()) else 7
    finally:
        if client:
            client._token = ""
            client.close()
        logging.disable(previous_logging_disable)
        probe.close_native_session(session)
        machine_data.clientNo = original_client_no


if __name__ == "__main__":
    raise SystemExit(main())
