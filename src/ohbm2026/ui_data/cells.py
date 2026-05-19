"""Build ``data/cells/<model>_<input>.json`` shards for Stage 6 (T016).

The Stage 4 rollup stores per-abstract coordinates + cluster ids in a wide
``annotations`` table with columns like ``umap2d_<model>_x`` /
``community_<model>_<input>`` / ``topic_cluster_<model>_<input>`` /
``neuroscape_cluster_<input>``. We project that wide shape into 15 per-cell
shards keyed by ``cell_key = "<model>_<input>"`` and positionally joined to
the abstracts shard's ordering.
"""

from __future__ import annotations

import math
import sqlite3
from collections.abc import Iterable, Iterator, Mapping
from pathlib import Path
from typing import Any

from ohbm2026.ui_data.manifest import discover_cells
from ohbm2026.ui_data.state_key import Stage6BuildError

SCHEMA_VERSION = "cell.v1"
NEUROSCAPE_MODEL = "neuroscape"


def _load_per_cell_projections(
    analysis_root: Path, cell_key: str
) -> tuple[dict[int, tuple[float, float]], dict[int, tuple[float, float, float]]]:
    """Return ``(umap2d_by_id, umap3d_by_id)`` for *cell_key*.

    Reads `data/outputs/analysis/<cell_key>/projections__<state-key>/`:
    ``ids.npy`` + ``umap2d_coords.npy`` + ``umap3d_coords.npy``. Empty maps
    when the bundle doesn't exist (older Stage 4 runs may have only
    populated the wide annotations table). Lazy-imports numpy so the
    builder still works without `[ui]` extras installed when only the
    annotations-table fallback is needed.
    """

    bundle_root = Path(analysis_root) / cell_key
    if not bundle_root.exists():
        return {}, {}
    projection_dirs = sorted(bundle_root.glob("projections__*"))
    if not projection_dirs:
        return {}, {}
    bundle_dir = projection_dirs[-1]  # newest by lexicographic; tie-break is fine
    try:
        import numpy as np  # type: ignore[import-not-found]
    except ImportError:
        return {}, {}
    try:
        ids = np.load(bundle_dir / "ids.npy")
        coords2d = np.load(bundle_dir / "umap2d_coords.npy")
        coords3d = np.load(bundle_dir / "umap3d_coords.npy")
    except FileNotFoundError:
        return {}, {}
    out2d: dict[int, tuple[float, float]] = {}
    out3d: dict[int, tuple[float, float, float]] = {}
    for i, aid in enumerate(ids):
        out2d[int(aid)] = (float(coords2d[i, 0]), float(coords2d[i, 1]))
        out3d[int(aid)] = (float(coords3d[i, 0]), float(coords3d[i, 1]), float(coords3d[i, 2]))
    return out2d, out3d


def _load_annotations(rollup_db: Path) -> dict[int, dict[str, Any]]:
    """Return ``annotations`` rows keyed by ``abstract_id``."""

    rows: dict[int, dict[str, Any]] = {}
    with sqlite3.connect(str(rollup_db)) as conn:
        conn.row_factory = sqlite3.Row
        for row in conn.execute("SELECT * FROM annotations"):
            rows[int(row["abstract_id"])] = dict(row)
    return rows


def _row_to_cell_record(
    abstract_id: int,
    row: Mapping[str, Any] | None,
    model: str,
    input_key: str,
    umap2d_by_id: Mapping[int, tuple[float, float]] | None = None,
    umap3d_by_id: Mapping[int, tuple[float, float, float]] | None = None,
) -> dict[str, Any]:
    """Project the wide ``annotations`` row into a per-(cell, abstract) record.

    UMAP coordinates come from the per-(model, input) ``projections__*``
    bundle when available — that gives each cell its own layout. If the
    per-bundle data is missing the wide annotations table (per-model only)
    is used as a fallback. Missing cluster ids surface as ``-1`` to keep
    the schema dense.
    """

    def _val(key: str, default: Any = None) -> Any:
        if row is None:
            return default
        v = row.get(key)
        return default if v is None else v

    coord2d = (umap2d_by_id or {}).get(int(abstract_id))
    coord3d = (umap3d_by_id or {}).get(int(abstract_id))
    umap2d = (
        [float(coord2d[0]), float(coord2d[1])]
        if coord2d is not None
        else [float(_val(f"umap2d_{model}_x", 0.0)), float(_val(f"umap2d_{model}_y", 0.0))]
    )
    umap3d = (
        [float(coord3d[0]), float(coord3d[1]), float(coord3d[2])]
        if coord3d is not None
        else [
            float(_val(f"umap3d_{model}_x", 0.0)),
            float(_val(f"umap3d_{model}_y", 0.0)),
            float(_val(f"umap3d_{model}_z", 0.0)),
        ]
    )
    # `umap_missing` lets the UI filter out abstracts that don't have a
    # projection in this cell (e.g. voyage_claims drops 2 abstracts that
    # lacked claim embeddings).
    has_projection = coord2d is not None
    record: dict[str, Any] = {
        "abstract_id": int(abstract_id),
        "umap2d": umap2d,
        "umap3d": umap3d,
        "umap_missing": not has_projection if (umap2d_by_id is not None or umap3d_by_id is not None) else False,
        "community_id": int(_val(f"community_{model}_{input_key}", -1)),
        "topic_cluster_id": int(_val(f"topic_cluster_{model}_{input_key}", -1)),
    }
    if model == NEUROSCAPE_MODEL:
        cluster_id = _val(f"neuroscape_cluster_neuroscape_{input_key}", -1)
        cluster_distance = _val(f"neuroscape_cluster_distance_neuroscape_{input_key}", 0.0)
        record["neuroscape_cluster_id"] = int(cluster_id) if cluster_id is not None else -1
        record["neuroscape_cluster_distance"] = (
            float(cluster_distance) if cluster_distance is not None else 0.0
        )
    return record


def build_cells_shards(
    *,
    rollup_db: Path,
    abstract_ids: Iterable[int],
    analysis_root: Path | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """Return ``{cell_key: [row, ...]}`` for every discovered cell.

    Each list is ordered to match *abstract_ids* (positional join with
    ``abstracts.json``; cells.md §4 invariant). When *analysis_root* is
    supplied each cell's UMAP coordinates are read from its own
    ``projections__*`` bundle (per-(model, input) layout); otherwise the
    builder falls back to the wide ``annotations`` table (per-model only).
    """

    rollup_path = Path(rollup_db)
    if not rollup_path.exists():
        raise Stage6BuildError(f"Stage 4 rollup not found: {rollup_path}")
    ordered_ids = list(abstract_ids)
    annotations = _load_annotations(rollup_path)
    cells = discover_cells(rollup_path)

    out: dict[str, list[dict[str, Any]]] = {}
    for model, input_key in cells:
        cell_key = f"{model}_{input_key}"
        u2d, u3d = (
            _load_per_cell_projections(analysis_root, cell_key)
            if analysis_root is not None
            else ({}, {})
        )
        out[cell_key] = [
            _row_to_cell_record(
                aid,
                annotations.get(aid),
                model,
                input_key,
                umap2d_by_id=u2d,
                umap3d_by_id=u3d,
            )
            for aid in ordered_ids
        ]
    return out


def iter_cells(
    *,
    rollup_db: Path,
    abstract_ids: Iterable[int],
    analysis_root: Path | None = None,
) -> Iterator[tuple[str, list[dict[str, Any]]]]:
    """Yield ``(cell_key, [row, ...])`` for every discovered cell.

    Stage-10 entry point: candidate emitters (Parquet, SQLite, …) consume
    one cell at a time so per-cell table files can be written without
    holding all 15 cells in memory simultaneously. The row list is still
    materialised per-cell because the rollup table is queried in bulk
    (one DB read per cell); per-row iteration there would be wasteful.
    """
    shards = build_cells_shards(
        rollup_db=rollup_db, abstract_ids=abstract_ids, analysis_root=analysis_root
    )
    yield from shards.items()


def build_cells(
    *,
    rollup_db: Path,
    abstract_ids: Iterable[int],
    build_info: Mapping[str, str],
    analysis_root: Path | None = None,
) -> dict[str, dict[str, Any]]:
    """Return ``{cell_key: envelope}`` per data-model.md §4."""

    shards = build_cells_shards(
        rollup_db=rollup_db,
        abstract_ids=abstract_ids,
        analysis_root=analysis_root,
    )
    return {
        cell_key: {
            "schema_version": SCHEMA_VERSION,
            "build_info": dict(build_info),
            "cell_key": cell_key,
            "rows": rows,
        }
        for cell_key, rows in shards.items()
    }
