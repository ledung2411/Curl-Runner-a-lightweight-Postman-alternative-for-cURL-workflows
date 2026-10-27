from __future__ import annotations

import json
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from core import (
    apply_env,
    beautify_curl_body,
    decode_response,
    execute_request,
    has_executable_code,
    parse_curl,
    run_pre_script,
    shell_split,
)


class _EchoHandler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:  # noqa: N802 - http.server API
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length)
        payload = json.dumps({
            "content_type": self.headers.get("Content-Type", ""),
            "body_hex": body.hex(),
        }).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *_args) -> None:
        pass


class ParseCurlTests(unittest.TestCase):
    def test_attached_and_combined_short_options(self) -> None:
        parsed = parse_curl("curl -sSL -XPUT -H'Accept: application/json' -d'{\"a\":1}' https://api.test/x")
        self.assertEqual(parsed["method"], "PUT")
        self.assertEqual(parsed["url"], "https://api.test/x")
        self.assertEqual(parsed["headers"], {"Accept": "application/json"})
        self.assertEqual(parsed["body"], '{"a":1}')

    def test_value_of_unknown_option_is_not_taken_as_url(self) -> None:
        parsed = parse_curl("curl -o out.json --connect-timeout 5 https://api.test/download")
        self.assertEqual(parsed["url"], "https://api.test/download")
        self.assertEqual(parsed["method"], "GET")

    def test_missing_option_value_raises_value_error(self) -> None:
        for curl in ("curl https://api.test -X", "curl https://api.test -H"):
            with self.assertRaises(ValueError):
                parse_curl(curl)

    def test_multiple_data_flags_are_joined_like_curl(self) -> None:
        parsed = parse_curl("curl https://api.test -d a=1 -d b=2")
        self.assertEqual(parsed["body"], "a=1&b=2")
        self.assertEqual(parsed["method"], "POST")

    def test_get_flag_moves_data_to_query_string(self) -> None:
        parsed = parse_curl("curl -G https://api.test/search?x=1 -d q=a --data-urlencode 'name=Lê Dũng'")
        self.assertEqual(parsed["method"], "GET")
        self.assertIsNone(parsed["body"])
        self.assertEqual(parsed["url"], "https://api.test/search?x=1&q=a&name=L%C3%AA%20D%C5%A9ng")

    def test_head_json_user_cookie_and_referer(self) -> None:
        self.assertEqual(parse_curl("curl -I https://api.test")["method"], "HEAD")

        parsed = parse_curl("curl --json '{\"x\":1}' https://api.test")
        self.assertEqual(parsed["method"], "POST")
        self.assertEqual(parsed["headers"]["Content-Type"], "application/json")

        parsed = parse_curl("curl.exe -u admin -b a=1 -b b=2 -e https://ref.test https://api.test")
        self.assertEqual(parsed["auth"], ("admin", ""))
        self.assertEqual(parsed["headers"]["Cookie"], "a=1; b=2")
        self.assertEqual(parsed["headers"]["Referer"], "https://ref.test")

    def test_headers_override_case_insensitively(self) -> None:
        parsed = parse_curl("curl https://api.test -H 'content-type: a' -H 'Content-Type: b'")
        self.assertEqual(parsed["headers"], {"Content-Type": "b"})

    def test_chrome_bash_ansi_c_quoting(self) -> None:
        parsed = parse_curl("curl 'https://api.test' --data-raw $'{\"msg\":\"it\\'s \\u1ebf\"}'")
        self.assertEqual(json.loads(parsed["body"]), {"msg": "it's ế"})

    def test_chrome_cmd_caret_quoting(self) -> None:
        curl = 'curl ^"https://api.test/x^" -H ^"Accept: */*^" --data-raw ^"^{^\\^"a^\\^":1^}^"'
        parsed = parse_curl(curl)
        self.assertEqual(parsed["url"], "https://api.test/x")
        self.assertEqual(parsed["headers"], {"Accept": "*/*"})
        self.assertEqual(json.loads(parsed["body"]), {"a": 1})

    def test_double_quotes_keep_unknown_backslash_escapes_like_bash(self) -> None:
        tokens = shell_split('curl -d "{\\"n\\":\\"a\\nb\\",\\"p\\":\\"\\$HOME\\"}"')
        self.assertEqual(tokens[2], '{"n":"a\\nb","p":"$HOME"}')

    def test_form_fields_and_data_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp) / "body.json"
            data.write_text('{"a":\n1}', encoding="utf-8")
            self.assertEqual(parse_curl(f"curl https://api.test -d @{data}")["body"], '{"a":1}')
            self.assertEqual(parse_curl(f"curl https://api.test --data-binary @{data}")["body"], '{"a":\n1}')

        parsed = parse_curl("curl https://api.test -F name=value -F 'file=@a.png;type=image/png'")
        self.assertEqual(parsed["body"], {"name": "value", "file": "@a.png;type=image/png"})
        with self.assertRaises(ValueError):
            parse_curl("curl https://api.test -F a=1 -d b=2")


class ExecuteRequestTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), _EchoHandler)
        cls.url = f"http://127.0.0.1:{cls.server.server_address[1]}/echo"
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()

    def _send(self, curl: str) -> dict:
        resp, elapsed = execute_request(parse_curl(curl))
        self.assertEqual(resp.status_code, 200)
        self.assertGreaterEqual(elapsed, 0)
        return resp.json()

    def test_unicode_json_body_is_sent_byte_for_byte(self) -> None:
        body = '{"name": "Tiếng Việt 🚀", "n": 1.50}'
        echo = self._send(f"curl {self.url} -H 'Content-Type: application/json' --data-raw '{body}'")
        self.assertEqual(bytes.fromhex(echo["body_hex"]).decode("utf-8"), body)

    def test_unicode_text_body_without_content_type(self) -> None:
        echo = self._send(f"curl {self.url} -d 'ghi chú=xin chào'")
        self.assertEqual(bytes.fromhex(echo["body_hex"]).decode("utf-8"), "ghi chú=xin chào")

    def test_form_plain_fields_are_not_sent_as_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            upload = Path(tmp) / "hello.txt"
            upload.write_text("file content", encoding="utf-8")
            echo = self._send(f"curl {self.url} -F name=Dung -F 'doc=@{upload};type=text/plain'")
        raw = bytes.fromhex(echo["body_hex"]).decode("utf-8")
        self.assertIn("multipart/form-data", echo["content_type"])
        self.assertIn('Content-Disposition: form-data; name="name"\r\n\r\nDung', raw)
        self.assertIn('name="doc"; filename="hello.txt"', raw)
        self.assertIn("Content-Type: text/plain", raw)


class HelperTests(unittest.TestCase):
    def test_beautify_keeps_shell_quoting_valid(self) -> None:
        curl = "curl https://api.test -d '{\"msg\":\"it'\\''s\",\"n\":1}'"
        pretty = beautify_curl_body(curl)
        self.assertIn("\n", pretty)
        self.assertEqual(json.loads(parse_curl(pretty)["body"]), {"msg": "it's", "n": 1})

        curl = 'curl https://api.test -d "{\\"q\\":\\"a\\\\\\"b\\",\\"p\\":\\"$x\\"}"'
        pretty = beautify_curl_body(curl)
        self.assertEqual(json.loads(parse_curl(pretty)["body"]), {"q": 'a"b', "p": "$x"})

        self.assertEqual(beautify_curl_body("curl https://api.test -d 'not json'"),
                         "curl https://api.test -d 'not json'")

    def test_decode_response_accepts_quoted_charset(self) -> None:
        class FakeResponse:
            headers = {"Content-Type": 'text/plain; charset="utf-8"'}
            content = "Xin chào".encode("utf-8")

        text, info = decode_response(FakeResponse())
        self.assertEqual(text, "Xin chào")
        self.assertNotIn("fallback", info)

    def test_pre_script_detection_and_values(self) -> None:
        self.assertFalse(has_executable_code("# only a comment\n\n   # another"))
        self.assertTrue(has_executable_code("# Ví dụ\nset_env('token', 'abc')"))

        env, logs = run_pre_script("# comment first\nenv['port'] = 8080\nset_env('token', 'abc')", {})
        self.assertEqual(env, {"port": "8080", "token": "abc"})
        self.assertTrue(logs[0].startswith("✅"))
        self.assertEqual(apply_env("{{token}}:{{port}}", env), "abc:8080")


if __name__ == "__main__":
    unittest.main()
