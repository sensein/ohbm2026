"""Tests for `ohbm2026.analyze.topics` (US5).

Coverage per FR-009 + CA-002:
- Phrase extraction returns canonicalized noun-chunks + entities.
- c-TF-IDF assigns higher score to discriminative phrases.
- `--skip-llm-topics` returns top-N c-TF-IDF phrases as Keywords with
  empty Title/Description/Focus.
- LLM `Keywords ⊆ candidate_phrases` guard raises
  `TopicGroupingHallucination` on invention.
- LLM cache: same `sorted(candidate_phrases)` hits cache; the LLM
  adapter is not called twice.
- `build_topics_artifact` end-to-end with mocked LLM.
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import unittest
from collections import Counter
from contextlib import contextmanager
from pathlib import Path

from ohbm2026.analyze.topics import (
    DEFAULT_KEYWORD_OUT_N,
    build_topics_artifact,
    compute_ctfidf,
    extract_cluster_phrases_local,
    group_phrases_via_llm,
)
from ohbm2026.exceptions import AnalysisError, TopicGroupingHallucination


@contextmanager
def _isolated_cwd():
    original = Path.cwd()
    tmp = tempfile.mkdtemp()
    try:
        os.chdir(tmp)
        yield Path(tmp)
    finally:
        os.chdir(original)
        shutil.rmtree(tmp, ignore_errors=True)


class PhraseExtractionTests(unittest.TestCase):
    def test_returns_lowercased_phrases(self) -> None:
        texts = [
            "Resting-state Functional Connectivity in the Default Mode Network.",
            "The default mode network shows resting-state connectivity.",
        ]
        counter = extract_cluster_phrases_local(texts)
        # At least one phrase containing "default mode" should appear
        self.assertTrue(
            any("default mode" in p for p in counter),
            f"expected a 'default mode' phrase; got {list(counter.keys())[:10]}",
        )

    def test_drops_pure_stopword_phrases(self) -> None:
        texts = ["the of and to in"]
        counter = extract_cluster_phrases_local(texts)
        # All entries should have at least one non-stopword token
        for phrase in counter:
            tokens = phrase.split()
            self.assertFalse(
                all(t in {"the", "of", "and", "to", "in"} for t in tokens),
                f"pure-stopword phrase leaked: {phrase!r}",
            )

    def test_empty_text(self) -> None:
        counter = extract_cluster_phrases_local(["", None or ""])
        self.assertEqual(len(counter), 0)


class CtfidfTests(unittest.TestCase):
    def test_discriminative_phrase_scores_higher(self) -> None:
        # Cluster 1: vocabulary A
        # Cluster 2: vocabulary B
        # Cluster 3: shared filler
        c1 = Counter({"functional connectivity": 5, "shared filler": 1})
        c2 = Counter({"diffusion mri": 5, "shared filler": 1})
        c3 = Counter({"shared filler": 5})
        scores = compute_ctfidf([c1, c2, c3])
        self.assertEqual(len(scores), 3)
        # "functional connectivity" is unique to cluster 0 → high score there
        self.assertGreater(
            scores[0]["functional connectivity"],
            scores[0]["shared filler"],
        )
        # "diffusion mri" should be top for cluster 1
        top_c2 = max(scores[1].items(), key=lambda kv: kv[1])[0]
        self.assertEqual(top_c2, "diffusion mri")

    def test_empty_input(self) -> None:
        self.assertEqual(compute_ctfidf([]), [])

    def test_zero_total_cluster(self) -> None:
        scores = compute_ctfidf([Counter(), Counter({"x": 1})])
        self.assertEqual(scores[0], {})
        self.assertIn("x", scores[1])


class GroupPhrasesViaLlmTests(unittest.TestCase):
    def test_subset_guard_filters_invented_keyword(self) -> None:
        """LLM invents `fmri` (not in candidates) — production drops the
        invented term but keeps the valid one. `Keywords ⊆ candidate_phrases`
        contract is preserved; the invented term is recorded for telemetry."""
        with _isolated_cwd() as tmp:
            cache_dir = tmp / "cache"
            candidates = ["functional connectivity", "default mode network"]

            def fake_llm(prompt: str, model_id: str) -> str:
                return json.dumps({
                    "Keywords": ["functional connectivity", "fmri"],
                    "Title": "T",
                    "Description": "D",
                    "Focus": "themes",
                })

            result = group_phrases_via_llm(
                candidates,
                cluster_id=0,
                cache_dir=cache_dir,
                llm_call=fake_llm,
            )
            self.assertEqual(result["Keywords"], ["functional connectivity"])
            self.assertEqual(result["DroppedKeywords"], ["fmri"])

    def test_subset_guard_raises_when_all_invented(self) -> None:
        """If EVERY emitted keyword is invented, the bundle still fails —
        the LLM ignored the shortlist entirely."""
        with _isolated_cwd() as tmp:
            cache_dir = tmp / "cache"
            candidates = ["functional connectivity", "default mode network"]

            def fake_llm(prompt: str, model_id: str) -> str:
                return json.dumps({
                    "Keywords": ["fmri", "ROI analysis"],
                    "Title": "T",
                    "Description": "D",
                    "Focus": "themes",
                })

            with self.assertRaises(TopicGroupingHallucination):
                group_phrases_via_llm(
                    candidates,
                    cluster_id=0,
                    cache_dir=cache_dir,
                    llm_call=fake_llm,
                )

    def test_subset_guard_accepts_valid(self) -> None:
        with _isolated_cwd() as tmp:
            cache_dir = tmp / "cache"
            candidates = ["functional connectivity", "default mode network", "fMRI"]

            def fake_llm(prompt: str, model_id: str) -> str:
                return json.dumps({
                    "Keywords": ["functional connectivity", "default mode network"],
                    "Title": "Resting-state DMN",
                    "Description": "Studies of intrinsic brain networks.",
                    "Focus": "themes",
                })

            result = group_phrases_via_llm(
                candidates,
                cluster_id=0,
                cache_dir=cache_dir,
                llm_call=fake_llm,
            )
            self.assertEqual(result["Title"], "Resting-state DMN")
            self.assertEqual(result["Focus"], "themes")
            self.assertIn("functional connectivity", result["Keywords"])

    def test_cache_hits_skip_llm_call(self) -> None:
        with _isolated_cwd() as tmp:
            cache_dir = tmp / "cache"
            candidates = ["a", "b", "c"]
            calls: list[int] = []

            def fake_llm(prompt: str, model_id: str) -> str:
                calls.append(1)
                return json.dumps({
                    "Keywords": ["a", "b"],
                    "Title": "T",
                    "Description": "D",
                    "Focus": "themes",
                })

            group_phrases_via_llm(
                candidates, cluster_id=0, cache_dir=cache_dir, llm_call=fake_llm,
            )
            self.assertEqual(len(calls), 1)
            # Second call with same input → cache hit, fake_llm not called again
            group_phrases_via_llm(
                candidates, cluster_id=0, cache_dir=cache_dir, llm_call=fake_llm,
            )
            self.assertEqual(len(calls), 1)
            # Same candidates in DIFFERENT order → still cache hit (sorted key)
            group_phrases_via_llm(
                ["c", "a", "b"], cluster_id=0, cache_dir=cache_dir, llm_call=fake_llm,
            )
            self.assertEqual(len(calls), 1)

    def test_no_llm_and_no_cache_raises(self) -> None:
        with _isolated_cwd() as tmp:
            cache_dir = tmp / "cache"
            with self.assertRaises(AnalysisError):
                group_phrases_via_llm(
                    ["a", "b"],
                    cluster_id=0,
                    cache_dir=cache_dir,
                    llm_call=None,
                )


class BuildTopicsArtifactTests(unittest.TestCase):
    def test_skip_llm_topics_path(self) -> None:
        with _isolated_cwd() as tmp:
            assignments = [0, 0, 0, 1, 1, 1]
            texts = [
                "functional connectivity in the default mode network",
                "default mode network connectivity at rest",
                "resting-state functional connectivity",
                "diffusion mri of white matter tracts",
                "white matter tractography with diffusion mri",
                "fiber tract diffusion analysis",
            ]
            result = build_topics_artifact(
                assignments,
                texts,
                cache_dir=tmp / "cache",
                skip_llm=True,
                keyword_out_n=5,
            )
            self.assertEqual(set(result.keys()), {0, 1})
            for entry in result.values():
                self.assertEqual(entry["Title"], "")
                self.assertEqual(entry["Description"], "")
                self.assertEqual(entry["Focus"], "")
                self.assertGreater(len(entry["Keywords"]), 0)
                self.assertLessEqual(len(entry["Keywords"]), 5)

    def test_mocked_llm_end_to_end(self) -> None:
        with _isolated_cwd() as tmp:
            assignments = [0, 0, 1, 1]
            texts = [
                "functional connectivity default mode network",
                "default mode network resting state",
                "diffusion mri white matter",
                "white matter diffusion tractography",
            ]
            calls: list[list[str]] = []

            def fake_llm(prompt: str, model_id: str) -> str:
                # Validate the phrase-list-only contract: the prompt
                # must contain the "Candidate phrases" structured block
                # (NOT the raw abstract paragraphs verbatim).
                self.assertIn("Candidate phrases (you MUST pick", prompt)
                # Echo back whatever the candidate list looked like
                lines = [
                    l.strip("- ").strip()
                    for l in prompt.splitlines()
                    if l.startswith("- ")
                ]
                calls.append(lines)
                return json.dumps({
                    "Keywords": lines[:2],
                    "Title": "Test cluster",
                    "Description": "Mock description.",
                    "Focus": "themes",
                })

            result = build_topics_artifact(
                assignments,
                texts,
                cache_dir=tmp / "cache",
                skip_llm=False,
                llm_call=fake_llm,
            )
            self.assertEqual(set(result.keys()), {0, 1})
            self.assertEqual(len(calls), 2)
            for entry in result.values():
                self.assertEqual(entry["Title"], "Test cluster")
                self.assertEqual(entry["Focus"], "themes")


if __name__ == "__main__":
    unittest.main()
