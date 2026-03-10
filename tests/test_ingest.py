import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from ohbm2026.assets import (
    asset_stem,
    build_existing_asset_index,
    download_asset,
    extract_external_urls,
    find_existing_asset,
    guess_extension,
    is_image_url_candidate,
    is_target_figure_question,
    is_valid_external_url,
    normalize_abstract,
    refresh_local_assets_from_database,
    stringify_error,
    extract_target_figure_urls,
)
from ohbm2026.graphql_api import chunked, extract_value_field, load_dotenv, timeout_sequence


class IngestHelpersTest(unittest.TestCase):
    def test_load_dotenv_parses_simple_pairs(self) -> None:
        with TemporaryDirectory() as temp_dir:
            env_file = Path(temp_dir) / ".env"
            env_file.write_text(
                "OHBM2026_API=test-key\n# comment\nOTHER=value\n",
                encoding="utf-8",
            )

            parsed = load_dotenv(env_file)

        self.assertEqual(parsed["OHBM2026_API"], "test-key")
        self.assertEqual(parsed["OTHER"], "value")

    def test_extract_external_urls_deduplicates_and_cleans(self) -> None:
        urls = extract_external_urls(
            [
                "See https://example.org/figure.png).",
                'Embedded <img src="https://example.org/figure.png">',
                "Supplemental https://example.org/data.csv",
                "Malformed https://doi.org:10.1038/s41586-020-2649-2",
            ]
        )

        self.assertEqual(
            urls,
            [
                "https://example.org/figure.png",
                "https://example.org/data.csv",
            ],
        )

    def test_normalize_abstract_collects_urls(self) -> None:
        raw = {
            "id": 123,
            "title": [{"value": "A title"}],
            "accepted_for": {"value": "Poster"},
            "authors": [{"author_order": 2, "id": 20}, {"author_order": 1, "id": 10}],
            "responses": [
                {
                    "question": {"question_name": "Methods Figure (Optional)"},
                    "value": "Figure: https://example.org/a.png",
                },
                {"question": {"question_name": "Notes"}, "value": None},
            ],
        }

        normalized = normalize_abstract(raw)

        self.assertEqual(
            normalized["authors"],
            [{"author_order": 1, "id": 10}, {"author_order": 2, "id": 20}],
        )
        self.assertEqual(normalized["external_urls"], ["https://example.org/a.png"])
        self.assertEqual(
            normalized["figure_urls"],
            [{"question_name": "Methods Figure (Optional)", "source_url": "https://example.org/a.png"}],
        )
        self.assertEqual(normalized["local_assets"], [])

    def test_extract_value_field_handles_list_backed_value(self) -> None:
        self.assertEqual(extract_value_field([{"value": "A title"}]), "A title")
        self.assertEqual(extract_value_field({"value": "Poster"}), "Poster")

    def test_guess_extension_prefers_content_type(self) -> None:
        self.assertEqual(guess_extension("https://example.org/noext", "image/png"), ".png")
        self.assertEqual(guess_extension("https://example.org/path/file.jpg", None), ".jpg")

    def test_is_image_url_candidate_uses_suffix_when_present(self) -> None:
        self.assertTrue(is_image_url_candidate("https://example.org/figure.png"))
        self.assertFalse(is_image_url_candidate("https://example.org/paper.pdf"))
        self.assertTrue(is_image_url_candidate("https://example.org/download"))

    def test_is_valid_external_url_rejects_invalid_port(self) -> None:
        self.assertTrue(is_valid_external_url("https://doi.org/10.1038/s41586-020-2649-2"))
        self.assertFalse(is_valid_external_url("https://doi.org:10.1038/s41586-020-2649-2"))

    def test_target_figure_question_matching(self) -> None:
        self.assertTrue(is_target_figure_question("Methods Figure (Optional)"))
        self.assertTrue(is_target_figure_question("Results Figure (Optional)"))
        self.assertFalse(is_target_figure_question("Introduction"))

    def test_extract_target_figure_urls_filters_non_figure_urls(self) -> None:
        responses = [
            {"question_name": "Methods Figure (Optional)", "value": "https://example.org/methods.png"},
            {"question_name": "Results Figure (Optional)", "value": "https://example.org/results.png"},
            {"question_name": "Introduction", "value": "https://example.org/paper.pdf"},
        ]
        self.assertEqual(
            extract_target_figure_urls(responses),
            [
                {"question_name": "Methods Figure (Optional)", "source_url": "https://example.org/methods.png"},
                {"question_name": "Results Figure (Optional)", "source_url": "https://example.org/results.png"},
            ],
        )

    def test_timeout_sequence_doubles_and_caps(self) -> None:
        self.assertEqual(
            timeout_sequence(start_seconds=0.1, limit_seconds=10.0),
            [0.1, 0.2, 0.4, 0.8, 1.6, 3.2, 6.4, 10.0],
        )

    def test_chunked_preserves_order(self) -> None:
        self.assertEqual(chunked([1, 2, 3, 4, 5], 2), [[1, 2], [3, 4], [5]])

    def test_asset_helpers_match_existing_file(self) -> None:
        with TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            stem = asset_stem(123, "https://example.org/figure.png")
            expected = temp_path / f"{stem}.png"
            expected.write_bytes(b"png")
            index = build_existing_asset_index(temp_path)

            self.assertEqual(find_existing_asset(index, 123, "https://example.org/figure.png"), expected)

    def test_stringify_error_normalizes_non_string(self) -> None:
        self.assertEqual(stringify_error(ValueError("bad value")), "bad value")
        self.assertIsNone(stringify_error(None))

    def test_download_asset_can_reuse_only_existing_files(self) -> None:
        with TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            result = download_asset(
                "https://example.org/missing.png",
                temp_path,
                999,
                cache={},
                existing_assets=build_existing_asset_index(temp_path),
                reuse_existing_assets_only=True,
            )

        self.assertFalse(result.downloaded)
        self.assertEqual(result.error, "Missing local asset from previous run")

    def test_refresh_local_assets_prunes_to_figure_questions(self) -> None:
        with TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            database_path = temp_path / "abstracts.json"
            methods_url = "https://example.org/methods.png"
            methods_path = temp_path / f"{asset_stem(123, methods_url)}.png"
            methods_path.write_bytes(b"png")
            database_path.write_text(
                json.dumps(
                    {
                        "abstract_count": 1,
                        "event_ids": [1],
                        "abstracts": [
                            {
                                "id": 123,
                                "responses": [
                                    {"question_name": "Methods Figure (Optional)", "value": methods_url},
                                    {"question_name": "Introduction", "value": "https://example.org/paper.pdf"},
                                ],
                                "local_assets": [
                                    {"source_url": "https://example.org/paper.pdf", "local_path": "/tmp/paper.pdf"}
                                ],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            refreshed = refresh_local_assets_from_database(
                database_path,
                temp_path,
                reuse_existing_assets_only=True,
            )

        self.assertEqual(
            refreshed["abstracts"][0]["local_assets"],
            [
                {
                    "source_url": methods_url,
                    "source_question_name": "Methods Figure (Optional)",
                    "local_path": str(methods_path),
                    "content_type": "image/png",
                    "downloaded": True,
                    "error": None,
                }
            ],
        )


if __name__ == "__main__":
    unittest.main()
