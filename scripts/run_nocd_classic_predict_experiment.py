from __future__ import annotations

import argparse
import json
from pathlib import Path

from ohbm2026.nocd_experiments import (
    annotate_community_structure_scores,
    classic_summary_markdown,
    discover_checkpoint_configs,
    discover_embedding_sources,
    load_embedding_source,
    prepare_source_artifacts,
    render_metric_heatmap,
    run_checkpoint_prediction,
    select_classic_checkpoint_config,
    write_summary_csv,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the NOCD classic checkpoint prediction experiment")
    parser.add_argument("--embeddings-root", default="data/embeddings")
    parser.add_argument("--checkpoint-dir", default="/tmp/nocd/checkpoints")
    parser.add_argument("--neighbor-count", type=int, default=20)
    parser.add_argument("--threshold", type=float, default=0.5)
    parser.add_argument("--output-root", default="experiments/2026-03-25-nocd-classic-predict/runs/latest")
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
    checkpoint_configs, _compatibility_rows = discover_checkpoint_configs(checkpoint_dir)
    classic_config = select_classic_checkpoint_config(checkpoint_configs)
    checkpoint_path = checkpoint_dir / str(classic_config["checkpoint_name"])

    source_dirs = discover_embedding_sources(embeddings_root)
    summary_rows: list[dict[str, object]] = []
    for source_dir in source_dirs:
        source = load_embedding_source(source_dir)
        source_root = output_root / source.name
        prepared = prepare_source_artifacts(
            source,
            source_root / "prepared_source",
            neighbor_count=int(args.neighbor_count),
        )
        row = run_checkpoint_prediction(
            source,
            prepared["adjacency"],
            checkpoint_path=checkpoint_path,
            output_dir=source_root / str(classic_config["model_key"]),
            output_model_key=str(classic_config["model_key"]),
            threshold=float(args.threshold),
        )
        summary_rows.append(row)

    annotate_community_structure_scores(summary_rows)
    summary_payload = {
        "experiment": "nocd_classic_predict",
        "checkpoint": str(checkpoint_path),
        "rows": summary_rows,
    }
    (output_root / "summary.json").write_text(json.dumps(summary_payload, indent=2, sort_keys=True), encoding="utf-8")
    write_summary_csv(output_root / "summary.csv", summary_rows)
    (output_root / "summary.md").write_text(
        classic_summary_markdown(summary_rows, checkpoint_path.name),
        encoding="utf-8",
    )
    source_order = [str(row["embedding_source"]) for row in summary_rows]
    render_metric_heatmap(
        summary_rows,
        model_order=[str(classic_config["model_key"])],
        source_order=source_order,
        value_key="coverage",
        output_path=output_root / "coverage_heatmap.png",
        title="NOCD classic checkpoint coverage by embedding source",
    )
    render_metric_heatmap(
        summary_rows,
        model_order=[str(classic_config["model_key"])],
        source_order=source_order,
        value_key="conductance",
        output_path=output_root / "conductance_heatmap.png",
        title="NOCD classic checkpoint conductance by embedding source",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
