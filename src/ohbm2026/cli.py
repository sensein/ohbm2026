from __future__ import annotations

import argparse
import sys

from ohbm2026 import assets, enrichment, neuroscape, openalex, ui


def _copy_actions(target: argparse.ArgumentParser, source: argparse.ArgumentParser) -> None:
    for action in source._actions[1:]:
        target._add_action(action)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ohbmcli", description="Unified CLI for OHBM 2026 ingest and enrichment")
    subparsers = parser.add_subparsers(dest="command", required=True)

    ingest_parser = subparsers.add_parser("ingest", help="Fetch abstracts and figure assets from Oxford Abstracts")
    _copy_actions(ingest_parser, assets.build_parser())

    refresh_parser = subparsers.add_parser("refresh-assets", help="Refresh local figure assets from existing abstracts.json")
    _copy_actions(refresh_parser, assets.build_parser())

    authors_parser = subparsers.add_parser("authors", help="Export author metadata from the local abstract database")
    _copy_actions(authors_parser, enrichment.build_authors_parser())

    enrich_parser = subparsers.add_parser("enrich", help="Build enriched abstracts from local databases")
    _copy_actions(enrich_parser, enrichment.build_enrich_parser())

    figure_parser = subparsers.add_parser("analyze-figures", help="Analyze local figures with Ollama")
    _copy_actions(figure_parser, enrichment.build_figure_analysis_parser())

    minilm_parser = subparsers.add_parser("embed-minilm", help="Generate local MiniLM embeddings")
    _copy_actions(minilm_parser, neuroscape.build_minilm_parser())

    hf_parser = subparsers.add_parser(
        "embed-hf",
        help="Generate local Hugging Face sentence-transformer embeddings",
    )
    _copy_actions(hf_parser, neuroscape.build_hf_parser())

    voyage_parser = subparsers.add_parser("embed-voyage", help="Generate Voyage embeddings")
    _copy_actions(voyage_parser, neuroscape.build_voyage_parser())

    openai_parser = subparsers.add_parser("embed-openai", help="Generate OpenAI embeddings")
    _copy_actions(openai_parser, neuroscape.build_openai_parser())

    stage2_parser = subparsers.add_parser("embed-stage2", help="Train and apply a local NeuroScape stage-2 model")
    _copy_actions(stage2_parser, neuroscape.build_stage2_parser())

    published_stage2_parser = subparsers.add_parser(
        "apply-published-stage2",
        help="Apply the published NeuroScape stage-2 model to a compatible embedding bundle",
    )
    _copy_actions(published_stage2_parser, neuroscape.build_apply_pretrained_stage2_parser())

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

    references_parser = subparsers.add_parser(
        "reference-metadata",
        help="Resolve abstract references against OpenAlex and persist citation metadata",
    )
    _copy_actions(references_parser, openalex.build_parser())

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
    if command == "ingest":
        return assets.main(subcommand_argv)
    if command == "refresh-assets":
        return _run_refresh_assets(subcommand_argv)
    if command == "authors":
        return enrichment.authors_main(subcommand_argv)
    if command == "enrich":
        return enrichment.enrich_main(subcommand_argv)
    if command == "analyze-figures":
        return enrichment.analyze_figures_main(subcommand_argv)
    if command == "embed-minilm":
        return neuroscape.minilm_main(subcommand_argv)
    if command == "embed-hf":
        return neuroscape.hf_main(subcommand_argv)
    if command == "embed-voyage":
        return neuroscape.voyage_main(subcommand_argv)
    if command == "embed-openai":
        return neuroscape.openai_main(subcommand_argv)
    if command == "embed-stage2":
        return neuroscape.stage2_main(subcommand_argv)
    if command == "apply-published-stage2":
        return neuroscape.apply_pretrained_stage2_main(subcommand_argv)
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
    if command == "reference-metadata":
        return openalex.main(subcommand_argv)
    if command == "export-ui":
        return ui.export_ui_main(subcommand_argv)
    if command == "build-ui":
        return ui.build_ui_main(subcommand_argv)
    if command == "write-manifest":
        return neuroscape.manifest_main(subcommand_argv)

    raise AssertionError(f"Unhandled command: {command}")


if __name__ == "__main__":
    raise SystemExit(main())
