"""Emit the canonical `book.md` + flat `fig_assets/` directory.

The markdown bundle is the source-of-truth artefact: PDF and DOCX
derive from it via pandoc (R3). Figure filename contract per
`data-model.md § Layer 3`:
`<submission_id>-<poster_id>-<type>[-<index>].<ext>`. Determinism
(SC-007a): same Book + same output dir → byte-identical `book.md`
+ fig_assets contents.
"""

from __future__ import annotations

import collections
import datetime as _dt
import pathlib
import re
import shutil
from importlib import resources

from ohbm2026.book.model import (
    Author,
    AuthorIndexEntry,
    Book,
    BookEntry,
    FigureBlock,
)


_DEF_TYPE_STRIP_SUFFIX = " figure"


def _figure_type(question_name: str) -> str:
    stem = question_name.strip().casefold()
    if stem.endswith(_DEF_TYPE_STRIP_SUFFIX):
        stem = stem[: -len(_DEF_TYPE_STRIP_SUFFIX)].strip()
    stem = re.sub(r"[^a-z0-9]+", "-", stem).strip("-")
    return stem or "figure"


def _ext_for(fig: FigureBlock) -> str:
    if fig.content_type:
        ct = fig.content_type.lower()
        if "png" in ct:
            return "png"
        if "jpeg" in ct or "jpg" in ct:
            return "jpg"
        if "gif" in ct:
            return "gif"
        if "webp" in ct:
            return "webp"
        if "tiff" in ct or "tif" in ct:
            return "tif"
    return fig.local_path.suffix.lstrip(".").lower() or "png"


def _figure_filename(entry: BookEntry, fig: FigureBlock, idx_in_type: int, n_of_type: int) -> str:
    """Build the figure filename per `data-model.md § Layer 3`.

    `idx_in_type` is 1-based; `n_of_type` is the total count of
    figures of this type within the entry. The index suffix is
    omitted when n_of_type == 1.
    """
    poster = f"{entry.poster_id:04d}"
    ftype = _figure_type(fig.question_name)
    ext = _ext_for(fig)
    if n_of_type > 1:
        return f"{entry.submission_id}-{poster}-{ftype}-{idx_in_type}.{ext}"
    return f"{entry.submission_id}-{poster}-{ftype}.{ext}"


def _figure_id(entry: BookEntry, fig: FigureBlock, idx_in_type: int, n_of_type: int) -> str:
    """The pandoc `{#id}` for a figure — uses the same type/index
    components as the filename so the LaTeX `\\ref{}` machinery can
    cross-reference.
    """
    poster = f"{entry.poster_id:04d}"
    ftype = _figure_type(fig.question_name)
    if n_of_type > 1:
        return f"fig-{poster}-{ftype}-{idx_in_type}"
    return f"fig-{poster}-{ftype}"


def _author_list_md(authors: tuple[Author, ...]) -> str:
    """Comma-separated author display names with inline \\index{}
    markers. Affiliations follow in parens.
    """
    parts: list[str] = []
    seen_affiliations: list[str] = []
    aff_lookup: dict[str, int] = {}

    for a in authors:
        # Aggregate affiliations across authors, preserving first-occurrence
        # order; emit a parenthetical superscript per author later.
        aff_indices: list[int] = []
        for aff in a.affiliations:
            label = f"{aff.institution}, {aff.city}, {aff.country}"
            if label not in aff_lookup:
                aff_lookup[label] = len(seen_affiliations) + 1
                seen_affiliations.append(label)
            aff_indices.append(aff_lookup[label])
        sup = ",".join(str(i) for i in aff_indices)
        sup_token = f"^{sup}^" if sup else ""
        parts.append(f"{a.display_name}{sup_token}\\index{{{a.latex_index_key}}}")

    name_line = ", ".join(parts) if parts else "_(no authors on file)_"
    if seen_affiliations:
        aff_lines = "  \n".join(
            f"^{i + 1}^ {label}" for i, label in enumerate(seen_affiliations)
        )
        return f"**Authors**: {name_line}\n\n{aff_lines}"
    return f"**Authors**: {name_line}"


def _figure_block_md(
    entry: BookEntry, fig: FigureBlock, idx_in_type: int, n_of_type: int
) -> str:
    """Markdown for one figure (or its 'unavailable' placeholder)."""
    label = fig.question_name.strip() or "Figure"
    if fig.error:
        return (
            f"> **figure unavailable: {fig.error}** "
            f"(intended: {label}, asset path "
            f"`{fig.local_path.name or '(unknown)'}`)\n"
        )
    filename = _figure_filename(entry, fig, idx_in_type, n_of_type)
    fid = _figure_id(entry, fig, idx_in_type, n_of_type)
    return f"![Figure — {label}](fig_assets/{filename}){{#{fid}}}\n"


def _standby_md(entry: BookEntry) -> str | None:
    """One-line standby summary, or None when no standby info exists.

    Format: `**Standby**: <first label> · <second label>`
    Uses the original CSV cell text verbatim so the reader sees the
    local-time label they're used to seeing in OHBM communications.
    """
    if entry.standby is None:
        return None
    parts: list[str] = []
    if entry.standby.first:
        parts.append(entry.standby.first.label)
    if entry.standby.second:
        parts.append(entry.standby.second.label)
    if not parts:
        return None
    return "**Standby**: " + " · ".join(parts)


def _entry_md(entry: BookEntry, fig_filenames: list[str]) -> str:
    """Render one abstract section as markdown.

    `fig_filenames` is filled in by this function — caller uses it to
    drive the file copies.
    """
    poster = f"{entry.poster_id:04d}"
    out: list[str] = []
    out.append(f"## Abstract {poster} — {entry.title} {{#abstract-{poster}}}\n")
    out.append("")
    out.append(_author_list_md(entry.authors))
    out.append("")
    standby_line = _standby_md(entry)
    if standby_line:
        out.append(standby_line)
        out.append("")

    # Counts per type so we know whether to apply the -1/-2 suffix.
    type_counts = collections.Counter(
        _figure_type(f.question_name) for f in entry.figures
    )
    type_seen: dict[str, int] = collections.defaultdict(int)

    # Body sections in canonical order (corpus.py already filters +
    # orders by BODY_SECTION_NAMES).
    sections_by_name = {s.name: s for s in entry.body_sections}

    # Methods section + Methods Figure rendered together.
    section_order = (
        "Introduction",
        "Methods",
        "Results",
        "Conclusion",
        "Acknowledgement",
    )
    methods_figs = [
        f for f in entry.figures if _figure_type(f.question_name) == "methods"
    ]
    results_figs = [
        f for f in entry.figures if _figure_type(f.question_name) == "results"
    ]
    other_figs = [
        f
        for f in entry.figures
        if _figure_type(f.question_name) not in ("methods", "results")
    ]

    for name in section_order:
        s = sections_by_name.get(name)
        if s is None:
            continue
        out.append(f"### {name}\n")
        out.append("")
        out.append(s.markdown.rstrip())
        out.append("")
        if name == "Methods":
            for fig in methods_figs:
                type_seen["methods"] += 1
                idx = type_seen["methods"]
                n_of_type = type_counts["methods"]
                out.append(_figure_block_md(entry, fig, idx, n_of_type))
                if not fig.error:
                    fig_filenames.append(
                        _figure_filename(entry, fig, idx, n_of_type)
                    )
            if methods_figs:
                out.append("")
        if name == "Results":
            for fig in results_figs:
                type_seen["results"] += 1
                idx = type_seen["results"]
                n_of_type = type_counts["results"]
                out.append(_figure_block_md(entry, fig, idx, n_of_type))
                if not fig.error:
                    fig_filenames.append(
                        _figure_filename(entry, fig, idx, n_of_type)
                    )
            if results_figs:
                out.append("")

    # Any other figure types render at the end of the entry.
    for fig in other_figs:
        ftype = _figure_type(fig.question_name)
        type_seen[ftype] += 1
        idx = type_seen[ftype]
        n_of_type = type_counts[ftype]
        out.append(_figure_block_md(entry, fig, idx, n_of_type))
        if not fig.error:
            fig_filenames.append(_figure_filename(entry, fig, idx, n_of_type))
    if other_figs:
        out.append("")

    if entry.references is not None:
        out.append("### References\n")
        out.append("")
        out.append(entry.references.markdown.rstrip())
        out.append("")

    out.append("\\clearpage")
    out.append("")
    return "\n".join(out)


def _author_index_back_matter_md(index: tuple[AuthorIndexEntry, ...]) -> str:
    out: list[str] = []
    out.append("# Author Index\n")
    out.append("")
    out.append("\\printindex")
    out.append("")
    out.append("<details><summary>Author Index (anchor links)</summary>")
    out.append("")
    for entry in index:
        links = ", ".join(
            f"[{pid:04d}](#abstract-{pid:04d})" for pid in entry.poster_ids
        )
        out.append(f"- {entry.display_name} → {links}")
    out.append("")
    out.append("</details>")
    out.append("")
    return "\n".join(out)


def _read_template() -> str:
    # importlib.resources keeps the templates packaged-with-the-code.
    pkg = resources.files("ohbm2026.book.templates")
    return pkg.joinpath("book.md.template").read_text(encoding="utf-8")


def emit_book_md(
    book: Book,
    output_dir: pathlib.Path,
    *,
    max_image_width: int | None = 1800,
) -> None:
    """Write `book.md` + the flat `fig_assets/` directory.

    Idempotent: the same `book` produces byte-identical output on
    re-run (SC-007a). The `built_at_date` field in the header is a
    fixed string (`1970-01-01`) so the markdown is byte-identical;
    the canonical run-time timestamp lives in `provenance.json`.

    `max_image_width` (default 1800 px ≈ 277 DPI at 6.5" display —
    publication-quality print) caps the figure dimensions written
    into ``fig_assets/``. Set to None to copy figures byte-for-byte
    from the original `local_path`. Resizing keeps PNG bit-depth +
    JPEG quality at sensible defaults; aspect ratio preserved.
    Without resize the OHBM corpus produces a 6 GB pandoc docx that
    Word refuses to open.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    fig_dir = output_dir / "fig_assets"
    if fig_dir.exists():
        shutil.rmtree(fig_dir)
    fig_dir.mkdir()

    template = _read_template()
    header = template.format(
        built_at_date="1970-01-01",
        sort_order=book.sort_order,
        corpus_state_key=book.corpus_state_key,
        abstract_count=len(book.entries),
    )

    fig_filenames: list[str] = []
    body_chunks = [_entry_md(e, fig_filenames) for e in book.entries]
    back_matter = _author_index_back_matter_md(book.author_index)

    full = header.rstrip() + "\n\n" + "\n".join(body_chunks).rstrip() + "\n\n" + back_matter
    # Normalize trailing whitespace + ensure exactly one trailing newline.
    full = "\n".join(line.rstrip() for line in full.splitlines()).rstrip() + "\n"
    # Second-pass normalisation: catches Unicode glyphs the emitter
    # itself injected (e.g. `→` in the anchor-link back matter) that
    # never went through `html_to_pandoc_md`. Idempotent on
    # already-converted spans.
    from ohbm2026.book.html_to_md import normalise_for_latex

    full = normalise_for_latex(full)
    (output_dir / "book.md").write_text(full, encoding="utf-8")

    # Copy the figure assets — flat directory, names from the contract.
    # We iterate over entries again to recover the (fig, filename)
    # pairing (deterministic order, no rely-on-side-effects).
    for entry in book.entries:
        type_counts = collections.Counter(
            _figure_type(f.question_name) for f in entry.figures
        )
        type_seen: collections.Counter = collections.Counter()
        for fig in entry.figures:
            if fig.error:
                continue
            ftype = _figure_type(fig.question_name)
            type_seen[ftype] += 1
            filename = _figure_filename(
                entry, fig, type_seen[ftype], type_counts[ftype]
            )
            dest = fig_dir / filename
            if fig.local_path.exists() and not dest.exists():
                _copy_figure(fig.local_path, dest, max_image_width)


def _copy_figure(
    src: pathlib.Path, dest: pathlib.Path, max_width: int | None
) -> None:
    """Copy `src` to `dest`, optionally downsizing if its pixel width
    exceeds `max_width`. Preserves format (PNG → PNG, JPEG → JPEG).
    Falls back to byte-copy when Pillow can't open the source.
    """
    if max_width is None:
        shutil.copy2(src, dest)
        return
    # Lazy import — keeps Pillow off the startup path for callers
    # that don't render figures (e.g. unit tests on the markdown
    # composer only).
    from PIL import Image, UnidentifiedImageError

    try:
        with Image.open(src) as img:
            if img.width <= max_width:
                # Already small enough; byte-copy.
                shutil.copy2(src, dest)
                return
            scale = max_width / img.width
            new_size = (max_width, max(1, round(img.height * scale)))
            resized = img.resize(new_size, Image.Resampling.LANCZOS)
            # Format-preserving save. PNG keeps full quality; JPEG
            # uses q=85 (standard print/web threshold, matches the
            # Stage-2 figure-analysis pipeline's compression policy).
            fmt = (img.format or "").upper()
            save_kwargs: dict[str, object] = {"optimize": True}
            if fmt == "JPEG":
                save_kwargs["quality"] = 85
                save_kwargs["progressive"] = True
            elif fmt == "PNG":
                save_kwargs["compress_level"] = 9
            # If RGBA → RGB conversion is needed for JPEG.
            save_image = resized
            if fmt == "JPEG" and save_image.mode in ("RGBA", "P", "LA"):
                save_image = save_image.convert("RGB")
            save_image.save(dest, format=fmt or "PNG", **save_kwargs)
    except (UnidentifiedImageError, OSError):
        # Anything Pillow refuses to open — fall back to a raw copy
        # so the figure still appears in the bundle. The figure-
        # resolution probe at corpus load will already have flagged
        # it; emit_book_md doesn't second-guess.
        shutil.copy2(src, dest)
