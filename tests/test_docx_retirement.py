"""T031 — DOCX export retired in Stage 11.1 US3.

Contract:
- `ohbmcli book --format docx` exits non-zero with a stderr message
  naming the surviving formats (`--format md`, `--format pdf`).
- No `book.docx` is written.
- The `--format docx` choice is rejected at the argparse layer or
  by a typed `BookBuildError` in `cli.main`; either way exit code 2.
"""

from __future__ import annotations

import io
import os
import pathlib
import shutil
import sys
import tempfile
import unittest


_FIX = pathlib.Path(__file__).parent / "fixtures" / "book"


class TestDocxRejection(unittest.TestCase):
    def setUp(self) -> None:
        try:
            from ohbm2026.book.cli import main  # noqa: F401
        except ImportError as exc:
            self.skipTest(f"book CLI not importable: {exc}")
        self.tmp = tempfile.TemporaryDirectory()
        self.workdir = pathlib.Path(self.tmp.name)
        for name in ("authors.json", "abstracts_withdrawn.json", "abstracts.json"):
            shutil.copy2(_FIX / name, self.workdir / name)
        shutil.copytree(_FIX / "assets", self.workdir / "assets")
        self._cwd = pathlib.Path.cwd()
        os.chdir(self.workdir)

    def tearDown(self) -> None:
        os.chdir(self._cwd)
        self.tmp.cleanup()

    def _run(self, argv: list[str]) -> tuple[int, str, str]:
        """Invoke `book.cli.main` and capture (exit_code, stdout, stderr)."""
        from ohbm2026.book import cli as book_cli

        out_buf = io.StringIO()
        err_buf = io.StringIO()
        old_out, old_err = sys.stdout, sys.stderr
        sys.stdout, sys.stderr = out_buf, err_buf
        try:
            try:
                exit_code = book_cli.main(argv)
            except SystemExit as exc:
                exit_code = int(exc.code) if exc.code is not None else 0
        finally:
            sys.stdout, sys.stderr = old_out, old_err
        return exit_code, out_buf.getvalue(), err_buf.getvalue()

    def test_format_docx_exits_nonzero(self) -> None:
        exit_code, _stdout, _stderr = self._run(
            [
                "--format",
                "docx",
                "--corpus",
                "abstracts.json",
                "--authors",
                "authors.json",
                "--withdrawn",
                "abstracts_withdrawn.json",
                "--assets-root",
                "assets",
                "--standby-csv",
                "",
                "--output-root",
                "out",
            ]
        )
        self.assertNotEqual(exit_code, 0, "docx must be rejected")

    def test_stderr_names_surviving_formats(self) -> None:
        _exit_code, _stdout, stderr = self._run(
            [
                "--format",
                "docx",
                "--corpus",
                "abstracts.json",
                "--authors",
                "authors.json",
                "--withdrawn",
                "abstracts_withdrawn.json",
                "--assets-root",
                "assets",
                "--standby-csv",
                "",
                "--output-root",
                "out",
            ]
        )
        # Stderr must mention the rationale + both surviving alternatives.
        lower = stderr.lower()
        self.assertIn("docx", lower)
        self.assertIn("retired", lower)
        self.assertIn("--format md", stderr)
        self.assertIn("--format pdf", stderr)

    def test_no_book_docx_written(self) -> None:
        self._run(
            [
                "--format",
                "docx",
                "--corpus",
                "abstracts.json",
                "--authors",
                "authors.json",
                "--withdrawn",
                "abstracts_withdrawn.json",
                "--assets-root",
                "assets",
                "--standby-csv",
                "",
                "--output-root",
                "out",
            ]
        )
        out_root = self.workdir / "out"
        # Either out/ doesn't exist or it has NO .docx file in it.
        docx_files = list(out_root.rglob("*.docx")) if out_root.exists() else []
        self.assertEqual(docx_files, [], f"unexpected docx files: {docx_files}")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
