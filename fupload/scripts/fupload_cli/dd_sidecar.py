"""DD-native JSONL sidecar. Run only with the version-matched netease_dd.exe."""

from __future__ import print_function

import ctypes
import json
import logging
import os
import re
import sys
import time
import urllib.error
import urllib.request


DD_DIR = os.environ["NETEASE_DD_DIR"]
DEVICE_STATE = os.environ["FUPLOAD_DD_DEVICE_STATE"]
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; WOW64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/108.0.0.0 Safari/537.36 app/df_client dfVersion/%s"
    % os.path.basename(DD_DIR.rstrip("\\/"))
)
_SENSITIVE_ERROR_VALUE = re.compile(r"(?i)((?:x-amz-(?:credential|signature|security-token)|token|jwt|authorization|cookie)=)[^&\s]+")


def safe_exception_message(exc):
    return _SENSITIVE_ERROR_VALUE.sub(r"\1[REDACTED]", str(exc).strip())


def output(payload):
    print("FUPLOAD_RESULT " + json.dumps(payload, ensure_ascii=True, sort_keys=True))
    sys.stdout.flush()


class SidecarFailure(Exception):
    def __init__(self, message, stage, http_status=None, business_code=None, verification_required=False):
        Exception.__init__(self, message)
        self.stage = stage
        self.http_status = http_status
        self.business_code = business_code
        self.verification_required = verification_required

    def as_dict(self):
        result = {
            "kind": "platform_error",
            "stage": self.stage,
            "message": self.args[0],
            "verification_required": bool(self.verification_required),
        }
        if self.http_status is not None:
            result["http_status"] = self.http_status
        if self.business_code is not None:
            result["business_code"] = self.business_code
        return result


def failure_from_exception(exc, stage):
    if isinstance(exc, SidecarFailure):
        return exc
    if isinstance(exc, urllib.error.HTTPError):
        return SidecarFailure("DD %s request returned HTTP %d" % (stage, exc.code), stage, http_status=exc.code)
    uncertain = stage in ("object_put", "mutation")
    message = safe_exception_message(exc)
    business_code = getattr(exc, "code", None) or getattr(exc, "error_code", None)
    if not message:
        message = type(exc).__name__
    return SidecarFailure(
        "DD %s request failed (%s): %s" % (stage, type(exc).__name__, message[:400]),
        stage,
        business_code=business_code,
        verification_required=uncertain,
    )


def bootstrap():
    resource = os.path.join(DD_DIR, "ccvoicehub.res")
    pyqt_dir = os.path.join(DD_DIR, "ccsub64", "PyQt5")
    support_dir = os.path.join(DD_DIR, "ccsub64")
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    os.environ["PATH"] = os.pathsep.join([pyqt_dir, DD_DIR, support_dir, os.environ.get("PATH", "")])
    ctypes.windll.kernel32.SetDllDirectoryW(pyqt_dir)
    sys.path.insert(0, resource)


def load_client_no(machine_data):
    if os.path.exists(DEVICE_STATE):
        try:
            with open(DEVICE_STATE, "r", encoding="utf-8") as handle:
                state = json.load(handle)
            value = state.get("client_no", "")
        except Exception as exc:
            raise RuntimeError("sidecar-device.json is unreadable") from exc
        if not re.match(r"^[0-9a-f]{32}$", value):
            raise RuntimeError("sidecar-device.json contains an invalid client_no")
        return value, False
    value = machine_data.generateClientNo()
    if not re.match(r"^[0-9a-f]{32}$", value):
        raise RuntimeError("DD generated an invalid client_no")
    directory = os.path.dirname(DEVICE_STATE)
    if not os.path.isdir(directory):
        os.makedirs(directory)
    temporary = DEVICE_STATE + ".tmp.%d" % os.getpid()
    with open(temporary, "w", encoding="utf-8") as handle:
        json.dump({"version": 1, "client_no": value}, handle, sort_keys=True)
    os.replace(temporary, DEVICE_STATE)
    return value, True


def wait_until(qt, predicate, timeout):
    deadline = time.time() + timeout
    while time.time() < deadline:
        qt.process_events(100)
        if predicate():
            return True
        time.sleep(0.02)
    return bool(predicate())


def open_session(timeout=45):
    from cli_anything.ccvoicehub.core.container import ContainerManager
    from cli_anything.ccvoicehub.core.qt_runtime import QtRuntime
    from components.login.flow import MobileReLoginFlow
    import components.login.login_controller as login_controller_module
    import logger.cclogger as cclogger

    qt = QtRuntime.get_instance()
    container = ContainerManager.get_container()
    storage = container.get_instance("AccountCredStorage")
    account = storage.getAutoAccount()
    credential = storage.getCred(account)
    if not account or not credential:
        raise RuntimeError("DD has no persisted credential; sign in with the desktop client first")
    cclogger.renameLogAfterLogin = lambda *_args, **_kwargs: None
    login_controller_module.renameLogAfterLogin = lambda *_args, **_kwargs: None
    controller = container.get_instance("LoginController")
    jwt_helper = container.get_instance("JwtHelper")
    state = {"done": False, "ok": False, "jwt": False, "error": ""}

    def login_result(*args):
        state["done"] = True
        state["ok"] = bool(args and args[0])
        if len(args) > 1 and args[1]:
            state["error"] = str(args[1])[:160]

    def jwt_result(*_args):
        state["jwt"] = True

    jwt_helper.sigJwtUpdated.connect(jwt_result)
    flow = MobileReLoginFlow(
        controller, container.get_instance("UrsSDK"), container.get_instance("CgiHelper"),
        container.get_instance("NetConfig"), credential.value,
        credential.modifier.name == "mobile_password", account.name,
    )
    flow.sigResult.connect(login_result)
    flow.start()
    if not wait_until(qt, lambda: state["done"], timeout) or not state["ok"]:
        raise RuntimeError(state["error"] or "DD native login failed or timed out")
    jwt_helper.startRequestJwt()
    if not wait_until(qt, lambda: state["jwt"] and bool(jwt_helper.getJwt()), timeout):
        raise RuntimeError("DD JWT refresh failed or timed out")
    from components.wow_ui.nep_wrapper import NepWrapper
    from cli_anything.ccvoicehub.core.ui_api_client import UiApiClient
    nep = NepWrapper(None)
    if not nep.isDllInited():
        raise RuntimeError("DD NEP module is not initialized")
    client = UiApiClient(nep, login_cookie=getattr(controller, "_cookie", None))
    client._session.headers["User-Agent"] = USER_AGENT
    if not client.login():
        raise RuntimeError("DD author API login failed")
    return qt, container, flow, jwt_helper, client


def api_result(payload):
    return payload.get("result") if isinstance(payload, dict) else None


def parse_native_wa(session, content):
    """Use a parser exposed by the installed DD runtime; never synthesize IDs."""
    container = session[1]
    service_names = (
        "WaParser", "WAParser", "WeakAurasParser", "WastParser",
        "WaParseService", "WAParseService", "UiWaParser",
    )
    method_names = ("parse", "parseWa", "parse_wa", "parseString", "parse_string")
    for service_name in service_names:
        try:
            service = container.get_instance(service_name)
        except Exception:
            continue
        for method_name in method_names:
            method = getattr(service, method_name, None)
            if not callable(method):
                continue
            parsed = method(content)
            if isinstance(parsed, dict):
                uid = parsed.get("parse_wa_uid") or parsed.get("uid") or parsed.get("wa_uid")
                ident = parsed.get("parse_wa_id") or parsed.get("id") or parsed.get("wa_id")
            elif isinstance(parsed, (list, tuple)) and len(parsed) >= 2:
                uid, ident = parsed[0], parsed[1]
            else:
                continue
            if uid and ident:
                return {"parse_wa_uid": str(uid), "parse_wa_id": str(ident)}
    raise RuntimeError("installed DD runtime does not expose a native WA parser")


def run_command(session, command):
    client = session[-1]
    action = command.get("action")
    try:
        if action == "request":
            method = command.get("method", "GET").upper()
            path = command["path"]
            params = command.get("payload") or {}
            return client.get(path, params) if method == "GET" else client.post(path, params)
        if action == "upload":
            path = command["file"]
            meta = command["meta"]
            try:
                auth = client.get("/file/upload", meta)
            except Exception as exc:
                raise failure_from_exception(exc, "upload_authorize")
            if isinstance(auth, dict) and auth.get("code") not in (None, 0):
                raise SidecarFailure(
                    "DD upload authorization was rejected",
                    "upload_authorize",
                    business_code=auth.get("code"),
                )
            info = api_result(auth)
            if not isinstance(info, dict) or not info.get("url") or not info.get("d_url"):
                raise SidecarFailure("DD upload authorization did not return a usable upload target", "upload_authorize")
            size = os.path.getsize(path)
            maximum = int(info.get("maxSize") or 0)
            if maximum and size > maximum:
                raise SidecarFailure("file exceeds DD server size limit", "upload_authorize")
            try:
                with open(path, "rb") as handle:
                    request = urllib.request.Request(
                        info["url"], data=handle.read(), method="PUT",
                        headers={"Content-Type": meta["mime_type"], "X-Amz-Acl": "public-read"},
                    )
                with urllib.request.urlopen(request, timeout=180) as response:
                    if response.status != 200:
                        raise SidecarFailure("DD object upload returned HTTP %d" % response.status, "object_put", http_status=response.status)
            except Exception as exc:
                raise failure_from_exception(exc, "object_put")
            return {"d_url": info["d_url"], "size": size}
        if action == "cc_get":
            jwt_value = session[3].getJwt()
            url = command["url"]
            request = urllib.request.Request(
                url,
                headers={
                    "Authentication": jwt_value,
                    "Authorization": jwt_value,
                    "User-Agent": USER_AGENT,
                },
            )
            with urllib.request.urlopen(request, timeout=30) as response:
                return json.loads(response.read().decode("utf-8"))
        if action == "parse_wa":
            return parse_native_wa(session, command["content"])
        raise SidecarFailure("unsupported sidecar action", "session")
    except Exception as exc:
        if action == "request":
            stage = command.get("request_stage")
            if stage not in ("dependency_get", "mutation"):
                stage = "dependency_get" if command.get("method", "GET").upper() == "GET" else "mutation"
        elif action == "cc_get":
            stage = "dependency_get"
        elif action == "parse_wa":
            stage = "native_parser"
        else:
            stage = "session"
        raise failure_from_exception(exc, stage)


def close_session(session):
    if not session:
        return
    qt, container, _flow, _jwt_helper, client = session
    try:
        message_center = container.get_instance("MessageCenter")
        message_center.logout()
        try:
            from components.net_server.messagecenter import State

            def stopped():
                state = message_center.state
                checker = getattr(state, "isStopped", None)
                if callable(checker):
                    return bool(checker())
                checker = getattr(State, "isStopped", None)
                return bool(checker(state)) if callable(checker) else False

            wait_until(qt, stopped, 5)
        except Exception:
            pass
    except Exception:
        pass
    try:
        client._token = ""
        client.close()
    except Exception:
        pass
    try:
        container.shutdown()
    finally:
        qt.shutdown()


def main():
    logging.disable(logging.CRITICAL)
    bootstrap()
    import datacenter.local_data.machine_data as machine_data
    original = machine_data.clientNo
    value, created = load_client_no(machine_data)
    machine_data.clientNo = value
    session = None
    try:
        session = open_session()
        output({"ready": True, "device_state_created": created})
        for line in sys.stdin:
            if not line.strip():
                continue
            command = None
            try:
                command = json.loads(line)
                result = run_command(session, command)
                output({"id": command.get("id"), "ok": True, "data": result})
            except Exception as exc:
                error = exc.as_dict() if isinstance(exc, SidecarFailure) else failure_from_exception(exc, "session").as_dict()
                output({"id": command.get("id") if isinstance(command, dict) else None, "ok": False,
                        "error": error})
        return 0
    except Exception as exc:
        output({"ready": False, "error": {"type": type(exc).__name__, "message": str(exc)[:400]}})
        return 1
    finally:
        machine_data.clientNo = original
        close_session(session)


if __name__ == "__main__":
    sys.exit(main())
