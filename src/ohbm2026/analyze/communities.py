"""Stage 4 community detection (US4).

Implements the published NeuroScape recipe:

1. FAISS `IndexFlatIP` kNN graph over L2-normalized vectors (inner
   product equals cosine similarity on the unit hypersphere).
2. Symmetrize the resulting adjacency: `A_sym = (A + A.T) / 2`.
3. Leiden with `CPMVertexPartition` (Constant Potts Model) on the
   weighted graph.
4. Resolution-parameter sweep (default 20 linear points over
   `(min_res, max_res]`); select the resolution at the modularity
   plateau as the cluster count grows.
5. Order community ids by descending community size so the largest
   community is always `0` (FR-007).

Per FR-007 + spec clarifications:
- L2 normalization makes inner product equivalent to cosine.
- CPM resolution sweep picks the elbow at the modularity-vs-cluster-
  count knee.
- Edge weights are kept symmetric and non-negative.
- Community resolution that produces a single dominant community
  holding >90% of abstracts triggers `CommunityResolutionDegenerate`
  warning (the bundle is still written; operator can re-run with a
  different resolution range).
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from ohbm2026.exceptions import AnalysisError, CommunityResolutionDegenerate


__all__ = [
    "DEFAULT_KNN_K",
    "DEFAULT_RESOLUTION_MIN",
    "DEFAULT_RESOLUTION_MAX",
    "DEFAULT_RESOLUTION_POINTS",
    "DEFAULT_SEED",
    "DOMINANT_COMMUNITY_THRESHOLD",
    "ResolutionSweepEntry",
    "CommunityResult",
    "build_faiss_knn",
    "knn_to_graph",
    "leiden_cpm_partition",
    "resolution_sweep",
    "select_plateau_resolution",
    "reorder_by_size",
    "detect_communities",
    "write_communities_bundle",
]


DEFAULT_KNN_K = 30
DEFAULT_RESOLUTION_MIN = 0.001
DEFAULT_RESOLUTION_MAX = 0.1
DEFAULT_RESOLUTION_POINTS = 20
DEFAULT_SEED = 42
DOMINANT_COMMUNITY_THRESHOLD = 0.9


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ResolutionSweepEntry:
    """One row of the resolution sweep table."""

    resolution: float
    n_communities: int
    modularity: float


@dataclass(frozen=True)
class CommunityResult:
    """Output of `detect_communities` — everything `write_communities_bundle` needs."""

    community_ids: np.ndarray  # int32, shape (n,); ordered by descending size
    knn_indices: np.ndarray  # int32, shape (n, k)
    knn_similarities: np.ndarray  # float32, shape (n, k)
    resolution_sweep: list[ResolutionSweepEntry]
    selected_resolution: float
    selected_modularity: float
    n_communities: int
    largest_community_share: float


# ---------------------------------------------------------------------------
# FAISS kNN graph
# ---------------------------------------------------------------------------


def _l2_normalize(matrix: np.ndarray, *, eps: float = 1e-12) -> np.ndarray:
    arr = np.asarray(matrix, dtype=np.float32)
    norms = np.linalg.norm(arr, axis=1, keepdims=True)
    norms = np.where(norms < eps, 1.0, norms)
    return (arr / norms).astype(np.float32, copy=False)


def build_faiss_knn(
    vectors: np.ndarray, *, k: int
) -> tuple[np.ndarray, np.ndarray]:
    """L2-normalize → FAISS `IndexFlatIP` kNN → `(indices, similarities)`.

    Returns:
        indices: int32, shape `(n, k_effective)` — top-k neighbor row
          indices for each row, excluding the row itself.
        similarities: float32, shape `(n, k_effective)` — inner products
          (cosine on the unit hypersphere) corresponding to `indices`.

    `k_effective = min(k, n - 1)` so a small synthetic corpus doesn't
    fail. Self-edges are stripped from the output.
    """
    try:
        import faiss  # lazy
    except ImportError as exc:  # pragma: no cover
        raise AnalysisError(
            "faiss-cpu is required for community detection. "
            "Install via: uv pip install --python .venv/bin/python '.[analysis]'"
        ) from exc

    arr = _l2_normalize(vectors)
    n, d = arr.shape
    k_effective = max(1, min(k, n - 1))
    # Ask for k_effective + 1 so we can drop the self-edge.
    index = faiss.IndexFlatIP(d)
    index.add(arr)
    sims, inds = index.search(arr, k_effective + 1)
    # Strip the self-edge: it's the row's own row index with similarity ~1.0,
    # and FAISS usually returns it as the first hit on an exact IP query.
    out_inds = np.zeros((n, k_effective), dtype=np.int32)
    out_sims = np.zeros((n, k_effective), dtype=np.float32)
    for i in range(n):
        mask = inds[i] != i
        keep = inds[i][mask][:k_effective]
        keep_s = sims[i][mask][:k_effective]
        # Pad if FAISS returned fewer than k_effective non-self hits
        # (only possible with duplicate rows on tiny corpora).
        if keep.shape[0] < k_effective:
            pad = k_effective - keep.shape[0]
            keep = np.concatenate([keep, np.full(pad, i, dtype=np.int32)])
            keep_s = np.concatenate([keep_s, np.zeros(pad, dtype=np.float32)])
        out_inds[i] = keep
        out_sims[i] = keep_s
    return out_inds, out_sims


# ---------------------------------------------------------------------------
# kNN → igraph (symmetrized weighted)
# ---------------------------------------------------------------------------


def knn_to_graph(
    indices: np.ndarray,
    similarities: np.ndarray,
    *,
    symmetrize: bool = True,
    keep_negative: bool = False,
) -> Any:
    """Build an `igraph.Graph` from a kNN edge list.

    Edges are weighted by cosine similarity. With `symmetrize=True`, the
    output is undirected and edge weights are averaged across the two
    directional kNN entries (matches NeuroScape's recipe). With
    `symmetrize=False`, the graph stays directed.
    """
    try:
        import igraph as ig  # lazy
    except ImportError as exc:  # pragma: no cover
        raise AnalysisError(
            "python-igraph is required for community detection."
        ) from exc

    n, k = indices.shape
    # Build a sparse adjacency dict: {(u, v): sim} averaged over both directions
    adj: dict[tuple[int, int], float] = {}
    for u in range(n):
        for j in range(k):
            v = int(indices[u, j])
            sim = float(similarities[u, j])
            if not keep_negative and sim <= 0.0:
                continue
            if u == v:
                continue
            if symmetrize:
                key = (u, v) if u < v else (v, u)
                if key in adj:
                    adj[key] = (adj[key] + sim) / 2.0
                else:
                    adj[key] = sim
            else:
                adj[(u, v)] = sim

    if not adj:
        # An entirely-disconnected corpus → return an edgeless graph.
        graph = ig.Graph(n=n, directed=not symmetrize)
        graph.es["weight"] = []
        return graph

    edges = list(adj.keys())
    weights = [adj[e] for e in edges]
    graph = ig.Graph(n=n, edges=edges, directed=not symmetrize)
    graph.es["weight"] = weights
    return graph


# ---------------------------------------------------------------------------
# Leiden CPM partition
# ---------------------------------------------------------------------------


def leiden_cpm_partition(
    graph: Any, *, resolution: float, seed: int = DEFAULT_SEED
) -> tuple[np.ndarray, float]:
    """Run Leiden with `CPMVertexPartition` at a fixed resolution.

    Returns `(membership, modularity)` where `membership[i]` is the
    community index of vertex `i` and `modularity` is `partition.modularity`
    (matches igraph's `modularity()` convention).
    """
    try:
        import leidenalg as la  # lazy
    except ImportError as exc:  # pragma: no cover
        raise AnalysisError(
            "leidenalg is required for community detection."
        ) from exc

    weights = graph.es["weight"] if "weight" in graph.es.attributes() else None
    partition = la.find_partition(
        graph,
        la.CPMVertexPartition,
        weights=weights,
        resolution_parameter=float(resolution),
        seed=int(seed),
    )
    membership = np.asarray(partition.membership, dtype=np.int32)
    return membership, float(partition.modularity)


# ---------------------------------------------------------------------------
# Resolution sweep + plateau selection
# ---------------------------------------------------------------------------


def resolution_sweep(
    graph: Any,
    *,
    resolution_min: float = DEFAULT_RESOLUTION_MIN,
    resolution_max: float = DEFAULT_RESOLUTION_MAX,
    points: int = DEFAULT_RESOLUTION_POINTS,
    seed: int = DEFAULT_SEED,
) -> list[ResolutionSweepEntry]:
    """Run Leiden CPM at each point in a linear sweep over `(min, max]`.

    Records `(resolution, n_communities, modularity)` per point. The sweep
    is deterministic for a fixed seed.
    """
    if points < 1:
        raise ValueError("resolution_sweep: points must be >= 1")
    if resolution_max <= resolution_min:
        raise ValueError(
            f"resolution_sweep: max ({resolution_max}) must exceed min ({resolution_min})"
        )
    # NeuroScape's recipe sweeps (min, max] — exclude the min endpoint.
    resolutions = np.linspace(resolution_min, resolution_max, points + 1)[1:]
    sweep: list[ResolutionSweepEntry] = []
    for resolution in resolutions:
        membership, modularity = leiden_cpm_partition(
            graph, resolution=float(resolution), seed=seed
        )
        n_communities = int(np.unique(membership).size)
        sweep.append(
            ResolutionSweepEntry(
                resolution=float(resolution),
                n_communities=n_communities,
                modularity=float(modularity),
            )
        )
    return sweep


def select_plateau_resolution(
    sweep: list[ResolutionSweepEntry],
) -> int:
    """Pick the resolution at the modularity plateau as the cluster
    count grows.

    Heuristic: sort by ascending `n_communities`, then choose the entry
    where the modularity gain per additional cluster first drops below
    the median gain — the elbow. For pathological monotonic curves
    (every step gains the same modularity), fall back to the entry with
    the highest modularity overall.

    Returns the sweep-list index of the chosen entry.
    """
    if not sweep:
        raise ValueError("select_plateau_resolution: empty sweep")
    if len(sweep) == 1:
        return 0
    # Sort by n_communities ascending (ties broken by resolution).
    order = sorted(
        range(len(sweep)),
        key=lambda i: (sweep[i].n_communities, sweep[i].resolution),
    )
    ordered = [sweep[i] for i in order]
    # Modularity gains per cluster added (between consecutive ordered points).
    gains: list[float] = []
    for prev, cur in zip(ordered[:-1], ordered[1:]):
        d_clusters = cur.n_communities - prev.n_communities
        if d_clusters <= 0:
            gains.append(0.0)
        else:
            gains.append(
                (cur.modularity - prev.modularity) / float(d_clusters)
            )
    if not gains:
        # Fall back to highest modularity overall.
        best_idx = max(range(len(sweep)), key=lambda i: sweep[i].modularity)
        return best_idx
    median_gain = float(np.median(gains))
    # Find the FIRST step where the gain drops below the median (elbow).
    elbow_step = None
    for i, gain in enumerate(gains):
        if gain < median_gain:
            elbow_step = i + 1  # the "after" entry of the step
            break
    if elbow_step is None:
        elbow_step = len(ordered) - 1
    chosen_ordered = ordered[elbow_step]
    # Map back to the original sweep list index.
    for i, entry in enumerate(sweep):
        if entry is chosen_ordered:
            return i
    return order[elbow_step]


# ---------------------------------------------------------------------------
# Community-id reordering by size
# ---------------------------------------------------------------------------


def reorder_by_size(membership: np.ndarray) -> np.ndarray:
    """Relabel communities so id `0` is the largest, `1` the next, etc.

    Returns `int32` array of the same shape as `membership`.
    """
    membership = np.asarray(membership, dtype=np.int32)
    if membership.size == 0:
        return membership
    unique, counts = np.unique(membership, return_counts=True)
    # Sort communities by descending size, then by ascending original id
    # (deterministic tie-break).
    order = sorted(
        zip(unique.tolist(), counts.tolist()),
        key=lambda kv: (-kv[1], kv[0]),
    )
    remap = {old_id: new_id for new_id, (old_id, _count) in enumerate(order)}
    out = np.zeros_like(membership)
    for i, m in enumerate(membership):
        out[i] = remap[int(m)]
    return out


# ---------------------------------------------------------------------------
# Top-level pipeline
# ---------------------------------------------------------------------------


def detect_communities(
    vectors: np.ndarray,
    *,
    knn_k: int = DEFAULT_KNN_K,
    resolution_min: float = DEFAULT_RESOLUTION_MIN,
    resolution_max: float = DEFAULT_RESOLUTION_MAX,
    resolution_points: int = DEFAULT_RESOLUTION_POINTS,
    seed: int = DEFAULT_SEED,
) -> CommunityResult:
    """Build FAISS kNN → symmetrize → Leiden CPM sweep → pick plateau
    → relabel by size. Returns everything `write_communities_bundle`
    needs.

    Emits a `CommunityResolutionDegenerate` warning when the largest
    community holds >`DOMINANT_COMMUNITY_THRESHOLD` of the abstracts.
    """
    indices, similarities = build_faiss_knn(vectors, k=knn_k)
    graph = knn_to_graph(indices, similarities, symmetrize=True)
    sweep = resolution_sweep(
        graph,
        resolution_min=resolution_min,
        resolution_max=resolution_max,
        points=resolution_points,
        seed=seed,
    )
    chosen_idx = select_plateau_resolution(sweep)
    chosen = sweep[chosen_idx]
    membership, modularity = leiden_cpm_partition(
        graph, resolution=chosen.resolution, seed=seed
    )
    community_ids = reorder_by_size(membership)
    n_communities = int(np.unique(community_ids).size)
    counts = np.bincount(community_ids)
    largest_share = float(counts.max()) / float(community_ids.size)
    if largest_share > DOMINANT_COMMUNITY_THRESHOLD:
        warnings.warn(
            f"largest community holds {largest_share:.2%} of abstracts "
            f"(>{DOMINANT_COMMUNITY_THRESHOLD:.0%}); resolution sweep may "
            f"need adjustment",
            CommunityResolutionDegenerate,
            stacklevel=2,
        )
    return CommunityResult(
        community_ids=community_ids,
        knn_indices=indices,
        knn_similarities=similarities,
        resolution_sweep=sweep,
        selected_resolution=chosen.resolution,
        selected_modularity=float(modularity),
        n_communities=n_communities,
        largest_community_share=largest_share,
    )


# ---------------------------------------------------------------------------
# Bundle writer
# ---------------------------------------------------------------------------


def write_communities_bundle(
    bundle_dir: Path,
    *,
    ids: np.ndarray,
    result: CommunityResult,
    source_model: str,
    input_source: str,
    seed: int = DEFAULT_SEED,
    knn_k: int = DEFAULT_KNN_K,
    resolution_min: float = DEFAULT_RESOLUTION_MIN,
    resolution_max: float = DEFAULT_RESOLUTION_MAX,
    resolution_points: int = DEFAULT_RESOLUTION_POINTS,
    topics: dict[int, dict[str, Any]] | None = None,
    metadata_extra: dict[str, Any] | None = None,
) -> Path:
    """Write a `communities` bundle per `contracts/bundle.md`.

    Topics may be passed in (filled by US5's topics-attachment pass) or
    left as `None` for the topics-skipping path (`--skip-llm-topics`
    without the local fallback wired yet).
    """
    from ohbm2026.analyze.storage import write_analysis_bundle

    if ids.shape[0] != result.community_ids.shape[0]:
        raise ValueError(
            "ids and result.community_ids must align on the leading axis"
        )

    import json

    payload = {
        "community_ids": result.community_ids.astype(np.int32, copy=False),
        "knn_indices": result.knn_indices.astype(np.int32, copy=False),
        "knn_similarities": result.knn_similarities.astype(np.float32, copy=False),
    }
    sweep_serialized = [
        {
            "resolution": entry.resolution,
            "n_communities": entry.n_communities,
            "modularity": entry.modularity,
        }
        for entry in result.resolution_sweep
    ]
    metadata = {
        "kind": "communities",
        "source_model": source_model,
        "input_source": input_source,
        "n_rows": int(ids.shape[0]),
        "knn_k": int(knn_k),
        "knn_metric": "ip_normalized",
        "leiden_partition": "CPMVertexPartition",
        "resolution_min": float(resolution_min),
        "resolution_max": float(resolution_max),
        "resolution_points": int(resolution_points),
        "selected_resolution": float(result.selected_resolution),
        "selected_modularity": float(result.selected_modularity),
        "n_communities": int(result.n_communities),
        "largest_community_share": float(result.largest_community_share),
        "seed": int(seed),
        "resolution_sweep": sweep_serialized,
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
            "kind": "communities",
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
