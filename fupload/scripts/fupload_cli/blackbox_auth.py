"""Authentication helpers for the Heybox desktop Workshop client."""
from __future__ import annotations
import hashlib, json, secrets, sqlite3, time
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from .errors import FuploadError

API_BASE = "https://workshopapi.xiaoheihe.cn"
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

def load_session(profile: Path | None = None):
    profile = profile or Path.home() / "AppData/Roaming/heybox-pc-launcher"
    db = profile / "Network/Cookies"
    try:
        with sqlite3.connect("file:%s?mode=ro" % db, uri=True) as con:
            rows = con.execute("select name,value from cookies where host_key like '%xiaoheihe.cn'").fetchall()
    except (OSError, sqlite3.Error) as exc:
        raise FuploadError("Heybox desktop Cookie DB is missing", kind="authentication_error") from exc
    cookies = {str(k): str(v) for k,v in rows if k in {"user_heybox_id","user_pkey","x_xhh_tokenid"} and v}
    if not {"user_heybox_id","user_pkey","x_xhh_tokenid"} <= set(cookies):
        raise FuploadError("Heybox desktop login state is incomplete", kind="authentication_error")
    identity = {}
    scope = profile / "sentry/scope_v3.json"
    try:
        crumbs = json.loads(scope.read_text(encoding="utf-8")).get("scope",{}).get("breadcrumbs",[])
        for crumb in reversed(crumbs):
            raw = crumb.get("data",{}).get("url","")
            if "x_app=heybox_pc" in raw:
                query = parse_qs(urlparse(raw).query)
                allowed = {"x_client_type","x_os_type","x_app","version","exe_version","os_version","device_id","channel","heybox_id"}
                identity = {k:v[-1] for k,v in query.items() if k in allowed and v}; break
    except (OSError, ValueError, TypeError):
        pass
    return cookies, identity
