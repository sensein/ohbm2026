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
    parser.add_argument("--references", type=Path, default=None)
    parser.add_argument("--analysis-root", dest="analysis_root", type=Path, default=None)
    parser.add_argument("--rollup", type=Path, default=None, help="Explicit Stage 4 rollup .sqlite path.")
    parser.add_argument(
        "--discover-rollup",
        dest="discover_rollup",
        action="store_true",
        help="Discover the active rollup state-key under --analysis-root.",
    )
    parser.add_argument("--minilm-bundle", dest="minilm_bundle", type=Path, default=None)
    parser.add_argument("--references-yaml", dest="references_yaml", type=Path, default=None)
    parser.add_argument("--output", required=True, type=Path)
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
        )
    except Stage6BuildError as exc:
        print(f"build_ui_data.py: {exc}", file=sys.stderr)
        return 3


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
