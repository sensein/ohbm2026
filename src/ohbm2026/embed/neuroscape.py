"""Stage 3 NeuroScape Stage-2 model surface.

Canonical Stage 3 import path for the NeuroScape Stage-2 transformer
(model architecture, checkpoint loader, applier, training entry-
points, and the bundle helpers Stage 3 needs).

The function bodies live in `ohbm2026.analyze` (the renamed
`neuroscape.py` — analysis tools, clustering, UMAP, projection
comparison live there as well). Stage 3 callers should always import
from this façade so the embed/ package presents a self-contained
public surface.
"""

from __future__ import annotations

from ohbm2026.analyze import (
    PUBLISHED_STAGE2_HIDDEN_DIMENSIONS,
    PUBLISHED_STAGE2_OUTPUT_DIMENSION,
    apply_stage2_model,
    build_stage2_network,
    choose_torch_device,
    load_pretrained_stage2_model,
    load_stage1_bundle,
    write_embedding_bundle,
)

__all__ = [
    "PUBLISHED_STAGE2_HIDDEN_DIMENSIONS",
    "PUBLISHED_STAGE2_OUTPUT_DIMENSION",
    "apply_stage2_model",
    "build_stage2_network",
    "choose_torch_device",
    "load_pretrained_stage2_model",
    "load_stage1_bundle",
    "write_embedding_bundle",
]
