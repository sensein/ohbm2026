"""Tests for `ohbm2026.analyze.rollup.write_rollup`.

Per contracts/rollup.md, the parquet + sqlite forms are
content-equivalent: same column count, same row count, same
`cluster_topics` rows.
"""

from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

import numpy as np

from ohbm2026.analyze.rollup import (
    build_rollup_tables,
    load_neuroscape_cluster_table,
    write_rollup,
)
from ohbm2026.analyze.storage import write_analysis_bundle


def _prov(kind: str, input_key: str, bundle_dir_rel: str) -> dict:
    return {
        "schema_version": "stage4.provenance.v1",
        "stage": "analysis",
        "kind": kind,
        "bundle_path": bundle_dir_rel,
        "corpus_state_key": "abc",
        "input_source_assembly_hash": "xyz",
        "algorithm_config_canonical_json": "{}",
        "cache_key": "k",
        "code_revision": "r",
        "command": "cmd",
        "seed": 42,
        "started_at": "t",
        "completed_at": "t",
    }


class BuildRollupTablesTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _write_projections_bundle(
        self, input_key: str, ids: list[int]
    ) -> Path:
        bundle = self.root / input_key / "projections__abc"
        ids_arr = np.asarray(ids, dtype=np.int64)
        coords2d = np.stack([np.arange(len(ids), dtype=np.float32)] * 2, axis=1)
        coords3d = np.stack(
            [np.arange(len(ids), dtype=np.float32)] * 3, axis=1
        )
        write_analysis_bundle(
            bundle,
            ids=ids_arr,
            payload={"umap2d_coords": coords2d, "umap3d_coords": coords3d},
            metadata={"kind": "projections", "n_rows": len(ids)},
            provenance=_prov(
                "projections", input_key, f"data/outputs/analysis/{input_key}/projections__abc/"
            ),
        )
        return bundle

    def _write_communities_bundle(
        self, input_key: str, ids: list[int], community_ids: list[int]
    ) -> Path:
        bundle = self.root / input_key / "communities__def"
        write_analysis_bundle(
            bundle,
            ids=np.asarray(ids, dtype=np.int64),
            payload={"community_ids": np.asarray(community_ids, dtype=np.int32)},
            metadata={"kind": "communities"},
            provenance=_prov(
                "communities", input_key, f"data/outputs/analysis/{input_key}/communities__def/"
            ),
            topics={
                0: {"Keywords": ["alpha", "beta"], "Title": "Title 0", "Description": "D0", "Focus": "themes"},
                1: {"Keywords": ["gamma"], "Title": "Title 1", "Description": "D1", "Focus": "themes"},
            },
        )
        return bundle

    def test_projections_columns_present(self) -> None:
        self._write_projections_bundle("voyage_abstract", [10, 20, 30])
        columns, rows, _ = build_rollup_tables(self.root)
        self.assertIn("umap2d_voyage_x", columns)
        self.assertIn("umap2d_voyage_y", columns)
        self.assertIn("umap3d_voyage_x", columns)
        self.assertIn("umap3d_voyage_y", columns)
        self.assertIn("umap3d_voyage_z", columns)
        self.assertEqual(len(rows), 3)
        self.assertEqual([r.abstract_id for r in rows], [10, 20, 30])

    def test_communities_emits_cluster_topics(self) -> None:
        self._write_communities_bundle("voyage_abstract", [1, 2, 3], [0, 0, 1])
        columns, rows, cluster_topics = build_rollup_tables(self.root)
        self.assertIn("community_voyage_abstract", columns)
        topics_by_id = {t.cluster_id: t for t in cluster_topics}
        self.assertEqual(set(topics_by_id.keys()), {0, 1})
        self.assertEqual(topics_by_id[0].topic_title, "Title 0")
        self.assertEqual(
            json.loads(topics_by_id[0].topic_keywords),
            ["alpha", "beta"],
        )

    def test_column_order_deterministic_across_models(self) -> None:
        """SC: reordering bundles on disk should not change column order
        (canonical sort lives in build_rollup_tables)."""
        self._write_projections_bundle("voyage_abstract", [1])
        self._write_projections_bundle("minilm_abstract", [1])
        cols_a, _, _ = build_rollup_tables(self.root)

        # Same content, different model order in source — should match.
        with tempfile.TemporaryDirectory() as tmp2:
            root2 = Path(tmp2)
            for model in ("minilm", "voyage"):  # reversed write order
                bundle = root2 / f"{model}_abstract" / "projections__abc"
                ids = np.asarray([1], dtype=np.int64)
                write_analysis_bundle(
                    bundle,
                    ids=ids,
                    payload={
                        "umap2d_coords": np.zeros((1, 2), dtype=np.float32),
                        "umap3d_coords": np.zeros((1, 3), dtype=np.float32),
                    },
                    metadata={},
                    provenance=_prov(
                        "projections",
                        f"{model}_abstract",
                        f"data/outputs/analysis/{model}_abstract/projections__abc/",
                    ),
                )
            cols_b, _, _ = build_rollup_tables(root2)
        self.assertEqual(cols_a, cols_b)


class WriteRollupShapeEquivalenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name) / "analysis"
        self.parquet = Path(self._tmp.name) / "annotations__test.parquet"
        self.sqlite_db = Path(self._tmp.name) / "annotations__test.sqlite"

        # Fixture: projections + communities for voyage_abstract.
        bundle = self.root / "voyage_abstract" / "projections__abc"
        ids = np.asarray([10, 20], dtype=np.int64)
        write_analysis_bundle(
            bundle,
            ids=ids,
            payload={
                "umap2d_coords": np.asarray([[0.1, 0.2], [0.3, 0.4]], dtype=np.float32),
                "umap3d_coords": np.asarray(
                    [[0.5, 0.6, 0.7], [0.8, 0.9, 1.0]], dtype=np.float32
                ),
            },
            metadata={},
            provenance=_prov(
                "projections",
                "voyage_abstract",
                "data/outputs/analysis/voyage_abstract/projections__abc/",
            ),
        )
        comm_bundle = self.root / "voyage_abstract" / "communities__def"
        write_analysis_bundle(
            comm_bundle,
            ids=ids,
            payload={"community_ids": np.asarray([0, 1], dtype=np.int32)},
            metadata={},
            provenance=_prov(
                "communities",
                "voyage_abstract",
                "data/outputs/analysis/voyage_abstract/communities__def/",
            ),
            topics={
                0: {"Keywords": ["a"], "Title": "T0", "Description": "D0", "Focus": "themes"},
                1: {"Keywords": ["b"], "Title": "T1", "Description": "D1", "Focus": "themes"},
            },
        )

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_parquet_and_sqlite_have_same_row_count(self) -> None:
        write_rollup(
            self.root, parquet_path=self.parquet, sqlite_path=self.sqlite_db
        )
        import pyarrow.parquet as pq

        parquet_rows = pq.read_table(self.parquet).num_rows
        conn = sqlite3.connect(str(self.sqlite_db))
        try:
            sqlite_rows = conn.execute("SELECT COUNT(*) FROM annotations").fetchone()[0]
        finally:
            conn.close()
        self.assertEqual(parquet_rows, sqlite_rows)
        self.assertEqual(parquet_rows, 2)

    def test_cluster_topics_round_trip_in_sqlite(self) -> None:
        write_rollup(
            self.root, parquet_path=self.parquet, sqlite_path=self.sqlite_db
        )
        conn = sqlite3.connect(str(self.sqlite_db))
        try:
            rows = conn.execute(
                """SELECT clustering_method, model_key, input_source, cluster_id, topic_keywords, topic_title
                   FROM cluster_topics ORDER BY cluster_id"""
            ).fetchall()
        finally:
            conn.close()
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0][0], "communities")
        self.assertEqual(rows[0][1], "voyage")
        self.assertEqual(rows[0][2], "abstract")
        self.assertEqual(rows[0][3], 0)
        self.assertEqual(json.loads(rows[0][4]), ["a"])
        self.assertEqual(rows[0][5], "T0")

    def test_neuroscape_cluster_table_join(self) -> None:
        """`neuroscape_clusters` bundle joins via cluster_table.csv."""
        # Write a neuroscape_clusters bundle
        bundle = self.root / "voyage_abstract" / "neuroscape_clusters__nsc"
        ids = np.asarray([10, 20], dtype=np.int64)
        write_analysis_bundle(
            bundle,
            ids=ids,
            payload={
                "neuroscape_cluster_ids": np.asarray([5, 5], dtype=np.int32),
                "neuroscape_cluster_distances": np.asarray([0.2, 0.3], dtype=np.float32),
            },
            metadata={},
            provenance=_prov(
                "neuroscape_clusters",
                "voyage_abstract",
                "data/outputs/analysis/voyage_abstract/neuroscape_clusters__nsc/",
            ),
        )
        # Synthesize a cluster_table.csv
        cluster_table = {
            5: {
                "Title": "DMN cluster",
                "Description": "Default mode network studies",
                "Keywords": ["DMN", "resting-state"],
                "Focus": "themes",
            }
        }
        write_rollup(
            self.root,
            parquet_path=self.parquet,
            sqlite_path=self.sqlite_db,
            neuroscape_cluster_table=cluster_table,
        )
        conn = sqlite3.connect(str(self.sqlite_db))
        try:
            rows = conn.execute(
                """SELECT cluster_id, topic_title, topic_keywords
                   FROM cluster_topics
                   WHERE clustering_method='neuroscape_clusters'"""
            ).fetchall()
        finally:
            conn.close()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][0], 5)
        self.assertEqual(rows[0][1], "DMN cluster")
        self.assertEqual(json.loads(rows[0][2]), ["DMN", "resting-state"])


class LoadNeuroscapeClusterTableTests(unittest.TestCase):
    def test_reads_keywords_as_json_list(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "cluster_table.csv"
            path.write_text(
                'Cluster ID,Title,Description,Keywords,Focus\n'
                '5,DMN,Default mode,"[""dmn"", ""rest""]",themes\n'
                '7,Visual,Visual processing,"[""V1""]",methodologies\n',
                encoding="utf-8",
            )
            table = load_neuroscape_cluster_table(path)
            self.assertEqual(set(table.keys()), {5, 7})
            self.assertEqual(table[5]["Keywords"], ["dmn", "rest"])
            self.assertEqual(table[7]["Focus"], "methodologies")

    def test_missing_file_returns_empty(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(load_neuroscape_cluster_table(Path(tmp) / "nope.csv"), {})


if __name__ == "__main__":
    unittest.main()
