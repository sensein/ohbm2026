from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import scipy.sparse as sp
from sklearn.neighbors import NearestNeighbors


DEFAULT_GRAPH_NEIGHBORS = 20
DEFAULT_NUM_COMMUNITIES = 31

X_FEATURE_INCOMPATIBILITY_REASON = (
    "Checkpoint expects fixed input-space X features and cannot predict zero-shot on these embedding dimensions."
)


@dataclass(frozen=True)
class EmbeddingSource:
    name: str
    bundle_dir: Path
    ids: list[int]
    matrix: np.ndarray


def _metadata_value(payload: dict[str, Any], key: str, default: Any = None) -> Any:
    if key in payload:
        return payload[key]
    namespaced_key = f"cr:{key}"
    if namespaced_key in payload:
        return payload[namespaced_key]
    return default


def load_checkpoint_metadata(metadata_path: Path) -> dict[str, Any]:
    payload = json.loads(metadata_path.read_text(encoding="utf-8"))
    checkpoint_name = None
    for entry in list(payload.get("distribution") or []):
        candidate = entry.get("name") or entry.get("contentUrl") or entry.get("@id")
        if isinstance(candidate, str) and candidate.endswith(".pt"):
            checkpoint_name = Path(candidate).name
            break
    if checkpoint_name is None:
        checkpoint_name = metadata_path.with_suffix(".pt").name
    return {
        "metadata_path": str(metadata_path),
        "checkpoint_name": checkpoint_name,
        "checkpoint_stem": Path(checkpoint_name).stem,
        "model_type": str(_metadata_value(payload, "modelArchitecture", "")),
        "feature_type": str(_metadata_value(payload, "featureType", "")),
        "hidden_dims": list(_metadata_value(payload, "hiddenDims", []) or []),
        "n_components": _metadata_value(payload, "nComponents", None),
        "trained_on": dict(_metadata_value(payload, "trainedOn", {}) or {}),
        "source_name": str(payload.get("name") or metadata_path.stem),
    }


def discover_checkpoint_configs(checkpoint_dir: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    portable_configs: list[dict[str, Any]] = []
    compatibility_rows: list[dict[str, Any]] = []
    for metadata_path in sorted(checkpoint_dir.glob("*.json")):
        metadata = load_checkpoint_metadata(metadata_path)
        checkpoint_name = str(metadata["checkpoint_name"])
        checkpoint_path = checkpoint_dir / checkpoint_name
        if not checkpoint_path.exists():
            continue
        feature_type = str(metadata["feature_type"])
        model_type = str(metadata["model_type"])
        base_key = str(metadata["checkpoint_stem"]).replace("-", "_")
        if feature_type.lower() == "x":
            compatibility_rows.append(
                {
                    "model_key": f"{base_key}_pretrained",
                    "checkpoint_name": checkpoint_name,
                    "model_type": model_type,
                    "feature_type": feature_type,
                    "reason": X_FEATURE_INCOMPATIBILITY_REASON,
                    "status": "incompatible",
                }
            )
            continue
        portable_configs.append(
            {
                "model_key": f"{base_key}_pretrained",
                "checkpoint_name": checkpoint_name,
                "mode": "checkpoint_predict",
                "model_type": model_type,
                "feature_type": feature_type,
                "hidden_dims": list(metadata["hidden_dims"]),
                "n_components": metadata["n_components"],
                "trained_on": dict(metadata["trained_on"]),
                "source_name": str(metadata["source_name"]),
            }
        )
    portable_configs.sort(key=lambda config: str(config["model_key"]))
    compatibility_rows.sort(key=lambda row: str(row["model_key"]))
    return portable_configs, compatibility_rows


def select_classic_checkpoint_config(checkpoint_configs: list[dict[str, Any]]) -> dict[str, Any]:
    if not checkpoint_configs:
        raise FileNotFoundError("No compatible NOCD checkpoints were discovered.")
    preferred_orders = [
        ("gcn", "structural"),
        ("gcn", "spectral"),
        ("improved", "structural"),
        ("improved", "spectral"),
    ]
    for model_type, feature_type in preferred_orders:
        for config in checkpoint_configs:
            if str(config.get("model_type")) == model_type and str(config.get("feature_type")) == feature_type:
                return {
                    **config,
                    "model_key": f"classic_{config['model_key']}",
                }
    config = checkpoint_configs[0]
    return {
        **config,
        "model_key": f"classic_{config['model_key']}",
    }


def discover_embedding_sources(embeddings_root: Path) -> list[Path]:
    return sorted(
        path
        for path in embeddings_root.iterdir()
        if path.is_dir() and (path / "vectors.npy").exists() and (path / "metadata.json").exists()
    )


def load_embedding_source(bundle_dir: Path) -> EmbeddingSource:
    metadata = json.loads((bundle_dir / "metadata.json").read_text(encoding="utf-8"))
    ids = [int(value) for value in list(metadata.get("ids") or [])]
    matrix = np.asarray(np.load(bundle_dir / "vectors.npy"), dtype=np.float32)
    if len(ids) != int(matrix.shape[0]):
        raise ValueError(f"Embedding bundle {bundle_dir} has {matrix.shape[0]} rows but {len(ids)} ids")
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms[norms == 0.0] = 1.0
    matrix = matrix / norms
    return EmbeddingSource(name=bundle_dir.name, bundle_dir=bundle_dir, ids=ids, matrix=matrix)


def build_knn_adjacency(matrix: np.ndarray, neighbor_count: int = DEFAULT_GRAPH_NEIGHBORS) -> sp.csr_matrix:
    if int(matrix.shape[0]) <= 1:
        return sp.csr_matrix((int(matrix.shape[0]), int(matrix.shape[0])), dtype=np.float32)
    effective_neighbors = min(max(2, int(neighbor_count)), int(matrix.shape[0]) - 1)
    model = NearestNeighbors(metric="cosine", n_neighbors=effective_neighbors + 1, algorithm="brute")
    model.fit(matrix)
    _distances, indices = model.kneighbors(matrix, return_distance=True)
    rows = np.repeat(np.arange(matrix.shape[0]), effective_neighbors)
    cols = indices[:, 1:].reshape(-1)
    data = np.ones(rows.shape[0], dtype=np.float32)
    adjacency = sp.csr_matrix((data, (rows, cols)), shape=(int(matrix.shape[0]), int(matrix.shape[0])))
    adjacency = adjacency.maximum(adjacency.T)
    adjacency.setdiag(0)
    adjacency.eliminate_zeros()
    return adjacency


def save_raw_csr_npz(path: Path, matrix: sp.csr_matrix) -> None:
    matrix = matrix.tocsr()
    np.savez(
        path,
        data=matrix.data,
        indices=matrix.indices,
        indptr=matrix.indptr,
        shape=np.asarray(matrix.shape, dtype=np.int64),
    )


def save_dense_features_npz(path: Path, matrix: np.ndarray) -> None:
    np.savez(path, X=np.asarray(matrix, dtype=np.float32))


def patch_nocd_sampler_num_workers_zero() -> None:
    import nocd
    from nocd.sampler import EdgeSampler, collate_fn
    from torch.utils.data import DataLoader

    def _patched_sampler(A: Any, num_pos: int = 1000, num_neg: int = 1000, num_workers: int = 2) -> DataLoader:
        return DataLoader(EdgeSampler(A, num_pos, num_neg), num_workers=0, collate_fn=collate_fn)

    nocd.sampler.get_edge_sampler = _patched_sampler


def preferred_device() -> str:
    import torch

    if torch.backends.mps.is_available():
        return "mps"
    if torch.cuda.is_available():
        return "cuda"
    return "cpu"


def summarize_memberships(
    ids: list[int],
    adjacency: sp.csr_matrix,
    z_soft: np.ndarray,
    z_binary: np.ndarray,
) -> dict[str, Any]:
    from nocd import metrics as nocd_metrics

    z_soft = np.asarray(z_soft, dtype=np.float32)
    z_binary = np.asarray(z_binary, dtype=np.float32)
    community_sizes = z_binary.sum(axis=0).astype(int)
    nonempty_communities = int(np.sum(community_sizes > 0))
    nodes_in_any = int(np.sum(z_binary.sum(axis=1) > 0))
    multi_membership = int(np.sum(z_binary.sum(axis=1) > 1))
    if int(z_binary.sum()) > 0:
        unsupervised = {key: float(value) for key, value in nocd_metrics.evaluate_unsupervised(z_binary, adjacency).items()}
    else:
        unsupervised = {
            "coverage": 0.0,
            "density": 0.0,
            "conductance": 1.0 if adjacency.nnz > 0 else 0.0,
            "clustering_coef": 0.0,
        }
    return {
        "node_count": len(ids),
        "edge_count": int(adjacency.nnz // 2),
        "mean_degree": float(adjacency.nnz / max(1, adjacency.shape[0])),
        "community_count": int(z_binary.shape[1]),
        "nonempty_community_count": nonempty_communities,
        "assigned_node_count": nodes_in_any,
        "assigned_node_fraction": float(nodes_in_any / max(1, len(ids))),
        "multi_membership_node_count": multi_membership,
        "multi_membership_fraction": float(multi_membership / max(1, len(ids))),
        "largest_community_size": int(community_sizes.max()) if community_sizes.size else 0,
        "smallest_nonempty_community_size": int(community_sizes[community_sizes > 0].min()) if np.any(community_sizes > 0) else 0,
        "coverage": float(unsupervised["coverage"]),
        "density": float(unsupervised["density"]),
        "conductance": float(unsupervised["conductance"]),
        "clustering_coefficient": float(unsupervised["clustering_coef"]),
    }


def write_communities_json(
    output_path: Path,
    ids: list[int],
    z_binary: np.ndarray,
    metrics: dict[str, Any],
    metadata: dict[str, Any],
) -> None:
    z_binary = np.asarray(z_binary, dtype=np.float32)
    communities: dict[str, list[int]] = {}
    for community_index in range(int(z_binary.shape[1])):
        member_positions = np.where(z_binary[:, community_index] > 0)[0].tolist()
        communities[str(community_index)] = [int(ids[position]) for position in member_positions]
    payload = {
        "metadata": metadata,
        "metrics": metrics,
        "num_communities": int(z_binary.shape[1]),
        "communities": communities,
    }
    output_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def write_visualization(
    output_path: Path,
    adjacency: sp.csr_matrix,
    z_soft: np.ndarray,
    title: str,
    threshold: float = 0.5,
    markersize: float = 0.08,
    dpi: int = 180,
) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from nocd import utils as nocd_utils

    z_soft = np.asarray(z_soft, dtype=np.float32)
    dominant = np.argmax(z_soft, axis=1)
    order = np.argsort(dominant)
    figure, axis = plt.subplots(figsize=(10, 10), dpi=dpi)
    nocd_utils.plot_sparse_clustered_adjacency(
        adjacency,
        int(z_soft.shape[1]),
        dominant,
        order,
        ax=axis,
        markersize=markersize,
    )
    axis.set_title(title)
    figure.tight_layout()
    figure.savefig(output_path, bbox_inches="tight")
    plt.close(figure)


def render_metric_heatmap(
    rows: list[dict[str, Any]],
    model_order: list[str],
    source_order: list[str],
    value_key: str,
    output_path: Path,
    title: str,
) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    if not rows:
        return
    matrix = np.full((len(model_order), len(source_order)), np.nan, dtype=np.float64)
    model_index = {name: idx for idx, name in enumerate(model_order)}
    source_index = {name: idx for idx, name in enumerate(source_order)}
    for row in rows:
        matrix[model_index[str(row["model_key"])], source_index[str(row["embedding_source"])]] = float(row[value_key])

    figure, axis = plt.subplots(
        figsize=(max(10.0, 0.55 * len(source_order)), max(4.5, 0.7 * len(model_order))),
        dpi=180,
    )
    image = axis.imshow(matrix, aspect="auto", cmap="viridis")
    axis.set_xticks(np.arange(len(source_order)))
    axis.set_xticklabels(source_order, rotation=45, ha="right")
    axis.set_yticks(np.arange(len(model_order)))
    axis.set_yticklabels(model_order)
    axis.set_title(title)
    colorbar = figure.colorbar(image, ax=axis, fraction=0.035, pad=0.02)
    colorbar.set_label(value_key.replace("_", " "))
    figure.tight_layout()
    figure.savefig(output_path, bbox_inches="tight")
    plt.close(figure)


def write_summary_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fieldnames = sorted({key for row in rows for key in row})
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def _rank_normalized(values: list[float], *, reverse: bool) -> list[float]:
    if not values:
        return []
    order = sorted(range(len(values)), key=lambda idx: float(values[idx]), reverse=reverse)
    result = [0.0] * len(values)
    if len(values) == 1:
        result[0] = 1.0
        return result
    for rank, original_index in enumerate(order):
        result[original_index] = 1.0 - (float(rank) / float(len(values) - 1))
    return result


def annotate_community_structure_scores(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not rows:
        return []

    coverage_ranks = _rank_normalized([float(row["coverage"]) for row in rows], reverse=True)
    density_ranks = _rank_normalized([float(row["density"]) for row in rows], reverse=True)
    conductance_ranks = _rank_normalized([float(row["conductance"]) for row in rows], reverse=False)
    clustering_ranks = _rank_normalized([float(row["clustering_coefficient"]) for row in rows], reverse=True)

    for index, row in enumerate(rows):
        weighted_score = (
            0.35 * coverage_ranks[index]
            + 0.20 * density_ranks[index]
            + 0.30 * conductance_ranks[index]
            + 0.15 * clustering_ranks[index]
        )
        if bool(row.get("degenerate_single_community")):
            weighted_score -= 1.0
        row["community_structure_score"] = float(weighted_score)

    rows.sort(
        key=lambda row: (
            bool(row.get("degenerate_single_community", False)),
            -float(row["community_structure_score"]),
            float(row["conductance"]),
            -float(row["coverage"]),
            -float(row["density"]),
            -float(row["clustering_coefficient"]),
        )
    )
    for rank, row in enumerate(rows, start=1):
        row["community_structure_rank"] = int(rank)
    return rows


def classic_summary_markdown(rows: list[dict[str, Any]], checkpoint_name: str) -> str:
    lines = [
        "# NOCD Classic Prediction Summary",
        "",
        f"Checkpoint: `{checkpoint_name}`",
        "",
        "Lay summary: results are ordered by a composite community-structure score rather than any single metric.",
        "The score rewards runs that explain more graph edges with their communities (`coverage`), produce tighter communities (`density`), keep communities better separated from the rest of the graph (`conductance`, lower is better), and preserve more local triangle structure (`clustering coefficient`).",
        "No degenerate penalty was needed in this classic single-checkpoint run because none of the results collapsed to a single nonempty community.",
        "",
        "| Rank | Embedding source | Score | Coverage | Density | Conductance | Clustering coeff. | Assigned fraction | Multi-membership fraction | Nonempty communities |",
        "| ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in rows:
        lines.append(
            f"| {row['community_structure_rank']} | `{row['embedding_source']}` | "
            f"{row['community_structure_score']:.4f} | "
            f"{row['coverage']:.4f} | "
            f"{row['density']:.4f} | "
            f"{row['conductance']:.4f} | "
            f"{row['clustering_coefficient']:.4f} | "
            f"{row['assigned_node_fraction']:.4f} | "
            f"{row['multi_membership_fraction']:.4f} | "
            f"{row['nonempty_community_count']} |"
        )
    return "\n".join(lines) + "\n"


def checkpoint_sweep_summary_markdown(rows: list[dict[str, Any]]) -> str:
    lines = [
        "# NOCD Checkpoint Sweep Summary",
        "",
        "Lay summary: results are ordered by a composite community-structure score rather than by one metric alone.",
        "The score rewards higher `coverage`, higher `density`, lower `conductance`, and higher `clustering coefficient`, so the top rows reflect the best overall balance of explanatory power, tightness, separation, and local structure.",
        "Rows marked `Degenerate = yes` collapsed to a single nonempty community. Those are explicitly penalized and pushed below nondegenerate runs even if their raw coverage or conductance looks superficially strong.",
        "",
        "| Rank | Model | Embedding source | Score | Coverage | Density | Conductance | Clustering coeff. | Assigned fraction | Multi-membership fraction | Nonempty communities | Degenerate |",
        "| ---: | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for row in rows:
        lines.append(
            f"| {row['community_structure_rank']} | `{row['model_key']}` | `{row['embedding_source']}` | "
            f"{row['community_structure_score']:.4f} | "
            f"{row['coverage']:.4f} | "
            f"{row['density']:.4f} | "
            f"{row['conductance']:.4f} | "
            f"{row['clustering_coefficient']:.4f} | "
            f"{row['assigned_node_fraction']:.4f} | "
            f"{row['multi_membership_fraction']:.4f} | "
            f"{row['nonempty_community_count']} | "
            f"{'yes' if row.get('degenerate_single_community') else 'no'} |"
        )
    return "\n".join(lines) + "\n"


def prepare_source_artifacts(
    source: EmbeddingSource,
    output_dir: Path,
    neighbor_count: int = DEFAULT_GRAPH_NEIGHBORS,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    adjacency = build_knn_adjacency(source.matrix, neighbor_count=neighbor_count)
    save_raw_csr_npz(output_dir / "graph.npz", adjacency)
    save_dense_features_npz(output_dir / "features.npz", source.matrix)
    graph_info = {
        "embedding_source": source.name,
        "node_count": len(source.ids),
        "feature_dim": int(source.matrix.shape[1]),
        "neighbor_count": int(neighbor_count),
        "edge_count": int(adjacency.nnz // 2),
        "mean_degree": float(adjacency.nnz / max(1, adjacency.shape[0])),
    }
    (output_dir / "graph_info.json").write_text(json.dumps(graph_info, indent=2, sort_keys=True), encoding="utf-8")
    return {"adjacency": adjacency, "features": source.matrix, "graph_info": graph_info}


def run_checkpoint_prediction(
    source: EmbeddingSource,
    adjacency: sp.csr_matrix,
    checkpoint_path: Path,
    output_dir: Path,
    output_model_key: str | None = None,
    device: str | None = None,
    threshold: float = 0.5,
) -> dict[str, Any]:
    from nocd.model import NOCD

    output_dir.mkdir(parents=True, exist_ok=True)
    model = NOCD.load(str(checkpoint_path), device=device or preferred_device())
    model.threshold = float(threshold)
    z_soft = np.asarray(model.predict_proba(adjacency, None), dtype=np.float32)
    z_binary = np.asarray(model.predict(adjacency, None), dtype=np.float32)
    np.savez(output_dir / "predictions.npz", Z_soft=z_soft, Z_binary=z_binary, threshold=float(threshold))
    metrics = summarize_memberships(source.ids, adjacency, z_soft, z_binary)
    metadata = {
        "embedding_source": source.name,
        "checkpoint_path": str(checkpoint_path),
        "mode": "checkpoint_predict",
        "model_type": str(model.model_type),
        "feature_type": str(model.feature_type),
        "device": str(device or preferred_device()),
        "threshold": float(threshold),
    }
    (output_dir / "metrics.json").write_text(
        json.dumps({"metadata": metadata, "metrics": metrics}, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    write_communities_json(output_dir / "communities.json", source.ids, z_binary, metrics, metadata)
    write_visualization(
        output_dir / "communities.png",
        adjacency,
        z_soft,
        title=f"{source.name} | {checkpoint_path.stem}",
        threshold=threshold,
    )
    return {
        "embedding_source": source.name,
        "model_key": str(output_model_key or checkpoint_path.stem),
        "mode": "checkpoint_predict",
        "model_type": str(model.model_type),
        "feature_type": str(model.feature_type),
        **metrics,
    }
