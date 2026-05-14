from __future__ import annotations

import argparse
import sys

from ohbm2026 import analyze as neuroscape
from ohbm2026 import (
    artifacts,
    assets,
    enrichment,
    titles,
    ui,
)
from ohbm2026.analyze import stage as analyze_stage
from ohbm2026.enrich import stage as enrich_stage
from ohbm2026.fetch import stage as fetch_stage
from ohbm2026.embed import stage as embed_stage


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

    stage2_parser = subparsers.add_parser("embed-stage2", help="Train and apply a local NeuroScape stage-2 model")
    _copy_actions(stage2_parser, neuroscape.build_stage2_parser())

    published_stage2_parser = subparsers.add_parser(
        "apply-published-stage2",
        help="Apply the published NeuroScape stage-2 model to a compatible embedding bundle",
    )
    _copy_actions(published_stage2_parser, neuroscape.build_apply_pretrained_stage2_parser())

    cluster_benchmark_parser = subparsers.add_parser(
        "cluster-benchmark",
        help="Benchmark label-independent clustering methods over a local embedding bundle",
    )
    _copy_actions(cluster_benchmark_parser, neuroscape.build_cluster_benchmark_parser())

    semantic_analysis_parser = subparsers.add_parser(
        "semantic-analysis",
        help="Build a semantic graph, communities, and cluster summaries from a local embedding bundle",
    )
    _copy_actions(semantic_analysis_parser, neuroscape.build_semantic_analysis_parser())

    umap_parser = subparsers.add_parser(
        "umap-plot",
        help="Project a local embedding bundle to 2D with UMAP and write an interactive Plotly HTML",
    )
    _copy_actions(umap_parser, neuroscape.build_umap_parser())

    projection_compare_parser = subparsers.add_parser(
        "compare-projections",
        help="Write a linked UMAP/t-SNE comparison HTML for a local embedding bundle",
    )
    _copy_actions(projection_compare_parser, neuroscape.build_projection_compare_parser())

    projection_optimize_parser = subparsers.add_parser(
        "optimize-projections",
        help="Score UMAP/t-SNE parameter sets for more separable projected clusters",
    )
    _copy_actions(projection_optimize_parser, neuroscape.build_projection_optimize_parser())

    analyze_stage2_parser = subparsers.add_parser(
        "analyze-stage2",
        help="Compatibility alias for semantic analysis on a local embedding bundle",
    )
    _copy_actions(analyze_stage2_parser, neuroscape.build_stage2_analysis_parser())

    title_audit_parser = subparsers.add_parser(
        "title-audit",
        help="Write an audit report for cleaned abstract titles",
    )
    _copy_actions(title_audit_parser, titles.build_parser())

    export_ui_parser = subparsers.add_parser(
        "export-ui",
        help="Build the static JSON data bundle for the standalone abstract search UI",
    )
    _copy_actions(export_ui_parser, ui.build_export_parser())

    build_ui_parser = subparsers.add_parser(
        "build-ui",
        help="Build the standalone static abstract search site bundle",
    )
    _copy_actions(build_ui_parser, ui.build_ui_parser())

    manifest_parser = subparsers.add_parser("write-manifest", help="Write the NeuroScape handoff manifest")
    _copy_actions(manifest_parser, neuroscape.build_manifest_parser())

    return parser


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
    if command == "embed-matrix":
        return embed_stage.main(subcommand_argv)
    if command == "analyze-matrix":
        return analyze_stage.main(subcommand_argv)
    if command == "embed-stage2":
        return neuroscape.stage2_main(subcommand_argv)
    if command == "apply-published-stage2":
        return neuroscape.apply_pretrained_stage2_main(subcommand_argv)
    if command == "cluster-benchmark":
        return neuroscape.cluster_benchmark_main(subcommand_argv)
    if command == "semantic-analysis":
        return neuroscape.semantic_analysis_main(subcommand_argv)
    if command == "umap-plot":
        return neuroscape.umap_main(subcommand_argv)
    if command == "compare-projections":
        return neuroscape.projection_compare_main(subcommand_argv)
    if command == "optimize-projections":
        return neuroscape.projection_optimize_main(subcommand_argv)
    if command == "analyze-stage2":
        return neuroscape.stage2_analysis_main(subcommand_argv)
    if command == "title-audit":
        return titles.main(subcommand_argv)
    if command == "export-ui":
        return ui.export_ui_main(subcommand_argv)
    if command == "build-ui":
        return ui.build_ui_main(subcommand_argv)
    if command == "write-manifest":
        return neuroscape.manifest_main(subcommand_argv)

    raise AssertionError(f"Unhandled command: {command}")


if __name__ == "__main__":
    raise SystemExit(main())
