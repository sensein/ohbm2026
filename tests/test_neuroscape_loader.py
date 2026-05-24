"""Tests for ``ohbm2026.atlas_package.neuroscape_loader``.

Spec: ``specs/015-neuroscape-context/`` — research R-001 + data-model
``NeuroScapeArticle`` / ``NeuroScapeCluster`` + research R-009
(``NeuroScapeInputError``). The loader extends the discovery
conventions of ``scripts/derive_neuroscape_centroids.py`` into a
callable + adds typed-exception failure modes.

Per the 2026-05-23 user directive, no unit test reads from the
~10 GB real release — every test uses the synthetic 6-article
fixture from :mod:`tests._atlas_fixtures`.
"""

from __future__ import annotations

import hashlib
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np

from ohbm2026 import exceptions
from ohbm2026.atlas_package import neuroscape_loader

from tests._atlas_fixtures import (
    FIXTURE_CLUSTERS_TOP_LEVEL,
    FIXTURE_CLUSTER_FOR_PMID,
    FIXTURE_PMIDS,
    MODEL_CHECKPOINT_STUB_BYTES,
    write_v101_fixture,
)


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class DiscoverInputsHappyPathTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.fixture_root = write_v101_fixture(Path(self._tmp.name))

    def test_returns_inputbundle_with_resolved_csv_paths(self) -> None:
        bundle = neuroscape_loader.discover_inputs(self.fixture_root)
        self.assertTrue(bundle.articles_csv.name.startswith("neuroscience_articles_"))
        self.assertTrue(bundle.clusters_csv.name.startswith("neuroscience_clusters_"))
        self.assertTrue(bundle.articles_csv.exists())
        self.assertTrue(bundle.clusters_csv.exists())

    def test_resolves_model_checkpoint(self) -> None:
        bundle = neuroscape_loader.discover_inputs(self.fixture_root)
        self.assertEqual(bundle.model_checkpoint.name, "domain_embedding_model.pth")
        self.assertEqual(bundle.model_checkpoint_sha256, hashlib.sha256(MODEL_CHECKPOINT_STUB_BYTES).hexdigest())

    def test_resolves_two_hdf5_shards_in_sorted_order(self) -> None:
        bundle = neuroscape_loader.discover_inputs(self.fixture_root)
        self.assertEqual(len(bundle.hdf5_shards), 2)
        names = [p.name for p in bundle.hdf5_shards]
        self.assertEqual(names, sorted(names))
        self.assertTrue(all(p.suffix == ".h5" for p in bundle.hdf5_shards))

    def test_records_sha256s_for_every_discovered_file(self) -> None:
        bundle = neuroscape_loader.discover_inputs(self.fixture_root)
        self.assertEqual(bundle.articles_csv_sha256, _sha256_file(bundle.articles_csv))
        self.assertEqual(bundle.clusters_csv_sha256, _sha256_file(bundle.clusters_csv))
        # The shard manifest sha is computed over the sorted
        # (shard_name, shard_sha) pairs so a change in any shard
        # surfaces as a single drift signal.
        self.assertRegex(bundle.hdf5_shard_manifest_sha256, r"^[0-9a-f]{64}$")


class DiscoverInputsRejectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.fixture_root = write_v101_fixture(Path(self._tmp.name))

    def test_missing_root_raises(self) -> None:
        missing = Path(self._tmp.name) / "does-not-exist"
        with self.assertRaises(exceptions.NeuroScapeInputError) as ctx:
            neuroscape_loader.discover_inputs(missing)
        self.assertIsNotNone(ctx.exception.file)

    def test_missing_articles_csv_raises(self) -> None:
        (self.fixture_root / "Data" / "CSV" / "neuroscience_articles_1999-2023.csv").unlink()
        with self.assertRaises(exceptions.NeuroScapeInputError) as ctx:
            neuroscape_loader.discover_inputs(self.fixture_root)
        self.assertIn("articles", (ctx.exception.file or "").lower())

    def test_missing_clusters_csv_raises(self) -> None:
        (self.fixture_root / "Data" / "CSV" / "neuroscience_clusters_1999-2023.csv").unlink()
        with self.assertRaises(exceptions.NeuroScapeInputError) as ctx:
            neuroscape_loader.discover_inputs(self.fixture_root)
        self.assertIn("clusters", (ctx.exception.file or "").lower())

    def test_missing_model_checkpoint_raises(self) -> None:
        (self.fixture_root / "Data" / "Models" / "domain_embedding_model.pth").unlink()
        with self.assertRaises(exceptions.NeuroScapeInputError) as ctx:
            neuroscape_loader.discover_inputs(self.fixture_root)
        self.assertIn("domain_embedding_model.pth", (ctx.exception.file or ""))

    def test_empty_hdf5_dir_raises(self) -> None:
        for shard in (self.fixture_root / "Data" / "HDF5" / "DomainEmbeddings").glob("*.h5"):
            shard.unlink()
        with self.assertRaises(exceptions.NeuroScapeInputError) as ctx:
            neuroscape_loader.discover_inputs(self.fixture_root)
        self.assertIn("hdf5", (ctx.exception.file or "").lower())


class IterStage2VectorsTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.fixture_root = write_v101_fixture(Path(self._tmp.name))
        self.bundle = neuroscape_loader.discover_inputs(self.fixture_root)

    def test_yields_one_pair_per_fixture_article(self) -> None:
        pairs = list(neuroscape_loader.iter_stage2_vectors(self.bundle))
        self.assertEqual(len(pairs), len(FIXTURE_PMIDS))

    def test_pmids_match_fixture_set(self) -> None:
        pairs = list(neuroscape_loader.iter_stage2_vectors(self.bundle))
        self.assertEqual(sorted(pmid for pmid, _ in pairs), sorted(FIXTURE_PMIDS))

    def test_vectors_are_float32_64dim_unit_norm(self) -> None:
        for pmid, vec in neuroscape_loader.iter_stage2_vectors(self.bundle):
            self.assertEqual(vec.dtype, np.float32, msg=f"pmid {pmid}")
            self.assertEqual(vec.shape, (64,), msg=f"pmid {pmid}")
            self.assertAlmostEqual(float(np.linalg.norm(vec)), 1.0, places=5, msg=f"pmid {pmid}")


class LoadClustersTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.fixture_root = write_v101_fixture(Path(self._tmp.name))
        self.bundle = neuroscape_loader.discover_inputs(self.fixture_root)

    def test_returns_only_top_level_clusters_referenced_by_articles(self) -> None:
        clusters = neuroscape_loader.load_clusters(self.bundle)
        cluster_ids = sorted(c.cluster_id for c in clusters)
        self.assertEqual(cluster_ids, list(FIXTURE_CLUSTERS_TOP_LEVEL))

    def test_clusters_carry_title_description_keywords_focus(self) -> None:
        clusters = {c.cluster_id: c for c in neuroscape_loader.load_clusters(self.bundle)}
        c0 = clusters[0]
        self.assertEqual(c0.title, "Synthetic Hippocampal Memory")
        self.assertIn("place cells", c0.keywords)
        self.assertIn("hippocampal", c0.description.lower())
        self.assertEqual(c0.focus, "Spatial memory")

    def test_keywords_are_decoded_from_upstream_json_string(self) -> None:
        clusters = neuroscape_loader.load_clusters(self.bundle)
        # Every keyword field MUST be a tuple of strings (the upstream
        # CSV encodes them as a JSON-encoded list inside a single cell).
        for c in clusters:
            self.assertIsInstance(c.keywords, tuple)
            for k in c.keywords:
                self.assertIsInstance(k, str)


class ArticleClusterAssignmentTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.fixture_root = write_v101_fixture(Path(self._tmp.name))
        self.bundle = neuroscape_loader.discover_inputs(self.fixture_root)

    def test_iter_articles_returns_pmid_year_title_cluster_id(self) -> None:
        articles = list(neuroscape_loader.iter_articles(self.bundle))
        self.assertEqual({a.pubmed_id for a in articles}, set(FIXTURE_PMIDS))
        # Cluster assignment matches the fixture's mapping.
        for a in articles:
            self.assertEqual(a.cluster_id, FIXTURE_CLUSTER_FOR_PMID[a.pubmed_id])
        # Local-only fields (title, year) are populated; the body
        # fields (abstract / authors / doi / journal) are NOT exposed
        # by the loader — they live only in the source release.
        for a in articles:
            self.assertIsInstance(a.title, str)
            self.assertTrue(a.title)
            self.assertIsInstance(a.year, int)
            self.assertGreaterEqual(a.year, 1999)
            self.assertLessEqual(a.year, 2023)


if __name__ == "__main__":
    unittest.main()
