"""Heybox Workshop plugin provider."""
from __future__ import annotations
import hashlib, json, secrets, time
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from typing import Any, Mapping
from .errors import FuploadError, ValidationError
from .blackbox_auth import API_BASE, hkey, load_session

class Blackbox:
    def __init__(self, config: Mapping[str, Any] | None = None, transport=None):
        self.config = dict(config or {})
        self.profile = Path(self.config.get("client_profile") or Path.home() / "AppData/Roaming/heybox-pc-launcher")
        self._transport = transport
    def _request(self, method, path, body=None, query=None):
        if self._transport: return self._transport(method, path, body or {}, query or {})
        cookies, identity = load_session(self.profile); ts=int(time.time()); nonce=hashlib.md5((str(ts)+secrets.token_hex(16)).encode()).hexdigest().upper()
        params={**identity,"version":identity.get("version","1.12.0"),"hkey":hkey(path,ts,nonce),"_time":ts,"_chat_time":int(time.time()*1000),"nonce":nonce,**(query or {})}
        headers={"User-Agent":"HeyboxApp/1.12.0","x_xhh_tokenid":cookies["x_xhh_tokenid"],"Cookie":"; ".join(f"{k}={v}" for k,v in cookies.items()),"Content-Type":"application/x-www-form-urlencoded"}
        url=API_BASE+path+"?"+urlencode(params); data=urlencode(body or {},doseq=True).encode() if method=="POST" else None
        try:
            with urlopen(Request(url,data=data,headers=headers,method=method),timeout=60) as r: result=json.loads(r.read().decode())
        except Exception as exc: raise FuploadError("Workshop API request failed", endpoint=path, verification_required=method=="POST") from exc
        if not isinstance(result,dict) or result.get("status")!="ok": raise FuploadError("Workshop API rejected request", endpoint=path, details={"status":result.get("status") if isinstance(result,dict) else None})
        return result
    @staticmethod
    def _result(payload): return payload.get("result") or {}
    def execute_read(self, resource: str, action: str, args: Any):
        if resource == "plugin" and action in ("list", "get", "versions"):
            if action == "list": return self.plugin_list()
            module_id = getattr(args,"module_id",None) if not isinstance(args,Mapping) else args.get("module_id")
            result = self.plugin_get(int(module_id))
            return result["versions"] if action == "versions" else result
        raise ValidationError("unsupported blackbox read operation")
    def execute_write(self, resource: str, action: str, doc: Mapping[str,Any]):
        if doc.get("dry_run"): return {"dry_run":True,"operation":f"{resource}.{action}","fields":sorted(k for k in doc if k not in {"dry_run","schema"})}
        if resource == "plugin" and action == "edit": return self.module_edit(doc)
        if resource == "plugin" and action == "update": return self.version_upsert(doc)
        if resource=="version" and action in ("create","update","edit"): return self.version_upsert(doc)
        if resource=="version" and action=="delete": return self.version_delete(doc)
        raise ValidationError("unsupported blackbox write operation")
    def plugin_list(self):
        rows=self._result(self._request("GET","/wow/open_platform/module/list/")).get("moduleList") or []
        return {"total_count":len(rows),"plugins":[self._redact(x) for x in rows if isinstance(x,dict)]}
    def plugin_get(self,module_id:int):
        detail=self._result(self._request("GET","/wow/open_platform/module/detail/",query={"moduleId":module_id}))
        versions=self._result(self._request("GET","/wow/open_platform/module_version/list/",query={"moduleId":module_id,"offset":0,"limit":100}))
        return {"module":self._redact(detail.get("module") or detail),"versions":[self._redact(x) for x in (versions.get("versionList") or [])]}
    def module_edit(self,doc):
        aliases={"module_id":"id","logo_url":"logoUrl","category_ids":"categoryIds","official_url":"officialUrl","core_folders":"coreFolders"}
        normalized={aliases.get(k,k):v for k,v in doc.items() if k not in {"schema","dry_run"}}
        if "id" not in normalized: raise ValidationError("id is required",path="$.id")
        module_id = int(normalized["id"])
        current = self.plugin_get(module_id)["module"]
        # The web client sends a complete module object; preserve omitted fields.
        defaults = {"name":"", "logoUrl":"", "id":module_id, "categoryIds":[],
                    "type":1, "desc":"", "official":"", "officialUrl":"", "coreFolders":""}
        fields={key: normalized.get(key, current.get(key, defaults[key]))
                for key in ("name","logoUrl","id","categoryIds","type","desc","official","officialUrl","coreFolders")}
        fields["id"] = module_id
        if isinstance(fields.get("coreFolders"),list): fields["coreFolders"]=",".join(map(str,fields["coreFolders"]))
        response=self._request("POST","/wow/open_platform/module/update/",body=fields)
        actual=self.plugin_get(module_id)["module"]
        mismatches=[]
        for key,wanted in ((aliases.get(key,key), value) for key,value in normalized.items() if key in aliases or key in fields):
            observed=actual.get(key)
            if key=="coreFolders" and isinstance(observed,list): wanted=[x for x in str(wanted).split(",") if x]
            if observed != wanted: mismatches.append(key)
        if mismatches: raise FuploadError("module update readback mismatch",kind="verification_required",verification_required=True,details={"fields":mismatches})
        return {"accepted":True,"verified":True,"module_id":module_id,"response":self._redact(response)}
    def version_upsert(self,doc):
        aliases={"module_id":"moduleId","version_id":"versionId","game_versions":"gameVersions","file_url":"fileUrl"}
        normalized={aliases.get(k,k):v for k,v in doc.items() if k not in {"schema","dry_run"}}
        if "file" in normalized and "fileUrl" not in normalized:
            normalized["fileUrl"]=self.upload_zip(int(normalized["moduleId"]),str(normalized["file"]))["url"]
        if "fileUrl" not in normalized and "versionId" in normalized:
            existing = self._find_version(int(normalized["moduleId"]), int(normalized["versionId"]))
            if existing and existing.get("fileUrlHeybox"):
                normalized["fileUrl"] = existing["fileUrlHeybox"]
        required=("moduleId","name","type","gameVersions","fileUrl")
        missing=[k for k in required if k not in normalized]
        if missing: raise ValidationError("missing field(s): %s"%", ".join(missing))
        games=normalized["gameVersions"] if isinstance(normalized["gameVersions"],list) else [x for x in str(normalized["gameVersions"]).split(",") if x]
        body={"moduleId":int(normalized["moduleId"]),"name":normalized["name"],"type":int(normalized["type"]),"gameVersions":",".join(map(str,games)),"fileUrl":normalized["fileUrl"]}
        if "versionId" in normalized: body["versionId"]=int(normalized["versionId"])
        response=self._request("POST","/wow/open_platform/module_version/upsert/",body=body)
        found=self._wait_version(body["moduleId"],body.get("versionId"),body["name"],
                                 expected={"name":body["name"],"type":body["type"],"gameVersions":list(map(str,games))})
        mismatches=[key for key,wanted in {"name":body["name"],"type":body["type"],"gameVersions":list(map(str,games))}.items() if found.get(key)!=wanted]
        if not found.get("fileUrlHeybox"):
            mismatches.append("fileUrl")
        if mismatches: raise FuploadError("version upsert readback mismatch",kind="verification_required",verification_required=True,details={"fields":mismatches})
        return {"accepted":True,"verified":True,"module_id":body["moduleId"],"version_id":found.get("id"),"readback":self._redact(found),"response":self._redact(response)}
    def version_delete(self,doc):
        version_id=doc.get("versionId",doc.get("version_id")); module_id=doc.get("moduleId",doc.get("module_id"))
        if version_id is None or module_id is None: raise ValidationError("versionId and moduleId are required")
        response=self._request("POST","/wow/open_platform/module_version/delete/",body={"versionId":int(version_id),"moduleId":int(module_id)})
        found=self._wait_version(int(module_id),int(version_id),None,deleted=True)
        retry = False
        settle = float(self.config.get("delete_settle_seconds", 10))
        if settle:
            time.sleep(settle)
            current = self._find_version(int(module_id), int(version_id))
            if current is not None and current.get("auditState") != 4:
                retry = True
                response = self._request("POST","/wow/open_platform/module_version/delete/",body={"versionId":int(version_id),"moduleId":int(module_id)})
                found = self._wait_version(int(module_id),int(version_id),None,deleted=True)
        return {"accepted":True,"verified":True,"module_id":int(module_id),"version_id":int(version_id),"audit_state":found.get("auditState") if found else None,"retry":retry,"response":self._redact(response)}
    def _version_rows(self,module_id):
        return self._result(self._request("GET","/wow/open_platform/module_version/list/",query={"moduleId":module_id,"offset":0,"limit":100})).get("versionList") or []

    def _find_version(self, module_id, version_id):
        return next((x for x in self._version_rows(module_id) if x.get("id") == version_id), None)
    def _wait_version(self,module_id,version_id,name,deleted=False,expected=None):
        for attempt in range(int(self.config.get("verify_attempts",20))):
            rows=self._version_rows(module_id)
            found=next((x for x in rows if (version_id is not None and x.get("id")==version_id) or (version_id is None and x.get("name")==name)),None)
            matches_expected = found and all(
                (list(map(str, found.get(key) or [])) if key == "gameVersions" else found.get(key)) == wanted
                for key, wanted in (expected or {}).items()
            )
            if (deleted and (found is None or found.get("auditState")==4)) or (not deleted and found and matches_expected): return found or {}
            if attempt+1<int(self.config.get("verify_attempts",20)): time.sleep(float(self.config.get("verify_interval",2)))
        raise FuploadError("version write was not confirmed by readback",kind="verification_required",verification_required=True)
    @staticmethod
    def _redact(value):
        if isinstance(value,dict): return {k:("<redacted>" if any(s in k.lower() for s in ("token","secret","cookie","nonce","hkey")) else Blackbox._redact(v)) for k,v in value.items()}
        if isinstance(value,list): return [Blackbox._redact(v) for v in value]
        return value

    def upload_zip(self, module_id: int, file_path: str, *, dry_run=False):
        path=Path(file_path)
        if not path.is_file(): raise ValidationError("file does not exist",path="$.file")
        if dry_run: return {"dry_run":True,"bytes":path.stat().st_size,"sha256":hashlib.sha256(path.read_bytes()).hexdigest()}
        size_mb=path.stat().st_size/1024/1024
        token=self._result(self._request("POST","/wow/cos/upload/token/",body={"jsonData":json.dumps({"upload_infos":[{"filename":path.name,"file_size":size_mb,"type":"module"}]},separators=(",",":"))}))
        info=token["info"]; f=token["files"][0]; creds=info["Credentials"].get("Credentials",info["Credentials"])
        try:
            from qcloud_cos import CosConfig, CosS3Client
        except ModuleNotFoundError as exc:
            raise FuploadError(
                "Heybox ZIP upload requires cos-python-sdk-v5",
                kind="environment_error",
                details={"install_command":"python -m pip install cos-python-sdk-v5"},
            ) from exc
        try:
            cos=CosS3Client(CosConfig(Region=info.get("region") or "ap-shanghai",SecretId=creds["TmpSecretID"],SecretKey=creds["TmpSecretKey"],Token=creds["Token"],Scheme="https"))
            with path.open("rb") as stream: cos.put_object(Bucket=info["bucket"],Key=f["key"],Body=stream)
        except Exception as exc: raise FuploadError("COS upload failed",verification_required=True) from exc
        return {"url":"https://%s/%s"%(info["host"],f["key"]),"bytes":path.stat().st_size,"sha256":hashlib.sha256(path.read_bytes()).hexdigest()}
