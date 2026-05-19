"""In-memory model for the Book of Abstracts.

All dataclasses are frozen + slotted; the renderer treats them as
immutable. Body sections and references carry **markdown** (not HTML)
— per `research.md § R2`, HTML → markdown conversion happens once at
corpus load.
"""

from __future__ import annotations

import pathlib
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class AuthorAffiliation:
    institution: str
    city: str
    state: str | None
    country: str


@dataclass(frozen=True, slots=True)
class Author:
    submission_id: int
    author_order: int
    first_name: str
    middle_initial: str | None
    last_name: str
    affiliations: tuple[AuthorAffiliation, ...]
    # Pre-computed at construction (corpus.py):
    sort_key_last_first: tuple[str, str]
    display_name: str
    latex_index_key: str


@dataclass(frozen=True, slots=True)
class FigureBlock:
    """A single figure entry.

    `error` is non-None when the asset is missing or unreadable; the
    renderer emits a "figure unavailable: <error>" block instead of
    the image. `pixel_width`/`pixel_height` may be None alongside a
    non-None `error`.
    """

    question_name: str
    local_path: pathlib.Path
    content_type: str
    pixel_width: int | None
    pixel_height: int | None
    error: str | None


@dataclass(frozen=True, slots=True)
class BodySection:
    """One academic section of an abstract.

    `markdown` is pandoc-flavored markdown — converted from the
    corpus's HTML value at load time (R2).
    """

    name: str
    markdown: str


@dataclass(frozen=True, slots=True)
class ReferencesBlock:
    """The author-supplied References/Citations block as markdown."""

    markdown: str


@dataclass(frozen=True, slots=True)
class StandbySlot:
    """One stand-by window as displayed in the book.

    `label` is the original CSV cell verbatim (e.g.
    `Monday, June 15 | 13:45-14:45`) — that's what gets rendered to
    the reader. `start_utc_iso` and `end_utc_iso` are present so
    machine consumers (UI facets) get a sortable key without
    re-parsing.
    """

    label: str
    start_utc_iso: str
    end_utc_iso: str


@dataclass(frozen=True, slots=True)
class StandbyTimes:
    first: StandbySlot | None
    second: StandbySlot | None


@dataclass(frozen=True, slots=True)
class BookEntry:
    submission_id: int
    poster_id: int
    title: str
    accepted_for: str
    authors: tuple[Author, ...]
    body_sections: tuple[BodySection, ...]
    figures: tuple[FigureBlock, ...]
    references: ReferencesBlock | None
    standby: StandbyTimes | None = None


@dataclass(frozen=True, slots=True)
class AuthorIndexEntry:
    display_name: str
    latex_index_key: str
    sort_key: tuple[str, str]
    # Sorted ascending; the same poster_id never appears twice for a
    # single author (an author only counts once per abstract).
    poster_ids: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class Book:
    sort_order: str
    format: str
    style: str
    entries: tuple[BookEntry, ...]
    author_index: tuple[AuthorIndexEntry, ...]
    corpus_state_key: str
