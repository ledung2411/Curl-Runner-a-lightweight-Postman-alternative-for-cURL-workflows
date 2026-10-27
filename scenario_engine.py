# scenario_engine.py - Rule engine (extract/assert) + scenario runner, không phụ thuộc UI.
# Dùng chung cho cửa sổ Scenario, Tests của từng request và CLI (cli.py).
from __future__ import annotations

import json
import re
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable

from core import apply_env, decode_response, execute_request, parse_curl

EventCallback = Callable[[str, dict], None]

_EXTRACTOR_RE = re.compile(r"^([A-Za-z_]\w*)\s*=\s*(json|header|regex)\s*:(.+)$", re.I)
_JSON_PATH_PART_RE = re.compile(r"\.([A-Za-z_][\w-]*)|\[(-?\d+)\]|\[\s*(['\"])(.*?)\3\s*\]")


# ──────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────
def active_rule_lines(text: str) -> list[str]:
    """Các dòng rule thật sự (bỏ dòng trống và comment #)."""
    out = []
    for line in (text or "").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            out.append(line)
    return out


def json_path_get(data: Any, path: str) -> Any:
    """JSONPath tối giản: $.a.b, $.items[0], $.items[-1], $['key with space']."""
    if not path.startswith("$"):
        raise ValueError(f"JSON path phải bắt đầu bằng `$`: {path}")
    cur = data
    rest = path[1:]
    pos = 0
    for m in _JSON_PATH_PART_RE.finditer(rest):
        if m.start() != pos:
            raise ValueError(f"JSON path không hợp lệ: {path}")
        pos = m.end()
        key, idx, quoted = m.group(1), m.group(2), m.group(4)
        if key is not None or quoted is not None:
            name = key if key is not None else quoted
            if not isinstance(cur, dict) or name not in cur:
                raise ValueError(f"Không tìm thấy JSON path `{path}`")
            cur = cur[name]
        else:
            i = int(idx)
            if not isinstance(cur, list) or not -len(cur) <= i < len(cur):
                raise ValueError(f"Không tìm thấy JSON path `{path}`")
            cur = cur[i]
    if pos != len(rest):
        raise ValueError(f"JSON path không hợp lệ: {path}")
    return cur


def strip_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        return value[1:-1]
    return value


def coerce_value(value: str) -> Any:
    lower = value.lower()
    if lower == "true":
        return True
    if lower == "false":
        return False
    if lower == "null":
        return None
    try:
        return int(value)
    except ValueError:
        pass
    try:
        return float(value)
    except ValueError:
        return value


def compare(actual: Any, op: str, expected: Any) -> bool:
    if op == "==":
        return actual == expected or str(actual) == str(expected)
    if op == "!=":
        return not compare(actual, "==", expected)
    try:
        left: Any = float(actual)
        right: Any = float(expected)
    except (TypeError, ValueError):
        left = str(actual)
        right = str(expected)
    if op == ">":
        return left > right
    if op == ">=":
        return left >= right
    if op == "<":
        return left < right
    if op == "<=":
        return left <= right
    return False


def _lower_headers(resp) -> dict[str, str]:
    return {str(k).lower(): str(v) for k, v in dict(resp.headers).items()}


def split_test_rules(text: str) -> tuple[str, str]:
    """Ô Tests của request chứa lẫn extractor (`ten = json:...`) và assertion → tách ra 2 phần."""
    extractors: list[str] = []
    assertions: list[str] = []
    for line in active_rule_lines(text):
        (extractors if _EXTRACTOR_RE.match(line) else assertions).append(line)
    return "\n".join(extractors), "\n".join(assertions)


def join_test_rules(extractors: str, assertions: str) -> str:
    return "\n".join(part for part in ((extractors or "").strip(), (assertions or "").strip()) if part)


# ──────────────────────────────────────────────
# Extractors / assertions
# ──────────────────────────────────────────────
def extract_values(rules: str, resp, body_text: str) -> tuple[dict[str, str], list[str]]:
    """
    Mỗi dòng: `ten_bien = json:$.data.token` | `header:X-Request-Id` | `regex:"id":"(\\w+)"`.
    Returns (biến đã extract, log).
    """
    extracted: dict[str, str] = {}
    logs: list[str] = []
    headers = _lower_headers(resp)
    body_json: Any = None
    json_loaded = False

    for line in active_rule_lines(rules):
        m = _EXTRACTOR_RE.match(line)
        if not m:
            raise ValueError(f"Extractor không hợp lệ: {line}")
        name, source, selector = m.group(1), m.group(2).lower(), m.group(3).strip()
        if source == "header":
            value = headers.get(selector.lower())
            if value is None:
                raise ValueError(f"Extractor `{name}` không tìm thấy header `{selector}`")
        elif source == "regex":
            hit = re.search(selector, body_text, re.S)
            if not hit:
                raise ValueError(f"Extractor `{name}` không match regex")
            value = hit.group(1) if hit.groups() else hit.group(0)
        else:
            if not json_loaded:
                body_json = json.loads(body_text)
                json_loaded = True
            value = json_path_get(body_json, selector)
        extracted[name] = str(value)
        logs.append(f"extract {name}={str(value)[:80]}")
    return extracted, logs


def evaluate_assertions(
    rules: str,
    resp,
    body_text: str,
    elapsed_ms: float | None = None,
) -> tuple[bool, list[str]]:
    """
    Đánh giá từng dòng assertion, dừng ở dòng FAIL đầu tiên.

    Cú pháp:
      status == 200 | status in 200, 201 | time < 800 (ms)
      body contains abc | body not_contains error
      header Content-Type contains json | header X-Id exists
      json $.ok == true | json $.items[0].id exists
    """
    lines = active_rule_lines(rules)
    if not lines:
        ok = 200 <= resp.status_code < 400
        return ok, [f"default status 2xx/3xx => {'PASS' if ok else 'FAIL'}"]

    details: list[str] = []
    body_json: Any = None
    json_loaded = False
    headers = _lower_headers(resp)

    def load_json() -> Any:
        nonlocal body_json, json_loaded
        if not json_loaded:
            body_json = json.loads(body_text)
            json_loaded = True
        return body_json

    for line in lines:
        if m := re.match(r"^status\s*(==|!=|>=|<=|>|<)\s*(\d+)$", line, re.I):
            passed = compare(int(resp.status_code), m.group(1), int(m.group(2)))
        elif m := re.match(r"^status\s+in\s+(.+)$", line, re.I):
            expected_codes = [int(x.strip()) for x in m.group(1).split(",") if x.strip()]
            passed = int(resp.status_code) in expected_codes
        elif m := re.match(r"^time\s*(==|!=|>=|<=|>|<)\s*(\d+(?:\.\d+)?)\s*(?:ms)?$", line, re.I):
            if elapsed_ms is None:
                raise ValueError(f"Không có thời gian phản hồi để kiểm tra: {line}")
            passed = compare(float(elapsed_ms), m.group(1), float(m.group(2)))
        elif m := re.match(r"^body\s+(contains|not_contains)\s+(.+)$", line, re.I):
            needle = strip_quotes(m.group(2).strip())
            contains = needle in body_text
            passed = contains if m.group(1).lower() == "contains" else not contains
        elif m := re.match(r"^header\s+(\S+)\s+exists$", line, re.I):
            passed = m.group(1).lower() in headers
        elif m := re.match(r"^header\s+(\S+)\s+(contains|==|!=)\s+(.+)$", line, re.I):
            actual = headers.get(m.group(1).lower(), "")
            expected = strip_quotes(m.group(3).strip())
            op = m.group(2).lower()
            passed = (expected in actual) if op == "contains" else compare(str(actual), op, expected)
        elif m := re.match(r"^json\s+(\S+)\s+exists$", line, re.I):
            try:
                json_path_get(load_json(), m.group(1))
                passed = True
            except ValueError:
                passed = False
        elif m := re.match(r"^json\s+(\S+)\s*(==|!=|>=|<=|>|<)\s*(.+)$", line, re.I):
            actual = json_path_get(load_json(), m.group(1))
            expected = coerce_value(strip_quotes(m.group(3).strip()))
            passed = compare(actual, m.group(2), expected)
        else:
            raise ValueError(f"Assertion không hợp lệ: {line}")
        details.append(f"{'PASS' if passed else 'FAIL'}: {line}")
        if not passed:
            return False, details
    return True, details


# ──────────────────────────────────────────────
# Scenario runner
# ──────────────────────────────────────────────
def safe_group(step: dict) -> int:
    try:
        return max(1, int(step.get("group", 1)))
    except (TypeError, ValueError):
        return 1


def run_step(step: dict, runtime_env: dict[str, str], insecure: bool = False) -> dict[str, Any]:
    """Chạy 1 step: apply env → gửi request → extract → assert. Không bao giờ raise."""
    name = step.get("name", "Step")
    try:
        curl = apply_env(step.get("curl", ""), runtime_env)
        parsed = parse_curl(curl)
        if insecure:
            parsed["verify_ssl"] = False
        resp, elapsed = execute_request(parsed)
        body_text, _ = decode_response(resp, True)
        # Rule cũng được thay biến: `json $.id == {{user_id}}`.
        extracts, extract_logs = extract_values(
            apply_env(step.get("extractors", ""), runtime_env), resp, body_text)
        ok, assertion_logs = evaluate_assertions(
            apply_env(step.get("assertions", ""), runtime_env), resp, body_text, elapsed)
        detail = "; ".join(assertion_logs + extract_logs)
        suffix = f" · {detail}" if detail else ""
        return {
            "ok": ok,
            "status": f"{resp.status_code} {resp.reason}",
            "elapsed": f"{elapsed:.0f} ms",
            "elapsed_ms": float(elapsed),
            "tag": "ok" if ok else "err",
            "message": f"{name}: {resp.status_code} {resp.reason} · {elapsed:.0f} ms{suffix}",
            "extracts": extracts,
            "extract_names": sorted(extracts),
            "assertions": assertion_logs,
            "error": "",
        }
    except Exception as exc:
        msg = str(exc) or repr(exc) or exc.__class__.__name__
        return {
            "ok": False,
            "status": "ERROR",
            "elapsed": "",
            "elapsed_ms": 0.0,
            "tag": "err",
            "message": f"{name}: ERROR · {msg}",
            "extracts": {},
            "extract_names": [],
            "assertions": [],
            "error": msg,
        }


def runnable_steps(scenario: dict) -> list[dict]:
    """Step đang bật và có curl."""
    return [
        dict(s) for s in scenario.get("steps", [])
        if s.get("enabled", True) and str(s.get("curl", "")).strip()
    ]


def run_scenario(
    steps: list[dict],
    runtime_env: dict[str, str],
    stop_on_fail: bool = True,
    stop_event: threading.Event | None = None,
    on_event: EventCallback | None = None,
    insecure: bool = False,
    max_workers: int = 16,
) -> dict[str, Any]:
    """
    Group chạy tuần tự theo số tăng dần; các step cùng group chạy song song.
    Biến extract được từ group N có hiệu lực cho group N+1 trở đi.

    on_event(kind, payload) được gọi từ thread runner với kind:
      group_start {group, steps} · step_result {step, result} ·
      group_extracts {group, names} · group_stop {group}
    """
    emit = on_event or (lambda _kind, _payload: None)
    env = dict(runtime_env)
    results: dict[str, dict] = {}
    passed = failed = 0
    stopped = False

    grouped: dict[int, list[dict]] = {}
    for step in steps:
        grouped.setdefault(safe_group(step), []).append(step)

    for group in sorted(grouped):
        if stop_event is not None and stop_event.is_set():
            stopped = True
            break
        group_steps = grouped[group]
        emit("group_start", {"group": group, "steps": group_steps})
        group_extracts: dict[str, str] = {}
        group_failed = False
        workers = max(1, min(len(group_steps), max_workers))
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {
                executor.submit(run_step, step, dict(env), insecure): step
                for step in group_steps
            }
            for future in as_completed(futures):
                step = futures[future]
                result = future.result()
                results[str(step.get("id", ""))] = result
                if result["ok"]:
                    passed += 1
                    group_extracts.update(result.get("extracts", {}))
                else:
                    failed += 1
                    group_failed = True
                emit("step_result", {"step": step, "result": result})
        if group_extracts:
            env.update(group_extracts)
            emit("group_extracts", {"group": group, "names": sorted(group_extracts)})
        if group_failed and stop_on_fail:
            emit("group_stop", {"group": group})
            stopped = True
            break

    if stop_event is not None and stop_event.is_set():
        stopped = True
    return {
        "results": results,
        "passed": passed,
        "failed": failed,
        "total": len(steps),
        "stopped": stopped,
        "env": env,
    }
