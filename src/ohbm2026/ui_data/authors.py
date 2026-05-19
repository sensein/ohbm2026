"""Build ``data/authors.json`` for Stage 6 (T014).

Per research.md R6 the de-dup key is ``(lower(name), lower(primary_affiliation))``.
Authors with the same name but different affiliations are distinct records.
"""

from __future__ import annotations

import json
import unicodedata
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any

from ohbm2026.ui_data.state_key import Stage6BuildError

SCHEMA_VERSION = "authors.v1"


def _normalize_for_key(value: str | None) -> str:
    """NFC-normalize, strip + lowercase. Diacritics are preserved (R6)."""

    if not value:
        return ""
    return unicodedata.normalize("NFC", str(value)).strip().lower()


def _full_name(author: Mapping[str, Any]) -> str:
    parts: list[str] = []
    for key in ("first_name", "middle_initial", "last_name"):
        value = author.get(key)
        if value:
            parts.append(str(value).strip())
    return " ".join(p for p in parts if p)


def _primary_affiliation(author: Mapping[str, Any]) -> str:
    affs = author.get("affiliations") or []
    for entry in affs:
        if not isinstance(entry, dict):
            continue
        # Lowest affiliation_order is the primary; default to the first listed.
        if entry.get("affiliation_order") in (0, "0"):
            return _format_affiliation(entry)
    if affs and isinstance(affs[0], dict):
        return _format_affiliation(affs[0])
    return ""


def _format_affiliation(entry: Mapping[str, Any]) -> str:
    parts = [
        str(entry.get("institution") or "").strip(),
        str(entry.get("city") or "").strip(),
        str(entry.get("state") or "").strip(),
        str(entry.get("country") or "").strip(),
    ]
    return ", ".join(p for p in parts if p)


def _all_affiliations(author: Mapping[str, Any]) -> list[str]:
    affs = author.get("affiliations") or []
    ordered = sorted(
        (entry for entry in affs if isinstance(entry, dict)),
        key=lambda e: int(e.get("affiliation_order") or 0),
    )
    return [_format_affiliation(entry) for entry in ordered if _format_affiliation(entry)]


def _load_authors_payload(authors_path: Path) -> list[dict[str, Any]]:
    with Path(authors_path).open() as fh:
        payload = json.load(fh)
    iterable = payload.get("authors") if isinstance(payload, dict) else payload
    if not isinstance(iterable, list):
        raise Stage6BuildError(
            f"Authors file at {authors_path} has no 'authors' list"
        )
    return [a for a in iterable if isinstance(a, dict)]


def _load_accepted_abstract_ids(corpus_path: Path) -> set[int]:
    """Return ``submission_id``s for accepted abstracts only."""

    with Path(corpus_path).open() as fh:
        payload = json.load(fh)
    iterable = payload.get("abstracts") if isinstance(payload, dict) else payload
    accepted: set[int] = set()
    if not isinstance(iterable, list):
        return accepted
    for a in iterable:
        if not isinstance(a, dict):
            continue
        if a.get("accepted_for") == "Withdrawn":
            continue
        if a.get("id") is None:
            continue
        accepted.add(int(a["id"]))
    return accepted


def build_authors_records(
    *,
    corpus_path: Path,
    authors_path: Path,
    return_remap: bool = False,
) -> list[dict[str, Any]] | tuple[list[dict[str, Any]], dict[int, int]]:
    """Return de-duplicated, accepted-only author records.

    De-dup key is ``(lower(name), lower(primary_affiliation))`` per R6.
    Differing affiliations produce distinct ids. Author records whose only
    listed submissions are withdrawn are dropped.

    When ``return_remap=True`` also returns ``{raw_author_id: synthetic_id}``
    so the abstracts builder can translate raw GraphQL author ids → synthetic
    indices into the authors shard (fixes the invariant-4 join referenced in
    ``builder.py``).
    """

    raw_authors = _load_authors_payload(authors_path)
    accepted_ids = _load_accepted_abstract_ids(corpus_path)

    # First pass: group raw rows by dedup key, accumulating accepted abstract ids
    groups: dict[tuple[str, str], dict[str, Any]] = {}
    for raw in raw_authors:
        submission_id = raw.get("submission_id")
        if submission_id is None or int(submission_id) not in accepted_ids:
            continue
        name = _full_name(raw)
        primary = _primary_affiliation(raw)
        key = (_normalize_for_key(name), _normalize_for_key(primary))
        if not key[0]:
            continue
        record = groups.get(key)
        if record is None:
            record = {
                "name": name,
                "affiliations": _all_affiliations(raw),
                "_abstract_ids": set(),
                "_raw_ids": set(),
            }
            groups[key] = record
        record["_abstract_ids"].add(int(submission_id))
        raw_id = raw.get("id")
        if raw_id is not None:
            record["_raw_ids"].add(int(raw_id))

    # Second pass: assign stable, sorted author_ids (sorted by (name, primary_aff))
    deduped = sorted(groups.items(), key=lambda kv: kv[0])
    records: list[dict[str, Any]] = []
    remap: dict[int, int] = {}
    for index, (_key, record) in enumerate(deduped):
        for raw_id in record["_raw_ids"]:
            remap[raw_id] = index
        records.append(
            {
                "author_id": index,
                "name": record["name"],
                "affiliations": record["affiliations"],
                "abstract_ids": sorted(record["_abstract_ids"]),
            }
        )
    if return_remap:
        return records, remap
    return records


def iter_authors(
    *,
    corpus_path: Path,
    authors_path: Path,
) -> Iterator[dict[str, Any]]:
    """Yield per-author rows.

    Stage-10 entry point. The dedup step (R6) inherently materialises the
    full list (we need to see every record to dedup by name+affiliation),
    so this is just a list-then-yield wrapper. The candidate emitters get
    a uniform interface; the memory cost is identical to the existing
    ``build_authors_records`` call.
    """
    records = build_authors_records(
        corpus_path=corpus_path, authors_path=authors_path, return_remap=False
    )
    # build_authors_records returns list when return_remap=False
    yield from records  # type: ignore[misc]


def build_authors(
    *,
    corpus_path: Path,
    authors_path: Path,
    build_info: Mapping[str, str],
    return_remap: bool = False,
) -> dict[str, Any] | tuple[dict[str, Any], dict[int, int]]:
    """Return the authors shard envelope per data-model.md §3.

    When ``return_remap=True`` also returns the raw→synthetic id map.
    """

    result = build_authors_records(
        corpus_path=corpus_path, authors_path=authors_path, return_remap=return_remap
    )
    if return_remap:
        records, remap = result  # type: ignore[misc]
        envelope = {
            "schema_version": SCHEMA_VERSION,
            "build_info": dict(build_info),
            "authors": records,
        }
        return envelope, remap
    return {
        "schema_version": SCHEMA_VERSION,
        "build_info": dict(build_info),
        "authors": result,  # type: ignore[dict-item]
    }
