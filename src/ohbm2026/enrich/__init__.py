"""Stage 2 — enrich the accepted corpus with figures, claims, references.

Public surface re-exported here so callers can use the package-level
import path instead of dipping into submodules.
"""

from ohbm2026.enrich import (
    claims,
    figures,
    flex_tier,
    image_quality,
    references,
    stage,
    storage,
)

__all__ = [
    "claims",
    "figures",
    "flex_tier",
    "image_quality",
    "references",
    "stage",
    "storage",
]
