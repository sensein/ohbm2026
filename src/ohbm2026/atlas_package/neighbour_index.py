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

import hashlib
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from ohbm2026.exceptions import KnnCacheError

__all__ = [
    "KnnResult",
    "build_knn",
    "compute_knn_state_key",
    "cache_paths",
]


@dataclass(frozen=True)
class KnnResult:
    pmids: np.ndarray  # shape (N,)
    nearest_pmids: np.ndarray  # shape (N, k)
    nearest_distances: np.ndarray  # shape (N, k)


# Cache layout under ``<cache_root>/<state_key>/`` (mirrors the UMAP fit
# cache in ``umap_fit.py``): three parallel ``.npy`` arrays + a forensic
# params file. An entry is "complete" only when all three arrays exist;
# a partial directory raises :class:`KnnCacheError` rather than silently
# recomputing the (expensive) brute-force search.
_CACHE_PMIDS_FILE = "pmids.npy"
_CACHE_NEAREST_PMIDS_FILE = "nearest_pmids.npy"
_CACHE_NEAREST_DIST_FILE = "nearest_distances.npy"
_CACHE_PARAMS_FILE = "params.json"


def compute_knn_state_key(pmids: np.ndarray, vectors: np.ndarray, k: int) -> str:
    """Return ``sha256(pmids_bytes || vectors_bytes || k)[:12]``.

    Keys the on-disk neighbour-index cache. ``query_chunk`` is
    deliberately NOT part of the key: it only affects the memory
    batching of an identical computation, never the result.
    """

    h = hashlib.sha256()
    h.update(np.ascontiguousarray(pmids.astype(np.int64, copy=False)).tobytes())
    h.update(np.ascontiguousarray(vectors.astype(np.float32, copy=False)).tobytes())
    h.update(f"k={int(k)}".encode())
    return h.hexdigest()[:12]


def cache_paths(cache_root: Path, state_key: str) -> dict[str, Path]:
    """Return the absolute paths inside a single cache entry."""

    base = Path(cache_root) / state_key
    return {
        "dir": base,
        "pmids": base / _CACHE_PMIDS_FILE,
        "nearest_pmids": base / _CACHE_NEAREST_PMIDS_FILE,
        "nearest_distances": base / _CACHE_NEAREST_DIST_FILE,
        "params": base / _CACHE_PARAMS_FILE,
    }


def _load_cached(entry: dict[str, Path], k: int) -> KnnResult:
    """Load a complete cache entry, or raise :class:`KnnCacheError`."""

    missing = [
        name
        for name in ("pmids", "nearest_pmids", "nearest_distances")
        if not entry[name].exists()
    ]
    if missing:
        raise KnnCacheError(
            f"k-NN cache entry at {entry['dir']!s} is incomplete "
            f"(missing: {', '.join(missing)})",
            path=str(entry["dir"]),
            reason="incomplete_entry",
        )
    try:
        pmids = np.load(entry["pmids"], allow_pickle=False)
        nearest_pmids = np.load(entry["nearest_pmids"], allow_pickle=False)
        nearest_distances = np.load(entry["nearest_distances"], allow_pickle=False)
    except Exception as exc:
        raise KnnCacheError(
            f"k-NN cache entry at {entry['dir']!s} is unreadable: {exc}",
            path=str(entry["dir"]),
            reason="unreadable",
        ) from exc
    expected_k = max(0, int(k))
    if nearest_pmids.shape[1] != expected_k or nearest_distances.shape[1] != expected_k:
        raise KnnCacheError(
            f"k-NN cache entry at {entry['dir']!s} has k="
            f"{nearest_pmids.shape[1]} but {expected_k} was requested",
            path=str(entry["dir"]),
            reason="k_mismatch",
        )
    return KnnResult(
        pmids=np.ascontiguousarray(pmids.astype(np.int64, copy=False)),
        nearest_pmids=np.ascontiguousarray(nearest_pmids.astype(np.int64, copy=False)),
        nearest_distances=np.ascontiguousarray(
            nearest_distances.astype(np.float32, copy=False)
        ),
    )


def _persist_cache(entry: dict[str, Path], result: KnnResult, state_key: str, k: int) -> None:
    """Persist a fresh cache entry atomically (temp → ``os.replace``)."""

    import json

    entry["dir"].mkdir(parents=True, exist_ok=True)

    def _atomic_save(target: Path, array: np.ndarray) -> None:
        fd, tmp = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".npy", dir=str(entry["dir"]))
        os.close(fd)
        try:
            np.save(tmp, array, allow_pickle=False)
            os.replace(tmp, target)
        except Exception:
            Path(tmp).unlink(missing_ok=True)
            raise

    _atomic_save(entry["pmids"], result.pmids)
    _atomic_save(entry["nearest_pmids"], result.nearest_pmids)
    _atomic_save(entry["nearest_distances"], result.nearest_distances)

    fd, tmp = tempfile.mkstemp(prefix=f".{_CACHE_PARAMS_FILE}.", suffix=".tmp", dir=str(entry["dir"]))
    os.close(fd)
    try:
        Path(tmp).write_bytes(
            json.dumps(
                {"state_key": state_key, "k": int(k), "n": int(result.pmids.shape[0])},
                sort_keys=True,
            ).encode()
        )
        os.replace(tmp, entry["params"])
    except Exception:
        Path(tmp).unlink(missing_ok=True)
        raise


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
    cache_root: Path | None = None,
) -> KnnResult:
    """Compute k-nearest neighbours under cosine distance.

    ``pmids`` is shape ``(N,)`` int64. ``vectors`` is shape
    ``(N, D)`` float32. ``k`` is clamped to ``N - 1`` (a row's own
    pmid is never returned as a neighbour). ``query_chunk`` controls
    the chunked query-side batch size — tune for memory on large
    corpora; for the 461K-row production corpus this defaults
    to 4096.

    When ``cache_root`` is provided, a lookup at
    ``<cache_root>/<state_key>/`` is performed first. On a complete hit
    the cached arrays are returned unchanged — the brute-force O(n²)
    cosine search (~20-30 min on the 461k corpus) is skipped entirely.
    On a miss the fresh result is persisted into the same path so a
    rebuild with unchanged ``(pmids, vectors, k)`` short-circuits
    (constitution III — same treatment the UMAP fit already gets).
    """

    pmids = np.ascontiguousarray(pmids.astype(np.int64, copy=False))
    vectors = np.ascontiguousarray(vectors.astype(np.float32, copy=False))
    n = int(vectors.shape[0])

    if k >= n:
        k = max(0, n - 1)

    # Cache key uses the CLAMPED k so the stored shape always matches a
    # later requested-then-clamped k (two callers whose k both clamp to
    # n-1 share one entry — same result).
    if cache_root is not None:
        state_key = compute_knn_state_key(pmids, vectors, k)
        entry = cache_paths(cache_root, state_key)
        if (
            entry["pmids"].exists()
            or entry["nearest_pmids"].exists()
            or entry["nearest_distances"].exists()
        ):
            return _load_cached(entry, k)

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
    result = KnnResult(
        pmids=pmids,
        nearest_pmids=nearest_pmids,
        nearest_distances=nearest_dist,
    )

    if cache_root is not None:
        _persist_cache(cache_paths(cache_root, state_key), result, state_key, k)

    return result
