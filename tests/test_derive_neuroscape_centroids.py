"""Tests for `scripts/derive_neuroscape_centroids.py`.

Synthetic H5 shards + articles.csv + clusters.csv → derivation
produces a centroid file with correct shape and recorded version
discoverable at runtime by `load_centroid_table`.
"""

from __future__ import annotations

import csv
import importlib.util
import json
import os
import shutil
import sys
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path

import numpy as np


REPO_ROOT = Path(__file__).resolve().parents[1]
DERIVE_SCRIPT = REPO_ROOT / "scripts" / "derive_neuroscape_centroids.py"


def _load_script_module():
    """Load scripts/derive_neuroscape_centroids.py as a module."""
    spec = importlib.util.spec_from_file_location(
        "derive_neuroscape_centroids", DERIVE_SCRIPT
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@contextmanager
def _isolated_cwd():
    original = Path.cwd()
    tmp = tempfile.mkdtemp()
    try:
        os.chdir(tmp)
        yield Path(tmp)
    finally:
        os.chdir(original)
        shutil.rmtree(tmp, ignore_errors=True)


def _seed_neuroscape_inputs(
    input_root: Path,
    *,
    n_clusters: int = 3,
    rows_per_cluster: int = 10,
    dim: int = 64,
) -> dict[str, np.ndarray]:
    """Write `<input_root>/DomainEmbeddings/shard.h5` + articles + clusters CSVs.

    Returns the per-cluster centroid expectations (for test assertions)."""
    import h5py

    input_root.mkdir(parents=True, exist_ok=True)
    (input_root / "DomainEmbeddings").mkdir()

    rng = np.random.default_rng(7)
    # Each cluster has a deliberate direction + small jitter.
    cluster_directions = []
    for c in range(n_clusters):
        d = rng.normal(size=dim).astype(np.float32)
        d = d / np.linalg.norm(d)
        cluster_directions.append(d)

    # Article id -> cluster id
    articles_csv = input_root / "neuroscience_articles_1999-2023.csv"
    clusters_csv = input_root / "neuroscience_clusters_1999-2023.csv"
    article_rows: list[tuple[str, int]] = []

    h5_path = input_root / "DomainEmbeddings" / "shard.h5"
    with h5py.File(h5_path, "w") as fh:
        for c, direction in enumerate(cluster_directions, start=1):
            for r in range(rows_per_cluster):
                aid = f"a{c}_{r}"
                jitter = rng.normal(scale=0.05, size=dim).astype(np.float32)
                v = direction + jitter
                fh.create_dataset(aid, data=v)
                article_rows.append((aid, c))

    with articles_csv.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["ArticleID", "Cluster ID"])
        for aid, cid in article_rows:
            writer.writerow([aid, cid])

    with clusters_csv.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["Cluster ID", "Title", "Description", "Keywords", "Focus"])
        for c in range(1, n_clusters + 1):
            writer.writerow([c, f"Title {c}", f"Description {c}", json.dumps([f"kw{c}"]), "themes"])

    return {
        "cluster_directions": np.stack(cluster_directions, axis=0),
    }


def _seed_nested_neuroscape_inputs(input_root: Path) -> None:
    """Write a compact fixture matching the downloaded NeuroScape layout."""
    import h5py

    csv_root = input_root / "CSV"
    h5_root = input_root / "HDF5" / "DomainEmbeddings"
    csv_root.mkdir(parents=True)
    h5_root.mkdir(parents=True)

    articles_csv = csv_root / "neuroscience_articles_1999-2023.csv"
    with articles_csv.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["Pmid", "Cluster ID"])
        for idx in range(6):
            writer.writerow([1000 + idx, 1 if idx < 3 else 2])

    clusters_csv = csv_root / "neuroscience_clusters_1999-2023.csv"
    with clusters_csv.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["Cluster ID", "Title", "Description", "Keywords", "Focus"])
        writer.writerow([1, "Cluster 1", "Description 1", "alpha; beta", "themes"])
        writer.writerow([2, "Cluster 2", "Description 2", "gamma; delta", "themes"])

    rng = np.random.default_rng(11)
    with h5py.File(h5_root / "shard_0000.h5", "w") as fh:
        embeddings = fh.create_group("embeddings")
        pmids = np.arange(1000, 1006, dtype=np.int32)
        fh.create_dataset("pmid", data=pmids)
        for idx in range(6):
            base = np.zeros(64, dtype=np.float32)
            base[0 if idx < 3 else 1] = 1.0
            vector = base + rng.normal(scale=0.01, size=64).astype(np.float32)
            embeddings.create_dataset(str(idx), data=vector)

    model_path = input_root / "Models" / "domain_embedding_model.pth"
    model_path.parent.mkdir(parents=True)
    model_path.write_bytes(b"stage2")


class DeriveCentroidsTests(unittest.TestCase):
    def test_derivation_over_synthetic_inputs(self) -> None:
        with _isolated_cwd() as tmp:
            input_root = tmp / "data" / "inputs" / "neuroscape"
            expected = _seed_neuroscape_inputs(input_root)
            output_root = tmp / "data" / "inputs" / "neuroscape" / "derived"

            module = _load_script_module()
            rc = module.main([
                "--input-root", str(input_root),
                "--output-root", str(output_root),
            ])
            self.assertEqual(rc, 0)

            # The centroids file must exist with a sha-12 version suffix.
            npys = list(output_root.glob("centroids__*.npy"))
            self.assertEqual(len(npys), 1)
            centroids = np.load(npys[0])
            self.assertEqual(centroids.shape, (3, 64))
            # Each derived centroid should be in the right hemisphere as
            # the original cluster direction. The polar mean_angle recipe
            # is less precise than a cartesian mean on small synthetic
            # clusters (10 rows × 0.05-scale noise), but still recovers
            # the direction qualitatively. The full NeuroScape v1.0.1 data
            # averages over thousands of articles per cluster.
            for i, expected_dir in enumerate(expected["cluster_directions"]):
                cos = float(np.dot(centroids[i], expected_dir))
                self.assertGreater(cos, 0.85)

            # Sidecar must carry the same version in every row.
            sidecar = output_root / "cluster_table.csv"
            self.assertTrue(sidecar.exists())
            with sidecar.open(newline="", encoding="utf-8") as fh:
                rows = list(csv.DictReader(fh))
            self.assertEqual(len(rows), 3)
            versions = {row["centroid_table_version"] for row in rows}
            self.assertEqual(len(versions), 1)
            # Version is the filename's <suffix>
            filename_version = npys[0].stem.split("__", 1)[1]
            self.assertEqual(versions.pop(), filename_version)

    def test_derivation_discovers_downloaded_neuroscape_layout(self) -> None:
        with _isolated_cwd() as tmp:
            input_root = tmp / "NeuroScape" / "Data"
            _seed_nested_neuroscape_inputs(input_root)
            output_root = tmp / "out"

            module = _load_script_module()
            rc = module.main([
                "--input-root", str(input_root),
                "--output-root", str(output_root),
            ])
            self.assertEqual(rc, 0)

            centroids = np.load(sorted(output_root.glob("centroids__*.npy"))[0])
            self.assertEqual(centroids.shape, (2, 64))
            with (output_root / "cluster_table.csv").open(newline="", encoding="utf-8") as fh:
                rows = list(csv.DictReader(fh))
            self.assertEqual([row["Cluster ID"] for row in rows], ["1", "2"])
            self.assertEqual((output_root / "stage2_model.pth").read_bytes(), b"stage2")

    def test_derivation_is_deterministic(self) -> None:
        """Same inputs → same table_version (sha256-based)."""
        with _isolated_cwd() as tmp:
            input_root = tmp / "ns"
            _seed_neuroscape_inputs(input_root)
            out_a = tmp / "out_a"
            out_b = tmp / "out_b"

            module = _load_script_module()
            module.main(["--input-root", str(input_root), "--output-root", str(out_a)])
            module.main(["--input-root", str(input_root), "--output-root", str(out_b)])

            a = sorted(out_a.glob("centroids__*.npy"))[0]
            b = sorted(out_b.glob("centroids__*.npy"))[0]
            self.assertEqual(a.name, b.name)

    def test_version_derived_from_grouped_vectors(self) -> None:
        """Changing any H5 source vector changes the centroid table version."""
        import h5py

        with _isolated_cwd() as tmp:
            input_root = tmp / "ns"
            _seed_neuroscape_inputs(input_root)
            out_a = tmp / "out_a"
            out_b = tmp / "out_b"

            module = _load_script_module()
            module.main(["--input-root", str(input_root), "--output-root", str(out_a)])

            shard = input_root / "DomainEmbeddings" / "shard.h5"
            with h5py.File(shard, "r+") as fh:
                vector = fh["a1_0"][()].astype(np.float32)
                vector[0] += np.float32(0.5)
                fh["a1_0"][...] = vector

            module.main(["--input-root", str(input_root), "--output-root", str(out_b)])

            a = sorted(out_a.glob("centroids__*.npy"))[0]
            b = sorted(out_b.glob("centroids__*.npy"))[0]
            self.assertNotEqual(a.name, b.name)

    def test_load_centroid_table_round_trip(self) -> None:
        """Derived file + sidecar must be readable by load_centroid_table."""
        from ohbm2026.analyze.centroids import load_centroid_table

        with _isolated_cwd() as tmp:
            input_root = tmp / "ns"
            _seed_neuroscape_inputs(input_root)
            output_root = tmp / "out"
            module = _load_script_module()
            module.main(["--input-root", str(input_root), "--output-root", str(output_root)])

            table = load_centroid_table(output_root)
            self.assertEqual(table.centroids.shape, (3, 64))
            self.assertEqual(len(table.labels), 3)
            self.assertEqual(table.labels[1]["Title"], "Title 1")

    def test_centroid_metadata_written(self) -> None:
        """Derivation must emit `centroid_metadata.json` with the
        runtime-discoverable fields (FR-008 + CA-007)."""
        with _isolated_cwd() as tmp:
            input_root = tmp / "ns"
            _seed_neuroscape_inputs(input_root)
            output_root = tmp / "out"
            module = _load_script_module()
            module.main(["--input-root", str(input_root), "--output-root", str(output_root)])

            metadata_path = output_root / "centroid_metadata.json"
            self.assertTrue(metadata_path.exists())
            meta = json.loads(metadata_path.read_text(encoding="utf-8"))
            # Required fields
            self.assertIn("centroid_table_version", meta)
            self.assertIn("source_csv_sha256s", meta)
            self.assertIn("hdf5_shard_manifest_sha256", meta)
            self.assertIn("cluster_count", meta)
            self.assertIn("cluster_ids", meta)
            self.assertEqual(meta["cluster_count"], 3)
            self.assertEqual(sorted(meta["cluster_ids"]), [1, 2, 3])
            # CSV sha256s should be 64-hex digests
            self.assertEqual(len(set(meta["source_csv_sha256s"].keys())), 2)
            for sha in meta["source_csv_sha256s"].values():
                self.assertEqual(len(sha), 64)
            # HDF5 manifest is also a 64-hex sha256
            self.assertEqual(len(meta["hdf5_shard_manifest_sha256"]), 64)
            # No domain model in the synthetic test inputs (the helper
            # doesn't write one), so checkpoint_sha may be None.
            self.assertIn("domain_model_checkpoint_sha256", meta)


if __name__ == "__main__":
    unittest.main()
