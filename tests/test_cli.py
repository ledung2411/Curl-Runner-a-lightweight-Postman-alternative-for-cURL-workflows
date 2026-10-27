from __future__ import annotations

import io
import json
import os
import tempfile
import unittest
import xml.etree.ElementTree as ET
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

import cli
from http_fixture import LocalApi


def run_cli(*argv: str) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = cli.main(list(argv))
    return code, out.getvalue(), err.getvalue()


class CliRunTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.api = LocalApi()
        self.base = self.api.__enter__()
        self.scenarios = self.dir / "scenarios.json"
        self.scenarios.write_text(json.dumps([
            {
                "id": "s1", "name": "Login flow",
                "steps": [
                    {"id": "login", "name": "Login", "group": 1, "curl": "curl -X POST {{base}}/login",
                     "extractors": "token = json:$.data.token", "assertions": "status == 200"},
                    {"id": "me", "name": "Me", "group": 2,
                     "curl": "curl {{base}}/me -H 'Authorization: Bearer {{token}}'",
                     "assertions": "json $.user == dung"},
                    {"id": "off", "name": "Disabled", "group": 3, "enabled": False, "curl": "curl {{base}}/x"},
                ],
            },
            {
                "id": "s2", "name": "Broken",
                "steps": [
                    {"id": "b1", "name": "Explode", "group": 1, "curl": "curl {{base}}/explode"},
                    {"id": "b2", "name": "Never", "group": 2, "curl": "curl {{base}}/health"},
                ],
            },
            {
                "id": "s3", "name": "Users",
                "steps": [{"id": "u", "name": "User", "curl": "curl {{base}}/users/{{user_id}}",
                           "assertions": "json $.id == {{user_id}}"}],
            },
        ]), encoding="utf-8")
        self.envs = self.dir / "envs.json"
        self.envs.write_text(json.dumps({"QA": {"base": self.base}, "Prod": {"base": "http://127.0.0.1:9"}}),
                             encoding="utf-8")

    def tearDown(self) -> None:
        self.api.__exit__(None, None, None)
        self.tmp.cleanup()

    def test_passing_scenario_writes_reports(self) -> None:
        junit, as_json = self.dir / "out" / "junit.xml", self.dir / "out" / "report.json"
        code, out, _ = run_cli("run", "--file", str(self.scenarios), "-s", "Login flow",
                               "--env-file", str(self.envs), "--env", "qa",
                               "--report", str(junit), "--report", str(as_json))
        self.assertEqual(code, cli.EXIT_OK, out)
        self.assertIn("PASS  [G2] Me", out)
        suite = ET.parse(junit).getroot()
        self.assertEqual((suite.attrib["tests"], suite.attrib["failures"], suite.attrib["skipped"]), ("3", "0", "1"))
        self.assertEqual(json.loads(as_json.read_text(encoding="utf-8"))["counts"]["passed"], 2)

    def test_failure_and_stop_on_fail_give_exit_code_1(self) -> None:
        code, out, _ = run_cli("run", "--file", str(self.scenarios), "-s", "Broken",
                               "--env-file", str(self.envs), "--env", "QA")
        self.assertEqual(code, cli.EXIT_FAILED)
        self.assertIn("FAIL  [G1] Explode", out)
        self.assertIn("1 không chạy", out)

        code, out, _ = run_cli("run", "--file", str(self.scenarios), "-s", "Broken", "--no-stop-on-fail",
                               "--env-file", str(self.envs), "--env", "QA")
        self.assertEqual(code, cli.EXIT_FAILED)
        self.assertIn("PASS  [G2] Never", out)

    def test_data_driven_iterations_and_variable_precedence(self) -> None:
        data = self.dir / "users.csv"
        data.write_text("user_id\n7\n42\n", encoding="utf-8")
        report = self.dir / "users.csv.json"
        code, out, _ = run_cli("run", "--file", str(self.scenarios), "-s", "Users", "--data", str(data),
                               "--var", f"base={self.base}", "--report", str(report))
        self.assertEqual(code, cli.EXIT_OK, out)
        self.assertIn("Users [#2]", out)
        names = [s["name"] for s in json.loads(report.read_text(encoding="utf-8"))["steps"]]
        self.assertEqual(names, ["Users [#1] › User", "Users [#2] › User"])

        # --var beats the environment; CURLRUNNER_VAR_* fills in secrets from CI.
        with mock.patch.dict(os.environ, {"CURLRUNNER_VAR_user_id": "99"}):
            code, out, _ = run_cli("run", "--file", str(self.scenarios), "-s", "Users",
                                   "--env-file", str(self.envs), "--env", "Prod", "--var", f"base={self.base}")
        self.assertEqual(code, cli.EXIT_OK, out)

    def test_collection_run_uses_saved_request_tests(self) -> None:
        collections = self.dir / "collections.json"
        collections.write_text(json.dumps({"Smoke": [
            {"id": "h", "name": "Health", "method": "GET", "curl": f"curl {self.base}/health",
             "assertions": "json $.items[1].id == 2"},
            {"id": "m", "name": "Me", "method": "GET", "curl": f"curl {self.base}/me",
             "assertions": "status == 200"},
        ]}), encoding="utf-8")
        code, out, _ = run_cli("run", "-c", "smoke", "--collections-file", str(collections))
        self.assertEqual(code, cli.EXIT_FAILED)
        self.assertIn("PASS  [G1] Health", out)
        self.assertIn("FAIL: status == 200", out)

    def test_configuration_errors_exit_2(self) -> None:
        cases = [
            ("run", "--file", str(self.scenarios)),                       # several scenarios, none chosen
            ("run", "--file", str(self.scenarios), "-s", "Nope"),
            ("run", "--file", str(self.scenarios), "-s", "Users", "--env-file", str(self.envs)),
            ("run", "--file", str(self.dir / "missing.json"), "--all"),
            ("run", "--file", str(self.scenarios), "-s", "Users", "--var", "novalue"),
        ]
        for argv in cases:
            with self.subTest(argv=argv):
                code, _, err = run_cli(*argv)
                self.assertEqual(code, cli.EXIT_USAGE, err)
                self.assertIn("Lỗi:", err)

    def test_postman_environment_export_is_accepted(self) -> None:
        env_file = self.dir / "postman_env.json"
        env_file.write_text(json.dumps({"name": "QA", "values": [
            {"key": "base", "value": self.base, "enabled": True},
            {"key": "unused", "value": "x", "enabled": False},
        ]}), encoding="utf-8")
        self.assertEqual(cli.load_environment(env_file, None), {"base": self.base})


class CliRequestTests(unittest.TestCase):
    def test_request_prints_body_and_checks_assertions(self) -> None:
        with LocalApi() as base:
            code, out, err = run_cli("request", f"curl {base}/health", "-a", "json $.ok == true",
                                     "-e", "first = json:$.items[0].id")
            self.assertEqual(code, cli.EXIT_OK, err)
            self.assertEqual(json.loads(out)["ok"], True)
            self.assertIn("extract first=1", err)
            self.assertIn("PASS: json $.ok == true", err)

            code, _, err = run_cli("request", f"{base}/me", "--show", "none")
            self.assertEqual(code, cli.EXIT_FAILED)          # default assertion: 2xx/3xx
            self.assertIn("401", err)


if __name__ == "__main__":
    unittest.main()
