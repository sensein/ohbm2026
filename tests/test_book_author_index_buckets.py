"""T028 — Stage 12 US4 — author-index letter-bucket headers.

The hand-rolled author index (`assemble_pdf._build_index_markdown`)
groups entries by Unicode-folded last-name initial and emits a
``## A`` / ``## B`` / ... / ``## Z`` / ``## Other`` heading before
each non-empty bucket.
"""

from __future__ import annotations

import unittest


class TestBucketLetter(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        try:
            from ohbm2026.book.assemble_pdf import _bucket_letter
        except ImportError as exc:
            raise unittest.SkipTest(f"_bucket_letter not yet implemented: {exc}")
        cls._bucket = staticmethod(_bucket_letter)

    def test_basic_ascii_uppercases_first_letter(self) -> None:
        self.assertEqual(self._bucket("Adams"), "A")
        self.assertEqual(self._bucket("baker"), "B")
        self.assertEqual(self._bucket("Zhang"), "Z")

    def test_unicode_accented_folds_to_ascii(self) -> None:
        self.assertEqual(self._bucket("Östen"), "O")
        self.assertEqual(self._bucket("Århus"), "A")
        self.assertEqual(self._bucket("Ñoñez"), "N")
        self.assertEqual(self._bucket("Šafarik"), "S")
        self.assertEqual(self._bucket("Èric"), "E")

    def test_numeric_or_symbol_initial_goes_to_other(self) -> None:
        self.assertEqual(self._bucket("1st"), "Other")
        self.assertEqual(self._bucket("@reply"), "Other")
        self.assertEqual(self._bucket("---empty---"), "Other")

    def test_empty_string_goes_to_other(self) -> None:
        self.assertEqual(self._bucket(""), "Other")
        self.assertEqual(self._bucket("   "), "Other")


class TestBuildIndexMarkdownBuckets(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        try:
            from ohbm2026.book.assemble_pdf import _build_index_markdown
            from ohbm2026.book.model import AuthorIndexEntry
        except ImportError as exc:
            raise unittest.SkipTest(f"index helpers not yet implemented: {exc}")
        cls._build = staticmethod(_build_index_markdown)
        cls.Entry = AuthorIndexEntry

    def _entry(self, display: str, last_first: tuple[str, str], poster_ids: tuple[int, ...]) -> object:
        return self.Entry(
            display_name=display,
            latex_index_key=display,
            sort_key=last_first,
            poster_ids=poster_ids,
        )

    def test_emits_letter_headers_in_alpha_order_with_other_last(self) -> None:
        # Mixed fixture: A, O (folded from Ö), 1 (→ Other).
        author_index = (
            self._entry("Adams, A.", ("adams", "a"), (1,)),
            self._entry("Östen, B.", ("östen", "b"), (2,)),
            self._entry("1st, C.", ("1st", "c"), (3,)),
        )
        offsets = {1: 5, 2: 7, 3: 12}
        md = self._build(author_index, offsets, first_appendix_page=15)
        # Headers appear in order: A first, then O, then Other.
        idx_a = md.find("## A")
        idx_o = md.find("## O")
        idx_other = md.find("## Other")
        self.assertGreater(idx_a, 0)
        self.assertGreater(idx_o, idx_a)
        self.assertGreater(idx_other, idx_o)
        # No `## B` heading because no B-surnames exist.
        self.assertNotIn("## B", md)

    def test_omits_empty_buckets(self) -> None:
        # Only one A entry → only `## A` heading, no `## B`...`## Z` / `## Other`.
        author_index = (self._entry("Adams, A.", ("adams", "a"), (1,)),)
        offsets = {1: 5}
        md = self._build(author_index, offsets, first_appendix_page=10)
        self.assertIn("## A", md)
        for letter in "BCDEFGHIJKLMNOPQRSTUVWXYZ":
            self.assertNotIn(f"## {letter}", md)
        self.assertNotIn("## Other", md)

    def test_entries_within_bucket_preserve_sort_order(self) -> None:
        # Three A-surnames in the order they're passed.
        author_index = (
            self._entry("Adams, A.", ("adams", "a"), (1,)),
            self._entry("Albright, B.", ("albright", "b"), (2,)),
            self._entry("Anders, C.", ("anders", "c"), (3,)),
        )
        offsets = {1: 5, 2: 7, 3: 12}
        md = self._build(author_index, offsets, first_appendix_page=15)
        # Display names appear in the order they were passed (which is
        # the existing sort order from build_author_index).
        idx_adams = md.find("Adams, A.")
        idx_albright = md.find("Albright, B.")
        idx_anders = md.find("Anders, C.")
        self.assertGreater(idx_adams, 0)
        self.assertGreater(idx_albright, idx_adams)
        self.assertGreater(idx_anders, idx_albright)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
