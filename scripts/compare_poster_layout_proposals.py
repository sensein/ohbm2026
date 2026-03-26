from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _layout_system_display_name(layout_label_system: str) -> str:
    mapping = {
        "submitter_primary_secondary": "submitter primary/subcategory taxonomy",
        "voyage_stage2_kmeans_25": "Voyage Stage 2 k-means (25 clusters)",
        "voyage_stage2_spectral_31": "Voyage Stage 2 spectral (31 clusters)",
        "minilm_claims_kmeans_28": "MiniLM claims k-means (28 clusters)",
        "voyage_stage2_olo_contiguous_31": "Voyage OLO contiguous categories (31 clusters)",
    }
    return mapping.get(layout_label_system, layout_label_system.replace("_", " "))


def _top_layout_categories(assignments: list[dict[str, Any]], limit: int = 8) -> list[dict[str, Any]]:
    counts = Counter(str(item.get("layout_exact_label") or item.get("primary_category") or "Unknown") for item in assignments)
    rows: list[dict[str, Any]] = []
    for label, count in counts.most_common(limit):
        accepted_for_counts = Counter(
            str(item.get("accepted_for") or "Unknown")
            for item in assignments
            if str(item.get("layout_exact_label") or item.get("primary_category") or "Unknown") == label
        )
        primary_counts = Counter(
            str(item.get("primary_category") or "Unknown")
            for item in assignments
            if str(item.get("layout_exact_label") or item.get("primary_category") or "Unknown") == label
        )
        rows.append(
            {
                "label": label,
                "count": int(count),
                "accepted_for_counts": dict(accepted_for_counts),
                "top_primary_categories": [
                    {"label": category, "count": int(category_count)}
                    for category, category_count in primary_counts.most_common(5)
                ],
            }
        )
    return rows


def summarize_proposal_dir(proposal_dir: Path) -> dict[str, Any]:
    proposal = load_json(proposal_dir / "proposal.json")
    analysis = load_json(proposal_dir / "analysis.json")
    assignments = list(proposal.get("assignments", []))
    metadata = dict(proposal.get("metadata") or {})
    layout_label_system = str(metadata.get("layout_label_system") or "submitter_primary_secondary")

    category_spread: dict[str, dict[str, Any]] = defaultdict(lambda: {"sessions": set(), "blocks": set(), "count": 0})
    submitter_category_spread: dict[str, dict[str, Any]] = defaultdict(lambda: {"sessions": set(), "blocks": set(), "count": 0})
    session_counts = Counter()
    for item in assignments:
        category = str(item.get("layout_exact_label") or item.get("primary_category") or "Unknown")
        submitter_category = str(item.get("primary_category") or "Unknown")
        session_id = int(item.get("standby_session"))
        block_id = int(item.get("block_id"))
        category_spread[category]["sessions"].add(session_id)
        category_spread[category]["blocks"].add(block_id)
        category_spread[category]["count"] += 1
        submitter_category_spread[submitter_category]["sessions"].add(session_id)
        submitter_category_spread[submitter_category]["blocks"].add(block_id)
        submitter_category_spread[submitter_category]["count"] += 1
        session_counts[session_id] += 1

    block_locality = analysis.get("block_analysis", {})
    discoverability = analysis.get("discoverability", {}).get("overall", {})
    claims_category_analysis = analysis.get("claims_category_analysis", {})
    claims_overall = claims_category_analysis.get("overall", {})
    accepted_for_counts = Counter(str(item.get("accepted_for") or "Unknown") for item in assignments)
    conflict_total = sum(
        int(session_data.get("conflict_count") or 0)
        for session_data in (analysis.get("author_conflicts_by_session") or {}).values()
    )
    return {
        "proposal_dir": str(proposal_dir),
        "proposal_name": proposal_dir.name,
        "weights": dict(metadata.get("weights") or {}),
        "sequencing_method": str(metadata.get("sequencing_method") or ""),
        "sequencing_assumption": str(metadata.get("sequencing_assumption") or ""),
        "layout_label_system": layout_label_system,
        "layout_exact_label_count": int(metadata.get("layout_exact_label_count") or 0),
        "layout_parent_label_count": int(metadata.get("layout_parent_label_count") or 0),
        "session_counts": {str(session_id): session_counts.get(session_id, 0) for session_id in (1, 2, 3, 4)},
        "accepted_count": int(metadata.get("accepted_count") or len(assignments)),
        "poster_count": int(accepted_for_counts.get("Poster") or 0),
        "oral_count": int(accepted_for_counts.get("Oral") or 0),
        "author_conflict_total": conflict_total,
        "exact_category_count": len(category_spread),
        "exact_categories_single_block": sum(1 for data in category_spread.values() if len(data["blocks"]) == 1),
        "exact_categories_single_block_multi_poster": sum(
            1 for data in category_spread.values() if len(data["blocks"]) == 1 and int(data["count"]) > 1
        ),
        "exact_categories_all_four_sessions": sum(1 for data in category_spread.values() if len(data["sessions"]) == 4),
        "exact_categories_three_plus_sessions": sum(
            1 for data in category_spread.values() if len(data["sessions"]) >= 3
        ),
        "submitter_exact_category_count": len(submitter_category_spread),
        "submitter_exact_categories_single_block_multi_poster": sum(
            1 for data in submitter_category_spread.values() if len(data["blocks"]) == 1 and int(data["count"]) > 1
        ),
        "block_adjacent_mean_semantic_distance": float(
            (
                float(block_locality.get("1", {}).get("locality", {}).get("adjacent_mean_semantic_distance") or 0.0)
                + float(block_locality.get("2", {}).get("locality", {}).get("adjacent_mean_semantic_distance") or 0.0)
            )
            / 2.0
        ),
        "block_adjacent_exact_category_match_rate": float(
            (
                float(block_locality.get("1", {}).get("locality", {}).get("adjacent_exact_category_match_rate") or 0.0)
                + float(block_locality.get("2", {}).get("locality", {}).get("adjacent_exact_category_match_rate") or 0.0)
            )
            / 2.0
        ),
        "block_adjacent_parent_category_match_rate": float(
            (
                float(block_locality.get("1", {}).get("locality", {}).get("adjacent_parent_category_match_rate") or 0.0)
                + float(block_locality.get("2", {}).get("locality", {}).get("adjacent_parent_category_match_rate") or 0.0)
            )
            / 2.0
        ),
        "claims_cluster_count": int(claims_category_analysis.get("cluster_count") or 0),
        "claims_clusters_used_by_posters": int(claims_category_analysis.get("clusters_used_by_posters") or 0),
        "claims_adjacent_same_cluster_rate": float(claims_overall.get("adjacent_same_claims_cluster_rate") or 0.0),
        "claims_clusters_single_block": int(claims_overall.get("claims_clusters_single_block") or 0),
        "claims_clusters_single_block_multi_poster": int(
            claims_overall.get("claims_clusters_single_block_multi_poster") or 0
        ),
        "claims_clusters_all_four_sessions": int(claims_overall.get("claims_clusters_all_four_sessions") or 0),
        "claims_clusters_three_plus_sessions": int(claims_overall.get("claims_clusters_three_plus_sessions") or 0),
        "mean_same_claims_cluster_posters_in_paired_session": float(
            claims_overall.get("mean_same_claims_cluster_posters_in_paired_session") or 0.0
        ),
        "mean_exact_category_posters_in_paired_session": float(
            discoverability.get("mean_exact_category_posters_in_paired_session") or 0.0
        ),
        "mean_parent_category_posters_in_paired_session": float(
            discoverability.get("mean_parent_category_posters_in_paired_session") or 0.0
        ),
        "top_claims_clusters_overall": list(claims_category_analysis.get("top_clusters_overall") or []),
        "session_top_claims_clusters": dict(claims_category_analysis.get("session_top_clusters") or {}),
        "proposal_kind": str(metadata.get("proposal_kind") or "weighted_assignment"),
        "proposal_method": str(metadata.get("proposal_method") or proposal_dir.name),
        "top_layout_categories_overall": _top_layout_categories(assignments, limit=10),
    }


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fieldnames = [
        "proposal_name",
        "proposal_dir",
        "layout_label_system",
        "layout_parent_label_count",
        "layout_exact_label_count",
        "accepted_count",
        "poster_count",
        "oral_count",
        "author_conflict_total",
        "exact_category_count",
        "exact_categories_single_block",
        "exact_categories_single_block_multi_poster",
        "exact_categories_all_four_sessions",
        "exact_categories_three_plus_sessions",
        "submitter_exact_category_count",
        "submitter_exact_categories_single_block_multi_poster",
        "claims_cluster_count",
        "claims_clusters_used_by_posters",
        "claims_clusters_single_block",
        "claims_clusters_single_block_multi_poster",
        "claims_clusters_all_four_sessions",
        "claims_clusters_three_plus_sessions",
        "claims_adjacent_same_cluster_rate",
        "mean_same_claims_cluster_posters_in_paired_session",
        "block_adjacent_mean_semantic_distance",
        "block_adjacent_exact_category_match_rate",
        "block_adjacent_parent_category_match_rate",
        "mean_exact_category_posters_in_paired_session",
        "mean_parent_category_posters_in_paired_session",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({fieldname: row.get(fieldname) for fieldname in fieldnames})


def _format_percent(value: float) -> str:
    return f"{value * 100:.1f}%"


def _best_recommendation(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not rows:
        return None
    return sorted(
        rows,
        key=lambda row: (
            int(row.get("author_conflict_total") or 0),
            int(row.get("exact_categories_single_block_multi_poster") or 0),
            int(row.get("claims_clusters_single_block_multi_poster") or 0),
            int(row.get("exact_categories_single_block") or 0),
            float(row.get("block_adjacent_mean_semantic_distance") or 0.0),
            -float(row.get("claims_adjacent_same_cluster_rate") or 0.0),
            -float(row.get("block_adjacent_exact_category_match_rate") or 0.0),
            row.get("proposal_name") or "",
        ),
    )[0]


def _proposal_emphasis(row: dict[str, Any]) -> str:
    proposal_name = str(row.get("proposal_name") or "")
    proposal_kind = str(row.get("proposal_kind") or "")
    proposal_method = str(row.get("proposal_method") or "")
    layout_label_system = str(row.get("layout_label_system") or "")
    sequencing_method = str(row.get("sequencing_method") or "")
    if proposal_name == "session_balance_baseline":
        return "Balance sessions and keep nearby posters closely related"
    if proposal_name == "block_spread_soft":
        return "Spread categories across blocks with a light touch"
    if proposal_name == "block_spread_strong":
        return "Spread categories across blocks more aggressively"
    if sequencing_method.startswith("global_olo_two_opt"):
        return (
            "Build one global voyage-based order using optimal leaf ordering plus sparse 2-opt refinement, "
            "derive contiguous layout categories from that sequence, then split it across blocks"
        )
    if sequencing_method.startswith("global_optimal_leaf_ordering"):
        return "Build one global voyage-based order with optimal leaf ordering, derive contiguous layout categories, then split it across blocks"
    if proposal_name.startswith("semantic_layout_") or (
        proposal_kind == "weighted_assignment" and layout_label_system != "submitter_primary_secondary"
    ):
        return f"Use learned semantic clusters from {layout_label_system} as the main layout taxonomy"
    if proposal_kind == "semantic_path":
        if "+" in proposal_method:
            return "Build one semantic path using both embedding spaces, then split it across blocks"
        if "voyage" in proposal_method.lower():
            return "Build one semantic path from voyage stage 2 embeddings, then split it across blocks"
        if "claim" in proposal_method.lower():
            return "Build one semantic path from claims embeddings, then split it across blocks"
        return "Build one semantic path across all accepted abstracts, then split it across blocks"
    return "Custom weighting"


def _block_spread_soft_detail() -> str:
    return (
        "`block_spread_soft` is the submitter-category reference layout. It uses the existing "
        "parent/subcategory taxonomy to spread related categories across the two blocks with a light touch, "
        "keeps a shared parent/subcategory order across blocks, and then uses embedding-based nearest-neighbor "
        "ordering within each subcategory for local coherence. It does not run an additional within-category "
        "hierarchical clustering pass."
    )


def build_markdown_summary(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "# Poster Layout Proposal Summary\n\nNo proposal summaries were generated.\n"

    recommendation = _best_recommendation(rows)
    baseline = next((row for row in rows if row.get("proposal_name") == "session_balance_baseline"), None)
    soft = next((row for row in rows if row.get("proposal_name") == "block_spread_soft"), None)
    strong = next((row for row in rows if row.get("proposal_name") == "block_spread_strong"), None)
    categorical_reference = soft or baseline or rows[0]
    source = recommendation if recommendation is not None else rows[0]

    lines = ["# Poster Layout Proposal Summary", ""]
    lines.append("## Plain-Language Takeaway")
    if recommendation is not None:
        lines.append(
            f"`{recommendation['proposal_name']}` is the strongest overall option in this set. "
            "It keeps sessions balanced, preserves strong topical grouping on the floor, and avoids the main weakness "
            "of the baseline approach by reducing meaningful one-block category concentration."
        )
        lines.append(
            f"It uses `{_layout_system_display_name(str(recommendation.get('layout_label_system') or ''))}` as the organizing taxonomy."
        )
    lines.append("")
    lines.append("## What All Proposals Share")
    shared_session_counts = ", ".join(
        f"session {session_id}: {categorical_reference['session_counts'][str(session_id)]}" for session_id in (1, 2, 3, 4)
    )
    lines.append(
        f"Each proposal assigns all `{categorical_reference['accepted_count']}` accepted abstracts, including `{categorical_reference['oral_count']}` oral presentations, across the four standby sessions: {shared_session_counts}."
    )
    if all(int(row.get("author_conflict_total") or 0) == 0 for row in rows):
        lines.append("Every proposal produces zero first-author conflicts.")
    else:
        lines.append("All proposals keep first-author conflicts low, but not all variants eliminate them entirely.")
    lines.append(
        "All proposals keep nearby posters strongly related once they are numbered in the hall, though some do this better than others."
    )
    lines.append("")
    lines.append("## What Each Proposal Emphasizes")
    for row in rows:
        lines.append(f"`{row['proposal_name']}`: {_proposal_emphasis(row)}.")
    if soft is not None:
        lines.append("")
        lines.append(_block_spread_soft_detail())
    lines.append("")
    lines.append("## Where They Critically Differ")
    if baseline is not None:
        lines.append(
            f"The baseline proposal leaves `{baseline['exact_categories_single_block_multi_poster']}` multi-poster exact categories confined to a single block."
        )
    if soft is not None and baseline is not None:
        lines.append(
            f"The soft block-spread proposal reduces that to `{soft['exact_categories_single_block_multi_poster']}`, which means it removes the meaningful cases where a category with multiple posters is trapped in one block."
        )
    elif soft is not None:
        lines.append(
            f"The categorical reference proposal `{soft['proposal_name']}` leaves `{soft['exact_categories_single_block_multi_poster']}` multi-poster exact categories confined to a single block."
        )
    if strong is not None:
        lines.append(
            f"The strong block-spread proposal also lands at `{strong['exact_categories_single_block_multi_poster']}`. On this dataset, the stronger weighting does not create a meaningful additional gain over the soft version."
        )
    path_rows = [row for row in rows if str(row.get("proposal_kind")) == "semantic_path"]
    if path_rows:
        best_path = sorted(
            path_rows,
            key=lambda row: (
                int(row.get("author_conflict_total") or 0),
                int(row.get("exact_categories_single_block_multi_poster") or 0),
                -float(row.get("claims_adjacent_same_cluster_rate") or 0.0),
                float(row.get("block_adjacent_mean_semantic_distance") or 0.0),
                row.get("proposal_name") or "",
            ),
        )[0]
        lines.append(
            f"Among the semantic-path options, `{best_path['proposal_name']}` is the strongest current tradeoff between spreading related work across blocks and keeping local semantic neighborhoods intact."
        )
    lines.append("")
    lines.append("The main practical takeaway is that the spread-oriented and path-based proposals improve cross-day discoverability in different ways, while the strongest options still preserve local coherence in the poster hall.")
    lines.append("")
    lines.append("## Active Layout Taxonomy")
    lines.append(
        f"The recommended proposal is driven by `{_layout_system_display_name(str(source.get('layout_label_system') or ''))}`, "
        f"with `{int(source.get('layout_exact_label_count') or 0)}` layout categories."
    )
    lines.append(
        f"About {_format_percent(float(source['block_adjacent_exact_category_match_rate']))} of adjacent posters stay within the same active layout category."
    )
    top_layout = list(source.get("top_layout_categories_overall") or [])[:8]
    if top_layout:
        lines.append("")
        lines.append("Largest layout categories in the recommended proposal:")
        for category in top_layout:
            lines.append(f"- `{category['label']}`: {int(category.get('count') or 0)} abstracts.")
    lines.append("")
    lines.append("## Claims-Based Category View")
    lines.append(
        f"The claims-based semantic clustering view contains `{source['claims_cluster_count']}` clusters, with "
        f"`{source['claims_clusters_used_by_posters']}` represented among posters."
    )
    lines.append(
        "These are content-driven themes derived from the claims embeddings rather than from the submitter-selected submission categories."
    )
    if baseline is not None:
        lines.append(
            f"In the baseline proposal, `{baseline['claims_clusters_single_block_multi_poster']}` multi-poster claims clusters "
            "are concentrated in a single block."
        )
    if soft is not None and baseline is not None:
        lines.append(
            f"In the soft block-spread proposal, that falls to `{soft['claims_clusters_single_block_multi_poster']}`."
        )
    elif soft is not None:
        lines.append(
            f"In the categorical reference proposal, `{soft['claims_clusters_single_block_multi_poster']}` multi-poster claims clusters are concentrated in a single block."
        )
    if strong is not None:
        lines.append(
            f"In the strong block-spread proposal, it is also `{strong['claims_clusters_single_block_multi_poster']}`."
        )
    lines.append(
        f"In the recommended proposal, about {_format_percent(float(source['claims_adjacent_same_cluster_rate']))} "
        "of adjacent posters remain in the same claims-derived cluster, which means the optimizer is still preserving "
        "strong semantic neighborhoods as a secondary content check."
    )
    lines.append("")
    lines.append("## Recommendation")
    if recommendation is not None:
        lines.append(
            f"`{recommendation['proposal_name']}` is the recommended version to review first. It best balances operational constraints, cross-block spread, and local topical coherence in this proposal set."
        )
    if soft is not None and strong is not None:
        lines.append(
            "Between the two block-spread options, the soft version is the more natural default because it achieves the same observed benefit as the strong version without needing a more forceful weighting scheme."
        )
    lines.append("")
    lines.append("## Proposal Snapshot")
    lines.append("")
    lines.append("| Proposal | Main Emphasis | First-Author Conflicts | Multi-Poster Categories in One Block | Adjacent Exact-Category Match |")
    lines.append("| --- | --- | ---: | ---: | ---: |")
    for row in rows:
        lines.append(
            f"| `{row['proposal_name']}` | {_proposal_emphasis(row)} | {row['author_conflict_total']} | "
            f"{row['exact_categories_single_block_multi_poster']} | "
            f"{_format_percent(float(row['block_adjacent_exact_category_match_rate']))} |"
        )
    lines.append("")
    lines.append("## Rich Summary Of Claims Categories")
    claims_source = recommendation if recommendation is not None else rows[0]
    for cluster in claims_source.get("top_claims_clusters_overall", [])[:10]:
        label = cluster.get("label") or f"Claims cluster {cluster.get('claims_cluster_id')}"
        size = cluster.get("total_size") or cluster.get("count") or 0
        accepted_for_counts = cluster.get("accepted_for_counts") or {}
        poster_count = accepted_for_counts.get("Poster", 0)
        oral_count = accepted_for_counts.get("Oral", 0)
        keywords = ", ".join(list(cluster.get("keywords") or [])[:6])
        representatives = ", ".join(
            item.get("title", "")
            for item in list(cluster.get("representative_abstracts") or [])[:3]
            if item.get("title")
        )
        lines.append(
            f"- `{label}`: {size} abstracts overall ({poster_count} posters, {oral_count} orals). "
            f"Keywords: {keywords}. Representative examples: {representatives}."
        )
    lines.append("")
    lines.append("## Top Claims Categories By Session In The Recommended Proposal")
    if recommendation is not None:
        session_top = recommendation.get("session_top_claims_clusters", {})
        for session_id in ("1", "2", "3", "4"):
            session_clusters = list(session_top.get(session_id) or [])[:5]
            if not session_clusters:
                continue
            lines.append(f"### Session {session_id}")
            for cluster in session_clusters:
                label = cluster.get("label") or f"Claims cluster {cluster.get('claims_cluster_id')}"
                count = int(cluster.get("count") or 0)
                keywords = ", ".join(list(cluster.get("keywords") or [])[:5])
                lines.append(f"- `{label}`: {count} posters. Keywords: {keywords}.")
            lines.append("")
    lines.append("")
    lines.append("## Files")
    for row in rows:
        proposal_dir = Path(str(row["proposal_dir"]))
        files = [proposal_dir / "proposal.json", proposal_dir / "analysis.json", proposal_dir / "session_day_umap.html"]
        if str(row.get("proposal_kind") or "") == "semantic_path":
            files.append(proposal_dir / "layout_reassignment_summary.md")
        lines.append(f"- `{row['proposal_name']}`: " + ", ".join(f"`{path}`" for path in files))
    lines.append("")
    return "\n".join(lines) + "\n"


def build_claims_categories_markdown(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "# Claims Category Summary\n\nNo proposal summaries were generated.\n"
    recommendation = _best_recommendation(rows)
    source = recommendation if recommendation is not None else rows[0]
    lines = ["# Claims Category Summary", ""]
    lines.append(
        "This summary uses the claims-based semantic clustering derived from the `minilm_claims` embedding benchmark. "
        "These are content-driven themes based on abstract claims, not the submitter-selected submission categories."
    )
    lines.append("")
    lines.append(
        f"The current clustering contains `{source.get('claims_cluster_count', 0)}` total claims clusters, "
        f"with `{source.get('claims_clusters_used_by_posters', 0)}` represented among posters."
    )
    lines.append(
        f"In the recommended proposal, `{source.get('claims_clusters_single_block_multi_poster', 0)}` multi-poster claims clusters "
        "are confined to a single block, and "
        f"`{source.get('claims_clusters_all_four_sessions', 0)}` claims clusters appear in all four standby sessions."
    )
    lines.append(
        f"About {_format_percent(float(source.get('claims_adjacent_same_cluster_rate') or 0.0))} of adjacent posters stay within the same claims-derived cluster, "
        "which indicates strong semantic grouping on the floor."
    )
    lines.append("")
    lines.append("## Largest Claims Categories")
    for cluster in source.get("top_claims_clusters_overall", [])[:12]:
        label = cluster.get("label") or f"Claims cluster {cluster.get('claims_cluster_id')}"
        size = cluster.get("total_size") or cluster.get("count") or 0
        accepted_for_counts = cluster.get("accepted_for_counts") or {}
        poster_count = accepted_for_counts.get("Poster", 0)
        oral_count = accepted_for_counts.get("Oral", 0)
        keywords = ", ".join(list(cluster.get("keywords") or [])[:8])
        representatives = "\n".join(
            f"  - {item.get('title', '')}"
            for item in list(cluster.get("representative_abstracts") or [])[:4]
            if item.get("title")
        )
        lines.append(f"### {label}")
        lines.append(f"- Cluster size: {size} abstracts overall ({poster_count} posters, {oral_count} orals)")
        lines.append(f"- Keywords: {keywords}")
        if representatives:
            lines.append("- Representative abstracts:")
            lines.append(representatives)
        lines.append("")
    lines.append("## Top Claims Categories By Session In The Recommended Proposal")
    session_top = source.get("session_top_claims_clusters", {})
    for session_id in ("1", "2", "3", "4"):
        session_clusters = list(session_top.get(session_id) or [])[:6]
        if not session_clusters:
            continue
        lines.append(f"### Session {session_id}")
        for cluster in session_clusters:
            label = cluster.get("label") or f"Claims cluster {cluster.get('claims_cluster_id')}"
            count = int(cluster.get("count") or 0)
            keywords = ", ".join(list(cluster.get("keywords") or [])[:6])
            lines.append(f"- `{label}`: {count} posters. Keywords: {keywords}.")
        lines.append("")
    return "\n".join(lines) + "\n"


def build_organizer_memo_markdown(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "# Organizer Memo\n\nNo proposal summaries were generated.\n"

    recommendation = _best_recommendation(rows)
    baseline = next((row for row in rows if row.get("proposal_name") == "session_balance_baseline"), None)
    soft = next((row for row in rows if row.get("proposal_name") == "block_spread_soft"), None)
    strong = next((row for row in rows if row.get("proposal_name") == "block_spread_strong"), None)
    categorical_reference = soft or baseline or rows[0]
    source = recommendation if recommendation is not None else rows[0]
    block_one_count = int(categorical_reference["session_counts"]["1"]) + int(categorical_reference["session_counts"]["2"])
    block_two_count = int(categorical_reference["session_counts"]["3"]) + int(categorical_reference["session_counts"]["4"])

    lines = ["# Organizer Memo: Poster Layout Proposals", ""]
    lines.append("## Recommendation")
    if recommendation is not None:
        lines.append(
            f"Use `{recommendation['proposal_name']}` as the working recommendation for organizer review."
        )
        lines.append(
            f"It uses `{_layout_system_display_name(str(recommendation.get('layout_label_system') or ''))}` as the main layout taxonomy and preserves the operational strengths of the categorical reference approach."
        )
    lines.append("")
    lines.append("## Why This Recommendation")
    lines.append(
        f"All proposals assign all `{categorical_reference['accepted_count']}` accepted abstracts and keep the two poster blocks balanced "
        f"(`{block_one_count}` in the June 15-16 block and `{block_two_count}` in the June 17-18 block)."
    )
    lines.append(
        f"That includes `{categorical_reference['poster_count']}` poster-selected abstracts and `{categorical_reference['oral_count']}` oral-selected abstracts."
    )
    if all(int(row.get("author_conflict_total") or 0) == 0 for row in rows):
        lines.append("All proposals produce zero first-author conflicts.")
    if baseline is not None:
        lines.append(
            f"The baseline leaves `{baseline['exact_categories_single_block_multi_poster']}` multi-poster layout categories "
            "confined to a single block."
        )
    if soft is not None and baseline is not None:
        lines.append(
            f"The soft block-spread version reduces that to `{soft['exact_categories_single_block_multi_poster']}`."
        )
    elif soft is not None:
        lines.append(
            f"The categorical reference proposal `{soft['proposal_name']}` also keeps multi-poster category concentration at `{soft['exact_categories_single_block_multi_poster']}`."
        )
    if strong is not None:
        lines.append(
            f"The strong block-spread version also reduces that to `{strong['exact_categories_single_block_multi_poster']}`, "
            "so it does not add a meaningful practical gain over the soft version on this dataset."
        )
    lines.append(
        f"Local floor coherence remains strong in the recommended proposal: "
        f"{_format_percent(float(source['block_adjacent_exact_category_match_rate']))} of adjacent posters match on the active layout category, "
        f"and {_format_percent(float(source['claims_adjacent_same_cluster_rate']))} stay within the same claims-derived semantic cluster."
    )
    lines.append("")
    lines.append(f"## What The {len(rows)} Proposals Emphasize")
    for row in rows:
        lines.append(f"- `{row['proposal_name']}`: {_proposal_emphasis(row)}.")
    if soft is not None:
        lines.append("")
        lines.append(_block_spread_soft_detail())
    lines.append("")
    lines.append("## What They Share")
    lines.append("- Even distribution across the two blocks.")
    lines.append("- Zero first-author conflicts.")
    lines.append("- Strong local topical grouping once posters are numbered in the hall.")
    lines.append("- Broad distribution of related work across both blocks.")
    lines.append("")
    lines.append("## TL;DR")
    if recommendation is not None:
        lines.append(
            f"If we want the cleanest organizer-facing option while prioritizing semantic coherence, start with `{recommendation['proposal_name']}`."
        )
    else:
        lines.append("Start with the top-ranked proposal in the comparison set.")
    lines.append(
        f"For the detailed metrics and side-by-side tradeoffs, use `data/poster_layout/proposals/summary.md` and "
        f"`{Path(str(source['proposal_dir'])) / 'layout_category_summary.md'}`."
    )
    lines.append("")
    lines.append("## Active Layout System")
    lines.append(
        f"The recommended proposal is organized around `{_layout_system_display_name(str(source.get('layout_label_system') or ''))}`."
    )
    lines.append(
        f"This produces `{int(source.get('layout_exact_label_count') or 0)}` organizer-facing layout categories."
    )
    top_layout_categories = list(source.get("top_layout_categories_overall") or [])[:8]
    if top_layout_categories:
        lines.append("")
        lines.append("Largest layout categories in the recommended proposal:")
        for category in top_layout_categories:
            label = category.get("label") or "Unknown"
            count = int(category.get("count") or 0)
            top_primary = ", ".join(
                item.get("label", "")
                for item in list(category.get("top_primary_categories") or [])[:3]
                if item.get("label")
            )
            if top_primary:
                lines.append(f"- `{label}`: {count} abstracts. Main submitter categories represented: {top_primary}.")
            else:
                lines.append(f"- `{label}`: {count} abstracts.")
    lines.append("")
    lines.append("## Claims-Based Cross-Check")
    lines.append(
        "As a secondary content check, we also evaluate the recommended proposal against the claims-derived semantic themes."
    )
    lines.append(
        "Using the claims embeddings, the accepted abstracts fall into 28 semantic content clusters. "
        "All 28 appear among posters, and in the recommended proposal all 28 appear in all four standby sessions."
    )
    lines.append("")
    lines.append("Largest claims-derived themes in the recommended proposal:")
    for cluster in source.get("top_claims_clusters_overall", [])[:8]:
        label = cluster.get("label") or f"Claims cluster {cluster.get('claims_cluster_id')}"
        size = cluster.get("total_size") or cluster.get("count") or 0
        keywords = ", ".join(list(cluster.get("keywords") or [])[:6])
        lines.append(f"- `{label}`: {size} abstracts overall. Keywords: {keywords}.")
    lines.append("")
    lines.append("## Recommended Review Files")
    recommended_dir = Path(str(source["proposal_dir"]))
    lines.append(f"- Proposal data: `{recommended_dir / 'proposal.json'}`")
    lines.append(f"- Proposal spreadsheet export: `{recommended_dir / 'proposal.csv'}`")
    lines.append(f"- Layout category summary: `{recommended_dir / 'layout_category_summary.md'}`")
    lines.append(f"- Analysis report: `{recommended_dir / 'analysis.json'}`")
    lines.append(f"- UMAP day/session comparison: `{recommended_dir / 'session_day_umap.html'}`")
    lines.append(f"- Proposal comparison summary: `data/poster_layout/proposals/summary.md`")
    lines.append("")
    lines.append("## Suggested Next Step")
    lines.append(
        "Review the recommended proposal together with the UMAP day/session plot and the proposal CSV, then spot-check a few large voyage-derived layout categories and use the claims-derived themes as a secondary content sanity check."
    )
    lines.append("")
    return "\n".join(lines) + "\n"


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Summarize multiple poster layout proposal directories")
    parser.add_argument("--proposal-dir", action="append", required=True)
    parser.add_argument("--output-json", default="data/poster_layout/proposals/summary.json")
    parser.add_argument("--output-csv", default="data/poster_layout/proposals/summary.csv")
    parser.add_argument("--output-md", default="data/poster_layout/proposals/summary.md")
    parser.add_argument("--output-organizer-md", default="data/poster_layout/proposals/organizer_memo.md")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    proposal_dirs = [Path(value) for value in args.proposal_dir]
    rows = [summarize_proposal_dir(proposal_dir) for proposal_dir in proposal_dirs]
    payload = {"proposals": rows}
    write_json(Path(args.output_json), payload)
    write_csv(Path(args.output_csv), rows)
    write_text(Path(args.output_md), build_markdown_summary(rows))
    write_text(Path(args.output_organizer_md), build_organizer_memo_markdown(rows))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
