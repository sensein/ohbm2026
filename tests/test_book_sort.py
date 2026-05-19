"""T029 — alternate sort orders (title + first_author)."""

from __future__ import annotations

import pathlib
import unittest

from ohbm2026.book.corpus import load_book
from ohbm2026.book.sort import by_first_author, by_poster_id, by_title

_FIX = pathlib.Path(__file__).parent / "fixtures" / "book"


def _book():
    return load_book(
        corpus_path=_FIX / "abstracts.json",
        authors_path=_FIX / "authors.json",
        withdrawn_path=_FIX / "abstracts_withdrawn.json",
        assets_root=_FIX / "assets",
    )


class TestSortOrders(unittest.TestCase):
    def setUp(self) -> None:
        self.book = _book()
        self.original = self.book.entries

    def test_poster_id_ascending(self) -> None:
        sorted_ = by_poster_id(self.original)
        self.assertEqual(
            [e.poster_id for e in sorted_],
            sorted(e.poster_id for e in self.original),
        )

    def test_title_lexicographic_case_insensitive(self) -> None:
        sorted_ = by_title(self.original)
        titles = [e.title.casefold() for e in sorted_]
        self.assertEqual(titles, sorted(titles))

    def test_first_author_surname_then_given(self) -> None:
        sorted_ = by_first_author(self.original)
        keys = [
            (
                e.authors[0].last_name.casefold() if e.authors else "",
                e.authors[0].first_name.casefold() if e.authors else "",
                e.title.casefold(),
            )
            for e in sorted_
        ]
        self.assertEqual(keys, sorted(keys))

    def test_each_strategy_preserves_set(self) -> None:
        original_ids = {e.submission_id for e in self.original}
        for strat in (by_poster_id, by_title, by_first_author):
            self.assertEqual(
                {e.submission_id for e in strat(self.original)},
                original_ids,
                msg=f"{strat.__name__} dropped or duplicated entries",
            )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
