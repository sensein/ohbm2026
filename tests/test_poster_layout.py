import json
import tempfile
import unittest
from pathlib import Path

import csv
import numpy as np

from ohbm2026 import poster_layout


def _response(parent: str, subcategory: str) -> dict[str, str]:
    return {
        "question_name": "Primary Parent Category & Sub-Category",
        "value": json.dumps([parent, subcategory]),
    }


def _abstract(
    abstract_id: int,
    accepted_for: str,
    title: str,
    parent: str,
    subcategory: str,
    first_author_id: int,
) -> dict[str, object]:
    return {
        "id": abstract_id,
        "accepted_for": accepted_for,
        "title": title,
        "authors": [{"author_order": 0, "id": first_author_id}],
        "responses": [_response(parent, subcategory)],
    }


class PosterLayoutTest(unittest.TestCase):
    @staticmethod
    def _collapse_label_runs(records: list[poster_layout.AcceptedAbstract], ordered_indices: list[int]) -> list[str]:
        records_by_embedding = {record.embedding_index: record for record in records}
        labels = [records_by_embedding[index].layout_exact_label for index in ordered_indices]
        collapsed: list[str] = []
        for label in labels:
            if not collapsed or collapsed[-1] != label:
                collapsed.append(label)
        return collapsed

    def _build_fixture(self, root: Path) -> tuple[Path, Path]:
        abstracts = [
            _abstract(1, "Poster", "A1 poster 1", "Systems", "Memory", 100),
            _abstract(2, "Poster", "A1 poster 2", "Systems", "Memory", 101),
            _abstract(3, "Poster", "A2 poster 1", "Systems", "Language", 100),
            _abstract(4, "Poster", "A2 poster 2", "Systems", "Language", 102),
            _abstract(5, "Poster", "B1 poster 1", "Methods", "Modeling", 103),
            _abstract(6, "Poster", "B1 poster 2", "Methods", "Modeling", 104),
            _abstract(7, "Poster", "B2 poster 1", "Methods", "Connectivity", 105),
            _abstract(8, "Poster", "B2 poster 2", "Methods", "Connectivity", 106),
            _abstract(9, "Oral", "A oral", "Systems", "Memory", 200),
            _abstract(10, "Oral", "B oral", "Methods", "Modeling", 201),
        ]
        raw_input = root / "abstracts.json"
        raw_input.write_text(json.dumps({"abstracts": abstracts}, indent=2), encoding="utf-8")

        embeddings_dir = root / "embeddings"
        embeddings_dir.mkdir(parents=True, exist_ok=True)
        matrix = np.asarray(
            [
                [1.0, 0.0, 0.0],
                [0.98, 0.02, 0.0],
                [0.9, 0.1, 0.0],
                [0.88, 0.12, 0.0],
                [0.0, 1.0, 0.0],
                [0.02, 0.98, 0.0],
                [0.0, 0.9, 0.1],
                [0.0, 0.88, 0.12],
                [0.96, 0.04, 0.0],
                [0.04, 0.96, 0.0],
            ],
            dtype=np.float32,
        )
        np.save(embeddings_dir / "vectors.npy", matrix)
        (embeddings_dir / "metadata.json").write_text(
            json.dumps(
                {
                    "embedding_name": "minilm_claims",
                    "embedding_fields": ["claims"],
                    "ids": list(range(1, 11)),
                    "metadata": [{"id": abstract_id, "accepted_for": "Poster", "title": str(abstract_id)} for abstract_id in range(1, 11)],
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        return raw_input, embeddings_dir

    def test_load_layout_inputs_extracts_posters_and_orals(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            raw_input, embeddings_dir = self._build_fixture(Path(tmpdir))

            inputs = poster_layout.load_layout_inputs(raw_input, embeddings_dir)

        self.assertEqual(len(inputs.records), 10)
        self.assertEqual(len(inputs.poster_records), 8)
        self.assertEqual(len(inputs.oral_records), 2)
        self.assertEqual(inputs.poster_records[0].primary_parent_category, "Systems")
        self.assertEqual(inputs.poster_records[0].primary_subcategory, "Memory")
        self.assertEqual(inputs.poster_records[0].layout_parent_label, "Systems")
        self.assertEqual(inputs.poster_records[0].layout_exact_label, "Systems :: Memory")
        self.assertEqual(inputs.layout_label_system, "submitter_primary_secondary")

    def test_load_layout_inputs_can_swap_in_semantic_layout_labels(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            raw_input, embeddings_dir = self._build_fixture(root)
            assignments_path = root / "semantic_assignments.json"
            summaries_path = root / "semantic_summaries.json"
            assignments_path.write_text(
                json.dumps({"assignments": {str(abstract_id): 0 if abstract_id <= 5 else 1 for abstract_id in range(1, 11)}}),
                encoding="utf-8",
            )
            summaries_path.write_text(
                json.dumps(
                    {
                        "clusters": [
                            {"cluster_id": 0, "label": "semantic cluster alpha"},
                            {"cluster_id": 1, "label": "semantic cluster beta"},
                        ]
                    }
                ),
                encoding="utf-8",
            )

            inputs = poster_layout.load_layout_inputs(
                raw_input,
                embeddings_dir,
                layout_cluster_assignments=assignments_path,
                layout_cluster_summaries=summaries_path,
                layout_label_system="semantic_fixture",
            )

        self.assertEqual(inputs.layout_label_system, "semantic_fixture")
        self.assertEqual(inputs.poster_records[0].layout_exact_label, "semantic cluster alpha")
        self.assertEqual(inputs.poster_records[-1].layout_exact_label, "semantic cluster beta")

    def test_build_block_numeric_order_can_share_category_order_across_blocks(self) -> None:
        records = [
            poster_layout.AcceptedAbstract(1, "Poster", "Alpha one", "Systems", "Memory", "Systems :: Memory", "Systems", "Systems :: Memory", "submitter_primary_secondary", 11, 0, None, None),
            poster_layout.AcceptedAbstract(2, "Poster", "Alpha two", "Systems", "Memory", "Systems :: Memory", "Systems", "Systems :: Memory", "submitter_primary_secondary", 12, 1, None, None),
            poster_layout.AcceptedAbstract(3, "Poster", "Beta one", "Systems", "Language", "Systems :: Language", "Systems", "Systems :: Language", "submitter_primary_secondary", 13, 2, None, None),
            poster_layout.AcceptedAbstract(4, "Poster", "Gamma one", "Methods", "Modeling", "Methods :: Modeling", "Methods", "Methods :: Modeling", "submitter_primary_secondary", 14, 3, None, None),
            poster_layout.AcceptedAbstract(5, "Poster", "Delta one", "Methods", "Connectivity", "Methods :: Connectivity", "Methods", "Methods :: Connectivity", "submitter_primary_secondary", 15, 4, None, None),
            poster_layout.AcceptedAbstract(6, "Poster", "Gamma two", "Methods", "Modeling", "Methods :: Modeling", "Methods", "Methods :: Modeling", "submitter_primary_secondary", 16, 5, None, None),
            poster_layout.AcceptedAbstract(7, "Poster", "Beta two", "Systems", "Language", "Systems :: Language", "Systems", "Systems :: Language", "submitter_primary_secondary", 17, 6, None, None),
            poster_layout.AcceptedAbstract(8, "Poster", "Delta two", "Methods", "Connectivity", "Methods :: Connectivity", "Methods", "Methods :: Connectivity", "submitter_primary_secondary", 18, 7, None, None),
        ]
        normalized_matrix = np.asarray(
            [
                [1.0, 0.0],
                [0.99, 0.01],
                [0.9, 0.1],
                [0.0, 1.0],
                [0.1, 0.9],
                [0.02, 0.98],
                [0.88, 0.12],
                [0.12, 0.88],
            ],
            dtype=np.float32,
        )
        normalized_matrix = poster_layout._normalize_rows(normalized_matrix)
        shared_parent_order, shared_subcategory_order = poster_layout.build_shared_layout_group_order(
            records,
            normalized_matrix,
        )
        block_one_records = [records[index] for index in (0, 2, 3, 4)]
        block_two_records = [records[index] for index in (1, 6, 5, 7)]

        block_one_order = poster_layout.build_block_numeric_order(
            block_one_records,
            normalized_matrix,
            shared_parent_order=shared_parent_order,
            shared_subcategory_order=shared_subcategory_order,
        )
        block_two_order = poster_layout.build_block_numeric_order(
            block_two_records,
            normalized_matrix,
            shared_parent_order=shared_parent_order,
            shared_subcategory_order=shared_subcategory_order,
        )

        self.assertEqual(
            self._collapse_label_runs(block_one_records, block_one_order),
            self._collapse_label_runs(block_two_records, block_two_order),
        )

    def test_standby_time_labels_follow_alternating_block_patterns(self) -> None:
        self.assertEqual(
            poster_layout.standby_time_labels_for_session(1),
            ("Monday, June 15 | 13:45-14:45", "Tuesday, June 16 | 13:30-14:30"),
        )
        self.assertEqual(
            poster_layout.standby_time_labels_for_session(2),
            ("Monday, June 15 | 14:45-15:45", "Tuesday, June 16 | 12:30-13:30"),
        )
        self.assertEqual(
            poster_layout.standby_time_labels_for_session(3),
            ("Wednesday, June 17 | 12:45-13:45", "Thursday, June 18 | 14:45-15:45"),
        )
        self.assertEqual(
            poster_layout.standby_time_labels_for_session(4),
            ("Wednesday, June 17 | 13:45-14:45", "Thursday, June 18 | 13:45-14:45"),
        )

    def test_optimize_main_writes_balanced_conflict_free_assignment(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            raw_input, embeddings_dir = self._build_fixture(root)
            output_dir = root / "poster_layout"

            result = poster_layout.optimize_main(
                [
                    "--raw-input",
                    str(raw_input),
                    "--embeddings-dir",
                    str(embeddings_dir),
                    "--output-dir",
                    str(output_dir),
                ]
            )

            self.assertEqual(result, 0)
            proposal = json.loads((output_dir / "proposal.json").read_text(encoding="utf-8"))
            proposal_listing = (output_dir / "proposal_listing.csv").read_text(encoding="utf-8")

        assignments = proposal["assignments"]
        self.assertEqual(len(assignments), 10)
        self.assertEqual([item["poster_number"] for item in assignments], list(range(1, 11)))
        session_counts = {
            session_id: sum(1 for item in assignments if item["standby_session"] == session_id)
            for session_id in poster_layout.SESSION_IDS
        }
        self.assertEqual(session_counts, {1: 3, 2: 3, 3: 2, 4: 2})
        for item in assignments:
            self.assertEqual(
                item["standby_session"],
                poster_layout.standby_session_for_block_and_poster_number(item["block_id"], item["poster_number"]),
            )
        assignments_by_id = {item["abstract_id"]: item for item in assignments}
        self.assertNotEqual(assignments_by_id[1]["standby_session"], assignments_by_id[3]["standby_session"])
        self.assertEqual(assignments[0]["hall_id"], 1)
        self.assertEqual(assignments[0]["hall_slot"], 1)
        self.assertEqual(assignments[0]["hall_row"], 1)
        self.assertEqual(assignments[0]["board_number"], 1)
        self.assertEqual(assignments[0]["board_side"], "A")
        self.assertEqual(assignments[0]["board_label"], "1A")
        expected_standby_times = poster_layout.standby_time_labels_for_session(assignments[0]["standby_session"])
        self.assertEqual(assignments[0]["first_standby_time_label"], expected_standby_times[0])
        self.assertEqual(assignments[0]["second_standby_time_label"], expected_standby_times[1])
        self.assertAlmostEqual(assignments[0]["hall_edge_x0"], 232.0)
        self.assertAlmostEqual(assignments[0]["hall_edge_x1"], 240.7, places=1)
        self.assertIn("OHBM 2026 POSTER LISTING", proposal_listing)
        self.assertIn("First Stand-by Time,Second Stand-by Time", proposal_listing)
        self.assertIn(assignments[0]["first_standby_time_label"], proposal_listing)

    def test_write_listing_csv_uses_utf8_bom_for_unicode_last_names(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            authors_path = root / "authors.json"
            listing_path = root / "proposal_listing.csv"
            authors_path.write_text(
                json.dumps({"authors": [{"id": 100, "last_name": "Tucić"}]}, indent=2),
                encoding="utf-8",
            )

            poster_layout.write_listing_csv(
                listing_path,
                {
                    "assignments": [
                        {
                            "abstract_id": 1,
                            "poster_number": 1,
                            "first_standby_time_label": "Monday, June 15 | 13:45-14:45",
                            "second_standby_time_label": "Tuesday, June 16 | 13:30-14:30",
                            "title": "Example title",
                            "primary_parent_category": "Category",
                            "first_author_id": 100,
                        }
                    ]
                },
                authors_input=authors_path,
            )

            raw_bytes = listing_path.read_bytes()

        self.assertTrue(raw_bytes.startswith(b"\xef\xbb\xbf"))
        self.assertIn("Tucić".encode("utf-8"), raw_bytes)

    def test_write_layout_csv_moves_categories_before_title_and_adds_neighbor_scores(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            voyage_dir = root / "voyage"
            claims_dir = root / "claims"
            for bundle_dir in (voyage_dir, claims_dir):
                bundle_dir.mkdir(parents=True, exist_ok=True)
                np.save(
                    bundle_dir / "vectors.npy",
                    np.asarray(
                        [
                            [1.0, 0.0],
                            [0.8, 0.2],
                            [0.0, 1.0],
                        ],
                        dtype=np.float32,
                    ),
                )
                (bundle_dir / "metadata.json").write_text(
                    json.dumps(
                        {
                            "ids": [1, 2, 3],
                            "metadata": [{"id": 1}, {"id": 2}, {"id": 3}],
                        }
                    ),
                    encoding="utf-8",
                )

            output_path = root / "proposal.csv"
            proposal = {
                "assignments": [
                    {
                        "poster_number": 1,
                        "abstract_id": 1,
                        "title": "One",
                        "primary_parent_category": "Parent A",
                        "primary_subcategory": "Sub A",
                        "primary_category": "Parent A :: Sub A",
                    },
                    {
                        "poster_number": 2,
                        "abstract_id": 2,
                        "title": "Two",
                        "primary_parent_category": "Parent A",
                        "primary_subcategory": "Sub B",
                        "primary_category": "Parent A :: Sub B",
                    },
                    {
                        "poster_number": 3,
                        "abstract_id": 3,
                        "title": "Three",
                        "primary_parent_category": "Parent B",
                        "primary_subcategory": "Sub C",
                        "primary_category": "Parent B :: Sub C",
                    },
                ]
            }

            previous_voyage_dir = poster_layout.DEFAULT_PROPOSAL_CSV_VOYAGE_EMBEDDINGS_DIR
            previous_claims_dir = poster_layout.DEFAULT_PROPOSAL_CSV_CLAIMS_EMBEDDINGS_DIR
            try:
                poster_layout.DEFAULT_PROPOSAL_CSV_VOYAGE_EMBEDDINGS_DIR = str(voyage_dir)
                poster_layout.DEFAULT_PROPOSAL_CSV_CLAIMS_EMBEDDINGS_DIR = str(claims_dir)
                poster_layout._load_optional_normalized_embedding_bundle.cache_clear()
                poster_layout.write_layout_csv(output_path, proposal)
            finally:
                poster_layout.DEFAULT_PROPOSAL_CSV_VOYAGE_EMBEDDINGS_DIR = previous_voyage_dir
                poster_layout.DEFAULT_PROPOSAL_CSV_CLAIMS_EMBEDDINGS_DIR = previous_claims_dir
                poster_layout._load_optional_normalized_embedding_bundle.cache_clear()

            with output_path.open("r", encoding="utf-8", newline="") as handle:
                reader = csv.DictReader(handle)
                fieldnames = list(reader.fieldnames or [])
                rows = list(reader)

        self.assertLess(fieldnames.index("primary_parent_category"), fieldnames.index("title"))
        self.assertLess(fieldnames.index("primary_subcategory"), fieldnames.index("title"))
        self.assertIn("voyage_stage2_neighbor5_mean_cosine_similarity", fieldnames)
        self.assertIn("claims_neighbor5_mean_cosine_similarity", fieldnames)
        self.assertAlmostEqual(float(rows[0]["voyage_stage2_neighbor5_mean_cosine_similarity"]), 0.485071, places=5)
        self.assertAlmostEqual(float(rows[1]["claims_neighbor5_mean_cosine_similarity"]), 0.606339, places=5)

    def test_analyze_main_reports_zero_conflicts_and_nearby_orals(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            raw_input, embeddings_dir = self._build_fixture(root)
            output_dir = root / "poster_layout"
            poster_layout.optimize_main(
                [
                    "--raw-input",
                    str(raw_input),
                    "--embeddings-dir",
                    str(embeddings_dir),
                    "--output-dir",
                    str(output_dir),
                ]
            )

            result = poster_layout.analyze_main(
                [
                    "--assignment",
                    str(output_dir / "proposal.json"),
                    "--raw-input",
                    str(raw_input),
                    "--embeddings-dir",
                    str(embeddings_dir),
                    "--output",
                    str(output_dir / "analysis.json"),
                    "--window-size",
                    "3",
                    "--oral-top-k",
                    "2",
                ]
            )

            self.assertEqual(result, 0)
            analysis = json.loads((output_dir / "analysis.json").read_text(encoding="utf-8"))

        self.assertEqual(len(analysis["oral_presentations"]), 2)
        for session_id in poster_layout.SESSION_IDS:
            session_summary = analysis["session_analysis"][str(session_id)]
            self.assertEqual(session_summary["author_conflicts"]["conflict_count"], 0)
            self.assertLessEqual(len(session_summary["nearest_oral_presentations"]), 2)
            self.assertIn("first_standby_time_label", session_summary)
            self.assertIn("second_standby_time_label", session_summary)
        self.assertTrue(all(item.get("assigned_session_id") in poster_layout.SESSION_IDS for item in analysis["oral_presentations"]))

    def test_layout_slot_for_block_position_snakes_across_rows(self) -> None:
        first = poster_layout.layout_slot_for_block_position(1)
        second = poster_layout.layout_slot_for_block_position(2)
        twentieth = poster_layout.layout_slot_for_block_position(20)
        twenty_first = poster_layout.layout_slot_for_block_position(21)
        sixtieth = poster_layout.layout_slot_for_block_position(60)
        sixty_first = poster_layout.layout_slot_for_block_position(61)
        one_hundred_twentieth = poster_layout.layout_slot_for_block_position(120)
        one_hundred_twenty_first = poster_layout.layout_slot_for_block_position(121)
        sixteen_hundred_eightieth = poster_layout.layout_slot_for_block_position(1680)

        self.assertEqual(first["hall_id"], 1)
        self.assertEqual(first["board_number"], 1)
        self.assertEqual(first["board_side"], "A")
        self.assertEqual(first["hall_row"], 1)
        self.assertEqual(first["hall_segment"], 1)
        self.assertEqual(first["hall_face_position"], 1)
        self.assertEqual(first["hall_row_direction"], "left_to_right")
        self.assertAlmostEqual(first["hall_edge_x0"], 232.0)
        self.assertAlmostEqual(first["hall_edge_x1"], 240.7, places=1)
        self.assertEqual(first["board_label"], "1A")

        self.assertEqual(second["board_number"], 2)
        self.assertEqual(second["board_side"], "A")
        self.assertEqual(second["hall_segment"], 1)
        self.assertEqual(second["hall_face_position"], 2)

        self.assertEqual(twentieth["board_number"], 20)
        self.assertEqual(twentieth["board_side"], "A")
        self.assertEqual(twentieth["hall_segment"], 2)
        self.assertEqual(twentieth["hall_face_position"], 10)
        self.assertEqual(twenty_first["board_number"], 21)
        self.assertEqual(twenty_first["board_side"], "A")
        self.assertEqual(twenty_first["hall_segment"], 3)
        self.assertEqual(twenty_first["hall_face_position"], 1)

        self.assertEqual(sixtieth["board_number"], 60)
        self.assertEqual(sixtieth["board_side"], "A")
        self.assertEqual(sixtieth["hall_row"], 1)
        self.assertEqual(sixtieth["hall_segment"], 6)
        self.assertEqual(sixtieth["hall_face_position"], 10)

        self.assertEqual(sixty_first["board_number"], 60)
        self.assertEqual(sixty_first["board_side"], "B")
        self.assertEqual(sixty_first["hall_row"], 1)
        self.assertEqual(sixty_first["hall_segment"], 6)
        self.assertEqual(sixty_first["hall_face_position"], 10)

        self.assertEqual(one_hundred_twentieth["board_number"], 1)
        self.assertEqual(one_hundred_twentieth["hall_row"], 1)
        self.assertEqual(one_hundred_twentieth["hall_segment"], 1)
        self.assertEqual(one_hundred_twentieth["hall_face_position"], 1)
        self.assertEqual(one_hundred_twentieth["board_side"], "B")

        self.assertEqual(one_hundred_twenty_first["board_number"], 120)
        self.assertEqual(one_hundred_twenty_first["hall_row"], 2)
        self.assertEqual(one_hundred_twenty_first["hall_segment"], 1)
        self.assertEqual(one_hundred_twenty_first["hall_face_position"], 1)
        self.assertEqual(one_hundred_twenty_first["hall_row_direction"], "right_to_left")
        self.assertEqual(one_hundred_twenty_first["board_side"], "A")

        self.assertEqual(sixteen_hundred_eightieth["board_number"], 840)
        self.assertEqual(sixteen_hundred_eightieth["board_side"], "B")
        self.assertEqual(sixteen_hundred_eightieth["hall_row"], 14)

    def test_assign_block_sequences_to_sessions_prefers_alternating_within_block(self) -> None:
        records_by_id = {
            1: poster_layout.AcceptedAbstract(1, "Poster", "One", "A", "A1", "A :: A1", "A", "A :: A1", "submitter_primary_secondary", 11, 0, None, None),
            2: poster_layout.AcceptedAbstract(2, "Poster", "Two", "A", "A1", "A :: A1", "A", "A :: A1", "submitter_primary_secondary", 12, 1, None, None),
            3: poster_layout.AcceptedAbstract(3, "Poster", "Three", "A", "A1", "A :: A1", "A", "A :: A1", "submitter_primary_secondary", 13, 2, None, None),
            4: poster_layout.AcceptedAbstract(4, "Poster", "Four", "A", "A1", "A :: A1", "A", "A :: A1", "submitter_primary_secondary", 14, 3, None, None),
            5: poster_layout.AcceptedAbstract(5, "Poster", "Five", "B", "B1", "B :: B1", "B", "B :: B1", "submitter_primary_secondary", 15, 4, None, None),
            6: poster_layout.AcceptedAbstract(6, "Poster", "Six", "B", "B1", "B :: B1", "B", "B :: B1", "submitter_primary_secondary", 16, 5, None, None),
            7: poster_layout.AcceptedAbstract(7, "Poster", "Seven", "B", "B1", "B :: B1", "B", "B :: B1", "submitter_primary_secondary", 17, 6, None, None),
            8: poster_layout.AcceptedAbstract(8, "Poster", "Eight", "B", "B1", "B :: B1", "B", "B :: B1", "submitter_primary_secondary", 18, 7, None, None),
        }

        assignments = poster_layout.assign_block_sequences_to_sessions(
            {1: [1, 2, 3, 4], 2: [5, 6, 7, 8]},
            records_by_id,
        )

        self.assertEqual([assignments[1], assignments[2], assignments[3], assignments[4]], [1, 2, 1, 2])
        self.assertEqual([assignments[5], assignments[6], assignments[7], assignments[8]], [3, 4, 3, 4])


if __name__ == "__main__":
    unittest.main()
