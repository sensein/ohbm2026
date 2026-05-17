from __future__ import annotations

import argparse
import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from ohbm2026.layout.poster_layout import (
    analyze_layout_proposal,
    build_global_numeric_order,
    build_layout_proposal,
    build_shared_layout_group_order,
    load_layout_inputs,
    write_json,
    write_layout_csv,
    write_listing_csv,
)
from ohbm2026.layout.poster_sequencing import build_global_path_split_proposal


@dataclass(frozen=True)
class TargetLayoutConfig:
    proposal_name: str
    layout_label_system: str
    layout_cluster_assignments: Path | None
    layout_cluster_summaries: Path | None
    within_group_strategy: str
    sequencing_method: str


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate the active poster layout proposals from one global order before block split")
    parser.add_argument("--raw-input", default="data/abstracts.json")
    parser.add_argument("--authors-input", default="data/authors.json")
    parser.add_argument("--embeddings-dir", default="data/embeddings/voyage_stage2_published")
    parser.add_argument("--claims-cluster-assignments", default="data/embeddings/minilm_claims/clustering_benchmark_25_30/cluster_assignments.json")
    parser.add_argument("--claims-cluster-summaries", default="data/embeddings/minilm_claims/clustering_benchmark_25_30/cluster_summaries.json")
    parser.add_argument(
        "--voyage-spectral-assignments",
        default="data/embeddings/voyage_stage2_published/clustering_benchmark_spectral/cluster_assignments.json",
    )
    parser.add_argument(
        "--voyage-spectral-summaries",
        default="data/embeddings/voyage_stage2_published/clustering_benchmark_spectral/cluster_summaries.json",
    )
    parser.add_argument(
        "--nocd-predictions",
        default=(
            "experiments/2026-03-25-nocd-checkpoint-sweep/runs/"
            "20260326T082242-nocd-magmed-v1/voyage_stage2_published/"
            "nocd_gcn_structural_mag_med_pretrained/predictions.npz"
        ),
    )
    parser.add_argument("--output-root", default="data/poster_layout/proposals")
    return parser


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_proposal_bundle(output_dir: Path, inputs, proposal: dict[str, Any], authors_input: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "proposal.json", proposal)
    write_layout_csv(output_dir / "proposal.csv", proposal)
    write_listing_csv(output_dir / "proposal_listing.csv", proposal, authors_input=authors_input)
    write_json(output_dir / "proposal_session_summaries.json", proposal.get("session_summaries", {}))
    analysis = analyze_layout_proposal(inputs, proposal)
    write_json(output_dir / "analysis.json", analysis)
    write_json(output_dir / "session_summaries.json", analysis.get("session_analysis", {}))


def _derive_nocd_cluster_files(
    predictions_path: Path,
    embeddings_dir: Path,
    output_dir: Path,
) -> tuple[Path, Path]:
    metadata = load_json(embeddings_dir / "metadata.json")
    ids = [int(value) for value in list(metadata.get("ids") or [])]
    predictions = np.load(predictions_path)
    z_soft = np.asarray(predictions["Z_soft"], dtype=np.float32)
    if int(z_soft.shape[0]) != len(ids):
        raise ValueError(
            f"NOCD predictions {predictions_path} contain {z_soft.shape[0]} rows but {len(ids)} embedding ids were found"
        )

    dominant = np.argmax(z_soft, axis=1).astype(int)
    counts = Counter(int(value) for value in dominant.tolist())
    assignments_path = output_dir / "nocd_cluster_assignments.json"
    summaries_path = output_dir / "nocd_cluster_summaries.json"
    write_json(
        assignments_path,
        {
            "assignments": {
                str(int(abstract_id)): int(cluster_id)
                for abstract_id, cluster_id in zip(ids, dominant.tolist(), strict=True)
            }
        },
    )
    write_json(
        summaries_path,
        {
            "clusters": [
                {
                    "cluster_id": int(cluster_id),
                    "label": f"NOCD community {int(cluster_id) + 1:02d}",
                    "parent_label": "NOCD structural communities",
                    "count": int(counts[int(cluster_id)]),
                }
                for cluster_id in sorted(counts)
            ]
        },
    )
    return assignments_path, summaries_path


def _metadata_for_global_group_proposal(
    proposal: dict[str, Any],
    *,
    proposal_name: str,
    sequencing_method: str,
    within_group_strategy: str,
) -> dict[str, Any]:
    metadata = dict(proposal.get("metadata") or {})
    metadata["proposal_kind"] = "global_grouped_order"
    metadata["proposal_method"] = proposal_name
    metadata["sequencing_method"] = sequencing_method
    metadata["sequencing_source"] = "global_order_before_block_split"
    metadata["group_within_order_strategy"] = within_group_strategy
    metadata["sequencing_assumption"] = (
        "The active layout taxonomy defines one global grouped order across all accepted abstracts first. "
        "That single global order is then split into the two paired-day poster blocks."
    )
    return metadata


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    raw_input = Path(args.raw_input)
    authors_input = Path(args.authors_input)
    embeddings_dir = Path(args.embeddings_dir)
    output_root = Path(args.output_root)
    claims_assignments = Path(args.claims_cluster_assignments) if args.claims_cluster_assignments else None
    claims_summaries = Path(args.claims_cluster_summaries) if args.claims_cluster_summaries else None

    nocd_output_dir = output_root / "semantic_layout_nocd17"
    nocd_assignments, nocd_summaries = _derive_nocd_cluster_files(
        Path(args.nocd_predictions),
        embeddings_dir,
        nocd_output_dir,
    )

    configs = [
        TargetLayoutConfig(
            proposal_name="categorical_layout",
            layout_label_system="submitter_primary_secondary",
            layout_cluster_assignments=None,
            layout_cluster_summaries=None,
            within_group_strategy="spectral_cluster",
            sequencing_method="categorical_global_spectral_within_category",
        ),
        TargetLayoutConfig(
            proposal_name="semantic_layout_voyage31",
            layout_label_system="voyage_stage2_spectral_31",
            layout_cluster_assignments=Path(args.voyage_spectral_assignments),
            layout_cluster_summaries=Path(args.voyage_spectral_summaries),
            within_group_strategy="nearest_neighbor",
            sequencing_method="voyage31_global_cluster_order",
        ),
        TargetLayoutConfig(
            proposal_name="semantic_layout_nocd17",
            layout_label_system="voyage_stage2_nocd_structural_17",
            layout_cluster_assignments=nocd_assignments,
            layout_cluster_summaries=nocd_summaries,
            within_group_strategy="nearest_neighbor",
            sequencing_method="nocd17_global_cluster_order",
        ),
    ]

    for config in configs:
        inputs = load_layout_inputs(
            raw_input,
            embeddings_dir,
            claims_cluster_assignments=claims_assignments,
            claims_cluster_summaries=claims_summaries,
            layout_cluster_assignments=config.layout_cluster_assignments,
            layout_cluster_summaries=config.layout_cluster_summaries,
            layout_label_system=config.layout_label_system,
        )
        base_proposal = build_layout_proposal(inputs)
        shared_parent_order, shared_subcategory_order = build_shared_layout_group_order(
            inputs.records,
            inputs.normalized_matrix,
        )
        ordered_indices = build_global_numeric_order(
            inputs.records,
            inputs.normalized_matrix,
            shared_parent_order=shared_parent_order,
            shared_subcategory_order=shared_subcategory_order,
            within_group_strategy=config.within_group_strategy,
        )
        embedding_to_id = {record.embedding_index: record.abstract_id for record in inputs.records}
        ordered_ids = [int(embedding_to_id[int(index)]) for index in ordered_indices]
        records_by_id = {record.abstract_id: record for record in inputs.records}
        proposal = build_global_path_split_proposal(
            base_proposal,
            global_ordered_ids=ordered_ids,
            records_by_id=records_by_id,
            method_name=config.sequencing_method,
        )
        proposal["metadata"] = _metadata_for_global_group_proposal(
            proposal,
            proposal_name=config.proposal_name,
            sequencing_method=config.sequencing_method,
            within_group_strategy=config.within_group_strategy,
        )
        _write_proposal_bundle(
            output_root / config.proposal_name,
            inputs,
            proposal,
            authors_input=authors_input,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
