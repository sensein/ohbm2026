"""Behavioral tests for `src/ohbm2026/fetch_stage.py`.

Stage 1 orchestrator. Tests cover the six contract elements named in
US2 (research.md / docs/per-stage-pattern.md). Per Principle IV these
land before fetch_stage.py exists and MUST initially fail.

This file is the canonical reference for T010 (US3). Test classes
correspond 1:1 to the six contracts.
"""

from __future__ import annotations

import json
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock


def _run_in_tmp_repo() -> TemporaryDirectory:
    """Construct an isolated working directory that satisfies the
    `data/inputs/`, `data/cache/`, `data/primary/` boundary tests."""
    tmp = TemporaryDirectory()
    root = Path(tmp.name)
    for sub in ("data/inputs/assets", "data/cache", "data/primary"):
        (root / sub).mkdir(parents=True, exist_ok=True)
    return tmp


def _fake_introspection() -> dict[str, object]:
    """Matches Hasura naming: GraphQL type name = table name in
    lowercase. Field names match what ABSTRACT_CONTENTS_QUERY asks
    for, so the hard-set extraction's `(parent_field_name,
    child_name)` keys overlap correctly with this introspection's
    `(type_name, field_name)` keys."""
    return {
        "queryType": {"name": "query_root"},
        "types": [
            {
                "kind": "OBJECT",
                "name": "submissions",
                "fields": [
                    {"name": "id", "type": {"kind": "SCALAR", "name": "Int", "ofType": None}, "args": []},
                    {"name": "program_code", "type": {"kind": "SCALAR", "name": "String", "ofType": None}, "args": []},
                    {"name": "title", "type": {"kind": "OBJECT", "name": "title_responses", "ofType": None}, "args": []},
                    {"name": "accepted_for", "type": {"kind": "OBJECT", "name": "submission_acceptance", "ofType": None}, "args": []},
                    {"name": "authors", "type": {"kind": "OBJECT", "name": "authors", "ofType": None}, "args": []},
                    {"name": "responses", "type": {"kind": "OBJECT", "name": "question_responses", "ofType": None}, "args": []},
                    {"name": "program_sessions_submissions", "type": {"kind": "OBJECT", "name": "program_sessions_submissions", "ofType": None}, "args": []},
                ],
            },
        ],
    }


def _fake_submission(sid: int) -> dict[str, object]:
    return {
        "id": sid,
        "title": [{"value": f"Abstract {sid}"}],
        "accepted_for": {"value": "Poster"},
        "authors": [{"author_order": 1, "id": sid * 10}],
        "responses": [],
        "poster_id": f"P-{sid:04d}",
    }


def _fake_author(aid: int) -> dict[str, object]:
    return {
        "id": aid,
        "first_name": f"First{aid}",
        "middle_initial": None,
        "last_name": f"Last{aid}",
        "title": None,
        "degree": "PhD",
        "email": f"a{aid}@example.org",  # to be stripped by normalize_author
        "orcid_id": f"0000-0000-0000-{aid:04d}",
        "presenting": False,
        "submission_id": aid // 10,
        "affiliations": [
            {
                "id": aid * 100,
                "affiliation_order": 1,
                "institution": "Demo University",
                "city": "Boston",
                "state": "MA",
                "country": "USA",
            }
        ],
    }


def _patch_upstream(
    *,
    introspection: dict[str, object] | None = None,
    submission_ids: list[int] | None = None,
    content_factory=_fake_submission,
    withdrawn_submission_ids: list[int] | None = None,
):
    """Context-manager helper: patches every upstream call in
    `ohbm2026.fetch.graphql_api` AND its name-imported reference inside
    `ohbm2026.assets` so fetch_stage.main() can run hermetically.

    Both targets are patched because `assets.py` imports
    `fetch_abstract_content` by name (a local reference); patching
    only the upstream module would leave the local binding active
    and the test would silently hit the live endpoint.
    """
    from ohbm2026 import assets as assets_module
    from ohbm2026.fetch import graphql_api as graphql_api

    introspection = introspection or _fake_introspection()
    submission_ids = submission_ids if submission_ids is not None else [1, 2, 3]

    def content_side_effect(api_key, ids, **kw):
        return [content_factory(sid) for sid in ids]

    def author_side_effect(api_key, ids, **kw):
        return [_fake_author(aid) for aid in ids]

    patches = [
        mock.patch.object(graphql_api, "fetch_schema_introspection", return_value=introspection),
        mock.patch.object(
            graphql_api,
            "fetch_abstract_ids",
            return_value=([1001], list(submission_ids)),
        ),
        mock.patch.object(
            graphql_api,
            "fetch_withdrawn_ids",
            return_value=([1001], list(withdrawn_submission_ids or [])),
        ),
        mock.patch.object(
            graphql_api,
            "fetch_abstract_content",
            side_effect=content_side_effect,
        ),
        mock.patch.object(
            assets_module,
            "fetch_abstract_content",
            side_effect=content_side_effect,
        ),
        mock.patch.object(
            graphql_api,
            "fetch_author_details",
            side_effect=author_side_effect,
        ),
    ]
    return patches


class _StackedPatches:
    def __init__(self, patches):
        self._patches = patches
        self._started: list[object] = []

    def __enter__(self):
        for p in self._patches:
            self._started.append(p.start())
        return self._started

    def __exit__(self, *exc_info):
        for p in reversed(self._patches):
            p.stop()


class InputContractTests(unittest.TestCase):
    """Contract 1: input — consumes OHBM2026_API by NAME only;
    missing → typed error, no upstream call attempted."""

    def test_missing_api_key_exits_non_zero_with_typed_error_message(self) -> None:
        from ohbm2026.fetch import stage as fetch_stage

        with _run_in_tmp_repo() as tmp_name, mock.patch.dict(os.environ, {}, clear=True):
            tmp = Path(tmp_name)
            with mock.patch("ohbm2026.fetch.stage.Path.cwd", return_value=tmp):
                exit_code = fetch_stage.main(["--env-file", str(tmp / ".env-missing")])
        self.assertNotEqual(exit_code, 0)

    def test_env_var_value_never_appears_in_provenance(self) -> None:
        from ohbm2026.fetch import stage as fetch_stage

        secret = "sk-" + "x" * 32
        with _run_in_tmp_repo() as tmp_name, mock.patch.dict(
            os.environ, {"OHBM2026_API": secret}, clear=False
        ), _StackedPatches(_patch_upstream(submission_ids=[1])):
            tmp = Path(tmp_name)
            with mock.patch("ohbm2026.fetch.stage.Path.cwd", return_value=tmp):
                exit_code = fetch_stage.main([])
            self.assertEqual(exit_code, 0)

            provenance_files = list((tmp / "data" / "inputs").glob("abstracts_fetch_provenance__*.json"))
            self.assertEqual(len(provenance_files), 1)
            body = provenance_files[0].read_text(encoding="utf-8")
            self.assertNotIn(secret, body)
            # The NAME should appear (we record it) but not the value.
            self.assertIn("OHBM2026_API", body)


class OutputContractTests(unittest.TestCase):
    """Contract 2: output — corpus, schema artifact, and provenance
    are written at the expected paths; checkpoint is deleted on success."""

    def test_clean_run_writes_all_three_primary_outputs_and_deletes_checkpoint(self) -> None:
        from ohbm2026.fetch import stage as fetch_stage

        with _run_in_tmp_repo() as tmp_name, mock.patch.dict(
            os.environ, {"OHBM2026_API": "fake"}, clear=False
        ), _StackedPatches(_patch_upstream(submission_ids=[1, 2])):
            tmp = Path(tmp_name)
            with mock.patch("ohbm2026.fetch.stage.Path.cwd", return_value=tmp):
                exit_code = fetch_stage.main([])
            self.assertEqual(exit_code, 0)

            corpus = list((tmp / "data" / "primary").glob("abstracts.json"))
            schema = list((tmp / "data" / "inputs").glob("abstracts_graphql_schema__*.json"))
            provenance = list((tmp / "data" / "inputs").glob("abstracts_fetch_provenance__*.json"))
            checkpoint = list((tmp / "data" / "cache" / "fetch_abstracts").glob("checkpoint__*.json"))

            self.assertEqual(len(corpus), 1)
            self.assertEqual(len(schema), 1)
            self.assertEqual(len(provenance), 1)
            self.assertEqual(len(checkpoint), 0, "checkpoint MUST be deleted on success")


class ProvenanceContractTests(unittest.TestCase):
    """Contract 3: provenance — record has the required fields, no
    absolute or ~-prefixed paths, env-var names only."""

    def test_provenance_record_has_required_fields_and_no_absolute_paths(self) -> None:
        from ohbm2026.fetch import stage as fetch_stage

        with _run_in_tmp_repo() as tmp_name, mock.patch.dict(
            os.environ, {"OHBM2026_API": "fake"}, clear=False
        ), _StackedPatches(_patch_upstream(submission_ids=[1])):
            tmp = Path(tmp_name)
            with mock.patch("ohbm2026.fetch.stage.Path.cwd", return_value=tmp):
                exit_code = fetch_stage.main([])
            self.assertEqual(exit_code, 0)

            provenance_path = list((tmp / "data" / "inputs").glob("abstracts_fetch_provenance__*.json"))[0]
            record = json.loads(provenance_path.read_text(encoding="utf-8"))

        for required_field in (
            "provenance_version", "run_id", "state_key", "run_timestamp",
            "code_revision", "command_line", "env_vars_consulted",
            "endpoint_url", "query_count", "request_retry_count",
            "retry_reasons", "abstract_count", "figure_asset_count",
            "figure_failure_count", "schema_artifact_path", "schema_hash",
            "schema_diff_vs_previous", "checkpoint_path",
            "resumed_from_previous_run",
        ):
            self.assertIn(required_field, record, f"missing required field {required_field}")

        for path_field in ("schema_artifact_path",):
            value = record[path_field]
            self.assertFalse(value.startswith("/"), f"{path_field} must be project-relative")
            self.assertFalse(value.startswith("~"), f"{path_field} must not be home-prefixed")
        self.assertEqual(record["env_vars_consulted"], ["OHBM2026_API"])


class ErrorContractTests(unittest.TestCase):
    """Contract 4: errors — HARD drift exits 2 without overwriting
    corpus; semantically empty corpus exits 6 (default policy);
    figure-failure-rate over threshold exits 5."""

    def test_hard_contract_drift_exits_two_without_overwriting_corpus(self) -> None:
        from ohbm2026.fetch import stage as fetch_stage

        with _run_in_tmp_repo() as tmp_name, mock.patch.dict(
            os.environ, {"OHBM2026_API": "fake"}, clear=False
        ):
            tmp = Path(tmp_name)
            corpus_path = tmp / "data" / "primary" / "abstracts.json"
            corpus_path.write_text(
                json.dumps({"abstract_count": 99, "abstracts": []}),
                encoding="utf-8",
            )
            sentinel = corpus_path.read_text(encoding="utf-8")

            # First run: write a schema artifact baseline.
            with mock.patch("ohbm2026.fetch.stage.Path.cwd", return_value=tmp), _StackedPatches(
                _patch_upstream(submission_ids=[1])
            ):
                first = fetch_stage.main([])
            self.assertEqual(first, 0)

            # Mutate the corpus on disk so we can verify the next failed
            # run did NOT touch it.
            corpus_path.write_text(sentinel, encoding="utf-8")

            # Second run: the SAME field set the live query asks for is
            # now missing from upstream — HARD-contract drift.
            broken_intro = {"queryType": {"name": "Query"}, "types": []}
            with mock.patch("ohbm2026.fetch.stage.Path.cwd", return_value=tmp), _StackedPatches(
                _patch_upstream(introspection=broken_intro, submission_ids=[1])
            ):
                second = fetch_stage.main([])
            self.assertEqual(second, 2, "HARD drift MUST exit code 2")
            self.assertEqual(
                corpus_path.read_text(encoding="utf-8"),
                sentinel,
                "corpus snapshot MUST NOT be overwritten when HARD drift detected",
            )

    def test_semantically_empty_corpus_exits_six_by_default(self) -> None:
        from ohbm2026.fetch import stage as fetch_stage

        with _run_in_tmp_repo() as tmp_name, mock.patch.dict(
            os.environ, {"OHBM2026_API": "fake"}, clear=False
        ), _StackedPatches(_patch_upstream(submission_ids=[])):
            tmp = Path(tmp_name)
            with mock.patch("ohbm2026.fetch.stage.Path.cwd", return_value=tmp):
                exit_code = fetch_stage.main([])
        self.assertEqual(exit_code, 6, "semantically empty corpus must exit code 6")

    def test_allow_empty_flag_permits_zero_abstract_corpus(self) -> None:
        from ohbm2026.fetch import stage as fetch_stage

        with _run_in_tmp_repo() as tmp_name, mock.patch.dict(
            os.environ, {"OHBM2026_API": "fake"}, clear=False
        ), _StackedPatches(_patch_upstream(submission_ids=[])):
            tmp = Path(tmp_name)
            with mock.patch("ohbm2026.fetch.stage.Path.cwd", return_value=tmp):
                exit_code = fetch_stage.main(["--allow-empty"])
        self.assertEqual(exit_code, 0)


class ResumabilityContractTests(unittest.TestCase):
    """Contract 5: resume — interrupted run is resumable; resume re-
    fetches only pending records."""

    def test_resume_after_mid_batch_interruption_completes_without_refetching_done_records(self) -> None:
        from ohbm2026.fetch import stage as fetch_stage

        all_ids = [1, 2, 3, 4]
        seen_ids: list[int] = []

        def recording_factory(sid: int) -> dict[str, object]:
            seen_ids.append(sid)
            return _fake_submission(sid)

        with _run_in_tmp_repo() as tmp_name, mock.patch.dict(
            os.environ, {"OHBM2026_API": "fake"}, clear=False
        ):
            tmp = Path(tmp_name)
            # First run: complete normally so we have a schema baseline +
            # know the run's state_key.
            with mock.patch("ohbm2026.fetch.stage.Path.cwd", return_value=tmp), _StackedPatches(
                _patch_upstream(submission_ids=all_ids)
            ):
                first = fetch_stage.main([])
            self.assertEqual(first, 0)

            # Delete the corpus + provenance to simulate a fresh run; keep
            # the schema artifact. Synthesize a checkpoint marking ids 1,2
            # done and ids 3,4 pending.
            (tmp / "data" / "primary" / "abstracts.json").unlink(missing_ok=True)
            for p in (tmp / "data" / "inputs").glob("abstracts_fetch_provenance__*.json"):
                p.unlink()

            schema_path = list((tmp / "data" / "inputs").glob("abstracts_graphql_schema__*.json"))[0]
            schema = json.loads(schema_path.read_text(encoding="utf-8"))
            ckpt_dir = tmp / "data" / "cache" / "fetch_abstracts"
            ckpt_dir.mkdir(parents=True, exist_ok=True)
            ckpt_path = ckpt_dir / f"checkpoint__{schema['state_key']}.json"
            ckpt_path.write_text(
                json.dumps(
                    {
                        "checkpoint_version": "fetch.checkpoint.v1",
                        "state_key": schema["state_key"],
                        "bound_schema_hash": schema["schema_hash"],
                        "started_at": "2026-05-13T00:00:00+00:00",
                        "last_updated_at": "2026-05-13T00:00:00+00:00",
                        "run_id": "00000000-0000-0000-0000-000000000001",
                        "all_submission_ids": all_ids,
                        "batch_size": 2,
                        "completed_submission_ids": [1, 2],
                        "in_flight_batch": None,
                    }
                ),
                encoding="utf-8",
            )

            # Second run (resume): record what upstream IDs were requested
            # via the recording content factory.
            seen_ids.clear()
            with mock.patch("ohbm2026.fetch.stage.Path.cwd", return_value=tmp), _StackedPatches(
                _patch_upstream(submission_ids=all_ids, content_factory=recording_factory)
            ):
                second = fetch_stage.main([])

        self.assertEqual(second, 0)
        # SC-009: the request set on resume MUST be the pending IDs only.
        self.assertEqual(sorted(set(seen_ids)), [3, 4])


class AuthorIngestionTests(unittest.TestCase):
    """FR-023 / FR-024: Stage 1 fetches author details inline and
    writes them to data/primary/authors.json (or authors_withdrawn.json
    for the withdrawn corpus). Email is dropped at normalize time."""

    def test_accepted_run_writes_authors_to_data_primary_authors_json(self) -> None:
        from ohbm2026.fetch import stage as fetch_stage

        with _run_in_tmp_repo() as tmp_name, mock.patch.dict(
            os.environ, {"OHBM2026_API": "fake"}, clear=False
        ), _StackedPatches(_patch_upstream(submission_ids=[1, 2])):
            tmp = Path(tmp_name)
            with mock.patch("ohbm2026.fetch.stage.Path.cwd", return_value=tmp):
                exit_code = fetch_stage.main([])
            self.assertEqual(exit_code, 0)

            authors_file = tmp / "data" / "primary" / "authors.json"
            self.assertTrue(authors_file.exists())
            payload = json.loads(authors_file.read_text(encoding="utf-8"))

            self.assertIn("author_count", payload)
            self.assertIn("authors", payload)
            self.assertEqual(payload["author_count"], 2)
            # Author IDs were derived from the corpus (sid*10 → 10, 20).
            self.assertEqual([a["id"] for a in payload["authors"]], [10, 20])
            # Email MUST NOT appear anywhere in the persisted record.
            self.assertNotIn("email", json.dumps(payload))

    def test_withdrawn_run_writes_authors_to_separate_file(self) -> None:
        from ohbm2026.fetch import stage as fetch_stage

        with _run_in_tmp_repo() as tmp_name, mock.patch.dict(
            os.environ, {"OHBM2026_API": "fake"}, clear=False
        ), _StackedPatches(
            _patch_upstream(submission_ids=[1], withdrawn_submission_ids=[99])
        ):
            tmp = Path(tmp_name)
            with mock.patch("ohbm2026.fetch.stage.Path.cwd", return_value=tmp):
                exit_code = fetch_stage.main(["--corpus-kind", "withdrawn"])
            self.assertEqual(exit_code, 0)

            withdrawn_authors = tmp / "data" / "primary" / "authors_withdrawn.json"
            accepted_authors = tmp / "data" / "primary" / "authors.json"

            self.assertTrue(withdrawn_authors.exists())
            self.assertFalse(
                accepted_authors.exists(),
                "withdrawn-mode MUST NOT write to the accepted authors path",
            )

    def test_provenance_record_includes_authors_path_and_count(self) -> None:
        from ohbm2026.fetch import stage as fetch_stage

        with _run_in_tmp_repo() as tmp_name, mock.patch.dict(
            os.environ, {"OHBM2026_API": "fake"}, clear=False
        ), _StackedPatches(_patch_upstream(submission_ids=[1])):
            tmp = Path(tmp_name)
            with mock.patch("ohbm2026.fetch.stage.Path.cwd", return_value=tmp):
                fetch_stage.main([])

            provenance_path = list((tmp / "data" / "inputs").glob("abstracts_fetch_provenance__*.json"))[0]
            record = json.loads(provenance_path.read_text(encoding="utf-8"))

        self.assertIn("authors_path", record)
        self.assertIn("author_count", record)
        self.assertEqual(record["authors_path"], "data/primary/authors.json")
        self.assertEqual(record["author_count"], 1)
        # Path must be project-relative.
        self.assertFalse(record["authors_path"].startswith("/"))
        self.assertFalse(record["authors_path"].startswith("~"))


class WithdrawnCorpusKindTests(unittest.TestCase):
    """FR-022: --corpus-kind=withdrawn dispatches to fetch_withdrawn_ids
    and writes a separate `data/primary/abstracts_withdrawn.json`. The
    accepted and withdrawn corpora MUST NEVER co-mingle on disk; the
    state-key namespace separates their schema/provenance/checkpoint
    artifacts too."""

    def test_withdrawn_run_writes_separate_corpus_file(self) -> None:
        from ohbm2026.fetch import stage as fetch_stage

        with _run_in_tmp_repo() as tmp_name, mock.patch.dict(
            os.environ, {"OHBM2026_API": "fake"}, clear=False
        ), _StackedPatches(
            _patch_upstream(submission_ids=[10, 20], withdrawn_submission_ids=[99, 88])
        ):
            tmp = Path(tmp_name)
            with mock.patch("ohbm2026.fetch.stage.Path.cwd", return_value=tmp):
                exit_code = fetch_stage.main(["--corpus-kind", "withdrawn"])
            self.assertEqual(exit_code, 0)

            withdrawn_corpus = tmp / "data" / "primary" / "abstracts_withdrawn.json"
            accepted_corpus = tmp / "data" / "primary" / "abstracts.json"

            self.assertTrue(
                withdrawn_corpus.exists(),
                "withdrawn corpus file must be written under data/primary/abstracts_withdrawn.json",
            )
            self.assertFalse(
                accepted_corpus.exists(),
                "withdrawn-mode run MUST NOT write to the accepted corpus path",
            )

            payload = json.loads(withdrawn_corpus.read_text(encoding="utf-8"))
            ids = {a["id"] for a in payload["abstracts"]}
            self.assertEqual(ids, {99, 88}, "withdrawn corpus must contain the withdrawn IDs only")

    def test_accepted_and_withdrawn_have_different_state_keys(self) -> None:
        from ohbm2026.fetch import stage as fetch_stage

        accepted_args = fetch_stage._build_parser().parse_args([])
        withdrawn_args = fetch_stage._build_parser().parse_args(["--corpus-kind", "withdrawn"])

        accepted_key = fetch_stage._compute_state_key(accepted_args)
        withdrawn_key = fetch_stage._compute_state_key(withdrawn_args)

        self.assertNotEqual(
            accepted_key,
            withdrawn_key,
            "accepted and withdrawn must use different state-key namespaces",
        )


class DiscoveryContractTests(unittest.TestCase):
    """Contract 6: discovery — introspection happens before content;
    schema-diff classification runs on every run; checkpoint with
    mismatched bound_schema_hash refuses to resume silently."""

    def test_introspection_call_happens_before_content_calls(self) -> None:
        from ohbm2026 import assets as assets_module
        from ohbm2026.fetch import stage as fetch_stage
        from ohbm2026.fetch import graphql_api as graphql_api

        call_order: list[str] = []

        def intro_recorder(*a, **kw):
            call_order.append("introspection")
            return _fake_introspection()

        def ids_recorder(*a, **kw):
            call_order.append("ids")
            return ([1001], [1, 2])

        def content_recorder(api_key, ids, **kw):
            call_order.append("content")
            return [_fake_submission(sid) for sid in ids]

        def author_recorder(api_key, ids, **kw):
            call_order.append("authors")
            return [_fake_author(aid) for aid in ids]

        with _run_in_tmp_repo() as tmp_name, mock.patch.dict(
            os.environ, {"OHBM2026_API": "fake"}, clear=False
        ), mock.patch.object(graphql_api, "fetch_schema_introspection", side_effect=intro_recorder), \
             mock.patch.object(graphql_api, "fetch_abstract_ids", side_effect=ids_recorder), \
             mock.patch.object(graphql_api, "fetch_abstract_content", side_effect=content_recorder), \
             mock.patch.object(assets_module, "fetch_abstract_content", side_effect=content_recorder), \
             mock.patch.object(graphql_api, "fetch_author_details", side_effect=author_recorder):
            tmp = Path(tmp_name)
            with mock.patch("ohbm2026.fetch.stage.Path.cwd", return_value=tmp):
                exit_code = fetch_stage.main([])
        self.assertEqual(exit_code, 0)
        self.assertEqual(call_order[0], "introspection")
        self.assertIn("content", call_order)
        self.assertLess(call_order.index("introspection"), call_order.index("content"))
        # Authors fetched AFTER content (corpus drives author_id list).
        self.assertIn("authors", call_order)
        self.assertLess(call_order.index("content"), call_order.index("authors"))

    def test_checkpoint_with_mismatched_schema_hash_refuses_to_resume_silently(self) -> None:
        from ohbm2026.fetch import stage as fetch_stage

        with _run_in_tmp_repo() as tmp_name, mock.patch.dict(
            os.environ, {"OHBM2026_API": "fake"}, clear=False
        ):
            tmp = Path(tmp_name)
            # Land a fresh schema artifact + state-key.
            with mock.patch("ohbm2026.fetch.stage.Path.cwd", return_value=tmp), _StackedPatches(
                _patch_upstream(submission_ids=[1])
            ):
                first = fetch_stage.main([])
            self.assertEqual(first, 0)

            schema_path = list((tmp / "data" / "inputs").glob("abstracts_graphql_schema__*.json"))[0]
            schema = json.loads(schema_path.read_text(encoding="utf-8"))
            ckpt_dir = tmp / "data" / "cache" / "fetch_abstracts"
            ckpt_dir.mkdir(parents=True, exist_ok=True)
            ckpt_path = ckpt_dir / f"checkpoint__{schema['state_key']}.json"
            ckpt_path.write_text(
                json.dumps(
                    {
                        "checkpoint_version": "fetch.checkpoint.v1",
                        "state_key": schema["state_key"],
                        "bound_schema_hash": "0" * 64,  # wrong hash
                        "started_at": "2026-05-13T00:00:00+00:00",
                        "last_updated_at": "2026-05-13T00:00:00+00:00",
                        "run_id": "00000000-0000-0000-0000-000000000002",
                        "all_submission_ids": [1],
                        "batch_size": 50,
                        "completed_submission_ids": [],
                        "in_flight_batch": None,
                    }
                ),
                encoding="utf-8",
            )

            # Resume attempt without explicit allow flag: MUST fail.
            (tmp / "data" / "primary" / "abstracts.json").unlink(missing_ok=True)
            with mock.patch("ohbm2026.fetch.stage.Path.cwd", return_value=tmp), _StackedPatches(
                _patch_upstream(submission_ids=[1])
            ):
                second = fetch_stage.main([])

        self.assertEqual(second, 3, "checkpoint hash mismatch must exit code 3")


if __name__ == "__main__":
    unittest.main()
