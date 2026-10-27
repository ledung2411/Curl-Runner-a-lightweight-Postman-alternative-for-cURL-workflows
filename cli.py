#!/usr/bin/env python3
"""
cli.py — Chạy Curl Runner không cần giao diện (terminal, CI/CD).

Ví dụ:
  python cli.py run --scenario "Checkout Smoke" --env QA --report junit.xml
  python cli.py run --file ci/scenarios.json --env-file ci/envs.json --env QA --data users.csv
  python cli.py run --collection "Smoke" --env QA
  python cli.py run --from postman_collection.json --env-file postman_env.json
  python cli.py import my-bruno-collection/
  python cli.py request "curl https://api.test/health" --assert "status == 200"
  python cli.py list scenarios

Exit code: 0 = tất cả PASS · 1 = có step FAIL/không chạy · 2 = lỗi cấu hình/tham số.
Biến lấy theo thứ tự ưu tiên tăng dần: environment < CURLRUNNER_VAR_<TÊN> (biến môi trường OS)
< dòng dữ liệu --data < --var KEY=VALUE.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from pathlib import Path
from typing import Any

if sys.version_info < (3, 10):
    sys.exit("Curl Runner cần Python 3.10 trở lên (đang chạy Python %d.%d)." % sys.version_info[:2])

import store  # noqa: E402
from importers import import_path, merge_import
from core import apply_env, decode_response, execute_request, parse_curl
from scenario_engine import evaluate_assertions, extract_values, run_scenario, runnable_steps
from scenario_report import build_scenario_report, export_scenario_report

EXIT_OK, EXIT_FAILED, EXIT_USAGE = 0, 1, 2
ENV_VAR_PREFIX = "CURLRUNNER_VAR_"


class CliError(Exception):
    """Lỗi cấu hình/tham số → exit code 2."""


# ──────────────────────────────────────────────
# Loading inputs
# ──────────────────────────────────────────────
def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError as exc:
        raise CliError(f"Không tìm thấy file: {path}") from exc
    except ValueError as exc:
        raise CliError(f"File JSON không hợp lệ ({path}): {exc}") from exc


def _with_step_ids(scenario: dict) -> dict:
    scenario = dict(scenario)
    steps = []
    for idx, step in enumerate(scenario.get("steps", []) or [], 1):
        step = dict(step)
        step["id"] = str(step.get("id") or f"step{idx}")
        steps.append(step)
    scenario["steps"] = steps
    scenario.setdefault("name", "Untitled Scenario")
    scenario["id"] = str(scenario.get("id") or scenario["name"])
    return scenario


def load_scenarios(path: Path) -> list[dict]:
    """Nhận scenarios.json của app (list), 1 scenario (dict có steps) hoặc {"scenarios": [...]}."""
    data = _load_json(path)
    if isinstance(data, dict) and isinstance(data.get("scenarios"), list):
        data = data["scenarios"]
    elif isinstance(data, dict) and "steps" in data:
        data = [data]
    if not isinstance(data, list):
        raise CliError(f"{path} không chứa danh sách scenario")
    return [_with_step_ids(s) for s in data if isinstance(s, dict)]


def _find_by_name(items: list[dict], wanted: str, kind: str) -> dict:
    for item in items:
        if wanted in (item.get("name"), item.get("id")):
            return item
    for item in items:
        if str(item.get("name", "")).lower() == wanted.lower():
            return item
    names = "\n".join(f"  - {i.get('name')}" for i in items) or "  (trống)"
    raise CliError(f"Không tìm thấy {kind} `{wanted}`. Danh sách:\n{names}")


def select_scenarios(scenarios: list[dict], names: list[str], run_all: bool) -> list[dict]:
    if run_all:
        return scenarios
    if not names:
        if len(scenarios) == 1:
            return scenarios
        listing = "\n".join(f"  - {s.get('name')}" for s in scenarios) or "  (trống)"
        raise CliError(f"Có {len(scenarios)} scenario, hãy chọn bằng --scenario <tên> hoặc --all:\n{listing}")
    return [_find_by_name(scenarios, name, "scenario") for name in names]


def collection_to_scenario(name: str, items: list[dict]) -> dict:
    """Collection = scenario tuần tự: mỗi request 1 group, dùng Tests (assertions) đã lưu của request."""
    steps = []
    for order, item in enumerate(items, 1):
        steps.append({
            "id": str(item.get("id") or f"req{order}"),
            "name": item.get("name") or f"Request {order}",
            "group": order,
            "enabled": True,
            "curl": item.get("curl", ""),
            "extractors": item.get("extractors", ""),
            "assertions": item.get("assertions", ""),
        })
    return {"id": f"collection:{name}", "name": name, "steps": steps}


def _str_map(data: dict) -> dict[str, str]:
    return {str(k): "" if v is None else str(v) for k, v in data.items()}


def load_environment(env_file: Path | None, env_name: str | None) -> dict[str, str]:
    """
    environments.json của app ({"QA": {...}}), file phẳng ({"base_url": ...})
    hoặc file export environment của Postman ({"values": [{key, value, enabled}]}).
    """
    if env_file is None:
        if not env_name:
            return {}
        env_file = store.ENV_FILE
    data = _load_json(env_file)
    if isinstance(data, dict) and isinstance(data.get("values"), list):
        return {
            str(v.get("key")): str(v.get("value", ""))
            for v in data["values"]
            if isinstance(v, dict) and v.get("key") and v.get("enabled", True)
        }
    if not isinstance(data, dict):
        raise CliError(f"{env_file} không phải file environment hợp lệ")
    if data and all(isinstance(v, dict) for v in data.values()):
        if env_name is None:
            if len(data) != 1:
                raise CliError(f"{env_file} có nhiều environment, hãy chọn --env: {', '.join(data)}")
            env_name = next(iter(data))
        return _str_map(_find_env(data, env_name))
    return _str_map(data)


def _find_env(envs: dict[str, dict], wanted: str) -> dict:
    if wanted in envs:
        return envs[wanted]
    for name, values in envs.items():
        if name.lower() == wanted.lower():
            return values
    raise CliError(f"Không có environment `{wanted}`. Có: {', '.join(envs) or '(trống)'}")


def parse_vars(pairs: list[str]) -> dict[str, str]:
    out = {}
    for pair in pairs or []:
        key, sep, value = pair.partition("=")
        if not sep or not key.strip():
            raise CliError(f"--var phải có dạng KEY=VALUE: {pair}")
        out[key.strip()] = value
    return out


def os_env_vars(environ: dict[str, str] | None = None) -> dict[str, str]:
    """CURLRUNNER_VAR_token=abc → biến {{token}} (tiện cho secret trên CI)."""
    environ = os.environ if environ is None else environ
    return {k[len(ENV_VAR_PREFIX):]: v for k, v in environ.items()
            if k.startswith(ENV_VAR_PREFIX) and len(k) > len(ENV_VAR_PREFIX)}


def load_data_rows(path: Path) -> list[dict[str, str]]:
    """File dữ liệu cho data-driven run: CSV có header hoặc JSON list các object."""
    if path.suffix.lower() == ".csv":
        try:
            with path.open(encoding="utf-8-sig", newline="") as fh:
                rows = [_str_map({k: v for k, v in row.items() if k}) for row in csv.DictReader(fh)]
        except FileNotFoundError as exc:
            raise CliError(f"Không tìm thấy file: {path}") from exc
    else:
        data = _load_json(path)
        if not isinstance(data, list) or not all(isinstance(r, dict) for r in data):
            raise CliError(f"{path} phải là JSON list các object")
        rows = [_str_map(r) for r in data]
    if not rows:
        raise CliError(f"{path} không có dòng dữ liệu nào")
    return rows


# ──────────────────────────────────────────────
# Output
# ──────────────────────────────────────────────
def _print(*parts: Any, err: bool = False) -> None:
    print(*parts, file=sys.stderr if err else sys.stdout, flush=True)


def _step_printer(verbose: bool):
    def on_event(kind: str, payload: dict) -> None:
        if kind == "step_result":
            step, result = payload["step"], payload["result"]
            mark = "PASS" if result["ok"] else "FAIL"
            timing = f" · {result['elapsed']}" if result.get("elapsed") else ""
            _print(f"  {mark}  [G{step.get('group', 1)}] {step.get('name', 'Step')} · {result['status']}{timing}")
            if not result["ok"] or verbose:
                for line in result.get("assertions", []):
                    _print(f"        {line}")
                if result.get("error"):
                    _print(f"        {result['error']}")
        elif kind == "group_stop":
            _print(f"  Group {payload['group']} lỗi → dừng scenario (dùng --no-stop-on-fail để chạy tiếp)")
    return on_event


# ──────────────────────────────────────────────
# Commands
# ──────────────────────────────────────────────
def _import_or_fail(path: str):
    try:
        return import_path(path)
    except (OSError, ValueError) as exc:
        raise CliError(str(exc)) from exc


def cmd_run(args: argparse.Namespace) -> int:
    targets: list[dict] = []
    if args.source:
        imported = _import_or_fail(args.source)
        for note in imported.notes:
            _print(f"  ! {note}", err=True)
        available = [{"name": name, "items": items} for name, items in imported.collections.items()]
        chosen = [_find_by_name(available, n, "collection") for n in args.collection] if args.collection else available
        for match in chosen:
            targets.append(_with_step_ids(collection_to_scenario(match["name"], match["items"])))
    elif args.collection:
        collections = _load_json(Path(args.collections_file) if args.collections_file else store.COLL_FILE)
        if not isinstance(collections, dict):
            raise CliError("File collections không hợp lệ")
        for name in args.collection:
            items = [{"name": key, "items": value} for key, value in collections.items()]
            match = _find_by_name(items, name, "collection")
            targets.append(_with_step_ids(collection_to_scenario(match["name"], match["items"])))
    if args.scenario or args.all or not (args.collection or args.source):
        scenarios = load_scenarios(Path(args.file) if args.file else store.SCEN_FILE)
        targets.extend(select_scenarios(scenarios, args.scenario or [], args.all))

    base_env = load_environment(Path(args.env_file) if args.env_file else None, args.env)
    base_env.update(os_env_vars())
    cli_vars = parse_vars(args.var)
    rows = load_data_rows(Path(args.data)) if args.data else [{}]

    multi = len(targets) > 1 or len(rows) > 1
    report_steps: list[dict] = []
    report_results: dict[str, dict] = {}
    total_passed = total_failed = total_not_run = 0

    for scenario in targets:
        for iteration, row in enumerate(rows, 1):
            label = scenario["name"] + (f" [#{iteration}]" if len(rows) > 1 else "")
            env = {**base_env, **row, **cli_vars}
            steps = runnable_steps(scenario)
            _print(f"\n▶ {label} ({len(steps)} step)")
            summary = run_scenario(
                steps, env,
                stop_on_fail=not args.no_stop_on_fail,
                on_event=_step_printer(args.verbose),
                insecure=args.insecure,
            )
            not_run = len(steps) - len(summary["results"])
            total_passed += summary["passed"]
            total_failed += summary["failed"]
            total_not_run += not_run
            extra = f", {not_run} không chạy" if not_run else ""
            _print(f"  → {summary['passed']} passed, {summary['failed']} failed{extra}")
            if not steps:
                _print("  (scenario không có step nào đang bật)")
                total_not_run += 1

            prefix = f"{label} › " if multi else ""
            for step in scenario["steps"]:
                rid = f"{scenario['id']}#{iteration}:{step['id']}" if multi else step["id"]
                report_steps.append({**step, "id": rid, "name": prefix + str(step.get("name", "Step"))})
                if step["id"] in summary["results"]:
                    report_results[rid] = summary["results"][step["id"]]

    summary_text = f"{total_passed} passed, {total_failed} failed, {total_not_run} not run"
    _print(f"\n{'OK' if not (total_failed or total_not_run) else 'FAILED'}: {summary_text}")

    if args.report:
        title = targets[0]["name"] if len(targets) == 1 else f"Curl Runner ({len(targets)} scenarios)"
        report = build_scenario_report(
            {"name": title, "steps": report_steps}, report_results,
            environment=args.env or "", summary=summary_text,
        )
        for output in args.report:
            try:
                path = export_scenario_report(report, output)
            except (OSError, ValueError) as exc:
                raise CliError(f"Không ghi được report {output}: {exc}") from exc
            _print(f"Report: {path}")

    return EXIT_OK if not (total_failed or total_not_run) else EXIT_FAILED


def _read_curl_arg(args: argparse.Namespace) -> str:
    if args.curl_file:
        source = sys.stdin.read() if args.curl_file == "-" else Path(args.curl_file).read_text(encoding="utf-8")
        return source.strip()
    if not args.curl:
        raise CliError("Cần truyền lệnh curl hoặc --curl-file")
    curl = args.curl.strip()
    return curl if curl.lower().startswith("curl") else f"curl {curl}"


def cmd_request(args: argparse.Namespace) -> int:
    env = load_environment(Path(args.env_file) if args.env_file else None, args.env)
    env.update(os_env_vars())
    env.update(parse_vars(args.var))
    try:
        parsed = parse_curl(apply_env(_read_curl_arg(args), env))
    except (OSError, ValueError) as exc:
        raise CliError(str(exc)) from exc
    if args.insecure:
        parsed["verify_ssl"] = False

    try:
        resp, elapsed = execute_request(parsed)
    except Exception as exc:
        _print(f"ERROR: {exc}", err=True)
        return EXIT_FAILED
    body, _ = decode_response(resp, True)

    _print(f"{parsed['method']} {parsed['url']} → {resp.status_code} {resp.reason} · {elapsed:.0f} ms", err=True)
    if args.show in ("headers", "all"):
        for key, value in resp.headers.items():
            _print(f"{key}: {value}")
        if args.show == "all":
            _print("")
    if args.show in ("body", "all"):
        _print(body)

    ok = True
    try:
        if args.extract:
            values, _ = extract_values(apply_env("\n".join(args.extract), env), resp, body)
            for key, value in values.items():
                _print(f"extract {key}={value}", err=True)
        rules = apply_env("\n".join(args.assertion or []), env)
        ok, details = evaluate_assertions(rules, resp, body, elapsed)
    except ValueError as exc:
        _print(f"FAIL: {exc}", err=True)
        return EXIT_FAILED
    for line in details:
        _print(line, err=True)
    return EXIT_OK if ok else EXIT_FAILED


def cmd_import(args: argparse.Namespace) -> int:
    result = _import_or_fail(args.path)
    _print(f"Nguồn: {result.source} · {result.request_count} request · {len(result.environments)} environment")
    for note in result.notes:
        _print(f"  ! {note}")
    if args.dry_run:
        for name, items in result.collections.items():
            _print(f"\n[{name}]")
            for item in items:
                tests = " (có Tests)" if item.get("assertions") or item.get("extractors") else ""
                _print(f"  {item['method']:7} {item['name']}{tests}")
        return EXIT_OK
    collections = store.load_collections()
    environments = store.load_environments()
    created = merge_import(result, collections, environments)
    store.save_collections(collections)
    if result.environments:
        store.save_environments(environments)
    for line in created:
        _print(f"  + {line}")
    return EXIT_OK


def cmd_list(args: argparse.Namespace) -> int:
    if args.what == "scenarios":
        for scenario in load_scenarios(Path(args.file) if args.file else store.SCEN_FILE):
            steps = scenario.get("steps", [])
            enabled = sum(1 for s in steps if s.get("enabled", True))
            _print(f"{scenario['name']}  ({enabled}/{len(steps)} step bật)")
    elif args.what == "environments":
        envs = _load_json(Path(args.file) if args.file else store.ENV_FILE)
        for name, values in (envs.items() if isinstance(envs, dict) else []):
            _print(f"{name}  ({len(values) if isinstance(values, dict) else 0} biến)")
    else:
        collections = _load_json(Path(args.file) if args.file else store.COLL_FILE)
        for name, items in (collections.items() if isinstance(collections, dict) else []):
            _print(f"{name}  ({len(items)} request)")
    return EXIT_OK


# ──────────────────────────────────────────────
# Entry point
# ──────────────────────────────────────────────
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cli.py",
        description="Curl Runner CLI — chạy scenario/collection/curl không cần giao diện.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__.split("\n\n", 1)[1],
    )
    sub = parser.add_subparsers(dest="command", required=True)

    def add_env_options(p: argparse.ArgumentParser) -> None:
        p.add_argument("--env", help="Tên environment (trong environments.json hoặc --env-file)")
        p.add_argument("--env-file", help="File environment (app, file phẳng hoặc export của Postman)")
        p.add_argument("--var", action="append", default=[], metavar="KEY=VALUE",
                       help="Ghi đè/thêm biến (dùng nhiều lần)")
        p.add_argument("-k", "--insecure", action="store_true", help="Bỏ qua kiểm tra SSL")

    run = sub.add_parser("run", help="Chạy scenario hoặc collection")
    run.add_argument("-s", "--scenario", action="append", help="Tên hoặc id scenario (dùng nhiều lần)")
    run.add_argument("--all", action="store_true", help="Chạy tất cả scenario trong file")
    run.add_argument("--file", help="File scenarios (mặc định ~/.curl_runner/scenarios.json)")
    run.add_argument("-c", "--collection", action="append", help="Chạy collection như 1 scenario tuần tự")
    run.add_argument("--from", dest="source", metavar="PATH",
                     help="Chạy thẳng Postman collection / thư mục Bruno / HAR (không cần import)")
    run.add_argument("--collections-file", help="File collections (mặc định ~/.curl_runner/collections.json)")
    run.add_argument("--data", help="CSV/JSON: chạy lặp mỗi dòng 1 lần, cột = biến")
    run.add_argument("--report", action="append", metavar="PATH",
                     help="Xuất report .xml (JUnit) / .html / .csv / .json (dùng nhiều lần)")
    run.add_argument("--no-stop-on-fail", action="store_true", help="Group lỗi vẫn chạy tiếp group sau")
    run.add_argument("-v", "--verbose", action="store_true", help="In chi tiết assertion cả khi PASS")
    add_env_options(run)
    run.set_defaults(func=cmd_run)

    req = sub.add_parser("request", help="Gửi 1 lệnh curl (in body ra stdout)")
    req.add_argument("curl", nargs="?", help="Lệnh curl (hoặc chỉ URL)")
    req.add_argument("--curl-file", help="Đọc lệnh curl từ file ('-' = stdin)")
    req.add_argument("-a", "--assert", dest="assertion", action="append",
                     help="Assertion, vd: 'status == 200' (dùng nhiều lần). Mặc định: status 2xx/3xx")
    req.add_argument("-e", "--extract", action="append", help="Extractor, vd: 'token = json:$.data.token'")
    req.add_argument("--show", choices=("body", "headers", "all", "none"), default="body")
    add_env_options(req)
    req.set_defaults(func=cmd_request)

    imp = sub.add_parser("import", help="Import Postman / Bruno / HAR vào collections & environments")
    imp.add_argument("path", help="File .json/.har của Postman/HAR, file .bru hoặc thư mục Bruno")
    imp.add_argument("--dry-run", action="store_true", help="Chỉ xem trước, không ghi dữ liệu")
    imp.set_defaults(func=cmd_import)

    lst = sub.add_parser("list", help="Liệt kê scenarios / environments / collections")
    lst.add_argument("what", choices=("scenarios", "environments", "collections"))
    lst.add_argument("--file", help="Đọc từ file khác thay vì ~/.curl_runner")
    lst.set_defaults(func=cmd_list)
    return parser


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")   # console Windows không in được tiếng Việt
        except (AttributeError, ValueError):
            pass
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except CliError as exc:
        _print(f"Lỗi: {exc}", err=True)
        return EXIT_USAGE


if __name__ == "__main__":
    sys.exit(main())
