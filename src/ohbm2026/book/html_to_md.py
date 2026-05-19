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
