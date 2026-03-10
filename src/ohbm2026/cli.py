from __future__ import annotations

import argparse
import sys

from ohbm2026 import assets, enrichment, neuroscape


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

    voyage_parser = subparsers.add_parser("embed-voyage", help="Generate Voyage embeddings")
    _copy_actions(voyage_parser, neuroscape.build_voyage_parser())

    stage2_parser = subparsers.add_parser("embed-stage2", help="Train and apply a local NeuroScape stage-2 model")
    _copy_actions(stage2_parser, neuroscape.build_stage2_parser())

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
    if command == "embed-voyage":
        return neuroscape.voyage_main(subcommand_argv)
    if command == "embed-stage2":
        return neuroscape.stage2_main(subcommand_argv)
    if command == "write-manifest":
        return neuroscape.manifest_main(subcommand_argv)

    raise AssertionError(f"Unhandled command: {command}")


if __name__ == "__main__":
    raise SystemExit(main())
