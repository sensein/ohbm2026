from __future__ import annotations

import argparse
import html
import json
import re
from pathlib import Path
from typing import Any

from ohbm2026.layout.poster_layout import analyze_layout_proposal, load_layout_inputs, write_json, write_layout_csv, write_listing_csv
from ohbm2026.layout.poster_sequencing import (
    build_global_path_split_proposal,
    derive_contiguous_layout_clusters,
    graph_reordering_metrics,
    order_records_by_optimal_leaf_ordering,
    order_records_by_sparse_two_opt,
)


HTML_TAG_PATTERN = re.compile(r"<[^>]+>")
CONTENT_QUESTION_NAMES = ("title", "introduction", "methods", "results", "conclusion")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate promoted advanced global-path proposal bundles")
    parser.add_argument("--base-proposal", default="data/poster_layout/proposals/semantic_layout_voyage31/proposal.json")
    parser.add_argument("--raw-input", default="data/abstracts.json")
    parser.add_argument("--authors-input", default="data/authors.json")
    parser.add_argument("--embeddings-dir", default="data/embeddings/voyage_stage2_published")
    parser.add_argument("--claims-cluster-assignments", default="data/embeddings/minilm_claims/clustering_benchmark_25_30/cluster_assignments.json")
    parser.add_argument("--claims-cluster-summaries", default="data/embeddings/minilm_claims/clustering_benchmark_25_30/cluster_summaries.json")
    parser.add_argument(
        "--layout-cluster-assignments",
        default="data/embeddings/voyage_stage2_published/clustering_benchmark_spectral/cluster_assignments.json",
    )
    parser.add_argument(
        "--layout-cluster-summaries",
        default="data/embeddings/voyage_stage2_published/clustering_benchmark_spectral/cluster_summaries.json",
    )
    parser.add_argument("--layout-label-system", default="voyage_stage2_spectral_31")
    parser.add_argument("--output-root", default="data/poster_layout/proposals")
    return parser


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _clean_rich_text(value: Any) -> str:
    text = str(value or "")
    text = html.unescape(text)
    text = HTML_TAG_PATTERN.sub(" ", text)
    return " ".join(text.split())


def _content_text_by_abstract_id(raw_database: dict[str, Any]) -> dict[int, str]:
    content_by_id: dict[int, str] = {}
    for abstract in list(raw_database.get("abstracts") or []):
        abstract_id = abstract.get("id")
        if not isinstance(abstract_id, int):
            continue
        parts: list[str] = []
        title = _clean_rich_text(abstract.get("title"))
        if title:
            parts.append(title)
        for response in list(abstract.get("responses") or []):
            if not isinstance(response, dict):
                continue
            question_name = str(response.get("question_name") or "").strip().lower()
            if question_name not in CONTENT_QUESTION_NAMES:
                continue
            value = _clean_rich_text(response.get("value"))
            if value:
                parts.append(value)
        content_by_id[int(abstract_id)] = " ".join(parts).strip()
    return content_by_id


def _proposal_records_in_order(inputs, proposal: dict[str, Any]):
    records_by_id = {record.abstract_id: record for record in inputs.records}
    ordered_assignments = sorted(
        [item for item in proposal.get("assignments", []) if isinstance(item, dict)],
        key=lambda item: int(item.get("poster_number") or 0),
    )
    return [records_by_id[int(item["abstract_id"])] for item in ordered_assignments]


def _promoted_metadata(
    proposal: dict[str, Any],
    embeddings_dir: Path,
    method_name: str,
    layout_label_system: str,
    layout_label_source: Path,
    layout_parent_count: int,
    layout_exact_count: int,
) -> dict[str, Any]:
    base_metadata = dict(proposal.get("metadata") or {})
    metadata = dict(base_metadata)
    metadata.update(
        {
            "proposal_kind": "semantic_path",
            "proposal_method": f"voyage_stage2_graph_{method_name}",
            "base_proposal_kind": str(base_metadata.get("proposal_kind") or ""),
            "base_proposal_method": str(base_metadata.get("proposal_method") or ""),
            "layout_label_system": str(layout_label_system),
            "layout_label_source": str(layout_label_source),
            "layout_parent_label_count": int(layout_parent_count),
            "layout_exact_label_count": int(layout_exact_count),
            "layout_has_distinct_parent_labels": int(layout_parent_count) != int(layout_exact_count),
            "path_primary_embeddings_dir": str(embeddings_dir),
            "path_seed_strategy": "optimal_leaf_ordering_then_sparse_two_opt",
            "sequencing_method": str(method_name),
            "sequencing_source": "global_order_before_block_split",
            "sequencing_assumption": (
                "A single global voyage-based graph-reordered sequence is built across all accepted abstracts, "
                "then split into the two paired-day blocks using the semantic-path alternation logic."
            ),
        }
    )
    return metadata


def _apply_contiguous_layout_categories(
    proposal: dict[str, Any],
    ordered_records,
    normalized_matrix,
    output_dir: Path,
    target_cluster_count: int,
    content_by_id: dict[int, str] | None = None,
) -> tuple[dict[str, Any], Path, Path, dict[str, Any]]:
    cluster_payload = derive_contiguous_layout_clusters(
        ordered_records,
        normalized_matrix,
        target_cluster_count=target_cluster_count,
        content_by_id=content_by_id,
    )
    assignments_path = output_dir / "cluster_assignments.json"
    summaries_path = output_dir / "cluster_summaries.json"
    write_json(assignments_path, {"assignments": {str(key): int(value) for key, value in cluster_payload["assignments"].items()}})
    write_json(summaries_path, {"clusters": list(cluster_payload["clusters"])})

    summary_by_id = {int(item["cluster_id"]): item for item in cluster_payload["clusters"]}
    updated_assignments = []
    for assignment in list(proposal.get("assignments") or []):
        abstract_id = int(assignment["abstract_id"])
        cluster_id = int(cluster_payload["assignments"][abstract_id])
        cluster_summary = summary_by_id[cluster_id]
        updated_assignments.append(
            {
                **assignment,
                "base_layout_parent_label": str(assignment.get("layout_parent_label") or ""),
                "base_layout_exact_label": str(assignment.get("layout_exact_label") or ""),
                "base_layout_label_system": str(assignment.get("layout_label_system") or ""),
                "layout_parent_label": str(cluster_summary.get("parent_label") or cluster_summary["label"]),
                "layout_exact_label": str(cluster_summary["label"]),
                "layout_label_system": "voyage_stage2_olo_contiguous_31",
            }
        )
    proposal["assignments"] = updated_assignments
    return proposal, assignments_path, summaries_path, cluster_payload


def _write_proposal_bundle(
    output_dir: Path,
    inputs,
    proposal: dict[str, Any],
    authors_input: Path,
    ordered_ids: list[int],
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "proposal.json", proposal)
    write_layout_csv(output_dir / "proposal.csv", proposal)
    write_listing_csv(output_dir / "proposal_listing.csv", proposal, authors_input=authors_input)
    write_json(output_dir / "proposal_session_summaries.json", proposal.get("session_summaries", {}))
    analysis = analyze_layout_proposal(inputs, proposal)
    write_json(output_dir / "analysis.json", analysis)
    write_json(output_dir / "session_summaries.json", analysis.get("session_analysis", {}))

    records_by_id = {record.abstract_id: record for record in inputs.records}
    overall_records = [records_by_id[abstract_id] for abstract_id in ordered_ids]
    write_json(
        output_dir / "global_sequence_metrics.json",
        {
            "ordered_abstract_ids": ordered_ids,
            "overall_graph_metrics": graph_reordering_metrics(overall_records, inputs.normalized_matrix, band_width=5),
        },
    )
    write_json(output_dir / "diagnostics.json", {"overall": {"method_name": proposal["metadata"].get("sequencing_method")}})


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    raw_database = load_json(Path(args.raw_input))
    content_by_id = _content_text_by_abstract_id(raw_database)
    inputs = load_layout_inputs(
        Path(args.raw_input),
        Path(args.embeddings_dir),
        claims_cluster_assignments=Path(args.claims_cluster_assignments) if args.claims_cluster_assignments else None,
        claims_cluster_summaries=Path(args.claims_cluster_summaries) if args.claims_cluster_summaries else None,
        layout_cluster_assignments=Path(args.layout_cluster_assignments) if args.layout_cluster_assignments else None,
        layout_cluster_summaries=Path(args.layout_cluster_summaries) if args.layout_cluster_summaries else None,
        layout_label_system=str(args.layout_label_system),
    )
    base_proposal = load_json(Path(args.base_proposal))
    ordered_records = _proposal_records_in_order(inputs, base_proposal)
    records_by_id = {record.abstract_id: record for record in ordered_records}
    olo_seed = order_records_by_optimal_leaf_ordering(ordered_records, inputs.normalized_matrix)

    configs = [
        ("semantic_path_voyage31_olo_two_opt_knn20_p8", "global_olo_two_opt_knn20_p8", 20, 8),
        ("semantic_path_voyage31_olo_two_opt_knn40_p8", "global_olo_two_opt_knn40_p8", 40, 8),
    ]
    output_root = Path(args.output_root)
    authors_input = Path(args.authors_input)
    for proposal_name, method_name, neighbor_count, max_passes in configs:
        output_dir = output_root / proposal_name
        ordered_ids = order_records_by_sparse_two_opt(
            ordered_records,
            inputs.normalized_matrix,
            seed_ids=olo_seed,
            neighbor_count=int(neighbor_count),
            max_passes=int(max_passes),
        )
        proposal = build_global_path_split_proposal(
            base_proposal,
            global_ordered_ids=ordered_ids,
            records_by_id=records_by_id,
            method_name=method_name,
        )
        target_cluster_count = int(base_proposal.get("metadata", {}).get("layout_exact_label_count") or 31)
        proposal, assignments_path, summaries_path, cluster_payload = _apply_contiguous_layout_categories(
            proposal=proposal,
            ordered_records=[records_by_id[abstract_id] for abstract_id in ordered_ids],
            normalized_matrix=inputs.normalized_matrix,
            output_dir=output_dir,
            target_cluster_count=target_cluster_count,
            content_by_id=content_by_id,
        )
        derived_inputs = load_layout_inputs(
            Path(args.raw_input),
            Path(args.embeddings_dir),
            claims_cluster_assignments=Path(args.claims_cluster_assignments) if args.claims_cluster_assignments else None,
            claims_cluster_summaries=Path(args.claims_cluster_summaries) if args.claims_cluster_summaries else None,
            layout_cluster_assignments=assignments_path,
            layout_cluster_summaries=summaries_path,
            layout_label_system="voyage_stage2_olo_contiguous_31",
        )
        proposal["metadata"] = _promoted_metadata(
            proposal=proposal,
            embeddings_dir=Path(args.embeddings_dir),
            method_name=method_name,
            layout_label_system="voyage_stage2_olo_contiguous_31",
            layout_label_source=assignments_path,
            layout_parent_count=len({str(item.get("parent_label") or item.get("label") or "Unknown") for item in cluster_payload["clusters"]}),
            layout_exact_count=len(list(cluster_payload["clusters"] or [])),
        )
        _write_proposal_bundle(
            output_dir,
            inputs=derived_inputs,
            proposal=proposal,
            authors_input=authors_input,
            ordered_ids=ordered_ids,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
