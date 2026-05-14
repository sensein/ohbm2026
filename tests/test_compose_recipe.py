"""Tests for `embed_compose.compose_recipe`.

The composition contract is documented in
`specs/005-embeddings-matrix/data-model.md` §5: union-of-ids per
abstract; per-abstract mean over the components it has.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import numpy as np

from ohbm2026.embed import compose as embed_compose
from ohbm2026.embed import storage as embed_storage
from ohbm2026.exceptions import EmbeddingError


class _Tmp:
    def __init__(self) -> None:
        self.dir = tempfile.TemporaryDirectory()
        self.path = Path(self.dir.name)

    def cleanup(self) -> None:
        self.dir.cleanup()


def _write_bundle(root: Path, name: str, ids: list[int], vectors: np.ndarray) -> Path:
    """Write a minimal per-component bundle under `root/name/`."""
    bundle_dir = root / name
    metadata = {
        "bundle_name": name,
        "model_key": name.split("_")[0],
        "component": "_".join(name.split("_")[1:]),
        "corpus_state_key": "test",
    }
    embed_storage.write_bundle(bundle_dir, ids=ids, vectors=vectors, metadata=metadata)
    return bundle_dir


class ComposeRecipeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fx = _Tmp()
        self.addCleanup(self.fx.cleanup)

    def test_union_ids_and_average_three_overlapping_bundles(self) -> None:
        # Three components, overlapping id sets:
        # title:        ids=[1, 2, 3]
        # results:      ids=[2, 3]
        # conclusion:   ids=[1, 3]
        # Union: {1, 2, 3}
        # mean for id=1: (title + conclusion) / 2  (results absent)
        # mean for id=2: (title + results) / 2
        # mean for id=3: (title + results + conclusion) / 3
        dim = 4
        title_vecs = np.array([[1, 1, 1, 1], [2, 2, 2, 2], [3, 3, 3, 3]], dtype=np.float32)
        results_vecs = np.array([[20, 20, 20, 20], [30, 30, 30, 30]], dtype=np.float32)
        conclusion_vecs = np.array([[100, 100, 100, 100], [300, 300, 300, 300]], dtype=np.float32)
        _write_bundle(self.fx.path, "voyage_title", [1, 2, 3], title_vecs)
        _write_bundle(self.fx.path, "voyage_results", [2, 3], results_vecs)
        _write_bundle(self.fx.path, "voyage_conclusion", [1, 3], conclusion_vecs)

        recipe = embed_compose.compose_recipe(
            ["title", "results", "conclusion"],
            model_key="voyage",
            bundles_root=self.fx.path,
        )
        ids = recipe["ids"].tolist()
        matrix = recipe["matrix"]
        meta = recipe["metadata"]
        self.assertEqual(ids, [1, 2, 3])
        # id=1 → (title + conclusion) / 2 = (1+100)/2 = 50.5
        np.testing.assert_allclose(matrix[0], np.full(dim, 50.5), atol=1e-5)
        # id=2 → (title + results) / 2 = (2+20)/2 = 11
        np.testing.assert_allclose(matrix[1], np.full(dim, 11.0), atol=1e-5)
        # id=3 → (title + results + conclusion) / 3 = (3+30+300)/3 = 111
        np.testing.assert_allclose(matrix[2], np.full(dim, 111.0), atol=1e-5)
        self.assertEqual(meta["dim"], dim)
        self.assertEqual(meta["n_union"], 3)
        self.assertEqual(meta["present_count_per_id"].tolist(), [2, 2, 3])
        self.assertEqual(meta["missing_per_id"][1], ["results"])
        self.assertEqual(meta["missing_per_id"][2], ["conclusion"])
        self.assertEqual(meta["missing_per_id"][3], [])

    def test_missing_bundle_raises(self) -> None:
        with self.assertRaises(FileNotFoundError):
            embed_compose.compose_recipe(
                ["title"], model_key="voyage", bundles_root=self.fx.path,
            )

    def test_inconsistent_dim_raises(self) -> None:
        _write_bundle(
            self.fx.path, "voyage_title", [1],
            np.zeros((1, 4), dtype=np.float32),
        )
        _write_bundle(
            self.fx.path, "voyage_results", [1],
            np.zeros((1, 8), dtype=np.float32),
        )
        with self.assertRaises(EmbeddingError):
            embed_compose.compose_recipe(
                ["title", "results"], model_key="voyage", bundles_root=self.fx.path,
            )

    def test_single_component_recipe_is_identity(self) -> None:
        # Composing a single-component recipe returns that bundle's
        # vectors unchanged (mean over a single value == that value).
        vecs = np.array([[1.0, 2.0], [3.0, 4.0]], dtype=np.float32)
        _write_bundle(self.fx.path, "voyage_title", [10, 20], vecs)
        recipe = embed_compose.compose_recipe(
            ["title"], model_key="voyage", bundles_root=self.fx.path,
        )
        np.testing.assert_array_equal(recipe["ids"], [10, 20])
        np.testing.assert_allclose(recipe["matrix"], vecs)


if __name__ == "__main__":
    unittest.main()
