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


def _load_standby_times(path: Path | None) -> dict[int, dict[str, str]]:
    """Load poster stand-by times from the proposal-listing CSV.

    Returns a `{submission_id: {first: "<day | hh:mm-hh:mm>", second: "..."}}`
    map. The CSV is the only place these times exist — they are not in
    the Oxford GraphQL schema. Lookup is by Oxford submission id (column
    "Abstract ID Number"), not poster_id, so the dedup upstream of this
    call still produces a valid lookup key for the surviving record.
    Returns an empty dict if no path is given or the CSV cannot be read.
    """
    if path is None:
        return {}
    import csv

    out: dict[int, dict[str, str]] = {}
    try:
        with Path(path).open() as f:
            lines = f.readlines()
        # The CSV has a multi-line preamble; the real header starts at
        # the row whose first cell reads "Abstract ID Number".
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
                "first": (row.get(first_col) or "").strip(),
                "second": (row.get(second_col) or "").strip(),
            }
    except (OSError, csv.Error):
        return {}
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
    seen_poster_ids: set[str] = set()
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
        poster_id_str = str(raw.get("poster_id"))
        if poster_id_str in seen_poster_ids:
            deduped_oxford_ids.append(int(abstract_id))
            continue
        seen_poster_ids.add(poster_id_str)

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

        # Stand-by times are sourced from the proposal-listing CSV (not in
        # Oxford GraphQL). Two empty strings if the CSV wasn't supplied or
        # this submission isn't in it; the UI suppresses the block until
        # the values are confirmed correct end-to-end.
        standby = standby_by_sid.get(int(abstract_id), {})
        yield {
            "abstract_id": int(abstract_id),
            "poster_id": str(raw.get("poster_id")),
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
                "first": standby.get("first", ""),
                "second": standby.get("second", ""),
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
