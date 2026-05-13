import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from ohbm2026.graphql_api import (
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
        from ohbm2026 import graphql_api

        query = getattr(graphql_api, "INTROSPECTION_QUERY", None)
        self.assertIsNotNone(query, "graphql_api must define INTROSPECTION_QUERY")
        # Canonical introspection asks for the entire __schema block.
        self.assertIn("__schema", query)
        self.assertIn("types", query)
        self.assertIn("queryType", query)

    def test_fetch_schema_introspection_returns_data_schema_block(self) -> None:
        from ohbm2026 import graphql_api

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
        from ohbm2026 import graphql_api
        from ohbm2026.graphql_api import GraphQLAPIError

        # urlopen_with_retries already implements the retry loop; if it
        # gives up, it re-raises the underlying error. Simulate that by
        # raising HTTPError 503 from urlopen_with_retries.
        from urllib.error import HTTPError

        boom = HTTPError("url", 503, "Service Unavailable", {}, None)
        with mock.patch.object(graphql_api, "urlopen_with_retries", side_effect=boom), \
             self.assertRaises(GraphQLAPIError):
            graphql_api.fetch_schema_introspection("fake-key")


class TestPosterIdRequested(unittest.TestCase):
    """T008 — the live content query MUST request the upstream poster-
    identifier field (FR-020).

    The exact field name is discovered at implementation time from the
    introspection, so this test asserts the query body contains AT
    LEAST ONE of the candidate names the implementation would pick.
    """

    def test_abstract_contents_query_requests_a_poster_identifier_field(self) -> None:
        from ohbm2026.graphql_api import ABSTRACT_CONTENTS_QUERY

        candidates = ("poster_id", "poster_number", "presentation_id", "submission_number")
        self.assertTrue(
            any(name in ABSTRACT_CONTENTS_QUERY for name in candidates),
            f"ABSTRACT_CONTENTS_QUERY must request a poster-identifier field; "
            f"none of {candidates} were found in the query body.",
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
