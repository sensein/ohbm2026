from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ohbm2026 import artifacts
from ohbm2026.util.json_io import load_json, write_json

DEFAULT_TITLE_MODIFICATIONS_OUTPUT = str(artifacts.TITLE_MODIFICATIONS_PATH)

LEADING_MARKER_PATTERN = re.compile(r"^[\s]*(?:[•*-]+)\s*")
WHITESPACE_PATTERN = re.compile(r"\s+")
WRAPPING_QUOTE_PAIRS = (
    ('"', '"'),
    ("“", "”"),
    ("‘", "’"),
    ("'", "'"),
)






def normalize_abstract_title(title: str | None) -> tuple[str, list[str]]:
    original = str(title or "")
    cleaned = original
    reasons: list[str] = []

    stripped = cleaned.strip()
    if stripped != cleaned:
        cleaned = stripped
        reasons.append("trim_whitespace")

    marker_match = LEADING_MARKER_PATTERN.match(cleaned)
    if marker_match:
        cleaned = cleaned[marker_match.end() :].lstrip()
        reasons.append("remove_leading_marker")

    for opening, closing in WRAPPING_QUOTE_PAIRS:
        if cleaned.startswith(opening) and cleaned.endswith(closing):
            inner = cleaned[len(opening) : len(cleaned) - len(closing)].strip()
            if inner:
                cleaned = inner
                reasons.append("remove_wrapping_quotes")
            break

    normalized_spacing = WHITESPACE_PATTERN.sub(" ", cleaned).strip()
    if normalized_spacing != cleaned:
        cleaned = normalized_spacing
        reasons.append("normalize_spacing")

    unique_reasons: list[str] = []
    for reason in reasons:
        if reason not in unique_reasons:
            unique_reasons.append(reason)
    return cleaned, unique_reasons


def cleaned_abstract_title(title: str | None) -> str:
    return normalize_abstract_title(title)[0]


def build_title_modification_report(database: dict[str, Any], *, input_path: str | None = None) -> dict[str, Any]:
    modifications: list[dict[str, Any]] = []
    for abstract in database.get("abstracts", []):
        abstract_id = abstract.get("id")
        original_title = str(abstract.get("title") or "")
        cleaned_title, reasons = normalize_abstract_title(original_title)
        if cleaned_title == original_title:
            continue
        modifications.append(
            {
                "abstract_id": abstract_id,
                "original_title": original_title,
                "cleaned_title": cleaned_title,
                "reasons": reasons,
            }
        )

    return {
        "built_at": datetime.now(timezone.utc).isoformat(),
        "input": input_path,
        "abstract_count": len(database.get("abstracts", [])),
        "modified_count": len(modifications),
        "modifications": modifications,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Write an audit report for cleaned abstract titles")
    parser.add_argument("--input", default=str(artifacts.PRIMARY_ABSTRACTS_PATH))
    parser.add_argument("--output", default=DEFAULT_TITLE_MODIFICATIONS_OUTPUT)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    database = load_json(Path(args.input))
    report = build_title_modification_report(database, input_path=args.input)
    write_json(Path(args.output), report)
    print(
        json.dumps(
            {
                "input": args.input,
                "output": args.output,
                "modified_count": report["modified_count"],
            },
            indent=2,
        )
    )
    return 0
