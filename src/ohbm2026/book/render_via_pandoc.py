"""pandoc subprocess wrappers for the Stage 11.1 PDF orchestrator.

PDF path: :func:`to_pdf` orchestrates a per-abstract render pipeline
driven by :mod:`render_per_abstract` + :mod:`assemble_pdf`. Each
abstract is pandoc-rendered to its own small PDF chunk (cached by
content+toolchain hash); chunks concatenate via pikepdf; a hand-
rolled author-index appendix is pandoc-compiled in a second pass and
appended. Per-abstract failures isolate cleanly — the offending entry
drops out, the rest renders, and the orchestrator returns an
``AssembledBook`` whose ``failures`` carries the diagnostic captures.

DOCX export was retired in Stage 11.1 US3 — the implementation,
the optional ``python-docx`` dep, and the docx-only test module were
removed. The CLI rejects ``--format docx`` with a pointer at the
surviving formats.
"""

from __future__ import annotations

import datetime as _dt
import pathlib
import shutil
import subprocess
from importlib import resources

from ohbm2026.exceptions import BookBuildError


def _which_or_raise(binary: str, hint: str) -> str:
    path = shutil.which(binary)
    if not path:
        raise BookBuildError(
            f"required system dep `{binary}` not on PATH; {hint}",
            details=f"shutil.which({binary!r}) returned None",
        )
    return path


def resolve_pdf_engine() -> tuple[str, str] | None:
    """Return `(binary_name, version_line)` of the first LaTeX engine
    on PATH that pandoc accepts as `--pdf-engine`.

    Preference order: `xelatex` (TeX Live / MacTeX) → `tectonic`
    (lighter, on-demand-fetch). Returns None when neither is available.
    """
    for binary in ("xelatex", "tectonic"):
        path = shutil.which(binary)
        if path:
            return binary, _first_line(subprocess.check_output([path, "--version"]))
    return None


def preflight(*, need_xelatex: bool) -> dict[str, str]:
    """Verify pandoc + (optionally) a LaTeX engine are on PATH.

    Returns a dict of `{name: version_line}` for provenance capture.
    Raises BookBuildError with an operator-actionable install hint
    when a binary is absent. `xelatex` and `tectonic` are accepted
    interchangeably — pandoc handles both as a `--pdf-engine`.
    """
    versions: dict[str, str] = {}
    pandoc = _which_or_raise(
        "pandoc",
        "install via `brew install pandoc` (macOS) or "
        "`apt-get install pandoc` (Linux). See quickstart.md step 2.",
    )
    versions["pandoc"] = _first_line(subprocess.check_output([pandoc, "--version"]))
    if need_xelatex:
        engine = resolve_pdf_engine()
        if engine is None:
            raise BookBuildError(
                "neither `xelatex` nor `tectonic` is on PATH; install one "
                "(Tectonic recommended for lightness: `brew install tectonic` "
                "or full TeX Live `apt-get install texlive-xetex`). "
                "See quickstart.md step 2.",
                details=f"shutil.which('xelatex')={shutil.which('xelatex')!r}, "
                f"shutil.which('tectonic')={shutil.which('tectonic')!r}",
            )
        binary, version_line = engine
        # The provenance schema field stays `xelatex_version` to keep
        # the contract stable — value records which engine actually ran.
        versions["xelatex"] = f"{binary}: {version_line}"
    return versions


def _first_line(b: bytes) -> str:
    return b.decode("utf-8", errors="replace").splitlines()[0].strip()


def _header_includes_path(style: str) -> pathlib.Path:
    """Return the absolute path to the right LaTeX header-includes
    file (plain vs tufte-book). Files live alongside the book
    package so the operator never has to manage them.
    """
    pkg = resources.files("ohbm2026.book.templates")
    if style == "tufte":
        return pathlib.Path(str(pkg.joinpath("header-includes-tufte.tex")))
    return pathlib.Path(str(pkg.joinpath("header-includes.tex")))


def to_pdf(
    book,  # type: ignore[no-untyped-def]
    output_dir: pathlib.Path,
    output_path: pathlib.Path,
    *,
    style: str = "plain",
    strip_metadata: bool = True,
    workers: int = -1,
    no_cache: bool = False,
    cache_dir: pathlib.Path | None = None,
):
    """Stage 11.1 — orchestrate the per-abstract PDF pipeline.

    Parameters
    ----------
    book :
        Loaded :class:`ohbm2026.book.model.Book`. The renderer iterates
        ``book.entries`` and uses ``book.author_index`` for the
        appendix.
    output_dir :
        Bundle directory (the staging dir created by ``cli.main``). The
        ``fig_assets/`` directory underneath is used as pandoc's
        ``--resource-path`` for per-abstract chunk renders. The front-
        matter chunk and intermediate draft PDF land here too.
    output_path :
        Final ``book.pdf`` location (typically ``output_dir / "book.pdf"``).
    workers :
        ``joblib.Parallel`` ``n_jobs`` argument. Default ``-1`` (all
        cores). ``1`` for serial debug builds.
    no_cache :
        Bypass the per-abstract cache: every chunk re-renders from
        scratch. Existing cache entries are NOT overwritten — only
        re-rendered ones get persisted on success.
    cache_dir :
        Where the per-abstract cache lives. Defaults to
        ``data/cache/book/abstracts``.

    Returns
    -------
    ``AssembledBook`` carrying the chunk_offsets, failure list, and
    cache hit/miss counts. The CLI hands this to the provenance writer.
    """

    from ohbm2026.book.assemble_pdf import assemble
    from ohbm2026.book.model import (
        AbstractPdfChunk,
        PerAbstractFailure,
    )
    from ohbm2026.book.render_per_abstract import (
        per_abstract_header_path,
        render_one,
    )

    pandoc = shutil.which("pandoc") or _which_or_raise(
        "pandoc", "see quickstart.md step 2"
    )
    engine = resolve_pdf_engine()
    if engine is None:
        raise BookBuildError(
            "neither `xelatex` nor `tectonic` is on PATH; install one. "
            "See quickstart.md step 2.",
        )
    engine_binary, engine_version = engine

    pandoc_version = _first_line(subprocess.check_output([pandoc, "--version"]))

    header_includes = _header_includes_path(style)
    if not header_includes.exists():
        raise BookBuildError(
            f"header-includes file missing at {header_includes} "
            f"(style={style!r})"
        )
    per_chunk_header = per_abstract_header_path()

    if cache_dir is None:
        cache_dir = pathlib.Path("data/cache/book/abstracts")
    cache_dir.mkdir(parents=True, exist_ok=True)
    # Resolve every path passed across the joblib boundary to absolute.
    # Loky's worker pool may have been created in a prior cwd (pools
    # are process-pool-cached); workers can't see relative paths that
    # aren't relative to their initial cwd.
    cache_dir = cache_dir.resolve()
    resource_path = output_dir.resolve()  # fig_assets/ sits under here
    header_includes_abs = header_includes.resolve()
    per_chunk_header_abs = per_chunk_header.resolve()

    # ---- Per-abstract render pass ------------------------------------
    # joblib's loky backend gives process-level parallelism, matching
    # the Stage 4 pattern. Each worker fires its own pandoc subprocess;
    # the cache absorbs duplicate work across re-runs.
    from joblib import Parallel, delayed

    n_jobs = workers if workers != 0 else -1
    render_results = Parallel(n_jobs=n_jobs, backend="loky")(
        delayed(render_one)(
            entry,
            style=style,
            header_includes_path=per_chunk_header_abs,
            pandoc_path=pandoc,
            engine_name=engine_binary,
            engine_version=engine_version,
            pandoc_version=pandoc_version,
            cache_dir=cache_dir,
            resource_path=resource_path,
            force_no_cache=no_cache,
        )
        for entry in book.entries
    )

    # Partition successes vs failures.
    surviving: list[AbstractPdfChunk] = []
    failures: list[PerAbstractFailure] = []
    cache_hits = 0
    cache_misses = 0
    now_iso = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    for chunk in render_results:
        if chunk.pandoc_stderr is not None:
            failures.append(
                PerAbstractFailure(
                    poster_id=chunk.poster_id,
                    cache_key=chunk.cache_key,
                    pandoc_exit_code=-1,  # captured separately if needed
                    stderr_tail=chunk.pandoc_stderr,
                    failed_at=now_iso,
                )
            )
            continue
        if chunk.cache_hit:
            cache_hits += 1
        else:
            cache_misses += 1
        surviving.append(chunk)

    if not surviving:
        raise BookBuildError(
            "zero abstracts survived per-abstract render; check "
            "provenance.failed_abstracts[] for diagnostics",
        )

    # ---- Front matter chunk ------------------------------------------
    # Build a minimal front-matter markdown carrying title + TOC.
    # Rendered once per build; cached under the same cache_dir.
    front_md = _build_front_matter_md(book)
    front = _render_front_matter(
        front_md,
        pandoc_path=pandoc,
        engine_binary=engine_binary,
        engine_version=engine_version,
        pandoc_version=pandoc_version,
        header_includes_path=header_includes_abs,
        style=style,
        cache_dir=cache_dir,
        no_cache=no_cache,
    )

    # ---- Assemble ----------------------------------------------------
    draft_dir = output_dir / ".assembly"
    assembled = assemble(
        surviving,
        front,
        output_path,
        pandoc_path=pandoc,
        engine_binary=engine_binary,
        header_includes_path=header_includes_abs,
        style=style,
        draft_dir=draft_dir,
        author_index=book.author_index,
        failures=failures,
        cache_hit_count=cache_hits,
        cache_miss_count=cache_misses,
    )

    if strip_metadata:
        _strip_pdf_metadata(output_path)

    return assembled


def _build_front_matter_md(book) -> str:  # type: ignore[no-untyped-def]
    """Title page + abstract count + TOC marker.

    The TOC anchors auto-populate via pandoc's `--toc` flag, which the
    front-matter render uses.
    """

    lines: list[str] = []
    lines.append("---")
    lines.append("title: 'OHBM 2026 — Book of Abstracts'")
    lines.append("documentclass: book")
    lines.append("---")
    lines.append("")
    lines.append("# OHBM 2026 — Book of Abstracts {.unnumbered}")
    lines.append("")
    lines.append(f"_{len(book.entries):,} accepted abstracts._")
    lines.append("")
    lines.append(f"_Sort order: {book.sort_order}._")
    lines.append("")
    lines.append(
        f"_Corpus state-key: `{book.corpus_state_key}`_"
    )
    lines.append("")
    lines.append("\\tableofcontents")
    lines.append("")
    return "\n".join(lines)


def _render_front_matter(
    markdown: str,
    *,
    pandoc_path: str,
    engine_binary: str,
    engine_version: str,
    pandoc_version: str,
    header_includes_path: pathlib.Path,
    style: str,
    cache_dir: pathlib.Path,
    no_cache: bool,
):
    """Render the front-matter chunk; cached like a per-abstract chunk."""

    import os as _os
    import tempfile as _tempfile

    import pikepdf

    from ohbm2026.book.cache import (
        cache_pdf_path,
        compute_cache_key,
        hash_header_includes,
        load_cached_pdf,
        store_cached_pdf_from_path,
    )
    from ohbm2026.book.model import AbstractPdfChunk

    header_hash = hash_header_includes(header_includes_path)
    key = compute_cache_key(
        md_body=markdown,
        pandoc_version=pandoc_version,
        engine_version=engine_version,
        header_includes_hash=header_hash,
        style=style,
    )

    if not no_cache:
        hit = load_cached_pdf(cache_dir, key)
        if hit is not None:
            _, sidecar = hit
            return AbstractPdfChunk(
                poster_id=-1,
                cache_key=key,
                cached_path=cache_pdf_path(cache_dir, key),
                page_count=int(sidecar.get("page_count", 0)),
                cache_hit=True,
                pandoc_stderr=None,
            )

    # Same write-temp-then-atomic-move pattern as render_one — no
    # bytes round-trip.
    cache_dir.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = _tempfile.mkstemp(
        prefix=f"{key}.",
        suffix=".pdf.tmp",
        dir=str(cache_dir),
    )
    _os.close(fd)
    tmp_path = pathlib.Path(tmp_name)
    argv = [
        pandoc_path,
        "--from=markdown+raw_tex+pandoc_title_block-strikeout",
        "--to=pdf",
        f"--pdf-engine={engine_binary}",
        "-H",
        str(header_includes_path),
        "--standalone",
        "--toc",
        "-o",
        str(tmp_path),
    ]
    proc = subprocess.run(argv, input=markdown, capture_output=True, text=True)
    if proc.returncode != 0:
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass
        raise BookBuildError(
            f"pandoc returned non-zero ({proc.returncode}) building front matter",
            details=(proc.stderr or "").strip(),
        )

    with pikepdf.Pdf.open(tmp_path) as pdf:
        page_count = len(pdf.pages)
    final_path = store_cached_pdf_from_path(
        cache_dir,
        key,
        tmp_path,
        page_count=page_count,
    )
    return AbstractPdfChunk(
        poster_id=-1,
        cache_key=key,
        cached_path=final_path,
        page_count=page_count,
        cache_hit=False,
        pandoc_stderr=None,
    )


def _strip_pdf_metadata(pdf_path: pathlib.Path) -> None:
    """Overwrite /CreationDate + /ModDate to a fixed epoch (R6)."""
    import pikepdf

    fixed = "D:19700101000000Z"
    with pikepdf.Pdf.open(pdf_path, allow_overwriting_input=True) as pdf:
        with pdf.open_metadata() as meta:
            # pikepdf's metadata helper handles XMP — clear the
            # producer/creator stamps too so two pandoc versions
            # produce the same body.
            for k in ("xmp:CreateDate", "xmp:ModifyDate", "xmp:MetadataDate"):
                if k in meta:
                    del meta[k]
        info = pdf.trailer.get("/Info")
        if info is not None:
            info["/CreationDate"] = fixed
            info["/ModDate"] = fixed
        pdf.save(pdf_path)


