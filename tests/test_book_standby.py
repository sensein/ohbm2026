"""Standby integration tests.

Covers (a) the standby parser shape, (b) load_book attaching the
times to each BookEntry, (c) the rendered `book.md` carrying a
"Standby" line, and (d) orphan poster_ids being silently dropped.
"""

from __future__ import annotations

import pathlib
import tempfile
import unittest

from ohbm2026.standby import (
    StandbyTimes as _ParserStandbyTimes,
    load_standby_csv,
    parse_window,
)

_FIX = pathlib.Path(__file__).parent / "fixtures" / "book"


class TestParser(unittest.TestCase):
    def test_window_round_trip(self) -> None:
        w = parse_window("Monday, June 15 | 13:45-14:45")
        self.assertIsNotNone(w)
        # CEST (UTC+2) → UTC subtracts 2 hours.
        self.assertEqual(w.start_utc.strftime("%Y-%m-%dT%H:%MZ"), "2026-06-15T11:45Z")
        self.assertEqual(w.end_utc.strftime("%Y-%m-%dT%H:%MZ"), "2026-06-15T12:45Z")
        self.assertEqual(w.label, "Monday, June 15 | 13:45-14:45")

    def test_window_malformed_returns_none(self) -> None:
        self.assertIsNone(parse_window(""))
        self.assertIsNone(parse_window("not a time"))
        self.assertIsNone(parse_window("Monday, June 32 | 13:45-14:45"))

    def test_load_csv_fixture(self) -> None:
        m = load_standby_csv(_FIX / "standby.csv")
        # 6 data rows in the fixture (5 accepted-matched + 1 orphan).
        self.assertEqual(set(m), {1, 2, 3, 4, 5, 9999})
        self.assertIsInstance(m[1], _ParserStandbyTimes)
        self.assertEqual(
            m[1].first.label, "Monday, June 15 | 13:45-14:45"
        )

    def test_missing_header_raises(self) -> None:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".csv", delete=False
        ) as f:
            f.write("title row only\n")
            path = pathlib.Path(f.name)
        try:
            with self.assertRaises(ValueError):
                load_standby_csv(path)
        finally:
            path.unlink(missing_ok=True)


class TestLoadBookWithStandby(unittest.TestCase):
    def setUp(self) -> None:
        from ohbm2026.book.corpus import load_book

        self.book = load_book(
            corpus_path=_FIX / "abstracts.json",
            authors_path=_FIX / "authors.json",
            withdrawn_path=_FIX / "abstracts_withdrawn.json",
            assets_root=_FIX / "assets",
            standby_path=_FIX / "standby.csv",
        )

    def test_every_accepted_entry_has_standby(self) -> None:
        for entry in self.book.entries:
            self.assertIsNotNone(
                entry.standby,
                msg=f"entry {entry.poster_id} missing standby",
            )

    def test_labels_match_csv(self) -> None:
        by_pid = {e.poster_id: e for e in self.book.entries}
        self.assertEqual(
            by_pid[1].standby.first.label,
            "Monday, June 15 | 13:45-14:45",
        )
        self.assertEqual(
            by_pid[1].standby.second.label,
            "Tuesday, June 16 | 12:30-13:30",
        )

    def test_start_utc_iso_normalised(self) -> None:
        by_pid = {e.poster_id: e for e in self.book.entries}
        self.assertEqual(
            by_pid[1].standby.first.start_utc_iso,
            "2026-06-15T11:45:00Z",
        )

    def test_no_standby_when_path_omitted(self) -> None:
        from ohbm2026.book.corpus import load_book

        book = load_book(
            corpus_path=_FIX / "abstracts.json",
            authors_path=_FIX / "authors.json",
            withdrawn_path=_FIX / "abstracts_withdrawn.json",
            assets_root=_FIX / "assets",
            standby_path=None,
        )
        for entry in book.entries:
            self.assertIsNone(entry.standby)


class TestMarkdownStandbyLine(unittest.TestCase):
    def setUp(self) -> None:
        from dataclasses import replace
        from ohbm2026.book.author_index import build_author_index
        from ohbm2026.book.corpus import load_book
        from ohbm2026.book.render_markdown import emit_book_md
        from ohbm2026.book.sort import by_poster_id

        self.tmp = tempfile.TemporaryDirectory()
        self.outdir = pathlib.Path(self.tmp.name)
        book = load_book(
            corpus_path=_FIX / "abstracts.json",
            authors_path=_FIX / "authors.json",
            withdrawn_path=_FIX / "abstracts_withdrawn.json",
            assets_root=_FIX / "assets",
            standby_path=_FIX / "standby.csv",
        )
        entries = by_poster_id(book.entries)
        book = replace(
            book, entries=entries, author_index=build_author_index(entries)
        )
        emit_book_md(book, self.outdir)
        self.text = (self.outdir / "book.md").read_text()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_standby_line_present_per_entry(self) -> None:
        # Each accepted entry should have one "**Standby**:" line.
        self.assertEqual(
            self.text.count("**Standby**:"),
            5,
            msg="expected one Standby line per surviving entry",
        )

    def test_csv_label_verbatim(self) -> None:
        # The user sees the local-time CSV label, not the UTC ISO form.
        self.assertIn("Monday, June 15 | 13:45-14:45", self.text)
        self.assertIn("Tuesday, June 16 | 12:30-13:30", self.text)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
