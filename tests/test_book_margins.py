"""T032 — Stage 12 US5 — tight margin preset + --margins flag.

Static verifications of the geometry preamble + the to_pdf
selection. Real-corpus page-count comparison is operator-side
(SC-005 verified at smoke time).
"""

from __future__ import annotations

import pathlib
import unittest
from importlib import resources


_TEMPLATES = resources.files("ohbm2026.book.templates")


class TestGeometryPreamble(unittest.TestCase):
    """The tight preset carries `\\usepackage[margin=0.65in]{geometry}`;
    the loose preset does NOT."""

    def test_tight_header_includes_geometry(self) -> None:
        path = pathlib.Path(str(_TEMPLATES.joinpath("header-includes.tex")))
        body = path.read_text()
        self.assertIn("\\usepackage[margin=0.65in]{geometry}", body)

    def test_loose_header_omits_geometry(self) -> None:
        path = pathlib.Path(str(_TEMPLATES.joinpath("header-includes-loose.tex")))
        body = path.read_text()
        # Recovers the LaTeX `book` class default ~1 in margins.
        # Strip comment lines (start with `%`) before the substring
        # check so the rationale comment ("no geometry import") doesn't
        # false-positive against itself.
        non_comments = "\n".join(
            line for line in body.splitlines() if not line.lstrip().startswith("%")
        )
        self.assertNotIn("\\usepackage[margin", non_comments)
        self.assertNotIn("\\usepackage{geometry}", non_comments)

    def test_per_abstract_template_carries_tight_geometry(self) -> None:
        # Per-chunk page dimensions must match the assembled book's
        # pages; otherwise pikepdf concatenation across chunks of
        # mixed sizes would produce visually inconsistent pages.
        path = pathlib.Path(str(_TEMPLATES.joinpath("per-abstract.tex.template")))
        body = path.read_text()
        self.assertIn("\\usepackage[margin=0.65in]{geometry}", body)


class TestHeaderIncludesPathSelection(unittest.TestCase):
    """`_header_includes_path(style, margins)` returns the right file."""

    @classmethod
    def setUpClass(cls) -> None:
        try:
            from ohbm2026.book.render_via_pandoc import _header_includes_path
        except ImportError as exc:
            raise unittest.SkipTest(f"_header_includes_path not yet implemented: {exc}")
        cls._select = staticmethod(_header_includes_path)

    def test_tight_returns_default_header(self) -> None:
        path = self._select("plain", margins="tight")
        self.assertEqual(path.name, "header-includes.tex")

    def test_loose_returns_loose_header(self) -> None:
        path = self._select("plain", margins="loose")
        self.assertEqual(path.name, "header-includes-loose.tex")

    def test_tufte_style_unchanged(self) -> None:
        # Tufte's experimental path is independent of the margins flag.
        path = self._select("tufte", margins="tight")
        self.assertEqual(path.name, "header-includes-tufte.tex")
        path_loose = self._select("tufte", margins="loose")
        self.assertEqual(path_loose.name, "header-includes-tufte.tex")


class TestCliMarginsFlag(unittest.TestCase):
    """`--margins {tight,loose}` flag is parsed + defaults to `tight`."""

    @classmethod
    def setUpClass(cls) -> None:
        try:
            from ohbm2026.book.cli import _build_parser
        except ImportError as exc:
            raise unittest.SkipTest(f"book CLI not importable: {exc}")
        cls._build_parser = staticmethod(_build_parser)

    def test_default_is_tight(self) -> None:
        parser = self._build_parser()
        args = parser.parse_args([])
        self.assertEqual(args.margins, "tight")

    def test_explicit_loose(self) -> None:
        parser = self._build_parser()
        args = parser.parse_args(["--margins", "loose"])
        self.assertEqual(args.margins, "loose")

    def test_invalid_value_rejected(self) -> None:
        parser = self._build_parser()
        with self.assertRaises(SystemExit):
            parser.parse_args(["--margins", "invalid"])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
