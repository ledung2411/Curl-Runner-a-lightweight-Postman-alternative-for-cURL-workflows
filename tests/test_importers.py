from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

import cli
from core import parse_curl
from http_fixture import LocalApi
from importers import (
    import_path,
    merge_import,
    parse_bru,
    translate_postman_tests,
)

POSTMAN_COLLECTION = {
    "info": {"name": "Shop API", "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json"},
    "auth": {"type": "bearer", "bearer": [{"key": "token", "value": "{{token}}", "type": "string"}]},
    "variable": [{"key": "base", "value": "http://localhost:3000"}],
    "item": [
        {
            "name": "Auth",
            "item": [{
                "name": "Login",
                "request": {
                    "auth": {"type": "noauth"},
                    "method": "POST",
                    "header": [],
                    "body": {"mode": "raw", "raw": "{\"user\": \"dung\"}", "options": {"raw": {"language": "json"}}},
                    "url": {"raw": "{{base}}/login", "host": ["{{base}}"], "path": ["login"]},
                },
                "event": [{"listen": "test", "script": {"exec": [
                    "pm.test(\"Status code is 200\", function () {",
                    "    pm.response.to.have.status(200);",
                    "});",
                    "var jsonData = pm.response.json();",
                    "pm.environment.set(\"token\", jsonData.data.token);",
                ]}}],
            }],
        },
        {
            "name": "Me",
            "request": {"method": "GET", "header": [{"key": "X-Off", "value": "1", "disabled": True}],
                        "url": "{{base}}/me"},
            "event": [{"listen": "test", "script": {"exec": [
                "pm.test('ok', () => {", "  pm.expect(pm.response.code).to.eql(200);", "});",
                "console.log('custom logic')",
            ]}}],
        },
        {
            "name": "Upload",
            "request": {"method": "POST", "url": "{{base}}/upload", "auth": {"type": "basic", "basic": [
                {"key": "username", "value": "u"}, {"key": "password", "value": "p"}]},
                "body": {"mode": "formdata", "formdata": [
                    {"key": "name", "value": "Lê", "type": "text"},
                    {"key": "file", "src": "/tmp/a.png", "type": "file"},
                    {"key": "skip", "value": "x", "type": "text", "disabled": True},
                ]}},
        },
        {
            "name": "Search",
            "request": {"method": "POST", "url": "{{base}}/graphql",
                        "body": {"mode": "graphql", "graphql": {"query": "{ me { id } }", "variables": "{\"a\": 1}"}}},
        },
    ],
}

BRU_LOGIN = """meta {
  name: Login
  type: http
  seq: 1
}

post {
  url: {{base}}/login
  body: json
  auth: none
}

headers {
  X-Trace: 1
  ~X-Disabled: 0
}

body:json {
  {
    "user": "dung"
  }
}

vars:post-response {
  token: res.body.data.token
  rid: res.headers['x-request-id']
}

assert {
  res.status: eq 200
  res.body.data.token: isDefined
}
"""

BRU_ME = """meta {
  name: Me
  type: http
  seq: 2
}

get {
  url: {{base}}/me
  body: none
  auth: bearer
}

auth:bearer {
  token: {{token}}
}

assert {
  res.body.user: eq dung
}

tests {
  test("custom", function() {});
}
"""


def run_cli(*argv: str) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = cli.main(list(argv))
    return code, out.getvalue(), err.getvalue()


class PostmanImportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "shop.postman_collection.json"
        self.path.write_text(json.dumps(POSTMAN_COLLECTION), encoding="utf-8")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_requests_become_parseable_curls(self) -> None:
        result = import_path(self.path)
        items = {item["name"]: item for item in result.collections["Shop API"]}
        self.assertEqual(list(items), ["Auth / Login", "Me", "Upload", "Search"])
        self.assertEqual(result.environments, {"Shop API (variables)": {"base": "http://localhost:3000"}})

        login = parse_curl(items["Auth / Login"]["curl"])
        self.assertEqual((login["method"], login["url"]), ("POST", "{{base}}/login"))
        self.assertEqual(login["headers"], {"Content-Type": "application/json"})   # noauth: no bearer
        self.assertEqual(items["Auth / Login"]["assertions"], "status == 200")
        self.assertEqual(items["Auth / Login"]["extractors"], "token = json:$.data.token")

        me = parse_curl(items["Me"]["curl"])
        self.assertEqual(me["headers"], {"Authorization": "Bearer {{token}}"})       # inherited auth
        self.assertEqual(items["Me"]["assertions"], "status == 200")

        upload = parse_curl(items["Upload"]["curl"])
        self.assertEqual(upload["auth"], ("u", "p"))
        self.assertEqual(upload["body"], {"name": "Lê", "file": "@/tmp/a.png"})

        search = parse_curl(items["Search"]["curl"])
        self.assertEqual(json.loads(search["body"]), {"query": "{ me { id } }", "variables": {"a": 1}})

        self.assertTrue(any("Me: một phần test script" in note for note in result.notes))
        self.assertFalse(any("Login" in note for note in result.notes))

    def test_translate_postman_tests(self) -> None:
        extractors, assertions, partial = translate_postman_tests([
            "pm.response.to.be.ok;",
            "pm.expect(pm.response.responseTime).to.be.below(800);",
            "pm.collectionVariables.set('rid', pm.response.headers.get('X-Request-Id'));",
            "pm.environment.set('first', pm.response.json().items[0].id);",
        ])
        self.assertEqual(assertions, "status >= 200\nstatus < 300\ntime < 800")
        self.assertEqual(extractors, "rid = header:X-Request-Id\nfirst = json:$.items[0].id")  # source order
        self.assertFalse(partial)

    def test_postman_environment_and_merge_without_overwrite(self) -> None:
        env_path = Path(self.tmp.name) / "qa.postman_environment.json"
        env_path.write_text(json.dumps({"name": "QA", "values": [
            {"key": "base", "value": "http://qa", "enabled": True},
            {"key": "off", "value": "x", "enabled": False},
        ]}), encoding="utf-8")
        result = import_path(env_path)
        collections, environments = {"Shop API": []}, {"QA": {"old": "1"}}
        merge_import(import_path(self.path), collections, environments)
        created = merge_import(result, collections, environments)
        self.assertEqual(environments["QA"], {"old": "1"})
        self.assertEqual(environments["QA (2)"], {"base": "http://qa"})
        self.assertIn("Shop API (2)", collections)
        self.assertEqual(created, ["environment: QA (2) (1 biến)"])


class BrunoImportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "shop-bruno"
        (self.root / "users").mkdir(parents=True)
        (self.root / "environments").mkdir()
        (self.root / "bruno.json").write_text(json.dumps({"version": "1", "name": "Shop", "type": "collection"}),
                                              encoding="utf-8")
        (self.root / "users" / "Me.bru").write_text(BRU_ME, encoding="utf-8")
        (self.root / "Login.bru").write_text(BRU_LOGIN, encoding="utf-8")
        (self.root / "environments" / "Local.bru").write_text(
            "vars {\n  base: http://localhost\n}\nvars:secret [\n  apiKey\n]\n", encoding="utf-8")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_parse_bru_blocks(self) -> None:
        blocks = parse_bru(BRU_LOGIN)
        self.assertEqual(json.loads(blocks["body:json"]), {"user": "dung"})
        self.assertIn("url: {{base}}/login", blocks["post"])

    def test_folder_import(self) -> None:
        result = import_path(self.root)
        items = result.collections["Shop"]
        self.assertEqual([i["name"] for i in items], ["Login", "users / Me"])
        login = parse_curl(items[0]["curl"])
        self.assertEqual(login["headers"], {"X-Trace": "1", "Content-Type": "application/json"})
        self.assertEqual(items[0]["extractors"], "token = json:$.data.token\nrid = header:x-request-id")
        self.assertEqual(items[0]["assertions"], "status == 200\njson $.data.token exists")
        self.assertEqual(parse_curl(items[1]["curl"])["headers"], {"Authorization": "Bearer {{token}}"})
        self.assertEqual(result.environments, {"Local": {"base": "http://localhost", "apiKey": ""}})
        self.assertTrue(any("tests" in note for note in result.notes))


class HarImportTests(unittest.TestCase):
    def test_har_keeps_api_calls_only(self) -> None:
        har = {"log": {"entries": [
            {"_resourceType": "fetch", "request": {
                "method": "POST", "url": "https://api.test/v1/orders?x=1",
                "headers": [{"name": ":authority", "value": "api.test"}, {"name": "content-type", "value": "application/json"},
                            {"name": "Content-Length", "value": "9"}],
                "postData": {"mimeType": "application/json", "text": "{\"id\": 1}"}}},
            {"_resourceType": "image", "request": {"method": "GET", "url": "https://api.test/logo.png", "headers": []}},
            {"_resourceType": "xhr", "request": {
                "method": "POST", "url": "https://api.test/login", "headers": [],
                "postData": {"mimeType": "application/x-www-form-urlencoded",
                             "params": [{"name": "user", "value": "lê dũng"}]}}},
        ]}}
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "session.har"
            path.write_text(json.dumps(har), encoding="utf-8")
            result = import_path(path)
        items = result.collections["session"]
        self.assertEqual([i["name"] for i in items], ["POST /v1/orders", "POST /login"])
        order = parse_curl(items[0]["curl"])
        self.assertEqual(order["headers"], {"content-type": "application/json"})
        self.assertEqual(order["body"], '{"id": 1}')
        self.assertEqual(parse_curl(items[1]["curl"])["body"], "user=l%C3%AA%20d%C5%A9ng")

    def test_unknown_format_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "x.json"
            path.write_text("[1, 2]", encoding="utf-8")
            with self.assertRaises(ValueError):
                import_path(path)


class EndToEndTests(unittest.TestCase):
    """Collection Postman/Bruno chạy thật: login → lưu token → gọi /me bằng token."""

    def test_run_postman_and_bruno_collections_from_cli(self) -> None:
        postman = dict(POSTMAN_COLLECTION, item=POSTMAN_COLLECTION["item"][:2])
        with tempfile.TemporaryDirectory() as tmp, LocalApi() as base:
            pm_path = Path(tmp) / "shop.json"
            pm_path.write_text(json.dumps(postman), encoding="utf-8")
            code, out, err = run_cli("run", "--from", str(pm_path), "--var", f"base={base}")
            self.assertEqual(code, cli.EXIT_OK, out + err)
            self.assertIn("PASS  [G2] Me", out)

            bruno = Path(tmp) / "bruno"
            bruno.mkdir()
            (bruno / "bruno.json").write_text('{"name": "Shop"}', encoding="utf-8")
            (bruno / "Login.bru").write_text(BRU_LOGIN, encoding="utf-8")
            (bruno / "Me.bru").write_text(BRU_ME, encoding="utf-8")
            code, out, err = run_cli("run", "--from", str(bruno), "--var", f"base={base}", "-c", "shop")
            self.assertEqual(code, cli.EXIT_OK, out + err)

            code, out, _ = run_cli("import", str(bruno), "--dry-run")
            self.assertEqual(code, cli.EXIT_OK)
            self.assertIn("POST    Login (có Tests)", out)


if __name__ == "__main__":
    unittest.main()
