"""Stage 15 UMAP fit — deterministic 2D + 3D projection of NeuroScape Stage-2 vectors.

Spec: ``specs/015-neuroscape-context/`` — research R-001 + R-009.

The Stage-15 pipeline fits **two independent** UMAP solutions on the
same set of NeuroScape Stage-2 vectors: one with ``n_components=3``
for the rotatable scatter and one with ``n_components=2`` for the
flat scatter (US2). The 2D solution is *not* a projection of the 3D
solution — UMAP's locality structure does not survive dimensional
truncation cleanly, so we pay for an extra full fit.

The fit is required to be deterministic for the byte-identity
invariants:

- SC-004 — second-run rebuild matches the first run byte-for-byte.
- Tests `test_atlas_umap_fit.FitDeterminismTests` enforce
  ``np.array_equal`` across two consecutive fits with the same input
  + params + seed.

UMAP's underlying ``pynndescent`` graph build has stochastic
elements; we lean on:

- ``random_state=seed`` set on the ``UMAP`` constructor so all
  internal RNGs receive the same seed;
- ``n_jobs=1`` so the optimisation is single-threaded (multi-thread
  ordering of float reductions is the most common source of UMAP
  non-determinism);
- ``transform_seed=seed`` so the ``transform`` step used by the OHBM
  projector (T024) is deterministic for the same OOS input.

Public surface:

- :class:`UmapFitParams` — frozen param record matching the R-001
  defaults (``n_neighbors=30``, ``min_dist=0.10``, ``metric='cosine'``,
  ``init='spectral'``, ``seed=0``).
- :func:`compute_state_key` — pure-function
  ``sha256(vectors_bytes || params_json)[:12]``; used by the
  orchestrator's UMAP fit cache.
- :func:`fit` — runs the fit, returns a :class:`UmapFitResult`
  carrying the fitted model handle, the embedded array, and the
  state key.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from ohbm2026.exceptions import UmapCacheError, UmapFitError

__all__ = [
    "UmapFitParams",
    "UmapFitResult",
    "compute_state_key",
    "fit",
    "cache_paths",
]

# Cache layout under ``<cache_root>/<state_key>/``:
#   - model.joblib    fitted ``umap.UMAP`` instance (includes the
#                     internal nearest-neighbour graph + numba-baked
#                     transform state).
#   - embedded.npy    the (N, n_components) float32 projection.
#   - params.json     forensic; lets a human inspect what produced
#                     this entry without loading the joblib.
#
# A cache entry is "complete" only when all three files exist. A
# partial directory (e.g. a crashed write) raises
# ``UmapCacheError`` rather than silently re-fitting — so operators
# notice + clean up rather than paying the 30-60 min fit cost twice.
_CACHE_MODEL_FILE = "model.joblib"
_CACHE_EMBEDDED_FILE = "embedded.npy"
_CACHE_PARAMS_FILE = "params.json"


@dataclass(frozen=True)
class UmapFitParams:
    """Frozen UMAP fit parameters. Defaults match spec 015 R-001."""

    n_components: int
    n_neighbors: int = 30
    min_dist: float = 0.10
    metric: str = "cosine"
    seed: int = 0
    init: str = "spectral"

    def as_dict(self) -> dict[str, Any]:
        return {
            "n_components": self.n_components,
            "n_neighbors": self.n_neighbors,
            "min_dist": self.min_dist,
            "metric": self.metric,
            "seed": self.seed,
            "init": self.init,
        }


@dataclass(frozen=True)
class UmapFitResult:
    """Output of :func:`fit`.

    ``embedded`` is the (N, n_components) float32 projection. ``model``
    is the fitted ``umap.UMAP`` instance — the OHBM projector
    (:mod:`ohbm2026.atlas_package.ohbm_projector`, T024) uses
    ``model.transform`` to land out-of-sample vectors in the same
    space without re-fitting.
    """

    params: UmapFitParams
    state_key: str
    embedded: np.ndarray
    model: Any  # umap.UMAP — typed as Any so callers don't need to import umap.


def compute_state_key(vectors: np.ndarray, params: UmapFitParams) -> str:
    """Return ``sha256(vectors_bytes || params_json)[:12]``.

    The cache key feeds the orchestrator's UMAP fit cache at
    ``data/cache/atlas-umap/<state-key>/``. Identical inputs always
    produce the identical 12-hex key.
    """

    h = hashlib.sha256()
    contiguous = np.ascontiguousarray(vectors.astype(np.float32, copy=False))
    h.update(contiguous.tobytes())
    h.update(json.dumps(params.as_dict(), sort_keys=True).encode())
    return h.hexdigest()[:12]


def _validate_input(vectors: np.ndarray) -> None:
    """Reject non-finite / wrong-shape / empty input loudly per R-009."""

    if vectors.ndim != 2:
        raise UmapFitError(
            f"UMAP input must be a 2-D matrix; got shape {vectors.shape!r}",
            reason="wrong_shape",
            n_vectors=int(vectors.shape[0]) if vectors.ndim > 0 else 0,
        )
    if vectors.shape[0] == 0:
        raise UmapFitError(
            "UMAP input is empty",
            reason="empty_input",
            n_vectors=0,
        )
    n = int(vectors.shape[0])
    if np.isnan(vectors).any():
        raise UmapFitError(
            "UMAP input contains NaN",
            reason="nan_input",
            n_vectors=n,
        )
    if not np.isfinite(vectors).all():
        raise UmapFitError(
            "UMAP input contains non-finite values (inf)",
            reason="nonfinite_input",
            n_vectors=n,
        )


def cache_paths(cache_root: Path, state_key: str) -> dict[str, Path]:
    """Return the absolute paths inside a single cache entry.

    Exposed so callers (tests, future invalidation tooling) can locate
    a cache entry by state key without re-deriving the filenames.
    """

    base = Path(cache_root) / state_key
    return {
        "dir": base,
        "model": base / _CACHE_MODEL_FILE,
        "embedded": base / _CACHE_EMBEDDED_FILE,
        "params": base / _CACHE_PARAMS_FILE,
    }


def _load_cached(
    entry: dict[str, Path],
    params: UmapFitParams,
) -> tuple[Any, np.ndarray]:
    """Load a fully-formed cache entry. Raises ``UmapCacheError`` on any
    inconsistency rather than silently falling back to a refit — the
    operator should notice + delete the bad entry.
    """

    # Lazy import — joblib is in the umap-learn dep tree, but we don't
    # want a stray import at module load.
    import joblib  # type: ignore[import-untyped]

    missing = [name for name in ("model", "embedded") if not entry[name].exists()]
    if missing:
        raise UmapCacheError(
            f"UMAP fit cache entry at {entry['dir']!s} is incomplete "
            f"(missing: {', '.join(missing)})",
            path=str(entry["dir"]),
            reason="incomplete_entry",
        )

    try:
        model = joblib.load(entry["model"])
    except Exception as exc:
        raise UmapCacheError(
            f"UMAP cached model at {entry['model']!s} is unreadable: {exc}",
            path=str(entry["model"]),
            reason="model_unreadable",
        ) from exc

    try:
        # ``allow_pickle=False`` is numpy's default since 1.16.3
        # (CVE-2019-6446); set it explicitly to document that
        # embedded.npy is plain float data and to harden against any
        # future numpy default flip — a tampered cache entry that
        # smuggled a pickled object would otherwise execute arbitrary
        # code at load time.
        embedded = np.load(entry["embedded"], allow_pickle=False)
    except Exception as exc:
        raise UmapCacheError(
            f"UMAP cached embedded array at {entry['embedded']!s} is unreadable: {exc}",
            path=str(entry["embedded"]),
            reason="embedded_unreadable",
        ) from exc

    if embedded.ndim != 2 or embedded.shape[1] != params.n_components:
        raise UmapCacheError(
            f"UMAP cached embedded shape {embedded.shape!r} does not match "
            f"n_components={params.n_components}",
            path=str(entry["embedded"]),
            reason="embedded_shape_mismatch",
        )

    embedded = np.asarray(embedded, dtype=np.float32)
    return model, embedded


def _persist_cache(
    entry: dict[str, Path],
    model: Any,
    embedded: np.ndarray,
    params: UmapFitParams,
    state_key: str,
) -> None:
    """Persist a fresh cache entry atomically.

    Writes each file to a sibling tempfile then ``os.replace``s it
    into place so an interrupted run never leaves a half-written
    file claiming to be a valid entry.
    """

    import joblib  # type: ignore[import-untyped]

    entry["dir"].mkdir(parents=True, exist_ok=True)

    def _atomic_write_bytes(target: Path, payload: bytes) -> None:
        # Close the raw fd immediately and use Path.write_bytes for the
        # actual write. Wrapping the fd via os.fdopen would leak it if
        # the wrapper itself raised before taking ownership (rare under
        # memory pressure but real); the explicit close-then-write
        # pattern has no such window.
        fd, tmp_path = tempfile.mkstemp(
            prefix=f".{target.name}.", suffix=".tmp", dir=str(entry["dir"])
        )
        os.close(fd)
        try:
            Path(tmp_path).write_bytes(payload)
            os.replace(tmp_path, target)
        except Exception:
            Path(tmp_path).unlink(missing_ok=True)
            raise

    fd, tmp_model = tempfile.mkstemp(
        prefix=f".{_CACHE_MODEL_FILE}.", suffix=".tmp", dir=str(entry["dir"])
    )
    os.close(fd)
    try:
        joblib.dump(model, tmp_model)
        os.replace(tmp_model, entry["model"])
    except Exception:
        Path(tmp_model).unlink(missing_ok=True)
        raise

    # ``np.save`` appends ``.npy`` to any path that lacks the
    # extension and writes to *that* derived name, leaving the
    # mkstemp-allocated file empty. Force the suffix so the file we
    # then ``os.replace`` is the one np.save actually populated.
    np_buf = embedded.astype(np.float32, copy=False)
    fd, tmp_emb = tempfile.mkstemp(
        prefix=f".{_CACHE_EMBEDDED_FILE}.", suffix=".npy", dir=str(entry["dir"])
    )
    os.close(fd)
    try:
        np.save(tmp_emb, np_buf, allow_pickle=False)
        os.replace(tmp_emb, entry["embedded"])
    except Exception:
        Path(tmp_emb).unlink(missing_ok=True)
        raise

    params_payload = json.dumps(
        {"state_key": state_key, **params.as_dict()}, sort_keys=True
    ).encode()
    _atomic_write_bytes(entry["params"], params_payload)


def fit(
    vectors: np.ndarray,
    params: UmapFitParams,
    cache_root: Path | None = None,
) -> UmapFitResult:
    """Fit a UMAP projection. Deterministic for the same input + params.

    The returned :class:`UmapFitResult` carries the fitted model
    handle so callers (the OHBM projector in particular) can
    ``transform`` out-of-sample vectors into the same space.

    When ``cache_root`` is provided, a cache lookup at
    ``<cache_root>/<state_key>/`` is performed first. On a complete
    hit the cached model + embedded array are returned unchanged
    (much faster than re-fitting on 461k vectors). On a miss the
    fresh fit is persisted into the same path so a subsequent run
    with the same inputs short-circuits.
    """

    _validate_input(vectors)

    # Lazy import keeps ``ohbm2026.atlas_package`` lightweight; umap is
    # only needed inside fit/transform paths.
    import umap  # type: ignore[import-untyped]

    state_key = compute_state_key(vectors, params)

    if cache_root is not None:
        entry = cache_paths(cache_root, state_key)
        # An entry is a hit only if BOTH critical files exist. An
        # entry with only one or the other is treated as corrupt
        # (raised loudly via _load_cached) so operators clean it up.
        if entry["model"].exists() or entry["embedded"].exists():
            model_cached, embedded_cached = _load_cached(entry, params)
            return UmapFitResult(
                params=params,
                state_key=state_key,
                embedded=embedded_cached,
                model=model_cached,
            )

    model = umap.UMAP(
        n_components=params.n_components,
        n_neighbors=params.n_neighbors,
        min_dist=params.min_dist,
        metric=params.metric,
        init=params.init,
        random_state=params.seed,
        transform_seed=params.seed,
        n_jobs=1,
    )
    try:
        embedded = model.fit_transform(vectors.astype(np.float32, copy=False))
    except Exception as exc:  # umap raises a variety of errors
        raise UmapFitError(
            f"UMAP fit failed: {exc}",
            reason="fit_failed",
            n_vectors=int(vectors.shape[0]),
        ) from exc
    embedded = np.asarray(embedded, dtype=np.float32)

    if cache_root is not None:
        entry = cache_paths(cache_root, state_key)
        _persist_cache(entry, model, embedded, params, state_key)

    return UmapFitResult(
        params=params,
        state_key=state_key,
        embedded=embedded,
        model=model,
    )
