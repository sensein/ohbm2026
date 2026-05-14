"""Tests for Stage 3's typed exception hierarchy.

Mirrors `tests/test_stage2_exceptions.py` if it exists, but kept
standalone so the Stage 3 import surface stays auditable.
"""

from __future__ import annotations

import unittest

from ohbm2026 import exceptions


class Stage3ExceptionTreeTests(unittest.TestCase):
    def test_stage3_base_is_a_runtimeerror(self) -> None:
        self.assertTrue(issubclass(exceptions.Stage3Error, exceptions.OhbmStageError))
        self.assertTrue(issubclass(exceptions.Stage3Error, RuntimeError))

    def test_embedding_error_subclasses_stage3(self) -> None:
        self.assertTrue(issubclass(exceptions.EmbeddingError, exceptions.Stage3Error))

    def test_provider_budget_contract_assembly_threshold_subclasses(self) -> None:
        cases = [
            (exceptions.EmbeddingProviderError, exceptions.EmbeddingError),
            (exceptions.EmbeddingBudgetError, exceptions.EmbeddingError),
            (exceptions.EmbeddingContractError, exceptions.EmbeddingError),
            (exceptions.ComponentAssemblyError, exceptions.Stage3Error),
            (exceptions.EmbeddingThresholdError, exceptions.Stage3Error),
        ]
        for cls, parent in cases:
            with self.subTest(cls=cls.__name__):
                self.assertTrue(issubclass(cls, parent))

    def test_all_public_names_exported(self) -> None:
        expected = {
            "Stage3Error",
            "EmbeddingError",
            "EmbeddingProviderError",
            "EmbeddingBudgetError",
            "EmbeddingContractError",
            "ComponentAssemblyError",
            "EmbeddingThresholdError",
        }
        self.assertTrue(expected.issubset(set(exceptions.__all__)))


if __name__ == "__main__":
    unittest.main()
