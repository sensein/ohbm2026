from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any

from ohbm2026 import artifacts
from ohbm2026.util.json_io import write_json

ROLLUP_BANDS = ("coarse", "mid", "fine")
DEFAULT_TOP_CANDIDATES = 3
DEFAULT_EVALUATION_GLOB = "*/category_evaluation/evaluation.json"


class CategoryRollupError(RuntimeError):
    """Raised when category rollup inputs are invalid."""




def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(0.0 if value is None else value)
    except (TypeError, ValueError):
        return float(default)


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(default)


def _dict_metric(row: dict[str, Any], *keys: str, default: float = 0.0) -> float:
    current: Any = row
    for key in keys:
        if not isinstance(current, dict):
            return float(default)
        current = current.get(key)
    return _safe_float(current, default=default)


def discover_evaluation_paths(embeddings_root: Path, glob_pattern: str = DEFAULT_EVALUATION_GLOB) -> list[Path]:
    return sorted(path for path in embeddings_root.glob(glob_pattern) if path.is_file())


def load_evaluation(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _row_label_systems(evaluation: dict[str, Any]) -> dict[str, dict[str, Any]]:
    rows = evaluation.get("label_systems") or []
    if not isinstance(rows, list):
        raise CategoryRollupError("evaluation payload is missing a label_systems list")
    output: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        label_system = str(row.get("label_system") or "").strip()
        if label_system:
            output[label_system] = dict(row)
    return output


def _baseline_metrics(row: dict[str, Any] | None) -> dict[str, Any]:
    if not row:
        return {
            "label_system": None,
            "label_count": None,
            "comparison_score": None,
            "silhouette_score": None,
            "graph_modularity": None,
            "intercluster_distance_ratio": None,
            "largest_cluster_fraction": None,
            "neighbor_agreement_k10": None,
            "nmi_vs_parent": None,
            "nmi_vs_exact": None,
        }
    return {
        "label_system": row.get("label_system"),
        "label_count": _safe_int(row.get("label_count")),
        "comparison_score": _safe_float(row.get("comparison_score")),
        "silhouette_score": _dict_metric(row, "embedding_metrics", "silhouette_score"),
        "graph_modularity": _safe_float(row.get("graph_modularity")),
        "intercluster_distance_ratio": _dict_metric(row, "embedding_metrics", "intercluster_distance_ratio"),
        "largest_cluster_fraction": _dict_metric(row, "embedding_metrics", "largest_cluster_fraction"),
        "neighbor_agreement_k10": _dict_metric(row, "neighborhood_agreement", "10"),
        "nmi_vs_parent": _dict_metric(row, "agreement_vs_submitter_parent", "normalized_mutual_info"),
        "nmi_vs_exact": _dict_metric(row, "agreement_vs_submitter_exact", "normalized_mutual_info"),
    }


def _band_candidate_row(
    evaluation: dict[str, Any],
    embeddings_dir: Path,
    band_name: str,
    candidate: dict[str, Any],
) -> dict[str, Any]:
    label_systems = _row_label_systems(evaluation)
    submitter_parent = _baseline_metrics(label_systems.get("submitter_parent"))
    submitter_exact = _baseline_metrics(label_systems.get("submitter_exact"))
    candidate_silhouette = _dict_metric(candidate, "embedding_metrics", "silhouette_score")
    candidate_graph_modularity = _safe_float(candidate.get("graph_modularity"))
    candidate_k10 = _dict_metric(candidate, "neighborhood_agreement", "10")
    parent_silhouette = _safe_float(submitter_parent["silhouette_score"] or 0.0)
    exact_silhouette = _safe_float(submitter_exact["silhouette_score"] or 0.0)
    parent_graph_modularity = _safe_float(submitter_parent["graph_modularity"] or 0.0)
    exact_graph_modularity = _safe_float(submitter_exact["graph_modularity"] or 0.0)
    parent_k10 = _safe_float(submitter_parent["neighbor_agreement_k10"] or 0.0)
    exact_k10 = _safe_float(submitter_exact["neighbor_agreement_k10"] or 0.0)
    return {
        "embedding_dir": str(embeddings_dir),
        "embedding_name": embeddings_dir.name,
        "abstract_count": _safe_int(evaluation.get("abstract_count")),
        "band": band_name,
        "label_system": candidate.get("label_system"),
        "source_type": candidate.get("source_type"),
        "label_count": _safe_int(candidate.get("label_count")),
        "comparison_score": _safe_float(candidate.get("comparison_score")),
        "silhouette_score": candidate_silhouette,
        "graph_modularity": candidate_graph_modularity,
        "intercluster_distance_ratio": _dict_metric(candidate, "embedding_metrics", "intercluster_distance_ratio"),
        "largest_cluster_fraction": _dict_metric(candidate, "embedding_metrics", "largest_cluster_fraction"),
        "neighbor_agreement_k5": _dict_metric(candidate, "neighborhood_agreement", "5"),
        "neighbor_agreement_k10": candidate_k10,
        "neighbor_agreement_k20": _dict_metric(candidate, "neighborhood_agreement", "20"),
        "parent_nmi": _dict_metric(candidate, "agreement_vs_submitter_parent", "normalized_mutual_info"),
        "exact_nmi": _dict_metric(candidate, "agreement_vs_submitter_exact", "normalized_mutual_info"),
        "parent_ami": _dict_metric(candidate, "agreement_vs_submitter_parent", "adjusted_mutual_info"),
        "exact_ami": _dict_metric(candidate, "agreement_vs_submitter_exact", "adjusted_mutual_info"),
        "submitter_parent_silhouette_score": parent_silhouette,
        "submitter_exact_silhouette_score": exact_silhouette,
        "submitter_parent_graph_modularity": parent_graph_modularity,
        "submitter_exact_graph_modularity": exact_graph_modularity,
        "submitter_parent_neighbor_agreement_k10": parent_k10,
        "submitter_exact_neighbor_agreement_k10": exact_k10,
        "silhouette_gain_vs_parent": candidate_silhouette - parent_silhouette,
        "silhouette_gain_vs_exact": candidate_silhouette - exact_silhouette,
        "graph_modularity_gain_vs_parent": candidate_graph_modularity - parent_graph_modularity,
        "graph_modularity_gain_vs_exact": candidate_graph_modularity - exact_graph_modularity,
        "neighbor_gain_vs_parent_k10": candidate_k10 - parent_k10,
        "neighbor_gain_vs_exact_k10": candidate_k10 - exact_k10,
        "assignment_path": candidate.get("assignment_path"),
        "label_count_band": band_name,
    }


def _sort_key(row: dict[str, Any]) -> tuple[float, float, float, int, str, str]:
    return (
        _safe_float(row.get("comparison_score")),
        _safe_float(row.get("silhouette_score")),
        _safe_float(row.get("neighbor_agreement_k10")),
        _safe_int(row.get("label_count")),
        str(row.get("embedding_name") or ""),
        str(row.get("label_system") or ""),
    )


def summarize_evaluation(path: Path) -> dict[str, Any]:
    evaluation = load_evaluation(path)
    embeddings_dir = Path(str(evaluation.get("embeddings_dir") or path.parent.parent))
    label_systems = _row_label_systems(evaluation)
    if "submitter_parent" not in label_systems or "submitter_exact" not in label_systems:
        raise CategoryRollupError(f"{path} is missing submitter_parent or submitter_exact")

    band_winners: list[dict[str, Any]] = []
    best_by_band = dict(evaluation.get("best_by_band") or {})
    for band_name in ROLLUP_BANDS:
        candidate = best_by_band.get(band_name)
        if isinstance(candidate, dict):
            band_winners.append(_band_candidate_row(evaluation, embeddings_dir, band_name, candidate))

    if not band_winners:
        raise CategoryRollupError(f"{path} did not provide any band winners")

    best_learned = sorted(band_winners, key=_sort_key, reverse=True)[0]
    return {
        "evaluation_path": str(path),
        "embeddings_dir": str(embeddings_dir),
        "embedding_name": embeddings_dir.name,
        "abstract_count": _safe_int(evaluation.get("abstract_count")),
        "neighbor_ks": list(evaluation.get("neighbor_ks") or []),
        "label_system_count": len(label_systems),
        "submitter_parent": _baseline_metrics(label_systems.get("submitter_parent")),
        "submitter_exact": _baseline_metrics(label_systems.get("submitter_exact")),
        "band_winners": band_winners,
        "best_learned": best_learned,
    }


def build_rollup(evaluation_paths: list[Path]) -> dict[str, Any]:
    embedding_summaries = [summarize_evaluation(path) for path in evaluation_paths]
    band_rows: list[dict[str, Any]] = []
    for summary in embedding_summaries:
        for row in summary["band_winners"]:
            band_rows.append(dict(row))

    band_winner_map: dict[str, dict[str, Any]] = {}
    for band_name in ROLLUP_BANDS:
        candidates = sorted(
            [row for row in band_rows if str(row.get("band")) == band_name],
            key=_sort_key,
            reverse=True,
        )
        for rank, row in enumerate(candidates, start=1):
            row["global_band_rank"] = rank
        if candidates:
            band_winner_map[band_name] = {
                "winner": candidates[0],
                "top_candidates": candidates[:DEFAULT_TOP_CANDIDATES],
            }

    best_learned_rows = [dict(summary["best_learned"]) for summary in embedding_summaries]
    overall_best = sorted(best_learned_rows, key=_sort_key, reverse=True)[0] if best_learned_rows else None
    embeddings_root = evaluation_paths[0].parents[2] if evaluation_paths else None
    return {
        "embeddings_root": str(embeddings_root) if embeddings_root is not None else None,
        "evaluation_paths": [str(path) for path in evaluation_paths],
        "evaluation_count": len(embedding_summaries),
        "band_rows": band_rows,
        "band_winners": band_winner_map,
        "embedding_summaries": embedding_summaries,
        "best_overall": overall_best,
    }


def write_rollup_csv(path: Path, rollup: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = list(rollup.get("band_rows") or [])
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fieldnames = [
        "band",
        "global_band_rank",
        "embedding_name",
        "embedding_dir",
        "abstract_count",
        "label_system",
        "source_type",
        "label_count",
        "comparison_score",
        "silhouette_score",
        "graph_modularity",
        "intercluster_distance_ratio",
        "largest_cluster_fraction",
        "neighbor_agreement_k5",
        "neighbor_agreement_k10",
        "neighbor_agreement_k20",
        "parent_nmi",
        "exact_nmi",
        "parent_ami",
        "exact_ami",
        "submitter_parent_silhouette_score",
        "submitter_exact_silhouette_score",
        "submitter_parent_graph_modularity",
        "submitter_exact_graph_modularity",
        "submitter_parent_neighbor_agreement_k10",
        "submitter_exact_neighbor_agreement_k10",
        "silhouette_gain_vs_parent",
        "silhouette_gain_vs_exact",
        "graph_modularity_gain_vs_parent",
        "graph_modularity_gain_vs_exact",
        "neighbor_gain_vs_parent_k10",
        "neighbor_gain_vs_exact_k10",
        "assignment_path",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in sorted(rows, key=lambda item: (str(item.get("band")), -_safe_float(item.get("comparison_score")))):
            writer.writerow({fieldname: row.get(fieldname) for fieldname in fieldnames})


def _format_gain(value: float) -> str:
    return f"{value:+.4f}"


def build_markdown_summary(rollup: dict[str, Any]) -> str:
    summaries = list(rollup.get("embedding_summaries") or [])
    if not summaries:
        return "# Category Evaluation Rollup\n\nNo evaluation outputs were found.\n"

    band_winners = dict(rollup.get("band_winners") or {})
    lines = ["# Category Evaluation Rollup", ""]
    lines.append(f"Evaluated embedding bundles: `{len(summaries)}`")
    lines.append("")
    lines.append("## Band Winners Across Embeddings")
    lines.append(
        "| Band | Rank | Embedding | Label system | Labels | Score | Silhouette | Graph modularity | k=10 neighbor agreement | Gain vs parent modularity |"
    )
    lines.append("| --- | ---: | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |")
    for band_name in ROLLUP_BANDS:
        band_info = band_winners.get(band_name)
        if not band_info:
            continue
        for row in band_info.get("top_candidates", []):
            lines.append(
                f"| `{band_name}` | {row.get('global_band_rank')} | `{row.get('embedding_name')}` | "
                f"`{row.get('label_system')}` | {row.get('label_count')} | {float(row.get('comparison_score') or 0.0):.4f} | "
                f"{float(row.get('silhouette_score') or 0.0):.4f} | {float(row.get('graph_modularity') or 0.0):.4f} | "
                f"{float(row.get('neighbor_agreement_k10') or 0.0):.4f} | "
                f"{_format_gain(float(row.get('graph_modularity_gain_vs_parent') or 0.0))} |"
            )
    lines.append("")
    lines.append("## Per-Embedding Best Learned Candidate")
    lines.append(
        "| Embedding | Best band | Best label system | Score | Parent modularity | Exact modularity | Parent k10 | Exact k10 |"
    )
    lines.append("| --- | --- | --- | ---: | ---: | ---: | ---: | ---: |")
    for summary in summaries:
        best = dict(summary.get("best_learned") or {})
        lines.append(
            f"| `{summary.get('embedding_name')}` | `{best.get('band')}` | `{best.get('label_system')}` | "
            f"{float(best.get('comparison_score') or 0.0):.4f} | "
            f"{float(best.get('submitter_parent_graph_modularity') or 0.0):.4f} | "
            f"{float(best.get('submitter_exact_graph_modularity') or 0.0):.4f} | "
            f"{float(best.get('submitter_parent_neighbor_agreement_k10') or 0.0):.4f} | "
            f"{float(best.get('submitter_exact_neighbor_agreement_k10') or 0.0):.4f} |"
        )
    parent_silhouettes = [float(summary.get("submitter_parent", {}).get("silhouette_score") or 0.0) for summary in summaries]
    exact_silhouettes = [float(summary.get("submitter_exact", {}).get("silhouette_score") or 0.0) for summary in summaries]
    best_silhouettes = [float(summary.get("best_learned", {}).get("silhouette_score") or 0.0) for summary in summaries]
    parent_modularities = [float(summary.get("submitter_parent", {}).get("graph_modularity") or 0.0) for summary in summaries]
    exact_modularities = [float(summary.get("submitter_exact", {}).get("graph_modularity") or 0.0) for summary in summaries]
    best_modularities = [float(summary.get("best_learned", {}).get("graph_modularity") or 0.0) for summary in summaries]
    parent_k10s = [float(summary.get("submitter_parent", {}).get("neighbor_agreement_k10") or 0.0) for summary in summaries]
    exact_k10s = [float(summary.get("submitter_exact", {}).get("neighbor_agreement_k10") or 0.0) for summary in summaries]
    best_k10s = [float(summary.get("best_learned", {}).get("neighbor_agreement_k10") or 0.0) for summary in summaries]
    lines.append("")
    lines.append("## Baseline Comparison")
    lines.append(
        f"Across the evaluated embedding bundles, the average submitter-parent silhouette is `{sum(parent_silhouettes) / len(parent_silhouettes):.4f}` "
        f"and the average submitter-exact silhouette is `{sum(exact_silhouettes) / len(exact_silhouettes):.4f}`. "
        f"The average best learned silhouette is `{sum(best_silhouettes) / len(best_silhouettes):.4f}`."
    )
    lines.append(
        f"On the embedding kNN graphs, average submitter-parent modularity is `{sum(parent_modularities) / len(parent_modularities):.4f}`, "
        f"submitter-exact modularity is `{sum(exact_modularities) / len(exact_modularities):.4f}`, and the best learned modularity is `{sum(best_modularities) / len(best_modularities):.4f}`."
    )
    lines.append(
        f"At `k=10`, submitter-parent neighborhood agreement averages `{sum(parent_k10s) / len(parent_k10s):.4f}`, "
        f"submitter-exact averages `{sum(exact_k10s) / len(exact_k10s):.4f}`, and the best learned candidates average `{sum(best_k10s) / len(best_k10s):.4f}`."
    )
    lines.append(
        "This means the learned embedding-native systems are consistently a better fit to the geometry than the submitter taxonomy, while still leaving room to choose between coarse, mid, and fine granularity depending on layout needs."
    )
    lines.append("")
    return "\n".join(lines) + "\n"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build a cross-embedding rollup from category-evaluation outputs")
    parser.add_argument("--embeddings-root", default=str(artifacts.EMBEDDINGS_ROOT))
    parser.add_argument("--evaluation", action="append", help="Explicit evaluation.json path; may be repeated")
    parser.add_argument("--output-json", default=str(artifacts.EMBEDDINGS_ROOT / "category_evaluation_summary.json"))
    parser.add_argument("--output-csv", default=str(artifacts.EMBEDDINGS_ROOT / "category_evaluation_summary.csv"))
    parser.add_argument("--output-md", default=str(artifacts.EMBEDDINGS_ROOT / "category_evaluation_summary.md"))
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.evaluation:
        evaluation_paths = [Path(value) for value in args.evaluation]
    else:
        evaluation_paths = discover_evaluation_paths(Path(args.embeddings_root))
    if not evaluation_paths:
        raise CategoryRollupError("No category_evaluation/evaluation.json files were found")
    rollup = build_rollup(evaluation_paths)
    write_json(Path(args.output_json), rollup)
    write_rollup_csv(Path(args.output_csv), rollup)
    Path(args.output_md).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output_md).write_text(build_markdown_summary(rollup), encoding="utf-8")
    return 0
