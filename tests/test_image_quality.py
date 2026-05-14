"""Tests for `src/ohbm2026/image_quality.py`.

Pure-function tests against synthetic Pillow images. No I/O.
"""

from __future__ import annotations

import io
import unittest

from PIL import Image, ImageFilter, ImageDraw

from ohbm2026 import image_quality


def _synth_sharp(size: int = 200) -> Image.Image:
    """High-contrast checkerboard — large Laplacian variance."""
    img = Image.new("RGB", (size, size), (255, 255, 255))
    draw = ImageDraw.Draw(img)
    step = 20
    for y in range(0, size, step):
        for x in range(0, size, step):
            if ((x // step) + (y // step)) % 2 == 0:
                draw.rectangle([(x, y), (x + step, y + step)], fill=(0, 0, 0))
    return img


def _synth_blurry(size: int = 200) -> Image.Image:
    """Same checkerboard heavily blurred — low Laplacian variance."""
    sharp = _synth_sharp(size)
    return sharp.filter(ImageFilter.GaussianBlur(radius=12))


class LaplacianVarianceTests(unittest.TestCase):
    def test_sharp_image_has_higher_variance_than_blurry(self) -> None:
        sharp_var = image_quality.laplacian_variance(_synth_sharp())
        blurry_var = image_quality.laplacian_variance(_synth_blurry())
        self.assertGreater(sharp_var, blurry_var)
        # Sharp checkerboard's edges should give a substantial variance.
        self.assertGreater(sharp_var, image_quality.BLUR_THRESHOLD_ADVISORY)

    def test_pure_gray_image_has_low_variance(self) -> None:
        # Pillow's 8-bit clipping at the kernel boundaries creates a
        # small amount of edge-pixel variance for a uniform image.
        # The "low blur" signal we care about is: variance is well
        # below the blurry-real-image threshold.
        img = Image.new("RGB", (200, 200), (128, 128, 128))
        self.assertLess(image_quality.laplacian_variance(img), 500.0)


class MeanBrightnessTests(unittest.TestCase):
    def test_white_image_is_bright(self) -> None:
        img = Image.new("RGB", (10, 10), (255, 255, 255))
        self.assertAlmostEqual(image_quality.mean_brightness(img), 255.0, places=0)

    def test_black_image_is_dark(self) -> None:
        img = Image.new("RGB", (10, 10), (0, 0, 0))
        self.assertAlmostEqual(image_quality.mean_brightness(img), 0.0, places=0)


class NativeMaxDimTests(unittest.TestCase):
    def test_wide_image_returns_width(self) -> None:
        img = Image.new("RGB", (1000, 400), (0, 0, 0))
        self.assertEqual(image_quality.native_max_dim(img), 1000)

    def test_tall_image_returns_height(self) -> None:
        img = Image.new("RGB", (300, 800), (0, 0, 0))
        self.assertEqual(image_quality.native_max_dim(img), 800)


class CompressionRatioTests(unittest.TestCase):
    def test_typical_ratio(self) -> None:
        self.assertAlmostEqual(image_quality.compression_ratio(1000, 200), 0.2)

    def test_clamps_negative_to_zero(self) -> None:
        self.assertEqual(image_quality.compression_ratio(1000, -100), 0.0)

    def test_clamps_above_one(self) -> None:
        # Pathological case: compressed bytes > original.
        self.assertEqual(image_quality.compression_ratio(100, 500), 1.0)

    def test_zero_original_returns_zero(self) -> None:
        self.assertEqual(image_quality.compression_ratio(0, 200), 0.0)


if __name__ == "__main__":
    unittest.main()
