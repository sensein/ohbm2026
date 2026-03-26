import importlib.util
import unittest
from pathlib import Path


def _load_compare_module():
    module_path = Path(__file__).resolve().parents[1] / "scripts" / "compare_poster_layout_proposals.py"
    spec = importlib.util.spec_from_file_location("compare_poster_layout_proposals", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Unable to load compare_poster_layout_proposals module")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ComparePosterLayoutProposalsTest(unittest.TestCase):
    def test_best_recommendation_prefers_semantic_coherence_after_hard_constraints(self) -> None:
        module = _load_compare_module()
        rows = [
            {
                "proposal_name": "semantic_layout_voyage25",
                "author_conflict_total": 0,
                "exact_categories_single_block_multi_poster": 0,
                "claims_clusters_single_block_multi_poster": 0,
                "exact_categories_single_block": 0,
                "block_adjacent_mean_semantic_distance": 0.305,
                "claims_adjacent_same_cluster_rate": 0.421,
                "block_adjacent_exact_category_match_rate": 0.986,
            },
            {
                "proposal_name": "semantic_layout_voyage31",
                "author_conflict_total": 0,
                "exact_categories_single_block_multi_poster": 0,
                "claims_clusters_single_block_multi_poster": 0,
                "exact_categories_single_block": 0,
                "block_adjacent_mean_semantic_distance": 0.302,
                "claims_adjacent_same_cluster_rate": 0.431,
                "block_adjacent_exact_category_match_rate": 0.982,
            },
        ]

        best = module._best_recommendation(rows)

        self.assertIsNotNone(best)
        self.assertEqual(best["proposal_name"], "semantic_layout_voyage31")

    def test_proposal_emphasis_calls_out_global_olo_two_opt_variants(self) -> None:
        module = _load_compare_module()
        emphasis = module._proposal_emphasis(
            {
                "proposal_name": "semantic_path_voyage31_olo_two_opt_knn20_p8",
                "proposal_kind": "semantic_path",
                "proposal_method": "voyage_stage2_graph_global_olo_two_opt_knn20_p8",
                "layout_label_system": "voyage_stage2_spectral_31",
                "sequencing_method": "global_olo_two_opt_knn20_p8",
            }
        )

        self.assertIn("optimal leaf ordering", emphasis)
        self.assertIn("sparse 2-opt", emphasis)
        self.assertIn("derive contiguous layout categories", emphasis)


if __name__ == "__main__":
    unittest.main()
