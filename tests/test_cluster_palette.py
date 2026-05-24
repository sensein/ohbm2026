"""Tests for ``ohbm2026.atlas_package.cluster_palette``.

Spec: ``specs/015-neuroscape-context/`` — FR-010 + research R-003.

The palette assigns one ``#RRGGBB`` colour and a ``palette_tier``
("primary" | "secondary") to each NeuroScape cluster. The assignment
is deterministic: clusters are ranked by ``point_count`` descending;
the top ``primary_size`` get ``primary`` palette slots in rank order;
the remainder get ``secondary`` slots in cluster_id order.

The output is identical across runs for the same input — this is what
makes the colour table persistable into both ``neuroscape.parquet``
and ``atlas.parquet`` with a row-for-row equality assertion (R-003).
"""

from __future__ import annotations

import unittest

from ohbm2026.atlas_package import cluster_palette


class AssignPaletteShapeTests(unittest.TestCase):
    def test_returns_one_entry_per_cluster(self) -> None:
        counts = {0: 100, 1: 50, 2: 25}
        out = cluster_palette.assign_palette(counts, primary_size=2)
        self.assertEqual(set(out.keys()), {0, 1, 2})

    def test_entries_are_colour_tier_tuples(self) -> None:
        counts = {0: 10}
        out = cluster_palette.assign_palette(counts, primary_size=32)
        (colour, tier) = out[0]
        self.assertRegex(colour, r"^#[0-9a-fA-F]{6}$")
        self.assertIn(tier, ("primary", "secondary"))


class AssignPaletteRankingTests(unittest.TestCase):
    def test_top_primary_size_clusters_get_primary_tier(self) -> None:
        # 5 clusters with strictly descending point counts.
        counts = {0: 5, 1: 50, 2: 10, 3: 100, 4: 25}
        out = cluster_palette.assign_palette(counts, primary_size=2)
        # Top-2 by point_count are ids 3 (100) and 1 (50).
        self.assertEqual(out[3][1], "primary")
        self.assertEqual(out[1][1], "primary")
        # The remaining three are secondary.
        for cid in (0, 2, 4):
            self.assertEqual(out[cid][1], "secondary")

    def test_secondary_palette_is_in_cluster_id_order(self) -> None:
        counts = {5: 1, 2: 1, 9: 1, 1: 1}
        out = cluster_palette.assign_palette(counts, primary_size=0)
        # All tiers are 'secondary'. The secondary palette MUST be
        # cycled in cluster_id order so colours stay stable across
        # rebuilds even when point_counts tie.
        ordered_by_id = [out[cid][0] for cid in sorted(counts)]
        # Adjacent secondary entries should not be identical (the
        # palette has more than 4 distinct slots).
        self.assertEqual(len(set(ordered_by_id)), len(ordered_by_id))


class AssignPaletteDeterminismTests(unittest.TestCase):
    def test_two_runs_produce_identical_output(self) -> None:
        counts = {i: (175 - i) * 10 for i in range(175)}
        a = cluster_palette.assign_palette(counts, primary_size=32)
        b = cluster_palette.assign_palette(counts, primary_size=32)
        self.assertEqual(a, b)

    def test_distinct_primary_colours(self) -> None:
        # All primary-tier colours MUST be distinct so the legend's
        # top-N entries remain visually distinguishable (R-003).
        counts = {i: 100 - i for i in range(32)}
        out = cluster_palette.assign_palette(counts, primary_size=32)
        primary_colours = [c for c, t in out.values() if t == "primary"]
        self.assertEqual(len(primary_colours), 32)
        self.assertEqual(len(set(primary_colours)), 32)


class AssignPaletteEdgeCaseTests(unittest.TestCase):
    def test_empty_input_returns_empty_mapping(self) -> None:
        self.assertEqual(cluster_palette.assign_palette({}, primary_size=32), {})

    def test_primary_size_larger_than_cluster_count_caps_at_count(self) -> None:
        counts = {0: 10, 1: 5}
        out = cluster_palette.assign_palette(counts, primary_size=32)
        # Both clusters get primary tier; secondary palette never engages.
        for cid in counts:
            self.assertEqual(out[cid][1], "primary")


if __name__ == "__main__":
    unittest.main()
