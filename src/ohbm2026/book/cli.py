"""CLI entry point for `ohbmcli book`.

Orchestrates: corpus load → sort → author index → emit markdown
bundle → (optional) pandoc PDF → write provenance. Runs the system-
dep preflight upfront so failures surface before composition.
"""

from __future__ import annotations

import argparse
import hashlib
import pathlib
import sys
from dataclasses import replace

from ohbm2026.book.author_index import build_author_index
from ohbm2026.book.corpus import load_book
from ohbm2026.book.provenance import write_provenance
from ohbm2026.book.render_markdown import emit_book_md
from ohbm2026.book.sort import STRATEGIES
from ohbm2026.exceptions import BookBuildError, ProvenanceError

_VALID_FORMATS = ("md", "pdf", "all")
_RETIRED_FORMATS = ("docx",)
_DOCX_RETIREMENT_MESSAGE = (
    "error: docx export was retired in Stage 11.1 — use --format md "
    "(markdown bundle) or --format pdf (per-abstract PDF pipeline) "
    "instead. See docs/abstracts-book-plan.md for the migration note."
)
_VALID_STYLES = ("plain", "tufte")


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="ohbmcli book",
        description="Compose a publication-quality book of all accepted abstracts.",
    )
    p.add_argument(
        "--sort",
        default="poster_id",
        choices=list(STRATEGIES.keys()),
        help="Sort order for abstract entries (default: poster_id).",
    )
    p.add_argument(
        "--format",
        default="md",
        # `docx` is intentionally accepted at the parser level so we
        # can emit a typed retirement message in `main()`; argparse
        # would otherwise reject with a generic "invalid choice"
        # line that doesn't name the alternatives.
        choices=tuple(list(_VALID_FORMATS) + list(_RETIRED_FORMATS)),
        help="Output format. `md` is always emitted (canonical intermediate); "
        "`pdf` is derived via the per-abstract pipeline; `all` produces both. "
        "`docx` was retired in Stage 11.1 (rejected with a pointer at the "
        "surviving formats).",
    )
    p.add_argument(
        "--style",
        default="plain",
        choices=_VALID_STYLES,
        help="PDF document-class style; ignored for md/docx.",
    )
    p.add_argument(
        "--corpus",
        default="data/primary/abstracts.json",
        help="Path to the accepted-corpus JSON.",
    )
    p.add_argument(
        "--authors",
        default="data/primary/authors.json",
        help="Path to the authors lookup JSON.",
    )
    p.add_argument(
        "--withdrawn",
        default="data/primary/abstracts_withdrawn.json",
        help="Path to the withdrawn-id source JSON.",
    )
    p.add_argument(
        "--assets-root",
        default="data/primary/assets",
        help=(
            "Directory holding the high-resolution figure files. "
            "Falls back to `data/inputs/assets/` (legacy) and the "
            "corpus-recorded absolute path; first hit wins."
        ),
    )
    p.add_argument(
        "--standby-csv",
        default="data/primary/032626 OHBM 2026 Poster Listing_FINAL.xlsx - Poster Listing.csv",
        help=(
            "Path to the authoritative OHBM 2026 poster standby CSV "
            "(keyed by poster_id). Default points at the FINAL program "
            "listing under data/primary/. Pass an empty string to omit "
            "standby times from the rendered book."
        ),
    )
    p.add_argument(
        "--output-root",
        default="data/outputs/book",
        help="Root for the produced book directory.",
    )
    p.add_argument(
        "--include-section",
        action="append",
        default=[],
        help="Extra response question_name to include in the body, beyond the "
        "default six (repeatable).",
    )
    p.add_argument(
        "--max-image-width",
        type=int,
        default=1800,
        help=(
            "Cap embedded figure pixel width at this value (Pillow LANCZOS "
            "resize, aspect ratio preserved). 1800 px ≈ 277 DPI at 6.5\" "
            "display — publication quality. Default 1800 keeps the corpus "
            "docx under ~1 GB; without resize the real-corpus docx hits "
            "~6 GB which Word refuses to open. Set to 0 to disable "
            "resizing (byte-copy from source)."
        ),
    )
    p.add_argument(
        "--no-determinism-strip",
        action="store_true",
        help="Skip the PDF/DOCX metadata-strip post-process (debug only).",
    )
    p.add_argument(
        "--state-key",
        default=None,
        help="Override the state-key suffix on the output directory.",
    )
    # Stage 12 US5 — margin preset.
    p.add_argument(
        "--margins",
        default="tight",
        choices=("tight", "loose"),
        help=(
            "Book margin preset (Stage 12). `tight` (default) uses "
            "\\usepackage[margin=0.65in]{geometry} for ≥ 15%% page-"
            "count reduction. `loose` recovers the LaTeX `book` "
            "class default (~1in margins) for archival / comparison."
        ),
    )
    # Stage 11.1 — per-abstract PDF pipeline flags.
    p.add_argument(
        "--workers",
        type=int,
        default=-1,
        help=(
            "joblib.Parallel n_jobs for per-abstract PDF rendering. "
            "Default -1 (all cores). Pass 1 for serial debug builds."
        ),
    )
    p.add_argument(
        "--no-cache",
        action="store_true",
        help=(
            "Bypass the per-abstract PDF cache (every chunk re-renders). "
            "Existing cache entries are NOT overwritten — only fresh "
            "renders get persisted on success."
        ),
    )
    p.add_argument(
        "--cache-dir",
        default="data/cache/book/abstracts",
        help=(
            "Where the per-abstract PDF cache lives. Default "
            "data/cache/book/abstracts — gitignored under the root "
            "data/ rule."
        ),
    )
    return p


def _derive_state_key(args: argparse.Namespace, content_state_key: str) -> str:
    """Combine the content state-key (from corpus.load_book) with the
    flags that influence the produced bundle. Same inputs + same
    flags → same key.
    """
    if args.state_key:
        return args.state_key
    h = hashlib.sha256()
    h.update(content_state_key.encode())
    h.update(args.sort.encode())
    h.update(args.format.encode())
    h.update(args.style.encode())
    for s in sorted(args.include_section):
        h.update(s.encode())
    return h.hexdigest()[:12]


def _resolve_output_dir(root: pathlib.Path, state_key: str) -> pathlib.Path:
    return root / f"book__{state_key}"


def _format_needs_pdf(fmt: str) -> bool:
    return fmt in ("pdf", "all")


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    # Stage 11.1 US3: --format docx is retired with a pointer at the
    # surviving formats. Exit 2 (typed BookBuildError) so any operator
    # wrapper script that checks the exit code still distinguishes
    # this from generic argparse errors (exit 1).
    if args.format in _RETIRED_FORMATS:
        print(_DOCX_RETIREMENT_MESSAGE, file=sys.stderr)
        return 2

    corpus_path = pathlib.Path(args.corpus)
    authors_path = pathlib.Path(args.authors)
    withdrawn_path = pathlib.Path(args.withdrawn)
    assets_root = pathlib.Path(args.assets_root)
    output_root = pathlib.Path(args.output_root)
    standby_path = (
        pathlib.Path(args.standby_csv) if args.standby_csv else None
    )

    need_pdf = _format_needs_pdf(args.format)

    # Preflight system deps when format touches pandoc.
    pandoc_version = None
    xelatex_version = None
    if need_pdf:
        from ohbm2026.book.render_via_pandoc import preflight

        try:
            versions = preflight(need_xelatex=need_pdf)
        except BookBuildError as exc:
            print(f"error: {exc}", file=sys.stderr)
            if exc.details:
                print(f"  details: {exc.details}", file=sys.stderr)
            return 2
        pandoc_version = versions.get("pandoc")
        xelatex_version = versions.get("xelatex")

    # Load + filter + convert HTML→md at the corpus boundary.
    try:
        book = load_book(
            corpus_path=corpus_path,
            authors_path=authors_path,
            withdrawn_path=withdrawn_path,
            assets_root=assets_root,
            standby_path=standby_path,
            sort_order=args.sort,
            format=args.format,
            style=args.style,
            include_sections=tuple(args.include_section),
        )
    except BookBuildError as exc:
        print(f"error: {exc}", file=sys.stderr)
        if exc.details:
            print(f"  details: {exc.details}", file=sys.stderr)
        return 2

    # Sort.
    sorter = STRATEGIES[args.sort]
    entries = sorter(book.entries)
    # Author index.
    author_index = build_author_index(entries)
    book = replace(book, entries=entries, author_index=author_index)

    # State-key from inputs + flags. We stage every step under
    # `.staging__<state-key>/` and only atomically promote the
    # directory to `book__<state-key>/` after EVERY requested
    # artefact has been written. Partial failures leave the staging
    # dir on disk so the operator can inspect it; the next run with
    # the same state-key cleans it up and starts fresh.
    state_key = _derive_state_key(args, book.corpus_state_key)
    final_dir = _resolve_output_dir(output_root, state_key)
    staging_dir = output_root / f".staging__{state_key}"
    try:
        output_root.mkdir(parents=True, exist_ok=True)
        if staging_dir.exists():
            import shutil as _sh
            _sh.rmtree(staging_dir)
        staging_dir.mkdir(parents=True)
        # Touch a sentinel to fail fast if unwritable.
        sentinel = staging_dir / ".write-probe"
        sentinel.write_text("ok")
        sentinel.unlink()
    except OSError as exc:
        print(f"error: output root {output_root} is not writable: {exc}", file=sys.stderr)
        return 2

    # Emit the canonical markdown bundle (always).
    max_w: int | None = args.max_image_width if args.max_image_width > 0 else None
    emit_book_md(book, staging_dir, max_image_width=max_w)

    strip_metadata = not args.no_determinism_strip

    # PDF (US1 + Stage 11.1).
    assembled = None
    if need_pdf:
        from ohbm2026.book.render_via_pandoc import to_pdf

        try:
            assembled = to_pdf(
                book,
                staging_dir,
                staging_dir / "book.pdf",
                style=args.style,
                strip_metadata=strip_metadata,
                workers=args.workers,
                no_cache=args.no_cache,
                cache_dir=pathlib.Path(args.cache_dir),
                margins=args.margins,
            )
        except BookBuildError as exc:
            print(f"error: {exc}", file=sys.stderr)
            if exc.details:
                print(f"  details: {exc.details}", file=sys.stderr)
            print(
                f"  partial artefacts left in {staging_dir} for inspection",
                file=sys.stderr,
            )
            return 2
        if assembled.failures:
            print(
                f"warning: {len(assembled.failures)} abstract(s) failed "
                f"to render and were omitted; see provenance.failed_abstracts[]",
                file=sys.stderr,
            )

    # Provenance.
    command_line = " ".join(["ohbmcli", "book", *(argv if argv is not None else sys.argv[1:])])
    try:
        write_provenance(
            book,
            staging_dir,
            corpus_path=corpus_path,
            authors_path=authors_path,
            withdrawn_path=withdrawn_path,
            command_line=command_line,
            pandoc_version=pandoc_version,
            xelatex_version=xelatex_version,
            assembled=assembled,
        )
    except ProvenanceError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    # Atomic promotion. The staging dir + the final dir live under
    # the same `output_root` on the same filesystem, so the rename
    # is a single inode op (POSIX guarantees atomicity on same-fs
    # renames). A prior final_dir for the same state-key is replaced
    # — that's the intentional re-run-is-idempotent behaviour.
    import shutil as _sh

    if final_dir.exists():
        _sh.rmtree(final_dir)
    staging_dir.rename(final_dir)

    print(f"ok: book written to {final_dir}", file=sys.stderr)
    return 0
