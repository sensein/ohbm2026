"""Tests for ``ohbm2026.atlas_package.semantic_index`` (spec 019, T009 + T018).

Covers:
- INV-003 enforcement (pubmed_id set mismatch raises VectorsParquetWriteError)
- Shape / dtype gate
- Row sort: rows arrive sorted by (cluster_id, pubmed_id) regardless of input order
- Byte-identity: two writes with identical inputs produce sha256-equal parquets (SC-004)
- Manifest round-trip via read_manifest()
- Row-group statistics include cluster_id min/max so predicate pushdown works
"""

from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np
import pyarrow.parquet as pq

from ohbm2026 import exceptions
from ohbm2026.atlas_package import semantic_index


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _synthetic(n_clusters: int = 3, per_cluster: int = 20) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Build (cluster_ids, pubmed_ids, vectors) with deterministic content."""
    cluster_ids = np.repeat(np.arange(n_clusters, dtype=np.int16), per_cluster)
    pubmed_ids = np.arange(100, 100 + n_clusters * per_cluster, dtype=np.int64)
    # INT8 vectors with predictable pattern.
    rng = np.random.default_rng(seed=42)
    vectors = rng.integers(-127, 127, size=(n_clusters * per_cluster, semantic_index.VECTOR_DIM), dtype=np.int8)
    return cluster_ids, pubmed_ids, vectors


def _manifest() -> dict:
    return {
        "schema_version": "semantic_vectors.v1",
        "corpus": "neuroscape",
        "state_key": "abc123def456",
        "code_revision": "test",
        "command_line": "ohbmcli build-atlas-package --semantic-index",
        "seed": 0,
        "model_id": "Xenova/all-MiniLM-L6-v2",
        "model_sha256": "deadbeef" * 8,
        "vector_dim": 384,
        "quantization": "int8-global-scale",
        "scale": 100.0,
        "max_abs_original": 1.27,
        "n_vectors": 60,
        "cluster_count": 3,
        "row_group_size": semantic_index.ROW_GROUP_SIZE,
        "build_started_utc": "2026-05-28T00:00:00Z",
        "build_finished_utc": "2026-05-28T00:00:01Z",
    }


class WriteHappyPathTests(unittest.TestCase):
    def test_writes_file_at_target_path(self) -> None:
        c, p, v = _synthetic()
        with TemporaryDirectory() as tmp:
            out = Path(tmp) / "neuroscape_vectors.parquet"
            written = semantic_index.write_neuroscape_vectors_parquet(
                out_path=out,
                cluster_ids=c,
                pubmed_ids=p,
                vectors=v,
                expected_pubmed_id_set=p.tolist(),
                manifest=_manifest(),
            )
            self.assertEqual(written, out)
            self.assertTrue(out.exists())

    def test_columns_are_in_documented_order_and_types(self) -> None:
        c, p, v = _synthetic()
        with TemporaryDirectory() as tmp:
            out = Path(tmp) / "v.parquet"
            semantic_index.write_neuroscape_vectors_parquet(
                out_path=out,
                cluster_ids=c,
                pubmed_ids=p,
                vectors=v,
                expected_pubmed_id_set=p.tolist(),
                manifest=_manifest(),
            )
            t = pq.read_table(out)
            self.assertEqual(t.column_names, ["cluster_id", "pubmed_id", "minilm_vector"])
            self.assertEqual(str(t.schema.field("cluster_id").type), "int16")
            self.assertEqual(str(t.schema.field("pubmed_id").type), "int64")
            # Fixed-length binary of 384 bytes per row.
            self.assertEqual(str(t.schema.field("minilm_vector").type), "fixed_size_binary[384]")

    def test_rows_sorted_by_cluster_then_pubmed(self) -> None:
        # Input deliberately scrambled.
        c = np.array([2, 0, 1, 0, 2, 1], dtype=np.int16)
        p = np.array([200, 100, 150, 99, 199, 151], dtype=np.int64)
        v = np.full((6, semantic_index.VECTOR_DIM), 0, dtype=np.int8)
        with TemporaryDirectory() as tmp:
            out = Path(tmp) / "v.parquet"
            semantic_index.write_neuroscape_vectors_parquet(
                out_path=out,
                cluster_ids=c,
                pubmed_ids=p,
                vectors=v,
                expected_pubmed_id_set=p.tolist(),
                manifest=_manifest(),
            )
            t = pq.read_table(out)
            cluster_col = t.column("cluster_id").to_pylist()
            pubmed_col = t.column("pubmed_id").to_pylist()
            self.assertEqual(cluster_col, [0, 0, 1, 1, 2, 2])
            self.assertEqual(pubmed_col, [99, 100, 150, 151, 199, 200])


class WriteByteIdentityTests(unittest.TestCase):
    """SC-004 byte-identity contract for the sibling vectors parquet."""

    def test_two_writes_with_identical_inputs_produce_sha256_equal_files(self) -> None:
        c, p, v = _synthetic()
        manifest = _manifest()
        with TemporaryDirectory() as tmp1, TemporaryDirectory() as tmp2:
            a = Path(tmp1) / "v.parquet"
            b = Path(tmp2) / "v.parquet"
            for path in (a, b):
                semantic_index.write_neuroscape_vectors_parquet(
                    out_path=path,
                    cluster_ids=c,
                    pubmed_ids=p,
                    vectors=v,
                    expected_pubmed_id_set=p.tolist(),
                    manifest=manifest,
                )
            self.assertEqual(_sha256(a), _sha256(b))


class WriteInvariantTests(unittest.TestCase):
    def test_pubmed_id_set_mismatch_raises_with_reason(self) -> None:
        c, p, v = _synthetic(n_clusters=2, per_cluster=5)
        expected = set(p.tolist())
        expected.add(999_999)  # introduce a missing id
        with TemporaryDirectory() as tmp:
            with self.assertRaises(exceptions.VectorsParquetWriteError) as ctx:
                semantic_index.write_neuroscape_vectors_parquet(
                    out_path=Path(tmp) / "v.parquet",
                    cluster_ids=c,
                    pubmed_ids=p,
                    vectors=v,
                    expected_pubmed_id_set=expected,
                    manifest=_manifest(),
                )
            self.assertEqual(ctx.exception.reason, "pubmed_id_set_mismatch")

    def test_wrong_shape_raises(self) -> None:
        c, p, _ = _synthetic(n_clusters=2, per_cluster=5)
        bad = np.zeros((10, 256), dtype=np.int8)
        with TemporaryDirectory() as tmp:
            with self.assertRaises(exceptions.VectorsParquetWriteError) as ctx:
                semantic_index.write_neuroscape_vectors_parquet(
                    out_path=Path(tmp) / "v.parquet",
                    cluster_ids=c,
                    pubmed_ids=p,
                    vectors=bad,
                    expected_pubmed_id_set=p.tolist(),
                    manifest=_manifest(),
                )
            self.assertEqual(ctx.exception.reason, "shape_mismatch")

    def test_wrong_dtype_raises(self) -> None:
        c, p, v = _synthetic(n_clusters=2, per_cluster=5)
        with TemporaryDirectory() as tmp:
            with self.assertRaises(exceptions.VectorsParquetWriteError) as ctx:
                semantic_index.write_neuroscape_vectors_parquet(
                    out_path=Path(tmp) / "v.parquet",
                    cluster_ids=c,
                    pubmed_ids=p,
                    vectors=v.astype(np.float32),
                    expected_pubmed_id_set=p.tolist(),
                    manifest=_manifest(),
                )
            self.assertEqual(ctx.exception.reason, "dtype_mismatch")


class WriteManifestTests(unittest.TestCase):
    def test_manifest_round_trips_via_read_manifest(self) -> None:
        c, p, v = _synthetic()
        m = _manifest()
        with TemporaryDirectory() as tmp:
            out = Path(tmp) / "v.parquet"
            semantic_index.write_neuroscape_vectors_parquet(
                out_path=out,
                cluster_ids=c,
                pubmed_ids=p,
                vectors=v,
                expected_pubmed_id_set=p.tolist(),
                manifest=m,
            )
            read = semantic_index.read_manifest(out)
            self.assertEqual(read["state_key"], m["state_key"])
            self.assertEqual(read["model_sha256"], m["model_sha256"])
            self.assertEqual(read["scale"], m["scale"])
            self.assertEqual(read["row_group_size"], m["row_group_size"])


class RowGroupStatsTests(unittest.TestCase):
    """The browser's predicate-pushdown for `cluster_id == X` depends on
    row-group min/max statistics being populated on the cluster_id column.
    """

    def test_cluster_id_min_max_statistics_populated(self) -> None:
        c, p, v = _synthetic(n_clusters=3, per_cluster=100)
        with TemporaryDirectory() as tmp:
            out = Path(tmp) / "v.parquet"
            semantic_index.write_neuroscape_vectors_parquet(
                out_path=out,
                cluster_ids=c,
                pubmed_ids=p,
                vectors=v,
                expected_pubmed_id_set=p.tolist(),
                manifest=_manifest(),
            )
            md = pq.ParquetFile(out).metadata
            saw_cluster_stats = False
            for rg_idx in range(md.num_row_groups):
                rg = md.row_group(rg_idx)
                for col_idx in range(rg.num_columns):
                    col = rg.column(col_idx)
                    if col.path_in_schema == "cluster_id":
                        self.assertIsNotNone(col.statistics)
                        # Pyarrow's stats expose min/max via .min/.max.
                        self.assertIsNotNone(col.statistics.min)
                        self.assertIsNotNone(col.statistics.max)
                        saw_cluster_stats = True
            self.assertTrue(saw_cluster_stats, "no cluster_id stats found in any row group")


if __name__ == "__main__":
    unittest.main()
