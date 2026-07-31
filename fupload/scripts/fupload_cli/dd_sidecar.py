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
_SENSITIVE_JSON_VALUE = re.compile(r'''(?i)((?:["']?(?:token|jwt|authorization|cookie)["']?)\s*:\s*["']?)[^"',}\s]+''')
_BEARER_VALUE = re.compile(r"(?i)Bearer\s+[A-Za-z0-9._~+/=-]+")
_HTTP_STATUS = re.compile(r"\bHTTP\s+(\d{3})\b", re.IGNORECASE)
_SENSITIVE_KEYS = {
    "token", "access_token", "refresh_token", "resource_token", "jwt", "jwttoken",
    "cookie", "set-cookie", "authorization", "authentication", "credential",
    "clientno", "client_no", "clientid", "client_id", "device_id", "device_proof", "signed_url", "upload_url",
    "presigneduri", "presigned_uri", "signature",
}
_MAX_LOG_BODY = 1024 * 1024


def safe_exception_message(exc):
    value = _SENSITIVE_ERROR_VALUE.sub(r"\1[REDACTED]", str(exc).strip())
    value = _SENSITIVE_JSON_VALUE.sub(r"\1[REDACTED]", value)
    return _BEARER_VALUE.sub("Bearer [REDACTED]", value)


def _sanitize_log_value(value, key=None, depth=0):
    if depth > 12:
        return "[MAX_DEPTH]"
    normalized_key = str(key or "").replace("-", "_").lower()
    if normalized_key in _SENSITIVE_KEYS or any(
        marker in normalized_key for marker in ("token", "cookie", "credential", "signature")
    ):
        return "[REDACTED]"
    if isinstance(value, dict):
        return {
            str(child_key): _sanitize_log_value(child_value, child_key, depth + 1)
            for child_key, child_value in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_sanitize_log_value(item, None, depth + 1) for item in value]
    if isinstance(value, str):
        return safe_exception_message(value)
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return safe_exception_message(str(value))


def _bounded_json_fields(prefix, value):
    sanitized = _sanitize_log_value(value)
    encoded = json.dumps(sanitized, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    size = len(encoded.encode("utf-8"))
    fields = {prefix + "_bytes": size, prefix + "_truncated": size > _MAX_LOG_BODY}
    if size <= _MAX_LOG_BODY:
        fields[prefix + "_json"] = sanitized
    else:
        fields[prefix + "_body"] = encoded[:_MAX_LOG_BODY]
    return fields


def _bounded_text(value):
    encoded = str(value).encode("utf-8")
    original_size = len(encoded)
    truncated = len(encoded) > _MAX_LOG_BODY
    if truncated:
        encoded = encoded[:_MAX_LOG_BODY]
    return encoded.decode("utf-8", "ignore"), original_size, truncated


def _response_log_content(probe, payload=None):
    if payload is not None:
        return _bounded_json_fields("response", payload)
    if not isinstance(probe, dict) or not probe.get("body"):
        return {}
    body = str(probe["body"])
    original_size = int(probe.get("body_bytes") or len(body.encode("utf-8")))
    originally_truncated = bool(probe.get("body_truncated"))
    if originally_truncated:
        sanitized, _stored_size, _ = _bounded_text(safe_exception_message(body))
        return {
            "response_body": sanitized,
            "response_bytes": original_size,
            "response_truncated": True,
        }
    try:
        parsed = json.loads(body)
    except (TypeError, ValueError):
        sanitized, size, truncated = _bounded_text(safe_exception_message(body))
        return {
            "response_body": sanitized,
            "response_bytes": size,
            "response_truncated": truncated,
        }
    return _bounded_json_fields("response", parsed)


def write_error_log(failure, command, probe=None, payload=None):
    log_dir = os.path.join(DD_DIR, "Fupload", "logs")
    os.makedirs(log_dir, exist_ok=True)
    path = os.path.join(log_dir, "dd-errors-%s.jsonl" % time.strftime("%Y%m%d"))
    request = command.get("payload") if isinstance(command, dict) else None
    if request is None and isinstance(command, dict) and command.get("action") == "upload":
        request = command.get("meta")
    record = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "action": command.get("action") if isinstance(command, dict) else None,
        "method": command.get("method") if isinstance(command, dict) else None,
        "endpoint": command.get("path") if isinstance(command, dict) else None,
        "stage": failure.stage,
        "message": safe_exception_message(failure),
        "http_status": failure.http_status,
        "business_code": failure.business_code,
        "verification_required": bool(failure.verification_required),
        "request_fields": sorted(str(key) for key in request) if isinstance(request, dict) else [],
        "validation": _sanitize_log_value(failure.details),
    }
    if request is not None:
        record.update(_bounded_json_fields("request", request))
    record.update(_response_log_content(probe, payload))
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=True, sort_keys=True, separators=(",", ":")) + "\n")
    return os.path.abspath(path)


def output(payload):
    print("FUPLOAD_RESULT " + json.dumps(payload, ensure_ascii=True, sort_keys=True))
    sys.stdout.flush()


class SidecarFailure(Exception):
    def __init__(self, message, stage, http_status=None, business_code=None, verification_required=False, details=None):
        Exception.__init__(self, message)
        self.stage = stage
        self.http_status = http_status
        self.business_code = business_code
        self.verification_required = verification_required
        self.details = details or {}

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
        if self.details:
            result["details"] = self.details
        return result


def _validation_details(probe):
    if not isinstance(probe, dict):
        return {}
    body = probe.get("body")
    if not body:
        return {}
    try:
        parsed = json.loads(body)
    except (TypeError, ValueError):
        return {"server_message": safe_exception_message(str(body))[:400]}
    if not isinstance(parsed, dict):
        return {"server_response": safe_exception_message(str(parsed))[:400]}
    result = {}
    for key in ("code", "msg", "message", "error", "field", "fields", "type"):
        if key in parsed and parsed[key] not in (None, ""):
            result["server_" + key] = safe_exception_message(str(parsed[key]))[:400]
    detail = parsed.get("detail")
    if isinstance(detail, list):
        items = []
        for item in detail[:20]:
            if not isinstance(item, dict):
                continue
            entry = {}
            for key in ("loc", "msg", "type"):
                if key in item:
                    entry[key] = safe_exception_message(str(item[key]))[:200]
            if entry:
                items.append(entry)
        if items:
            result["server_detail"] = items
    elif detail not in (None, ""):
        result["server_detail"] = safe_exception_message(str(detail))[:400]
    return result


def install_response_probe(client):
    """Capture response objects and HTTPError bodies without changing DD behavior."""
    session = getattr(client, "_session", None)
    restore = getattr(client, "_fupload_restore_response_probe", None)
    if callable(restore):
        restore()
    original_opener_open = urllib.request.OpenerDirector.open

    def opener_open(opener, *args, **kwargs):
        try:
            return original_opener_open(opener, *args, **kwargs)
        except urllib.error.HTTPError as error:
            original_read = error.read

            def error_read(*read_args, _error=error, **read_kwargs):
                body = original_read(*read_args, **read_kwargs)
                try:
                    text = bytes(body or b"").decode("utf-8", "replace")
                except Exception:
                    text = ""
                bounded, size, truncated = _bounded_text(text)
                client._fupload_last_response_error = {
                    "status": int(getattr(_error, "code", 0) or 0),
                    "body": bounded,
                    "body_bytes": size,
                    "body_truncated": truncated,
                }
                return body

            error.read = error_read
            raise

    urllib.request.OpenerDirector.open = opener_open

    def restore_probe():
        if getattr(urllib.request.OpenerDirector, "open", None) is opener_open:
            urllib.request.OpenerDirector.open = original_opener_open
        client._fupload_restore_response_probe = None

    client._fupload_restore_response_probe = restore_probe
    for method_name in ("get", "post"):
        original = getattr(session, method_name, None)
        if not callable(original):
            continue

        def wrapped_factory(original_method):
            def wrapped(*args, **kwargs):
                client._fupload_last_response_error = None
                response = original_method(*args, **kwargs)
                try:
                    status = int(getattr(response, "status_code", 0) or 0)
                except (TypeError, ValueError):
                    status = 0
                if status >= 400:
                    try:
                        body = str(getattr(response, "text", "") or "")
                    except Exception:
                        body = ""
                    bounded, size, truncated = _bounded_text(body)
                    client._fupload_last_response_error = {
                        "status": status,
                        "body": bounded,
                        "body_bytes": size,
                        "body_truncated": truncated,
                    }
                return response
            return wrapped

        try:
            setattr(session, method_name, wrapped_factory(original))
        except (AttributeError, TypeError):
            continue


def failure_from_exception(exc, stage, response=None):
    if isinstance(exc, SidecarFailure):
        return exc
    if isinstance(exc, urllib.error.HTTPError):
        probe = dict(response) if isinstance(response, dict) else {}
        if not probe.get("body"):
            try:
                body = exc.read()
            except Exception:
                body = b""
            if body:
                text = bytes(body).decode("utf-8", "replace")
                bounded, size, truncated = _bounded_text(text)
                probe.update({
                    "status": int(exc.code),
                    "body": bounded,
                    "body_bytes": size,
                    "body_truncated": truncated,
                })
        business_code = None
        if probe.get("body"):
            try:
                body_value = json.loads(probe["body"])
                if isinstance(body_value, dict):
                    business_code = body_value.get("code") or body_value.get("error_code")
            except (TypeError, ValueError):
                pass
        return SidecarFailure(
            "DD %s request returned HTTP %d" % (stage, exc.code), stage,
            http_status=exc.code,
            business_code=business_code,
            verification_required=stage in ("object_put", "mutation") and exc.code >= 500,
            details=_validation_details(probe),
        )
    uncertain = stage in ("object_put", "mutation")
    message = safe_exception_message(exc)
    probe = response if isinstance(response, dict) else {}
    status = probe.get("status")
    match = _HTTP_STATUS.search(message)
    if status is None and match:
        status = int(match.group(1))
    try:
        status = int(status) if status is not None else None
    except (TypeError, ValueError):
        status = None
    business_code = getattr(exc, "code", None) or getattr(exc, "error_code", None)
    if business_code is None and isinstance(probe, dict) and probe.get("body"):
        try:
            body_value = json.loads(probe["body"])
            if isinstance(body_value, dict):
                business_code = body_value.get("code") or body_value.get("error_code")
        except (TypeError, ValueError):
            pass
    if not message:
        message = type(exc).__name__
    return SidecarFailure(
        "DD %s request failed (%s): %s" % (stage, type(exc).__name__, message[:400]),
        stage,
        http_status=status,
        business_code=business_code,
        verification_required=uncertain and not (status is not None and 400 <= status < 500),
        details=_validation_details(probe),
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
    install_response_probe(client)
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
    client._fupload_last_response_error = None
    action = command.get("action")
    rejected_payload = None
    try:
        if action == "request":
            method = command.get("method", "GET").upper()
            path = command["path"]
            params = command.get("payload") or {}
            response_payload = client.get(path, params) if method == "GET" else client.post(path, params)
            if isinstance(response_payload, dict) and response_payload.get("code") not in (None, 0):
                rejected_payload = response_payload
                raise SidecarFailure(
                    str(response_payload.get("msg") or response_payload.get("message") or "DD operation failed"),
                    command.get("request_stage") or ("dependency_get" if method == "GET" else "mutation"),
                    business_code=response_payload.get("code"),
                    details=_validation_details({"body": json.dumps(response_payload, ensure_ascii=False)}),
                )
            return response_payload
        if action == "upload":
            path = command["file"]
            meta = command["meta"]
            try:
                auth = client.get("/file/upload", meta)
            except Exception as exc:
                raise failure_from_exception(exc, "upload_authorize", getattr(client, "_fupload_last_response_error", None))
            if isinstance(auth, dict) and auth.get("code") not in (None, 0):
                rejected_payload = auth
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
        failure = failure_from_exception(exc, stage, getattr(client, "_fupload_last_response_error", None))
        try:
            log_path = write_error_log(
                failure, command,
                getattr(client, "_fupload_last_response_error", None),
                rejected_payload,
            )
            failure.details["log_path"] = log_path
        except Exception as log_exc:
            failure.details["log_write_error"] = type(log_exc).__name__
        raise failure


def close_session(session):
    if not session:
        return
    qt, container, _flow, _jwt_helper, client = session
    restore_probe = getattr(client, "_fupload_restore_response_probe", None)
    if callable(restore_probe):
        restore_probe()
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
