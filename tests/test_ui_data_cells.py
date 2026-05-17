"""T015 — cells builder positional-join test."""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from ohbm2026.ui_data.cells import build_cells, build_cells_shards

from tests._ui_data_fixtures import BUILD_INFO, write_fixtures


class TestCellsPositionalJoin(unittest.TestCase):
    def test_positional_join_matches_abstract_id_order(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = write_fixtures(Path(tmp))
            shards = build_cells_shards(
                rollup_db=paths["rollup"],
                abstract_ids=[1001, 1003],
            )
        for cell_key, rows in shards.items():
            self.assertEqual(len(rows), 2, msg=f"cell {cell_key} length")
            self.assertEqual(rows[0]["abstract_id"], 1001)
            self.assertEqual(rows[1]["abstract_id"], 1003)

    def test_neuroscape_cells_carry_extra_fields(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = write_fixtures(Path(tmp))
            shards = build_cells_shards(
                rollup_db=paths["rollup"],
                abstract_ids=[1001, 1003],
            )
        ns = shards["neuroscape_abstract"]
        self.assertIn("neuroscape_cluster_id", ns[0])
        self.assertIn("neuroscape_cluster_distance", ns[0])
        # Non-neuroscape cells should NOT carry these.
        ml = shards["minilm_methods"]
        self.assertNotIn("neuroscape_cluster_id", ml[0])

    def test_envelope_carries_build_info(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = write_fixtures(Path(tmp))
            envelopes = build_cells(
                rollup_db=paths["rollup"],
                abstract_ids=[1001, 1003],
                build_info=BUILD_INFO,
            )
        for envelope in envelopes.values():
            self.assertEqual(envelope["schema_version"], "cell.v1")
            self.assertEqual(envelope["build_info"], BUILD_INFO)
            self.assertIn("cell_key", envelope)
            self.assertIn("rows", envelope)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
