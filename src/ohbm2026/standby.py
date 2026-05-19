"""Shared parser for the authoritative OHBM 2026 poster standby times.

Source-of-truth: `data/primary/032626 OHBM 2026 Poster Listing_FINAL.xlsx
- Poster Listing.csv`. Replaces the earlier proposal-listing source
(`archive/proposals/.../proposal_listing.csv`) — the new file is the
final program-committee schedule and is keyed by **poster_id**, not
submission_id.

The CSV has a multi-line title row, then a column-header row, then
data. Columns:

    A  NEW POSTER NUMBER ...
    B  First Stand-by Time     "Monday, June 15 | 13:45-14:45"
    C  Second Stand-by Time    "Tuesday, June 16 | 12:30-13:30"
    D  Abstract Title
    E  Primary Category
    F  Last Name of First Author

OHBM 2026 is in Bordeaux, France (CEST = UTC+2, no DST transitions
between June 15 and 18). Each standby window is exactly 1 hour, so we
store the start datetime in UTC; the end is implicit (start + 1h).

The parser returns `dict[int, StandbyTimes]` keyed by poster_id (int,
zero-leading stripped). Callers translate to other identifiers as
needed.
"""

from __future__ import annotations

import csv
import datetime as _dt
import pathlib
import re
from dataclasses import dataclass
from typing import Mapping


_CEST = _dt.timezone(_dt.timedelta(hours=2))
_UTC = _dt.timezone.utc

_MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5,
    "june": 6, "july": 7, "august": 8, "september": 9, "october": 10,
    "november": 11, "december": 12,
}

_PATTERN = re.compile(
    r"\s*(?P<weekday>\w+),\s*(?P<month>\w+)\s+(?P<day>\d+)\s*\|\s*"
    r"(?P<sh>\d{1,2}):(?P<sm>\d{2})\s*-\s*(?P<eh>\d{1,2}):(?P<em>\d{2})",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class StandbyWindow:
    """One stand-by window as a UTC start instant + duration (always
    1 hour for OHBM 2026). The original local-time label is kept for
    display fidelity in the book + UI."""

    start_utc: _dt.datetime
    end_utc: _dt.datetime
    label: str  # "Monday, June 15 | 13:45-14:45" — display verbatim


@dataclass(frozen=True, slots=True)
class StandbyTimes:
    first: StandbyWindow | None
    second: StandbyWindow | None


def parse_window(local: str) -> StandbyWindow | None:
    """Parse one CSV cell like `Monday, June 15 | 13:45-14:45`.

    Returns None for empty/malformed input — callers decide how to
    surface that (logged warning, or fall back to None display).
    """
    if not local:
        return None
    m = _PATTERN.match(local.strip())
    if not m:
        return None
    month = _MONTHS.get(m["month"].lower())
    if month is None:
        return None
    try:
        start = _dt.datetime(
            2026, month, int(m["day"]), int(m["sh"]), int(m["sm"]), tzinfo=_CEST
        ).astimezone(_UTC)
        end = _dt.datetime(
            2026, month, int(m["day"]), int(m["eh"]), int(m["em"]), tzinfo=_CEST
        ).astimezone(_UTC)
    except ValueError:
        return None
    return StandbyWindow(start_utc=start, end_utc=end, label=local.strip())


def load_standby_csv(path: pathlib.Path) -> dict[int, StandbyTimes]:
    """Parse the authoritative CSV → `{poster_id: StandbyTimes}`.

    poster_id keys are stripped of leading zeros and stored as int.
    Rows with malformed times are silently dropped; callers can detect
    the gap by intersecting against the corpus's accepted-poster set.
    """
    out: dict[int, StandbyTimes] = {}
    with path.open(encoding="utf-8") as f:
        reader = csv.reader(f)
        rows = list(reader)
    # Find the data-table header row — it's the one starting with
    # "NEW POSTER NUMBER" (the column-A label in the new file).
    header_idx = None
    for i, row in enumerate(rows):
        if row and row[0].lstrip().upper().startswith("NEW POSTER NUMBER"):
            header_idx = i
            break
    if header_idx is None:
        raise ValueError(
            f"could not locate the 'NEW POSTER NUMBER' header row in {path}"
        )
    for row in rows[header_idx + 1 :]:
        if not row or not row[0].strip():
            continue
        pid_raw = row[0].strip()
        try:
            pid = int(pid_raw)
        except ValueError:
            continue
        first_label = row[1].strip() if len(row) > 1 else ""
        second_label = row[2].strip() if len(row) > 2 else ""
        out[pid] = StandbyTimes(
            first=parse_window(first_label),
            second=parse_window(second_label),
        )
    return out


def key_by_submission_id(
    standby_by_poster: Mapping[int, StandbyTimes],
    poster_to_submission: Mapping[int, int],
) -> dict[int, StandbyTimes]:
    """Translate a poster_id-keyed map → submission_id-keyed.

    Caller supplies the `poster_id → submission_id` map (derived from
    the accepted corpus). Poster IDs absent from the corpus map are
    silently dropped — those are CSV rows for slots that didn't end up
    with an accepted submission.
    """
    out: dict[int, StandbyTimes] = {}
    for pid, times in standby_by_poster.items():
        sid = poster_to_submission.get(pid)
        if sid is None:
            continue
        out[sid] = times
    return out
