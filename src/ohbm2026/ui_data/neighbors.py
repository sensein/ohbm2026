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
      "poster_ids": [ ...N ],
      "nearest_ids":  [ [ ...10 ], ...N ],
      "nearest_distances": [ [ ...10 ], ...N ],
      "farthest_ids": [ [ ...10 ], ...N ],
      "farthest_distances": [ [ ...10 ], ...N ]
    }

Stage 10: all ids in this shard are **poster_id** integers (max ~3333,
fits int16). The internal analysis bundles store Oxford submission_id
arrays; the builder translates them via the abstract→poster map before
emit. The UI joins by position: ``poster_ids[i]`` corresponds to row
*i* of the matching cells shard.
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


def _translate_ids(
    payload: Mapping[str, Any], abstract_to_poster: Mapping[int, int]
) -> dict[str, Any]:
    """Translate every abstract_id (Oxford submission id) referenced in
    *payload* to its poster_id integer.

    The internal analysis bundles under
    ``data/outputs/analysis/<cell_key>/neighbors__<state-key>/`` are
    keyed by abstract_id (the embedding matrix's row labels). The
    exported shard speaks poster_id only. Records whose abstract_id has
    no poster mapping (dedup drop or missing poster_id) are filtered
    out positionally so the parallel arrays stay aligned.
    """
    src_ids: list[int] = list(payload["ids"])
    src_nearest_ids: list[list[int]] = list(payload["nearest_ids"])
    src_nearest_dist: list[list[float]] = list(payload["nearest_distances"])
    src_farthest_ids: list[list[int]] = list(payload["farthest_ids"])
    src_farthest_dist: list[list[float]] = list(payload["farthest_distances"])

    poster_ids: list[int] = []
    nearest_ids: list[list[int]] = []
    nearest_dist: list[list[float]] = []
    farthest_ids: list[list[int]] = []
    farthest_dist: list[list[float]] = []

    for i, aid in enumerate(src_ids):
        pid = abstract_to_poster.get(int(aid))
        if pid is None:
            # The abstract was dropped (dedup or missing poster_id); skip
            # both its row entry and the corresponding neighbor entries
            # to keep the parallel arrays aligned with `poster_ids`.
            continue
        # Filter neighbor lists too: skip any neighbor whose abstract_id
        # isn't in the export. The distances list shrinks in lockstep.
        nn_ids_row: list[int] = []
        nn_dist_row: list[float] = []
        for nid, ndist in zip(src_nearest_ids[i], src_nearest_dist[i]):
            np_id = abstract_to_poster.get(int(nid))
            if np_id is None:
                continue
            nn_ids_row.append(int(np_id))
            nn_dist_row.append(float(ndist))
        ff_ids_row: list[int] = []
        ff_dist_row: list[float] = []
        for fid, fdist in zip(src_farthest_ids[i], src_farthest_dist[i]):
            fp_id = abstract_to_poster.get(int(fid))
            if fp_id is None:
                continue
            ff_ids_row.append(int(fp_id))
            ff_dist_row.append(float(fdist))

        poster_ids.append(int(pid))
        nearest_ids.append(nn_ids_row)
        nearest_dist.append(nn_dist_row)
        farthest_ids.append(ff_ids_row)
        farthest_dist.append(ff_dist_row)

    # k is the typical neighbor count post-filter; usually unchanged
    # because the abstract→poster map is essentially 1:1 minus dedup.
    return {
        "k": payload["k"],
        "poster_ids": poster_ids,
        "nearest_ids": nearest_ids,
        "nearest_distances": nearest_dist,
        "farthest_ids": farthest_ids,
        "farthest_distances": farthest_dist,
    }


def iter_neighbours(
    *,
    analysis_root: Path,
    cell_keys: Iterable[str],
    abstract_to_poster: Mapping[int, int],
) -> Iterator[tuple[str, dict[str, Any]]]:
    """Yield ``(cell_key, payload)`` per cell with parallel-array
    neighbours, all ids translated to poster_id integers."""
    if not Path(analysis_root).exists():
        raise Stage6BuildError(f"analysis root not found: {analysis_root}")
    for cell_key in cell_keys:
        payload = _load_per_cell_neighbors(analysis_root, cell_key)
        if payload is None:
            continue
        yield cell_key, _translate_ids(payload, abstract_to_poster)


def build_neighbors(
    *,
    analysis_root: Path,
    cell_keys: Iterable[str],
    abstract_to_poster: Mapping[int, int],
    build_info: Mapping[str, str],
) -> dict[str, dict[str, Any]]:
    """Return ``{cell_key: envelope}`` per cell, with all ids in poster_id
    space. Skips cells without a pre-computed neighbors bundle so the
    build is resilient when ``compute_neighbors.py`` has only run for
    some cells.
    """

    if not Path(analysis_root).exists():
        raise Stage6BuildError(f"analysis root not found: {analysis_root}")
    out: dict[str, dict[str, Any]] = {}
    for cell_key in cell_keys:
        payload = _load_per_cell_neighbors(analysis_root, cell_key)
        if payload is None:
            continue
        translated = _translate_ids(payload, abstract_to_poster)
        envelope = {
            "schema_version": SCHEMA_VERSION,
            "build_info": dict(build_info),
            "cell_key": cell_key,
            **translated,
        }
        out[cell_key] = envelope
    return out
