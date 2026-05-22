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


# Greek letters that appear in body text (Latin Modern lacks every
# one of these). Wrap in `\(...\)` math markers so they fall through
# to Latin Modern Math, which DOES have Greek. Pandoc passes raw
# TeX (`\( \)`) through unchanged when `raw_tex` is enabled.
_GREEK_LATEX = {
    # Lowercase
    "α": r"\alpha", "β": r"\beta", "γ": r"\gamma", "δ": r"\delta",
    "ε": r"\epsilon", "ζ": r"\zeta", "η": r"\eta", "θ": r"\theta",
    "ι": r"\iota", "κ": r"\kappa", "λ": r"\lambda", "μ": r"\mu",
    "ν": r"\nu", "ξ": r"\xi", "ο": "o", "π": r"\pi",
    "ρ": r"\rho", "σ": r"\sigma", "ς": r"\varsigma", "τ": r"\tau",
    "υ": r"\upsilon", "φ": r"\varphi", "ϕ": r"\phi", "χ": r"\chi",
    "ψ": r"\psi", "ω": r"\omega",
    "ϑ": r"\vartheta", "ϱ": r"\varrho", "ϖ": r"\varpi", "ε": r"\varepsilon",
    # Uppercase
    "Α": "A", "Β": "B", "Γ": r"\Gamma", "Δ": r"\Delta",
    "Ε": "E", "Ζ": "Z", "Η": "H", "Θ": r"\Theta",
    "Ι": "I", "Κ": "K", "Λ": r"\Lambda", "Μ": "M",
    "Ν": "N", "Ξ": r"\Xi", "Ο": "O", "Π": r"\Pi",
    "Ρ": "P", "Σ": r"\Sigma", "Τ": "T",
    "Υ": r"\Upsilon", "Φ": r"\Phi", "Χ": "X", "Ψ": r"\Psi",
    "Ω": r"\Omega",
}

# Math operators / relations that Latin Modern's text font also
# doesn't carry. Latin Modern Math has them in math mode.
_MATH_OP_LATEX = {
    "→": r"\to", "←": r"\gets", "↔": r"\leftrightarrow",
    "⇒": r"\Rightarrow", "⇐": r"\Leftarrow", "⇔": r"\Leftrightarrow",
    "≥": r"\geq", "≤": r"\leq", "≠": r"\neq", "≈": r"\approx",
    "≡": r"\equiv", "∼": r"\sim", "∝": r"\propto",
    "∞": r"\infty", "∂": r"\partial", "∇": r"\nabla",
    "∑": r"\sum", "∏": r"\prod", "∫": r"\int",
    "∈": r"\in", "∉": r"\notin", "⊂": r"\subset", "⊃": r"\supset",
    "∩": r"\cap", "∪": r"\cup", "∅": r"\emptyset",
    "±": r"\pm", "∓": r"\mp", "×": r"\times", "÷": r"\div",
    "√": r"\surd", "∗": r"\ast",
    "−": "-",  # MINUS SIGN U+2212 → ASCII hyphen
    "‐": "-", "‑": "-", "‒": "-",  # various dash glyphs
}

_GREEK_RE = re.compile("([" + "".join(_GREEK_LATEX.keys()) + "])")
_MATH_OP_RE = re.compile("([" + "".join(re.escape(c) for c in _MATH_OP_LATEX.keys()) + "])")


def _fold_math_alphanumerics(text: str) -> str:
    """Normalise the Unicode Mathematical Alphanumeric Symbols block
    (U+1D400-U+1D7FF) to plain ASCII / Greek so the downstream
    Greek/math normaliser can handle them through a single map.

    Authors paste italicised math letters (e.g. 𝜌 U+1D70C "MATHEMATICAL
    ITALIC SMALL RHO") directly into body text. Latin Modern lacks
    every codepoint in this block. The Unicode standard defines each
    char as a stylistic variant of a basic letter (Latin a-z / A-Z
    or Greek α-ω / Α-Ω); we fold the styles away and let the basic
    glyph carry the meaning. Italic / bold styling is lost.
    """
    out: list[str] = []
    for ch in text:
        cp = ord(ch)
        if 0x1D400 <= cp <= 0x1D7FF:
            out.append(_fold_one_math_alphanumeric(cp))
        else:
            out.append(ch)
    return "".join(out)


def _fold_one_math_alphanumeric(cp: int) -> str:
    """Map one codepoint in the Mathematical Alphanumeric Symbols
    block to its basic-letter equivalent. Returns the original glyph
    when the codepoint is one of the gap reservations Unicode skips.
    """
    # The block is laid out as 13 alphabets × 52 letters (A-Z then
    # a-z), then a digits-only tail. Within each alphabet:
    #   block_base + i*52 + 0..25  ⇒  uppercase Latin A..Z
    #   block_base + i*52 + 26..51 ⇒  lowercase Latin a..z
    # Greek alphabets start at U+1D6A8 (Greek bold uppercase).
    # Digits start at U+1D7CE.
    LATIN_BASES = [
        0x1D400, 0x1D434, 0x1D468, 0x1D49C,  # bold, italic, bold-italic, script
        0x1D4D0, 0x1D504, 0x1D538, 0x1D56C,  # script-bold, fraktur, double-struck, fraktur-bold
        0x1D5A0, 0x1D5D4, 0x1D608, 0x1D63C,  # sans-serif, sans-bold, sans-italic, sans-bold-italic
        0x1D670,                              # monospace
    ]
    GREEK_BASES = [
        0x1D6A8, 0x1D6E2, 0x1D71C, 0x1D756, 0x1D790,
    ]  # 25 + 28 = 53 chars per alphabet (Greek has extras)
    DIGIT_BASES = [0x1D7CE, 0x1D7D8, 0x1D7E2, 0x1D7EC, 0x1D7F6]

    # Latin alphabets (52 chars each: 26 upper + 26 lower).
    for base in LATIN_BASES:
        if base <= cp < base + 52:
            idx = cp - base
            if idx < 26:
                return chr(ord("A") + idx)
            return chr(ord("a") + (idx - 26))

    # Greek alphabets. Layout per Unicode 14 (each block is 58 codepoints):
    #   base + 0..24    → CAPITAL ALPHA..OMEGA (25 letters)
    #   base + 25       → NABLA (∇, special)
    #   base + 26..50   → small alpha..omega (25 letters)
    #   base + 51       → PARTIAL DIFFERENTIAL (∂)
    #   base + 52..57   → epsilon/theta/kappa/phi/rho/pi symbols (variants)
    # We fold to the basic Greek glyph when possible; skip the variants
    # (callers' Greek-to-LaTeX map handles the basic forms).
    for base in GREEK_BASES:
        # 25 capitals: Alpha .. Omega
        if base <= cp < base + 25:
            return chr(0x0391 + (cp - base))
        # Nabla
        if cp == base + 25:
            return "∇"  # ∇
        # 25 lowercase: alpha .. omega
        if base + 26 <= cp < base + 51:
            return chr(0x03B1 + (cp - base - 26))
        # Partial differential
        if cp == base + 51:
            return "∂"  # ∂

    # Digits (10 chars each, 5 alphabets).
    for base in DIGIT_BASES:
        if base <= cp < base + 10:
            return chr(ord("0") + (cp - base))

    return chr(cp)


def normalise_for_latex(text: str) -> str:
    """Idempotent pipeline that takes any string (markdown OR plain
    text the book emitter produces) and folds away the Unicode that
    Latin Modern can't render. Safe to apply over already-converted
    HTML output: the patterns are character-class-driven and don't
    touch ASCII or already-converted `$...$` math spans.
    """
    text = _strip_control_chars(text)
    text = _fold_math_alphanumerics(text)
    text = _normalise_unicode_super_sub(text)
    text = _normalise_greek_and_math(text)
    # Stage 12.1: convert well-formed `^X^` caret-super pairs BEFORE
    # `_collapse_caret_runs` so adjacent pairs (`^X^^Y^` from HTML
    # like `<sup>X</sup><sup>Y</sup>`) get cleanly split into
    # `\textsuperscript{X}\textsuperscript{Y}` instead of being
    # mangled by the `^^` collapse pass. Running the collapse first
    # turned poster 239's `^-^^17^` into `^-\^17^` which downstream
    # regexes captured wrong and produced
    # `\textsuperscript{-\}17^` (Stage 11.1 / Stage 12 failure #2 in
    # provenance.failed_abstracts[]).
    text = _caret_super_to_latex(text)
    text = _collapse_caret_runs(text)
    text = _escape_bare_ampersand(text)
    text = _defang_unknown_commands(text)
    return text


# C0 (U+0000-U+001F) and C1 (U+0080-U+009F) control characters,
# plus zero-width and bidi-marker codepoints that authors paste in
# unintentionally (Word's "smart" non-printing markers, soft hyphens,
# the BOM, etc.). Latin Modern can't represent them and Tectonic
# raises "Text line contains an invalid character" → whole abstract
# fails to render. Preserve newline, tab, and carriage return so we
# don't destroy line structure.
_SAFE_CONTROL_CHARS = {"\n", "\t", "\r"}


def _strip_control_chars(text: str) -> str:
    """Remove C0/C1 control codepoints and zero-width markers that
    Tectonic refuses to typeset.

    Examples observed in the corpus (Stage 12.1 / 12.2 failures):
    - U+0002 (STX) inside "Nat\\x02ural Science Foundation" (poster 995)
    - U+000B (vertical tab) breaking a multi-line author affiliation
      (poster 2024)
    """
    out: list[str] = []
    for ch in text:
        cp = ord(ch)
        if ch in _SAFE_CONTROL_CHARS:
            out.append(ch)
            continue
        if cp < 0x20:
            continue
        if 0x7F <= cp <= 0x9F:
            continue
        # Zero-width + bidi markers
        if cp in (0x200B, 0x200C, 0x200D, 0x200E, 0x200F, 0xFEFF, 0x00AD):
            continue
        out.append(ch)
    return "".join(out)


# Escape any bare `&` (not already `\&`, not part of an HTML entity)
# to `\&`. Pandoc normally escapes `&` in markdown body text, but
# leaks the literal through when neighbouring `$...$` math spans
# confuse its inline parser (observed in posters 913 + 1898 where
# `... $\pm$ ...; H&Y ...` produced an unescaped `H&Y` in the .tex →
# LaTeX "Misplaced alignment tab" error).
_BARE_AMP_RE = re.compile(r"(?<!\\)&(?!amp;|lt;|gt;|quot;|apos;|nbsp;|#\d+;|#x[0-9a-fA-F]+;|[a-zA-Z]+;)")


def _escape_bare_ampersand(text: str) -> str:
    return _BARE_AMP_RE.sub(r"\\&", text)


# Whitelist of LaTeX commands we intentionally emit OR pandoc emits
# in normal markdown→latex conversion. Anything else looking like
# `\Capitalized` or `\R` outside our control is most likely an
# author-pasted typo with a stray backslash (observed: `\State` for
# "State", `\R1` for "R1" in grant-IDs). We defang these by stripping
# the leading backslash so the bare word renders as text.
_KNOWN_COMMAND_PREFIXES = frozenset({
    # Pandoc-emitted text commands
    "textbf", "textit", "textsuperscript", "textsubscript", "emph",
    "textbackslash", "textless", "textgreater",
    "textasciitilde", "textasciicircum", "textendash", "textemdash",
    # Pandoc-emitted structural commands
    "section", "subsection", "subsubsection", "paragraph", "label",
    "footnote", "footnotemark", "footnotetext", "cite", "ref", "url", "href",
    "item", "begin", "end", "includegraphics", "caption", "centering",
    "newline", "par", "newpage", "clearpage", "hline", "tabular",
    "figure", "table", "ldots", "cdots", "quad", "qquad",
    "hspace", "vspace", "strut", "tightlist", "pandocbounded",
    "providecommand", "def", "labelenumi", "arabic", "setcounter",
    "printindex", "tableofcontents", "index", "makeindex",
    # Greek letters (we emit these via _normalise_greek_and_math)
    "alpha", "beta", "gamma", "delta", "epsilon", "varepsilon", "zeta",
    "eta", "theta", "vartheta", "iota", "kappa", "lambda", "mu", "nu",
    "xi", "pi", "varpi", "rho", "varrho", "sigma", "varsigma", "tau",
    "upsilon", "phi", "varphi", "chi", "psi", "omega",
    "Alpha", "Beta", "Gamma", "Delta", "Epsilon", "Zeta", "Eta", "Theta",
    "Iota", "Kappa", "Lambda", "Mu", "Nu", "Xi", "Pi", "Rho", "Sigma",
    "Tau", "Upsilon", "Phi", "Chi", "Psi", "Omega",
    # Math operators we emit
    "to", "gets", "leftrightarrow", "Rightarrow", "Leftarrow",
    "Leftrightarrow", "leq", "geq", "neq", "approx", "equiv", "sim",
    "propto", "infty", "partial", "nabla", "sum", "prod", "int",
    "in", "notin", "subset", "supset", "cap", "cup", "emptyset",
    "pm", "mp", "times", "div", "surd", "ast", "cdot", "circ", "prime",
    "star", "forall", "exists", "frac", "sqrt", "mathbb", "mathbf",
    "mathit", "mathrm", "mathcal",
    # Math delimiters + sizing (authors quote these often in equations)
    "left", "right", "big", "Big", "bigg", "Bigg",
    "bigl", "bigr", "Bigl", "Bigr", "biggl", "biggr", "Biggl", "Biggr",
    "bigm", "Bigm", "biggm", "Biggm",
    "langle", "rangle", "lvert", "rvert", "lVert", "rVert",
    "vert", "Vert",
    # Math accents
    "hat", "widehat", "tilde", "widetilde", "bar", "overline",
    "underline", "dot", "ddot", "vec", "overrightarrow", "overleftarrow",
    "overbrace", "underbrace",
    # Math functions
    "sin", "cos", "tan", "cot", "sec", "csc",
    "arcsin", "arccos", "arctan", "sinh", "cosh", "tanh",
    "log", "ln", "exp", "lim", "limsup", "liminf",
    "sup", "inf", "min", "max", "arg", "det", "dim", "ker",
    "gcd", "lcm", "mod", "deg",
    # Spacing
    "thinspace", "negthinspace", "thinsp", "negthinsp",
    "medspace", "thickspace",
})

# Match `\CamelCase` or `\R` style commands that are NOT followed by
# `{` (we don't touch `\command{...}` forms — those are more likely
# real commands and false-positive risk is higher). Only Latin
# letters; anything else is unaffected.
_UNKNOWN_CMD_RE = re.compile(r"\\([A-Za-z]+)(?![A-Za-z\{])")


def _defang_unknown_commands(text: str) -> str:
    """Strip the leading backslash from `\\Command` patterns that
    aren't in our known whitelist. Targets author-pasted typos like
    `\\State Key Laboratory` (poster 1791) where the backslash is
    spurious and LaTeX errors out with "Undefined control sequence".

    Only defangs forms NOT followed by an opening brace — `\\foo{...}`
    is more likely to be a real LaTeX call (e.g. an author quoting
    a citation macro) and we err on the side of letting LaTeX itself
    raise the error, rather than silently transforming the call.
    """

    def _sub(m: "re.Match[str]") -> str:
        name = m.group(1)
        if name in _KNOWN_COMMAND_PREFIXES:
            return m.group(0)
        # Strip the backslash; the word stays as text.
        return name

    return _UNKNOWN_CMD_RE.sub(_sub, text)


# Pandoc's `^...^` superscript syntax pairs ONE opening + ONE closing
# caret around the content. A run of 2+ adjacent carets (`^^`,
# `^^^`, `(R^^2^^`, `^4^^^`, …) comes from corpus artefacts —
# accidentally-pasted carets, empty `<sup></sup>` tags collapsing,
# or `<sup><sup>` flattening edge cases — and pandoc emits `^^` to
# LaTeX where it triggers "Double superscript" errors at xelatex.
#
# Policy: any adjacent run of 2+ carets reduces to a single escaped
# literal caret (`\^`). Already-valid `^N^` super spans (where the
# carets are NOT adjacent — content sits between them) are untouched.
_DOUBLE_CARET_RE = re.compile(r"\^{2,}")


def _collapse_caret_runs(text: str) -> str:
    return _DOUBLE_CARET_RE.sub(r"\\^", text)


# Stage 12.1 — convert pandoc text-superscript syntax `^X^` to
# explicit LaTeX `\textsuperscript{X}` so pandoc's math-mode parser
# never sees stray carets adjacent to `$math$` spans. Without this,
# patterns like `3$\times$3 mm^3^` get parsed weirdly: pandoc pairs
# the dollars across the `mm^3^` boundary, creating a math-mode
# span that contains `^3^` — which LaTeX reads as
# "superscript-3-superscript" → "Double superscript" error.
#
# This was the dominant cause of the 76 broken-LaTeX abstracts in
# Stage 11.1's `provenance.failed_abstracts[]` (clustered under
# "Double superscript" error signatures).
#
# Match shape: `^<non-space-non-caret content>^`. Mostly affects:
#   - author-affiliation markers (`Doe^1^`)
#   - unit notations (`mm^3^`, `cm^2^`)
#   - inline references (`Smith^2024^`)
# Already-escaped `\^X^` won't match (the leading `^` is preceded
# by `\`); we use a negative lookbehind to skip those.
_CARET_SUPER_RE = re.compile(r"(?<!\\)\^([^\s^]+)\^")


def _caret_super_to_latex(text: str) -> str:
    return _CARET_SUPER_RE.sub(r"\\textsuperscript{\1}", text)


def _normalise_greek_and_math(text: str) -> str:
    """Wrap Greek letters and math operators in `$...$` inline-math
    markers so they fall through to LaTeX's math mode (Computer
    Modern Math by default), which has the Greek alphabet + math
    symbols. Pandoc's default `tex_math_dollars` extension parses
    `$...$` as inline math and emits the correct
    `\\(...\\)` LaTeX wrapping — using `\\(...\\)` directly in
    markdown source would be stripped by pandoc as escaped
    parentheses (the `tex_math_single_backslash` extension is OFF by
    default).

    Each Greek/math glyph yields its own `$...$` span — contiguous
    spans don't collapse because that's harder to undo and the
    rendered PDF treats `$\\alpha$ $+$ $\\beta$` identically to
    `$\\alpha + \\beta$` once you ignore the (invisible) spacing.

    Stage 12.2 — when a Greek/math glyph is ALREADY inside an
    author-written `$...$` math span, we MUST NOT re-wrap it in
    another `$...$` pair. Doing so closes the outer span prematurely
    and reopens it later, producing broken nesting like
    ``$A = diag(e^{$\\alpha$})$`` → pandoc renders this as
    ``\\(A = diag(e^{\\)\\alpha\\(})\\)`` which Tectonic rejects with
    "Missing }" (observed: poster 455). Split the text by `$...$`
    spans first; inside math regions emit the LaTeX command bare
    (no `$` wrap); outside math regions wrap as before.
    """
    parts = _split_by_math_spans(text)
    out: list[str] = []
    for chunk, in_math in parts:
        if in_math:
            # Already in math mode — emit bare commands, no extra `$`.
            chunk = _GREEK_RE.sub(
                lambda m: _GREEK_LATEX[m.group(0)], chunk
            )
            chunk = _MATH_OP_RE.sub(
                lambda m: _MATH_OP_LATEX[m.group(0)], chunk
            )
            out.append(chunk)
        else:
            chunk = _GREEK_RE.sub(
                lambda m: f"${_GREEK_LATEX[m.group(0)]}$", chunk
            )

            def _mathop(m: "re.Match[str]") -> str:
                repl = _MATH_OP_LATEX[m.group(0)]
                if repl.startswith("\\"):
                    return f"${repl}$"
                return repl

            chunk = _MATH_OP_RE.sub(_mathop, chunk)
            out.append(chunk)
    return "".join(out)


# Match author-written inline-math spans (`$...$`). Single-dollar
# only — display math (`$$...$$`) is handled by recognising the
# balanced pair as TWO `$...$` regions with an empty inside, which
# is harmless. The non-greedy body excludes `$` so we don't span
# across multiple math regions. Backslash-escaped `\$` (literal
# dollar sign) is NOT treated as a delimiter.
_MATH_SPAN_RE = re.compile(r"(?<!\\)\$([^$]*?)(?<!\\)\$")


def _split_by_math_spans(text: str) -> list[tuple[str, bool]]:
    """Return ``[(chunk, in_math), ...]`` covering ``text`` end-to-end.

    Inside math spans (``in_math=True``) the chunk includes the
    opening `$` and closing `$` so reassembly via ``"".join`` round-
    trips exactly. Outside math, the chunk is plain text.
    """
    parts: list[tuple[str, bool]] = []
    cursor = 0
    for m in _MATH_SPAN_RE.finditer(text):
        if m.start() > cursor:
            parts.append((text[cursor : m.start()], False))
        parts.append((m.group(0), True))
        cursor = m.end()
    if cursor < len(text):
        parts.append((text[cursor:], False))
    return parts


def html_to_pandoc_md(html: str) -> str:
    """Convert an Oxford-corpus HTML fragment to pandoc markdown.

    Pure function, no I/O. Returns a stripped string; empty input
    yields empty output.
    """
    if not html or not html.strip():
        return ""

    soup = BeautifulSoup(html, "html.parser")

    # Flatten nested <sup>/<sub> first. The Oxford rich-text editor
    # occasionally produces `<sup><sup>2</sup></sup>` (operator error
    # or paste artefact). If left as-is the conversion below emits
    # `^^2^^` which pandoc parses as a literal-caret + invalid super
    # → "Double superscript" LaTeX error. Unwrapping the inner tag
    # before conversion produces a clean `^2^`.
    for tag in list(soup.find_all(["sup", "sub"])):
        parent = tag.parent
        while parent is not None and parent.name in ("sup", "sub"):
            tag.unwrap()
            break

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

    # Fold the Mathematical Alphanumeric Symbols block (U+1D400-
    # U+1D7FF) — math-italic letters and styled digits authors paste
    # directly — into basic Latin / Greek / digit glyphs. Loses the
    # italic/bold styling (acceptable in body prose) and lets the
    # Greek+math normaliser below pick up the math-italic Greek
    # variants through a single code path.
    md = _fold_math_alphanumerics(md)
    # Normalise direct Unicode super/subscript glyphs into pandoc
    # `^...^` / `~...~` literals. Run AFTER markdownify so we operate
    # on plain text — any `<sup>`/`<sub>` already became `^...^` /
    # `~...~` in the BeautifulSoup pre-pass above.
    md = _normalise_unicode_super_sub(md)
    # Wrap Greek letters + math operators in `\(...\)` so the LaTeX
    # renderer sees them via Latin Modern Math (the text-mode font
    # lacks the codepoints).
    md = _normalise_greek_and_math(md)

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
