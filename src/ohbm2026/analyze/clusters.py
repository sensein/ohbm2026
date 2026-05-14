"""Stage 4 clustering helpers + semantic-analysis surface.

Owns the legacy clustering surface lifted out of the monolithic
`analyze.py`:

- Clustering preparation + execution (`prepare_clustering_matrix`,
  `cluster_with_method`, `_agglomerative_kwargs`, `_normalize_rows`).
- Cluster-quality metrics (`compute_clustering_metrics`,
  `_normalized_cluster_entropy`, `rank_clustering_benchmark_results`,
  `_valid_benchmark_run`, `_normalized_metric_value`).
- Cluster benchmark runner + writer (`run_clustering_benchmark`,
  `write_clustering_benchmark`, `cluster_benchmark_main`).
- Semantic-community detection over a kNN graph
  (`build_knn_graph`, `detect_semantic_communities`,
  `detect_semantic_communities_at_resolution`,
  `detect_stage2_communities`).
- Cluster summarization + keyword extraction
  (`summarize_membership_groups`, `summarize_semantic_clusters`,
  `summarize_stage2_clusters`, `extract_cluster_keywords`,
  `build_group_rationale`).
- Semantic-analysis CLI surface (`write_semantic_analysis`,
  `write_stage2_analysis`, `semantic_analysis_main`,
  `stage2_analysis_main`).

The Stage 4 FAISS+Leiden+CPM community detection (US4) lands in
`analyze/communities.py` separately; this module retains the
sklearn-based kNN graph + Louvain-style community detection used by
the existing semantic-analysis CLI and the cluster benchmark.
"""

from __future__ import annotations

import argparse
import copy
import json
import math
from collections import Counter
from pathlib import Path
from typing import Any

import numpy as np

from ohbm2026 import artifacts
from ohbm2026.analyze.storage import (
    ALLOWED_EMBEDDING_FIELDS,
    DEFAULT_EMBEDDING_FIELDS,
    NeuroScapeError,
    build_distinct_color_map,
    build_embedding_output_name,
    build_embedding_text,
    build_embedding_texts,
    build_visualization_records,
    compute_neighbors,
    embedding_variant_name,
    extract_primary_topic,
    extract_raw_keywords,
    load_annotation_lookup,
    load_embedding_bundle,
    load_embedding_inputs,
    load_title_lookup,
    model_name_slug,
    normalize_embedding_fields,
    parse_string_list_value,
    unique_strings,
    write_embedding_bundle,
    write_json,
)
from ohbm2026.titles import cleaned_abstract_title


def _normalize_rows(matrix: Any) -> Any:
    import numpy as np

    normalized = np.asarray(matrix, dtype=np.float32).copy()
    norms = np.linalg.norm(normalized, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return normalized / norms


def prepare_clustering_matrix(
    matrix: Any,
    normalize_rows: bool = True,
    pca_components: int | None = 50,
    random_state: int = 42,
) -> dict[str, Any]:
    import numpy as np

    prepared = np.asarray(matrix, dtype=np.float32)
    metadata: dict[str, Any] = {
        "input_dimension": int(prepared.shape[1]) if prepared.ndim == 2 else 0,
        "row_normalized": bool(normalize_rows),
        "pca_components": None,
    }
    if normalize_rows:
        prepared = _normalize_rows(prepared)
    requested_components = None if pca_components is None else int(pca_components)
    if requested_components and requested_components > 0:
        max_components = min(int(prepared.shape[0]), int(prepared.shape[1]))
        effective_components = min(requested_components, max_components)
        if effective_components >= 2 and effective_components < int(prepared.shape[1]):
            from sklearn.decomposition import PCA

            reducer = PCA(n_components=effective_components, random_state=random_state)
            prepared = reducer.fit_transform(prepared).astype(np.float32, copy=False)
            metadata["pca_components"] = int(effective_components)
            metadata["explained_variance_ratio"] = float(reducer.explained_variance_ratio_.sum())
    metadata["output_dimension"] = int(prepared.shape[1]) if prepared.ndim == 2 else 0
    return {"matrix": prepared, "metadata": metadata}


def _agglomerative_kwargs(metric: str, linkage: str) -> dict[str, Any]:
    kwargs: dict[str, Any] = {"n_clusters": None, "distance_threshold": None, "linkage": linkage}
    try:
        from sklearn.cluster import AgglomerativeClustering

        AgglomerativeClustering(metric=metric, **kwargs)
        kwargs["metric"] = metric
    except TypeError:
        kwargs["affinity"] = metric
    return kwargs


def cluster_with_method(
    matrix: Any,
    method: str,
    cluster_count: int,
    random_state: int = 42,
) -> list[int]:
    import numpy as np
    from sklearn.cluster import AgglomerativeClustering, Birch, KMeans, SpectralClustering
    from sklearn.mixture import GaussianMixture

    method_name = str(method).strip().lower()
    if cluster_count < 2:
        raise NeuroScapeError("cluster_count must be at least 2")

    if method_name == "kmeans":
        estimator = KMeans(n_clusters=cluster_count, random_state=random_state, n_init=10)
        return estimator.fit_predict(matrix).astype(np.int32).tolist()
    if method_name == "agglomerative-ward":
        estimator = AgglomerativeClustering(n_clusters=cluster_count, linkage="ward")
        return estimator.fit_predict(matrix).astype(np.int32).tolist()
    if method_name == "agglomerative-average":
        kwargs = _agglomerative_kwargs("cosine", "average")
        kwargs["n_clusters"] = cluster_count
        kwargs.pop("distance_threshold", None)
        estimator = AgglomerativeClustering(**kwargs)
        try:
            return estimator.fit_predict(matrix).astype(np.int32).tolist()
        except ValueError as exc:
            if "zero vectors" not in str(exc).lower():
                raise
            fallback_kwargs = _agglomerative_kwargs("euclidean", "average")
            fallback_kwargs["n_clusters"] = cluster_count
            fallback_kwargs.pop("distance_threshold", None)
            fallback_estimator = AgglomerativeClustering(**fallback_kwargs)
            return fallback_estimator.fit_predict(matrix).astype(np.int32).tolist()
    if method_name == "gaussian-mixture":
        estimator = GaussianMixture(n_components=cluster_count, covariance_type="diag", random_state=random_state)
        return estimator.fit(matrix).predict(matrix).astype(np.int32).tolist()
    if method_name == "birch":
        estimator = Birch(n_clusters=cluster_count)
        return estimator.fit_predict(matrix).astype(np.int32).tolist()
    if method_name == "spectral-nearest-neighbors":
        array = np.asarray(matrix, dtype=np.float32)
        if int(array.shape[0]) <= cluster_count:
            raise NeuroScapeError("spectral-nearest-neighbors requires more rows than cluster_count")
        n_neighbors = min(max(int(cluster_count), 10), int(array.shape[0]) - 1)
        estimator = SpectralClustering(
            n_clusters=cluster_count,
            affinity="nearest_neighbors",
            n_neighbors=n_neighbors,
            assign_labels="kmeans",
            random_state=random_state,
        )
        return estimator.fit_predict(array).astype(np.int32).tolist()
    raise NeuroScapeError(f"Unsupported clustering method: {method}")


def _normalized_cluster_entropy(counts: list[int]) -> float:
    import math

    total = sum(counts)
    if total <= 0 or len(counts) <= 1:
        return 0.0
    probabilities = [count / total for count in counts if count > 0]
    entropy = -sum(probability * math.log(probability) for probability in probabilities)
    return float(entropy / math.log(len(probabilities))) if len(probabilities) > 1 else 0.0


def compute_clustering_metrics(
    ids: list[int],
    matrix: Any,
    labels: list[int] | tuple[int, ...],
) -> dict[str, Any]:
    import numpy as np
    from sklearn.metrics import calinski_harabasz_score, davies_bouldin_score, silhouette_score

    if len(ids) != len(labels):
        raise NeuroScapeError("ID and label counts do not match")
    numeric_labels = np.asarray(labels, dtype=np.int32)
    cluster_ids = sorted({int(value) for value in numeric_labels.tolist()})
    cluster_sizes = [int(np.sum(numeric_labels == cluster_id)) for cluster_id in cluster_ids]
    total = max(1, len(labels))
    assignments = {int(abstract_id): int(cluster_id) for abstract_id, cluster_id in zip(ids, numeric_labels.tolist())}
    distance_metrics = _cluster_distance_metrics(ids, matrix, assignments)

    metrics: dict[str, Any] = {
        "cluster_count": len(cluster_ids),
        "cluster_sizes": cluster_sizes,
        "largest_cluster_fraction": (max(cluster_sizes) / total) if cluster_sizes else 1.0,
        "smallest_cluster_size": min(cluster_sizes) if cluster_sizes else 0,
        "cluster_size_std_fraction": (
            float(np.std(cluster_sizes) / np.mean(cluster_sizes)) if len(cluster_sizes) > 1 else 0.0
        ),
        "cluster_size_entropy": _normalized_cluster_entropy(cluster_sizes),
        "mean_intercluster_distance": float(distance_metrics["mean_intercluster_distance"]),
        "mean_intracluster_distance": float(distance_metrics["mean_intracluster_distance"]),
        "intercluster_distance_ratio": float(distance_metrics["intercluster_distance_ratio"]),
        "silhouette_score": None,
        "calinski_harabasz_score": None,
        "davies_bouldin_score": None,
        "valid": len(cluster_ids) > 1,
    }
    if len(cluster_ids) <= 1:
        return metrics

    try:
        metrics["silhouette_score"] = float(silhouette_score(matrix, numeric_labels, metric="euclidean"))
    except Exception:
        metrics["silhouette_score"] = None
    try:
        metrics["calinski_harabasz_score"] = float(calinski_harabasz_score(matrix, numeric_labels))
    except Exception:
        metrics["calinski_harabasz_score"] = None
    try:
        metrics["davies_bouldin_score"] = float(davies_bouldin_score(matrix, numeric_labels))
    except Exception:
        metrics["davies_bouldin_score"] = None
    return metrics


def _valid_benchmark_run(result: dict[str, Any]) -> bool:
    cluster_count = int(result.get("cluster_count") or 0)
    smallest_cluster_size = int(result.get("smallest_cluster_size") or 0)
    largest_cluster_fraction = float(result.get("largest_cluster_fraction") or 1.0)
    return (
        bool(result.get("valid"))
        and cluster_count >= 2
        and smallest_cluster_size > 0
        and largest_cluster_fraction < 0.98
    )


def _normalized_metric_value(
    results: list[dict[str, Any]],
    result: dict[str, Any],
    key: str,
    higher_is_better: bool,
) -> float:
    numeric_values = [
        float(candidate[key])
        for candidate in results
        if _valid_benchmark_run(candidate) and candidate.get(key) is not None
    ]
    if not numeric_values or result.get(key) is None:
        return 0.0
    value = float(result[key])
    minimum = min(numeric_values)
    maximum = max(numeric_values)
    if maximum <= minimum:
        return 1.0
    normalized = (value - minimum) / (maximum - minimum)
    return normalized if higher_is_better else 1.0 - normalized


def rank_clustering_benchmark_results(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ranked: list[dict[str, Any]] = []
    for result in results:
        normalized_metrics = {
            "silhouette": _normalized_metric_value(results, result, "silhouette_score", higher_is_better=True),
            "intercluster_ratio": _normalized_metric_value(
                results,
                result,
                "intercluster_distance_ratio",
                higher_is_better=True,
            ),
            "calinski_harabasz": _normalized_metric_value(
                results,
                result,
                "calinski_harabasz_score",
                higher_is_better=True,
            ),
            "davies_bouldin": _normalized_metric_value(
                results,
                result,
                "davies_bouldin_score",
                higher_is_better=False,
            ),
            "cluster_entropy": _normalized_metric_value(
                results,
                result,
                "cluster_size_entropy",
                higher_is_better=True,
            ),
            "cluster_balance": _normalized_metric_value(
                results,
                result,
                "largest_cluster_fraction",
                higher_is_better=False,
            ),
        }
        weights = {
            "silhouette": 0.30,
            "intercluster_ratio": 0.20,
            "calinski_harabasz": 0.15,
            "davies_bouldin": 0.15,
            "cluster_entropy": 0.10,
            "cluster_balance": 0.10,
        }
        composite_score = sum(normalized_metrics[key] * weights[key] for key in weights)
        if not _valid_benchmark_run(result):
            composite_score = -1.0
        ranked_result = dict(result)
        ranked_result["normalized_metrics"] = normalized_metrics
        ranked_result["composite_score"] = float(composite_score)
        ranked.append(ranked_result)

    return sorted(
        ranked,
        key=lambda item: (
            float(item.get("composite_score") or -1.0),
            float(item.get("silhouette_score") if item.get("silhouette_score") is not None else -1.0),
            float(item.get("intercluster_distance_ratio") or 0.0),
            -float(item.get("davies_bouldin_score") or 999999.0),
        ),
        reverse=True,
    )


def run_clustering_benchmark(
    ids: list[int],
    matrix: Any,
    methods: list[str],
    k_values: list[int],
    random_state: int = 42,
) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    best_labels_by_signature: dict[tuple[str, int], list[int]] = {}
    for method in methods:
        for cluster_count in k_values:
            try:
                labels = cluster_with_method(matrix, method, cluster_count=cluster_count, random_state=random_state)
                metrics = compute_clustering_metrics(ids, matrix, labels)
                result = {
                    "method": method,
                    "requested_cluster_count": int(cluster_count),
                    **metrics,
                }
                results.append(result)
                best_labels_by_signature[(method, int(cluster_count))] = labels
            except Exception as exc:
                results.append(
                    {
                        "method": method,
                        "requested_cluster_count": int(cluster_count),
                        "cluster_count": 0,
                        "valid": False,
                        "error": str(exc),
                    }
                )
    ranked_results = rank_clustering_benchmark_results(results)
    best_result = ranked_results[0] if ranked_results else None
    best_labels = None
    if best_result and _valid_benchmark_run(best_result):
        best_labels = best_labels_by_signature.get(
            (str(best_result["method"]), int(best_result["requested_cluster_count"]))
        )
    return {
        "results": ranked_results,
        "best_result": best_result,
        "best_labels": best_labels,
    }


def write_clustering_benchmark(
    output_dir: Path,
    benchmark: dict[str, Any],
    ids: list[int],
    records: list[dict[str, Any]],
    matrix: Any,
    config: dict[str, Any],
    max_keywords: int = 8,
    max_representatives: int = 5,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(
        output_dir / "benchmark.json",
        {
            "config": config,
            "best_result": benchmark["best_result"],
            "results": benchmark["results"],
        },
    )
    best_result = benchmark.get("best_result")
    best_labels = benchmark.get("best_labels")
    if not best_result or not best_labels or not _valid_benchmark_run(best_result):
        return
    assignments = {
        int(abstract_id): int(cluster_id)
        for abstract_id, cluster_id in zip(ids, best_labels)
    }
    cluster_summaries = summarize_semantic_clusters(
        ids,
        matrix,
        records,
        assignments,
        max_keywords=max_keywords,
        max_representatives=max_representatives,
    )
    write_json(output_dir / "best_run.json", {"result": best_result})
    write_json(
        output_dir / "cluster_assignments.json",
        {
            "assignments": {
                str(abstract_id): cluster_id
                for abstract_id, cluster_id in sorted(assignments.items())
            }
        },
    )
    write_json(output_dir / "cluster_summaries.json", {"clusters": cluster_summaries})


def load_enriched_lookup(path: Path) -> dict[int, dict[str, Any]]:
    return {
        abstract["id"]: abstract
        for abstract in load_embedding_inputs(path)
        if isinstance(abstract.get("id"), int)
    }


def align_semantic_records(
    ids: list[int],
    enriched_lookup: dict[int, dict[str, Any]],
    title_lookup: dict[int, str] | None = None,
    embedding_fields: list[str] | tuple[str, ...] | None = None,
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    selected_fields = normalize_embedding_fields(embedding_fields)
    for abstract_id in ids:
        abstract = enriched_lookup.get(abstract_id, {"id": abstract_id})
        record = dict(abstract)
        record["id"] = abstract_id
        record["title"] = (
            (title_lookup or {}).get(abstract_id)
            or abstract.get("title")
            or ""
        )
        record["cluster_document"] = build_embedding_text(
            record,
            selected_fields,
            title_lookup=title_lookup,
        )
        records.append(record)
    return records


def align_cluster_records(
    ids: list[int],
    enriched_lookup: dict[int, dict[str, Any]],
    title_lookup: dict[int, str] | None = None,
    embedding_fields: list[str] | tuple[str, ...] | None = None,
) -> list[dict[str, Any]]:
    return align_semantic_records(
        ids,
        enriched_lookup,
        title_lookup=title_lookup,
        embedding_fields=embedding_fields,
    )


def build_knn_graph(ids: list[int], matrix: Any, num_neighbors: int = 50) -> Any:
    import networkx as nx
    from sklearn.neighbors import NearestNeighbors

    if num_neighbors <= 0:
        raise NeuroScapeError("num_neighbors must be positive")
    if len(ids) != int(matrix.shape[0]):
        raise NeuroScapeError("IDs and matrix row count do not match")

    graph = nx.Graph()
    graph.add_nodes_from(int(abstract_id) for abstract_id in ids)
    neighbor_count = min(num_neighbors + 1, int(matrix.shape[0]))
    search = NearestNeighbors(n_neighbors=neighbor_count, metric="cosine", algorithm="brute")
    search.fit(matrix)
    distances, indices = search.kneighbors(matrix)

    for row_index, abstract_id in enumerate(ids):
        for neighbor_index, distance in zip(indices[row_index][1:], distances[row_index][1:]):
            neighbor_id = int(ids[int(neighbor_index)])
            similarity = max(0.0, 1.0 - float(distance))
            if similarity <= 0.0:
                continue
            if graph.has_edge(int(abstract_id), neighbor_id):
                graph[int(abstract_id)][neighbor_id]["weight"] = max(
                    float(graph[int(abstract_id)][neighbor_id]["weight"]),
                    similarity,
                )
            else:
                graph.add_edge(int(abstract_id), neighbor_id, weight=similarity)
    return graph


def detect_semantic_communities(
    graph: Any,
    num_resolution_parameter: int = 20,
    max_resolution_parameter: float = 1.0,
    min_community_count: int = 1,
) -> dict[str, Any]:
    import numpy as np
    from networkx.algorithms.community import greedy_modularity_communities, modularity

    if num_resolution_parameter <= 0:
        raise NeuroScapeError("num_resolution_parameter must be positive")
    if min_community_count <= 0:
        raise NeuroScapeError("min_community_count must be positive")
    resolution_values = np.linspace(
        max_resolution_parameter / num_resolution_parameter,
        max_resolution_parameter,
        num_resolution_parameter,
    )
    history: list[dict[str, Any]] = []
    best_modularity = float("-inf")
    best_resolution = float(resolution_values[0])
    best_communities: list[set[int]] = []
    best_nontrivial_modularity = float("-inf")
    best_nontrivial_resolution = float(resolution_values[0])
    best_nontrivial_communities: list[set[int]] = []

    for resolution in resolution_values:
        try:
            communities = list(
                greedy_modularity_communities(
                    graph,
                    weight="weight",
                    resolution=float(resolution),
                )
            )
            modularity_value = float(
                modularity(graph, communities, weight="weight", resolution=float(resolution))
            )
        except TypeError:
            communities = list(greedy_modularity_communities(graph, weight="weight"))
            modularity_value = float(modularity(graph, communities, weight="weight"))
        history.append(
            {
                "resolution": float(resolution),
                "modularity": modularity_value,
                "community_count": len(communities),
            }
        )
        if modularity_value > best_modularity:
            best_modularity = modularity_value
            best_resolution = float(resolution)
            best_communities = [set(community) for community in communities]
        if len(communities) >= min_community_count and modularity_value > best_nontrivial_modularity:
            best_nontrivial_modularity = modularity_value
            best_nontrivial_resolution = float(resolution)
            best_nontrivial_communities = [set(community) for community in communities]

    selected_communities = best_nontrivial_communities or best_communities
    selected_modularity = best_nontrivial_modularity if best_nontrivial_communities else best_modularity
    selected_resolution = best_nontrivial_resolution if best_nontrivial_communities else best_resolution

    ordered_communities = sorted(selected_communities, key=lambda community: (-len(community), min(community)))
    assignments: dict[int, int] = {}
    for cluster_id, community in enumerate(ordered_communities):
        for abstract_id in community:
            assignments[int(abstract_id)] = cluster_id

    return {
        "best_resolution": selected_resolution,
        "best_modularity": selected_modularity,
        "history": history,
        "communities": ordered_communities,
        "assignments": assignments,
    }


def detect_semantic_communities_at_resolution(
    graph: Any,
    resolution: float,
) -> dict[str, Any]:
    from networkx.algorithms.community import greedy_modularity_communities, modularity

    if resolution <= 0:
        raise NeuroScapeError("resolution must be positive")
    try:
        communities = list(
            greedy_modularity_communities(
                graph,
                weight="weight",
                resolution=float(resolution),
            )
        )
        modularity_value = float(
            modularity(graph, communities, weight="weight", resolution=float(resolution))
        )
    except TypeError:
        communities = list(greedy_modularity_communities(graph, weight="weight"))
        modularity_value = float(modularity(graph, communities, weight="weight"))

    ordered_communities = sorted(communities, key=lambda community: (-len(community), min(community)))
    assignments: dict[int, int] = {}
    for cluster_id, community in enumerate(ordered_communities):
        for abstract_id in community:
            assignments[int(abstract_id)] = cluster_id

    return {
        "best_resolution": float(resolution),
        "best_modularity": modularity_value,
        "history": [
            {
                "resolution": float(resolution),
                "modularity": modularity_value,
                "community_count": len(ordered_communities),
            }
        ],
        "communities": [set(community) for community in ordered_communities],
        "assignments": assignments,
    }


def detect_stage2_communities(
    graph: Any,
    num_resolution_parameter: int = 20,
    max_resolution_parameter: float = 1.0,
    min_community_count: int = 1,
) -> dict[str, Any]:
    return detect_semantic_communities(
        graph,
        num_resolution_parameter=num_resolution_parameter,
        max_resolution_parameter=max_resolution_parameter,
        min_community_count=min_community_count,
    )


def extract_cluster_keywords(documents: list[str], max_keywords: int = 8) -> list[str]:
    from sklearn.feature_extraction.text import TfidfVectorizer

    filtered_documents = [document for document in documents if document.strip()]
    if not filtered_documents:
        return []
    try:
        vectorizer = TfidfVectorizer(stop_words="english", ngram_range=(1, 2), max_features=5000)
        matrix = vectorizer.fit_transform(filtered_documents)
    except ValueError:
        return []
    scores = matrix.sum(axis=0).A1
    feature_names = vectorizer.get_feature_names_out()
    ranked_indices = scores.argsort()[::-1]
    keywords = [feature_names[index] for index in ranked_indices if scores[index] > 0]
    return keywords[:max_keywords]


def build_group_rationale(
    *,
    group_label: str,
    keywords: list[str],
    primary_topic_counts: dict[str, int],
    accepted_for_counts: dict[str, int],
) -> str:
    keyword_phrase = ", ".join(keywords[:3]) if keywords else group_label
    dominant_topics = sorted(primary_topic_counts.items(), key=lambda item: (-int(item[1]), item[0]))
    dominant_formats = sorted(accepted_for_counts.items(), key=lambda item: (-int(item[1]), item[0]))
    topic_phrase = ", ".join(topic for topic, _count in dominant_topics[:2]) if dominant_topics else "multiple areas"
    format_phrase = (
        ", ".join(format_name for format_name, _count in dominant_formats[:2])
        if dominant_formats
        else "multiple presentation formats"
    )
    return (
        f"This group centers on {keyword_phrase} and connects abstracts spanning {topic_phrase}. "
        f"The current members are mostly associated with {format_phrase}."
    )


def summarize_membership_groups(
    ids: list[int],
    matrix: Any,
    records: list[dict[str, Any]],
    group_members: dict[int, list[int]],
    max_keywords: int = 8,
    max_representatives: int = 5,
) -> list[dict[str, Any]]:
    import numpy as np

    if not group_members:
        return []

    index_by_id = {int(abstract_id): position for position, abstract_id in enumerate(ids)}
    record_by_id = {int(record["id"]): record for record in records}
    centroids: dict[int, Any] = {}
    valid_group_ids: list[int] = []
    for group_id, member_ids in sorted(group_members.items()):
        filtered_member_ids = [int(member_id) for member_id in member_ids if int(member_id) in index_by_id]
        if not filtered_member_ids:
            continue
        member_matrix = matrix[[index_by_id[member_id] for member_id in filtered_member_ids]]
        centroid = member_matrix.mean(axis=0)
        centroid_norm = np.linalg.norm(centroid)
        if centroid_norm:
            centroid = centroid / centroid_norm
        centroids[int(group_id)] = centroid
        valid_group_ids.append(int(group_id))

    if not valid_group_ids:
        return []

    centroid_matrix = np.vstack([centroids[group_id] for group_id in valid_group_ids])
    centroid_similarities = centroid_matrix @ centroid_matrix.T
    summaries: list[dict[str, Any]] = []
    for group_position, group_id in enumerate(valid_group_ids):
        member_ids = sorted(int(member_id) for member_id in group_members[group_id] if int(member_id) in index_by_id)
        member_indices = [index_by_id[member_id] for member_id in member_ids]
        member_matrix = matrix[member_indices]
        centroid = centroids[group_id]
        scores = member_matrix @ centroid
        representative_order = np.argsort(scores)[::-1][:max_representatives]
        representative_ids = [member_ids[index] for index in representative_order]
        documents = [record_by_id.get(member_id, {}).get("cluster_document", "") for member_id in member_ids]
        keywords = extract_cluster_keywords(documents, max_keywords=max_keywords)
        accepted_for_counts: dict[str, int] = {}
        primary_topic_counts: dict[str, int] = {}
        for member_id in member_ids:
            record = record_by_id.get(member_id, {})
            accepted_for = str(record.get("accepted_for") or "Unknown")
            primary_topic = str(record.get("primary_topic") or "Unknown")
            accepted_for_counts[accepted_for] = accepted_for_counts.get(accepted_for, 0) + 1
            primary_topic_counts[primary_topic] = primary_topic_counts.get(primary_topic, 0) + 1
        similarity_row = centroid_similarities[group_position].copy()
        similarity_row[group_position] = -1.0
        nearest_group_position = int(np.argmax(similarity_row)) if len(valid_group_ids) > 1 else group_position
        label = ", ".join(keywords[:3]) if keywords else f"Group {group_id}"
        summaries.append(
            {
                "group_id": group_id,
                "size": len(member_ids),
                "label": label,
                "keywords": keywords,
                "rationale": build_group_rationale(
                    group_label=label,
                    keywords=keywords,
                    primary_topic_counts=primary_topic_counts,
                    accepted_for_counts=accepted_for_counts,
                ),
                "accepted_for_counts": accepted_for_counts,
                "primary_topic_counts": primary_topic_counts,
                "representative_abstracts": [
                    {
                        "id": member_id,
                        "title": record_by_id.get(member_id, {}).get("title") or "",
                    }
                    for member_id in representative_ids
                ],
                "most_similar_group_id": valid_group_ids[nearest_group_position],
                "most_similar_group_score": float(similarity_row[nearest_group_position]),
                "member_ids": member_ids,
            }
        )
    return summaries


def summarize_semantic_clusters(
    ids: list[int],
    matrix: Any,
    records: list[dict[str, Any]],
    assignments: dict[int, int],
    max_keywords: int = 8,
    max_representatives: int = 5,
) -> list[dict[str, Any]]:
    cluster_members: dict[int, list[int]] = {}
    for abstract_id, cluster_id in assignments.items():
        cluster_members.setdefault(int(cluster_id), []).append(int(abstract_id))
    group_summaries = summarize_membership_groups(
        ids,
        matrix,
        records,
        cluster_members,
        max_keywords=max_keywords,
        max_representatives=max_representatives,
    )
    summaries: list[dict[str, Any]] = []
    for summary in group_summaries:
        cluster_summary = dict(summary)
        cluster_summary["cluster_id"] = int(cluster_summary.pop("group_id"))
        cluster_summary["most_similar_cluster_id"] = int(cluster_summary.pop("most_similar_group_id"))
        cluster_summary["most_similar_cluster_score"] = float(cluster_summary.pop("most_similar_group_score"))
        summaries.append(cluster_summary)
    return summaries


def summarize_stage2_clusters(
    ids: list[int],
    matrix: Any,
    records: list[dict[str, Any]],
    assignments: dict[int, int],
    max_keywords: int = 8,
    max_representatives: int = 5,
) -> list[dict[str, Any]]:
    return summarize_semantic_clusters(
        ids,
        matrix,
        records,
        assignments,
        max_keywords=max_keywords,
        max_representatives=max_representatives,
    )


def write_semantic_analysis(
    output_dir: Path,
    graph: Any,
    community_result: dict[str, Any],
    cluster_summaries: list[dict[str, Any]],
) -> None:
    import networkx as nx

    output_dir.mkdir(parents=True, exist_ok=True)
    graphml_graph = nx.relabel_nodes(graph, lambda node: str(node))
    nx.write_graphml(graphml_graph, output_dir / "article_similarity.graphml")
    write_json(
        output_dir / "community_detection.json",
        {
            "best_resolution": community_result["best_resolution"],
            "best_modularity": community_result["best_modularity"],
            "history": community_result["history"],
        },
    )
    write_json(
        output_dir / "cluster_assignments.json",
        {
            "assignments": {
                str(abstract_id): cluster_id
                for abstract_id, cluster_id in sorted(community_result["assignments"].items())
            }
        },
    )
    write_json(output_dir / "cluster_summaries.json", {"clusters": cluster_summaries})


def write_stage2_analysis(
    output_dir: Path,
    graph: Any,
    community_result: dict[str, Any],
    cluster_summaries: list[dict[str, Any]],
) -> None:
    write_semantic_analysis(output_dir, graph, community_result, cluster_summaries)


def build_cluster_benchmark_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Benchmark label-independent clustering methods over a local embedding bundle"
    )
    parser.add_argument("--embeddings-dir", default=str(artifacts.EMBEDDINGS_ROOT / "minilm_stage1"))
    parser.add_argument("--input", default=str(artifacts.PRIMARY_ENRICHED_ABSTRACTS_PATH))
    parser.add_argument("--title-input", default=str(artifacts.PRIMARY_ABSTRACTS_PATH))
    parser.add_argument(
        "--output-dir",
        default=str(
            artifacts.build_output_path(
                "experiments",
                "clustering_benchmark",
                artifacts.build_state_key(
                    artifacts.build_dependency_basis(
                        input_sources=[
                            str(artifacts.EMBEDDINGS_ROOT / "minilm_stage1"),
                            str(artifacts.PRIMARY_ENRICHED_ABSTRACTS_PATH),
                            str(artifacts.PRIMARY_ABSTRACTS_PATH),
                        ]
                    )
                ),
            )
        ),
    )
    parser.add_argument(
        "--methods",
        nargs="+",
        default=["kmeans", "agglomerative-ward", "agglomerative-average", "gaussian-mixture", "birch"],
    )
    parser.add_argument("--k-min", type=int, default=2)
    parser.add_argument("--k-max", type=int, default=30)
    parser.set_defaults(row_normalize=True)
    parser.add_argument("--row-normalize", action="store_true", dest="row_normalize")
    parser.add_argument("--no-row-normalize", action="store_false", dest="row_normalize")
    parser.add_argument("--pca-components", type=int, default=50)
    parser.add_argument("--random-state", type=int, default=42)
    parser.add_argument("--max-keywords", type=int, default=8)
    parser.add_argument("--max-representatives", type=int, default=5)
    return parser


def cluster_benchmark_main(argv: list[str] | None = None) -> int:
    args = build_cluster_benchmark_parser().parse_args(argv)
    if args.k_min < 2:
        raise NeuroScapeError("k-min must be at least 2")
    if args.k_max < args.k_min:
        raise NeuroScapeError("k-max must be greater than or equal to k-min")
    bundle = load_embedding_bundle(Path(args.embeddings_dir))
    prepared = prepare_clustering_matrix(
        bundle["matrix"],
        normalize_rows=bool(args.row_normalize),
        pca_components=args.pca_components,
        random_state=args.random_state,
    )
    embedding_fields = normalize_embedding_fields(bundle["source_metadata"].get("embedding_fields"))
    title_lookup = load_title_lookup(Path(args.title_input))
    enriched_lookup = load_enriched_lookup(Path(args.input))
    records = align_cluster_records(
        bundle["ids"],
        enriched_lookup,
        title_lookup=title_lookup,
        embedding_fields=embedding_fields,
    )
    methods = [str(method).strip().lower() for method in args.methods if str(method).strip()]
    k_values = list(range(int(args.k_min), int(args.k_max) + 1))
    benchmark = run_clustering_benchmark(
        bundle["ids"],
        prepared["matrix"],
        methods=methods,
        k_values=k_values,
        random_state=args.random_state,
    )
    config = {
        "embeddings_dir": args.embeddings_dir,
        "input": args.input,
        "title_input": args.title_input,
        "methods": methods,
        "k_values": k_values,
        "random_state": args.random_state,
        **prepared["metadata"],
    }
    write_clustering_benchmark(
        Path(args.output_dir),
        benchmark,
        bundle["ids"],
        records,
        prepared["matrix"],
        config,
        max_keywords=args.max_keywords,
        max_representatives=args.max_representatives,
    )
    valid_results = [result for result in benchmark["results"] if _valid_benchmark_run(result)]
    print(
        json.dumps(
            {
                "embeddings_dir": args.embeddings_dir,
                "output_dir": args.output_dir,
                "count": len(bundle["ids"]),
                "tested_runs": len(benchmark["results"]),
                "valid_runs": len(valid_results),
                "best_result": benchmark["best_result"],
                "preprocessing": prepared["metadata"],
            },
            indent=2,
        )
    )
    return 0


def build_semantic_analysis_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build a semantic graph, detect communities, and summarize clusters from a local embedding bundle"
    )
    parser.add_argument("--embeddings-dir", default=str(artifacts.EMBEDDINGS_ROOT / "minilm_stage1"))
    parser.add_argument("--input", default=str(artifacts.PRIMARY_ENRICHED_ABSTRACTS_PATH))
    parser.add_argument("--title-input", default=str(artifacts.PRIMARY_ABSTRACTS_PATH))
    parser.add_argument(
        "--output-dir",
        default=str(
            artifacts.build_output_path(
                "experiments",
                "semantic_analysis",
                artifacts.build_state_key(
                    artifacts.build_dependency_basis(
                        input_sources=[
                            str(artifacts.EMBEDDINGS_ROOT / "minilm_stage1"),
                            str(artifacts.PRIMARY_ENRICHED_ABSTRACTS_PATH),
                            str(artifacts.PRIMARY_ABSTRACTS_PATH),
                        ]
                    )
                ),
            )
        ),
    )
    parser.add_argument("--num-neighbors", type=int, default=50)
    parser.add_argument("--resolution", type=float)
    parser.add_argument("--num-resolution-parameter", type=int, default=20)
    parser.add_argument("--max-resolution-parameter", type=float, default=1.0)
    parser.add_argument("--min-community-count", type=int, default=1)
    parser.add_argument("--max-keywords", type=int, default=8)
    parser.add_argument("--max-representatives", type=int, default=5)
    return parser


def semantic_analysis_main(argv: list[str] | None = None) -> int:
    args = build_semantic_analysis_parser().parse_args(argv)
    bundle = load_embedding_bundle(Path(args.embeddings_dir))
    embedding_fields = normalize_embedding_fields(bundle["source_metadata"].get("embedding_fields"))
    title_lookup = load_title_lookup(Path(args.title_input))
    enriched_lookup = load_enriched_lookup(Path(args.input))
    records = align_semantic_records(
        bundle["ids"],
        enriched_lookup,
        title_lookup=title_lookup,
        embedding_fields=embedding_fields,
    )
    graph = build_knn_graph(bundle["ids"], bundle["matrix"], num_neighbors=args.num_neighbors)
    if args.resolution is not None:
        community_result = detect_semantic_communities_at_resolution(graph, args.resolution)
    else:
        community_result = detect_semantic_communities(
            graph,
            num_resolution_parameter=args.num_resolution_parameter,
            max_resolution_parameter=args.max_resolution_parameter,
            min_community_count=args.min_community_count,
        )
    cluster_summaries = summarize_semantic_clusters(
        bundle["ids"],
        bundle["matrix"],
        records,
        community_result["assignments"],
        max_keywords=args.max_keywords,
        max_representatives=args.max_representatives,
    )
    write_semantic_analysis(Path(args.output_dir), graph, community_result, cluster_summaries)
    print(
        json.dumps(
            {
                "embeddings_dir": args.embeddings_dir,
                "output_dir": args.output_dir,
                "node_count": len(bundle["ids"]),
                "edge_count": int(graph.number_of_edges()),
                "cluster_count": len(cluster_summaries),
                "best_resolution": community_result["best_resolution"],
                "best_modularity": community_result["best_modularity"],
                "resolution": args.resolution,
                "min_community_count": args.min_community_count,
            },
            indent=2,
        )
    )
    return 0


def build_stage2_analysis_parser() -> argparse.ArgumentParser:
    parser = build_semantic_analysis_parser()
    parser.description = (
        "Compatibility alias for semantic analysis from a local embedding bundle"
    )
    return parser


def stage2_analysis_main(argv: list[str] | None = None) -> int:
    argv = list(argv or [])
    translated_argv: list[str] = []
    index = 0
    while index < len(argv):
        token = argv[index]
        if token == "--stage2-dir":
            translated_argv.append("--embeddings-dir")
        else:
            translated_argv.append(token)
        index += 1
    return semantic_analysis_main(translated_argv)


def _cluster_distance_metrics(
    ids: list[int],
    coordinates: Any,
    assignments: dict[int, int],
) -> dict[str, float | int | None]:
    import numpy as np

    matrix = np.asarray(coordinates, dtype=np.float32)
    if matrix.shape[0] != len(ids):
        raise NeuroScapeError("Coordinate count does not match ids")

    members: dict[int, list[int]] = {}
    index_by_id = {int(abstract_id): index for index, abstract_id in enumerate(ids)}
    for abstract_id, cluster_id in assignments.items():
        members.setdefault(int(cluster_id), []).append(index_by_id[int(abstract_id)])

    cluster_ids = sorted(members)
    if len(cluster_ids) <= 1:
        return {
            "cluster_count": len(cluster_ids),
            "mean_intercluster_distance": 0.0,
            "mean_intracluster_distance": 0.0,
            "intercluster_distance_ratio": 0.0,
            "silhouette_score": None,
        }

    centroids: dict[int, Any] = {}
    within_distances: list[float] = []
    for cluster_id, member_indices in members.items():
        cluster_points = matrix[member_indices]
        centroid = cluster_points.mean(axis=0)
        centroids[cluster_id] = centroid
        within_distances.extend(np.linalg.norm(cluster_points - centroid, axis=1).tolist())

    centroid_distances: list[float] = []
    for index, cluster_id in enumerate(cluster_ids):
        for other_cluster_id in cluster_ids[index + 1 :]:
            centroid_distances.append(
                float(np.linalg.norm(centroids[cluster_id] - centroids[other_cluster_id]))
            )

    mean_intercluster_distance = float(np.mean(centroid_distances)) if centroid_distances else 0.0
    mean_intracluster_distance = float(np.mean(within_distances)) if within_distances else 0.0
    denominator = mean_intracluster_distance if mean_intracluster_distance > 0 else 1.0
    metrics: dict[str, float | int | None] = {
        "cluster_count": len(cluster_ids),
        "mean_intercluster_distance": mean_intercluster_distance,
        "mean_intracluster_distance": mean_intracluster_distance,
        "intercluster_distance_ratio": mean_intercluster_distance / denominator,
        "silhouette_score": None,
    }

    try:
        from sklearn.metrics import silhouette_score

        labels = np.asarray([assignments[int(abstract_id)] for abstract_id in ids], dtype=np.int32)
        metrics["silhouette_score"] = float(silhouette_score(matrix, labels, metric="euclidean"))
    except Exception:
        metrics["silhouette_score"] = None
    return metrics
