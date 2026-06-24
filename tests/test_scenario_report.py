from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path
import xml.etree.ElementTree as ET

from scenario_report import build_scenario_report, export_scenario_report


class ScenarioReportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.scenario = {
            "name": "Checkout <Smoke>",
            "steps": [
                {
                    "id": "pass",
                    "name": "Get cart",
                    "group": 1,
                    "enabled": True,
                    "curl": "curl 'https://api.test/cart?api_key=secret123&locale=en'",
                },
                {
                    "id": "fail",
                    "name": "Submit order",
                    "group": 2,
                    "enabled": True,
                    "curl": "curl -X POST https://api.test/orders",
                },
                {
                    "id": "disabled",
                    "name": "Disabled step",
                    "group": 3,
                    "enabled": False,
                    "curl": "curl https://api.test/disabled",
                },
                {
                    "id": "not-run",
                    "name": "Not run step",
                    "group": 4,
                    "enabled": True,
                    "curl": "curl https://api.test/not-run",
                },
            ],
        }
        self.results = {
            "pass": {
                "ok": True,
                "status": "200 OK",
                "elapsed_ms": 25.5,
                "assertions": ["PASS: status == 200"],
                "extract_names": ["cart_id"],
            },
            "fail": {
                "ok": False,
                "status": "500 Server Error",
                "elapsed_ms": 40,
                "assertions": ["FAIL: status == 201"],
                "extract_names": [],
                "error": "",
            },
        }

    def test_build_report_counts_and_redacts_sensitive_query(self) -> None:
        report = build_scenario_report(
            self.scenario,
            self.results,
            environment="QA",
            summary="1 passed, 1 failed",
        )

        self.assertEqual(report["counts"], {
            "total": 4,
            "executed": 2,
            "passed": 1,
            "failed": 1,
            "skipped": 2,
        })
        self.assertEqual([step["outcome"] for step in report["steps"]], [
            "PASSED", "FAILED", "SKIPPED", "NOT RUN",
        ])
        self.assertIn("api_key=%5BREDACTED%5D", report["steps"][0]["url"])
        self.assertIn("locale=en", report["steps"][0]["url"])
        self.assertNotIn("secret123", report["steps"][0]["url"])

    def test_export_html_csv_and_junit(self) -> None:
        report = build_scenario_report(self.scenario, self.results, environment="QA")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            html_path = export_scenario_report(report, root / "report.html")
            csv_path = export_scenario_report(report, root / "report.csv")
            xml_path = export_scenario_report(report, root / "report.xml")

            html_text = html_path.read_text(encoding="utf-8")
            self.assertIn("Checkout &lt;Smoke&gt;", html_text)
            self.assertIn("%5BREDACTED%5D", html_text)
            self.assertNotIn("secret123", html_text)

            with csv_path.open(encoding="utf-8-sig", newline="") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(len(rows), 4)
            self.assertEqual(rows[1]["outcome"], "FAILED")

            suite = ET.parse(xml_path).getroot()
            self.assertEqual(suite.tag, "testsuite")
            self.assertEqual(suite.attrib["tests"], "4")
            self.assertEqual(suite.attrib["failures"], "1")
            self.assertEqual(suite.attrib["skipped"], "2")
            self.assertEqual(len(suite.findall("testcase")), 4)

    def test_rejects_unknown_extension(self) -> None:
        report = build_scenario_report(self.scenario, self.results)
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                export_scenario_report(report, Path(tmp) / "report.txt")


if __name__ == "__main__":
    unittest.main()
