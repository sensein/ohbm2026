from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path

from ohbm2026.poster_layout import (
    OptimizationWeights,
    analyze_layout_proposal,
    build_layout_proposal,
    load_layout_inputs,
    write_json,
    write_listing_csv,
    write_layout_csv,
)


@dataclass(frozen=True)
class SemanticLayoutConfig:
    proposal_name: str
    embeddings_dir: Path
    layout_cluster_assignments: Path
    layout_cluster_summaries: Path
    layout_label_system: str
    weights: OptimizationWeights


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate semantic-cluster-driven layout proposals")
    parser.add_argument("--raw-input", default="data/abstracts.json")
    parser.add_argument("--claims-cluster-assignments", default="data/embeddings/minilm_claims/clustering_benchmark_25_30/cluster_assignments.json")
    parser.add_argument("--claims-cluster-summaries", default="data/embeddings/minilm_claims/clustering_benchmark_25_30/cluster_summaries.json")
    parser.add_argument("--output-root", default="data/poster_layout/proposals")
    return parser


def _write_proposal_bundle(output_dir: Path, inputs, proposal: dict) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "proposal.json", proposal)
    write_layout_csv(output_dir / "proposal.csv", proposal)
    write_listing_csv(output_dir / "proposal_listing.csv", proposal, authors_input=Path("data/authors.json"))
    write_json(output_dir / "proposal_session_summaries.json", proposal.get("session_summaries", {}))
    analysis = analyze_layout_proposal(inputs, proposal)
    write_json(output_dir / "analysis.json", analysis)
    write_json(output_dir / "session_summaries.json", analysis.get("session_analysis", {}))


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    output_root = Path(args.output_root)
    claims_assignments = Path(args.claims_cluster_assignments) if args.claims_cluster_assignments else None
    claims_summaries = Path(args.claims_cluster_summaries) if args.claims_cluster_summaries else None
    semantic_weights = OptimizationWeights(
        exact_session_weight=3.0,
        parent_session_weight=0.0,
        exact_block_weight=2.25,
        parent_block_weight=0.0,
        claims_session_weight=0.0,
        claims_block_weight=0.0,
        fill_weight=0.75,
    )

    configs = [
        SemanticLayoutConfig(
            proposal_name="semantic_layout_voyage25",
            embeddings_dir=Path("data/embeddings/voyage_stage2_published"),
            layout_cluster_assignments=Path("data/embeddings/voyage_stage2_published/clustering_benchmark/cluster_assignments.json"),
            layout_cluster_summaries=Path("data/embeddings/voyage_stage2_published/clustering_benchmark/cluster_summaries.json"),
            layout_label_system="voyage_stage2_kmeans_25",
            weights=semantic_weights,
        ),
        SemanticLayoutConfig(
            proposal_name="semantic_layout_voyage31",
            embeddings_dir=Path("data/embeddings/voyage_stage2_published"),
            layout_cluster_assignments=Path("data/embeddings/voyage_stage2_published/clustering_benchmark_spectral/cluster_assignments.json"),
            layout_cluster_summaries=Path("data/embeddings/voyage_stage2_published/clustering_benchmark_spectral/cluster_summaries.json"),
            layout_label_system="voyage_stage2_spectral_31",
            weights=semantic_weights,
        ),
        SemanticLayoutConfig(
            proposal_name="semantic_layout_claims28",
            embeddings_dir=Path("data/embeddings/minilm_claims"),
            layout_cluster_assignments=Path("data/embeddings/minilm_claims/clustering_benchmark_25_30/cluster_assignments.json"),
            layout_cluster_summaries=Path("data/embeddings/minilm_claims/clustering_benchmark_25_30/cluster_summaries.json"),
            layout_label_system="minilm_claims_kmeans_28",
            weights=semantic_weights,
        ),
    ]

    for config in configs:
        inputs = load_layout_inputs(
            Path(args.raw_input),
            config.embeddings_dir,
            claims_cluster_assignments=claims_assignments,
            claims_cluster_summaries=claims_summaries,
            layout_cluster_assignments=config.layout_cluster_assignments,
            layout_cluster_summaries=config.layout_cluster_summaries,
            layout_label_system=config.layout_label_system,
        )
        proposal = build_layout_proposal(inputs, weights=config.weights)
        _write_proposal_bundle(output_root / config.proposal_name, inputs, proposal)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
