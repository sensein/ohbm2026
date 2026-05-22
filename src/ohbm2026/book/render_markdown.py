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

# Disable Pillow's decompression-bomb safety check at module-import
# time. The default ~179 MP limit defends against malicious external
# uploads; our corpus comes from Oxford Abstracts and is fully
# trusted. A handful of legitimate figures (large screenshots,
# high-res neuroimaging exports) exceed 179 MP and would otherwise
# crash the whole joblib batch via raise-on-first-failure semantics.
# Setting it here (not inside _copy_figure) means each joblib loky
# worker pays the override exactly once at module import, not on
# every per-figure call. The Pillow import is lazy via a try block
# so unit tests that compose the markdown without copying figures
# don't pay the Pillow import cost when render_markdown loads.
try:
    from PIL import Image as _PIL_Image  # noqa: F401

    _PIL_Image.MAX_IMAGE_PIXELS = None
except ImportError:
    pass

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
    # Stage 12 US2 — every figure under fig_assets/ is JPEG q=90
    # regardless of source format (PNG, GIF, WebP, TIF all re-encoded).
    # The markdown references MUST match the on-disk files, so this
    # helper now returns `.jpg` unconditionally. Sources whose Pillow
    # decode fails still get byte-copied with original extension by
    # `_copy_figure`, BUT they're audited in
    # `_figure_normalise_fallbacks` and the markdown body still
    # references the `.jpg` path; pandoc/Tectonic will warn loudly
    # for that missing file (which is the loud-failure surface the
    # operator wants — silent absence would be worse).
    return "jpg"


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


def entry_to_md(entry: BookEntry) -> str:
    """Render one abstract section as markdown (Stage 11.1 public helper).

    Stable wrapper around `_entry_md` for the per-abstract PDF pipeline
    in :mod:`ohbm2026.book.render_per_abstract`. Discards the figure-
    filename side-effect list — figures are still written by
    :func:`emit_book_md` for the markdown bundle; the per-abstract
    render reads them via pandoc's ``--resource-path``.

    Stage 12.1 — applies ``normalise_for_latex`` so per-chunk
    markdown gets the same caret-superscript → ``\\textsuperscript{}``
    conversion that the assembled ``book.md`` does. Without this,
    abstracts with mixed ``$\\times$`` math spans + ``^N^`` text
    superscripts trigger "Double superscript" LaTeX errors at
    Tectonic time (the dominant Stage-11.1 failure cluster).
    """

    from ohbm2026.book.html_to_md import normalise_for_latex

    return normalise_for_latex(_entry_md(entry, fig_filenames=[]))


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

    Stage 11.1 — figure resizing runs joblib-parallel + skips
    already-present destinations (no rmtree of fig_assets/ on entry),
    so the first build pays the ~3-min cost once and subsequent runs
    just byte-skip. **Operator: if you change ``--max-image-width``,
    delete ``data/outputs/book/.staging__*/fig_assets/`` manually
    OR `rm -rf data/outputs/book/`** — the cache has no per-file
    width sidecar so it can't auto-invalidate.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    fig_dir = output_dir / "fig_assets"
    fig_dir.mkdir(exist_ok=True)

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
    # We iterate over entries to recover the (fig, filename) pairing
    # (deterministic order, no rely-on-side-effects), then dispatch
    # the resize work via joblib loky-backed parallel. Per-file
    # `dest.exists()` short-circuit means warm runs are O(N) stat
    # calls — no Pillow load.
    copy_jobs: list[tuple[pathlib.Path, pathlib.Path, int | None]] = []
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
                # Resolve to absolute paths before handing off to joblib.
                # Loky's worker pool may have been created in a prior
                # cwd (pools are process-pool-cached); workers can't
                # find relative paths that aren't relative to their
                # initial cwd. Absolute paths are immune to that.
                copy_jobs.append(
                    (
                        fig.local_path.resolve(),
                        dest.resolve(),
                        max_image_width,
                    )
                )

    if copy_jobs:
        # Lazy import joblib — only the figure-resize codepath needs
        # it; unit tests that compose the markdown without copying
        # figures don't pay the import cost.
        from joblib import Parallel, delayed

        Parallel(n_jobs=-1, backend="loky")(
            delayed(_copy_figure)(src, dest, max_width)
            for (src, dest, max_width) in copy_jobs
        )


# Stage 12 US2 — figure normalisation parameters. Every figure is
# re-encoded to JPEG q=90 at the 150 DPI dimension cap (≈ 975 px at
# the book's 6.5" content width). PNG sources with transparency flatten
# to RGB against white before save.
FIGURE_JPEG_QUALITY = 90
FIGURE_DPI = 150
FIGURE_CONTENT_WIDTH_INCHES = 6.5
FIGURE_WIDTH_CAP = int(FIGURE_DPI * FIGURE_CONTENT_WIDTH_INCHES)  # 975 px

# Module-level audit registry of byte-copy fallbacks — figures Pillow
# couldn't open. The CLI reads this at provenance-write time (per
# CA-006 / FR-006). Joblib loky workers each see their own copy of
# the module; the orchestrator collects via `get_normalise_fallbacks`.
_figure_normalise_fallbacks: list[dict[str, object]] = []


def get_normalise_fallbacks() -> list[dict[str, object]]:
    """Return a copy of the figure-normalisation fallback list."""
    return list(_figure_normalise_fallbacks)


def reset_normalise_fallbacks() -> None:
    """Reset the fallback registry. The CLI calls this after writing
    provenance so the next build starts with an empty list."""
    _figure_normalise_fallbacks.clear()


def _copy_figure(
    src: pathlib.Path, dest: pathlib.Path, max_width: int | None
) -> None:
    """Stage 12 US2 — re-encode the source figure to JPEG q=90 at a
    150 DPI dimension cap and write to ``dest`` (extension forced to
    ``.jpg``). Source format does NOT matter: even already-small
    JPEGs re-encode through Pillow so the output is deterministic.

    PNG sources with transparency convert to RGB on a white background
    before JPEG save (print convention — transparent PNGs would otherwise
    render as black in the embedded JPEG). Pillow-unopenable sources
    fall back to a byte-copy with the original extension AND an entry
    in ``_figure_normalise_fallbacks`` (CA-006 / FR-006).
    """

    # Lazy import — keeps Pillow off the startup path for callers
    # that don't render figures. The decompression-bomb-check disable
    # lives at module-import time (see top of file) so loky workers
    # get the override once at import.
    from PIL import Image, UnidentifiedImageError

    # Honour the caller-passed max_width when it's tighter than the
    # 150 DPI cap (e.g. the operator passed `--max-image-width=800`).
    effective_cap = FIGURE_WIDTH_CAP
    if max_width is not None and max_width > 0:
        effective_cap = min(FIGURE_WIDTH_CAP, max_width)

    # Force `.jpg` extension regardless of caller's input. Stage 12
    # contract: every fig_assets/ file is `.jpg` after normalisation.
    jpg_dest = dest.with_suffix(".jpg")

    try:
        with Image.open(src) as img:
            img.load()  # force decode now so EXIF / truncated streams raise here
            fmt = (img.format or "").upper()
            # Scale-down only (no upscale).
            target_width = min(img.width, effective_cap)
            if target_width < img.width:
                scale = target_width / img.width
                target_height = max(1, round(img.height * scale))
                resized = img.resize((target_width, target_height), Image.Resampling.LANCZOS)
            else:
                resized = img
            # Flatten transparency against white before JPEG save.
            if resized.mode in ("RGBA", "LA"):
                from PIL import Image as _Image

                bg = _Image.new("RGB", resized.size, (255, 255, 255))
                bg.paste(resized, mask=resized.split()[-1])
                resized = bg
            elif resized.mode != "RGB":
                resized = resized.convert("RGB")
            resized.save(
                jpg_dest,
                format="JPEG",
                quality=FIGURE_JPEG_QUALITY,
                optimize=True,
                progressive=True,
            )
        # Clean up the source-extension dest if a prior run wrote there.
        if dest != jpg_dest and dest.exists():
            try:
                dest.unlink()
            except OSError:
                pass
    except (UnidentifiedImageError, OSError) as exc:
        # Pillow can't open this — byte-copy fallback with original
        # extension preserved. Audit the failure (FR-006 / CA-006).
        shutil.copy2(src, dest)
        # The figure-asset filename contract is
        # `<submission_id>-<poster_id>-<type>[-<index>].<ext>` —
        # extract the poster_id from the dest stem.
        stem_parts = dest.stem.split("-")
        poster_id_str = stem_parts[1] if len(stem_parts) >= 2 else ""
        _figure_normalise_fallbacks.append(
            {
                "poster_id": poster_id_str,
                "filename": dest.name,
                "error_reason": f"{type(exc).__name__}: {exc}",
            }
        )
