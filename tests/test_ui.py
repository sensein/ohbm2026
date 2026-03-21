import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np

from ohbm2026.ui import (
    build_export_parser,
    build_ui_main,
    build_ui_payload,
    markdown_to_html,
    primary_topic_from_questions,
    render_additional_content_markdown,
    secondary_topic_from_questions,
    topic_subcategories_from_questions,
)


class UIHelpersTest(unittest.TestCase):
    def test_markdown_to_html_renders_lists_and_links(self) -> None:
        html = markdown_to_html("## Heading\n\n- One\n- Two\n\n[Paper](https://example.com)")

        self.assertIn("<h3>Heading</h3>", html)
        self.assertIn("<ul><li>One</li><li>Two</li></ul>", html)
        self.assertIn('href="https://example.com"', html)

    def test_markdown_to_html_renders_four_hash_heading(self) -> None:
        html = markdown_to_html("#### Top panel\n\n- Point")

        self.assertIn("<h5>Top panel</h5>", html)
        self.assertNotIn("#### Top panel", html)

    def test_render_additional_content_markdown_normalizes_list_payload(self) -> None:
        markdown = render_additional_content_markdown(
            [
                {"question_name": "Keywords", "markdown": '["MRI","Aging"]'},
                {"question_name": "Methods", "markdown": "Functional MRI"},
            ]
        )

        self.assertIn("### Keywords", markdown)
        self.assertIn("Functional MRI", markdown)

    def test_topic_helpers_use_parent_and_true_subcategories(self) -> None:
        questions = {
            "Primary Parent Category & Sub-Category": '["Modeling and Analysis Methods","Classification and Predictive Modeling"]',
            "Secondary Parent Category & Sub-Category": '["Neuroinformatics and Data Sharing","Informatics Other"]',
        }

        self.assertEqual(primary_topic_from_questions(questions), "Modeling and Analysis Methods")
        self.assertEqual(secondary_topic_from_questions(questions), "Classification and Predictive Modeling")
        self.assertEqual(
            topic_subcategories_from_questions(questions),
            ["Classification and Predictive Modeling", "Informatics Other"],
        )

    def test_build_export_parser_defaults(self) -> None:
        args = build_export_parser().parse_args([])

        self.assertEqual(args.output_dir, "export/ui-site/data")
        self.assertEqual(args.top_neighbors, 8)
        self.assertEqual(args.image_analyses_input, "data/image_analyses_openai.json")
        self.assertEqual(args.cluster_25_dir, "data/embeddings/voyage_stage2_published/clustering_benchmark")
        self.assertEqual(args.spectral_cluster_dir, "data/embeddings/voyage_stage2_published/clustering_benchmark_spectral")
        self.assertEqual(args.claims_cluster_dir, "data/embeddings/minilm_claims/clustering_benchmark_25_30")
        self.assertEqual(args.semantic_vectors_input, "data/embeddings/minilm_stage1/vectors.npy")
        self.assertEqual(args.umap_input, "data/embeddings/minilm_stage1/umap_title-introduction-methods-results-conclusion.json")

    def test_build_ui_payload_writes_search_detail_and_relation_fields(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            raw_input = root / "abstracts.json"
            enriched_input = root / "abstracts_enriched.json"
            references_input = root / "reference_metadata.json"
            image_analyses_input = root / "image_analyses.json"
            neighbors_input = root / "neighbors.json"
            semantic_vectors_input = root / "vectors.npy"
            semantic_metadata_input = root / "metadata.json"
            umap_input = root / "umap.json"
            cluster_15_dir = root / "semantic_analysis_15"
            cluster_21_dir = root / "semantic_analysis_21"
            cluster_25_dir = root / "clustering_benchmark"
            spectral_cluster_dir = root / "clustering_benchmark_spectral"
            claims_cluster_dir = root / "claims_clustering_benchmark"
            cluster_15_dir.mkdir()
            cluster_21_dir.mkdir()
            cluster_25_dir.mkdir()
            spectral_cluster_dir.mkdir()
            claims_cluster_dir.mkdir()

            raw_input.write_text(
                json.dumps(
                    {
                        "abstracts": [
                            {
                                "id": 1,
                                "title": "  Memory fMRI in aging  ",
                                "accepted_for": "Poster",
                                "responses": [
                                    {"question_name": "Keywords", "value": '["Aging","MRI"]'},
                                    {
                                        "question_name": "Primary Parent Category & Sub-Category",
                                        "value": '["Lifespan Development","Aging"]',
                                    },
                                    {
                                        "question_name": "Secondary Parent Category & Sub-Category",
                                        "value": '["Neuroinformatics and Data Sharing","Informatics Other"]',
                                    },
                                    {
                                        "question_name": "Please indicate which methods were used in your research:",
                                        "value": '["Functional MRI"]',
                                    },
                                    {
                                        "question_name": "Results",
                                        "value": "Human hippocampus connectivity changes were measured with fMRI in the default mode network.",
                                    },
                                ],
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            enriched_input.write_text(
                json.dumps(
                    {
                        "abstracts": [
                            {
                                "id": 1,
                                "accepted_for": "Poster",
                                "introduction_markdown": "Intro text",
                                "methods_markdown": "Human participants were scanned with fMRI.",
                                "results_markdown": "Hippocampus connectivity increased in the default mode network.",
                                "conclusion_markdown": "Conclusion text",
                                "claim_extraction": {
                                    "status": "ok",
                                    "backend": "cllm",
                                    "llm_provider": "openai",
                                    "llm_model": "gpt-4o-2024-08-06",
                                    "claim_count": 1,
                                    "claims": [
                                        {
                                            "claim_id": "C1",
                                            "claim": "Hippocampus connectivity increased.",
                                            "claim_type": "result",
                                            "source": "Results",
                                            "source_type": "section",
                                            "evidence": "Connectivity increased in the default mode network.",
                                            "evidence_type": "text",
                                        }
                                    ],
                                },
                                "figure_keywords": ["Flowchart"],
                                "figure_analyses": [
                                    {
                                        "question_name": "Results Figure (Optional)",
                                        "analysis": {
                                            "caption_guess": "Results panel",
                                            "notes": "Result note",
                                            "ocr_text": "",
                                            "rich_markdown": "#### Result panel",
                                            "keywords": ["result"],
                                        },
                                    },
                                    {
                                        "question_name": "Methods Figure (Optional)",
                                        "analysis": {
                                            "caption_guess": "Methods panel",
                                            "notes": "Method note",
                                            "ocr_text": "",
                                            "rich_markdown": "#### Method panel",
                                            "keywords": ["method"],
                                        },
                                    },
                                    {
                                        "analysis": {
                                            "caption_guess": "Flowchart of hippocampus MRI processing",
                                            "notes": "Shows memory cohort filtering",
                                            "ocr_text": "hippocampus default mode network MRI",
                                            "rich_markdown": "Figure describes **hippocampus** filtering",
                                            "keywords": ["hippocampus", "MRI"],
                                        }
                                    }
                                ],
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            references_input.write_text(
                json.dumps(
                    {
                        "references": [
                            {
                                "reference_key": "doi:10.1/example",
                                "openalex": {
                                    "display_name": "Example paper",
                                    "journal": "NeuroImage",
                                    "publication_year": 2024,
                                    "cited_by_count": 12,
                                    "doi": "10.1/example",
                                    "openalex_id": "https://openalex.org/W1",
                                },
                            }
                        ],
                        "abstracts": [
                            {
                                "id": 1,
                                "references": [
                                    {
                                        "reference_key": "doi:10.1/example",
                                        "matched": True,
                                    }
                                ],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            image_analyses_input.write_text(
                json.dumps(
                    {
                        "analyses": {
                            "data/assets/1_fig.png": {
                                "abstract_id": 1,
                                "question_name": "Methods Figure (Optional)",
                                "analysis": {
                                    "caption_guess": "Figure caption",
                                    "notes": "Figure notes",
                                    "keywords": ["Diagram"],
                                    "rich_markdown": "Figure **detail**",
                                },
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )
            neighbors_input.write_text(
                json.dumps({"neighbors": {"1": [{"id": 2, "score": 0.9}]}}),
                encoding="utf-8",
            )
            np.save(semantic_vectors_input, np.array([[1.0, 0.0], [0.0, 1.0]], dtype=np.float32))
            semantic_metadata_input.write_text(
                json.dumps(
                    {
                        "ids": [1, 99],
                        "embedding_fields": ["title", "methods"],
                        "embedding_name": "minilm_stage1",
                        "model_name": "sentence-transformers/all-MiniLM-L6-v2",
                    }
                ),
                encoding="utf-8",
            )
            umap_input.write_text(
                json.dumps(
                    {
                        "title": "Test UMAP",
                        "points": [
                            {
                                "id": 1,
                                "title": "Memory fMRI in aging",
                                "accepted_for": "Poster",
                                "primary_topic": "Lifespan Development",
                                "keywords": ["Aging", "MRI"],
                                "x": 1.0,
                                "y": 2.0,
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            for directory, cluster_id, label in (
                (cluster_15_dir, 3, "graph, memory, aging"),
                (cluster_21_dir, 7, "unused"),
                (cluster_25_dir, 11, "memory, aging, hippocampus"),
                (spectral_cluster_dir, 31, "spectral, memory, fmri"),
                (claims_cluster_dir, 28, "pd, disease, patients"),
            ):
                (directory / "cluster_assignments.json").write_text(
                    json.dumps({"assignments": {"1": cluster_id}}),
                    encoding="utf-8",
                )
                if "semantic_analysis" in directory.name:
                    (directory / "community_detection.json").write_text(
                        json.dumps({"best_resolution": 2.5, "best_modularity": 0.41}),
                        encoding="utf-8",
                    )
                else:
                    (directory / "best_run.json").write_text(
                        json.dumps({"method": "kmeans", "cluster_count": cluster_id, "silhouette_score": 0.1}),
                        encoding="utf-8",
                    )
                (directory / "cluster_summaries.json").write_text(
                    json.dumps(
                        {
                            "clusters": [
                                {
                                    "cluster_id": cluster_id,
                                    "label": label,
                                    "size": 10,
                                    "keywords": label.split(", "),
                                    "accepted_for_counts": {"Poster": 10},
                                    "representative_abstracts": [{"id": 1, "title": "Memory fMRI in aging"}],
                                }
                            ]
                        }
                    ),
                    encoding="utf-8",
                )

            payload = build_ui_payload(
                raw_input=raw_input,
                enriched_input=enriched_input,
                references_input=references_input,
                image_analyses_input=image_analyses_input,
                neighbors_input=neighbors_input,
                cluster_15_dir=cluster_15_dir,
                cluster_21_dir=cluster_21_dir,
                cluster_25_dir=cluster_25_dir,
                spectral_cluster_dir=spectral_cluster_dir,
                claims_cluster_dir=claims_cluster_dir,
                semantic_vectors_input=semantic_vectors_input,
                semantic_metadata_input=semantic_metadata_input,
                umap_input=umap_input,
                top_neighbors=5,
            )

        self.assertEqual(payload["manifest"]["abstract_count"], 1)
        self.assertEqual(payload["search"]["abstracts"][0]["title"], "Memory fMRI in aging")
        self.assertEqual(payload["search"]["abstracts"][0]["primary_topic"], "Lifespan Development")
        self.assertEqual(payload["search"]["abstracts"][0]["secondary_topic"], "Aging")
        self.assertEqual(payload["search"]["abstracts"][0]["facets"]["voyage_graph_15"], ["3: graph, memory, aging"])
        self.assertEqual(payload["search"]["abstracts"][0]["facets"]["semantic_25"], ["11: memory, aging, hippocampus"])
        self.assertEqual(payload["search"]["abstracts"][0]["facets"]["voyage_spectral_31"], ["31: spectral, memory, fmri"])
        self.assertEqual(payload["search"]["abstracts"][0]["facets"]["claims_28"], ["28: pd, disease, patients"])
        self.assertEqual(
            payload["search"]["abstracts"][0]["facets"]["secondary_topic"],
            ["Aging", "Informatics Other"],
        )
        self.assertEqual(
            payload["facets"]["groups"][:5],
            ["accepted_for", "primary_topic", "secondary_topic", "keywords", "methods"],
        )
        self.assertIn("secondary_topic", payload["facets"]["groups"])
        self.assertIn("voyage_graph_15", payload["facets"]["groups"])
        self.assertIn("voyage_spectral_31", payload["facets"]["groups"])
        self.assertIn("claims_28", payload["facets"]["groups"])
        self.assertEqual(payload["search"]["abstracts"][0]["facets"]["species"], ["Human"])
        self.assertEqual(payload["search"]["abstracts"][0]["facets"]["brain_regions"], ["Hippocampus"])
        self.assertEqual(payload["search"]["abstracts"][0]["facets"]["brain_networks"], ["Default Mode Network"])
        self.assertNotIn("figure_keywords", payload["search"]["abstracts"][0]["facets"])
        self.assertNotIn("figure_keywords", payload["facets"]["groups"])
        self.assertEqual(payload["details"]["abstracts"]["1"]["recording_technology"], ["fMRI"])
        self.assertEqual(payload["details"]["abstracts"]["1"]["figure_keywords"], ["Flowchart"])
        self.assertEqual(
            [item["question_name"] for item in payload["details"]["abstracts"]["1"]["figure_analyses"][:2]],
            ["Methods Figure (Optional)", "Results Figure (Optional)"],
        )
        self.assertEqual(payload["details"]["abstracts"]["1"]["claim_extraction"]["claim_count"], 1)
        self.assertEqual(payload["details"]["abstracts"]["1"]["reference_summary"]["matched_count"], 1)
        self.assertEqual(payload["relations"]["abstracts"]["1"]["neighbors"][0]["id"], 2)
        self.assertEqual(
            payload["relations"]["abstracts"]["1"]["clusters"],
            {"voyage_graph_15": 3, "semantic_25": 11, "voyage_spectral_31": 31, "claims_28": 28},
        )
        self.assertEqual(
            payload["manifest"]["partitions"],
            {
                "voyage_graph_15": str(cluster_15_dir),
                "semantic_25": str(cluster_25_dir),
                "voyage_spectral_31": str(spectral_cluster_dir),
                "claims_28": str(claims_cluster_dir),
            },
        )
        self.assertEqual([layer["key"] for layer in payload["manifest"]["cluster_layers"]], ["voyage_graph_15", "semantic_25", "voyage_spectral_31", "claims_28"])
        self.assertEqual(payload["manifest"]["semantic_search"]["dimension"], 2)
        self.assertEqual(payload["manifest"]["semantic_search"]["browser_model"], "Xenova/all-MiniLM-L6-v2")
        self.assertEqual(payload["projection"]["umap"]["count"], 1)
        self.assertIn("Flowchart of hippocampus MRI processing", payload["search"]["abstracts"][0]["search_blob"])

    def test_build_ui_main_copies_static_assets_and_data(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source_dir = root / "ui"
            source_dir.mkdir()
            (source_dir / "index.html").write_text("<!doctype html><title>UI</title>", encoding="utf-8")
            (source_dir / "app.js").write_text("console.log('ui');", encoding="utf-8")
            (source_dir / "styles.css").write_text("body{}", encoding="utf-8")

            raw_input = root / "abstracts.json"
            enriched_input = root / "abstracts_enriched.json"
            references_input = root / "reference_metadata.json"
            image_analyses_input = root / "image_analyses.json"
            neighbors_input = root / "neighbors.json"
            semantic_vectors_input = root / "vectors.npy"
            semantic_metadata_input = root / "metadata.json"
            umap_input = root / "umap.json"
            cluster_15_dir = root / "semantic_analysis_15"
            cluster_21_dir = root / "semantic_analysis_21"
            cluster_25_dir = root / "clustering_benchmark"
            spectral_cluster_dir = root / "clustering_benchmark_spectral"
            claims_cluster_dir = root / "claims_clustering_benchmark"
            site_output_dir = root / "site"
            cluster_15_dir.mkdir()
            cluster_21_dir.mkdir()
            cluster_25_dir.mkdir()
            spectral_cluster_dir.mkdir()
            claims_cluster_dir.mkdir()

            raw_input.write_text(
                json.dumps({"abstracts": [{"id": 1, "title": "T", "accepted_for": "Poster", "responses": []}]}),
                encoding="utf-8",
            )
            enriched_input.write_text(
                json.dumps({"abstracts": [{"id": 1, "accepted_for": "Poster"}]}),
                encoding="utf-8",
            )
            references_input.write_text(
                json.dumps({"references": [], "abstracts": [{"id": 1, "references": []}]}),
                encoding="utf-8",
            )
            image_analyses_input.write_text(json.dumps({"analyses": {}}), encoding="utf-8")
            neighbors_input.write_text(json.dumps({"neighbors": {"1": []}}), encoding="utf-8")
            np.save(semantic_vectors_input, np.array([[1.0, 0.0]], dtype=np.float32))
            semantic_metadata_input.write_text(
                json.dumps(
                    {
                        "ids": [1],
                        "embedding_fields": ["title"],
                        "embedding_name": "minilm_stage1",
                        "model_name": "sentence-transformers/all-MiniLM-L6-v2",
                    }
                ),
                encoding="utf-8",
            )
            umap_input.write_text(
                json.dumps(
                    {
                        "title": "Test UMAP",
                        "points": [
                            {
                                "id": 1,
                                "title": "T",
                                "accepted_for": "Poster",
                                "primary_topic": "Unknown",
                                "keywords": [],
                                "x": 0.0,
                                "y": 0.0,
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            for directory in (cluster_15_dir, cluster_21_dir, cluster_25_dir, spectral_cluster_dir, claims_cluster_dir):
                (directory / "cluster_assignments.json").write_text(
                    json.dumps({"assignments": {"1": 0}}),
                    encoding="utf-8",
                )
                if "semantic_analysis" in directory.name:
                    (directory / "community_detection.json").write_text(
                        json.dumps({"best_resolution": 2.5, "best_modularity": 0.41}),
                        encoding="utf-8",
                    )
                else:
                    (directory / "best_run.json").write_text(
                        json.dumps({"method": "kmeans", "cluster_count": 1, "silhouette_score": 0.1}),
                        encoding="utf-8",
                    )
                (directory / "cluster_summaries.json").write_text(
                    json.dumps(
                        {
                            "clusters": [
                                {
                                    "cluster_id": 0,
                                    "label": "cluster",
                                    "size": 1,
                                    "keywords": [],
                                    "accepted_for_counts": {},
                                    "representative_abstracts": [],
                                }
                            ]
                        }
                    ),
                    encoding="utf-8",
                )

            result = build_ui_main(
                [
                    "--source-dir",
                    str(source_dir),
                    "--site-output-dir",
                    str(site_output_dir),
                    "--raw-input",
                    str(raw_input),
                    "--enriched-input",
                    str(enriched_input),
                    "--references-input",
                    str(references_input),
                    "--image-analyses-input",
                    str(image_analyses_input),
                    "--neighbors-input",
                    str(neighbors_input),
                    "--cluster-15-dir",
                    str(cluster_15_dir),
                    "--cluster-21-dir",
                    str(cluster_21_dir),
                    "--cluster-25-dir",
                    str(cluster_25_dir),
                    "--spectral-cluster-dir",
                    str(spectral_cluster_dir),
                    "--claims-cluster-dir",
                    str(claims_cluster_dir),
                    "--semantic-vectors-input",
                    str(semantic_vectors_input),
                    "--semantic-metadata-input",
                    str(semantic_metadata_input),
                    "--umap-input",
                    str(umap_input),
                ]
            )

            self.assertEqual(result, 0)
            self.assertTrue((site_output_dir / "index.html").exists())
            self.assertTrue((site_output_dir / "data" / "abstracts.search.json").exists())
            self.assertTrue((site_output_dir / "data" / "semantic.vectors.f32").exists())
            self.assertTrue((site_output_dir / "data" / "projection.umap.json").exists())


if __name__ == "__main__":
    unittest.main()
