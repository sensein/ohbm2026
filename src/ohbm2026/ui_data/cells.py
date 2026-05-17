"""Build ``data/cells/<model>_<input>.json`` shards for Stage 6 (T016).

The Stage 4 rollup stores per-abstract coordinates + cluster ids in a wide
``annotations`` table with columns like ``umap2d_<model>_x`` /
``community_<model>_<input>`` / ``topic_cluster_<model>_<input>`` /
``neuroscape_cluster_<input>``. We project that wide shape into 15 per-cell
shards keyed by ``cell_key = "<model>_<input>"`` and positionally joined to
the abstracts shard's ordering.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from ohbm2026.ui_data.manifest import discover_cells
from ohbm2026.ui_data.state_key import Stage6BuildError

SCHEMA_VERSION = "cell.v1"
NEUROSCAPE_MODEL = "neuroscape"


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
) -> dict[str, Any]:
    """Project the wide ``annotations`` row into a per-(cell, abstract) record.

    Coordinates fall back to ``[0.0, 0.0]`` / ``[0.0, 0.0, 0.0]`` only when
    upstream produced NULL (an abstract present in the corpus but absent from
    the rollup, which the builder will flag via the cross-shard invariants).
    Missing cluster ids surface as ``-1`` to keep the schema dense.
    """

    def _val(key: str, default: Any = None) -> Any:
        if row is None:
            return default
        v = row.get(key)
        return default if v is None else v

    record: dict[str, Any] = {
        "abstract_id": int(abstract_id),
        "umap2d": [float(_val(f"umap2d_{model}_x", 0.0)), float(_val(f"umap2d_{model}_y", 0.0))],
        "umap3d": [
            float(_val(f"umap3d_{model}_x", 0.0)),
            float(_val(f"umap3d_{model}_y", 0.0)),
            float(_val(f"umap3d_{model}_z", 0.0)),
        ],
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
) -> dict[str, list[dict[str, Any]]]:
    """Return ``{cell_key: [row, ...]}`` for every discovered cell.

    Each list is ordered to match *abstract_ids* (positional join with
    ``abstracts.json``; cells.md §4 invariant).
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
        out[cell_key] = [
            _row_to_cell_record(aid, annotations.get(aid), model, input_key)
            for aid in ordered_ids
        ]
    return out


def build_cells(
    *,
    rollup_db: Path,
    abstract_ids: Iterable[int],
    build_info: Mapping[str, str],
) -> dict[str, dict[str, Any]]:
    """Return ``{cell_key: envelope}`` per data-model.md §4."""

    shards = build_cells_shards(rollup_db=rollup_db, abstract_ids=abstract_ids)
    return {
        cell_key: {
            "schema_version": SCHEMA_VERSION,
            "build_info": dict(build_info),
            "cell_key": cell_key,
            "rows": rows,
        }
        for cell_key, rows in shards.items()
    }
