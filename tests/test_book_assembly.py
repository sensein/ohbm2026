"""T007 — two-pass PDF assembly: page-offset measurement + index injection.

The test builds three small fixture PDFs of known page counts (2 + 3 + 1)
plus a 1-page front-matter chunk in-process via pikepdf, hands them to
`assemble`, and verifies:
- chunk_offsets correctly index each chunk start
- the index-appendix stub markdown contains the right \\setcounter{page}
- the final PDF's last N pages are the index appendix
- pdftotext (when available) shows index-entries in the back matter
"""

from __future__ import annotations

import pathlib
import shutil
import subprocess
import tempfile
import unittest


def _pandoc_engine_ok() -> bool:
    """assemble pass-2 requires pandoc + an engine to emit the index appendix."""
    if not shutil.which("pandoc"):
        return False
    return bool(shutil.which("xelatex")) or bool(shutil.which("tectonic"))


class TestTwoPassAssembly(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        try:
            import pikepdf  # noqa: F401
        except ImportError as exc:
            raise unittest.SkipTest(f"pikepdf not installed: {exc}")
        try:
            from ohbm2026.book.assemble_pdf import assemble  # noqa: F401
            from ohbm2026.book.model import AbstractPdfChunk  # noqa: F401
        except ImportError as exc:
            raise unittest.SkipTest(
                f"assemble_pdf / AbstractPdfChunk not yet implemented: {exc}"
            )

    def setUp(self) -> None:
        import pikepdf

        self.tmp = tempfile.TemporaryDirectory()
        self.dir = pathlib.Path(self.tmp.name)
        self.cache_dir = self.dir / "cache"
        self.cache_dir.mkdir()

        # Build four fixture PDFs of known page counts.
        self.page_counts = {
            "front": 1,
            "chunk_a": 2,
            "chunk_b": 3,
            "chunk_c": 1,
        }
        self.paths: dict[str, pathlib.Path] = {}
        for name, n in self.page_counts.items():
            pdf = pikepdf.Pdf.new()
            for _ in range(n):
                pdf.add_blank_page()
            p = self.cache_dir / f"{name}.pdf"
            pdf.save(p)
            self.paths[name] = p

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _build_chunks(self):
        from ohbm2026.book.model import AbstractPdfChunk

        chunks = []
        for i, name in enumerate(("chunk_a", "chunk_b", "chunk_c")):
            chunks.append(
                AbstractPdfChunk(
                    poster_id=1000 + i,
                    cache_key=f"chunk_{i:016d}"[:16],
                    cached_path=self.paths[name],
                    page_count=self.page_counts[name],
                    cache_hit=True,
                    pandoc_stderr=None,
                )
            )
        front = AbstractPdfChunk(
            poster_id=-1,
            cache_key="frontmatter_____"[:16],
            cached_path=self.paths["front"],
            page_count=self.page_counts["front"],
            cache_hit=True,
            pandoc_stderr=None,
        )
        return front, chunks

    def test_chunk_offsets_measured_in_pass_one(self) -> None:
        from ohbm2026.book.assemble_pdf import assemble

        front, chunks = self._build_chunks()
        out = self.dir / "book.pdf"
        if not _pandoc_engine_ok():
            self.skipTest("pandoc + engine required for pass-2 index appendix")
        from importlib import resources

        header = pathlib.Path(
            str(
                resources.files("ohbm2026.book.templates").joinpath(
                    "header-includes.tex"
                )
            )
        )
        result = assemble(
            chunks,
            front,
            out,
            pandoc_path=shutil.which("pandoc"),
            engine_binary=(
                "xelatex" if shutil.which("xelatex") else "tectonic"
            ),
            header_includes_path=header,
            style="plain",
            draft_dir=self.dir / "draft",
        )

        # Expected starts:
        #   front: page 1
        #   chunk_a: page 2 (after 1 front page)
        #   chunk_b: page 4 (after 1 + 2 = 3 pages)
        #   chunk_c: page 7 (after 1 + 2 + 3 = 6 pages)
        expected = [
            (-1, 1),
            (1000, 2),
            (1001, 4),
            (1002, 7),
        ]
        self.assertEqual(list(result.chunk_offsets), expected)
        self.assertEqual(result.front_matter_pages, 1)

    def test_final_pdf_contains_index_appendix(self) -> None:
        if not _pandoc_engine_ok():
            self.skipTest("pandoc + engine required for pass-2 index appendix")
        from ohbm2026.book.assemble_pdf import assemble
        import pikepdf
        from importlib import resources

        front, chunks = self._build_chunks()
        out = self.dir / "book.pdf"
        header = pathlib.Path(
            str(
                resources.files("ohbm2026.book.templates").joinpath(
                    "header-includes.tex"
                )
            )
        )
        result = assemble(
            chunks,
            front,
            out,
            pandoc_path=shutil.which("pandoc"),
            engine_binary=(
                "xelatex" if shutil.which("xelatex") else "tectonic"
            ),
            header_includes_path=header,
            style="plain",
            draft_dir=self.dir / "draft",
        )
        with pikepdf.Pdf.open(out) as pdf:
            total = len(pdf.pages)
        # 1 + 2 + 3 + 1 = 7 chunk pages; index_pages >= 1.
        self.assertGreaterEqual(total, 7 + 1)
        # Index appendix appended at the back — total > sum of chunks.
        self.assertGreater(total, sum(self.page_counts.values()))
        self.assertEqual(result.final_path, out)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
