"""Tests for ``ohbm2026.atlas_package.parquet_writer``.

Spec: ``specs/015-neuroscape-context/`` — research R-008 + R-011 +
data-model.md + ``contracts/parquet-schemas.md`` + R-009
(``CrossParquetDriftError``).

The writer produces two parquet files:

- ``neuroscape.parquet`` — manifest + articles (identity/search only,
  no coordinates) + coords (standalone scatter geometry) +
  backdrop_decimated (self-contained landing scatter) + clusters +
  neighbors + title-only search sidecar
- ``atlas.parquet`` — manifest (with sibling_state_keys) + ohbm_overlay
  ONLY (the OHBM→NeuroScape projection — the one thing that cannot be
  derived from the sibling parquets). Everything else atlas-root needs
  is range-fetched from the sibling ``neuroscape.parquet``.

atlas.parquet declares the sibling state-keys it was built against;
the writer asserts they're present + correct at emit time (the
browser-side drift check depends on them).
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
    lod,
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
        # Quadtree LOD over the 2D coords. Small resolutions so the 6-row
        # fixture spreads across a couple of representative tiers + a rest
        # tier. tiebreak by pubmed_id → order-independent + reproducible.
        self.resolutions = (2, 4)
        self.n_backdrop_levels = len(self.resolutions)
        self.lod_levels = lod.assign_lod_levels(
            self.embedded_2d,
            resolutions=self.resolutions,
            tiebreak_keys=np.array([a.pubmed_id for a in self.articles], dtype=np.int64),
        )
        # Indices that land in a real backdrop tier (rest tier excluded —
        # atlas-root never fetches the full corpus as a backdrop).
        self.backdrop_indices = [
            i for i, lv in enumerate(self.lod_levels.tolist()) if lv < self.n_backdrop_levels
        ]
        parquet_writer.write_neuroscape_parquet(
            out_path=self.out,
            build_info=_build_info(state_key="ns0000000001"),
            articles=self.articles,
            clusters=self.clusters,
            cluster_counts=cluster_counts,
            palette=self.palette,
            embedded_3d=self.embedded_3d,
            embedded_2d=self.embedded_2d,
            lod_levels=self.lod_levels,
            n_backdrop_levels=self.n_backdrop_levels,
            knn=self.knn,
            titles_index_bin=b"<placeholder title index>",
            titles_index_meta={"schema_version": "search.neuroscape_titles.v1", "n_documents": len(self.articles)},
        )

    def test_outer_rows_match_data_model(self) -> None:
        names = [n for n, _ in _decoded_outer_rows(self.out)]
        expected = [
            "manifest",
            "articles",
            "coords",
            "clusters",
            "neighbors_neuroscape",
            "search:neuroscape_titles",
            "search:neuroscape_titles_meta",
        ] + [f"backdrop_lod{k}" for k in range(self.n_backdrop_levels)]
        self.assertEqual(sorted(names), sorted(expected))
        self.assertNotIn("backdrop_decimated", names)

    def test_manifest_carries_build_info(self) -> None:
        outer = dict(_decoded_outer_rows(self.out))
        manifest_table = _read_inner_table(outer["manifest"])
        manifest_json = manifest_table.column("manifest_json").to_pylist()[0]
        decoded = json.loads(manifest_json)
        self.assertEqual(decoded["schema_version"], "neuroscape.v1")
        self.assertEqual(decoded["build_info"]["state_key"], "ns0000000001")
        self.assertEqual(decoded["n_articles"], len(self.articles))
        self.assertEqual(decoded["n_clusters"], len(self.clusters))
        self.assertEqual(decoded["n_backdrop_levels"], self.n_backdrop_levels)
        sizes = decoded["backdrop_lod_sizes"]
        self.assertEqual(len(sizes), self.n_backdrop_levels)
        self.assertEqual(sum(sizes), len(self.backdrop_indices))

    def test_articles_table_has_no_body_or_coord_columns(self) -> None:
        outer = dict(_decoded_outer_rows(self.out))
        articles = _read_inner_table(outer["articles"])
        columns = set(articles.column_names)
        self.assertEqual(
            columns,
            {"pubmed_id", "title", "year", "cluster_id"},
            msg=(
                "articles stores ONLY identity + search fields. Body "
                "columns (authors, journal, abstract_text, doi) are "
                "fetched at view time per FR-019a; coordinates moved to "
                "the standalone `coords` table so geometry + titles can "
                "be range-fetched independently."
            ),
        )

    def test_coords_table_carries_geometry_cluster_and_lod_level(self) -> None:
        outer = dict(_decoded_outer_rows(self.out))
        coords = _read_inner_table(outer["coords"])
        self.assertEqual(
            set(coords.column_names),
            {"pubmed_id", "cluster_id", "umap_2d", "umap_3d", "lod_level"},
        )
        self.assertEqual(coords.num_rows, len(self.articles))
        self.assertEqual(
            coords.column("pubmed_id").to_pylist(),
            [a.pubmed_id for a in self.articles],
        )
        # lod_level annotates EVERY point (including the rest tier) so
        # neuroscape mode can cap its scatter without an extra fetch.
        self.assertEqual(
            coords.column("lod_level").to_pylist(),
            self.lod_levels.tolist(),
        )

    def test_backdrop_lod_tables_partition_the_sample_by_level(self) -> None:
        outer = dict(_decoded_outer_rows(self.out))
        seen_pmids: list[int] = []
        for k in range(self.n_backdrop_levels):
            tbl = _read_inner_table(outer[f"backdrop_lod{k}"])
            self.assertEqual(
                set(tbl.column_names),
                {"pubmed_id", "cluster_id", "umap_2d", "umap_3d", "title", "year"},
                msg="each backdrop tier is a self-contained scatter sample",
            )
            expected = [
                self.articles[i].pubmed_id
                for i, lv in enumerate(self.lod_levels.tolist())
                if lv == k
            ]
            self.assertEqual(tbl.column("pubmed_id").to_pylist(), expected)
            seen_pmids.extend(tbl.column("pubmed_id").to_pylist())
        # The tiers together equal the representative sample (rest tier
        # excluded) and never duplicate a point.
        self.assertEqual(len(seen_pmids), len(set(seen_pmids)))
        self.assertEqual(
            sorted(seen_pmids),
            sorted(self.articles[i].pubmed_id for i in self.backdrop_indices),
        )

    def test_rest_tier_points_are_in_coords_but_not_in_any_backdrop_tier(self) -> None:
        outer = dict(_decoded_outer_rows(self.out))
        rest_pmids = {
            self.articles[i].pubmed_id
            for i, lv in enumerate(self.lod_levels.tolist())
            if lv >= self.n_backdrop_levels
        }
        if not rest_pmids:
            self.skipTest("fixture produced no rest-tier points")
        backdrop_pmids: set[int] = set()
        for k in range(self.n_backdrop_levels):
            tbl = _read_inner_table(outer[f"backdrop_lod{k}"])
            backdrop_pmids.update(tbl.column("pubmed_id").to_pylist())
        self.assertTrue(rest_pmids.isdisjoint(backdrop_pmids))
        coords_pmids = set(_read_inner_table(outer["coords"]).column("pubmed_id").to_pylist())
        self.assertTrue(rest_pmids.issubset(coords_pmids))

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
        self.ohbm_overlay = _ohbm_overlay(n=4)
        self.ohbm_poster_ids = {sid: 200 + i for i, sid in enumerate(self.ohbm_overlay.submission_ids)}
        self.ohbm_titles = {sid: f"OHBM Title {sid}" for sid in self.ohbm_overlay.submission_ids}
        self.ohbm_nearest_cluster = {sid: 0 for sid in self.ohbm_overlay.submission_ids}
        self.ohbm_2d = _embedded(len(self.ohbm_overlay.submission_ids), 2, seed=99)
        parquet_writer.write_atlas_parquet(
            out_path=self.out,
            build_info=_build_info(state_key="atl000000001"),
            sibling_state_keys={"ohbm2026": "ohbm00000001", "neuroscape": "ns0000000001"},
            ohbm_overlay=self.ohbm_overlay,
            ohbm_overlay_2d=self.ohbm_2d,
            ohbm_poster_ids=self.ohbm_poster_ids,
            ohbm_titles=self.ohbm_titles,
            ohbm_nearest_cluster=self.ohbm_nearest_cluster,
        )

    def test_outer_rows_match_data_model(self) -> None:
        # atlas.parquet carries ONLY the projection that can't be
        # reconstructed from the siblings + the manifest.
        names = [n for n, _ in _decoded_outer_rows(self.out)]
        self.assertEqual(sorted(names), sorted(["manifest", "ohbm_overlay"]))

    def test_manifest_embeds_sibling_state_keys(self) -> None:
        outer = dict(_decoded_outer_rows(self.out))
        manifest = json.loads(_read_inner_table(outer["manifest"]).column("manifest_json").to_pylist()[0])
        self.assertEqual(manifest["schema_version"], "atlas.v1")
        self.assertEqual(manifest["build_info"]["sibling_state_keys"]["ohbm2026"], "ohbm00000001")
        self.assertEqual(manifest["build_info"]["sibling_state_keys"]["neuroscape"], "ns0000000001")
        self.assertEqual(manifest["n_overlay_points"], len(self.ohbm_overlay.submission_ids))

    def test_ohbm_overlay_shape(self) -> None:
        outer = dict(_decoded_outer_rows(self.out))
        ovr = _read_inner_table(outer["ohbm_overlay"])
        self.assertEqual(
            set(ovr.column_names),
            {"submission_id", "poster_id", "umap_2d", "umap_3d", "nearest_cluster_id", "title"},
        )
        self.assertEqual(ovr.num_rows, len(self.ohbm_overlay.submission_ids))


class CrossParquetInvariantTests(unittest.TestCase):
    """atlas.parquet must declare the sibling state-keys it was built
    against — the browser-side drift check (verifyAtlasSiblingDrift)
    is meaningless if these are missing/wrong, so the writer asserts
    them at emit time."""

    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.atlas_path = Path(self._tmp.name) / "atlas.parquet"
        overlay = _ohbm_overlay(4)
        parquet_writer.write_atlas_parquet(
            out_path=self.atlas_path,
            build_info=_build_info(state_key="atl000000001"),
            sibling_state_keys={"ohbm2026": "ohbm00000001", "neuroscape": "ns0000000001"},
            ohbm_overlay=overlay,
            ohbm_overlay_2d=_embedded(4, 2, seed=99),
            ohbm_poster_ids={sid: 200 + i for i, sid in enumerate(overlay.submission_ids)},
            ohbm_titles={sid: f"OHBM {sid}" for sid in overlay.submission_ids},
            ohbm_nearest_cluster={sid: 0 for sid in overlay.submission_ids},
        )

    def test_assert_passes_on_matching_keys(self) -> None:
        parquet_writer.assert_atlas_sibling_keys(
            self.atlas_path,
            {"ohbm2026": "ohbm00000001", "neuroscape": "ns0000000001"},
        )

    def test_assert_raises_on_key_mismatch(self) -> None:
        with self.assertRaises(exceptions.CrossParquetDriftError) as ctx:
            parquet_writer.assert_atlas_sibling_keys(
                self.atlas_path,
                {"ohbm2026": "ohbm00000001", "neuroscape": "STALE0000000"},
            )
        self.assertIn("sibling_state_keys", (ctx.exception.field or "").lower())


if __name__ == "__main__":
    unittest.main()
