from __future__ import annotations

import argparse
from pathlib import Path

from ohbm2026.layout.poster_layout import DEFAULT_CLAIMS_CLUSTER_ASSIGNMENTS, DEFAULT_CLAIMS_CLUSTER_SUMMARIES, load_layout_inputs
from ohbm2026.layout.poster_sequencing import run_advanced_global_path_experiment_from_files


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the advanced non-diffusion global-path ordering experiment"
    )
    parser.add_argument("--proposal", default="data/poster_layout/proposals/semantic_layout_voyage31/proposal.json")
    parser.add_argument("--raw-input", default="data/abstracts.json")
    parser.add_argument("--authors-input", default="data/authors.json")
    parser.add_argument("--embeddings-dir", default="data/embeddings/voyage_stage2_published")
    parser.add_argument("--claims-cluster-assignments", default=DEFAULT_CLAIMS_CLUSTER_ASSIGNMENTS)
    parser.add_argument("--claims-cluster-summaries", default=DEFAULT_CLAIMS_CLUSTER_SUMMARIES)
    parser.add_argument(
        "--layout-cluster-assignments",
        default="data/embeddings/voyage_stage2_published/clustering_benchmark_spectral/cluster_assignments.json",
    )
    parser.add_argument(
        "--layout-cluster-summaries",
        default="data/embeddings/voyage_stage2_published/clustering_benchmark_spectral/cluster_summaries.json",
    )
    parser.add_argument("--layout-label-system", default="voyage_stage2_spectral_31")
    parser.add_argument("--graph-band-width", type=int, default=5)
    parser.add_argument(
        "--output-root",
        default="experiments/2026-03-22-advanced-global-path-methods/runs/latest",
    )
    parser.add_argument(
        "--allow-existing-output",
        action="store_true",
        help="Allow writing into an existing non-empty output directory.",
    )
    return parser


def validate_output_root(output_root: Path, allow_existing_output: bool) -> None:
    if not output_root.exists():
        return
    if not output_root.is_dir():
        raise FileExistsError(f"Output root exists and is not a directory: {output_root}")
    if allow_existing_output:
        return
    if any(output_root.iterdir()):
        raise FileExistsError(
            f"Output root already exists and is not empty: {output_root}. "
            "Use a fresh run directory or pass --allow-existing-output for intentional scratch reruns."
        )


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    output_root = Path(args.output_root)
    validate_output_root(output_root, bool(args.allow_existing_output))
    inputs = load_layout_inputs(
        Path(args.raw_input),
        Path(args.embeddings_dir),
        Path(args.claims_cluster_assignments) if args.claims_cluster_assignments else None,
        Path(args.claims_cluster_summaries) if args.claims_cluster_summaries else None,
        Path(args.layout_cluster_assignments) if args.layout_cluster_assignments else None,
        Path(args.layout_cluster_summaries) if args.layout_cluster_summaries else None,
        str(args.layout_label_system),
    )
    run_advanced_global_path_experiment_from_files(
        proposal_path=Path(args.proposal),
        inputs=inputs,
        output_root=output_root,
        authors_input=Path(args.authors_input) if args.authors_input else None,
        graph_band_width=int(args.graph_band_width),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
