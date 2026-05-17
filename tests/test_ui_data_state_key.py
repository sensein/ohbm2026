"""T011a — state_key.py discovery tests."""

from __future__ import annotations

import json
import sqlite3
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from ohbm2026.ui_data.state_key import (
    Stage6BuildError,
    discover_corpus_state_key,
    discover_minilm_bundle,
    discover_rollup_state_key,
)


def _touch_rollup(root: Path, state_key: str) -> Path:
    target = root / f"annotations__{state_key}.sqlite"
    conn = sqlite3.connect(target)
    conn.execute("CREATE TABLE annotations (abstract_id INTEGER PRIMARY KEY)")
    conn.close()
    return target


class TestRollupDiscovery(unittest.TestCase):
    def test_no_rollup_raises(self) -> None:
        with TemporaryDirectory() as tmp:
            with self.assertRaises(Stage6BuildError) as exc:
                discover_rollup_state_key(Path(tmp))
            self.assertIn("No annotations__", str(exc.exception))

    def test_single_rollup_returns_state_key(self) -> None:
        with TemporaryDirectory() as tmp:
            _touch_rollup(Path(tmp), "abcdef012345")
            self.assertEqual(discover_rollup_state_key(Path(tmp)), "abcdef012345")

    def test_multiple_rollups_raise(self) -> None:
        with TemporaryDirectory() as tmp:
            _touch_rollup(Path(tmp), "aaaaaaaaaaaa")
            _touch_rollup(Path(tmp), "bbbbbbbbbbbb")
            with self.assertRaises(Stage6BuildError) as exc:
                discover_rollup_state_key(Path(tmp))
            self.assertIn("Multiple", str(exc.exception))


class TestCorpusStateKey(unittest.TestCase):
    def test_uses_meta_state_key_when_present(self) -> None:
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "abstracts.json"
            path.write_text(json.dumps({"meta": {"state_key": "deadbeef1234"}, "abstracts": []}))
            self.assertEqual(discover_corpus_state_key(path), "deadbeef1234")

    def test_hashes_bytes_when_meta_absent(self) -> None:
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "abstracts.json"
            path.write_text(json.dumps({"abstracts": []}))
            key = discover_corpus_state_key(path)
            self.assertRegex(key, r"^[0-9a-f]{12}$")


class TestMinilmBundleDiscovery(unittest.TestCase):
    def test_returns_most_recent(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "introduction__aaaaaaaaaaaa").mkdir()
            (root / "introduction__bbbbbbbbbbbb").mkdir()
            (root / "methods__bbbbbbbbbbbb").mkdir()
            found = discover_minilm_bundle(root, component="introduction")
            self.assertTrue(found.name.startswith("introduction__"))

    def test_missing_component_raises(self) -> None:
        with TemporaryDirectory() as tmp:
            with self.assertRaises(Stage6BuildError):
                discover_minilm_bundle(Path(tmp), component="introduction")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
