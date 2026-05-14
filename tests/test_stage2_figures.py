"""Tests for `src/ohbm2026/stage2_figures.py`.

- LocalCompressionTests: byte budget, canonical PNG preserved.
- LocalQualityProbeTests: probe fields populated on every figure.
- PerAbstractGroupingTests: one model call per abstract.
- ModelQualityEstimateTests: enum validation via Pydantic.
"""

from __future__ import annotations

import io
import shutil
import tempfile
import unittest
from pathlib import Path
from PIL import Image, ImageDraw

from ohbm2026 import stage2_figures
from ohbm2026.exceptions import EnrichmentError


def _make_png(path: Path, size: tuple[int, int] = (2000, 1500), color: tuple = (200, 200, 200)) -> int:
    """Create a synthetic PNG at `path`, return its byte size."""
    img = Image.new("RGB", size, color)
    draw = ImageDraw.Draw(img)
    # Add some content so the JPEG encoder has actual work to do.
    for i in range(0, size[0], 30):
        draw.line([(i, 0), (i, size[1])], fill=(50, 50, 100), width=2)
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path, format="PNG", optimize=True)
    return path.stat().st_size


class _Fixture:
    """Per-test tmp dir + synthetic PNGs."""
    def __init__(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="ohbm-stage2-fig-"))

    def cleanup(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)


# ----- Compression tests -----------------------------------------------


class LocalCompressionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fx = _Fixture()
        self.addCleanup(self.fx.cleanup)

    def test_compresses_large_png_to_under_300kb(self) -> None:
        big = self.fx.tmp / "big.png"
        _make_png(big, size=(3000, 2000))
        jpeg_bytes, _ = stage2_figures.compress_image(big.read_bytes())
        self.assertLess(len(jpeg_bytes), 300_000)

    def test_canonical_png_unchanged_after_compression(self) -> None:
        png = self.fx.tmp / "asset.png"
        _make_png(png)
        before = png.read_bytes()
        stage2_figures.compress_image(before)
        after = png.read_bytes()
        self.assertEqual(before, after, "compression MUST be in-memory only")

    def test_long_side_capped_at_1024(self) -> None:
        png = self.fx.tmp / "tall.png"
        _make_png(png, size=(4000, 3000))
        jpeg_bytes, _ = stage2_figures.compress_image(
            png.read_bytes(), max_dim=1024,
        )
        from PIL import Image as _Image
        with _Image.open(io.BytesIO(jpeg_bytes)) as im:
            self.assertLessEqual(max(im.size), 1024)


# ----- Local quality probe -------------------------------------------


class LocalQualityProbeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fx = _Fixture()
        self.addCleanup(self.fx.cleanup)

    def test_estimate_dict_has_four_fields(self) -> None:
        png = self.fx.tmp / "asset.png"
        _make_png(png)
        _, estimate = stage2_figures.compress_image(png.read_bytes())
        for key in ("laplacian_variance", "mean_brightness", "native_max_dim", "compression_ratio"):
            self.assertIn(key, estimate)

    def test_compression_ratio_in_unit_interval(self) -> None:
        png = self.fx.tmp / "asset.png"
        _make_png(png)
        _, estimate = stage2_figures.compress_image(png.read_bytes())
        self.assertGreaterEqual(estimate["compression_ratio"], 0.0)
        self.assertLessEqual(estimate["compression_ratio"], 1.0)


# ----- Per-abstract grouping ----------------------------------------


class _FakeResponseFigures:
    def __init__(self, items) -> None:
        self.output_parsed = stage2_figures.FigureInterpretationResponse(figures=items)
        self.usage = _FakeUsage()


class _FakeUsage:
    input_tokens = 5000
    output_tokens = 800
    cached_tokens = 0


class _FakeClientFigures:
    def __init__(self, items: list[stage2_figures.FigureInterpretationItem]) -> None:
        self._items = items
        self.calls = 0
        self.responses = self
    def parse(self, **kwargs):
        self.calls += 1
        return _FakeResponseFigures(self._items)
    def create(self, **kwargs):
        return self.parse(**kwargs)


def _abstract_with_figures(n: int, cwd: Path, abstract_id: int = 1) -> dict:
    """Build a synthetic abstract with N local figure assets."""
    abstract: dict = {
        "id": abstract_id,
        "title": f"abstract {abstract_id}",
        "responses": [
            {"question_name": "Introduction", "value": "intro text"},
            {"question_name": "Methods", "value": "methods text"},
            {"question_name": "Results", "value": "results text"},
        ],
        "figure_urls": [],
        "local_assets": [],
    }
    for i in range(n):
        url = f"https://figs.example/{abstract_id}_{i}.png"
        rel = f"data/primary/assets/{abstract_id}_{i}.png"
        abstract["figure_urls"].append({"url": url, "question_name": "Methods Figure (Optional)"})
        abstract["local_assets"].append({"figure_url": url, "local_path": rel})
        _make_png(cwd / rel)
    return abstract


class PerAbstractGroupingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fx = _Fixture()
        self.addCleanup(self.fx.cleanup)

    def test_single_call_per_abstract_for_two_figures(self) -> None:
        abstract = _abstract_with_figures(2, cwd=self.fx.tmp)
        items = [
            stage2_figures.FigureInterpretationItem(
                figure_index=i + 1,
                interpretation=f"interp {i+1}",
                keywords=["a"],
                ocr_text=None,
                model_quality_estimate="high",
            )
            for i in range(2)
        ]
        client = _FakeClientFigures(items)
        records, summary = stage2_figures.run_figure_component(
            abstract, model_id="gpt-5.4-mini", flex_enabled=True,
            client=client, cwd=self.fx.tmp,
        )
        self.assertEqual(client.calls, 1, "should be exactly one Responses API call")
        self.assertEqual(len(records), 2)
        self.assertEqual(summary.figure_count, 2)

    def test_per_figure_local_quality_estimate_populated(self) -> None:
        abstract = _abstract_with_figures(2, cwd=self.fx.tmp)
        items = [
            stage2_figures.FigureInterpretationItem(
                figure_index=i + 1, interpretation="x",
                keywords=[], ocr_text=None, model_quality_estimate="medium",
            )
            for i in range(2)
        ]
        client = _FakeClientFigures(items)
        records, _ = stage2_figures.run_figure_component(
            abstract, model_id="gpt-5.4-mini", flex_enabled=True,
            client=client, cwd=self.fx.tmp,
        )
        for record in records:
            self.assertIn("local_quality_estimate", record)
            self.assertIn("model_quality_estimate", record)
            self.assertEqual(record["model_quality_estimate"], "medium")

    def test_missing_local_asset_raises_typed_error(self) -> None:
        abstract = {
            "id": 1,
            "title": "x",
            "responses": [],
            "figure_urls": [{"url": "https://missing/1.png", "question_name": "Methods Figure (Optional)"}],
            "local_assets": [{"figure_url": "https://missing/1.png", "local_path": "data/primary/assets/missing.png"}],
        }
        client = _FakeClientFigures([])
        with self.assertRaises(EnrichmentError) as ctx:
            stage2_figures.run_figure_component(
                abstract, model_id="gpt-5.4-mini", flex_enabled=True,
                client=client, cwd=self.fx.tmp,
            )
        self.assertIn("local asset missing", str(ctx.exception))


# ----- Model quality enum enforcement -------------------------------


class ModelQualityEstimateTests(unittest.TestCase):
    def test_off_enum_value_raises_validation_error(self) -> None:
        from pydantic import ValidationError
        with self.assertRaises(ValidationError):
            stage2_figures.FigureInterpretationItem(
                figure_index=1, interpretation="x", keywords=[],
                ocr_text=None, model_quality_estimate="terrible",
            )

    def test_all_documented_enum_values_accepted(self) -> None:
        for value in stage2_figures.MODEL_QUALITY_ENUM:
            stage2_figures.FigureInterpretationItem(
                figure_index=1, interpretation="x", keywords=[],
                ocr_text=None, model_quality_estimate=value,
            )


if __name__ == "__main__":
    unittest.main()
