"""Stage 15 atlas package (spec ``015-neuroscape-context``).

Orchestrates the ``ohbmcli build-atlas-package`` pipeline: NeuroScape
release loader → deterministic 2D + 3D UMAP fit → OHBM 2026 projection
via ``umap.transform`` → k=20 neighbour index → palette assignment →
quadtree blue-noise LOD backdrop (progressive tiers) →
``neuroscape.parquet`` + ``atlas.parquet`` writer → provenance JSON.

Module surface is intentionally narrow at scaffold time; sub-modules
land per Phase-3 tasks (T022 onward in
``specs/015-neuroscape-context/tasks.md``).
"""

from __future__ import annotations

__all__: list[str] = []
