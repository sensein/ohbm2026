from __future__ import annotations

import asyncio
import argparse
import hashlib
import json
import os
import re
import time
from collections import deque
from datetime import datetime, timezone
from difflib import SequenceMatcher
from functools import lru_cache
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, quote, urlencode, urlparse, urlunparse
from urllib.request import Request

from openai import APIStatusError, AsyncOpenAI, RateLimitError

from ohbm2026.enrichment import html_to_markdown
from ohbm2026.graphql_api import load_dotenv, urlopen_with_retries

OPENALEX_API = "https://api.openalex.org/works"
OPENALEX_RATE_LIMIT_API = "https://api.openalex.org/rate-limit"
OPENALEX_API_ENV = "OPENALEX_API"
OPENAI_RESPONSES_API = "https://api.openai.com/v1/responses"
OLLAMA_API = "http://127.0.0.1:11434/api"
DEFAULT_REFERENCE_SPLIT_BACKEND = "openai"
DEFAULT_REFERENCE_SPLIT_MODEL = "gpt-5-nano"
DEFAULT_REFERENCE_SPLIT_MAX_ATTEMPTS = 3
DEFAULT_REFERENCE_SPLIT_CONCURRENCY = 1
DEFAULT_REFERENCE_SPLIT_MAX_REQUEUES = 5
DEFAULT_OPENALEX_TITLE_CONCURRENCY = 20
DEFAULT_OPENALEX_TITLE_MAX_RPS = 90.0
SEMANTIC_SCHOLAR_API = "https://api.semanticscholar.org/graph/v1/paper/search"
SEMANTIC_SCHOLAR_API_ENV = "SEMANTIC_SCHOLAR_API_KEY"
CROSSREF_API = "https://api.crossref.org/works"
DOI_PATTERN = re.compile(r"(?:https?://(?:dx\.)?doi\.org/|doi:\s*)?(10\.\d{4,9}/[-._;()/:A-Z0-9]+)", re.I)
PMID_PATTERN = re.compile(r"\bPMID\s*:?\s*(\d+)\b", re.I)
YEAR_PATTERN = re.compile(r"\b(19|20)\d{2}\b")


class OpenAlexError(RuntimeError):
    """Raised when OpenAlex reference enrichment cannot continue."""


def reference_split_system_prompt() -> str:
    return (
        "Estimate how many distinct bibliographic references are present in the input before producing output. "
        "Then split the block into separate references. "
        "Return JSON with keys estimated_reference_count and references. "
        "Each object must include reference, title, and doi keys. "
        "The reference value must copy text from the input only; do not paraphrase, reorder, or invent content. "
        "The title must be copied from the reference text itself. "
        "The doi must be copied from the reference text when available, otherwise set it to null. "
        "Normalize whitespace only when needed."
    )


def reference_split_response_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "estimated_reference_count": {"type": "integer", "minimum": 0},
            "references": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "reference": {"type": "string"},
                        "title": {"type": ["string", "null"]},
                        "doi": {"type": ["string", "null"]},
                    },
                    "required": ["reference", "title", "doi"],
                },
            },
        },
        "required": ["estimated_reference_count", "references"],
    }


def openai_reference_split_payload(reference_text: str, *, model: str) -> dict[str, Any]:
    return {
        "model": model,
        "store": False,
        "reasoning": {"effort": "minimal"},
        "input": [
            {
                "role": "system",
                "content": [{"type": "input_text", "text": reference_split_system_prompt()}],
            },
            {
                "role": "user",
                "content": [{"type": "input_text", "text": reference_text}],
            },
        ],
        "text": {
            "format": {
                "type": "json_schema",
                "name": "reference_split",
                "strict": True,
                "schema": reference_split_response_schema(),
            }
        },
    }


def default_request_counts() -> dict[str, int]:
    return {
        "doi_requests": 0,
        "pmid_requests": 0,
        "title_requests": 0,
        "reference_split_requests": 0,
        "reference_split_requeues": 0,
        "reference_split_rate_limit_requeues": 0,
        "semantic_scholar_requests": 0,
    }


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def normalize_reference_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def extract_reference_entries_heuristic(raw_value: str | None) -> list[str]:
    markdown = html_to_markdown(raw_value or "")
    if not markdown.strip():
        return []

    lines = [line.strip() for line in markdown.splitlines() if line.strip()]
    entries: list[str] = []
    current: list[str] = []
    for line in lines:
        if re.match(r"^(\d+\.\s+|-+\s+)", line):
            if current:
                entries.append(normalize_reference_text(" ".join(current)))
            current = [re.sub(r"^(\d+\.\s+|-+\s+)", "", line)]
        else:
            current.append(line)

    if current:
        entries.append(normalize_reference_text(" ".join(current)))
    if not entries and markdown.strip():
        entries.append(normalize_reference_text(markdown))
    return [entry for entry in entries if entry]


def normalize_reference_match_text(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip().lower()


def validate_reference_split_candidates(reference_text: str, candidates: list[str], *, min_coverage: float = 0.6) -> bool:
    normalized_source = normalize_reference_match_text(reference_text)
    if not normalized_source or not candidates:
        return False
    position = 0
    matched_characters = 0
    for candidate in candidates:
        normalized_candidate = normalize_reference_match_text(candidate)
        if not normalized_candidate:
            return False
        index = normalized_source.find(normalized_candidate, position)
        if index < 0:
            return False
        position = index + len(normalized_candidate)
        matched_characters += len(normalized_candidate)
    return (matched_characters / len(normalized_source)) >= min_coverage


def normalize_reference_split_candidate(candidate: Any) -> dict[str, str | None] | None:
    if isinstance(candidate, str):
        reference = normalize_reference_text(candidate)
        if not reference:
            return None
        return {"reference": reference, "title": None, "doi": None}
    if not isinstance(candidate, dict):
        return None
    reference = normalize_reference_text(str(candidate.get("reference") or ""))
    if not reference:
        return None
    title = normalize_reference_text(str(candidate.get("title") or "")) or None
    doi = normalize_doi(candidate.get("doi")) if candidate.get("doi") else None
    return {"reference": reference, "title": title, "doi": doi}


def normalize_reference_split_response(response: Any) -> dict[str, Any]:
    if isinstance(response, list):
        return {
            "estimated_reference_count": None,
            "references": response,
        }
    if not isinstance(response, dict):
        raise OpenAlexError("Reference split returned an unsupported payload")
    estimated_count = response.get("estimated_reference_count")
    if estimated_count is not None:
        try:
            estimated_count = int(estimated_count)
        except (TypeError, ValueError) as exc:
            raise OpenAlexError("Reference split returned a non-integer estimated_reference_count") from exc
        if estimated_count < 0:
            raise OpenAlexError("Reference split returned a negative estimated_reference_count")
    references = response.get("references")
    if not isinstance(references, list):
        raise OpenAlexError("Reference split returned no references array")
    return {
        "estimated_reference_count": estimated_count,
        "references": references,
    }


def validate_reference_candidate_metadata(candidate: dict[str, str | None]) -> bool:
    reference = candidate.get("reference") or ""
    normalized_reference = normalize_reference_match_text(reference)
    if not normalized_reference:
        return False
    title = candidate.get("title")
    if title and normalize_reference_match_text(title) not in normalized_reference:
        return False
    doi = candidate.get("doi")
    if doi and doi not in extract_dois(reference):
        return False
    return True


def validate_reference_split_structured_candidates(
    reference_text: str,
    candidates: list[dict[str, str | None] | str],
    *,
    min_coverage: float = 0.6,
) -> bool:
    normalized_candidates: list[dict[str, str | None]] = []
    for candidate in candidates:
        normalized_candidate = normalize_reference_split_candidate(candidate)
        if normalized_candidate is None or not validate_reference_candidate_metadata(normalized_candidate):
            return False
        normalized_candidates.append(normalized_candidate)
    return validate_reference_split_candidates(
        reference_text,
        [candidate["reference"] or "" for candidate in normalized_candidates],
        min_coverage=min_coverage,
    )


def fallback_reference_candidates(reference_text: str) -> list[dict[str, str | None]]:
    normalized = normalize_reference_text(reference_text)
    if not normalized:
        return []
    return [{"reference": normalized, "title": None, "doi": None}]


def split_reference_markdown(
    reference_text: str,
    *,
    backend: str = DEFAULT_REFERENCE_SPLIT_BACKEND,
    model: str = DEFAULT_REFERENCE_SPLIT_MODEL,
    env_path: str = ".env",
    openai_api_var: str = "OPENAI_API_KEY",
    max_attempts: int = DEFAULT_REFERENCE_SPLIT_MAX_ATTEMPTS,
) -> tuple[list[dict[str, str | None]], dict[str, Any]]:
    if not normalize_reference_text(reference_text):
        return [], {
            "reference_split_strategy": "empty",
            "reference_split_attempts": 0,
            "reference_split_error": None,
            "reference_split_fallback_reason": None,
            "reference_split_candidate_count": 0,
            "reference_split_estimated_count": 0,
        }

    last_error: str | None = None
    estimated_count: int | None = None
    for attempt in range(1, max(1, max_attempts) + 1):
        try:
            llm_response = normalize_reference_split_response(
                llm_reference_split_request(
                    reference_text,
                    backend=backend,
                    model=model,
                    env_path=env_path,
                    openai_api_var=openai_api_var,
                )
            )
        except OpenAlexError as exc:
            last_error = str(exc)
            continue

        estimated_count = llm_response.get("estimated_reference_count")
        llm_candidates = llm_response.get("references") or []
        normalized_candidates = [normalize_reference_split_candidate(candidate) for candidate in llm_candidates]
        normalized_candidates = [candidate for candidate in normalized_candidates if candidate is not None]
        if validate_reference_split_structured_candidates(reference_text, normalized_candidates):
            return normalized_candidates, {
                "reference_split_strategy": "llm",
                "reference_split_attempts": attempt,
                "reference_split_error": None,
                "reference_split_fallback_reason": None,
                "reference_split_candidate_count": len(normalized_candidates),
                "reference_split_estimated_count": estimated_count,
            }
        last_error = "Structured split failed lexical validation"

    fallback_candidates = fallback_reference_candidates(reference_text)
    fallback_reason = "llm_error" if last_error and last_error != "Structured split failed lexical validation" else "validation_failed"
    return fallback_candidates, {
        "reference_split_strategy": "fallback_single_block",
        "reference_split_attempts": max(1, max_attempts),
        "reference_split_error": last_error,
        "reference_split_fallback_reason": fallback_reason,
        "reference_split_candidate_count": len(fallback_candidates),
        "reference_split_estimated_count": estimated_count,
    }


def extract_reference_entries(
    raw_value: str | None,
    *,
    use_llm_reference_splitting: bool = False,
    reference_splitting_backend: str = DEFAULT_REFERENCE_SPLIT_BACKEND,
    reference_splitting_model: str = DEFAULT_REFERENCE_SPLIT_MODEL,
    env_path: str = ".env",
    openai_api_var: str = "OPENAI_API_KEY",
) -> list[str]:
    markdown = html_to_markdown(raw_value or "")
    if not use_llm_reference_splitting:
        return extract_reference_entries_heuristic(raw_value)
    candidates, _ = split_reference_markdown(
        markdown,
        backend=reference_splitting_backend,
        model=reference_splitting_model,
        env_path=env_path,
        openai_api_var=openai_api_var,
    )
    return [candidate["reference"] for candidate in candidates if candidate and candidate.get("reference")]


def normalize_doi(doi: str | None) -> str | None:
    if not doi:
        return None
    cleaned = doi.strip()
    cleaned = re.sub(r"^(?:https?://(?:dx\.)?doi\.org/|doi:\s*)", "", cleaned, flags=re.I)
    cleaned = cleaned.split()[0]
    cleaned = re.split(r"(?i)\.pmid:?", cleaned)[0]
    cleaned = cleaned.rstrip(").,; ]}")
    return cleaned.lower() or None


def extract_dois(reference_text: str) -> list[str]:
    dois = [normalize_doi(match) for match in DOI_PATTERN.findall(reference_text)]
    seen: set[str] = set()
    result: list[str] = []
    for doi in dois:
        if doi and doi not in seen:
            seen.add(doi)
            result.append(doi)
    return result


def extract_pmid(reference_text: str) -> str | None:
    match = PMID_PATTERN.search(reference_text)
    return match.group(1) if match else None


def guess_reference_title(reference_text: str) -> str:
    text = DOI_PATTERN.sub("", reference_text)
    text = PMID_PATTERN.sub("", text)
    segments = [segment.strip(" .") for segment in re.split(r"\.\s+", text) if segment.strip(" .")]
    if len(segments) >= 2 and len(segments[1].split()) >= 3:
        return segments[1]
    if segments:
        return segments[0]
    return normalize_reference_text(reference_text)


def extract_reference_year(reference_text: str) -> int | None:
    matches = YEAR_PATTERN.findall(reference_text)
    if not matches:
        return None
    year_match = re.search(r"\b((?:19|20)\d{2})\b", reference_text)
    return int(year_match.group(1)) if year_match else None


def build_reference_key(reference_text: str, doi: str | None = None, pmid: str | None = None) -> str:
    if doi:
        return f"doi:{doi}"
    if pmid:
        return f"pmid:{pmid}"
    digest = hashlib.sha1(normalize_reference_text(reference_text).lower().encode("utf-8")).hexdigest()
    return f"text:{digest}"


def title_similarity(left: str, right: str) -> float:
    normalized_left = re.sub(r"[^a-z0-9]+", " ", left.lower()).strip()
    normalized_right = re.sub(r"[^a-z0-9]+", " ", right.lower()).strip()
    if not normalized_left or not normalized_right:
        return 0.0
    return SequenceMatcher(a=normalized_left, b=normalized_right).ratio()


@lru_cache(maxsize=1)
def get_openalex_api_key(env_path: str = ".env") -> str | None:
    env_values = load_dotenv(Path(env_path))
    api_key = os.environ.get(OPENALEX_API_ENV) or env_values.get(OPENALEX_API_ENV)
    return api_key or None


@lru_cache(maxsize=1)
def get_semantic_scholar_api_key(env_path: str = ".env") -> str | None:
    env_values = load_dotenv(Path(env_path))
    api_key = os.environ.get(SEMANTIC_SCHOLAR_API_ENV) or env_values.get(SEMANTIC_SCHOLAR_API_ENV)
    return api_key or None


@lru_cache(maxsize=None)
def get_openai_api_key(env_path: str = ".env", api_var: str = "OPENAI_API_KEY") -> str | None:
    env_values = load_dotenv(Path(env_path))
    api_key = os.environ.get(api_var) or env_values.get(api_var)
    return api_key or None


def add_query_parameter(url: str, key: str, value: str) -> str:
    parsed = urlparse(url)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query[key] = value
    return urlunparse(parsed._replace(query=urlencode(query)))


def scholarly_request(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    error_label: str,
) -> dict[str, Any]:
    payload, _ = scholarly_request_with_headers(url, headers=headers, error_label=error_label)
    return payload


def scholarly_request_with_headers(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    error_label: str,
) -> tuple[dict[str, Any], dict[str, str]]:
    request_headers = {"User-Agent": "ohbm2026-reference-enrichment/0.1", "Accept": "application/json"}
    if headers:
        request_headers.update(headers)
    request = Request(url, headers=request_headers)
    try:
        with urlopen_with_retries(request) as response:
            payload = json.loads(response.read().decode("utf-8"))
            response_headers = dict(getattr(response, "headers", {}).items()) if getattr(response, "headers", None) else {}
            return payload, response_headers
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise OpenAlexError(f"{error_label} failed with HTTP {exc.code}: {body}") from exc
    except (URLError, OSError, TimeoutError, ValueError) as exc:
        raise OpenAlexError(f"{error_label} failed: {exc}") from exc


def openalex_request(url: str) -> dict[str, Any]:
    payload, _ = openalex_request_with_headers(url)
    return payload


def openalex_request_with_headers(url: str) -> tuple[dict[str, Any], dict[str, str]]:
    api_key = get_openalex_api_key()
    if api_key:
        url = add_query_parameter(url, "api_key", api_key)
    return scholarly_request_with_headers(url, error_label="OpenAlex request")


def semantic_scholar_request(url: str) -> dict[str, Any]:
    headers: dict[str, str] = {}
    api_key = get_semantic_scholar_api_key()
    if api_key:
        headers["x-api-key"] = api_key
    return scholarly_request(url, headers=headers, error_label="Semantic Scholar request")


def crossref_request(url: str, *, mailto: str | None = None) -> dict[str, Any]:
    if mailto:
        url = add_query_parameter(url, "mailto", mailto)
    return scholarly_request(url, error_label="Crossref request")


def ollama_reference_split_request(
    reference_text: str,
    *,
    model: str = DEFAULT_REFERENCE_SPLIT_MODEL,
) -> dict[str, Any]:
    payload = {
        "model": model,
        "stream": False,
        "format": "json",
        "options": {"temperature": 0},
        "messages": [
            {
                "role": "system",
                "content": reference_split_system_prompt(),
            },
            {
                "role": "user",
                "content": reference_text,
            },
        ],
    }
    request = Request(
        f"{OLLAMA_API}/chat",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urlopen_with_retries(request) as response:
            parsed = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise OpenAlexError(f"Ollama reference split failed with HTTP {exc.code}: {body}") from exc
    except (URLError, OSError, TimeoutError, ValueError) as exc:
        raise OpenAlexError(f"Ollama reference split failed: {exc}") from exc

    message = parsed.get("message") or {}
    content = message.get("content")
    if not content:
        raise OpenAlexError("Ollama reference split returned no content")
    try:
        content_payload = json.loads(content)
    except json.JSONDecodeError as exc:
        raise OpenAlexError(f"Ollama reference split returned invalid JSON: {content}") from exc
    normalized_payload = normalize_reference_split_response(content_payload)
    normalized_references = [normalize_reference_split_candidate(reference) for reference in normalized_payload["references"]]
    return {
        "estimated_reference_count": normalized_payload["estimated_reference_count"],
        "references": [reference for reference in normalized_references if reference is not None],
    }


def openai_reference_split_request(
    reference_text: str,
    *,
    env_path: str = ".env",
    openai_api_var: str = "OPENAI_API_KEY",
    model: str = DEFAULT_REFERENCE_SPLIT_MODEL,
) -> dict[str, Any]:
    api_key = get_openai_api_key(env_path, openai_api_var)
    if not api_key:
        raise OpenAlexError(f"Missing OpenAI API key in {openai_api_var}")

    payload = openai_reference_split_payload(reference_text, model=model)
    request = Request(
        OPENAI_RESPONSES_API,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": "ohbm2026-reference-enrichment/0.1",
        },
        method="POST",
    )
    try:
        with urlopen_with_retries(request) as response:
            parsed = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise OpenAlexError(f"OpenAI reference split failed with HTTP {exc.code}: {body}") from exc
    except (URLError, OSError, TimeoutError, ValueError) as exc:
        raise OpenAlexError(f"OpenAI reference split failed: {exc}") from exc

    content = parsed.get("output_text")
    if not content:
        for item in parsed.get("output", []):
            if item.get("type") != "message":
                continue
            for entry in item.get("content", []):
                if entry.get("type") in {"output_text", "text"} and entry.get("text"):
                    content = entry["text"]
                    break
            if content:
                break
    if not content:
        raise OpenAlexError("OpenAI reference split returned no content")
    try:
        content_payload = json.loads(content)
    except json.JSONDecodeError as exc:
        raise OpenAlexError(f"OpenAI reference split returned invalid JSON: {content}") from exc
    normalized_payload = normalize_reference_split_response(content_payload)
    normalized_references = [normalize_reference_split_candidate(reference) for reference in normalized_payload["references"]]
    return {
        "estimated_reference_count": normalized_payload["estimated_reference_count"],
        "references": [reference for reference in normalized_references if reference is not None],
    }


async def openai_reference_split_request_async(
    client: AsyncOpenAI,
    reference_text: str,
    *,
    model: str = DEFAULT_REFERENCE_SPLIT_MODEL,
) -> dict[str, Any]:
    try:
        response = await client.responses.create(**openai_reference_split_payload(reference_text, model=model))
    except Exception as exc:  # pragma: no cover - SDK/network wrapper
        raise exc

    content = getattr(response, "output_text", None) or ""
    if not content:
        for item in getattr(response, "output", []) or []:
            if getattr(item, "type", None) != "message":
                continue
            for entry in getattr(item, "content", []) or []:
                entry_type = getattr(entry, "type", None)
                text = getattr(entry, "text", None)
                if entry_type in {"output_text", "text"} and text:
                    content = text
                    break
            if content:
                break
    if not content:
        raise OpenAlexError("OpenAI reference split returned no content")
    try:
        content_payload = json.loads(content)
    except json.JSONDecodeError as exc:
        raise OpenAlexError(f"OpenAI reference split returned invalid JSON: {content}") from exc
    normalized_payload = normalize_reference_split_response(content_payload)
    normalized_references = [normalize_reference_split_candidate(reference) for reference in normalized_payload["references"]]
    return {
        "estimated_reference_count": normalized_payload["estimated_reference_count"],
        "references": [reference for reference in normalized_references if reference is not None],
    }


def llm_reference_split_request(
    reference_text: str,
    *,
    backend: str = DEFAULT_REFERENCE_SPLIT_BACKEND,
    model: str = DEFAULT_REFERENCE_SPLIT_MODEL,
    env_path: str = ".env",
    openai_api_var: str = "OPENAI_API_KEY",
) -> dict[str, Any]:
    if backend == "ollama":
        return ollama_reference_split_request(reference_text, model=model)
    if backend == "openai":
        return openai_reference_split_request(
            reference_text,
            env_path=env_path,
            openai_api_var=openai_api_var,
            model=model,
        )
    raise OpenAlexError(f"Unsupported reference splitting backend: {backend}")


def fetch_openalex_work_by_doi(doi: str) -> dict[str, Any] | None:
    url = f"{OPENALEX_API}?filter=doi:{quote(doi, safe='')}&per-page=1"
    parsed = openalex_request(url)
    results = parsed.get("results", [])
    return results[0] if results else None


def fetch_openalex_work_by_pmid(pmid: str) -> dict[str, Any] | None:
    url = f"{OPENALEX_API}?filter=pmid:{quote(pmid, safe='')}&per-page=1"
    parsed = openalex_request(url)
    results = parsed.get("results", [])
    return results[0] if results else None


def search_openalex_work_by_title(title: str, min_similarity: float = 0.75) -> dict[str, Any] | None:
    work, _ = search_openalex_work_by_title_with_headers(title, min_similarity=min_similarity)
    return work


def search_openalex_work_by_title_with_headers(
    title: str,
    min_similarity: float = 0.75,
) -> tuple[dict[str, Any] | None, dict[str, str]]:
    if not title.strip():
        return None, {}
    url = f"{OPENALEX_API}?search={quote(title)}&per-page=5"
    parsed, headers = openalex_request_with_headers(url)
    best_match: dict[str, Any] | None = None
    best_score = 0.0
    for result in parsed.get("results", []):
        score = title_similarity(title, result.get("display_name") or "")
        if score > best_score:
            best_score = score
            best_match = result
    if best_match and best_score >= min_similarity:
        return best_match, headers
    return None, headers


def fetch_openalex_rate_limit_status() -> dict[str, Any]:
    payload, _ = openalex_request_with_headers(OPENALEX_RATE_LIMIT_API)
    return payload


def extract_semantic_scholar_doi(result: dict[str, Any]) -> str | None:
    external_ids = result.get("externalIds") or {}
    for key in ("DOI", "doi"):
        doi = normalize_doi(external_ids.get(key))
        if doi:
            return doi
    return None


def semantic_scholar_year(result: dict[str, Any]) -> int | None:
    year = result.get("year")
    return int(year) if isinstance(year, int) else None


def semantic_scholar_title_score(result: dict[str, Any], title: str, reference_year: int | None = None) -> float:
    score = title_similarity(title, str(result.get("title") or ""))
    result_year = semantic_scholar_year(result)
    if reference_year is not None and result_year is not None and reference_year == result_year:
        score += 0.03
    return score


def search_semantic_scholar_doi_by_title(
    title: str,
    *,
    min_similarity: float = 0.8,
    reference_year: int | None = None,
) -> tuple[str | None, float]:
    if not title.strip():
        return None, 0.0
    url = (
        f"{SEMANTIC_SCHOLAR_API}?query={quote(title)}&limit=5"
        "&fields=title,year,externalIds,venue"
    )
    parsed = semantic_scholar_request(url)
    best_doi: str | None = None
    best_score = 0.0
    for result in parsed.get("data", []):
        doi = extract_semantic_scholar_doi(result)
        if not doi:
            continue
        score = semantic_scholar_title_score(result, title, reference_year=reference_year)
        if score > best_score:
            best_score = score
            best_doi = doi
    if best_doi and best_score >= min_similarity:
        return best_doi, best_score
    return None, best_score


def semantic_scholar_reference_score(result: dict[str, Any], reference_text: str, reference_year: int | None = None) -> float:
    normalized_reference = normalize_reference_match_text(reference_text)
    title = str(result.get("title") or "")
    normalized_title = normalize_reference_match_text(title)
    if normalized_title and normalized_title in normalized_reference:
        score = 1.0
    else:
        score = title_similarity(reference_text, title)
    result_year = semantic_scholar_year(result)
    if reference_year is not None and result_year is not None and reference_year == result_year:
        score += 0.03
    return score


def search_semantic_scholar_doi_by_reference(
    reference_text: str,
    *,
    min_similarity: float = 0.8,
    reference_year: int | None = None,
) -> tuple[str | None, float]:
    if not reference_text.strip():
        return None, 0.0
    url = (
        f"{SEMANTIC_SCHOLAR_API}?query={quote(reference_text)}&limit=5"
        "&fields=title,year,externalIds,venue"
    )
    parsed = semantic_scholar_request(url)
    best_doi: str | None = None
    best_score = 0.0
    for result in parsed.get("data", []):
        doi = extract_semantic_scholar_doi(result)
        if not doi:
            continue
        score = semantic_scholar_reference_score(result, reference_text, reference_year=reference_year)
        if score > best_score:
            best_score = score
            best_doi = doi
    if best_doi and best_score >= min_similarity:
        return best_doi, best_score
    return None, best_score


def extract_crossref_title(item: dict[str, Any]) -> str:
    titles = item.get("title") or []
    if isinstance(titles, list) and titles:
        return str(titles[0] or "")
    return str(item.get("title") or "")


def extract_crossref_year(item: dict[str, Any]) -> int | None:
    for field in ("published-print", "published-online", "published"):
        parts = ((item.get(field) or {}).get("date-parts") or [])
        if parts and parts[0]:
            first = parts[0][0]
            if isinstance(first, int):
                return first
    return None


def crossref_title_score(item: dict[str, Any], title: str, reference_year: int | None = None) -> float:
    score = title_similarity(title, extract_crossref_title(item))
    item_year = extract_crossref_year(item)
    if reference_year is not None and item_year is not None and reference_year == item_year:
        score += 0.03
    return score


def search_crossref_doi_by_title(
    title: str,
    *,
    min_similarity: float = 0.8,
    reference_year: int | None = None,
    mailto: str | None = None,
) -> tuple[str | None, float]:
    if not title.strip():
        return None, 0.0
    url = f"{CROSSREF_API}?query.title={quote(title)}&rows=5"
    parsed = crossref_request(url, mailto=mailto)
    items = ((parsed.get("message") or {}).get("items") or [])
    best_doi: str | None = None
    best_score = 0.0
    for item in items:
        doi = normalize_doi(item.get("DOI"))
        if not doi:
            continue
        score = crossref_title_score(item, title, reference_year=reference_year)
        if score > best_score:
            best_score = score
            best_doi = doi
    if best_doi and best_score >= min_similarity:
        return best_doi, best_score
    return None, best_score


def normalize_openalex_work(work: dict[str, Any]) -> dict[str, Any]:
    pmid_value = ((work.get("ids") or {}).get("pmid") or "").strip()
    pmid_match = re.search(r"(\d+)", pmid_value)
    return {
        "openalex_id": work.get("id"),
        "doi": normalize_doi((work.get("doi") or "").strip()) if work.get("doi") else None,
        "pmid": pmid_match.group(1) if pmid_match else None,
        "display_name": work.get("display_name"),
        "publication_year": work.get("publication_year"),
        "publication_date": work.get("publication_date"),
        "journal": (((work.get("primary_location") or {}).get("source") or {}).get("display_name")),
        "type": work.get("type"),
        "type_crossref": work.get("type_crossref"),
        "is_review": str(work.get("type") or "").lower() == "review"
        or str(work.get("type_crossref") or "").lower() == "review-article",
        "cited_by_count": work.get("cited_by_count"),
        "referenced_works": work.get("referenced_works") or [],
        "referenced_works_count": work.get("referenced_works_count"),
    }


def build_reference_record(
    reference_text: str,
    *,
    title_guess_override: str | None = None,
    doi_override: str | None = None,
) -> dict[str, Any]:
    normalized_reference_text = normalize_reference_text(reference_text)
    extracted_dois = extract_dois(normalized_reference_text)
    override_doi = normalize_doi(doi_override) if doi_override else None
    doi = override_doi if override_doi and override_doi in extracted_dois else next(iter(extracted_dois), None)
    pmid = extract_pmid(reference_text)
    override_title = normalize_reference_text(title_guess_override) if title_guess_override else None
    if override_title and normalize_reference_match_text(override_title) in normalize_reference_match_text(normalized_reference_text):
        title_guess = override_title
    else:
        title_guess = guess_reference_title(reference_text)
    return {
        "reference_key": build_reference_key(reference_text, doi=doi, pmid=pmid),
        "raw_text": normalized_reference_text,
        "doi": doi,
        "pmid": pmid,
        "title_guess": title_guess,
        "reference_year": extract_reference_year(reference_text),
    }


def merge_reference_candidates_into_cache(
    reference_candidates: list[dict[str, str | None]],
    reference_cache: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    references: list[dict[str, Any]] = []
    for reference_candidate in reference_candidates:
        reference = build_reference_record(
            reference_candidate["reference"] or "",
            title_guess_override=reference_candidate.get("title"),
            doi_override=reference_candidate.get("doi"),
        )
        cached = reference_cache.get(reference["reference_key"])
        if cached is None:
            cached = {
                **reference,
                "matched": False,
                "match_method": "pending",
                "openalex": None,
                "source_count": 0,
                "raw_text_examples": [],
                "doi_lookup_completed": False,
                "doi_discovery_completed": False,
                "doi_discovery_source": None,
                "doi_discovery_title_score": None,
                "pmid_lookup_completed": False,
                "title_lookup_completed": False,
            }
            reference_cache[reference["reference_key"]] = cached
        else:
            if not cached.get("doi") and reference.get("doi"):
                cached["doi"] = reference["doi"]
            if not cached.get("pmid") and reference.get("pmid"):
                cached["pmid"] = reference["pmid"]
            if not cached.get("title_guess") and reference.get("title_guess"):
                cached["title_guess"] = reference["title_guess"]
            if not cached.get("reference_year") and reference.get("reference_year"):
                cached["reference_year"] = reference["reference_year"]
            cached.setdefault("matched", False)
            cached.setdefault("match_method", "pending")
            cached.setdefault("openalex", None)
            cached.setdefault("source_count", 0)
            cached.setdefault("raw_text_examples", [])
            cached.setdefault("doi_lookup_completed", False)
            cached.setdefault("doi_discovery_completed", False)
            cached.setdefault("doi_discovery_source", None)
            cached.setdefault("doi_discovery_title_score", None)
            cached.setdefault("pmid_lookup_completed", False)
            cached.setdefault("title_lookup_completed", False)

        cached["source_count"] = int(cached.get("source_count", 0)) + 1
        raw_text_examples = list(cached.get("raw_text_examples", []))
        if reference["raw_text"] not in raw_text_examples and len(raw_text_examples) < 3:
            raw_text_examples.append(reference["raw_text"])
        cached["raw_text_examples"] = raw_text_examples
        references.append(reference)
    return references


def build_abstract_reference_record(
    abstract_id: int,
    reference_candidates: list[dict[str, str | None]],
    reference_cache: dict[str, dict[str, Any]],
    split_diagnostics: dict[str, Any],
) -> dict[str, Any]:
    return {
        "id": abstract_id,
        "references": merge_reference_candidates_into_cache(reference_candidates, reference_cache),
        **split_diagnostics,
    }


def load_existing_reference_cache(output_path: Path) -> dict[str, dict[str, Any]]:
    if not output_path.exists():
        return {}
    try:
        database = load_json(output_path)
    except json.JSONDecodeError:
        return {}
    return {
        reference["reference_key"]: reference
        for reference in database.get("references", [])
        if isinstance(reference.get("reference_key"), str)
    }


def normalize_cached_reference(reference: dict[str, Any]) -> dict[str, Any]:
    return {
        "reference_key": reference["reference_key"],
        "raw_text": reference.get("raw_text") or "",
        "doi": reference.get("doi"),
        "pmid": reference.get("pmid"),
        "title_guess": reference.get("title_guess"),
        "reference_year": reference.get("reference_year"),
        "matched": bool(reference.get("matched")),
        "match_method": reference.get("match_method") or "pending",
        "openalex": reference.get("openalex"),
        "source_count": 0,
        "raw_text_examples": [],
        "doi_lookup_completed": bool(reference.get("doi_lookup_completed")),
        "doi_discovery_completed": bool(reference.get("doi_discovery_completed")),
        "doi_discovery_source": reference.get("doi_discovery_source"),
        "doi_discovery_title_score": reference.get("doi_discovery_title_score"),
        "pmid_lookup_completed": bool(reference.get("pmid_lookup_completed")),
        "title_lookup_completed": bool(reference.get("title_lookup_completed")),
    }


def chunked_values(values: list[str], chunk_size: int) -> list[list[str]]:
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")
    return [values[index : index + chunk_size] for index in range(0, len(values), chunk_size)]


def is_rate_limit_error_message(message: str) -> bool:
    lowered = message.lower()
    return (
        "rate limit" in lowered
        or "requests per min" in lowered
        or "requests per minute" in lowered
        or "tokens per min" in lowered
        or "tokens per minute" in lowered
        or "429" in lowered
    )


def rate_limit_retry_delay_seconds(error: Exception, attempt: int) -> float:
    response = getattr(error, "response", None)
    headers = getattr(response, "headers", None)
    if headers:
        retry_after = headers.get("retry-after") or headers.get("Retry-After")
        if retry_after:
            try:
                return max(1.0, float(retry_after))
            except ValueError:
                pass
    return min(60.0, max(1.0, 2**attempt))


def fetch_openalex_works_by_field(field_name: str, values: list[str]) -> dict[str, dict[str, Any]]:
    if not values:
        return {}
    filter_value = f"{field_name}:" + "|".join(quote(value, safe="") for value in values)
    try:
        parsed = openalex_request(f"{OPENALEX_API}?filter={filter_value}&per-page={len(values)}")
    except OpenAlexError as exc:
        if "HTTP 400" not in str(exc):
            raise
        if len(values) == 1:
            return {}
        midpoint = max(1, len(values) // 2)
        left = fetch_openalex_works_by_field(field_name, values[:midpoint])
        right = fetch_openalex_works_by_field(field_name, values[midpoint:])
        return {**left, **right}
    results = parsed.get("results", [])
    mapping: dict[str, dict[str, Any]] = {}
    for result in results:
        if field_name == "doi":
            key = normalize_doi(result.get("doi"))
        elif field_name == "pmid":
            pmid_value = ((result.get("ids") or {}).get("pmid") or "").strip()
            pmid_match = re.search(r"(\d+)", pmid_value)
            key = pmid_match.group(1) if pmid_match else None
        else:
            raise ValueError(f"Unsupported field_name: {field_name}")
        if key:
            mapping[key] = result
    return mapping


async def collect_reference_cache_openai_async(
    abstracts_database: dict[str, Any],
    output_path: Path,
    *,
    use_title_search: bool,
    reference_splitting_model: str,
    env_path: str,
    openai_api_var: str,
    request_counts: dict[str, int] | None,
    collect_checkpoint_every_abstracts: int,
    split_concurrency: int,
    split_max_requeues: int,
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    api_key = get_openai_api_key(env_path, openai_api_var)
    if not api_key:
        raise OpenAlexError(f"Missing OpenAI API key in {openai_api_var}")

    reference_cache = {
        key: normalize_cached_reference(value)
        for key, value in load_existing_reference_cache(output_path).items()
    }
    stats = request_counts if request_counts is not None else default_request_counts()
    abstracts = list(abstracts_database.get("abstracts", []))
    pending: asyncio.Queue[tuple[int, dict[str, Any], int]] = asyncio.Queue()
    completed: asyncio.Queue[tuple[int, dict[str, Any]]] = asyncio.Queue()
    loop = asyncio.get_running_loop()
    rate_limit_lock = asyncio.Lock()
    blocked_until = 0.0

    async def wait_for_capacity() -> None:
        nonlocal blocked_until
        while True:
            async with rate_limit_lock:
                delay = blocked_until - loop.time()
            if delay <= 0:
                return
            await asyncio.sleep(min(delay, 1.0))

    async def extend_backoff(delay_seconds: float) -> None:
        nonlocal blocked_until
        async with rate_limit_lock:
            blocked_until = max(blocked_until, loop.time() + delay_seconds)

    def fallback_diagnostics(attempt: int, error_message: str, estimated_count: int | None, *, rate_limited: bool) -> dict[str, Any]:
        fallback_reason = "rate_limited" if rate_limited else "validation_failed" if error_message == "Structured split failed lexical validation" else "llm_error"
        return {
            "reference_split_strategy": "fallback_single_block",
            "reference_split_attempts": attempt,
            "reference_split_error": error_message,
            "reference_split_fallback_reason": fallback_reason,
            "reference_split_candidate_count": 1,
            "reference_split_estimated_count": estimated_count,
        }

    async def worker(client: AsyncOpenAI) -> None:
        while True:
            index, abstract, attempt = await pending.get()
            if index < 0:
                pending.task_done()
                return

            raw_reference_value = ""
            for response in abstract.get("responses", []):
                if response.get("question_name") == "References/Citations":
                    raw_reference_value = response.get("value") or ""
                    break
            markdown = html_to_markdown(raw_reference_value or "")
            if not markdown.strip():
                await completed.put(
                    (
                        index,
                        {
                            "id": abstract["id"],
                            "reference_candidates": [],
                            "diagnostics": {
                                "reference_split_strategy": "empty",
                                "reference_split_attempts": 0,
                                "reference_split_error": None,
                                "reference_split_fallback_reason": None,
                                "reference_split_candidate_count": 0,
                                "reference_split_estimated_count": 0,
                            },
                        },
                    )
                )
                pending.task_done()
                continue

            estimated_count: int | None = None
            await wait_for_capacity()
            stats["reference_split_requests"] = int(stats.get("reference_split_requests", 0)) + 1
            try:
                response_payload = await openai_reference_split_request_async(
                    client,
                    markdown,
                    model=reference_splitting_model,
                )
                estimated_count = response_payload.get("estimated_reference_count")
                normalized_candidates = [normalize_reference_split_candidate(candidate) for candidate in response_payload.get("references") or []]
                normalized_candidates = [candidate for candidate in normalized_candidates if candidate is not None]
                if validate_reference_split_structured_candidates(markdown, normalized_candidates):
                    await completed.put(
                        (
                            index,
                            {
                                "id": abstract["id"],
                                "reference_candidates": normalized_candidates,
                                "diagnostics": {
                                    "reference_split_strategy": "llm",
                                    "reference_split_attempts": attempt,
                                    "reference_split_error": None,
                                    "reference_split_fallback_reason": None,
                                    "reference_split_candidate_count": len(normalized_candidates),
                                    "reference_split_estimated_count": estimated_count,
                                },
                            },
                        )
                    )
                else:
                    error_message = "Structured split failed lexical validation"
                    if attempt < split_max_requeues:
                        stats["reference_split_requeues"] = int(stats.get("reference_split_requeues", 0)) + 1
                        await pending.put((index, abstract, attempt + 1))
                    else:
                        await completed.put(
                            (
                                index,
                                {
                                    "id": abstract["id"],
                                    "reference_candidates": fallback_reference_candidates(markdown),
                                    "diagnostics": fallback_diagnostics(attempt, error_message, estimated_count, rate_limited=False),
                                },
                            )
                        )
            except Exception as exc:  # pragma: no cover - exercised via live runs
                error_message = str(exc)
                rate_limited = isinstance(exc, (RateLimitError, APIStatusError)) or is_rate_limit_error_message(error_message)
                if attempt < split_max_requeues:
                    stats["reference_split_requeues"] = int(stats.get("reference_split_requeues", 0)) + 1
                    if rate_limited:
                        stats["reference_split_rate_limit_requeues"] = int(stats.get("reference_split_rate_limit_requeues", 0)) + 1
                        await extend_backoff(rate_limit_retry_delay_seconds(exc, attempt))
                    await pending.put((index, abstract, attempt + 1))
                else:
                    await completed.put(
                        (
                            index,
                            {
                                "id": abstract["id"],
                                "reference_candidates": fallback_reference_candidates(markdown),
                                "diagnostics": fallback_diagnostics(attempt, error_message, estimated_count, rate_limited=rate_limited),
                            },
                        )
                    )
            finally:
                pending.task_done()

    for index, abstract in enumerate(abstracts):
        pending.put_nowait((index, abstract, 1))

    client = AsyncOpenAI(api_key=api_key, timeout=120.0)
    workers = [asyncio.create_task(worker(client)) for _ in range(max(1, split_concurrency))]
    completed_records: dict[int, dict[str, Any]] = {}
    try:
        while len(completed_records) < len(abstracts):
            index, result = await completed.get()
            completed_records[index] = build_abstract_reference_record(
                result["id"],
                result["reference_candidates"],
                reference_cache,
                result["diagnostics"],
            )
            if collect_checkpoint_every_abstracts > 0 and len(completed_records) % collect_checkpoint_every_abstracts == 0:
                ordered_records = [completed_records[idx] for idx in sorted(completed_records)]
                write_reference_metadata_snapshot(
                    output_path,
                    ordered_records,
                    reference_cache,
                    use_title_search=use_title_search,
                    request_counts=stats,
                    status="running",
                    phase="collect",
                )
                print(
                    json.dumps(
                        {
                            "phase": "collect",
                            "completed_abstracts": len(completed_records),
                            "reference_split_requests": stats.get("reference_split_requests", 0),
                            "reference_split_requeues": stats.get("reference_split_requeues", 0),
                            "reference_split_rate_limit_requeues": stats.get("reference_split_rate_limit_requeues", 0),
                        }
                    )
                )
    finally:
        await pending.join()
        for _ in workers:
            pending.put_nowait((-1, {}, 0))
        await asyncio.gather(*workers, return_exceptions=True)
        await client.close()

    return [completed_records[idx] for idx in sorted(completed_records)], reference_cache


def collect_reference_cache(
    abstracts_database: dict[str, Any],
    output_path: Path,
    *,
    use_title_search: bool = False,
    use_llm_reference_splitting: bool = False,
    reference_splitting_backend: str = DEFAULT_REFERENCE_SPLIT_BACKEND,
    reference_splitting_model: str = DEFAULT_REFERENCE_SPLIT_MODEL,
    env_path: str = ".env",
    openai_api_var: str = "OPENAI_API_KEY",
    request_counts: dict[str, int] | None = None,
    collect_checkpoint_every_abstracts: int = 25,
    split_concurrency: int = DEFAULT_REFERENCE_SPLIT_CONCURRENCY,
    split_max_requeues: int = DEFAULT_REFERENCE_SPLIT_MAX_REQUEUES,
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    if use_llm_reference_splitting and reference_splitting_backend == "openai" and split_concurrency > 1:
        return asyncio.run(
            collect_reference_cache_openai_async(
                abstracts_database,
                output_path,
                use_title_search=use_title_search,
                reference_splitting_model=reference_splitting_model,
                env_path=env_path,
                openai_api_var=openai_api_var,
                request_counts=request_counts,
                collect_checkpoint_every_abstracts=collect_checkpoint_every_abstracts,
                split_concurrency=split_concurrency,
                split_max_requeues=split_max_requeues,
            )
        )

    reference_cache = {
        key: normalize_cached_reference(value)
        for key, value in load_existing_reference_cache(output_path).items()
    }
    abstract_reference_records: list[dict[str, Any]] = []
    stats = request_counts if request_counts is not None else default_request_counts()

    for abstract in abstracts_database.get("abstracts", []):
        raw_reference_value = ""
        for response in abstract.get("responses", []):
            if response.get("question_name") == "References/Citations":
                raw_reference_value = response.get("value") or ""
                break

        markdown = html_to_markdown(raw_reference_value or "")
        if use_llm_reference_splitting and markdown.strip():
            stats["reference_split_requests"] = int(stats.get("reference_split_requests", 0)) + 1
            reference_candidates, split_diagnostics = split_reference_markdown(
                markdown,
                backend=reference_splitting_backend,
                model=reference_splitting_model,
                env_path=env_path,
                openai_api_var=openai_api_var,
            )
        else:
            heuristic_entries = extract_reference_entries_heuristic(raw_reference_value)
            reference_candidates = [normalize_reference_split_candidate(entry) for entry in heuristic_entries]
            reference_candidates = [candidate for candidate in reference_candidates if candidate is not None]
            split_diagnostics = {
                "reference_split_strategy": "heuristic",
                "reference_split_attempts": 0,
                "reference_split_error": None,
                "reference_split_fallback_reason": None,
                "reference_split_candidate_count": len(reference_candidates),
                "reference_split_estimated_count": None,
            }

        abstract_reference_records.append(
            build_abstract_reference_record(
                abstract["id"],
                reference_candidates,
                reference_cache,
                split_diagnostics,
            )
        )
        if collect_checkpoint_every_abstracts > 0 and len(abstract_reference_records) % collect_checkpoint_every_abstracts == 0:
            write_reference_metadata_snapshot(
                output_path,
                abstract_reference_records,
                reference_cache,
                use_title_search=use_title_search,
                request_counts=stats,
                status="running",
                phase="collect",
            )
            print(
                json.dumps(
                    {
                        "phase": "collect",
                        "completed_abstracts": len(abstract_reference_records),
                        "reference_split_requests": stats.get("reference_split_requests", 0),
                    }
                )
            )

    return abstract_reference_records, reference_cache


def build_reference_metadata_payload(
    abstract_reference_records: list[dict[str, Any]],
    reference_cache: dict[str, dict[str, Any]],
    *,
    use_title_search: bool,
    request_counts: dict[str, int] | None = None,
    status: str = "completed",
    phase: str = "completed",
) -> dict[str, Any]:
    abstracts_out: list[dict[str, Any]] = []
    for abstract in abstract_reference_records:
        abstract_references: list[dict[str, Any]] = []
        for reference in abstract["references"]:
            resolved = reference_cache[reference["reference_key"]]
            abstract_references.append(
                {
                    "reference_key": resolved["reference_key"],
                    "raw_text": reference["raw_text"],
                    "doi": resolved.get("doi"),
                    "pmid": resolved.get("pmid"),
                    "title_guess": resolved.get("title_guess"),
                    "matched": bool(resolved.get("matched")),
                    "match_method": resolved.get("match_method"),
                    "openalex_id": ((resolved.get("openalex") or {}).get("openalex_id")),
                }
            )
        abstracts_out.append(
            {
                "id": abstract["id"],
                "references": abstract_references,
                "reference_split_strategy": abstract.get("reference_split_strategy"),
                "reference_split_attempts": abstract.get("reference_split_attempts"),
                "reference_split_error": abstract.get("reference_split_error"),
                "reference_split_fallback_reason": abstract.get("reference_split_fallback_reason"),
                "reference_split_candidate_count": abstract.get("reference_split_candidate_count"),
                "reference_split_estimated_count": abstract.get("reference_split_estimated_count"),
            }
        )

    references = sorted(reference_cache.values(), key=lambda item: item["reference_key"])
    matched_count = sum(1 for reference in references if reference.get("matched"))
    doi_completed = sum(1 for reference in references if reference.get("doi_lookup_completed"))
    doi_discovery_completed = sum(1 for reference in references if reference.get("doi_discovery_completed"))
    pmid_completed = sum(1 for reference in references if reference.get("pmid_lookup_completed"))
    title_completed = sum(1 for reference in references if reference.get("title_lookup_completed"))
    return {
        "built_at": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "phase": phase,
        "abstract_count": len(abstracts_out),
        "unique_reference_count": len(references),
        "matched_reference_count": matched_count,
        "unmatched_reference_count": len(references) - matched_count,
        "use_title_search": use_title_search,
        "request_counts": request_counts or default_request_counts(),
        "progress": {
            "doi_lookup_completed_count": doi_completed,
            "doi_discovery_completed_count": doi_discovery_completed,
            "pmid_lookup_completed_count": pmid_completed,
            "title_lookup_completed_count": title_completed,
        },
        "abstracts": abstracts_out,
        "references": references,
    }


def write_reference_metadata_snapshot(
    output_path: Path,
    abstract_reference_records: list[dict[str, Any]],
    reference_cache: dict[str, dict[str, Any]],
    *,
    use_title_search: bool,
    request_counts: dict[str, int],
    status: str,
    phase: str,
) -> None:
    write_json(
        output_path,
        build_reference_metadata_payload(
            abstract_reference_records,
            reference_cache,
            use_title_search=use_title_search,
            request_counts=request_counts,
            status=status,
            phase=phase,
        ),
    )


def reference_split_needs_repair(abstract: dict[str, Any]) -> bool:
    if abstract.get("reference_split_strategy") != "llm":
        return True
    if abstract.get("reference_split_fallback_reason") or abstract.get("reference_split_error"):
        return True
    estimated_count = abstract.get("reference_split_estimated_count")
    candidate_count = abstract.get("reference_split_candidate_count")
    if isinstance(estimated_count, int) and isinstance(candidate_count, int) and estimated_count > candidate_count:
        return True
    return False


def failed_reference_split_ids(reference_metadata_payload: dict[str, Any]) -> list[int]:
    return [
        int(abstract["id"])
        for abstract in reference_metadata_payload.get("abstracts", [])
        if isinstance(abstract.get("id"), int) and reference_split_needs_repair(abstract)
    ]


def refresh_reference_source_counts(
    abstracts_out: list[dict[str, Any]],
    references_by_key: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    for reference in references_by_key.values():
        reference["source_count"] = 0
        reference["raw_text_examples"] = []

    referenced_keys: set[str] = set()
    for abstract in abstracts_out:
        for reference in abstract.get("references", []):
            reference_key = reference.get("reference_key")
            if not isinstance(reference_key, str):
                continue
            referenced_keys.add(reference_key)
            resolved = references_by_key.get(reference_key)
            if resolved is None:
                resolved = normalize_cached_reference(
                    {
                        "reference_key": reference_key,
                        "raw_text": reference.get("raw_text") or "",
                        "doi": reference.get("doi"),
                        "pmid": reference.get("pmid"),
                        "title_guess": reference.get("title_guess"),
                        "matched": bool(reference.get("matched")),
                        "match_method": reference.get("match_method") or "pending",
                        "openalex": None,
                    }
                )
                references_by_key[reference_key] = resolved
            resolved["source_count"] = int(resolved.get("source_count", 0)) + 1
            raw_text = normalize_reference_text(str(reference.get("raw_text") or ""))
            examples = list(resolved.get("raw_text_examples", []))
            if raw_text and raw_text not in examples and len(examples) < 3:
                examples.append(raw_text)
            resolved["raw_text_examples"] = examples

    return {
        key: value
        for key, value in references_by_key.items()
        if key in referenced_keys
    }


def merge_reference_metadata_payloads(
    existing_payload: dict[str, Any],
    repaired_payload: dict[str, Any],
) -> dict[str, Any]:
    repaired_abstracts = {
        int(abstract["id"]): abstract
        for abstract in repaired_payload.get("abstracts", [])
        if isinstance(abstract.get("id"), int)
    }
    merged_abstracts: list[dict[str, Any]] = []
    seen_ids: set[int] = set()
    for abstract in existing_payload.get("abstracts", []):
        abstract_id = abstract.get("id")
        if isinstance(abstract_id, int) and abstract_id in repaired_abstracts:
            merged_abstracts.append(repaired_abstracts[abstract_id])
            seen_ids.add(abstract_id)
        else:
            merged_abstracts.append(abstract)
            if isinstance(abstract_id, int):
                seen_ids.add(abstract_id)
    for abstract_id, abstract in repaired_abstracts.items():
        if abstract_id not in seen_ids:
            merged_abstracts.append(abstract)

    references_by_key = {
        reference["reference_key"]: normalize_cached_reference(reference)
        for reference in existing_payload.get("references", [])
        if isinstance(reference.get("reference_key"), str)
    }
    for reference in repaired_payload.get("references", []):
        reference_key = reference.get("reference_key")
        if isinstance(reference_key, str):
            references_by_key[reference_key] = normalize_cached_reference(reference)
    references_by_key = refresh_reference_source_counts(merged_abstracts, references_by_key)
    request_counts = default_request_counts()
    request_counts.update(existing_payload.get("request_counts") or {})
    request_counts.update(repaired_payload.get("request_counts") or {})
    use_title_search = bool(repaired_payload.get("use_title_search", existing_payload.get("use_title_search", False)))
    return build_reference_metadata_payload(
        merged_abstracts,
        references_by_key,
        use_title_search=use_title_search,
        request_counts=request_counts,
        status="completed",
        phase="completed",
    )


def repair_failed_reference_splits(
    abstracts_database: dict[str, Any],
    existing_payload: dict[str, Any],
    *,
    output_path: Path,
    use_llm_reference_splitting: bool = True,
    reference_splitting_backend: str = DEFAULT_REFERENCE_SPLIT_BACKEND,
    reference_splitting_model: str = DEFAULT_REFERENCE_SPLIT_MODEL,
    env_path: str = ".env",
    openai_api_var: str = "OPENAI_API_KEY",
    use_doi_discovery: bool = True,
    use_title_search: bool = False,
    doi_discovery_similarity_threshold: float = 0.8,
    title_similarity_threshold: float = 0.75,
    delay_seconds: float = 1.05,
    exact_batch_size: int = 50,
    checkpoint_every_batches: int = 5,
    collect_checkpoint_every_abstracts: int = 25,
    split_concurrency: int = DEFAULT_REFERENCE_SPLIT_CONCURRENCY,
    split_max_requeues: int = DEFAULT_REFERENCE_SPLIT_MAX_REQUEUES,
    title_concurrency: int = DEFAULT_OPENALEX_TITLE_CONCURRENCY,
    title_max_rps: float = DEFAULT_OPENALEX_TITLE_MAX_RPS,
) -> dict[str, Any]:
    target_ids = set(failed_reference_split_ids(existing_payload))
    if not target_ids:
        return existing_payload
    subset_database = {
        "abstracts": [
            abstract
            for abstract in abstracts_database.get("abstracts", [])
            if abstract.get("id") in target_ids
        ]
    }
    with TemporaryDirectory() as temp_dir:
        temp_output_path = Path(temp_dir) / "reference_metadata.repair.json"
        repaired_payload = build_reference_metadata_database(
            subset_database,
            output_path=temp_output_path,
            use_llm_reference_splitting=use_llm_reference_splitting,
            reference_splitting_backend=reference_splitting_backend,
            reference_splitting_model=reference_splitting_model,
            env_path=env_path,
            openai_api_var=openai_api_var,
            use_doi_discovery=use_doi_discovery,
            use_title_search=use_title_search,
            doi_discovery_similarity_threshold=doi_discovery_similarity_threshold,
            title_similarity_threshold=title_similarity_threshold,
            delay_seconds=delay_seconds,
            exact_batch_size=exact_batch_size,
            checkpoint_every_batches=checkpoint_every_batches,
            collect_checkpoint_every_abstracts=collect_checkpoint_every_abstracts,
            split_concurrency=split_concurrency,
            split_max_requeues=split_max_requeues,
            title_concurrency=title_concurrency,
            title_max_rps=title_max_rps,
        )
    merged_payload = merge_reference_metadata_payloads(existing_payload, repaired_payload)
    write_json(output_path, merged_payload)
    return merged_payload


def resolve_reference_cache_doi_discovery(
    abstract_reference_records: list[dict[str, Any]],
    reference_cache: dict[str, dict[str, Any]],
    *,
    output_path: Path,
    use_title_search: bool,
    doi_discovery_similarity_threshold: float = 0.8,
    delay_seconds: float = 0.0,
    request_counts: dict[str, int] | None = None,
) -> dict[str, int]:
    stats = default_request_counts()
    stats.update(request_counts or {})
    stats.setdefault("semantic_scholar_errors", 0)

    for reference in reference_cache.values():
        if reference.get("matched"):
            reference["doi_discovery_completed"] = True
            continue
        if reference.get("doi"):
            reference["doi_discovery_completed"] = True
            continue
        if reference.get("title_guess"):
            reference["doi_discovery_completed"] = True
            continue
        if reference.get("doi_discovery_completed"):
            continue
        raw_text = str(reference.get("raw_text") or "").strip()
        if not raw_text:
            reference["doi_discovery_completed"] = True
            continue

        discovered_doi: str | None = None
        discovery_source: str | None = None
        discovery_score: float | None = None
        reference_year = reference.get("reference_year")

        stats["semantic_scholar_requests"] += 1
        try:
            discovered_doi, discovery_score = search_semantic_scholar_doi_by_reference(
                raw_text,
                min_similarity=doi_discovery_similarity_threshold,
                reference_year=reference_year if isinstance(reference_year, int) else None,
            )
        except OpenAlexError as exc:
            stats["semantic_scholar_errors"] = int(stats.get("semantic_scholar_errors", 0)) + 1
            reference["last_error"] = str(exc)
        else:
            if discovered_doi:
                discovery_source = "semantic_scholar"
                reference.pop("last_error", None)

        if discovered_doi:
            reference["doi"] = discovered_doi
            reference["doi_discovery_source"] = discovery_source
            reference["doi_discovery_title_score"] = discovery_score
            stats["doi_requests"] += 1
            work = fetch_openalex_work_by_doi(discovered_doi)
            reference["doi_lookup_completed"] = True
            if work is not None:
                reference["matched"] = True
                reference["match_method"] = f"{discovery_source}_doi"
                reference["openalex"] = normalize_openalex_work(work)
                reference["pmid_lookup_completed"] = True
            elif reference.get("pmid_lookup_completed"):
                reference["match_method"] = "unmatched"
        reference["doi_discovery_completed"] = True

        if delay_seconds:
            time.sleep(delay_seconds)
        completed = stats["semantic_scholar_requests"]
        if completed % 50 == 0:
            write_reference_metadata_snapshot(
                output_path,
                abstract_reference_records,
                reference_cache,
                use_title_search=use_title_search,
                request_counts=stats,
                status="running",
                phase="doi-discovery",
            )
            print(
                json.dumps(
                    {
                        "phase": "doi-discovery",
                        "semantic_scholar_requests": stats["semantic_scholar_requests"],
                    }
                )
            )

    return stats


def resolve_reference_cache_exact_matches(
    abstract_reference_records: list[dict[str, Any]],
    reference_cache: dict[str, dict[str, Any]],
    *,
    output_path: Path,
    use_title_search: bool,
    exact_batch_size: int = 50,
    request_counts: dict[str, int] | None = None,
    checkpoint_every_batches: int = 5,
) -> dict[str, int]:
    stats = default_request_counts()
    stats.update(request_counts or {})

    for reference in reference_cache.values():
        if not reference.get("doi"):
            reference["doi_lookup_completed"] = True
        if not reference.get("pmid"):
            reference["pmid_lookup_completed"] = True
        if reference.get("matched") and reference.get("match_method") == "doi":
            reference["doi_lookup_completed"] = True
            reference["pmid_lookup_completed"] = True
        if reference.get("matched") and reference.get("match_method") == "pmid":
            reference["pmid_lookup_completed"] = True
        if reference.get("doi_lookup_completed") and reference.get("pmid_lookup_completed") and not reference.get("matched"):
            reference["match_method"] = "unmatched"

    doi_pending = sorted(
        {
            str(reference["doi"])
            for reference in reference_cache.values()
            if reference.get("doi")
            and not reference.get("doi_lookup_completed")
        }
    )
    doi_batches = chunked_values(doi_pending, exact_batch_size)
    for batch_index, doi_batch in enumerate(doi_batches, start=1):
        matched_by_doi = fetch_openalex_works_by_field("doi", doi_batch)
        stats["doi_requests"] += 1
        for reference in reference_cache.values():
            doi = reference.get("doi")
            if not doi or doi not in doi_batch or reference.get("doi_lookup_completed"):
                continue
            reference["doi_lookup_completed"] = True
            work = matched_by_doi.get(str(doi))
            if work is not None:
                reference["matched"] = True
                reference["match_method"] = "doi"
                reference["openalex"] = normalize_openalex_work(work)
                reference["pmid_lookup_completed"] = True
            elif reference.get("pmid_lookup_completed"):
                reference["match_method"] = "unmatched"
        if batch_index % checkpoint_every_batches == 0:
            write_reference_metadata_snapshot(
                output_path,
                abstract_reference_records,
                reference_cache,
                use_title_search=use_title_search,
                request_counts=stats,
                status="running",
                phase="exact",
            )
            print(
                json.dumps(
                    {
                        "phase": "exact",
                        "doi_requests": stats["doi_requests"],
                        "pmid_requests": stats["pmid_requests"],
                        "completed_batches": batch_index,
                        "total_batches": len(doi_batches),
                    }
                )
            )

    pmid_pending = sorted(
        {
            str(reference["pmid"])
            for reference in reference_cache.values()
            if reference.get("pmid")
            and not reference.get("pmid_lookup_completed")
        }
    )
    pmid_batches = chunked_values(pmid_pending, exact_batch_size)
    for batch_index, pmid_batch in enumerate(pmid_batches, start=1):
        matched_by_pmid = fetch_openalex_works_by_field("pmid", pmid_batch)
        stats["pmid_requests"] += 1
        for reference in reference_cache.values():
            pmid = reference.get("pmid")
            if not pmid or pmid not in pmid_batch or reference.get("pmid_lookup_completed"):
                continue
            reference["pmid_lookup_completed"] = True
            work = matched_by_pmid.get(str(pmid))
            if work is not None:
                reference["matched"] = True
                reference["match_method"] = "pmid"
                reference["openalex"] = normalize_openalex_work(work)
            elif reference.get("doi_lookup_completed"):
                reference["match_method"] = "unmatched"
        if batch_index % checkpoint_every_batches == 0:
            write_reference_metadata_snapshot(
                output_path,
                abstract_reference_records,
                reference_cache,
                use_title_search=use_title_search,
                request_counts=stats,
                status="running",
                phase="exact",
            )
            print(
                json.dumps(
                    {
                        "phase": "exact",
                        "doi_requests": stats["doi_requests"],
                        "pmid_requests": stats["pmid_requests"],
                        "completed_batches": batch_index,
                        "total_batches": len(pmid_batches),
                    }
                )
            )

    for reference in reference_cache.values():
        if reference.get("doi_lookup_completed") and reference.get("pmid_lookup_completed") and not reference.get("matched"):
            reference["match_method"] = "unmatched"

    return stats


def resolve_reference_cache_title_matches(
    abstract_reference_records: list[dict[str, Any]],
    reference_cache: dict[str, dict[str, Any]],
    *,
    output_path: Path,
    use_title_search: bool,
    title_similarity_threshold: float = 0.75,
    delay_seconds: float = 0.0,
    request_counts: dict[str, int] | None = None,
    title_concurrency: int = DEFAULT_OPENALEX_TITLE_CONCURRENCY,
    title_max_rps: float = DEFAULT_OPENALEX_TITLE_MAX_RPS,
) -> dict[str, int]:
    if title_concurrency > 1:
        return asyncio.run(
            resolve_reference_cache_title_matches_async(
                abstract_reference_records,
                reference_cache,
                output_path=output_path,
                use_title_search=use_title_search,
                title_similarity_threshold=title_similarity_threshold,
                delay_seconds=delay_seconds,
                request_counts=request_counts,
                title_concurrency=title_concurrency,
                title_max_rps=title_max_rps,
            )
        )
    stats = default_request_counts()
    stats.update(request_counts or {})
    stats.setdefault("title_errors", 0)
    for reference in reference_cache.values():
        if reference.get("title_lookup_completed"):
            continue
        if reference.get("matched") or not reference.get("title_guess"):
            reference["title_lookup_completed"] = True
            continue
        stats["title_requests"] += 1
        try:
            work = search_openalex_work_by_title(
                str(reference["title_guess"]),
                min_similarity=title_similarity_threshold,
            )
        except OpenAlexError as exc:
            stats["title_errors"] = int(stats.get("title_errors", 0)) + 1
            reference["last_error"] = str(exc)
            if delay_seconds:
                time.sleep(delay_seconds)
            if stats["title_requests"] % 50 == 0 or stats["title_errors"] % 10 == 0:
                write_reference_metadata_snapshot(
                    output_path,
                    abstract_reference_records,
                    reference_cache,
                    use_title_search=use_title_search,
                    request_counts=stats,
                    status="running",
                    phase="title",
                )
                print(
                    json.dumps(
                        {
                            "phase": "title",
                            "title_requests": stats["title_requests"],
                            "title_errors": stats["title_errors"],
                        }
                    )
                )
            continue
        if work is not None:
            reference["matched"] = True
            reference["match_method"] = "title"
            reference["openalex"] = normalize_openalex_work(work)
            reference.pop("last_error", None)
        elif reference.get("match_method") == "pending":
            reference["match_method"] = "unmatched"
        reference["title_lookup_completed"] = True
        if delay_seconds:
            time.sleep(delay_seconds)
        if stats["title_requests"] % 50 == 0:
            write_reference_metadata_snapshot(
                output_path,
                abstract_reference_records,
                reference_cache,
                use_title_search=use_title_search,
                request_counts=stats,
                status="running",
                phase="title",
            )
            print(
                json.dumps(
                    {
                        "phase": "title",
                        "title_requests": stats["title_requests"],
                        "title_errors": stats.get("title_errors", 0),
                    }
                )
            )
    return stats


async def resolve_reference_cache_title_matches_async(
    abstract_reference_records: list[dict[str, Any]],
    reference_cache: dict[str, dict[str, Any]],
    *,
    output_path: Path,
    use_title_search: bool,
    title_similarity_threshold: float = 0.75,
    delay_seconds: float = 0.0,
    request_counts: dict[str, int] | None = None,
    title_concurrency: int = DEFAULT_OPENALEX_TITLE_CONCURRENCY,
    title_max_rps: float = DEFAULT_OPENALEX_TITLE_MAX_RPS,
) -> dict[str, int]:
    stats = default_request_counts()
    stats.update(request_counts or {})
    stats.setdefault("title_errors", 0)
    stats.setdefault("openalex_budget_exhausted", 0)
    candidates = [
        reference
        for reference in reference_cache.values()
        if not reference.get("title_lookup_completed")
        and not reference.get("matched")
        and reference.get("title_guess")
    ]
    skipped = [
        reference
        for reference in reference_cache.values()
        if not reference.get("title_lookup_completed")
        and (reference.get("matched") or not reference.get("title_guess"))
    ]
    for reference in skipped:
        reference["title_lookup_completed"] = True

    try:
        rate_limit_payload = await asyncio.to_thread(fetch_openalex_rate_limit_status)
        if isinstance(rate_limit_payload, dict):
            for key in (
                "limit",
                "interval",
                "requests_limit",
                "requests_remaining",
                "daily_limit_usd",
                "daily_remaining_usd",
                "prepaid_remaining_usd",
            ):
                if key in rate_limit_payload:
                    stats[f"openalex_{key}"] = rate_limit_payload.get(key)
    except OpenAlexError:
        pass

    request_times: deque[float] = deque()
    limiter_lock = asyncio.Lock()
    stop_event = asyncio.Event()

    async def acquire_request_slot() -> None:
        if title_max_rps <= 0:
            return
        while True:
            async with limiter_lock:
                now = asyncio.get_running_loop().time()
                while request_times and now - request_times[0] >= 1.0:
                    request_times.popleft()
                if len(request_times) < max(1, int(title_max_rps)):
                    request_times.append(now)
                    return
                wait_seconds = max(0.01, 1.0 - (now - request_times[0]))
            await asyncio.sleep(wait_seconds)

    pending: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()
    completed_count = 0
    for reference in candidates:
        pending.put_nowait(reference)

    async def worker() -> None:
        nonlocal completed_count
        while True:
            reference = await pending.get()
            if reference is None:
                pending.task_done()
                return
            if stop_event.is_set():
                pending.task_done()
                continue
            await acquire_request_slot()
            stats["title_requests"] += 1
            try:
                work, _headers = await asyncio.to_thread(
                    search_openalex_work_by_title_with_headers,
                    str(reference["title_guess"]),
                    title_similarity_threshold,
                )
            except OpenAlexError as exc:
                stats["title_errors"] = int(stats.get("title_errors", 0)) + 1
                reference["last_error"] = str(exc)
                if "Insufficient budget" in str(exc) or "HTTP 429" in str(exc):
                    stats["openalex_budget_exhausted"] = 1
                    stop_event.set()
            else:
                if work is not None:
                    reference["matched"] = True
                    reference["match_method"] = "title"
                    reference["openalex"] = normalize_openalex_work(work)
                    reference.pop("last_error", None)
                elif reference.get("match_method") == "pending":
                    reference["match_method"] = "unmatched"
                reference["title_lookup_completed"] = True
                completed_count += 1
                if completed_count % 50 == 0:
                    write_reference_metadata_snapshot(
                        output_path,
                        abstract_reference_records,
                        reference_cache,
                        use_title_search=use_title_search,
                        request_counts=stats,
                        status="running",
                        phase="title",
                    )
                    print(
                        json.dumps(
                            {
                                "phase": "title",
                                "title_requests": stats["title_requests"],
                                "title_errors": stats.get("title_errors", 0),
                                "title_completed": completed_count,
                            }
                        )
                    )
            finally:
                pending.task_done()

    workers = [asyncio.create_task(worker()) for _ in range(max(1, title_concurrency))]
    try:
        await pending.join()
    finally:
        for _ in workers:
            pending.put_nowait(None)
        await asyncio.gather(*workers, return_exceptions=True)
    return stats


def build_reference_metadata_database(
    abstracts_database: dict[str, Any],
    *,
    output_path: Path,
    use_llm_reference_splitting: bool = True,
    reference_splitting_backend: str = DEFAULT_REFERENCE_SPLIT_BACKEND,
    reference_splitting_model: str = DEFAULT_REFERENCE_SPLIT_MODEL,
    env_path: str = ".env",
    openai_api_var: str = "OPENAI_API_KEY",
    use_doi_discovery: bool = True,
    use_title_search: bool = False,
    doi_discovery_similarity_threshold: float = 0.8,
    title_similarity_threshold: float = 0.75,
    delay_seconds: float = 1.05,
    exact_batch_size: int = 50,
    checkpoint_every_batches: int = 5,
    collect_checkpoint_every_abstracts: int = 25,
    split_concurrency: int = DEFAULT_REFERENCE_SPLIT_CONCURRENCY,
    split_max_requeues: int = DEFAULT_REFERENCE_SPLIT_MAX_REQUEUES,
    title_concurrency: int = DEFAULT_OPENALEX_TITLE_CONCURRENCY,
    title_max_rps: float = DEFAULT_OPENALEX_TITLE_MAX_RPS,
) -> dict[str, Any]:
    effective_use_title_search = True
    request_counts = default_request_counts()
    abstract_reference_records, reference_cache = collect_reference_cache(
        abstracts_database,
        output_path,
        use_title_search=effective_use_title_search,
        use_llm_reference_splitting=use_llm_reference_splitting,
        reference_splitting_backend=reference_splitting_backend,
        reference_splitting_model=reference_splitting_model,
        env_path=env_path,
        openai_api_var=openai_api_var,
        request_counts=request_counts,
        collect_checkpoint_every_abstracts=collect_checkpoint_every_abstracts,
        split_concurrency=split_concurrency,
        split_max_requeues=split_max_requeues,
    )
    write_reference_metadata_snapshot(
        output_path,
        abstract_reference_records,
        reference_cache,
        use_title_search=effective_use_title_search,
        request_counts=request_counts,
        status="running",
        phase="collect",
    )
    request_counts = resolve_reference_cache_exact_matches(
        abstract_reference_records,
        reference_cache,
        output_path=output_path,
        use_title_search=effective_use_title_search,
        exact_batch_size=exact_batch_size,
        request_counts=request_counts,
        checkpoint_every_batches=checkpoint_every_batches,
    )
    request_counts.setdefault("title_errors", 0)
    request_counts = resolve_reference_cache_title_matches(
        abstract_reference_records,
        reference_cache,
        output_path=output_path,
        use_title_search=effective_use_title_search,
        title_similarity_threshold=title_similarity_threshold,
        delay_seconds=delay_seconds,
        request_counts=request_counts,
        title_concurrency=title_concurrency,
        title_max_rps=title_max_rps,
    )
    if use_doi_discovery:
        request_counts = resolve_reference_cache_doi_discovery(
            abstract_reference_records,
            reference_cache,
            output_path=output_path,
            use_title_search=effective_use_title_search,
            doi_discovery_similarity_threshold=doi_discovery_similarity_threshold,
            delay_seconds=delay_seconds,
            request_counts=request_counts,
        )

    return build_reference_metadata_payload(
        abstract_reference_records,
        reference_cache,
        use_title_search=effective_use_title_search,
        request_counts=request_counts,
        status="completed",
        phase="completed",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Resolve abstract references against OpenAlex and persist citation metadata")
    parser.add_argument("--input", default="data/abstracts.json")
    parser.add_argument("--output", default="data/reference_metadata.json")
    parser.add_argument("--repair-failed-splits-from")
    parser.add_argument("--env-file", default=".env")
    parser.add_argument("--openai-api-var", default="OPENAI_API_KEY")
    parser.add_argument("--no-llm-reference-splitting", action="store_true")
    parser.add_argument("--reference-splitting-backend", choices=["ollama", "openai"], default=DEFAULT_REFERENCE_SPLIT_BACKEND)
    parser.add_argument("--reference-splitting-model", default=DEFAULT_REFERENCE_SPLIT_MODEL)
    parser.add_argument("--exact-batch-size", type=int, default=50)
    parser.add_argument("--checkpoint-every-batches", type=int, default=5)
    parser.add_argument("--collect-checkpoint-every-abstracts", type=int, default=25)
    parser.add_argument("--split-concurrency", type=int, default=DEFAULT_REFERENCE_SPLIT_CONCURRENCY)
    parser.add_argument("--split-max-requeues", type=int, default=DEFAULT_REFERENCE_SPLIT_MAX_REQUEUES)
    parser.add_argument("--title-concurrency", type=int, default=DEFAULT_OPENALEX_TITLE_CONCURRENCY)
    parser.add_argument("--title-max-rps", type=float, default=DEFAULT_OPENALEX_TITLE_MAX_RPS)
    parser.add_argument("--no-doi-discovery", action="store_true")
    parser.add_argument("--doi-discovery-similarity-threshold", type=float, default=0.8)
    parser.add_argument("--use-title-search", action="store_true")
    parser.add_argument("--title-similarity-threshold", type=float, default=0.75)
    parser.add_argument("--delay-seconds", type=float, default=1.05)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    database = load_json(Path(args.input))
    output_path = Path(args.output)
    if args.repair_failed_splits_from:
        existing_payload = load_json(Path(args.repair_failed_splits_from))
        result = repair_failed_reference_splits(
            database,
            existing_payload,
            output_path=output_path,
            use_llm_reference_splitting=not args.no_llm_reference_splitting,
            reference_splitting_backend=args.reference_splitting_backend,
            reference_splitting_model=args.reference_splitting_model,
            env_path=args.env_file,
            openai_api_var=args.openai_api_var,
            use_doi_discovery=not args.no_doi_discovery,
            use_title_search=args.use_title_search,
            doi_discovery_similarity_threshold=args.doi_discovery_similarity_threshold,
            title_similarity_threshold=args.title_similarity_threshold,
            delay_seconds=args.delay_seconds,
            exact_batch_size=args.exact_batch_size,
            checkpoint_every_batches=args.checkpoint_every_batches,
            collect_checkpoint_every_abstracts=args.collect_checkpoint_every_abstracts,
            split_concurrency=args.split_concurrency,
            split_max_requeues=args.split_max_requeues,
            title_concurrency=args.title_concurrency,
            title_max_rps=args.title_max_rps,
        )
    else:
        result = build_reference_metadata_database(
            database,
            output_path=output_path,
            use_llm_reference_splitting=not args.no_llm_reference_splitting,
            reference_splitting_backend=args.reference_splitting_backend,
            reference_splitting_model=args.reference_splitting_model,
            env_path=args.env_file,
            openai_api_var=args.openai_api_var,
            use_doi_discovery=not args.no_doi_discovery,
            use_title_search=args.use_title_search,
            doi_discovery_similarity_threshold=args.doi_discovery_similarity_threshold,
            title_similarity_threshold=args.title_similarity_threshold,
            delay_seconds=args.delay_seconds,
            exact_batch_size=args.exact_batch_size,
            checkpoint_every_batches=args.checkpoint_every_batches,
            collect_checkpoint_every_abstracts=args.collect_checkpoint_every_abstracts,
            split_concurrency=args.split_concurrency,
            split_max_requeues=args.split_max_requeues,
            title_concurrency=args.title_concurrency,
            title_max_rps=args.title_max_rps,
        )
    write_json(output_path, result)
    print(
        json.dumps(
            {
                "input": args.input,
                "output": args.output,
                "repair_failed_split_count": len(failed_reference_split_ids(result)),
                "abstract_count": result["abstract_count"],
                "unique_reference_count": result["unique_reference_count"],
                "matched_reference_count": result["matched_reference_count"],
                "unmatched_reference_count": result["unmatched_reference_count"],
                "use_llm_reference_splitting": not args.no_llm_reference_splitting,
                "reference_splitting_backend": args.reference_splitting_backend,
                "reference_splitting_model": args.reference_splitting_model,
                "split_concurrency": args.split_concurrency,
                "split_max_requeues": args.split_max_requeues,
                "title_concurrency": args.title_concurrency,
                "title_max_rps": args.title_max_rps,
                "use_doi_discovery": not args.no_doi_discovery,
                "use_title_search": args.use_title_search,
                "request_counts": result["request_counts"],
            },
            indent=2,
        )
    )
    return 0
