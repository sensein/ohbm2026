from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
from sklearn.metrics import silhouette_score

from ohbm2026.analyze import (
    DEFAULT_UMAP_MIN_DIST,
    DEFAULT_UMAP_NEIGHBORS,
    NeuroScapeError,
    load_embedding_bundle,
)


DEFAULT_OUTPUT_PATH = Path("data/embeddings/cluster_projection_silhouette.json")
DEFAULT_RANDOM_STATE = 42
DEFAULT_METRIC = "cosine"
CLUSTER_CONFIGS = {
    "semantic_25": {
        "label": "25-cluster benchmark",
        "embeddings_dir": Path("data/embeddings/voyage_stage2_published"),
        "assignments_path": Path("data/embeddings/voyage_stage2_published/clustering_benchmark/cluster_assignments.json"),
    },
    "claims_28": {
        "label": "Claims 28-cluster benchmark",
        "embeddings_dir": Path("data/embeddings/minilm_claims"),
        "assignments_path": Path("data/embeddings/minilm_claims/clustering_benchmark_25_30/cluster_assignments.json"),
    },
}


def load_cluster_assignments(path: Path) -> dict[int, int]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    assignments = payload.get("assignments")
    if not isinstance(assignments, dict):
        raise NeuroScapeError(f"Cluster assignments file is missing an assignments map: {path}")
    return {int(abstract_id): int(cluster_id) for abstract_id, cluster_id in assignments.items()}


def compute_umap_projection_nd(
    matrix: Any,
    n_components: int,
    n_neighbors: int,
    min_dist: float,
    metric: str,
    random_state: int,
) -> np.ndarray:
    import umap

    array = np.asarray(matrix)
    if int(array.shape[0]) <= 3:
        if int(array.shape[1]) >= n_components:
            return array[:, :n_components].astype(np.float32, copy=True)
        if int(array.shape[1]) > 0:
            padding = np.zeros((int(array.shape[0]), n_components - int(array.shape[1])), dtype=np.float32)
            return np.hstack([array.astype(np.float32, copy=True), padding])
        raise NeuroScapeError("UMAP projection requires at least one embedding dimension")

    reducer = umap.UMAP(
        n_components=n_components,
        n_neighbors=n_neighbors,
        min_dist=min_dist,
        metric=metric,
        random_state=random_state,
    )
    return np.asarray(reducer.fit_transform(array), dtype=np.float32)


def aligned_labels(ids: list[int], assignments: dict[int, int]) -> np.ndarray:
    missing_ids = [int(abstract_id) for abstract_id in ids if int(abstract_id) not in assignments]
    if missing_ids:
        preview = ", ".join(str(value) for value in missing_ids[:5])
        raise NeuroScapeError(f"Missing cluster assignments for {len(missing_ids)} abstracts: {preview}")
    return np.asarray([int(assignments[int(abstract_id)]) for abstract_id in ids], dtype=np.int32)


def safe_silhouette(matrix: np.ndarray, labels: np.ndarray) -> float | None:
    if len(set(labels.tolist())) <= 1:
        return None
    try:
        return float(silhouette_score(matrix, labels, metric="euclidean"))
    except Exception:
        return None


def analyze_cluster_projection(
    name: str,
    label: str,
    embeddings_dir: Path,
    assignments_path: Path,
    n_neighbors: int,
    min_dist: float,
    metric: str,
    random_state: int,
) -> dict[str, Any]:
    bundle = load_embedding_bundle(embeddings_dir)
    assignments = load_cluster_assignments(assignments_path)
    ids = [int(abstract_id) for abstract_id in bundle["ids"]]
    matrix = np.asarray(bundle["vectors"], dtype=np.float32)
    labels = aligned_labels(ids, assignments)

    projection_2d = compute_umap_projection_nd(
        matrix,
        n_components=2,
        n_neighbors=n_neighbors,
        min_dist=min_dist,
        metric=metric,
        random_state=random_state,
    )
    projection_3d = compute_umap_projection_nd(
        matrix,
        n_components=3,
        n_neighbors=n_neighbors,
        min_dist=min_dist,
        metric=metric,
        random_state=random_state,
    )

    original_silhouette = safe_silhouette(matrix, labels)
    silhouette_2d = safe_silhouette(projection_2d, labels)
    silhouette_3d = safe_silhouette(projection_3d, labels)
    return {
        "cluster_key": name,
        "label": label,
        "embeddings_dir": str(embeddings_dir),
        "assignments_path": str(assignments_path),
        "embedding_name": bundle.get("embedding_name"),
        "model_name": bundle.get("model_name"),
        "embedding_fields": list(bundle.get("embedding_fields") or []),
        "abstract_count": len(ids),
        "cluster_count": len(set(labels.tolist())),
        "umap_n_neighbors": int(n_neighbors),
        "umap_min_dist": float(min_dist),
        "umap_metric": metric,
        "silhouette_original": original_silhouette,
        "silhouette_2d": silhouette_2d,
        "silhouette_3d": silhouette_3d,
        "silhouette_3d_minus_2d": (
            None if silhouette_2d is None or silhouette_3d is None else float(silhouette_3d - silhouette_2d)
        ),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Compute silhouette scores for the semantic_25 and claims_28 cluster assignments on 2D and 3D UMAP projections."
    )
    parser.add_argument(
        "--cluster-key",
        choices=sorted(CLUSTER_CONFIGS),
        action="append",
        help="Limit the analysis to one or more cluster approaches. Defaults to both.",
    )
    parser.add_argument("--n-neighbors", type=int, default=DEFAULT_UMAP_NEIGHBORS)
    parser.add_argument("--min-dist", type=float, default=DEFAULT_UMAP_MIN_DIST)
    parser.add_argument("--metric", default=DEFAULT_METRIC)
    parser.add_argument("--random-state", type=int, default=DEFAULT_RANDOM_STATE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    cluster_keys = args.cluster_key or list(CLUSTER_CONFIGS.keys())
    results = [
        analyze_cluster_projection(
            name=cluster_key,
            label=str(CLUSTER_CONFIGS[cluster_key]["label"]),
            embeddings_dir=Path(CLUSTER_CONFIGS[cluster_key]["embeddings_dir"]),
            assignments_path=Path(CLUSTER_CONFIGS[cluster_key]["assignments_path"]),
            n_neighbors=int(args.n_neighbors),
            min_dist=float(args.min_dist),
            metric=str(args.metric),
            random_state=int(args.random_state),
        )
        for cluster_key in cluster_keys
    ]
    payload = {
        "projection_method": "umap",
        "dimensions_compared": [2, 3],
        "n_neighbors": int(args.n_neighbors),
        "min_dist": float(args.min_dist),
        "metric": str(args.metric),
        "random_state": int(args.random_state),
        "results": results,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
