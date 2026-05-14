"""Local image-quality probe helpers for Stage 2.1.

Pure functions over a PIL `Image` object and the raw byte sequence
of the encoded form. No I/O — callers open the file and read bytes
themselves so this module can be exercised against in-memory
fixtures without disk access.

Used by `stage2_figures.run_figure_component` to populate the
`local_quality_estimate` dict on every `FigureInterpretation`
record. The four-field shape is documented in
`specs/004-enrich-production-wiring/data-model.md` §2.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from PIL.Image import Image as PILImage

__all__ = [
    "laplacian_variance",
    "mean_brightness",
    "native_max_dim",
    "compression_ratio",
    "BLUR_THRESHOLD_ADVISORY",
]

# Advisory (NOT enforcement) — Laplacian variance below this value
# usually indicates a blurry image. The orchestrator records the
# raw number and does NOT auto-drop blurry figures (research.md §2).
BLUR_THRESHOLD_ADVISORY: float = 100.0


def laplacian_variance(image: "PILImage") -> float:
    """Variance of a 3x3 Laplacian filter on the grayscale image.

    Lower values indicate blurriness. Threshold ~100 is the
    advisory cutoff used in OpenCV-style blur detection.
    """
    from PIL import ImageFilter, ImageStat

    gray = image.convert("L")
    filtered = gray.filter(
        ImageFilter.Kernel(
            (3, 3),
            [0, 1, 0, 1, -4, 1, 0, 1, 0],
            scale=1,
            offset=0,
        )
    )
    return float(ImageStat.Stat(filtered).var[0])


def mean_brightness(image: "PILImage") -> float:
    """Mean grayscale intensity, 0..255.

    Near-zero values flag dark scans; near-255 values flag washed-
    out scans.
    """
    from PIL import ImageStat

    gray = image.convert("L")
    return float(ImageStat.Stat(gray).mean[0])


def native_max_dim(image: "PILImage") -> int:
    """Max(width, height) of the original image, in pixels.

    Used to surface oddly-small or oddly-large inputs in
    provenance — the model sees the resized 1024-px form, but the
    operator may want to know whether the source was a thumbnail
    or a poster-sized scan.
    """
    width, height = image.size
    return int(max(width, height))


def compression_ratio(original_bytes: int, compressed_bytes: int) -> float:
    """`compressed_bytes / original_bytes`, clamped to [0.0, 1.0].

    Used to flag figures that compressed poorly (often line-art
    / diagram content where JPEG performs poorly).
    """
    if original_bytes <= 0:
        return 0.0
    ratio = float(compressed_bytes) / float(original_bytes)
    if ratio < 0.0:
        return 0.0
    if ratio > 1.0:
        return 1.0
    return ratio
