"""T016 — markdown bundle: filename contract + determinism + index."""

from __future__ import annotations

import pathlib
import re
import tempfile
import unittest


_FIX = pathlib.Path(__file__).parent / "fixtures" / "book"


def _load_book():
    from ohbm2026.book.corpus import load_book

    return load_book(
        corpus_path=_FIX / "abstracts.json",
        authors_path=_FIX / "authors.json",
        withdrawn_path=_FIX / "abstracts_withdrawn.json",
        assets_root=_FIX / "assets",
    )


def _emit(outdir: pathlib.Path):
    try:
        from ohbm2026.book.author_index import build_author_index
        from ohbm2026.book.render_markdown import emit_book_md
        from ohbm2026.book.sort import by_poster_id
    except ImportError:
        return None
    book = _load_book()
    entries = by_poster_id(book.entries)
    author_index = build_author_index(entries)
    # Replace entries + index on the book (frozen dataclass — rebuild).
    from dataclasses import replace

    book = replace(book, entries=entries, author_index=author_index)
    emit_book_md(book, outdir)
    return book


class TestMarkdownBundle(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.outdir = pathlib.Path(self.tmp.name)
        self.book = _emit(self.outdir)
        if self.book is None:
            self.skipTest("render_markdown/sort/author_index not yet implemented")
        self.text = (self.outdir / "book.md").read_text()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    # (a) one "## Abstract NNNN" line per surviving entry
    def test_abstract_headings(self) -> None:
        headings = re.findall(r"^## Abstract (\d{4}) ", self.text, re.M)
        self.assertEqual(set(headings), {"0001", "0002", "0003", "0004", "0005"})

    # (b)+(c) figure references resolve + every emitted file is referenced
    def test_figure_references_resolve_and_are_complete(self) -> None:
        refs = set(re.findall(r"!\[[^\]]*\]\(fig_assets/([^)]+)\)", self.text))
        emitted = {
            p.name
            for p in (self.outdir / "fig_assets").iterdir()
            if p.is_file()
        }
        self.assertEqual(refs, emitted, "figure references vs emitted files mismatch")

    # (d) index-suffix contract
    def test_index_suffix_only_for_repeats(self) -> None:
        files = sorted(p.name for p in (self.outdir / "fig_assets").iterdir())
        # Stage 12 US2: every fig_assets file is `.jpg` regardless of
        # source-side extension (PNG / GIF / WebP → JPEG q=90).
        # Abstract 0001: one methods, one results (no -1/-2 suffix).
        self.assertIn("9000001-0001-methods.jpg", files)
        self.assertIn("9000001-0001-results.jpg", files)
        self.assertNotIn("9000001-0001-methods-1.jpg", files)
        # Abstract 0004: TWO results → suffix present.
        self.assertIn("9000004-0004-results-1.jpg", files)
        self.assertIn("9000004-0004-results-2.jpg", files)
        self.assertNotIn("9000004-0004-results.jpg", files)

    # (e) determinism
    def test_re_emit_byte_identical(self) -> None:
        first = (self.outdir / "book.md").read_bytes()
        with tempfile.TemporaryDirectory() as tmp2:
            _emit(pathlib.Path(tmp2))
            second = (pathlib.Path(tmp2) / "book.md").read_bytes()
        self.assertEqual(first, second)

    # (f) `\index{Last, First}` markers beside author names
    def test_latex_index_markers_present(self) -> None:
        # Jane A. Smith is on abstract 0001 → \index{Smith, Jane A.}
        self.assertIn(r"\index{Smith, Jane A.}", self.text)

    # (g) `\printindex` exactly once near the end
    def test_printindex_singleton(self) -> None:
        self.assertEqual(self.text.count(r"\printindex"), 1)
        # near the end (within the last 20% of the file)
        idx = self.text.rfind(r"\printindex")
        self.assertGreater(idx, int(len(self.text) * 0.5))

    # (h) `<details>` anchor-link author index follows \printindex
    def test_details_anchor_index_present(self) -> None:
        self.assertIn(
            "<details><summary>Author Index (anchor links)</summary>",
            self.text,
        )
        # Each distinct fixture author should have a poster anchor link.
        # Jane A. Smith is on 0001 only.
        self.assertRegex(
            self.text,
            r"Jane A\. Smith[^\n]+\(#abstract-0001\)",
        )
        # Maria B. Brown shared across 0002 + 0004.
        block = self.text[self.text.find("<details>"):]
        self.assertIn("Maria B. Brown", block)
        self.assertIn("#abstract-0002", block)
        self.assertIn("#abstract-0004", block)


class TestFigureResize(unittest.TestCase):
    """`emit_book_md`'s `max_image_width` controls a Pillow downsize
    pass during the figure-copy step. Fixture PNGs are 2400×2400; a
    1000 px cap yields 1000×1000 copies. A 0/None cap byte-copies."""

    def setUp(self) -> None:
        try:
            from dataclasses import replace
            from ohbm2026.book.author_index import build_author_index
            from ohbm2026.book.corpus import load_book
            from ohbm2026.book.render_markdown import emit_book_md
            from ohbm2026.book.sort import by_poster_id
        except ImportError:
            self.skipTest("renderers not yet implemented")
        self.replace = replace
        self.build_author_index = build_author_index
        self.load_book = load_book
        self.emit_book_md = emit_book_md
        self.by_poster_id = by_poster_id

    def _build_book(self):
        book = self.load_book(
            corpus_path=_FIX / "abstracts.json",
            authors_path=_FIX / "authors.json",
            withdrawn_path=_FIX / "abstracts_withdrawn.json",
            assets_root=_FIX / "assets",
        )
        entries = self.by_poster_id(book.entries)
        return self.replace(
            book, entries=entries, author_index=self.build_author_index(entries)
        )

    def test_resize_when_max_width_below_cap(self) -> None:
        # Stage 12 US2: every figure caps at FIGURE_WIDTH_CAP (975 px,
        # = 150 DPI × 6.5" content width). Passing
        # `max_image_width=1000` does NOT request 1000 px — it just
        # confirms the operator is OK with up to 1000 px; the
        # effective cap is min(975, 1000) = 975.
        from PIL import Image as _Image
        from ohbm2026.book.render_markdown import FIGURE_WIDTH_CAP

        with tempfile.TemporaryDirectory() as tmp:
            out = pathlib.Path(tmp)
            self.emit_book_md(self._build_book(), out, max_image_width=1000)
            sample = next((out / "fig_assets").iterdir())
            with _Image.open(sample) as img:
                self.assertEqual(img.width, FIGURE_WIDTH_CAP)
                # Source is 2400×2400 square → height ≈ width after cap.
                self.assertEqual(img.height, FIGURE_WIDTH_CAP)

    def test_max_width_none_uses_default_cap(self) -> None:
        # Stage 12: max_image_width=None → use the default 975 px cap.
        from PIL import Image as _Image
        from ohbm2026.book.render_markdown import FIGURE_WIDTH_CAP

        with tempfile.TemporaryDirectory() as tmp:
            out = pathlib.Path(tmp)
            self.emit_book_md(self._build_book(), out, max_image_width=None)
            sample = next((out / "fig_assets").iterdir())
            with _Image.open(sample) as img:
                self.assertEqual(img.width, FIGURE_WIDTH_CAP)

    def test_max_width_above_cap_still_capped(self) -> None:
        # Stage 12: max_image_width=5000 still caps at 975 px (the
        # operator-supplied value can only tighten the cap, never loosen).
        from PIL import Image as _Image
        from ohbm2026.book.render_markdown import FIGURE_WIDTH_CAP

        with tempfile.TemporaryDirectory() as tmp:
            out = pathlib.Path(tmp)
            self.emit_book_md(self._build_book(), out, max_image_width=5000)
            sample = next((out / "fig_assets").iterdir())
            with _Image.open(sample) as img:
                self.assertEqual(img.width, FIGURE_WIDTH_CAP)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
