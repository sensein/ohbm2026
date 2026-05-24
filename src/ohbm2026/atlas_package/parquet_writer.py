"""Stage 15 parquet writer — emits ``neuroscape.parquet`` + ``atlas.parquet``.

Spec: ``specs/015-neuroscape-context/`` —
``contracts/parquet-schemas.md`` (column types, nullability, table
names) + data-model.md (entity surface) + R-009
(``CrossParquetDriftError``) + the 2026-05-23 clarification (no body
columns in ``neuroscape.parquet/articles``; bodies are fetched at
view time per FR-019a).

The outer-row layout matches Stage 10's ``parquet_single`` shape: one
outer row per inner table with ``(table_name: STRING,
table_bytes: LARGE_BINARY)`` and ``row_group_size=1`` so the browser-
side decoder can range-fetch a single inner table at a time.

Public surface:

- :func:`write_neuroscape_parquet` — emits ``neuroscape.parquet``.
- :func:`write_atlas_parquet` — emits ``atlas.parquet`` (embeds
  ``sibling_state_keys`` per R-012).
- :func:`assert_cluster_tables_match` — orchestrator-side invariant
  asserting the ``clusters`` row groups in both parquets are row-
  for-row identical; raises :class:`CrossParquetDriftError`.
"""

from __future__ import annotations

import io
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

from ohbm2026.exceptions import CrossParquetDriftError

from .neighbour_index import KnnResult
from .neuroscape_loader import ArticleHeader, NeuroScapeCluster
from .ohbm_projector import ProjectionResult

__all__ = [
    "write_neuroscape_parquet",
    "write_atlas_parquet",
    "assert_cluster_tables_match",
]


# Mirror Stage 10's outer/inner parquet write kwargs.
_INNER_PARQUET_KWARGS = {
    "compression": "zstd",
    "compression_level": 3,
    "use_dictionary": True,
    "write_statistics": True,
}

_OUTER_PARQUET_KWARGS = {
    "compression": "zstd",
    "compression_level": 3,
    "use_dictionary": False,
    "write_statistics": True,
    "row_group_size": 1,
}


# ---------------------------------------------------------------------------
# Inner-table builders
# ---------------------------------------------------------------------------


def _to_inner_parquet_bytes(table: pa.Table) -> bytes:
    """Serialise one inner table to Parquet bytes for embedding in
    the outer file's ``table_bytes`` BLOB column."""

    buf = io.BytesIO()
    pq.write_table(table, buf, **_INNER_PARQUET_KWARGS)
    return buf.getvalue()


def _manifest_table(manifest_json: dict[str, Any]) -> pa.Table:
    return pa.table(
        {"manifest_json": pa.array([json.dumps(manifest_json, sort_keys=True)], type=pa.string())}
    )


def _articles_table(
    articles: Sequence[ArticleHeader],
    embedded_2d: np.ndarray,
    embedded_3d: np.ndarray,
) -> pa.Table:
    n = len(articles)
    if embedded_2d.shape != (n, 2):
        raise ValueError(f"embedded_2d shape {embedded_2d.shape} != ({n}, 2)")
    if embedded_3d.shape != (n, 3):
        raise ValueError(f"embedded_3d shape {embedded_3d.shape} != ({n}, 3)")
    return pa.table(
        {
            "pubmed_id": pa.array([a.pubmed_id for a in articles], type=pa.int64()),
            "title": pa.array([a.title for a in articles], type=pa.string()),
            "year": pa.array([a.year for a in articles], type=pa.int16()),
            "cluster_id": pa.array([a.cluster_id for a in articles], type=pa.int16()),
            "umap_2d": pa.array(
                [row.astype(np.float32).tolist() for row in embedded_2d],
                type=pa.list_(pa.float32(), 2),
            ),
            "umap_3d": pa.array(
                [row.astype(np.float32).tolist() for row in embedded_3d],
                type=pa.list_(pa.float32(), 3),
            ),
        }
    )


def _clusters_table(
    clusters: Sequence[NeuroScapeCluster],
    cluster_counts: Mapping[int, int],
    palette: Mapping[int, tuple[str, str]],
) -> pa.Table:
    """Build the shared clusters table — content MUST be identical
    between neuroscape.parquet and atlas.parquet (cross-parquet
    invariant per R-009)."""

    ordered = sorted(clusters, key=lambda c: c.cluster_id)
    cids = [c.cluster_id for c in ordered]
    titles = [c.title for c in ordered]
    descriptions = [c.description for c in ordered]
    keywords = [list(c.keywords) for c in ordered]
    focuses = [c.focus for c in ordered]
    point_counts = [int(cluster_counts.get(c.cluster_id, 0)) for c in ordered]
    colours = []
    tiers = []
    for c in ordered:
        entry = palette.get(c.cluster_id, ("#000000", "secondary"))
        colours.append(entry[0])
        tiers.append(entry[1])
    return pa.table(
        {
            "cluster_id": pa.array(cids, type=pa.int16()),
            "title": pa.array(titles, type=pa.string()),
            "description": pa.array(descriptions, type=pa.string()),
            "keywords": pa.array(keywords, type=pa.list_(pa.string())),
            "focus": pa.array(focuses, type=pa.string()),
            "point_count": pa.array(point_counts, type=pa.int32()),
            "colour_hex": pa.array(colours, type=pa.string()),
            "palette_tier": pa.array(tiers, type=pa.string()),
        }
    )


def _neighbours_table(knn: KnnResult) -> pa.Table:
    return pa.table(
        {
            "pubmed_id": pa.array(knn.pmids.tolist(), type=pa.int64()),
            "nearest_pubmed_ids": pa.array(
                [row.tolist() for row in knn.nearest_pmids],
                type=pa.list_(pa.int64()),
            ),
            "nearest_distances": pa.array(
                [row.astype(np.float32).tolist() for row in knn.nearest_distances],
                type=pa.list_(pa.float32()),
            ),
        }
    )


def _backdrop_table(
    articles: Sequence[ArticleHeader],
    indices: Sequence[int],
    embedded_2d: np.ndarray,
    embedded_3d: np.ndarray,
) -> pa.Table:
    """Build the landing-page backdrop scatter rows — adds ``title``
    + ``year`` for hover tooltips (R-014)."""

    selected = [articles[i] for i in indices]
    pmids = [a.pubmed_id for a in selected]
    cluster_ids = [a.cluster_id for a in selected]
    titles = [a.title for a in selected]
    years = [a.year for a in selected]
    u2 = embedded_2d[list(indices)]
    u3 = embedded_3d[list(indices)]
    return pa.table(
        {
            "pubmed_id": pa.array(pmids, type=pa.int64()),
            "cluster_id": pa.array(cluster_ids, type=pa.int16()),
            "umap_2d": pa.array(
                [row.astype(np.float32).tolist() for row in u2],
                type=pa.list_(pa.float32(), 2),
            ),
            "umap_3d": pa.array(
                [row.astype(np.float32).tolist() for row in u3],
                type=pa.list_(pa.float32(), 3),
            ),
            "title": pa.array(titles, type=pa.string()),
            "year": pa.array(years, type=pa.int16()),
        }
    )


def _ohbm_overlay_table(
    overlay: ProjectionResult,
    overlay_2d: np.ndarray,
    poster_ids: Mapping[int, int],
    titles: Mapping[int, str],
    nearest_cluster: Mapping[int, int],
) -> pa.Table:
    sub_ids = list(overlay.submission_ids)
    if overlay_2d.shape != (len(sub_ids), 2):
        raise ValueError(
            f"overlay_2d shape {overlay_2d.shape} != ({len(sub_ids)}, 2)"
        )
    return pa.table(
        {
            "submission_id": pa.array(sub_ids, type=pa.int64()),
            "poster_id": pa.array([int(poster_ids[s]) for s in sub_ids], type=pa.int16()),
            "umap_2d": pa.array(
                [row.astype(np.float32).tolist() for row in overlay_2d],
                type=pa.list_(pa.float32(), 2),
            ),
            "umap_3d": pa.array(
                [row.astype(np.float32).tolist() for row in overlay.coordinates],
                type=pa.list_(pa.float32(), 3),
            ),
            "nearest_cluster_id": pa.array(
                [int(nearest_cluster[s]) for s in sub_ids], type=pa.int16()
            ),
            "title": pa.array([titles[s] for s in sub_ids], type=pa.string()),
        }
    )


def _cross_pointers_table(
    overlay: ProjectionResult,
    poster_ids: Mapping[int, int],
    articles: Sequence[ArticleHeader],
) -> pa.Table:
    """Build the cross_pointers row group — one row per visible point
    with the absolute permalink into the sibling subsite."""

    kinds: list[str] = []
    ids: list[int] = []
    permalinks: list[str] = []

    for sid in overlay.submission_ids:
        poster_id = int(poster_ids[sid])
        kinds.append("ohbm2026")
        ids.append(poster_id)
        permalinks.append(f"/ohbm2026/abstract/{poster_id}/")
    for a in articles:
        kinds.append("neuroscape")
        ids.append(int(a.pubmed_id))
        permalinks.append(f"/neuroscape/abstract/{a.pubmed_id}/")

    return pa.table(
        {
            "point_kind": pa.array(kinds, type=pa.string()),
            "id": pa.array(ids, type=pa.int64()),
            "permalink": pa.array(permalinks, type=pa.string()),
        }
    )


# ---------------------------------------------------------------------------
# Outer writer
# ---------------------------------------------------------------------------


def _write_outer(
    out_path: Path,
    entries: list[tuple[str, bytes]],
) -> None:
    """Write the outer parquet ``(table_name, table_bytes)`` rows.

    Atomic: writes to a sibling ``.part`` file and ``os.rename`` on
    success so a failed mid-write never leaves a partial canonical
    file at the target path.
    """

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_path.with_suffix(out_path.suffix + ".part")
    outer = pa.table(
        {
            "table_name": pa.array([n for n, _ in entries], type=pa.string()),
            "table_bytes": pa.array([b for _, b in entries], type=pa.large_binary()),
        }
    )
    pq.write_table(outer, tmp, **_OUTER_PARQUET_KWARGS)
    tmp.replace(out_path)


# ---------------------------------------------------------------------------
# Public writers
# ---------------------------------------------------------------------------


def write_neuroscape_parquet(
    *,
    out_path: Path,
    build_info: Mapping[str, Any],
    articles: Sequence[ArticleHeader],
    clusters: Sequence[NeuroScapeCluster],
    cluster_counts: Mapping[int, int],
    palette: Mapping[int, tuple[str, str]],
    embedded_3d: np.ndarray,
    embedded_2d: np.ndarray,
    knn: KnnResult,
    titles_index_bin: bytes,
    titles_index_meta: Mapping[str, Any],
) -> None:
    """Emit ``neuroscape.parquet`` per contracts/parquet-schemas.md."""

    manifest_json = {
        "schema_version": "neuroscape.v1",
        "build_info": dict(build_info),
        "n_articles": len(articles),
        "n_clusters": len(clusters),
        "k_neighbors": int(knn.nearest_pmids.shape[1]) if knn.nearest_pmids.size else 0,
    }
    entries: list[tuple[str, bytes]] = [
        ("manifest", _to_inner_parquet_bytes(_manifest_table(manifest_json))),
        (
            "articles",
            _to_inner_parquet_bytes(_articles_table(articles, embedded_2d, embedded_3d)),
        ),
        (
            "clusters",
            _to_inner_parquet_bytes(_clusters_table(clusters, cluster_counts, palette)),
        ),
        ("neighbors_neuroscape", _to_inner_parquet_bytes(_neighbours_table(knn))),
        # Sidecar binary blobs are stored without inner-Parquet wrapping.
        ("search:neuroscape_titles", bytes(titles_index_bin)),
        (
            "search:neuroscape_titles_meta",
            json.dumps(dict(titles_index_meta), sort_keys=True).encode(),
        ),
    ]
    _write_outer(out_path, entries)


def write_atlas_parquet(
    *,
    out_path: Path,
    build_info: Mapping[str, Any],
    sibling_state_keys: Mapping[str, str],
    articles: Sequence[ArticleHeader],
    clusters: Sequence[NeuroScapeCluster],
    cluster_counts: Mapping[int, int],
    palette: Mapping[int, tuple[str, str]],
    embedded_3d: np.ndarray,
    embedded_2d: np.ndarray,
    decimated_indices: np.ndarray,
    ohbm_overlay: ProjectionResult,
    ohbm_overlay_2d: np.ndarray,
    ohbm_poster_ids: Mapping[int, int],
    ohbm_titles: Mapping[int, str],
    ohbm_nearest_cluster: Mapping[int, int],
) -> None:
    """Emit ``atlas.parquet`` per contracts/parquet-schemas.md."""

    bi = dict(build_info)
    bi["sibling_state_keys"] = dict(sibling_state_keys)

    manifest_json = {
        "schema_version": "atlas.v1",
        "build_info": bi,
        "n_overlay_points": len(ohbm_overlay.submission_ids),
        "n_backdrop_full": len(articles),
        "n_backdrop_decimated": int(decimated_indices.shape[0]),
        "n_clusters": len(clusters),
        "ohbm_omitted_submission_ids": list(ohbm_overlay.failed_submission_ids),
    }

    full_indices = list(range(len(articles)))
    entries: list[tuple[str, bytes]] = [
        ("manifest", _to_inner_parquet_bytes(_manifest_table(manifest_json))),
        (
            "clusters",
            _to_inner_parquet_bytes(_clusters_table(clusters, cluster_counts, palette)),
        ),
        (
            "neuroscape_backdrop_full",
            _to_inner_parquet_bytes(
                _backdrop_table(articles, full_indices, embedded_2d, embedded_3d)
            ),
        ),
        (
            "neuroscape_backdrop_decimated",
            _to_inner_parquet_bytes(
                _backdrop_table(
                    articles,
                    [int(i) for i in decimated_indices.tolist()],
                    embedded_2d,
                    embedded_3d,
                )
            ),
        ),
        (
            "ohbm_overlay",
            _to_inner_parquet_bytes(
                _ohbm_overlay_table(
                    ohbm_overlay,
                    ohbm_overlay_2d,
                    ohbm_poster_ids,
                    ohbm_titles,
                    ohbm_nearest_cluster,
                )
            ),
        ),
        (
            "cross_pointers",
            _to_inner_parquet_bytes(_cross_pointers_table(ohbm_overlay, ohbm_poster_ids, articles)),
        ),
    ]
    _write_outer(out_path, entries)


# ---------------------------------------------------------------------------
# Cross-parquet invariant
# ---------------------------------------------------------------------------


def _read_outer_row(path: Path, name: str) -> bytes:
    """Pull the bytes of a named outer row from ``path``."""

    table = pq.read_table(path)
    names = table.column("table_name").to_pylist()
    bodies = table.column("table_bytes").to_pylist()
    for n, body in zip(names, bodies):
        if n == name:
            return bytes(body)
    raise CrossParquetDriftError(
        f"outer row {name!r} missing from {path}",
        parquet=str(path),
        field=name,
        expected="<present>",
        actual="<missing>",
    )


def assert_cluster_tables_match(neuroscape_path: Path, atlas_path: Path) -> None:
    """Raise :class:`CrossParquetDriftError` if the two parquets'
    ``clusters`` inner tables differ row-for-row.

    The two tables are produced from the same input via
    :func:`_clusters_table` so a divergence indicates one of:

    - a hand-edited parquet (the operator regenerated only one side),
    - a code drift in :func:`_clusters_table`,
    - a palette / cluster-count drift between the two writer calls.

    Any of these would let the SvelteKit loader render an inconsistent
    cluster legend at view time — the assertion stops the build
    before that can ship.
    """

    ns_bytes = _read_outer_row(neuroscape_path, "clusters")
    atlas_bytes = _read_outer_row(atlas_path, "clusters")
    if ns_bytes == atlas_bytes:
        return
    # Bytes differ — decode + compare column-by-column so the error
    # message names the offending field.
    ns_table = pq.read_table(io.BytesIO(ns_bytes))
    atlas_table = pq.read_table(io.BytesIO(atlas_bytes))
    if ns_table.num_rows != atlas_table.num_rows:
        raise CrossParquetDriftError(
            f"clusters row count drift: {ns_table.num_rows} vs {atlas_table.num_rows}",
            parquet=str(atlas_path),
            field="clusters.num_rows",
            expected=str(ns_table.num_rows),
            actual=str(atlas_table.num_rows),
        )
    for col in ns_table.column_names:
        ns_col = ns_table.column(col).to_pylist()
        atlas_col = atlas_table.column(col).to_pylist()
        if ns_col != atlas_col:
            raise CrossParquetDriftError(
                f"clusters column {col!r} differs between neuroscape.parquet and atlas.parquet",
                parquet=str(atlas_path),
                field=f"clusters.{col}",
                expected=repr(ns_col),
                actual=repr(atlas_col),
            )
    # Bytes differ but every column matches: usually a metadata-level
    # serialisation difference (e.g. row group statistics). Surface
    # loudly so it's noticed, but name it as a metadata drift.
    raise CrossParquetDriftError(
        "clusters bytes differ between neuroscape.parquet and atlas.parquet (metadata drift)",
        parquet=str(atlas_path),
        field="clusters.metadata",
        expected="byte-identical",
        actual="diverged",
    )
