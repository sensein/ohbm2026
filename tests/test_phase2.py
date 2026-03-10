import unittest

from ohbm2026.enrichment import (
    build_sections_markdown,
    enrich_database,
    html_to_markdown,
    parse_jsonish_content,
    question_to_section,
    render_abstract_markdown,
)


class Phase2HelpersTest(unittest.TestCase):
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

    def test_enrich_database_adds_embedding_text_and_resolved_authors(self) -> None:
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
                        {"question_name": "Keywords", "value": "[\"A\", \"B\"]"},
                    ],
                    "local_assets": [],
                }
            ],
        }
        authors = {"authors": [{"id": 10, "first_name": "Ada", "last_name": "Lovelace"}]}
        enriched = enrich_database(base, authors)
        abstract = enriched["abstracts"][0]
        self.assertEqual(abstract["authors_resolved"][0]["first_name"], "Ada")
        self.assertIn("Introduction:\nHello", abstract["embedding_text"])
        self.assertEqual(abstract["generated_keywords"], ["A", "B"])


if __name__ == "__main__":
    unittest.main()
