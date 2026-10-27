# core.py — Business logic: parse curl, execute request, pre-script, decode, beautify
# type: ignore
from __future__ import annotations

import re
import json
import time
import os
import shutil
from pathlib import Path
from urllib.parse import quote, urlparse
from typing import Any

try:
    import requests
except ImportError as exc:  # pragma: no cover - depends on the local install
    # Never pip-install silently at import time; tell the user what to run instead.
    raise ImportError(
        "Thiếu thư viện 'requests'. Chạy: pip install -r requirements.txt"
    ) from exc

try:
    from charset_normalizer import from_bytes as _detect_encoding
    HAS_DETECT = True
except ImportError:
    try:
        from chardet import detect as _chardet_detect  # type: ignore
        def _detect_encoding(raw: bytes):              # type: ignore
            class _R:
                best = type("B", (), {
                    "encoding": _chardet_detect(raw).get("encoding", "utf-8")
                })()
            return _R()
        HAS_DETECT = True
    except ImportError:
        HAS_DETECT = False


AI_ANALYSIS_BODY_LIMIT = 12_000
AI_ANALYSIS_REQUEST_BODY_LIMIT = 4_000
OLLAMA_DEFAULT_BASE_URL = "http://localhost:11434"
OLLAMA_FALLBACK_MODELS = ("llama3.2", "llama3.1", "gemma3", "mistral", "qwen2.5")
OLLAMA_DEFAULT_MODEL = OLLAMA_FALLBACK_MODELS[0]
OLLAMA_DOWNLOAD_URL = "https://ollama.com/download"
SENSITIVE_KEY_RE = re.compile(
    r"(authorization|cookie|set-cookie|token|secret|password|passwd|api[-_ ]?key|x-api-key|access[_-]?token|refresh[_-]?token|jwt)",
    re.I,
)


def is_local_ollama_url(base_url: str = OLLAMA_DEFAULT_BASE_URL) -> bool:
    host = (urlparse(base_url).hostname or "").lower()
    return host in ("", "localhost", "127.0.0.1", "::1")


def find_ollama_executable() -> str:
    """Find the Ollama CLI even when PATH was not refreshed after install."""
    for name in ("ollama.exe", "ollama"):
        found = shutil.which(name)
        if found:
            return found

    candidates: list[Path] = []
    if os.name == "nt":
        local = os.environ.get("LOCALAPPDATA")
        program_files = os.environ.get("ProgramFiles")
        program_files_x86 = os.environ.get("ProgramFiles(x86)")
        for base in (local, program_files, program_files_x86):
            if not base:
                continue
            candidates.extend([
                Path(base) / "Programs" / "Ollama" / "ollama.exe",
                Path(base) / "Ollama" / "ollama.exe",
            ])
    else:
        candidates.extend([
            Path("/usr/local/bin/ollama"),
            Path("/usr/bin/ollama"),
            Path("/opt/homebrew/bin/ollama"),
        ])

    for path in candidates:
        if path.exists():
            return str(path)
    return ""


def ollama_install_command() -> list[str]:
    """Return the official command used by the setup popup to install Ollama."""
    if os.name == "nt":
        return [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            "irm https://ollama.com/install.ps1 | iex",
        ]
    return ["/bin/sh", "-lc", "curl -fsSL https://ollama.com/install.sh | sh"]


def ollama_start_command() -> list[str]:
    exe = find_ollama_executable()
    if not exe:
        raise RuntimeError("Ollama CLI chưa được cài hoặc chưa tìm thấy trong PATH.")
    return [exe, "serve"]


def ollama_pull_command(model: str = OLLAMA_DEFAULT_MODEL) -> list[str]:
    exe = find_ollama_executable()
    if not exe:
        raise RuntimeError("Ollama CLI chưa được cài hoặc chưa tìm thấy trong PATH.")
    return [exe, "pull", model or OLLAMA_DEFAULT_MODEL]


def _match_ollama_model(model: str, installed_models: list[str]) -> str:
    if not model:
        return ""
    for installed in installed_models:
        if installed == model or installed.startswith(model + ":"):
            return installed
    return ""


def get_ollama_status(
    preferred_model: str = "",
    base_url: str = OLLAMA_DEFAULT_BASE_URL,
    timeout: float = 2.5,
) -> dict[str, Any]:
    """Return install/server/model readiness for the Ollama setup UI."""
    base = base_url.rstrip("/")
    local_endpoint = is_local_ollama_url(base)
    cli_path = find_ollama_executable()
    models: list[str] = []
    api_error = ""
    api_running = False
    target_model = preferred_model or OLLAMA_DEFAULT_MODEL
    selected_model = ""

    try:
        r = requests.get(f"{base}/api/tags", timeout=timeout)
        r.raise_for_status()
        data = r.json()
        api_running = True
        for item in data.get("models", []) if isinstance(data, dict) else []:
            name = item.get("name") if isinstance(item, dict) else None
            if name:
                models.append(str(name))
    except Exception as exc:
        api_error = str(exc) or exc.__class__.__name__

    if api_running:
        if preferred_model:
            selected_model = _match_ollama_model(preferred_model, models)
        elif models:
            selected_model = _match_ollama_model(OLLAMA_DEFAULT_MODEL, models)
            if not selected_model:
                for candidate in OLLAMA_FALLBACK_MODELS:
                    selected_model = _match_ollama_model(candidate, models)
                    if selected_model:
                        break
            if not selected_model:
                selected_model = models[0]

    needs_install = local_endpoint and not cli_path
    needs_start = local_endpoint and bool(cli_path) and not api_running
    needs_model = api_running and not selected_model
    ready = api_running and bool(selected_model) and not needs_install

    if ready:
        message = f"Ollama ready ({selected_model})."
    elif needs_install:
        message = "Chưa tìm thấy Ollama trên máy local."
    elif needs_start:
        message = "Ollama đã cài nhưng server local chưa chạy."
    elif needs_model:
        message = f"Chưa có model `{target_model}` trong Ollama."
    elif not api_running:
        message = "Không kết nối được Ollama API."
    else:
        message = "Ollama chưa sẵn sàng."

    return {
        "ready": ready,
        "message": message,
        "base_url": base,
        "local_endpoint": local_endpoint,
        "cli_path": cli_path,
        "installed": bool(cli_path) or not local_endpoint,
        "api_running": api_running,
        "api_error": api_error,
        "models": models,
        "target_model": target_model,
        "selected_model": selected_model,
        "needs_install": needs_install,
        "needs_start": needs_start,
        "needs_model": needs_model,
    }


def redact_sensitive_text(text: str) -> str:
    """Best-effort redaction before sending request/response context to an AI model."""
    if not text:
        return ""
    text = re.sub(r"(?i)(bearer\s+)[A-Za-z0-9._~+/=-]+", r"\1[REDACTED]", text)
    text = re.sub(
        r"(?i)(\"?(?:access_token|refresh_token|token|api_key|apikey|secret|password|passwd)\"?\s*[:=]\s*\"?)[^\",\s}\]]+(\"?)",
        r"\1[REDACTED]\2",
        text,
    )
    lines = []
    for line in text.splitlines():
        head = line.split(":", 1)[0].split("=", 1)[0]
        if SENSITIVE_KEY_RE.search(head):
            if ":" in line:
                key, _, _ = line.partition(":")
                lines.append(f"{key}: [REDACTED]")
            elif "=" in line:
                key, _, _ = line.partition("=")
                lines.append(f"{key}=[REDACTED]")
            else:
                lines.append("[REDACTED]")
        else:
            lines.append(line)
    return "\n".join(lines)


def _redact_headers(headers: dict | Any) -> dict[str, str]:
    out: dict[str, str] = {}
    for k, v in dict(headers or {}).items():
        out[str(k)] = "[REDACTED]" if SENSITIVE_KEY_RE.search(str(k)) else str(v)
    return out


def build_ai_response_context(parsed: dict, resp, body_text: str, enc_info: str) -> str:
    """Build a compact, redacted prompt context for response debugging."""
    request_body = parsed.get("body") if parsed else None
    if isinstance(request_body, bytes):
        request_body_text = f"[binary body: {len(request_body):,} bytes]"
    elif request_body is None:
        request_body_text = ""
    else:
        request_body_text = redact_sensitive_text(str(request_body))[:AI_ANALYSIS_REQUEST_BODY_LIMIT]

    body_preview = redact_sensitive_text(body_text or "")
    truncated = ""
    if len(body_preview) > AI_ANALYSIS_BODY_LIMIT:
        truncated = f"\n[Response body truncated from {len(body_preview):,} characters.]"
        body_preview = body_preview[:AI_ANALYSIS_BODY_LIMIT]

    context = {
        "request": {
            "method": (parsed or {}).get("method"),
            "url": (parsed or {}).get("url"),
            "headers": _redact_headers((parsed or {}).get("headers", {})),
            "body_preview": request_body_text,
        },
        "response": {
            "status": f"{getattr(resp, 'status_code', '?')} {getattr(resp, 'reason', '')}".strip(),
            "headers": _redact_headers(getattr(resp, "headers", {})),
            "encoding": enc_info,
            "size_bytes": len(getattr(resp, "content", b"") or b""),
            "body_preview": body_preview + truncated,
        },
    }
    return json.dumps(context, ensure_ascii=False, indent=2)


def _extract_response_text(data: dict) -> str:
    if isinstance(data.get("output_text"), str):
        return data["output_text"].strip()

    parts: list[str] = []
    for item in data.get("output", []) or []:
        if item.get("type") != "message":
            continue
        for content in item.get("content", []) or []:
            if isinstance(content.get("text"), str):
                parts.append(content["text"])
    return "\n".join(parts).strip()


def _openai_error_message(status_code: int, body_text: str, data: dict | None) -> str:
    if isinstance(data, dict):
        err = data.get("error")
        if isinstance(err, dict):
            for key in ("message", "code", "type"):
                value = err.get(key)
                if value:
                    return str(value)
        elif err:
            return str(err)
    snippet = (body_text or "").strip()
    if snippet:
        return snippet[:800]
    return f"HTTP {status_code} with an empty response body"


def analyze_response_with_ai(api_key: str, context_json: str, model: str = "gpt-5.4-mini") -> str:
    """Call the OpenAI Responses API and return an API debugging report."""
    payload = {
        "model": model,
        "store": False,
        "max_output_tokens": 1200,
        "instructions": (
            "Respond in Vietnamese. Use clear, practical Vietnamese for developers. "
            "You are a senior API debugging assistant. Analyze the HTTP response and "
            "request context. Identify likely backend/client bugs, bad input, auth issues, "
            "schema mismatches, timeout/rate-limit clues, and suspicious response content. "
            "If the response appears healthy, say that clearly. Keep the answer concise "
            "with sections: Summary, Evidence, Likely cause, Suggested fixes, Next checks."
        ),
        "input": (
            "Analyze this redacted HTTP request/response context for errors or bugs. "
            "Do not reveal or reconstruct secrets.\n\n"
            f"{context_json}"
        ),
    }
    try:
        r = requests.post(
            "https://api.openai.com/v1/responses",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=90,
        )
    except requests.RequestException as exc:
        raise RuntimeError(f"Could not reach OpenAI API: {exc}") from exc

    raw_text = r.text or ""
    try:
        data = r.json()
    except Exception:
        data = None
    if r.status_code >= 400:
        msg = _openai_error_message(r.status_code, raw_text, data if isinstance(data, dict) else None)
        raise RuntimeError(f"OpenAI API error ({r.status_code}): {msg}")
    text = _extract_response_text(data if isinstance(data, dict) else {})
    if not text:
        snippet = raw_text[:800].strip()
        detail = f" Response body: {snippet}" if snippet else ""
        raise RuntimeError(f"OpenAI API returned no analysis text.{detail}")
    return text


def list_ollama_models(base_url: str = OLLAMA_DEFAULT_BASE_URL) -> list[str]:
    """Return locally installed Ollama model names."""
    base = base_url.rstrip("/")
    try:
        r = requests.get(f"{base}/api/tags", timeout=5)
        r.raise_for_status()
        data = r.json()
    except requests.RequestException as exc:
        raise RuntimeError(
            "Cannot connect to Ollama. Install and start Ollama, then run `ollama pull llama3.2`."
        ) from exc
    except Exception as exc:
        raise RuntimeError(f"Ollama returned an invalid model list: {exc}") from exc

    models = []
    for item in data.get("models", []) if isinstance(data, dict) else []:
        name = item.get("name") if isinstance(item, dict) else None
        if name:
            models.append(str(name))
    return models


def choose_ollama_model(preferred_model: str = "", base_url: str = OLLAMA_DEFAULT_BASE_URL) -> str:
    models = list_ollama_models(base_url)
    if preferred_model:
        matched = _match_ollama_model(preferred_model, models)
        if matched:
            return matched
        raise RuntimeError(
            f"Ollama model `{preferred_model}` is not installed. Run `ollama pull {preferred_model}`."
        )
    if not models:
        raise RuntimeError("No Ollama models installed. Run `ollama pull llama3.2` first.")

    for candidate in OLLAMA_FALLBACK_MODELS:
        for installed in models:
            if installed == candidate or installed.startswith(candidate + ":"):
                return installed
    return models[0]


def analyze_response_with_ollama(
    context_json: str,
    model: str = "",
    base_url: str = OLLAMA_DEFAULT_BASE_URL,
) -> tuple[str, str]:
    """Analyze a response through a local Ollama model. Returns (report, model_used)."""
    base = base_url.rstrip("/")
    model_used = choose_ollama_model(model, base)
    prompt = (
        "Respond in Vietnamese. Use clear, practical Vietnamese for developers. "
        "You are a senior API debugging assistant. Analyze the redacted HTTP "
        "request/response context below. Identify likely backend/client bugs, bad input, "
        "auth issues, schema mismatches, timeout/rate-limit clues, and suspicious response "
        "content. If the response appears healthy, say that clearly. Keep the answer concise "
        "with sections: Summary, Evidence, Likely cause, Suggested fixes, Next checks. "
        "Do not reveal or reconstruct secrets.\n\n"
        f"{context_json}"
    )
    payload = {
        "model": model_used,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": 0.2,
            "num_predict": 1000,
        },
    }
    try:
        r = requests.post(f"{base}/api/generate", json=payload, timeout=180)
    except requests.RequestException as exc:
        raise RuntimeError(f"Could not reach Ollama generate API: {exc}") from exc

    raw_text = r.text or ""
    try:
        data = r.json()
    except Exception as exc:
        raise RuntimeError(f"Ollama returned invalid JSON: {raw_text[:500] or exc}") from exc
    if r.status_code >= 400:
        msg = data.get("error") if isinstance(data, dict) else raw_text[:500]
        raise RuntimeError(f"Ollama API error ({r.status_code}): {msg or 'empty error body'}")
    text = data.get("response", "") if isinstance(data, dict) else ""
    if not str(text).strip():
        raise RuntimeError(f"Ollama returned no analysis text. Response body: {raw_text[:500]}")
    return str(text).strip(), model_used


# ──────────────────────────────────────────────
# Environment variable substitution
# ──────────────────────────────────────────────
def apply_env(text: str, env: dict[str, str]) -> str:
    """Thay thế {{key}} bằng giá trị trong env dict."""
    for k, v in env.items():
        text = text.replace("{{" + str(k) + "}}", "" if v is None else str(v))
    return text


# ──────────────────────────────────────────────
# Pre-request script
# ──────────────────────────────────────────────
def has_executable_code(script: str) -> bool:
    """True nếu script có ít nhất 1 dòng không phải comment/dòng trống."""
    return any(
        line.strip() and not line.strip().startswith("#")
        for line in (script or "").splitlines()
    )


def run_pre_script(script: str, env: dict[str, str]) -> tuple[dict, list[str]]:
    """
    Chạy pre-request Python script.

    LƯU Ý: đây KHÔNG phải sandbox — script chạy với toàn quyền của app
    (có thể import os, đọc/ghi file...). Chỉ chạy script do chính bạn viết
    hoặc đã đọc kỹ, đặc biệt khi import collection/scenario của người khác.

    API dùng được trong script:
      set_env('key', 'value')  → set biến env
      env['key'] = 'value'     → cách khác
      log('message')           → ghi vào Script Log tab
      requests / json / re     → thư viện sẵn có

    Returns:
        (env_updated, logs)
    """
    logs      = []
    local_env = dict(env)

    def set_env(k: str, v: Any) -> None:
        local_env[k] = str(v)
        logs.append(f"✓ set_env({k!r}, {str(v)[:40]!r})")

    def log(msg: Any) -> None:
        logs.append(f"  {msg}")

    sandbox = {
        "env":      local_env,
        "set_env":  set_env,
        "log":      log,
        "requests": requests,
        "json":     json,
        "re":       re,
    }
    try:
        exec(compile(script, "<pre-request>", "exec"), sandbox)
        # Script có thể gán lại `env = {...}` hoặc `env['n'] = 5`; giá trị phải là str
        # để apply_env() không lỗi TypeError.
        for k, v in dict(sandbox.get("env") or {}).items():
            local_env[str(k)] = "" if v is None else str(v)
        logs.insert(0, "✅ Script chạy thành công")
    except Exception as e:
        logs.insert(0, f"❌ Script lỗi: {e}")

    return local_env, logs


# ──────────────────────────────────────────────
# Curl parser
# ──────────────────────────────────────────────
DEFAULT_TIMEOUT = 30

_SHELL_WHITESPACE = " \t\r\n"
_DQ_ESCAPABLE = '"\\$`\n'   # ký tự mà `\` escape được bên trong "..." (POSIX shell)
_ANSI_C_SIMPLE = {
    "n": "\n", "t": "\t", "r": "\r", "a": "\a", "b": "\b", "f": "\f",
    "v": "\v", "e": "\x1b", "E": "\x1b", "\\": "\\", "'": "'", '"': '"', "?": "?",
}

# Short options của curl nhận giá trị (ví dụ -XPOST, -H 'A: b', -sSL không có giá trị)
_SHORT_WITH_VALUE = set("AbcCdDeEFHKmoPQrtTuUwxXyYz")
# Long options nhận giá trị. Những option app không dùng vẫn phải nằm ở đây để
# giá trị của chúng không bị hiểu nhầm thành URL (vd: `curl -o out.txt https://...`).
_LONG_WITH_VALUE = {
    "--request", "--header", "--data", "--data-raw", "--data-ascii", "--data-binary",
    "--data-urlencode", "--json", "--form", "--form-string", "--user-agent", "--user",
    "--url", "--max-time", "--oauth2-bearer", "--cookie", "--referer",
    "--connect-timeout", "--output", "--write-out", "--proxy", "--proxy-user",
    "--cacert", "--capath", "--cert", "--key", "--cert-type", "--key-type", "--pass",
    "--resolve", "--connect-to", "--cookie-jar", "--range", "--retry", "--retry-delay",
    "--retry-max-time", "--upload-file", "--config", "--limit-rate", "--speed-limit",
    "--speed-time", "--interface", "--dns-servers", "--max-redirs", "--proto",
    "--proto-redir", "--keepalive-time", "--unix-socket", "--abstract-unix-socket",
    "--ciphers", "--noproxy", "--preproxy", "--socks4", "--socks4a", "--socks5",
    "--socks5-hostname", "--time-cond", "--expect100-timeout", "--trace",
    "--trace-ascii", "--stderr", "--dump-header", "--continue-at", "--local-port",
    "--request-target", "--aws-sigv4", "--url-query", "--variable", "--header-file",
    "--max-filesize", "--happy-eyeballs-timeout-ms", "--telnet-option", "--quote",
}
_SHORT_TO_LONG = {
    "-X": "--request", "-H": "--header", "-d": "--data", "-F": "--form",
    "-A": "--user-agent", "-u": "--user", "-m": "--max-time", "-b": "--cookie",
    "-e": "--referer", "-k": "--insecure", "-L": "--location", "-G": "--get",
    "-I": "--head",
}
_DATA_OPTIONS = {"--data", "--data-ascii", "--data-raw", "--data-binary", "--data-urlencode", "--json"}


def _decode_ansi_c(raw: str) -> str:
    """Giải mã nội dung của bash ANSI-C quote $'...' (Chrome "Copy as cURL (bash)" dùng dạng này)."""
    out = bytearray()
    i = 0
    while i < len(raw):
        ch = raw[i]
        if ch != "\\" or i + 1 >= len(raw):
            out += ch.encode("utf-8")
            i += 1
            continue
        nxt = raw[i + 1]
        if nxt in _ANSI_C_SIMPLE:
            out += _ANSI_C_SIMPLE[nxt].encode("utf-8")
            i += 2
        elif nxt == "x" and (m := re.match(r"[0-9A-Fa-f]{1,2}", raw[i + 2:])):
            out.append(int(m.group(), 16))
            i += 2 + len(m.group())
        elif nxt in "uU" and (m := re.match(r"[0-9A-Fa-f]{1,%d}" % (4 if nxt == "u" else 8), raw[i + 2:])):
            code = min(int(m.group(), 16), 0x10FFFF)
            out += chr(code).encode("utf-8", "surrogatepass")
            i += 2 + len(m.group())
        elif nxt in "01234567":
            m = re.match(r"[0-7]{1,3}", raw[i + 1:])
            out.append(int(m.group(), 8) & 0xFF)
            i += 1 + len(m.group())
        else:
            out += ("\\" + nxt).encode("utf-8")
            i += 2
    return out.decode("utf-8", errors="replace")


def shell_split(text: str) -> list[str]:
    """
    Tách chuỗi theo quy tắc POSIX shell (giống bash), hỗ trợ thêm $'...'.

    Khác shlex.split: bên trong "..." chỉ \\" \\\\ \\$ \\` được escape (như bash),
    và hiểu được ANSI-C quoting mà Chrome DevTools sinh ra.
    """
    tokens: list[str] = []
    buf: list[str] = []
    in_token = False
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        if ch in _SHELL_WHITESPACE:
            if in_token:
                tokens.append("".join(buf))
                buf, in_token = [], False
            i += 1
            continue
        in_token = True
        if ch == "\\":
            if i + 1 < n:
                if text[i + 1] != "\n":   # backslash-newline = nối dòng
                    buf.append(text[i + 1])
                i += 2
            else:
                buf.append(ch)
                i += 1
        elif ch == "'":
            end = text.find("'", i + 1)
            if end < 0:
                raise ValueError("Thiếu dấu ' đóng")
            buf.append(text[i + 1:end])
            i = end + 1
        elif ch == '"':
            i += 1
            while True:
                if i >= n:
                    raise ValueError('Thiếu dấu " đóng')
                c = text[i]
                if c == '"':
                    i += 1
                    break
                if c == "\\" and i + 1 < n and text[i + 1] in _DQ_ESCAPABLE:
                    if text[i + 1] != "\n":
                        buf.append(text[i + 1])
                    i += 2
                    continue
                buf.append(c)
                i += 1
        elif ch == "$" and i + 1 < n and text[i + 1] == "'":
            j, raw = i + 2, []
            while True:
                if j >= n:
                    raise ValueError("Thiếu dấu ' đóng cho $'...'")
                c = text[j]
                if c == "\\" and j + 1 < n:
                    raw.append(text[j:j + 2])
                    j += 2
                    continue
                if c == "'":
                    j += 1
                    break
                raw.append(c)
                j += 1
            buf.append(_decode_ansi_c("".join(raw)))
            i = j
        else:
            buf.append(ch)
            i += 1
    if in_token:
        tokens.append("".join(buf))
    return tokens


def _normalize_curl_text(curl_string: str) -> str:
    text = re.sub(r'\\\s*\n\s*', ' ', curl_string or "")   # nối dòng bash
    text = re.sub(r'\^\s*\n\s*', ' ', text)                 # nối dòng cmd.exe
    text = text.strip()
    # Chrome "Copy as cURL (cmd)" escape mọi ký tự đặc biệt bằng ^ và bọc giá trị trong ^"...^"
    if re.search(r'(?<!\S)\^"', text):
        text = re.sub(r'\^(.)', r'\1', text)
    return text


def _iter_curl_options(args: list[str]):
    """Yield (option, value). option=None nghĩa là đối số vị trí (URL)."""
    i = 0
    positional_only = False
    while i < len(args):
        token = args[i]
        i += 1
        if positional_only or token == "-" or not token.startswith("-"):
            yield None, token
            continue
        if token == "--":
            positional_only = True
            continue
        if token.startswith("--"):
            name = token
            if name.startswith("--no-"):
                yield name, None
                continue
            if name in _LONG_WITH_VALUE:
                if i >= len(args):
                    raise ValueError(f"Option {name} thiếu giá trị")
                yield name, args[i]
                i += 1
            else:
                yield name, None
            continue
        # Short options: -sSL, -XPOST, -H 'A: b', -d@file.json
        pos = 1
        while pos < len(token):
            letter = token[pos]
            name = _SHORT_TO_LONG.get(f"-{letter}", f"-{letter}")
            if letter in _SHORT_WITH_VALUE:
                value = token[pos + 1:]
                if not value:
                    if i >= len(args):
                        raise ValueError(f"Option -{letter} thiếu giá trị")
                    value = args[i]
                    i += 1
                yield name, value
                break
            yield name, None
            pos += 1


def _read_data_file(path: str) -> bytes:
    if path == "-":
        raise ValueError("Không hỗ trợ đọc body từ stdin (@-)")
    try:
        with open(path, "rb") as fh:
            return fh.read()
    except OSError as exc:
        raise ValueError(f"Không đọc được file dữ liệu `{path}`: {exc}") from exc


def _data_part(option: str, value: str) -> str | bytes:
    """Chuyển 1 lần dùng -d/--data-*/--json thành nội dung body giống curl."""
    if option == "--data-urlencode":
        name, sep, content = value.partition("=")
        if not sep:
            if "@" in value:
                name, _, path = value.partition("@")
                content = _read_data_file(path).decode("utf-8", errors="replace")
                return f"{name}={quote(content, safe='')}" if name else quote(content, safe="")
            return quote(value, safe="")
        encoded = quote(content, safe="")
        return f"{name}={encoded}" if name else encoded
    if option == "--data-raw" or not value.startswith("@"):
        return value
    raw = _read_data_file(value[1:])
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw
    if option in ("--data", "--data-ascii"):
        # curl -d @file bỏ CR/LF trong file; --data-binary giữ nguyên.
        text = text.replace("\r", "").replace("\n", "")
    return text


def _join_data_parts(parts: list[str | bytes], separator: str) -> str | bytes:
    if len(parts) == 1:
        return parts[0]
    if any(isinstance(p, bytes) for p in parts):
        return separator.encode().join(p if isinstance(p, bytes) else p.encode("utf-8") for p in parts)
    return separator.join(parts)  # type: ignore[arg-type]


def _set_header(headers: dict[str, str], key: str, value: str) -> None:
    """Set header không phân biệt hoa/thường (header sau ghi đè header trước)."""
    for existing in [k for k in headers if k.lower() == key.lower()]:
        del headers[existing]
    headers[key] = value


def _has_header(headers: dict[str, str], key: str) -> bool:
    return any(k.lower() == key.lower() for k in headers)


def parse_curl(curl_string: str) -> dict:
    """
    Parse chuỗi curl thành dict:
      method, url, headers, body, auth,
      verify_ssl, allow_redirects, timeout
    (thêm "body_file" khi body là file nhị phân đọc từ --data-binary @file)
    """
    try:
        tokens = shell_split(_normalize_curl_text(curl_string))
    except ValueError as e:
        raise ValueError(f"Không thể parse curl: {e}") from e

    if not tokens or tokens[0].lower() not in ("curl", "curl.exe"):
        raise ValueError("Chuỗi phải bắt đầu bằng 'curl'")

    r: dict[str, Any] = {
        "method": None, "url": None, "headers": {}, "body": None,
        "auth": None, "verify_ssl": True, "allow_redirects": True,
        "timeout": DEFAULT_TIMEOUT,
    }
    data_parts: list[str | bytes] = []
    data_options: list[str] = []
    data_files: list[str] = []
    form: dict[str, str] = {}
    use_get = False
    use_head = False

    for opt, value in _iter_curl_options(tokens[1:]):
        if opt is None:
            if r["url"] is None:
                r["url"] = value
        elif opt == "--request":
            r["method"] = value.upper()
        elif opt == "--header":
            if value.startswith("@"):
                continue  # header file: không hỗ trợ
            if ":" in value:
                k, _, v = value.partition(":")
                if k.strip() and v.strip():
                    _set_header(r["headers"], k.strip(), v.strip())
            elif value.endswith(";") and value[:-1].strip():
                _set_header(r["headers"], value[:-1].strip(), "")   # `-H 'X-Empty;'`
        elif opt in _DATA_OPTIONS:
            data_parts.append(_data_part(opt, value))
            data_options.append(opt)
            if opt not in ("--data-raw", "--data-urlencode") and value.startswith("@"):
                data_files.append(value[1:])
            if opt == "--json":
                if not _has_header(r["headers"], "Content-Type"):
                    r["headers"]["Content-Type"] = "application/json"
                if not _has_header(r["headers"], "Accept"):
                    r["headers"]["Accept"] = "application/json"
        elif opt in ("--form", "--form-string"):
            k, _, v = value.partition("=")
            form[k] = v
        elif opt == "--user-agent":
            _set_header(r["headers"], "User-Agent", value)
        elif opt == "--user":
            user, _, password = value.partition(":")
            r["auth"] = (user, password)
        elif opt == "--oauth2-bearer":
            _set_header(r["headers"], "Authorization", f"Bearer {value}")
        elif opt == "--cookie":
            if "=" in value:   # không có "=" nghĩa là tên file cookie → bỏ qua
                existing = next((v for k, v in r["headers"].items() if k.lower() == "cookie"), "")
                _set_header(r["headers"], "Cookie", f"{existing}; {value}" if existing else value)
        elif opt == "--referer":
            referer = value.replace(";auto", "")
            if referer:
                _set_header(r["headers"], "Referer", referer)
        elif opt == "--insecure":
            r["verify_ssl"] = False
        elif opt == "--location":
            r["allow_redirects"] = True
        elif opt == "--url":
            r["url"] = value
        elif opt == "--max-time":
            try:
                r["timeout"] = float(value)
            except ValueError:
                pass
        elif opt == "--get":
            use_get = True
        elif opt == "--head":
            use_head = True
        # Các option khác (-s, -v, --compressed, -o file...) không ảnh hưởng request.

    if r["url"] is None:
        raise ValueError("Không tìm thấy URL trong chuỗi curl")

    if form and data_parts:
        raise ValueError("Không thể dùng -d/--data cùng với -F/--form trong một request")
    if form:
        r["body"] = form
    elif data_parts:
        separator = "" if all(o == "--json" for o in data_options) else "&"
        body = _join_data_parts(data_parts, separator)
        if use_get:
            text = body.decode("utf-8", errors="replace") if isinstance(body, bytes) else body
            r["url"] += ("&" if "?" in r["url"] else "?") + text
        else:
            r["body"] = body
            if isinstance(body, bytes) and len(data_files) == 1 and len(data_parts) == 1:
                r["body_file"] = data_files[0]

    if r["method"] is None:
        if use_head:
            r["method"] = "HEAD"
        elif use_get:
            r["method"] = "GET"
        else:
            r["method"] = "POST" if r["body"] is not None else "GET"
    return r


# ──────────────────────────────────────────────
# HTTP executor
# ──────────────────────────────────────────────
def _split_form_value(value: str) -> tuple[str, dict[str, str]]:
    """'file.png;type=image/png;filename=a.png' → ('file.png', {'type':..., 'filename':...})."""
    path, *params = value.split(";")
    options: dict[str, str] = {}
    for param in params:
        key, sep, val = param.partition("=")
        if sep:
            options[key.strip().lower()] = val.strip().strip('"')
    return path.strip().strip('"'), options


def _build_multipart(form: dict, opened: list) -> list[tuple[str, tuple]]:
    """-F name=value → field thường; name=@file → upload file; name=<file → field lấy nội dung file."""
    parts: list[tuple[str, tuple]] = []
    for name, raw in form.items():
        value = "" if raw is None else str(raw)
        if value.startswith("@"):
            path, options = _split_form_value(value[1:])
            fh = open(path, "rb")
            opened.append(fh)
            filename = options.get("filename") or os.path.basename(path)
            if options.get("type"):
                parts.append((str(name), (filename, fh, options["type"])))
            else:
                parts.append((str(name), (filename, fh)))
        elif value.startswith("<"):
            path, options = _split_form_value(value[1:])
            with open(path, "rb") as fh:
                content = fh.read()
            if options.get("type"):
                parts.append((str(name), (None, content, options["type"])))
            else:
                parts.append((str(name), (None, content)))
        else:
            parts.append((str(name), (None, value)))
    return parts


def execute_request(parsed: dict) -> tuple:
    """Gửi HTTP request, trả về (response, elapsed_ms)."""
    kwargs: dict[str, Any] = {
        "headers": parsed.get("headers") or {},
        "auth":    parsed.get("auth"),
        "verify":  parsed.get("verify_ssl", True),
        "allow_redirects": parsed.get("allow_redirects", True),
        "timeout": parsed.get("timeout", DEFAULT_TIMEOUT),
    }
    body = parsed.get("body")
    opened: list = []
    try:
        if isinstance(body, dict):
            kwargs["files"] = _build_multipart(body, opened)
        elif isinstance(body, str):
            # Gửi đúng từng byte người dùng nhập (UTF-8), không parse/serialize lại JSON.
            # (requests encode str body bằng latin-1 → lỗi với tiếng Việt / emoji.)
            kwargs["data"] = body.encode("utf-8")
        elif isinstance(body, bytes):
            kwargs["data"] = body

        t0 = time.perf_counter()
        resp = requests.request(parsed["method"], parsed["url"], **kwargs)
        return resp, (time.perf_counter() - t0) * 1000
    finally:
        for fh in opened:
            fh.close()


# ──────────────────────────────────────────────
# Response decoder
# ──────────────────────────────────────────────
def decode_response(resp, auto_decode: bool = True) -> tuple[str, str]:
    """
    Decode response body theo thứ tự ưu tiên:
      1. charset từ Content-Type header
      2. Auto-detect qua charset-normalizer / chardet
      3. Fallback UTF-8

    Returns:
        (body_text, encoding_info)
    """
    if not auto_decode:
        return resp.content.decode("latin-1"), "raw (no decode)"

    ct_header     = resp.headers.get("Content-Type", "")
    charset_match = re.search(r'charset=([^\s;]+)', ct_header, re.I)

    if charset_match:
        charset = charset_match.group(1).strip().strip("\"'")   # charset="utf-8"
        enc_info = f"{charset}  (từ Content-Type header)"
        try:
            return resp.content.decode(charset, errors="replace"), enc_info
        except (LookupError, UnicodeDecodeError):
            return resp.content.decode("utf-8", errors="replace"), enc_info + " → fallback utf-8"

    if HAS_DETECT and resp.content:
        result = _detect_encoding(resp.content)
        best = result.best() if callable(getattr(result, "best", None)) else getattr(result, "best", None)
        charset = getattr(best, "encoding", None) or "utf-8"
        enc_info = f"{charset}  (auto-detected)"
        try:
            return resp.content.decode(charset or "utf-8", errors="replace"), enc_info
        except (LookupError, UnicodeDecodeError):
            return resp.content.decode("utf-8", errors="replace"), "utf-8  (fallback)"

    return resp.content.decode("utf-8", errors="replace"), \
           "utf-8  (fallback — charset-normalizer not installed)"


# ──────────────────────────────────────────────
# Beautify curl body
# ──────────────────────────────────────────────
_BEAUTIFY_DATA_RE = re.compile(
    r"(?<!\S)(?P<flag>-d|--data|--data-raw|--data-binary|--data-ascii|--json)(?P<sep>\s+)"
    r"(?P<arg>'[^']*'(?:\\''[^']*')*|\"(?:[^\"\\]|\\.)*\")",
    re.DOTALL,
)


def _shell_quote_like(value: str, quote_char: str) -> str:
    """Quote lại giá trị theo đúng kiểu quote ban đầu, an toàn với bash."""
    if quote_char == "'":
        return "'" + value.replace("'", "'\\''") + "'"
    escaped = (value.replace("\\", "\\\\").replace('"', '\\"')
               .replace("$", "\\$").replace("`", "\\`"))
    return f'"{escaped}"'


def beautify_curl_body(curl_str: str) -> str:
    """
    Tìm -d / --data-raw / --json trong curl string.
    Nếu body là JSON hợp lệ → format indent=2.
    Trả về curl string đã format (quote lại đúng chuẩn shell, kể cả khi JSON có dấu ').
    """
    def _fmt(m: re.Match) -> str:
        raw = m.group("arg")
        try:
            value = shell_split(raw)[0]
            pretty = json.dumps(json.loads(value), indent=2, ensure_ascii=False)
        except Exception:
            return m.group(0)
        return f"{m.group('flag')}{m.group('sep')}{_shell_quote_like(pretty, raw[0])}"

    return _BEAUTIFY_DATA_RE.sub(_fmt, curl_str)
