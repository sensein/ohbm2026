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
        # The entity decodes to U+00B1 (±) which the math-operator
        # normaliser then wraps in `\(\pm\)` so it falls through to
        # Latin Modern Math at LaTeX-compile time.
        self.assertIn(r"$\pm$", md)

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

    def test_greek_letters_wrapped_in_math(self) -> None:
        md = html_to_pandoc_md("<p>The α-value is 0.05; ρ = 0.42; Δ change</p>")
        self.assertIn(r"$\alpha$", md)
        self.assertIn(r"$\rho$", md)
        self.assertIn(r"$\Delta$", md)

    def test_math_operators_wrapped_in_math(self) -> None:
        md = html_to_pandoc_md("<p>A → B with p ≤ 0.05; ratio ≈ 1.5</p>")
        self.assertIn(r"$\to$", md)
        self.assertIn(r"$\leq$", md)
        self.assertIn(r"$\approx$", md)

    def test_math_italic_greek_folded(self) -> None:
        # 𝜌 (U+1D70C) is MATHEMATICAL ITALIC SMALL RHO — different
        # codepoint from basic ρ (U+03C1). Folder maps it to the
        # basic Greek; then the Greek normaliser wraps it in math.
        md = html_to_pandoc_md("<p>The 𝜌 value is 0.42</p>")
        self.assertIn(r"$\rho$", md)
        # 𝑥 (U+1D465) is MATHEMATICAL ITALIC SMALL X — folds to ASCII x.
        md = html_to_pandoc_md("<p>variable 𝑥</p>")
        self.assertIn("x", md)
        self.assertNotIn("𝑥", md)

    def test_minus_sign_normalised_to_ascii(self) -> None:
        md = html_to_pandoc_md("<p>Result: −0.42</p>")
        # MINUS SIGN (U+2212) → ASCII hyphen (no math wrap needed)
        self.assertIn("-0.42", md)
        self.assertNotIn("−", md)

    def test_deterministic(self) -> None:
        html = (
            '<p style="x" id="isPasted">A<sup>1</sup></p>'
            "<p>B<sub>2</sub></p><ol><li>r1</li><li>r2</li></ol>"
        )
        self.assertEqual(html_to_pandoc_md(html), html_to_pandoc_md(html))


class TestCaretSuperscriptToLatex(unittest.TestCase):
    """Stage 12.1 — `normalise_for_latex` converts pandoc text-
    superscript syntax `^X^` to explicit `\\textsuperscript{X}` so
    the dominant cluster of "Double superscript" LaTeX errors (76
    failed abstracts in Stage 11.1's provenance) is eliminated.
    """

    def test_simple_caret_to_textsuperscript(self) -> None:
        from ohbm2026.book.html_to_md import normalise_for_latex

        self.assertIn("\\textsuperscript{3}", normalise_for_latex("4 mm^3^"))
        self.assertIn("\\textsuperscript{1,2}", normalise_for_latex("Doe^1,2^"))

    def test_caret_survives_math_span_adjacency(self) -> None:
        # The exact pattern that broke Stage 11.1: `$\times$3 mm^3^`.
        from ohbm2026.book.html_to_md import normalise_for_latex

        out = normalise_for_latex("3$\\times$3$\\times$4 mm^3^;")
        # No bare `^3^` remains — pandoc's math-mode parser can't
        # confuse the result anymore.
        self.assertNotIn("mm^3^", out)
        self.assertIn("\\textsuperscript{3}", out)

    def test_escaped_caret_not_touched(self) -> None:
        # Already-escaped `\^X^` (rare; usually authors who want a
        # literal caret) should NOT be re-converted. The regex uses
        # a negative lookbehind on `\\`.
        from ohbm2026.book.html_to_md import normalise_for_latex

        out = normalise_for_latex("a \\^x^ b")
        self.assertNotIn("\\textsuperscript{x}", out)

    def test_idempotent(self) -> None:
        from ohbm2026.book.html_to_md import normalise_for_latex

        once = normalise_for_latex("k^c^")
        twice = normalise_for_latex(once)
        self.assertEqual(once, twice)


class TestStripControlChars(unittest.TestCase):
    """Stage 12.2 — strip C0/C1 control + zero-width markers that
    Tectonic refuses to typeset ("Text line contains an invalid
    character"). Real-corpus failures fixed:
    - poster 995: U+0002 inside "Nat\\x02ural Science Foundation"
    - poster 2024: U+000B (vertical tab) inside an author affiliation
    """

    def test_c0_stripped(self) -> None:
        from ohbm2026.book.html_to_md import normalise_for_latex

        out = normalise_for_latex("Nat\x02ural Science Foundation")
        self.assertEqual(out, "Natural Science Foundation")

    def test_vertical_tab_stripped(self) -> None:
        from ohbm2026.book.html_to_md import normalise_for_latex

        out = normalise_for_latex("Brain Korea 21 Project,\x0bYonsei")
        self.assertEqual(out, "Brain Korea 21 Project,Yonsei")

    def test_newline_tab_preserved(self) -> None:
        from ohbm2026.book.html_to_md import normalise_for_latex

        out = normalise_for_latex("line1\nline2\tcol2")
        self.assertEqual(out, "line1\nline2\tcol2")

    def test_zero_width_stripped(self) -> None:
        from ohbm2026.book.html_to_md import normalise_for_latex

        # ZWSP (U+200B), BOM (U+FEFF), soft hyphen (U+00AD)
        out = normalise_for_latex("foo​bar﻿baz­qux")
        self.assertEqual(out, "foobarbazqux")


class TestEscapeBareAmpersand(unittest.TestCase):
    """Stage 12.2 — pre-escape bare `&` to `\\&` so pandoc never
    leaks an unescaped `&` into LaTeX body text (real failures: H&Y,
    Hoehn & Yahr → LaTeX "Misplaced alignment tab character &"). The
    leak happens when neighbouring `$math$` spans confuse pandoc's
    inline parser.
    """

    def test_bare_amp_escaped(self) -> None:
        from ohbm2026.book.html_to_md import normalise_for_latex

        self.assertEqual(normalise_for_latex("H&Y staging"), "H\\&Y staging")
        self.assertEqual(
            normalise_for_latex("Hoehn & Yahr"), "Hoehn \\& Yahr"
        )

    def test_already_escaped_not_doubled(self) -> None:
        from ohbm2026.book.html_to_md import normalise_for_latex

        # `\&` already an escape sequence → leave it alone.
        self.assertEqual(normalise_for_latex("R\\&D dept"), "R\\&D dept")

    def test_html_entities_not_escaped(self) -> None:
        from ohbm2026.book.html_to_md import normalise_for_latex

        # `&amp;` `&lt;` etc. — pandoc decodes these; don't pre-escape.
        self.assertEqual(normalise_for_latex("a &amp; b"), "a &amp; b")
        self.assertEqual(normalise_for_latex("a &lt; b"), "a &lt; b")
        self.assertEqual(
            normalise_for_latex("a &#8217; b"), "a &#8217; b"
        )

    def test_idempotent(self) -> None:
        from ohbm2026.book.html_to_md import normalise_for_latex

        once = normalise_for_latex("H&Y and R\\&D")
        twice = normalise_for_latex(once)
        self.assertEqual(once, twice)


class TestDefangUnknownCommands(unittest.TestCase):
    """Stage 12.2 — strip the leading backslash from author-pasted
    `\\Command` typos so LaTeX doesn't error out with "Undefined
    control sequence". Real-corpus failures fixed:
    - poster 1791: `\\State Key Laboratory` (typo for "State Key")
    - poster 1329: `DHF\\R1\\textbackslash241022` (stray `\\R` in
      grant-ID)
    """

    def test_unknown_capitalised_defanged(self) -> None:
        from ohbm2026.book.html_to_md import normalise_for_latex

        out = normalise_for_latex(
            "\\textsuperscript{3} \\State Key Laboratory of Brain Cognition"
        )
        self.assertNotIn("\\State", out)
        self.assertIn("State Key Laboratory", out)
        # The intentional `\textsuperscript{3}` is preserved.
        self.assertIn("\\textsuperscript{3}", out)

    def test_unknown_single_letter_defanged(self) -> None:
        from ohbm2026.book.html_to_md import normalise_for_latex

        out = normalise_for_latex("Grant DHF\\R1\\textbackslash241022")
        self.assertNotIn("\\R1", out)
        self.assertIn("R1", out)
        # `\textbackslash` is in our whitelist (pandoc emits it).
        self.assertIn("\\textbackslash", out)

    def test_known_command_preserved(self) -> None:
        from ohbm2026.book.html_to_md import normalise_for_latex

        # Greek letters, math operators — all whitelisted.
        out = normalise_for_latex("\\alpha + \\pm = \\Delta")
        self.assertIn("\\alpha", out)
        self.assertIn("\\pm", out)
        self.assertIn("\\Delta", out)

    def test_command_with_braces_left_alone(self) -> None:
        from ohbm2026.book.html_to_md import normalise_for_latex

        # `\command{...}` looks like a real call — let LaTeX decide
        # rather than mangling the call.
        out = normalise_for_latex("\\unknowncmd{value}")
        self.assertIn("\\unknowncmd{value}", out)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
