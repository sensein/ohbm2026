from __future__ import annotations

import argparse
from pathlib import Path

from ohbm2026.poster_layout import (
    PathProposalConfig,
    analyze_layout_proposal,
    build_semantic_path_proposal,
    load_layout_inputs,
    write_json,
    write_listing_csv,
    write_layout_csv,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate semantic-path layout proposals over all accepted abstracts")
    parser.add_argument("--raw-input", default="data/abstracts.json")
    parser.add_argument("--claims-embeddings-dir", default="data/embeddings/minilm_claims")
    parser.add_argument("--voyage-stage2-embeddings-dir", default="data/embeddings/voyage_stage2_published")
    parser.add_argument("--claims-cluster-assignments", default="data/embeddings/minilm_claims/clustering_benchmark_25_30/cluster_assignments.json")
    parser.add_argument("--claims-cluster-summaries", default="data/embeddings/minilm_claims/clustering_benchmark_25_30/cluster_summaries.json")
    parser.add_argument("--output-root", default="data/poster_layout/proposals")
    return parser


def _write_proposal_bundle(
    output_dir: Path,
    inputs,
    proposal: dict,
) -> None:
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
    inputs = load_layout_inputs(
        Path(args.raw_input),
        Path(args.claims_embeddings_dir),
        Path(args.claims_cluster_assignments) if args.claims_cluster_assignments else None,
        Path(args.claims_cluster_summaries) if args.claims_cluster_summaries else None,
    )

    configs = [
        (
            "semantic_path_claims",
            build_semantic_path_proposal(
                inputs,
                primary_embeddings_dir=Path(args.claims_embeddings_dir),
                config=PathProposalConfig(primary_embedding_name="claims"),
            ),
        ),
        (
            "semantic_path_voyage_stage2",
            build_semantic_path_proposal(
                inputs,
                primary_embeddings_dir=Path(args.voyage_stage2_embeddings_dir),
                config=PathProposalConfig(primary_embedding_name="voyage_stage2"),
            ),
        ),
        (
            "semantic_path_combined",
            build_semantic_path_proposal(
                inputs,
                primary_embeddings_dir=Path(args.voyage_stage2_embeddings_dir),
                secondary_embeddings_dir=Path(args.claims_embeddings_dir),
                config=PathProposalConfig(primary_embedding_name="voyage_stage2", secondary_embedding_name="claims"),
            ),
        ),
    ]

    for proposal_name, proposal in configs:
        _write_proposal_bundle(output_root / proposal_name, inputs, proposal)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
