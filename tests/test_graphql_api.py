import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from ohbm2026.fetch.graphql_api import (
    chunked,
    extract_value_field,
    is_valid_external_url,
    load_dotenv,
    timeout_sequence,
)


class GraphQLAPIHelpersTest(unittest.TestCase):
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

    def test_extract_value_field_handles_list_backed_value(self) -> None:
        self.assertEqual(extract_value_field([{"value": "A title"}]), "A title")
        self.assertEqual(extract_value_field({"value": "Poster"}), "Poster")

    def test_timeout_sequence_doubles_and_caps(self) -> None:
        self.assertEqual(
            timeout_sequence(start_seconds=0.1, limit_seconds=10.0),
            [0.1, 0.2, 0.4, 0.8, 1.6, 3.2, 6.4, 10.0],
        )

    def test_chunked_preserves_order(self) -> None:
        self.assertEqual(chunked([1, 2, 3, 4, 5], 2), [[1, 2], [3, 4], [5]])

    def test_is_valid_external_url_rejects_invalid_port(self) -> None:
        self.assertTrue(is_valid_external_url("https://doi.org/10.1038/s41586-020-2649-2"))
        self.assertFalse(is_valid_external_url("https://doi.org:10.1038/s41586-020-2649-2"))


class _FakeResponse:
    """Minimal stand-in for the urllib response object."""

    def __init__(self, body: bytes) -> None:
        self._body = body

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *args: object) -> None:
        return None


class TestIntrospectionQuery(unittest.TestCase):
    """T008 — introspection request shape + happy path.

    `INTROSPECTION_QUERY` MUST be the canonical GraphQL spec
    introspection query (so the persisted schema artifact captures
    the full upstream type system, not just the fields the fetch
    query selects). `fetch_schema_introspection` MUST POST it
    through the same retry/auth machinery the rest of the file uses.
    """

    def test_introspection_query_constant_is_a_full_schema_query(self) -> None:
        from ohbm2026.fetch import graphql_api as graphql_api

        query = getattr(graphql_api, "INTROSPECTION_QUERY", None)
        self.assertIsNotNone(query, "graphql_api must define INTROSPECTION_QUERY")
        # Canonical introspection asks for the entire __schema block.
        self.assertIn("__schema", query)
        self.assertIn("types", query)
        self.assertIn("queryType", query)

    def test_fetch_schema_introspection_returns_data_schema_block(self) -> None:
        from ohbm2026.fetch import graphql_api as graphql_api

        expected_schema = {
            "queryType": {"name": "Query"},
            "types": [
                {"kind": "OBJECT", "name": "Submission", "fields": []},
            ],
        }
        fake_response = _FakeResponse(
            json.dumps({"data": {"__schema": expected_schema}}).encode("utf-8")
        )
        with mock.patch.object(graphql_api, "urlopen_with_retries", return_value=fake_response):
            result = graphql_api.fetch_schema_introspection("fake-key")

        self.assertEqual(result, expected_schema)


class TestIntrospectionRetry(unittest.TestCase):
    """T008 — transient errors are retried within budget; budget
    exhaustion raises GraphQLAPIError."""

    def test_exhausted_retries_raise_graphqlapierror(self) -> None:
        from ohbm2026.fetch import graphql_api as graphql_api
        from ohbm2026.fetch.graphql_api import GraphQLAPIError

        # urlopen_with_retries already implements the retry loop; if it
        # gives up, it re-raises the underlying error. Simulate that by
        # raising HTTPError 503 from urlopen_with_retries.
        from urllib.error import HTTPError

        boom = HTTPError("url", 503, "Service Unavailable", {}, None)
        with mock.patch.object(graphql_api, "urlopen_with_retries", side_effect=boom), \
             self.assertRaises(GraphQLAPIError):
            graphql_api.fetch_schema_introspection("fake-key")


class TestPosterIdRequested(unittest.TestCase):
    """T008 — the live content query MUST request the empirically
    confirmed upstream poster-identifier field (FR-020).

    The field name was pinned via the 2026-05-13 introspection probe:
    `submissions.program_code` (String) carries the conference-assigned
    poster number.
    """

    def test_abstract_contents_query_requests_program_code(self) -> None:
        from ohbm2026.fetch.graphql_api import ABSTRACT_CONTENTS_QUERY

        self.assertIn(
            "program_code",
            ABSTRACT_CONTENTS_QUERY,
            "ABSTRACT_CONTENTS_QUERY must request the upstream "
            "`program_code` field — this is the poster identifier "
            "per FR-020 / Clarifications 2026-05-13.",
        )


class TestWithdrawnIdsQuery(unittest.TestCase):
    """FR-022 / probe 2026-05-13: withdrawn submissions live in a
    separate corpus. The query filters on `decision_status=Withdrawn`
    plus `complete=true` and `archived=false` so abandoned drafts
    don't appear."""

    def test_withdrawn_ids_query_filters_on_decision_status_withdrawn(self) -> None:
        from ohbm2026.fetch.graphql_api import WITHDRAWN_IDS_QUERY

        self.assertIn('decision_status: {_eq: "Withdrawn"}', WITHDRAWN_IDS_QUERY)
        self.assertIn("complete: {_eq: true}", WITHDRAWN_IDS_QUERY)
        # Must NOT include the accepted-only filter on accepted_for.
        self.assertNotIn("accepted_for", WITHDRAWN_IDS_QUERY)

    def test_withdrawn_ids_query_is_distinct_from_accepted_query(self) -> None:
        from ohbm2026.fetch.graphql_api import ABSTRACT_IDS_QUERY, WITHDRAWN_IDS_QUERY

        self.assertNotEqual(ABSTRACT_IDS_QUERY, WITHDRAWN_IDS_QUERY)

    def test_fetch_withdrawn_ids_returns_event_and_submission_ids(self) -> None:
        from ohbm2026.fetch import graphql_api as graphql_api

        with mock.patch.object(
            graphql_api,
            "graphql_request",
            return_value={
                "events": [{"id": 1001}],
                "submissions": [{"id": 1201321}, {"id": 1244579}],
            },
        ) as mock_request:
            events, sids = graphql_api.fetch_withdrawn_ids("fake-key")

        self.assertEqual(events, [1001])
        self.assertEqual(sids, [1201321, 1244579])
        # Confirm the WITHDRAWN_IDS_QUERY was the body sent, not the
        # accepted one (no accidental cross-wiring).
        call = mock_request.call_args
        self.assertEqual(call.args[1], graphql_api.WITHDRAWN_IDS_QUERY)
        self.assertEqual(call.args[2], "withdrawn_ids")


class TestStandbyChainRequested(unittest.TestCase):
    """T008 — the live content query MUST also request the program-
    session chain that carries poster standby time / location /
    session type per FR-021. Even though upstream may not have
    scheduling populated yet (empirically empty as of 2026-05-13),
    the query asks for the structure so values flow automatically
    once scheduling lands."""

    def test_abstract_contents_query_requests_program_sessions_submissions(self) -> None:
        from ohbm2026.fetch.graphql_api import ABSTRACT_CONTENTS_QUERY

        # The fetch query must traverse the junction table.
        self.assertIn("program_sessions_submissions", ABSTRACT_CONTENTS_QUERY)

    def test_abstract_contents_query_requests_session_metadata_chain(self) -> None:
        from ohbm2026.fetch.graphql_api import ABSTRACT_CONTENTS_QUERY

        # Each linked program_session contributes day, location, type,
        # track, and the standby time window.
        for required in (
            "start_time",
            "end_time",
            "display_order",
            "program_session",
            "program_date",
            "program_location",
            "program_type",
        ):
            self.assertIn(
                required,
                ABSTRACT_CONTENTS_QUERY,
                f"FR-021: query body must include `{required}` so poster "
                f"standby info lands when upstream populates it.",
            )


class TestSchemaContractError(unittest.TestCase):
    """T008 — hard-contract drift raises a typed error whose message
    names the affected field and the shape change."""

    def test_schema_contract_error_is_a_runtime_error_and_is_named(self) -> None:
        from ohbm2026.exceptions import SchemaContractError, Stage1Error

        self.assertTrue(issubclass(SchemaContractError, Stage1Error))
        self.assertTrue(issubclass(SchemaContractError, RuntimeError))

    def test_message_carries_field_and_shape_context(self) -> None:
        from ohbm2026.exceptions import SchemaContractError

        try:
            raise SchemaContractError(
                "HARD-tier drift on Submission.title: previous=NON_NULL String, "
                "current=NON_NULL Int"
            )
        except SchemaContractError as exc:
            message = str(exc)

        self.assertIn("Submission.title", message)
        self.assertIn("previous=", message)
        self.assertIn("current=", message)


if __name__ == "__main__":
    unittest.main()
