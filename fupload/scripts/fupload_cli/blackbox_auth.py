"""Authentication helpers for the Heybox desktop Workshop client."""
from __future__ import annotations
import hashlib, json, platform, secrets, sqlite3, time
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from .errors import FuploadError

API_BASE = "https://workshopapi.xiaoheihe.cn"
CLIENT_VERSION = "1.14.1"
_CONFIG_AES_KEY = bytes.fromhex("5f1d7f11e6e90dbb5c2f0c1e614a6a8c4b9e16b50fa724e4c54d6f25b1208b93")
_ALPHABET = "AB45STUVWZEFGJ6CH01D237IXYPQRKLMN89"

def _n8(value: str, limit: int) -> str:
    table = _ALPHABET[:limit]
    return "".join(table[ord(ch) % len(table)] for ch in value)
def _i8(value: str) -> str:
    return "".join(_ALPHABET[ord(ch) % len(_ALPHABET)] for ch in value)
def _interleave(parts):
    return "".join(part[i] for i in range(max(map(len, parts))) for part in parts if i < len(part))
def _mix(values):
    def p(x): return ((x << 1) ^ 27) & 255 if x & 128 else (x << 1) & 255
    def hm(x): return p(x) ^ x
    def qg(x): return hm(p(x))
    def dx(x): return qg(hm(p(x)))
    def mw(x): return dx(x) ^ qg(x) ^ hm(x)
    a,b,c,d,*rest=values
    return [mw(a)^dx(b)^qg(c)^hm(d), hm(a)^mw(b)^dx(c)^qg(d), qg(a)^hm(b)^mw(c)^dx(d), dx(a)^qg(b)^hm(c)^mw(d), *rest]
def hkey(path: str, timestamp: int, nonce: str) -> str:
    normalized = "/" + "/".join(x for x in path.split("/") if x) + "/"
    digest = hashlib.md5(_interleave([_n8(str(timestamp), -2), _i8(normalized), _i8(nonce)]).encode()).hexdigest()
    return _n8(digest[:5], -4) + "%02d" % (sum(_mix([ord(x) for x in digest[-6:]])) % 100)

def _decrypt_user_pkey(value: str) -> str:
    """Decrypt the desktop config's ``iv:ciphertext`` AES-256-CBC value.

    Older Chromium cookie databases contain the already decrypted pkey, so this
    helper deliberately returns ordinary values unchanged and only attempts
    crypto for the new config format.
    """
    if not isinstance(value, str) or ":" not in value:
        return value
    iv_hex, ciphertext_hex = value.split(":", 1)
    try:
        iv = bytes.fromhex(iv_hex)
        ciphertext = bytes.fromhex(ciphertext_hex)
        if len(iv) != 16 or not ciphertext or len(ciphertext) % 16:
            return value
    except ValueError:
        return value
    try:
        from Crypto.Cipher import AES
        plaintext = AES.new(_CONFIG_AES_KEY, AES.MODE_CBC, iv).decrypt(ciphertext)
    except ImportError:
        try:
            from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
            decryptor = Cipher(algorithms.AES(_CONFIG_AES_KEY), modes.CBC(iv)).decryptor()
            plaintext = decryptor.update(ciphertext) + decryptor.finalize()
        except ImportError as exc:
            raise FuploadError(
                "AES support is required to read the Heybox desktop session",
                kind="environment_error",
                details={"install": "Crypto or cryptography"},
            ) from exc
    if not plaintext:
        return value
    pad = plaintext[-1]
    if not 1 <= pad <= 16 or plaintext[-pad:] != bytes([pad]) * pad:
        raise FuploadError("Heybox desktop pkey could not be decrypted", kind="authentication_error")
    try:
        return plaintext[:-pad].decode("utf-8")
    except UnicodeDecodeError as exc:
        raise FuploadError("Heybox desktop pkey is invalid", kind="authentication_error") from exc


def _read_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _load_cookie_db(profile: Path) -> dict[str, str]:
    db = profile / "Network/Cookies"
    try:
        with sqlite3.connect("file:%s?mode=ro" % db, uri=True) as con:
            rows = con.execute("select name,value from cookies where host_key like '%xiaoheihe.cn'").fetchall()
    except (OSError, sqlite3.Error):
        return {}
    return {str(k): str(v) for k, v in rows if k in {"user_heybox_id", "user_pkey", "x_xhh_tokenid"} and v}


def _read_sentry_identity(profile: Path) -> dict[str, str]:
    identity: dict[str, str] = {}
    scope = profile / "sentry/scope_v3.json"
    try:
        crumbs = _read_json(scope).get("scope", {}).get("breadcrumbs", [])
        for crumb in reversed(crumbs):
            raw = crumb.get("data",{}).get("url","")
            if "x_app=heybox_pc" in raw:
                query = parse_qs(urlparse(raw).query)
                allowed = {
                    "app", "client_type", "device_id", "exe_version", "heybox_id",
                    "os_type", "os_version", "version", "web_version", "x_app",
                    "x_client_type", "x_client_version", "x_os_type",
                }
                identity = {k: v[-1] for k, v in query.items() if k in allowed and v}
                break
    except (OSError, ValueError, TypeError):
        pass
    return identity


def load_session(profile: Path | None = None):
    """Load the current desktop session without exposing credential material.

    Heybox 1.14 stores its authoritative session in ``config.json``.  The
    Chromium database is retained as a compatibility fallback because older
    installations and upgrade paths may not have written the new config yet.
    """
    profile = profile or Path.home() / "AppData/Roaming/heybox-pc-launcher"
    config = _read_json(profile / "config.json")
    db_cookies = _load_cookie_db(profile)
    cookies: dict[str, str] = dict(db_cookies)
    config_cookies = config.get("cookies")
    if isinstance(config_cookies, list):
        for item in config_cookies:
            if not isinstance(item, dict):
                continue
            name, value = item.get("name"), item.get("value")
            if isinstance(name, str) and isinstance(value, str) and value:
                if name in {"user_heybox_id", "user_pkey", "x_xhh_tokenid"}:
                    cookies[name] = value
    acc_config = config.get("acc_config")
    if isinstance(acc_config, dict) and acc_config.get("xhh_token_id"):
        cookies["x_xhh_tokenid"] = str(acc_config["xhh_token_id"])
    if cookies.get("user_pkey"):
        cookies["user_pkey"] = _decrypt_user_pkey(cookies["user_pkey"])
    account = config.get("account") if isinstance(config.get("account"), dict) else {}
    if not cookies.get("user_heybox_id") and account.get("heybox_id"):
        cookies["user_heybox_id"] = str(account["heybox_id"])
    if not {"user_heybox_id", "user_pkey", "x_xhh_tokenid"} <= set(cookies):
        raise FuploadError("Heybox desktop login state is incomplete", kind="authentication_error")

    identity = _read_sentry_identity(profile)
    version = identity.get("version") or CLIENT_VERSION
    identity = {
        "x_client_type": "pc",
        "x_os_type": "Windows",
        "x_app": "heybox_pc",
        "version": version,
        "exe_version": identity.get("exe_version") or version,
        "os_version": identity.get("os_version") or platform.platform(aliased=True),
        **identity,
    }
    identity["version"] = version
    identity["exe_version"] = identity.get("exe_version") or version
    identity["heybox_id"] = cookies["user_heybox_id"]
    return cookies, identity
