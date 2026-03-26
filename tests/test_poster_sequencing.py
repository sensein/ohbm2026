import json
import tempfile
import unittest
from pathlib import Path

import numpy as np

from ohbm2026 import poster_layout, poster_sequencing


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
    first_author_id: int,
) -> dict[str, object]:
    return {
        "id": abstract_id,
        "accepted_for": accepted_for,
        "title": title,
        "authors": [{"author_order": 0, "id": first_author_id}],
        "responses": [_response(parent, subcategory)],
    }


class PosterSequencingTest(unittest.TestCase):
    def _build_fixture(self, root: Path) -> tuple[poster_layout.LayoutInputs, dict]:
        abstracts = [
            _abstract(1, "Poster", "Alpha one", "Systems", "Memory", 101),
            _abstract(2, "Poster", "Alpha two", "Systems", "Memory", 102),
            _abstract(3, "Poster", "Beta one", "Methods", "Modeling", 103),
            _abstract(4, "Poster", "Beta two", "Methods", "Modeling", 104),
        ]
        raw_input = root / "abstracts.json"
        raw_input.write_text(json.dumps({"abstracts": abstracts}, indent=2), encoding="utf-8")
        authors_input = root / "authors.json"
        authors_input.write_text(
            json.dumps(
                {
                    "authors": [
                        {"id": 101, "last_name": "Alpha"},
                        {"id": 102, "last_name": "Bravo"},
                        {"id": 103, "last_name": "Charlie"},
                        {"id": 104, "last_name": "Delta"},
                    ]
                },
                indent=2,
            ),
            encoding="utf-8",
        )

        claims_assignments = root / "claims_assignments.json"
        claims_assignments.write_text(
            json.dumps({"assignments": {"1": 0, "2": 0, "3": 1, "4": 1}}),
            encoding="utf-8",
        )
        claims_summaries = root / "claims_summaries.json"
        claims_summaries.write_text(
            json.dumps(
                {
                    "clusters": [
                        {"cluster_id": 0, "label": "Alpha cluster"},
                        {"cluster_id": 1, "label": "Beta cluster"},
                    ]
                }
            ),
            encoding="utf-8",
        )

        embeddings_dir = root / "embeddings"
        embeddings_dir.mkdir(parents=True, exist_ok=True)
        np.save(
            embeddings_dir / "vectors.npy",
            np.asarray(
                [
                    [1.0, 0.0],
                    [0.98, 0.02],
                    [0.0, 1.0],
                    [0.02, 0.98],
                ],
                dtype=np.float32,
            ),
        )
        (embeddings_dir / "metadata.json").write_text(
            json.dumps(
                {
                    "ids": [1, 2, 3, 4],
                    "metadata": [{"id": 1}, {"id": 2}, {"id": 3}, {"id": 4}],
                },
                indent=2,
            ),
            encoding="utf-8",
        )

        inputs = poster_layout.load_layout_inputs(
            raw_input,
            embeddings_dir,
            claims_cluster_assignments=claims_assignments,
            claims_cluster_summaries=claims_summaries,
        )
        assignments = []
        current_number = 1
        for block_id, abstract_ids in ((1, [1, 3]), (2, [2, 4])):
            for block_position, abstract_id in enumerate(abstract_ids, start=1):
                record = {item.abstract_id: item for item in inputs.records}[abstract_id]
                session_id = poster_layout.standby_session_for_block_and_poster_number(block_id, current_number)
                first_standby, second_standby = poster_layout.standby_time_labels_for_session(session_id)
                assignments.append(
                    {
                        "abstract_id": abstract_id,
                        "accepted_for": record.accepted_for,
                        "title": record.title,
                        "primary_parent_category": record.primary_parent_category,
                        "primary_subcategory": record.primary_subcategory,
                        "primary_category": record.primary_category,
                        "layout_parent_label": record.layout_parent_label,
                        "layout_exact_label": record.layout_exact_label,
                        "layout_label_system": record.layout_label_system,
                        "first_author_id": record.first_author_id,
                        "claims_cluster_id": record.claims_cluster_id,
                        "claims_cluster_label": record.claims_cluster_label,
                        "standby_session": session_id,
                        "standby_session_label": poster_layout.SESSION_LABELS[session_id],
                        "first_standby_time_label": first_standby,
                        "second_standby_time_label": second_standby,
                        "block_id": block_id,
                        "block_label": poster_layout.BLOCK_LABELS[block_id],
                        "poster_number": current_number,
                        "block_position": block_position,
                        **poster_layout.layout_slot_for_block_position(block_position),
                    }
                )
                current_number += 1

        proposal = {"metadata": {"proposal_method": "fixture"}, "assignments": assignments, "session_summaries": {}}
        return inputs, proposal

    def test_graph_reordering_metrics_prefer_contiguous_order(self) -> None:
        records = [
            poster_layout.AcceptedAbstract(1, "Poster", "Alpha one", "Systems", "Memory", "Systems :: Memory", "Systems", "Systems :: Memory", "submitter_primary_secondary", 101, 0, None, None),
            poster_layout.AcceptedAbstract(2, "Poster", "Alpha two", "Systems", "Memory", "Systems :: Memory", "Systems", "Systems :: Memory", "submitter_primary_secondary", 102, 1, None, None),
            poster_layout.AcceptedAbstract(3, "Poster", "Beta one", "Methods", "Modeling", "Methods :: Modeling", "Methods", "Methods :: Modeling", "submitter_primary_secondary", 103, 2, None, None),
            poster_layout.AcceptedAbstract(4, "Poster", "Beta two", "Methods", "Modeling", "Methods :: Modeling", "Methods", "Methods :: Modeling", "submitter_primary_secondary", 104, 3, None, None),
        ]
        normalized_matrix = poster_layout._normalize_rows(
            np.asarray(
                [
                    [1.0, 0.0],
                    [0.98, 0.02],
                    [0.0, 1.0],
                    [0.02, 0.98],
                ],
                dtype=np.float32,
            )
        )
        contiguous = poster_sequencing.graph_reordering_metrics(records, normalized_matrix, band_width=1)
        interleaved = poster_sequencing.graph_reordering_metrics(
            [records[0], records[2], records[1], records[3]],
            normalized_matrix,
            band_width=1,
        )

        self.assertGreater(contiguous["adjacent_edge_mass_rate"], interleaved["adjacent_edge_mass_rate"])
        self.assertLess(contiguous["mean_weighted_index_distance"], interleaved["mean_weighted_index_distance"])

    def test_order_methods_group_similar_records(self) -> None:
        records = [
            poster_layout.AcceptedAbstract(1, "Poster", "Alpha one", "Systems", "Memory", "Systems :: Memory", "Systems", "Systems :: Memory", "submitter_primary_secondary", 101, 0, None, None),
            poster_layout.AcceptedAbstract(2, "Poster", "Alpha two", "Systems", "Memory", "Systems :: Memory", "Systems", "Systems :: Memory", "submitter_primary_secondary", 102, 1, None, None),
            poster_layout.AcceptedAbstract(3, "Poster", "Beta one", "Methods", "Modeling", "Methods :: Modeling", "Methods", "Methods :: Modeling", "submitter_primary_secondary", 103, 2, None, None),
            poster_layout.AcceptedAbstract(4, "Poster", "Beta two", "Methods", "Modeling", "Methods :: Modeling", "Methods", "Methods :: Modeling", "submitter_primary_secondary", 104, 3, None, None),
        ]
        normalized_matrix = poster_layout._normalize_rows(
            np.asarray(
                [
                    [1.0, 0.0],
                    [0.98, 0.02],
                    [0.0, 1.0],
                    [0.02, 0.98],
                ],
                dtype=np.float32,
            )
        )
        label_by_id = {record.abstract_id: record.layout_exact_label for record in records}
        methods = [
            poster_sequencing.order_records_by_spectral_graph(records, normalized_matrix),
            poster_sequencing.order_records_by_diffusion_map_path(records, normalized_matrix),
            poster_sequencing.order_records_by_optimal_leaf_ordering(records, normalized_matrix),
        ]

        for ordered_ids in methods:
            collapsed = []
            for abstract_id in ordered_ids:
                label = label_by_id[abstract_id]
                if not collapsed or collapsed[-1] != label:
                    collapsed.append(label)
            self.assertLessEqual(len(collapsed), 2)

    def test_weighted_knn_graph_reports_connectivity_diagnostics(self) -> None:
        records = [
            poster_layout.AcceptedAbstract(1, "Poster", "Alpha one", "Systems", "Memory", "Systems :: Memory", "Systems", "Systems :: Memory", "submitter_primary_secondary", 101, 0, None, None),
            poster_layout.AcceptedAbstract(2, "Poster", "Alpha two", "Systems", "Memory", "Systems :: Memory", "Systems", "Systems :: Memory", "submitter_primary_secondary", 102, 1, None, None),
            poster_layout.AcceptedAbstract(3, "Poster", "Beta one", "Methods", "Modeling", "Methods :: Modeling", "Methods", "Methods :: Modeling", "submitter_primary_secondary", 103, 2, None, None),
            poster_layout.AcceptedAbstract(4, "Poster", "Beta two", "Methods", "Modeling", "Methods :: Modeling", "Methods", "Methods :: Modeling", "submitter_primary_secondary", 104, 3, None, None),
        ]
        normalized_matrix = poster_layout._normalize_rows(
            np.asarray(
                [
                    [1.0, 0.0],
                    [0.99, 0.01],
                    [0.0, 1.0],
                    [0.01, 0.99],
                ],
                dtype=np.float32,
            )
        )
        graph = poster_sequencing.build_weighted_knn_graph(records, normalized_matrix, neighbor_count=2)

        self.assertGreaterEqual(graph["diagnostics"]["components_before_bridge"], 1)
        self.assertEqual(graph["diagnostics"]["components_after_bridge"], 1)
        self.assertIn("graph_was_disconnected", graph["diagnostics"])

    def test_derive_contiguous_layout_clusters_respects_sequence_blocks(self) -> None:
        records = [
            poster_layout.AcceptedAbstract(1, "Poster", "Alpha memory one", "Systems", "Memory", "Systems :: Memory", "Systems", "alpha seed", "submitter_primary_secondary", 101, 0, None, None),
            poster_layout.AcceptedAbstract(2, "Poster", "Alpha memory two", "Systems", "Memory", "Systems :: Memory", "Systems", "alpha seed", "submitter_primary_secondary", 102, 1, None, None),
            poster_layout.AcceptedAbstract(3, "Poster", "Beta modeling one", "Methods", "Modeling", "Methods :: Modeling", "Methods", "beta seed", "submitter_primary_secondary", 103, 2, None, None),
            poster_layout.AcceptedAbstract(4, "Poster", "Beta modeling two", "Methods", "Modeling", "Methods :: Modeling", "Methods", "beta seed", "submitter_primary_secondary", 104, 3, None, None),
        ]
        normalized_matrix = poster_layout._normalize_rows(
            np.asarray(
                [
                    [1.0, 0.0],
                    [0.99, 0.01],
                    [0.0, 1.0],
                    [0.01, 0.99],
                ],
                dtype=np.float32,
            )
        )

        result = poster_sequencing.derive_contiguous_layout_clusters(records, normalized_matrix, target_cluster_count=2)

        self.assertEqual(result["assignments"][1], result["assignments"][2])
        self.assertEqual(result["assignments"][3], result["assignments"][4])
        self.assertNotEqual(result["assignments"][1], result["assignments"][3])
        self.assertEqual(len(result["clusters"]), 2)

    def test_derive_contiguous_layout_clusters_uses_content_phrases_and_keeps_labels_unique(self) -> None:
        records = [
            poster_layout.AcceptedAbstract(1, "Poster", "Study one", "Systems", "Memory", "Systems :: Memory", "Systems", "shared label", "submitter_primary_secondary", 101, 0, None, None),
            poster_layout.AcceptedAbstract(2, "Poster", "Study two", "Systems", "Memory", "Systems :: Memory", "Systems", "shared label", "submitter_primary_secondary", 102, 1, None, None),
            poster_layout.AcceptedAbstract(3, "Poster", "Study three", "Methods", "Modeling", "Methods :: Modeling", "Methods", "shared label", "submitter_primary_secondary", 103, 2, None, None),
            poster_layout.AcceptedAbstract(4, "Poster", "Study four", "Methods", "Modeling", "Methods :: Modeling", "Methods", "shared label", "submitter_primary_secondary", 104, 3, None, None),
        ]
        normalized_matrix = poster_layout._normalize_rows(
            np.asarray(
                [
                    [1.0, 0.0],
                    [0.99, 0.01],
                    [0.0, 1.0],
                    [0.01, 0.99],
                ],
                dtype=np.float32,
            )
        )

        result = poster_sequencing.derive_contiguous_layout_clusters(
            records,
            normalized_matrix,
            target_cluster_count=2,
            content_by_id={
                1: "migraine occipital cortex stimulation response model",
                2: "migraine occipital cortex stimulation target treatment",
                3: "white matter diffusion tractography microstructure analysis",
                4: "white matter diffusion imaging tractography analysis",
            },
        )

        labels = [str(cluster["label"]) for cluster in result["clusters"]]
        self.assertEqual(len(labels), 2)
        self.assertEqual(len(set(labels)), 2)
        self.assertTrue(any("migraine" in label or "occipital" in label for label in labels))
        self.assertTrue(any("diffusion" in label or "tractography" in label for label in labels))

    def test_diffusion_map_can_return_multi_coordinate_diagnostics(self) -> None:
        records = [
            poster_layout.AcceptedAbstract(1, "Poster", "Alpha one", "Systems", "Memory", "Systems :: Memory", "Systems", "Systems :: Memory", "submitter_primary_secondary", 101, 0, None, None),
            poster_layout.AcceptedAbstract(2, "Poster", "Alpha two", "Systems", "Memory", "Systems :: Memory", "Systems", "Systems :: Memory", "submitter_primary_secondary", 102, 1, None, None),
            poster_layout.AcceptedAbstract(3, "Poster", "Beta one", "Methods", "Modeling", "Methods :: Modeling", "Methods", "Methods :: Modeling", "submitter_primary_secondary", 103, 2, None, None),
            poster_layout.AcceptedAbstract(4, "Poster", "Beta two", "Methods", "Modeling", "Methods :: Modeling", "Methods", "Methods :: Modeling", "submitter_primary_secondary", 104, 3, None, None),
        ]
        normalized_matrix = poster_layout._normalize_rows(
            np.asarray(
                [
                    [1.0, 0.0],
                    [0.98, 0.02],
                    [0.0, 1.0],
                    [0.02, 0.98],
                ],
                dtype=np.float32,
            )
        )
        result = poster_sequencing.order_records_by_diffusion_map_path(
            records,
            normalized_matrix,
            neighbor_count=2,
            coordinate_dims=2,
            coordinate_mode="pca",
            return_diagnostics=True,
        )

        self.assertEqual(len(result["ordered_ids"]), 4)
        self.assertEqual(result["diagnostics"]["coordinate_dims"], 2)
        self.assertEqual(result["diagnostics"]["coordinate_mode"], "pca")
        self.assertTrue(result["diagnostics"]["chosen_eigenvalues"])

    def test_compute_community_metrics_reports_requested_fields(self) -> None:
        records = [
            poster_layout.AcceptedAbstract(1, "Poster", "Alpha one", "Systems", "Memory", "Systems :: Memory", "Systems", "Systems :: Memory", "submitter_primary_secondary", 101, 0, None, None),
            poster_layout.AcceptedAbstract(2, "Poster", "Alpha two", "Systems", "Memory", "Systems :: Memory", "Systems", "Systems :: Memory", "submitter_primary_secondary", 102, 1, None, None),
            poster_layout.AcceptedAbstract(3, "Poster", "Beta one", "Methods", "Modeling", "Methods :: Modeling", "Methods", "Methods :: Modeling", "submitter_primary_secondary", 103, 2, None, None),
            poster_layout.AcceptedAbstract(4, "Poster", "Beta two", "Methods", "Modeling", "Methods :: Modeling", "Methods", "Methods :: Modeling", "submitter_primary_secondary", 104, 3, None, None),
        ]
        normalized_matrix = poster_layout._normalize_rows(
            np.asarray(
                [
                    [1.0, 0.0],
                    [0.99, 0.01],
                    [0.0, 1.0],
                    [0.01, 0.99],
                ],
                dtype=np.float32,
            )
        )

        metrics = poster_sequencing.compute_community_metrics(records, normalized_matrix, neighbor_count=2)

        self.assertGreaterEqual(metrics["community_count"], 1)
        self.assertGreaterEqual(metrics["coverage"], 0.0)
        self.assertLessEqual(metrics["coverage"], 1.0)
        self.assertGreaterEqual(metrics["density"], 0.0)
        self.assertGreaterEqual(metrics["conductance"], 0.0)
        self.assertGreaterEqual(metrics["clustering_coefficient"], 0.0)
        self.assertIn("assignments", metrics["community_detection"])

    def test_compute_community_metrics_changes_with_order(self) -> None:
        records = [
            poster_layout.AcceptedAbstract(1, "Poster", "Alpha one", "Systems", "Memory", "Systems :: Memory", "Systems", "Systems :: Memory", "submitter_primary_secondary", 101, 0, None, None),
            poster_layout.AcceptedAbstract(2, "Poster", "Alpha two", "Systems", "Memory", "Systems :: Memory", "Systems", "Systems :: Memory", "submitter_primary_secondary", 102, 1, None, None),
            poster_layout.AcceptedAbstract(3, "Poster", "Beta one", "Methods", "Modeling", "Methods :: Modeling", "Methods", "Methods :: Modeling", "submitter_primary_secondary", 103, 2, None, None),
            poster_layout.AcceptedAbstract(4, "Poster", "Beta two", "Methods", "Modeling", "Methods :: Modeling", "Methods", "Methods :: Modeling", "submitter_primary_secondary", 104, 3, None, None),
        ]
        normalized_matrix = poster_layout._normalize_rows(
            np.asarray(
                [
                    [1.0, 0.0],
                    [0.99, 0.01],
                    [0.0, 1.0],
                    [0.01, 0.99],
                ],
                dtype=np.float32,
            )
        )

        contiguous = poster_sequencing.compute_community_metrics(records, normalized_matrix, neighbor_count=2)
        interleaved = poster_sequencing.compute_community_metrics(
            [records[0], records[2], records[1], records[3]],
            normalized_matrix,
            neighbor_count=2,
        )

        self.assertNotEqual(contiguous["coverage"], interleaved["coverage"])
        self.assertGreater(contiguous["density"], interleaved["density"])
        self.assertLess(contiguous["conductance"], interleaved["conductance"])

    def test_mapalign_style_diffusion_returns_diagnostics(self) -> None:
        records = [
            poster_layout.AcceptedAbstract(1, "Poster", "Alpha one", "Systems", "Memory", "Systems :: Memory", "Systems", "Systems :: Memory", "submitter_primary_secondary", 101, 0, None, None),
            poster_layout.AcceptedAbstract(2, "Poster", "Alpha two", "Systems", "Memory", "Systems :: Memory", "Systems", "Systems :: Memory", "submitter_primary_secondary", 102, 1, None, None),
            poster_layout.AcceptedAbstract(3, "Poster", "Beta one", "Methods", "Modeling", "Methods :: Modeling", "Methods", "Methods :: Modeling", "submitter_primary_secondary", 103, 2, None, None),
            poster_layout.AcceptedAbstract(4, "Poster", "Beta two", "Methods", "Modeling", "Methods :: Modeling", "Methods", "Methods :: Modeling", "submitter_primary_secondary", 104, 3, None, None),
        ]
        normalized_matrix = poster_layout._normalize_rows(
            np.asarray(
                [
                    [1.0, 0.0],
                    [0.98, 0.02],
                    [0.0, 1.0],
                    [0.02, 0.98],
                ],
                dtype=np.float32,
            )
        )
        result = poster_sequencing.order_records_by_mapalign_style_diffusion(
            records,
            normalized_matrix,
            affinity_mode="knn",
            neighbor_count=2,
            alpha=0.5,
            diffusion_time=0.0,
            coordinate_dims=2,
            coordinate_mode="pca",
            return_diagnostics=True,
        )

        self.assertEqual(len(result["ordered_ids"]), 4)
        self.assertEqual(result["diagnostics"]["affinity_mode"], "knn")
        self.assertEqual(result["diagnostics"]["coordinate_mode"], "pca")
        self.assertEqual(result["diagnostics"]["alpha"], 0.5)
        self.assertTrue(result["diagnostics"]["chosen_eigenvalues"])

    def test_benchmark_graph_reordering_methods_writes_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            inputs, proposal = self._build_fixture(root)
            output_root = root / "benchmarks"

            result = poster_sequencing.benchmark_graph_reordering_methods(
                inputs,
                proposal,
                output_root=output_root,
                authors_input=root / "authors.json",
                methods=("baseline_current", "spectral_knn", "diffusion_map_path"),
                spectral_neighbors=2,
                graph_band_width=2,
            )

            summary = json.loads((output_root / "summary.json").read_text(encoding="utf-8"))

            self.assertEqual(len(summary["methods"]), 3)
            self.assertIn("baseline_current", {row["method_name"] for row in summary["methods"]})
            self.assertIn("diffusion_map_path", {row["method_name"] for row in summary["methods"]})
            self.assertTrue((output_root / "spectral_knn" / "proposal.csv").exists())
            self.assertTrue((output_root / "diffusion_map_path" / "graph_metrics.json").exists())
            self.assertIn("summary", result)

    def test_sweep_diffusion_variants_writes_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            inputs, proposal = self._build_fixture(root)
            output_root = root / "diffusion_sweep"

            result = poster_sequencing.sweep_diffusion_variants(
                inputs,
                proposal,
                output_root=output_root,
                authors_input=root / "authors.json",
                neighbor_counts=(2, 3),
                coordinate_variants=((1, "single"), (2, "pca")),
                graph_band_width=2,
            )
            summary = json.loads((output_root / "summary.json").read_text(encoding="utf-8"))

            self.assertEqual(len(summary["variants"]), 4)
            self.assertTrue((output_root / "diffusion_k2_single1" / "diffusion_diagnostics.json").exists())
            self.assertTrue((output_root / "diffusion_k3_pca2" / "proposal.csv").exists())
            self.assertIn("summary", result)

    def test_sweep_global_path_diffusion_variants_writes_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            inputs, proposal = self._build_fixture(root)
            output_root = root / "global_path_sweep"

            result = poster_sequencing.sweep_global_path_diffusion_variants(
                inputs,
                proposal,
                output_root=output_root,
                authors_input=root / "authors.json",
                neighbor_counts=(2,),
                coordinate_variants=((1, "single"),),
                graph_band_width=2,
                include_baselines=True,
            )
            summary = json.loads((output_root / "summary.json").read_text(encoding="utf-8"))

            self.assertTrue((output_root / "global_baseline_current" / "global_sequence_metrics.json").exists())
            self.assertTrue((output_root / "global_optimal_leaf_ordering" / "proposal.csv").exists())
            self.assertTrue((output_root / "global_diffusion_k2_single1" / "diffusion_diagnostics.json").exists())
            self.assertGreaterEqual(len(summary["variants"]), 3)
            self.assertIn("summary", result)

    def test_sweep_global_path_mapalign_variants_writes_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            inputs, proposal = self._build_fixture(root)
            output_root = root / "mapalign_sweep"

            result = poster_sequencing.sweep_global_path_mapalign_variants(
                inputs,
                proposal,
                output_root=output_root,
                authors_input=root / "authors.json",
                affinity_modes=("knn",),
                neighbor_counts=(2,),
                alphas=(0.5,),
                diffusion_times=(0.0,),
                coordinate_variants=((1, "single"),),
                graph_band_width=2,
                include_baselines=True,
            )
            summary = json.loads((output_root / "summary.json").read_text(encoding="utf-8"))

            self.assertTrue((output_root / "global_optimal_leaf_ordering" / "diffusion_diagnostics.json").exists())
            self.assertTrue((output_root / "mapalign_knn_k2_a05_t00_single1" / "proposal.csv").exists())
            self.assertTrue((output_root / "mapalign_knn_k2_a05_t00_single1" / "diffusion_diagnostics.json").exists())
            self.assertGreaterEqual(len(summary["variants"]), 2)
            self.assertIn("summary", result)

    def test_run_advanced_global_path_experiment_writes_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            inputs, proposal = self._build_fixture(root)
            output_root = root / "advanced_global_path"

            result = poster_sequencing.run_advanced_global_path_experiment(
                inputs,
                proposal,
                output_root=output_root,
                authors_input=root / "authors.json",
                graph_band_width=2,
                include_parameter_sweep=True,
            )
            summary = json.loads((output_root / "summary.json").read_text(encoding="utf-8"))

            self.assertTrue((output_root / "global_optimal_leaf_ordering" / "diagnostics.json").exists())
            self.assertTrue((output_root / "global_olo_two_opt_knn20" / "proposal.csv").exists())
            self.assertTrue((output_root / "global_olo_two_opt_knn10_p2" / "proposal.csv").exists())
            self.assertTrue((output_root / "global_clustered_kmeans_olo" / "global_sequence_metrics.json").exists())
            self.assertTrue((output_root / "global_clustered_kmeans_olo" / "community_metrics.json").exists())
            self.assertTrue((output_root / "global_clustered_kmeans_olo" / "community_detection.json").exists())
            self.assertTrue((output_root / "global_clustered_kmeans_olo" / "ordered_cosine_similarity_matrix.png").exists())
            self.assertGreaterEqual(len(summary["variants"]), 4)
            self.assertIn("voyage_neighbor5_below_0_4", summary["variants"][0])
            self.assertIn("community_coverage", summary["variants"][0])
            self.assertIn("community_density", summary["variants"][0])
            self.assertIn("community_conductance", summary["variants"][0])
            self.assertIn("community_clustering_coefficient", summary["variants"][0])
            self.assertIn("summary", result)


if __name__ == "__main__":
    unittest.main()
