"""Build ``data/abstracts.json`` for Stage 6 (T012).

Strips ``submission_id``, emits ``poster_id`` as the user-facing identifier
(FR-002), assembles topics + methods checklist + per-record facets, and
populates ``author_ids`` referencing the canonical authors shard.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from ohbm2026.analyze.storage import parse_string_list_value
from ohbm2026.titles import cleaned_abstract_title
from ohbm2026.ui.payload import (
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


def _topics(questions: Mapping[str, Any]) -> dict[str, str]:
    """Return ``{primary, primary_subcategory, secondary, secondary_subcategory}``.

    Mirrors the existing ``build_metadata`` semantics in
    ``ohbm2026.ui.payload`` but in a flat record shape suited to the per-shard
    schema in data-model.md §2.
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


def _section(enriched: Mapping[str, Any] | None, name: str) -> str:
    if not enriched:
        return ""
    return str(enriched.get(f"{name}_markdown") or "")


def _references(record_refs: Iterable[Mapping[str, Any]] | None) -> tuple[list[str], list[str]]:
    """Return ``(reference_dois, reference_urls)`` as parallel arrays.

    Empty string fills the slot if either piece is missing.
    """

    dois: list[str] = []
    urls: list[str] = []
    for ref in record_refs or []:
        doi = str(ref.get("doi") or "")
        url = str(ref.get("url") or "")
        if not doi and not url:
            continue
        dois.append(doi)
        urls.append(url)
    return dois, urls


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
    """Read ``data/primary/reference_metadata.json`` if present."""

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
        if isinstance(refs, list):
            out[int(abstract_id)] = [r for r in refs if isinstance(r, dict)]
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


def build_abstracts_records(
    *,
    corpus_path: Path,
    enriched_path: Path | None,
    references_path: Path | None,
    withdrawn_path: Path | None,
) -> list[dict[str, Any]]:
    """Return the per-abstract list (accepted-only, poster_id-keyed)."""

    corpus = _load_corpus(corpus_path)
    enriched_by_id = _load_enriched_by_id(enriched_path)
    refs_by_id = _load_references_by_id(references_path)
    withdrawn = _withdrawn_ids(withdrawn_path)

    records: list[dict[str, Any]] = []
    for raw in corpus:
        if raw.get("accepted_for") == "Withdrawn":
            continue
        abstract_id = raw.get("id")
        if abstract_id is None:
            continue
        if int(abstract_id) in withdrawn:
            continue

        questions = question_lookup(raw)
        enriched = enriched_by_id.get(int(abstract_id), {})
        dois, urls = _references(refs_by_id.get(int(abstract_id)))
        authors = raw.get("authors") or []
        author_ids = [
            int(a["id"]) for a in authors if isinstance(a, dict) and a.get("id") is not None
        ]

        record = {
            "abstract_id": int(abstract_id),
            "poster_id": raw.get("poster_id") or "",
            "title": cleaned_abstract_title(raw.get("title")) or "",
            "accepted_for": raw.get("accepted_for") or "Unknown",
            "sections": {
                "introduction": _section(enriched, "introduction"),
                "methods": _section(enriched, "methods"),
                "results": _section(enriched, "results"),
                "conclusion": _section(enriched, "conclusion"),
                "references": _section(enriched, "references"),
            },
            "topics": _topics(questions),
            "methods_checklist": parse_string_list_value(
                questions.get(QUESTION_MAP["methods"])
            ),
            "facets": _facets(raw, questions, enriched),
            "author_ids": author_ids,
            "reference_dois": dois,
            "reference_urls": urls,
        }
        records.append(record)
    return records


def build_abstracts(
    *,
    corpus_path: Path,
    enriched_path: Path | None,
    references_path: Path | None,
    withdrawn_path: Path | None,
    build_info: Mapping[str, str],
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
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "build_info": dict(build_info),
        "abstracts": records,
    }
