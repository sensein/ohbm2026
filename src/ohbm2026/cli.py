from __future__ import annotations

import argparse
import sys

from ohbm2026 import (
    artifacts,
    assets,
    titles,
)
from ohbm2026.analyze import clusters as analyze_clusters
from ohbm2026.analyze import projections as analyze_projections
from ohbm2026.analyze import stage as analyze_stage
from ohbm2026.embed import neuroscape as embed_neuroscape
from ohbm2026.enrich import stage as enrich_stage
from ohbm2026.fetch import stage as fetch_stage
from ohbm2026.embed import stage as embed_stage
from ohbm2026.atlas_package import cli as atlas_cli
from ohbm2026.atlas_hosting import cli as atlas_hosting_cli


def _copy_actions(target: argparse.ArgumentParser, source: argparse.ArgumentParser) -> None:
    for action in source._actions[1:]:
        target._add_action(action)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ohbmcli",
        description="Unified CLI for OHBM 2026 ingest and enrichment",
        epilog=(
            f"Local artifacts are organized under {artifacts.INPUTS_ROOT}, "
            f"{artifacts.CACHE_ROOT}, {artifacts.OUTPUTS_ROOT}, and optional publish mirrors under {artifacts.EXPORT_ROOT}."
        ),
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    fetch_abstracts_parser = subparsers.add_parser(
        "fetch-abstracts",
        help="Stage 1 (accepted): fetch accepted OHBM 2026 abstracts + persist GraphQL schema",
    )
    _copy_actions(fetch_abstracts_parser, fetch_stage._build_parser())

    fetch_withdrawn_parser = subparsers.add_parser(
        "fetch-withdrawn",
        help="Stage 1 (withdrawn): fetch withdrawn-decision submissions into a separate corpus",
    )
    _copy_actions(fetch_withdrawn_parser, fetch_stage._build_parser())

    refresh_parser = subparsers.add_parser("refresh-assets", help="Refresh local figure assets from an existing normalized abstracts dataset")
    _copy_actions(refresh_parser, assets.build_parser())

    enrich_abstracts_parser = subparsers.add_parser(
        "enrich-abstracts",
        help="Stage 2: enrich the accepted corpus (figures, claims, references)",
    )
    _copy_actions(enrich_abstracts_parser, enrich_stage._build_parser())

    build_atlas_package_parser = subparsers.add_parser(
        "build-atlas-package",
        help="Stage 15: build neuroscape.parquet + atlas.parquet from the NeuroScape v1.0.1 release + voyage_stage2_published recipe",
    )
    _copy_actions(build_atlas_package_parser, atlas_cli.build_parser())

    upload_atlas_package_parser = subparsers.add_parser(
        "upload-atlas-package",
        help="Stage 20: upload the built atlas-package parquets to Cloudflare R2 under content-hashed immutable keys",
    )
    _copy_actions(upload_atlas_package_parser, atlas_hosting_cli.build_upload_parser())

    embed_matrix_parser = subparsers.add_parser(
        "embed-matrix",
        help="Stage 3: generate the multi-model embeddings matrix (per-component bundles)",
    )
    _copy_actions(embed_matrix_parser, embed_stage.build_parser())

    analyze_matrix_parser = subparsers.add_parser(
        "analyze-matrix",
        help="Stage 4: run the (model, input, kind) analysis matrix and write the canonical rollup",
    )
    _copy_actions(analyze_matrix_parser, analyze_stage.build_parser())

    analyze_umap_project_parser = subparsers.add_parser(
        "analyze-umap-project",
        help="Stage 4: project new vectors into an existing fitted UMAP bundle (US2)",
    )
    analyze_umap_project_parser.add_argument(
        "--fitted-bundle", type=str, required=True,
        help="Path to a Stage 4 projections bundle directory.",
    )
    analyze_umap_project_parser.add_argument(
        "--input-vectors", type=str, required=True,
        help="Path to a .npy file of shape (m, d) — new vectors to project.",
    )
    analyze_umap_project_parser.add_argument(
        "--algorithm",
        choices=["native", "knn_weighted", "parametric"],
        required=True,
    )
    analyze_umap_project_parser.add_argument(
        "--dim", type=int, default=2, choices=[2, 3],
    )
    analyze_umap_project_parser.add_argument(
        "--knn-k", type=int, default=15,
    )
    analyze_umap_project_parser.add_argument(
        "--knn-temperature", type=float, default=1.0,
    )
    analyze_umap_project_parser.add_argument(
        "--output", type=str, required=True,
        help="Path to write the projected coordinates as a .npy file.",
    )

    stage2_parser = subparsers.add_parser("embed-stage2", help="Train and apply a local NeuroScape stage-2 model")
    _copy_actions(stage2_parser, embed_neuroscape.build_stage2_parser())

    published_stage2_parser = subparsers.add_parser(
        "apply-published-stage2",
        help="Apply the published NeuroScape stage-2 model to a compatible embedding bundle",
    )
    _copy_actions(published_stage2_parser, embed_neuroscape.build_apply_pretrained_stage2_parser())

    cluster_benchmark_parser = subparsers.add_parser(
        "cluster-benchmark",
        help="Benchmark label-independent clustering methods over a local embedding bundle",
    )
    _copy_actions(cluster_benchmark_parser, analyze_clusters.build_cluster_benchmark_parser())

    semantic_analysis_parser = subparsers.add_parser(
        "semantic-analysis",
        help="Build a semantic graph, communities, and cluster summaries from a local embedding bundle",
    )
    _copy_actions(semantic_analysis_parser, analyze_clusters.build_semantic_analysis_parser())

    umap_parser = subparsers.add_parser(
        "umap-plot",
        help="Project a local embedding bundle to 2D with UMAP and write an interactive Plotly HTML",
    )
    _copy_actions(umap_parser, analyze_projections.build_umap_parser())

    projection_compare_parser = subparsers.add_parser(
        "compare-projections",
        help="Write a linked UMAP/t-SNE comparison HTML for a local embedding bundle",
    )
    _copy_actions(projection_compare_parser, analyze_projections.build_projection_compare_parser())

    projection_optimize_parser = subparsers.add_parser(
        "optimize-projections",
        help="Score UMAP/t-SNE parameter sets for more separable projected clusters",
    )
    _copy_actions(projection_optimize_parser, analyze_projections.build_projection_optimize_parser())

    analyze_stage2_parser = subparsers.add_parser(
        "analyze-stage2",
        help="Compatibility alias for semantic analysis on a local embedding bundle",
    )
    _copy_actions(analyze_stage2_parser, analyze_clusters.build_stage2_analysis_parser())

    title_audit_parser = subparsers.add_parser(
        "title-audit",
        help="Write an audit report for cleaned abstract titles",
    )
    _copy_actions(title_audit_parser, titles.build_parser())

    manifest_parser = subparsers.add_parser("write-manifest", help="Write the NeuroScape handoff manifest")
    _copy_actions(manifest_parser, embed_neuroscape.build_manifest_parser())

    book_parser = subparsers.add_parser(
        "book",
        help="Compose the Book of Abstracts (md + pdf + docx) from Stage-1 artefacts",
    )
    from ohbm2026.book.cli import _build_parser as _book_build_parser

    _copy_actions(book_parser, _book_build_parser())

    return parser


def _run_analyze_umap_project(argv: list[str]) -> int:
    """Project new vectors into an existing fitted UMAP bundle (US2)."""
    import argparse as _argparse
    import json as _json

    import numpy as _np

    from ohbm2026.analyze.umap import project_into_umap
    from ohbm2026.exceptions import (
        AnalysisError,
        ProjectionDimensionMismatch,
        UnsupportedProjectionAlgorithm,
    )

    parser = _argparse.ArgumentParser(prog="ohbmcli analyze-umap-project")
    parser.add_argument("--fitted-bundle", type=str, required=True)
    parser.add_argument("--input-vectors", type=str, required=True)
    parser.add_argument(
        "--algorithm", choices=["native", "knn_weighted", "parametric"], required=True
    )
    parser.add_argument("--dim", type=int, default=2, choices=[2, 3])
    parser.add_argument("--knn-k", type=int, default=15)
    parser.add_argument("--knn-temperature", type=float, default=1.0)
    parser.add_argument("--output", type=str, required=True)
    args = parser.parse_args(argv)

    from pathlib import Path as _Path

    new_vectors = _np.load(args.input_vectors)
    try:
        coords = project_into_umap(
            new_vectors,
            _Path(args.fitted_bundle),
            algorithm=args.algorithm,
            dim=args.dim,
            knn_k=args.knn_k,
            knn_temperature=args.knn_temperature,
        )
    except (UnsupportedProjectionAlgorithm, ProjectionDimensionMismatch) as e:
        print(_json.dumps({"event": "project_into_umap_error", "error": str(e), "type": e.__class__.__name__}))
        return 2
    except AnalysisError as e:
        print(_json.dumps({"event": "project_into_umap_error", "error": str(e), "type": "AnalysisError"}))
        return 2

    out_path = _Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    _np.save(out_path, coords)
    print(_json.dumps({
        "event": "project_into_umap_complete",
        "n_rows": int(coords.shape[0]),
        "dim": int(coords.shape[1]),
        "output_path": str(out_path),
    }))
    return 0


def _run_refresh_assets(argv: list[str]) -> int:
    if "--refresh-assets-from-existing-db" not in argv:
        argv = list(argv) + ["--refresh-assets-from-existing-db"]
    return assets.main(argv)


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = build_parser()
    parser.parse_args(argv)
    if not argv:
        raise AssertionError("argparse should exit before reaching this branch")

    command, subcommand_argv = argv[0], argv[1:]
    if command == "fetch-abstracts":
        return fetch_stage.main(subcommand_argv)
    if command == "fetch-withdrawn":
        # Force --corpus-kind=withdrawn unless the operator passed it
        # explicitly to something else.
        if "--corpus-kind" not in subcommand_argv:
            subcommand_argv = list(subcommand_argv) + ["--corpus-kind", "withdrawn"]
        return fetch_stage.main(subcommand_argv)
    if command == "refresh-assets":
        return _run_refresh_assets(subcommand_argv)
    if command == "enrich-abstracts":
        return enrich_stage.main(subcommand_argv)
    if command == "build-atlas-package":
        return atlas_cli.main(subcommand_argv)
    if command == "upload-atlas-package":
        return atlas_hosting_cli.upload_main(subcommand_argv)
    if command == "embed-matrix":
        return embed_stage.main(subcommand_argv)
    if command == "analyze-matrix":
        return analyze_stage.main(subcommand_argv)
    if command == "analyze-umap-project":
        return _run_analyze_umap_project(subcommand_argv)
    if command == "embed-stage2":
        return embed_neuroscape.stage2_main(subcommand_argv)
    if command == "apply-published-stage2":
        return embed_neuroscape.apply_pretrained_stage2_main(subcommand_argv)
    if command == "cluster-benchmark":
        return analyze_clusters.cluster_benchmark_main(subcommand_argv)
    if command == "semantic-analysis":
        return analyze_clusters.semantic_analysis_main(subcommand_argv)
    if command == "umap-plot":
        return analyze_projections.umap_main(subcommand_argv)
    if command == "compare-projections":
        return analyze_projections.projection_compare_main(subcommand_argv)
    if command == "optimize-projections":
        return analyze_projections.projection_optimize_main(subcommand_argv)
    if command == "analyze-stage2":
        return analyze_clusters.stage2_analysis_main(subcommand_argv)
    if command == "title-audit":
        return titles.main(subcommand_argv)
    if command == "write-manifest":
        return embed_neuroscape.manifest_main(subcommand_argv)
    if command == "book":
        from ohbm2026.book.cli import main as book_main

        return book_main(subcommand_argv)

    raise AssertionError(f"Unhandled command: {command}")


if __name__ == "__main__":
    raise SystemExit(main())
