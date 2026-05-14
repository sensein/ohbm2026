from __future__ import annotations

import json
import os
import re
import time
from html import unescape
from http.client import InvalidURL
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

GRAPHQL_ENDPOINT = "https://app.oxfordabstracts.com/v1/graphql"
DEFAULT_TIMEOUT_START_SECONDS = 0.1
DEFAULT_TIMEOUT_LIMIT_SECONDS = 10.0

ABSTRACT_IDS_QUERY = """
query abstract_ids {
  events {
    id
  }
  submissions(
    where: {complete: {_eq: true}, accepted_for: {value: {_is_null: false}}}
  ) {
    id
  }
}
"""

# Withdrawn submissions: distinct corpus, distinct query body, distinct
# state-key namespace. The downstream pipeline keeps these in a separate
# file (`data/primary/abstracts_withdrawn.json`) and never mixes them
# with accepted. Empirically (2026-05-13 probe) the 89 abstracts that
# were Accepted at the March snapshot but are no longer in the live
# Accepted set are all `decision_status: Withdrawn`, with `complete=true`
# and `archived=false`. Their `accepted_for.value` is null (which is why
# the existing accepted-only filter correctly excludes them).
WITHDRAWN_IDS_QUERY = """
query withdrawn_ids {
  events {
    id
  }
  submissions(
    where: {complete: {_eq: true}, decision_status: {_eq: "Withdrawn"}, archived: {_eq: false}}
  ) {
    id
  }
}
"""

ABSTRACT_CONTENTS_QUERY = """
query abstract_contents($submission_ids: [Int!]!) {
  events {
    id
  }
  submissions(where: {id: {_in: $submission_ids}}) {
    id
    program_code
    title {
      value
    }
    accepted_for {
      value
    }
    authors {
      author_order
      id
    }
    responses {
      question {
        question_name
      }
      value
    }
    program_sessions_submissions {
      start_time
      end_time
      display_order
      program_session {
        id
        name
        start_time
        end_time
        program_date {
          program_date
        }
        program_location {
          name
        }
        program_type {
          name
        }
        program_track {
          name
        }
      }
    }
  }
}
"""

# Canonical GraphQL introspection query (graphql-spec). Persisted
# alongside the corpus snapshot so Stage 1 can detect upstream schema
# drift on every run. The query is a standard protocol contract, not a
# project-specific assumption — Principle VII applies to the data we
# fetch, not the introspection protocol itself.
INTROSPECTION_QUERY = """
query IntrospectionQuery {
  __schema {
    queryType { name }
    types {
      kind
      name
      description
      fields(includeDeprecated: true) {
        name
        description
        type {
          kind
          name
          ofType {
            kind
            name
            ofType {
              kind
              name
              ofType {
                kind
                name
              }
            }
          }
        }
        args {
          name
          type {
            kind
            name
            ofType {
              kind
              name
              ofType {
                kind
                name
              }
            }
          }
        }
      }
    }
  }
}
"""

AUTHOR_QUERY = """
query authors_by_ids($ids: [Int!]!) {
  authors(where: {id: {_in: $ids}}) {
    id
    first_name
    middle_initial
    last_name
    title
    degree
    email
    orcid_id
    presenting
    submission_id
    affiliations {
      id
      affiliation_order
      institution
      city
      state
      country
    }
  }
}
"""


class GraphQLAPIError(RuntimeError):
    """Raised when a GraphQL or related network request cannot continue."""


def load_dotenv(path: Path) -> dict[str, str]:
    env: dict[str, str] = {}
    if not path.exists():
        return env

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        env[key.strip()] = value.strip().strip("'").strip('"')
    return env


def get_api_key(env_path: Path, env_var: str) -> str:
    env_values = load_dotenv(env_path)
    api_key = os.environ.get(env_var) or env_values.get(env_var)
    if not api_key:
        raise GraphQLAPIError(f"Missing required API key: {env_var}")
    return api_key


def timeout_sequence(
    start_seconds: float = DEFAULT_TIMEOUT_START_SECONDS,
    limit_seconds: float = DEFAULT_TIMEOUT_LIMIT_SECONDS,
) -> list[float]:
    timeout = start_seconds
    timeouts: list[float] = []
    while timeout < limit_seconds:
        timeouts.append(timeout)
        timeout *= 2
    timeouts.append(limit_seconds)
    return timeouts


def urlopen_with_retries(
    request: Request,
    timeout_start: float = DEFAULT_TIMEOUT_START_SECONDS,
    timeout_limit: float = DEFAULT_TIMEOUT_LIMIT_SECONDS,
):
    last_error: Exception | None = None
    for timeout in timeout_sequence(timeout_start, timeout_limit):
        try:
            return urlopen(request, timeout=timeout)
        except HTTPError as exc:
            if exc.code in {408, 425, 429, 500, 502, 503, 504} and timeout < timeout_limit:
                last_error = exc
                time.sleep(min(timeout, 1.0))
                continue
            raise
        except (TimeoutError, URLError, OSError) as exc:
            last_error = exc
            if timeout >= timeout_limit:
                break
            time.sleep(min(timeout, 1.0))

    if last_error is None:
        raise GraphQLAPIError("Request failed without a captured error")
    raise last_error


def graphql_request(
    api_key: str,
    query: str,
    operation_name: str,
    variables: dict[str, Any] | None = None,
    timeout_start: float = DEFAULT_TIMEOUT_START_SECONDS,
    timeout_limit: float = DEFAULT_TIMEOUT_LIMIT_SECONDS,
) -> dict[str, Any]:
    payload = json.dumps(
        {"query": query, "variables": variables, "operationName": operation_name}
    ).encode("utf-8")
    request = Request(
        GRAPHQL_ENDPOINT,
        data=payload,
        headers={"content-type": "application/json", "x-api-key": api_key},
        method="POST",
    )

    try:
        with urlopen_with_retries(
            request,
            timeout_start=timeout_start,
            timeout_limit=timeout_limit,
        ) as response:
            raw = response.read().decode("utf-8")
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise GraphQLAPIError(f"GraphQL request failed with HTTP {exc.code}: {body}") from exc
    except (URLError, OSError, TimeoutError, InvalidURL, ValueError) as exc:
        reason = getattr(exc, "reason", str(exc))
        raise GraphQLAPIError(f"GraphQL request failed: {reason}") from exc

    parsed = json.loads(raw)
    if parsed.get("errors"):
        raise GraphQLAPIError(f"GraphQL errors: {parsed['errors']}")
    return parsed["data"]


def chunked(values: list[int], chunk_size: int) -> list[list[int]]:
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")
    return [values[index : index + chunk_size] for index in range(0, len(values), chunk_size)]


def fetch_schema_introspection(
    api_key: str,
    timeout_start: float = DEFAULT_TIMEOUT_START_SECONDS,
    timeout_limit: float = DEFAULT_TIMEOUT_LIMIT_SECONDS,
) -> dict[str, Any]:
    """Send the canonical introspection query and return the
    `data.__schema` block. Raises `GraphQLAPIError` on transport
    failure (re-raised from `urlopen_with_retries`)."""
    try:
        data = graphql_request(
            api_key,
            INTROSPECTION_QUERY,
            "IntrospectionQuery",
            timeout_start=timeout_start,
            timeout_limit=timeout_limit,
        )
    except (HTTPError, URLError, OSError, TimeoutError, ValueError) as exc:
        reason = getattr(exc, "reason", str(exc))
        raise GraphQLAPIError(f"Introspection request failed: {reason}") from exc
    schema = data.get("__schema")
    if schema is None:
        raise GraphQLAPIError("Introspection response missing __schema block")
    return schema


def fetch_abstract_ids(
    api_key: str,
    timeout_start: float = DEFAULT_TIMEOUT_START_SECONDS,
    timeout_limit: float = DEFAULT_TIMEOUT_LIMIT_SECONDS,
) -> tuple[list[int], list[int]]:
    data = graphql_request(
        api_key,
        ABSTRACT_IDS_QUERY,
        "abstract_ids",
        timeout_start=timeout_start,
        timeout_limit=timeout_limit,
    )
    event_ids = [item["id"] for item in data.get("events", [])]
    abstract_ids = [item["id"] for item in data.get("submissions", [])]
    return event_ids, abstract_ids


def fetch_withdrawn_ids(
    api_key: str,
    timeout_start: float = DEFAULT_TIMEOUT_START_SECONDS,
    timeout_limit: float = DEFAULT_TIMEOUT_LIMIT_SECONDS,
) -> tuple[list[int], list[int]]:
    """Return the (event_ids, submission_ids) tuple for the withdrawn
    corpus — submissions with decision_status='Withdrawn'. Separate
    from `fetch_abstract_ids` so the two corpora never share an ID
    list or state-key namespace (FR-022)."""
    data = graphql_request(
        api_key,
        WITHDRAWN_IDS_QUERY,
        "withdrawn_ids",
        timeout_start=timeout_start,
        timeout_limit=timeout_limit,
    )
    event_ids = [item["id"] for item in data.get("events", [])]
    abstract_ids = [item["id"] for item in data.get("submissions", [])]
    return event_ids, abstract_ids


def fetch_abstract_content(
    api_key: str,
    submission_ids: list[int],
    timeout_start: float = DEFAULT_TIMEOUT_START_SECONDS,
    timeout_limit: float = DEFAULT_TIMEOUT_LIMIT_SECONDS,
) -> list[dict[str, Any]]:
    data = graphql_request(
        api_key,
        ABSTRACT_CONTENTS_QUERY,
        "abstract_contents",
        variables={"submission_ids": submission_ids},
        timeout_start=timeout_start,
        timeout_limit=timeout_limit,
    )
    submissions = data.get("submissions", [])
    if not submissions:
        raise GraphQLAPIError(f"No submission data returned for abstract batch: {submission_ids}")

    by_id = {submission["id"]: submission for submission in submissions}
    missing_ids = [submission_id for submission_id in submission_ids if submission_id not in by_id]
    if missing_ids:
        raise GraphQLAPIError(f"Missing submission data for abstracts: {missing_ids[:10]}")

    return [by_id[submission_id] for submission_id in submission_ids]


def fetch_author_details(
    api_key: str,
    author_ids: list[int],
    batch_size: int = 200,
    timeout_start: float = DEFAULT_TIMEOUT_START_SECONDS,
    timeout_limit: float = DEFAULT_TIMEOUT_LIMIT_SECONDS,
) -> list[dict[str, Any]]:
    authors: list[dict[str, Any]] = []
    for author_id_batch in chunked(author_ids, batch_size):
        data = graphql_request(
            api_key,
            AUTHOR_QUERY,
            "authors_by_ids",
            variables={"ids": author_id_batch},
            timeout_start=timeout_start,
            timeout_limit=timeout_limit,
        )
        authors.extend(data.get("authors", []))
    authors.sort(key=lambda item: item["id"])
    return authors


def extract_value_field(value: Any) -> Any:
    if isinstance(value, list):
        for item in value:
            extracted = extract_value_field(item)
            if extracted not in (None, ""):
                return extracted
        return None
    if isinstance(value, dict):
        if "value" in value:
            return value.get("value")
        return value
    return value


def is_valid_external_url(source_url: str) -> bool:
    parsed = urlparse(source_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return False
    try:
        _ = parsed.port
    except ValueError:
        return False
    return True


def extract_external_urls(values: list[str], pattern: re.Pattern[str]) -> list[str]:
    urls: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = unescape(value)
        for match in pattern.findall(text):
            cleaned = match.rstrip(".,);]")
            if not is_valid_external_url(cleaned):
                continue
            if cleaned not in seen:
                seen.add(cleaned)
                urls.append(cleaned)
    return urls
