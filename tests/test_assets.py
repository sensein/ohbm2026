import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from ohbm2026 import artifacts
from ohbm2026.assets import (
    asset_stem,
    build_database,
    build_parser,
    build_existing_asset_index,
    download_asset,
    extract_external_urls,
    extract_target_figure_urls,
    find_existing_asset,
    guess_extension,
    is_image_url_candidate,
    is_target_figure_question,
    normalize_abstract,
    refresh_local_assets_from_database,
    stringify_error,
)


class AssetHelpersTest(unittest.TestCase):
    def test_build_parser_defaults_include_input_snapshot_dir(self) -> None:
        args = build_parser().parse_args([])

        self.assertEqual(args.output, str(artifacts.PRIMARY_ABSTRACTS_PATH))
        self.assertEqual(args.input_snapshot_dir, str(artifacts.INPUTS_ROOT))
        self.assertEqual(args.assets_dir, str(artifacts.INPUT_ASSETS_ROOT))

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

    def test_guess_extension_prefers_content_type(self) -> None:
        self.assertEqual(guess_extension("https://example.org/noext", "image/png"), ".png")
        self.assertEqual(guess_extension("https://example.org/path/file.jpg", None), ".jpg")

    def test_is_image_url_candidate_uses_suffix_when_present(self) -> None:
        self.assertTrue(is_image_url_candidate("https://example.org/figure.png"))
        self.assertFalse(is_image_url_candidate("https://example.org/paper.pdf"))
        self.assertTrue(is_image_url_candidate("https://example.org/download"))

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

    def test_build_database_writes_graphql_input_snapshot(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            output_path = root / "abstracts.json"
            assets_dir = root / "assets"
            snapshot_dir = root / "inputs"

            with (
                mock.patch("ohbm2026.assets.fetch_abstract_ids", return_value=([1], [123])),
                mock.patch(
                    "ohbm2026.assets.fetch_abstract_content",
                    return_value=[
                        {
                            "id": 123,
                            "title": [{"value": "Example"}],
                            "accepted_for": {"value": "Poster"},
                            "authors": [],
                            "responses": [],
                        }
                    ],
                ),
            ):
                database = build_database(
                    "test-key",
                    output_path,
                    assets_dir,
                    input_snapshot_dir=snapshot_dir,
                )

            snapshot_path = Path(database["input_snapshot"])
            self.assertTrue(snapshot_path.exists())
            self.assertEqual(snapshot_path.parent, snapshot_dir)
            self.assertEqual(snapshot_path.name.split("__", 1)[0], "abstracts_graphql")
            snapshot_payload = json.loads(snapshot_path.read_text(encoding="utf-8"))

        self.assertEqual(snapshot_payload["abstract_count"], 1)
        self.assertEqual(snapshot_payload["abstracts"][0]["id"], 123)


class TestBatchedFetchHooks(unittest.TestCase):
    """T009 — `fetch_content_batches` MUST expose callback hooks for
    Stage 1's checkpoint lifecycle: one fired per record state change,
    one fired when a whole batch finishes."""

    def _content_payload(self, sid: int) -> dict[str, object]:
        return {
            "id": sid,
            "title": [{"value": f"Title {sid}"}],
            "accepted_for": {"value": "Poster"},
            "authors": [{"author_order": 1, "id": sid * 10}],
            "responses": [],
            "poster_id": f"P-{sid}",
        }

    def test_on_batch_complete_fires_once_per_batch(self) -> None:
        from ohbm2026 import assets as assets_module

        captured_batches: list[list[int]] = []

        def on_batch_complete(submission_ids: list[int]) -> None:
            captured_batches.append(list(submission_ids))

        def fake_fetch_abstract_content(api_key, submission_ids, **kwargs):
            return [self._content_payload(sid) for sid in submission_ids]

        with mock.patch.object(assets_module, "fetch_abstract_content", side_effect=fake_fetch_abstract_content):
            results = list(
                assets_module.fetch_content_batches(
                    api_key="fake",
                    submission_ids=[1, 2, 3, 4, 5],
                    batch_size=2,
                    on_batch_complete=on_batch_complete,
                    on_record_state_change=lambda *_args, **_kwargs: None,
                )
            )

        # 5 IDs / 2 per batch → 3 batches: [1,2], [3,4], [5]
        self.assertEqual(captured_batches, [[1, 2], [3, 4], [5]])
        self.assertEqual(len(results), 5)
        self.assertEqual([r["id"] for r in results], [1, 2, 3, 4, 5])

    def test_on_record_state_change_fires_for_every_record(self) -> None:
        from ohbm2026 import assets as assets_module

        seen: list[tuple[int, str]] = []

        def on_record_state_change(sid: int, state: str) -> None:
            seen.append((sid, state))

        def fake_fetch_abstract_content(api_key, submission_ids, **kwargs):
            return [self._content_payload(sid) for sid in submission_ids]

        with mock.patch.object(assets_module, "fetch_abstract_content", side_effect=fake_fetch_abstract_content):
            list(
                assets_module.fetch_content_batches(
                    api_key="fake",
                    submission_ids=[10, 20],
                    batch_size=2,
                    on_batch_complete=lambda *_args, **_kwargs: None,
                    on_record_state_change=on_record_state_change,
                )
            )

        sids_seen = [sid for sid, _ in seen]
        self.assertIn(10, sids_seen)
        self.assertIn(20, sids_seen)
        # Every record MUST end in a terminal state (done or
        # failed-retryable) — never strictly "pending" at run end.
        last_state_per_sid = {sid: state for sid, state in seen}
        for sid in (10, 20):
            self.assertIn(last_state_per_sid[sid], {"done", "failed-retryable"})


class TestPerRecordStateTransitions(unittest.TestCase):
    """T009 — state machine for per-record progress within a batch.

    Legal sequence per data-model.md:
        pending → corpus_fetched → figures_in_progress → done
                                                       → failed-retryable
                                ↘ done (when abstract has zero figures)
    Backwards transitions MUST be rejected.
    """

    def test_pending_can_advance_to_corpus_fetched(self) -> None:
        from ohbm2026.assets import advance_record_state

        self.assertEqual(advance_record_state("pending", "corpus_fetched"), "corpus_fetched")

    def test_corpus_fetched_can_advance_to_figures_in_progress(self) -> None:
        from ohbm2026.assets import advance_record_state

        self.assertEqual(
            advance_record_state("corpus_fetched", "figures_in_progress"),
            "figures_in_progress",
        )

    def test_corpus_fetched_can_advance_directly_to_done_when_no_figures(self) -> None:
        from ohbm2026.assets import advance_record_state

        self.assertEqual(advance_record_state("corpus_fetched", "done"), "done")

    def test_figures_in_progress_can_advance_to_done_or_failed_retryable(self) -> None:
        from ohbm2026.assets import advance_record_state

        self.assertEqual(advance_record_state("figures_in_progress", "done"), "done")
        self.assertEqual(
            advance_record_state("figures_in_progress", "failed-retryable"),
            "failed-retryable",
        )

    def test_backwards_transition_raises(self) -> None:
        from ohbm2026.assets import advance_record_state

        with self.assertRaises(ValueError):
            advance_record_state("done", "pending")
        with self.assertRaises(ValueError):
            advance_record_state("corpus_fetched", "pending")
        with self.assertRaises(ValueError):
            advance_record_state("figures_in_progress", "corpus_fetched")


class TestPosterIdPropagation(unittest.TestCase):
    """T009 (FR-020) — normalize_abstract MUST surface the upstream
    poster identifier as `poster_id` on the normalized record. If
    upstream does not include any poster-identifier-shaped field,
    the function MUST surface it loudly rather than fabricating one."""

    def test_normalize_abstract_propagates_poster_id_when_present(self) -> None:
        raw = {
            "id": 42,
            "title": [{"value": "Demo"}],
            "accepted_for": {"value": "Poster"},
            "authors": [{"author_order": 1, "id": 7}],
            "responses": [],
            "poster_id": "P-042",
        }
        normalized = normalize_abstract(raw)

        self.assertEqual(normalized["poster_id"], "P-042")

    def test_normalize_abstract_passes_through_alternative_poster_field_names(self) -> None:
        # The implementation discovers the upstream field name from
        # introspection at fetch time, so multiple input shapes can
        # land in the normalized record. Whatever the discovered key
        # was, normalize_abstract must expose it as `poster_id`.
        for upstream_key in ("poster_id", "poster_number", "presentation_id"):
            with self.subTest(upstream_key=upstream_key):
                raw = {
                    "id": 1,
                    "title": [{"value": "X"}],
                    "accepted_for": {"value": "Poster"},
                    "authors": [],
                    "responses": [],
                    upstream_key: "P-1",
                }
                normalized = normalize_abstract(raw)
                self.assertEqual(normalized["poster_id"], "P-1")


if __name__ == "__main__":
    unittest.main()
