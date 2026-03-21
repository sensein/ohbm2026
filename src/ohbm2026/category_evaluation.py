from __future__ import annotations

import argparse
import csv
import json
import math
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from ohbm2026.neuroscape import build_knn_graph, compute_clustering_metrics, load_embedding_bundle, parse_string_list_value

UNKNOWN_LABEL = "Unknown"


class CategoryEvaluationError(RuntimeError):
    """Raised when category-evaluation inputs are invalid."""


@dataclass(frozen=True)
class CategoryRecord:
    abstract_id: int
    accepted_for: str
    title: str
    parent_category: str
    exact_category: str


@dataclass(frozen=True)
class LabelSystemSpec:
    name: str
    source_type: str
    path: Path | None = None


@dataclass(frozen=True)
class LabelCountBand:
    name: str
    min_count: int
    max_count: int


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


DEFAULT_LABEL_COUNT_BANDS = (
    LabelCountBand("coarse", 10, 15),
    LabelCountBand("mid", 20, 30),
    LabelCountBand("fine", 31, 40),
)


def _normalize_rows(matrix: np.ndarray) -> np.ndarray:
    matrix = np.asarray(matrix, dtype=np.float32)
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms = np.where(norms > 0.0, norms, 1.0)
    return matrix / norms


def _extract_primary_category_parts(abstract: dict[str, Any]) -> tuple[str, str]:
    for response in abstract.get("responses", []):
        question_name = str(response.get("question_name") or "").strip().lower()
        if question_name != "primary parent category & sub-category":
            continue
        values = parse_string_list_value(response.get("value"))
        parent = values[0] if values else UNKNOWN_LABEL
        subcategory = values[1] if len(values) > 1 else UNKNOWN_LABEL
        return parent or UNKNOWN_LABEL, subcategory or UNKNOWN_LABEL
    return UNKNOWN_LABEL, UNKNOWN_LABEL


def load_category_records(raw_input: Path) -> dict[int, CategoryRecord]:
    payload = json.loads(raw_input.read_text(encoding="utf-8"))
    records: dict[int, CategoryRecord] = {}
    for abstract in payload.get("abstracts", []):
        abstract_id = abstract.get("id")
        if not isinstance(abstract_id, int):
            continue
        accepted_for = str(abstract.get("accepted_for") or "").strip()
        if accepted_for not in {"Poster", "Oral"}:
            continue
        parent, subcategory = _extract_primary_category_parts(abstract)
        records[abstract_id] = CategoryRecord(
            abstract_id=abstract_id,
            accepted_for=accepted_for,
            title=str(abstract.get("title") or "").strip(),
            parent_category=parent,
            exact_category=f"{parent} :: {subcategory}",
        )
    return records


def _load_assignment_map(path: Path) -> dict[int, str]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    raw_assignments = payload.get("assignments", payload)
    if not isinstance(raw_assignments, dict):
        raise CategoryEvaluationError(f"Assignment file is missing an assignments map: {path}")
    assignments: dict[int, str] = {}
    for raw_id, raw_label in raw_assignments.items():
        abstract_id = int(raw_id)
        assignments[abstract_id] = str(raw_label)
    return assignments


def _sanitize_label_system_name(value: str) -> str:
    return (
        str(value)
        .strip()
        .replace("clustering_benchmark", "benchmark")
        .replace("semantic_analysis", "semantic_graph")
        .replace("-", "_")
    )


def _discover_label_system_specs(embeddings_dir: Path) -> list[LabelSystemSpec]:
    discovered: list[LabelSystemSpec] = []
    candidate_dirs = sorted(
        [
            path
            for path in embeddings_dir.iterdir()
            if path.is_dir()
            and (
                path.name.startswith("clustering_benchmark")
                or path.name.startswith("semantic_analysis")
            )
        ]
    )
    for candidate_dir in candidate_dirs:
        assignments_path = candidate_dir / "cluster_assignments.json"
        if not assignments_path.exists():
            continue
        if candidate_dir.name == "clustering_benchmark":
            name = "benchmark_best"
        elif candidate_dir.name == "semantic_analysis":
            name = "semantic_graph"
        else:
            name = _sanitize_label_system_name(candidate_dir.name)
        discovered.append(LabelSystemSpec(name=name, source_type="file", path=assignments_path))
    return discovered


def parse_label_system_specs(values: list[str] | None, embeddings_dir: Path) -> list[LabelSystemSpec]:
    if values:
        specs: list[LabelSystemSpec] = []
        for value in values:
            raw_value = str(value).strip()
            if not raw_value:
                continue
            if raw_value in {"submitter_parent", "submitter_exact"}:
                specs.append(LabelSystemSpec(name=raw_value, source_type="builtin"))
                continue
            if "=" not in raw_value:
                raise CategoryEvaluationError(
                    f"Label system '{raw_value}' must be a builtin label or formatted as name=path/to/assignments.json"
                )
            name, raw_path = raw_value.split("=", 1)
            specs.append(LabelSystemSpec(name=name.strip(), source_type="file", path=Path(raw_path.strip())))
        return specs

    specs = [
        LabelSystemSpec(name="submitter_parent", source_type="builtin"),
        LabelSystemSpec(name="submitter_exact", source_type="builtin"),
    ]
    seen_names = {spec.name for spec in specs}
    for spec in _discover_label_system_specs(embeddings_dir):
        if spec.name in seen_names:
            continue
        specs.append(spec)
        seen_names.add(spec.name)
    return specs


def _labels_for_spec(
    spec: LabelSystemSpec,
    ids: list[int],
    records_by_id: dict[int, CategoryRecord],
) -> list[str]:
    if spec.source_type == "builtin":
        if spec.name == "submitter_parent":
            return [records_by_id[abstract_id].parent_category for abstract_id in ids]
        if spec.name == "submitter_exact":
            return [records_by_id[abstract_id].exact_category for abstract_id in ids]
        raise CategoryEvaluationError(f"Unsupported builtin label system: {spec.name}")
    if spec.path is None:
        raise CategoryEvaluationError(f"File-based label system '{spec.name}' is missing a path")
    assignments = _load_assignment_map(spec.path)
    missing_ids = [abstract_id for abstract_id in ids if abstract_id not in assignments]
    if missing_ids:
        preview = ", ".join(str(value) for value in missing_ids[:5])
        raise CategoryEvaluationError(
            f"Label system '{spec.name}' is missing {len(missing_ids)} abstract ids, including {preview}"
        )
    return [assignments[abstract_id] for abstract_id in ids]


def encode_labels(labels: list[str]) -> tuple[np.ndarray, dict[int, str]]:
    values = sorted({str(label) for label in labels})
    value_to_index = {value: index for index, value in enumerate(values)}
    encoded = np.asarray([value_to_index[str(label)] for label in labels], dtype=np.int32)
    return encoded, {index: value for value, index in value_to_index.items()}


def _compute_neighbor_indices(normalized_matrix: np.ndarray, max_k: int) -> np.ndarray:
    matrix = np.asarray(normalized_matrix, dtype=np.float32)
    if int(matrix.shape[0]) == 0:
        return np.zeros((0, 0), dtype=np.int32)
    effective_k = max(1, min(int(max_k), int(matrix.shape[0]) - 1))
    similarity = np.asarray(matrix @ matrix.T, dtype=np.float32)
    np.fill_diagonal(similarity, -np.inf)
    candidate_indices = np.argpartition(similarity, -effective_k, axis=1)[:, -effective_k:]
    row_indices = np.arange(int(matrix.shape[0]))[:, None]
    ordered = np.argsort(similarity[row_indices, candidate_indices], axis=1)[:, ::-1]
    return candidate_indices[row_indices, ordered].astype(np.int32)


def compute_neighborhood_agreement(
    encoded_labels: np.ndarray,
    neighbor_indices: np.ndarray,
    neighbor_ks: list[int],
) -> dict[str, float]:
    if int(encoded_labels.shape[0]) == 0:
        return {}
    agreements: dict[str, float] = {}
    for neighbor_k in neighbor_ks:
        effective_k = min(int(neighbor_k), int(neighbor_indices.shape[1]))
        if effective_k <= 0:
            agreements[str(neighbor_k)] = 0.0
            continue
        matches = encoded_labels[neighbor_indices[:, :effective_k]] == encoded_labels[:, None]
        agreements[str(neighbor_k)] = float(np.mean(matches))
    return agreements


def compute_graph_label_modularity(
    ids: list[int],
    normalized_matrix: np.ndarray,
    encoded_labels: np.ndarray,
    num_neighbors: int,
) -> float | None:
    from networkx.algorithms.community import modularity

    if len(ids) <= 1:
        return None
    graph = build_knn_graph(ids, normalized_matrix, num_neighbors=num_neighbors)
    if graph.number_of_edges() <= 0:
        return None
    communities: list[set[int]] = []
    for cluster_id in sorted(set(encoded_labels.tolist())):
        members = {
            int(ids[index])
            for index, assigned_cluster in enumerate(encoded_labels.tolist())
            if int(assigned_cluster) == int(cluster_id)
        }
        if members:
            communities.append(members)
    if len(communities) <= 1:
        return None
    try:
        return float(modularity(graph, communities, weight="weight"))
    except Exception:
        return None


def _weighted_cluster_purity_and_entropy(
    candidate_labels: np.ndarray,
    reference_labels: np.ndarray,
) -> dict[str, float]:
    total = max(1, int(candidate_labels.shape[0]))
    reference_count = max(1, len(set(reference_labels.tolist())))
    weighted_purity = 0.0
    weighted_entropy = 0.0
    for cluster_id in sorted(set(candidate_labels.tolist())):
        member_indices = np.where(candidate_labels == cluster_id)[0]
        if int(member_indices.shape[0]) == 0:
            continue
        cluster_reference = reference_labels[member_indices]
        counts = Counter(int(value) for value in cluster_reference.tolist())
        cluster_size = sum(counts.values())
        probabilities = [count / cluster_size for count in counts.values() if count > 0]
        weighted_purity += (max(counts.values()) / cluster_size) * (cluster_size / total)
        if len(probabilities) <= 1:
            normalized_entropy = 0.0
        else:
            entropy = -sum(probability * math.log(probability) for probability in probabilities)
            normalized_entropy = float(entropy / math.log(reference_count)) if reference_count > 1 else 0.0
        weighted_entropy += normalized_entropy * (cluster_size / total)
    return {
        "weighted_purity": float(weighted_purity),
        "weighted_entropy": float(weighted_entropy),
    }


def _reference_fragmentation(
    candidate_labels: np.ndarray,
    reference_labels: np.ndarray,
) -> dict[str, float]:
    total = max(1, int(reference_labels.shape[0]))
    weighted_active_cluster_count = 0.0
    weighted_entropy = 0.0
    candidate_cluster_count = max(1, len(set(candidate_labels.tolist())))
    for reference_label in sorted(set(reference_labels.tolist())):
        member_indices = np.where(reference_labels == reference_label)[0]
        if int(member_indices.shape[0]) == 0:
            continue
        assigned_clusters = candidate_labels[member_indices]
        counts = Counter(int(value) for value in assigned_clusters.tolist())
        label_size = sum(counts.values())
        probabilities = [count / label_size for count in counts.values() if count > 0]
        weighted_active_cluster_count += len(counts) * (label_size / total)
        if len(probabilities) <= 1:
            normalized_entropy = 0.0
        else:
            entropy = -sum(probability * math.log(probability) for probability in probabilities)
            normalized_entropy = float(entropy / math.log(candidate_cluster_count)) if candidate_cluster_count > 1 else 0.0
        weighted_entropy += normalized_entropy * (label_size / total)
    return {
        "weighted_active_cluster_count": float(weighted_active_cluster_count),
        "weighted_fragmentation_entropy": float(weighted_entropy),
    }


def compute_label_agreement(
    candidate_labels: np.ndarray,
    reference_labels: np.ndarray,
) -> dict[str, float]:
    from sklearn.metrics import (
        adjusted_mutual_info_score,
        adjusted_rand_score,
        completeness_score,
        homogeneity_score,
        normalized_mutual_info_score,
        v_measure_score,
    )

    metrics = {
        "adjusted_mutual_info": float(adjusted_mutual_info_score(reference_labels, candidate_labels)),
        "normalized_mutual_info": float(normalized_mutual_info_score(reference_labels, candidate_labels)),
        "adjusted_rand_index": float(adjusted_rand_score(reference_labels, candidate_labels)),
        "homogeneity": float(homogeneity_score(reference_labels, candidate_labels)),
        "completeness": float(completeness_score(reference_labels, candidate_labels)),
        "v_measure": float(v_measure_score(reference_labels, candidate_labels)),
    }
    metrics.update(_weighted_cluster_purity_and_entropy(candidate_labels, reference_labels))
    metrics.update(_reference_fragmentation(candidate_labels, reference_labels))
    return metrics


def _label_count_band_name(label_count: int, bands: tuple[LabelCountBand, ...]) -> str:
    for band in bands:
        if int(band.min_count) <= int(label_count) <= int(band.max_count):
            return band.name
    return "outside_target_band"


def _comparison_score(result: dict[str, Any]) -> float:
    embedding_metrics = dict(result.get("embedding_metrics") or {})
    neighborhood = dict(result.get("neighborhood_agreement") or {})
    graph_modularity = float(result.get("graph_modularity") or 0.0)
    return float(
        0.30 * float(embedding_metrics.get("silhouette_score") or 0.0)
        + 0.30 * float(neighborhood.get("10") or 0.0)
        + 0.20 * float(embedding_metrics.get("intercluster_distance_ratio") or 0.0)
        + 0.20 * graph_modularity
    )


def _best_by_band(results: list[dict[str, Any]], bands: tuple[LabelCountBand, ...]) -> dict[str, dict[str, Any]]:
    band_names = [band.name for band in bands] + ["outside_target_band"]
    output: dict[str, dict[str, Any]] = {}
    for band_name in band_names:
        candidates = [result for result in results if str(result.get("label_count_band")) == band_name]
        if not candidates:
            continue
        output[band_name] = sorted(
            candidates,
            key=lambda item: (
                float(item.get("comparison_score") or 0.0),
                float(dict(item.get("embedding_metrics") or {}).get("silhouette_score") or 0.0),
                float(dict(item.get("neighborhood_agreement") or {}).get("10") or 0.0),
                -(int(item.get("label_count") or 0)),
            ),
            reverse=True,
        )[0]
    return output


def evaluate_label_systems(
    embeddings_dir: Path,
    raw_input: Path,
    label_system_specs: list[LabelSystemSpec],
    neighbor_ks: list[int] | None = None,
    label_count_bands: tuple[LabelCountBand, ...] = DEFAULT_LABEL_COUNT_BANDS,
) -> dict[str, Any]:
    neighbor_ks = [5, 10, 20] if neighbor_ks is None else [int(value) for value in neighbor_ks]
    bundle = load_embedding_bundle(embeddings_dir)
    ids = [int(abstract_id) for abstract_id in bundle["ids"]]
    matrix = np.asarray(bundle["matrix"], dtype=np.float32)
    normalized_matrix = _normalize_rows(matrix)
    records_by_id = load_category_records(raw_input)
    missing_ids = [abstract_id for abstract_id in ids if abstract_id not in records_by_id]
    if missing_ids:
        preview = ", ".join(str(value) for value in missing_ids[:5])
        raise CategoryEvaluationError(
            f"Category records are missing {len(missing_ids)} embedding ids, including {preview}"
        )

    parent_labels = [records_by_id[abstract_id].parent_category for abstract_id in ids]
    exact_labels = [records_by_id[abstract_id].exact_category for abstract_id in ids]
    encoded_parent, _ = encode_labels(parent_labels)
    encoded_exact, _ = encode_labels(exact_labels)
    neighbor_indices = _compute_neighbor_indices(normalized_matrix, max(neighbor_ks))
    graph_neighbor_count = max(neighbor_ks)

    results: list[dict[str, Any]] = []
    for spec in label_system_specs:
        raw_labels = _labels_for_spec(spec, ids, records_by_id)
        encoded_labels, index_to_label = encode_labels(raw_labels)
        cluster_metrics = compute_clustering_metrics(ids, normalized_matrix, encoded_labels.tolist())
        result = {
            "label_system": spec.name,
            "source_type": spec.source_type,
            "assignment_path": None if spec.path is None else str(spec.path),
            "label_count": len(index_to_label),
            "label_count_band": _label_count_band_name(len(index_to_label), label_count_bands),
            "label_examples": [index_to_label[index] for index in sorted(index_to_label)[:10]],
            "embedding_metrics": cluster_metrics,
            "neighborhood_agreement": compute_neighborhood_agreement(encoded_labels, neighbor_indices, neighbor_ks),
            "graph_modularity": compute_graph_label_modularity(
                ids,
                normalized_matrix,
                encoded_labels,
                num_neighbors=graph_neighbor_count,
            ),
            "agreement_vs_submitter_parent": compute_label_agreement(encoded_labels, encoded_parent),
            "agreement_vs_submitter_exact": compute_label_agreement(encoded_labels, encoded_exact),
        }
        result["comparison_score"] = _comparison_score(result)
        results.append(result)

    return {
        "embeddings_dir": str(embeddings_dir),
        "abstract_count": len(ids),
        "neighbor_ks": neighbor_ks,
        "label_count_bands": [
            {"name": band.name, "min_count": int(band.min_count), "max_count": int(band.max_count)}
            for band in label_count_bands
        ],
        "best_by_band": _best_by_band(results, label_count_bands),
        "label_systems": results,
    }


def write_evaluation_csv(path: Path, evaluation: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = list(evaluation.get("label_systems") or [])
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fieldnames = [
        "label_system",
        "source_type",
        "label_count",
        "label_count_band",
        "comparison_score",
        "silhouette_score",
        "intercluster_distance_ratio",
        "largest_cluster_fraction",
        "smallest_cluster_size",
        "neighbor_agreement_k5",
        "neighbor_agreement_k10",
        "neighbor_agreement_k20",
        "graph_modularity",
        "parent_adjusted_mutual_info",
        "parent_normalized_mutual_info",
        "parent_weighted_purity",
        "parent_weighted_fragmentation_entropy",
        "exact_adjusted_mutual_info",
        "exact_normalized_mutual_info",
        "exact_weighted_purity",
        "exact_weighted_fragmentation_entropy",
        "assignment_path",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            embedding_metrics = dict(row.get("embedding_metrics") or {})
            neighborhood = dict(row.get("neighborhood_agreement") or {})
            parent_metrics = dict(row.get("agreement_vs_submitter_parent") or {})
            exact_metrics = dict(row.get("agreement_vs_submitter_exact") or {})
            writer.writerow(
                {
                    "label_system": row.get("label_system"),
                    "source_type": row.get("source_type"),
                    "label_count": row.get("label_count"),
                    "label_count_band": row.get("label_count_band"),
                    "comparison_score": row.get("comparison_score"),
                    "silhouette_score": embedding_metrics.get("silhouette_score"),
                    "intercluster_distance_ratio": embedding_metrics.get("intercluster_distance_ratio"),
                    "largest_cluster_fraction": embedding_metrics.get("largest_cluster_fraction"),
                    "smallest_cluster_size": embedding_metrics.get("smallest_cluster_size"),
                    "neighbor_agreement_k5": neighborhood.get("5"),
                    "neighbor_agreement_k10": neighborhood.get("10"),
                    "neighbor_agreement_k20": neighborhood.get("20"),
                    "graph_modularity": row.get("graph_modularity"),
                    "parent_adjusted_mutual_info": parent_metrics.get("adjusted_mutual_info"),
                    "parent_normalized_mutual_info": parent_metrics.get("normalized_mutual_info"),
                    "parent_weighted_purity": parent_metrics.get("weighted_purity"),
                    "parent_weighted_fragmentation_entropy": parent_metrics.get("weighted_fragmentation_entropy"),
                    "exact_adjusted_mutual_info": exact_metrics.get("adjusted_mutual_info"),
                    "exact_normalized_mutual_info": exact_metrics.get("normalized_mutual_info"),
                    "exact_weighted_purity": exact_metrics.get("weighted_purity"),
                    "exact_weighted_fragmentation_entropy": exact_metrics.get("weighted_fragmentation_entropy"),
                    "assignment_path": row.get("assignment_path"),
                }
            )


def build_markdown_summary(evaluation: dict[str, Any]) -> str:
    rows = list(evaluation.get("label_systems") or [])
    if not rows:
        return "# Label System Evaluation\n\nNo label systems were evaluated.\n"
    lines = ["# Label System Evaluation", ""]
    lines.append(f"Embedding space: `{evaluation.get('embeddings_dir')}`")
    lines.append(f"Abstract count: `{evaluation.get('abstract_count')}`")
    lines.append("")
    lines.append("## Best Candidate By Label-Count Band")
    best_by_band = dict(evaluation.get("best_by_band") or {})
    for band_name, row in best_by_band.items():
        embedding_metrics = dict(row.get("embedding_metrics") or {})
        neighborhood = dict(row.get("neighborhood_agreement") or {})
        lines.append(
            f"- `{band_name}`: `{row.get('label_system')}` with `{row.get('label_count')}` labels, "
            f"silhouette `{float(embedding_metrics.get('silhouette_score') or 0.0):.4f}`, "
            f"k=10 neighbor agreement `{float(neighborhood.get('10') or 0.0):.4f}`."
        )
    lines.append("")
    lines.append(
        "| Label system | Labels | Silhouette | Graph modularity | k=10 neighbor agreement | NMI vs parent | NMI vs exact |"
    )
    lines.append("| --- | ---: | ---: | ---: | ---: | ---: | ---: |")
    for row in rows:
        embedding_metrics = dict(row.get("embedding_metrics") or {})
        neighborhood = dict(row.get("neighborhood_agreement") or {})
        parent_metrics = dict(row.get("agreement_vs_submitter_parent") or {})
        exact_metrics = dict(row.get("agreement_vs_submitter_exact") or {})
        lines.append(
            f"| `{row.get('label_system')}` ({row.get('label_count_band')}) | {row.get('label_count')} | "
            f"{float(embedding_metrics.get('silhouette_score') or 0.0):.4f} | "
            f"{float(row.get('graph_modularity') or 0.0):.4f} | "
            f"{float(neighborhood.get('10') or 0.0):.4f} | "
            f"{float(parent_metrics.get('normalized_mutual_info') or 0.0):.4f} | "
            f"{float(exact_metrics.get('normalized_mutual_info') or 0.0):.4f} |"
        )
    lines.append("")
    return "\n".join(lines) + "\n"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Evaluate submitter and learned label systems in a shared embedding space")
    parser.add_argument("--embeddings-dir", required=True)
    parser.add_argument("--raw-input", default="data/abstracts.json")
    parser.add_argument(
        "--label-system",
        action="append",
        help="Builtin label system name or name=path/to/cluster_assignments.json. Defaults to submitter baselines plus discovered benchmark/community outputs.",
    )
    parser.add_argument("--neighbor-k", nargs="+", type=int, default=[5, 10, 20])
    parser.add_argument("--output-dir")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    embeddings_dir = Path(args.embeddings_dir)
    output_dir = Path(args.output_dir) if args.output_dir else embeddings_dir / "category_evaluation"
    specs = parse_label_system_specs(args.label_system, embeddings_dir)
    evaluation = evaluate_label_systems(
        embeddings_dir=embeddings_dir,
        raw_input=Path(args.raw_input),
        label_system_specs=specs,
        neighbor_ks=[int(value) for value in args.neighbor_k],
    )
    write_json(output_dir / "evaluation.json", evaluation)
    write_evaluation_csv(output_dir / "summary.csv", evaluation)
    (output_dir / "summary.md").write_text(build_markdown_summary(evaluation), encoding="utf-8")
    return 0
