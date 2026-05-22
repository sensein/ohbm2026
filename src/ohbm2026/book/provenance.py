"""Provenance writer for the Book of Abstracts.

Schema pinned at `version: 1`; field list documented in
`data-model.md § Layer 3`. CA-008 / FR-010 — every produced book
ships with this file co-located so the audit trail is portable.

`assert_project_relative` rejects absolute / `~/` paths in any
path-shaped value — those would make the bundle unportable.
"""

from __future__ import annotations

import datetime as _dt
import json
import pathlib
import subprocess

from ohbm2026.book.figure_check import (
    PUBLICATION_DPI_THRESHOLD,
    effective_dpi,
)
from ohbm2026.book.model import Book
from ohbm2026.exceptions import ProvenanceError


_PROVENANCE_VERSION = 1


def _git_revision() -> tuple[str, str]:
    """Best-effort short + full SHA. Returns ("unknown", "unknown")
    when not in a git checkout (e.g. installed-from-wheel).
    """
    try:
        full = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], stderr=subprocess.DEVNULL
        ).decode().strip()
        short = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], stderr=subprocess.DEVNULL
        ).decode().strip()
        return short, full
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "unknown", "unknown"


def _assert_project_relative(value: str, key: str) -> None:
    if not value:
        return
    if value.startswith("/") or value.startswith("~"):
        raise ProvenanceError(
            f"provenance field {key!r} contains an absolute or user-home path: {value!r}"
        )


def _compute_below_threshold(book: Book, display_width_inches: float) -> list[dict]:
    out: list[dict] = []
    for entry in book.entries:
        for idx, fig in enumerate(entry.figures):
            if fig.error or fig.pixel_width is None:
                continue
            dpi = effective_dpi(fig.pixel_width, display_width_inches)
            if dpi < PUBLICATION_DPI_THRESHOLD:
                out.append(
                    {
                        "poster_id": entry.poster_id,
                        "figure_index": idx,
                        "question_name": fig.question_name,
                        "effective_dpi": round(dpi, 1),
                    }
                )
    return out


def _no_ai_audit(book_md_path: pathlib.Path) -> dict:
    """Audit `book.md` for Stage-2 string leakage (SC-006)."""
    if not book_md_path.exists():
        return {
            "checked": False,
            "matches_found": 0,
            "reason": "book.md not present",
        }
    text = book_md_path.read_text(encoding="utf-8")
    eco_codes = _load_eco_codes()
    leaked_eco = [c for c in eco_codes if c in text]
    tool_names = ["verify_source_quote", "lookup_eco_code", "dedupe_check"]
    leaked_tools = [t for t in tool_names if t in text]
    return {
        "checked": True,
        "matches_found": len(leaked_eco) + len(leaked_tools),
        "checked_against": ["eco_top_codes", "stage2_tool_names"],
        "leaked_eco": leaked_eco,
        "leaked_tool_names": leaked_tools,
    }


def _load_eco_codes() -> list[str]:
    """Best-effort load of `src/ohbm2026/data/eco_top_codes.json`.
    Returns an empty list when the file is absent (no false positives).
    """
    candidates = [
        pathlib.Path(__file__).parent.parent / "data" / "eco_top_codes.json",
    ]
    for path in candidates:
        if not path.exists():
            continue
        try:
            payload = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        codes: list[str] = []
        if isinstance(payload, dict):
            for entry in payload.get("codes", []):
                if isinstance(entry, dict):
                    c = entry.get("code") or entry.get("eco_code")
                    if c:
                        codes.append(c)
                elif isinstance(entry, str):
                    codes.append(entry)
        elif isinstance(payload, list):
            for entry in payload:
                if isinstance(entry, dict):
                    c = entry.get("code") or entry.get("eco_code")
                    if c:
                        codes.append(c)
                elif isinstance(entry, str):
                    codes.append(entry)
        return codes
    return []


def write_provenance(
    book: Book,
    output_dir: pathlib.Path,
    *,
    corpus_path: pathlib.Path,
    authors_path: pathlib.Path,
    withdrawn_path: pathlib.Path,
    command_line: str,
    pandoc_version: str | None = None,
    xelatex_version: str | None = None,
    display_width_inches: float = 6.5,
    assembled=None,  # type: ignore[no-untyped-def]
) -> pathlib.Path:
    """Write `output_dir/provenance.json` and return its path.

    ``assembled`` is the :class:`AssembledBook` returned by Stage 11.1's
    per-abstract PDF orchestrator. When provided, the emitted
    provenance gains the Stage-11.1 fields: cache_hit_count,
    cache_miss_count, failed_abstracts[], assembly_time_seconds,
    index_pages, included_poster_ids, pdf_pipeline_version,
    pdf_engine_version. When None (md-only / legacy single-pass build)
    those fields are omitted so the provenance contract remains a
    superset of Stage 11's.
    """

    output_dir.mkdir(parents=True, exist_ok=True)

    short, full = _git_revision()

    # Path fields stored project-relative so the bundle is portable.
    def _rel(p: pathlib.Path) -> str:
        try:
            return str(p.resolve().relative_to(pathlib.Path.cwd()))
        except ValueError:
            # Fall back to as-given (already relative when callers
            # pass `data/primary/...`).
            return str(p)

    corpus_rel = _rel(corpus_path)
    authors_rel = _rel(authors_path)
    withdrawn_rel = _rel(withdrawn_path)
    for key, val in (
        ("corpus_path", corpus_rel),
        ("authors_path", authors_rel),
        ("withdrawn_path", withdrawn_rel),
    ):
        _assert_project_relative(val, key)

    figure_count = sum(len(e.figures) for e in book.entries)
    below = _compute_below_threshold(book, display_width_inches)
    no_ai = _no_ai_audit(output_dir / "book.md")

    payload = {
        "version": _PROVENANCE_VERSION,
        "corpus_state_key": book.corpus_state_key,
        "corpus_path": corpus_rel,
        "authors_path": authors_rel,
        "withdrawn_path": withdrawn_rel,
        "sort_order": book.sort_order,
        "format": book.format,
        "style": book.style,
        "code_revision_short": short,
        "code_revision_full": full,
        "command_line": command_line,
        "built_at": _dt.datetime.now(_dt.timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        ),
        "abstract_count": len(book.entries),
        "figure_count": figure_count,
        "figures_below_resolution_threshold": below,
        "pandoc_version": pandoc_version,
        # Legacy field name kept for one deploy cycle so downstream
        # consumers reading old provenance files don't break; Stage
        # 11.1 also writes the new `pdf_engine_version` below when
        # the assembled-book path produced this run.
        "xelatex_version": xelatex_version,
        "no_ai_audit": no_ai,
    }
    if assembled is not None:
        payload["pdf_pipeline_version"] = "stage-12"
        payload["pdf_engine_version"] = xelatex_version
        payload["cache_hit_count"] = assembled.cache_hit_count
        payload["cache_miss_count"] = assembled.cache_miss_count
        payload["assembly_time_seconds"] = assembled.assembly_time_seconds
        payload["index_pages"] = assembled.index_pages
        payload["front_matter_pages"] = assembled.front_matter_pages
        # Stage 12 US2 / FR-006 — figure-normalisation audit fields.
        # Read the module-level fallback registry from render_markdown
        # then reset it so the next build starts clean.
        from ohbm2026.book.render_markdown import (
            get_normalise_fallbacks,
            reset_normalise_fallbacks,
        )

        fallbacks = get_normalise_fallbacks()
        payload["figures_normalised_count"] = max(0, figure_count - len(fallbacks))
        payload["figures_normalised_with_fallback"] = fallbacks
        # Stage 12 US3 / FR-010 — TOC page count derives from the
        # front-matter chunk's page count (the new 3-column longtable
        # IS the dominant content of the front matter).
        payload["toc_page_count"] = assembled.front_matter_pages
        reset_normalise_fallbacks()
        # Surviving abstracts (sort order preserved).
        included = [
            offset_pid
            for (offset_pid, _start) in assembled.chunk_offsets
            if offset_pid >= 0  # filter out the front-matter slot (-1)
        ]
        payload["included_poster_ids"] = included
        payload["failed_abstracts"] = [
            {
                "poster_id": f.poster_id,
                "cache_key": f.cache_key,
                "pandoc_exit_code": f.pandoc_exit_code,
                "stderr_tail": f.stderr_tail,
                "failed_at": f.failed_at,
            }
            for f in assembled.failures
        ]
    dest = output_dir / "provenance.json"
    dest.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return dest
