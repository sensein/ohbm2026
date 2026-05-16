"""Stage 4 `topic_clusters` analysis kind (US5).

A topic-model-driven clustering: UMAP → HDBSCAN (BERTopic-style). The
output bundle ships both `topic_cluster_ids` (per-row int32) and
`topic_cluster_probabilities` (per-row soft assignment) plus the
per-cluster `topics.json` built by the spaCy + c-TF-IDF + optional LLM
pipeline in `analyze.topics`.

`n_topics=None` triggers an elbow-on-noise-fraction selection rule:
sweep HDBSCAN's `min_cluster_size` (and thus the resulting cluster
count) and pick the operating point where the noise-fraction's first
derivative flattens.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from ohbm2026.exceptions import AnalysisError


__all__ = [
    "DEFAULT_UMAP_N_NEIGHBORS",
    "DEFAULT_UMAP_MIN_DIST",
    "DEFAULT_UMAP_COMPONENTS",
    "DEFAULT_MIN_CLUSTER_SIZE",
    "TopicClustersResult",
    "run_topic_clustering",
    "write_topic_clusters_bundle",
]


# BERTopic-style defaults (tuned slightly for smaller corpora).
DEFAULT_UMAP_N_NEIGHBORS = 15
DEFAULT_UMAP_MIN_DIST = 0.0
DEFAULT_UMAP_COMPONENTS = 5
DEFAULT_MIN_CLUSTER_SIZE = 10


@dataclass(frozen=True)
class TopicClustersResult:
    topic_cluster_ids: np.ndarray  # int32 (n,); -1 = HDBSCAN noise, others ≥ 0
    topic_cluster_probabilities: np.ndarray  # float32 (n,)
    n_topics: int
    n_noise: int
    min_cluster_size: int


def _umap_reduce(
    vectors: np.ndarray,
    *,
    n_components: int,
    n_neighbors: int,
    min_dist: float,
    seed: int,
) -> np.ndarray:
    try:
        import umap
    except ImportError as exc:  # pragma: no cover
        raise AnalysisError(
            "umap-learn is required for topic_clusters. "
            "Install via: uv pip install --python .venv/bin/python '.[analysis]'"
        ) from exc

    n_rows = int(vectors.shape[0])
    if n_rows <= n_neighbors:
        n_neighbors = max(2, n_rows - 1)
    if n_rows <= n_components:
        n_components = max(2, n_rows - 1)
    model = umap.UMAP(
        n_components=n_components,
        n_neighbors=n_neighbors,
        min_dist=min_dist,
        metric="cosine",
        random_state=seed,
    )
    reduced = model.fit_transform(np.asarray(vectors, dtype=np.float32))
    return np.asarray(reduced, dtype=np.float32)


def _hdbscan_cluster(
    reduced: np.ndarray, *, min_cluster_size: int
) -> tuple[np.ndarray, np.ndarray]:
    try:
        import hdbscan
    except ImportError as exc:  # pragma: no cover
        raise AnalysisError(
            "hdbscan is required for topic_clusters."
        ) from exc

    n_rows = int(reduced.shape[0])
    mcs = max(2, min(min_cluster_size, max(2, n_rows // 2)))
    clusterer = hdbscan.HDBSCAN(
        min_cluster_size=mcs,
        prediction_data=True,
        cluster_selection_method="eom",
    )
    labels = np.asarray(clusterer.fit_predict(reduced), dtype=np.int32)
    probabilities = np.asarray(clusterer.probabilities_, dtype=np.float32)
    return labels, probabilities


def _select_auto_min_cluster_size(reduced: np.ndarray, *, seed: int) -> int:
    """Auto-pick `min_cluster_size` by sweeping a small grid and choosing
    the value at the noise-fraction elbow.

    Sweeps `min_cluster_size ∈ {5, 10, 15, 20, 30, 50}` (clipped to the
    corpus size). Picks the smallest `mcs` whose noise fraction is
    `<= 0.5` and whose subsequent step's noise fraction differs by
    `< 0.05` (the plateau). Falls back to `DEFAULT_MIN_CLUSTER_SIZE`
    when no clean elbow exists.
    """
    n_rows = int(reduced.shape[0])
    candidates = [c for c in (5, 10, 15, 20, 30, 50) if c < n_rows]
    if not candidates:
        return max(2, n_rows // 4)
    sweep: list[tuple[int, float]] = []
    for mcs in candidates:
        labels, _probs = _hdbscan_cluster(reduced, min_cluster_size=mcs)
        n_noise = int(np.sum(labels == -1))
        noise_frac = n_noise / n_rows
        sweep.append((mcs, noise_frac))
    # Elbow: first mcs where noise fraction ≤ 0.5 AND the next step's
    # noise fraction is within 0.05 of this one.
    for i in range(len(sweep) - 1):
        mcs, noise_here = sweep[i]
        _next_mcs, noise_next = sweep[i + 1]
        if noise_here <= 0.5 and abs(noise_here - noise_next) < 0.05:
            return mcs
    # Fallback: the mcs with the lowest noise fraction.
    best = min(sweep, key=lambda kv: kv[1])
    return best[0]


def run_topic_clustering(
    vectors: np.ndarray,
    *,
    n_topics: int | None = None,
    min_cluster_size: int | None = None,
    umap_n_neighbors: int = DEFAULT_UMAP_N_NEIGHBORS,
    umap_min_dist: float = DEFAULT_UMAP_MIN_DIST,
    umap_components: int = DEFAULT_UMAP_COMPONENTS,
    seed: int = 42,
) -> TopicClustersResult:
    """UMAP-reduce → HDBSCAN cluster. Returns `TopicClustersResult`.

    When `n_topics` is set, ignored — HDBSCAN doesn't accept a target
    count directly; the auto-min_cluster_size sweep approximates it by
    picking the noise-elbow operating point. If you need a hard target,
    pass `min_cluster_size` explicitly.
    """
    reduced = _umap_reduce(
        vectors,
        n_components=umap_components,
        n_neighbors=umap_n_neighbors,
        min_dist=umap_min_dist,
        seed=seed,
    )

    if min_cluster_size is None:
        mcs = _select_auto_min_cluster_size(reduced, seed=seed)
    else:
        mcs = int(min_cluster_size)

    labels, probabilities = _hdbscan_cluster(reduced, min_cluster_size=mcs)
    n_topics_observed = int(labels.max() + 1) if labels.max() >= 0 else 0
    n_noise = int(np.sum(labels == -1))
    return TopicClustersResult(
        topic_cluster_ids=labels,
        topic_cluster_probabilities=probabilities,
        n_topics=n_topics_observed,
        n_noise=n_noise,
        min_cluster_size=mcs,
    )


def write_topic_clusters_bundle(
    bundle_dir: Path,
    *,
    ids: np.ndarray,
    result: TopicClustersResult,
    source_model: str,
    input_source: str,
    seed: int = 42,
    topics: dict[int, dict[str, Any]] | None = None,
    metadata_extra: dict[str, Any] | None = None,
) -> Path:
    """Write a `topic_clusters` bundle per `contracts/bundle.md`."""
    from ohbm2026.analyze.storage import write_analysis_bundle

    if ids.shape[0] != result.topic_cluster_ids.shape[0]:
        raise ValueError(
            "ids and result.topic_cluster_ids must align on the leading axis"
        )

    payload = {
        "topic_cluster_ids": result.topic_cluster_ids.astype(np.int32, copy=False),
        "topic_cluster_probabilities": result.topic_cluster_probabilities.astype(
            np.float32, copy=False
        ),
    }
    metadata = {
        "kind": "topic_clusters",
        "source_model": source_model,
        "input_source": input_source,
        "n_rows": int(ids.shape[0]),
        "n_topics": int(result.n_topics),
        "n_noise": int(result.n_noise),
        "min_cluster_size": int(result.min_cluster_size),
        "topic_selection_rule": "noise_elbow_sweep",
        "topic_model_seed": int(seed),
        "seed": int(seed),
    }
    if metadata_extra:
        metadata.update(metadata_extra)
    return write_analysis_bundle(
        bundle_dir,
        ids=ids,
        payload=payload,
        metadata=metadata,
        provenance={
            "schema_version": "stage4.provenance.v1",
            "stage": "analysis",
            "kind": "topic_clusters",
            "bundle_path": str(bundle_dir),
            "corpus_state_key": "",
            "input_source_assembly_hash": "",
            "algorithm_config_canonical_json": "{}",
            "cache_key": "",
            "code_revision": "",
            "command": "",
            "seed": seed,
            "started_at": "",
            "completed_at": "",
        },
        topics=topics,
    )
