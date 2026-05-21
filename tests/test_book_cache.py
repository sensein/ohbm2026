"""T006 — per-abstract PDF cache: key derivation + hit/miss + atomic store.

Constitution principle IV: this lands as failing-before-impl per CA-002.

Tests cover:
- `compute_cache_key` is stable across calls with identical inputs.
- `compute_cache_key` changes when ANY of the five inputs changes (one
  assertion per input).
- The output matches `^[0-9a-f]{16}$` (16-hex slice).
- `load_cached_pdf` returns None on miss + the cached bytes on hit.
- `store_cached_pdf` writes both `<key>.pdf` and `<key>.json` sidecar
  atomically (temp file + os.replace).
"""

from __future__ import annotations

import pathlib
import re
import tempfile
import unittest


class TestCacheKey(unittest.TestCase):
    """compute_cache_key derivation rules (R1)."""

    @classmethod
    def setUpClass(cls) -> None:
        try:
            from ohbm2026.book.cache import compute_cache_key
        except ImportError as exc:
            raise unittest.SkipTest(
                f"ohbm2026.book.cache not yet implemented: {exc}"
            )
        cls.compute = staticmethod(compute_cache_key)
        cls.base = dict(
            md_body="# Test\nSome body.\n",
            pandoc_version="pandoc 3.5\n",
            engine_version="tectonic 0.15.0\n",
            header_includes_hash="abc123def4567890",
            style="plain",
        )

    def test_format_is_16_hex(self) -> None:
        key = self.compute(**self.base)
        self.assertRegex(key, r"^[0-9a-f]{16}$")

    def test_stable_across_calls(self) -> None:
        a = self.compute(**self.base)
        b = self.compute(**self.base)
        self.assertEqual(a, b)

    def test_changes_when_md_body_changes(self) -> None:
        base_key = self.compute(**self.base)
        other = dict(self.base, md_body="# Test\nSomething else.\n")
        self.assertNotEqual(self.compute(**other), base_key)

    def test_changes_when_pandoc_version_changes(self) -> None:
        base_key = self.compute(**self.base)
        other = dict(self.base, pandoc_version="pandoc 3.6\n")
        self.assertNotEqual(self.compute(**other), base_key)

    def test_changes_when_engine_version_changes(self) -> None:
        base_key = self.compute(**self.base)
        other = dict(self.base, engine_version="tectonic 0.16.0\n")
        self.assertNotEqual(self.compute(**other), base_key)

    def test_changes_when_header_includes_hash_changes(self) -> None:
        base_key = self.compute(**self.base)
        other = dict(self.base, header_includes_hash="0000000000000000")
        self.assertNotEqual(self.compute(**other), base_key)

    def test_changes_when_style_changes(self) -> None:
        base_key = self.compute(**self.base)
        other = dict(self.base, style="tufte")
        self.assertNotEqual(self.compute(**other), base_key)


class TestCacheLoadStore(unittest.TestCase):
    """load_cached_pdf / store_cached_pdf atomic disk contract."""

    @classmethod
    def setUpClass(cls) -> None:
        try:
            from ohbm2026.book.cache import (
                load_cached_pdf,
                store_cached_pdf,
            )
        except ImportError as exc:
            raise unittest.SkipTest(
                f"ohbm2026.book.cache not yet implemented: {exc}"
            )
        cls.load = staticmethod(load_cached_pdf)
        cls.store = staticmethod(store_cached_pdf)

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.cache_dir = pathlib.Path(self.tmp.name)
        # A minimal valid PDF (one empty page) — pikepdf to keep it real.
        import pikepdf

        pdf = pikepdf.Pdf.new()
        pdf.add_blank_page()
        out = self.cache_dir / "seed.pdf"
        pdf.save(out)
        self.pdf_bytes = out.read_bytes()
        out.unlink()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_load_miss_returns_none(self) -> None:
        result = self.load(self.cache_dir, "0123456789abcdef")
        self.assertIsNone(result)

    def test_store_then_load_round_trip(self) -> None:
        key = "0123456789abcdef"
        path = self.store(
            self.cache_dir,
            key,
            self.pdf_bytes,
            page_count=1,
        )
        self.assertTrue(path.exists())
        self.assertEqual(path.name, f"{key}.pdf")

        loaded = self.load(self.cache_dir, key)
        self.assertIsNotNone(loaded)
        bytes_back, sidecar = loaded
        self.assertEqual(bytes_back, self.pdf_bytes)
        self.assertEqual(sidecar.get("page_count"), 1)

    def test_store_writes_sidecar(self) -> None:
        key = "fedcba9876543210"
        self.store(
            self.cache_dir,
            key,
            self.pdf_bytes,
            page_count=3,
        )
        self.assertTrue((self.cache_dir / f"{key}.pdf").exists())
        self.assertTrue((self.cache_dir / f"{key}.json").exists())

    def test_store_is_atomic_temp_then_rename(self) -> None:
        """No `*.tmp` files should remain after a successful store."""
        key = "aaaabbbbccccdddd"
        self.store(
            self.cache_dir,
            key,
            self.pdf_bytes,
            page_count=1,
        )
        stragglers = list(self.cache_dir.glob("*.tmp")) + list(
            self.cache_dir.glob("*.partial")
        )
        self.assertEqual(stragglers, [])

    def test_store_from_path_avoids_bytes_round_trip(self) -> None:
        """Stage-11.1.1 hot path — render_one's pandoc-to-temp workflow.

        ``store_cached_pdf_from_path`` consumes the src path (atomic-
        moves it into the cache). No read-bytes-then-write-temp
        round-trip; the source path no longer exists after the call.
        """
        from ohbm2026.book.cache import store_cached_pdf_from_path

        key = "1111222233334444"
        # Write a temp PDF (same shape as pandoc's output would be).
        src = self.cache_dir / "raw.pdf.tmp"
        src.write_bytes(self.pdf_bytes)
        final = store_cached_pdf_from_path(
            self.cache_dir, key, src, page_count=1
        )
        self.assertTrue(final.exists())
        self.assertFalse(src.exists(), "src path must be consumed")

        loaded = self.load(self.cache_dir, key)
        self.assertIsNotNone(loaded)
        bytes_back, sidecar = loaded
        self.assertEqual(bytes_back, self.pdf_bytes)
        self.assertEqual(sidecar.get("page_count"), 1)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
