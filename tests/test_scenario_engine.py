from __future__ import annotations

import threading
import unittest

from http_fixture import LocalApi
from scenario_engine import (
    evaluate_assertions,
    extract_values,
    json_path_get,
    run_scenario,
)


class FakeResponse:
    def __init__(self, status: int = 200, headers: dict | None = None) -> None:
        self.status_code = status
        self.headers = headers or {"Content-Type": "application/json", "X-Request-Id": "req-9"}


BODY = '{"data": {"token": "abc", "count": 2, "tags": ["a", "b"], "full name": "Lê"}, "ok": true}'


class RuleTests(unittest.TestCase):
    def test_json_path_variants(self) -> None:
        data = {"data": {"items": [{"id": 1}, {"id": 2}], "full name": "Lê"}}
        self.assertEqual(json_path_get(data, "$.data.items[0].id"), 1)
        self.assertEqual(json_path_get(data, "$.data.items[-1].id"), 2)
        self.assertEqual(json_path_get(data, "$.data['full name']"), "Lê")
        with self.assertRaises(ValueError):
            json_path_get(data, "$.data.missing")
        with self.assertRaises(ValueError):
            json_path_get(data, "data.items")

    def test_extract_values(self) -> None:
        values, logs = extract_values(
            "token = json:$.data.token\nrid = header:x-request-id\ncount = regex:\"count\": (\\d+)",
            FakeResponse(), BODY,
        )
        self.assertEqual(values, {"token": "abc", "rid": "req-9", "count": "2"})
        self.assertEqual(len(logs), 3)
        with self.assertRaises(ValueError):
            extract_values("token = json:$.nope", FakeResponse(), BODY)

    def test_assertions_pass_and_stop_at_first_failure(self) -> None:
        ok, details = evaluate_assertions(
            "# comment\nstatus == 200\nstatus in 200, 201\ntime < 500\n"
            "header Content-Type contains json\nheader X-Request-Id exists\n"
            "body contains token\njson $.ok == true\njson $.data.count >= 2\n"
            "json $.data.tags[1] == 'b'\njson $.data.token exists",
            FakeResponse(), BODY, elapsed_ms=120,
        )
        self.assertTrue(ok, details)
        self.assertTrue(all(d.startswith("PASS") for d in details))

        ok, details = evaluate_assertions(
            "status == 200\njson $.data.missing exists\nbody contains never-checked",
            FakeResponse(), BODY,
        )
        self.assertFalse(ok)
        self.assertEqual(details, ["PASS: status == 200", "FAIL: json $.data.missing exists"])

    def test_default_assertion_and_invalid_rule(self) -> None:
        self.assertTrue(evaluate_assertions("", FakeResponse(204), "")[0])
        self.assertFalse(evaluate_assertions("", FakeResponse(404), "")[0])
        with self.assertRaises(ValueError):
            evaluate_assertions("status is great", FakeResponse(), BODY)
        with self.assertRaises(ValueError):
            evaluate_assertions("time < 100", FakeResponse(), BODY)  # no elapsed given


class RunScenarioTests(unittest.TestCase):
    def test_extracts_flow_to_next_group_and_events_fire(self) -> None:
        with LocalApi() as base:
            steps = [
                {"id": "login", "name": "Login", "group": 1, "curl": f"curl -X POST {base}/login",
                 "extractors": "token = json:$.data.token", "assertions": "status == 200"},
                {"id": "health", "name": "Health", "group": 1, "curl": "curl {{base}}/health",
                 "assertions": "json $.ok == true"},
                {"id": "me", "name": "Me", "group": 2,
                 "curl": "curl {{base}}/me -H 'Authorization: Bearer {{token}}'",
                 "assertions": "status == 200\njson $.user == dung"},
            ]
            events: list[str] = []
            summary = run_scenario(steps, {"base": base}, on_event=lambda kind, _p: events.append(kind))

        self.assertEqual((summary["passed"], summary["failed"], summary["total"]), (3, 0, 3))
        self.assertFalse(summary["stopped"])
        self.assertEqual(summary["env"]["token"], "tok-123")
        self.assertEqual(events.count("group_start"), 2)
        self.assertEqual(events.count("step_result"), 3)
        self.assertIn("group_extracts", events)

    def test_stop_on_fail_skips_later_groups(self) -> None:
        with LocalApi() as base:
            steps = [
                {"id": "a", "name": "Broken", "group": 1, "curl": f"curl {base}/explode"},
                {"id": "b", "name": "Later", "group": 2, "curl": f"curl {base}/health"},
            ]
            stopped = run_scenario(steps, {}, stop_on_fail=True)
            continued = run_scenario(steps, {}, stop_on_fail=False)

        self.assertEqual((stopped["passed"], stopped["failed"]), (0, 1))
        self.assertTrue(stopped["stopped"])
        self.assertNotIn("b", stopped["results"])
        self.assertEqual((continued["passed"], continued["failed"]), (1, 1))

    def test_stop_event_and_errors_are_reported_not_raised(self) -> None:
        stop = threading.Event()
        stop.set()
        summary = run_scenario([{"id": "x", "curl": "curl http://127.0.0.1:9/never"}], {}, stop_event=stop)
        self.assertTrue(summary["stopped"])
        self.assertEqual(summary["results"], {})

        summary = run_scenario([{"id": "bad", "name": "Bad", "curl": "not a curl"}], {})
        self.assertEqual(summary["failed"], 1)
        self.assertEqual(summary["results"]["bad"]["status"], "ERROR")


if __name__ == "__main__":
    unittest.main()
