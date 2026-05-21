"""T021 — Stage 11.1 US2 parquet standby-slots derivation.

Verifies the v2 schema mechanics (no UI involvement):
- ``derive_standby_slots`` produces dense 0..N-1 ordered slot_indexes
- per-abstract ``(first_idx, second_idx)`` lookup matches the legacy
  v1 datetime pair byte-for-byte after lookup
- orphan abstracts (absent from standby data) get ``(None, None)``
- display_label format matches what the UI's existing
  ``standbyBlockKey`` emits — so v2 records carry already-rendered
  labels and the UI can drop its ``Intl.DateTimeFormat`` work entirely.

Pure Python — no parquet I/O — to keep the test fast + portable.
"""

from __future__ import annotations

import datetime as _dt
import unittest


_CEST = _dt.timezone(_dt.timedelta(hours=2))
_UTC = _dt.timezone.utc


def _utc(year: int, month: int, day: int, hour: int, minute: int) -> _dt.datetime:
    return _dt.datetime(year, month, day, hour, minute, tzinfo=_CEST).astimezone(_UTC)


class TestDeriveStandbySlots(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        try:
            from ohbm2026.ui_data.standby_slots import (
                build_poster_to_index_map,
                derive_standby_slots,
            )
        except ImportError as exc:
            raise unittest.SkipTest(
                f"ohbm2026.ui_data.standby_slots not yet implemented: {exc}"
            )
        cls.derive = staticmethod(derive_standby_slots)
        cls.build_map = staticmethod(build_poster_to_index_map)

    def setUp(self) -> None:
        # 8 distinct OHBM 2026-shaped windows, intentionally NOT sorted
        # in input order so we can assert the sort happens inside the
        # function. Each window is exactly 1 hour.
        self.standby_by_pid = {
            1001: {
                "first": _utc(2026, 6, 16, 13, 45),  # Day 2 (Tue), 13:45 Paris
                "second": _utc(2026, 6, 17, 12, 45),  # Day 3 (Wed), 12:45 Paris
            },
            1002: {
                "first": _utc(2026, 6, 15, 12, 45),  # Day 1 (Mon), 12:45 Paris
                "second": _utc(2026, 6, 18, 13, 45),  # Day 4 (Thu), 13:45 Paris
            },
            1003: {
                "first": _utc(2026, 6, 17, 12, 45),  # same as 1001's second
                "second": _utc(2026, 6, 18, 12, 45),  # Day 4 (Thu), 12:45 Paris
            },
            1004: {
                "first": _utc(2026, 6, 15, 13, 45),  # Day 1 (Mon), 13:45 Paris
                "second": _utc(2026, 6, 16, 12, 45),  # Day 2 (Tue), 12:45 Paris
            },
        }
        # An "orphan" poster with no standby data.
        self.orphan_pid = 1099

    def test_slots_are_dense_and_chronological(self) -> None:
        slots = self.derive(self.standby_by_pid)
        # 7 distinct windows across the 4-abstract fixture:
        # pid 1003's "first" duplicates pid 1001's "second" (same
        # Day-3 12:45 slot), so the dedupe collapses to 7. Exercises
        # the dedupe path explicitly.
        self.assertEqual(len(slots), 7)
        # slot_index dense 0..N-1.
        self.assertEqual([s["slot_index"] for s in slots], list(range(7)))
        # start_utc strictly ascending.
        starts = [s["start_utc"] for s in slots]
        self.assertEqual(starts, sorted(starts))

    def test_each_slot_has_paris_local_display_label(self) -> None:
        slots = self.derive(self.standby_by_pid)
        # First chronological slot is Mon Jun 15 12:45 Paris.
        first_label = slots[0]["display_label"]
        # Format: "Day N (Wkd Mon DD) · HH:MM-HH:MM" per US2 contract,
        # matching the UI's existing standbyBlockKey output for v1.
        self.assertIn("Day 1", first_label)
        self.assertIn("Mon Jun 15", first_label)
        self.assertIn("12:45", first_label)
        self.assertIn("13:45", first_label)
        # Last is Thu Jun 18 13:45 Paris.
        last_label = slots[-1]["display_label"]
        self.assertIn("Day 4", last_label)
        self.assertIn("Thu Jun 18", last_label)

    def test_end_utc_is_start_plus_one_hour(self) -> None:
        slots = self.derive(self.standby_by_pid)
        for s in slots:
            self.assertEqual(
                s["end_utc"] - s["start_utc"],
                _dt.timedelta(hours=1),
            )

    def test_poster_to_index_lookup_matches_legacy_datetime_pair(self) -> None:
        slots = self.derive(self.standby_by_pid)
        lookup = self.build_map(self.standby_by_pid, slots)

        # Re-derive the slot_index for each abstract via the lookup and
        # confirm the stored start_utc in slots[idx] matches the
        # legacy datetime exactly (round-trip equivalence).
        for pid, times in self.standby_by_pid.items():
            first_idx, second_idx = lookup[pid]
            self.assertIsNotNone(first_idx, f"pid={pid} missing first_idx")
            self.assertIsNotNone(second_idx, f"pid={pid} missing second_idx")
            self.assertEqual(slots[first_idx]["start_utc"], times["first"])
            self.assertEqual(slots[second_idx]["start_utc"], times["second"])

    def test_orphan_abstract_gets_null_indices(self) -> None:
        slots = self.derive(self.standby_by_pid)
        lookup = self.build_map(self.standby_by_pid, slots)
        # An orphan pid not present in input gets no entry in lookup;
        # callers downstream interpret absence as (None, None).
        self.assertNotIn(self.orphan_pid, lookup)


class TestParquetSchemaVersionBump(unittest.TestCase):
    """The parquet emitter MUST bump the format version when emitting
    the new shape so the in-browser decoder can dispatch correctly.
    """

    @classmethod
    def setUpClass(cls) -> None:
        try:
            from ohbm2026.ui_data.formats import parquet_single  # noqa: F401
        except ImportError as exc:
            raise unittest.SkipTest(f"parquet_single module not importable: {exc}")
        cls.module = parquet_single

    def test_format_version_is_v2(self) -> None:
        self.assertEqual(self.module.PARQUET_FORMAT_VERSION, "parquet-single.v2")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
