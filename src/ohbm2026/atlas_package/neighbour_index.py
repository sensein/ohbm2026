"""k-NN over NeuroScape Stage-2 vectors.

Spec: ``specs/015-neuroscape-context/`` — research R-008.

Produces the ``neighbors_neuroscape`` row group for
``neuroscape.parquet`` (parallel arrays per
:data:`contracts/parquet-schemas.md`):

- ``pmids`` — one row per NeuroScape article
- ``nearest_pmids`` — int64 (N, k); excludes self
- ``nearest_distances`` — float32 (N, k); cosine distances in
  ascending order (closest first)

For the 461K-row production corpus this uses sklearn's
``NearestNeighbors`` with the ``brute`` algorithm (cosine metric is
exact and reproducible — tree-based algorithms approximate cosine).
The trade-off is fully acceptable: at 461K × 64-dim float32, brute-
force pairwise distance is ~30 GB peak memory if computed in one
batch, so the implementation chunks the query side.

For unit tests the brute path is exact + deterministic so the
"nearest neighbour is actually nearest" assertion holds without
flake.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

__all__ = ["KnnResult", "build_knn"]


@dataclass(frozen=True)
class KnnResult:
    pmids: np.ndarray  # shape (N,)
    nearest_pmids: np.ndarray  # shape (N, k)
    nearest_distances: np.ndarray  # shape (N, k)


def _normalise_rows(v: np.ndarray) -> np.ndarray:
    """Return a copy with each row L2-normalised."""

    norms = np.linalg.norm(v, axis=1, keepdims=True)
    norms = np.where(norms == 0.0, 1.0, norms)
    return (v / norms).astype(np.float32)


def build_knn(
    pmids: np.ndarray,
    vectors: np.ndarray,
    *,
    k: int,
    query_chunk: int = 4096,
) -> KnnResult:
    """Compute k-nearest neighbours under cosine distance.

    ``pmids`` is shape ``(N,)`` int64. ``vectors`` is shape
    ``(N, D)`` float32. ``k`` is clamped to ``N - 1`` (a row's own
    pmid is never returned as a neighbour). ``query_chunk`` controls
    the chunked query-side batch size — tune for memory on large
    corpora; for the 461K-row production corpus this defaults
    to 4096.
    """

    pmids = np.ascontiguousarray(pmids.astype(np.int64, copy=False))
    vectors = np.ascontiguousarray(vectors.astype(np.float32, copy=False))
    n = int(vectors.shape[0])

    if k >= n:
        k = max(0, n - 1)

    # L2-normalise so cosine similarity = inner product.
    normed = _normalise_rows(vectors)

    nearest_idx = np.empty((n, k), dtype=np.int64)
    nearest_dist = np.empty((n, k), dtype=np.float32)

    for start in range(0, n, query_chunk):
        stop = min(start + query_chunk, n)
        # Cosine similarity for the chunk — shape (chunk, n).
        sims = normed[start:stop] @ normed.T
        # Mask self-similarity so each row's own index is never
        # picked. -inf so it sorts to the end after `-sims` argsort.
        for offset in range(stop - start):
            sims[offset, start + offset] = -np.inf
        # Convert similarity → distance (1 - cos), exclude self by
        # taking top-k from the masked similarity ranking.
        # `argpartition` is faster than full argsort but doesn't
        # guarantee internal order; we then sort the k-block itself.
        if k > 0:
            partial_idx = np.argpartition(-sims, kth=k - 1, axis=1)[:, :k]
            # Pull the corresponding sims, sort each row in descending
            # similarity (= ascending distance).
            row_idx = np.arange(stop - start)[:, None]
            top_sims = sims[row_idx, partial_idx]
            order = np.argsort(-top_sims, axis=1, kind="stable")
            sorted_idx = partial_idx[row_idx, order]
            sorted_sims = top_sims[row_idx, order]
            nearest_idx[start:stop] = sorted_idx
            nearest_dist[start:stop] = (1.0 - sorted_sims).astype(np.float32)
        else:
            nearest_idx[start:stop] = np.empty((stop - start, 0), dtype=np.int64)
            nearest_dist[start:stop] = np.empty((stop - start, 0), dtype=np.float32)

    nearest_pmids = pmids[nearest_idx]
    # Numerical floor: cosine distance can be slightly negative due
    # to floating-point error on near-identical vectors. Clamp to
    # 0.0 so downstream consumers don't see negative distances.
    np.maximum(nearest_dist, 0.0, out=nearest_dist)
    return KnnResult(
        pmids=pmids,
        nearest_pmids=nearest_pmids,
        nearest_distances=nearest_dist,
    )
