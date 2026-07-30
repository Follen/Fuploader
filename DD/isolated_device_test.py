"""Concurrent-session test with a stable DD sidecar device identity.

Only the non-secret client number is persisted. Credentials, JWTs, cookies,
and signed URLs are never printed or written to disk.
"""

from __future__ import print_function

import argparse
import json
import logging
import os
import re
import time

import headless_probe as probe


DEVICE_STATE_PATH = os.environ.get(
    "FUPLOAD_DD_DEVICE_STATE",
    os.path.join(os.path.dirname(__file__), "sidecar-device.json"),
)


def load_or_create_client_no(machine_data):
    try:
        with open(DEVICE_STATE_PATH, "r", encoding="utf-8") as handle:
            value = json.load(handle).get("client_no", "")
        if re.fullmatch(r"[0-9a-f]{32}", value):
            return value, False
    except (FileNotFoundError, OSError, ValueError, AttributeError):
        pass

    value = machine_data.generateClientNo()
    if not re.fullmatch(r"[0-9a-f]{32}", value):
        raise RuntimeError("DD generated an invalid client number")
    state_dir = os.path.dirname(DEVICE_STATE_PATH)
    os.makedirs(state_dir, exist_ok=True)
    temp_path = DEVICE_STATE_PATH + ".tmp.%d" % os.getpid()
    with open(temp_path, "w", encoding="utf-8") as handle:
        json.dump({"version": 1, "client_no": value}, handle, sort_keys=True)
    os.replace(temp_path, DEVICE_STATE_PATH)
    return value, True


def collect_recent_history(jwt_value, hours, max_pages=100):
    end_ms = int(time.time() * 1000)
    start_ms = end_ms - int(hours * 60 * 60 * 1000)
    cursor = 0
    seen_cursors = set()
    selected = {}
    pages = 0
    while cursor not in seen_cursors and pages < max_pages:
        seen_cursors.add(cursor)
        messages = probe.history_page(jwt_value, 10075340, cursor, 15)
        pages += 1
        if not messages:
            break
        page_times = []
        page_ids = []
        for message in messages:
            send_time = int(probe.message_value(message, ("sendTime", "send_time"), 0))
            msg_id = int(probe.message_value(message, ("msgId", "msg_id"), 0))
            page_times.append(send_time)
            page_ids.append(msg_id)
            if start_ms <= send_time < end_ms:
                selected[msg_id] = message
        if page_times and min(page_times) < start_ms:
            break
        if not page_ids:
            break
        next_cursor = min(page_ids)
        if next_cursor == cursor:
            break
        cursor = next_cursor
    return start_ms, end_ms, pages, selected


def test_author_signatures(session):
    previous_logging_disable = logging.root.manager.disable
    client = None
    try:
        logging.disable(logging.CRITICAL)
        from components.wow_ui.nep_wrapper import NepWrapper
        from cli_anything.ccvoicehub.core.ui_api_client import UiApiClient

        login_controller = session["container"].get_instance("LoginController")
        nep = NepWrapper(None)
        client = UiApiClient(nep, login_cookie=getattr(login_controller, "_cookie", None))
        client._session.headers["User-Agent"] = probe.DD_USER_AGENT
        login_ok = client.login()
        probe.emit(
            "stable_author_login",
            ok=login_ok,
            nep_ready=nep.isDllInited(),
            server_time_ready=bool(client._server_ts),
            token_length=len(client._token) if login_ok else 0,
        )
        if not login_ok:
            return False

        body = json.dumps(
            {"probe": "stable-device-signature-only", "dry_run": True},
            separators=(",", ":"),
            sort_keys=True,
        )
        all_ready = True
        for path in (
            "/addon/create",
            "/addon/modify",
            "/share/create",
            "/share/modify",
            "/wa/create",
            "/wa/modify",
        ):
            code, signed_url = nep.getHttpPostSignedUrl(
                client.base_url + path, body, client._buildExtraArgs()
            )
            ready = bool(code == 1 and signed_url)
            all_ready = all_ready and ready
            probe.emit(
                "stable_author_signature",
                path=path,
                ready=ready,
                request_sent=False,
            )
            signed_url = None
        return all_ready
    finally:
        if client:
            client._token = ""
            client.close()
        logging.disable(previous_logging_disable)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--hold-seconds", type=int, default=30)
    parser.add_argument("--timeout", type=int, default=45)
    parser.add_argument("--history-hours", type=float, default=3.0)
    args = parser.parse_args()

    probe.bootstrap()
    import datacenter.local_data.machine_data as machine_data

    original_client_no = machine_data.clientNo
    isolated_client_no, state_created = load_or_create_client_no(machine_data)
    machine_data.clientNo = isolated_client_no
    session = None
    try:
        session = probe.open_native_session(args.timeout)
        user = session["container"].get_instance("DataCenter").getMyUserInfo()
        start_ms, end_ms, pages, messages = collect_recent_history(
            session["jwt"], args.history_hours
        )
        probe.emit(
            "stable_session",
            ready=True,
            client_no_length=len(isolated_client_no),
            eid=int(user.eid),
            jwt_ready=bool(session["jwt"]),
            state_created=state_created,
            state_path=DEVICE_STATE_PATH,
            history_from=probe.format_timestamp(start_ms),
            history_to=probe.format_timestamp(end_ms),
            history_pages=pages,
            history_count=len(messages),
            hold_seconds=args.hold_seconds,
        )

        author_ready = test_author_signatures(session)

        deadline = time.time() + args.hold_seconds
        while time.time() < deadline:
            session["qt"].process_events(100)
            time.sleep(0.05)
        probe.emit("stable_session_complete", ok=author_ready)
        return 0 if author_ready else 2
    finally:
        probe.close_native_session(session)
        machine_data.clientNo = original_client_no


if __name__ == "__main__":
    raise SystemExit(main())
