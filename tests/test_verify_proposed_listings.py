import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


def _load_verify_module():
    module_path = Path(__file__).resolve().parents[1] / "scripts" / "verify_proposed_listings.py"
    spec = importlib.util.spec_from_file_location("verify_proposed_listings", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Unable to load verify_proposed_listings module")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class VerifyProposedListingsTest(unittest.TestCase):
    def test_verify_proposal_dir_reports_matches_and_conflicts(self) -> None:
        module = _load_verify_module()
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            abstracts_path = root / "abstracts.json"
            authors_path = root / "authors.json"
            proposal_dir = root / "proposal"
            proposal_dir.mkdir(parents=True, exist_ok=True)

            abstracts_path.write_text(
                json.dumps(
                    {
                        "abstracts": [
                            {
                                "id": 1,
                                "title": "First title",
                                "authors": [{"author_order": 0, "id": 100}],
                                "accepted_for": "Poster",
                                "responses": [],
                            },
                            {
                                "id": 2,
                                "title": "Second title",
                                "authors": [{"author_order": 0, "id": 100}],
                                "accepted_for": "Poster",
                                "responses": [],
                            },
                        ]
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
            authors_path.write_text(
                json.dumps(
                    {
                        "authors": [
                            {"id": 100, "last_name": "Smith"},
                        ]
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
            (proposal_dir / "proposal.json").write_text(
                json.dumps(
                    {
                        "assignments": [
                            {
                                "abstract_id": 1,
                                "poster_number": 1,
                                "title": "First title",
                                "first_author_id": 100,
                            },
                            {
                                "abstract_id": 2,
                                "poster_number": 2,
                                "title": "Second title",
                                "first_author_id": 100,
                            },
                        ]
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
            (proposal_dir / "proposal_listing.csv").write_text(
                (
                    '"intro",,,,,,\n'
                    "Abstract ID Number,NEW POSTER NUMBER *USE THIS NUMBER FOR YOUR LOCATION IN THE POSTER HALL,First Stand-by Time,Second Stand-by Time,Abstract Title,Primary Category,Last Name of First Author\n"
                    '1,0001,"Monday, June 15 | 13:45-14:45","Tuesday, June 16 | 13:30-14:30",First title,Category A,Smith\n'
                    '2,0002,"Monday, June 15 | 13:45-14:45","Tuesday, June 16 | 12:30-13:30",Second title,Category B,Smith\n'
                ),
                encoding="utf-8",
            )

            result = module.verify_proposal_dir(
                proposal_dir,
                module.load_abstract_lookup(abstracts_path),
                module.load_author_lookup(authors_path),
            )

        self.assertTrue(result["match_ok"])
        self.assertFalse(result["conflict_free"])
        self.assertEqual(len(result["standby_conflicts"]), 1)
        self.assertEqual(result["standby_conflicts"][0]["first_author_id"], 100)

    def test_load_listing_rows_accepts_multiline_intro_before_header(self) -> None:
        module = _load_verify_module()
        with tempfile.TemporaryDirectory() as tmpdir:
            listing_path = Path(tmpdir) / "proposal_listing.csv"
            listing_path.write_text(
                (
                    '"OHBM 2026 POSTER LISTING\n'
                    'POSTER HALL LOCATION: EXHIBITION HALL 1\n\n'
                    'Please use this document",,,,,,\n'
                    "Abstract ID Number,NEW POSTER NUMBER *USE THIS NUMBER FOR YOUR LOCATION IN THE POSTER HALL,First Stand-by Time,Second Stand-by Time,Abstract Title,Primary Category,Last Name of First Author\n"
                    '1,0001,"Monday, June 15 | 13:45-14:45","Tuesday, June 16 | 13:30-14:30",First title,Category A,Smith\n'
                ),
                encoding="utf-8",
            )

            rows = module.load_listing_rows(listing_path)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["Abstract ID Number"], "1")


if __name__ == "__main__":
    unittest.main()
