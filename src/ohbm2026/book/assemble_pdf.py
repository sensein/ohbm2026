"""Stage 11.1 — two-pass assembly of per-abstract PDF chunks.

Pass 1: concatenate chunks (front matter + per-abstract) into a draft
        PDF via :mod:`pikepdf`. Record each chunk's starting page
        offset (1-based) in `AssembledBook.chunk_offsets`.

Pass 2: build a hand-rolled author-index appendix markdown using the
        MEASURED chunk offsets from pass 1 (so page numbers in the
        index are guaranteed-correct), pandoc-compile it to its own
        PDF chunk, and concatenate onto the draft → final book.pdf.

The pass-2 author index is computed directly from
``book.author_index`` + ``chunk_offsets`` rather than via LaTeX's
``\\index{}`` / ``\\printindex`` machinery, because the latter binds
each ``\\index{}`` macro to the page where it's *shipped out*, not
the page where ``\\setcounter{page}`` was last set. Hand-rolling the
appendix keeps the page numbers provably right.

Hardware constraint: this is the only stage that must hold every
chunk PDF in memory simultaneously. At ~50 KB per chunk × 3,242
abstracts that's ~160 MB — fine on any developer laptop.
"""

from __future__ import annotations

import collections
import datetime as _dt
import pathlib
import shutil
import subprocess
import time
from typing import Sequence

import pikepdf

from ohbm2026.book.model import (
    AbstractPdfChunk,
    AssembledBook,
    AuthorIndexEntry,
    PerAbstractFailure,
)
from ohbm2026.exceptions import BookBuildError


def assemble(
    chunks: Sequence[AbstractPdfChunk],
    front_matter_chunk: AbstractPdfChunk,
    output_path: pathlib.Path,
    *,
    pandoc_path: str | None,
    engine_binary: str,
    header_includes_path: pathlib.Path,
    style: str,
    draft_dir: pathlib.Path,
    author_index: Sequence[AuthorIndexEntry] = (),
    failures: Sequence[PerAbstractFailure] = (),
    cache_hit_count: int = 0,
    cache_miss_count: int = 0,
) -> AssembledBook:
    """Two-pass assembly. See module docstring for the algorithm."""

    if not chunks:
        raise BookBuildError(
            "no abstract chunks to assemble — every per-abstract render failed",
        )
    if pandoc_path is None:
        raise BookBuildError(
            "pandoc not available for index-appendix pass-2 render",
        )

    started = time.monotonic()
    draft_dir.mkdir(parents=True, exist_ok=True)
    draft_path = draft_dir / "draft.pdf"

    # ---- Pass 1: concatenate + measure offsets ----------------------
    chunk_offsets: list[tuple[int, int]] = []
    next_start = 1  # PDF pages are 1-based for display

    with pikepdf.Pdf.new() as draft:
        # Front matter first.
        with pikepdf.Pdf.open(front_matter_chunk.cached_path) as fm:
            chunk_offsets.append((front_matter_chunk.poster_id, next_start))
            draft.pages.extend(fm.pages)
            next_start += len(fm.pages)
            front_matter_pages = len(fm.pages)

        # Per-abstract chunks in caller-given (sort) order.
        for chunk in chunks:
            if not chunk.cached_path.exists():
                # Defensive: assembler shouldn't have been handed a
                # failed-render chunk. The orchestrator pre-filters
                # those.
                raise BookBuildError(
                    f"chunk for poster_id={chunk.poster_id} "
                    f"(cache_key={chunk.cache_key}) not on disk; "
                    f"path={chunk.cached_path}",
                )
            with pikepdf.Pdf.open(chunk.cached_path) as src:
                chunk_offsets.append((chunk.poster_id, next_start))
                draft.pages.extend(src.pages)
                next_start += len(src.pages)

        draft.save(draft_path)

    # ---- Pass 2: build hand-rolled index appendix -------------------
    poster_to_start = {pid: start for pid, start in chunk_offsets}
    index_md = _build_index_markdown(
        author_index,
        poster_to_start,
        # The appendix starts on the page AFTER the draft ends.
        first_appendix_page=next_start,
    )

    appendix_pdf = draft_dir / "index_appendix.pdf"
    _render_index_appendix(
        markdown=index_md,
        output_pdf=appendix_pdf,
        pandoc_path=pandoc_path,
        engine_binary=engine_binary,
        header_includes_path=header_includes_path,
        style=style,
    )

    with pikepdf.Pdf.open(appendix_pdf) as ap:
        index_pages = len(ap.pages)

    # Concatenate appendix onto draft → final.
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with pikepdf.Pdf.open(draft_path) as final:
        with pikepdf.Pdf.open(appendix_pdf) as ap:
            final.pages.extend(ap.pages)
        final.save(output_path)

    assembly_time = round(time.monotonic() - started, 3)

    return AssembledBook(
        chunks=(front_matter_chunk, *chunks),
        chunk_offsets=tuple(chunk_offsets),
        front_matter_pages=front_matter_pages,
        draft_path=draft_path,
        final_path=output_path,
        cache_hit_count=cache_hit_count,
        cache_miss_count=cache_miss_count,
        failures=tuple(failures),
        assembly_time_seconds=assembly_time,
        index_pages=index_pages,
    )


def _build_index_markdown(
    author_index: Sequence[AuthorIndexEntry],
    poster_to_start: dict[int, int],
    *,
    first_appendix_page: int,
) -> str:
    """Build the appendix markdown using the measured chunk offsets.

    The appendix is plain markdown rendered to PDF by pandoc — no
    LaTeX ``\\index{}`` / ``\\printindex`` machinery, because that
    would bind page numbers to the appendix's pages rather than to
    each abstract's actual page. We hand-roll the table using the
    measured offsets so the page numbers match the printed pagination.
    """

    lines: list[str] = []
    # YAML metadata so pandoc treats this as a standalone doc.
    lines.append("---")
    lines.append("title: 'Author Index'")
    lines.append("documentclass: book")
    lines.append("---")
    lines.append("")
    lines.append("```{=latex}")
    # \setcounter{page} so the appendix's pages continue from where
    # the draft ended (display-only nicety; matches the draft's
    # printed page numbers).
    lines.append(f"\\setcounter{{page}}{{{first_appendix_page}}}")
    lines.append("```")
    lines.append("")
    lines.append("# Author Index {.unnumbered}")
    lines.append("")
    if not author_index:
        lines.append("_(no author entries to index)_")
        lines.append("")
        return "\n".join(lines)

    for entry in author_index:
        pages: list[int] = []
        for pid in entry.poster_ids:
            page = poster_to_start.get(pid)
            if page is None:
                # Abstract dropped (failure isolation). Skip the page
                # reference but keep the author present.
                continue
            pages.append(page)
        if not pages:
            # Every abstract for this author was filtered out.
            continue
        # `**Doe, J.**` followed by space + comma-separated page numbers.
        # Sort + dedupe so the printed back-of-book reads "12, 47, 50"
        # not "50, 12, 47" — the input ``entry.poster_ids`` is sorted
        # by poster_id (sort.py contract), but the poster_id→page
        # mapping is non-monotonic when --sort is `title` or
        # `first_author`. Explicit sort here keeps the printed index
        # readable regardless of which --sort flag the operator
        # passed.
        sorted_pages = ", ".join(str(p) for p in sorted(set(pages)))
        lines.append(f"**{entry.display_name}** {sorted_pages}")
        lines.append("")
    return "\n".join(lines)


def _render_index_appendix(
    *,
    markdown: str,
    output_pdf: pathlib.Path,
    pandoc_path: str,
    engine_binary: str,
    header_includes_path: pathlib.Path,
    style: str,
) -> None:
    """Run pandoc against the appendix markdown, writing `output_pdf`."""

    argv = [
        pandoc_path,
        "--from=markdown+raw_tex+pandoc_title_block-strikeout",
        "--to=pdf",
        f"--pdf-engine={engine_binary}",
        "-H",
        str(header_includes_path),
        "--standalone",
        "-o",
        str(output_pdf),
    ]
    proc = subprocess.run(
        argv,
        input=markdown,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise BookBuildError(
            f"pandoc returned non-zero ({proc.returncode}) building "
            f"index appendix",
            details=(proc.stderr or "").strip(),
        )
