from __future__ import annotations

import csv
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import numpy as np
from scipy.cluster.hierarchy import leaves_list, linkage, optimal_leaf_ordering
from scipy.sparse import csr_matrix
from scipy.sparse.csgraph import connected_components, laplacian
from scipy.sparse.linalg import eigs, eigsh
from scipy.spatial.distance import pdist
from sklearn.cluster import AgglomerativeClustering, KMeans
from sklearn.feature_extraction.text import ENGLISH_STOP_WORDS, TfidfVectorizer
from sklearn.neighbors import NearestNeighbors

from ohbm2026.poster_layout import (
    BLOCK_TO_SESSIONS,
    BLOCK_LABELS,
    SESSION_LABELS,
    SESSION_TO_BLOCK,
    AcceptedAbstract,
    LayoutInputs,
    PosterLayoutError,
    _normalize_rows,
    _ordered_neighbor_mean_cosine_similarity,
    _window_distances,
    analyze_layout_proposal,
    assign_path_to_blocks,
    layout_slot_for_block_position,
    load_proposal,
    standby_session_for_block_and_poster_number,
    standby_time_labels_for_session,
    write_json,
    write_layout_csv,
    write_listing_csv,
)


GRAPH_METHODS = (
    "baseline_current",
    "spectral_knn",
    "diffusion_map_path",
    "optimal_leaf_ordering",
    "spectral_adjacent_refinement",
)

TOKEN_PATTERN = re.compile(r"[A-Za-z][A-Za-z0-9'-]+")
LAYOUT_LABEL_STOPWORDS = {
    "a",
    "across",
    "an",
    "after",
    "among",
    "analysis",
    "and",
    "are",
    "based",
    "by",
    "de",
    "does",
    "between",
    "brain",
    "clinical",
    "cross",
    "changes",
    "derived",
    "during",
    "effects",
    "for",
    "from",
    "functional",
    "how",
    "in",
    "into",
    "is",
    "its",
    "longitudinal",
    "more",
    "new",
    "of",
    "on",
    "our",
    "over",
    "preliminary",
    "regional",
    "responses",
    "revealed",
    "reveals",
    "study",
    "systematic",
    "task",
    "than",
    "that",
    "the",
    "their",
    "these",
    "through",
    "to",
    "toward",
    "under",
    "using",
    "via",
    "with",
    "within",
    "without",
    "during",
    "human",
    "imaging",
    "neural",
    "neuronal",
    "predicts",
}


def _sorted_assignments(proposal: dict[str, Any]) -> list[dict[str, Any]]:
    return sorted(
        list(proposal.get("assignments", [])),
        key=lambda item: (
            int(item.get("poster_number") or 0),
            int(item.get("abstract_id") or 0),
        ),
    )


def _proposal_records_by_block(
    inputs: LayoutInputs,
    proposal: dict[str, Any],
) -> dict[int, list[AcceptedAbstract]]:
    records_by_id = {record.abstract_id: record for record in inputs.records}
    by_block: dict[int, list[AcceptedAbstract]] = {block_id: [] for block_id in BLOCK_TO_SESSIONS}
    for assignment in _sorted_assignments(proposal):
        abstract_id = assignment.get("abstract_id")
        block_id = assignment.get("block_id")
        if not isinstance(abstract_id, int) or not isinstance(block_id, int):
            raise PosterLayoutError("Proposal assignments must include integer abstract ids and block ids")
        record = records_by_id.get(abstract_id)
        if record is None:
            raise PosterLayoutError(f"Proposal references accepted abstract {abstract_id}, which is not available")
        by_block[int(block_id)].append(record)
    return by_block


def _proposal_records_in_order(
    inputs: LayoutInputs,
    proposal: dict[str, Any],
) -> list[AcceptedAbstract]:
    records_by_id = {record.abstract_id: record for record in inputs.records}
    ordered_records: list[AcceptedAbstract] = []
    for assignment in _sorted_assignments(proposal):
        abstract_id = assignment.get("abstract_id")
        if not isinstance(abstract_id, int):
            raise PosterLayoutError("Proposal assignments must include integer abstract ids")
        record = records_by_id.get(abstract_id)
        if record is None:
            raise PosterLayoutError(f"Proposal references accepted abstract {abstract_id}, which is not available")
        ordered_records.append(record)
    return ordered_records


def _vectors_for_records(records: list[AcceptedAbstract], normalized_matrix: np.ndarray) -> np.ndarray:
    return normalized_matrix[[record.embedding_index for record in records]]


def _positive_similarity_matrix(vectors: np.ndarray) -> np.ndarray:
    similarities = np.asarray(vectors @ vectors.T, dtype=np.float32)
    np.fill_diagonal(similarities, 0.0)
    return np.clip(similarities, 0.0, 1.0)


def _window_similarity_score(
    ordered_positions: np.ndarray,
    similarity_matrix: np.ndarray,
    band_width: int = 5,
) -> float:
    if ordered_positions.size <= 1:
        return 0.0
    score = 0.0
    for offset in range(1, min(int(band_width), int(ordered_positions.size) - 1) + 1):
        weight = 1.0 / float(offset)
        score += weight * float(similarity_matrix[ordered_positions[:-offset], ordered_positions[offset:]].sum())
    return score


def _signed_similarity_matrix(vectors: np.ndarray) -> np.ndarray:
    similarities = np.asarray(vectors @ vectors.T, dtype=np.float32)
    np.fill_diagonal(similarities, 0.0)
    return similarities


def _contiguous_connectivity_matrix(size: int) -> csr_matrix:
    if size <= 1:
        return csr_matrix((size, size), dtype=np.int8)
    rows: list[int] = []
    cols: list[int] = []
    values: list[int] = []
    for index in range(size - 1):
        rows.extend((index, index + 1))
        cols.extend((index + 1, index))
        values.extend((1, 1))
    return csr_matrix((values, (rows, cols)), shape=(size, size), dtype=np.int8)


def _top_title_keywords(records: list[AcceptedAbstract], max_keywords: int = 4) -> list[str]:
    counts: Counter[str] = Counter()
    for record in records:
        for token in TOKEN_PATTERN.findall(str(record.title or "").lower()):
            if len(token) < 3 or token in LAYOUT_LABEL_STOPWORDS:
                continue
            counts[token] += 1
    return [token for token, _count in counts.most_common(max_keywords)]


def _top_cluster_content_phrases(
    cluster_records_by_id: list[tuple[int, list[AcceptedAbstract]]],
    content_by_id: dict[int, str] | None,
    max_keywords: int = 4,
) -> dict[int, list[str]]:
    if not cluster_records_by_id:
        return {}

    documents: list[str] = []
    cluster_ids: list[int] = []
    for cluster_id, cluster_records in cluster_records_by_id:
        parts: list[str] = []
        for record in cluster_records:
            content = (content_by_id or {}).get(int(record.abstract_id), "").strip()
            parts.append(content or str(record.title or ""))
        cluster_ids.append(int(cluster_id))
        documents.append(" ".join(parts))

    if not any(document.strip() for document in documents):
        return {}

    stop_words = sorted(set(ENGLISH_STOP_WORDS).union(LAYOUT_LABEL_STOPWORDS))
    vectorizer = TfidfVectorizer(
        stop_words=stop_words,
        ngram_range=(1, 2),
        max_features=8000,
        lowercase=True,
        token_pattern=r"(?u)\b[a-zA-Z][a-zA-Z0-9'-]{1,}\b",
    )
    matrix = vectorizer.fit_transform(documents)
    feature_names = vectorizer.get_feature_names_out()
    phrases_by_cluster: dict[int, list[str]] = {}
    for row_index, cluster_id in enumerate(cluster_ids):
        row = matrix.getrow(row_index)
        if row.nnz == 0:
            phrases_by_cluster[int(cluster_id)] = []
            continue
        ranked_indices = np.argsort(row.data)[::-1]
        phrases: list[str] = []
        for offset in ranked_indices.tolist():
            phrase = str(feature_names[row.indices[offset]]).strip()
            if not phrase:
                continue
            if phrase in phrases:
                continue
            phrases.append(phrase)
            if len(phrases) >= int(max_keywords):
                break
        phrases_by_cluster[int(cluster_id)] = phrases
    return phrases_by_cluster


def _uniquify_cluster_labels(cluster_summaries: list[dict[str, Any]]) -> None:
    counts: Counter[str] = Counter()
    for cluster_summary in cluster_summaries:
        base_label = str(cluster_summary.get("label") or "").strip() or f"contiguous cluster {cluster_summary.get('cluster_id')}"
        counts[base_label] += 1
        occurrence = counts[base_label]
        cluster_summary["label"] = base_label if occurrence == 1 else f"{base_label} ({occurrence})"


def derive_contiguous_layout_clusters(
    records: list[AcceptedAbstract],
    normalized_matrix: np.ndarray,
    target_cluster_count: int = 31,
    content_by_id: dict[int, str] | None = None,
) -> dict[str, Any]:
    if not records:
        return {"assignments": {}, "clusters": []}

    vectors = _vectors_for_records(records, normalized_matrix)
    effective_cluster_count = min(max(1, int(target_cluster_count)), len(records))
    if effective_cluster_count == len(records):
        raw_labels = np.arange(len(records), dtype=np.int32)
    elif effective_cluster_count == 1:
        raw_labels = np.zeros(len(records), dtype=np.int32)
    else:
        model = AgglomerativeClustering(
            n_clusters=effective_cluster_count,
            metric="cosine",
            linkage="average",
            connectivity=_contiguous_connectivity_matrix(len(records)),
        )
        raw_labels = np.asarray(model.fit_predict(vectors), dtype=np.int32)

    positions_by_raw: dict[int, list[int]] = defaultdict(list)
    for index, raw_label in enumerate(raw_labels.tolist()):
        positions_by_raw[int(raw_label)].append(index)
    ordered_raw_labels = sorted(positions_by_raw, key=lambda raw_label: positions_by_raw[raw_label][0])
    remapped_cluster_ids = {raw_label: cluster_id for cluster_id, raw_label in enumerate(ordered_raw_labels, start=1)}

    assignment_map: dict[int, int] = {}
    cluster_summaries: list[dict[str, Any]] = []
    cluster_records_by_id: list[tuple[int, list[AcceptedAbstract]]] = []
    for raw_label in ordered_raw_labels:
        cluster_id = remapped_cluster_ids[raw_label]
        positions = positions_by_raw[raw_label]
        cluster_records = [records[index] for index in positions]
        cluster_records_by_id.append((int(cluster_id), cluster_records))
        for record in cluster_records:
            assignment_map[int(record.abstract_id)] = int(cluster_id)

    cluster_phrases = _top_cluster_content_phrases(cluster_records_by_id, content_by_id, max_keywords=4)
    for cluster_id, cluster_records in cluster_records_by_id:
        inherited_counts = Counter(record.layout_exact_label for record in cluster_records)
        top_inherited_label, top_inherited_count = inherited_counts.most_common(1)[0]
        content_keywords = list(cluster_phrases.get(int(cluster_id)) or [])
        fallback_keywords = _top_title_keywords(cluster_records, max_keywords=4)
        keywords = content_keywords or fallback_keywords
        if keywords:
            label = ", ".join(keywords[:3])
        elif int(top_inherited_count) >= max(2, int(round(0.6 * len(cluster_records)))):
            label = str(top_inherited_label)
        else:
            label = str(top_inherited_label or f"contiguous cluster {cluster_id}")

        primary_parent_counts = Counter(record.primary_parent_category for record in cluster_records)
        parent_label = primary_parent_counts.most_common(1)[0][0] if primary_parent_counts else label
        representative_abstracts = [
            {"abstract_id": int(record.abstract_id), "title": str(record.title)}
            for record in cluster_records[:5]
        ]
        cluster_summaries.append(
            {
                "cluster_id": int(cluster_id),
                "label": str(label),
                "parent_label": str(parent_label),
                "size": len(cluster_records),
                "keywords": keywords,
                "representative_abstracts": representative_abstracts,
            }
        )

    _uniquify_cluster_labels(cluster_summaries)

    return {
        "assignments": assignment_map,
        "clusters": cluster_summaries,
    }


def graph_reordering_metrics(
    records: list[AcceptedAbstract],
    normalized_matrix: np.ndarray,
    band_width: int = 5,
) -> dict[str, Any]:
    if len(records) <= 1:
        return {
            "count": len(records),
            "band_width": int(band_width),
            "positive_edge_weight_sum": 0.0,
            "adjacent_edge_mass_rate": 0.0,
            "window_edge_mass_rate": 0.0,
            "mean_weighted_index_distance": 0.0,
            "mean_weighted_squared_index_distance": 0.0,
            "distance_to_capture_50_edge_mass": 0,
            "distance_to_capture_80_edge_mass": 0,
        }

    similarity_matrix = _positive_similarity_matrix(_vectors_for_records(records, normalized_matrix))
    total_weight = 0.0
    adjacent_weight = 0.0
    band_weight = 0.0
    weighted_distance = 0.0
    weighted_squared_distance = 0.0
    offset_weights: list[float] = []
    max_offset = similarity_matrix.shape[0] - 1
    for offset in range(1, max_offset + 1):
        diagonal = np.asarray(similarity_matrix.diagonal(offset), dtype=np.float64)
        weight = float(diagonal.sum())
        offset_weights.append(weight)
        total_weight += weight
        weighted_distance += float(offset) * weight
        weighted_squared_distance += float(offset * offset) * weight
        if offset == 1:
            adjacent_weight += weight
        if offset <= int(band_width):
            band_weight += weight

    if total_weight <= 0.0:
        return {
            "count": len(records),
            "band_width": int(band_width),
            "positive_edge_weight_sum": 0.0,
            "adjacent_edge_mass_rate": 0.0,
            "window_edge_mass_rate": 0.0,
            "mean_weighted_index_distance": 0.0,
            "mean_weighted_squared_index_distance": 0.0,
            "distance_to_capture_50_edge_mass": 0,
            "distance_to_capture_80_edge_mass": 0,
        }

    cumulative = 0.0
    distance_to_50 = max_offset
    distance_to_80 = max_offset
    for offset, weight in enumerate(offset_weights, start=1):
        cumulative += weight
        if cumulative >= 0.5 * total_weight and distance_to_50 == max_offset:
            distance_to_50 = offset
        if cumulative >= 0.8 * total_weight:
            distance_to_80 = offset
            break

    return {
        "count": len(records),
        "band_width": int(band_width),
        "positive_edge_weight_sum": float(total_weight),
        "adjacent_edge_mass_rate": float(adjacent_weight / total_weight),
        "window_edge_mass_rate": float(band_weight / total_weight),
        "mean_weighted_index_distance": float(weighted_distance / total_weight),
        "mean_weighted_squared_index_distance": float(weighted_squared_distance / total_weight),
        "distance_to_capture_50_edge_mass": int(distance_to_50),
        "distance_to_capture_80_edge_mass": int(distance_to_80),
    }


def _connect_knn_graph(
    weights: csr_matrix,
    similarities: np.ndarray,
) -> csr_matrix:
    component_count, labels = connected_components(weights, directed=False, return_labels=True)
    if component_count <= 1:
        return weights
    rows: list[int] = []
    cols: list[int] = []
    data: list[float] = []
    for component_id in range(component_count - 1):
        left = np.where(labels == component_id)[0]
        right = np.where(labels == component_id + 1)[0]
        if left.size == 0 or right.size == 0:
            continue
        bridge_scores = similarities[np.ix_(left, right)]
        bridge_position = np.unravel_index(int(np.argmax(bridge_scores)), bridge_scores.shape)
        left_index = int(left[int(bridge_position[0])])
        right_index = int(right[int(bridge_position[1])])
        bridge_weight = float(max(bridge_scores[bridge_position], 1e-6))
        rows.extend([left_index, right_index])
        cols.extend([right_index, left_index])
        data.extend([bridge_weight, bridge_weight])
    if not data:
        return weights
    bridge_matrix = csr_matrix((np.asarray(data), (np.asarray(rows), np.asarray(cols))), shape=weights.shape)
    return (weights + bridge_matrix).maximum(weights + bridge_matrix.T)


def build_weighted_knn_graph(
    records: list[AcceptedAbstract],
    normalized_matrix: np.ndarray,
    neighbor_count: int = 20,
) -> dict[str, Any]:
    if len(records) <= 1:
        adjacency = csr_matrix((len(records), len(records)), dtype=np.float64)
        return {
            "adjacency": adjacency,
            "adjacency_connected": adjacency,
            "similarities": np.zeros((len(records), len(records)), dtype=np.float32),
            "diagnostics": {
                "node_count": len(records),
                "neighbor_count": 0,
                "components_before_bridge": 1 if records else 0,
                "components_after_bridge": 1 if records else 0,
                "largest_component_size_before_bridge": len(records),
                "largest_component_size_after_bridge": len(records),
                "bridge_edges_added": 0,
                "graph_was_disconnected": False,
                "mean_degree_before_bridge": 0.0,
                "mean_degree_after_bridge": 0.0,
            },
        }

    vectors = _vectors_for_records(records, normalized_matrix)
    similarities = _positive_similarity_matrix(vectors)
    effective_neighbors = min(max(2, int(neighbor_count)), len(records) - 1)
    neighbor_model = NearestNeighbors(metric="cosine", n_neighbors=effective_neighbors + 1)
    neighbor_model.fit(vectors)
    distances, indices = neighbor_model.kneighbors(vectors, return_distance=True)
    row_positions = np.repeat(np.arange(len(records)), effective_neighbors)
    column_positions = indices[:, 1:].reshape(-1)
    edge_weights = np.clip(1.0 - distances[:, 1:].reshape(-1), 0.0, 1.0)
    adjacency = csr_matrix(
        (edge_weights.astype(np.float64), (row_positions, column_positions)),
        shape=(len(records), len(records)),
    )
    adjacency = adjacency.maximum(adjacency.T)

    component_count_before, labels_before = connected_components(adjacency, directed=False, return_labels=True)
    component_sizes_before = np.bincount(labels_before) if labels_before.size else np.asarray([], dtype=np.int64)
    adjacency_connected = _connect_knn_graph(adjacency, similarities)
    component_count_after, labels_after = connected_components(adjacency_connected, directed=False, return_labels=True)
    component_sizes_after = np.bincount(labels_after) if labels_after.size else np.asarray([], dtype=np.int64)
    degree_before = np.asarray(adjacency.astype(bool).sum(axis=1)).reshape(-1)
    degree_after = np.asarray(adjacency_connected.astype(bool).sum(axis=1)).reshape(-1)

    return {
        "adjacency": adjacency,
        "adjacency_connected": adjacency_connected,
        "similarities": similarities,
        "diagnostics": {
            "node_count": len(records),
            "neighbor_count": int(effective_neighbors),
            "components_before_bridge": int(component_count_before),
            "components_after_bridge": int(component_count_after),
            "largest_component_size_before_bridge": int(component_sizes_before.max()) if component_sizes_before.size else 0,
            "largest_component_size_after_bridge": int(component_sizes_after.max()) if component_sizes_after.size else 0,
            "bridge_edges_added": max(0, int(component_count_before) - int(component_count_after)),
            "graph_was_disconnected": bool(component_count_before > 1),
            "mean_degree_before_bridge": float(np.mean(degree_before)) if degree_before.size else 0.0,
            "mean_degree_after_bridge": float(np.mean(degree_after)) if degree_after.size else 0.0,
        },
    }


def order_records_by_spectral_graph(
    records: list[AcceptedAbstract],
    normalized_matrix: np.ndarray,
    neighbor_count: int = 20,
) -> list[int]:
    if len(records) <= 2:
        return [record.abstract_id for record in records]

    graph = build_weighted_knn_graph(records, normalized_matrix, neighbor_count=neighbor_count)
    adjacency = graph["adjacency_connected"]
    lap = laplacian(adjacency, normed=True)
    eigen_count = min(3, len(records) - 1)
    values, vectors_eig = eigsh(lap, k=eigen_count, which="SM")
    order = np.argsort(values)
    chosen_vector = np.asarray(vectors_eig[:, int(order[min(1, len(order) - 1)])], dtype=np.float64)
    for position in order:
        if float(values[int(position)]) > 1e-8:
            chosen_vector = np.asarray(vectors_eig[:, int(position)], dtype=np.float64)
            break
    ordered_positions = np.argsort(chosen_vector)
    return [records[int(position)].abstract_id for position in ordered_positions]


def order_records_by_diffusion_map_path(
    records: list[AcceptedAbstract],
    normalized_matrix: np.ndarray,
    neighbor_count: int = 20,
    coordinate_dims: int = 1,
    coordinate_mode: str = "single",
    return_diagnostics: bool = False,
) -> list[int]:
    if len(records) <= 2:
        ordered_ids = [record.abstract_id for record in records]
        if return_diagnostics:
            return {
                "ordered_ids": ordered_ids,
                "diagnostics": {
                    "coordinate_dims": int(min(max(1, coordinate_dims), 1)),
                    "coordinate_mode": str(coordinate_mode),
                    "eigenvalues_desc": [],
                    "chosen_eigenvalues": [],
                    "graph": build_weighted_knn_graph(records, normalized_matrix, neighbor_count=neighbor_count)["diagnostics"],
                },
            }
        return ordered_ids

    graph = build_weighted_knn_graph(records, normalized_matrix, neighbor_count=neighbor_count)
    adjacency = graph["adjacency_connected"]
    degrees = np.asarray(adjacency.sum(axis=1)).reshape(-1)
    inv_sqrt_degrees = np.where(degrees > 0.0, 1.0 / np.sqrt(degrees), 0.0)
    diffusion_operator = adjacency.multiply(inv_sqrt_degrees[:, None]).multiply(inv_sqrt_degrees[None, :]).tocsr()
    effective_dims = min(max(1, int(coordinate_dims)), len(records) - 1)
    eigen_count = min(max(4, effective_dims + 1), len(records) - 1)
    values, vectors_eig = eigsh(diffusion_operator, k=eigen_count, which="LA")
    order = np.argsort(values)[::-1]
    nontrivial_positions = [int(position) for position in order if float(values[int(position)]) < 1.0 - 1e-8]
    if not nontrivial_positions:
        nontrivial_positions = [int(order[min(1, len(order) - 1)])]
    chosen_positions = nontrivial_positions[:effective_dims]
    chosen_values = np.asarray([float(values[position]) for position in chosen_positions], dtype=np.float64)
    chosen_vectors = np.asarray(vectors_eig[:, chosen_positions], dtype=np.float64)
    diffusion_embedding = chosen_vectors * chosen_values.reshape(1, -1)
    if str(coordinate_mode) == "single" or diffusion_embedding.shape[1] == 1:
        coordinate = diffusion_embedding[:, 0]
    elif str(coordinate_mode) == "pca":
        centered = diffusion_embedding - diffusion_embedding.mean(axis=0, keepdims=True)
        _, _, vh = np.linalg.svd(centered, full_matrices=False)
        coordinate = centered @ vh[0]
    elif str(coordinate_mode) == "lexsort":
        key_matrix = np.asarray(diffusion_embedding, dtype=np.float64)
        ordered_positions = np.lexsort(tuple(key_matrix[:, column] for column in range(key_matrix.shape[1] - 1, -1, -1)))
        ordered_ids = [records[int(position)].abstract_id for position in ordered_positions]
        if return_diagnostics:
            return {
                "ordered_ids": ordered_ids,
                "diagnostics": {
                    "coordinate_dims": int(effective_dims),
                    "coordinate_mode": str(coordinate_mode),
                    "eigenvalues_desc": [float(values[int(position)]) for position in order],
                    "chosen_eigenvalues": [float(value) for value in chosen_values],
                    "graph": graph["diagnostics"],
                },
            }
        return ordered_ids
    else:
        raise PosterLayoutError(f"Unknown diffusion coordinate mode: {coordinate_mode}")
    ordered_positions = np.argsort(coordinate)
    ordered_ids = [records[int(position)].abstract_id for position in ordered_positions]
    if return_diagnostics:
        return {
            "ordered_ids": ordered_ids,
            "diagnostics": {
                "coordinate_dims": int(effective_dims),
                "coordinate_mode": str(coordinate_mode),
                "eigenvalues_desc": [float(values[int(position)]) for position in order],
                "chosen_eigenvalues": [float(value) for value in chosen_values],
                "graph": graph["diagnostics"],
            },
        }
    return ordered_ids


def _dense_connected_affinity(
    records: list[AcceptedAbstract],
    normalized_matrix: np.ndarray,
    affinity_mode: str = "knn",
    neighbor_count: int = 20,
) -> tuple[np.ndarray, dict[str, Any]]:
    vectors = _vectors_for_records(records, normalized_matrix)
    similarities = _positive_similarity_matrix(vectors).astype(np.float64)
    if len(records) <= 1:
        return similarities, {
            "affinity_mode": str(affinity_mode),
            "components_before_bridge": 1 if records else 0,
            "components_after_bridge": 1 if records else 0,
            "graph_was_disconnected": False,
            "neighbor_count": 0,
        }
    if str(affinity_mode) == "full":
        adjacency = csr_matrix(similarities)
        component_count_before, _ = connected_components(adjacency, directed=False, return_labels=True)
        connected = _connect_knn_graph(adjacency, similarities) if component_count_before > 1 else adjacency
        component_count_after, _ = connected_components(connected, directed=False, return_labels=True)
        return np.asarray(connected.toarray(), dtype=np.float64), {
            "affinity_mode": "full",
            "components_before_bridge": int(component_count_before),
            "components_after_bridge": int(component_count_after),
            "graph_was_disconnected": bool(component_count_before > 1),
            "neighbor_count": int(len(records) - 1),
        }
    graph = build_weighted_knn_graph(records, normalized_matrix, neighbor_count=neighbor_count)
    return np.asarray(graph["adjacency_connected"].toarray(), dtype=np.float64), {
        "affinity_mode": "knn",
        **graph["diagnostics"],
    }


def order_records_by_mapalign_style_diffusion(
    records: list[AcceptedAbstract],
    normalized_matrix: np.ndarray,
    affinity_mode: str = "knn",
    neighbor_count: int = 20,
    alpha: float = 0.5,
    diffusion_time: float = 0.0,
    coordinate_dims: int = 1,
    coordinate_mode: str = "single",
    return_diagnostics: bool = False,
) -> list[int] | dict[str, Any]:
    if len(records) <= 2:
        ordered_ids = [record.abstract_id for record in records]
        if return_diagnostics:
            return {
                "ordered_ids": ordered_ids,
                "diagnostics": {
                    "affinity_mode": str(affinity_mode),
                    "neighbor_count": int(max(0, neighbor_count)),
                    "alpha": float(alpha),
                    "diffusion_time": float(diffusion_time),
                    "coordinate_dims": int(min(max(1, coordinate_dims), 1)),
                    "coordinate_mode": str(coordinate_mode),
                    "eigenvalues_desc": [],
                    "chosen_eigenvalues": [],
                    "graph": {
                        "components_before_bridge": 1 if records else 0,
                        "components_after_bridge": 1 if records else 0,
                        "graph_was_disconnected": False,
                        "neighbor_count": int(max(0, neighbor_count)),
                    },
                },
            }
        return ordered_ids

    affinity, graph_diag = _dense_connected_affinity(
        records,
        normalized_matrix,
        affinity_mode=affinity_mode,
        neighbor_count=neighbor_count,
    )
    operator = np.asarray(affinity, dtype=np.float64)
    if float(alpha) > 0.0:
        degree = operator.sum(axis=1)
        degree = np.where(degree > 1e-12, degree, 1e-12)
        d_alpha = np.power(degree, -float(alpha))
        operator = d_alpha[:, None] * operator * d_alpha[None, :]
    row_sum = operator.sum(axis=1)
    row_sum = np.where(row_sum > 1e-12, row_sum, 1e-12)
    operator = (np.power(row_sum, -1.0)[:, None]) * operator
    eigen_count = min(max(5, int(coordinate_dims) + 2), len(records) - 1)
    if eigen_count >= len(records) - 1:
        values, vectors_eig = np.linalg.eig(operator)
        values = np.real(values)
        vectors_eig = np.real(vectors_eig)
    else:
        values, vectors_eig = eigs(csr_matrix(operator), k=eigen_count)
        values = np.real(values)
        vectors_eig = np.real(vectors_eig)
    order = np.argsort(values)[::-1]
    sorted_values = np.asarray([float(values[int(position)]) for position in order], dtype=np.float64)
    sorted_vectors = np.asarray(vectors_eig[:, order], dtype=np.float64)
    base_vector = sorted_vectors[:, [0]]
    safe_base = np.where(np.abs(base_vector) > 1e-12, base_vector, 1.0)
    psi = sorted_vectors / safe_base
    nontrivial_values = np.clip(sorted_values[1:], 1e-9, 1.0 - 1e-9)
    nontrivial_psi = psi[:, 1:]
    effective_dims = min(max(1, int(coordinate_dims)), nontrivial_psi.shape[1])
    chosen_values = nontrivial_values[:effective_dims]
    chosen_psi = nontrivial_psi[:, :effective_dims]
    if float(diffusion_time) == 0.0:
        scaled_values = chosen_values / (1.0 - chosen_values)
    else:
        scaled_values = chosen_values ** float(diffusion_time)
    embedding = chosen_psi * scaled_values.reshape(1, -1)
    if str(coordinate_mode) == "single" or embedding.shape[1] == 1:
        coordinate = embedding[:, 0]
        ordered_positions = np.argsort(coordinate)
    elif str(coordinate_mode) == "pca":
        centered = embedding - embedding.mean(axis=0, keepdims=True)
        _, _, vh = np.linalg.svd(centered, full_matrices=False)
        coordinate = centered @ vh[0]
        ordered_positions = np.argsort(coordinate)
    elif str(coordinate_mode) == "lexsort":
        ordered_positions = np.lexsort(tuple(embedding[:, column] for column in range(embedding.shape[1] - 1, -1, -1)))
    else:
        raise PosterLayoutError(f"Unknown mapalign-style coordinate mode: {coordinate_mode}")
    ordered_ids = [records[int(position)].abstract_id for position in ordered_positions]
    if return_diagnostics:
        return {
            "ordered_ids": ordered_ids,
            "diagnostics": {
                "affinity_mode": str(affinity_mode),
                "neighbor_count": int(neighbor_count),
                "alpha": float(alpha),
                "diffusion_time": float(diffusion_time),
                "coordinate_dims": int(effective_dims),
                "coordinate_mode": str(coordinate_mode),
                "eigenvalues_desc": [float(value) for value in sorted_values],
                "chosen_eigenvalues": [float(value) for value in chosen_values],
                "scaled_eigenvalues": [float(value) for value in scaled_values],
                "graph": graph_diag,
            },
        }
    return ordered_ids


def order_records_by_optimal_leaf_ordering(
    records: list[AcceptedAbstract],
    normalized_matrix: np.ndarray,
) -> list[int]:
    if len(records) <= 2:
        return [record.abstract_id for record in records]
    vectors = _vectors_for_records(records, normalized_matrix)
    condensed_distances = pdist(vectors, metric="cosine")
    linkage_matrix = linkage(condensed_distances, method="average")
    optimal_linkage = optimal_leaf_ordering(linkage_matrix, condensed_distances)
    ordered_positions = leaves_list(optimal_linkage)
    return [records[int(position)].abstract_id for position in ordered_positions]


def _order_positions_by_optimal_leaf_ordering(vectors: np.ndarray) -> list[int]:
    if int(vectors.shape[0]) <= 2:
        return list(range(int(vectors.shape[0])))
    condensed_distances = pdist(vectors, metric="cosine")
    linkage_matrix = linkage(condensed_distances, method="average")
    optimal_linkage = optimal_leaf_ordering(linkage_matrix, condensed_distances)
    return [int(position) for position in leaves_list(optimal_linkage)]


def _refine_order_by_adjacent_swaps(
    seed_ids: list[int],
    records: list[AcceptedAbstract],
    normalized_matrix: np.ndarray,
    band_width: int = 5,
    max_passes: int = 8,
) -> list[int]:
    if len(seed_ids) <= 2:
        return list(seed_ids)
    local_index_by_id = {record.abstract_id: index for index, record in enumerate(records)}
    similarities = _positive_similarity_matrix(_vectors_for_records(records, normalized_matrix))
    order_positions = np.asarray([local_index_by_id[abstract_id] for abstract_id in seed_ids], dtype=np.int32)
    current_score = _window_similarity_score(order_positions, similarities, band_width=band_width)
    for _ in range(max_passes):
        improved = False
        for index in range(len(order_positions) - 1):
            swapped = order_positions.copy()
            swapped[index], swapped[index + 1] = swapped[index + 1], swapped[index]
            swapped_score = _window_similarity_score(swapped, similarities, band_width=band_width)
            if swapped_score > current_score + 1e-9:
                order_positions = swapped
                current_score = swapped_score
                improved = True
        if not improved:
            break
    return [records[int(position)].abstract_id for position in order_positions]


def order_records_by_spectral_adjacent_refinement(
    records: list[AcceptedAbstract],
    normalized_matrix: np.ndarray,
    band_width: int = 5,
    max_passes: int = 8,
) -> list[int]:
    if len(records) <= 2:
        return [record.abstract_id for record in records]
    spectral_ids = order_records_by_spectral_graph(records, normalized_matrix)
    return _refine_order_by_adjacent_swaps(
        spectral_ids,
        records,
        normalized_matrix,
        band_width=band_width,
        max_passes=max_passes,
    )


def order_records_by_olo_adjacent_refinement(
    records: list[AcceptedAbstract],
    normalized_matrix: np.ndarray,
    band_width: int = 5,
    max_passes: int = 8,
) -> list[int]:
    return _refine_order_by_adjacent_swaps(
        order_records_by_optimal_leaf_ordering(records, normalized_matrix),
        records,
        normalized_matrix,
        band_width=band_width,
        max_passes=max_passes,
    )


def order_records_by_sparse_two_opt(
    records: list[AcceptedAbstract],
    normalized_matrix: np.ndarray,
    seed_ids: list[int],
    neighbor_count: int = 20,
    max_passes: int = 4,
) -> list[int]:
    if len(seed_ids) <= 3:
        return list(seed_ids)

    vectors = _vectors_for_records(records, normalized_matrix)
    signed_similarities = _signed_similarity_matrix(vectors)
    local_index_by_id = {record.abstract_id: index for index, record in enumerate(records)}
    effective_neighbors = min(max(2, int(neighbor_count)), len(records) - 1)
    neighbor_model = NearestNeighbors(metric="cosine", n_neighbors=effective_neighbors + 1)
    neighbor_model.fit(vectors)
    _, indices = neighbor_model.kneighbors(vectors, return_distance=True)
    neighbor_sets = [set(int(value) for value in row[1:]) for row in indices]

    order_positions = np.asarray([local_index_by_id[abstract_id] for abstract_id in seed_ids], dtype=np.int32)
    position_of_local = {int(local): int(position) for position, local in enumerate(order_positions)}

    for _ in range(max_passes):
        improved = False
        for i in range(len(order_positions) - 3):
            a = int(order_positions[i])
            b = int(order_positions[i + 1])
            candidate_locals = neighbor_sets[a] | neighbor_sets[b]
            candidate_js: set[int] = set()
            for candidate_local in candidate_locals:
                candidate_position = position_of_local.get(int(candidate_local))
                if candidate_position is None:
                    continue
                if candidate_position > i + 1:
                    candidate_js.add(int(candidate_position))
                if candidate_position - 1 > i + 1:
                    candidate_js.add(int(candidate_position - 1))

            best_gain = 0.0
            best_j: int | None = None
            for j in sorted(candidate_js):
                if j >= len(order_positions) - 1:
                    continue
                c = int(order_positions[j])
                d = int(order_positions[j + 1])
                old_score = float(signed_similarities[a, b] + signed_similarities[c, d])
                new_score = float(signed_similarities[a, c] + signed_similarities[b, d])
                gain = new_score - old_score
                if gain > best_gain + 1e-9:
                    best_gain = gain
                    best_j = int(j)
            if best_j is not None:
                order_positions[i + 1 : best_j + 1] = order_positions[i + 1 : best_j + 1][::-1]
                position_of_local = {int(local): int(position) for position, local in enumerate(order_positions)}
                improved = True
        if not improved:
            break
    return [records[int(position)].abstract_id for position in order_positions]


def order_records_by_clustered_kmeans_olo(
    records: list[AcceptedAbstract],
    normalized_matrix: np.ndarray,
    cluster_count: int | None = None,
    random_state: int = 42,
) -> list[int]:
    if len(records) <= 2:
        return [record.abstract_id for record in records]
    vectors = _vectors_for_records(records, normalized_matrix)
    inferred_cluster_count = int(np.clip(round(np.sqrt(len(records) / 2.0)), 8, 64))
    effective_cluster_count = min(max(2, cluster_count or inferred_cluster_count), len(records))
    kmeans = KMeans(n_clusters=effective_cluster_count, random_state=random_state, n_init=10)
    labels = kmeans.fit_predict(vectors)
    centroid_order = _order_positions_by_optimal_leaf_ordering(_normalize_rows(kmeans.cluster_centers_))

    ordered_ids: list[int] = []
    for cluster_label in centroid_order:
        member_positions = np.where(labels == int(cluster_label))[0]
        cluster_vectors = vectors[member_positions]
        within_order = _order_positions_by_optimal_leaf_ordering(cluster_vectors)
        for local_position in within_order:
            ordered_ids.append(records[int(member_positions[int(local_position)])].abstract_id)
    return ordered_ids


def resequence_proposal_blocks(
    proposal: dict[str, Any],
    ordered_ids_by_block: dict[int, list[int]],
    method_name: str,
) -> dict[str, Any]:
    assignments_by_id = {
        int(item["abstract_id"]): dict(item)
        for item in proposal.get("assignments", [])
        if isinstance(item, dict) and isinstance(item.get("abstract_id"), int)
    }
    expected_ids = set(assignments_by_id)
    received_ids = {abstract_id for values in ordered_ids_by_block.values() for abstract_id in values}
    if expected_ids != received_ids:
        missing = sorted(expected_ids - received_ids)
        extras = sorted(received_ids - expected_ids)
        raise PosterLayoutError(
            f"Resequencing ids do not match proposal assignments. Missing={missing[:5]} extra={extras[:5]}"
        )

    resequenced_assignments: list[dict[str, Any]] = []
    poster_number = 1
    for block_id in sorted(BLOCK_TO_SESSIONS):
        for block_position, abstract_id in enumerate(ordered_ids_by_block[block_id], start=1):
            row = dict(assignments_by_id[int(abstract_id)])
            session_id = standby_session_for_block_and_poster_number(block_id, poster_number)
            first_standby_label, second_standby_label = standby_time_labels_for_session(session_id)
            row.update(
                {
                    "poster_number": int(poster_number),
                    "block_position": int(block_position),
                    "block_id": int(block_id),
                    "block_label": BLOCK_LABELS[int(block_id)],
                    "standby_session": int(session_id),
                    "standby_session_label": SESSION_LABELS[int(session_id)],
                    "first_standby_time_label": first_standby_label,
                    "second_standby_time_label": second_standby_label,
                    **layout_slot_for_block_position(block_position),
                }
            )
            resequenced_assignments.append(row)
            poster_number += 1

    metadata = dict(proposal.get("metadata") or {})
    metadata["sequencing_method"] = str(method_name)
    metadata["sequencing_assumption"] = (
        "Poster-to-block assignments are held fixed while the within-block order is recomputed as a weighted graph "
        "reordering problem that seeks stronger near-diagonal and block-coherent similarity structure."
    )
    return {
        "metadata": metadata,
        "session_summaries": dict(proposal.get("session_summaries") or {}),
        "assignments": resequenced_assignments,
    }


def build_global_path_split_proposal(
    proposal: dict[str, Any],
    global_ordered_ids: list[int],
    records_by_id: dict[int, AcceptedAbstract],
    method_name: str,
) -> dict[str, Any]:
    _block_by_id, block_sequences = assign_path_to_blocks(global_ordered_ids, records_by_id)
    ordered_ids_by_block = {int(block_id): list(ids) for block_id, ids in block_sequences.items()}
    return resequence_proposal_blocks(proposal, ordered_ids_by_block, method_name=method_name)


def _load_neighbor_tail_metrics(proposal_csv: Path) -> dict[str, Any]:
    with proposal_csv.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        scores: list[float] = []
        for row in reader:
            value = row.get("voyage_stage2_neighbor5_mean_cosine_similarity")
            if value is None or value == "":
                continue
            scores.append(float(value))
    if not scores:
        return {
            "voyage_neighbor5_mean": 0.0,
            "voyage_neighbor5_median": 0.0,
            "voyage_neighbor5_p10": 0.0,
            "voyage_neighbor5_below_0_6": 0,
            "voyage_neighbor5_below_0_5": 0,
            "voyage_neighbor5_below_0_4": 0,
        }
    ordered = np.asarray(sorted(scores), dtype=np.float64)
    return {
        "voyage_neighbor5_mean": float(np.mean(ordered)),
        "voyage_neighbor5_median": float(np.median(ordered)),
        "voyage_neighbor5_p10": float(np.percentile(ordered, 10)),
        "voyage_neighbor5_below_0_6": int(np.sum(ordered < 0.6)),
        "voyage_neighbor5_below_0_5": int(np.sum(ordered < 0.5)),
        "voyage_neighbor5_below_0_4": int(np.sum(ordered < 0.4)),
    }


def _neighbor_tail_metrics_from_ordered_ids(
    ordered_ids: list[int],
    bundle_dir: str = "data/embeddings/voyage_stage2_published",
) -> dict[str, Any]:
    scores_by_id = _ordered_neighbor_mean_cosine_similarity(
        [{"abstract_id": int(abstract_id)} for abstract_id in ordered_ids],
        bundle_dir,
    )
    scores = [float(value) for value in scores_by_id.values() if value is not None]
    if not scores:
        return {
            "voyage_neighbor5_mean": 0.0,
            "voyage_neighbor5_median": 0.0,
            "voyage_neighbor5_p10": 0.0,
            "voyage_neighbor5_below_0_6": 0,
            "voyage_neighbor5_below_0_5": 0,
            "voyage_neighbor5_below_0_4": 0,
        }
    ordered = np.asarray(sorted(scores), dtype=np.float64)
    return {
        "voyage_neighbor5_mean": float(np.mean(ordered)),
        "voyage_neighbor5_median": float(np.median(ordered)),
        "voyage_neighbor5_p10": float(np.percentile(ordered, 10)),
        "voyage_neighbor5_below_0_6": int(np.sum(ordered < 0.6)),
        "voyage_neighbor5_below_0_5": int(np.sum(ordered < 0.5)),
        "voyage_neighbor5_below_0_4": int(np.sum(ordered < 0.4)),
    }


def _write_ordered_cosine_similarity_matrix_plot(
    records: list[AcceptedAbstract],
    normalized_matrix: np.ndarray,
    output_path: Path,
    boundary_positions: list[int] | None = None,
) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    signed_similarities = _signed_similarity_matrix(_vectors_for_records(records, normalized_matrix))
    figure, axis = plt.subplots(figsize=(8.5, 8.0), dpi=160)
    image = axis.matshow(signed_similarities, cmap="coolwarm", vmin=-1.0, vmax=1.0)
    axis.set_title("Ordered Cosine Similarity Matrix")
    axis.set_xlabel("Ordered position")
    axis.set_ylabel("Ordered position")
    for boundary in boundary_positions or []:
        boundary_offset = float(boundary) - 0.5
        axis.axhline(boundary_offset, color="black", linewidth=0.6, alpha=0.6)
        axis.axvline(boundary_offset, color="black", linewidth=0.6, alpha=0.6)
    colorbar = figure.colorbar(image, ax=axis, fraction=0.046, pad=0.04)
    colorbar.set_label("Cosine similarity")
    figure.tight_layout()
    figure.savefig(output_path, bbox_inches="tight")
    plt.close(figure)


def _community_graph_from_records(
    records: list[AcceptedAbstract],
    normalized_matrix: np.ndarray,
    neighbor_count: int = 20,
) -> tuple[Any, dict[str, Any]]:
    import networkx as nx

    graph_data = build_weighted_knn_graph(records, normalized_matrix, neighbor_count=neighbor_count)
    adjacency = graph_data["adjacency_connected"].tocoo()
    ordered_ids = [int(record.abstract_id) for record in records]
    graph = nx.Graph()
    graph.add_nodes_from(ordered_ids)
    for row_index, column_index, weight in zip(adjacency.row, adjacency.col, adjacency.data, strict=False):
        if int(row_index) >= int(column_index):
            continue
        if float(weight) <= 0.0:
            continue
        graph.add_edge(
            int(ordered_ids[int(row_index)]),
            int(ordered_ids[int(column_index)]),
            weight=float(weight),
        )
    return graph, graph_data["diagnostics"]


def _community_conductance(graph: Any, community_nodes: set[int]) -> float:
    if not community_nodes:
        return 0.0
    community = {int(node) for node in community_nodes}
    cut_weight = 0.0
    volume = 0.0
    for node in community:
        for neighbor, edge_data in graph[int(node)].items():
            weight = float(edge_data.get("weight", 1.0))
            volume += weight
            if int(neighbor) not in community:
                cut_weight += weight
    total_volume = float(sum(dict(graph.degree(weight="weight")).values()))
    complement_volume = max(total_volume - volume, 0.0)
    denominator = min(volume, complement_volume)
    if denominator <= 1e-12:
        return 0.0
    return float(cut_weight / denominator)


def compute_community_metrics(
    records: list[AcceptedAbstract],
    normalized_matrix: np.ndarray,
    neighbor_count: int = 20,
    target_cluster_count: int = 31,
) -> dict[str, Any]:
    import networkx as nx

    effective_target_cluster_count = 1 if len(records) <= 1 else min(max(2, int(target_cluster_count)), max(2, len(records) // 2))
    graph, graph_diagnostics = _community_graph_from_records(
        records,
        normalized_matrix,
        neighbor_count=neighbor_count,
    )
    cluster_result = derive_contiguous_layout_clusters(
        records,
        normalized_matrix,
        target_cluster_count=effective_target_cluster_count,
    )
    assignments = {
        int(abstract_id): int(cluster_id)
        for abstract_id, cluster_id in (cluster_result.get("assignments") or {}).items()
    }
    communities_by_cluster: dict[int, set[int]] = defaultdict(set)
    for abstract_id, cluster_id in assignments.items():
        communities_by_cluster[int(cluster_id)].add(int(abstract_id))
    ordered_cluster_ids = sorted(communities_by_cluster)
    ordered_communities = [communities_by_cluster[cluster_id] for cluster_id in ordered_cluster_ids]
    sizes = np.asarray([len(community) for community in ordered_communities], dtype=np.float64)
    total_size = float(sizes.sum()) if sizes.size else 0.0

    edge_total = int(graph.number_of_edges())
    explained_edges = 0
    for left, right in graph.edges():
        if assignments.get(int(left)) == assignments.get(int(right)):
            explained_edges += 1
    coverage = float(explained_edges / edge_total) if edge_total > 0 else 0.0

    densities: list[float] = []
    conductances: list[float] = []
    clustering_coefficients: list[float] = []
    for community in ordered_communities:
        subgraph = graph.subgraph(community).copy()
        node_count = int(subgraph.number_of_nodes())
        if node_count <= 1:
            density = 0.0
            clustering = 0.0
        else:
            internal_weight = float(
                sum(float(edge_data.get("weight", 1.0)) for *_nodes, edge_data in subgraph.edges(data=True))
            )
            possible_edges = float(node_count * (node_count - 1) / 2)
            density = float(internal_weight / possible_edges) if possible_edges > 0.0 else 0.0
            clustering = float(nx.average_clustering(subgraph, weight="weight"))
        densities.append(density)
        conductances.append(_community_conductance(graph, community))
        clustering_coefficients.append(clustering)

    if total_size > 0.0:
        weights = sizes / total_size
        weighted_density = float(np.dot(weights, np.asarray(densities, dtype=np.float64)))
        weighted_conductance = float(np.dot(weights, np.asarray(conductances, dtype=np.float64)))
        weighted_clustering = float(np.dot(weights, np.asarray(clustering_coefficients, dtype=np.float64)))
    else:
        weighted_density = 0.0
        weighted_conductance = 0.0
        weighted_clustering = 0.0

    return {
        "graph_neighbor_count": int(graph_diagnostics.get("neighbor_count") or 0),
        "graph_edge_count": edge_total,
        "graph_node_count": int(graph.number_of_nodes()),
        "community_count": len(ordered_communities),
        "target_cluster_count": int(effective_target_cluster_count),
        "coverage": coverage,
        "density": weighted_density,
        "conductance": weighted_conductance,
        "clustering_coefficient": weighted_clustering,
        "community_detection": {
            "method": "contiguous_sequence_agglomerative",
            "target_cluster_count": int(effective_target_cluster_count),
            "clusters": list(cluster_result.get("clusters") or []),
            "communities": [sorted(int(node) for node in community) for community in ordered_communities],
            "assignments": {
                str(abstract_id): int(cluster_id)
                for abstract_id, cluster_id in sorted(assignments.items())
            },
        },
    }


def _mean_block_metric(analysis: dict[str, Any], key_path: tuple[str, ...]) -> float:
    values: list[float] = []
    for block_id in sorted(BLOCK_TO_SESSIONS):
        current: Any = analysis.get("block_analysis", {}).get(str(block_id), {})
        for key in key_path:
            if not isinstance(current, dict):
                current = None
                break
            current = current.get(key)
        if isinstance(current, (int, float)):
            values.append(float(current))
    return float(np.mean(values)) if values else 0.0


def summarize_benchmark_row(
    method_name: str,
    analysis: dict[str, Any],
    graph_metrics_by_block: dict[int, dict[str, Any]],
    proposal_csv: Path,
) -> dict[str, Any]:
    graph_window_mass = float(
        np.mean([graph_metrics_by_block[block_id]["window_edge_mass_rate"] for block_id in sorted(graph_metrics_by_block)])
    )
    graph_weighted_distance = float(
        np.mean([graph_metrics_by_block[block_id]["mean_weighted_index_distance"] for block_id in sorted(graph_metrics_by_block)])
    )
    row = {
        "method_name": str(method_name),
        "block_adjacent_mean_semantic_distance": _mean_block_metric(
            analysis,
            ("locality", "adjacent_mean_semantic_distance"),
        ),
        "block_window_mean_semantic_distance": _mean_block_metric(
            analysis,
            ("locality", "window_mean_semantic_distance"),
        ),
        "block_adjacent_exact_category_match_rate": _mean_block_metric(
            analysis,
            ("locality", "adjacent_exact_category_match_rate"),
        ),
        "block_graph_window_edge_mass_rate": graph_window_mass,
        "block_graph_mean_weighted_index_distance": graph_weighted_distance,
        "author_conflict_total": int(
            sum(
                int(item.get("conflict_count") or 0)
                for item in (analysis.get("author_conflicts_by_session") or {}).values()
                if isinstance(item, dict)
            )
        ),
    }
    row.update(_load_neighbor_tail_metrics(proposal_csv))
    return row


def summarize_diffusion_variant_row(
    variant_name: str,
    analysis: dict[str, Any],
    graph_metrics_by_block: dict[int, dict[str, Any]],
    proposal_csv: Path,
    diffusion_diagnostics_by_block: dict[int, dict[str, Any]],
) -> dict[str, Any]:
    row = summarize_benchmark_row(
        method_name=variant_name,
        analysis=analysis,
        graph_metrics_by_block=graph_metrics_by_block,
        proposal_csv=proposal_csv,
    )
    row.update(
        {
            "max_components_before_bridge": int(
                max(
                    int(diffusion_diagnostics_by_block[block_id]["graph"]["components_before_bridge"])
                    for block_id in sorted(diffusion_diagnostics_by_block)
                )
            ),
            "max_components_after_bridge": int(
                max(
                    int(diffusion_diagnostics_by_block[block_id]["graph"]["components_after_bridge"])
                    for block_id in sorted(diffusion_diagnostics_by_block)
                )
            ),
            "any_disconnected_before_bridge": bool(
                any(
                    bool(diffusion_diagnostics_by_block[block_id]["graph"]["graph_was_disconnected"])
                    for block_id in sorted(diffusion_diagnostics_by_block)
                )
            ),
            "mean_neighbor_count": float(
                np.mean(
                    [
                        float(diffusion_diagnostics_by_block[block_id]["graph"]["neighbor_count"])
                        for block_id in sorted(diffusion_diagnostics_by_block)
                    ]
                )
            ),
            "mean_first_nontrivial_eigenvalue": float(
                np.mean(
                    [
                        float((diffusion_diagnostics_by_block[block_id]["chosen_eigenvalues"] or [0.0])[0])
                        for block_id in sorted(diffusion_diagnostics_by_block)
                    ]
                )
            ),
        }
    )
    return row


def summarize_global_path_variant_row(
    variant_name: str,
    overall_locality: dict[str, Any],
    overall_graph_metrics: dict[str, Any],
    ordered_ids: list[int],
    diffusion_diagnostics: dict[str, Any],
    community_metrics: dict[str, Any] | None = None,
) -> dict[str, Any]:
    row = {
        "method_name": str(variant_name),
        "overall_adjacent_mean_semantic_distance": float(overall_locality.get("adjacent_mean_semantic_distance") or 0.0),
        "overall_window_mean_semantic_distance": float(overall_locality.get("window_mean_semantic_distance") or 0.0),
        "overall_adjacent_exact_category_match_rate": float(overall_locality.get("adjacent_exact_category_match_rate") or 0.0),
        "overall_graph_window_edge_mass_rate": float(overall_graph_metrics.get("window_edge_mass_rate") or 0.0),
        "overall_graph_mean_weighted_index_distance": float(overall_graph_metrics.get("mean_weighted_index_distance") or 0.0),
        "max_components_before_bridge": int(diffusion_diagnostics["graph"]["components_before_bridge"]),
        "max_components_after_bridge": int(diffusion_diagnostics["graph"]["components_after_bridge"]),
        "any_disconnected_before_bridge": bool(diffusion_diagnostics["graph"]["graph_was_disconnected"]),
        "mean_neighbor_count": float(diffusion_diagnostics["graph"]["neighbor_count"]),
        "mean_first_nontrivial_eigenvalue": float((diffusion_diagnostics.get("chosen_eigenvalues") or [0.0])[0]),
    }
    row.update(_neighbor_tail_metrics_from_ordered_ids(ordered_ids))
    community_metrics = community_metrics or {}
    row.update(
        {
            "community_count": int(community_metrics.get("community_count") or 0),
            "community_coverage": float(community_metrics.get("coverage") or 0.0),
            "community_density": float(community_metrics.get("density") or 0.0),
            "community_conductance": float(community_metrics.get("conductance") or 0.0),
            "community_clustering_coefficient": float(community_metrics.get("clustering_coefficient") or 0.0),
        }
    )
    return row


def markdown_benchmark_summary(summary_rows: list[dict[str, Any]]) -> str:
    lines = [
        "# Poster Sequencing Benchmark Summary",
        "",
        "This benchmark holds the current block assignment fixed and reorders posters within each block as a weighted graph reordering problem.",
        "",
        "| Method | Adjacent semantic distance | Window semantic distance | Window edge mass | Weighted index distance | Adjacent category match | Neighbor5 p10 | Below 0.6 |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in summary_rows:
        lines.append(
            f"| `{row['method_name']}` | "
            f"{row['block_adjacent_mean_semantic_distance']:.4f} | "
            f"{row['block_window_mean_semantic_distance']:.4f} | "
            f"{row['block_graph_window_edge_mass_rate']:.4f} | "
            f"{row['block_graph_mean_weighted_index_distance']:.2f} | "
            f"{row['block_adjacent_exact_category_match_rate']:.4f} | "
            f"{row['voyage_neighbor5_p10']:.4f} | "
            f"{row['voyage_neighbor5_below_0_6']} |"
        )
    return "\n".join(lines) + "\n"


def markdown_diffusion_variant_summary(summary_rows: list[dict[str, Any]]) -> str:
    lines = [
        "# Diffusion Variant Sweep Summary",
        "",
        "This sweep keeps the current block assignments fixed and varies the diffusion-map graph and coordinate settings within each block.",
        "",
        "| Variant | Adjacent semantic distance | Window semantic distance | Window edge mass | Neighbor5 p10 | Below 0.6 | Components before bridge | First nontrivial eigenvalue |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in summary_rows:
        lines.append(
            f"| `{row['method_name']}` | "
            f"{row['block_adjacent_mean_semantic_distance']:.4f} | "
            f"{row['block_window_mean_semantic_distance']:.4f} | "
            f"{row['block_graph_window_edge_mass_rate']:.4f} | "
            f"{row['voyage_neighbor5_p10']:.4f} | "
            f"{row['voyage_neighbor5_below_0_6']} | "
            f"{row['max_components_before_bridge']} | "
            f"{row['mean_first_nontrivial_eigenvalue']:.4f} |"
        )
    return "\n".join(lines) + "\n"


def markdown_global_path_diffusion_summary(summary_rows: list[dict[str, Any]]) -> str:
    lines = [
        "# Global Path Diffusion Sweep Summary",
        "",
        "This sweep orders all posters in one global diffusion path, evaluates metrics on that overall sequence, and only then splits the path into blocks using the semantic-path alternation logic.",
        "",
        "| Variant | Overall adjacent semantic distance | Overall window semantic distance | Overall window edge mass | Neighbor5 p10 | Below 0.6 | Components before bridge | First nontrivial eigenvalue |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in summary_rows:
        lines.append(
            f"| `{row['method_name']}` | "
            f"{row['overall_adjacent_mean_semantic_distance']:.4f} | "
            f"{row['overall_window_mean_semantic_distance']:.4f} | "
            f"{row['overall_graph_window_edge_mass_rate']:.4f} | "
            f"{row['voyage_neighbor5_p10']:.4f} | "
            f"{row['voyage_neighbor5_below_0_6']} | "
            f"{row['max_components_before_bridge']} | "
            f"{row['mean_first_nontrivial_eigenvalue']:.4f} |"
        )
    return "\n".join(lines) + "\n"


def benchmark_graph_reordering_methods(
    inputs: LayoutInputs,
    base_proposal: dict[str, Any],
    output_root: Path,
    authors_input: Path | None = None,
    methods: tuple[str, ...] = GRAPH_METHODS,
    spectral_neighbors: int = 20,
    graph_band_width: int = 5,
) -> dict[str, Any]:
    output_root.mkdir(parents=True, exist_ok=True)
    proposal_records_by_block = _proposal_records_by_block(inputs, base_proposal)
    summary_rows: list[dict[str, Any]] = []
    analyses_by_method: dict[str, Any] = {}

    for method_name in methods:
        ordered_ids_by_block: dict[int, list[int]] = {}
        for block_id in sorted(BLOCK_TO_SESSIONS):
            block_records = proposal_records_by_block[block_id]
            if method_name == "baseline_current":
                ordered_ids = [record.abstract_id for record in block_records]
            elif method_name == "spectral_knn":
                ordered_ids = order_records_by_spectral_graph(
                    block_records,
                    inputs.normalized_matrix,
                    neighbor_count=spectral_neighbors,
                )
            elif method_name == "diffusion_map_path":
                ordered_ids = order_records_by_diffusion_map_path(
                    block_records,
                    inputs.normalized_matrix,
                    neighbor_count=spectral_neighbors,
                )
            elif method_name == "optimal_leaf_ordering":
                ordered_ids = order_records_by_optimal_leaf_ordering(block_records, inputs.normalized_matrix)
            elif method_name == "spectral_adjacent_refinement":
                ordered_ids = order_records_by_spectral_adjacent_refinement(
                    block_records,
                    inputs.normalized_matrix,
                    band_width=graph_band_width,
                )
            else:
                raise PosterLayoutError(f"Unknown graph sequencing method: {method_name}")
            ordered_ids_by_block[block_id] = ordered_ids

        proposal = resequence_proposal_blocks(base_proposal, ordered_ids_by_block, method_name=method_name)
        method_dir = output_root / method_name
        method_dir.mkdir(parents=True, exist_ok=True)
        write_json(method_dir / "proposal.json", proposal)
        write_layout_csv(method_dir / "proposal.csv", proposal)
        write_listing_csv(method_dir / "proposal_listing.csv", proposal, authors_input=authors_input)
        analysis = analyze_layout_proposal(inputs, proposal)
        write_json(method_dir / "analysis.json", analysis)
        record_lookup = {record.abstract_id: record for records in proposal_records_by_block.values() for record in records}
        graph_metrics_by_block = {
            block_id: graph_reordering_metrics(
                [record_lookup[abstract_id] for abstract_id in ordered_ids_by_block[block_id]],
                inputs.normalized_matrix,
                band_width=graph_band_width,
            )
            for block_id in sorted(BLOCK_TO_SESSIONS)
        }
        write_json(method_dir / "graph_metrics.json", {"by_block": graph_metrics_by_block})
        summary_row = summarize_benchmark_row(
            method_name=method_name,
            analysis=analysis,
            graph_metrics_by_block=graph_metrics_by_block,
            proposal_csv=method_dir / "proposal.csv",
        )
        summary_rows.append(summary_row)
        analyses_by_method[method_name] = {
            "analysis": analysis,
            "graph_metrics_by_block": graph_metrics_by_block,
            "summary": summary_row,
        }

    summary_rows.sort(
        key=lambda row: (
            int(row["author_conflict_total"]),
            float(row["block_adjacent_mean_semantic_distance"]),
            -float(row["block_graph_window_edge_mass_rate"]),
            float(row["block_graph_mean_weighted_index_distance"]),
            -float(row["voyage_neighbor5_p10"]),
        )
    )
    summary_payload = {
        "base_proposal_method": str((base_proposal.get("metadata") or {}).get("proposal_method") or "unknown"),
        "methods": summary_rows,
    }
    write_json(output_root / "summary.json", summary_payload)
    (output_root / "summary.md").write_text(markdown_benchmark_summary(summary_rows), encoding="utf-8")
    return {
        "summary": summary_payload,
        "details": analyses_by_method,
    }


def sweep_diffusion_variants(
    inputs: LayoutInputs,
    base_proposal: dict[str, Any],
    output_root: Path,
    authors_input: Path | None = None,
    neighbor_counts: tuple[int, ...] = (5, 10, 20, 40),
    coordinate_variants: tuple[tuple[int, str], ...] = ((1, "single"), (2, "pca"), (3, "pca")),
    graph_band_width: int = 5,
) -> dict[str, Any]:
    output_root.mkdir(parents=True, exist_ok=True)
    proposal_records_by_block = _proposal_records_by_block(inputs, base_proposal)
    record_lookup = {record.abstract_id: record for records in proposal_records_by_block.values() for record in records}
    summary_rows: list[dict[str, Any]] = []
    details: dict[str, Any] = {}

    for neighbor_count in neighbor_counts:
        for coordinate_dims, coordinate_mode in coordinate_variants:
            variant_name = f"diffusion_k{int(neighbor_count)}_{str(coordinate_mode)}{int(coordinate_dims)}"
            ordered_ids_by_block: dict[int, list[int]] = {}
            diagnostics_by_block: dict[int, dict[str, Any]] = {}
            for block_id in sorted(BLOCK_TO_SESSIONS):
                result = order_records_by_diffusion_map_path(
                    proposal_records_by_block[block_id],
                    inputs.normalized_matrix,
                    neighbor_count=int(neighbor_count),
                    coordinate_dims=int(coordinate_dims),
                    coordinate_mode=str(coordinate_mode),
                    return_diagnostics=True,
                )
                ordered_ids_by_block[block_id] = list(result["ordered_ids"])
                diagnostics_by_block[block_id] = dict(result["diagnostics"])

            proposal = resequence_proposal_blocks(base_proposal, ordered_ids_by_block, method_name=variant_name)
            method_dir = output_root / variant_name
            method_dir.mkdir(parents=True, exist_ok=True)
            write_json(method_dir / "proposal.json", proposal)
            write_layout_csv(method_dir / "proposal.csv", proposal)
            write_listing_csv(method_dir / "proposal_listing.csv", proposal, authors_input=authors_input)
            analysis = analyze_layout_proposal(inputs, proposal)
            write_json(method_dir / "analysis.json", analysis)
            graph_metrics_by_block = {
                block_id: graph_reordering_metrics(
                    [record_lookup[abstract_id] for abstract_id in ordered_ids_by_block[block_id]],
                    inputs.normalized_matrix,
                    band_width=graph_band_width,
                )
                for block_id in sorted(BLOCK_TO_SESSIONS)
            }
            write_json(method_dir / "graph_metrics.json", {"by_block": graph_metrics_by_block})
            write_json(method_dir / "diffusion_diagnostics.json", {"by_block": diagnostics_by_block})
            summary_row = summarize_diffusion_variant_row(
                variant_name=variant_name,
                analysis=analysis,
                graph_metrics_by_block=graph_metrics_by_block,
                proposal_csv=method_dir / "proposal.csv",
                diffusion_diagnostics_by_block=diagnostics_by_block,
            )
            summary_rows.append(summary_row)
            details[variant_name] = {
                "summary": summary_row,
                "analysis": analysis,
                "graph_metrics_by_block": graph_metrics_by_block,
                "diffusion_diagnostics_by_block": diagnostics_by_block,
            }

    summary_rows.sort(
        key=lambda row: (
            int(row["author_conflict_total"]),
            float(row["block_adjacent_mean_semantic_distance"]),
            -float(row["block_graph_window_edge_mass_rate"]),
            float(row["block_graph_mean_weighted_index_distance"]),
            -float(row["voyage_neighbor5_p10"]),
        )
    )
    summary_payload = {
        "base_proposal_method": str((base_proposal.get("metadata") or {}).get("proposal_method") or "unknown"),
        "variants": summary_rows,
    }
    write_json(output_root / "summary.json", summary_payload)
    (output_root / "summary.md").write_text(markdown_diffusion_variant_summary(summary_rows), encoding="utf-8")
    return {
        "summary": summary_payload,
        "details": details,
    }


def sweep_global_path_diffusion_variants(
    inputs: LayoutInputs,
    base_proposal: dict[str, Any],
    output_root: Path,
    authors_input: Path | None = None,
    neighbor_counts: tuple[int, ...] = (5, 10, 20, 40),
    coordinate_variants: tuple[tuple[int, str], ...] = ((1, "single"), (2, "pca"), (3, "pca")),
    graph_band_width: int = 5,
    include_baselines: bool = True,
) -> dict[str, Any]:
    output_root.mkdir(parents=True, exist_ok=True)
    ordered_records = _proposal_records_in_order(inputs, base_proposal)
    records_by_id = {record.abstract_id: record for record in ordered_records}
    summary_rows: list[dict[str, Any]] = []
    details: dict[str, Any] = {}

    if include_baselines:
        baseline_variants = [
            ("global_baseline_current", [record.abstract_id for record in ordered_records], {"baseline": "current proposal order"}),
            (
                "global_spectral_knn",
                order_records_by_spectral_graph(ordered_records, inputs.normalized_matrix),
                {"baseline": "spectral knn"},
            ),
            (
                "global_spectral_adjacent_refinement",
                order_records_by_spectral_adjacent_refinement(ordered_records, inputs.normalized_matrix),
                {"baseline": "spectral adjacent refinement"},
            ),
            (
                "global_optimal_leaf_ordering",
                order_records_by_optimal_leaf_ordering(ordered_records, inputs.normalized_matrix),
                {"baseline": "optimal leaf ordering"},
            ),
        ]
        for variant_name, global_ordered_ids, diagnostics in baseline_variants:
            proposal = build_global_path_split_proposal(
                base_proposal,
                global_ordered_ids=global_ordered_ids,
                records_by_id=records_by_id,
                method_name=variant_name,
            )
            method_dir = output_root / variant_name
            method_dir.mkdir(parents=True, exist_ok=True)
            write_json(method_dir / "proposal.json", proposal)
            write_layout_csv(method_dir / "proposal.csv", proposal)
            write_listing_csv(method_dir / "proposal_listing.csv", proposal, authors_input=authors_input)
            analysis = analyze_layout_proposal(inputs, proposal)
            write_json(method_dir / "analysis.json", analysis)
            overall_records = [records_by_id[abstract_id] for abstract_id in global_ordered_ids]
            overall_locality = _window_distances(overall_records, inputs.normalized_matrix, window_size=graph_band_width)
            overall_graph_metrics = graph_reordering_metrics(
                overall_records,
                inputs.normalized_matrix,
                band_width=graph_band_width,
            )
            write_json(
                method_dir / "global_sequence_metrics.json",
                {
                    "overall_locality": overall_locality,
                    "overall_graph_metrics": overall_graph_metrics,
                    "ordered_abstract_ids": global_ordered_ids,
                },
            )
            write_json(method_dir / "diffusion_diagnostics.json", {"overall": diagnostics})
            summary_row = {
                "method_name": variant_name,
                "overall_adjacent_mean_semantic_distance": float(overall_locality.get("adjacent_mean_semantic_distance") or 0.0),
                "overall_window_mean_semantic_distance": float(overall_locality.get("window_mean_semantic_distance") or 0.0),
                "overall_adjacent_exact_category_match_rate": float(overall_locality.get("adjacent_exact_category_match_rate") or 0.0),
                "overall_graph_window_edge_mass_rate": float(overall_graph_metrics.get("window_edge_mass_rate") or 0.0),
                "overall_graph_mean_weighted_index_distance": float(overall_graph_metrics.get("mean_weighted_index_distance") or 0.0),
                "max_components_before_bridge": 0,
                "max_components_after_bridge": 0,
                "any_disconnected_before_bridge": False,
                "mean_neighbor_count": 0.0,
                "mean_first_nontrivial_eigenvalue": 0.0,
            }
            summary_row.update(_neighbor_tail_metrics_from_ordered_ids(global_ordered_ids))
            summary_rows.append(summary_row)
            details[variant_name] = {
                "summary": summary_row,
                "analysis": analysis,
                "overall_locality": overall_locality,
                "overall_graph_metrics": overall_graph_metrics,
                "diffusion_diagnostics": diagnostics,
                "ordered_abstract_ids": global_ordered_ids,
            }

    for neighbor_count in neighbor_counts:
        for coordinate_dims, coordinate_mode in coordinate_variants:
            variant_name = f"global_diffusion_k{int(neighbor_count)}_{str(coordinate_mode)}{int(coordinate_dims)}"
            result = order_records_by_diffusion_map_path(
                ordered_records,
                inputs.normalized_matrix,
                neighbor_count=int(neighbor_count),
                coordinate_dims=int(coordinate_dims),
                coordinate_mode=str(coordinate_mode),
                return_diagnostics=True,
            )
            global_ordered_ids = list(result["ordered_ids"])
            proposal = build_global_path_split_proposal(
                base_proposal,
                global_ordered_ids=global_ordered_ids,
                records_by_id=records_by_id,
                method_name=variant_name,
            )
            method_dir = output_root / variant_name
            method_dir.mkdir(parents=True, exist_ok=True)
            write_json(method_dir / "proposal.json", proposal)
            write_layout_csv(method_dir / "proposal.csv", proposal)
            write_listing_csv(method_dir / "proposal_listing.csv", proposal, authors_input=authors_input)
            analysis = analyze_layout_proposal(inputs, proposal)
            write_json(method_dir / "analysis.json", analysis)
            overall_records = [records_by_id[abstract_id] for abstract_id in global_ordered_ids]
            overall_locality = _window_distances(overall_records, inputs.normalized_matrix, window_size=graph_band_width)
            overall_graph_metrics = graph_reordering_metrics(
                overall_records,
                inputs.normalized_matrix,
                band_width=graph_band_width,
            )
            write_json(
                method_dir / "global_sequence_metrics.json",
                {
                    "overall_locality": overall_locality,
                    "overall_graph_metrics": overall_graph_metrics,
                    "ordered_abstract_ids": global_ordered_ids,
                },
            )
            write_json(method_dir / "diffusion_diagnostics.json", {"overall": result["diagnostics"]})
            summary_row = summarize_global_path_variant_row(
                variant_name=variant_name,
                overall_locality=overall_locality,
                overall_graph_metrics=overall_graph_metrics,
                ordered_ids=global_ordered_ids,
                diffusion_diagnostics=result["diagnostics"],
            )
            summary_rows.append(summary_row)
            details[variant_name] = {
                "summary": summary_row,
                "analysis": analysis,
                "overall_locality": overall_locality,
                "overall_graph_metrics": overall_graph_metrics,
                "diffusion_diagnostics": result["diagnostics"],
                "ordered_abstract_ids": global_ordered_ids,
            }

    summary_rows.sort(
        key=lambda row: (
            float(row["overall_adjacent_mean_semantic_distance"]),
            -float(row["overall_graph_window_edge_mass_rate"]),
            float(row["overall_graph_mean_weighted_index_distance"]),
            -float(row["voyage_neighbor5_p10"]),
        )
    )
    summary_payload = {
        "base_proposal_method": str((base_proposal.get("metadata") or {}).get("proposal_method") or "unknown"),
        "variants": summary_rows,
    }
    write_json(output_root / "summary.json", summary_payload)
    (output_root / "summary.md").write_text(markdown_global_path_diffusion_summary(summary_rows), encoding="utf-8")
    return {
        "summary": summary_payload,
        "details": details,
    }


def markdown_global_path_mapalign_summary(summary_rows: list[dict[str, Any]]) -> str:
    lines = [
        "# Global Path Mapalign-Style Diffusion Summary",
        "",
        "This sweep uses a mapalign-style diffusion embedding with anisotropic normalization and explicit diffusion-time handling, then splits the global path into blocks using the semantic-path alternation logic.",
        "",
        "| Variant | Overall adjacent semantic distance | Overall window semantic distance | Overall window edge mass | Neighbor5 p10 | Below 0.6 | Affinity | Alpha | Time |",
        "| --- | ---: | ---: | ---: | ---: | ---: | --- | ---: | ---: |",
    ]
    for row in summary_rows:
        lines.append(
            f"| `{row['method_name']}` | "
            f"{row['overall_adjacent_mean_semantic_distance']:.4f} | "
            f"{row['overall_window_mean_semantic_distance']:.4f} | "
            f"{row['overall_graph_window_edge_mass_rate']:.4f} | "
            f"{row['voyage_neighbor5_p10']:.4f} | "
            f"{row['voyage_neighbor5_below_0_6']} | "
            f"{row['affinity_mode']} | "
            f"{row['alpha']:.2f} | "
            f"{row['diffusion_time']:.1f} |"
        )
    return "\n".join(lines) + "\n"


def summarize_mapalign_variant_row(
    variant_name: str,
    overall_locality: dict[str, Any],
    overall_graph_metrics: dict[str, Any],
    ordered_ids: list[int],
    diagnostics: dict[str, Any],
) -> dict[str, Any]:
    row = summarize_global_path_variant_row(
        variant_name=variant_name,
        overall_locality=overall_locality,
        overall_graph_metrics=overall_graph_metrics,
        ordered_ids=ordered_ids,
        diffusion_diagnostics=diagnostics,
    )
    row["affinity_mode"] = str(diagnostics.get("affinity_mode") or diagnostics.get("graph", {}).get("affinity_mode") or "")
    row["alpha"] = float(diagnostics.get("alpha") or 0.0)
    row["diffusion_time"] = float(diagnostics.get("diffusion_time") or 0.0)
    return row


def _global_path_baseline_variants(
    ordered_records: list[AcceptedAbstract],
    normalized_matrix: np.ndarray,
) -> list[tuple[str, list[int], dict[str, Any]]]:
    return [
        ("global_baseline_current", [record.abstract_id for record in ordered_records], {"graph": {"components_before_bridge": 0, "components_after_bridge": 0, "graph_was_disconnected": False, "neighbor_count": 0}}),
        ("global_spectral_knn", order_records_by_spectral_graph(ordered_records, normalized_matrix), {"graph": {"components_before_bridge": 0, "components_after_bridge": 0, "graph_was_disconnected": False, "neighbor_count": 0}}),
        ("global_spectral_adjacent_refinement", order_records_by_spectral_adjacent_refinement(ordered_records, normalized_matrix), {"graph": {"components_before_bridge": 0, "components_after_bridge": 0, "graph_was_disconnected": False, "neighbor_count": 0}}),
        ("global_optimal_leaf_ordering", order_records_by_optimal_leaf_ordering(ordered_records, normalized_matrix), {"graph": {"components_before_bridge": 0, "components_after_bridge": 0, "graph_was_disconnected": False, "neighbor_count": 0}}),
    ]


def _write_global_path_variant(
    variant_name: str,
    global_ordered_ids: list[int],
    diagnostics: dict[str, Any],
    base_proposal: dict[str, Any],
    records_by_id: dict[int, AcceptedAbstract],
    inputs: LayoutInputs,
    output_root: Path,
    authors_input: Path | None,
    graph_band_width: int,
    diagnostics_filename: str = "diffusion_diagnostics.json",
) -> dict[str, Any]:
    proposal = build_global_path_split_proposal(
        base_proposal,
        global_ordered_ids=global_ordered_ids,
        records_by_id=records_by_id,
        method_name=variant_name,
    )
    method_dir = output_root / variant_name
    method_dir.mkdir(parents=True, exist_ok=True)
    write_json(method_dir / "proposal.json", proposal)
    write_layout_csv(method_dir / "proposal.csv", proposal)
    write_listing_csv(method_dir / "proposal_listing.csv", proposal, authors_input=authors_input)
    analysis = analyze_layout_proposal(inputs, proposal)
    write_json(method_dir / "analysis.json", analysis)
    overall_records = [records_by_id[abstract_id] for abstract_id in global_ordered_ids]
    overall_locality = _window_distances(overall_records, inputs.normalized_matrix, window_size=graph_band_width)
    overall_graph_metrics = graph_reordering_metrics(
        overall_records,
        inputs.normalized_matrix,
        band_width=graph_band_width,
    )
    community_metrics = compute_community_metrics(
        overall_records,
        inputs.normalized_matrix,
        neighbor_count=20,
    )
    assignment_by_id = {
        int(abstract_id): int(cluster_id)
        for abstract_id, cluster_id in (community_metrics["community_detection"].get("assignments") or {}).items()
    }
    boundary_positions: list[int] = []
    previous_cluster_id: int | None = None
    for position, record in enumerate(overall_records, start=1):
        cluster_id = assignment_by_id.get(int(record.abstract_id))
        if previous_cluster_id is not None and cluster_id != previous_cluster_id:
            boundary_positions.append(int(position))
        previous_cluster_id = cluster_id
    _write_ordered_cosine_similarity_matrix_plot(
        overall_records,
        inputs.normalized_matrix,
        method_dir / "ordered_cosine_similarity_matrix.png",
        boundary_positions=boundary_positions,
    )
    write_json(
        method_dir / "global_sequence_metrics.json",
        {
            "overall_locality": overall_locality,
            "overall_graph_metrics": overall_graph_metrics,
            "community_metrics": {
                key: value
                for key, value in community_metrics.items()
                if key != "community_detection"
            },
            "ordered_abstract_ids": global_ordered_ids,
        },
    )
    write_json(method_dir / "community_detection.json", community_metrics["community_detection"])
    write_json(
        method_dir / "community_metrics.json",
        {
            key: value
            for key, value in community_metrics.items()
            if key != "community_detection"
        },
    )
    write_json(method_dir / str(diagnostics_filename), {"overall": diagnostics})
    return {
        "analysis": analysis,
        "overall_locality": overall_locality,
        "overall_graph_metrics": overall_graph_metrics,
        "community_metrics": {
            key: value
            for key, value in community_metrics.items()
            if key != "community_detection"
        },
        "ordered_abstract_ids": global_ordered_ids,
    }


def sweep_global_path_mapalign_variants(
    inputs: LayoutInputs,
    base_proposal: dict[str, Any],
    output_root: Path,
    authors_input: Path | None = None,
    affinity_modes: tuple[str, ...] = ("knn", "full"),
    neighbor_counts: tuple[int, ...] = (10, 20, 40),
    alphas: tuple[float, ...] = (0.5, 1.0),
    diffusion_times: tuple[float, ...] = (0.0, 1.0),
    coordinate_variants: tuple[tuple[int, str], ...] = ((1, "single"), (2, "pca"), (2, "lexsort")),
    graph_band_width: int = 5,
    include_baselines: bool = True,
) -> dict[str, Any]:
    output_root.mkdir(parents=True, exist_ok=True)
    ordered_records = _proposal_records_in_order(inputs, base_proposal)
    records_by_id = {record.abstract_id: record for record in ordered_records}
    summary_rows: list[dict[str, Any]] = []
    details: dict[str, Any] = {}

    if include_baselines:
        for variant_name, global_ordered_ids, diagnostics in _global_path_baseline_variants(
            ordered_records,
            inputs.normalized_matrix,
        ):
            result = _write_global_path_variant(
                variant_name=variant_name,
                global_ordered_ids=global_ordered_ids,
                diagnostics=diagnostics,
                base_proposal=base_proposal,
                records_by_id=records_by_id,
                inputs=inputs,
                output_root=output_root,
                authors_input=authors_input,
                graph_band_width=graph_band_width,
                diagnostics_filename="diffusion_diagnostics.json",
            )
            summary_row = summarize_global_path_variant_row(
                variant_name=variant_name,
                overall_locality=result["overall_locality"],
                overall_graph_metrics=result["overall_graph_metrics"],
                ordered_ids=global_ordered_ids,
                diffusion_diagnostics=diagnostics,
            )
            summary_row["affinity_mode"] = "baseline"
            summary_row["alpha"] = 0.0
            summary_row["diffusion_time"] = 0.0
            summary_rows.append(summary_row)
            details[variant_name] = {"summary": summary_row, **result, "diffusion_diagnostics": diagnostics}

    for affinity_mode in affinity_modes:
        active_neighbor_counts = neighbor_counts if affinity_mode == "knn" else (0,)
        for neighbor_count in active_neighbor_counts:
            for alpha in alphas:
                for diffusion_time in diffusion_times:
                    for coordinate_dims, coordinate_mode in coordinate_variants:
                        variant_name = f"mapalign_{affinity_mode}"
                        if affinity_mode == "knn":
                            variant_name += f"_k{int(neighbor_count)}"
                        variant_name += f"_a{str(alpha).replace('.', '')}_t{str(diffusion_time).replace('.', '')}_{coordinate_mode}{int(coordinate_dims)}"
                        diffusion_result = order_records_by_mapalign_style_diffusion(
                            ordered_records,
                            inputs.normalized_matrix,
                            affinity_mode=affinity_mode,
                            neighbor_count=max(2, int(neighbor_count)) if affinity_mode == "knn" else 2,
                            alpha=float(alpha),
                            diffusion_time=float(diffusion_time),
                            coordinate_dims=int(coordinate_dims),
                            coordinate_mode=str(coordinate_mode),
                            return_diagnostics=True,
                        )
                        global_ordered_ids = list(diffusion_result["ordered_ids"])
                        result = _write_global_path_variant(
                            variant_name=variant_name,
                            global_ordered_ids=global_ordered_ids,
                            diagnostics=diffusion_result["diagnostics"],
                            base_proposal=base_proposal,
                            records_by_id=records_by_id,
                            inputs=inputs,
                            output_root=output_root,
                            authors_input=authors_input,
                            graph_band_width=graph_band_width,
                            diagnostics_filename="diffusion_diagnostics.json",
                        )
                        summary_row = summarize_mapalign_variant_row(
                            variant_name=variant_name,
                            overall_locality=result["overall_locality"],
                            overall_graph_metrics=result["overall_graph_metrics"],
                            ordered_ids=global_ordered_ids,
                            diagnostics=diffusion_result["diagnostics"],
                        )
                        summary_rows.append(summary_row)
                        details[variant_name] = {
                            "summary": summary_row,
                            **result,
                            "diffusion_diagnostics": diffusion_result["diagnostics"],
                        }

    summary_rows.sort(
        key=lambda row: (
            float(row["overall_adjacent_mean_semantic_distance"]),
            -float(row["overall_graph_window_edge_mass_rate"]),
            float(row["overall_graph_mean_weighted_index_distance"]),
            -float(row["voyage_neighbor5_p10"]),
        )
    )
    summary_payload = {
        "base_proposal_method": str((base_proposal.get("metadata") or {}).get("proposal_method") or "unknown"),
        "variants": summary_rows,
    }
    write_json(output_root / "summary.json", summary_payload)
    (output_root / "summary.md").write_text(markdown_global_path_mapalign_summary(summary_rows), encoding="utf-8")
    return {
        "summary": summary_payload,
        "details": details,
    }


def markdown_advanced_global_path_summary(summary_rows: list[dict[str, Any]]) -> str:
    lines = [
        "# Advanced Global Path Summary",
        "",
        "This experiment compares stronger non-diffusion global orderers before splitting the sequence into blocks with the semantic-path alternation logic.",
        "",
        "| Method | Overall adjacent semantic distance | Overall window semantic distance | Overall window edge mass | Neighbor5 p10 | Below 0.6 | Below 0.4 | Coverage | Density | Conductance | Clustering coeff. |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in summary_rows:
        lines.append(
            f"| `{row['method_name']}` | "
            f"{row['overall_adjacent_mean_semantic_distance']:.4f} | "
            f"{row['overall_window_mean_semantic_distance']:.4f} | "
            f"{row['overall_graph_window_edge_mass_rate']:.4f} | "
            f"{row['voyage_neighbor5_p10']:.4f} | "
            f"{row['voyage_neighbor5_below_0_6']} | "
            f"{row['voyage_neighbor5_below_0_4']} | "
            f"{row['community_coverage']:.4f} | "
            f"{row['community_density']:.4f} | "
            f"{row['community_conductance']:.4f} | "
            f"{row['community_clustering_coefficient']:.4f} |"
        )
    return "\n".join(lines) + "\n"


def _advanced_global_path_variants(
    ordered_records: list[AcceptedAbstract],
    normalized_matrix: np.ndarray,
) -> list[tuple[str, list[int], dict[str, Any]]]:
    olo_ids = order_records_by_optimal_leaf_ordering(ordered_records, normalized_matrix)
    spectral_ids = order_records_by_spectral_graph(ordered_records, normalized_matrix)
    diagnostics = {"graph": {"components_before_bridge": 0, "components_after_bridge": 0, "graph_was_disconnected": False, "neighbor_count": 0}}
    return [
        ("global_baseline_current", [record.abstract_id for record in ordered_records], diagnostics),
        ("global_optimal_leaf_ordering", olo_ids, diagnostics),
        (
            "global_olo_adjacent_refinement",
            order_records_by_olo_adjacent_refinement(ordered_records, normalized_matrix),
            diagnostics,
        ),
        (
            "global_olo_two_opt_knn20",
            order_records_by_sparse_two_opt(
                ordered_records,
                normalized_matrix,
                seed_ids=olo_ids,
                neighbor_count=20,
            ),
            diagnostics,
        ),
        (
            "global_spectral_two_opt_knn20",
            order_records_by_sparse_two_opt(
                ordered_records,
                normalized_matrix,
                seed_ids=spectral_ids,
                neighbor_count=20,
            ),
            diagnostics,
        ),
        (
            "global_clustered_kmeans_olo",
            order_records_by_clustered_kmeans_olo(ordered_records, normalized_matrix),
            diagnostics,
        ),
    ]


def _olo_two_opt_parameter_variants(
    ordered_records: list[AcceptedAbstract],
    normalized_matrix: np.ndarray,
) -> list[tuple[str, list[int], dict[str, Any]]]:
    olo_seed = order_records_by_optimal_leaf_ordering(ordered_records, normalized_matrix)
    spectral_seed = order_records_by_spectral_graph(ordered_records, normalized_matrix)
    diagnostics = {"graph": {"components_before_bridge": 0, "components_after_bridge": 0, "graph_was_disconnected": False, "neighbor_count": 0}}
    variants: list[tuple[str, list[int], dict[str, Any]]] = []
    for seed_name, seed_ids in (("olo", olo_seed), ("spectral", spectral_seed)):
        for neighbor_count in (10, 20, 40):
            for max_passes in (2, 4, 8):
                variant_name = f"global_{seed_name}_two_opt_knn{neighbor_count}_p{max_passes}"
                variants.append(
                    (
                        variant_name,
                        order_records_by_sparse_two_opt(
                            ordered_records,
                            normalized_matrix,
                            seed_ids=seed_ids,
                            neighbor_count=neighbor_count,
                            max_passes=max_passes,
                        ),
                        diagnostics,
                    )
                )
    return variants


def run_advanced_global_path_experiment(
    inputs: LayoutInputs,
    base_proposal: dict[str, Any],
    output_root: Path,
    authors_input: Path | None = None,
    graph_band_width: int = 5,
    include_parameter_sweep: bool = True,
) -> dict[str, Any]:
    output_root.mkdir(parents=True, exist_ok=True)
    ordered_records = _proposal_records_in_order(inputs, base_proposal)
    records_by_id = {record.abstract_id: record for record in ordered_records}
    summary_rows: list[dict[str, Any]] = []
    details: dict[str, Any] = {}

    variants = _advanced_global_path_variants(
        ordered_records,
        inputs.normalized_matrix,
    )
    if include_parameter_sweep:
        variants.extend(_olo_two_opt_parameter_variants(ordered_records, inputs.normalized_matrix))

    for variant_name, global_ordered_ids, diagnostics in variants:
        result = _write_global_path_variant(
            variant_name=variant_name,
            global_ordered_ids=global_ordered_ids,
            diagnostics=diagnostics,
            base_proposal=base_proposal,
            records_by_id=records_by_id,
            inputs=inputs,
            output_root=output_root,
            authors_input=authors_input,
            graph_band_width=graph_band_width,
            diagnostics_filename="diagnostics.json",
        )
        summary_row = summarize_global_path_variant_row(
            variant_name=variant_name,
            overall_locality=result["overall_locality"],
            overall_graph_metrics=result["overall_graph_metrics"],
            ordered_ids=global_ordered_ids,
            diffusion_diagnostics=diagnostics,
            community_metrics=result["community_metrics"],
        )
        summary_rows.append(summary_row)
        details[variant_name] = {
            "summary": summary_row,
            **result,
            "diagnostics": diagnostics,
        }

    summary_rows.sort(
        key=lambda row: (
            float(row["overall_adjacent_mean_semantic_distance"]),
            -float(row["overall_graph_window_edge_mass_rate"]),
            float(row["overall_graph_mean_weighted_index_distance"]),
            -float(row["voyage_neighbor5_p10"]),
            int(row["voyage_neighbor5_below_0_4"]),
        )
    )
    summary_payload = {
        "base_proposal_method": str((base_proposal.get("metadata") or {}).get("proposal_method") or "unknown"),
        "variants": summary_rows,
    }
    write_json(output_root / "summary.json", summary_payload)
    (output_root / "summary.md").write_text(markdown_advanced_global_path_summary(summary_rows), encoding="utf-8")
    return {
        "summary": summary_payload,
        "details": details,
    }


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def benchmark_from_files(
    proposal_path: Path,
    inputs: LayoutInputs,
    output_root: Path,
    authors_input: Path | None = None,
    methods: tuple[str, ...] = GRAPH_METHODS,
    spectral_neighbors: int = 20,
    graph_band_width: int = 5,
) -> dict[str, Any]:
    proposal = load_proposal(proposal_path)
    return benchmark_graph_reordering_methods(
        inputs,
        proposal,
        output_root=output_root,
        authors_input=authors_input,
        methods=methods,
        spectral_neighbors=spectral_neighbors,
        graph_band_width=graph_band_width,
    )


def sweep_diffusion_from_files(
    proposal_path: Path,
    inputs: LayoutInputs,
    output_root: Path,
    authors_input: Path | None = None,
    neighbor_counts: tuple[int, ...] = (5, 10, 20, 40),
    coordinate_variants: tuple[tuple[int, str], ...] = ((1, "single"), (2, "pca"), (3, "pca")),
    graph_band_width: int = 5,
) -> dict[str, Any]:
    proposal = load_proposal(proposal_path)
    return sweep_diffusion_variants(
        inputs,
        proposal,
        output_root=output_root,
        authors_input=authors_input,
        neighbor_counts=neighbor_counts,
        coordinate_variants=coordinate_variants,
        graph_band_width=graph_band_width,
    )


def sweep_global_path_diffusion_from_files(
    proposal_path: Path,
    inputs: LayoutInputs,
    output_root: Path,
    authors_input: Path | None = None,
    neighbor_counts: tuple[int, ...] = (5, 10, 20, 40),
    coordinate_variants: tuple[tuple[int, str], ...] = ((1, "single"), (2, "pca"), (3, "pca")),
    graph_band_width: int = 5,
) -> dict[str, Any]:
    proposal = load_proposal(proposal_path)
    return sweep_global_path_diffusion_variants(
        inputs,
        proposal,
        output_root=output_root,
        authors_input=authors_input,
        neighbor_counts=neighbor_counts,
        coordinate_variants=coordinate_variants,
        graph_band_width=graph_band_width,
    )


def sweep_global_path_mapalign_from_files(
    proposal_path: Path,
    inputs: LayoutInputs,
    output_root: Path,
    authors_input: Path | None = None,
    affinity_modes: tuple[str, ...] = ("knn", "full"),
    neighbor_counts: tuple[int, ...] = (10, 20, 40),
    alphas: tuple[float, ...] = (0.5, 1.0),
    diffusion_times: tuple[float, ...] = (0.0, 1.0),
    coordinate_variants: tuple[tuple[int, str], ...] = ((1, "single"), (2, "pca"), (2, "lexsort")),
    graph_band_width: int = 5,
    include_baselines: bool = True,
) -> dict[str, Any]:
    proposal = load_proposal(proposal_path)
    return sweep_global_path_mapalign_variants(
        inputs,
        proposal,
        output_root=output_root,
        authors_input=authors_input,
        affinity_modes=affinity_modes,
        neighbor_counts=neighbor_counts,
        alphas=alphas,
        diffusion_times=diffusion_times,
        coordinate_variants=coordinate_variants,
        graph_band_width=graph_band_width,
        include_baselines=include_baselines,
    )


def run_advanced_global_path_experiment_from_files(
    proposal_path: Path,
    inputs: LayoutInputs,
    output_root: Path,
    authors_input: Path | None = None,
    graph_band_width: int = 5,
) -> dict[str, Any]:
    proposal = load_proposal(proposal_path)
    return run_advanced_global_path_experiment(
        inputs,
        proposal,
        output_root=output_root,
        authors_input=authors_input,
        graph_band_width=graph_band_width,
    )
