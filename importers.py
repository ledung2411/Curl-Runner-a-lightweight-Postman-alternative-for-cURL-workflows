# importers.py - Import Postman (collection v2.x + environment), Bruno (thư mục .bru) và HAR.
# Mọi request được chuyển thành lệnh curl — định dạng gốc của Curl Runner.
from __future__ import annotations

import json
import re
import shlex
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit


@dataclass
class ImportResult:
    source: str = ""
    collections: dict[str, list[dict]] = field(default_factory=dict)
    environments: dict[str, dict[str, str]] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    @property
    def request_count(self) -> int:
        return sum(len(items) for items in self.collections.values())


# ──────────────────────────────────────────────
# Shared helpers
# ──────────────────────────────────────────────
def build_curl(
    method: str,
    url: str,
    headers: list[tuple[str, str]] | None = None,
    body: str | None = None,
    form: list[tuple[str, str, bool]] | None = None,
    urlencoded: list[tuple[str, str]] | None = None,
    basic_auth: tuple[str, str] | None = None,
) -> str:
    """Sinh lệnh curl nhiều dòng, quote an toàn cho bash."""
    method = (method or "GET").upper()
    parts = ["curl"]
    has_body = bool(body) or bool(form) or bool(urlencoded)
    if method != "GET" or has_body:
        parts.append(f"-X {method}")
    parts.append(shlex.quote(url))
    for key, value in headers or []:
        parts.append(f"-H {shlex.quote(f'{key}: {value}')}")
    if basic_auth:
        parts.append(f"-u {shlex.quote(':'.join(basic_auth))}")
    for key, value, is_file in form or []:
        parts.append(f"-F {shlex.quote(f'{key}=@{value}' if is_file else f'{key}={value}')}")
    for key, value in urlencoded or []:
        parts.append(f"--data-urlencode {shlex.quote(f'{key}={value}')}")
    if body:
        parts.append(f"--data-raw {shlex.quote(body)}")
    return " \\\n  ".join(parts)


def _item(name: str, method: str, curl: str, extractors: str = "", assertions: str = "") -> dict:
    item = {"id": str(uuid.uuid4())[:8], "name": name, "method": (method or "GET").upper(), "curl": curl}
    if extractors:
        item["extractors"] = extractors
    if assertions:
        item["assertions"] = assertions
    return item


def _has_header(headers: list[tuple[str, str]], name: str) -> bool:
    return any(k.lower() == name.lower() for k, _ in headers)


def _json_path_from_js(expr: str) -> str | None:
    """`data.items[0].id` / `['full name']` (JS) → `$.data.items[0].id` (JSONPath của app)."""
    expr = expr.strip()
    if not expr:
        return "$"
    if not re.fullmatch(r"(?:\.?[A-Za-z_$][\w$-]*|\[\d+\]|\[\s*(['\"]).*?\1\s*\])+", expr):
        return None
    if not expr.startswith(("[", ".")):
        expr = "." + expr
    return "$" + expr


# ──────────────────────────────────────────────
# Postman
# ──────────────────────────────────────────────
_PM_STATUS_RES = [
    re.compile(r"pm\.response\.to\.have\.status\(\s*(\d{3})\s*\)"),
    re.compile(r"pm\.expect\(\s*pm\.response\.(?:code|status)\s*\)\.to\.(?:eql|equal|eq)\(\s*(\d{3})\s*\)"),
]
_PM_SET_RE = re.compile(
    r"pm\.(?:environment|collectionVariables|globals|variables)\.set\(\s*['\"]([\w.-]+)['\"]\s*,\s*"
    r"(?:pm\.response\.json\(\)|(?:jsonData|data|json|body|res|response)\b)([^)]*?)\s*\)"
)
_PM_SET_HEADER_RE = re.compile(
    r"pm\.(?:environment|collectionVariables|globals|variables)\.set\(\s*['\"]([\w.-]+)['\"]\s*,\s*"
    r"pm\.response\.headers\.get\(\s*['\"]([^'\"]+)['\"]\s*\)\s*\)"
)
_PM_TIME_RE = re.compile(r"pm\.expect\(\s*pm\.response\.responseTime\s*\)\.to\.be\.below\(\s*(\d+)\s*\)")
_PM_BODY_INCLUDE_RE = re.compile(r"pm\.expect\(\s*pm\.response\.text\(\)\s*\)\.to\.include\(\s*['\"]([^'\"]+)['\"]\s*\)")
_PM_OK_RE = re.compile(r"pm\.response\.to\.(?:be|have)\.(?:ok|success)\b")
# Dòng "khung" không chứa logic: pm.test(..., function () {, });, var json = pm.response.json();
_PM_BOILERPLATE_RE = re.compile(
    r"^\s*(?://.*|[{}();\s]*|pm\.test\(.*(?:function\s*\(\)|\(\)\s*=>)\s*\{\s*"
    r"|(?:var|let|const)\s+\w+\s*=\s*pm\.response\.json\(\)\s*;?)$"
)


def translate_postman_tests(lines: list[str]) -> tuple[str, str, bool]:
    """Dịch các mẫu test Postman phổ biến. Returns (extractors, assertions, có phần không dịch được)."""
    extractors: list[str] = []
    assertions: list[str] = []
    partial = False
    for line in lines:
        found_before = len(extractors) + len(assertions)
        for pattern in _PM_STATUS_RES:
            assertions += [f"status == {code}" for code in pattern.findall(line)]
        if _PM_OK_RE.search(line):
            assertions += ["status >= 200", "status < 300"]
        assertions += [f"time < {ms}" for ms in _PM_TIME_RE.findall(line)]
        assertions += [f"body contains {text}" for text in _PM_BODY_INCLUDE_RE.findall(line)]
        for name, path in _PM_SET_RE.findall(line):
            json_path = _json_path_from_js(path)
            if json_path:
                extractors.append(f"{name} = json:{json_path}")
        for name, header in _PM_SET_HEADER_RE.findall(line):
            extractors.append(f"{name} = header:{header}")
        if len(extractors) + len(assertions) == found_before and not _PM_BOILERPLATE_RE.match(line):
            partial = True
    return "\n".join(extractors), "\n".join(dict.fromkeys(assertions)), partial


def _pm_kv(entries: Any) -> list[tuple[str, str]]:
    out = []
    for entry in entries or []:
        if isinstance(entry, dict) and entry.get("key") and not entry.get("disabled"):
            out.append((str(entry["key"]), "" if entry.get("value") is None else str(entry["value"])))
    return out


def _pm_auth_map(auth: dict) -> dict[str, str]:
    raw = auth.get(auth.get("type", ""), [])
    if isinstance(raw, dict):        # collection v2.0
        return {str(k): str(v) for k, v in raw.items()}
    return {str(e.get("key")): "" if e.get("value") is None else str(e.get("value"))
            for e in raw if isinstance(e, dict)}


def _pm_url(url: Any) -> str:
    if isinstance(url, str):
        return url
    if not isinstance(url, dict):
        return ""
    if url.get("raw"):
        return str(url["raw"])
    host = url.get("host", "")
    host = ".".join(host) if isinstance(host, list) else str(host)
    path = url.get("path", "")
    path = "/".join(str(p) for p in path) if isinstance(path, list) else str(path)
    built = f"{url.get('protocol', 'https')}://{host}" + (f"/{path}" if path else "")
    query = "&".join(f"{k}={v}" for k, v in _pm_kv(url.get("query")))
    return built + (f"?{query}" if query else "")


def _pm_request_to_item(name: str, request: dict, events: list, inherited_auth: dict | None,
                        notes: list[str]) -> dict:
    method = str(request.get("method") or "GET")
    url = _pm_url(request.get("url"))
    headers = _pm_kv(request.get("header"))
    body = request.get("body") or {}
    raw_body: str | None = None
    form: list[tuple[str, str, bool]] = []
    urlencoded: list[tuple[str, str]] = []
    basic: tuple[str, str] | None = None

    mode = body.get("mode") if isinstance(body, dict) else None
    if mode == "raw" and body.get("raw"):
        raw_body = str(body["raw"])
        language = (((body.get("options") or {}).get("raw") or {}).get("language") or "").lower()
        if language == "json" and not _has_header(headers, "Content-Type"):
            headers.append(("Content-Type", "application/json"))
    elif mode == "urlencoded":
        urlencoded = _pm_kv(body.get("urlencoded"))
    elif mode == "formdata":
        for entry in body.get("formdata") or []:
            if not isinstance(entry, dict) or not entry.get("key") or entry.get("disabled"):
                continue
            if entry.get("type") == "file":
                src = entry.get("src")
                form.append((str(entry["key"]), str(src[0] if isinstance(src, list) and src else src or ""), True))
            else:
                form.append((str(entry["key"]), str(entry.get("value") or ""), False))
    elif mode == "graphql":
        graphql = body.get("graphql") or {}
        variables = graphql.get("variables") or "{}"
        try:
            variables_obj = json.loads(variables) if isinstance(variables, str) else variables
        except ValueError:
            variables_obj = {}
        raw_body = json.dumps({"query": graphql.get("query", ""), "variables": variables_obj}, ensure_ascii=False)
        if not _has_header(headers, "Content-Type"):
            headers.append(("Content-Type", "application/json"))
    elif mode == "file":
        notes.append(f"{name}: body dạng file (binary) chưa được import — hãy thêm --data-binary @file.")

    auth = request.get("auth") if isinstance(request.get("auth"), dict) else inherited_auth
    if auth:
        kind = auth.get("type")
        values = _pm_auth_map(auth)
        if kind == "bearer" and not _has_header(headers, "Authorization"):
            headers.append(("Authorization", f"Bearer {values.get('token', '')}"))
        elif kind == "basic":
            basic = (values.get("username", ""), values.get("password", ""))
        elif kind == "apikey":
            key, value = values.get("key", "x-api-key"), values.get("value", "")
            if values.get("in") == "query":
                url += ("&" if "?" in url else "?") + f"{key}={value}"
            else:
                headers.append((key, value))
        elif kind not in (None, "noauth"):
            notes.append(f"{name}: kiểu auth `{kind}` chưa hỗ trợ, hãy thêm header thủ công.")

    extractors, assertions = "", ""
    for event in events or []:
        if not isinstance(event, dict) or event.get("listen") != "test":
            if isinstance(event, dict) and event.get("listen") == "prerequest":
                script = (event.get("script") or {}).get("exec") or []
                if any(str(line).strip() for line in script):
                    notes.append(f"{name}: pre-request script (JS) không được chuyển đổi.")
            continue
        exec_lines = (event.get("script") or {}).get("exec") or []
        if isinstance(exec_lines, str):
            exec_lines = exec_lines.splitlines()
        extractors, assertions, partial = translate_postman_tests([str(x) for x in exec_lines])
        if partial:
            notes.append(f"{name}: một phần test script (JS) không dịch được, cần kiểm tra lại tab Tests.")

    curl = build_curl(method, url, headers, raw_body, form, urlencoded, basic)
    return _item(name, method, curl, extractors, assertions)


def import_postman_collection(data: dict) -> ImportResult:
    info = data.get("info") or {}
    name = str(info.get("name") or "Postman Collection")
    result = ImportResult(source="Postman collection")
    items: list[dict] = []

    def walk(entries: list, prefix: str, inherited_auth: dict | None) -> None:
        for entry in entries or []:
            if not isinstance(entry, dict):
                continue
            entry_name = str(entry.get("name") or "Request")
            if isinstance(entry.get("item"), list):        # folder
                folder_auth = entry.get("auth") if isinstance(entry.get("auth"), dict) else inherited_auth
                walk(entry["item"], f"{prefix}{entry_name} / ", folder_auth)
            elif isinstance(entry.get("request"), (dict, str)):
                request = entry["request"]
                if isinstance(request, str):
                    request = {"method": "GET", "url": request}
                items.append(_pm_request_to_item(
                    prefix + entry_name, request, entry.get("event") or [], inherited_auth, result.notes,
                ))

    walk(data.get("item") or [], "", data.get("auth") if isinstance(data.get("auth"), dict) else None)
    result.collections[name] = items
    variables = _pm_kv(data.get("variable"))
    if variables:
        result.environments[f"{name} (variables)"] = dict(variables)
    for event in data.get("event") or []:
        if isinstance(event, dict) and any(str(x).strip() for x in (event.get("script") or {}).get("exec") or []):
            result.notes.append("Script cấp collection (JS) không được chuyển đổi.")
            break
    return result


def import_postman_environment(data: dict) -> ImportResult:
    result = ImportResult(source="Postman environment")
    name = str(data.get("name") or "Postman Environment")
    result.environments[name] = {
        str(v["key"]): "" if v.get("value") is None else str(v.get("value"))
        for v in data.get("values") or []
        if isinstance(v, dict) and v.get("key") and v.get("enabled", True)
    }
    return result


# ──────────────────────────────────────────────
# Bruno (.bru)
# ──────────────────────────────────────────────
_BRU_BLOCK_RE = re.compile(r"^([A-Za-z][\w:-]*)\s*([{\[])\s*$")
_BRU_METHODS = ("get", "post", "put", "patch", "delete", "head", "options", "trace", "connect")
_BRU_OPS = {"eq": "==", "neq": "!=", "gt": ">", "gte": ">=", "lt": "<", "lte": "<="}


def parse_bru(text: str) -> dict[str, str]:
    """Tách file .bru thành {tên block: nội dung đã bỏ thụt lề}."""
    blocks: dict[str, str] = {}
    lines = text.replace("\r\n", "\n").split("\n")
    i = 0
    while i < len(lines):
        m = _BRU_BLOCK_RE.match(lines[i])
        if not m:
            i += 1
            continue
        name, closer = m.group(1), "}" if m.group(2) == "{" else "]"
        body: list[str] = []
        i += 1
        while i < len(lines) and lines[i].rstrip() != closer:
            body.append(lines[i])
            i += 1
        blocks[name] = "\n".join(ln[2:] if ln.startswith("  ") else ln for ln in body).strip("\n")
        i += 1
    return blocks


def _bru_kv(block: str) -> list[tuple[str, str]]:
    out = []
    for line in (block or "").splitlines():
        if not line.strip() or line.lstrip().startswith("~"):   # ~ = dòng bị tắt
            continue
        key, sep, value = line.partition(":")
        if sep and key.strip():
            out.append((key.strip(), value.strip()))
    return out


def _bru_res_path(expr: str) -> tuple[str, str] | None:
    """`res.body.data.id` → ("json", "$.data.id"); `res.headers['x-id']` → ("header", "x-id")."""
    expr = expr.strip()
    for pattern in (r"res\.headers\[\s*['\"]([^'\"]+)['\"]\s*\]",
                    r"res\.headers\.([\w-]+)",
                    r"res\.getHeader\(\s*['\"]([^'\"]+)['\"]\s*\)"):
        if m := re.fullmatch(pattern, expr):
            return "header", m.group(1)
    if m := re.fullmatch(r"res\.body(.*)", expr):
        path = _json_path_from_js(m.group(1))
        return ("json", path) if path else None
    if m := re.fullmatch(r"res\(\s*['\"]([^'\"]+)['\"]\s*\)", expr):
        path = _json_path_from_js(m.group(1))
        return ("json", path) if path else None
    return None


def bru_to_item(text: str, fallback_name: str, notes: list[str]) -> dict | None:
    blocks = parse_bru(text)
    meta = dict(_bru_kv(blocks.get("meta", "")))
    name = meta.get("name") or fallback_name
    method_block = next((m for m in _BRU_METHODS if m in blocks), None)
    if method_block is None:
        if meta.get("type") and meta.get("type") != "http":
            notes.append(f"{name}: request loại `{meta.get('type')}` (không phải HTTP) bị bỏ qua.")
        return None
    request = dict(_bru_kv(blocks[method_block]))
    url = request.get("url", "")
    headers = _bru_kv(blocks.get("headers", ""))
    body_kind = request.get("body", "none")
    raw_body: str | None = None
    form: list[tuple[str, str, bool]] = []
    urlencoded: list[tuple[str, str]] = []
    basic: tuple[str, str] | None = None

    if body_kind in ("json", "text", "xml", "sparql", "graphql"):
        raw_body = blocks.get(f"body:{body_kind}", "") or None
        if body_kind == "graphql" and raw_body:
            variables = blocks.get("body:graphql:vars", "") or "{}"
            try:
                variables_obj = json.loads(variables)
            except ValueError:
                variables_obj = {}
            raw_body = json.dumps({"query": raw_body, "variables": variables_obj}, ensure_ascii=False)
        content_type = {"json": "application/json", "graphql": "application/json",
                        "xml": "application/xml", "text": "text/plain"}.get(body_kind)
        if raw_body and content_type and not _has_header(headers, "Content-Type"):
            headers.append(("Content-Type", content_type))
    elif body_kind == "form-urlencoded":
        urlencoded = _bru_kv(blocks.get("body:form-urlencoded", ""))
    elif body_kind == "multipart-form":
        for key, value in _bru_kv(blocks.get("body:multipart-form", "")):
            if m := re.fullmatch(r"@file\((.*)\)", value):
                form.append((key, m.group(1).split("|")[0], True))
            else:
                form.append((key, value, False))
    elif body_kind not in ("none", ""):
        notes.append(f"{name}: body `{body_kind}` chưa hỗ trợ.")

    auth_kind = request.get("auth", "none")
    if auth_kind == "bearer":
        token = dict(_bru_kv(blocks.get("auth:bearer", ""))).get("token", "")
        headers.append(("Authorization", f"Bearer {token}"))
    elif auth_kind == "basic":
        values = dict(_bru_kv(blocks.get("auth:basic", "")))
        basic = (values.get("username", ""), values.get("password", ""))
    elif auth_kind == "apikey":
        values = dict(_bru_kv(blocks.get("auth:apikey", "")))
        if values.get("placement") == "queryparams":
            url += ("&" if "?" in url else "?") + f"{values.get('key', '')}={values.get('value', '')}"
        else:
            headers.append((values.get("key", "x-api-key"), values.get("value", "")))
    elif auth_kind not in ("none", "inherit", ""):
        notes.append(f"{name}: auth `{auth_kind}` chưa hỗ trợ, hãy thêm header thủ công.")

    extractors: list[str] = []
    for var, expr in _bru_kv(blocks.get("vars:post-response", "")):
        target = _bru_res_path(expr)
        if target:
            extractors.append(f"{var} = {target[0]}:{target[1]}")
        else:
            notes.append(f"{name}: biến post-response `{var}: {expr}` không chuyển đổi được.")

    assertions: list[str] = []
    for subject, rule in _bru_kv(blocks.get("assert", "")):
        op, _, expected = rule.partition(" ")
        expected = expected.strip()
        if subject == "res.status" and op in _BRU_OPS:
            assertions.append(f"status {_BRU_OPS[op]} {expected}")
        elif subject == "res.responseTime" and op in _BRU_OPS:
            assertions.append(f"time {_BRU_OPS[op]} {expected}")
        elif (target := _bru_res_path(subject)) and target[0] == "json" and op in _BRU_OPS:
            assertions.append(f"json {target[1]} {_BRU_OPS[op]} {expected}")
        elif (target := _bru_res_path(subject)) and target[0] == "json" and op == "isDefined":
            assertions.append(f"json {target[1]} exists")
        elif (target := _bru_res_path(subject)) and target[0] == "header" and op in ("eq", "contains"):
            assertions.append(f"header {target[1]} {'==' if op == 'eq' else 'contains'} {expected}")
        else:
            notes.append(f"{name}: assert `{subject}: {rule}` không chuyển đổi được.")
    for script_block in ("tests", "script:pre-request", "script:post-response"):
        if blocks.get(script_block, "").strip():
            notes.append(f"{name}: khối `{script_block}` (JS) không được chuyển đổi.")

    curl = build_curl(method_block, url, headers, raw_body, form, urlencoded, basic)
    item = _item(name, method_block, curl, "\n".join(extractors), "\n".join(assertions))
    item["_seq"] = float(meta.get("seq") or 0)
    return item


def import_bruno_folder(folder: Path) -> ImportResult:
    result = ImportResult(source="Bruno collection")
    config: dict = {}
    if (folder / "bruno.json").is_file():
        try:
            config = json.loads((folder / "bruno.json").read_text(encoding="utf-8"))
        except ValueError:
            config = {}
    name = str(config.get("name") or folder.name)
    items: list[tuple[str, dict]] = []
    for path in sorted(folder.rglob("*.bru")):
        rel = path.relative_to(folder)
        if rel.parts[0] == "environments" or path.name in ("collection.bru", "folder.bru"):
            continue
        item = bru_to_item(path.read_text(encoding="utf-8"), path.stem, result.notes)
        if item is None:
            continue
        folder_prefix = " / ".join(rel.parts[:-1])
        if folder_prefix:
            item["name"] = f"{folder_prefix} / {item['name']}"
        items.append((folder_prefix, item))
    items.sort(key=lambda pair: (pair[0], pair[1]["_seq"]))
    result.collections[name] = [{k: v for k, v in item.items() if k != "_seq"} for _, item in items]

    env_dir = folder / "environments"
    for env_path in sorted(env_dir.glob("*.bru")) if env_dir.is_dir() else []:
        blocks = parse_bru(env_path.read_text(encoding="utf-8"))
        values = dict(_bru_kv(blocks.get("vars", "")))
        secrets = [ln.strip().rstrip(",") for ln in blocks.get("vars:secret", "").splitlines() if ln.strip()]
        for secret in secrets:
            values.setdefault(secret.lstrip("~"), "")
        if secrets:
            result.notes.append(
                f"Environment {env_path.stem}: biến bí mật {', '.join(secrets)} không có giá trị trong file, hãy điền lại.")
        result.environments[env_path.stem] = values
    return result


# ──────────────────────────────────────────────
# HAR (DevTools → Network → Save all as HAR)
# ──────────────────────────────────────────────
_HAR_SKIP_HEADERS = {"content-length", "host", "connection", "accept-encoding"}


def import_har(data: dict, name: str = "HAR import") -> ImportResult:
    result = ImportResult(source="HAR")
    entries = [e for e in ((data.get("log") or {}).get("entries") or []) if isinstance(e, dict)]
    if any("_resourceType" in e for e in entries):
        before = len(entries)
        entries = [e for e in entries if e.get("_resourceType") in ("xhr", "fetch")]
        if before != len(entries):
            result.notes.append(f"Bỏ qua {before - len(entries)} request không phải XHR/fetch (ảnh, CSS, JS...).")
    items = []
    for entry in entries:
        request = entry.get("request") or {}
        method = str(request.get("method") or "GET")
        url = str(request.get("url") or "")
        headers = [
            (str(h.get("name")), str(h.get("value", "")))
            for h in request.get("headers") or []
            if isinstance(h, dict) and h.get("name")
            and not str(h["name"]).startswith(":")                  # pseudo-header HTTP/2
            and str(h["name"]).lower() not in _HAR_SKIP_HEADERS
        ]
        post = request.get("postData") or {}
        body = post.get("text") or None
        urlencoded: list[tuple[str, str]] = []
        if not body and post.get("params"):
            urlencoded = [(str(p.get("name")), str(p.get("value", ""))) for p in post["params"] if p.get("name")]
        parts = urlsplit(url)
        label = f"{method.upper()} {parts.path or '/'}"
        items.append(_item(label, method, build_curl(method, url, headers, body, None, urlencoded)))
    result.collections[name] = items
    result.notes.append("HAR chứa cookie/token thật của phiên duyệt web — hãy thay bằng {{biến}} trước khi chia sẻ.")
    return result


# ──────────────────────────────────────────────
# Auto-detect + merge
# ──────────────────────────────────────────────
def import_path(path: str | Path) -> ImportResult:
    path = Path(path)
    if path.is_dir():
        if (path / "bruno.json").is_file() or any(path.rglob("*.bru")):
            return import_bruno_folder(path)
        raise ValueError(f"Thư mục {path} không phải Bruno collection (không có bruno.json / *.bru)")
    if path.suffix.lower() == ".bru":
        result = ImportResult(source="Bruno request")
        item = bru_to_item(path.read_text(encoding="utf-8"), path.stem, result.notes)
        result.collections[path.parent.name or "Bruno"] = [item] if item else []
        return result
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except ValueError as exc:
        raise ValueError(f"{path.name} không phải JSON hợp lệ: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"{path.name}: định dạng không được hỗ trợ")
    if isinstance(data.get("log"), dict) and "entries" in data["log"]:
        return import_har(data, name=path.stem)
    if isinstance(data.get("item"), list) and isinstance(data.get("info"), dict):
        return import_postman_collection(data)
    if isinstance(data.get("values"), list):
        return import_postman_environment(data)
    raise ValueError(f"{path.name}: không nhận ra định dạng (hỗ trợ Postman collection/environment, Bruno, HAR)")


def _unique_name(name: str, existing: dict) -> str:
    if name not in existing:
        return name
    n = 2
    while f"{name} ({n})" in existing:
        n += 1
    return f"{name} ({n})"


def merge_import(result: ImportResult, collections: dict, environments: dict) -> list[str]:
    """Gộp kết quả import vào dữ liệu app (không ghi đè dữ liệu cũ). Returns tên đã tạo."""
    created = []
    for name, items in result.collections.items():
        target = _unique_name(name, collections)
        collections[target] = items
        created.append(f"collection: {target} ({len(items)} request)")
    for name, values in result.environments.items():
        target = _unique_name(name, environments)
        environments[target] = values
        created.append(f"environment: {target} ({len(values)} biến)")
    return created
