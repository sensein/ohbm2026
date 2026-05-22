"""T016 — Stage 12 US2 — figure normalisation.

`_copy_figure` MUST always re-encode to JPEG quality 90 with a
150 DPI pixel-dimension cap (≈ 975 px wide). Source format does
not matter — even an already-small JPEG re-encodes through Pillow
so the output is deterministic. Pillow-unopenable sources fall
back to a byte-copy with their original extension AND an audit
entry in the module-level fallback registry.
"""

from __future__ import annotations

import pathlib
import tempfile
import unittest


class TestFigureNormalisation(unittest.TestCase):
    """Pillow-driven re-encode behaviour."""

    @classmethod
    def setUpClass(cls) -> None:
        try:
            from PIL import Image  # noqa: F401
        except ImportError:
            raise unittest.SkipTest("Pillow not installed")
        try:
            from ohbm2026.book.render_markdown import (
                _copy_figure,
                _figure_normalise_fallbacks,
                get_normalise_fallbacks,
                reset_normalise_fallbacks,
            )
        except ImportError as exc:
            raise unittest.SkipTest(f"figure-normalise helpers not yet implemented: {exc}")
        cls._copy_figure = staticmethod(_copy_figure)
        cls._fallbacks = _figure_normalise_fallbacks
        cls.get_normalise_fallbacks = staticmethod(get_normalise_fallbacks)
        cls.reset_normalise_fallbacks = staticmethod(reset_normalise_fallbacks)

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.workdir = pathlib.Path(self.tmp.name)
        self.reset_normalise_fallbacks()

    def tearDown(self) -> None:
        self.tmp.cleanup()
        self.reset_normalise_fallbacks()

    def _make_png(self, name: str, *, width: int, height: int, mode: str = "RGB") -> pathlib.Path:
        from PIL import Image

        src = self.workdir / name
        img = Image.new(mode, (width, height), color=(255, 0, 0) if mode == "RGB" else (255, 0, 0, 128))
        img.save(src, format="PNG")
        return src

    def _make_jpeg(self, name: str, *, width: int, height: int, quality: int) -> pathlib.Path:
        from PIL import Image

        src = self.workdir / name
        img = Image.new("RGB", (width, height), color=(0, 128, 0))
        img.save(src, format="JPEG", quality=quality)
        return src

    def test_large_png_resized_to_975_jpeg_q90(self) -> None:
        from PIL import Image

        src = self._make_png("big.png", width=4000, height=3000)
        dest_in = self.workdir / "fig_assets" / "1234567-0123-results.png"
        dest_in.parent.mkdir()
        # _copy_figure should force `.jpg` extension regardless of caller's input.
        chunk = self._copy_figure(src, dest_in, max_width=1800)
        # The function returns a NormalisedFigureAsset; the test inspects
        # both the return value and the on-disk artefact.
        # Dest forced to .jpg.
        out = dest_in.with_suffix(".jpg")
        self.assertTrue(out.exists(), f"expected {out} on disk; got files {list(dest_in.parent.iterdir())}")
        self.assertFalse(dest_in.exists(), "original-extension dest must NOT remain")
        # JPEG width capped to 975 (150 DPI × 6.5").
        with Image.open(out) as img:
            self.assertEqual(img.format, "JPEG")
            self.assertEqual(img.width, 975)
            # Height preserves aspect ratio (4000 × 3000 → 975 × ~731).
            self.assertAlmostEqual(img.height, round(3000 * 975 / 4000), delta=1)

    def test_small_jpeg_preserves_dimensions_but_re_encodes(self) -> None:
        from PIL import Image

        src = self._make_jpeg("small.jpg", width=600, height=400, quality=50)
        dest_in = self.workdir / "fig_assets" / "9999999-0042-methods.jpg"
        dest_in.parent.mkdir()
        self._copy_figure(src, dest_in, max_width=1800)
        out = dest_in.with_suffix(".jpg")
        self.assertTrue(out.exists())
        with Image.open(out) as img:
            self.assertEqual(img.format, "JPEG")
            self.assertEqual((img.width, img.height), (600, 400))
        # The output bytes differ from the (q=50) source because we re-encoded at q=90.
        self.assertNotEqual(src.read_bytes(), out.read_bytes())

    def test_transparent_png_flattens_to_rgb_on_white(self) -> None:
        from PIL import Image

        src = self._make_png("transparent.png", width=200, height=200, mode="RGBA")
        dest_in = self.workdir / "fig_assets" / "5555555-0007-figure.png"
        dest_in.parent.mkdir()
        self._copy_figure(src, dest_in, max_width=1800)
        out = dest_in.with_suffix(".jpg")
        with Image.open(out) as img:
            self.assertEqual(img.format, "JPEG")
            self.assertEqual(img.mode, "RGB")

    def test_unreadable_source_falls_back_to_byte_copy(self) -> None:
        # Create a file that's NOT a valid image — Pillow rejects.
        src = self.workdir / "junk.png"
        src.write_bytes(b"not a real image, just some bytes")
        dest_in = self.workdir / "fig_assets" / "7777777-0099-methods.png"
        dest_in.parent.mkdir()
        self._copy_figure(src, dest_in, max_width=1800)
        # Byte-copy fallback preserves the original extension.
        self.assertTrue(dest_in.exists(), "original-extension dest expected on fallback")
        self.assertEqual(dest_in.read_bytes(), src.read_bytes())
        # No .jpg variant exists for this entry.
        self.assertFalse(dest_in.with_suffix(".jpg").exists())
        # Fallback registry has the entry.
        fallbacks = self.get_normalise_fallbacks()
        self.assertEqual(len(fallbacks), 1)
        entry = fallbacks[0]
        self.assertIn("filename", entry)
        self.assertIn("error_reason", entry)
        self.assertIn("0099", entry["filename"])

    def test_reset_clears_fallback_registry(self) -> None:
        src = self.workdir / "junk.png"
        src.write_bytes(b"not an image")
        dest_in = self.workdir / "fig_assets" / "junk-dest.png"
        dest_in.parent.mkdir()
        self._copy_figure(src, dest_in, max_width=1800)
        self.assertEqual(len(self.get_normalise_fallbacks()), 1)
        self.reset_normalise_fallbacks()
        self.assertEqual(len(self.get_normalise_fallbacks()), 0)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
