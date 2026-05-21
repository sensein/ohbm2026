"""Stage 11.1 — per-abstract pandoc render with content+toolchain cache.

`render_one(entry, …)` returns an :class:`AbstractPdfChunk`:
- cache hit  → ``cache_hit=True``, no subprocess fired.
- cache miss → pandoc subprocess; on success persist + return; on
  failure return a chunk with ``pandoc_stderr`` populated and
  ``cached_path`` pointing at a path that does NOT exist (the
  assembler treats that as a per-abstract failure and routes the
  poster_id to ``provenance.failed_abstracts``).

The renderer DOES NOT raise on per-abstract pandoc failures — the
orchestrator decides whether to isolate or abort (FR-002). It does
raise :class:`BookBuildError` on environmental failures (missing
pandoc binary, unwritable cache dir) since those affect every
abstract identically.

The CLI provides a separate `__main__` so an operator can re-render
one abstract in isolation for debugging:

    PYTHONPATH=src .venv/bin/python -m ohbm2026.book.render_per_abstract \\
        --corpus data/primary/abstracts.json --poster-id 0042 --style plain
"""

from __future__ import annotations

import argparse
import datetime as _dt
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
from importlib import resources

import pikepdf

from ohbm2026.book.cache import (
    cache_pdf_path,
    compute_cache_key,
    hash_header_includes,
    load_cached_pdf,
    store_cached_pdf_from_path,
)
from ohbm2026.book.model import AbstractPdfChunk, BookEntry
from ohbm2026.book.render_markdown import entry_to_md
from ohbm2026.exceptions import BookBuildError


def per_abstract_header_path() -> pathlib.Path:
    """Path to the stripped-down per-abstract LaTeX preamble."""
    pkg = resources.files("ohbm2026.book.templates")
    return pathlib.Path(str(pkg.joinpath("per-abstract.tex.template")))


def render_one(
    entry: BookEntry,
    *,
    style: str,
    header_includes_path: pathlib.Path,
    pandoc_path: str,
    engine_name: str,
    engine_version: str,
    pandoc_version: str,
    cache_dir: pathlib.Path,
    resource_path: pathlib.Path,
    force_no_cache: bool = False,
) -> AbstractPdfChunk:
    """Render one abstract; cache-aware. See module docstring for contract."""

    md_body = entry_to_md(entry)
    header_hash = hash_header_includes(header_includes_path)
    key = compute_cache_key(
        md_body=md_body,
        pandoc_version=pandoc_version,
        engine_version=engine_version,
        header_includes_hash=header_hash,
        style=style,
    )

    if not force_no_cache:
        hit = load_cached_pdf(cache_dir, key)
        if hit is not None:
            _, sidecar = hit
            return AbstractPdfChunk(
                poster_id=entry.poster_id,
                cache_key=key,
                cached_path=cache_pdf_path(cache_dir, key),
                page_count=int(sidecar.get("page_count", 0)),
                cache_hit=True,
                pandoc_stderr=None,
            )

    # Cache miss → pandoc subprocess. Pandoc writes to a temp path
    # inside cache_dir (same filesystem so the final os.replace is
    # atomic); we measure the page count via pikepdf on the temp file
    # then atomic-move it to <key>.pdf via store_cached_pdf_from_path.
    # No bytes round-trip.
    cache_dir.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=f"{key}.",
        suffix=".pdf.tmp",
        dir=str(cache_dir),
    )
    os.close(fd)
    tmp_path = pathlib.Path(tmp_name)
    argv = [
        pandoc_path,
        "--from=markdown+raw_tex+pandoc_title_block-strikeout",
        "--to=pdf",
        f"--pdf-engine={engine_name}",
        "-H",
        str(header_includes_path),
        f"--resource-path={resource_path}",
        "--standalone",
        "-o",
        str(tmp_path),
    ]
    proc = subprocess.run(
        argv,
        input=md_body,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass
        return AbstractPdfChunk(
            poster_id=entry.poster_id,
            cache_key=key,
            cached_path=cache_pdf_path(cache_dir, key),  # NOTE: not on disk
            page_count=0,
            cache_hit=False,
            pandoc_stderr=_tail((proc.stderr or "").strip(), max_bytes=2048),
        )

    # Probe page count via pikepdf, then atomic-move temp → <key>.pdf
    # + write sidecar. No read-then-write-back cycle.
    with pikepdf.Pdf.open(tmp_path) as pdf:
        page_count = len(pdf.pages)

    pdf_path = store_cached_pdf_from_path(
        cache_dir,
        key,
        tmp_path,
        page_count=page_count,
    )

    return AbstractPdfChunk(
        poster_id=entry.poster_id,
        cache_key=key,
        cached_path=pdf_path,
        page_count=page_count,
        cache_hit=False,
        pandoc_stderr=None,
    )


def _tail(text: str, *, max_bytes: int) -> str:
    if len(text) <= max_bytes:
        return text
    # Keep the END (last 2 KB) since pandoc's most informative error
    # lines come at the bottom (the actual TeX error vs the run banner).
    return "…(truncated)…\n" + text[-max_bytes:]


# ---------------------------------------------------------------------------
# Debug CLI: re-render one abstract in isolation
# ---------------------------------------------------------------------------


def _debug_main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="python -m ohbm2026.book.render_per_abstract",
        description=(
            "Render a single abstract in isolation, populating the "
            "per-abstract PDF cache. Useful for diagnosing a chunk "
            "that fails inside the full ohbmcli book pipeline."
        ),
    )
    p.add_argument("--corpus", default="data/primary/abstracts.json")
    p.add_argument("--authors", default="data/primary/authors.json")
    p.add_argument("--withdrawn", default="data/primary/abstracts_withdrawn.json")
    p.add_argument("--assets-root", default="data/primary/assets")
    p.add_argument(
        "--cache-dir",
        default="data/cache/book/abstracts",
        help="Where the per-abstract PDF cache lives.",
    )
    p.add_argument("--style", default="plain", choices=("plain", "tufte"))
    p.add_argument(
        "--poster-id",
        required=True,
        type=int,
        help="poster_id (integer) of the abstract to render.",
    )
    args = p.parse_args(argv)

    from ohbm2026.book.corpus import load_book
    from ohbm2026.book.render_via_pandoc import preflight, resolve_pdf_engine

    try:
        versions = preflight(need_xelatex=True)
    except BookBuildError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    pandoc_version = versions.get("pandoc", "")
    engine_pair = resolve_pdf_engine()
    if engine_pair is None:
        print("error: no LaTeX engine on PATH", file=sys.stderr)
        return 2
    engine_name, engine_version = engine_pair

    book = load_book(
        corpus_path=pathlib.Path(args.corpus),
        authors_path=pathlib.Path(args.authors),
        withdrawn_path=pathlib.Path(args.withdrawn),
        assets_root=pathlib.Path(args.assets_root),
        sort_order="poster_id",
        format="pdf",
        style=args.style,
    )
    entry = next(
        (e for e in book.entries if e.poster_id == args.poster_id),
        None,
    )
    if entry is None:
        print(
            f"error: no abstract with poster_id={args.poster_id} in corpus",
            file=sys.stderr,
        )
        return 2

    pandoc_path = shutil.which("pandoc")
    if not pandoc_path:
        print("error: pandoc not on PATH", file=sys.stderr)
        return 2

    cache_dir = pathlib.Path(args.cache_dir)
    chunk = render_one(
        entry,
        style=args.style,
        header_includes_path=per_abstract_header_path(),
        pandoc_path=pandoc_path,
        engine_name=engine_name,
        engine_version=engine_version,
        pandoc_version=pandoc_version,
        cache_dir=cache_dir,
        # No fig_assets/ directory in single-abstract debug mode; the
        # operator can pass a custom resource-path if they need
        # figures to resolve.
        resource_path=pathlib.Path.cwd(),
    )

    if chunk.pandoc_stderr is not None:
        print(
            f"error: pandoc failed for poster_id={chunk.poster_id} "
            f"(cache_key={chunk.cache_key})",
            file=sys.stderr,
        )
        print(chunk.pandoc_stderr, file=sys.stderr)
        return 2

    cache_action = "hit" if chunk.cache_hit else "miss → stored"
    print(
        f"ok: chunk {chunk.cache_key} ({chunk.page_count} pages, "
        f"{cache_action}) at {chunk.cached_path}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_debug_main())
