"""Deterministic colour assignment for NeuroScape clusters.

Spec: ``specs/015-neuroscape-context/`` — FR-010 + research R-003.

175 NeuroScape clusters cannot be uniquely coloured without
sacrificing distinguishability. The strategy is two-tier:

- the top ``primary_size`` clusters (by descending ``point_count``) get
  distinct colours from a perceptually-uniform qualitative palette;
- the remaining clusters cycle a documented secondary palette in
  ``cluster_id`` order so colours stay stable across rebuilds even
  when point counts tie.

The output is deterministic (input → output is a pure function), so
both ``neuroscape.parquet`` and ``atlas.parquet`` can persist the
palette and the parquet writer can assert row-for-row equality
between them.
"""

from __future__ import annotations

from typing import Mapping

__all__ = ["assign_palette", "PRIMARY_PALETTE", "SECONDARY_PALETTE"]


# 32-slot perceptually-uniform qualitative palette. Mix of:
# - matplotlib's `tab20` (the first 20 entries below, in `tab20` order);
# - 12 additional hues chosen for distinguishability from the `tab20`
#   set (no two adjacent hex codes share more than 16 R/G/B units).
# Colours are stable; reordering this list changes published colours
# and bumps both parquet state-keys.
PRIMARY_PALETTE: tuple[str, ...] = (
    "#1f77b4",
    "#aec7e8",
    "#ff7f0e",
    "#ffbb78",
    "#2ca02c",
    "#98df8a",
    "#d62728",
    "#ff9896",
    "#9467bd",
    "#c5b0d5",
    "#8c564b",
    "#c49c94",
    "#e377c2",
    "#f7b6d2",
    "#7f7f7f",
    "#c7c7c7",
    "#bcbd22",
    "#dbdb8d",
    "#17becf",
    "#9edae5",
    "#393b79",
    "#637939",
    "#8c6d31",
    "#843c39",
    "#7b4173",
    "#5254a3",
    "#8ca252",
    "#bd9e39",
    "#ad494a",
    "#a55194",
    "#9c9ede",
    "#cedb9c",
)


# 24-slot secondary palette: muted greys + low-saturation hues. Used
# for clusters past the top-N; visitors see them as a backdrop the
# top-N stand out from. Cycled in `cluster_id` order so the cycle is
# stable across rebuilds.
SECONDARY_PALETTE: tuple[str, ...] = (
    "#9c9c9c",
    "#a8b5c2",
    "#bca58f",
    "#a8bca0",
    "#bca8a8",
    "#a0a8bc",
    "#b5a8a0",
    "#a8a0bc",
    "#909a9c",
    "#b09a90",
    "#90a8b0",
    "#9c9080",
    "#80909c",
    "#90a09c",
    "#a09080",
    "#a8a0a8",
    "#909c80",
    "#80a098",
    "#988090",
    "#a09098",
    "#888888",
    "#a3a3a3",
    "#b8b8b8",
    "#959595",
)


def assign_palette(
    cluster_counts: Mapping[int, int],
    *,
    primary_size: int,
) -> dict[int, tuple[str, str]]:
    """Return ``{cluster_id: (colour_hex, palette_tier)}``.

    Parameters
    ----------
    cluster_counts:
        Mapping ``cluster_id -> point_count`` derived from
        ``neuroscape.parquet/articles``.
    primary_size:
        Maximum number of clusters to assign primary-palette colours
        to. The top ``primary_size`` clusters by descending
        ``point_count`` get primary slots in rank order; the rest get
        secondary slots in ``cluster_id`` order. Capped at the number
        of clusters available.

    Returns
    -------
    dict[int, tuple[str, str]]
        Deterministic mapping from cluster id to
        ``(colour_hex, palette_tier)`` where ``palette_tier`` is
        ``"primary"`` or ``"secondary"``.

    Notes
    -----
    The function is pure: identical input produces byte-identical
    output across runs. This is what lets ``parquet_writer`` persist
    the palette into two separate parquets and assert row-for-row
    equality between them.
    """

    if not cluster_counts:
        return {}

    capped_primary = min(primary_size, len(cluster_counts))

    # Rank by (-count, cluster_id) so ties break on the lower id —
    # stable across rebuilds and easy to reason about.
    ranked = sorted(
        cluster_counts.items(),
        key=lambda kv: (-kv[1], kv[0]),
    )

    out: dict[int, tuple[str, str]] = {}

    primary_ids = [cid for cid, _ in ranked[:capped_primary]]
    for slot, cid in enumerate(primary_ids):
        colour = PRIMARY_PALETTE[slot % len(PRIMARY_PALETTE)]
        out[cid] = (colour, "primary")

    # Secondary tier: clusters NOT in the primary set, in cluster_id
    # order (NOT in `ranked` order). The secondary palette cycles
    # modulo its length when there are more secondary clusters than
    # palette slots.
    secondary_ids = sorted(set(cluster_counts) - set(primary_ids))
    for slot, cid in enumerate(secondary_ids):
        colour = SECONDARY_PALETTE[slot % len(SECONDARY_PALETTE)]
        out[cid] = (colour, "secondary")

    return out
