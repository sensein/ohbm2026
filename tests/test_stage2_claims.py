"""Tests for `src/ohbm2026/stage2_claims.py`.

Three test groups:
- FunctionToolHandlerTests: pure-function correctness for
  verify_source_quote, lookup_eco_code, dedupe_check.
- ClaimsRunComponentTests: end-to-end stub-driven agentic loop
  with a fake OpenAI client returning canned responses + tool
  call traces.
- ClaimsResponseSchemaTests: Pydantic model validation.
"""

from __future__ import annotations

import dataclasses
import json
import sys
import unittest
from unittest import mock

from ohbm2026.enrich import claims as stage2_claims
from ohbm2026.exceptions import EnrichmentError


# ----- Function-tool handler tests -------------------------------------


class FunctionToolHandlerTests(unittest.TestCase):
    def test_verify_source_quote_finds_exact_match(self) -> None:
        manuscript = "We observed a 23% decrease in BOLD signal."
        result = stage2_claims._verify_source_quote_handler(
            claim_text="BOLD decrease",
            source_quote="23% decrease in BOLD signal",
            manuscript=manuscript,
        )
        self.assertTrue(result["is_substring"])
        self.assertEqual(result["candidate_corrections"], [])

    def test_verify_source_quote_returns_candidates_on_miss(self) -> None:
        manuscript = (
            "We observed a 23% decrease in BOLD signal. "
            "Subjects showed significant gamma-band activity."
        )
        result = stage2_claims._verify_source_quote_handler(
            claim_text="any",
            source_quote="we observed a 22% decrease in BOLD signal",
            manuscript=manuscript,
        )
        self.assertFalse(result["is_substring"])
        # difflib should find the 23% sentence as a close match.
        self.assertGreater(len(result["candidate_corrections"]), 0)

    def test_lookup_eco_code_matches_label(self) -> None:
        vocabulary = stage2_claims.load_eco_vocabulary()
        result = stage2_claims._lookup_eco_code_handler(
            "experimental", vocabulary=vocabulary
        )
        self.assertTrue(any(r["eco_id"] == "ECO:0000006" for r in result))

    def test_lookup_eco_code_matches_definition_substring(self) -> None:
        vocabulary = stage2_claims.load_eco_vocabulary()
        result = stage2_claims._lookup_eco_code_handler(
            "neuroimaging analyses", vocabulary=vocabulary
        )
        # Computational evidence's definition mentions neuroimaging.
        self.assertTrue(any(r["eco_id"] == "ECO:0007672" for r in result))

    def test_dedupe_check_high_jaccard_is_duplicate(self) -> None:
        result = stage2_claims._dedupe_check_handler(
            "the BOLD signal decreased by 23 percent in motor cortex",
            "the BOLD signal decreased by 23 percent in motor cortex",
        )
        self.assertTrue(result["is_duplicate"])

    def test_dedupe_check_unrelated_claims_not_duplicate(self) -> None:
        result = stage2_claims._dedupe_check_handler(
            "BOLD signal decreased in motor cortex",
            "ERP latency increased in occipital cortex",
        )
        self.assertFalse(result["is_duplicate"])


# ----- ClaimsResponse schema tests -------------------------------------


class ClaimsResponseSchemaTests(unittest.TestCase):
    def test_well_formed_claim_validates(self) -> None:
        claim = {
            "claim": "test claim",
            "claim_type": "EXPLICIT",
            "source": "some quote",
            "source_type": ["TEXT"],
            "evidence": "test reasoning",
            "evidence_type": ["DATA"],
            "evidence_eco_codes": ["ECO:0000006"],
            "source_quote_verified": True,
        }
        stage2_claims.Claim.model_validate(claim)

    def test_empty_eco_codes_allowed(self) -> None:
        # ECO is an additive annotation, not a gate: empty list is
        # legitimate when no v1 code applies.
        claim = {
            "claim": "test claim",
            "claim_type": "EXPLICIT",
            "source": "some quote",
            "source_type": ["TEXT"],
            "evidence": "test reasoning",
            "evidence_type": ["DATA"],
            "evidence_eco_codes": [],
            "source_quote_verified": True,
        }
        parsed = stage2_claims.Claim.model_validate(claim)
        self.assertEqual(parsed.evidence_eco_codes, [])

    def test_invalid_claim_type_rejected(self) -> None:
        claim = {
            "claim": "test claim",
            "claim_type": "neither",
            "source": "some quote",
            "source_type": ["TEXT"],
            "evidence": "test reasoning",
            "evidence_type": ["DATA"],
            "evidence_eco_codes": ["ECO:0000006"],
            "source_quote_verified": True,
        }
        from pydantic import ValidationError
        with self.assertRaises(ValidationError):
            stage2_claims.Claim.model_validate(claim)


# ----- Agentic claim-extraction tests ----------------------------------


def _make_abstract() -> dict:
    """Synthetic abstract with a known sentence we can target as a
    source quote."""
    return {
        "id": 42,
        "title": "Cortical processing of auditory motion",
        "responses": [
            {"question_name": "Introduction", "value": "We studied auditory motion in fMRI."},
            {"question_name": "Methods", "value": "Subjects listened to moving tones in a 7T scanner."},
            {"question_name": "Results", "value": "We observed a 23 percent decrease in BOLD signal in auditory cortex."},
            {"question_name": "Conclusion", "value": "Auditory motion suppresses auditory cortex."},
        ],
    }


class _FakeFinalResponse:
    """Mimics SDK response with `.output_parsed`, `.output`, `.usage`."""
    def __init__(self, claims: list[stage2_claims.Claim], tool_calls: list[dict] | None = None) -> None:
        self.output_parsed = stage2_claims.ClaimsResponse(claims=claims)
        self.output_text = self.output_parsed.model_dump_json()
        self.output = tool_calls or []
        self.usage = _FakeUsage()


class _FakeUsage:
    input_tokens = 1500
    output_tokens = 300
    cached_tokens = 0


class _FakeClient:
    """Stub OpenAI client. `responses.create()` returns a final
    response by default; tests can override via the canned_responses
    list to simulate tool-call iterations."""
    def __init__(self, canned_responses: list) -> None:
        self.canned_responses = list(canned_responses)
        self.calls = []
        self.responses = self
    def create(self, **kwargs):
        self.calls.append(kwargs)
        if not self.canned_responses:
            raise AssertionError("no more canned responses")
        return self.canned_responses.pop(0)
    def parse(self, **kwargs):
        return self.create(**kwargs)


class AgenticClaimsTests(unittest.TestCase):
    def test_known_substring_yields_verified_claim(self) -> None:
        abstract = _make_abstract()
        manuscript = stage2_claims._build_manuscript_markdown(abstract, [])
        sentence = "We observed a 23 percent decrease in BOLD signal in auditory cortex."
        self.assertIn(sentence, manuscript)
        claim = stage2_claims.Claim(
            claim="BOLD signal decreased in auditory cortex by 23%.",
            claim_type="EXPLICIT",
            source=sentence,
            source_type=["TEXT"],
            evidence="Quantified measurement reported in the results section.",
            evidence_type=["DATA"],
            evidence_eco_codes=["ECO:0000006"],
            source_quote_verified=True,
        )
        client = _FakeClient([_FakeFinalResponse([claim])])
        records, summary = stage2_claims.run_claims_component(
            abstract,
            model_id="gpt-5.4-mini",
            flex_enabled=True,
            client=client,
        )
        self.assertEqual(len(records), 1)
        self.assertTrue(records[0]["source_quote_verified"])
        self.assertEqual(records[0]["evidence_eco_codes"], ["ECO:0000006"])
        self.assertEqual(records[0]["claim_type"], "EXPLICIT")
        self.assertEqual(records[0]["evidence_type"], ["DATA"])
        self.assertEqual(summary.dropped_off_vocab_count, 0)
        self.assertEqual(summary.dropped_unverified_count, 0)

    def test_off_vocabulary_eco_codes_are_filtered_not_dropped(self) -> None:
        # ECO codes are an additive annotation, not a gate. Off-vocab
        # codes get filtered from the list, but the claim is kept.
        abstract = _make_abstract()
        manuscript = stage2_claims._build_manuscript_markdown(abstract, [])
        sentence = "We observed a 23 percent decrease in BOLD signal in auditory cortex."
        on_vocab = stage2_claims.Claim(
            claim="A",
            claim_type="EXPLICIT",
            source=sentence,
            source_type=["TEXT"],
            evidence="Direct measurement.",
            evidence_type=["DATA"],
            evidence_eco_codes=["ECO:0000006"],
            source_quote_verified=True,
        )
        off_vocab = stage2_claims.Claim(
            claim="B",
            claim_type="EXPLICIT",
            source=sentence,
            source_type=["TEXT"],
            evidence="Direct measurement.",
            evidence_type=["DATA"],
            evidence_eco_codes=["ECO:9999999"],
            source_quote_verified=True,
        )
        client = _FakeClient([_FakeFinalResponse([on_vocab, off_vocab])])
        records, summary = stage2_claims.run_claims_component(
            abstract, model_id="gpt-5.4-mini", flex_enabled=True, client=client,
        )
        # Both claims survive; the off-vocab claim has its codes filtered to [].
        self.assertEqual(len(records), 2)
        self.assertEqual(records[0]["evidence_eco_codes"], ["ECO:0000006"])
        self.assertEqual(records[1]["evidence_eco_codes"], [])
        # Counter tracks number of off-vocab codes filtered.
        self.assertEqual(summary.dropped_off_vocab_count, 1)

    def test_unverifiable_quote_drops_claim(self) -> None:
        abstract = _make_abstract()
        # Quote that's NOT in the manuscript.
        ghost = stage2_claims.Claim(
            claim="ghost claim",
            claim_type="EXPLICIT",
            source="this exact wording is nowhere in the abstract",
            source_type=["TEXT"],
            evidence="Fabricated.",
            evidence_type=["DATA"],
            evidence_eco_codes=["ECO:0000006"],
            source_quote_verified=True,  # model claims true; orchestrator re-verifies
        )
        client = _FakeClient([_FakeFinalResponse([ghost])])
        records, summary = stage2_claims.run_claims_component(
            abstract, model_id="gpt-5.4-mini", flex_enabled=True, client=client,
        )
        self.assertEqual(records, [])
        self.assertEqual(summary.dropped_unverified_count, 1)

    def test_empty_claims_list_is_legitimate(self) -> None:
        abstract = _make_abstract()
        client = _FakeClient([_FakeFinalResponse([])])
        records, summary = stage2_claims.run_claims_component(
            abstract, model_id="gpt-5.4-mini", flex_enabled=True, client=client,
        )
        self.assertEqual(records, [])
        self.assertEqual(summary.claims_count, 0)

    def test_cache_key_includes_vocabulary_version(self) -> None:
        from ohbm2026.enrich.claims import _hash_for_cache
        vocab = stage2_claims.load_eco_vocabulary()
        k1 = _hash_for_cache("manuscript", "gpt-5.4-mini", vocab["vocabulary_version"])
        k2 = _hash_for_cache("manuscript", "gpt-5.4-mini", "eco.v2")
        self.assertNotEqual(k1, k2, "vocabulary version MUST be part of the cache key")


# ----- ECO vocabulary loader test --------------------------------------


class VocabularyLoaderTests(unittest.TestCase):
    def test_load_eco_vocabulary_returns_v1_with_id_set(self) -> None:
        vocab = stage2_claims.load_eco_vocabulary()
        self.assertEqual(vocab["vocabulary_version"], "eco.v1")
        self.assertIn("_id_set", vocab)
        self.assertEqual(len(vocab["_id_set"]), 9)
        self.assertIn("ECO:0000006", vocab["_id_set"])


if __name__ == "__main__":
    unittest.main()
