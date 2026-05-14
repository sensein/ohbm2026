"""Stage 3 storage layer — atomic bundle + per-abstract cache I/O.

The Stage 3 bundle format is documented in
`specs/005-embeddings-matrix/contracts/bundle.schema.json`:

    <bundle_dir>/
    ├── vectors.npy
    ├── ids.npy
    ├── metadata.json
    └── provenance.json

The per-abstract cache entry shape is in
`specs/005-embeddings-matrix/contracts/cache-entry.schema.json`:

    <cache_root>/<model_key>/<cache_key>.json

All writes are atomic (temp + os.replace) so a SIGTERM mid-write
never leaves partial files visible.
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any, Iterable

import numpy as np

from ohbm2026.exceptions import EmbeddingContractError

__all__ = [
    "CACHE_VERSION",
    "BUNDLE_SCHEMA_VERSION",
    "atomic_write_bytes",
    "atomic_write_json",
    "write_cache_entry",
    "load_cache_entry",
    "cache_path_for",
    "write_bundle",
    "load_bundle",
    "bundle_corpus_state_key",
]


CACHE_VERSION = "embed.matrix.v1"
BUNDLE_SCHEMA_VERSION = "stage3.bundle.v1"


# ---------- Atomic write helpers ---------------------------------------


def atomic_write_bytes(path: Path, data: bytes) -> None:
    """Write `data` to `path` atomically (temp + rename in the same dir).

    The temp file lives in the destination's parent directory so the
    rename is a same-filesystem operation and is therefore atomic on
    POSIX. The parent is created if missing.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # NamedTemporaryFile creates the file with delete=False so we can
    # rename it; we manage cleanup ourselves on failure.
    fd, tmp_path = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        os.replace(tmp_path, path)
    except BaseException:
        # Clean up on any failure including KeyboardInterrupt.
        try:
            os.unlink(tmp_path)
        except FileNotFoundError:
            pass
        raise


def atomic_write_json(path: Path, payload: Any) -> None:
    """Serialize `payload` as compact JSON and write atomically."""
    atomic_write_bytes(
        path,
        json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8") + b"\n",
    )


# ---------- Per-abstract cache I/O -------------------------------------


def cache_path_for(cache_root: Path, model_key: str, cache_key: str) -> Path:
    """Return the on-disk path for one cache entry.

    `cache_key` is the sha256-hex string the orchestrator computed
    over (input_text || model_id || model_version).
    """
    return Path(cache_root) / model_key / f"{cache_key}.json"


def write_cache_entry(
    cache_root: Path,
    *,
    model_key: str,
    cache_key: str,
    payload: dict,
) -> Path:
    """Persist one cache entry atomically.

    Returns the resulting path. The caller is responsible for the
    payload's schema (see `contracts/cache-entry.schema.json`).
    """
    path = cache_path_for(cache_root, model_key, cache_key)
    atomic_write_json(path, payload)
    return path


def load_cache_entry(cache_root: Path, model_key: str, cache_key: str) -> dict | None:
    """Return the cached entry's payload, or None on cache miss."""
    path = cache_path_for(cache_root, model_key, cache_key)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise EmbeddingContractError(
            f"corrupted cache entry at {path}: {exc}"
        ) from exc


# ---------- Bundle I/O --------------------------------------------------


def _bundle_paths(bundle_dir: Path) -> dict[str, Path]:
    bundle_dir = Path(bundle_dir)
    return {
        "vectors": bundle_dir / "vectors.npy",
        "ids": bundle_dir / "ids.npy",
        "metadata": bundle_dir / "metadata.json",
        "provenance": bundle_dir / "provenance.json",
    }


def write_bundle(
    bundle_dir: Path,
    *,
    ids: Iterable[int],
    vectors: np.ndarray,
    metadata: dict,
    provenance: dict | None = None,
) -> Path:
    """Write a Stage 3 bundle atomically.

    The strategy is "stage the whole bundle in a sibling temp
    directory, then rename it into place". This makes the entire
    bundle (4 files) atomic from the consumer's perspective — a
    half-written bundle is never visible.

    On success the bundle directory contains:
    - `vectors.npy`  (float32, shape == (len(ids), dim))
    - `ids.npy`      (int64, shape == (len(ids),))
    - `metadata.json`
    - `provenance.json` (optional; written only if `provenance` given)

    Raises `EmbeddingContractError` if vectors / ids / metadata
    disagree on row count.
    """
    bundle_dir = Path(bundle_dir)
    ids_array = np.asarray(list(ids), dtype=np.int64)
    vectors_array = np.ascontiguousarray(vectors, dtype=np.float32)
    if vectors_array.ndim != 2:
        raise EmbeddingContractError(
            f"vectors must be 2-D, got shape {vectors_array.shape}"
        )
    if vectors_array.shape[0] != ids_array.shape[0]:
        raise EmbeddingContractError(
            f"vectors / ids row-count mismatch: "
            f"{vectors_array.shape[0]} vs {ids_array.shape[0]}"
        )
    if metadata.get("present_count") not in (None, vectors_array.shape[0]):
        raise EmbeddingContractError(
            f"metadata.present_count={metadata['present_count']} disagrees with "
            f"vectors row count {vectors_array.shape[0]}"
        )
    if "ids" in metadata and list(metadata["ids"]) != ids_array.tolist():
        raise EmbeddingContractError(
            "metadata.ids does not match ids.npy element-wise"
        )

    metadata = dict(metadata)
    metadata.setdefault("schema_version", BUNDLE_SCHEMA_VERSION)
    metadata["present_count"] = vectors_array.shape[0]
    metadata["dim"] = vectors_array.shape[1]
    metadata["dtype"] = "float32"
    metadata["ids"] = ids_array.tolist()

    parent = bundle_dir.parent
    parent.mkdir(parents=True, exist_ok=True)
    tmp_dir = Path(tempfile.mkdtemp(prefix=bundle_dir.name + ".", suffix=".tmp", dir=parent))
    try:
        np.save(tmp_dir / "vectors.npy", vectors_array, allow_pickle=False)
        np.save(tmp_dir / "ids.npy", ids_array, allow_pickle=False)
        atomic_write_json(tmp_dir / "metadata.json", metadata)
        if provenance is not None:
            atomic_write_json(tmp_dir / "provenance.json", provenance)
        if bundle_dir.exists():
            # Move the prior bundle aside before renaming the new one in.
            # The caller (orchestrator) is expected to have already
            # validated `corpus_state_key` compatibility — write_bundle
            # itself does not enforce that policy.
            backup = bundle_dir.with_name(bundle_dir.name + ".prev")
            if backup.exists():
                shutil.rmtree(backup)
            os.rename(bundle_dir, backup)
        os.rename(tmp_dir, bundle_dir)
    except BaseException:
        # Cleanup the temp stage on any failure.
        if tmp_dir.exists():
            shutil.rmtree(tmp_dir, ignore_errors=True)
        raise

    return bundle_dir


def load_bundle(bundle_dir: Path) -> dict:
    """Read a bundle from disk.

    Returns:
        {"ids": np.ndarray[int64], "vectors": np.ndarray[float32],
         "metadata": dict, "provenance": dict | None}

    Raises FileNotFoundError if the bundle dir is missing.
    Raises EmbeddingContractError if files disagree on row count.
    """
    paths = _bundle_paths(bundle_dir)
    if not paths["vectors"].exists():
        raise FileNotFoundError(paths["vectors"])
    vectors = np.load(paths["vectors"], allow_pickle=False)
    ids = np.load(paths["ids"], allow_pickle=False)
    metadata = json.loads(paths["metadata"].read_text(encoding="utf-8"))
    provenance = None
    if paths["provenance"].exists():
        provenance = json.loads(paths["provenance"].read_text(encoding="utf-8"))
    if vectors.shape[0] != ids.shape[0]:
        raise EmbeddingContractError(
            f"vectors / ids row-count mismatch on disk at {bundle_dir}: "
            f"{vectors.shape[0]} vs {ids.shape[0]}"
        )
    return {"ids": ids, "vectors": vectors, "metadata": metadata, "provenance": provenance}


def bundle_corpus_state_key(bundle_dir: Path) -> str | None:
    """Read the `corpus_state_key` from an existing bundle's metadata,
    or return None if the bundle does not exist / lacks the key."""
    metadata_path = Path(bundle_dir) / "metadata.json"
    if not metadata_path.exists():
        return None
    try:
        meta = json.loads(metadata_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    return meta.get("corpus_state_key")
