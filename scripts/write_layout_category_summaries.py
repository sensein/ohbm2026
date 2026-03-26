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


def _infer_cluster_summaries_path(proposal: dict[str, Any]) -> Path | None:
    metadata = dict(proposal.get("metadata") or {})
    layout_source = str(metadata.get("layout_label_source") or "").strip()
    if not layout_source or layout_source == "submitter primary parent/subcategory responses":
        return None
    source_path = Path(layout_source)
    if source_path.name == "cluster_assignments.json":
        candidate = source_path.with_name("cluster_summaries.json")
        if candidate.exists():
            return candidate
    return None


def _cluster_summary_by_label(path: Path | None) -> dict[str, dict[str, Any]]:
    if path is None or not path.exists():
        return {}
    payload = load_json(path)
    raw_clusters = payload.get("clusters", payload)
    if not isinstance(raw_clusters, list):
        return {}
    summaries: dict[str, dict[str, Any]] = {}
    for item in raw_clusters:
        if not isinstance(item, dict):
            continue
        label = str(item.get("label") or "").strip()
        if not label:
            continue
        summaries[label] = item
    return summaries


def build_layout_category_summary(proposal_dir: Path) -> dict[str, Any]:
    proposal = load_json(proposal_dir / "proposal.json")
    assignments = list(proposal.get("assignments") or [])
    metadata = dict(proposal.get("metadata") or {})
    layout_label_system = str(metadata.get("layout_label_system") or "unknown")
    cluster_summaries = _cluster_summary_by_label(_infer_cluster_summaries_path(proposal))

    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in assignments:
        grouped[str(item.get("layout_exact_label") or "Unknown")].append(item)

    categories: list[dict[str, Any]] = []
    for label, rows in grouped.items():
        accepted_for_counts = Counter(str(row.get("accepted_for") or "Unknown") for row in rows)
        block_counts = Counter(int(row.get("block_id") or 0) for row in rows)
        parent_labels = Counter(str(row.get("layout_parent_label") or "Unknown") for row in rows)
        primary_categories = Counter(str(row.get("primary_category") or "Unknown") for row in rows)
        representative_rows = sorted(
            rows,
            key=lambda row: (int(row.get("poster_number") or 0), int(row.get("abstract_id") or 0)),
        )[:5]
        cluster_summary = cluster_summaries.get(label) or {}
        categories.append(
            {
                "layout_exact_label": label,
                "layout_parent_label": parent_labels.most_common(1)[0][0] if parent_labels else "Unknown",
                "count": len(rows),
                "accepted_for_counts": dict(sorted(accepted_for_counts.items())),
                "block_counts": {str(block_id): int(block_counts.get(block_id, 0)) for block_id in (1, 2)},
                "top_primary_categories": [
                    {"label": category, "count": int(count)}
                    for category, count in primary_categories.most_common(5)
                ],
                "keywords": list(cluster_summary.get("keywords") or []),
                "representative_abstracts": list(cluster_summary.get("representative_abstracts") or []),
                "sample_posters": [
                    {
                        "poster_number": int(row.get("poster_number") or 0),
                        "abstract_id": int(row.get("abstract_id") or 0),
                        "title": str(row.get("title") or ""),
                    }
                    for row in representative_rows
                ],
                "source_cluster_id": cluster_summary.get("cluster_id"),
                "source_cluster_size": cluster_summary.get("size"),
            }
        )

    categories.sort(key=lambda item: (-int(item["count"]), str(item["layout_exact_label"])))
    return {
        "proposal_name": proposal_dir.name,
        "layout_label_system": layout_label_system,
        "layout_label_source": metadata.get("layout_label_source"),
        "category_count": len(categories),
        "categories": categories,
    }


def build_layout_category_markdown(summary: dict[str, Any]) -> str:
    proposal_name = str(summary.get("proposal_name") or "proposal")
    layout_label_system = str(summary.get("layout_label_system") or "unknown")
    categories = list(summary.get("categories") or [])

    lines = [f"# Layout Category Summary: {proposal_name}", ""]
    lines.append(f"Layout system: `{layout_label_system}`")
    lines.append(f"Category count: `{int(summary.get('category_count') or 0)}`")
    lines.append("")
    lines.append("This file summarizes the active layout categories used in this proposal.")
    lines.append("")
    for category in categories:
        lines.append(f"## {category['layout_exact_label']}")
        lines.append(
            f"- Size: `{category['count']}` abstracts "
            f"(`{category['accepted_for_counts'].get('Poster', 0)}` posters, `{category['accepted_for_counts'].get('Oral', 0)}` orals)"
        )
        lines.append(
            f"- Block split: June 15-16=`{category['block_counts'].get('1', 0)}`, "
            f"June 17-18=`{category['block_counts'].get('2', 0)}`"
        )
        top_primary = ", ".join(
            f"{item['label']} ({item['count']})"
            for item in list(category.get("top_primary_categories") or [])[:4]
        )
        if top_primary:
            lines.append(f"- Top submitter categories: {top_primary}")
        keywords = ", ".join(list(category.get("keywords") or [])[:8])
        if keywords:
            lines.append(f"- Keywords: {keywords}")
        representative_abstracts = list(category.get("representative_abstracts") or [])[:4]
        if representative_abstracts:
            lines.append("- Representative abstracts:")
            for item in representative_abstracts:
                lines.append(f"  - {item.get('title', '')}")
        else:
            sample_posters = list(category.get("sample_posters") or [])[:4]
            if sample_posters:
                lines.append("- Sample posters in this layout category:")
                for item in sample_posters:
                    lines.append(f"  - #{item['poster_number']}: {item['title']}")
        lines.append("")
    return "\n".join(lines) + "\n"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Write per-proposal layout category summaries")
    parser.add_argument("--proposal-dir", action="append", required=True)
    parser.add_argument("--json-name", default="layout_category_summary.json")
    parser.add_argument("--md-name", default="layout_category_summary.md")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    for raw_proposal_dir in args.proposal_dir:
        proposal_dir = Path(raw_proposal_dir)
        summary = build_layout_category_summary(proposal_dir)
        write_json(proposal_dir / args.json_name, summary)
        write_text(proposal_dir / args.md_name, build_layout_category_markdown(summary))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
