"""Quadtree blue-noise level-of-detail (LOD) for the landing backdrop.

Spec: ``specs/019-neuroscape-semantic-search/plan-lod-backdrop.md``.

The atlas-root + ``/neuroscape/`` UMAP backdrop ships its scatter in
level-of-detail tiers so a browser can paint a coarse silhouette first
and refine — and so atlas-root only range-fetches the tiers it needs.

:func:`assign_lod_levels` assigns every point a level from a
deterministic coarse→fine quadtree. At each resolution it keeps ONE
representative per occupied grid cell that is not already covered by a
coarser representative; the remaining points fall to a final "rest"
level. Two properties follow:

- The cumulative prefix ``levels <= k`` holds at most one point per cell
  at resolution ``resolutions[k]`` → a near-uniform (blue-noise) spatial
  cover that preserves the scatter silhouette while denser regions
  (more occupied cells) still contribute more points.
- ``union(all levels) == all points`` → the full corpus is recoverable
  by loading every tier; nothing is dropped.

No RNG: cells use a single square grid over the global extent, and the
per-cell representative is the smallest ``tiebreak_key`` (default the
point index; pass ``pubmed_id`` for an order-independent, reproducible
assignment). Same input → byte-identical levels.
"""

from __future__ import annotations

from typing import Sequence

import numpy as np

__all__ = ["DEFAULT_RESOLUTIONS", "assign_lod_levels", "lod_coverage"]


# 5 representative tiers + 1 rest tier (``lod0..lod5``). Tuned against
# the real 461k NeuroScape 2D UMAP: tier sizes ≈ [327, 845, 3135, 11670,
# 40291] (≈ 56k representative backdrop — on par with the prior 50k
# stratified sample), rest tier ≈ 405k. Coarse → fine, doubling each
# level. Measured silhouette coverage@64 ≈ [0.16, 0.51, 0.98, 1.0, 1.0]
# → a recognisable shape by ~4.3k points (tier ≤ 2).
DEFAULT_RESOLUTIONS: tuple[int, ...] = (24, 48, 96, 192, 384)

# Reference grid for the provenance "shape maintained" coverage metric.
# A coarse silhouette grid (not the finest tier) so the numbers reflect
# the overall shape a viewer perceives rather than fine point density.
COVERAGE_REFERENCE_RESOLUTION: int = 64


def _square_cell_ids(
    coords: np.ndarray, resolution: int, mins: np.ndarray, span: float
) -> np.ndarray:
    """Cell id per point on a square ``resolution × resolution`` grid.

    A *single* span (the larger of the two axis extents) keeps cells
    square in UMAP space, so the sample is spatially uniform rather than
    per-axis uniform.
    """

    norm = (coords - mins) / span
    cell = np.floor(norm * resolution).astype(np.int64)
    np.clip(cell, 0, resolution - 1, out=cell)
    return cell[:, 0] * resolution + cell[:, 1]


def assign_lod_levels(
    coords: np.ndarray,
    *,
    resolutions: Sequence[int] = DEFAULT_RESOLUTIONS,
    tiebreak_keys: np.ndarray | None = None,
) -> np.ndarray:
    """Return an ``int16`` LOD level per point.

    Levels run ``0`` (coarsest) .. ``len(resolutions)`` (the rest tier).
    """

    coords = np.ascontiguousarray(coords, dtype=np.float64)
    n = coords.shape[0]
    n_levels = len(resolutions)
    if n == 0:
        return np.empty(0, dtype=np.int16)

    if tiebreak_keys is None:
        tiebreak_keys = np.arange(n, dtype=np.int64)
    else:
        tiebreak_keys = np.asarray(tiebreak_keys)
        if tiebreak_keys.shape != (n,):
            raise ValueError(
                f"tiebreak_keys shape {tiebreak_keys.shape} != ({n},)"
            )

    # Rest tier is the default; representatives overwrite it below.
    levels = np.full(n, n_levels, dtype=np.int16)

    mins = coords.min(axis=0)
    span = float((coords.max(axis=0) - mins).max())
    if span <= 0.0:
        span = 1.0

    unclaimed = np.ones(n, dtype=bool)

    for level, resolution in enumerate(resolutions):
        idx = np.flatnonzero(unclaimed)
        if idx.size == 0:
            break

        cell_all = _square_cell_ids(coords, resolution, mins, span)

        # Cells already holding a coarser representative — finer tiers
        # must NOT add a second point to them (keeps the cumulative
        # prefix ≤ 1 point per cell at this resolution).
        covered_pts = levels < level
        covered_cells = np.unique(cell_all[covered_pts]) if covered_pts.any() else None

        cand_cells = cell_all[idx]
        if covered_cells is not None and covered_cells.size:
            is_new = ~np.isin(cand_cells, covered_cells)
        else:
            is_new = np.ones(idx.shape, dtype=bool)

        new_local = np.flatnonzero(is_new)
        if new_local.size == 0:
            continue

        nl_cells = cand_cells[new_local]
        nl_keys = tiebreak_keys[idx][new_local]
        # One representative per new cell: smallest tiebreak key wins.
        order = np.lexsort((nl_keys, nl_cells))
        sorted_cells = nl_cells[order]
        first_in_cell = np.empty(sorted_cells.shape, dtype=bool)
        first_in_cell[0] = True
        first_in_cell[1:] = sorted_cells[1:] != sorted_cells[:-1]

        chosen = idx[new_local[order[first_in_cell]]]
        levels[chosen] = level
        unclaimed[chosen] = False

    return levels


def lod_coverage(
    coords: np.ndarray,
    levels: np.ndarray,
    *,
    reference_resolution: int,
) -> list[float]:
    """Cumulative occupied-cell coverage per level (a "shape maintained"
    metric for provenance).

    ``out[k]`` is the fraction of cells occupied by the *full* corpus
    (at ``reference_resolution``) that are also occupied by points with
    ``level <= k``. Monotone non-decreasing; ``out[-1] == 1.0``.
    """

    n = coords.shape[0]
    if n == 0:
        return []

    coords = np.ascontiguousarray(coords, dtype=np.float64)
    mins = coords.min(axis=0)
    span = float((coords.max(axis=0) - mins).max())
    if span <= 0.0:
        span = 1.0

    cell = _square_cell_ids(coords, reference_resolution, mins, span)
    total = int(np.unique(cell).size)
    if total == 0:
        return []

    max_level = int(np.asarray(levels).max())
    out: list[float] = []
    for k in range(max_level + 1):
        covered = int(np.unique(cell[levels <= k]).size)
        out.append(covered / total)
    return out
