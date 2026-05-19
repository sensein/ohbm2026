#!/usr/bin/env python
"""Stage 6 — build the UI data package (T019).

Thin CLI wrapper around :func:`ohbm2026.ui_data.builder.build_ui_data_package`.
See specs/008-ui-rewrite/quickstart.md for the canonical invocations.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="build_ui_data.py",
        description="Build the static-JSON-shard data package consumed by the Stage 6 site.",
    )
    parser.add_argument("--corpus", required=True, type=Path)
    parser.add_argument("--withdrawn", type=Path, default=None)
    parser.add_argument("--authors", required=True, type=Path)
    parser.add_argument("--enriched", type=Path, default=None)
    parser.add_argument(
        "--references",
        type=Path,
        default=Path("data/cache/reference_metadata/openalex_resolved.json"),
        help="OpenAlex-resolved references shard (curated). Defaults to the Stage 2.1 canonical path.",
    )
    parser.add_argument("--analysis-root", dest="analysis_root", type=Path, default=None)
    parser.add_argument("--rollup", type=Path, default=None, help="Explicit Stage 4 rollup .sqlite path.")
    parser.add_argument(
        "--discover-rollup",
        dest="discover_rollup",
        action="store_true",
        help="Discover the active rollup state-key under --analysis-root.",
    )
    parser.add_argument(
        "--minilm-root",
        dest="minilm_root",
        type=Path,
        default=Path("data/outputs/embeddings/minilm"),
        help="Root of MiniLM component bundles (introduction__*/, methods__*/, …) for the int8 vector buffer.",
    )
    parser.add_argument("--minilm-bundle", dest="minilm_bundle", type=Path, default=None,
                        help="Deprecated single-bundle alias; use --minilm-root.")
    parser.add_argument("--references-yaml", dest="references_yaml", type=Path, default=None)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument(
        "--output-format",
        dest="output_format",
        default="gzip-json-shards",
        choices=[
            "gzip-json-shards",
            # The next 5 are wired up in Stage-10 Phase 3 (T019-T024).
            # Listed here so the CLI surface is stable from Phase 2 onward
            # and the bench harness can validate every choice it intends
            # to invoke, even before the emitter exists.
            "parquet-files",
            "parquet-duckdb",
            "sqlite-single",
            "duckdb-single",
            "arrow-ipc",
            # Candidate #7 — added 2026-05-18 when the single-URL deploy
            # constraint ruled out the multi-file Parquet candidates. One
            # `.parquet` file with per-table BLOB rows.
            "parquet-single",
        ],
        help=(
            "Container format for the emitted data package. "
            "`gzip-json-shards` is Stage-6 behaviour (default); the other "
            "5 are Stage-10 bench candidates whose emitters land in "
            "`src/ohbm2026/ui_data/formats/`. Pre-Phase-3, only "
            "`gzip-json-shards` is implemented."
        ),
    )
    parser.add_argument(
        "--conference",
        dest="conference_id",
        default="ohbm2026",
        help=(
            "Conference identifier baked into the manifest's `build_info` "
            "envelope (FR-206). URL-safe, lower-snake-case. Default "
            "`ohbm2026`."
        ),
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    from ohbm2026.ui_data.builder import Stage6BuildError, build_ui_data_package

    try:
        return build_ui_data_package(
            corpus_path=args.corpus,
            withdrawn_path=args.withdrawn,
            authors_path=args.authors,
            enriched_path=args.enriched,
            references_path=args.references,
            analysis_root=args.analysis_root,
            rollup=args.rollup,
            discover_rollup=args.discover_rollup,
            output_dir=args.output,
            minilm_root=args.minilm_root,
            conference_id=args.conference_id,
            output_format=args.output_format,
        )
    except Stage6BuildError as exc:
        print(f"build_ui_data.py: {exc}", file=sys.stderr)
        return 3


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
