"""T022 — Stage 12 US3 — 3-column TOC + LaTeX-special escape.

The new TOC is a raw-LaTeX ``longtable`` block with columns
``Poster | Title | Page``. Page values come from the assembler's
`chunk_offsets` (1-based). Abstracts absent from `chunk_offsets`
(failure-isolated) MUST NOT appear in the TOC. Titles containing
LaTeX-special characters MUST be escaped so pandoc passes them
through cleanly.
"""

from __future__ import annotations

import unittest


class TestLatexEscape(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        try:
            from ohbm2026.book.assemble_pdf import _latex_escape
        except ImportError as exc:
            raise unittest.SkipTest(f"_latex_escape not yet implemented: {exc}")
        cls._escape = staticmethod(_latex_escape)

    def test_ampersand(self) -> None:
        self.assertEqual(self._escape("R&R study"), "R\\&R study")

    def test_percent(self) -> None:
        self.assertEqual(self._escape("90% accuracy"), "90\\% accuracy")

    def test_underscore(self) -> None:
        self.assertEqual(self._escape("test_one"), "test\\_one")

    def test_hash(self) -> None:
        self.assertEqual(self._escape("topic #1"), "topic \\#1")

    def test_braces(self) -> None:
        self.assertEqual(self._escape("{x} and {y}"), "\\{x\\} and \\{y\\}")

    def test_dollar(self) -> None:
        self.assertEqual(self._escape("cost $100"), "cost \\$100")

    def test_combined(self) -> None:
        # Multiple specials in one title.
        self.assertEqual(
            self._escape("A&B {x} 50% test_one #2 $cost"),
            "A\\&B \\{x\\} 50\\% test\\_one \\#2 \\$cost",
        )

    def test_plain_passes_through(self) -> None:
        self.assertEqual(self._escape("plain title"), "plain title")
        self.assertEqual(self._escape("UTF-8 Ümlaut"), "UTF-8 Ümlaut")


class TestBuildTocMarkdown(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        try:
            from ohbm2026.book.assemble_pdf import _build_toc_markdown
            from ohbm2026.book.model import (
                Author,
                BookEntry,
            )
        except ImportError as exc:
            raise unittest.SkipTest(f"_build_toc_markdown not yet implemented: {exc}")
        cls._build = staticmethod(_build_toc_markdown)
        cls.Author = Author
        cls.BookEntry = BookEntry

    def _entry(self, poster_id: int, title: str):
        return self.BookEntry(
            submission_id=900_000 + poster_id,
            poster_id=poster_id,
            title=title,
            accepted_for="Poster",
            authors=(),
            body_sections=(),
            figures=(),
            references=None,
            standby=None,
        )

    def test_emits_longtable_header_with_three_columns(self) -> None:
        entries = (
            self._entry(1, "First abstract"),
            self._entry(2, "Second abstract"),
        )
        chunk_offsets = {1: 5, 2: 9}
        md = self._build(entries, chunk_offsets)
        self.assertIn("longtable", md)
        # Column headers (Poster / Title / Page) appear in the rendered markdown.
        for header in ("Poster", "Title", "Page"):
            self.assertIn(header, md)

    def test_omits_failure_isolated_abstracts(self) -> None:
        entries = (
            self._entry(1, "First abstract"),
            self._entry(2, "Failed abstract"),
            self._entry(3, "Third abstract"),
        )
        # Abstract 2 is missing from chunk_offsets (failure-isolated).
        chunk_offsets = {1: 5, 3: 12}
        md = self._build(entries, chunk_offsets)
        # First + Third appear; Failed does NOT.
        self.assertIn("First abstract", md)
        self.assertIn("Third abstract", md)
        self.assertNotIn("Failed abstract", md)

    def test_page_column_matches_chunk_offset(self) -> None:
        entries = (self._entry(42, "Long title for poster 42"),)
        chunk_offsets = {42: 73}
        md = self._build(entries, chunk_offsets)
        # The page number 73 appears in the row.
        # The row layout is `poster_id & escaped_title & page \\`,
        # so the rendered markdown should contain "& 73".
        self.assertIn("73", md)

    def test_escapes_latex_special_chars_in_titles(self) -> None:
        entries = (self._entry(1, "R&R study with 90% accuracy"),)
        chunk_offsets = {1: 5}
        md = self._build(entries, chunk_offsets)
        # Both `&` and `%` must be escaped.
        self.assertIn("R\\&R", md)
        self.assertIn("90\\%", md)
        # The raw unescaped form must NOT appear (otherwise pandoc/Tectonic
        # would break on `&` inside a longtable row).
        self.assertNotIn("R&R", md)
        self.assertNotIn("90% accuracy", md)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
