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
    parser.add_argument(
        "--proposal-listing",
        dest="proposal_listing",
        type=Path,
        default=None,
        help=(
            "Optional CSV with the program-committee proposal numbering "
            "(`data/primary/proposal_listing_block_spread_soft.csv`). Each "
            "abstract record gets a `poster_standby: {first, second}` struct "
            "with the two stand-by times from the CSV. Keyed by Oxford "
            "submission_id. Superseded by --standby-final-csv when both are "
            "provided."
        ),
    )
    parser.add_argument(
        "--standby-final-csv",
        dest="standby_final_csv",
        type=Path,
        default=Path(
            "data/primary/032626 OHBM 2026 Poster Listing_FINAL.xlsx "
            "- Poster Listing.csv"
        ),
        help=(
            "Path to the authoritative FINAL OHBM 2026 poster-listing CSV "
            "(keyed by poster_id). When this file exists, it overrides "
            "--proposal-listing for the poster_standby fields. Default points "
            "at the FINAL listing under data/primary/."
        ),
    )
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument(
        "--output-format",
        dest="output_format",
        default="parquet-single",
        choices=["parquet-single", "gzip-json-shards"],
        help=(
            "Container format for the emitted data package. "
            "`parquet-single` (default) is the canonical Stage-10 export — "
            "one `data.parquet` file with all logical tables as per-row "
            "Parquet blobs. `gzip-json-shards` is the Stage-6 legacy "
            "emitter, kept for one-off dev comparisons."
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
            proposal_listing_path=args.proposal_listing,
            standby_final_csv_path=(
                args.standby_final_csv
                if args.standby_final_csv and args.standby_final_csv.exists()
                else None
            ),
        )
    except Stage6BuildError as exc:
        print(f"build_ui_data.py: {exc}", file=sys.stderr)
        return 3


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
