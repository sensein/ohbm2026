"""Build ``data/abstracts.json`` for Stage 6 (T012).

Strips ``submission_id``, emits ``poster_id`` as the user-facing identifier
(FR-002), assembles topics + methods checklist + per-record facets, and
populates ``author_ids`` referencing the canonical authors shard.
"""

from __future__ import annotations

import html
import json
import re
from collections.abc import Iterable, Iterator, Mapping
from pathlib import Path
from typing import Any

from ohbm2026.analyze.storage import parse_string_list_value
from ohbm2026.titles import cleaned_abstract_title
from ohbm2026.ui_data.questions import (
    PRIMARY_TOPIC_QUESTION,
    QUESTION_MAP,
    SECONDARY_TOPIC_QUESTION,
    build_domain_facets,
    primary_topic_from_questions,
    question_lookup,
    topic_pair_from_questions,
    topic_subcategory,
)
from ohbm2026.ui_data.state_key import Stage6BuildError


SCHEMA_VERSION = "abstracts.v1"

_BLOCK_TAGS = re.compile(r"</?(?:p|div|li|ul|ol|h[1-6]|br|tr|table|tbody|thead|section|article)[^>]*>", re.IGNORECASE)
_TAG = re.compile(r"<[^>]+>")
_WHITESPACE = re.compile(r"[ \t ]+")
_BLANK_LINES = re.compile(r"\n{3,}")


def _html_to_text(blob: str | None) -> str:
    """Convert the rich-text editor HTML stored in `responses[].value` into a
    paragraph-preserving plain-text string the UI can render with `white-space: pre-wrap`.

    Strips all tags, decodes entities, collapses runs of whitespace, and
    inserts a blank line at every block-level tag boundary so paragraphs
    survive. Inline tags (span, strong, em, …) are dropped silently.
    """

    if not blob:
        return ""
    text = str(blob)
    # Insert paragraph boundaries before stripping block tags.
    text = _BLOCK_TAGS.sub("\n\n", text)
    # Strip remaining tags.
    text = _TAG.sub("", text)
    # Decode HTML entities (&nbsp; → space, &amp; → &, etc.).
    text = html.unescape(text)
    # Normalize whitespace + collapse runs of blank lines.
    text = _WHITESPACE.sub(" ", text)
    text = _BLANK_LINES.sub("\n\n", text)
    return text.strip()


_SECTION_QUESTION = {
    "introduction": "Introduction",
    "methods": "Methods",
    "results": "Results",
    "conclusion": "Conclusion",
    "references": "References/Citations",
}


def _topics(questions: Mapping[str, Any]) -> dict[str, str]:
    """Return ``{primary, primary_subcategory, secondary, secondary_subcategory}``
    in a flat record shape suited to the per-shard schema in
    data-model.md §2.
    """

    primary_values = topic_pair_from_questions(questions, PRIMARY_TOPIC_QUESTION)
    secondary_values = topic_pair_from_questions(questions, SECONDARY_TOPIC_QUESTION)
    return {
        "primary": primary_topic_from_questions(questions),
        "primary_subcategory": topic_subcategory(primary_values) if primary_values else "",
        "secondary": secondary_values[0] if secondary_values else "",
        "secondary_subcategory": topic_subcategory(secondary_values) if secondary_values else "",
    }


def _facets(
    raw: Mapping[str, Any],
    questions: Mapping[str, Any],
    enriched: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Per-record facets matching the manifest's `facets[].key` set."""

    enriched_dict: dict[str, Any] = dict(enriched or {})
    keywords = parse_string_list_value(questions.get("Keywords"))
    methods = parse_string_list_value(questions.get(QUESTION_MAP["methods"]))
    study_type = parse_string_list_value(questions.get(QUESTION_MAP["study_type"]))
    population = parse_string_list_value(questions.get(QUESTION_MAP["population"]))
    field_strength = parse_string_list_value(questions.get(QUESTION_MAP["field_strength"]))
    processing_packages = parse_string_list_value(
        questions.get(QUESTION_MAP["processing_packages"])
    )
    domain = build_domain_facets(dict(raw), enriched_dict, {"keywords": keywords, "methods": methods})
    return {
        "keywords": keywords,
        "methods": methods,
        "study_type": study_type,
        "population": population,
        "field_strength": field_strength,
        "processing_packages": processing_packages,
        "species": domain["species"],
        "recording_technology": domain["recording_technology"],
        "brain_regions": domain["brain_regions"],
        "brain_networks": domain["brain_networks"],
    }


def _section(questions: Mapping[str, Any], name: str) -> str:
    """Render the section text from the raw corpus's responses.

    The submission form stores the body of each section under a fixed
    question name (Introduction / Methods / Results / Conclusion /
    References/Citations) as HTML produced by the rich-text editor. We
    strip the HTML to plain text with paragraph boundaries preserved so the
    UI can render it with `white-space: pre-wrap`.
    """

    question = _SECTION_QUESTION.get(name)
    if question is None:
        return ""
    value = questions.get(question)
    if value is None:
        return ""
    return _html_to_text(value)


def _references(record_refs: Iterable[Mapping[str, Any]] | None) -> tuple[list[str], list[str], list[str]]:
    """Return ``(reference_dois, reference_urls, reference_titles)`` as parallel arrays.

    Empty string fills the slot if a piece is missing. References without any
    DOI / URL / title are dropped.
    """

    dois: list[str] = []
    urls: list[str] = []
    titles: list[str] = []
    for ref in record_refs or []:
        doi = str(ref.get("doi") or "")
        url = str(ref.get("url") or "")
        if not url and doi:
            url = f"https://doi.org/{doi}"
        title = str(ref.get("title") or "")
        if not doi and not url and not title:
            continue
        dois.append(doi)
        urls.append(url)
        titles.append(title)
    return dois, urls, titles


def _load_corpus(corpus_path: Path) -> list[dict[str, Any]]:
    with corpus_path.open() as fh:
        payload = json.load(fh)
    if not isinstance(payload, dict):
        raise Stage6BuildError(
            f"Unexpected corpus shape at {corpus_path}: expected dict, got {type(payload).__name__}"
        )
    abstracts = payload.get("abstracts")
    if not isinstance(abstracts, list):
        raise Stage6BuildError(
            f"Corpus at {corpus_path} missing 'abstracts' list"
        )
    return [a for a in abstracts if isinstance(a, dict)]


def _load_references_by_id(references_path: Path | None) -> dict[int, list[dict[str, Any]]]:
    """Read the curated OpenAlex-resolved references shard.

    ``references_path`` defaults (via the builder CLI) to
    ``data/cache/reference_metadata/openalex_resolved.json`` — the Stage 2.1
    canonical store. Each record looks like
    ``{id, references: [{doi, pmid, openalex_id, title_guess, matched, ...}]}``.
    Only matched references with a usable DOI / openalex_id / title are
    surfaced to the UI.
    """

    if references_path is None or not Path(references_path).exists():
        return {}
    with Path(references_path).open() as fh:
        payload = json.load(fh)
    out: dict[int, list[dict[str, Any]]] = {}
    iterable = payload.get("abstracts") if isinstance(payload, dict) else payload
    if not isinstance(iterable, list):
        return out
    for entry in iterable:
        if not isinstance(entry, dict):
            continue
        abstract_id = entry.get("abstract_id") or entry.get("id")
        if abstract_id is None:
            continue
        refs = entry.get("references") or []
        if not isinstance(refs, list):
            continue
        normalized: list[dict[str, Any]] = []
        for ref in refs:
            if not isinstance(ref, dict):
                continue
            doi = ref.get("doi") or ""
            url = ""
            if doi:
                url = f"https://doi.org/{doi}"
            elif ref.get("openalex_id"):
                url = str(ref["openalex_id"])
            title = ref.get("title_guess") or ref.get("title") or ""
            if not doi and not url and not title:
                continue
            normalized.append({"doi": doi, "url": url, "title": title})
        out[int(abstract_id)] = normalized
    return out


def _load_enriched_by_id(enriched_path: Path | None) -> dict[int, dict[str, Any]]:
    """Load enriched-abstract markdown blobs from the Stage 2 SQLite store.

    The schema lives in ``ohbm2026.enrich.storage``; we read by abstract id.
    Returns an empty mapping when the file is absent so the manifest build
    still succeeds in the placeholder/skeleton case.
    """

    if enriched_path is None or not Path(enriched_path).exists():
        return {}
    try:
        from ohbm2026.enrich.storage import iter_enriched
    except ImportError:
        return {}
    out: dict[int, dict[str, Any]] = {}
    for record in iter_enriched(Path(enriched_path)):
        abstract_id = record.get("abstract_id")
        if abstract_id is None:
            continue
        out[int(abstract_id)] = dict(record)
    return out


def _withdrawn_ids(withdrawn_path: Path | None) -> set[int]:
    if withdrawn_path is None or not Path(withdrawn_path).exists():
        return set()
    with Path(withdrawn_path).open() as fh:
        payload = json.load(fh)
    iterable = payload.get("abstracts") if isinstance(payload, dict) else payload
    if not isinstance(iterable, list):
        return set()
    return {int(a["id"]) for a in iterable if isinstance(a, dict) and a.get("id") is not None}


def _load_standby_times(
    path: Path | None,
) -> dict[int, dict[str, "_dt.datetime | None"]]:  # type: ignore[name-defined]
    """Load poster stand-by start times from the proposal-listing CSV.

    Returns `{submission_id: {first: datetime|None, second: datetime|None}}`
    with timezone-aware Python `datetime` objects (UTC). Each emitter
    converts these to its native time representation — for the parquet
    candidate that's a `TIMESTAMP(unit=ms, tz=UTC)` column, which is
    int64 on disk + dict-encoded over the 8 unique conference slots
    (~1 byte per value after compression).

    The CSV is the only source for these times — Oxford GraphQL doesn't
    expose them. Each row's two stand-by times are local Bordeaux
    strings like "Wednesday, June 17 | 12:45-13:45"; OHBM 2026 lands
    inside CEST (UTC+2, no DST transitions between June 15 and 18) and
    every window is exactly 1 hour, so the start time is sufficient —
    the end is implicit (start + 1h).
    """
    if path is None:
        return {}
    import csv
    import datetime as _dt
    import re as _re

    _CEST = _dt.timezone(_dt.timedelta(hours=2))
    _UTC = _dt.timezone.utc
    _MONTHS = {
        "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
        "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
    }
    _PATTERN = _re.compile(
        r"\s*\w+,\s*(?P<month>\w+)\s+(?P<day>\d+)\s*\|\s*(?P<hh>\d{1,2}):(?P<mm>\d{2})\s*-",
        _re.IGNORECASE,
    )

    def _to_utc(local: str) -> "_dt.datetime | None":
        if not local:
            return None
        m = _PATTERN.match(local)
        if not m:
            return None
        month = _MONTHS.get(m["month"].lower())
        if month is None:
            return None
        try:
            local_dt = _dt.datetime(
                2026, month, int(m["day"]), int(m["hh"]), int(m["mm"]), tzinfo=_CEST
            )
        except ValueError:
            return None
        return local_dt.astimezone(_UTC)

    out: dict[int, dict[str, "_dt.datetime | None"]] = {}
    try:
        with Path(path).open() as f:
            lines = f.readlines()
        header_idx = next(
            (i for i, ln in enumerate(lines) if ln.startswith("Abstract ID Number")),
            None,
        )
        if header_idx is None:
            return {}
        reader = csv.DictReader(lines[header_idx:])
        first_col = "First Stand-by Time"
        second_col = "Second Stand-by Time"
        for row in reader:
            sid_raw = (row.get("Abstract ID Number") or "").strip()
            if not sid_raw.isdigit():
                continue
            sid = int(sid_raw)
            out[sid] = {
                "first": _to_utc((row.get(first_col) or "").strip()),
                "second": _to_utc((row.get(second_col) or "").strip()),
            }
    except (OSError, csv.Error):
        return {}
    return out


def build_abstract_to_poster_map(
    *,
    corpus_path: Path,
    withdrawn_path: Path | None,
) -> dict[int, int]:
    """Return ``{oxford_submission_id: poster_id_int}`` for the accepted,
    deduped corpus.

    Stage 10: this is the canonical translation table threaded into every
    sub-builder so each emits poster_id-keyed shapes directly (no
    post-process). The dedup logic mirrors ``iter_abstracts`` —
    first-encountered record per poster_id wins; records without a
    numeric poster_id are excluded.
    """
    corpus = _load_corpus(corpus_path)
    withdrawn = _withdrawn_ids(withdrawn_path)
    out: dict[int, int] = {}
    seen: set[int] = set()
    for raw in corpus:
        if raw.get("accepted_for") == "Withdrawn":
            continue
        abstract_id = raw.get("id")
        if abstract_id is None:
            continue
        if int(abstract_id) in withdrawn:
            continue
        poster_raw = raw.get("poster_id")
        if poster_raw is None:
            continue
        poster_raw_str = str(poster_raw)
        if not poster_raw_str.isdigit():
            raise Stage6BuildError(
                f"non-numeric poster_id {poster_raw_str!r} on submission {abstract_id}; "
                f"Stage-10 export uses int16 poster_id throughout"
            )
        poster_id_int = int(poster_raw_str)
        if poster_id_int in seen:
            continue
        seen.add(poster_id_int)
        out[int(abstract_id)] = poster_id_int
    return out


def iter_abstracts(
    *,
    corpus_path: Path,
    enriched_path: Path | None,
    references_path: Path | None,
    withdrawn_path: Path | None,
    author_id_remap: Mapping[int, int] | None = None,
    standby_times_path: Path | None = None,
) -> Iterator[dict[str, Any]]:
    """Yield per-abstract rows (accepted-only, poster_id-keyed).

    Stage-10 entry point: the format-agnostic row stream every candidate
    emitter under ``ohbm2026.ui_data.formats`` consumes. Rows match the
    ``AbstractRow`` shape in ``types.py``. Identical record contents to
    ``build_abstracts_records()`` — that wrapper is now ``list(iter_abstracts(...))``.

    Streaming benefits: Parquet RecordBatch builders + SQLite INSERT
    sequences both prefer row-at-a-time consumption to a fully-materialised
    list (saves a ~30 MB allocation for the OHBM corpus).
    """

    corpus = _load_corpus(corpus_path)
    enriched_by_id = _load_enriched_by_id(enriched_path)
    refs_by_id = _load_references_by_id(references_path)
    withdrawn = _withdrawn_ids(withdrawn_path)
    standby_by_sid = _load_standby_times(standby_times_path)

    skipped_no_poster_id = 0
    # Dedupe poster_id collisions. Oxford ingest preserves all submission
    # IDs (unique), but the program committee's poster_id assignment
    # (Oxford `program_code`) can collide when an author accidentally
    # submits the same abstract twice. Known case as of 2026-05-18:
    # poster_id 2335 shared by submissions 1246466 + 1248744 (identical
    # title + identical lead author "Knight"; the proposal-listing CSV
    # shows them as adjacent posters 2335/2336, but Oxford's program_code
    # field is stale for 1248744). Treat them as a single poster: keep
    # the first-encountered record (corpus iteration order), drop later
    # ones with the same poster_id. Log so the call is visible.
    seen_poster_ids: set[int] = set()
    deduped_oxford_ids: list[int] = []
    for raw in corpus:
        if raw.get("accepted_for") == "Withdrawn":
            continue
        abstract_id = raw.get("id")
        if abstract_id is None:
            continue
        if int(abstract_id) in withdrawn:
            continue
        # FR-002 requires the poster_id as the user-facing identifier; records
        # without one cannot be linked to or displayed. Drop them (with a log).
        if not raw.get("poster_id"):
            skipped_no_poster_id += 1
            continue
        # Coerce poster_id to int. Stage-10: the poster_id is the sole
        # user-facing identifier across the export and is stored as int16
        # (range 1–3333). Source values from Oxford are zero-padded strings
        # like "0503", "2335"; we strip the padding here and rely on the UI
        # to re-pad for display (`String(id).padStart(4, '0')`). Reject
        # non-numeric poster_ids loudly — they would silently break the
        # exported schema (no historical case of non-numeric in OHBM).
        poster_raw = str(raw.get("poster_id"))
        if not poster_raw.isdigit():
            raise Stage6BuildError(
                f"non-numeric poster_id {poster_raw!r} on submission {abstract_id}; "
                f"Stage-10 export uses int16 poster_id throughout"
            )
        poster_id_int = int(poster_raw)
        if poster_id_int in seen_poster_ids:
            deduped_oxford_ids.append(int(abstract_id))
            continue
        seen_poster_ids.add(poster_id_int)

        questions = question_lookup(raw)
        enriched = enriched_by_id.get(int(abstract_id), {})
        dois, urls, ref_titles = _references(refs_by_id.get(int(abstract_id)))
        authors = raw.get("authors") or []
        raw_author_ids = [
            int(a["id"]) for a in authors if isinstance(a, dict) and a.get("id") is not None
        ]
        if author_id_remap is not None:
            # Translate to synthetic ids; preserve author order; deduplicate
            # while preserving first-seen index so the lead author stays first.
            seen: set[int] = set()
            author_ids: list[int] = []
            for raw_id in raw_author_ids:
                synth = author_id_remap.get(raw_id)
                if synth is None or synth in seen:
                    continue
                seen.add(synth)
                author_ids.append(synth)
        else:
            author_ids = raw_author_ids

        # Stand-by start times are sourced from the proposal-listing CSV
        # (not in Oxford GraphQL). Stored as tz-aware UTC `datetime`
        # objects — the parquet emitter writes them as TIMESTAMP[ms, UTC]
        # (int64 on disk, dict-encodes well over the ~8 unique
        # conference slots). None for either field if the CSV wasn't
        # supplied or this submission isn't in it. Each window is
        # always 1 hour, so the end is implicit (start + 1h).
        standby = standby_by_sid.get(int(abstract_id), {})
        yield {
            # `abstract_id` is the Oxford submission id. It stays on the
            # yielded record so the rest of the build pipeline can join
            # against rollup/analysis files (which key by submission id).
            # The parquet emitter drops this field — only `poster_id`
            # lands in the exported shard.
            "abstract_id": int(abstract_id),
            "poster_id": poster_id_int,
            "title": cleaned_abstract_title(raw.get("title")) or "",
            "accepted_for": raw.get("accepted_for") or "Unknown",
            "sections": {
                "introduction": _section(questions, "introduction"),
                "methods": _section(questions, "methods"),
                "results": _section(questions, "results"),
                "conclusion": _section(questions, "conclusion"),
                "references": _section(questions, "references"),
            },
            "topics": _topics(questions),
            "methods_checklist": parse_string_list_value(
                questions.get(QUESTION_MAP["methods"])
            ),
            "facets": _facets(raw, questions, enriched),
            "author_ids": author_ids,
            "reference_dois": dois,
            "reference_urls": urls,
            "reference_titles": ref_titles,
            "poster_standby": {
                "first": standby.get("first"),
                "second": standby.get("second"),
            },
        }
    if skipped_no_poster_id:
        print(
            f"abstracts: skipped {skipped_no_poster_id} accepted record(s) without poster_id "
            f"(FR-002 requires the program-assigned poster_id as the user-facing identifier)"
        )
    if deduped_oxford_ids:
        print(
            f"abstracts: dropped {len(deduped_oxford_ids)} duplicate-poster_id record(s) "
            f"(Oxford submission ids: {deduped_oxford_ids}). First-encountered record per "
            f"poster_id wins; check upstream Oxford `program_code` for stale assignments."
        )


def build_abstracts_records(
    *,
    corpus_path: Path,
    enriched_path: Path | None,
    references_path: Path | None,
    withdrawn_path: Path | None,
    author_id_remap: Mapping[int, int] | None = None,
    standby_times_path: Path | None = None,
) -> list[dict[str, Any]]:
    """List-materialising wrapper around ``iter_abstracts`` for backward compat.

    Pre-Stage-10 callers (the json-shards emitter, every test fixture, the
    Stage-6 ``build_abstracts`` envelope below) consume the records as a
    list. Stage-10 candidate emitters (Parquet, SQLite, etc.) call
    ``iter_abstracts`` directly.
    """
    return list(
        iter_abstracts(
            corpus_path=corpus_path,
            enriched_path=enriched_path,
            references_path=references_path,
            withdrawn_path=withdrawn_path,
            author_id_remap=author_id_remap,
            standby_times_path=standby_times_path,
        )
    )


def build_abstracts(
    *,
    corpus_path: Path,
    enriched_path: Path | None,
    references_path: Path | None,
    withdrawn_path: Path | None,
    build_info: Mapping[str, str],
    author_id_remap: Mapping[int, int] | None = None,
    standby_times_path: Path | None = None,
) -> dict[str, Any]:
    """Return the abstracts shard envelope per data-model.md §2.

    Shape: ``{schema_version, build_info, abstracts: [...]}`` — raw-array
    output is forbidden (FR-019 + CA-008; §8 invariant 6).
    """

    records = build_abstracts_records(
        corpus_path=corpus_path,
        enriched_path=enriched_path,
        references_path=references_path,
        withdrawn_path=withdrawn_path,
        author_id_remap=author_id_remap,
        standby_times_path=standby_times_path,
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "build_info": dict(build_info),
        "abstracts": records,
    }
