"""Per-cluster stratified decimation for the landing-page backdrop.

Spec: ``specs/015-neuroscape-context/`` — research R-011.

The bare-root cross-conference atlas page ships two NeuroScape
backdrop samples in ``atlas.parquet``: the full corpus (461K points)
and a decimated one (≤50K points) that keeps the landing page
interactive on mid-range mobile devices. The decimated backdrop is
a per-cluster stratified random sample with deterministic seed so
consecutive rebuilds emit byte-identical decimated points.

Quota policy:

- Compute ``quota_c = ceil(target_size * size_c / total_size)`` per
  cluster, then ensure every cluster contributes at least 1 row so
  the legend remains meaningful for small clusters.
- If the resulting total exceeds ``target_size``, trim from the
  largest clusters first until the total fits — small clusters
  retain their floor of 1.
- Sampling within each cluster uses ``numpy.random.default_rng(seed)``
  so the result is reproducible across runs.
"""

from __future__ import annotations

import numpy as np

__all__ = ["stratified_sample"]


def stratified_sample(
    cluster_ids: np.ndarray,
    *,
    target_size: int,
    seed: int = 0,
) -> np.ndarray:
    """Return int64 indices into ``cluster_ids`` for a stratified sample.

    The returned indices are unordered (the caller may sort if
    deterministic row order is desired). Every cluster present in
    ``cluster_ids`` is guaranteed to contribute at least one index
    so the legend is never empty for a present cluster (R-003 +
    R-011).
    """

    cluster_ids = np.ascontiguousarray(cluster_ids)
    n = int(cluster_ids.shape[0])

    if n == 0:
        return np.empty(0, dtype=np.int64)

    if target_size >= n:
        # No decimation needed — return every index in original order.
        return np.arange(n, dtype=np.int64)

    rng = np.random.default_rng(seed=seed)

    unique_clusters, inverse, counts = np.unique(
        cluster_ids, return_inverse=True, return_counts=True
    )
    n_clusters = unique_clusters.shape[0]

    # Floor-1 + proportional quota. ceil(target * size_c / total).
    total = int(counts.sum())
    raw_quotas = np.ceil(target_size * counts / max(total, 1)).astype(np.int64)
    quotas = np.maximum(raw_quotas, 1)
    quotas = np.minimum(quotas, counts)

    # If we over-shot the target, trim from the largest cluster first
    # while keeping the floor of 1 for every cluster.
    while int(quotas.sum()) > target_size:
        # Pick the cluster with the most "trimmable" headroom
        # (quota - 1). Argmax breaks ties on the smallest cluster_id
        # (np.argmax returns the first occurrence) which keeps the
        # trim order deterministic.
        headroom = quotas - 1
        if headroom.max() <= 0:
            break
        trim_idx = int(np.argmax(headroom))
        quotas[trim_idx] -= 1

    # Build the per-cluster member index lists and sample from each.
    selected: list[np.ndarray] = []
    for ci in range(n_clusters):
        member_indices = np.flatnonzero(inverse == ci)
        q = int(quotas[ci])
        if q >= member_indices.shape[0]:
            selected.append(member_indices)
        else:
            pick = rng.choice(member_indices, size=q, replace=False)
            selected.append(np.asarray(pick, dtype=np.int64))

    out = np.concatenate(selected, axis=0) if selected else np.empty(0, dtype=np.int64)
    return out.astype(np.int64, copy=False)
