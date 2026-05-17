"""CLI front-ends for the static-UI export pipeline.

`export_ui_main` builds the JSON-only bundle; `build_ui_main` additionally
copies the HTML/JS shell and publishes it. Both delegate to
`ohbm2026.ui.payload.build_ui_payload` (or, when `--analysis-rollup` is
supplied, `build_ui_payload_from_stage4`).

Lifted out of the monolithic `src/ohbm2026/ui.py` as part of Stage 5
package reorganization (specs/007-package-reorg/ US3). Trunk module:
imports from `ohbm2026.ui.payload` only.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from ohbm2026.ui.payload import (
    DEFAULT_CLAIMS_CLUSTER_DIR,
    DEFAULT_CLUSTER_15_DIR,
    DEFAULT_CLUSTER_21_DIR,
    DEFAULT_CLUSTER_25_DIR,
    DEFAULT_CLUSTER_SPECTRAL_DIR,
    DEFAULT_ENRICHED_INPUT,
    DEFAULT_EXPORT_OUTPUT,
    DEFAULT_IMAGE_ANALYSES_INPUT,
    DEFAULT_NEIGHBORS_INPUT,
    DEFAULT_PHENOMENA_THEORIES_INPUT,
    DEFAULT_PUBLISH_OUTPUT,
    DEFAULT_RAW_INPUT,
    DEFAULT_REFERENCES_INPUT,
    DEFAULT_SEMANTIC_METADATA_INPUT,
    DEFAULT_SEMANTIC_VECTORS_INPUT,
    DEFAULT_SITE_OUTPUT,
    DEFAULT_SITE_SOURCE,
    DEFAULT_UMAP_INPUT,
    build_ui_payload,
    build_ui_payload_from_stage4,
    copy_ui_assets,
    default_export_output_dir,
    default_site_output_dir,
    export_ui_bundle,
    publish_ui_bundle,
)


def _cli_option_present(argv: list[str] | None, option: str) -> bool:
    return argv is not None and option in argv


def build_export_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Export a static JSON bundle for the OHBM abstract search UI")
    parser.add_argument("--raw-input", default=DEFAULT_RAW_INPUT)
    parser.add_argument("--enriched-input", default=DEFAULT_ENRICHED_INPUT)
    parser.add_argument("--references-input", default=DEFAULT_REFERENCES_INPUT)
    parser.add_argument("--image-analyses-input", default=DEFAULT_IMAGE_ANALYSES_INPUT)
    parser.add_argument("--phenomena-theories-input", default=DEFAULT_PHENOMENA_THEORIES_INPUT)
    parser.add_argument("--neighbors-input", default=DEFAULT_NEIGHBORS_INPUT)
    parser.add_argument("--cluster-15-dir", default=DEFAULT_CLUSTER_15_DIR)
    parser.add_argument("--cluster-21-dir", default=DEFAULT_CLUSTER_21_DIR)
    parser.add_argument("--cluster-25-dir", default=DEFAULT_CLUSTER_25_DIR)
    parser.add_argument("--spectral-cluster-dir", default=DEFAULT_CLUSTER_SPECTRAL_DIR)
    parser.add_argument("--claims-cluster-dir", default=DEFAULT_CLAIMS_CLUSTER_DIR)
    parser.add_argument("--semantic-vectors-input", default=DEFAULT_SEMANTIC_VECTORS_INPUT)
    parser.add_argument("--semantic-metadata-input", default=DEFAULT_SEMANTIC_METADATA_INPUT)
    parser.add_argument("--umap-input", default=DEFAULT_UMAP_INPUT)
    parser.add_argument("--output-dir", default=DEFAULT_EXPORT_OUTPUT)
    parser.add_argument("--top-neighbors", type=int, default=8)
    parser.add_argument(
        "--analysis-rollup",
        default=None,
        help="Path to data/outputs/analysis/annotations__<state-key>.sqlite. "
             "When set, the exporter uses the canonical Stage 4 rollup + "
             "per-bundle topics.json instead of the legacy cluster-dir scan.",
    )
    parser.add_argument(
        "--analysis-root",
        default="data/outputs/analysis",
        help="Root of the Stage 4 output tree (default: data/outputs/analysis). "
             "Only consulted when --analysis-rollup is set.",
    )
    return parser


def export_ui_main(argv: list[str] | None = None) -> int:
    raw_argv = list(argv) if argv is not None else None
    args = build_export_parser().parse_args(argv)
    output_dir = (
        Path(args.output_dir)
        if _cli_option_present(raw_argv, "--output-dir")
        else default_export_output_dir(
            raw_input=Path(args.raw_input),
            enriched_input=Path(args.enriched_input),
            references_input=Path(args.references_input),
            image_analyses_input=Path(args.image_analyses_input),
            neighbors_input=Path(args.neighbors_input),
            semantic_metadata_input=Path(args.semantic_metadata_input),
            umap_input=Path(args.umap_input),
            top_neighbors=args.top_neighbors,
        )
    )
    if args.analysis_rollup is not None:
        payload = build_ui_payload_from_stage4(
            raw_input=Path(args.raw_input),
            enriched_input=Path(args.enriched_input),
            rollup_sqlite=Path(args.analysis_rollup),
            analysis_root=Path(args.analysis_root),
        )
    else:
        payload = build_ui_payload(
            raw_input=Path(args.raw_input),
            enriched_input=Path(args.enriched_input),
            references_input=Path(args.references_input),
            image_analyses_input=Path(args.image_analyses_input),
            phenomena_theories_input=Path(args.phenomena_theories_input),
            neighbors_input=Path(args.neighbors_input),
            cluster_15_dir=Path(args.cluster_15_dir),
            cluster_21_dir=Path(args.cluster_21_dir),
            cluster_25_dir=Path(args.cluster_25_dir),
            spectral_cluster_dir=Path(args.spectral_cluster_dir),
            claims_cluster_dir=Path(args.claims_cluster_dir),
            semantic_vectors_input=Path(args.semantic_vectors_input),
            semantic_metadata_input=Path(args.semantic_metadata_input),
            umap_input=Path(args.umap_input),
            top_neighbors=args.top_neighbors,
        )
    export_ui_bundle(output_dir, payload)
    print(
        json.dumps(
            {
                "output_dir": str(output_dir),
                "abstract_count": payload["manifest"]["abstract_count"],
                "top_neighbors": args.top_neighbors,
                "source": payload["manifest"].get("source", "legacy"),
            },
            indent=2,
        )
    )
    return 0


def build_ui_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build the standalone static OHBM abstract search UI")
    parser.add_argument("--raw-input", default=DEFAULT_RAW_INPUT)
    parser.add_argument("--enriched-input", default=DEFAULT_ENRICHED_INPUT)
    parser.add_argument("--references-input", default=DEFAULT_REFERENCES_INPUT)
    parser.add_argument("--image-analyses-input", default=DEFAULT_IMAGE_ANALYSES_INPUT)
    parser.add_argument("--phenomena-theories-input", default=DEFAULT_PHENOMENA_THEORIES_INPUT)
    parser.add_argument("--neighbors-input", default=DEFAULT_NEIGHBORS_INPUT)
    parser.add_argument("--cluster-15-dir", default=DEFAULT_CLUSTER_15_DIR)
    parser.add_argument("--cluster-21-dir", default=DEFAULT_CLUSTER_21_DIR)
    parser.add_argument("--cluster-25-dir", default=DEFAULT_CLUSTER_25_DIR)
    parser.add_argument("--spectral-cluster-dir", default=DEFAULT_CLUSTER_SPECTRAL_DIR)
    parser.add_argument("--claims-cluster-dir", default=DEFAULT_CLAIMS_CLUSTER_DIR)
    parser.add_argument("--semantic-vectors-input", default=DEFAULT_SEMANTIC_VECTORS_INPUT)
    parser.add_argument("--semantic-metadata-input", default=DEFAULT_SEMANTIC_METADATA_INPUT)
    parser.add_argument("--umap-input", default=DEFAULT_UMAP_INPUT)
    parser.add_argument("--top-neighbors", type=int, default=8)
    parser.add_argument("--source-dir", default=DEFAULT_SITE_SOURCE)
    parser.add_argument("--site-output-dir", default=DEFAULT_SITE_OUTPUT)
    parser.add_argument("--publish-dir", default=DEFAULT_PUBLISH_OUTPUT)
    return parser


def build_ui_main(argv: list[str] | None = None) -> int:
    raw_argv = list(argv) if argv is not None else None
    args = build_ui_parser().parse_args(argv)
    site_output_dir = (
        Path(args.site_output_dir)
        if _cli_option_present(raw_argv, "--site-output-dir")
        else default_site_output_dir(
            raw_input=Path(args.raw_input),
            enriched_input=Path(args.enriched_input),
            references_input=Path(args.references_input),
            image_analyses_input=Path(args.image_analyses_input),
            neighbors_input=Path(args.neighbors_input),
            semantic_metadata_input=Path(args.semantic_metadata_input),
            umap_input=Path(args.umap_input),
            top_neighbors=args.top_neighbors,
        )
    )
    copy_ui_assets(Path(args.source_dir), site_output_dir)
    payload = build_ui_payload(
        raw_input=Path(args.raw_input),
        enriched_input=Path(args.enriched_input),
        references_input=Path(args.references_input),
        image_analyses_input=Path(args.image_analyses_input),
        phenomena_theories_input=Path(args.phenomena_theories_input),
        neighbors_input=Path(args.neighbors_input),
        cluster_15_dir=Path(args.cluster_15_dir),
        cluster_21_dir=Path(args.cluster_21_dir),
        cluster_25_dir=Path(args.cluster_25_dir),
        spectral_cluster_dir=Path(args.spectral_cluster_dir),
        claims_cluster_dir=Path(args.claims_cluster_dir),
        semantic_vectors_input=Path(args.semantic_vectors_input),
        semantic_metadata_input=Path(args.semantic_metadata_input),
        umap_input=Path(args.umap_input),
        top_neighbors=args.top_neighbors,
    )
    export_ui_bundle(site_output_dir / "data", payload)
    publish_dir = (
        Path(args.publish_dir)
        if _cli_option_present(raw_argv, "--publish-dir") or not _cli_option_present(raw_argv, "--site-output-dir")
        else None
    )
    if publish_dir is not None:
        publish_ui_bundle(site_output_dir, publish_dir)
    print(
        json.dumps(
            {
                "site_output_dir": str(site_output_dir),
                "publish_dir": str(publish_dir) if publish_dir is not None else None,
                "abstract_count": payload["manifest"]["abstract_count"],
            },
            indent=2,
        )
    )
    return 0
