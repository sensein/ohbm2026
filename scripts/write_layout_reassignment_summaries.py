from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def build_reassignment_summary(proposal_dir: Path) -> dict[str, Any]:
    proposal = load_json(proposal_dir / "proposal.json")
    assignments = list(proposal.get("assignments") or [])
    metadata = dict(proposal.get("metadata") or {})
    old_to_new_counts: dict[str, Counter[str]] = defaultdict(Counter)
    new_to_old_counts: dict[str, Counter[str]] = defaultdict(Counter)
    examples_by_new: dict[str, list[dict[str, Any]]] = defaultdict(list)
    old_layout_systems = {
        str(item.get("base_layout_label_system") or "").strip()
        for item in assignments
        if str(item.get("base_layout_label_system") or "").strip()
    }

    for item in assignments:
        old_label = str(item.get("base_layout_exact_label") or item.get("layout_exact_label") or "Unknown")
        new_label = str(item.get("layout_exact_label") or "Unknown")
        old_to_new_counts[old_label][new_label] += 1
        new_to_old_counts[new_label][old_label] += 1
        if len(examples_by_new[new_label]) < 5:
            examples_by_new[new_label].append(
                {
                    "poster_number": int(item.get("poster_number") or 0),
                    "abstract_id": int(item.get("abstract_id") or 0),
                    "title": str(item.get("title") or ""),
                }
            )

    old_categories = sorted(old_to_new_counts)
    new_categories = sorted(new_to_old_counts)
    old_rows = []
    for old_label in old_categories:
        overlaps = old_to_new_counts[old_label]
        old_rows.append(
            {
                "old_label": old_label,
                "poster_count": int(sum(overlaps.values())),
                "new_category_count": len(overlaps),
                "top_new_categories": [
                    {"label": label, "count": int(count)}
                    for label, count in overlaps.most_common(5)
                ],
            }
        )

    new_rows = []
    for new_label in new_categories:
        overlaps = new_to_old_counts[new_label]
        new_rows.append(
            {
                "new_label": new_label,
                "poster_count": int(sum(overlaps.values())),
                "source_category_count": len(overlaps),
                "top_source_categories": [
                    {"label": label, "count": int(count)}
                    for label, count in overlaps.most_common(5)
                ],
                "examples": list(examples_by_new[new_label]),
            }
        )

    old_rows.sort(key=lambda item: (-int(item["poster_count"]), str(item["old_label"])))
    new_rows.sort(key=lambda item: (-int(item["poster_count"]), str(item["new_label"])))
    retained_old_count = sum(1 for row in old_rows if int(row["new_category_count"]) == 1)
    split_old_count = sum(1 for row in old_rows if int(row["new_category_count"]) > 1)
    pure_new_count = sum(1 for row in new_rows if int(row["source_category_count"]) == 1)
    mixed_new_count = sum(1 for row in new_rows if int(row["source_category_count"]) > 1)
    return {
        "proposal_name": proposal_dir.name,
        "old_layout_label_system": sorted(old_layout_systems)[0] if old_layout_systems else None,
        "new_layout_label_system": str(metadata.get("layout_label_system") or "").strip() or None,
        "old_category_count": len(old_rows),
        "new_category_count": len(new_rows),
        "retained_old_category_count": retained_old_count,
        "split_old_category_count": split_old_count,
        "pure_new_category_count": pure_new_count,
        "mixed_new_category_count": mixed_new_count,
        "from_old_to_new": old_rows,
        "from_new_to_old": new_rows,
    }


def build_reassignment_markdown(summary: dict[str, Any]) -> str:
    lines = [f"# Layout Reassignment Summary: {summary['proposal_name']}", ""]
    old_layout_label_system = str(summary.get("old_layout_label_system") or "previous layout taxonomy")
    new_layout_label_system = str(summary.get("new_layout_label_system") or "new layout taxonomy")
    lines.append(
        f"Old categories: `{int(summary.get('old_category_count') or 0)}`. "
        f"New contiguous OLO categories: `{int(summary.get('new_category_count') or 0)}`."
    )
    lines.append(f"Old taxonomy: `{old_layout_label_system}`.")
    lines.append(f"New taxonomy: `{new_layout_label_system}`.")
    lines.append("")
    lines.append("## TL;DR")
    lines.append(
        f"`{int(summary.get('retained_old_category_count') or 0)}` old categories stayed intact, while "
        f"`{int(summary.get('split_old_category_count') or 0)}` old categories were split across multiple new contiguous segments."
    )
    lines.append(
        f"`{int(summary.get('pure_new_category_count') or 0)}` new categories are dominated by a single source category, while "
        f"`{int(summary.get('mixed_new_category_count') or 0)}` are composites assembled from multiple old categories."
    )
    lines.append("")
    lines.append("## Old Voyage-Derived Categories Split Across New OLO Categories")
    for row in list(summary.get("from_old_to_new") or [])[:20]:
        top_targets = ", ".join(
            f"{item['label']} ({item['count']})" for item in list(row.get("top_new_categories") or [])[:4]
        )
        lines.append(
            f"- `{row['old_label']}`: `{row['poster_count']}` posters across `{row['new_category_count']}` new categories. "
            f"Main targets: {top_targets}"
        )
    lines.append("")
    lines.append("## New OLO Categories And Their Main Source Categories")
    for row in list(summary.get("from_new_to_old") or [])[:20]:
        top_sources = ", ".join(
            f"{item['label']} ({item['count']})" for item in list(row.get("top_source_categories") or [])[:4]
        )
        example_titles = "; ".join(item["title"] for item in list(row.get("examples") or [])[:3])
        lines.append(
            f"- `{row['new_label']}`: `{row['poster_count']}` posters from `{row['source_category_count']}` old categories. "
            f"Main sources: {top_sources}"
        )
        if example_titles:
            lines.append(f"  Examples: {example_titles}")
    lines.append("")
    return "\n".join(lines) + "\n"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Write per-proposal layout reassignment summaries")
    parser.add_argument("--proposal-dir", action="append", required=True)
    parser.add_argument("--json-name", default="layout_reassignment_summary.json")
    parser.add_argument("--md-name", default="layout_reassignment_summary.md")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    for raw_proposal_dir in args.proposal_dir:
        proposal_dir = Path(raw_proposal_dir)
        summary = build_reassignment_summary(proposal_dir)
        write_json(proposal_dir / args.json_name, summary)
        write_text(proposal_dir / args.md_name, build_reassignment_markdown(summary))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
