"""Stage 4 typed exception hierarchy — re-export surface.

The class definitions live in `ohbm2026.exceptions` next to the other
per-stage error hierarchies (`Stage1Error`, `Stage2Error`, `Stage3Error`)
so the project-wide import surface stays uniform. This module
re-exports them so Stage 4 callers can `from ohbm2026.analyze.errors
import AnalysisError` instead of reaching into `exceptions`.
"""

from __future__ import annotations

from ohbm2026.exceptions import (
    AnalysisError,
    CentroidTableMissing,
    CentroidTableVersionMismatch,
    CommunityResolutionDegenerate,
    InputBundleMissing,
    ProjectionDimensionMismatch,
    TopicGroupingHallucination,
    UnsupportedProjectionAlgorithm,
)

__all__ = [
    "AnalysisError",
    "CentroidTableMissing",
    "CentroidTableVersionMismatch",
    "CommunityResolutionDegenerate",
    "InputBundleMissing",
    "ProjectionDimensionMismatch",
    "TopicGroupingHallucination",
    "UnsupportedProjectionAlgorithm",
]
