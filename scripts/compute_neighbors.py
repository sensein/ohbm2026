#!/usr/bin/env python
"""Compute k-nearest + k-farthest neighbors per (model, input) cell.

For each `data/outputs/analysis/<cell_key>/projections__<state-key>/` bundle
this script loads `ids.npy` + `reference_matrix.npy`, computes the pairwise
cosine-distance matrix, and writes:

    data/outputs/analysis/<cell_key>/neighbors__<state-key>/
        ids.npy                    (N,)        int64  abstract_id per row
        nearest_ids.npy            (N, K)      int64  abstract_id of k-th nearest (excl. self)
        nearest_distances.npy      (N, K)      float32 corresponding distance
        farthest_ids.npy           (N, K)      int64
        farthest_distances.npy     (N, K)      float32
        provenance.json                       run metadata + state-keys

K defaults to 10. Cosine distance is `1 - cos(u, v)` on the L2-normalized
embeddings; `M @ M.T` gives the cosine similarity matrix in one BLAS call.

Run via:
    PYTHONPATH=src .venv/bin/python scripts/compute_neighbors.py \
        --analysis-root data/outputs/analysis [--k 10]
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np


def _argmin_k(distances: np.ndarray, k: int, exclude: int) -> np.ndarray:
    """Indices of the *k* smallest values in `distances`, skipping `exclude` (the row's own index)."""

    n = distances.shape[0]
    # argpartition is O(N) per row; take k+1 to leave room for the self-skip.
    take = min(n, k + 1)
    candidate_idx = np.argpartition(distances, take - 1)[:take]
    # Sort by actual distance for deterministic order.
    candidate_idx = candidate_idx[np.argsort(distances[candidate_idx])]
    out = candidate_idx[candidate_idx != exclude][:k]
    return out


def _argmax_k(distances: np.ndarray, k: int) -> np.ndarray:
    """Indices of the *k* largest values."""

    n = distances.shape[0]
    take = min(n, k)
    candidate_idx = np.argpartition(distances, n - take)[n - take:]
    candidate_idx = candidate_idx[np.argsort(-distances[candidate_idx])]
    return candidate_idx[:k]


def compute_cell_neighbors(
    bundle_dir: Path, k: int = 10
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Return `(ids, nearest_ids, nearest_dist, farthest_ids, farthest_dist)`."""

    ids = np.load(bundle_dir / "ids.npy").astype(np.int64)
    matrix = np.load(bundle_dir / "reference_matrix.npy").astype(np.float32)
    n, d = matrix.shape
    if ids.shape[0] != n:
        raise RuntimeError(f"shape mismatch in {bundle_dir}: ids={ids.shape}, matrix={matrix.shape}")
    # L2-normalize → cosine similarity is just M @ M.T.
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    normed = matrix / norms
    sim = normed @ normed.T  # (N, N)
    np.clip(sim, -1.0, 1.0, out=sim)
    dist = 1.0 - sim  # cosine distance
    nearest_ids = np.zeros((n, k), dtype=np.int64)
    nearest_dist = np.zeros((n, k), dtype=np.float32)
    farthest_ids = np.zeros((n, k), dtype=np.int64)
    farthest_dist = np.zeros((n, k), dtype=np.float32)
    for i in range(n):
        n_idx = _argmin_k(dist[i], k=k, exclude=i)
        f_idx = _argmax_k(dist[i], k=k)
        nearest_ids[i, : len(n_idx)] = ids[n_idx]
        nearest_dist[i, : len(n_idx)] = dist[i, n_idx]
        farthest_ids[i, : len(f_idx)] = ids[f_idx]
        farthest_dist[i, : len(f_idx)] = dist[i, f_idx]
    return ids, nearest_ids, nearest_dist, farthest_ids, farthest_dist


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--analysis-root",
        type=Path,
        default=Path("data/outputs/analysis"),
        help="Root containing per-cell <cell_key>/projections__*/ bundles.",
    )
    parser.add_argument("--k", type=int, default=10, help="Number of nearest + farthest to store.")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Recompute even if the neighbors__<state-key>/ output already exists.",
    )
    args = parser.parse_args(argv)

    analysis_root = args.analysis_root
    if not analysis_root.exists():
        print(f"analysis-root {analysis_root} does not exist", file=sys.stderr)
        return 2
    cell_dirs = sorted(p for p in analysis_root.iterdir() if p.is_dir() and "_" in p.name)
    if not cell_dirs:
        print(f"no cell directories under {analysis_root}", file=sys.stderr)
        return 2

    total_start = time.time()
    n_done = 0
    for cell_dir in cell_dirs:
        proj = sorted(cell_dir.glob("projections__*"))
        if not proj:
            continue
        bundle = proj[-1]
        state_key = bundle.name.split("__", 1)[1]
        out_dir = cell_dir / f"neighbors__{state_key}"
        if out_dir.exists() and not args.force:
            print(f"skip {cell_dir.name}: neighbors already at {out_dir}")
            continue
        out_dir.mkdir(parents=True, exist_ok=True)

        t0 = time.time()
        try:
            ids, n_ids, n_dist, f_ids, f_dist = compute_cell_neighbors(bundle, k=args.k)
        except FileNotFoundError as exc:
            print(f"skip {cell_dir.name}: missing input {exc}", file=sys.stderr)
            continue
        np.save(out_dir / "ids.npy", ids)
        np.save(out_dir / "nearest_ids.npy", n_ids)
        np.save(out_dir / "nearest_distances.npy", n_dist)
        np.save(out_dir / "farthest_ids.npy", f_ids)
        np.save(out_dir / "farthest_distances.npy", f_dist)
        provenance = {
            "cell_key": cell_dir.name,
            "state_key": state_key,
            "k": args.k,
            "n": int(ids.shape[0]),
            "distance_metric": "cosine",
            "source_bundle": str(bundle.relative_to(analysis_root.parent.parent))
            if analysis_root.is_absolute() is False
            else str(bundle),
            "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        (out_dir / "provenance.json").write_text(json.dumps(provenance, indent=2) + "\n")
        n_done += 1
        print(f"  {cell_dir.name:30s}  N={ids.shape[0]}  k={args.k}  {time.time() - t0:.2f}s")

    print(f"done — {n_done} cells / {time.time() - total_start:.2f}s total")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
