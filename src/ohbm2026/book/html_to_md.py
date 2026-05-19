"""HTML → pandoc-markdown conversion (R2).

The Oxford form's rich-text editor stores all long-form values as HTML
fragments with `<p>`, `<sup>`, `<sub>`, `<ol>`, `<li>`, `<em>`,
`<strong>`, `<a>`, `<br>` and inline `style="..."`/`id="isPasted"`
attributes. The book renders from markdown, so the conversion happens
ONCE at corpus load (the in-memory model carries markdown, not HTML).

Pandoc-flavored superscripts (`^N^`) and subscripts (`~N~`) preserve
the scientific-citation markup that plain CommonMark cannot express.
"""

from __future__ import annotations

import re
import sys

from bs4 import BeautifulSoup
from markdownify import markdownify

# markdownify recurses through the BeautifulSoup tree; the Oxford
# rich-text editor produces deeply-nested HTML (especially for
# References/Citations <ol><li><p><span>... chains). Default 1000 is
# too tight; 5000 is plenty for the observed corpus.
_RECURSION_FLOOR = 5000


# Unicode superscript / subscript characters that authors paste in
# directly (instead of using `<sup>N</sup>`). Latin Modern lacks
# these glyphs and Tectonic refuses to fall through to a substitute
# font — so we normalise them BEFORE pandoc emits LaTeX. Each cluster
# of contiguous super/sub chars maps to a single `^...^` / `~...~`
# pandoc token; non-contiguous occurrences stay independent.
_SUPER_DIGITS = "⁰¹²³⁴⁵⁶⁷⁸⁹"
_SUB_DIGITS = "₀₁₂₃₄₅₆₇₈₉"
_SUPER_SIGNS = {
    "⁺": "+",  # SUPERSCRIPT PLUS SIGN
    "⁻": "-",  # SUPERSCRIPT MINUS
    "⁼": "=",  # SUPERSCRIPT EQUALS SIGN
    "⁽": "(",
    "⁾": ")",
    "ⁿ": "n",  # SUPERSCRIPT LATIN SMALL LETTER N
}
_SUB_SIGNS = {
    "₊": "+",
    "₋": "-",
    "₌": "=",
    "₍": "(",
    "₎": ")",
}

_SUPER_RE = re.compile(
    "([" + _SUPER_DIGITS + "".join(_SUPER_SIGNS.keys()) + "]+)"
)
_SUB_RE = re.compile(
    "([" + _SUB_DIGITS + "".join(_SUB_SIGNS.keys()) + "]+)"
)

_SUPER_TRANS = str.maketrans(
    {ch: a for ch, a in zip(_SUPER_DIGITS, "0123456789")} | _SUPER_SIGNS
)
_SUB_TRANS = str.maketrans(
    {ch: a for ch, a in zip(_SUB_DIGITS, "0123456789")} | _SUB_SIGNS
)


def _normalise_unicode_super_sub(text: str) -> str:
    """Replace contiguous Unicode super/subscript runs with pandoc
    `^...^` / `~...~` literals so the LaTeX renderer never sees a
    glyph its font can't represent (Latin Modern lacks U+2074, etc.).
    """

    def _super(m: "re.Match[str]") -> str:
        return "^" + m.group(0).translate(_SUPER_TRANS) + "^"

    def _sub(m: "re.Match[str]") -> str:
        return "~" + m.group(0).translate(_SUB_TRANS) + "~"

    text = _SUPER_RE.sub(_super, text)
    text = _SUB_RE.sub(_sub, text)
    return text


def html_to_pandoc_md(html: str) -> str:
    """Convert an Oxford-corpus HTML fragment to pandoc markdown.

    Pure function, no I/O. Returns a stripped string; empty input
    yields empty output.
    """
    if not html or not html.strip():
        return ""

    soup = BeautifulSoup(html, "html.parser")

    # Pre-pass: convert sup/sub to pandoc literals BEFORE markdownify
    # collapses them into stray HTML islands. We replace each
    # <sup>x</sup> node with a NavigableString containing `^x^` (and
    # likewise for sub). Markdownify then sees plain text and leaves
    # the literal alone.
    for tag in soup.find_all("sup"):
        text = tag.get_text()
        # Pandoc superscript syntax disallows whitespace inside;
        # backslash-escape if necessary to keep the marker valid.
        text = re.sub(r"\s+", r"\\ ", text)
        tag.replace_with(f"^{text}^")
    for tag in soup.find_all("sub"):
        text = tag.get_text()
        text = re.sub(r"\s+", r"\\ ", text)
        tag.replace_with(f"~{text}~")

    # Strip the rich-text-editor artefacts before markdownify sees them.
    for tag in soup.find_all(attrs={"id": "isPasted"}):
        del tag.attrs["id"]
    for tag in soup.find_all(style=True):
        del tag.attrs["style"]

    prior_limit = sys.getrecursionlimit()
    if prior_limit < _RECURSION_FLOOR:
        sys.setrecursionlimit(_RECURSION_FLOOR)
    try:
        md = markdownify(
            str(soup),
            heading_style="ATX",
            bullets="-",
            strip=["span"],
        )
    finally:
        if prior_limit < _RECURSION_FLOOR:
            sys.setrecursionlimit(prior_limit)

    # Normalise direct Unicode super/subscript glyphs into pandoc
    # `^...^` / `~...~` literals. Run AFTER markdownify so we operate
    # on plain text — any `<sup>`/`<sub>` already became `^...^` /
    # `~...~` in the BeautifulSoup pre-pass above.
    md = _normalise_unicode_super_sub(md)

    # markdownify leaves trailing whitespace per line + collapses
    # multiple blank lines unevenly; tighten the output so re-runs
    # are byte-deterministic (SC-007a).
    lines = [ln.rstrip() for ln in md.splitlines()]
    out: list[str] = []
    blank = False
    for ln in lines:
        if ln == "":
            if blank:
                continue
            blank = True
        else:
            blank = False
        out.append(ln)
    return "\n".join(out).strip() + "\n"
