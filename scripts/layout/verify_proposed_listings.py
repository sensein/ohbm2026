from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from ohbm2026.layout.poster_layout import LISTING_TEMPLATE_COLUMNS
from ohbm2026.titles import cleaned_abstract_title


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_abstract_lookup(path: Path) -> dict[int, dict[str, Any]]:
    payload = load_json(path)
    abstracts = payload.get("abstracts", [])
    return {
        int(abstract["id"]): abstract
        for abstract in abstracts
        if isinstance(abstract, dict) and isinstance(abstract.get("id"), int)
    }


def load_author_lookup(path: Path) -> dict[int, dict[str, Any]]:
    payload = load_json(path)
    authors = payload.get("authors", [])
    return {
        int(author["id"]): author
        for author in authors
        if isinstance(author, dict) and isinstance(author.get("id"), int)
    }


def _first_author_id(abstract: dict[str, Any]) -> int | None:
    authors = sorted(list(abstract.get("authors", [])), key=lambda item: int(item.get("author_order", 0)))
    if not authors:
        return None
    author_id = authors[0].get("id")
    return int(author_id) if isinstance(author_id, int) else None


def load_proposal_lookup(path: Path) -> dict[int, dict[str, Any]]:
    payload = load_json(path)
    assignments = payload.get("assignments", [])
    return {
        int(item["abstract_id"]): item
        for item in assignments
        if isinstance(item, dict) and isinstance(item.get("abstract_id"), int)
    }


def load_listing_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.reader(handle)
        rows = list(reader)
    expected_header = list(LISTING_TEMPLATE_COLUMNS)
    header_index: int | None = None
    for index, row in enumerate(rows):
        if row == expected_header:
            header_index = index
            break
    if header_index is None:
        preview = rows[: min(5, len(rows))]
        raise ValueError(f"{path} does not contain the expected listing header row. First rows: {preview}")
    header = rows[header_index]
    listing_rows: list[dict[str, str]] = []
    for row in rows[header_index + 1 :]:
        if not any(str(value).strip() for value in row):
            continue
        padded = list(row) + [""] * (len(header) - len(row))
        listing_rows.append({header[index]: padded[index] for index in range(len(header))})
    return listing_rows


def verify_proposal_dir(
    proposal_dir: Path,
    abstracts_by_id: dict[int, dict[str, Any]],
    authors_by_id: dict[int, dict[str, Any]],
) -> dict[str, Any]:
    listing_path = proposal_dir / "proposal_listing.csv"
    proposal_path = proposal_dir / "proposal.json"
    proposal_by_id = load_proposal_lookup(proposal_path)
    listing_rows = load_listing_rows(listing_path)

    errors: list[str] = []
    seen_listing_ids: set[int] = set()
    standby_conflicts: list[dict[str, Any]] = []
    author_time_index: dict[tuple[int, str], list[dict[str, Any]]] = defaultdict(list)

    for row_index, row in enumerate(listing_rows, start=3):
        try:
            abstract_id = int(str(row["Abstract ID Number"]).strip())
        except ValueError as exc:
            errors.append(f"{listing_path}:{row_index} invalid abstract id: {row['Abstract ID Number']!r} ({exc})")
            continue
        seen_listing_ids.add(abstract_id)

        abstract = abstracts_by_id.get(abstract_id)
        if abstract is None:
            errors.append(f"{listing_path}:{row_index} abstract id {abstract_id} not found in abstracts.json")
            continue
        proposal_row = proposal_by_id.get(abstract_id)
        if proposal_row is None:
            errors.append(f"{listing_path}:{row_index} abstract id {abstract_id} not found in proposal.json")
            continue

        source_title = cleaned_abstract_title(str(abstract.get("title") or ""))
        proposal_title = str(proposal_row.get("title") or "")
        listing_title = str(row["Abstract Title"] or "")
        if listing_title != proposal_title:
            errors.append(
                f"{listing_path}:{row_index} title mismatch for abstract {abstract_id}: "
                f"listing={listing_title!r} proposal={proposal_title!r}"
            )
        if proposal_title != source_title:
            errors.append(
                f"{proposal_path} title mismatch for abstract {abstract_id}: proposal={proposal_title!r} source={source_title!r}"
            )

        source_first_author_id = _first_author_id(abstract)
        proposal_first_author_id = proposal_row.get("first_author_id")
        if proposal_first_author_id != source_first_author_id:
            errors.append(
                f"{proposal_path} first author id mismatch for abstract {abstract_id}: "
                f"proposal={proposal_first_author_id!r} source={source_first_author_id!r}"
            )

        expected_last_name = ""
        if isinstance(source_first_author_id, int):
            expected_last_name = str((authors_by_id.get(source_first_author_id) or {}).get("last_name") or "").strip()
        listing_last_name = str(row["Last Name of First Author"] or "").strip()
        if listing_last_name != expected_last_name:
            errors.append(
                f"{listing_path}:{row_index} first author last name mismatch for abstract {abstract_id}: "
                f"listing={listing_last_name!r} source={expected_last_name!r}"
            )

        for time_field in ("First Stand-by Time", "Second Stand-by Time"):
            standby_label = str(row[time_field] or "").strip()
            if not standby_label:
                errors.append(f"{listing_path}:{row_index} missing {time_field} for abstract {abstract_id}")
                continue
            if isinstance(source_first_author_id, int):
                author_time_index[(source_first_author_id, standby_label)].append(
                    {
                        "abstract_id": abstract_id,
                        "poster_number": proposal_row.get("poster_number"),
                        "time_field": time_field,
                        "standby_label": standby_label,
                        "title": proposal_title,
                        "first_author_last_name": expected_last_name,
                    }
                )

    missing_from_listing = sorted(set(proposal_by_id) - seen_listing_ids)
    if missing_from_listing:
        errors.append(f"{listing_path} is missing {len(missing_from_listing)} proposal rows")

    extra_in_listing = sorted(seen_listing_ids - set(proposal_by_id))
    if extra_in_listing:
        errors.append(f"{listing_path} has {len(extra_in_listing)} rows not present in proposal.json")

    for (first_author_id, standby_label), matches in sorted(author_time_index.items()):
        if len(matches) <= 1:
            continue
        standby_conflicts.append(
            {
                "first_author_id": first_author_id,
                "first_author_last_name": matches[0]["first_author_last_name"],
                "standby_label": standby_label,
                "posters": [
                    {
                        "abstract_id": int(item["abstract_id"]),
                        "poster_number": int(item["poster_number"]),
                        "title": str(item["title"]),
                        "time_field": str(item["time_field"]),
                    }
                    for item in sorted(matches, key=lambda item: (int(item["poster_number"]), int(item["abstract_id"])))
                ],
            }
        )

    return {
        "proposal_name": proposal_dir.name,
        "proposal_dir": str(proposal_dir),
        "listing_row_count": len(listing_rows),
        "proposal_row_count": len(proposal_by_id),
        "match_ok": not errors,
        "conflict_free": not standby_conflicts,
        "errors": errors,
        "standby_conflicts": standby_conflicts,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Verify proposal listing CSVs against abstracts/authors/proposal data")
    parser.add_argument("--abstracts-input", default="data/abstracts.json")
    parser.add_argument("--authors-input", default="data/authors.json")
    parser.add_argument("--proposal-dir", action="append", required=True)
    parser.add_argument("--output-json")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    abstracts_by_id = load_abstract_lookup(Path(args.abstracts_input))
    authors_by_id = load_author_lookup(Path(args.authors_input))
    results = [
        verify_proposal_dir(Path(proposal_dir), abstracts_by_id, authors_by_id)
        for proposal_dir in args.proposal_dir
    ]
    payload = {"proposals": results}
    if args.output_json:
        output_path = Path(args.output_json)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")

    has_errors = False
    for result in results:
        print(f"[{result['proposal_name']}] rows={result['listing_row_count']} match_ok={result['match_ok']} conflict_free={result['conflict_free']}")
        if result["errors"]:
            has_errors = True
            for error in result["errors"]:
                print(f"  ERROR: {error}")
        if result["standby_conflicts"]:
            has_errors = True
            for conflict in result["standby_conflicts"]:
                poster_labels = ", ".join(
                    f"#{item['poster_number']} (abstract {item['abstract_id']})"
                    for item in conflict["posters"]
                )
                print(
                    "  CONFLICT: "
                    f"first_author_id={conflict['first_author_id']} "
                    f"last_name={conflict['first_author_last_name']!r} "
                    f"time={conflict['standby_label']!r} posters={poster_labels}"
                )
    return 1 if has_errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
