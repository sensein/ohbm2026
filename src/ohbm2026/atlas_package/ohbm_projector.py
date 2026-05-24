"""Project OHBM 2026 Stage-2 vectors into the NeuroScape UMAP space.

Spec: ``specs/015-neuroscape-context/`` — research R-002 + R-009.

The Stage-15 orchestrator fits UMAP once on the NeuroScape corpus
(:func:`ohbm2026.atlas_package.umap_fit.fit`), then lands the ~3K
OHBM 2026 abstracts into the same coordinate frame via this module.
We **never** re-fit UMAP on the OHBM 2026 vectors alone (R-002): a
union-fit would shift the NeuroScape points across rebuilds, and a
NN-copy fallback would stack OHBM points on top of NeuroScape ones
rather than placing them. ``umap.transform`` is the documented OOS
projection path; both corpora come from the same Stage-2 embedding
distribution so they are in-distribution.

Failure aggregation (R-009)
---------------------------

A single bad OHBM record (NaN vector, mis-shaped vector) MUST NOT
abort the pass mid-stream — the orchestrator collects every failing
submission id and re-raises ONCE at the end via :func:`raise_if_failed`.
This matches the resumability promise: a partial OHBM 2026 corpus is
better than no corpus, and the operator can re-run after fixing the
offending records.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import numpy as np

from ohbm2026.exceptions import OhbmProjectionError

from .umap_fit import UmapFitResult

__all__ = [
    "ProjectionResult",
    "project",
    "raise_if_failed",
]


@dataclass(frozen=True)
class ProjectionResult:
    """Per-pass result of :func:`project`.

    ``coordinates[i]`` corresponds to ``submission_ids[i]``. Records
    that failed to project (NaN / inf / wrong-shape vector) are not
    in ``submission_ids`` — their ids appear in
    ``failed_submission_ids`` so the orchestrator can record them in
    provenance + decide whether to raise via :func:`raise_if_failed`.
    """

    n_components: int
    submission_ids: tuple[int, ...]
    coordinates: np.ndarray  # shape (len(submission_ids), n_components)
    failed_submission_ids: tuple[int, ...]


def project(
    oos: Iterable[tuple[int, np.ndarray]],
    fitted: UmapFitResult,
) -> ProjectionResult:
    """Project OHBM 2026 (submission_id, stage2_vector) pairs.

    Caller passes any iterable of pairs. The function partitions into
    "valid" and "failed" buckets, calls ``fitted.model.transform`` on
    the valid bucket in one batch, and returns a
    :class:`ProjectionResult`.

    The expected vector dim is read from the fitted UMAP — typically
    64 for the NeuroScape Stage-2 embedding.
    """

    n_components = fitted.params.n_components
    # The fitted UMAP records its training-input shape; the OHBM
    # vectors must match that dim.
    expected_dim = int(getattr(fitted.model, "_raw_data", np.empty((0, 0))).shape[1])
    if expected_dim == 0:
        # Fallback for older umap-learn versions that don't expose
        # `_raw_data` — fall back to the standard NeuroScape Stage-2
        # dim (64) so we still reject mis-shaped inputs.
        expected_dim = 64

    valid_ids: list[int] = []
    valid_vectors: list[np.ndarray] = []
    failed_ids: list[int] = []

    for sub_id, vec in oos:
        if not isinstance(vec, np.ndarray) or vec.ndim != 1 or vec.shape[0] != expected_dim:
            failed_ids.append(int(sub_id))
            continue
        if not np.isfinite(vec).all():
            failed_ids.append(int(sub_id))
            continue
        valid_ids.append(int(sub_id))
        valid_vectors.append(vec.astype(np.float32, copy=False))

    if valid_vectors:
        batch = np.stack(valid_vectors, axis=0).astype(np.float32, copy=False)
        try:
            embedded = np.asarray(
                fitted.model.transform(batch), dtype=np.float32
            )
        except Exception as exc:  # pragma: no cover — defensive net
            # umap.transform should not raise for in-distribution
            # inputs; if it does, surface as an aggregate failure of
            # every valid id (so the orchestrator records them).
            raise OhbmProjectionError(
                f"umap.transform failed in the OHBM batch: {exc}",
                failed_submission_ids=list(valid_ids) + failed_ids,
            ) from exc
    else:
        embedded = np.empty((0, n_components), dtype=np.float32)

    return ProjectionResult(
        n_components=n_components,
        submission_ids=tuple(valid_ids),
        coordinates=embedded,
        failed_submission_ids=tuple(failed_ids),
    )


def raise_if_failed(result: ProjectionResult) -> None:
    """Raise :class:`OhbmProjectionError` if any record failed.

    Called at the END of the orchestrator's projection pass per R-009.
    A no-op when the projection is clean — keeps the orchestrator
    code linear (``raise_if_failed(project(...))`` is the canonical
    pattern).
    """

    if not result.failed_submission_ids:
        return
    n = len(result.failed_submission_ids)
    raise OhbmProjectionError(
        f"{n} OHBM 2026 abstract(s) failed to project into the NeuroScape UMAP space",
        failed_submission_ids=list(result.failed_submission_ids),
    )
