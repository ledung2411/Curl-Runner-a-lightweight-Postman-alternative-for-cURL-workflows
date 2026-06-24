# scenario_report.py - pure scenario report builders and exporters
from __future__ import annotations

import csv
import html
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
import xml.etree.ElementTree as ET

from core import parse_curl


SENSITIVE_QUERY_KEY = re.compile(
    r"token|key|secret|password|passwd|auth|signature|credential|session",
    re.IGNORECASE,
)


def _safe_preview(curl: str) -> tuple[str, str]:
    try:
        parsed = parse_curl(curl or "")
        method = str(parsed.get("method", ""))
        url = _redact_url(str(parsed.get("url", "")))
        return method, url
    except Exception:
        return "", ""


def _redact_url(url: str) -> str:
    if not url:
        return ""
    try:
        parts = urlsplit(url)
        host = parts.hostname or ""
        if parts.port:
            host = f"{host}:{parts.port}"
        query = urlencode([
            (key, "[REDACTED]" if SENSITIVE_QUERY_KEY.search(key) else value)
            for key, value in parse_qsl(parts.query, keep_blank_values=True)
        ])
        return urlunsplit((parts.scheme, host, parts.path, query, parts.fragment))
    except Exception:
        return url


def _elapsed_ms(result: dict[str, Any]) -> float:
    raw = result.get("elapsed_ms")
    if isinstance(raw, (int, float)):
        return max(0.0, float(raw))
    match = re.search(r"([0-9]+(?:\.[0-9]+)?)", str(result.get("elapsed", "")))
    return float(match.group(1)) if match else 0.0


def build_scenario_report(
    scenario: dict[str, Any],
    step_results: dict[str, dict[str, Any]],
    environment: str = "",
    summary: str = "",
) -> dict[str, Any]:
    steps: list[dict[str, Any]] = []
    counts = {"total": 0, "executed": 0, "passed": 0, "failed": 0, "skipped": 0}

    for order, step in enumerate(scenario.get("steps", []), 1):
        step_id = str(step.get("id", ""))
        result = dict(step_results.get(step_id, {}))
        enabled = bool(step.get("enabled", True))
        ok = result.get("ok")

        if not enabled:
            outcome = "SKIPPED"
        elif ok is True:
            outcome = "PASSED"
        elif ok is False:
            outcome = "FAILED"
        else:
            outcome = "NOT RUN"

        counts["total"] += 1
        if outcome == "PASSED":
            counts["passed"] += 1
            counts["executed"] += 1
        elif outcome == "FAILED":
            counts["failed"] += 1
            counts["executed"] += 1
        else:
            counts["skipped"] += 1

        method, url = _safe_preview(str(step.get("curl", "")))
        assertions = result.get("assertions", [])
        extract_names = result.get("extract_names", [])
        elapsed_ms = _elapsed_ms(result)
        steps.append({
            "order": order,
            "id": step_id,
            "group": int(step.get("group", 1) or 1),
            "enabled": enabled,
            "name": str(step.get("name", "Step")),
            "method": method,
            "url": url,
            "outcome": outcome,
            "status": str(result.get("status", "")),
            "elapsed_ms": elapsed_ms,
            "assertions": [str(item) for item in assertions] if isinstance(assertions, list) else [],
            "extract_names": [str(item) for item in extract_names] if isinstance(extract_names, list) else [],
            "error": str(result.get("error", "")),
        })

    return {
        "scenario": str(scenario.get("name", "Untitled Scenario")),
        "environment": environment,
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "summary": summary,
        "counts": counts,
        "duration_ms": sum(step["elapsed_ms"] for step in steps),
        "steps": steps,
    }


def export_scenario_report(report: dict[str, Any], output_path: str | Path) -> Path:
    path = Path(output_path)
    suffix = path.suffix.lower()
    if suffix in (".html", ".htm"):
        _write_html(report, path)
    elif suffix == ".csv":
        _write_csv(report, path)
    elif suffix == ".xml":
        _write_junit(report, path)
    else:
        raise ValueError("Report extension must be .html, .csv, or .xml")
    return path


def _write_html(report: dict[str, Any], path: Path) -> None:
    def esc(value: Any) -> str:
        return html.escape(str(value), quote=True)

    counts = report["counts"]
    rows = []
    for step in report["steps"]:
        assertions = "<br>".join(esc(item) for item in step["assertions"])
        extracts = ", ".join(esc(item) for item in step["extract_names"])
        detail = assertions or esc(step["error"])
        rows.append(
            f"<tr class='{step['outcome'].lower().replace(' ', '-')}'><td>{step['order']}</td>"
            f"<td>{step['group']}</td><td>{esc(step['name'])}</td><td>{esc(step['method'])}</td>"
            f"<td class='url'>{esc(step['url'])}</td><td><strong>{esc(step['outcome'])}</strong></td>"
            f"<td>{esc(step['status'])}</td><td>{step['elapsed_ms']:.0f} ms</td>"
            f"<td>{detail}</td><td>{extracts}</td></tr>"
        )

    document = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(report['scenario'])} - API Scenario Report</title>
<style>
body {{ margin: 0; font: 14px Segoe UI, Arial, sans-serif; color: #1f2937; background: #f5f7fb; }}
header {{ padding: 24px 32px; background: #fff; border-bottom: 1px solid #d8dee9; }}
h1 {{ margin: 0 0 6px; font-size: 24px; }}
.meta {{ color: #667085; }}
.stats {{ display: flex; gap: 20px; padding: 18px 32px; background: #fff; border-bottom: 1px solid #d8dee9; }}
.stat strong {{ display: block; font-size: 20px; }}
main {{ padding: 20px 32px 32px; overflow-x: auto; }}
table {{ width: 100%; border-collapse: collapse; background: #fff; }}
th, td {{ padding: 9px 10px; border: 1px solid #d8dee9; text-align: left; vertical-align: top; }}
th {{ background: #eef1f6; white-space: nowrap; }}
.passed td:nth-child(6) {{ color: #16794e; }}
.failed td:nth-child(6) {{ color: #c8323c; }}
.skipped td:nth-child(6), .not-run td:nth-child(6) {{ color: #667085; }}
.url {{ max-width: 420px; overflow-wrap: anywhere; }}
</style>
</head>
<body>
<header><h1>{esc(report['scenario'])}</h1>
<div class="meta">Environment: {esc(report['environment'] or '-')} &middot; Generated: {esc(report['generated_at'])}</div>
<div class="meta">{esc(report['summary'])}</div></header>
<section class="stats">
<div class="stat"><strong>{counts['total']}</strong>Total</div>
<div class="stat"><strong>{counts['passed']}</strong>Passed</div>
<div class="stat"><strong>{counts['failed']}</strong>Failed</div>
<div class="stat"><strong>{counts['skipped']}</strong>Skipped / Not run</div>
<div class="stat"><strong>{report['duration_ms']:.0f} ms</strong>Duration</div>
</section>
<main><table><thead><tr><th>#</th><th>Group</th><th>Step</th><th>Method</th><th>URL</th>
<th>Outcome</th><th>Status</th><th>Time</th><th>Assertions / Error</th><th>Extracted names</th></tr></thead>
<tbody>{''.join(rows)}</tbody></table></main>
</body></html>"""
    path.write_text(document, encoding="utf-8")


def _write_csv(report: dict[str, Any], path: Path) -> None:
    fields = [
        "order", "group", "name", "method", "url", "outcome", "status",
        "elapsed_ms", "assertions", "extract_names", "error",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for step in report["steps"]:
            row = {key: step.get(key, "") for key in fields}
            row["assertions"] = " | ".join(step["assertions"])
            row["extract_names"] = " | ".join(step["extract_names"])
            writer.writerow(row)


def _write_junit(report: dict[str, Any], path: Path) -> None:
    counts = report["counts"]
    suite = ET.Element("testsuite", {
        "name": str(report["scenario"]),
        "tests": str(counts["total"]),
        "failures": str(counts["failed"]),
        "skipped": str(counts["skipped"]),
        "time": f"{report['duration_ms'] / 1000:.3f}",
        "timestamp": str(report["generated_at"]),
    })
    properties = ET.SubElement(suite, "properties")
    ET.SubElement(properties, "property", {
        "name": "environment", "value": str(report.get("environment", "")),
    })

    for step in report["steps"]:
        case = ET.SubElement(suite, "testcase", {
            "classname": str(report["scenario"]),
            "name": str(step["name"]),
            "time": f"{step['elapsed_ms'] / 1000:.3f}",
        })
        if step["outcome"] == "FAILED":
            failure = ET.SubElement(case, "failure", {
                "message": step["error"] or step["status"] or "Scenario step failed",
            })
            failure.text = "\n".join(step["assertions"]) or step["error"]
        elif step["outcome"] in ("SKIPPED", "NOT RUN"):
            ET.SubElement(case, "skipped", {"message": step["outcome"]})

        output = {
            "method": step["method"],
            "url": step["url"],
            "status": step["status"],
            "assertions": step["assertions"],
            "extract_names": step["extract_names"],
        }
        ET.SubElement(case, "system-out").text = json.dumps(output, ensure_ascii=False)

    ET.indent(suite, space="  ")
    ET.ElementTree(suite).write(path, encoding="utf-8", xml_declaration=True)
