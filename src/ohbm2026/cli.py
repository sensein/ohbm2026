from __future__ import annotations

import argparse
import sys

from ohbm2026 import assets, enrichment


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ohbmcli", description="Unified CLI for OHBM 2026 ingest and enrichment")
    subparsers = parser.add_subparsers(dest="command", required=True)

    ingest_parser = subparsers.add_parser("ingest", help="Fetch abstracts and figure assets from Oxford Abstracts")
    for action in assets.build_parser()._actions[1:]:
        ingest_parser._add_action(action)
    ingest_parser.set_defaults(_runner=assets.main)

    refresh_parser = subparsers.add_parser("refresh-assets", help="Refresh local figure assets from existing abstracts.json")
    for action in assets.build_parser()._actions[1:]:
        refresh_parser._add_action(action)
    refresh_parser.set_defaults(_runner=_run_refresh_assets)

    phase2_parser = subparsers.add_parser("phase2", help="Run phase 2 enrichment and embedding steps")
    for action in enrichment.build_parser()._actions[1:]:
        phase2_parser._add_action(action)
    phase2_parser.set_defaults(_runner=enrichment.main)

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
    if command == "phase2":
        return enrichment.main(subcommand_argv)

    raise AssertionError(f"Unhandled command: {command}")


if __name__ == "__main__":
    raise SystemExit(main())
