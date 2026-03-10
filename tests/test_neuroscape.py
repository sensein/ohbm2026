import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from ohbm2026.neuroscape import (
    DEFAULT_EMBEDDING_FIELDS,
    build_embedding_text,
    build_embedding_texts,
    embedding_variant_name,
    load_stage1_bundle,
    normalize_embedding_fields,
    normalize_hidden_dimensions,
    split_stage2_matrix,
    write_stage2_bundle,
)


class NeuroScapeHelpersTest(unittest.TestCase):
    def test_build_embedding_text_uses_default_fields(self) -> None:
        abstract = {
            "id": 1,
            "title": "Example",
            "introduction_markdown": "Intro",
            "methods_markdown": "Methods",
            "results_markdown": "Results",
            "conclusion_markdown": "Conclusion",
            "discussion_markdown": "Discussion",
        }

        text = build_embedding_text(abstract)

        self.assertIn("Example", text)
        self.assertIn("Introduction:\nIntro", text)
        self.assertIn("Methods:\nMethods", text)
        self.assertIn("Results:\nResults", text)
        self.assertIn("Conclusion:\nConclusion", text)
        self.assertNotIn("Discussion:\nDiscussion", text)

    def test_build_embedding_text_supports_custom_fields(self) -> None:
        abstract = {
            "id": 1,
            "title": "Example",
            "introduction_markdown": "Intro",
            "discussion_markdown": "Discussion",
        }

        text = build_embedding_text(abstract, ["discussion"])

        self.assertEqual(text, "Discussion:\nDiscussion")

    def test_build_embedding_texts_preserves_order(self) -> None:
        abstracts = [
            {"id": 1, "introduction_markdown": "A"},
            {"id": 2, "introduction_markdown": "B"},
        ]

        texts = build_embedding_texts(abstracts, ["title", "introduction"], title_lookup={1: "First", 2: "Second"})

        self.assertEqual(texts[0], "First\n\nIntroduction:\nA")
        self.assertEqual(texts[1], "Second\n\nIntroduction:\nB")

    def test_normalize_embedding_fields_deduplicates(self) -> None:
        self.assertEqual(
            normalize_embedding_fields(["title", "methods", "title", "results"]),
            ["title", "methods", "results"],
        )

    def test_embedding_variant_name_defaults_to_stage1(self) -> None:
        self.assertEqual(embedding_variant_name(DEFAULT_EMBEDDING_FIELDS), "stage1")
        self.assertEqual(embedding_variant_name(["title", "methods"]), "title-methods")

    def test_normalize_hidden_dimensions_requires_three_values(self) -> None:
        self.assertEqual(normalize_hidden_dimensions([12, 8, 4]), (12, 8, 4))
        with self.assertRaises(Exception):
            normalize_hidden_dimensions([12, 8])

    def test_split_stage2_matrix_preserves_row_count(self) -> None:
        import numpy as np

        matrix = np.arange(200, dtype=np.float32).reshape(20, 10)
        train_matrix, validation_matrix = split_stage2_matrix(matrix, validation_size=0.2, seed=7)

        self.assertEqual(train_matrix.shape[0] + validation_matrix.shape[0], 20)
        self.assertEqual(validation_matrix.shape[0], 4)

    def test_write_stage2_bundle_uses_stage1_metadata(self) -> None:
        import json
        import numpy as np
        import torch

        with TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir) / "stage2"
            stage1_bundle = {
                "ids": [1, 2],
                "metadata": [{"id": 1, "accepted_for": "Poster"}, {"id": 2, "accepted_for": "Oral"}],
                "source_metadata": {
                    "embedding_name": "minilm_stage1",
                    "model_name": "sentence-transformers/all-MiniLM-L6-v2",
                    "embedding_fields": ["title", "methods"],
                },
            }
            projected_matrix = np.asarray([[1.0, 0.0], [0.0, 1.0]], dtype=np.float32)
            model = torch.nn.Linear(2, 2)

            write_stage2_bundle(
                output_dir,
                stage1_bundle,
                projected_matrix,
                model,
                {"device": "cpu", "epochs": 2, "batch_size": 4, "best_validation_loss": 0.12},
                hidden_dimensions=(8, 4, 2),
                output_dimension=2,
                dropout=0.1,
            )

            metadata = json.loads((output_dir / "metadata.json").read_text(encoding="utf-8"))
            self.assertEqual(metadata["embedding_name"], "stage2")
            self.assertEqual(metadata["source_embedding_name"], "minilm_stage1")
            self.assertEqual(metadata["count"], 2)
            self.assertTrue((output_dir / "vectors.npy").exists())
            self.assertTrue((output_dir / "neighbors.json").exists())
            self.assertTrue((output_dir / "domain_embedding_model_best.pth").exists())

    def test_load_stage1_bundle_reads_saved_files(self) -> None:
        import json
        import numpy as np

        with TemporaryDirectory() as temp_dir:
            bundle_dir = Path(temp_dir)
            np.save(bundle_dir / "vectors.npy", np.asarray([[1.0, 2.0], [3.0, 4.0]], dtype=np.float32))
            (bundle_dir / "metadata.json").write_text(
                json.dumps(
                    {
                        "ids": [10, 11],
                        "metadata": [{"id": 10}, {"id": 11}],
                        "embedding_name": "minilm_stage1",
                    }
                ),
                encoding="utf-8",
            )

            bundle = load_stage1_bundle(bundle_dir)

            self.assertEqual(bundle["ids"], [10, 11])
            self.assertEqual(tuple(bundle["matrix"].shape), (2, 2))


if __name__ == "__main__":
    unittest.main()
