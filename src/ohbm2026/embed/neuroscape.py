"""Stage 3 NeuroScape Stage-2 model surface.

Thin façade that exposes the NeuroScape Stage-2 model loader,
applier, and constants under the canonical Stage 3 package path.
The function bodies still live in `ohbm2026.neuroscape` for now
(historical: the legacy CLI subcommands continue to import from
there) — extracting them physically is a follow-up cleanup, but
new Stage 3 callers should import from this façade so the
Stage 3 surface is self-contained.
"""

from __future__ import annotations

from ohbm2026.neuroscape import (
    PUBLISHED_STAGE2_HIDDEN_DIMENSIONS,
    PUBLISHED_STAGE2_OUTPUT_DIMENSION,
    apply_stage2_model,
    build_stage2_network,
    choose_torch_device,
    load_pretrained_stage2_model,
)

__all__ = [
    "PUBLISHED_STAGE2_HIDDEN_DIMENSIONS",
    "PUBLISHED_STAGE2_OUTPUT_DIMENSION",
    "apply_stage2_model",
    "build_stage2_network",
    "choose_torch_device",
    "load_pretrained_stage2_model",
]
