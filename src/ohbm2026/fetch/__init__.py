"""Stage 1 — fetch + normalize OHBM 2026 abstracts from Oxford Abstracts.

Public surface re-exported here so callers can use the package-level
import path instead of dipping into submodules.
"""

from ohbm2026.fetch import schema_diff, stage

__all__ = ["schema_diff", "stage"]
