import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from ohbm2026.enrichment import (
    EnrichmentError,
    analyze_figures,
    build_figure_analysis_parser,
    build_sections_markdown,
    enrich_database,
    filter_content_questions_markdown,
    html_to_markdown,
    is_content_question,
    load_json,
    parse_jsonish_content,
    question_to_section,
    resolve_openai_api_key,
    render_abstract_markdown,
)


class EnrichmentHelpersTest(unittest.TestCase):
    def test_html_to_markdown_handles_lists_and_emphasis(self) -> None:
        html = "<p>Hello <strong>world</strong></p><ol><li>One</li><li>Two</li></ol>"
        markdown = html_to_markdown(html)
        self.assertIn("Hello **world**", markdown)
        self.assertIn("1. One", markdown)
        self.assertIn("2. Two", markdown)

    def test_question_to_section_maps_expected_questions(self) -> None:
        self.assertEqual(question_to_section("Introduction"), "introduction")
        self.assertEqual(question_to_section("Methods"), "methods")
        self.assertEqual(question_to_section("Results Figure (Optional)"), None)

    def test_build_sections_markdown_collects_core_sections(self) -> None:
        abstract = {
            "responses": [
                {"question_name": "Introduction", "value": "<p>Intro text</p>"},
                {"question_name": "Methods", "value": "<p>Methods text</p>"},
                {"question_name": "Random", "value": "<p>Other text</p>"},
            ]
        }
        sections, unmapped = build_sections_markdown(abstract)
        self.assertEqual(sections["introduction"], "Intro text")
        self.assertEqual(sections["methods"], "Methods text")
        self.assertEqual(unmapped, [{"question_name": "Random", "markdown": "Other text"}])

    def test_render_abstract_markdown_includes_section_headings(self) -> None:
        rendered = render_abstract_markdown("Title", {"introduction": "Intro", "results": "Result"})
        self.assertIn("# Title", rendered)
        self.assertIn("## Introduction", rendered)
        self.assertIn("## Results", rendered)

    def test_parse_jsonish_content_accepts_fenced_json(self) -> None:
        content = "```json\n{\"caption_guess\": \"Example\", \"keywords\": []}\n```"
        parsed = parse_jsonish_content(content)
        self.assertEqual(parsed["caption_guess"], "Example")

    def test_is_content_question_filters_admin_prompts(self) -> None:
        self.assertTrue(is_content_question("Keywords"))
        self.assertTrue(is_content_question("Which processing packages did you use for your study?"))
        self.assertFalse(is_content_question("Submitter Approval"))
        self.assertFalse(is_content_question("5. Country"))

    def test_filter_content_questions_moves_if_other_after_processing_packages(self) -> None:
        ordered = filter_content_questions_markdown(
            [
                {"question_name": "If other, please specify:", "markdown": "CONN"},
                {"question_name": "Keywords", "markdown": '["MRI"]'},
                {"question_name": "Which processing packages did you use for your study?", "markdown": '["AFNI","Other"]'},
            ]
        )

        self.assertEqual(
            [item["question_name"] for item in ordered],
            [
                "Keywords",
                "Which processing packages did you use for your study?",
                "If other, please specify:",
            ],
        )

    def test_enrich_database_adds_markdown_fields_and_removes_authors(self) -> None:
        base = {
            "event_ids": [1],
            "abstracts": [
                {
                    "id": 1,
                    "title": "Example",
                    "accepted_for": "Poster",
                    "authors": [{"id": 10}],
                    "responses": [
                        {"question_name": "Introduction", "value": "<p>Hello</p>"},
                        {"question_name": "Methods", "value": "<p>Method text</p>"},
                        {"question_name": "Keywords", "value": "[\"A\", \"B\"]"},
                        {"question_name": "Submitter Approval", "value": "yes"},
                    ],
                    "local_assets": [],
                }
            ],
        }
        enriched = enrich_database(base)
        abstract = enriched["abstracts"][0]
        self.assertEqual(sorted(abstract.keys()), [
            "accepted_for",
            "additional_content_questions_markdown",
            "figure_analyses",
            "figure_keywords",
            "id",
            "introduction_markdown",
            "methods_markdown",
        ])
        self.assertEqual(abstract["introduction_markdown"], "Hello")
        self.assertEqual(abstract["methods_markdown"], "Method text")
        self.assertEqual(
            abstract["additional_content_questions_markdown"],
            [{"question_name": "Keywords", "markdown": "[\"A\", \"B\"]"}],
        )

    def test_build_figure_analysis_parser_defaults_to_raw_database(self) -> None:
        parser = build_figure_analysis_parser()
        args = parser.parse_args([])

        self.assertEqual(args.input, "data/abstracts.json")
        self.assertEqual(args.vision_backend, "ollama")
        self.assertEqual(args.save_every, 1)
        self.assertEqual(args.enrich_every, 25)

    def test_resolve_openai_api_key_reads_env_file(self) -> None:
        with TemporaryDirectory() as temp_dir:
            env_path = Path(temp_dir) / ".env"
            env_path.write_text("OPENAI_API_KEY=test-key\n", encoding="utf-8")

            api_key = resolve_openai_api_key(env_path, "OPENAI_API_KEY")

        self.assertEqual(api_key, "test-key")

    def test_analyze_figures_openai_writes_incremental_cache_and_enriched_output(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            image_path = root / "figure.png"
            image_path.write_bytes(b"png-bytes")
            cache_path = root / "image_analyses_openai.json"
            enriched_output = root / "abstracts_enriched_openai.json"
            base_database = {
                "event_ids": [1],
                "abstracts": [
                    {
                        "id": 1,
                        "title": "Example",
                        "accepted_for": "Poster",
                        "responses": [
                            {"question_name": "Introduction", "value": "<p>Hello</p>"},
                            {"question_name": "Methods", "value": "<p>Method text</p>"},
                        ],
                        "local_assets": [
                            {
                                "local_path": str(image_path),
                                "source_question_name": "Methods Figure (Optional)",
                            }
                        ],
                    }
                ],
            }

            with mock.patch(
                "ohbm2026.enrichment.openai_chat_multimodal",
                return_value={
                    "caption_guess": "Figure caption",
                    "rich_markdown": "Figure notes",
                    "ocr_text": "OCR",
                    "keywords": ["MRI", "Flowchart"],
                    "notes": "Notes",
                },
            ) as openai_chat:
                cache = analyze_figures(
                    base_database,
                    cache_path,
                    backend="openai",
                    model="gpt-4.1-mini",
                    openai_api_key="test-key",
                    save_every=1,
                    enriched_output_path=enriched_output,
                    enrich_every=1,
                )

            self.assertEqual(len(cache["analyses"]), 1)
            self.assertTrue(cache_path.exists())
            self.assertTrue(enriched_output.exists())
            saved_cache = load_json(cache_path)
            saved_enriched = load_json(enriched_output)
            analysis_entry = saved_cache["analyses"][str(image_path)]
            self.assertEqual(analysis_entry["backend"], "openai")
            self.assertEqual(analysis_entry["model"], "gpt-4.1-mini")
            self.assertEqual(saved_enriched["abstracts"][0]["figure_keywords"], ["MRI", "Flowchart"])
            self.assertEqual(saved_enriched["abstracts"][0]["figure_analyses"][0]["analysis"]["caption_guess"], "Figure caption")
            openai_chat.assert_called_once()

    def test_analyze_figures_continues_after_openai_error(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            image_one = root / "figure1.png"
            image_two = root / "figure2.png"
            image_one.write_bytes(b"png-bytes-1")
            image_two.write_bytes(b"png-bytes-2")
            cache_path = root / "image_analyses_openai.json"
            base_database = {
                "event_ids": [1],
                "abstracts": [
                    {
                        "id": 1,
                        "title": "Example",
                        "accepted_for": "Poster",
                        "responses": [],
                        "local_assets": [
                            {
                                "local_path": str(image_one),
                                "source_question_name": "Methods Figure (Optional)",
                            },
                            {
                                "local_path": str(image_two),
                                "source_question_name": "Results Figure (Optional)",
                            },
                        ],
                    }
                ],
            }

            with mock.patch(
                "ohbm2026.enrichment.openai_chat_multimodal",
                side_effect=[
                    EnrichmentError("bad json"),
                    {
                        "caption_guess": "Figure caption",
                        "rich_markdown": "Figure notes",
                        "ocr_text": "OCR",
                        "keywords": ["MRI"],
                        "notes": "Notes",
                    },
                ],
            ):
                cache = analyze_figures(
                    base_database,
                    cache_path,
                    backend="openai",
                    model="gpt-4.1-mini",
                    openai_api_key="test-key",
                    save_every=1,
                )

            self.assertEqual(cache["processed_count"], 2)
            self.assertEqual(cache["error_count"], 1)
            self.assertIn("error", cache["analyses"][str(image_one)])
            self.assertEqual(cache["analyses"][str(image_two)]["analysis"]["caption_guess"], "Figure caption")


if __name__ == "__main__":
    unittest.main()
