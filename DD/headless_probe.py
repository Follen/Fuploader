"""Read-only headless probe using NetEase DD's bundled Python runtime.

Run this file with the version-matched ``netease_dd.exe``. It intentionally
never prints credentials, login tokens, JWTs, cookies, or signed URLs.
"""

from __future__ import print_function

import argparse
import datetime
import json
import logging
import os
import sys
import time
import urllib.parse
import urllib.request


DD_DIR = os.environ.get("NETEASE_DD_DIR", r"D:\Software\NetEaseDD\100128")
DD_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; WOW64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/108.0.0.0 Safari/537.36 "
    "app/df_client dfVersion/100128"
)


def emit(event, **fields):
    payload = {"event": event}
    payload.update(fields)
    print("DDPROBE " + json.dumps(payload, ensure_ascii=False, sort_keys=True))
    sys.stdout.flush()


def bootstrap():
    resource = os.path.join(DD_DIR, "ccvoicehub.res")
    pyqt_dir = os.path.join(DD_DIR, "ccsub64", "PyQt5")
    support_dir = os.path.join(DD_DIR, "ccsub64")

    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    os.environ["PATH"] = os.pathsep.join(
        [pyqt_dir, DD_DIR, support_dir, os.environ.get("PATH", "")]
    )
    # Python 3.7 predates os.add_dll_directory. SetDllDirectory covers the
    # PyQt DLL dependency lookup used by the client modules.
    import ctypes

    ctypes.windll.kernel32.SetDllDirectoryW(pyqt_dir)
    if resource not in sys.path:
        sys.path.insert(0, resource)


def load_runtime():
    bootstrap()
    from cli_anything.ccvoicehub.core.container import ContainerManager
    from cli_anything.ccvoicehub.core.qt_runtime import QtRuntime

    qt = QtRuntime.get_instance()
    container = ContainerManager.get_container()
    return qt, container


def credential_metadata(container):
    storage = container.get_instance("AccountCredStorage")
    account = storage.getAutoAccount()
    credential = storage.getCred(account)
    return account, credential, {
        "account_present": bool(account),
        "account_name_length": len(account.name) if account else 0,
        "credential_present": bool(credential),
        "credential_length": len(credential.value) if credential else 0,
        "credential_type": credential.type.name if credential else "empty",
        "login_method": account.method.name if account else "empty",
        "modifier": credential.modifier.name if credential else "normal",
    }


def wait_until(qt, predicate, timeout):
    deadline = time.time() + timeout
    while time.time() < deadline:
        qt.process_events(100)
        if predicate():
            return True
        time.sleep(0.02)
    return bool(predicate())


def doctor(_args):
    qt, container = load_runtime()
    try:
        _account, _credential, metadata = credential_metadata(container)
        emit("doctor", **metadata)
        return 0 if metadata["credential_present"] else 2
    finally:
        container.shutdown()
        qt.shutdown()


class SessionError(RuntimeError):
    def __init__(self, exit_code, reason):
        RuntimeError.__init__(self, reason)
        self.exit_code = exit_code


def open_native_session(timeout):
    qt, container = load_runtime()
    credential = None
    flow = None
    try:
        account, credential, metadata = credential_metadata(container)
        emit("credential", **metadata)
        if not account or not credential:
            emit("login", ok=False, reason="missing_persisted_credential")
            raise SessionError(2, "missing_persisted_credential")

        from components.login.flow import MobileReLoginFlow
        import logger.cclogger as cclogger
        import components.login.login_controller as login_controller_module

        login_controller = container.get_instance("LoginController")
        jwt_helper = container.get_instance("JwtHelper")

        # The GUI initializes a FileHandler before login. A headless process
        # intentionally uses stdout only, so skip this non-authentication
        # housekeeping step while preserving the native login callback.
        _skip_log_rename = lambda *_args, **_kwargs: None
        cclogger.renameLogAfterLogin = _skip_log_rename
        login_controller_module.renameLogAfterLogin = _skip_log_rename

        state = {
            "login_done": False,
            "login_ok": False,
            "login_error": "",
            "jwt_updated": False,
        }

        def on_login_result(*signal_args):
            state["login_done"] = True
            state["login_ok"] = bool(signal_args and signal_args[0])
            if len(signal_args) > 1 and signal_args[1]:
                state["login_error"] = str(signal_args[1])[:160]

        def on_jwt_updated(*_signal_args):
            state["jwt_updated"] = True

        jwt_helper.sigJwtUpdated.connect(on_jwt_updated)

        flow = MobileReLoginFlow(
            login_controller,
            container.get_instance("UrsSDK"),
            container.get_instance("CgiHelper"),
            container.get_instance("NetConfig"),
            credential.value,
            credential.modifier.name == "mobile_password",
            account.name,
        )
        flow.sigResult.connect(on_login_result)
        flow.start()
        login_ready = wait_until(qt, lambda: state["login_done"], timeout)
        emit(
            "login",
            completed=login_ready,
            ok=state["login_ok"],
            reason=state["login_error"] if login_ready and not state["login_ok"] else "",
            timeout_seconds=timeout,
        )
        if not login_ready or not state["login_ok"]:
            raise SessionError(3, state["login_error"] or "login_failed_or_timed_out")

        # LoginController reaches LoggedIn before JwtHelper can request the
        # SID 44204/CID 8 login token. Requesting here is idempotent.
        jwt_helper.startRequestJwt()
        jwt_ready = wait_until(
            qt,
            lambda: state["jwt_updated"] and bool(jwt_helper.getJwt()),
            timeout,
        )
        jwt_value = jwt_helper.getJwt() if jwt_ready else ""
        login_token = jwt_helper.getLoginToken() if jwt_ready else ""
        emit(
            "jwt",
            ready=jwt_ready,
            jwt_length=len(jwt_value),
            login_token_length=len(login_token),
        )
        login_token = None
        if not jwt_ready:
            raise SessionError(4, "jwt_failed_or_timed_out")
        return {
            "qt": qt,
            "container": container,
            "flow": flow,
            "jwt_helper": jwt_helper,
            "jwt": jwt_value,
        }
    except Exception:
        container.shutdown()
        qt.shutdown()
        raise
    finally:
        credential = None


def close_native_session(session):
    if not session:
        return
    session["jwt"] = None
    session["jwt_helper"] = None
    session["flow"] = None
    session["container"].shutdown()
    session["qt"].shutdown()
    session.clear()


def login(args):
    session = None
    try:
        session = open_native_session(args.timeout)
        return 0
    except SessionError as exc:
        return exc.exit_code
    finally:
        close_native_session(session)


def http_json_get(url, jwt_value, timeout):
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json, text/plain, */*",
            "Authentication": jwt_value,
            "User-Agent": DD_USER_AGENT,
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def history_page(jwt_value, channel_id, cursor, timeout):
    query = urllib.parse.urlencode(
        {"channelId": channel_id, "msgId": cursor, "isAsc": 0}
    )
    url = "https://api.cc.163.com/v1/mixteamchat/chatMsg/list?" + query
    payload = http_json_get(url, jwt_value, timeout)
    if payload.get("code") not in (None, "OK", 0, 200):
        raise RuntimeError("history API returned code %s" % payload.get("code"))
    data = payload.get("data") or {}
    return data.get("msgList") or data.get("list") or []


def message_value(message, keys, default=""):
    for key in keys:
        value = message.get(key)
        if value not in (None, ""):
            return value
    return default


def message_sender(message):
    for key in ("sender", "user", "userInfo", "fromUser"):
        value = message.get(key)
        if isinstance(value, dict):
            name = message_value(value, ("nickname", "nickName", "name", "displayName"))
            if name:
                return str(name)
    return str(
        message_value(
            message,
            ("senderNickname", "nickname", "nickName", "senderName"),
        )
    )


def message_content(message):
    value = message_value(message, ("content", "text", "body", "msgContent"))
    if isinstance(value, dict):
        value = message_value(value, ("text", "content", "title"), value)
    if isinstance(value, (dict, list)):
        value = json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value)[:2000]


def format_timestamp(milliseconds):
    timestamp = datetime.datetime.fromtimestamp(
        float(milliseconds) / 1000.0, datetime.timezone.utc
    ).astimezone()
    return timestamp.isoformat(timespec="milliseconds")


def history(args):
    session = None
    try:
        session = open_native_session(args.timeout)
        end_ms = int(time.time() * 1000)
        start_ms = end_ms - int(args.hours * 60 * 60 * 1000)
        cursor = 0
        seen_cursors = set()
        selected = {}
        pages = 0

        while cursor not in seen_cursors and pages < args.max_pages:
            seen_cursors.add(cursor)
            messages = history_page(
                session["jwt"], args.channel_id, cursor, args.http_timeout
            )
            pages += 1
            if not messages:
                break

            page_times = []
            page_ids = []
            for message in messages:
                send_time = message_value(message, ("sendTime", "send_time"), 0)
                msg_id = message_value(message, ("msgId", "msg_id"), "")
                try:
                    send_time = int(send_time)
                    page_times.append(send_time)
                except (TypeError, ValueError):
                    continue
                try:
                    page_ids.append(int(msg_id))
                except (TypeError, ValueError):
                    pass
                if start_ms <= send_time < end_ms:
                    selected[str(msg_id)] = message

            if page_times and min(page_times) < start_ms:
                break
            if not page_ids:
                break
            next_cursor = min(page_ids)
            if next_cursor == cursor:
                break
            cursor = next_cursor
            time.sleep(0.08)

        ordered = sorted(
            selected.values(),
            key=lambda item: (
                int(message_value(item, ("sendTime", "send_time"), 0)),
                int(message_value(item, ("msgId", "msg_id"), 0)),
            ),
        )
        emit(
            "history_range",
            channel_id=args.channel_id,
            from_time=format_timestamp(start_ms),
            to_time=format_timestamp(end_ms),
            pages=pages,
            message_count=len(ordered),
            truncated=pages >= args.max_pages,
        )
        for message in ordered:
            send_time = int(message_value(message, ("sendTime", "send_time"), 0))
            emit(
                "message",
                msg_id=str(message_value(message, ("msgId", "msg_id"))),
                send_time=format_timestamp(send_time),
                sender=message_sender(message),
                message_type=str(
                    message_value(message, ("msgType", "type", "contentType"))
                ),
                status=str(message_value(message, ("msgStatus", "status"))),
                content=message_content(message),
            )
        return 0
    except SessionError as exc:
        return exc.exit_code
    finally:
        close_native_session(session)


def author(args):
    session = None
    client = None
    previous_logging_disable = logging.root.manager.disable
    try:
        session = open_native_session(args.timeout)
        login_controller = session["container"].get_instance("LoginController")
        login_cookie = getattr(login_controller, "_cookie", None)
        if not login_cookie or not isinstance(login_cookie, tuple):
            emit("author_login", ok=False, reason="missing_login_cookie")
            return 5

        # UiApiClient's informational logs include authentication metadata.
        # The probe emits its own strictly redacted status records instead.
        logging.disable(logging.CRITICAL)
        from components.wow_ui.nep_wrapper import NepWrapper
        from cli_anything.ccvoicehub.core.ui_api_client import UiApiClient

        nep = NepWrapper(None)
        if not nep.isDllInited():
            emit("author_login", ok=False, reason="nep_not_initialized")
            return 6

        client = UiApiClient(nep, login_cookie=login_cookie)
        client._session.headers["User-Agent"] = DD_USER_AGENT
        login_ok = client.login()
        emit(
            "author_login",
            ok=login_ok,
            token_length=len(client._token) if login_ok else 0,
            server_time_ready=bool(client._server_ts),
            nep_ready=True,
        )
        if not login_ok:
            return 7

        dry_run_body = json.dumps(
            {"probe": "signature-only", "dry_run": True},
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        for path in (
            "/addon/create",
            "/addon/modify",
            "/share/create",
            "/share/modify",
            "/wa/create",
            "/wa/modify",
        ):
            extra_args = client._buildExtraArgs()
            code, signed_url = nep.getHttpPostSignedUrl(
                client.base_url + path, dry_run_body, extra_args
            )
            emit(
                "author_post_signature",
                path=path,
                ready=bool(code == 1 and signed_url),
                signed_url_length=len(signed_url) if signed_url else 0,
                request_sent=False,
            )
            signed_url = None
        return 0
    finally:
        if client:
            client._token = ""
            client.close()
        logging.disable(previous_logging_disable)
        close_native_session(session)


def parse_args(argv):
    parser = argparse.ArgumentParser(description="Read-only NetEase DD headless probe")
    subparsers = parser.add_subparsers(dest="command")

    doctor_parser = subparsers.add_parser("doctor")
    doctor_parser.set_defaults(handler=doctor)

    login_parser = subparsers.add_parser("login")
    login_parser.add_argument("--timeout", type=int, default=30)
    login_parser.set_defaults(handler=login)

    history_parser = subparsers.add_parser("history")
    history_parser.add_argument("--channel-id", type=int, default=10075340)
    history_parser.add_argument("--hours", type=float, default=3.0)
    history_parser.add_argument("--max-pages", type=int, default=100)
    history_parser.add_argument("--timeout", type=int, default=30)
    history_parser.add_argument("--http-timeout", type=int, default=15)
    history_parser.set_defaults(handler=history)

    author_parser = subparsers.add_parser("author")
    author_parser.add_argument("--timeout", type=int, default=30)
    author_parser.set_defaults(handler=author)

    args = parser.parse_args(argv)
    if not getattr(args, "handler", None):
        parser.error("a command is required")
    return args


def main(argv=None):
    args = parse_args(sys.argv[1:] if argv is None else argv)
    try:
        return args.handler(args)
    except Exception as exc:
        emit("fatal", error_type=type(exc).__name__, message=str(exc)[:240])
        return 1


if __name__ == "__main__":
    sys.exit(main())
