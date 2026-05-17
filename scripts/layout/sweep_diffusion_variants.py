from __future__ import annotations

import argparse
from pathlib import Path

from ohbm2026.layout.poster_layout import DEFAULT_CLAIMS_CLUSTER_ASSIGNMENTS, DEFAULT_CLAIMS_CLUSTER_SUMMARIES, load_layout_inputs
from ohbm2026.layout.poster_sequencing import sweep_diffusion_from_files


def _parse_int_list(value: str) -> tuple[int, ...]:
    return tuple(int(part.strip()) for part in str(value).split(",") if part.strip())


def _parse_coordinate_variants(value: str) -> tuple[tuple[int, str], ...]:
    variants: list[tuple[int, str]] = []
    for chunk in str(value).split(","):
        item = chunk.strip()
        if not item:
            continue
        if ":" not in item:
            raise ValueError(f"Expected coordinate variant like '2:pca', got {item!r}")
        dims, mode = item.split(":", 1)
        variants.append((int(dims.strip()), mode.strip()))
    return tuple(variants)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Sweep diffusion-map graph and coordinate variants against an existing proposal"
    )
    parser.add_argument(
        "--proposal",
        default="data/poster_layout/proposals/semantic_layout_voyage31/proposal.json",
    )
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
    parser.add_argument(
        "--neighbor-counts",
        default="5,10,20,40",
        help="Comma-separated k values for the weighted kNN graph.",
    )
    parser.add_argument(
        "--coordinate-variants",
        default="1:single,2:pca,3:pca,2:lexsort",
        help="Comma-separated diffusion coordinate settings like '1:single,2:pca'.",
    )
    parser.add_argument("--graph-band-width", type=int, default=5)
    parser.add_argument(
        "--output-root",
        default="data/poster_layout/sequencing_benchmarks/semantic_layout_voyage31_diffusion_sweep",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    inputs = load_layout_inputs(
        Path(args.raw_input),
        Path(args.embeddings_dir),
        Path(args.claims_cluster_assignments) if args.claims_cluster_assignments else None,
        Path(args.claims_cluster_summaries) if args.claims_cluster_summaries else None,
        Path(args.layout_cluster_assignments) if args.layout_cluster_assignments else None,
        Path(args.layout_cluster_summaries) if args.layout_cluster_summaries else None,
        str(args.layout_label_system),
    )
    sweep_diffusion_from_files(
        proposal_path=Path(args.proposal),
        inputs=inputs,
        output_root=Path(args.output_root),
        authors_input=Path(args.authors_input) if args.authors_input else None,
        neighbor_counts=_parse_int_list(args.neighbor_counts),
        coordinate_variants=_parse_coordinate_variants(args.coordinate_variants),
        graph_band_width=int(args.graph_band_width),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
