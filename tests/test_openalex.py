import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from ohbm2026.openalex import (
    OPENAI_RESPONSES_API,
    OpenAlexError,
    add_query_parameter,
    build_reference_record,
    build_reference_key,
    build_reference_metadata_payload,
    collect_reference_cache,
    extract_dois,
    extract_pmid,
    extract_reference_entries,
    extract_reference_year,
    failed_reference_split_ids,
    get_openalex_api_key,
    guess_reference_title,
    merge_reference_metadata_payloads,
    normalize_doi,
    normalize_openalex_work,
    openai_reference_split_request,
    openalex_request,
    repair_failed_reference_splits,
    resolve_reference_cache_doi_discovery,
    search_crossref_doi_by_title,
    search_semantic_scholar_doi_by_reference,
    search_semantic_scholar_doi_by_title,
    split_reference_markdown,
    title_similarity,
    validate_reference_candidate_metadata,
    validate_reference_split_candidates,
    validate_reference_split_structured_candidates,
)


class OpenAlexHelpersTest(unittest.TestCase):
    def tearDown(self) -> None:
        get_openalex_api_key.cache_clear()

    def test_extract_reference_entries_splits_html_list(self) -> None:
        html = "<ol><li>Smith A. Interesting title. Journal. 2024.</li><li>Jones B. Another title. Journal. 2023.</li></ol>"

        entries = extract_reference_entries(html)

        self.assertEqual(
            entries,
            [
                "Smith A. Interesting title. Journal. 2024.",
                "Jones B. Another title. Journal. 2023.",
            ],
        )

    def test_extract_reference_entries_uses_llm_split_for_concatenated_block(self) -> None:
        raw = "Smith A. Interesting title. Journal. 2024. Jones B. Another title. Journal. 2023."

        with patch(
            "ohbm2026.openalex.llm_reference_split_request",
            return_value=[
                {
                    "reference": "Smith A. Interesting title. Journal. 2024.",
                    "title": "Interesting title",
                    "doi": None,
                },
                {
                    "reference": "Jones B. Another title. Journal. 2023.",
                    "title": "Another title",
                    "doi": None,
                },
            ],
        ):
            entries = extract_reference_entries(raw, use_llm_reference_splitting=True)

        self.assertEqual(
            entries,
            [
                "Smith A. Interesting title. Journal. 2024.",
                "Jones B. Another title. Journal. 2023.",
            ],
        )

    def test_extract_reference_entries_falls_back_when_llm_split_is_not_lexical(self) -> None:
        raw = "Smith A. Interesting title. Journal. 2024. Jones B. Another title. Journal. 2023."

        with patch(
            "ohbm2026.openalex.llm_reference_split_request",
            return_value=[
                {"reference": "Invented reference one", "title": "Invented one", "doi": None},
                {"reference": "Invented reference two", "title": "Invented two", "doi": None},
            ],
        ):
            entries = extract_reference_entries(raw, use_llm_reference_splitting=True)

        self.assertEqual(entries, [raw])

    def test_normalize_doi_strips_prefix_and_punctuation(self) -> None:
        self.assertEqual(
            normalize_doi("https://doi.org/10.1038/s42256-023-00702-9."),
            "10.1038/s42256-023-00702-9",
        )
        self.assertEqual(
            normalize_doi("10.1097/wco.0000000000000829.PMID:12345678"),
            "10.1097/wco.0000000000000829",
        )

    def test_extract_dois_and_pmid(self) -> None:
        reference = "D'Sa K. Prediction. Nature. 2023. doi:https://doi.org/10.1038/s42256-023-00702-9 PMID: 12345678"

        self.assertEqual(extract_dois(reference), ["10.1038/s42256-023-00702-9"])
        self.assertEqual(extract_pmid(reference), "12345678")

    def test_guess_reference_title_prefers_second_sentence(self) -> None:
        reference = "Ashina M, Terwindt GM. Migraine: disease characterisation, biomarkers, and precision medicine. The Lancet. 2021;397(10283):1496-1504."

        self.assertEqual(
            guess_reference_title(reference),
            "Migraine: disease characterisation, biomarkers, and precision medicine",
        )

    def test_extract_reference_year_reads_four_digit_year(self) -> None:
        self.assertEqual(extract_reference_year("Example title. Journal. 2021;10(2):1-4."), 2021)

    def test_validate_reference_split_candidates_requires_lexical_match(self) -> None:
        self.assertTrue(
            validate_reference_split_candidates(
                "Smith A. Interesting title. Journal. 2024. Jones B. Another title. Journal. 2023.",
                [
                    "Smith A. Interesting title. Journal. 2024.",
                    "Jones B. Another title. Journal. 2023.",
                ],
            )
        )
        self.assertFalse(
            validate_reference_split_candidates(
                "Smith A. Interesting title. Journal. 2024. Jones B. Another title. Journal. 2023.",
                ["Completely different reference"],
            )
        )

    def test_validate_reference_candidate_metadata_requires_title_and_doi_to_be_lexical(self) -> None:
        self.assertTrue(
            validate_reference_candidate_metadata(
                {
                    "reference": "Smith A. Interesting title. Journal. 2024. doi:10.1000/abc",
                    "title": "Interesting title",
                    "doi": "10.1000/abc",
                }
            )
        )
        self.assertFalse(
            validate_reference_candidate_metadata(
                {
                    "reference": "Smith A. Interesting title. Journal. 2024.",
                    "title": "Different title",
                    "doi": None,
                }
            )
        )
        self.assertFalse(
            validate_reference_candidate_metadata(
                {
                    "reference": "Smith A. Interesting title. Journal. 2024.",
                    "title": "Interesting title",
                    "doi": "10.1/not-in-reference",
                }
            )
        )

    def test_validate_reference_split_structured_candidates_requires_source_coverage(self) -> None:
        self.assertTrue(
            validate_reference_split_structured_candidates(
                "Smith A. Interesting title. Journal. 2024. Jones B. Another title. Journal. 2023.",
                [
                    {"reference": "Smith A. Interesting title. Journal. 2024.", "title": "Interesting title", "doi": None},
                    {"reference": "Jones B. Another title. Journal. 2023.", "title": "Another title", "doi": None},
                ],
            )
        )
        self.assertFalse(
            validate_reference_split_structured_candidates(
                "Smith A. Interesting title. Journal. 2024. Jones B. Another title. Journal. 2023.",
                [
                    {"reference": "Smith A. Interesting title. Journal. 2024.", "title": "Interesting title", "doi": None},
                    {"reference": "Different text", "title": "Different text", "doi": None},
                ],
            )
        )

    def test_build_reference_key_prefers_doi_then_pmid(self) -> None:
        self.assertEqual(build_reference_key("x", doi="10.1/abc", pmid="123"), "doi:10.1/abc")
        self.assertEqual(build_reference_key("x", doi=None, pmid="123"), "pmid:123")
        self.assertTrue(build_reference_key("x").startswith("text:"))

    def test_build_reference_record_prefers_lexical_title_and_doi_overrides(self) -> None:
        reference = build_reference_record(
            "Smith A. Interesting title. Journal. 2024. doi:10.1000/abc",
            title_guess_override="Interesting title",
            doi_override="10.1000/abc",
        )

        self.assertEqual(reference["title_guess"], "Interesting title")
        self.assertEqual(reference["doi"], "10.1000/abc")

    def test_build_reference_record_ignores_non_lexical_title_override(self) -> None:
        reference = build_reference_record(
            "Smith A. Interesting title. Journal. 2024.",
            title_guess_override="Completely different title",
        )

        self.assertNotEqual(reference["title_guess"], "Completely different title")

    def test_title_similarity_recognizes_close_titles(self) -> None:
        score = title_similarity(
            "Migraine disease characterisation biomarkers and precision medicine",
            "Migraine: disease characterisation, biomarkers, and precision medicine",
        )
        self.assertGreater(score, 0.9)

    def test_normalize_openalex_work_extracts_needed_fields(self) -> None:
        work = {
            "id": "https://openalex.org/W123",
            "doi": "https://doi.org/10.1000/test",
            "ids": {"pmid": "https://pubmed.ncbi.nlm.nih.gov/12345678/"},
            "display_name": "Example review",
            "publication_year": 2024,
            "publication_date": "2024-01-01",
            "primary_location": {"source": {"display_name": "NeuroImage"}},
            "type": "review",
            "type_crossref": "review-article",
            "cited_by_count": 42,
            "referenced_works": ["https://openalex.org/W1"],
            "referenced_works_count": 1,
        }

        normalized = normalize_openalex_work(work)

        self.assertEqual(normalized["openalex_id"], "https://openalex.org/W123")
        self.assertEqual(normalized["doi"], "10.1000/test")
        self.assertEqual(normalized["pmid"], "12345678")
        self.assertTrue(normalized["is_review"])
        self.assertEqual(normalized["journal"], "NeuroImage")

    def test_add_query_parameter_preserves_existing_query(self) -> None:
        url = add_query_parameter("https://api.openalex.org/works?per-page=5", "api_key", "secret")

        self.assertEqual(url, "https://api.openalex.org/works?per-page=5&api_key=secret")

    @patch.dict("os.environ", {"OPENALEX_API": "secret-key"}, clear=False)
    def test_openalex_request_appends_api_key_from_environment(self) -> None:
        class DummyResponse:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self) -> bytes:
                return b'{"results": []}'

        captured: dict[str, str] = {}

        def fake_urlopen(request):
            captured["url"] = request.full_url
            return DummyResponse()

        with patch("ohbm2026.openalex.urlopen_with_retries", side_effect=fake_urlopen):
            parsed = openalex_request("https://api.openalex.org/works?per-page=1")

        self.assertEqual(parsed, {"results": []})
        self.assertEqual(
            captured["url"],
            "https://api.openalex.org/works?per-page=1&api_key=secret-key",
        )

    def test_collect_reference_cache_recomputes_counts_from_input(self) -> None:
        with TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "reference_metadata.json"
            output_path.write_text(
                """
                {
                  "references": [
                    {
                      "reference_key": "doi:10.1000/test",
                      "raw_text": "Smith A. Example title. doi:10.1000/test",
                      "doi": "10.1000/test",
                      "matched": true,
                      "match_method": "doi",
                      "openalex": {"openalex_id": "https://openalex.org/W1"},
                      "source_count": 7,
                      "raw_text_examples": ["old"],
                      "doi_lookup_completed": true,
                      "pmid_lookup_completed": true,
                      "title_lookup_completed": false
                    }
                  ]
                }
                """,
                encoding="utf-8",
            )
            database = {
                "abstracts": [
                    {
                        "id": 1,
                        "responses": [
                            {
                                "question_name": "References/Citations",
                                "value": "<ol><li>Smith A. Example title. doi:10.1000/test</li></ol>",
                            }
                        ],
                    }
                ]
            }

            _, reference_cache = collect_reference_cache(database, output_path)

        cached = reference_cache["doi:10.1000/test"]
        self.assertTrue(cached["matched"])
        self.assertEqual(cached["source_count"], 1)
        self.assertEqual(cached["raw_text_examples"], ["Smith A. Example title. doi:10.1000/test"])

    def test_collect_reference_cache_uses_llm_split_for_concatenated_reference_text(self) -> None:
        with TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "reference_metadata.json"
            database = {
                "abstracts": [
                    {
                        "id": 1,
                        "responses": [
                            {
                                "question_name": "References/Citations",
                                "value": "Smith A. Interesting title. Journal. 2024. Jones B. Another title. Journal. 2023.",
                            }
                        ],
                    }
                ]
            }
            request_counts = {"reference_split_requests": 0}

            with patch(
                "ohbm2026.openalex.llm_reference_split_request",
                return_value={
                    "estimated_reference_count": 2,
                    "references": [
                        {
                            "reference": "Smith A. Interesting title. Journal. 2024.",
                            "title": "Interesting title",
                            "doi": None,
                        },
                        {
                            "reference": "Jones B. Another title. Journal. 2023.",
                            "title": "Another title",
                            "doi": None,
                        },
                    ],
                },
            ):
                abstracts, reference_cache = collect_reference_cache(
                    database,
                    output_path,
                    use_llm_reference_splitting=True,
                    request_counts=request_counts,
                )

        self.assertEqual(len(abstracts[0]["references"]), 2)
        self.assertEqual(len(reference_cache), 2)
        self.assertEqual(request_counts["reference_split_requests"], 1)
        self.assertEqual(abstracts[0]["reference_split_strategy"], "llm")
        self.assertEqual(abstracts[0]["reference_split_candidate_count"], 2)
        self.assertEqual(abstracts[0]["reference_split_estimated_count"], 2)

    def test_collect_reference_cache_writes_collect_checkpoint_incrementally(self) -> None:
        with TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "reference_metadata.json"
            database = {
                "abstracts": [
                    {
                        "id": 1,
                        "responses": [
                            {
                                "question_name": "References/Citations",
                                "value": "<ol><li>Smith A. Example title. doi:10.1000/test</li></ol>",
                            }
                        ],
                    }
                ]
            }

            abstracts, _ = collect_reference_cache(
                database,
                output_path,
                use_title_search=True,
                collect_checkpoint_every_abstracts=1,
            )

            payload = json.loads(output_path.read_text())

        self.assertEqual(len(abstracts), 1)
        self.assertEqual(payload["status"], "running")
        self.assertEqual(payload["phase"], "collect")
        self.assertEqual(payload["abstract_count"], 1)

    def test_split_reference_markdown_retries_before_fallback(self) -> None:
        with patch(
            "ohbm2026.openalex.llm_reference_split_request",
            side_effect=[
                OpenAlexError("temporary timeout"),
                {
                    "estimated_reference_count": 2,
                    "references": [
                        {
                            "reference": "Smith A. Interesting title. Journal. 2024.",
                            "title": "Interesting title",
                            "doi": None,
                        },
                        {
                            "reference": "Jones B. Another title. Journal. 2023.",
                            "title": "Another title",
                            "doi": None,
                        },
                    ],
                },
            ],
        ):
            candidates, diagnostics = split_reference_markdown(
                "Smith A. Interesting title. Journal. 2024. Jones B. Another title. Journal. 2023."
            )

        self.assertEqual(len(candidates), 2)
        self.assertEqual(diagnostics["reference_split_strategy"], "llm")
        self.assertEqual(diagnostics["reference_split_attempts"], 2)
        self.assertIsNone(diagnostics["reference_split_error"])
        self.assertEqual(diagnostics["reference_split_estimated_count"], 2)

    def test_split_reference_markdown_records_fallback_reason(self) -> None:
        with patch(
            "ohbm2026.openalex.llm_reference_split_request",
            side_effect=OpenAlexError("temporary timeout"),
        ):
            candidates, diagnostics = split_reference_markdown(
                "Smith A. Interesting title. Journal. 2024."
            )

        self.assertEqual(len(candidates), 1)
        self.assertEqual(diagnostics["reference_split_strategy"], "fallback_single_block")
        self.assertEqual(diagnostics["reference_split_fallback_reason"], "llm_error")
        self.assertEqual(diagnostics["reference_split_error"], "temporary timeout")
        self.assertIsNone(diagnostics["reference_split_estimated_count"])

    def test_openai_reference_split_request_uses_responses_api(self) -> None:
        class DummyResponse:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self) -> bytes:
                return json.dumps(
                    {
                        "output_text": json.dumps(
                            {
                                "estimated_reference_count": 2,
                                "references": [
                                    {
                                        "reference": "Smith A. Interesting title. Journal. 2024.",
                                        "title": "Interesting title",
                                        "doi": None
                                    },
                                    {
                                        "reference": "Jones B. Another title. Journal. 2023.",
                                        "title": "Another title",
                                        "doi": None
                                    }
                                ]
                            }
                        )
                    }
                ).encode("utf-8")

        captured: dict[str, object] = {}

        def fake_urlopen(request):
            captured["url"] = request.full_url
            captured["payload"] = json.loads(request.data.decode("utf-8"))
            return DummyResponse()

        with (
            patch("ohbm2026.openalex.get_openai_api_key", return_value="test-key"),
            patch("ohbm2026.openalex.urlopen_with_retries", side_effect=fake_urlopen),
        ):
            references = openai_reference_split_request("1. Smith A. Interesting title. Journal. 2024.")

        self.assertEqual(
            references,
            {
                "estimated_reference_count": 2,
                "references": [
                    {
                        "reference": "Smith A. Interesting title. Journal. 2024.",
                        "title": "Interesting title",
                        "doi": None,
                    },
                    {
                        "reference": "Jones B. Another title. Journal. 2023.",
                        "title": "Another title",
                        "doi": None,
                    },
                ],
            },
        )
        self.assertEqual(captured["url"], OPENAI_RESPONSES_API)
        self.assertEqual(captured["payload"]["model"], "gpt-5-nano")
        self.assertFalse(captured["payload"]["store"])
        self.assertEqual(captured["payload"]["reasoning"]["effort"], "minimal")
        self.assertEqual(captured["payload"]["text"]["format"]["type"], "json_schema")
        self.assertEqual(captured["payload"]["text"]["format"]["name"], "reference_split")
        self.assertEqual(
            captured["payload"]["text"]["format"]["schema"]["required"],
            ["estimated_reference_count", "references"],
        )
        item_schema = captured["payload"]["text"]["format"]["schema"]["properties"]["references"]["items"]
        self.assertEqual(item_schema["required"], ["reference", "title", "doi"])
        self.assertIn("estimated_reference_count", captured["payload"]["text"]["format"]["schema"]["properties"])
        self.assertNotIn("max_output_tokens", captured["payload"])

    def test_search_semantic_scholar_doi_by_title_returns_best_matching_doi(self) -> None:
        payload = {
            "data": [
                {
                    "title": "Unrelated paper",
                    "year": 2021,
                    "externalIds": {"DOI": "10.1/ignore"},
                },
                {
                    "title": "Migraine: disease characterisation, biomarkers, and precision medicine",
                    "year": 2021,
                    "externalIds": {"DOI": "10.1/migraine"},
                },
            ]
        }

        with patch("ohbm2026.openalex.semantic_scholar_request", return_value=payload):
            doi, score = search_semantic_scholar_doi_by_title(
                "Migraine disease characterisation biomarkers and precision medicine",
                reference_year=2021,
            )

        self.assertEqual(doi, "10.1/migraine")
        self.assertGreaterEqual(score, 0.8)

    def test_search_semantic_scholar_doi_by_reference_returns_best_matching_doi(self) -> None:
        payload = {
            "data": [
                {
                    "title": "Unrelated paper",
                    "year": 2021,
                    "externalIds": {"DOI": "10.1/ignore"},
                },
                {
                    "title": "Migraine: disease characterisation, biomarkers, and precision medicine",
                    "year": 2021,
                    "externalIds": {"DOI": "10.1/migraine"},
                },
            ]
        }

        with patch("ohbm2026.openalex.semantic_scholar_request", return_value=payload):
            doi, score = search_semantic_scholar_doi_by_reference(
                "Ashina M, Terwindt GM. Migraine: disease characterisation, biomarkers, and precision medicine. The Lancet. 2021;397(10283):1496-1504.",
                reference_year=2021,
            )

        self.assertEqual(doi, "10.1/migraine")
        self.assertGreaterEqual(score, 0.8)

    def test_search_crossref_doi_by_title_returns_best_matching_doi(self) -> None:
        payload = {
            "message": {
                "items": [
                    {"title": ["Unrelated paper"], "DOI": "10.1/ignore", "published-print": {"date-parts": [[2021]]}},
                    {
                        "title": ["Migraine: disease characterisation, biomarkers, and precision medicine"],
                        "DOI": "10.1/migraine",
                        "published-print": {"date-parts": [[2021]]},
                    },
                ]
            }
        }

        with patch("ohbm2026.openalex.crossref_request", return_value=payload):
            doi, score = search_crossref_doi_by_title(
                "Migraine disease characterisation biomarkers and precision medicine",
                reference_year=2021,
            )

        self.assertEqual(doi, "10.1/migraine")
        self.assertGreaterEqual(score, 0.8)

    def test_resolve_reference_cache_doi_discovery_finds_doi_and_matches_openalex(self) -> None:
        abstract_reference_records = [{"id": 1, "references": [{"reference_key": "text:abc", "raw_text": "Example ref"}]}]
        reference_cache = {
            "text:abc": {
                "reference_key": "text:abc",
                "raw_text": "Example ref",
                "doi": None,
                "pmid": None,
                "title_guess": None,
                "reference_year": 2024,
                "matched": False,
                "match_method": "pending",
                "openalex": None,
                "source_count": 1,
                "raw_text_examples": ["Example ref"],
                "doi_lookup_completed": False,
                "doi_discovery_completed": False,
                "doi_discovery_source": None,
                "doi_discovery_title_score": None,
                "pmid_lookup_completed": False,
                "title_lookup_completed": False,
            }
        }
        openalex_work = {
            "id": "https://openalex.org/W123",
            "doi": "https://doi.org/10.1/example",
            "display_name": "Example reference title",
            "ids": {},
            "primary_location": {"source": {"display_name": "NeuroImage"}},
        }

        with TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "reference_metadata.json"
            with (
                patch("ohbm2026.openalex.search_semantic_scholar_doi_by_reference", return_value=("10.1/example", 0.93)),
                patch("ohbm2026.openalex.fetch_openalex_work_by_doi", return_value=openalex_work),
            ):
                stats = resolve_reference_cache_doi_discovery(
                    abstract_reference_records,
                    reference_cache,
                    output_path=output_path,
                    use_title_search=False,
                    request_counts={"doi_requests": 0, "pmid_requests": 0, "title_requests": 0},
                )

        resolved = reference_cache["text:abc"]
        self.assertEqual(resolved["doi"], "10.1/example")
        self.assertTrue(resolved["matched"])
        self.assertEqual(resolved["match_method"], "semantic_scholar_doi")
        self.assertEqual(resolved["doi_discovery_source"], "semantic_scholar")
        self.assertEqual(resolved["openalex"]["openalex_id"], "https://openalex.org/W123")
        self.assertEqual(stats["doi_requests"], 1)

    def test_resolve_reference_cache_doi_discovery_does_not_fallback_to_crossref(self) -> None:
        abstract_reference_records = [{"id": 1, "references": [{"reference_key": "text:abc", "raw_text": "Example ref"}]}]
        reference_cache = {
            "text:abc": {
                "reference_key": "text:abc",
                "raw_text": "Example ref",
                "doi": None,
                "pmid": None,
                "title_guess": None,
                "reference_year": 2024,
                "matched": False,
                "match_method": "pending",
                "openalex": None,
                "source_count": 1,
                "raw_text_examples": ["Example ref"],
                "doi_lookup_completed": False,
                "doi_discovery_completed": False,
                "doi_discovery_source": None,
                "doi_discovery_title_score": None,
                "pmid_lookup_completed": False,
                "title_lookup_completed": False,
            }
        }

        with TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "reference_metadata.json"
            with (
                patch("ohbm2026.openalex.search_semantic_scholar_doi_by_reference", return_value=(None, 0.42)),
                patch("ohbm2026.openalex.search_crossref_doi_by_title", side_effect=AssertionError("Crossref should not be called")),
            ):
                stats = resolve_reference_cache_doi_discovery(
                    abstract_reference_records,
                    reference_cache,
                    output_path=output_path,
                    use_title_search=False,
                    request_counts={"doi_requests": 0, "pmid_requests": 0, "title_requests": 0},
                )

        resolved = reference_cache["text:abc"]
        self.assertIsNone(resolved["doi"])
        self.assertTrue(resolved["doi_discovery_completed"])
        self.assertIsNone(resolved["doi_discovery_source"])
        self.assertEqual(stats["semantic_scholar_requests"], 1)
        self.assertNotIn("crossref_requests", stats)

    def test_resolve_reference_cache_doi_discovery_skips_references_with_titles(self) -> None:
        abstract_reference_records = [{"id": 1, "references": [{"reference_key": "text:abc", "raw_text": "Example ref"}]}]
        reference_cache = {
            "text:abc": {
                "reference_key": "text:abc",
                "raw_text": "Example ref",
                "doi": None,
                "pmid": None,
                "title_guess": "Example reference title",
                "reference_year": 2024,
                "matched": False,
                "match_method": "pending",
                "openalex": None,
                "source_count": 1,
                "raw_text_examples": ["Example ref"],
                "doi_lookup_completed": False,
                "doi_discovery_completed": False,
                "doi_discovery_source": None,
                "doi_discovery_title_score": None,
                "pmid_lookup_completed": False,
                "title_lookup_completed": False,
            }
        }

        with TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "reference_metadata.json"
            with patch(
                "ohbm2026.openalex.search_semantic_scholar_doi_by_reference",
                side_effect=AssertionError("Semantic Scholar should not be called when title exists"),
            ):
                stats = resolve_reference_cache_doi_discovery(
                    abstract_reference_records,
                    reference_cache,
                    output_path=output_path,
                    use_title_search=True,
                    request_counts={"doi_requests": 0, "pmid_requests": 0, "title_requests": 0},
                )

        resolved = reference_cache["text:abc"]
        self.assertTrue(resolved["doi_discovery_completed"])
        self.assertEqual(stats["semantic_scholar_requests"], 0)

    def test_build_reference_metadata_payload_uses_resolved_doi(self) -> None:
        payload = build_reference_metadata_payload(
            [
                {
                    "id": 1,
                    "references": [{"reference_key": "text:abc", "raw_text": "Example ref"}],
                    "reference_split_strategy": "llm",
                    "reference_split_attempts": 1,
                    "reference_split_error": None,
                    "reference_split_fallback_reason": None,
                    "reference_split_candidate_count": 1,
                    "reference_split_estimated_count": 1,
                }
            ],
            {
                "text:abc": {
                    "reference_key": "text:abc",
                    "raw_text": "Example ref",
                    "doi": "10.1/example",
                    "pmid": None,
                    "title_guess": "Example title",
                    "matched": True,
                    "match_method": "semantic_scholar_doi",
                    "openalex": {"openalex_id": "https://openalex.org/W123"},
                    "doi_lookup_completed": True,
                    "doi_discovery_completed": True,
                    "pmid_lookup_completed": True,
                    "title_lookup_completed": False,
                }
            },
            use_title_search=False,
        )

        self.assertEqual(payload["abstracts"][0]["references"][0]["doi"], "10.1/example")
        self.assertEqual(payload["abstracts"][0]["reference_split_strategy"], "llm")
        self.assertEqual(payload["abstracts"][0]["reference_split_estimated_count"], 1)
        self.assertEqual(payload["progress"]["doi_discovery_completed_count"], 1)

    def test_failed_reference_split_ids_includes_fallback_and_under_split(self) -> None:
        payload = {
            "abstracts": [
                {
                    "id": 1,
                    "reference_split_strategy": "fallback_single_block",
                    "reference_split_estimated_count": None,
                    "reference_split_candidate_count": 1,
                },
                {
                    "id": 2,
                    "reference_split_strategy": "llm",
                    "reference_split_estimated_count": 4,
                    "reference_split_candidate_count": 2,
                },
                {
                    "id": 3,
                    "reference_split_strategy": "llm",
                    "reference_split_estimated_count": 2,
                    "reference_split_candidate_count": 2,
                },
            ]
        }

        self.assertEqual(failed_reference_split_ids(payload), [1, 2])

    def test_merge_reference_metadata_payloads_replaces_repaired_abstracts_and_drops_orphans(self) -> None:
        existing_payload = {
            "use_title_search": True,
            "request_counts": {"reference_split_requests": 10},
            "abstracts": [
                {
                    "id": 1,
                    "references": [
                        {
                            "reference_key": "text:merged",
                            "raw_text": "Merged reference block",
                            "doi": None,
                            "pmid": None,
                            "title_guess": "Merged title",
                            "matched": False,
                            "match_method": "unmatched",
                            "openalex_id": None,
                        }
                    ],
                    "reference_split_strategy": "fallback_single_block",
                    "reference_split_attempts": 3,
                    "reference_split_error": "validation failed",
                    "reference_split_fallback_reason": "validation_failed",
                    "reference_split_candidate_count": 1,
                    "reference_split_estimated_count": 4,
                },
                {
                    "id": 2,
                    "references": [
                        {
                            "reference_key": "doi:10.1/existing",
                            "raw_text": "Existing good ref",
                            "doi": "10.1/existing",
                            "pmid": None,
                            "title_guess": "Existing good ref",
                            "matched": True,
                            "match_method": "doi",
                            "openalex_id": "https://openalex.org/Wexisting",
                        }
                    ],
                    "reference_split_strategy": "llm",
                    "reference_split_attempts": 1,
                    "reference_split_error": None,
                    "reference_split_fallback_reason": None,
                    "reference_split_candidate_count": 1,
                    "reference_split_estimated_count": 1,
                },
            ],
            "references": [
                {
                    "reference_key": "text:merged",
                    "raw_text": "Merged reference block",
                    "doi": None,
                    "pmid": None,
                    "title_guess": "Merged title",
                    "matched": False,
                    "match_method": "unmatched",
                    "openalex": None,
                    "source_count": 1,
                    "raw_text_examples": ["Merged reference block"],
                    "doi_lookup_completed": True,
                    "doi_discovery_completed": True,
                    "pmid_lookup_completed": True,
                    "title_lookup_completed": True,
                },
                {
                    "reference_key": "doi:10.1/existing",
                    "raw_text": "Existing good ref",
                    "doi": "10.1/existing",
                    "pmid": None,
                    "title_guess": "Existing good ref",
                    "matched": True,
                    "match_method": "doi",
                    "openalex": {"openalex_id": "https://openalex.org/Wexisting"},
                    "source_count": 1,
                    "raw_text_examples": ["Existing good ref"],
                    "doi_lookup_completed": True,
                    "doi_discovery_completed": True,
                    "pmid_lookup_completed": True,
                    "title_lookup_completed": True,
                },
            ],
        }
        repaired_payload = {
            "use_title_search": True,
            "request_counts": {"reference_split_requests": 2},
            "abstracts": [
                {
                    "id": 1,
                    "references": [
                        {
                            "reference_key": "doi:10.1/a",
                            "raw_text": "Split ref A",
                            "doi": "10.1/a",
                            "pmid": None,
                            "title_guess": "Split ref A",
                            "matched": True,
                            "match_method": "doi",
                            "openalex_id": "https://openalex.org/Wa",
                        },
                        {
                            "reference_key": "text:b",
                            "raw_text": "Split ref B",
                            "doi": None,
                            "pmid": None,
                            "title_guess": "Split ref B",
                            "matched": False,
                            "match_method": "unmatched",
                            "openalex_id": None,
                        },
                    ],
                    "reference_split_strategy": "llm",
                    "reference_split_attempts": 1,
                    "reference_split_error": None,
                    "reference_split_fallback_reason": None,
                    "reference_split_candidate_count": 2,
                    "reference_split_estimated_count": 2,
                }
            ],
            "references": [
                {
                    "reference_key": "doi:10.1/a",
                    "raw_text": "Split ref A",
                    "doi": "10.1/a",
                    "pmid": None,
                    "title_guess": "Split ref A",
                    "matched": True,
                    "match_method": "doi",
                    "openalex": {"openalex_id": "https://openalex.org/Wa"},
                    "source_count": 1,
                    "raw_text_examples": ["Split ref A"],
                    "doi_lookup_completed": True,
                    "doi_discovery_completed": True,
                    "pmid_lookup_completed": True,
                    "title_lookup_completed": True,
                },
                {
                    "reference_key": "text:b",
                    "raw_text": "Split ref B",
                    "doi": None,
                    "pmid": None,
                    "title_guess": "Split ref B",
                    "matched": False,
                    "match_method": "unmatched",
                    "openalex": None,
                    "source_count": 1,
                    "raw_text_examples": ["Split ref B"],
                    "doi_lookup_completed": True,
                    "doi_discovery_completed": True,
                    "pmid_lookup_completed": True,
                    "title_lookup_completed": True,
                },
            ],
        }

        merged = merge_reference_metadata_payloads(existing_payload, repaired_payload)

        self.assertEqual(len(merged["abstracts"]), 2)
        self.assertEqual(merged["abstracts"][0]["reference_split_strategy"], "llm")
        merged_keys = {reference["reference_key"] for reference in merged["references"]}
        self.assertEqual(merged_keys, {"doi:10.1/a", "text:b", "doi:10.1/existing"})
        self.assertNotIn("text:merged", merged_keys)

    def test_repair_failed_reference_splits_reruns_only_failed_abstracts(self) -> None:
        abstracts_database = {
            "abstracts": [
                {"id": 1, "responses": [{"question_name": "References/Citations", "value": "bad"}]},
                {"id": 2, "responses": [{"question_name": "References/Citations", "value": "good"}]},
            ]
        }
        existing_payload = {
            "use_title_search": True,
            "request_counts": {},
            "abstracts": [
                {
                    "id": 1,
                    "references": [],
                    "reference_split_strategy": "fallback_single_block",
                    "reference_split_attempts": 3,
                    "reference_split_error": "timeout",
                    "reference_split_fallback_reason": "llm_error",
                    "reference_split_candidate_count": 1,
                    "reference_split_estimated_count": None,
                },
                {
                    "id": 2,
                    "references": [],
                    "reference_split_strategy": "llm",
                    "reference_split_attempts": 1,
                    "reference_split_error": None,
                    "reference_split_fallback_reason": None,
                    "reference_split_candidate_count": 1,
                    "reference_split_estimated_count": 1,
                },
            ],
            "references": [],
        }
        repaired_payload = {
            "use_title_search": True,
            "request_counts": {},
            "abstracts": [
                {
                    "id": 1,
                    "references": [],
                    "reference_split_strategy": "llm",
                    "reference_split_attempts": 1,
                    "reference_split_error": None,
                    "reference_split_fallback_reason": None,
                    "reference_split_candidate_count": 2,
                    "reference_split_estimated_count": 2,
                }
            ],
            "references": [],
        }
        captured: dict[str, object] = {}

        def fake_build_reference_metadata_database(database, **kwargs):
            captured["database"] = database
            return repaired_payload

        with TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "reference_metadata.json"
            with patch(
                "ohbm2026.openalex.build_reference_metadata_database",
                side_effect=fake_build_reference_metadata_database,
            ):
                merged = repair_failed_reference_splits(
                    abstracts_database,
                    existing_payload,
                    output_path=output_path,
                )

        self.assertEqual([abstract["id"] for abstract in captured["database"]["abstracts"]], [1])
        self.assertEqual(merged["abstracts"][0]["reference_split_strategy"], "llm")


if __name__ == "__main__":
    unittest.main()
