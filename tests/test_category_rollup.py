import json
import tempfile
import unittest
from pathlib import Path

from ohbm2026.analyze import category_rollup


def _band_row(
    label_system: str,
    label_count: int,
    comparison_score: float,
    silhouette_score: float,
    graph_modularity: float,
    neighbor_agreement_k10: float,
    parent_nmi: float,
    exact_nmi: float,
    assignment_path: str | None,
) -> dict[str, object]:
    return {
        "label_system": label_system,
        "source_type": "file" if not label_system.startswith("submitter_") else "builtin",
        "assignment_path": assignment_path,
        "label_count": label_count,
        "comparison_score": comparison_score,
        "graph_modularity": graph_modularity,
        "embedding_metrics": {
            "silhouette_score": silhouette_score,
            "intercluster_distance_ratio": 1.0 + silhouette_score,
            "largest_cluster_fraction": 0.1,
        },
        "neighborhood_agreement": {"5": neighbor_agreement_k10 - 0.05, "10": neighbor_agreement_k10, "20": neighbor_agreement_k10 - 0.1},
        "agreement_vs_submitter_parent": {"normalized_mutual_info": parent_nmi, "adjusted_mutual_info": parent_nmi / 2.0},
        "agreement_vs_submitter_exact": {"normalized_mutual_info": exact_nmi, "adjusted_mutual_info": exact_nmi / 2.0},
    }


def _evaluation_payload(
    embedding_name: str,
    parent_silhouette: float,
    exact_silhouette: float,
    band_rows: dict[str, dict[str, object]],
) -> dict[str, object]:
    submitter_parent = _band_row("submitter_parent", 16, 0.1, parent_silhouette, 0.08, 0.45, 1.0, 0.7, None)
    submitter_exact = _band_row("submitter_exact", 121, 0.05, exact_silhouette, 0.02, 0.25, 0.7, 1.0, None)
    return {
        "embeddings_dir": f"data/outputs/experiments/embeddings/{embedding_name}",
        "abstract_count": 3333,
        "neighbor_ks": [5, 10, 20],
        "label_count_bands": [
            {"name": "coarse", "min_count": 10, "max_count": 15},
            {"name": "mid", "min_count": 20, "max_count": 30},
            {"name": "fine", "min_count": 31, "max_count": 40},
        ],
        "label_systems": [submitter_parent, submitter_exact, *band_rows.values()],
        "best_by_band": band_rows,
    }


class CategoryRollupTest(unittest.TestCase):
    def test_build_rollup_ranks_band_winners_and_baseline_gains(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            first_eval = _evaluation_payload(
                "voyage_stage2_published",
                parent_silhouette=-0.01,
                exact_silhouette=-0.08,
                band_rows={
                    "coarse": _band_row("semantic_15", 15, 0.48, 0.01, 0.21, 0.80, 0.21, 0.28, "coarse.json"),
                    "mid": _band_row("benchmark_best", 25, 0.54, 0.09, 0.27, 0.72, 0.25, 0.36, "mid.json"),
                    "fine": _band_row("spectral", 31, 0.57, 0.10, 0.31, 0.75, 0.27, 0.38, "fine.json"),
                },
            )
            second_eval = _evaluation_payload(
                "minilm_stage1",
                parent_silhouette=-0.02,
                exact_silhouette=-0.09,
                band_rows={
                    "coarse": _band_row("semantic_15", 15, 0.40, 0.00, 0.17, 0.70, 0.18, 0.25, "coarse.json"),
                    "mid": _band_row("benchmark_best", 30, 0.52, 0.05, 0.23, 0.62, 0.23, 0.31, "mid.json"),
                    "fine": _band_row("spectral", 34, 0.53, 0.06, 0.26, 0.66, 0.24, 0.33, "fine.json"),
                },
            )

            first_path = root / "data/outputs/experiments/embeddings/voyage_stage2_published/category_evaluation/evaluation.json"
            second_path = root / "data/outputs/experiments/embeddings/minilm_stage1/category_evaluation/evaluation.json"
            first_path.parent.mkdir(parents=True, exist_ok=True)
            second_path.parent.mkdir(parents=True, exist_ok=True)
            first_path.write_text(json.dumps(first_eval), encoding="utf-8")
            second_path.write_text(json.dumps(second_eval), encoding="utf-8")

            rollup = category_rollup.build_rollup([first_path, second_path])

        self.assertEqual(rollup["evaluation_count"], 2)
        self.assertIn("coarse", rollup["band_winners"])
        self.assertEqual(rollup["band_winners"]["fine"]["winner"]["embedding_name"], "voyage_stage2_published")
        self.assertEqual(rollup["band_winners"]["mid"]["winner"]["label_system"], "benchmark_best")
        self.assertGreater(rollup["band_winners"]["fine"]["winner"]["silhouette_gain_vs_parent"], 0.0)
        self.assertGreater(rollup["band_winners"]["fine"]["winner"]["graph_modularity_gain_vs_parent"], 0.0)
        self.assertGreater(rollup["band_winners"]["fine"]["winner"]["neighbor_gain_vs_parent_k10"], 0.0)
        self.assertEqual(rollup["best_overall"]["label_system"], "spectral")
        self.assertEqual(rollup["band_winners"]["fine"]["winner"]["global_band_rank"], 1)

    def test_main_writes_rollup_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            evaluation_dir = root / "data/outputs/experiments/embeddings/voyage_stage2_published/category_evaluation"
            evaluation_dir.mkdir(parents=True, exist_ok=True)
            evaluation_payload = _evaluation_payload(
                "voyage_stage2_published",
                parent_silhouette=-0.01,
                exact_silhouette=-0.08,
                band_rows={
                    "coarse": _band_row("semantic_15", 15, 0.48, 0.01, 0.21, 0.80, 0.21, 0.28, "coarse.json"),
                    "mid": _band_row("benchmark_best", 25, 0.54, 0.09, 0.27, 0.72, 0.25, 0.36, "mid.json"),
                    "fine": _band_row("spectral", 31, 0.57, 0.10, 0.31, 0.75, 0.27, 0.38, "fine.json"),
                },
            )
            evaluation_dir.joinpath("evaluation.json").write_text(json.dumps(evaluation_payload), encoding="utf-8")
            output_json = root / "rollup.json"
            output_csv = root / "rollup.csv"
            output_md = root / "rollup.md"

            result = category_rollup.main(
                [
                    "--embeddings-root",
                    str(root / "data/outputs/experiments/embeddings"),
                    "--output-json",
                    str(output_json),
                    "--output-csv",
                    str(output_csv),
                    "--output-md",
                    str(output_md),
                ]
            )

            self.assertEqual(result, 0)
            rollup = json.loads(output_json.read_text(encoding="utf-8"))
            markdown = output_md.read_text(encoding="utf-8")
            csv_text = output_csv.read_text(encoding="utf-8")

        self.assertEqual(rollup["evaluation_count"], 1)
        self.assertIn("Band Winners Across Embeddings", markdown)
        self.assertIn("Graph modularity", markdown)
        self.assertIn("voyage_stage2_published", markdown)
        self.assertIn("global_band_rank", csv_text)


if __name__ == "__main__":
    unittest.main()
