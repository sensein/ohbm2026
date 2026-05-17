"""Stage 4 NeuroScape centroid cluster assignment (US3).

Reads the **precomputed** centroid file at
`data/inputs/neuroscape/centroids__<table_version>.npy` (paired with
`cluster_table.csv` for labels and `centroid_metadata.json` for the
runtime-discoverable source hashes), and assigns each Stage 3
`neuroscape` embedding to the nearest published centroid by **spherical
angular distance** on the unit hypersphere.

Per spec FR-008 + clarifications (Session 2026-05-14 + 2026-05-15):
- Centroids use the published NeuroScape polar `mean_angle` recipe
  (`convert_to_polar → mean_angle → convert_to_cartesian`); the result
  is unit-norm.
- Distances are `arccos(clip(v · μ, -1, 1))` ∈ [0, π].
- The centroid table version, source CSV hashes, HDF5 shard manifest
  hash, discovered cluster ids/count, and `domain_model_checkpoint_sha256`
  are **discovered at runtime** from `centroid_metadata.json`
  (Principle VII); a missing or version-mismatched table raises a typed
  error, not a silent fallback.
- This analysis kind only runs for `model_key == "neuroscape"` — the
  published centroids live in the domain-embedding space, so the runner
  consumes the Stage 3 neuroscape bundle directly. The orchestrator
  auto-skips every other model.
"""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any

import numpy as np

from ohbm2026.exceptions import (
    AnalysisError,
    CentroidTableMissing,
    CentroidTableVersionMismatch,
)


__all__ = [
    "STAGE2_DIM",
    "CentroidTable",
    "spherical_mean",
    "discover_centroid_table_path",
    "load_centroid_table",
    "assign_nearest_centroid",
    "write_neuroscape_clusters_bundle",
]


STAGE2_DIM = 64


# ---------------------------------------------------------------------------
# Spherical mean
# ---------------------------------------------------------------------------


def _convert_to_polar(x: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Cartesian → polar (matches NeuroScape's hypersphere.convert_to_polar).

    Returns `(phi, radius)` where `phi` is `(n, d-1)` and `radius` is `(n,)`.
    """
    n, d = x.shape
    phi = np.zeros((n, d - 1), dtype=np.float64)
    squares = x.astype(np.float64) ** 2
    radius = np.sqrt(squares.sum(axis=1))
    for i in range(d - 1):
        phi[:, i] = np.arctan2(
            np.sqrt(squares[:, i + 1 :].sum(axis=1)), x[:, i]
        )
    return phi, radius


def _convert_to_cartesian(phi: np.ndarray) -> np.ndarray:
    """Polar → cartesian on the unit hypersphere (matches NeuroScape)."""
    n, d_minus_1 = phi.shape
    x = np.zeros((n, d_minus_1 + 1), dtype=np.float64)
    sines = np.sin(phi)
    cosines = np.cos(phi)
    x[:, 0] = cosines[:, 0]
    x[:, -1] = np.prod(sines, axis=1)
    for i in range(1, d_minus_1):
        x[:, i] = cosines[:, i] * np.prod(sines[:, :i], axis=1)
    return x


def _mean_angle(phi: np.ndarray) -> np.ndarray:
    """Wrapped circular mean per coordinate (matches NeuroScape)."""
    return np.angle(np.mean(np.exp(1j * phi), axis=0)).__abs__()


def spherical_mean(vectors: np.ndarray, *, eps: float = 1e-12) -> np.ndarray:
    """Mean direction on the unit hypersphere (NeuroScape polar recipe).

    Per FR-008 + NeuroScape's published `get_centroids` from
    `src/utils/hypersphere.py`: convert each input vector to polar,
    take per-coordinate `mean_angle = |angle(mean(exp(i·phi)))|`,
    convert back to cartesian on the unit hypersphere. Output is
    unit-norm by construction.

    Raises `ValueError` if `vectors` is empty.
    """
    if vectors.size == 0 or vectors.shape[0] == 0:
        raise ValueError("spherical_mean: input is empty")
    arr = np.asarray(vectors, dtype=np.float64)
    phi, _radius = _convert_to_polar(arr)
    mean_phi = _mean_angle(phi).reshape(1, -1)
    centroid = _convert_to_cartesian(mean_phi)[0]
    norm = float(np.linalg.norm(centroid))
    if norm < eps:
        raise AnalysisError(
            "spherical_mean: input vectors cancel out; cannot compute mean direction"
        )
    return (centroid / norm).astype(np.float32)


# ---------------------------------------------------------------------------
# Centroid table loader
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CentroidTable:
    """The precomputed NeuroScape centroid sidecar."""

    matrix_path: Path
    sidecar_path: Path
    table_version: str
    cluster_ids: np.ndarray  # int32, shape (n_centroids,)
    centroids: np.ndarray  # float32, shape (n_centroids, STAGE2_DIM)
    labels: dict[int, dict[str, Any]]  # cluster_id -> {Title, Description, Keywords, Size, ...}
    # Runtime-discovered metadata (FR-008 + clarification Session 2026-05-15 Q5).
    # `None` means the centroid file was produced by an older derivation
    # that did not emit `centroid_metadata.json` — older centroids still
    # load but the SHA-gate falls back to a permissive check.
    domain_model_checkpoint_sha256: str | None = None
    source_csv_sha256s: dict[str, str] | None = None  # {filename: sha256}
    hdf5_shard_manifest_sha256: str | None = None
    metadata_path: Path | None = None


def discover_centroid_table_path(neuroscape_dir: Path) -> Path:
    """Find the latest `centroids__*.npy` under `neuroscape_dir`.

    Raises `CentroidTableMissing` if no matching file exists.
    """
    neuroscape_dir = Path(neuroscape_dir)
    if not neuroscape_dir.exists():
        raise CentroidTableMissing(
            f"NeuroScape centroid directory does not exist: {neuroscape_dir}. "
            f"Run scripts/derive_neuroscape_centroids.py to produce the centroid file."
        )
    candidates = sorted(neuroscape_dir.glob("centroids__*.npy"))
    if not candidates:
        raise CentroidTableMissing(
            f"No centroids__*.npy under {neuroscape_dir}. "
            f"Run scripts/derive_neuroscape_centroids.py to produce one."
        )
    # If multiple, take the lexicographically last one (operator should
    # keep only the version they want active).
    return candidates[-1]


def _parse_keywords_field(raw: str) -> list[str]:
    """Decode the Keywords column of cluster_table.csv (JSON-encoded list)."""
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return [raw]
    if isinstance(parsed, list):
        return [str(x) for x in parsed]
    return [str(parsed)]


def load_centroid_table(neuroscape_dir: Path) -> CentroidTable:
    """Load `centroids__<version>.npy` + `cluster_table.csv` into a CentroidTable.

    Per Principle VII, the version is discovered at runtime from the
    sidecar; mismatches between the npy filename and the sidecar's
    `centroid_table_version` column raise `CentroidTableVersionMismatch`.
    """
    neuroscape_dir = Path(neuroscape_dir)
    matrix_path = discover_centroid_table_path(neuroscape_dir)
    sidecar_path = neuroscape_dir / "cluster_table.csv"
    if not sidecar_path.exists():
        raise CentroidTableMissing(
            f"cluster_table.csv not found at {sidecar_path}. The centroid sidecar must "
            f"accompany centroids__*.npy."
        )

    # Version recorded in the matrix filename (e.g.,
    # centroids__ns2632-v1.npy -> "ns2632-v1").
    filename_version = matrix_path.stem.split("__", 1)[1]

    # Discover Cluster ID rows + labels + sidecar's recorded version.
    cluster_ids_raw: list[int] = []
    labels: dict[int, dict[str, Any]] = {}
    sidecar_versions: set[str] = set()
    with sidecar_path.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            cid_raw = row.get("Cluster ID") or row.get("cluster_id")
            if cid_raw in (None, ""):
                continue
            try:
                cid = int(cid_raw)
            except ValueError:
                continue
            cluster_ids_raw.append(cid)
            labels[cid] = {
                "Title": row.get("Title", "") or "",
                "Description": row.get("Description", "") or "",
                "Keywords": _parse_keywords_field(row.get("Keywords", "") or ""),
                "Focus": row.get("Focus", "") or "",
            }
            v = row.get("centroid_table_version") or row.get("table_version")
            if v:
                sidecar_versions.add(v.strip())

    if sidecar_versions and filename_version not in sidecar_versions:
        raise CentroidTableVersionMismatch(
            f"centroid matrix filename version {filename_version!r} does not match "
            f"sidecar versions {sorted(sidecar_versions)}. Re-derive the centroid file."
        )

    centroids = np.load(matrix_path).astype(np.float32)
    if centroids.ndim != 2 or centroids.shape[1] != STAGE2_DIM:
        raise AnalysisError(
            f"centroid matrix has unexpected shape {centroids.shape}; expected (n, {STAGE2_DIM})"
        )
    if centroids.shape[0] != len(cluster_ids_raw):
        raise AnalysisError(
            f"centroid matrix has {centroids.shape[0]} rows but cluster_table.csv lists "
            f"{len(cluster_ids_raw)} cluster ids"
        )
    cluster_ids = np.asarray(cluster_ids_raw, dtype=np.int32)

    # Verify centroids are unit-norm (tolerate small float drift).
    norms = np.linalg.norm(centroids, axis=1)
    if not np.allclose(norms, 1.0, atol=1e-4):
        raise AnalysisError(
            f"centroids are not unit-norm: norm range "
            f"[{float(norms.min()):.4f}, {float(norms.max()):.4f}]"
        )

    # Runtime-discoverable metadata sidecar (FR-008 + CA-007). Loaded
    # opportunistically — older centroid files without metadata still
    # work but the checkpoint-SHA gate falls back to permissive.
    metadata_path = neuroscape_dir / "centroid_metadata.json"
    checkpoint_sha: str | None = None
    csv_shas: dict[str, str] | None = None
    h5_manifest_sha: str | None = None
    if metadata_path.exists():
        try:
            meta = json.loads(metadata_path.read_text(encoding="utf-8"))
            checkpoint_sha = meta.get("domain_model_checkpoint_sha256")
            csv_shas = meta.get("source_csv_sha256s")
            h5_manifest_sha = meta.get("hdf5_shard_manifest_sha256")
            recorded_version = meta.get("centroid_table_version")
            if recorded_version and recorded_version != filename_version:
                raise CentroidTableVersionMismatch(
                    f"centroid_metadata.json records version "
                    f"{recorded_version!r}; centroid filename records "
                    f"{filename_version!r}. Re-derive the centroid table."
                )
        except json.JSONDecodeError as e:
            raise AnalysisError(
                f"centroid_metadata.json is not valid JSON: {metadata_path}: {e}"
            ) from e

    return CentroidTable(
        matrix_path=matrix_path,
        sidecar_path=sidecar_path,
        table_version=filename_version,
        cluster_ids=cluster_ids,
        centroids=centroids,
        labels=labels,
        domain_model_checkpoint_sha256=checkpoint_sha,
        source_csv_sha256s=csv_shas,
        hdf5_shard_manifest_sha256=h5_manifest_sha,
        metadata_path=metadata_path if metadata_path.exists() else None,
    )


# ---------------------------------------------------------------------------
# Nearest-centroid assignment
# ---------------------------------------------------------------------------


def _l2_normalize(matrix: np.ndarray, *, eps: float = 1e-12) -> np.ndarray:
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms = np.where(norms < eps, 1.0, norms)
    return (matrix / norms).astype(np.float32, copy=False)


def assign_nearest_centroid(
    vectors: np.ndarray,
    centroid_table: CentroidTable,
) -> tuple[np.ndarray, np.ndarray]:
    """Assign each row of `vectors` to the nearest centroid by spherical
    angular distance.

    Returns `(cluster_ids, angular_distances)`:
    - `cluster_ids` — int32, shape `(n,)`; the `Cluster ID` from
      `cluster_table.csv` of the nearest centroid.
    - `angular_distances` — float32, shape `(n,)`; `arccos(clip(v · μ, -1, 1))`
      ∈ [0, π] (cosine of 1 → distance 0; antipodal → π).
    """
    if vectors.shape[1] != centroid_table.centroids.shape[1]:
        raise AnalysisError(
            f"assign_nearest_centroid: input dim {vectors.shape[1]} != centroid dim "
            f"{centroid_table.centroids.shape[1]}"
        )
    unit_in = _l2_normalize(np.asarray(vectors, dtype=np.float32))
    unit_centroids = _l2_normalize(centroid_table.centroids)
    sims = unit_in @ unit_centroids.T  # (n, n_centroids), cosine on the sphere
    # Numerical clip: dot products of unit vectors may slightly exceed [-1, 1].
    sims_clipped = np.clip(sims, -1.0, 1.0)
    nearest_indices = np.argmax(sims, axis=1)
    angular_distances = np.arccos(
        sims_clipped[np.arange(sims.shape[0]), nearest_indices]
    ).astype(np.float32)
    cluster_ids = centroid_table.cluster_ids[nearest_indices].astype(np.int32)
    return cluster_ids, angular_distances


# ---------------------------------------------------------------------------
# Bundle writer
# ---------------------------------------------------------------------------


def write_neuroscape_clusters_bundle(
    bundle_dir: Path,
    *,
    ids: np.ndarray,
    cluster_ids: np.ndarray,
    distances: np.ndarray,
    centroid_table: CentroidTable,
    source_model: str,
    seed: int = 42,
    metadata_extra: dict[str, Any] | None = None,
) -> Path:
    """Write a `neuroscape_clusters` bundle.

    The bundle does NOT ship a `topics.json` — labels join from
    `cluster_table.csv` via the rollup writer.
    """
    from ohbm2026.analyze.storage import write_analysis_bundle

    if ids.shape[0] != cluster_ids.shape[0] or ids.shape[0] != distances.shape[0]:
        raise ValueError(
            "ids / cluster_ids / distances must align on the leading axis"
        )

    payload = {
        "neuroscape_cluster_ids": cluster_ids.astype(np.int32, copy=False),
        "neuroscape_cluster_distances": distances.astype(np.float32, copy=False),
    }
    metadata = {
        "kind": "neuroscape_clusters",
        "source_model": source_model,
        "centroid_table_version": centroid_table.table_version,
        "centroid_table_path": str(centroid_table.matrix_path),
        "domain_model_checkpoint_sha256": centroid_table.domain_model_checkpoint_sha256,
        "n_centroids": int(centroid_table.centroids.shape[0]),
        "n_rows": int(ids.shape[0]),
        "vector_dim": STAGE2_DIM,
        "seed": int(seed),
        "distance_mean": float(distances.mean()) if distances.size else 0.0,
        "distance_std": float(distances.std()) if distances.size else 0.0,
        "distance_percentile_10": (
            float(np.percentile(distances, 10)) if distances.size else 0.0
        ),
        "distance_percentile_90": (
            float(np.percentile(distances, 90)) if distances.size else 0.0
        ),
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
            "kind": "neuroscape_clusters",
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
    )
