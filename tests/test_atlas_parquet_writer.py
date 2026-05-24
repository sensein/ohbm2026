"""Tests for ``ohbm2026.atlas_package.parquet_writer``.

Spec: ``specs/015-neuroscape-context/`` — research R-008 + R-011 +
data-model.md + ``contracts/parquet-schemas.md`` + R-009
(``CrossParquetDriftError``).

The writer produces two parquet files:

- ``neuroscape.parquet`` — manifest + articles (local-only fields) +
  clusters + neighbors + title-only search sidecar
- ``atlas.parquet`` — manifest (with sibling_state_keys) + clusters +
  backdrop_full + backdrop_decimated + ohbm_overlay + cross_pointers

The cluster tables in both parquets MUST be row-for-row identical —
the writer asserts the invariant at emit time per R-009.
"""

from __future__ import annotations

import io
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np
import pyarrow.parquet as pq

from ohbm2026 import exceptions
from ohbm2026.atlas_package import (
    cluster_palette as palette_mod,
    neighbour_index,
    parquet_writer,
)
from ohbm2026.atlas_package.neuroscape_loader import ArticleHeader, NeuroScapeCluster
from ohbm2026.atlas_package.ohbm_projector import ProjectionResult


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _articles() -> list[ArticleHeader]:
    return [
        ArticleHeader(pubmed_id=10001, title="Title 1", year=2020, cluster_id=0),
        ArticleHeader(pubmed_id=10002, title="Title 2", year=2021, cluster_id=0),
        ArticleHeader(pubmed_id=10003, title="Title 3", year=2019, cluster_id=0),
        ArticleHeader(pubmed_id=10004, title="Title 4", year=2022, cluster_id=1),
        ArticleHeader(pubmed_id=10005, title="Title 5", year=2023, cluster_id=1),
        ArticleHeader(pubmed_id=10006, title="Title 6", year=2018, cluster_id=2),
    ]


def _clusters() -> list[NeuroScapeCluster]:
    return [
        NeuroScapeCluster(cluster_id=0, title="C0", description="D0", keywords=("k0",), focus="F0"),
        NeuroScapeCluster(cluster_id=1, title="C1", description="D1", keywords=("k1",), focus="F1"),
        NeuroScapeCluster(cluster_id=2, title="C2", description="D2", keywords=("k2",), focus="F2"),
    ]


def _embedded(n: int, dim: int, seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed=seed)
    return rng.standard_normal((n, dim)).astype(np.float32)


def _knn_result(articles: list[ArticleHeader]) -> neighbour_index.KnnResult:
    pmids = np.array([a.pubmed_id for a in articles], dtype=np.int64)
    vectors = _embedded(len(articles), 64, seed=0)
    return neighbour_index.build_knn(pmids, vectors, k=3)


def _ohbm_overlay(n: int = 4) -> ProjectionResult:
    sub_ids = tuple(range(1000, 1000 + n))
    coords = _embedded(n, 3, seed=42)
    return ProjectionResult(
        n_components=3,
        submission_ids=sub_ids,
        coordinates=coords,
        failed_submission_ids=(),
    )


def _build_info(state_key: str = "abcd12345678") -> dict:
    return {
        "state_key": state_key,
        "code_revision": "deadbeef",
        "command_line": "ohbmcli build-atlas-package",
        "seed": 0,
        "umap_state_key": "111111111111",
        "centroid_table_version": "ec7a69d7cccd",
        "voyage_bundle_id": "voyage_stage2_published",
        "build_started_utc": "2026-05-24T00:00:00Z",
        "build_finished_utc": "2026-05-24T00:05:00Z",
    }


def _decoded_outer_rows(path: Path) -> list[tuple[str, bytes]]:
    table = pq.read_table(path)
    names = table.column("table_name").to_pylist()
    bodies = table.column("table_bytes").to_pylist()
    return list(zip(names, bodies))


def _read_inner_table(blob: bytes):
    return pq.read_table(io.BytesIO(blob))


# ---------------------------------------------------------------------------
# Writer tests
# ---------------------------------------------------------------------------


class WriteNeuroscapeParquetTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.out = Path(self._tmp.name) / "neuroscape.parquet"
        self.articles = _articles()
        self.clusters = _clusters()
        self.embedded_3d = _embedded(len(self.articles), 3, seed=1)
        self.embedded_2d = _embedded(len(self.articles), 2, seed=2)
        self.knn = _knn_result(self.articles)
        cluster_counts = {0: 3, 1: 2, 2: 1}
        self.palette = palette_mod.assign_palette(cluster_counts, primary_size=32)
        self.cluster_counts = cluster_counts
        parquet_writer.write_neuroscape_parquet(
            out_path=self.out,
            build_info=_build_info(state_key="ns0000000001"),
            articles=self.articles,
            clusters=self.clusters,
            cluster_counts=cluster_counts,
            palette=self.palette,
            embedded_3d=self.embedded_3d,
            embedded_2d=self.embedded_2d,
            knn=self.knn,
            titles_index_bin=b"<placeholder title index>",
            titles_index_meta={"schema_version": "search.neuroscape_titles.v1", "n_documents": len(self.articles)},
        )

    def test_outer_rows_match_data_model(self) -> None:
        names = [n for n, _ in _decoded_outer_rows(self.out)]
        self.assertEqual(
            sorted(names),
            sorted(
                [
                    "manifest",
                    "articles",
                    "clusters",
                    "neighbors_neuroscape",
                    "search:neuroscape_titles",
                    "search:neuroscape_titles_meta",
                ]
            ),
        )

    def test_manifest_carries_build_info(self) -> None:
        outer = dict(_decoded_outer_rows(self.out))
        manifest_table = _read_inner_table(outer["manifest"])
        manifest_json = manifest_table.column("manifest_json").to_pylist()[0]
        decoded = json.loads(manifest_json)
        self.assertEqual(decoded["schema_version"], "neuroscape.v1")
        self.assertEqual(decoded["build_info"]["state_key"], "ns0000000001")
        self.assertEqual(decoded["n_articles"], len(self.articles))
        self.assertEqual(decoded["n_clusters"], len(self.clusters))

    def test_articles_table_has_no_body_columns(self) -> None:
        outer = dict(_decoded_outer_rows(self.out))
        articles = _read_inner_table(outer["articles"])
        columns = set(articles.column_names)
        self.assertEqual(
            columns,
            {"pubmed_id", "title", "year", "cluster_id", "umap_2d", "umap_3d"},
            msg=(
                "Stage 15 stores ONLY local-UI-required fields. Body "
                "columns (authors, journal, abstract_text, doi) MUST "
                "be absent — they're fetched at view time per FR-019a."
            ),
        )

    def test_articles_table_rows_match_input(self) -> None:
        outer = dict(_decoded_outer_rows(self.out))
        articles = _read_inner_table(outer["articles"])
        pmids = articles.column("pubmed_id").to_pylist()
        titles = articles.column("title").to_pylist()
        years = articles.column("year").to_pylist()
        self.assertEqual(pmids, [a.pubmed_id for a in self.articles])
        self.assertEqual(titles, [a.title for a in self.articles])
        self.assertEqual(years, [a.year for a in self.articles])

    def test_clusters_table_carries_palette_columns(self) -> None:
        outer = dict(_decoded_outer_rows(self.out))
        clusters = _read_inner_table(outer["clusters"])
        columns = set(clusters.column_names)
        # Per contracts/parquet-schemas.md the clusters table carries
        # palette colour + tier + point_count alongside the static
        # cluster fields.
        self.assertIn("cluster_id", columns)
        self.assertIn("colour_hex", columns)
        self.assertIn("palette_tier", columns)
        self.assertIn("point_count", columns)

    def test_neighbors_table_shape(self) -> None:
        outer = dict(_decoded_outer_rows(self.out))
        nbr = _read_inner_table(outer["neighbors_neuroscape"])
        self.assertEqual(set(nbr.column_names), {"pubmed_id", "nearest_pubmed_ids", "nearest_distances"})
        self.assertEqual(nbr.num_rows, len(self.articles))

    def test_search_sidecar_is_raw_bytes_for_index_and_json_for_meta(self) -> None:
        outer = dict(_decoded_outer_rows(self.out))
        self.assertEqual(outer["search:neuroscape_titles"], b"<placeholder title index>")
        meta = json.loads(outer["search:neuroscape_titles_meta"].decode())
        self.assertEqual(meta["schema_version"], "search.neuroscape_titles.v1")
        self.assertEqual(meta["n_documents"], len(self.articles))


class WriteAtlasParquetTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.out = Path(self._tmp.name) / "atlas.parquet"
        self.articles = _articles()
        self.clusters = _clusters()
        self.embedded_3d = _embedded(len(self.articles), 3, seed=1)
        self.embedded_2d = _embedded(len(self.articles), 2, seed=2)
        cluster_counts = {0: 3, 1: 2, 2: 1}
        self.palette = palette_mod.assign_palette(cluster_counts, primary_size=32)
        self.cluster_counts = cluster_counts
        self.decimated = np.array([0, 2, 3, 5], dtype=np.int64)
        self.ohbm_overlay = _ohbm_overlay(n=4)
        self.ohbm_poster_ids = {sid: 200 + i for i, sid in enumerate(self.ohbm_overlay.submission_ids)}
        self.ohbm_titles = {sid: f"OHBM Title {sid}" for sid in self.ohbm_overlay.submission_ids}
        self.ohbm_nearest_cluster = {sid: 0 for sid in self.ohbm_overlay.submission_ids}
        self.ohbm_2d = _embedded(len(self.ohbm_overlay.submission_ids), 2, seed=99)
        parquet_writer.write_atlas_parquet(
            out_path=self.out,
            build_info=_build_info(state_key="atl000000001"),
            sibling_state_keys={"ohbm2026": "ohbm00000001", "neuroscape": "ns0000000001"},
            articles=self.articles,
            clusters=self.clusters,
            cluster_counts=self.cluster_counts,
            palette=self.palette,
            embedded_3d=self.embedded_3d,
            embedded_2d=self.embedded_2d,
            decimated_indices=self.decimated,
            ohbm_overlay=self.ohbm_overlay,
            ohbm_overlay_2d=self.ohbm_2d,
            ohbm_poster_ids=self.ohbm_poster_ids,
            ohbm_titles=self.ohbm_titles,
            ohbm_nearest_cluster=self.ohbm_nearest_cluster,
        )

    def test_outer_rows_match_data_model(self) -> None:
        names = [n for n, _ in _decoded_outer_rows(self.out)]
        self.assertEqual(
            sorted(names),
            sorted(
                [
                    "manifest",
                    "clusters",
                    "neuroscape_backdrop_full",
                    "neuroscape_backdrop_decimated",
                    "ohbm_overlay",
                    "cross_pointers",
                ]
            ),
        )

    def test_manifest_embeds_sibling_state_keys(self) -> None:
        outer = dict(_decoded_outer_rows(self.out))
        manifest = json.loads(_read_inner_table(outer["manifest"]).column("manifest_json").to_pylist()[0])
        self.assertEqual(manifest["schema_version"], "atlas.v1")
        self.assertEqual(manifest["build_info"]["sibling_state_keys"]["ohbm2026"], "ohbm00000001")
        self.assertEqual(manifest["build_info"]["sibling_state_keys"]["neuroscape"], "ns0000000001")

    def test_backdrop_full_has_title_year_for_hover(self) -> None:
        outer = dict(_decoded_outer_rows(self.out))
        bk = _read_inner_table(outer["neuroscape_backdrop_full"])
        self.assertEqual(
            set(bk.column_names),
            {"pubmed_id", "cluster_id", "umap_2d", "umap_3d", "title", "year"},
        )
        self.assertEqual(bk.num_rows, len(self.articles))

    def test_backdrop_decimated_uses_indices(self) -> None:
        outer = dict(_decoded_outer_rows(self.out))
        dec = _read_inner_table(outer["neuroscape_backdrop_decimated"])
        self.assertEqual(dec.num_rows, len(self.decimated))
        expected_pmids = [self.articles[i].pubmed_id for i in self.decimated.tolist()]
        self.assertEqual(dec.column("pubmed_id").to_pylist(), expected_pmids)

    def test_ohbm_overlay_shape(self) -> None:
        outer = dict(_decoded_outer_rows(self.out))
        ovr = _read_inner_table(outer["ohbm_overlay"])
        self.assertEqual(
            set(ovr.column_names),
            {"submission_id", "poster_id", "umap_2d", "umap_3d", "nearest_cluster_id", "title"},
        )
        self.assertEqual(ovr.num_rows, len(self.ohbm_overlay.submission_ids))

    def test_cross_pointers_covers_overlay_and_backdrop(self) -> None:
        outer = dict(_decoded_outer_rows(self.out))
        cp = _read_inner_table(outer["cross_pointers"])
        self.assertEqual(set(cp.column_names), {"point_kind", "id", "permalink"})
        # One pointer per OHBM overlay row + one per NeuroScape backdrop row.
        self.assertEqual(
            cp.num_rows,
            len(self.ohbm_overlay.submission_ids) + len(self.articles),
        )
        # Permalinks must be absolute paths to the sibling subsite.
        permalinks = cp.column("permalink").to_pylist()
        for link in permalinks:
            self.assertTrue(link.startswith("/ohbm2026/abstract/") or link.startswith("/neuroscape/abstract/"))


class CrossParquetInvariantTests(unittest.TestCase):
    """The clusters row group MUST be row-for-row identical between
    the two emitted parquets — R-009 / parquet-schemas.md cross-
    parquet drift contract."""

    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.ns_path = Path(self._tmp.name) / "neuroscape.parquet"
        self.atlas_path = Path(self._tmp.name) / "atlas.parquet"
        articles = _articles()
        clusters = _clusters()
        cluster_counts = {0: 3, 1: 2, 2: 1}
        pal = palette_mod.assign_palette(cluster_counts, primary_size=32)
        embedded_3d = _embedded(len(articles), 3, seed=1)
        embedded_2d = _embedded(len(articles), 2, seed=2)
        knn = _knn_result(articles)
        parquet_writer.write_neuroscape_parquet(
            out_path=self.ns_path,
            build_info=_build_info(state_key="ns0000000001"),
            articles=articles,
            clusters=clusters,
            cluster_counts=cluster_counts,
            palette=pal,
            embedded_3d=embedded_3d,
            embedded_2d=embedded_2d,
            knn=knn,
            titles_index_bin=b"<ph>",
            titles_index_meta={"schema_version": "search.neuroscape_titles.v1", "n_documents": len(articles)},
        )
        overlay = _ohbm_overlay(4)
        parquet_writer.write_atlas_parquet(
            out_path=self.atlas_path,
            build_info=_build_info(state_key="atl000000001"),
            sibling_state_keys={"ohbm2026": "ohbm00000001", "neuroscape": "ns0000000001"},
            articles=articles,
            clusters=clusters,
            cluster_counts=cluster_counts,
            palette=pal,
            embedded_3d=embedded_3d,
            embedded_2d=embedded_2d,
            decimated_indices=np.array([0, 2, 3], dtype=np.int64),
            ohbm_overlay=overlay,
            ohbm_overlay_2d=_embedded(4, 2, seed=99),
            ohbm_poster_ids={sid: 200 + i for i, sid in enumerate(overlay.submission_ids)},
            ohbm_titles={sid: f"OHBM {sid}" for sid in overlay.submission_ids},
            ohbm_nearest_cluster={sid: 0 for sid in overlay.submission_ids},
        )

    def test_clusters_tables_row_for_row_equal(self) -> None:
        # Use the public assertion helper — it MUST not raise on a
        # consistent pair of outputs.
        parquet_writer.assert_cluster_tables_match(self.ns_path, self.atlas_path)

    def test_assert_raises_when_clusters_table_diverges(self) -> None:
        # Build a tampered atlas.parquet whose clusters table has a
        # diverging row (different colour_hex on cluster 0). The
        # assertion MUST raise CrossParquetDriftError.
        articles = _articles()
        clusters = _clusters()
        cluster_counts = {0: 3, 1: 2, 2: 1}
        pal = palette_mod.assign_palette(cluster_counts, primary_size=32)
        # Hand-mutate the palette so cluster 0 has a different colour.
        tampered = dict(pal)
        tampered[0] = ("#ff0000", tampered[0][1])
        bad_atlas = Path(self._tmp.name) / "atlas_tampered.parquet"
        overlay = _ohbm_overlay(2)
        parquet_writer.write_atlas_parquet(
            out_path=bad_atlas,
            build_info=_build_info(state_key="atltampered1"),
            sibling_state_keys={"ohbm2026": "ohbm00000001", "neuroscape": "ns0000000001"},
            articles=articles,
            clusters=clusters,
            cluster_counts=cluster_counts,
            palette=tampered,
            embedded_3d=_embedded(len(articles), 3, seed=1),
            embedded_2d=_embedded(len(articles), 2, seed=2),
            decimated_indices=np.array([0, 1], dtype=np.int64),
            ohbm_overlay=overlay,
            ohbm_overlay_2d=_embedded(2, 2, seed=99),
            ohbm_poster_ids={sid: 200 + i for i, sid in enumerate(overlay.submission_ids)},
            ohbm_titles={sid: f"OHBM {sid}" for sid in overlay.submission_ids},
            ohbm_nearest_cluster={sid: 0 for sid in overlay.submission_ids},
        )
        with self.assertRaises(exceptions.CrossParquetDriftError) as ctx:
            parquet_writer.assert_cluster_tables_match(self.ns_path, bad_atlas)
        self.assertIn("clusters", (ctx.exception.field or "").lower())


if __name__ == "__main__":
    unittest.main()
