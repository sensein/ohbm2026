"""T012 — HTML → pandoc-markdown conversion (R2)."""

from __future__ import annotations

import unittest

from ohbm2026.book.html_to_md import html_to_pandoc_md


class TestHtmlToMd(unittest.TestCase):
    def test_empty(self) -> None:
        self.assertEqual(html_to_pandoc_md(""), "")
        self.assertEqual(html_to_pandoc_md("   "), "")

    def test_superscript_becomes_pandoc_caret(self) -> None:
        md = html_to_pandoc_md("<p>cite<sup>1,2</sup></p>")
        self.assertIn("^1,2^", md)
        # Single-char form too.
        md = html_to_pandoc_md("<p>x<sup>1</sup></p>")
        self.assertIn("^1^", md)

    def test_subscript_becomes_pandoc_tilde(self) -> None:
        md = html_to_pandoc_md("<p>H<sub>2</sub>O</p>")
        self.assertIn("~2~", md)

    def test_ordered_list_becomes_numbered(self) -> None:
        md = html_to_pandoc_md("<ol><li>A</li><li>B</li></ol>")
        self.assertIn("1. A", md)
        self.assertIn("2. B", md)

    def test_inline_style_and_ispasted_stripped(self) -> None:
        md = html_to_pandoc_md(
            '<p style="font-family:Arial" id="isPasted">hello</p>'
        )
        self.assertIn("hello", md)
        self.assertNotIn("style", md)
        self.assertNotIn("isPasted", md)
        self.assertNotIn("font-family", md)

    def test_strong_em(self) -> None:
        md = html_to_pandoc_md(
            "<p><strong>bold</strong> and <em>italic</em></p>"
        )
        self.assertIn("**bold**", md)
        # markdownify uses underscore or asterisk for em; either is fine
        self.assertTrue("*italic*" in md or "_italic_" in md)

    def test_html_entity_resolves(self) -> None:
        md = html_to_pandoc_md("<p>x&plusmn;y</p>")
        self.assertIn("±", md)

    def test_unicode_superscript_normalised(self) -> None:
        # Authors sometimes paste literal Unicode super/subscript
        # glyphs instead of using <sup>/<sub>. Latin Modern lacks the
        # codepoints, so we coerce them to pandoc literals before
        # LaTeX sees the input.
        md = html_to_pandoc_md("<p>fMRI⁴ data is processed in H₂O</p>")
        self.assertIn("^4^", md)
        self.assertIn("~2~", md)
        # Multi-char run collapses into a single pandoc token.
        md = html_to_pandoc_md("<p>x²⁰²⁶ years</p>")
        self.assertIn("^2026^", md)

    def test_deterministic(self) -> None:
        html = (
            '<p style="x" id="isPasted">A<sup>1</sup></p>'
            "<p>B<sub>2</sub></p><ol><li>r1</li><li>r2</li></ol>"
        )
        self.assertEqual(html_to_pandoc_md(html), html_to_pandoc_md(html))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
