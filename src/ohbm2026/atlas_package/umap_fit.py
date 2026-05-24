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
from dataclasses import dataclass
from typing import Any

import numpy as np

from ohbm2026.exceptions import UmapFitError

__all__ = [
    "UmapFitParams",
    "UmapFitResult",
    "compute_state_key",
    "fit",
]


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


def fit(vectors: np.ndarray, params: UmapFitParams) -> UmapFitResult:
    """Fit a UMAP projection. Deterministic for the same input + params.

    The returned :class:`UmapFitResult` carries the fitted model
    handle so callers (the OHBM projector in particular) can
    ``transform`` out-of-sample vectors into the same space.
    """

    _validate_input(vectors)

    # Lazy import keeps ``ohbm2026.atlas_package`` lightweight; umap is
    # only needed inside fit/transform paths.
    import umap  # type: ignore[import-untyped]

    state_key = compute_state_key(vectors, params)
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
    return UmapFitResult(
        params=params,
        state_key=state_key,
        embedded=embedded,
        model=model,
    )
