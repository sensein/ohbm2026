"""T005 — Stage 12 US1 — sections.acknowledgments roundtrip.

The data-package abstracts emitter MUST surface each record's
`Acknowledgement` corpus response under `sections.acknowledgments`,
trimmed + HTML-to-text via the existing `_section` helper. Empty /
whitespace / absent responses MUST yield empty string.
"""

from __future__ import annotations

import json
import pathlib
import tempfile
import unittest


_FIX = pathlib.Path(__file__).parent / "fixtures" / "book"


def _question(name: str, value: str) -> dict:
    return {"question_name": name, "value": value}


def _abstract(*, abstract_id: int, poster_id: str, questions: list[dict]) -> dict:
    return {
        "id": abstract_id,
        "poster_id": poster_id,
        "title": f"abstract {poster_id}",
        "accepted_for": "Poster",
        "authors": [],
        "responses": questions,
        "external_urls": [],
        "figure_urls": [],
        "program_sessions": [],
    }


class TestAcknowledgmentsField(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        try:
            from ohbm2026.ui_data.abstracts import iter_abstracts
        except ImportError as exc:
            raise unittest.SkipTest(f"abstracts module not importable: {exc}")
        cls.iter_abstracts = staticmethod(iter_abstracts)

    def _make_corpus(self, abstracts: list[dict]) -> pathlib.Path:
        tmp = tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".json",
            delete=False,
            encoding="utf-8",
        )
        json.dump(
            {
                "fetched_at": "2026-05-21T00:00:00Z",
                "event_ids": [1],
                "abstract_count": len(abstracts),
                "abstracts": abstracts,
            },
            tmp,
        )
        tmp.close()
        return pathlib.Path(tmp.name)

    def _empty_withdrawn(self) -> pathlib.Path:
        tmp = tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".json",
            delete=False,
            encoding="utf-8",
        )
        json.dump({"withdrawn_ids": []}, tmp)
        tmp.close()
        return pathlib.Path(tmp.name)

    def _records(self, abstracts: list[dict]) -> list[dict]:
        corpus = self._make_corpus(abstracts)
        withdrawn = self._empty_withdrawn()
        try:
            return list(
                self.iter_abstracts(
                    corpus_path=corpus,
                    enriched_path=None,
                    references_path=None,
                    withdrawn_path=withdrawn,
                )
            )
        finally:
            corpus.unlink(missing_ok=True)
            withdrawn.unlink(missing_ok=True)

    def test_present_acknowledgment_lands_in_sections(self) -> None:
        recs = self._records(
            [
                _abstract(
                    abstract_id=1001,
                    poster_id="0001",
                    questions=[
                        _question("Title", "abstract 0001"),
                        _question("Introduction", "<p>intro</p>"),
                        _question(
                            "Acknowledgement",
                            "<p>Funded by NIH grant ABC123.</p>",
                        ),
                    ],
                )
            ]
        )
        self.assertEqual(len(recs), 1)
        self.assertIn("acknowledgments", recs[0]["sections"])
        ack = recs[0]["sections"]["acknowledgments"]
        self.assertIn("NIH grant ABC123", ack)
        # Trimmed (no leading/trailing whitespace).
        self.assertEqual(ack, ack.strip())

    def test_empty_acknowledgment_yields_empty_string(self) -> None:
        recs = self._records(
            [
                _abstract(
                    abstract_id=1002,
                    poster_id="0002",
                    questions=[
                        _question("Title", "abstract 0002"),
                        _question("Acknowledgement", "   "),
                    ],
                )
            ]
        )
        self.assertEqual(recs[0]["sections"]["acknowledgments"], "")

    def test_absent_acknowledgment_yields_empty_string(self) -> None:
        recs = self._records(
            [
                _abstract(
                    abstract_id=1003,
                    poster_id="0003",
                    questions=[
                        _question("Title", "abstract 0003"),
                        # No Acknowledgement entry at all.
                    ],
                )
            ]
        )
        self.assertEqual(recs[0]["sections"]["acknowledgments"], "")

    def test_independent_of_other_sections(self) -> None:
        recs = self._records(
            [
                _abstract(
                    abstract_id=1004,
                    poster_id="0004",
                    questions=[
                        _question("Title", "abstract 0004"),
                        _question("Introduction", "<p>intro body</p>"),
                        _question("Methods", "<p>methods body</p>"),
                        _question("Acknowledgement", "<p>ack body</p>"),
                    ],
                )
            ]
        )
        sections = recs[0]["sections"]
        self.assertIn("intro body", sections.get("introduction", ""))
        self.assertIn("methods body", sections.get("methods", ""))
        self.assertIn("ack body", sections.get("acknowledgments", ""))
        # Conclusion / results absent → empty.
        self.assertEqual(sections.get("conclusion", ""), "")
        self.assertEqual(sections.get("results", ""), "")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
