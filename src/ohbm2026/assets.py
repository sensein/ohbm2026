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

from ohbm2026.graphql_api import (
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
    from ohbm2026.graphql_api import extract_external_urls as _extract

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


def normalize_abstract(raw: dict[str, Any]) -> dict[str, Any]:
    responses = [
        {"question_name": item.get("question", {}).get("question_name"), "value": item.get("value")}
        for item in raw.get("responses", [])
    ]
    response_values = [item["value"] for item in responses if isinstance(item.get("value"), str)]
    authors = sorted(raw.get("authors", []), key=lambda item: item.get("author_order", 0))
    return {
        "id": raw.get("id"),
        "title": extract_value_field(raw.get("title")),
        "accepted_for": extract_value_field(raw.get("accepted_for")),
        "authors": authors,
        "responses": responses,
        "external_urls": extract_external_urls(response_values),
        "figure_urls": extract_target_figure_urls(responses),
        "local_assets": [],
    }


def build_database(
    api_key: str,
    output_path: Path,
    assets_dir: Path,
    batch_size: int = 50,
    reuse_existing_assets_only: bool = False,
    timeout_start: float = DEFAULT_TIMEOUT_START_SECONDS,
    timeout_limit: float = DEFAULT_TIMEOUT_LIMIT_SECONDS,
) -> dict[str, Any]:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    assets_dir.mkdir(parents=True, exist_ok=True)
    event_ids, abstract_ids = fetch_abstract_ids(
        api_key,
        timeout_start=timeout_start,
        timeout_limit=timeout_limit,
    )
    asset_cache: dict[str, AssetDownload] = {}
    existing_assets = build_existing_asset_index(assets_dir)
    abstracts: list[dict[str, Any]] = []

    for abstract_id_batch in chunked(abstract_ids, batch_size):
        raw_batch = fetch_abstract_content(
            api_key,
            abstract_id_batch,
            timeout_start=timeout_start,
            timeout_limit=timeout_limit,
        )
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
    output_path.write_text(json.dumps(database, indent=2, sort_keys=True), encoding="utf-8")
    return database


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Fetch OHBM 2026 abstracts to a local JSON DB")
    parser.add_argument("--env-file", default=".env")
    parser.add_argument("--env-var", default="OHBM2026_API")
    parser.add_argument("--output", default="data/abstracts.json")
    parser.add_argument("--assets-dir", default="data/assets")
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
                "assets_dir": args.assets_dir,
                "abstract_count": database["abstract_count"],
                "event_ids": database["event_ids"],
            },
            indent=2,
        )
    )
    return 0
