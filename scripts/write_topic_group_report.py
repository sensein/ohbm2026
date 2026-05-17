from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from ohbm2026 import artifacts
from ohbm2026.analyze.clusters import (
    align_semantic_records,
    load_enriched_lookup,
    summarize_membership_groups,
)
from ohbm2026.analyze.storage import (
    load_annotation_lookup,
    load_embedding_bundle,
    load_title_lookup,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Write explainable markdown and JSON reports for hard clusters or overlapping communities"
    )
    parser.add_argument("--embeddings-dir", required=True)
    parser.add_argument("--input", default=str(artifacts.PRIMARY_ENRICHED_ABSTRACTS_PATH))
    parser.add_argument("--title-input", default=str(artifacts.PRIMARY_ABSTRACTS_PATH))
    parser.add_argument("--assignments-json")
    parser.add_argument("--communities-json")
    parser.add_argument("--report-title", default="Topic Group Report")
    parser.add_argument("--group-label", default="Group")
    parser.add_argument("--output-json", required=True)
    parser.add_argument("--output-md", required=True)
    parser.add_argument("--max-keywords", type=int, default=8)
    parser.add_argument("--max-representatives", type=int, default=5)
    return parser


def _load_group_members(args: argparse.Namespace) -> dict[int, list[int]]:
    assignments_json = bool(args.assignments_json)
    communities_json = bool(args.communities_json)
    if assignments_json == communities_json:
        raise ValueError("Provide exactly one of --assignments-json or --communities-json")

    if assignments_json:
        payload = json.loads(Path(args.assignments_json).read_text(encoding="utf-8"))
        assignments = payload.get("assignments") or {}
        group_members: dict[int, list[int]] = {}
        for abstract_id, group_id in assignments.items():
            group_members.setdefault(int(group_id), []).append(int(abstract_id))
        return group_members

    payload = json.loads(Path(args.communities_json).read_text(encoding="utf-8"))
    communities = payload.get("communities") or {}
    return {
        int(group_id): [int(member_id) for member_id in list(member_ids or [])]
        for group_id, member_ids in communities.items()
    }


def _top_counts(counts: dict[str, int], limit: int = 3) -> str:
    ordered = sorted(counts.items(), key=lambda item: (-int(item[1]), item[0]))
    if not ordered:
        return "n/a"
    return ", ".join(f"{name} ({count})" for name, count in ordered[:limit])


def _render_markdown(
    *,
    report_title: str,
    group_label: str,
    embeddings_dir: Path,
    summaries: list[dict[str, Any]],
) -> str:
    lines = [
        f"# {report_title}",
        "",
        f"Embedding bundle: `{embeddings_dir}`",
        f"Recorded groups: {len(summaries)}",
        "",
    ]
    for summary in summaries:
        representatives = ", ".join(
            f"{item['id']} {item['title']}" for item in summary.get("representative_abstracts") or []
        )
        lines.extend(
            [
                f"## {group_label} {summary['group_id']}: {summary['label']}",
                "",
                summary["rationale"],
                "",
                f"- Size: {summary['size']}",
                f"- Keywords: {', '.join(summary.get('keywords') or []) or 'n/a'}",
                f"- Dominant primary topics: {_top_counts(summary.get('primary_topic_counts') or {})}",
                f"- Accepted-for mix: {_top_counts(summary.get('accepted_for_counts') or {})}",
                f"- Most similar {group_label.lower()}: {summary['most_similar_group_id']}",
                f"- Representative abstracts: {representatives or 'n/a'}",
                "",
            ]
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    embeddings_dir = Path(args.embeddings_dir)
    bundle = load_embedding_bundle(embeddings_dir)
    title_lookup = load_title_lookup(Path(args.title_input))
    enriched_lookup = load_enriched_lookup(Path(args.input))
    annotation_lookup = load_annotation_lookup(Path(args.title_input), Path(args.input))
    records = align_semantic_records(
        bundle["ids"],
        enriched_lookup,
        title_lookup=title_lookup,
        embedding_fields=bundle["source_metadata"].get("embedding_fields"),
    )
    for record in records:
        annotation = annotation_lookup.get(int(record["id"]), {})
        if annotation:
            record["accepted_for"] = annotation.get("accepted_for") or record.get("accepted_for") or "Unknown"
            record["primary_topic"] = annotation.get("primary_topic") or record.get("primary_topic") or "Unknown"
            record["keywords"] = list(annotation.get("keywords") or record.get("keywords") or [])
            if not record.get("title"):
                record["title"] = annotation.get("title") or ""

    summaries = summarize_membership_groups(
        bundle["ids"],
        bundle["matrix"],
        records,
        _load_group_members(args),
        max_keywords=args.max_keywords,
        max_representatives=args.max_representatives,
    )
    output_json = Path(args.output_json)
    output_json.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "report_title": args.report_title,
        "group_label": args.group_label,
        "embeddings_dir": str(embeddings_dir),
        "input": args.input,
        "title_input": args.title_input,
        "summaries": summaries,
    }
    output_json.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    output_md = Path(args.output_md)
    output_md.parent.mkdir(parents=True, exist_ok=True)
    output_md.write_text(
        _render_markdown(
            report_title=args.report_title,
            group_label=args.group_label,
            embeddings_dir=embeddings_dir,
            summaries=summaries,
        ),
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "group_count": len(summaries),
                "output_json": str(output_json),
                "output_md": str(output_md),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
