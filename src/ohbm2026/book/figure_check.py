"""Figure-resolution probe.

`probe_figure` returns the pixel dimensions (or a typed error) for a
local figure asset. `effective_dpi` computes the rendered DPI given
the pixel width and the target display-width inches; the renderer
logs poster_ids whose figures fall below the 300-DPI publication
threshold to `provenance.json` (FR-007 / SC-004). No silent upscale,
no rejection — the figure renders at whatever resolution it has and
the shortfall is audit-logged.
"""

from __future__ import annotations

import pathlib

from PIL import Image, UnidentifiedImageError

# Pillow's `DecompressionBombError` default fires at ~179M px; some
# corpus figures legitimately exceed that. The book treats local
# files as trusted inputs (no random network sources), so we lift
# the limit. Higher-resolution figures are what we WANT — they
# clear the 300 DPI publication threshold more easily.
Image.MAX_IMAGE_PIXELS = None

# Standard print-publication threshold; configurable per FR-006b
# when the renderer's body-width changes (e.g. tufte-book narrower
# body column).
PUBLICATION_DPI_THRESHOLD: int = 300


def probe_figure(
    local_path: pathlib.Path,
) -> tuple[int | None, int | None, str | None]:
    """Open `local_path` with Pillow; return (width, height, error).

    On success: (pixel_width, pixel_height, None).
    On missing file: (None, None, "asset missing").
    On unreadable file: (None, None, f"unreadable: <reason>").
    """
    if not local_path.exists():
        return (None, None, "asset missing")
    try:
        with Image.open(local_path) as img:
            return (img.width, img.height, None)
    except UnidentifiedImageError as exc:
        return (None, None, f"unreadable: {exc}")
    except OSError as exc:
        return (None, None, f"unreadable: {exc}")


def effective_dpi(pixel_width: int, display_width_inches: float) -> float:
    """Return the rendered DPI when a `pixel_width` raster fills
    `display_width_inches` of page-width.

    `effective_dpi(3000, 6.5) ≈ 461.5` — clears the 300-DPI bar.
    `effective_dpi(1500, 6.5) ≈ 230.8` — below; would land in
    `provenance.figures_below_resolution_threshold`.
    """
    if display_width_inches <= 0:
        raise ValueError("display_width_inches must be positive")
    return pixel_width / display_width_inches
