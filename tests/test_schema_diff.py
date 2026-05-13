"""Behavioral tests for `src/ohbm2026/schema_diff.py`.

Stage 1 of the pipeline rewire (per `specs/002-rewire-pipeline/`).
Tests are written first per Principle IV; they MUST fail before
`schema_diff.py` exists. After T013 lands, every test here must
pass without weakening assertions.

Covers, per FR-003 and research.md §5:

  - FieldIndexEntry shape + JSON round-trip
  - flatten_introspection: synthetic introspection → expected
    field_index
  - hash_field_index: deterministic; JSON-whitespace-invariant;
    serialization-order-invariant
  - parse_hard_set_from_queries: the minimal recursive AST walker
    over the live ABSTRACT_IDS_QUERY + ABSTRACT_CONTENTS_QUERY
    bodies (including the new poster-id field per FR-020)
  - collect_soft_contract_fields: consumer-module registration
    model (union of `CONSUMED_ABSTRACT_FIELDS` across modules)
  - compare: HARD / SOFT / INFORMATIONAL classification, with the
    HARD+SOFT overlap case populating `downstream_consumers`
"""

from __future__ import annotations

import json
import textwrap
import types
import unittest


def _introspection_with(fields_by_type: dict[str, list[dict[str, object]]]) -> dict[str, object]:
    """Build a minimal GraphQL introspection payload from a flat dict.

    ``fields_by_type`` maps `type_name` → list of field descriptors,
    each with at least `name` and `type` keys. The returned shape
    matches the `data.__schema` block of a real introspection
    response sufficiently for `flatten_introspection` to consume it.
    """
    types_list = []
    for type_name, fields in fields_by_type.items():
        types_list.append(
            {
                "kind": "OBJECT",
                "name": type_name,
                "fields": [dict(field) for field in fields],
            }
        )
    return {"types": types_list}


def _named_type(name: str) -> dict[str, object]:
    return {"kind": "SCALAR", "name": name, "ofType": None}


def _non_null(inner: dict[str, object]) -> dict[str, object]:
    return {"kind": "NON_NULL", "name": None, "ofType": inner}


def _list_of(inner: dict[str, object]) -> dict[str, object]:
    return {"kind": "LIST", "name": None, "ofType": inner}


class TestFieldIndexEntry(unittest.TestCase):
    def test_dataclass_shape_round_trips_through_json(self) -> None:
        from ohbm2026.schema_diff import FieldIndexEntry

        entry = FieldIndexEntry(
            type_name="Submission",
            field_name="title",
            wrapping_kinds=("NON_NULL",),
            named_type="TitleResponse",
            args_signature="",
        )
        payload = entry.to_dict()

        self.assertEqual(payload["type_name"], "Submission")
        self.assertEqual(payload["field_name"], "title")
        self.assertEqual(payload["wrapping_kinds"], ["NON_NULL"])
        self.assertEqual(payload["named_type"], "TitleResponse")
        self.assertEqual(payload["args_signature"], "")

        restored = FieldIndexEntry.from_dict(payload)
        self.assertEqual(restored, entry)

    def test_entries_are_orderable_by_type_then_field(self) -> None:
        from ohbm2026.schema_diff import FieldIndexEntry

        unsorted = [
            FieldIndexEntry("Z", "b", (), "Int", ""),
            FieldIndexEntry("A", "z", (), "Int", ""),
            FieldIndexEntry("A", "a", (), "Int", ""),
        ]
        ordered = sorted(unsorted, key=lambda e: (e.type_name, e.field_name))
        self.assertEqual([e.type_name for e in ordered], ["A", "A", "Z"])
        self.assertEqual([e.field_name for e in ordered], ["a", "z", "b"])


class TestFlattenIntrospection(unittest.TestCase):
    def test_unwraps_non_null_and_list_into_wrapping_kinds(self) -> None:
        from ohbm2026.schema_diff import flatten_introspection

        # Submission.id : NON_NULL Int
        # Submission.authors : NON_NULL LIST NON_NULL Author
        raw = _introspection_with(
            {
                "Submission": [
                    {"name": "id", "type": _non_null(_named_type("Int")), "args": []},
                    {
                        "name": "authors",
                        "type": _non_null(_list_of(_non_null(_named_type("Author")))),
                        "args": [],
                    },
                ]
            }
        )
        entries = flatten_introspection(raw)
        as_dict = {(e.type_name, e.field_name): e for e in entries}

        self.assertIn(("Submission", "id"), as_dict)
        self.assertEqual(as_dict[("Submission", "id")].wrapping_kinds, ("NON_NULL",))
        self.assertEqual(as_dict[("Submission", "id")].named_type, "Int")

        self.assertEqual(
            as_dict[("Submission", "authors")].wrapping_kinds,
            ("NON_NULL", "LIST", "NON_NULL"),
        )
        self.assertEqual(as_dict[("Submission", "authors")].named_type, "Author")

    def test_output_is_sorted_by_type_then_field(self) -> None:
        from ohbm2026.schema_diff import flatten_introspection

        raw = _introspection_with(
            {
                "Zeta": [
                    {"name": "b", "type": _named_type("Int"), "args": []},
                ],
                "Alpha": [
                    {"name": "z", "type": _named_type("Int"), "args": []},
                    {"name": "a", "type": _named_type("Int"), "args": []},
                ],
            }
        )
        entries = flatten_introspection(raw)
        keys = [(e.type_name, e.field_name) for e in entries]
        self.assertEqual(keys, [("Alpha", "a"), ("Alpha", "z"), ("Zeta", "b")])

    def test_skips_introspection_meta_types(self) -> None:
        # Real introspection responses include __Schema, __Type, etc.
        # Those are GraphQL machinery, not corpus shape.
        from ohbm2026.schema_diff import flatten_introspection

        raw = {
            "types": [
                {
                    "kind": "OBJECT",
                    "name": "__Schema",
                    "fields": [{"name": "queryType", "type": _named_type("__Type"), "args": []}],
                },
                {
                    "kind": "OBJECT",
                    "name": "Submission",
                    "fields": [{"name": "id", "type": _named_type("Int"), "args": []}],
                },
            ]
        }
        entries = flatten_introspection(raw)
        type_names = {e.type_name for e in entries}
        self.assertNotIn("__Schema", type_names)
        self.assertIn("Submission", type_names)


class TestHashFieldIndex(unittest.TestCase):
    def test_is_deterministic_across_calls(self) -> None:
        from ohbm2026.schema_diff import FieldIndexEntry, hash_field_index

        entries = [
            FieldIndexEntry("Submission", "id", ("NON_NULL",), "Int", ""),
            FieldIndexEntry("Submission", "title", (), "TitleResponse", ""),
        ]
        self.assertEqual(hash_field_index(entries), hash_field_index(list(entries)))

    def test_is_invariant_to_input_order(self) -> None:
        from ohbm2026.schema_diff import FieldIndexEntry, hash_field_index

        forward = [
            FieldIndexEntry("Submission", "id", ("NON_NULL",), "Int", ""),
            FieldIndexEntry("Submission", "title", (), "TitleResponse", ""),
        ]
        reverse = list(reversed(forward))
        self.assertEqual(hash_field_index(forward), hash_field_index(reverse))

    def test_changes_when_a_field_changes_named_type(self) -> None:
        from ohbm2026.schema_diff import FieldIndexEntry, hash_field_index

        original = [FieldIndexEntry("Submission", "id", ("NON_NULL",), "Int", "")]
        renamed = [FieldIndexEntry("Submission", "id", ("NON_NULL",), "String", "")]
        self.assertNotEqual(hash_field_index(original), hash_field_index(renamed))


class TestParseHardSetFromQueries(unittest.TestCase):
    def test_picks_up_top_level_query_fields(self) -> None:
        from ohbm2026.schema_diff import parse_hard_set_from_queries

        query = textwrap.dedent(
            """
            query example {
              events {
                id
              }
              submissions(where: {complete: {_eq: true}}) {
                id
              }
            }
            """
        )
        hard = parse_hard_set_from_queries(query)
        # The walker emits (parent-type-name, field-name) pairs from the
        # query's structure. The top-level operation is `Query`, so the
        # outermost fields are owned by Query.
        self.assertIn(("Query", "events"), hard)
        self.assertIn(("Query", "submissions"), hard)

    def test_picks_up_nested_selection_fields(self) -> None:
        from ohbm2026.schema_diff import parse_hard_set_from_queries

        query = textwrap.dedent(
            """
            query example {
              submissions {
                id
                title { value }
                authors {
                  id
                  affiliations { institution }
                }
              }
            }
            """
        )
        hard = parse_hard_set_from_queries(query)
        # Nested fields are recorded as (immediate-parent-field-name,
        # child-field-name) — the parser doesn't have type info, so it
        # uses the parent selection's field as the type bucket.
        self.assertIn(("submissions", "id"), hard)
        self.assertIn(("submissions", "title"), hard)
        self.assertIn(("title", "value"), hard)
        self.assertIn(("submissions", "authors"), hard)
        self.assertIn(("authors", "affiliations"), hard)
        self.assertIn(("affiliations", "institution"), hard)

    def test_unions_across_multiple_query_texts(self) -> None:
        from ohbm2026.schema_diff import parse_hard_set_from_queries

        q1 = "query a { events { id } }"
        q2 = "query b { submissions { id } }"
        hard = parse_hard_set_from_queries(q1, q2)
        self.assertIn(("Query", "events"), hard)
        self.assertIn(("Query", "submissions"), hard)

    def test_ignores_argument_blocks(self) -> None:
        from ohbm2026.schema_diff import parse_hard_set_from_queries

        # Arguments like `where: {complete: {_eq: true}}` MUST NOT be
        # parsed as selection set children.
        query = textwrap.dedent(
            """
            query example {
              submissions(where: {complete: {_eq: true}, accepted_for: {value: {_is_null: false}}}) {
                id
              }
            }
            """
        )
        hard = parse_hard_set_from_queries(query)
        self.assertIn(("Query", "submissions"), hard)
        self.assertIn(("submissions", "id"), hard)
        # _eq and _is_null are argument keys, not GraphQL fields.
        self.assertNotIn(("complete", "_eq"), hard)
        self.assertNotIn(("value", "_is_null"), hard)


class TestCollectSoftContractFields(unittest.TestCase):
    def test_unions_consumed_abstract_fields_across_provided_modules(self) -> None:
        from ohbm2026.schema_diff import collect_soft_contract_fields

        mod_a = types.SimpleNamespace(
            __name__="ohbm2026.fake_a",
            CONSUMED_ABSTRACT_FIELDS=frozenset({("Submission", "title"), ("Submission", "id")}),
        )
        mod_b = types.SimpleNamespace(
            __name__="ohbm2026.fake_b",
            CONSUMED_ABSTRACT_FIELDS=frozenset({("Submission", "title"), ("Author", "id")}),
        )
        soft = collect_soft_contract_fields([mod_a, mod_b])

        self.assertEqual(soft[("Submission", "title")], ["ohbm2026.fake_a", "ohbm2026.fake_b"])
        self.assertEqual(soft[("Submission", "id")], ["ohbm2026.fake_a"])
        self.assertEqual(soft[("Author", "id")], ["ohbm2026.fake_b"])

    def test_modules_without_consumed_abstract_fields_are_skipped(self) -> None:
        from ohbm2026.schema_diff import collect_soft_contract_fields

        mod_a = types.SimpleNamespace(
            __name__="ohbm2026.fake_a",
            CONSUMED_ABSTRACT_FIELDS=frozenset({("Submission", "title")}),
        )
        mod_b = types.SimpleNamespace(__name__="ohbm2026.fake_b")  # no declaration

        soft = collect_soft_contract_fields([mod_a, mod_b])
        self.assertEqual(soft[("Submission", "title")], ["ohbm2026.fake_a"])
        self.assertEqual(len(soft), 1)


class TestCompare(unittest.TestCase):
    def _entry(self, type_name: str, field_name: str, named_type: str = "Int") -> object:
        from ohbm2026.schema_diff import FieldIndexEntry

        return FieldIndexEntry(type_name, field_name, (), named_type, "")

    def test_removed_field_in_hard_set_classifies_as_hard(self) -> None:
        from ohbm2026.schema_diff import compare

        previous = [self._entry("Submission", "id"), self._entry("Submission", "title", "TitleResponse")]
        current = [self._entry("Submission", "id")]
        hard = {("Submission", "id"), ("Submission", "title")}
        soft: dict[tuple[str, str], list[str]] = {}

        diffs = compare(previous, current, hard_set=hard, soft_set=soft)
        title_diff = [d for d in diffs if d.field_name == "title"]
        self.assertEqual(len(title_diff), 1)
        self.assertEqual(title_diff[0].tier, "HARD")
        self.assertEqual(title_diff[0].change_kind, "removed")

    def test_removed_field_only_in_soft_set_classifies_as_soft(self) -> None:
        from ohbm2026.schema_diff import compare

        previous = [self._entry("Submission", "extras", "String")]
        current: list[object] = []
        hard: set[tuple[str, str]] = set()
        soft = {("Submission", "extras"): ["ohbm2026.future_consumer"]}

        diffs = compare(previous, current, hard_set=hard, soft_set=soft)
        self.assertEqual(len(diffs), 1)
        self.assertEqual(diffs[0].tier, "SOFT")
        self.assertEqual(diffs[0].downstream_consumers, ["ohbm2026.future_consumer"])

    def test_removed_field_in_neither_set_classifies_as_informational(self) -> None:
        from ohbm2026.schema_diff import compare

        previous = [self._entry("Submission", "unused", "String")]
        current: list[object] = []
        hard: set[tuple[str, str]] = set()
        soft: dict[tuple[str, str], list[str]] = {}

        diffs = compare(previous, current, hard_set=hard, soft_set=soft)
        self.assertEqual(len(diffs), 1)
        self.assertEqual(diffs[0].tier, "INFORMATIONAL")
        self.assertEqual(diffs[0].downstream_consumers, [])

    def test_hard_takes_precedence_when_field_is_also_in_soft_set(self) -> None:
        from ohbm2026.schema_diff import compare

        # Field is in BOTH sets. Expected: HARD tier; downstream_consumers
        # still populated so operators see both signals (edge case in
        # spec.md).
        previous = [self._entry("Submission", "title", "TitleResponse")]
        current: list[object] = []
        hard = {("Submission", "title")}
        soft = {("Submission", "title"): ["ohbm2026.enrichment"]}

        diffs = compare(previous, current, hard_set=hard, soft_set=soft)
        self.assertEqual(len(diffs), 1)
        self.assertEqual(diffs[0].tier, "HARD")
        self.assertEqual(diffs[0].downstream_consumers, ["ohbm2026.enrichment"])

    def test_type_change_on_hard_field_records_previous_and_current(self) -> None:
        from ohbm2026.schema_diff import compare

        previous = [self._entry("Submission", "id", "Int")]
        current = [self._entry("Submission", "id", "String")]
        hard = {("Submission", "id")}
        soft: dict[tuple[str, str], list[str]] = {}

        diffs = compare(previous, current, hard_set=hard, soft_set=soft)
        self.assertEqual(len(diffs), 1)
        self.assertEqual(diffs[0].change_kind, "type_changed")
        self.assertEqual(diffs[0].tier, "HARD")
        # previous/current MUST carry the FieldIndexEntry-like dict so
        # error messages can quote old shape and new shape.
        self.assertIsNotNone(diffs[0].previous)
        self.assertIsNotNone(diffs[0].current)
        self.assertEqual(diffs[0].previous["named_type"], "Int")
        self.assertEqual(diffs[0].current["named_type"], "String")

    def test_added_field_classified_against_hard_then_soft(self) -> None:
        from ohbm2026.schema_diff import compare

        previous: list[object] = []
        current = [
            self._entry("Submission", "poster_id", "String"),
            self._entry("Submission", "new_other_field", "Int"),
        ]
        hard = {("Submission", "poster_id")}  # newly added to query
        soft: dict[tuple[str, str], list[str]] = {}

        diffs = compare(previous, current, hard_set=hard, soft_set=soft)
        kinds = {(d.tier, d.field_name) for d in diffs}
        self.assertIn(("HARD", "poster_id"), kinds)
        self.assertIn(("INFORMATIONAL", "new_other_field"), kinds)


if __name__ == "__main__":
    unittest.main()
