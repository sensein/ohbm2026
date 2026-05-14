#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from ohbm2026.enrichment import html_to_markdown
from ohbm2026.enrich.openalex import (
    extract_reference_entries_heuristic,
    llm_reference_split_request,
    normalize_reference_match_text,
    normalize_reference_split_candidate,
    validate_reference_candidate_metadata,
    validate_reference_split_structured_candidates,
)


DEFAULT_ABSTRACT_IDS = [1245443, 1241895]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Probe OpenAI reference splitting on known regression abstracts")
    parser.add_argument("--input", default="data/abstracts.json")
    parser.add_argument("--env-file", default=".env")
    parser.add_argument("--openai-api-var", default="OPENAI_API_KEY")
    parser.add_argument("--backend", default="openai", choices=["openai", "ollama"])
    parser.add_argument("--model", default="gpt-5-nano")
    parser.add_argument("--abstract-id", action="append", type=int, dest="abstract_ids")
    parser.add_argument("--markdown-preview-chars", type=int, default=1200)
    parser.add_argument("--candidate-preview-chars", type=int, default=220)
    return parser.parse_args()


def load_abstract_map(path: Path) -> dict[int, dict[str, Any]]:
    database = json.loads(path.read_text())
    return {int(abstract["id"]): abstract for abstract in database.get("abstracts", [])}


def find_reference_value(abstract: dict[str, Any]) -> str:
    for response in abstract.get("responses", []):
        if response.get("question_name") == "References/Citations":
            return str(response.get("value") or "")
    return ""


def summarize_candidate(
    candidate: dict[str, str | None],
    source_markdown: str,
    preview_chars: int,
) -> dict[str, Any]:
    reference = candidate.get("reference") or ""
    title = candidate.get("title")
    doi = candidate.get("doi")
    normalized_source = normalize_reference_match_text(source_markdown)
    normalized_reference = normalize_reference_match_text(reference)
    normalized_title = normalize_reference_match_text(title) if title else ""
    return {
        "reference_preview": reference[:preview_chars],
        "title": title,
        "doi": doi,
        "reference_in_source": bool(normalized_reference and normalized_reference in normalized_source),
        "title_in_reference": bool(not title or normalized_title in normalized_reference),
        "doi_in_reference": bool(not doi or doi in reference.lower()),
        "candidate_metadata_valid": validate_reference_candidate_metadata(candidate),
    }


def main() -> int:
    args = parse_args()
    abstract_ids = args.abstract_ids or DEFAULT_ABSTRACT_IDS
    abstract_map = load_abstract_map(Path(args.input))

    results: list[dict[str, Any]] = []
    for abstract_id in abstract_ids:
        abstract = abstract_map.get(int(abstract_id))
        if abstract is None:
            results.append({"abstract_id": abstract_id, "error": "abstract not found"})
            continue

        raw_reference_value = find_reference_value(abstract)
        markdown = html_to_markdown(raw_reference_value)
        heuristic_entries = extract_reference_entries_heuristic(raw_reference_value)
        should_try = bool(markdown.strip())

        record: dict[str, Any] = {
            "abstract_id": abstract_id,
            "title": abstract.get("title"),
            "heuristic_count": len(heuristic_entries),
            "heuristic_preview": [entry[: args.candidate_preview_chars] for entry in heuristic_entries[:8]],
            "llm_enabled_for_markdown": should_try,
            "markdown_preview": markdown[: args.markdown_preview_chars],
        }

        if not should_try:
            record["llm_candidates"] = []
            results.append(record)
            continue

        try:
            raw_candidates = llm_reference_split_request(
                markdown,
                backend=args.backend,
                model=args.model,
                env_path=args.env_file,
                openai_api_var=args.openai_api_var,
            )
        except Exception as exc:  # pragma: no cover - this is a live probe script
            record["error"] = str(exc)
            results.append(record)
            continue

        normalized_candidates = [normalize_reference_split_candidate(candidate) for candidate in raw_candidates]
        normalized_candidates = [candidate for candidate in normalized_candidates if candidate is not None]
        record["llm_candidate_count"] = len(normalized_candidates)
        record["llm_candidates_validated_as_group"] = validate_reference_split_structured_candidates(markdown, normalized_candidates)
        record["llm_candidates"] = [
            summarize_candidate(candidate, markdown, args.candidate_preview_chars)
            for candidate in normalized_candidates
        ]
        results.append(record)

    print(
        json.dumps(
            {
                "input": args.input,
                "backend": args.backend,
                "model": args.model,
                "abstract_ids": abstract_ids,
                "results": results,
            },
            indent=2,
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
