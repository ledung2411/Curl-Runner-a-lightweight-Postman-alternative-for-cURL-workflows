# redaction.py - Biến bí mật & che token trong lệnh curl (history, AI, màn hình Info).
from __future__ import annotations

import json
import re
import shlex
from typing import Any
from urllib.parse import parse_qsl

from core import SENSITIVE_KEY_RE, _iter_curl_options, _normalize_curl_text, shell_split

REDACTED = "[REDACTED]"
MASK = "••••••"
MIN_SECRET_LENGTH = 4   # giá trị quá ngắn ("1", "yes") thay thế sẽ làm hỏng text

_EXTRA_SECRET_NAME_RE = re.compile(r"(pass|pwd|credential|private|session|signature|(^|[_-])key$)", re.I)
_SECRET_HEADERS = {"authorization", "proxy-authorization", "cookie", "x-api-key", "api-key", "x-auth-token"}
_DATA_OPTIONS = {"--data", "--data-ascii", "--data-raw", "--data-binary", "--json"}


def is_secret_name(name: str, extra_names: set[str] | list[str] | None = None) -> bool:
    """Biến bí mật: tên giống token/secret/password/api_key... hoặc được người dùng đánh dấu."""
    if extra_names and name in extra_names:
        return True
    return bool(SENSITIVE_KEY_RE.search(name) or _EXTRA_SECRET_NAME_RE.search(name))


def secret_map(env: dict[str, Any], extra_names: set[str] | list[str] | None = None) -> dict[str, str]:
    """{tên biến: giá trị} của các biến bí mật đủ dài để thay thế an toàn."""
    return {
        str(name): str(value) for name, value in (env or {}).items()
        if value is not None and len(str(value)) >= MIN_SECRET_LENGTH and is_secret_name(str(name), extra_names)
    }


def replace_secret_values(text: str, secrets: dict[str, str], placeholder: str | None = None) -> str:
    """Thay giá trị bí mật bằng {{tên}} (hoặc placeholder cố định). Giá trị dài thay trước."""
    for name, value in sorted(secrets.items(), key=lambda kv: len(kv[1]), reverse=True):
        text = text.replace(value, placeholder if placeholder is not None else "{{" + name + "}}")
    return text


def _has_var(value: str) -> bool:
    return "{{" in value


def _redact_pairs(text: str, sep: str = "&") -> str:
    """`user=a&password=b` → `user=a&password=[REDACTED]` (giữ nguyên phần không nhạy cảm)."""
    parts = []
    changed = False
    for part in text.split(sep):
        key, eq, value = part.partition("=")
        if eq and SENSITIVE_KEY_RE.search(key.strip()) and value.strip() and not _has_var(value):
            parts.append(f"{key}={REDACTED}")
            changed = True
        else:
            parts.append(part)
    return sep.join(parts) if changed else text


def _redact_json(value: Any) -> tuple[Any, bool]:
    if isinstance(value, dict):
        changed = False
        out = {}
        for key, item in value.items():
            if SENSITIVE_KEY_RE.search(str(key)) and isinstance(item, (str, int, float)) \
                    and not (isinstance(item, str) and (not item or _has_var(item))):
                out[key] = REDACTED
                changed = True
            else:
                out[key], sub_changed = _redact_json(item)
                changed = changed or sub_changed
        return out, changed
    if isinstance(value, list):
        results = [_redact_json(item) for item in value]
        return [r[0] for r in results], any(r[1] for r in results)
    return value, False


def _redact_url(url: str) -> str:
    base, q, query = url.partition("?")
    if not q:
        return url
    fragment = ""
    if "#" in query:
        query, _, fragment = query.partition("#")
        fragment = "#" + fragment
    if not any(SENSITIVE_KEY_RE.search(k) for k, _ in parse_qsl(query, keep_blank_values=True)):
        return url
    return f"{base}?{_redact_pairs(query)}{fragment}"


def _redact_header(value: str) -> str:
    name, sep, header_value = value.partition(":")
    lower = name.strip().lower()
    header_value = header_value.strip()
    if not sep or not header_value or _has_var(header_value):
        return value
    if lower == "cookie":
        return f"{name.strip()}: {_redact_cookie(header_value)}"
    if lower in _SECRET_HEADERS or SENSITIVE_KEY_RE.search(lower):
        scheme, space, _credential = header_value.partition(" ")
        if lower.endswith("authorization") and space and scheme.isalpha():
            return f"{name.strip()}: {scheme} {REDACTED}"       # giữ "Bearer"/"Basic"
        return f"{name.strip()}: {REDACTED}"
    return value


def _redact_cookie(cookie: str) -> str:
    parts = []
    for part in cookie.split(";"):
        key, eq, value = part.partition("=")
        parts.append(f"{key.strip()}={REDACTED}" if eq and value.strip() and not _has_var(value) else part.strip())
    return "; ".join(p for p in parts if p)


def _redact_option(opt: str | None, value: str | None) -> str | None:
    if value is None:
        return None
    if opt is None or opt == "--url":
        return _redact_url(value)
    if opt == "--header":
        return _redact_header(value)
    if opt == "--user":
        user, sep, password = value.partition(":")
        return f"{user}:{REDACTED}" if sep and password and not _has_var(password) else value
    if opt == "--oauth2-bearer":
        return value if _has_var(value) else REDACTED
    if opt == "--cookie":
        return _redact_cookie(value) if "=" in value else value
    if opt in ("--form", "--form-string", "--data-urlencode"):
        key, eq, field = value.partition("=")
        if eq and SENSITIVE_KEY_RE.search(key) and field and not field.startswith(("@", "<")) and not _has_var(field):
            return f"{key}={REDACTED}"
        return value
    if opt in _DATA_OPTIONS and not value.startswith("@"):
        try:
            data = json.loads(value)
        except ValueError:
            return _redact_pairs(value) if "=" in value else value
        redacted, changed = _redact_json(data)
        return json.dumps(redacted, ensure_ascii=False) if changed else value
    return value


def redact_curl(curl: str, secrets: dict[str, str] | None = None) -> str:
    """
    Che bí mật trong lệnh curl để lưu history / chia sẻ:
      1. giá trị của biến bí mật → {{tên_biến}} (mở lại vẫn chạy được);
      2. token dán thẳng (Authorization, Cookie, -u, --oauth2-bearer, ?token=, "password": ...)
         → [REDACTED].
    Lệnh không có gì cần che được giữ nguyên định dạng gốc.
    """
    text = replace_secret_values(curl or "", secrets or {})
    try:
        tokens = shell_split(_normalize_curl_text(text))
        pairs = list(_iter_curl_options(tokens[1:])) if tokens else []
    except ValueError:
        return text
    redacted = [(opt, _redact_option(opt, value)) for opt, value in pairs]
    if redacted == pairs:
        return text
    parts = [tokens[0]]
    for opt, value in redacted:
        if opt is None:
            parts.append(shlex.quote(value or ""))
        elif value is None:
            parts.append(opt)
        else:
            parts.append(f"{opt} {shlex.quote(value)}")
    return " \\\n  ".join(parts)


def redact_url(url: str, secrets: dict[str, str] | None = None) -> str:
    """URL lưu history: giá trị bí mật → {{tên}}, query nhạy cảm (?token=) → [REDACTED]."""
    return _redact_url(replace_secret_values(url or "", secrets or {}))


def mask_value(name: str, value: str, extra_names: set[str] | list[str] | None = None) -> str:
    """Giá trị hiển thị trên màn hình: biến bí mật → ••••••."""
    return MASK if value and is_secret_name(name, extra_names) else value
