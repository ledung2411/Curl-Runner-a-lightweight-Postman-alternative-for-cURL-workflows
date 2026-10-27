from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import store


class StoreTests(unittest.TestCase):
    def test_save_then_load_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "nested" / "history.json"
            store.save(path, [{"url": "https://api.test", "note": "tiếng Việt"}])
            self.assertEqual(store.load(path, []), [{"url": "https://api.test", "note": "tiếng Việt"}])
            self.assertEqual([p.name for p in path.parent.iterdir()], ["history.json"])

    def test_missing_file_returns_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(store.load(Path(tmp) / "missing.json", {"Default": {}}), {"Default": {}})

    def test_corrupt_file_is_backed_up_instead_of_overwritten(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "collections.json"
            path.write_text('{"broken": [', encoding="utf-8")

            self.assertEqual(store.load(path, {}), {})
            backups = list(Path(tmp).glob("collections.json.corrupt-*.bak"))
            self.assertEqual(len(backups), 1)
            self.assertEqual(backups[0].read_text(encoding="utf-8"), '{"broken": [')

    def test_wrong_top_level_type_is_backed_up(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "history.json"
            path.write_text('{"not": "a list"}', encoding="utf-8")
            self.assertEqual(store.load(path, []), [])
            self.assertEqual(len(list(Path(tmp).glob("history.json.corrupt-*.bak"))), 1)


if __name__ == "__main__":
    unittest.main()
