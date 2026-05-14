import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from ohbm2026.neuroscape import (
    DEFAULT_EMBEDDING_FIELDS,
    align_semantic_records,
    build_embedding_output_name,
    build_claim_embedding_text,
    build_distinct_color_map,
    build_embedding_visualization_title,
    build_apply_pretrained_stage2_parser,
    build_cluster_benchmark_parser,
    build_projection_compare_parser,
    build_projection_graph,
    build_projection_optimize_parser,
    build_visualization_records,
    build_knn_graph,
    build_semantic_analysis_parser,
    build_umap_parser,
    compute_tsne_projection,
    compute_clustering_metrics,
    cluster_benchmark_main,
    cluster_with_method,
    default_umap_output_paths,
    default_projection_output_paths,
    build_embedding_text,
    build_embedding_texts,
    configure_huggingface_auth,
    compute_umap_projection,
    extract_raw_keywords,
    detect_semantic_communities,
    detect_semantic_communities_at_resolution,
    detect_stage2_communities,
    embedding_variant_name,
    load_annotation_lookup,
    load_pretrained_stage2_model,
    load_stage1_bundle,
    model_name_slug,
    normalize_embedding_fields,
    normalize_hidden_dimensions,
    parse_string_list_value,
    projection_compare_main,
    projection_optimize_main,
    rank_clustering_benchmark_results,
    run_clustering_benchmark,
    score_projection,
    semantic_analysis_main,
    split_stage2_matrix,
    summarize_membership_groups,
    summarize_semantic_clusters,
    summarize_stage2_clusters,
    umap_main,
    apply_pretrained_stage2_main,
    write_projection_comparison_outputs,
    write_pretrained_stage2_bundle,
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

    def test_build_claim_embedding_text_formats_claims(self) -> None:
        abstract = {
            "claim_extraction": {
                "claims": [
                    {
                        "claim_id": "C1",
                        "claim_type": "EXPLICIT",
                        "claim": "Memory encoding recruits the hippocampus.",
                    },
                    {
                        "claim_id": "C2",
                        "claim_type": "IMPLICIT",
                        "claim": "This pattern may generalize to retrieval.",
                    },
                ]
            }
        }

        text = build_claim_embedding_text(abstract)

        self.assertEqual(
            text,
            "- Memory encoding recruits the hippocampus.\n"
            "- This pattern may generalize to retrieval.",
        )

    def test_build_embedding_text_supports_claims_field(self) -> None:
        abstract = {
            "id": 1,
            "claim_extraction": {
                "claims": [
                    {
                        "claim_id": "C1",
                        "claim_type": "EXPLICIT",
                        "claim": "Stimulus timing improved decoding accuracy.",
                    }
                ]
            },
        }

        text = build_embedding_text(abstract, ["claims"])

        self.assertEqual(text, "Claims:\n- Stimulus timing improved decoding accuracy.")

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

    def test_model_name_slug_normalizes_hf_model_name(self) -> None:
        self.assertEqual(
            model_name_slug("neuml/pubmedbert-base-embeddings"),
            "neuml-pubmedbert-base-embeddings",
        )

    def test_build_embedding_output_name_uses_model_and_fields(self) -> None:
        self.assertEqual(
            build_embedding_output_name(
                "neuml/pubmedbert-base-embeddings",
                ["title", "results", "conclusion"],
                prefix="hf",
            ),
            "hf_neuml-pubmedbert-base-embeddings_title-results-conclusion",
        )
        self.assertEqual(
            build_embedding_output_name(
                "neuml/pubmedbert-base-embeddings",
                ["title"],
                output_name="custom",
                prefix="hf",
            ),
            "custom",
        )

    def test_build_embedding_visualization_title_uses_source_name_and_fields(self) -> None:
        bundle = {
            "source_metadata": {
                "embedding_name": "neuroscape_stage2_local",
                "source_embedding_name": "minilm_stage1",
                "embedding_fields": ["title", "methods", "results"],
            }
        }

        title = build_embedding_visualization_title(bundle, "OHBM 2026 Projection Comparison")

        self.assertEqual(
            title,
            "OHBM 2026 Projection Comparison: neuroscape_stage2_local (source: minilm_stage1) | fields: title, methods, results",
        )

    def test_normalize_hidden_dimensions_requires_three_values(self) -> None:
        self.assertEqual(normalize_hidden_dimensions([12, 8, 4]), (12, 8, 4))
        with self.assertRaises(Exception):
            normalize_hidden_dimensions([12, 8])

    def test_parse_string_list_value_handles_json_list(self) -> None:
        self.assertEqual(parse_string_list_value('["A", "B"]'), ["A", "B"])
        self.assertEqual(parse_string_list_value("Single"), ["Single"])

    def test_compute_umap_projection_falls_back_for_tiny_bundle(self) -> None:
        import numpy as np

        matrix = np.asarray([[1.0, 2.0, 3.0], [4.0, 5.0, 6.0], [0.5, 0.25, 0.75]], dtype=np.float32)

        coordinates = compute_umap_projection(matrix)

        self.assertEqual(tuple(coordinates.shape), (3, 2))
        self.assertTrue((coordinates[:, 0] == matrix[:, 0]).all())

    def test_compute_tsne_projection_falls_back_for_tiny_bundle(self) -> None:
        import numpy as np

        matrix = np.asarray([[1.0, 2.0], [4.0, 5.0], [0.5, 0.25]], dtype=np.float32)

        coordinates = compute_tsne_projection(matrix)

        self.assertEqual(tuple(coordinates.shape), (3, 2))
        self.assertTrue((coordinates[:, 0] == matrix[:, 0]).all())

    def test_configure_huggingface_auth_reads_token_from_env_file(self) -> None:
        with TemporaryDirectory() as temp_dir:
            env_path = Path(temp_dir) / ".env"
            env_path.write_text("HF_TOKEN=test-token\n", encoding="utf-8")

            with mock.patch.dict("os.environ", {}, clear=True):
                token = configure_huggingface_auth(env_path)
                self.assertEqual(token, "test-token")
                self.assertEqual(__import__("os").environ["HF_TOKEN"], "test-token")
                self.assertEqual(__import__("os").environ["HUGGINGFACE_HUB_TOKEN"], "test-token")

    def test_summarize_membership_groups_includes_rationale_and_primary_topics(self) -> None:
        import numpy as np

        ids = [1, 2, 3]
        matrix = np.asarray(
            [
                [1.0, 0.0],
                [0.8, 0.2],
                [0.0, 1.0],
            ],
            dtype=np.float32,
        )
        records = [
            {
                "id": 1,
                "title": "Memory coding in hippocampus",
                "accepted_for": "Poster",
                "primary_topic": "Memory",
                "cluster_document": "hippocampus memory coding fmri",
            },
            {
                "id": 2,
                "title": "Memory retrieval patterns",
                "accepted_for": "Poster",
                "primary_topic": "Memory",
                "cluster_document": "memory retrieval pattern hippocampus",
            },
            {
                "id": 3,
                "title": "Motor cortex decoding",
                "accepted_for": "Talk",
                "primary_topic": "Motor",
                "cluster_document": "motor cortex decoding movement",
            },
        ]

        summaries = summarize_membership_groups(ids, matrix, records, {0: [1, 2], 1: [3]})

        self.assertEqual(len(summaries), 2)
        self.assertEqual(summaries[0]["primary_topic_counts"]["Memory"], 2)
        self.assertIn("This group centers on", summaries[0]["rationale"])
        self.assertIn("Poster", summaries[0]["rationale"])

    def test_extract_raw_keywords_reads_keywords_response(self) -> None:
        abstract = {
            "responses": [
                {"question_name": "Keywords", "value": '["MRI", "Connectivity"]'},
            ]
        }

        self.assertEqual(extract_raw_keywords(abstract), ["MRI", "Connectivity"])

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

    def test_build_knn_graph_adds_weighted_edges(self) -> None:
        import numpy as np

        ids = [1, 2, 3, 4]
        matrix = np.asarray(
            [
                [1.0, 0.0],
                [0.95, 0.05],
                [0.0, 1.0],
                [0.05, 0.95],
            ],
            dtype=np.float32,
        )

        graph = build_knn_graph(ids, matrix, num_neighbors=2)

        self.assertEqual(graph.number_of_nodes(), 4)
        self.assertGreater(graph.number_of_edges(), 0)
        self.assertIn("weight", next(iter(graph.edges(data=True)))[2])

    def test_detect_stage2_communities_assigns_each_node(self) -> None:
        import networkx as nx

        graph = nx.Graph()
        graph.add_edge(1, 2, weight=1.0)
        graph.add_edge(3, 4, weight=1.0)
        graph.add_edge(2, 3, weight=0.01)

        result = detect_stage2_communities(graph, num_resolution_parameter=4, max_resolution_parameter=1.0)

        self.assertEqual(set(result["assignments"]), {1, 2, 3, 4})
        self.assertGreaterEqual(len(result["communities"]), 1)
        self.assertGreaterEqual(len(result["history"]), 1)

    def test_detect_semantic_communities_assigns_each_node(self) -> None:
        import networkx as nx

        graph = nx.Graph()
        graph.add_edge(10, 11, weight=1.0)
        graph.add_edge(12, 13, weight=1.0)
        graph.add_edge(11, 12, weight=0.01)

        result = detect_semantic_communities(graph, num_resolution_parameter=4, max_resolution_parameter=1.0)

        self.assertEqual(set(result["assignments"]), {10, 11, 12, 13})
        self.assertGreaterEqual(len(result["communities"]), 1)

    def test_detect_semantic_communities_can_require_nontrivial_partition(self) -> None:
        import networkx as nx

        graph = nx.Graph()
        graph.add_edge(1, 2, weight=1.0)
        graph.add_edge(3, 4, weight=1.0)
        graph.add_edge(2, 3, weight=0.1)

        result = detect_semantic_communities(
            graph,
            num_resolution_parameter=10,
            max_resolution_parameter=1.0,
            min_community_count=2,
        )

        self.assertGreaterEqual(len(result["communities"]), 2)

    def test_detect_semantic_communities_at_resolution_assigns_each_node(self) -> None:
        import networkx as nx

        graph = nx.Graph()
        graph.add_edge(20, 21, weight=1.0)
        graph.add_edge(22, 23, weight=1.0)
        graph.add_edge(21, 22, weight=0.01)

        result = detect_semantic_communities_at_resolution(graph, resolution=1.0)

        self.assertEqual(set(result["assignments"]), {20, 21, 22, 23})
        self.assertEqual(result["best_resolution"], 1.0)
        self.assertEqual(len(result["history"]), 1)

    def test_summarize_stage2_clusters_returns_representatives(self) -> None:
        import numpy as np

        ids = [1, 2, 3, 4]
        matrix = np.asarray(
            [
                [1.0, 0.0],
                [0.9, 0.1],
                [0.0, 1.0],
                [0.1, 0.9],
            ],
            dtype=np.float32,
        )
        records = [
            {"id": 1, "title": "Memory encoding", "accepted_for": "Poster", "cluster_document": "memory hippocampus"},
            {"id": 2, "title": "Memory retrieval", "accepted_for": "Poster", "cluster_document": "memory recall"},
            {"id": 3, "title": "Visual cortex", "accepted_for": "Oral", "cluster_document": "vision cortex"},
            {"id": 4, "title": "Visual attention", "accepted_for": "Oral", "cluster_document": "vision attention"},
        ]
        assignments = {1: 0, 2: 0, 3: 1, 4: 1}

        summaries = summarize_stage2_clusters(ids, matrix, records, assignments, max_keywords=3, max_representatives=2)

        self.assertEqual(len(summaries), 2)
        self.assertEqual(summaries[0]["size"], 2)
        self.assertEqual(len(summaries[0]["representative_abstracts"]), 2)
        self.assertIn("accepted_for_counts", summaries[0])

    def test_summarize_semantic_clusters_returns_representatives(self) -> None:
        import numpy as np

        ids = [1, 2, 3, 4]
        matrix = np.asarray(
            [
                [1.0, 0.0],
                [0.9, 0.1],
                [0.0, 1.0],
                [0.1, 0.9],
            ],
            dtype=np.float32,
        )
        records = [
            {"id": 1, "title": "Memory encoding", "accepted_for": "Poster", "cluster_document": "memory hippocampus"},
            {"id": 2, "title": "Memory retrieval", "accepted_for": "Poster", "cluster_document": "memory recall"},
            {"id": 3, "title": "Visual cortex", "accepted_for": "Oral", "cluster_document": "vision cortex"},
            {"id": 4, "title": "Visual attention", "accepted_for": "Oral", "cluster_document": "vision attention"},
        ]
        assignments = {1: 0, 2: 0, 3: 1, 4: 1}

        summaries = summarize_semantic_clusters(ids, matrix, records, assignments, max_keywords=3, max_representatives=2)

        self.assertEqual(len(summaries), 2)
        self.assertEqual(summaries[0]["size"], 2)
        self.assertEqual(len(summaries[0]["representative_abstracts"]), 2)

    def test_align_semantic_records_uses_title_lookup(self) -> None:
        records = align_semantic_records(
            [1],
            {1: {"id": 1, "accepted_for": "Poster", "introduction_markdown": "Intro"}},
            title_lookup={1: "Example title"},
        )

        self.assertEqual(records[0]["title"], "Example title")
        self.assertIn("Introduction:\nIntro", records[0]["cluster_document"])

    def test_align_semantic_records_uses_requested_embedding_fields(self) -> None:
        records = align_semantic_records(
            [1],
            {
                1: {
                    "id": 1,
                    "accepted_for": "Poster",
                    "title": "Example title",
                    "introduction_markdown": "Intro",
                    "claim_extraction": {
                        "claims": [
                            {
                                "claim_id": "C1",
                                "claim_type": "EXPLICIT",
                                "claim": "Neural responses tracked sentence difficulty.",
                            }
                        ]
                    },
                }
            },
            embedding_fields=["claims"],
        )

        self.assertIn("Claims:\n- Neural responses tracked sentence difficulty.", records[0]["cluster_document"])
        self.assertNotIn("Introduction:\nIntro", records[0]["cluster_document"])

    def test_load_annotation_lookup_merges_raw_and_figure_keywords(self) -> None:
        import json

        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            raw_path = root / "abstracts.json"
            enriched_path = root / "abstracts_enriched.json"
            raw_path.write_text(
                json.dumps(
                    {
                        "abstracts": [
                            {
                                "id": 1,
                                "title": "Example",
                                "accepted_for": "Poster",
                                "responses": [
                                    {"question_name": "Keywords", "value": '["MRI"]'},
                                    {
                                        "question_name": "Primary Parent Category & Sub-Category",
                                        "value": '["Brain Stimulation","Non-invasive Magnetic/TMS"]',
                                    },
                                ],
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            enriched_path.write_text(
                json.dumps({"abstracts": [{"id": 1, "figure_keywords": ["cortex", "MRI"]}]}),
                encoding="utf-8",
            )

            lookup = load_annotation_lookup(raw_path, enriched_path)

        self.assertEqual(lookup[1]["title"], "Example")
        self.assertEqual(lookup[1]["keywords"], ["MRI", "cortex"])
        self.assertEqual(lookup[1]["primary_topic"], "Brain Stimulation")

    def test_build_visualization_records_preserves_id_order(self) -> None:
        records = build_visualization_records(
            [2, 1],
            {
                1: {"title": "One", "accepted_for": "Poster", "primary_topic": "MRI", "keywords": ["a"]},
                2: {"title": "Two", "accepted_for": "Oral", "primary_topic": "EEG", "keywords": ["b"]},
            },
        )

        self.assertEqual([record["id"] for record in records], [2, 1])
        self.assertEqual(records[0]["title"], "Two")
        self.assertEqual(records[0]["primary_topic"], "EEG")

    def test_build_semantic_analysis_parser_defaults_to_minilm_bundle(self) -> None:
        parser = build_semantic_analysis_parser()
        args = parser.parse_args([])

        self.assertEqual(args.embeddings_dir, "data/outputs/experiments/embeddings/minilm_stage1")
        self.assertTrue(args.output_dir.startswith("data/outputs/experiments/semantic_analysis__"))

    def test_build_cluster_benchmark_parser_defaults_to_minilm_bundle(self) -> None:
        parser = build_cluster_benchmark_parser()
        args = parser.parse_args([])

        self.assertEqual(args.embeddings_dir, "data/outputs/experiments/embeddings/minilm_stage1")
        self.assertTrue(args.output_dir.startswith("data/outputs/experiments/clustering_benchmark__"))
        self.assertEqual(args.k_min, 2)
        self.assertEqual(args.k_max, 30)
        self.assertTrue(args.row_normalize)

    def test_build_umap_parser_defaults_to_minilm_bundle(self) -> None:
        parser = build_umap_parser()
        args = parser.parse_args([])

        self.assertEqual(args.embeddings_dir, "data/outputs/experiments/embeddings/minilm_stage1")
        self.assertIsNone(args.output_html)
        self.assertIsNone(args.output_json)

    def test_default_umap_output_paths_include_fieldset(self) -> None:
        html_path, json_path = default_umap_output_paths(
            Path("data/outputs/experiments/embeddings/minilm_stage1"),
            ["title", "methods", "results"],
        )

        self.assertIn("data/outputs/experiments/umap_title-methods-results__", str(html_path))
        self.assertIn("/report.html", str(html_path))
        self.assertIn("data/outputs/experiments/umap_title-methods-results__", str(json_path))
        self.assertIn("/projection.json", str(json_path))

    def test_default_projection_output_paths_include_fieldset(self) -> None:
        html_path, json_path = default_projection_output_paths(
            Path("data/outputs/experiments/embeddings/minilm_stage1"),
            ["title", "methods", "results"],
        )

        self.assertIn(
            "data/outputs/experiments/projection_comparison_title-methods-results__",
            str(html_path),
        )
        self.assertIn("/report.html", str(html_path))
        self.assertIn(
            "data/outputs/experiments/projection_comparison_title-methods-results__",
            str(json_path),
        )
        self.assertIn("/projection.json", str(json_path))

    def test_build_distinct_color_map_assigns_unique_colors(self) -> None:
        color_map = build_distinct_color_map(["A", "B", "C", "A"])

        self.assertEqual(set(color_map), {"A", "B", "C"})
        self.assertEqual(len(set(color_map.values())), 3)

    def test_build_projection_compare_parser_defaults(self) -> None:
        parser = build_projection_compare_parser()
        args = parser.parse_args([])

        self.assertEqual(args.embeddings_dir, "data/outputs/experiments/embeddings/minilm_stage1")
        self.assertEqual(args.umap_n_neighbors, 15)
        self.assertEqual(args.tsne_perplexity, 30.0)

    def test_build_projection_optimize_parser_defaults(self) -> None:
        parser = build_projection_optimize_parser()
        args = parser.parse_args([])

        self.assertEqual(args.embeddings_dir, "data/outputs/experiments/embeddings/minilm_stage1")
        self.assertEqual(args.umap_neighbors, [10, 30])
        self.assertEqual(args.tsne_perplexities, [20.0, 40.0])

    def test_build_apply_pretrained_stage2_parser_defaults(self) -> None:
        parser = build_apply_pretrained_stage2_parser()
        args = parser.parse_args([])

        self.assertEqual(args.stage1_dir, "data/outputs/experiments/embeddings/voyage_stage1")
        self.assertTrue(args.model_path.endswith("domain_embedding_model.pth"))
        self.assertEqual(args.output_dir, "data/outputs/experiments/embeddings/voyage_stage2_published")

    def test_build_projection_graph_creates_edges(self) -> None:
        import numpy as np

        graph = build_projection_graph(
            [1, 2, 3, 4],
            np.asarray([[0.0, 0.0], [0.1, 0.0], [2.0, 2.0], [2.1, 2.0]], dtype=np.float32),
            num_neighbors=2,
        )

        self.assertEqual(graph.number_of_nodes(), 4)
        self.assertGreater(graph.number_of_edges(), 0)

    def test_score_projection_reports_cluster_metrics(self) -> None:
        import numpy as np

        metrics = score_projection(
            [1, 2, 3, 4],
            np.asarray([[0.0, 0.0], [0.1, 0.0], [2.0, 2.0], [2.1, 2.0]], dtype=np.float32),
            graph_neighbors=2,
            num_resolution_parameter=4,
        )

        self.assertGreaterEqual(metrics["cluster_count"], 1)
        self.assertIn("best_modularity", metrics)
        self.assertIn("intercluster_distance_ratio", metrics)

    def test_cluster_with_method_returns_labels_for_supported_methods(self) -> None:
        import numpy as np

        matrix = np.asarray(
            [
                [0.0, 0.0],
                [0.1, 0.0],
                [4.0, 4.0],
                [4.1, 4.0],
            ],
            dtype=np.float32,
        )

        for method in [
            "kmeans",
            "agglomerative-ward",
            "agglomerative-average",
            "gaussian-mixture",
            "birch",
            "spectral-nearest-neighbors",
        ]:
            labels = cluster_with_method(matrix, method, cluster_count=2, random_state=7)
            self.assertEqual(len(labels), 4)
            self.assertEqual(len(set(labels)), 2)

    def test_compute_clustering_metrics_reports_density_and_separation(self) -> None:
        import numpy as np

        ids = [1, 2, 3, 4]
        matrix = np.asarray(
            [
                [0.0, 0.0],
                [0.1, 0.0],
                [5.0, 5.0],
                [5.1, 5.0],
            ],
            dtype=np.float32,
        )

        metrics = compute_clustering_metrics(ids, matrix, [0, 0, 1, 1])

        self.assertEqual(metrics["cluster_count"], 2)
        self.assertEqual(metrics["smallest_cluster_size"], 2)
        self.assertGreater(metrics["intercluster_distance_ratio"], 1.0)
        self.assertIsNotNone(metrics["silhouette_score"])
        self.assertIsNotNone(metrics["calinski_harabasz_score"])
        self.assertIsNotNone(metrics["davies_bouldin_score"])

    def test_rank_clustering_benchmark_results_prefers_better_separated_solution(self) -> None:
        ranked = rank_clustering_benchmark_results(
            [
                {
                    "method": "kmeans",
                    "requested_cluster_count": 2,
                    "cluster_count": 2,
                    "valid": True,
                    "silhouette_score": 0.82,
                    "intercluster_distance_ratio": 4.0,
                    "calinski_harabasz_score": 250.0,
                    "davies_bouldin_score": 0.35,
                    "cluster_size_entropy": 1.0,
                    "largest_cluster_fraction": 0.5,
                    "smallest_cluster_size": 10,
                },
                {
                    "method": "birch",
                    "requested_cluster_count": 2,
                    "cluster_count": 2,
                    "valid": True,
                    "silhouette_score": 0.18,
                    "intercluster_distance_ratio": 1.2,
                    "calinski_harabasz_score": 20.0,
                    "davies_bouldin_score": 1.8,
                    "cluster_size_entropy": 0.7,
                    "largest_cluster_fraction": 0.9,
                    "smallest_cluster_size": 1,
                },
            ]
        )

        self.assertEqual(ranked[0]["method"], "kmeans")
        self.assertGreater(ranked[0]["composite_score"], ranked[1]["composite_score"])

    def test_run_clustering_benchmark_returns_ranked_results(self) -> None:
        import numpy as np

        ids = [1, 2, 3, 4, 5, 6]
        matrix = np.asarray(
            [
                [0.0, 0.0],
                [0.1, 0.1],
                [0.2, 0.0],
                [5.0, 5.0],
                [5.1, 5.0],
                [5.0, 5.1],
            ],
            dtype=np.float32,
        )

        benchmark = run_clustering_benchmark(ids, matrix, methods=["kmeans", "birch"], k_values=[2, 3], random_state=7)

        self.assertEqual(len(benchmark["results"]), 4)
        self.assertIsNotNone(benchmark["best_result"])
        self.assertEqual(len(benchmark["best_labels"]), 6)
        self.assertGreaterEqual(benchmark["results"][0]["composite_score"], benchmark["results"][-1]["composite_score"])

    def test_write_projection_comparison_outputs_writes_linked_html_and_json(self) -> None:
        import json
        import numpy as np

        records = [
            {"id": 1, "title": "One", "accepted_for": "Poster", "primary_topic": "MRI", "keywords": ["a"]},
            {"id": 2, "title": "Two", "accepted_for": "Oral", "primary_topic": "EEG", "keywords": ["b"]},
        ]

        with TemporaryDirectory() as temp_dir:
            html_path = Path(temp_dir) / "comparison.html"
            json_path = Path(temp_dir) / "comparison.json"
            write_projection_comparison_outputs(
                html_path,
                json_path,
                np.asarray([[0.1, 0.2], [0.3, 0.4]], dtype=np.float32),
                np.asarray([[1.1, 1.2], [1.3, 1.4]], dtype=np.float32),
                records,
            )

            html = html_path.read_text(encoding="utf-8")
            payload = json.loads(json_path.read_text(encoding="utf-8"))

        self.assertIn("plotly_hover", html)
        self.assertEqual(payload["count"], 2)
        self.assertAlmostEqual(payload["points"][0]["umap_x"], 0.1)
        self.assertAlmostEqual(payload["points"][1]["tsne_y"], 1.4)

    def test_write_pretrained_stage2_bundle_uses_published_metadata(self) -> None:
        import json
        import numpy as np

        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            output_dir = root / "stage2"
            model_path = root / "domain_embedding_model.pth"
            model_path.write_bytes(b"placeholder")
            stage1_bundle = {
                "ids": [1, 2],
                "metadata": [{"id": 1}, {"id": 2}],
                "source_metadata": {
                    "embedding_name": "voyage_stage1",
                    "model_name": "voyage-large-2-instruct",
                    "embedding_fields": ["title", "methods"],
                },
            }
            projected_matrix = np.asarray([[1.0, 0.0], [0.0, 1.0]], dtype=np.float32)

            write_pretrained_stage2_bundle(
                output_dir,
                stage1_bundle,
                projected_matrix,
                model_path=model_path,
                model_name="neuroscape-stage2-published",
                hidden_dimensions=(512, 256, 128),
                output_dimension=64,
                dropout=0.05,
            )

            metadata = json.loads((output_dir / "metadata.json").read_text(encoding="utf-8"))
            self.assertEqual(metadata["source_embedding_name"], "voyage_stage1")
            self.assertEqual(metadata["model_name"], "neuroscape-stage2-published")
            self.assertEqual(metadata["stage2_config"]["hidden_dimensions"], [512, 256, 128])
            self.assertTrue((output_dir / "domain_embedding_model.pth").exists())

    def test_projection_traces_share_legend_groups_across_methods(self) -> None:
        import numpy as np
        from plotly.subplots import make_subplots
        import ohbm2026.neuroscape as neuroscape_module

        records = [
            {"id": 1, "title": "One", "accepted_for": "Poster", "primary_topic": "MRI", "keywords": ["a"]},
            {"id": 2, "title": "Two", "accepted_for": "Poster", "primary_topic": "MRI", "keywords": ["b"]},
        ]
        figure = make_subplots(rows=2, cols=1)

        neuroscape_module._add_projection_panel_traces(
            figure,
            np.asarray([[0.1, 0.2], [0.3, 0.4]], dtype=np.float32),
            records,
            row=1,
            column=1,
            color_by="accepted_for",
            topic_color_map={},
            show_legend=True,
        )
        neuroscape_module._add_projection_panel_traces(
            figure,
            np.asarray([[1.1, 1.2], [1.3, 1.4]], dtype=np.float32),
            records,
            row=2,
            column=1,
            color_by="accepted_for",
            topic_color_map={},
            show_legend=False,
        )

        self.assertEqual(len(figure.data), 2)
        self.assertEqual(figure.data[0].legendgroup, "accepted_for:Poster")
        self.assertEqual(figure.data[1].legendgroup, "accepted_for:Poster")
        self.assertTrue(figure.data[0].showlegend)
        self.assertFalse(figure.data[1].showlegend)

    def test_semantic_analysis_main_writes_outputs(self) -> None:
        import json
        import numpy as np

        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            embeddings_dir = root / "bundle"
            output_dir = root / "analysis"
            input_path = root / "abstracts_enriched.json"
            title_input = root / "abstracts.json"
            embeddings_dir.mkdir(parents=True, exist_ok=True)
            np.save(
                embeddings_dir / "vectors.npy",
                np.asarray(
                    [
                        [1.0, 0.0],
                        [0.95, 0.05],
                        [0.0, 1.0],
                        [0.05, 0.95],
                    ],
                    dtype=np.float32,
                ),
            )
            (embeddings_dir / "metadata.json").write_text(
                json.dumps(
                    {
                        "ids": [1, 2, 3, 4],
                        "metadata": [{"id": 1}, {"id": 2}, {"id": 3}, {"id": 4}],
                        "embedding_name": "minilm_stage1",
                    }
                ),
                encoding="utf-8",
            )
            input_path.write_text(
                json.dumps(
                    {
                        "abstracts": [
                            {"id": 1, "accepted_for": "Poster", "introduction_markdown": "memory intro"},
                            {"id": 2, "accepted_for": "Poster", "introduction_markdown": "memory retrieval"},
                            {"id": 3, "accepted_for": "Oral", "introduction_markdown": "visual cortex"},
                            {"id": 4, "accepted_for": "Oral", "introduction_markdown": "visual attention"},
                        ]
                    }
                ),
                encoding="utf-8",
            )
            title_input.write_text(
                json.dumps(
                    {
                        "abstracts": [
                            {"id": 1, "title": "Memory encoding"},
                            {"id": 2, "title": "Memory retrieval"},
                            {"id": 3, "title": "Visual cortex"},
                            {"id": 4, "title": "Visual attention"},
                        ]
                    }
                ),
                encoding="utf-8",
            )

            with mock.patch("builtins.print") as fake_print:
                result = semantic_analysis_main(
                    [
                        "--embeddings-dir",
                        str(embeddings_dir),
                        "--input",
                        str(input_path),
                        "--title-input",
                        str(title_input),
                        "--output-dir",
                        str(output_dir),
                        "--num-neighbors",
                        "2",
                        "--num-resolution-parameter",
                        "4",
                    ]
                )

            self.assertEqual(result, 0)
            self.assertTrue((output_dir / "article_similarity.graphml").exists())
            self.assertTrue((output_dir / "community_detection.json").exists())
            self.assertTrue((output_dir / "cluster_assignments.json").exists())
            self.assertTrue((output_dir / "cluster_summaries.json").exists())
            fake_print.assert_called_once()

    def test_semantic_analysis_main_supports_fixed_resolution(self) -> None:
        import json
        import numpy as np

        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            embeddings_dir = root / "bundle"
            input_path = root / "abstracts_enriched.json"
            title_input = root / "abstracts.json"
            output_dir = root / "semantic_analysis"
            embeddings_dir.mkdir(parents=True, exist_ok=True)
            np.save(
                embeddings_dir / "vectors.npy",
                np.asarray(
                    [
                        [1.0, 0.0],
                        [0.9, 0.1],
                        [0.0, 1.0],
                        [0.1, 0.9],
                    ],
                    dtype=np.float32,
                ),
            )
            (embeddings_dir / "metadata.json").write_text(
                json.dumps(
                    {
                        "ids": [1, 2, 3, 4],
                        "metadata": [{"id": 1}, {"id": 2}, {"id": 3}, {"id": 4}],
                        "embedding_name": "bundle",
                    }
                ),
                encoding="utf-8",
            )
            input_path.write_text(
                json.dumps(
                    {
                        "abstracts": [
                            {"id": 1, "accepted_for": "Poster", "introduction_markdown": "memory"},
                            {"id": 2, "accepted_for": "Poster", "introduction_markdown": "recall"},
                            {"id": 3, "accepted_for": "Oral", "introduction_markdown": "vision"},
                            {"id": 4, "accepted_for": "Oral", "introduction_markdown": "attention"},
                        ]
                    }
                ),
                encoding="utf-8",
            )
            title_input.write_text(
                json.dumps(
                    {
                        "abstracts": [
                            {"id": 1, "title": "Memory encoding"},
                            {"id": 2, "title": "Memory retrieval"},
                            {"id": 3, "title": "Visual cortex"},
                            {"id": 4, "title": "Visual attention"},
                        ]
                    }
                ),
                encoding="utf-8",
            )

            with mock.patch("builtins.print") as fake_print:
                result = semantic_analysis_main(
                    [
                        "--embeddings-dir",
                        str(embeddings_dir),
                        "--input",
                        str(input_path),
                        "--title-input",
                        str(title_input),
                        "--output-dir",
                        str(output_dir),
                        "--num-neighbors",
                        "2",
                        "--resolution",
                        "1.0",
                    ]
                )

            self.assertEqual(result, 0)
            self.assertTrue((output_dir / "community_detection.json").exists())
            data = json.loads((output_dir / "community_detection.json").read_text(encoding="utf-8"))
            self.assertEqual(data["best_resolution"], 1.0)
            fake_print.assert_called_once()

    def test_cluster_benchmark_main_writes_outputs(self) -> None:
        import json
        import numpy as np

        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            embeddings_dir = root / "bundle"
            input_path = root / "abstracts_enriched.json"
            title_input = root / "abstracts.json"
            output_dir = root / "clustering_benchmark"
            embeddings_dir.mkdir(parents=True, exist_ok=True)
            np.save(
                embeddings_dir / "vectors.npy",
                np.asarray(
                    [
                        [0.0, 0.0],
                        [0.1, 0.0],
                        [0.0, 0.1],
                        [5.0, 5.0],
                        [5.1, 5.0],
                        [5.0, 5.1],
                    ],
                    dtype=np.float32,
                ),
            )
            (embeddings_dir / "metadata.json").write_text(
                json.dumps(
                    {
                        "ids": [1, 2, 3, 4, 5, 6],
                        "metadata": [{"id": 1}, {"id": 2}, {"id": 3}, {"id": 4}, {"id": 5}, {"id": 6}],
                        "embedding_name": "bundle",
                        "embedding_fields": ["claims"],
                    }
                ),
                encoding="utf-8",
            )
            input_path.write_text(
                json.dumps(
                    {
                        "abstracts": [
                            {
                                "id": 1,
                                "accepted_for": "Poster",
                                "claim_extraction": {"claims": [{"claim_id": "C1", "claim_type": "EXPLICIT", "claim": "memory fmri hippocampus"}]},
                            },
                            {
                                "id": 2,
                                "accepted_for": "Poster",
                                "claim_extraction": {"claims": [{"claim_id": "C1", "claim_type": "EXPLICIT", "claim": "memory fmri encoding"}]},
                            },
                            {
                                "id": 3,
                                "accepted_for": "Poster",
                                "claim_extraction": {"claims": [{"claim_id": "C1", "claim_type": "EXPLICIT", "claim": "memory fmri recall"}]},
                            },
                            {
                                "id": 4,
                                "accepted_for": "Oral",
                                "claim_extraction": {"claims": [{"claim_id": "C1", "claim_type": "EXPLICIT", "claim": "vision eeg cortex"}]},
                            },
                            {
                                "id": 5,
                                "accepted_for": "Oral",
                                "claim_extraction": {"claims": [{"claim_id": "C1", "claim_type": "EXPLICIT", "claim": "vision eeg attention"}]},
                            },
                            {
                                "id": 6,
                                "accepted_for": "Oral",
                                "claim_extraction": {"claims": [{"claim_id": "C1", "claim_type": "EXPLICIT", "claim": "vision eeg perception"}]},
                            },
                        ]
                    }
                ),
                encoding="utf-8",
            )
            title_input.write_text(
                json.dumps(
                    {
                        "abstracts": [
                            {"id": 1, "title": "Memory 1"},
                            {"id": 2, "title": "Memory 2"},
                            {"id": 3, "title": "Memory 3"},
                            {"id": 4, "title": "Vision 1"},
                            {"id": 5, "title": "Vision 2"},
                            {"id": 6, "title": "Vision 3"},
                        ]
                    }
                ),
                encoding="utf-8",
            )

            with mock.patch("builtins.print") as fake_print:
                result = cluster_benchmark_main(
                    [
                        "--embeddings-dir",
                        str(embeddings_dir),
                        "--input",
                        str(input_path),
                        "--title-input",
                        str(title_input),
                        "--output-dir",
                        str(output_dir),
                        "--methods",
                        "kmeans",
                        "birch",
                        "--k-min",
                        "2",
                        "--k-max",
                        "3",
                        "--pca-components",
                        "2",
                    ]
                )

            self.assertEqual(result, 0)
            self.assertTrue((output_dir / "benchmark.json").exists())
            self.assertTrue((output_dir / "best_run.json").exists())
            self.assertTrue((output_dir / "cluster_assignments.json").exists())
            self.assertTrue((output_dir / "cluster_summaries.json").exists())
            benchmark = json.loads((output_dir / "benchmark.json").read_text(encoding="utf-8"))
            self.assertEqual(len(benchmark["results"]), 4)
            summaries = json.loads((output_dir / "cluster_summaries.json").read_text(encoding="utf-8"))
            cluster_text = json.dumps(summaries)
            self.assertIn("memory", cluster_text)
            self.assertIn("vision", cluster_text)
            fake_print.assert_called_once()

    def test_umap_main_writes_outputs(self) -> None:
        import json
        import numpy as np

        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            embeddings_dir = root / "bundle"
            raw_path = root / "abstracts.json"
            enriched_path = root / "abstracts_enriched.json"
            output_html = root / "umap.html"
            output_json = root / "umap.json"
            embeddings_dir.mkdir(parents=True, exist_ok=True)
            np.save(
                embeddings_dir / "vectors.npy",
                np.asarray([[1.0, 0.0], [0.0, 1.0]], dtype=np.float32),
            )
            (embeddings_dir / "metadata.json").write_text(
                json.dumps(
                    {
                        "ids": [1, 2],
                        "metadata": [{"id": 1}, {"id": 2}],
                        "embedding_name": "minilm_stage1",
                    }
                ),
                encoding="utf-8",
            )
            raw_path.write_text(
                json.dumps(
                    {
                        "abstracts": [
                            {
                                "id": 1,
                                "title": "One",
                                "accepted_for": "Poster",
                                "responses": [{"question_name": "Keywords", "value": '["MRI"]'}],
                            },
                            {
                                "id": 2,
                                "title": "Two",
                                "accepted_for": "Oral",
                                "responses": [{"question_name": "Keywords", "value": '["EEG"]'}],
                            },
                        ]
                    }
                ),
                encoding="utf-8",
            )
            enriched_path.write_text(
                json.dumps({"abstracts": [{"id": 1, "figure_keywords": ["cortex"]}, {"id": 2, "figure_keywords": []}]}),
                encoding="utf-8",
            )

            with mock.patch("ohbm2026.neuroscape.compute_umap_projection", return_value=np.asarray([[0.1, 0.2], [0.3, 0.4]])), \
                 mock.patch("ohbm2026.neuroscape.write_umap_outputs") as write_umap_outputs_mock, \
                 mock.patch("builtins.print") as fake_print:
                result = umap_main(
                    [
                        "--embeddings-dir",
                        str(embeddings_dir),
                        "--raw-input",
                        str(raw_path),
                        "--enriched-input",
                        str(enriched_path),
                        "--output-html",
                        str(output_html),
                        "--output-json",
                        str(output_json),
                    ]
                )

            self.assertEqual(result, 0)
            write_umap_outputs_mock.assert_called_once()
            args = write_umap_outputs_mock.call_args.args
            self.assertEqual(args[0], output_html)
            self.assertEqual(args[1], output_json)
            self.assertEqual(args[3][0]["keywords"], ["MRI", "cortex"])
            fake_print.assert_called_once()

    def test_projection_compare_main_writes_outputs(self) -> None:
        import json
        import numpy as np

        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            embeddings_dir = root / "bundle"
            raw_path = root / "abstracts.json"
            enriched_path = root / "abstracts_enriched.json"
            output_html = root / "comparison.html"
            output_json = root / "comparison.json"
            embeddings_dir.mkdir(parents=True, exist_ok=True)
            np.save(embeddings_dir / "vectors.npy", np.asarray([[1.0, 0.0], [0.0, 1.0]], dtype=np.float32))
            (embeddings_dir / "metadata.json").write_text(
                json.dumps(
                    {
                        "ids": [1, 2],
                        "metadata": [{"id": 1}, {"id": 2}],
                        "embedding_name": "minilm_stage1",
                        "embedding_fields": ["title", "results"],
                    }
                ),
                encoding="utf-8",
            )
            raw_path.write_text(
                json.dumps(
                    {
                        "abstracts": [
                            {
                                "id": 1,
                                "title": "One",
                                "accepted_for": "Poster",
                                "responses": [{"question_name": "Keywords", "value": '["MRI"]'}],
                            },
                            {
                                "id": 2,
                                "title": "Two",
                                "accepted_for": "Oral",
                                "responses": [{"question_name": "Keywords", "value": '["EEG"]'}],
                            },
                        ]
                    }
                ),
                encoding="utf-8",
            )
            enriched_path.write_text(json.dumps({"abstracts": [{"id": 1}, {"id": 2}]}), encoding="utf-8")

            with mock.patch(
                "ohbm2026.neuroscape.compute_umap_projection",
                return_value=np.asarray([[0.1, 0.2], [0.3, 0.4]], dtype=np.float32),
            ), mock.patch(
                "ohbm2026.neuroscape.compute_tsne_projection",
                return_value=np.asarray([[1.1, 1.2], [1.3, 1.4]], dtype=np.float32),
            ), mock.patch(
                "ohbm2026.neuroscape.write_projection_comparison_outputs"
            ) as write_projection_comparison_outputs_mock, mock.patch("builtins.print") as fake_print:
                result = projection_compare_main(
                    [
                        "--embeddings-dir",
                        str(embeddings_dir),
                        "--raw-input",
                        str(raw_path),
                        "--enriched-input",
                        str(enriched_path),
                        "--output-html",
                        str(output_html),
                        "--output-json",
                        str(output_json),
                    ]
                )

            self.assertEqual(result, 0)
            write_projection_comparison_outputs_mock.assert_called_once()
            args = write_projection_comparison_outputs_mock.call_args.args
            self.assertEqual(args[0], output_html)
            self.assertEqual(args[1], output_json)
            self.assertEqual(args[4][0]["keywords"], ["MRI"])
            fake_print.assert_called_once()

    def test_projection_optimize_main_prints_ranked_results(self) -> None:
        import json
        import numpy as np

        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            embeddings_dir = root / "bundle"
            output_path = root / "scores.json"
            embeddings_dir.mkdir(parents=True, exist_ok=True)
            np.save(embeddings_dir / "vectors.npy", np.asarray([[1.0, 0.0], [0.9, 0.1], [0.0, 1.0]], dtype=np.float32))
            (embeddings_dir / "metadata.json").write_text(
                json.dumps(
                    {
                        "ids": [1, 2, 3],
                        "metadata": [{"id": 1}, {"id": 2}, {"id": 3}],
                        "embedding_name": "minilm_stage1",
                    }
                ),
                encoding="utf-8",
            )

            optimization_payload = {
                "best_overall": {"method": "umap", "best_modularity": 0.5},
                "best_by_method": {"umap": {"method": "umap"}, "tsne": {"method": "tsne"}},
                "results": [{"method": "umap"}, {"method": "tsne"}],
            }
            with mock.patch(
                "ohbm2026.neuroscape.optimize_projection_parameters",
                return_value=optimization_payload,
            ) as optimize_mock, mock.patch("builtins.print") as fake_print:
                result = projection_optimize_main(
                    [
                        "--embeddings-dir",
                        str(embeddings_dir),
                        "--output",
                        str(output_path),
                        "--top-k",
                        "1",
                    ]
                )

            self.assertEqual(result, 0)
            optimize_mock.assert_called_once()
            self.assertTrue(output_path.exists())
            fake_print.assert_called_once()

    def test_apply_pretrained_stage2_main_writes_outputs(self) -> None:
        import json
        import numpy as np

        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            stage1_dir = root / "voyage_stage1"
            output_dir = root / "voyage_stage2_published"
            model_path = root / "domain_embedding_model.pth"
            stage1_dir.mkdir(parents=True, exist_ok=True)
            np.save(stage1_dir / "vectors.npy", np.ones((2, 1024), dtype=np.float32))
            (stage1_dir / "metadata.json").write_text(
                json.dumps(
                    {
                        "ids": [1, 2],
                        "metadata": [{"id": 1}, {"id": 2}],
                        "embedding_name": "voyage_stage1",
                        "model_name": "voyage-large-2-instruct",
                        "embedding_fields": ["title", "results"],
                    }
                ),
                encoding="utf-8",
            )
            model_path.write_bytes(b"model")

            fake_model = object()
            projected = np.asarray([[0.1] * 64, [0.2] * 64], dtype=np.float32)
            with mock.patch(
                "ohbm2026.neuroscape.load_pretrained_stage2_model",
                return_value=(fake_model, "cpu"),
            ) as load_model_mock, mock.patch(
                "ohbm2026.neuroscape.apply_stage2_model",
                return_value=projected,
            ) as apply_mock, mock.patch(
                "builtins.print"
            ) as fake_print:
                result = apply_pretrained_stage2_main(
                    [
                        "--stage1-dir",
                        str(stage1_dir),
                        "--model-path",
                        str(model_path),
                        "--output-dir",
                        str(output_dir),
                    ]
                )

            self.assertEqual(result, 0)
            load_model_mock.assert_called_once()
            apply_mock.assert_called_once()
            self.assertTrue((output_dir / "metadata.json").exists())
            fake_print.assert_called_once()


if __name__ == "__main__":
    unittest.main()
