"""Heybox Workshop plugin provider."""
from __future__ import annotations
import hashlib, json, time, zipfile
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from typing import Any, Mapping
from .errors import FuploadError, ValidationError
from .blackbox_web import API_ORIGIN, BlackboxWebSession

API_MISC_BASE = "https://api.xiaoheihe.cn"
API_BASE = API_ORIGIN

class Blackbox:
    def __init__(self, config: Mapping[str, Any] | None = None, transport=None, *, web_session=None, web_session_factory=None):
        self.config = dict(config or {})
        self._transport = transport
        self._web_session = web_session
        self._web_session_factory = web_session_factory or BlackboxWebSession

    def close(self):
        if self._web_session is not None:
            self._web_session.close()
            self._web_session = None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def _request(self, method, path, body=None, query=None, *, base=API_BASE):
        if self._transport:
            if base != API_BASE:
                raise ValidationError("API origin is fixed to Workshop web protocol", path="$.base")
            return self._transport(method, path, body or {}, query or {})
        if base != API_BASE:
            raise ValidationError("API origin is fixed to Workshop web protocol", path="$.base")
        if self._web_session is None:
            self._web_session = self._web_session_factory()
        return self._web_session.request(method, path, body=body, query=query)
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
        detail=self._module_detail(module_id)
        return {"module":self._redact(detail),"versions":[self._redact(x) for x in self._version_rows(module_id)]}
    def _module_detail(self,module_id:int):
        detail=self._result(self._request("GET","/wow/open_platform/module/detail/",query={"moduleId":module_id}))
        module=detail.get("module") or detail
        return module if isinstance(module,dict) else {}
    def module_edit(self,doc):
        aliases={"module_id":"id","logo_url":"logoUrl","category_ids":"categoryIds","official_url":"officialUrl","core_folders":"coreFolders"}
        normalized={aliases.get(k,k):v for k,v in doc.items() if k not in {"schema","dry_run"}}
        if "id" not in normalized: raise ValidationError("id is required",path="$.id")
        module_id = int(normalized["id"])
        current = self._module_detail(module_id)
        # The web client sends a complete module object; preserve omitted fields.
        defaults = {"name":"", "logoUrl":"", "id":module_id, "categoryIds":[],
                    "type":1, "desc":"", "official":"", "officialUrl":"", "coreFolders":""}
        fields={key: normalized.get(key, current.get(key, defaults[key]))
                for key in ("name","logoUrl","id","categoryIds","type","desc","official","officialUrl","coreFolders")}
        fields["id"] = module_id
        if isinstance(fields.get("coreFolders"),list): fields["coreFolders"]=",".join(map(str,fields["coreFolders"]))
        response=self._request("POST","/wow/open_platform/module/update/",body=fields)
        expected={aliases.get(key,key):value for key,value in normalized.items() if key in aliases or key in fields}
        self._wait_module(module_id,expected)
        return {"accepted":True,"verified":True,"module_id":module_id,"response":self._redact(response)}
    def version_upsert(self,doc):
        aliases={"module_id":"moduleId","version_id":"versionId","game_versions":"gameVersions","file_url":"fileUrl"}
        normalized={aliases.get(k,k):v for k,v in doc.items() if k not in {"schema","dry_run"}}
        upload_result = None
        if "file" in normalized:
            upload_result=self.upload_zip(int(normalized["moduleId"]),str(normalized["file"]))
            normalized["fileUrl"]=upload_result["url"]
        if "fileUrl" not in normalized and "versionId" in normalized:
            existing = self._find_version(int(normalized["moduleId"]), int(normalized["versionId"]))
            current_url=self._archive_url(existing or {})
            if current_url: normalized["fileUrl"]=current_url
        required=("moduleId","name","type","gameVersions","fileUrl")
        missing=[k for k in required if k not in normalized]
        if missing: raise ValidationError("missing field(s): %s"%", ".join(missing))
        games=normalized["gameVersions"] if isinstance(normalized["gameVersions"],list) else [x for x in str(normalized["gameVersions"]).split(",") if x]
        body={"moduleId":int(normalized["moduleId"]),"name":normalized["name"],"type":int(normalized["type"]),"gameVersions":",".join(map(str,games)),"fileUrl":normalized["fileUrl"]}
        if "versionId" in normalized: body["versionId"]=int(normalized["versionId"])
        existing_ids={self._id_value(row.get("id")) for row in self._version_rows(body["moduleId"])} if "versionId" not in body else set()
        response=self._request("POST","/wow/open_platform/module_version/upsert/",body=body)
        response_result=self._result(response)
        response_id=(response_result.get("versionId") or response_result.get("id")) if isinstance(response_result,dict) else None
        target_id=body.get("versionId") or (self._id_value(response_id) if response_id is not None else None)
        expected = {"name":body["name"],"type":body["type"],"gameVersions":list(map(str,games))}
        found=self._wait_version(body["moduleId"],target_id,body["name"],excluded_ids=existing_ids,
                                 expected=expected,expected_archive=body["fileUrl"])
        mismatches=[key for key,wanted in {"name":body["name"],"type":body["type"],"gameVersions":list(map(str,games))}.items() if self._comparable(key,found.get(key))!=self._comparable(key,wanted)]
        if self._comparable("fileUrl", self._archive_url(found)) != self._comparable("fileUrl", body["fileUrl"]):
            mismatches.append("fileUrl")
        if mismatches: raise FuploadError("version upsert readback mismatch",kind="verification_required",verification_required=True,details={"fields":mismatches})
        result={"accepted":True,"verified":True,"module_id":body["moduleId"],"version_id":found.get("id"),"readback":self._redact(found),"response":self._redact(response)}
        if upload_result:
            result["upload"]={key:upload_result[key] for key in ("protocol","bytes","sha256") if key in upload_result}
        return result
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
                time.sleep(settle)
                current = self._find_version(int(module_id), int(version_id))
                if current is not None and current.get("auditState") != 4:
                    raise FuploadError("version delete did not remain stable",kind="verification_required",verification_required=True)
        return {"accepted":True,"verified":True,"module_id":int(module_id),"version_id":int(version_id),"audit_state":found.get("auditState") if found else None,"retry":retry,"response":self._redact(response)}
    def _version_rows(self,module_id):
        limit = int(self.config.get("version_page_size", 100))
        max_pages = int(self.config.get("version_max_pages", 100))
        rows = []
        page_fingerprints = set()
        for page_index in range(max_pages):
            offset = page_index * limit
            result = self._result(self._request(
                "GET", "/wow/open_platform/module_version/list/",
                query={"moduleId":module_id,"offset":offset,"limit":limit},
            ))
            page = result.get("versionList") or []
            if not isinstance(page, list):
                raise FuploadError("version list response is invalid", kind="verification_required", verification_required=True)
            fingerprint = tuple(self._id_value(item.get("id")) for item in page if isinstance(item, Mapping))
            if page and fingerprint in page_fingerprints:
                raise FuploadError("version list pagination did not advance", kind="verification_required", verification_required=True)
            page_fingerprints.add(fingerprint)
            rows.extend(item for item in page if isinstance(item, dict))
            total = next((result.get(key) for key in ("totalCount", "total_count", "total", "count") if isinstance(result.get(key), int)), None)
            if not page or len(page) < limit or (total is not None and len(rows) >= total):
                return rows
        raise FuploadError("version list pagination exceeded the supported limit", kind="verification_required", verification_required=True)

    def _find_version(self, module_id, version_id):
        wanted=self._id_value(version_id)
        return next((x for x in self._version_rows(module_id) if self._id_value(x.get("id"))==wanted),None)
    def _wait_module(self,module_id,expected):
        attempts=int(self.config.get("verify_attempts",30))
        mismatches=list(expected)
        for attempt in range(attempts):
            actual=self._module_detail(module_id)
            mismatches=[key for key,wanted in expected.items() if self._comparable(key,actual.get(key))!=self._comparable(key,wanted)]
            if not mismatches: return actual
            if attempt+1<attempts: time.sleep(float(self.config.get("verify_interval",2)))
        raise FuploadError("module update readback mismatch",kind="verification_required",verification_required=True,details={"fields":mismatches})
    def _wait_version(self,module_id,version_id,name,deleted=False,expected=None,excluded_ids=None,expected_archive=None):
        excluded_ids=excluded_ids or set()
        for attempt in range(int(self.config.get("verify_attempts",30))):
            rows=self._version_rows(module_id)
            if version_id is not None:
                candidates=[x for x in rows if self._id_value(x.get("id"))==self._id_value(version_id)]
            else:
                candidates=[x for x in rows if x.get("name")==name and self._id_value(x.get("id")) not in excluded_ids]
            if len(candidates)>1: raise FuploadError("version write readback is ambiguous",kind="verification_required",verification_required=True)
            found=candidates[0] if candidates else None
            matches_expected = found and all(
                self._comparable(key,found.get(key))==self._comparable(key,wanted)
                for key, wanted in (expected or {}).items()
            )
            if matches_expected and expected_archive is not None:
                matches_expected = self._comparable("fileUrl", self._archive_url(found)) == self._comparable("fileUrl", expected_archive)
            if (deleted and (found is None or found.get("auditState")==4)) or (not deleted and found and matches_expected): return found or {}
            if attempt+1<int(self.config.get("verify_attempts",30)): time.sleep(float(self.config.get("verify_interval",2)))
        raise FuploadError("version write was not confirmed by readback",kind="verification_required",verification_required=True)
    @staticmethod
    def _redact(value):
        if isinstance(value,dict):
            markers=("token","secret","cookie","nonce","hkey","pkey","credential","signature","authorization","authentication","device_id","signed_url","upload_url","presigned")
            return {k:("<redacted>" if any(s in str(k).lower() for s in markers) else Blackbox._redact(v)) for k,v in value.items()}
        if isinstance(value,(list,tuple)): return [Blackbox._redact(v) for v in value]
        if isinstance(value,str):
            parsed=urlsplit(value)
            if parsed.scheme in {"http","https"} and parsed.netloc and parsed.query:
                return urlunsplit((parsed.scheme,parsed.netloc,parsed.path,"<redacted>",parsed.fragment))
        return value

    @staticmethod
    def _id_value(value):
        try: return int(value)
        except (TypeError,ValueError): return value
    @staticmethod
    def _archive_url(row): return row.get("fileUrlHeybox") or row.get("fileUrl") or row.get("file_url")
    @staticmethod
    def _comparable(key,value):
        if key in {"categoryIds","gameVersions","coreFolders"}:
            if isinstance(value,str): items=[item for item in value.split(",") if item]
            elif isinstance(value,(list,tuple,set)): items=list(value)
            else: items=[] if value is None else [value]
            normalized=[]
            for item in items:
                if isinstance(item,Mapping): item=item.get("id",item.get("value"))
                if item not in (None, ""):
                    normalized.append(str(item))
            return tuple(sorted(normalized))
        if key in {"id","type"}: return Blackbox._id_value(value)
        return value

    def upload_zip(self, module_id: int, file_path: str, *, dry_run=False):
        path=Path(file_path)
        if not path.is_file(): raise ValidationError("file does not exist",path="$.file")
        if not zipfile.is_zipfile(path): raise ValidationError("file must be a valid ZIP archive",path="$.file")
        if dry_run: return {"dry_run":True,"bytes":path.stat().st_size,"sha256":hashlib.sha256(path.read_bytes()).hexdigest()}
        return self._upload_zip_legacy(path)

    def _upload_zip_legacy(self, path: Path):
        size_mb=path.stat().st_size/1024/1024
        token=self._result(self._request("POST","/wow/cos/upload/token/",body={"jsonData":json.dumps({"upload_infos":[{"filename":path.name,"file_size":size_mb,"type":"module"}]},separators=(",",":"))}))
        info=token["info"]; f=token["files"][0]; creds=info["Credentials"].get("Credentials",info["Credentials"])
        try:
            from qcloud_cos import CosConfig, CosS3Client
        except ModuleNotFoundError as exc:
            raise FuploadError(
                "The managed Fuploader Python runtime is missing the Heybox COS SDK",
                kind="environment_error",
                details={"repair_command":"fupload update"},
            ) from exc
        try:
            cos=CosS3Client(CosConfig(Region=info.get("region") or "ap-shanghai",SecretId=creds["TmpSecretID"],SecretKey=creds["TmpSecretKey"],Token=creds["Token"],Scheme="https"))
            with path.open("rb") as stream: cos.put_object(Bucket=info["bucket"],Key=f["key"],Body=stream)
        except Exception as exc: raise FuploadError("COS upload failed",verification_required=True) from exc
        return {"url":"https://%s/%s"%(info["host"],f["key"]),"bytes":path.stat().st_size,"sha256":hashlib.sha256(path.read_bytes()).hexdigest(),"protocol":"legacy"}
