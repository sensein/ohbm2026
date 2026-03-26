from __future__ import annotations

import argparse
import json
from pathlib import Path

from ohbm2026.nocd_experiments import (
    annotate_community_structure_scores,
    checkpoint_sweep_summary_markdown,
    discover_checkpoint_configs,
    discover_embedding_sources,
    load_embedding_source,
    prepare_source_artifacts,
    render_metric_heatmap,
    run_checkpoint_prediction,
    write_summary_csv,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the NOCD pretrained checkpoint sweep experiment")
    parser.add_argument("--embeddings-root", default="data/embeddings")
    parser.add_argument("--checkpoint-dir", default="/tmp/nocd/checkpoints")
    parser.add_argument("--neighbor-count", type=int, default=20)
    parser.add_argument("--threshold", type=float, default=0.5)
    parser.add_argument("--output-root", default="experiments/2026-03-25-nocd-checkpoint-sweep/runs/latest")
    parser.add_argument("--allow-existing-output", action="store_true")
    return parser


def validate_output_root(output_root: Path, allow_existing_output: bool) -> None:
    if not output_root.exists():
        return
    if not output_root.is_dir():
        raise FileExistsError(f"Output root exists and is not a directory: {output_root}")
    if allow_existing_output:
        return
    if any(output_root.iterdir()):
        raise FileExistsError(f"Output root already exists and is not empty: {output_root}")


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    output_root = Path(args.output_root)
    validate_output_root(output_root, bool(args.allow_existing_output))
    output_root.mkdir(parents=True, exist_ok=True)

    embeddings_root = Path(args.embeddings_root)
    checkpoint_dir = Path(args.checkpoint_dir)
    checkpoint_configs, compatibility_templates = discover_checkpoint_configs(checkpoint_dir)
    if not checkpoint_configs:
        raise FileNotFoundError(f"No compatible NOCD checkpoints were discovered in {checkpoint_dir}")
    source_dirs = discover_embedding_sources(embeddings_root)
    summary_rows: list[dict[str, object]] = []
    compatibility_rows: list[dict[str, object]] = []

    for source_dir in source_dirs:
        source = load_embedding_source(source_dir)
        source_root = output_root / source.name
        prepared = prepare_source_artifacts(
            source,
            source_root / "prepared_source",
            neighbor_count=int(args.neighbor_count),
        )
        feature_dim = int(source.matrix.shape[1])
        for config in compatibility_templates:
            compatibility_rows.append(
                {
                    "embedding_source": source.name,
                    "feature_dim": feature_dim,
                    **config,
                }
            )
        for config in checkpoint_configs:
            checkpoint_path = checkpoint_dir / str(config["checkpoint_name"])
            row = run_checkpoint_prediction(
                source,
                prepared["adjacency"],
                checkpoint_path=checkpoint_path,
                output_dir=source_root / str(config["model_key"]),
                output_model_key=str(config["model_key"]),
                threshold=float(args.threshold),
            )
            row["checkpoint_name"] = str(config["checkpoint_name"])
            row["degenerate_single_community"] = bool(int(row["nonempty_community_count"]) <= 1)
            summary_rows.append(row)

    annotate_community_structure_scores(summary_rows)
    payload = {
        "experiment": "nocd_checkpoint_sweep",
        "checkpoint_dir": str(checkpoint_dir),
        "rows": summary_rows,
        "compatibility": compatibility_rows,
    }
    (output_root / "summary.json").write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    (output_root / "compatibility.json").write_text(
        json.dumps({"rows": compatibility_rows}, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    write_summary_csv(output_root / "summary.csv", summary_rows)
    write_summary_csv(output_root / "compatibility.csv", compatibility_rows)
    (output_root / "summary.md").write_text(checkpoint_sweep_summary_markdown(summary_rows), encoding="utf-8")
    source_order = sorted({str(row["embedding_source"]) for row in summary_rows})
    model_order = [str(config["model_key"]) for config in checkpoint_configs]
    render_metric_heatmap(
        summary_rows,
        model_order=model_order,
        source_order=source_order,
        value_key="coverage",
        output_path=output_root / "coverage_heatmap.png",
        title="NOCD checkpoint sweep coverage",
    )
    render_metric_heatmap(
        summary_rows,
        model_order=model_order,
        source_order=source_order,
        value_key="conductance",
        output_path=output_root / "conductance_heatmap.png",
        title="NOCD checkpoint sweep conductance",
    )
    render_metric_heatmap(
        summary_rows,
        model_order=model_order,
        source_order=source_order,
        value_key="density",
        output_path=output_root / "density_heatmap.png",
        title="NOCD checkpoint sweep density",
    )
    render_metric_heatmap(
        summary_rows,
        model_order=model_order,
        source_order=source_order,
        value_key="clustering_coefficient",
        output_path=output_root / "clustering_heatmap.png",
        title="NOCD checkpoint sweep clustering coefficient",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
