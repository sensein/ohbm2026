"""Stage 11.1 US2 — standby_slots derivation for the parquet emitter.

The legacy v1 parquet stored each abstract's stand-by windows as two
UTC timestamps in a ``poster_standby: {first, second}`` STRUCT
column. The browser then converted those timestamps to Paris-local
display labels via ``Intl.DateTimeFormat`` 6,500+ times per filter
click — a hot-path that crashed the tab pre-PR-27 without memoization.

v2 replaces that with:

- one ``standby_slots`` table (8 rows for OHBM 2026) carrying the
  pre-rendered display labels + UTC start/end;
- two nullable ``INT8`` columns on the ``abstracts`` table
  (``standby_first_index``, ``standby_second_index``) referencing
  rows in ``standby_slots`` by ``slot_index``.

This module is the pure-Python derivation. The parquet emitter calls
``derive_standby_slots(standby_by_poster)`` once at build time,
``build_poster_to_index_map(...)`` for the per-record lookup, and
writes the two artefacts. UI-side dispatch lives in
``site/src/lib/standby.ts``.

`StandbySchemaError` lives here (rather than in the central
``exceptions.py`` module) to preserve the import-safety pattern used
by ``Stage6BuildError`` in ``state_key.py`` — see that module's
docstring for the circular-import rationale.
"""

from __future__ import annotations

import datetime as _dt
from typing import Mapping


VENUE_TZ = _dt.timezone(_dt.timedelta(hours=2))  # CEST, OHBM 2026 Bordeaux
CONFERENCE_DAY_BASE = _dt.date(2026, 6, 15)  # Day 1


_WEEKDAY_SHORT = {
    0: "Mon",
    1: "Tue",
    2: "Wed",
    3: "Thu",
    4: "Fri",
    5: "Sat",
    6: "Sun",
}
_MONTH_SHORT = {
    1: "Jan", 2: "Feb", 3: "Mar", 4: "Apr", 5: "May", 6: "Jun",
    7: "Jul", 8: "Aug", 9: "Sep", 10: "Oct", 11: "Nov", 12: "Dec",
}


class StandbySchemaError(RuntimeError):
    """Raised when the standby-slots lookup detects a dangling index.

    Subclasses ``RuntimeError`` (not the central ``Stage6BuildError``)
    for the same reason — see module docstring + ``state_key.py``.
    """


def _to_paris_local(utc_dt: _dt.datetime) -> _dt.datetime:
    """Convert a UTC datetime to Paris venue time.

    OHBM 2026 runs entirely inside CEST (UTC+2; no DST transitions
    between June 15 and 18), so a fixed offset is correct + portable.
    """

    if utc_dt.tzinfo is None:
        utc_dt = utc_dt.replace(tzinfo=_dt.timezone.utc)
    return utc_dt.astimezone(VENUE_TZ)


def _display_label(start_utc: _dt.datetime, end_utc: _dt.datetime) -> str:
    """Render ``"Day N (Wkd Mon DD) · HH:MM-HH:MM"`` for one window.

    Matches the UI's existing ``standbyBlockKey`` output verbatim so
    facets that already filter on these strings see the SAME options
    after the v2 migration — no UI-side fallout from the rename.
    """

    paris_start = _to_paris_local(start_utc)
    paris_end = _to_paris_local(end_utc)
    weekday = _WEEKDAY_SHORT[paris_start.weekday()]
    month = _MONTH_SHORT[paris_start.month]
    day_num = paris_start.day
    s = paris_start.strftime("%H:%M")
    e = paris_end.strftime("%H:%M")
    day_index = max(1, (paris_start.date() - CONFERENCE_DAY_BASE).days + 1)
    return f"Day {day_index} ({weekday} {month} {day_num:02d}) · {s}–{e}"


def derive_standby_slots(
    standby_by_poster: Mapping[int, Mapping[str, _dt.datetime | None]],
) -> list[dict]:
    """Return the global ``standby_slots`` table for the corpus.

    Rows: ``{slot_index, start_utc, end_utc, display_label}``.

    ``slot_index`` is assigned by sorting unique start_utc values
    ascending — so the index is *also* the chronological position.
    Each window is exactly 1 hour (OHBM 2026's program is uniform);
    ``end_utc = start_utc + 1h``.
    """

    unique_starts: set[_dt.datetime] = set()
    for times in standby_by_poster.values():
        for key in ("first", "second"):
            v = times.get(key)
            if v is None:
                continue
            unique_starts.add(_ensure_utc(v))

    sorted_starts = sorted(unique_starts)
    out: list[dict] = []
    for idx, start in enumerate(sorted_starts):
        end = start + _dt.timedelta(hours=1)
        out.append(
            {
                "slot_index": idx,
                "start_utc": start,
                "end_utc": end,
                "display_label": _display_label(start, end),
            }
        )
    return out


def build_poster_to_index_map(
    standby_by_poster: Mapping[int, Mapping[str, _dt.datetime | None]],
    slots: list[dict],
) -> dict[int, tuple[int | None, int | None]]:
    """Return ``{poster_id: (first_idx, second_idx)}`` for the corpus.

    Each value is a 2-tuple of INT8-fitting slot_indexes (or None when
    the abstract has no value for that slot). Orphan posters — those
    absent from ``standby_by_poster`` — get no entry; downstream
    callers treat absence as ``(None, None)``.
    """

    start_to_index = {s["start_utc"]: int(s["slot_index"]) for s in slots}
    out: dict[int, tuple[int | None, int | None]] = {}
    for pid, times in standby_by_poster.items():
        first = times.get("first")
        second = times.get("second")
        first_idx = (
            start_to_index.get(_ensure_utc(first)) if first is not None else None
        )
        second_idx = (
            start_to_index.get(_ensure_utc(second)) if second is not None else None
        )
        out[pid] = (first_idx, second_idx)
    return out


def _ensure_utc(value: _dt.datetime) -> _dt.datetime:
    """Coerce a possibly-naive datetime to UTC tz-aware.

    Inputs from the legacy proposal-listing parser are always
    tz-aware (CEST → UTC), but the FINAL-CSV path can hand back naive
    values via the older standby module — keep the coercion close to
    the boundary so the rest of this module never sees naive times.
    """

    if value.tzinfo is None:
        return value.replace(tzinfo=_dt.timezone.utc)
    return value.astimezone(_dt.timezone.utc)
