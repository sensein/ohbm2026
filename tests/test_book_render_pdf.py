"""T017 — pandoc → PDF render (skip if pandoc / xelatex absent)."""

from __future__ import annotations

import pathlib
import shutil
import subprocess
import tempfile
import unittest


_FIX = pathlib.Path(__file__).parent / "fixtures" / "book"


def _pandoc_ok() -> bool:
    """True when pandoc and at least one LaTeX engine are on PATH."""
    if not shutil.which("pandoc"):
        return False
    return bool(shutil.which("xelatex")) or bool(shutil.which("tectonic"))


@unittest.skipUnless(
    _pandoc_ok(),
    "pandoc + a LaTeX engine (xelatex or tectonic) not on PATH; skipping PDF render test",
)
class TestBookRenderPdf(unittest.TestCase):
    def setUp(self) -> None:
        try:
            from ohbm2026.book.author_index import build_author_index
            from ohbm2026.book.corpus import load_book
            from ohbm2026.book.render_markdown import emit_book_md
            from ohbm2026.book.render_via_pandoc import to_pdf
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
            format="pdf",
        )
        emit_book_md(book, self.outdir)
        self.pdf_path = self.outdir / "book.pdf"
        self.book = book
        # Stage 11.1 — to_pdf is now the per-abstract orchestrator;
        # capture the AssembledBook so the page-floor test can read
        # the measured index_pages.
        self.assembled = to_pdf(
            book,
            self.outdir,
            self.pdf_path,
            style="plain",
            workers=1,  # serial keeps the test deterministic and fast
            cache_dir=self.outdir / ".cache",
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_pandoc_emitted_pdf(self) -> None:
        self.assertTrue(self.pdf_path.exists())
        self.assertGreater(self.pdf_path.stat().st_size, 1024)

    def test_page_count_floor(self) -> None:
        import json
        import pikepdf

        with pikepdf.Pdf.open(self.pdf_path) as pdf:
            page_count = len(pdf.pages)

        # Stage 11.1 floor: front-matter (>= 1 page) + N abstract chunks
        # (>= 1 page each) + measured index appendix (>= 1 page).
        # Reads index_pages from provenance.json's assembly metadata when
        # available (post-Stage-11.1 builds); falls back to a >= 1
        # conservative floor when the build is the legacy single-pass
        # path that doesn't write the field.
        prov_path = self.outdir / "provenance.json"
        index_pages = 1
        if prov_path.exists():
            prov = json.loads(prov_path.read_text())
            measured = prov.get("index_pages")
            if isinstance(measured, int) and measured >= 1:
                index_pages = measured
        # Title page (>= 1) + N abstract pages (>= 1 each) +
        # index_pages (>= measured).
        self.assertGreaterEqual(
            page_count,
            len(self.book.entries) + index_pages + 1,
        )

    def test_pdftotext_byte_identical_on_rerun(self) -> None:
        from ohbm2026.book.render_via_pandoc import to_pdf
        from ohbm2026.book.render_markdown import emit_book_md

        with tempfile.TemporaryDirectory() as tmp2:
            other_dir = pathlib.Path(tmp2)
            emit_book_md(self.book, other_dir)
            other = other_dir / "book.pdf"
            # Re-render via the Stage 11.1 orchestrator with a fresh
            # cache so the result is independent of setUp's run.
            to_pdf(
                self.book,
                other_dir,
                other,
                style="plain",
                workers=1,
                cache_dir=other_dir / ".cache",
            )
            if not shutil.which("pdftotext"):
                self.skipTest("pdftotext not on PATH")
            a = subprocess.check_output(["pdftotext", str(self.pdf_path), "-"])
            b = subprocess.check_output(["pdftotext", str(other), "-"])
        self.assertEqual(a, b, "PDF body content differs on re-run")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
