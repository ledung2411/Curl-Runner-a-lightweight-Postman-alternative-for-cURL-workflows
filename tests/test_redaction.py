from __future__ import annotations

import json
import unittest

from core import parse_curl
from redaction import (
    MASK,
    REDACTED,
    is_secret_name,
    mask_value,
    redact_curl,
    redact_url,
    replace_secret_values,
    secret_map,
)


class SecretNameTests(unittest.TestCase):
    def test_detects_secret_names(self) -> None:
        for name in ("token", "access_token", "client_secret", "password", "db_pass", "api_key",
                     "x-api-key", "private_key", "session_id", "jwt"):
            self.assertTrue(is_secret_name(name), name)
        for name in ("base_url", "user_id", "page", "keyword"):
            self.assertFalse(is_secret_name(name), name)
        self.assertTrue(is_secret_name("otp_seed", {"otp_seed"}))

    def test_secret_map_skips_short_values(self) -> None:
        env = {"token": "tok-123456", "pin_token": "12", "base_url": "https://api.test"}
        self.assertEqual(secret_map(env), {"token": "tok-123456"})

    def test_mask_and_replace(self) -> None:
        self.assertEqual(mask_value("password", "hunter2"), MASK)
        self.assertEqual(mask_value("base_url", "https://x"), "https://x")
        self.assertEqual(mask_value("password", ""), "")
        self.assertEqual(replace_secret_values("a tok-1234 b", {"token": "tok-1234"}), "a {{token}} b")
        self.assertEqual(replace_secret_values("a tok-1234", {"token": "tok-1234"}, REDACTED), f"a {REDACTED}")


class RedactCurlTests(unittest.TestCase):
    def test_known_secret_values_become_variables_and_still_parse(self) -> None:
        curl = "curl https://api.test/me -H 'Authorization: Bearer tok-123456'"
        redacted = redact_curl(curl, {"token": "tok-123456"})
        self.assertEqual(redacted, "curl https://api.test/me -H 'Authorization: Bearer {{token}}'")

    def test_pasted_credentials_are_redacted(self) -> None:
        curl = (
            "curl -u admin:hunter2 'https://api.test/x?token=abc&page=2' "
            "-H 'Authorization: Bearer raw.jwt.value' -H 'X-Api-Key: k-999' -H 'Accept: application/json' "
            "-b 'session=s1' --oauth2-bearer zzz "
            "-d '{\"user\": \"dung\", \"password\": \"p@ss\", \"items\": [{\"refresh_token\": \"r1\"}]}'"
        )
        redacted = redact_curl(curl)
        for leaked in ("hunter2", "abc&", "raw.jwt.value", "k-999", "s1", "zzz", "p@ss", "r1"):
            self.assertNotIn(leaked, redacted)
        parsed = parse_curl(redacted)
        self.assertEqual(parsed["auth"], ("admin", REDACTED))
        self.assertEqual(parsed["url"], f"https://api.test/x?token={REDACTED}&page=2")
        self.assertEqual(parsed["headers"]["Authorization"], f"Bearer {REDACTED}")
        self.assertEqual(parsed["headers"]["Accept"], "application/json")
        self.assertEqual(json.loads(parsed["body"])["user"], "dung")

    def test_variables_and_safe_commands_are_left_untouched(self) -> None:
        curl = "curl {{base}}/login \\\n  -H 'Authorization: Bearer {{token}}' \\\n  -d 'user=dung&password={{password}}'"
        self.assertEqual(redact_curl(curl), curl)
        self.assertEqual(redact_curl("curl https://api.test/health"), "curl https://api.test/health")
        self.assertEqual(redact_curl("curl 'unclosed"), "curl 'unclosed")   # unparsable → unchanged

    def test_form_and_urlencoded_fields(self) -> None:
        redacted = redact_curl("curl https://api.test -F password=abc -F file=@a.png --data-urlencode 'secret=x y'")
        body = parse_curl(redacted.replace("--data-urlencode", "-F"))["body"]
        self.assertEqual(body, {"password": REDACTED, "file": "@a.png", "secret": REDACTED})

    def test_redact_url(self) -> None:
        self.assertEqual(redact_url("https://api.test/x?api_key=K1#top"), f"https://api.test/x?api_key={REDACTED}#top")
        self.assertEqual(redact_url("https://api.test/u/tok-1234", {"token": "tok-1234"}), "https://api.test/u/{{token}}")
        self.assertEqual(redact_url("https://api.test/x?page=1"), "https://api.test/x?page=1")


if __name__ == "__main__":
    unittest.main()
