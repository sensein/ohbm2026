from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
from sklearn.mixture import GaussianMixture

from ohbm2026.neuroscape import load_embedding_bundle, prepare_clustering_matrix


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run a soft overlapping topic experiment with Gaussian-mixture posteriors")
    parser.add_argument("--embeddings-dir", required=True)
    parser.add_argument("--benchmark-json", required=True)
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--threshold", type=float, default=0.2)
    parser.add_argument("--top-k", type=int, default=2)
    parser.add_argument("--random-state", type=int, default=42)
    parser.set_defaults(row_normalize=True)
    parser.add_argument("--row-normalize", action="store_true", dest="row_normalize")
    parser.add_argument("--no-row-normalize", action="store_false", dest="row_normalize")
    parser.add_argument("--pca-components", type=int, default=50)
    return parser


def _normalized_entropy(probabilities: np.ndarray) -> float:
    nonzero = probabilities[probabilities > 0]
    if nonzero.size <= 1:
        return 0.0
    entropy = float(-(nonzero * np.log(nonzero)).sum())
    return entropy / math.log(float(probabilities.size))


def _load_cluster_count(benchmark_json: Path) -> int:
    payload = json.loads(benchmark_json.read_text(encoding="utf-8"))
    best_result = payload.get("best_result") or {}
    cluster_count = int(best_result.get("requested_cluster_count") or 0)
    if cluster_count < 2:
        raise ValueError(f"Benchmark file does not contain a usable cluster count: {benchmark_json}")
    return cluster_count


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    embeddings_dir = Path(args.embeddings_dir)
    benchmark_json = Path(args.benchmark_json)
    output_root = Path(args.output_root)
    output_root.mkdir(parents=True, exist_ok=True)

    bundle = load_embedding_bundle(embeddings_dir)
    prepared = prepare_clustering_matrix(
        bundle["matrix"],
        normalize_rows=bool(args.row_normalize),
        pca_components=args.pca_components,
        random_state=args.random_state,
    )
    cluster_count = _load_cluster_count(benchmark_json)
    model = GaussianMixture(
        n_components=cluster_count,
        covariance_type="diag",
        random_state=args.random_state,
    )
    matrix = np.asarray(prepared["matrix"], dtype=np.float32)
    model.fit(matrix)
    probabilities = np.asarray(model.predict_proba(matrix), dtype=np.float32)

    communities: dict[int, list[int]] = {cluster_id: [] for cluster_id in range(cluster_count)}
    memberships: dict[str, list[dict[str, float]]] = {}
    entropy_values: list[float] = []
    primary_probabilities: list[float] = []
    secondary_probabilities: list[float] = []
    multi_membership_count = 0

    for row_index, abstract_id in enumerate(bundle["ids"]):
        row = probabilities[row_index]
        order = np.argsort(row)[::-1]
        selected = [int(order[0])]
        for candidate in order[1:int(args.top_k)]:
            if float(row[candidate]) >= float(args.threshold):
                selected.append(int(candidate))
        if len(selected) > 1:
            multi_membership_count += 1
            secondary_probabilities.append(float(row[selected[1]]))
        for cluster_id in selected:
            communities[cluster_id].append(int(abstract_id))
        memberships[str(int(abstract_id))] = [
            {"cluster_id": int(cluster_id), "probability": float(row[cluster_id])}
            for cluster_id in selected
        ]
        entropy_values.append(_normalized_entropy(row))
        primary_probabilities.append(float(row[selected[0]]))

    nonempty_communities = {cluster_id: members for cluster_id, members in communities.items() if members}
    metrics = {
        "node_count": len(bundle["ids"]),
        "community_count": cluster_count,
        "nonempty_community_count": len(nonempty_communities),
        "multi_membership_node_count": multi_membership_count,
        "multi_membership_fraction": float(multi_membership_count / max(1, len(bundle["ids"]))),
        "mean_memberships_per_node": float(
            sum(len(membership) for membership in memberships.values()) / max(1, len(memberships))
        ),
        "mean_assignment_entropy": float(sum(entropy_values) / max(1, len(entropy_values))),
        "mean_primary_probability": float(sum(primary_probabilities) / max(1, len(primary_probabilities))),
        "mean_secondary_probability": float(
            sum(secondary_probabilities) / max(1, len(secondary_probabilities))
        ) if secondary_probabilities else 0.0,
        "largest_community_size": max((len(members) for members in nonempty_communities.values()), default=0),
        "smallest_nonempty_community_size": min((len(members) for members in nonempty_communities.values()), default=0),
    }
    metadata = {
        "embeddings_dir": str(embeddings_dir),
        "benchmark_json": str(benchmark_json),
        "threshold": float(args.threshold),
        "top_k": int(args.top_k),
        "cluster_count": cluster_count,
        "random_state": int(args.random_state),
        "preprocessing": prepared["metadata"],
    }

    (output_root / "metrics.json").write_text(
        json.dumps({"metadata": metadata, "metrics": metrics}, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    (output_root / "communities.json").write_text(
        json.dumps(
            {
                "metadata": metadata,
                "metrics": metrics,
                "num_communities": cluster_count,
                "communities": {str(cluster_id): members for cluster_id, members in sorted(nonempty_communities.items())},
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    (output_root / "memberships.json").write_text(
        json.dumps(
            {
                "metadata": metadata,
                "memberships": memberships,
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "embeddings_dir": str(embeddings_dir),
                "output_root": str(output_root),
                "cluster_count": cluster_count,
                "multi_membership_fraction": metrics["multi_membership_fraction"],
                "mean_primary_probability": metrics["mean_primary_probability"],
                "mean_secondary_probability": metrics["mean_secondary_probability"],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
