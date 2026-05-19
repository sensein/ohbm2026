"""T032 — pandoc → DOCX render (skip if pandoc absent)."""

from __future__ import annotations

import pathlib
import shutil
import subprocess
import tempfile
import unittest


_FIX = pathlib.Path(__file__).parent / "fixtures" / "book"


def _pandoc_ok() -> bool:
    return bool(shutil.which("pandoc"))


@unittest.skipUnless(_pandoc_ok(), "pandoc not on PATH; skipping DOCX render test")
class TestBookRenderDocx(unittest.TestCase):
    def setUp(self) -> None:
        try:
            from ohbm2026.book.author_index import build_author_index
            from ohbm2026.book.corpus import load_book
            from ohbm2026.book.render_markdown import emit_book_md
            from ohbm2026.book.render_via_pandoc import to_docx
            from ohbm2026.book.sort import by_poster_id
        except ImportError:
            self.skipTest("renderers not yet implemented")
        from dataclasses import replace

        self.tmp = tempfile.TemporaryDirectory()
        self.outdir = pathlib.Path(self.tmp.name)
        book = load_book(
            corpus_path=_FIX / "abstracts.json",
            authors_path=_FIX / "authors.json",
            withdrawn_path=_FIX / "abstracts_withdrawn.json",
            assets_root=_FIX / "assets",
        )
        entries = by_poster_id(book.entries)
        book = replace(
            book,
            entries=entries,
            author_index=build_author_index(entries),
            format="docx",
        )
        emit_book_md(book, self.outdir)
        self.docx_path = self.outdir / "book.docx"
        self.book = book
        to_docx(self.outdir / "book.md", self.docx_path)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_docx_emitted(self) -> None:
        self.assertTrue(self.docx_path.exists())
        self.assertGreater(self.docx_path.stat().st_size, 1024)

    def test_opens_with_python_docx(self) -> None:
        from docx import Document  # type: ignore[import-not-found]

        doc = Document(str(self.docx_path))
        headings = [
            p.text for p in doc.paragraphs if p.style and p.style.name.startswith("Heading")
        ]
        self.assertGreaterEqual(
            len(headings),
            len(self.book.entries),
            msg=f"expected ≥ {len(self.book.entries)} headings; got {len(headings)}",
        )

    def test_pandoc_plaintext_byte_identical_on_rerun(self) -> None:
        from ohbm2026.book.render_via_pandoc import to_docx

        with tempfile.TemporaryDirectory() as tmp2:
            other = pathlib.Path(tmp2) / "book.docx"
            to_docx(self.outdir / "book.md", other)
            pandoc = shutil.which("pandoc")
            if not pandoc:
                self.skipTest("pandoc not on PATH")
            a = subprocess.check_output(
                [pandoc, str(self.docx_path), "-t", "plain"]
            )
            b = subprocess.check_output([pandoc, str(other), "-t", "plain"])
        self.assertEqual(a, b)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
