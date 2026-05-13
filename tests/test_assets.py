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


class TestFetchContentBatchesFigureResolution(unittest.TestCase):
    """T015 / fix-after-Phase-4: when ``assets_dir`` is provided,
    ``fetch_content_batches`` resolves figure URLs inline AND reuses
    on-disk files via ``asset_stem`` matching (zero HTTP for reused
    figures). When ``assets_dir`` is ``None``, figure resolution is
    skipped (the original no-figures path)."""

    def _content_with_figure(self, sid: int, source_url: str) -> dict[str, object]:
        return {
            "id": sid,
            "title": [{"value": f"Abs {sid}"}],
            "accepted_for": {"value": "Poster"},
            "authors": [],
            "responses": [
                {
                    "question": {"question_name": "Methods Figure (Optional)"},
                    "value": source_url,
                },
            ],
            "program_code": f"{sid:04d}",
        }

    def test_figure_download_skipped_when_assets_dir_is_none(self) -> None:
        from ohbm2026 import assets as assets_module

        def fake_fetch_abstract_content(api_key, ids, **kwargs):
            return [
                self._content_with_figure(sid, f"https://example.org/{sid}.png")
                for sid in ids
            ]

        with mock.patch.object(assets_module, "fetch_abstract_content", side_effect=fake_fetch_abstract_content), \
             mock.patch.object(assets_module, "download_asset") as mock_download:
            results = list(
                assets_module.fetch_content_batches(
                    api_key="fake",
                    submission_ids=[1, 2],
                    batch_size=2,
                    on_batch_complete=lambda *a, **kw: None,
                    on_record_state_change=lambda *a, **kw: None,
                )
            )

        mock_download.assert_not_called()
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0]["local_assets"], [])

    def test_figure_download_runs_and_populates_local_assets(self) -> None:
        from ohbm2026 import assets as assets_module
        from ohbm2026.assets import AssetDownload

        def fake_fetch_abstract_content(api_key, ids, **kwargs):
            return [
                self._content_with_figure(sid, f"https://example.org/{sid}.png")
                for sid in ids
            ]

        def fake_download(source_url, destination_dir, abstract_id, cache, existing, **kwargs):
            return AssetDownload(
                source_url=source_url,
                local_path=f"{destination_dir}/{abstract_id}_fake.png",
                content_type="image/png",
                downloaded=True,
                error=None,
            )

        with TemporaryDirectory() as tmp:
            assets_dir = Path(tmp)
            with mock.patch.object(assets_module, "fetch_abstract_content", side_effect=fake_fetch_abstract_content), \
                 mock.patch.object(assets_module, "download_asset", side_effect=fake_download) as mock_download:
                results = list(
                    assets_module.fetch_content_batches(
                        api_key="fake",
                        submission_ids=[1, 2],
                        batch_size=2,
                        on_batch_complete=lambda *a, **kw: None,
                        on_record_state_change=lambda *a, **kw: None,
                        assets_dir=assets_dir,
                    )
                )

        self.assertEqual(mock_download.call_count, 2)
        self.assertEqual(len(results[0]["local_assets"]), 1)
        self.assertTrue(results[0]["local_assets"][0]["downloaded"])

    def test_existing_on_disk_asset_is_reused_without_download_call(self) -> None:
        """Same abstract_id + same source_url → same asset_stem → file
        already on disk → ``download_asset`` reuses it (no new HTTP
        request issued by the real ``download_asset`` function).

        We test the integration through the real ``download_asset``
        path here so the reuse semantics are exercised end to end —
        we just pre-seed the destination directory with a file at the
        expected stem."""
        from ohbm2026 import assets as assets_module
        from ohbm2026.assets import asset_stem

        source_url = "https://example.org/abstract-1.png"
        abstract_id = 1
        stem = asset_stem(abstract_id, source_url)

        def fake_fetch_abstract_content(api_key, ids, **kwargs):
            return [self._content_with_figure(sid, source_url) for sid in ids]

        with TemporaryDirectory() as tmp:
            assets_dir = Path(tmp)
            # Pre-seed an on-disk asset at the expected stem.
            seeded = assets_dir / f"{stem}.png"
            seeded.write_bytes(b"\x89PNG\r\n\x1a\n")

            with mock.patch.object(assets_module, "fetch_abstract_content", side_effect=fake_fetch_abstract_content), \
                 mock.patch.object(assets_module, "urlopen_with_retries") as mock_urlopen:
                results = list(
                    assets_module.fetch_content_batches(
                        api_key="fake",
                        submission_ids=[abstract_id],
                        batch_size=1,
                        on_batch_complete=lambda *a, **kw: None,
                        on_record_state_change=lambda *a, **kw: None,
                        assets_dir=assets_dir,
                    )
                )

        # Real download_asset ran; it found the seeded file and reused
        # it — urlopen_with_retries (the actual network call) MUST NOT
        # have been invoked.
        mock_urlopen.assert_not_called()
        local_assets = results[0]["local_assets"]
        self.assertEqual(len(local_assets), 1)
        self.assertTrue(local_assets[0]["downloaded"])
        self.assertEqual(local_assets[0]["local_path"], str(seeded))


class TestPosterIdPropagation(unittest.TestCase):
    """T009 (FR-020) — `normalize_abstract` MUST rename upstream
    `program_code` to `poster_id` on the normalized record.

    Pinned by the 2026-05-13 introspection probe: the upstream field
    that carries the conference-assigned poster number is
    `submissions.program_code` (String); confirmed live values are
    short numeric strings like "0581"."""

    def test_normalize_abstract_renames_program_code_to_poster_id(self) -> None:
        raw = {
            "id": 1227181,
            "title": [{"value": "Demo"}],
            "accepted_for": {"value": "Poster"},
            "authors": [{"author_order": 1, "id": 7}],
            "responses": [],
            "program_code": "0581",
        }
        normalized = normalize_abstract(raw)

        self.assertEqual(normalized["poster_id"], "0581")
        # The upstream raw key MUST NOT be exposed under both names on
        # the normalized record — one canonical key only.
        self.assertNotIn("program_code", normalized)

    def test_normalize_abstract_carries_null_poster_id_through(self) -> None:
        # Upstream may legitimately not have assigned a program_code
        # yet for a brand-new submission. normalize_abstract MUST NOT
        # crash; it surfaces None.
        raw = {
            "id": 999,
            "title": [{"value": "Demo"}],
            "accepted_for": {"value": "Poster"},
            "authors": [],
            "responses": [],
            "program_code": None,
        }
        normalized = normalize_abstract(raw)
        self.assertIsNone(normalized["poster_id"])


class TestProgramSessionsPropagation(unittest.TestCase):
    """T009 (FR-021) — `normalize_abstract` MUST flatten upstream
    `program_sessions_submissions[]` into a `program_sessions` list on
    the normalized record. Each entry carries per-poster + session-
    level fields.

    Empirical state (2026-05-13): the upstream relationship is empty
    for accepted submissions — OHBM 2026 organizer scheduling has
    not yet been entered. The normalize step MUST therefore tolerate
    both empty input and populated input.
    """

    def test_empty_relationship_yields_empty_program_sessions_list(self) -> None:
        raw = {
            "id": 1227181,
            "title": [{"value": "Demo"}],
            "accepted_for": {"value": "Poster"},
            "authors": [],
            "responses": [],
            "program_code": "0581",
            "program_sessions_submissions": [],
        }
        normalized = normalize_abstract(raw)
        self.assertEqual(normalized["program_sessions"], [])

    def test_populated_relationship_flattens_into_program_sessions_list(self) -> None:
        raw = {
            "id": 1,
            "title": [{"value": "Demo"}],
            "accepted_for": {"value": "Poster"},
            "authors": [],
            "responses": [],
            "program_code": "0001",
            "program_sessions_submissions": [
                {
                    "start_time": "10:00:00",
                    "end_time": "11:00:00",
                    "display_order": 7,
                    "program_session": {
                        "id": 42,
                        "name": "Poster Session 1",
                        "start_time": "09:00:00",
                        "end_time": "12:00:00",
                        "program_date": {"program_date": "2026-06-26"},
                        "program_location": {"name": "Hall A"},
                        "program_type": {"name": "Poster Standby"},
                        "program_track": {"name": "Cognitive"},
                    },
                }
            ],
        }
        normalized = normalize_abstract(raw)

        self.assertEqual(len(normalized["program_sessions"]), 1)
        entry = normalized["program_sessions"][0]
        self.assertEqual(entry["session_id"], 42)
        self.assertEqual(entry["session_name"], "Poster Session 1")
        self.assertEqual(entry["session_type"], "Poster Standby")
        self.assertEqual(entry["session_track"], "Cognitive")
        self.assertEqual(entry["session_date"], "2026-06-26")
        self.assertEqual(entry["session_location"], "Hall A")
        self.assertEqual(entry["session_start_time"], "09:00:00")
        self.assertEqual(entry["session_end_time"], "12:00:00")
        self.assertEqual(entry["standby_start_time"], "10:00:00")
        self.assertEqual(entry["standby_end_time"], "11:00:00")
        self.assertEqual(entry["display_order"], 7)

    def test_null_subfields_in_populated_session_are_preserved_as_none(self) -> None:
        # Upstream may populate the junction row but leave individual
        # sub-fields null (e.g. location not yet decided). normalize
        # MUST carry None through, not crash or fabricate.
        raw = {
            "id": 1,
            "title": [{"value": "Demo"}],
            "accepted_for": {"value": "Poster"},
            "authors": [],
            "responses": [],
            "program_code": "0001",
            "program_sessions_submissions": [
                {
                    "start_time": None,
                    "end_time": None,
                    "display_order": None,
                    "program_session": {
                        "id": 5,
                        "name": None,
                        "start_time": None,
                        "end_time": None,
                        "program_date": None,
                        "program_location": None,
                        "program_type": None,
                        "program_track": None,
                    },
                }
            ],
        }
        normalized = normalize_abstract(raw)
        entry = normalized["program_sessions"][0]
        self.assertEqual(entry["session_id"], 5)
        self.assertIsNone(entry["session_name"])
        self.assertIsNone(entry["session_date"])
        self.assertIsNone(entry["session_location"])
        self.assertIsNone(entry["session_type"])
        self.assertIsNone(entry["standby_start_time"])


if __name__ == "__main__":
    unittest.main()
