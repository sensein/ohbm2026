"""Stage 4 canonical rollup writer.

Reads every per-`(model, input_source, analysis_kind)` bundle under the
analysis output root and emits **two shape-equivalent files** at
`data/outputs/analysis/annotations__<state-key>.{parquet,sqlite}`:

- `annotations` — one row per abstract; wide-table columns
  `umap2d_<model>_{x,y}` / `umap3d_<model>_{x,y,z}` /
  `community_<model>_<input>` / `neuroscape_cluster_<model>_<input>` /
  `neuroscape_cluster_distance_<model>_<input>` /
  `topic_cluster_<model>_<input>`. Missing analyses for an abstract are
  encoded as nulls.
- `cluster_topics` — join table keyed by
  `(clustering_method, model_key, input_source, cluster_id)` → topic
  keywords / title / description / focus. For the `neuroscape_clusters`
  method, labels come verbatim from the NeuroScape `cluster_table.csv`
  (no spaCy/LLM pipeline); for `communities` and `topic_clusters`, the
  per-bundle `topics.json` is the source.

Both writes are atomic (temp-file + rename); parquet uses pyarrow's
native writer, SQLite uses the stdlib `sqlite3` module.
"""

from __future__ import annotations

import csv
import json
import sqlite3
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import numpy as np

from ohbm2026.analyze.storage import iter_analysis_bundles

__all__ = [
    "RollupRow",
    "ClusterTopicsRow",
    "build_rollup_tables",
    "load_neuroscape_cluster_table",
    "write_rollup",
]


@dataclass(frozen=True)
class RollupRow:
    """One row of the `annotations` table — `abstract_id` + cell values keyed by column name."""

    abstract_id: int
    columns: dict[str, Any]


@dataclass(frozen=True)
class ClusterTopicsRow:
    """One row of the `cluster_topics` join table."""

    clustering_method: str
    model_key: str
    input_source: str
    cluster_id: int
    topic_keywords: str  # JSON-encoded list[str]
    topic_title: str
    topic_description: str
    topic_focus: str


# ---------------------------------------------------------------------------
# Bundle scanning + table construction
# ---------------------------------------------------------------------------


def _parse_input_key(input_key: str) -> tuple[str, str] | None:
    """Parse `<model>_<input>` directory name into a (model, input) pair.

    The Stage 4 contract uses an underscore separator. Models in the
    Stage 4 v1 lineup are voyage / minilm / openai / pubmedbert /
    neuroscape; inputs are `abstract` / `claims` / arbitrary
    Stage 3 component names. We split on the FIRST underscore because
    the model keys are all single tokens.
    """
    if "_" not in input_key:
        return None
    model, input_source = input_key.split("_", 1)
    return model, input_source


def _read_bundle_payload(bundle_dir: Path) -> dict[str, Any] | None:
    """Read a bundle into a small dict: kind, ids, payload arrays, topics, metadata."""
    metadata_path = bundle_dir / "metadata.json"
    ids_path = bundle_dir / "ids.npy"
    if not metadata_path.exists() or not ids_path.exists():
        return None
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    name = bundle_dir.name
    kind = name.split("__", 1)[0]
    record: dict[str, Any] = {
        "kind": kind,
        "ids": np.load(ids_path),
        "metadata": metadata,
        "payload": {},
    }
    for npy_path in sorted(bundle_dir.glob("*.npy")):
        if npy_path.name == "ids.npy":
            continue
        record["payload"][npy_path.stem] = np.load(npy_path)
    topics_path = bundle_dir / "topics.json"
    if topics_path.exists():
        record["topics"] = {
            int(k): v
            for k, v in json.loads(topics_path.read_text(encoding="utf-8")).items()
        }
    return record


def load_neuroscape_cluster_table(table_path: Path) -> dict[int, dict[str, Any]]:
    """Read `cluster_table.csv` (NeuroScape sidecar) into a `{cluster_id: {...}}` map.

    Expected columns: `Cluster ID`, `Title`, `Description`, `Keywords`
    (JSON-encoded list), `Focus`. Missing columns default to empty
    strings / empty lists.
    """
    rows: dict[int, dict[str, Any]] = {}
    if not table_path.exists():
        return rows
    with table_path.open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            try:
                cid = int(row.get("Cluster ID") or row.get("cluster_id"))
            except (TypeError, ValueError):
                continue
            keywords_raw = row.get("Keywords", "") or ""
            try:
                keywords = json.loads(keywords_raw) if keywords_raw else []
                if not isinstance(keywords, list):
                    keywords = [str(keywords)]
            except json.JSONDecodeError:
                keywords = [keywords_raw]
            rows[cid] = {
                "Title": row.get("Title", "") or "",
                "Description": row.get("Description", "") or "",
                "Keywords": keywords,
                "Focus": row.get("Focus", "") or "",
            }
    return rows


def build_rollup_tables(
    output_root: Path,
    *,
    neuroscape_cluster_table: dict[int, dict[str, Any]] | None = None,
) -> tuple[list[str], list[RollupRow], list[ClusterTopicsRow]]:
    """Scan every bundle under `output_root` and return (column_order, annotations, cluster_topics).

    `column_order` follows the contracts/rollup.md ordering:
        `abstract_id` first, then per-model UMAP columns sorted by
        `(model_key)`, then per-(model, input) cluster columns sorted
        by `(kind, model_key, input_source)`. Re-ordering CLI flags
        does not change the column order — the canonical sort lives
        here.
    """
    annotations: dict[int, dict[str, Any]] = {}
    cluster_topics: list[ClusterTopicsRow] = []
    seen_models: set[str] = set()
    seen_cluster_cells: set[tuple[str, str, str]] = set()  # (kind, model, input)
    nsc_table = neuroscape_cluster_table or {}

    for bundle_dir in iter_analysis_bundles(output_root):
        input_key = bundle_dir.parent.name
        parsed = _parse_input_key(input_key)
        if parsed is None:
            continue
        model_key, input_source = parsed
        record = _read_bundle_payload(bundle_dir)
        if record is None:
            continue
        seen_models.add(model_key)
        kind = record["kind"]
        ids = record["ids"]
        topics = record.get("topics") or {}

        if kind == "projections":
            coords2d = record["payload"].get("umap2d_coords")
            coords3d = record["payload"].get("umap3d_coords")
            for idx, abstract_id in enumerate(ids.tolist()):
                row = annotations.setdefault(int(abstract_id), {})
                if coords2d is not None and idx < len(coords2d):
                    row[f"umap2d_{model_key}_x"] = float(coords2d[idx][0])
                    row[f"umap2d_{model_key}_y"] = float(coords2d[idx][1])
                if coords3d is not None and idx < len(coords3d):
                    row[f"umap3d_{model_key}_x"] = float(coords3d[idx][0])
                    row[f"umap3d_{model_key}_y"] = float(coords3d[idx][1])
                    row[f"umap3d_{model_key}_z"] = float(coords3d[idx][2])

        elif kind == "communities":
            community_ids = record["payload"].get("community_ids")
            col = f"community_{model_key}_{input_source}"
            if community_ids is not None:
                for idx, abstract_id in enumerate(ids.tolist()):
                    annotations.setdefault(int(abstract_id), {})[col] = int(
                        community_ids[idx]
                    )
                seen_cluster_cells.add(("communities", model_key, input_source))
                for cluster_id, topic in topics.items():
                    cluster_topics.append(
                        ClusterTopicsRow(
                            clustering_method="communities",
                            model_key=model_key,
                            input_source=input_source,
                            cluster_id=int(cluster_id),
                            topic_keywords=json.dumps(
                                list(topic.get("Keywords", []))
                            ),
                            topic_title=str(topic.get("Title", "") or ""),
                            topic_description=str(topic.get("Description", "") or ""),
                            topic_focus=str(topic.get("Focus", "") or ""),
                        )
                    )

        elif kind == "neuroscape_clusters":
            cluster_ids = record["payload"].get("neuroscape_cluster_ids")
            distances = record["payload"].get("neuroscape_cluster_distances")
            id_col = f"neuroscape_cluster_{model_key}_{input_source}"
            d_col = f"neuroscape_cluster_distance_{model_key}_{input_source}"
            if cluster_ids is not None:
                for idx, abstract_id in enumerate(ids.tolist()):
                    row = annotations.setdefault(int(abstract_id), {})
                    row[id_col] = int(cluster_ids[idx])
                    if distances is not None:
                        row[d_col] = float(distances[idx])
                # Join in cluster-table labels for every cluster_id this
                # bundle assigned at least one abstract to.
                unique_clusters = sorted(set(int(c) for c in cluster_ids.tolist()))
                seen_cluster_cells.add(
                    ("neuroscape_clusters", model_key, input_source)
                )
                for cid in unique_clusters:
                    label = nsc_table.get(cid, {})
                    cluster_topics.append(
                        ClusterTopicsRow(
                            clustering_method="neuroscape_clusters",
                            model_key=model_key,
                            input_source=input_source,
                            cluster_id=cid,
                            topic_keywords=json.dumps(
                                list(label.get("Keywords", []))
                            ),
                            topic_title=str(label.get("Title", "") or ""),
                            topic_description=str(label.get("Description", "") or ""),
                            topic_focus=str(label.get("Focus", "") or ""),
                        )
                    )

        elif kind == "topic_clusters":
            topic_cluster_ids = record["payload"].get("topic_cluster_ids")
            col = f"topic_cluster_{model_key}_{input_source}"
            if topic_cluster_ids is not None:
                for idx, abstract_id in enumerate(ids.tolist()):
                    annotations.setdefault(int(abstract_id), {})[col] = int(
                        topic_cluster_ids[idx]
                    )
                seen_cluster_cells.add(("topic_clusters", model_key, input_source))
                for cluster_id, topic in topics.items():
                    cluster_topics.append(
                        ClusterTopicsRow(
                            clustering_method="topic_clusters",
                            model_key=model_key,
                            input_source=input_source,
                            cluster_id=int(cluster_id),
                            topic_keywords=json.dumps(
                                list(topic.get("Keywords", []))
                            ),
                            topic_title=str(topic.get("Title", "") or ""),
                            topic_description=str(topic.get("Description", "") or ""),
                            topic_focus=str(topic.get("Focus", "") or ""),
                        )
                    )

    # Build canonical column ordering.
    ordered_columns: list[str] = ["abstract_id"]
    for model in sorted(seen_models):
        for suffix in ("umap2d_x", "umap2d_y", "umap3d_x", "umap3d_y", "umap3d_z"):
            # Reconstruct the actual column name shape we wrote into row dicts.
            if suffix.startswith("umap2d_"):
                base = "umap2d_"
                axis = suffix.split("_", 1)[1]
            else:
                base = "umap3d_"
                axis = suffix.split("_", 1)[1]
            ordered_columns.append(f"{base}{model}_{axis}")
    # Cluster columns sorted by (kind, model, input)
    cluster_kind_order = {"communities": 0, "neuroscape_clusters": 1, "topic_clusters": 2}
    for kind, model, input_source in sorted(
        seen_cluster_cells, key=lambda x: (cluster_kind_order.get(x[0], 99), x[1], x[2])
    ):
        if kind == "communities":
            ordered_columns.append(f"community_{model}_{input_source}")
        elif kind == "neuroscape_clusters":
            ordered_columns.append(f"neuroscape_cluster_{model}_{input_source}")
            ordered_columns.append(f"neuroscape_cluster_distance_{model}_{input_source}")
        elif kind == "topic_clusters":
            ordered_columns.append(f"topic_cluster_{model}_{input_source}")

    rows = [
        RollupRow(abstract_id=aid, columns=cols)
        for aid, cols in sorted(annotations.items())
    ]
    return ordered_columns, rows, cluster_topics


# ---------------------------------------------------------------------------
# Writers
# ---------------------------------------------------------------------------


def _write_parquet(
    out_path: Path,
    columns: list[str],
    rows: list[RollupRow],
    cluster_topics: list[ClusterTopicsRow],
) -> None:
    """Atomic parquet write — both `annotations` and `cluster_topics`
    written as a single multi-table parquet file is not standard;
    Parquet is single-table, so we write `annotations` to the given
    path and `cluster_topics` to a sibling file
    `<stem>__cluster_topics.parquet`.
    """
    import pyarrow as pa  # lazy
    import pyarrow.parquet as pq

    # Build column-major dict for the annotations table
    column_data: dict[str, list[Any]] = {c: [] for c in columns}
    for row in rows:
        column_data["abstract_id"].append(row.abstract_id)
        for c in columns[1:]:
            column_data[c].append(row.columns.get(c))

    table = pa.Table.from_pydict(column_data)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_path.with_suffix(out_path.suffix + ".tmp")
    pq.write_table(table, tmp)
    tmp.replace(out_path)

    # Sibling cluster_topics parquet
    ct_path = out_path.with_name(f"{out_path.stem}__cluster_topics.parquet")
    ct_table = pa.Table.from_pydict(
        {
            "clustering_method": [r.clustering_method for r in cluster_topics],
            "model_key": [r.model_key for r in cluster_topics],
            "input_source": [r.input_source for r in cluster_topics],
            "cluster_id": [r.cluster_id for r in cluster_topics],
            "topic_keywords": [r.topic_keywords for r in cluster_topics],
            "topic_title": [r.topic_title for r in cluster_topics],
            "topic_description": [r.topic_description for r in cluster_topics],
            "topic_focus": [r.topic_focus for r in cluster_topics],
        }
    )
    tmp = ct_path.with_suffix(ct_path.suffix + ".tmp")
    pq.write_table(ct_table, tmp)
    tmp.replace(ct_path)


def _write_sqlite(
    out_path: Path,
    columns: list[str],
    rows: list[RollupRow],
    cluster_topics: list[ClusterTopicsRow],
) -> None:
    """Atomic SQLite write — writes both tables into one db file."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_path.with_suffix(out_path.suffix + ".tmp")
    if tmp.exists():
        tmp.unlink()
    conn = sqlite3.connect(str(tmp))
    try:
        cur = conn.cursor()
        # Build annotations schema. Strings are unused here; everything
        # else is REAL or INTEGER. We use ANY-flavored columns since
        # SQLite is type-permissive — `abstract_id` is the only NOT NULL.
        col_defs = ["abstract_id INTEGER PRIMARY KEY"]
        for c in columns[1:]:
            sql_type = "INTEGER" if c.startswith(("community_", "neuroscape_cluster_", "topic_cluster_")) and not c.startswith("neuroscape_cluster_distance_") else "REAL"
            # Allow nulls. SQLite accepts mixed types but we declare for clarity.
            col_defs.append(f'"{c}" {sql_type}')
        cur.execute(f"CREATE TABLE annotations ({', '.join(col_defs)})")
        placeholders = ", ".join("?" for _ in columns)
        col_names_sql = ", ".join(f'"{c}"' for c in columns)
        cur.executemany(
            f"INSERT INTO annotations ({col_names_sql}) VALUES ({placeholders})",
            [
                tuple(
                    row.abstract_id if c == "abstract_id" else row.columns.get(c)
                    for c in columns
                )
                for row in rows
            ],
        )

        cur.execute(
            """
            CREATE TABLE cluster_topics (
                clustering_method TEXT NOT NULL,
                model_key TEXT NOT NULL,
                input_source TEXT NOT NULL,
                cluster_id INTEGER NOT NULL,
                topic_keywords TEXT,
                topic_title TEXT,
                topic_description TEXT,
                topic_focus TEXT,
                PRIMARY KEY (clustering_method, model_key, input_source, cluster_id)
            )
            """
        )
        cur.executemany(
            """
            INSERT OR REPLACE INTO cluster_topics
            (clustering_method, model_key, input_source, cluster_id,
             topic_keywords, topic_title, topic_description, topic_focus)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    r.clustering_method,
                    r.model_key,
                    r.input_source,
                    r.cluster_id,
                    r.topic_keywords,
                    r.topic_title,
                    r.topic_description,
                    r.topic_focus,
                )
                for r in cluster_topics
            ],
        )
        conn.commit()
    finally:
        conn.close()
    tmp.replace(out_path)


def write_rollup(
    output_root: Path,
    *,
    parquet_path: Path,
    sqlite_path: Path,
    neuroscape_cluster_table: dict[int, dict[str, Any]] | None = None,
) -> tuple[Path, Path]:
    """Scan every analysis bundle under `output_root` and write the
    canonical `annotations.{parquet,sqlite}` rollup pair atomically.

    Returns `(parquet_path, sqlite_path)`. The two files are
    content-equivalent: identical column count, identical row count,
    identical cluster_topics rows.
    """
    columns, rows, cluster_topics = build_rollup_tables(
        output_root, neuroscape_cluster_table=neuroscape_cluster_table
    )
    _write_parquet(parquet_path, columns, rows, cluster_topics)
    _write_sqlite(sqlite_path, columns, rows, cluster_topics)
    return parquet_path, sqlite_path
