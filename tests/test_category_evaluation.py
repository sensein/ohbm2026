import json
import tempfile
import unittest
from pathlib import Path

import numpy as np

from ohbm2026 import category_evaluation


def _response(parent: str, subcategory: str) -> dict[str, str]:
    return {
        "question_name": "Primary Parent Category & Sub-Category",
        "value": json.dumps([parent, subcategory]),
    }


def _abstract(
    abstract_id: int,
    accepted_for: str,
    title: str,
    parent: str,
    subcategory: str,
) -> dict[str, object]:
    return {
        "id": abstract_id,
        "accepted_for": accepted_for,
        "title": title,
        "responses": [_response(parent, subcategory)],
    }


class CategoryEvaluationTest(unittest.TestCase):
    def _build_fixture(self, root: Path) -> tuple[Path, Path, Path]:
        abstracts = [
            _abstract(1, "Poster", "Memory one", "Systems", "Memory"),
            _abstract(2, "Poster", "Memory two", "Systems", "Memory"),
            _abstract(3, "Poster", "Vision one", "Systems", "Vision"),
            _abstract(4, "Poster", "Vision two", "Systems", "Vision"),
            _abstract(5, "Oral", "Methods one", "Methods", "Modeling"),
            _abstract(6, "Oral", "Methods two", "Methods", "Modeling"),
        ]
        raw_input = root / "abstracts.json"
        raw_input.write_text(json.dumps({"abstracts": abstracts}, indent=2), encoding="utf-8")

        embeddings_dir = root / "embeddings"
        embeddings_dir.mkdir(parents=True, exist_ok=True)
        matrix = np.asarray(
            [
                [1.0, 0.0],
                [0.98, 0.02],
                [0.0, 1.0],
                [0.02, 0.98],
                [-1.0, 0.0],
                [-0.98, -0.02],
            ],
            dtype=np.float32,
        )
        np.save(embeddings_dir / "vectors.npy", matrix)
        (embeddings_dir / "metadata.json").write_text(
            json.dumps(
                {
                    "embedding_fields": ["title", "introduction", "methods", "results", "conclusion"],
                    "ids": [1, 2, 3, 4, 5, 6],
                    "metadata": [{"id": abstract_id} for abstract_id in range(1, 7)],
                },
                indent=2,
            ),
            encoding="utf-8",
        )

        assignments_path = embeddings_dir / "cluster_assignments.json"
        assignments_path.write_text(
            json.dumps(
                {
                    "assignments": {
                        "1": 0,
                        "2": 0,
                        "3": 1,
                        "4": 1,
                        "5": 2,
                        "6": 2,
                    }
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        return raw_input, embeddings_dir, assignments_path

    def test_evaluate_label_systems_scores_builtins_and_file_assignments(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            raw_input, embeddings_dir, assignments_path = self._build_fixture(Path(tmpdir))
            evaluation = category_evaluation.evaluate_label_systems(
                embeddings_dir=embeddings_dir,
                raw_input=raw_input,
                label_system_specs=[
                    category_evaluation.LabelSystemSpec("submitter_parent", "builtin"),
                    category_evaluation.LabelSystemSpec("submitter_exact", "builtin"),
                    category_evaluation.LabelSystemSpec("learned", "file", assignments_path),
                ],
                neighbor_ks=[1, 2],
            )

        self.assertEqual(evaluation["abstract_count"], 6)
        self.assertEqual(len(evaluation["label_systems"]), 3)
        learned = next(item for item in evaluation["label_systems"] if item["label_system"] == "learned")
        self.assertEqual(learned["label_count"], 3)
        self.assertEqual(learned["label_count_band"], "outside_target_band")
        self.assertGreater(learned["embedding_metrics"]["silhouette_score"], 0.0)
        self.assertIn("1", learned["neighborhood_agreement"])
        self.assertIsNotNone(learned["graph_modularity"])
        self.assertIn("adjusted_mutual_info", learned["agreement_vs_submitter_parent"])
        self.assertIn("weighted_purity", learned["agreement_vs_submitter_exact"])
        self.assertIn("best_by_band", evaluation)

    def test_main_writes_json_csv_and_markdown(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            raw_input, embeddings_dir, assignments_path = self._build_fixture(root)
            output_dir = root / "category_evaluation"

            result = category_evaluation.main(
                [
                    "--embeddings-dir",
                    str(embeddings_dir),
                    "--raw-input",
                    str(raw_input),
                    "--label-system",
                    "submitter_parent",
                    "--label-system",
                    f"learned={assignments_path}",
                    "--neighbor-k",
                    "1",
                    "2",
                    "--output-dir",
                    str(output_dir),
                ]
            )

            self.assertEqual(result, 0)
            evaluation = json.loads((output_dir / "evaluation.json").read_text(encoding="utf-8"))
            summary_csv = (output_dir / "summary.csv").read_text(encoding="utf-8")
            summary_md = (output_dir / "summary.md").read_text(encoding="utf-8")

        self.assertEqual(len(evaluation["label_systems"]), 2)
        self.assertIn("label_system", summary_csv)
        self.assertIn("graph_modularity", summary_csv)
        self.assertIn("label_count_band", summary_csv)
        self.assertIn("`learned`", summary_md)
        self.assertIn("Graph modularity", summary_md)
        self.assertIn("Best Candidate By Label-Count Band", summary_md)

    def test_parse_label_system_specs_discovers_benchmark_and_semantic_variants(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            _raw_input, embeddings_dir, _assignments_path = self._build_fixture(root)
            (embeddings_dir / "clustering_benchmark").mkdir(exist_ok=True)
            (embeddings_dir / "clustering_benchmark_25_30").mkdir(exist_ok=True)
            (embeddings_dir / "clustering_benchmark_spectral").mkdir(exist_ok=True)
            (embeddings_dir / "semantic_analysis").mkdir(exist_ok=True)
            (embeddings_dir / "semantic_analysis_21-communities").mkdir(exist_ok=True)
            for relative_path in [
                "clustering_benchmark/cluster_assignments.json",
                "clustering_benchmark_25_30/cluster_assignments.json",
                "clustering_benchmark_spectral/cluster_assignments.json",
                "semantic_analysis/cluster_assignments.json",
                "semantic_analysis_21-communities/cluster_assignments.json",
            ]:
                (embeddings_dir / relative_path).write_text(
                    json.dumps({"assignments": {"1": 0, "2": 0, "3": 1, "4": 1, "5": 2, "6": 2}}, indent=2),
                    encoding="utf-8",
                )

            specs = category_evaluation.parse_label_system_specs(None, embeddings_dir)

        names = [spec.name for spec in specs]
        self.assertEqual(names[:2], ["submitter_parent", "submitter_exact"])
        self.assertIn("benchmark_best", names)
        self.assertIn("benchmark_25_30", names)
        self.assertIn("benchmark_spectral", names)
        self.assertIn("semantic_graph", names)
        self.assertIn("semantic_graph_21_communities", names)


if __name__ == "__main__":
    unittest.main()
