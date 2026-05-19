"""Build ``data/neighbors/<cell_key>.json`` shards for Stage 6.

Each shard carries the per-(model, input) k-nearest + k-farthest neighbor
indices + cosine distances computed offline by ``scripts/compute_neighbors.py``
and stored under ``data/outputs/analysis/<cell_key>/neighbors__<state-key>/``.

Shard shape (array-form for compact JSON):

    {
      "schema_version": "neighbors.v1",
      "build_info": { ... },
      "cell_key": "neuroscape_abstract",
      "k": 10,
      "abstract_ids": [ ...N ],
      "nearest_ids":  [ [ ...10 ], ...N ],
      "nearest_distances": [ [ ...10 ], ...N ],
      "farthest_ids": [ [ ...10 ], ...N ],
      "farthest_distances": [ [ ...10 ], ...N ]
    }

The UI joins by position: ``abstract_ids[i]`` corresponds to row *i* of the
matching cells shard, so given an abstract the client looks up its row index
in the cell shard, then reads the same row of the neighbors shard.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping
from pathlib import Path
from typing import Any

from ohbm2026.ui_data.state_key import Stage6BuildError

SCHEMA_VERSION = "neighbors.v1"


def _round_floats(values: Iterable[float], precision: int = 4) -> list[float]:
    return [round(float(v), precision) for v in values]


def _load_per_cell_neighbors(
    analysis_root: Path, cell_key: str
) -> dict[str, Any] | None:
    """Return the neighbor arrays for *cell_key*, or None when no bundle exists."""

    cell_dir = Path(analysis_root) / cell_key
    if not cell_dir.exists():
        return None
    candidates = sorted(cell_dir.glob("neighbors__*"))
    if not candidates:
        return None
    bundle = candidates[-1]
    try:
        import numpy as np  # type: ignore[import-not-found]
    except ImportError:
        return None
    try:
        ids = np.load(bundle / "ids.npy")
        nearest_ids = np.load(bundle / "nearest_ids.npy")
        nearest_dist = np.load(bundle / "nearest_distances.npy")
        farthest_ids = np.load(bundle / "farthest_ids.npy")
        farthest_dist = np.load(bundle / "farthest_distances.npy")
    except FileNotFoundError:
        return None
    return {
        "ids": [int(x) for x in ids.tolist()],
        "nearest_ids": [[int(x) for x in row] for row in nearest_ids.tolist()],
        "nearest_distances": [_round_floats(row) for row in nearest_dist.tolist()],
        "farthest_ids": [[int(x) for x in row] for row in farthest_ids.tolist()],
        "farthest_distances": [_round_floats(row) for row in farthest_dist.tolist()],
        "k": int(nearest_ids.shape[1]) if nearest_ids.ndim == 2 else 0,
    }


def iter_neighbours(
    *,
    analysis_root: Path,
    cell_keys: Iterable[str],
) -> Iterator[tuple[str, dict[str, Any]]]:
    """Yield ``(cell_key, payload)`` per cell with parallel-array neighbours.

    Stage-10 entry point. Payload shape:
    ``{k, abstract_ids, nearest_ids, nearest_distances,
        farthest_ids, farthest_distances}``.

    Candidate emitters that want row-shaped (abstract_id, …) per-row tuples
    rather than parallel arrays can transpose locally — this iterator
    yields the source-of-truth parallel-array shape to avoid forcing the
    layout decision on every consumer.
    """
    if not Path(analysis_root).exists():
        raise Stage6BuildError(f"analysis root not found: {analysis_root}")
    for cell_key in cell_keys:
        payload = _load_per_cell_neighbors(analysis_root, cell_key)
        if payload is None:
            continue
        yield cell_key, {
            "k": payload["k"],
            "abstract_ids": payload["ids"],
            "nearest_ids": payload["nearest_ids"],
            "nearest_distances": payload["nearest_distances"],
            "farthest_ids": payload["farthest_ids"],
            "farthest_distances": payload["farthest_distances"],
        }


def build_neighbors(
    *,
    analysis_root: Path,
    cell_keys: Iterable[str],
    build_info: Mapping[str, str],
) -> dict[str, dict[str, Any]]:
    """Return ``{cell_key: envelope}`` per cell, skipping cells without a
    pre-computed neighbors bundle. The skip behavior keeps the build
    resilient when ``compute_neighbors.py`` has only run for some cells.
    """

    if not Path(analysis_root).exists():
        raise Stage6BuildError(f"analysis root not found: {analysis_root}")
    out: dict[str, dict[str, Any]] = {}
    for cell_key in cell_keys:
        payload = _load_per_cell_neighbors(analysis_root, cell_key)
        if payload is None:
            continue
        envelope = {
            "schema_version": SCHEMA_VERSION,
            "build_info": dict(build_info),
            "cell_key": cell_key,
            "k": payload["k"],
            "abstract_ids": payload["ids"],
            "nearest_ids": payload["nearest_ids"],
            "nearest_distances": payload["nearest_distances"],
            "farthest_ids": payload["farthest_ids"],
            "farthest_distances": payload["farthest_distances"],
        }
        out[cell_key] = envelope
    return out
