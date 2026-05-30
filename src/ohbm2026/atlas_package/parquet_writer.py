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
- :func:`assert_atlas_sibling_keys` — orchestrator-side invariant
  asserting ``atlas.parquet``'s manifest declares the sibling
  state-keys it was built against; raises
  :class:`CrossParquetDriftError`.
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
    "assert_atlas_sibling_keys",
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


def _cluster_centroids_table(
    cluster_centroids: Mapping[int, np.ndarray],
    cluster_counts: Mapping[int, int],
) -> pa.Table:
    """Spec 019 — cluster-centroid table inside neuroscape.parquet.

    Schema: `cluster_id INT16, centroid_vector LIST<FLOAT32, 384>,
    member_count INT32`. Sorted by cluster_id ASC. The browser scores
    the embedded query against these centroids before any range-fetch
    into neuroscape_vectors.parquet (5-step pipeline, Step 2).
    """
    if not cluster_centroids:
        # Defensive: an empty centroid table is allowed (corresponds to
        # --no-semantic-index builds) but produces an empty table to
        # keep the schema readable by the browser.
        return pa.table(
            {
                "cluster_id": pa.array([], type=pa.int16()),
                "centroid_vector": pa.array([], type=pa.list_(pa.float32(), 384)),
                "member_count": pa.array([], type=pa.int32()),
            }
        )
    ordered = sorted(cluster_centroids.keys())
    return pa.table(
        {
            "cluster_id": pa.array(ordered, type=pa.int16()),
            "centroid_vector": pa.array(
                [cluster_centroids[c].astype(np.float32).tolist() for c in ordered],
                type=pa.list_(pa.float32(), 384),
            ),
            "member_count": pa.array(
                [int(cluster_counts.get(c, 0)) for c in ordered],
                type=pa.int32(),
            ),
        }
    )


def _articles_table(articles: Sequence[ArticleHeader]) -> pa.Table:
    """Build the articles table — identity + search fields only.

    Coordinates moved to the standalone ``coords`` table (spec 019
    follow-up) so a browser can range-fetch the scatter geometry
    without paying for titles, and search/result-list views can read
    titles without paying for coordinates.
    """

    return pa.table(
        {
            "pubmed_id": pa.array([a.pubmed_id for a in articles], type=pa.int64()),
            "title": pa.array([a.title for a in articles], type=pa.string()),
            "year": pa.array([a.year for a in articles], type=pa.int16()),
            "cluster_id": pa.array([a.cluster_id for a in articles], type=pa.int16()),
        }
    )


def _coords_table(
    articles: Sequence[ArticleHeader],
    embedded_2d: np.ndarray,
    embedded_3d: np.ndarray,
    lod_levels: np.ndarray,
) -> pa.Table:
    """Build the standalone scatter-coordinate table.

    Carries ``cluster_id`` alongside the 2D/3D UMAP coordinates so the
    landing scatter can colour every point from this single table — no
    join against ``articles`` needed to render. Titles/years stay out
    (fetched from ``articles`` only when a tooltip/result row needs them).

    ``lod_level`` annotates every point with its quadtree level-of-detail
    tier (spec 019 follow-up). ``/neuroscape/`` loads the full corpus for
    search anyway, so it caps the scatter with ``lod_level <= cap`` at
    render time — no extra fetch. atlas-root instead range-fetches the
    per-tier ``backdrop_lod*`` tables.
    """

    n = len(articles)
    if embedded_2d.shape != (n, 2):
        raise ValueError(f"embedded_2d shape {embedded_2d.shape} != ({n}, 2)")
    if embedded_3d.shape != (n, 3):
        raise ValueError(f"embedded_3d shape {embedded_3d.shape} != ({n}, 3)")
    if lod_levels.shape != (n,):
        raise ValueError(f"lod_levels shape {lod_levels.shape} != ({n},)")
    return pa.table(
        {
            "pubmed_id": pa.array([a.pubmed_id for a in articles], type=pa.int64()),
            "cluster_id": pa.array([a.cluster_id for a in articles], type=pa.int16()),
            "umap_2d": pa.array(
                [row.astype(np.float32).tolist() for row in embedded_2d],
                type=pa.list_(pa.float32(), 2),
            ),
            "umap_3d": pa.array(
                [row.astype(np.float32).tolist() for row in embedded_3d],
                type=pa.list_(pa.float32(), 3),
            ),
            "lod_level": pa.array(
                [int(v) for v in lod_levels.tolist()], type=pa.int16()
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
    lod_levels: np.ndarray,
    n_backdrop_levels: int,
    knn: KnnResult,
    titles_index_bin: bytes,
    titles_index_meta: Mapping[str, Any],
    cluster_centroids: Mapping[int, np.ndarray] | None = None,
) -> None:
    """Emit ``neuroscape.parquet`` per contracts/parquet-schemas.md.

    Table layout (each is its own outer row → one Range request each):

    - ``articles``   identity + search fields (no coordinates).
    - ``coords``     full-corpus scatter geometry (pubmed_id, cluster_id,
                     umap_2d, umap_3d, lod_level) — split out so the
                     scatter geometry can be fetched without titles and
                     vice versa, and so ``/neuroscape/`` can cap the
                     scatter by ``lod_level`` without an extra fetch.
    - ``backdrop_lod0 … backdrop_lod{n-1}`` self-contained progressive
                     scatter tiers (each with title/year for hover). The
                     quadtree LOD (``lod.assign_lod_levels``) makes every
                     cumulative prefix a blue-noise cover, so atlas-root
                     range-fetches ``backdrop_lod0`` for an instant coarse
                     paint and the finer tiers to refine — the rest tier
                     (``lod_level == n_backdrop_levels``) is the full-
                     corpus remainder and is deliberately NOT emitted as a
                     backdrop table (it lives only in ``coords``).
    - ``clusters`` / ``neighbors_neuroscape`` / search sidecars.

    Spec 019: ``cluster_centroids`` is an OPTIONAL additional table
    (one per cluster, FP32 centroid + member_count) that, when present,
    drives the browser's query→cluster routing step. Defaults to None
    so existing callers (and `--no-semantic-index` builds) don't have
    to thread it through; the table is omitted in that case.
    """

    lod_levels = np.asarray(lod_levels)
    levels_list = lod_levels.tolist()
    # Partition representative tiers (rest tier excluded — see docstring).
    tier_indices: list[list[int]] = [[] for _ in range(n_backdrop_levels)]
    for i, lv in enumerate(levels_list):
        if 0 <= lv < n_backdrop_levels:
            tier_indices[int(lv)].append(i)
    backdrop_lod_sizes = [len(t) for t in tier_indices]

    manifest_json = {
        "schema_version": "neuroscape.v1",
        "build_info": dict(build_info),
        "n_articles": len(articles),
        "n_clusters": len(clusters),
        "n_backdrop_levels": int(n_backdrop_levels),
        "backdrop_lod_sizes": backdrop_lod_sizes,
        "k_neighbors": int(knn.nearest_pmids.shape[1]) if knn.nearest_pmids.size else 0,
        "has_cluster_centroids": cluster_centroids is not None and len(cluster_centroids) > 0,
    }
    entries: list[tuple[str, bytes]] = [
        ("manifest", _to_inner_parquet_bytes(_manifest_table(manifest_json))),
        ("articles", _to_inner_parquet_bytes(_articles_table(articles))),
        (
            "coords",
            _to_inner_parquet_bytes(
                _coords_table(articles, embedded_2d, embedded_3d, lod_levels)
            ),
        ),
        *(
            (
                f"backdrop_lod{k}",
                _to_inner_parquet_bytes(
                    _backdrop_table(articles, tier_indices[k], embedded_2d, embedded_3d)
                ),
            )
            for k in range(n_backdrop_levels)
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
    if cluster_centroids is not None and len(cluster_centroids) > 0:
        entries.append(
            (
                "cluster_centroids",
                _to_inner_parquet_bytes(_cluster_centroids_table(cluster_centroids, cluster_counts)),
            )
        )
    _write_outer(out_path, entries)


def write_atlas_parquet(
    *,
    out_path: Path,
    build_info: Mapping[str, Any],
    sibling_state_keys: Mapping[str, str],
    ohbm_overlay: ProjectionResult,
    ohbm_overlay_2d: np.ndarray,
    ohbm_poster_ids: Mapping[int, int],
    ohbm_titles: Mapping[int, str],
    ohbm_nearest_cluster: Mapping[int, int],
) -> None:
    """Emit ``atlas.parquet`` — ONLY the data that cannot be derived
    from the two sibling parquets.

    The single substantive table is ``ohbm_overlay``: the OHBM 2026
    abstracts projected (via ``umap.transform``) into the NeuroScape
    UMAP space. That projection is impossible to reconstruct from the
    sibling files, so it lives here. Everything else atlas-root needs —
    the cluster legend, the NeuroScape backdrop scatter, the centroid
    table — is range-fetched from the sibling ``neuroscape.parquet``
    (the outer envelope is written ``row_group_size=1`` so a single
    inner table costs one Range request, not the full file).

    ``cross_pointers`` is gone too: the permalinks were a pure function
    of poster_id / pubmed_id (``/ohbm2026/abstract/<poster_id>/``,
    ``/neuroscape/abstract/<pubmed_id>/``) so the browser derives them
    on demand. One source of truth, no duplication, no cross-parquet
    drift surface beyond the declared ``sibling_state_keys``.
    """

    bi = dict(build_info)
    bi["sibling_state_keys"] = dict(sibling_state_keys)

    manifest_json = {
        "schema_version": "atlas.v1",
        "build_info": bi,
        "n_overlay_points": len(ohbm_overlay.submission_ids),
        "ohbm_omitted_submission_ids": list(ohbm_overlay.failed_submission_ids),
    }

    entries: list[tuple[str, bytes]] = [
        ("manifest", _to_inner_parquet_bytes(_manifest_table(manifest_json))),
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


def assert_atlas_sibling_keys(
    atlas_path: Path,
    expected: Mapping[str, str],
) -> None:
    """Raise :class:`CrossParquetDriftError` unless ``atlas.parquet``'s
    manifest declares ``build_info.sibling_state_keys`` matching
    ``expected``.

    atlas.parquet no longer carries a ``clusters`` table to byte-match
    against — the cluster legend (and the whole NeuroScape backdrop) is
    range-fetched from the sibling ``neuroscape.parquet`` at view time.
    The only cross-parquet contract atlas.parquet still owns is the
    declaration of WHICH sibling builds it was projected against; the
    browser's :func:`verifyAtlasSiblingDrift` reads the live siblings'
    manifests and compares them to these declared keys. This build-time
    assertion guards the upstream half: that the writer actually wrote
    the keys the orchestrator intended (a missing/empty/mismatched key
    here would make the browser drift-check meaningless).
    """

    manifest_bytes = _read_outer_row(atlas_path, "manifest")
    manifest_table = pq.read_table(io.BytesIO(manifest_bytes))
    manifest_json = manifest_table.column("manifest_json").to_pylist()[0]
    manifest = json.loads(manifest_json)
    actual = (manifest.get("build_info") or {}).get("sibling_state_keys") or {}
    for sibling, want in expected.items():
        got = actual.get(sibling)
        if got != want:
            raise CrossParquetDriftError(
                f"atlas.parquet sibling_state_keys[{sibling!r}] drift",
                parquet=str(atlas_path),
                field=f"sibling_state_keys.{sibling}",
                expected=str(want),
                actual=str(got),
            )
