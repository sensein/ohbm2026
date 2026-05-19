"""Stage-1 corpus → in-memory Book.

Filters withdrawn / null-poster-id / non-Poster|Oral entries; joins
authors by submission_id; converts every body-section HTML value to
markdown via `html_to_md.html_to_pandoc_md` at the corpus boundary
(R2 — the in-memory model carries markdown). Returns a `Book` ready
for the sort + render pipeline.
"""

from __future__ import annotations

import hashlib
import json
import pathlib
from typing import Iterable, Mapping, Sequence

from ohbm2026.book.figure_check import probe_figure
from ohbm2026.book.html_to_md import html_to_pandoc_md
from ohbm2026.book.model import (
    Author,
    AuthorAffiliation,
    BodySection,
    Book,
    BookEntry,
    FigureBlock,
    ReferencesBlock,
    StandbySlot,
    StandbyTimes,
)
from ohbm2026.book.sections import BODY_SECTION_NAMES
from ohbm2026.exceptions import BookBuildError
from ohbm2026 import standby as _standby

_ACCEPTED_FOR = {"Poster", "Oral"}


def _load_json(path: pathlib.Path) -> dict | list:
    if not path.exists():
        raise BookBuildError(
            f"required input not found at {path}; "
            "run `ohbmcli fetch-abstracts` first"
        )
    return json.loads(path.read_text(encoding="utf-8"))


def _build_authors_index(
    authors_doc: Mapping,
) -> dict[int, list[Author]]:
    """Group authors by `submission_id`, sorted by `author_order`."""
    by_sub: dict[int, list[dict]] = {}
    for raw in authors_doc.get("authors", []):
        sub = raw.get("submission_id")
        if sub is None:
            continue
        by_sub.setdefault(int(sub), []).append(raw)

    result: dict[int, list[Author]] = {}
    for sub, raws in by_sub.items():
        ordered = sorted(raws, key=lambda r: r.get("author_order", 0))
        result[sub] = [_make_author(r) for r in ordered]
    return result


def _make_author(raw: Mapping) -> Author:
    first = (raw.get("first_name") or "").strip()
    middle = raw.get("middle_initial")
    last = (raw.get("last_name") or "").strip()
    affs: list[AuthorAffiliation] = []
    for a in sorted(
        raw.get("affiliations") or [], key=lambda x: x.get("affiliation_order", 0)
    ):
        affs.append(
            AuthorAffiliation(
                institution=(a.get("institution") or "").strip(),
                city=(a.get("city") or "").strip(),
                state=(a.get("state") or None),
                country=(a.get("country") or "").strip(),
            )
        )

    middle_disp = f" {middle.strip()}." if middle and middle.strip() else ""
    display_name = f"{first}{middle_disp} {last}".strip()
    # LaTeX `\index{Last, First M.}` — backslash-escape LaTeX
    # specials so makeindex doesn't choke.
    given = f"{first}{middle_disp}".strip()
    latex_key = f"{last}, {given}" if given else last
    latex_key = _latex_escape(latex_key)

    return Author(
        submission_id=int(raw["submission_id"]),
        author_order=int(raw.get("author_order", 0)),
        first_name=first,
        middle_initial=middle,
        last_name=last,
        affiliations=tuple(affs),
        sort_key_last_first=(last.casefold(), first.casefold()),
        display_name=display_name,
        latex_index_key=latex_key,
    )


_LATEX_SPECIALS = str.maketrans(
    {
        "#": r"\#",
        "$": r"\$",
        "%": r"\%",
        "&": r"\&",
        "_": r"\_",
        "{": r"\{",
        "}": r"\}",
    }
)


def _latex_escape(s: str) -> str:
    return s.translate(_LATEX_SPECIALS)


def _figure_type(question_name: str) -> str:
    """Normalise a `figure_urls[].question_name` into the filename
    type token. "Methods Figure" → "methods"; "Results Figure" →
    "results". Future names follow the same rule: strip a trailing
    " Figure", lowercase, replace non-word chars with dashes.
    """
    stem = question_name.strip()
    if stem.lower().endswith(" figure"):
        stem = stem[:-7].strip()
    stem = stem.casefold()
    # Replace any run of non-alphanumeric with a single dash.
    import re

    stem = re.sub(r"[^a-z0-9]+", "-", stem).strip("-")
    return stem or "figure"


def _ext_from_content_type(content_type: str | None, fallback_path: pathlib.Path) -> str:
    if content_type:
        if "png" in content_type:
            return "png"
        if "jpeg" in content_type or "jpg" in content_type:
            return "jpg"
        if "gif" in content_type:
            return "gif"
        if "webp" in content_type:
            return "webp"
        if "tiff" in content_type:
            return "tif"
    ext = fallback_path.suffix.lstrip(".").lower()
    return ext or "png"


def _build_figures(
    abstract: Mapping, assets_root: pathlib.Path | None
) -> tuple[FigureBlock, ...]:
    """Match `figure_urls[]` to `local_assets[]` by `question_name`.
    Probe each asset; missing/unreadable → FigureBlock with error.
    """
    local_by_q: dict[str, dict] = {}
    for la in abstract.get("local_assets", []) or []:
        qn = la.get("source_question_name")
        if qn:
            local_by_q[qn] = la

    figs: list[FigureBlock] = []
    for fu in abstract.get("figure_urls", []) or []:
        qn = fu.get("question_name", "")
        la = local_by_q.get(qn)
        if la is None or not la.get("downloaded"):
            figs.append(
                FigureBlock(
                    question_name=qn,
                    local_path=pathlib.Path(""),
                    content_type="",
                    pixel_width=None,
                    pixel_height=None,
                    error="asset missing",
                )
            )
            continue
        local_path_str = la.get("local_path") or ""
        local_path = pathlib.Path(local_path_str)
        # If the caller passed an assets_root override (test fixtures
        # or relocated installs), prefer a file with the same basename
        # under that root.
        if assets_root is not None:
            candidate = assets_root / local_path.name
            if candidate.exists():
                local_path = candidate
        width, height, err = probe_figure(local_path)
        figs.append(
            FigureBlock(
                question_name=qn,
                local_path=local_path,
                content_type=la.get("content_type", ""),
                pixel_width=width,
                pixel_height=height,
                error=err,
            )
        )
    return tuple(figs)


def _build_body_sections(
    abstract: Mapping,
    extra_section_names: Sequence[str],
) -> tuple[BodySection, ...]:
    by_q: dict[str, str] = {}
    for r in abstract.get("responses", []) or []:
        qn = r.get("question_name")
        val = r.get("value") or ""
        if qn:
            by_q[qn] = val
    wanted = list(BODY_SECTION_NAMES) + [
        n for n in extra_section_names if n not in BODY_SECTION_NAMES
    ]
    out: list[BodySection] = []
    for name in wanted:
        if name == "References/Citations":
            continue  # rendered separately via ReferencesBlock
        if name not in by_q:
            continue
        md = html_to_pandoc_md(by_q[name]).strip()
        if not md:
            continue
        out.append(BodySection(name=name, markdown=md))
    return tuple(out)


def _build_references(abstract: Mapping) -> ReferencesBlock | None:
    for r in abstract.get("responses", []) or []:
        if r.get("question_name") == "References/Citations":
            md = html_to_pandoc_md(r.get("value") or "").strip()
            if md:
                return ReferencesBlock(markdown=md)
    return None


def _derive_state_key(*paths: pathlib.Path) -> str:
    """12-hex-char digest of the inputs' mtimes (best-effort
    short-form identifier for the build).
    """
    h = hashlib.sha256()
    for p in paths:
        try:
            h.update(p.name.encode())
            h.update(str(int(p.stat().st_mtime_ns)).encode())
        except FileNotFoundError:
            h.update(b"missing")
    return h.hexdigest()[:12]


def _standby_for(times: _standby.StandbyTimes | None) -> StandbyTimes | None:
    """Translate parser dataclass → book model dataclass."""
    if times is None:
        return None

    def _slot(w: _standby.StandbyWindow | None) -> StandbySlot | None:
        if w is None:
            return None
        return StandbySlot(
            label=w.label,
            start_utc_iso=w.start_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
            end_utc_iso=w.end_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
        )

    return StandbyTimes(first=_slot(times.first), second=_slot(times.second))


def load_book(
    *,
    corpus_path: pathlib.Path,
    authors_path: pathlib.Path,
    withdrawn_path: pathlib.Path,
    assets_root: pathlib.Path | None = None,
    standby_path: pathlib.Path | None = None,
    sort_order: str = "poster_id",
    format: str = "md",
    style: str = "plain",
    include_sections: Iterable[str] = (),
) -> Book:
    """Assemble the in-memory `Book` from Stage-1 inputs.

    Raises `BookBuildError` on missing inputs or empty filtered set.
    The caller selects sort order + format; this function does NOT
    apply the sort (that's `sort.py`) but stores the choice for
    downstream renderers.
    """
    corpus_doc = _load_json(corpus_path)
    authors_doc = _load_json(authors_path)
    withdrawn_doc = _load_json(withdrawn_path)

    if not isinstance(corpus_doc, dict) or "abstracts" not in corpus_doc:
        raise BookBuildError(
            f"corpus at {corpus_path} does not contain an `abstracts` array"
        )
    if not isinstance(authors_doc, dict) or not authors_doc.get("authors"):
        raise BookBuildError(
            f"authors at {authors_path} is empty or malformed"
        )

    withdrawn_ids: set[int] = set()
    for w in (withdrawn_doc or {}).get("abstracts", []) or []:
        if w.get("id") is not None:
            withdrawn_ids.add(int(w["id"]))

    authors_by_sub = _build_authors_index(authors_doc)

    # Load standby times (poster_id-keyed) when a path is provided.
    standby_by_pid: dict[int, _standby.StandbyTimes] = {}
    if standby_path is not None:
        if not standby_path.exists():
            raise BookBuildError(
                f"standby CSV not found at {standby_path}"
            )
        standby_by_pid = _standby.load_standby_csv(standby_path)

    entries: list[BookEntry] = []
    # Dedupe poster_id collisions — Oxford preserves all submission ids
    # (unique), but the program-committee `poster_id` (Oxford
    # `program_code`) can collide when an author resubmits the same
    # abstract. Match the UI builder's policy (`ui_data.abstracts.
    # iter_abstracts`): keep first-encountered record, drop later ones
    # with the same poster_id. As of 2026-05-18 the known case is
    # poster_id 2335 (submissions 1246466 + 1248744; identical title +
    # lead author). The authoritative standby CSV is also keyed by
    # poster_id and has a single row per number — so first-encountered
    # is the right policy on both sides.
    seen_poster_ids: set[int] = set()
    deduped_oxford_ids: list[int] = []
    for raw in corpus_doc.get("abstracts", []) or []:
        sub_id = raw.get("id")
        poster_str = raw.get("poster_id")
        accepted_for = raw.get("accepted_for") or ""
        if sub_id is None or poster_str is None:
            continue
        if int(sub_id) in withdrawn_ids:
            continue
        if accepted_for not in _ACCEPTED_FOR:
            continue
        try:
            poster_id = int(poster_str)
        except (TypeError, ValueError):
            continue
        if poster_id in seen_poster_ids:
            deduped_oxford_ids.append(int(sub_id))
            continue
        seen_poster_ids.add(poster_id)

        authors = tuple(authors_by_sub.get(int(sub_id), []))
        body_sections = _build_body_sections(raw, list(include_sections))
        figures = _build_figures(raw, assets_root)
        references = _build_references(raw)
        standby = _standby_for(standby_by_pid.get(poster_id))

        title = (raw.get("title") or "").strip()
        entries.append(
            BookEntry(
                submission_id=int(sub_id),
                poster_id=poster_id,
                title=title,
                accepted_for=accepted_for,
                authors=authors,
                body_sections=body_sections,
                figures=figures,
                references=references,
                standby=standby,
            )
        )

    if not entries:
        raise BookBuildError(
            "zero entries after filter (every row is withdrawn / "
            "null-poster-id / non-Poster|Oral)"
        )

    if deduped_oxford_ids:
        # CA-006 / Principle VI — visible logging, not a silent skip.
        # Same wording shape as the UI builder so audit-grep finds both.
        import sys as _sys
        print(
            f"book.corpus: dropped {len(deduped_oxford_ids)} duplicate-poster_id "
            f"record(s) (Oxford submission ids: {deduped_oxford_ids}). "
            f"First-encountered record per poster_id wins; check upstream "
            f"Oxford `program_code` for stale assignments.",
            file=_sys.stderr,
        )

    state_key = _derive_state_key(corpus_path, authors_path, withdrawn_path)

    # Author index built in a separate module to keep concerns sharp;
    # the corpus loader emits an empty placeholder that sort + the
    # index builder fill in downstream.
    return Book(
        sort_order=sort_order,
        format=format,
        style=style,
        entries=tuple(entries),
        author_index=(),  # populated by author_index.build_author_index
        corpus_state_key=state_key,
    )
