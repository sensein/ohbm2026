from __future__ import annotations

import argparse
import hashlib
import json
import mimetypes
import re
import sys
from datetime import datetime, timezone
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request

from ohbm2026 import artifacts
from ohbm2026.fetch.graphql_api import (
    DEFAULT_TIMEOUT_LIMIT_SECONDS,
    DEFAULT_TIMEOUT_START_SECONDS,
    GraphQLAPIError,
    chunked,
    extract_value_field,
    fetch_abstract_content,
    fetch_abstract_ids,
    get_api_key,
    is_valid_external_url,
    urlopen_with_retries,
)

IMAGE_EXTENSIONS = {
    ".apng",
    ".avif",
    ".bmp",
    ".gif",
    ".jpeg",
    ".jpg",
    ".png",
    ".svg",
    ".tif",
    ".tiff",
    ".webp",
}
URL_PATTERN = re.compile(r"https?://[^\s<>'\")]+")
TARGET_FIGURE_QUESTION_TOKENS = ("methods", "results")

# This module writes `data/primary/abstracts.json`; it does NOT read
# from it. Declaration kept for symmetry with the per-stage pattern
# (research.md §4 / FR-021) — once a consumer module reads from the
# normalized corpus, it adds its own CONSUMED_ABSTRACT_FIELDS.
CONSUMED_ABSTRACT_FIELDS: frozenset[tuple[str, str]] = frozenset()

# Per-record state machine for Stage 1 (data-model.md). Legal forward
# transitions only. The orchestrator's checkpoint is the source of
# truth for actual progress; this helper validates a transition is
# permitted before committing it.
_LEGAL_TRANSITIONS: dict[str, frozenset[str]] = {
    "pending": frozenset({"corpus_fetched"}),
    "corpus_fetched": frozenset({"figures_in_progress", "done"}),
    "figures_in_progress": frozenset({"done", "failed-retryable"}),
    "failed-retryable": frozenset({"done", "figures_in_progress"}),
    "done": frozenset(),
    "failed-blocking": frozenset(),
}


def advance_record_state(current: str, next_state: str) -> str:
    """Validate a per-record state transition; return ``next_state`` if
    legal, raise ``ValueError`` otherwise. Used by the orchestrator to
    keep the checkpoint's per-record map honest."""
    legal = _LEGAL_TRANSITIONS.get(current)
    if legal is None:
        raise ValueError(f"Unknown state: {current!r}")
    if next_state not in legal:
        raise ValueError(
            f"Illegal record-state transition: {current!r} → {next_state!r}; "
            f"legal next states from {current!r}: {sorted(legal)}"
        )
    return next_state


@dataclass
class AssetDownload:
    source_url: str
    local_path: str | None
    content_type: str | None
    downloaded: bool
    error: str | None = None


def stringify_error(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def guess_extension(source_url: str, content_type: str | None) -> str:
    if content_type:
        content_type = content_type.split(";", 1)[0].strip().lower()
        extension = mimetypes.guess_extension(content_type)
        if extension:
            return extension

    suffix = Path(urlparse(source_url).path).suffix
    if suffix:
        return suffix
    return ".bin"


def is_image_url_candidate(source_url: str) -> bool:
    suffix = Path(urlparse(source_url).path).suffix.lower()
    if not suffix:
        return True
    return suffix in IMAGE_EXTENSIONS


def asset_stem(abstract_id: int, source_url: str) -> str:
    url_hash = hashlib.sha256(source_url.encode("utf-8")).hexdigest()[:12]
    return f"{abstract_id}_{url_hash}"


def build_existing_asset_index(destination_dir: Path) -> dict[str, Path]:
    return {path.stem: path for path in destination_dir.iterdir() if path.is_file()}


def find_existing_asset(existing_assets: dict[str, Path], abstract_id: int, source_url: str) -> Path | None:
    return existing_assets.get(asset_stem(abstract_id, source_url))


def is_target_figure_question(question_name: str | None) -> bool:
    if not question_name:
        return False
    lowered = question_name.lower()
    return "figure" in lowered and any(token in lowered for token in TARGET_FIGURE_QUESTION_TOKENS)


def extract_external_urls(values: list[str]) -> list[str]:
    from ohbm2026.fetch.graphql_api import extract_external_urls as _extract

    return _extract(values, URL_PATTERN)


def extract_target_figure_urls(responses: list[dict[str, Any]]) -> list[dict[str, str]]:
    figure_urls: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for response in responses:
        question_name = response.get("question_name")
        value = response.get("value")
        if not is_target_figure_question(question_name) or not isinstance(value, str):
            continue
        for source_url in extract_external_urls([value]):
            key = (question_name, source_url)
            if key in seen:
                continue
            seen.add(key)
            figure_urls.append({"question_name": question_name, "source_url": source_url})
    return figure_urls


def normalize_local_asset(asset: AssetDownload, source_question_name: str) -> dict[str, Any]:
    return {
        "source_url": asset.source_url,
        "source_question_name": source_question_name,
        "local_path": asset.local_path,
        "content_type": asset.content_type,
        "downloaded": asset.downloaded,
        "error": stringify_error(asset.error),
    }


def download_asset(
    source_url: str,
    destination_dir: Path,
    abstract_id: int,
    cache: dict[str, AssetDownload],
    existing_assets: dict[str, Path],
    reuse_existing_assets_only: bool = False,
    timeout_start: float = DEFAULT_TIMEOUT_START_SECONDS,
    timeout_limit: float = DEFAULT_TIMEOUT_LIMIT_SECONDS,
) -> AssetDownload:
    cached = cache.get(source_url)
    if cached:
        return cached

    if not is_valid_external_url(source_url):
        result = AssetDownload(source_url, None, None, False, "Skipped invalid URL")
        cache[source_url] = result
        return result

    if not is_image_url_candidate(source_url):
        result = AssetDownload(source_url, None, None, False, "Skipped non-image URL")
        cache[source_url] = result
        return result

    existing_path = find_existing_asset(existing_assets, abstract_id, source_url)
    if existing_path is not None:
        result = AssetDownload(
            source_url=source_url,
            local_path=str(existing_path),
            content_type=mimetypes.guess_type(existing_path.name)[0],
            downloaded=True,
            error=None,
        )
        cache[source_url] = result
        return result

    if reuse_existing_assets_only:
        result = AssetDownload(source_url, None, None, False, "Missing local asset from previous run")
        cache[source_url] = result
        return result

    stem = asset_stem(abstract_id, source_url)
    request = Request(
        source_url,
        headers={"User-Agent": "ohbm2026-abstract-ingest/0.1"},
        method="GET",
    )

    try:
        with urlopen_with_retries(
            request,
            timeout_start=timeout_start,
            timeout_limit=timeout_limit,
        ) as response:
            content_type = response.headers.get_content_type()
            if not content_type.startswith("image/"):
                result = AssetDownload(source_url, None, content_type, False, "Skipped non-image content")
                cache[source_url] = result
                return result
            content = response.read()
            extension = guess_extension(source_url, content_type)
            target_path = destination_dir / f"{stem}{extension}"
            target_path.write_bytes(content)
            existing_assets[target_path.stem] = target_path
    except HTTPError as exc:
        result = AssetDownload(source_url, None, None, False, f"HTTP {exc.code}")
        cache[source_url] = result
        return result
    except (URLError, OSError, TimeoutError, ValueError) as exc:
        reason = getattr(exc, "reason", exc)
        result = AssetDownload(source_url, None, None, False, stringify_error(reason))
        cache[source_url] = result
        return result

    result = AssetDownload(source_url, str(target_path), content_type, True, None)
    cache[source_url] = result
    return result


def refresh_local_assets_from_database(
    database_path: Path,
    assets_dir: Path,
    reuse_existing_assets_only: bool = False,
    timeout_start: float = DEFAULT_TIMEOUT_START_SECONDS,
    timeout_limit: float = DEFAULT_TIMEOUT_LIMIT_SECONDS,
) -> dict[str, Any]:
    database = json.loads(database_path.read_text(encoding="utf-8"))
    assets_dir.mkdir(parents=True, exist_ok=True)
    asset_cache: dict[str, AssetDownload] = {}
    existing_assets = build_existing_asset_index(assets_dir)

    for abstract in database.get("abstracts", []):
        figure_urls = extract_target_figure_urls(abstract.get("responses", []))
        abstract["figure_urls"] = figure_urls
        abstract["local_assets"] = [
            normalize_local_asset(
                download_asset(
                    figure_url["source_url"],
                    assets_dir,
                    abstract["id"],
                    asset_cache,
                    existing_assets,
                    reuse_existing_assets_only=reuse_existing_assets_only,
                    timeout_start=timeout_start,
                    timeout_limit=timeout_limit,
                ),
                figure_url["question_name"],
            )
            for figure_url in figure_urls
        ]

    database_path.write_text(json.dumps(database, indent=2, sort_keys=True), encoding="utf-8")
    return database


def _flatten_program_session_row(pss: dict[str, Any]) -> dict[str, Any]:
    """Flatten one ``program_sessions_submissions`` junction row into a
    ``program_sessions[]`` entry per FR-021 / data-model.md."""
    if not isinstance(pss, dict):
        return {}
    ps = pss.get("program_session") or {}
    pd = ps.get("program_date") or {}
    pl = ps.get("program_location") or {}
    ptype = ps.get("program_type") or {}
    ptrack = ps.get("program_track") or {}
    return {
        "session_id": ps.get("id"),
        "session_name": ps.get("name"),
        "session_type": ptype.get("name") if isinstance(ptype, dict) else None,
        "session_track": ptrack.get("name") if isinstance(ptrack, dict) else None,
        "session_date": pd.get("program_date") if isinstance(pd, dict) else None,
        "session_location": pl.get("name") if isinstance(pl, dict) else None,
        "session_start_time": ps.get("start_time"),
        "session_end_time": ps.get("end_time"),
        "standby_start_time": pss.get("start_time"),
        "standby_end_time": pss.get("end_time"),
        "display_order": pss.get("display_order"),
    }


def normalize_abstract(raw: dict[str, Any]) -> dict[str, Any]:
    """Normalize one Oxford Abstracts submission payload into the
    Stage 1 corpus record. Maps upstream ``program_code`` to
    ``poster_id`` (FR-020) and flattens ``program_sessions_submissions``
    into ``program_sessions`` (FR-021)."""
    responses = [
        {"question_name": item.get("question", {}).get("question_name"), "value": item.get("value")}
        for item in raw.get("responses", [])
    ]
    response_values = [item["value"] for item in responses if isinstance(item.get("value"), str)]
    authors = sorted(raw.get("authors", []), key=lambda item: item.get("author_order", 0))
    program_sessions = [
        _flatten_program_session_row(pss)
        for pss in (raw.get("program_sessions_submissions") or [])
    ]
    return {
        "id": raw.get("id"),
        "poster_id": raw.get("program_code"),
        "title": extract_value_field(raw.get("title")),
        "accepted_for": extract_value_field(raw.get("accepted_for")),
        "authors": authors,
        "responses": responses,
        "external_urls": extract_external_urls(response_values),
        "figure_urls": extract_target_figure_urls(responses),
        "program_sessions": program_sessions,
        "local_assets": [],
    }


# Asset-download error kinds that are TERMINAL (not retryable):
# the URL is malformed, the content type is not an image, or the
# operator asked us not to issue new HTTP requests. Retrying these
# would produce the same outcome.
_TERMINAL_ASSET_ERRORS = frozenset(
    {
        "Skipped invalid URL",
        "Skipped non-image URL",
        "Skipped non-image content",
        "Missing local asset from previous run",
    }
)


def _resolve_figures(
    abstract: dict[str, Any],
    *,
    assets_dir: Path,
    asset_cache: dict[str, AssetDownload],
    existing_assets: dict[str, Path],
    reuse_existing_assets_only: bool,
    timeout_start: float,
    timeout_limit: float,
) -> tuple[list[dict[str, Any]], bool]:
    """Resolve every figure URL on ``abstract`` into a local asset
    descriptor. Returns (local_assets, has_retryable_failure). Reuses
    on-disk files via ``find_existing_asset`` — same abstract id +
    same source URL → matching ``asset_stem`` → zero HTTP requests
    issued for that figure."""
    local_assets: list[dict[str, Any]] = []
    has_retryable_failure = False
    for figure_url in abstract.get("figure_urls", []):
        download = download_asset(
            figure_url["source_url"],
            assets_dir,
            abstract["id"],
            asset_cache,
            existing_assets,
            reuse_existing_assets_only=reuse_existing_assets_only,
            timeout_start=timeout_start,
            timeout_limit=timeout_limit,
        )
        local_assets.append(
            normalize_local_asset(download, figure_url["question_name"])
        )
        if (
            not download.downloaded
            and download.error is not None
            and download.error not in _TERMINAL_ASSET_ERRORS
        ):
            has_retryable_failure = True
    return local_assets, has_retryable_failure


def normalize_author(raw: dict[str, Any]) -> dict[str, Any]:
    """Strip PII from an upstream author record and stabilize the
    affiliations order.

    Per FR-023: the persisted record MUST NOT include `email`. The
    upstream `AUTHOR_QUERY` returns it; this function drops it before
    the record reaches disk. ORCID is retained (public researcher
    identifier). Affiliations are sorted by `affiliation_order` so
    re-runs are byte-identical."""
    affiliations_raw = raw.get("affiliations") or []
    affiliations = sorted(
        (dict(a) for a in affiliations_raw if isinstance(a, dict)),
        key=lambda a: (a.get("affiliation_order") or 0, a.get("id") or 0),
    )
    return {
        "id": raw.get("id"),
        "first_name": raw.get("first_name"),
        "middle_initial": raw.get("middle_initial"),
        "last_name": raw.get("last_name"),
        "title": raw.get("title"),
        "degree": raw.get("degree"),
        "orcid_id": raw.get("orcid_id"),
        "presenting": raw.get("presenting"),
        "submission_id": raw.get("submission_id"),
        "affiliations": [
            {
                "id": a.get("id"),
                "affiliation_order": a.get("affiliation_order"),
                "institution": a.get("institution"),
                "city": a.get("city"),
                "state": a.get("state"),
                "country": a.get("country"),
            }
            for a in affiliations
        ],
    }


def fetch_content_batches(
    *,
    api_key: str,
    submission_ids: list[int],
    batch_size: int,
    on_batch_complete: "callable",
    on_record_state_change: "callable",
    assets_dir: Path | None = None,
    reuse_existing_assets_only: bool = False,
    timeout_start: float = DEFAULT_TIMEOUT_START_SECONDS,
    timeout_limit: float = DEFAULT_TIMEOUT_LIMIT_SECONDS,
):
    """Generator: fetch submission content in chunks of ``batch_size``,
    firing ``on_record_state_change(sid, state)`` for each per-record
    transition and ``on_batch_complete(batch_ids)`` after the batch
    finishes. Yields one normalized abstract per submission in input
    order.

    When ``assets_dir`` is provided, every record's figure URLs are
    resolved inline against the existing on-disk asset cache before
    yielding — matched files are reused (zero HTTP), unmatched ones
    are downloaded. Per-record state transitions then include
    ``figures_in_progress`` and end in ``done`` or
    ``failed-retryable``.

    When ``assets_dir`` is ``None`` (test path / corpus-only re-run),
    figure resolution is skipped and the transitions are
    ``pending`` → ``corpus_fetched`` → ``done``."""
    if assets_dir is not None:
        assets_dir.mkdir(parents=True, exist_ok=True)
        existing_assets = build_existing_asset_index(assets_dir)
    else:
        existing_assets = {}
    asset_cache: dict[str, AssetDownload] = {}

    for batch in chunked(submission_ids, batch_size):
        for sid in batch:
            on_record_state_change(sid, "pending")
        raw_batch = fetch_abstract_content(
            api_key,
            batch,
            timeout_start=timeout_start,
            timeout_limit=timeout_limit,
        )
        for raw in raw_batch:
            sid = raw.get("id")
            on_record_state_change(sid, "corpus_fetched")
            normalized = normalize_abstract(raw)
            if assets_dir is not None and normalized.get("figure_urls"):
                on_record_state_change(sid, "figures_in_progress")
                local_assets, retryable = _resolve_figures(
                    normalized,
                    assets_dir=assets_dir,
                    asset_cache=asset_cache,
                    existing_assets=existing_assets,
                    reuse_existing_assets_only=reuse_existing_assets_only,
                    timeout_start=timeout_start,
                    timeout_limit=timeout_limit,
                )
                normalized["local_assets"] = local_assets
                on_record_state_change(
                    sid,
                    "failed-retryable" if retryable else "done",
                )
            else:
                on_record_state_change(sid, "done")
            yield normalized
        on_batch_complete(list(batch))


def build_database(
    api_key: str,
    output_path: Path,
    assets_dir: Path,
    input_snapshot_dir: Path | None = None,
    batch_size: int = 50,
    reuse_existing_assets_only: bool = False,
    timeout_start: float = DEFAULT_TIMEOUT_START_SECONDS,
    timeout_limit: float = DEFAULT_TIMEOUT_LIMIT_SECONDS,
) -> dict[str, Any]:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    assets_dir.mkdir(parents=True, exist_ok=True)
    if input_snapshot_dir is not None:
        input_snapshot_dir.mkdir(parents=True, exist_ok=True)
    event_ids, abstract_ids = fetch_abstract_ids(
        api_key,
        timeout_start=timeout_start,
        timeout_limit=timeout_limit,
    )
    asset_cache: dict[str, AssetDownload] = {}
    existing_assets = build_existing_asset_index(assets_dir)
    abstracts: list[dict[str, Any]] = []
    raw_abstracts: list[dict[str, Any]] = []

    for abstract_id_batch in chunked(abstract_ids, batch_size):
        raw_batch = fetch_abstract_content(
            api_key,
            abstract_id_batch,
            timeout_start=timeout_start,
            timeout_limit=timeout_limit,
        )
        raw_abstracts.extend(raw_batch)
        for raw in raw_batch:
            abstract = normalize_abstract(raw)
            abstract["local_assets"] = [
                normalize_local_asset(
                    download_asset(
                        figure_url["source_url"],
                        assets_dir,
                        abstract["id"],
                        asset_cache,
                        existing_assets,
                        reuse_existing_assets_only=reuse_existing_assets_only,
                        timeout_start=timeout_start,
                        timeout_limit=timeout_limit,
                    ),
                    figure_url["question_name"],
                )
                for figure_url in abstract["figure_urls"]
            ]
            abstracts.append(abstract)

    database = {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "event_ids": event_ids,
        "abstract_count": len(abstracts),
        "abstracts": abstracts,
    }
    if input_snapshot_dir is not None:
        snapshot_payload = {
            "fetched_at": database["fetched_at"],
            "event_ids": event_ids,
            "abstract_count": len(raw_abstracts),
            "abstracts": raw_abstracts,
        }
        basis = artifacts.build_dependency_basis(
            input_sources=[str(output_path)],
            input_digest=artifacts.build_state_key(snapshot_payload),
        )
        snapshot_path = input_snapshot_dir / artifacts.build_input_snapshot_path(
            "abstracts_graphql",
            artifacts.build_state_key(basis),
        ).name
        snapshot_path.write_text(json.dumps(snapshot_payload, indent=2, sort_keys=True), encoding="utf-8")
        database["input_snapshot"] = str(snapshot_path)
    output_path.write_text(json.dumps(database, indent=2, sort_keys=True), encoding="utf-8")
    return database


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Fetch OHBM 2026 abstracts to a local JSON DB")
    parser.add_argument("--env-file", default=".env")
    parser.add_argument("--env-var", default="OHBM2026_API")
    parser.add_argument("--output", default=str(artifacts.PRIMARY_ABSTRACTS_PATH))
    parser.add_argument("--input-snapshot-dir", default=str(artifacts.INPUTS_ROOT))
    parser.add_argument("--assets-dir", default=str(artifacts.PRIMARY_ASSETS_ROOT))
    parser.add_argument("--batch-size", default=50, type=int)
    parser.add_argument("--reuse-existing-assets-only", action="store_true")
    parser.add_argument("--refresh-assets-from-existing-db", action="store_true")
    parser.add_argument("--timeout-start-ms", default=100, type=int)
    parser.add_argument("--timeout-limit-seconds", default=10.0, type=float)
    return parser


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    return build_parser().parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        if args.refresh_assets_from_existing_db:
            database = refresh_local_assets_from_database(
                Path(args.output),
                Path(args.assets_dir),
                reuse_existing_assets_only=args.reuse_existing_assets_only,
                timeout_start=args.timeout_start_ms / 1000,
                timeout_limit=args.timeout_limit_seconds,
            )
        else:
            database = build_database(
                get_api_key(Path(args.env_file), args.env_var),
                Path(args.output),
                Path(args.assets_dir),
                input_snapshot_dir=Path(args.input_snapshot_dir),
                batch_size=args.batch_size,
                reuse_existing_assets_only=args.reuse_existing_assets_only,
                timeout_start=args.timeout_start_ms / 1000,
                timeout_limit=args.timeout_limit_seconds,
            )
    except GraphQLAPIError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    print(
        json.dumps(
            {
                "output": args.output,
                "input_snapshot_dir": args.input_snapshot_dir,
                "assets_dir": args.assets_dir,
                "abstract_count": database["abstract_count"],
                "event_ids": database["event_ids"],
            },
            indent=2,
        )
    )
    return 0
