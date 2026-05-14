"""Per-kind runner registrations.

This module is imported for its side-effect of populating
`KIND_RUNNERS` in `ohbm2026.analyze.stage`. Each runner:
  1. Reads the Stage 3 input vectors for `(model, input_source)` via
     `embed.compose.compose_recipe` (for the `abstract` recipe) or
     the per-component bundle.
  2. Runs the analysis-specific computation.
  3. Writes the per-kind bundle via the matching writer.
  4. Returns a dict with at least `{"cache": "miss"|"hit", ...stats}`.

Runners that aren't yet registered fall through to a
`runner_not_registered` skip event in the orchestrator (stage.py).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

from ohbm2026.analyze.provenance import write_bundle_provenance
from ohbm2026.analyze.stage import (
    AnalysisConfig,
    PlanEntry,
    _bundle_output_path,
    _kind_state_key,
    register_kind_runner,
)
from ohbm2026.analyze.umap import (
    DEFAULT_UMAP_METRIC,
    DEFAULT_UMAP_MIN_DIST,
    DEFAULT_UMAP_N_NEIGHBORS,
    DEFAULT_UMAP_RANDOM_STATE,
    fit_parametric_mlp,
    fit_umap_2d,
    fit_umap_3d,
    write_projections_bundle,
)


__all__ = ["projections_runner"]


# ---------------------------------------------------------------------------
# Input loading
# ---------------------------------------------------------------------------


def _load_input_matrix(
    config: AnalysisConfig, entry: PlanEntry
) -> tuple[np.ndarray, np.ndarray, str]:
    """Load the `(ids, vectors, input_source_assembly_hash)` for the entry.

    For `input_source == "abstract"`, compose the manuscript recipe via
    `embed.compose.compose_recipe`. For other components, read the
    per-component bundle directly.
    """
    if entry.input_source == "abstract":
        from ohbm2026.embed.compose import compose_recipe

        result = compose_recipe(
            ["title", "introduction", "methods", "results", "conclusion"],
            model_key=entry.model_key,
            bundles_root=config.embeddings_root,
            corpus_state_key=config.corpus_state_key,
        )
        return (
            np.asarray(result.ids, dtype=np.int64),
            np.asarray(result.vectors, dtype=np.float32),
            getattr(result, "assembly_hash", "") or "",
        )

    bundle_path = (
        config.embeddings_root
        / entry.model_key
        / f"{entry.input_source}__{config.corpus_state_key}"
    )
    ids = np.load(bundle_path / "ids.npy")
    vectors = np.load(bundle_path / "vectors.npy")
    # Best-effort: hash the bundle's metadata.json for traceability.
    meta_path = bundle_path / "metadata.json"
    if meta_path.exists():
        from hashlib import sha256

        assembly_hash = sha256(meta_path.read_bytes()).hexdigest()[:16]
    else:
        assembly_hash = ""
    return ids, vectors, assembly_hash


# ---------------------------------------------------------------------------
# Cache key
# ---------------------------------------------------------------------------


def _projections_algorithm_config(config: AnalysisConfig) -> dict[str, Any]:
    """The algorithm config hashed into the projections cache key."""
    return {
        "n_neighbors": DEFAULT_UMAP_N_NEIGHBORS,
        "min_dist": DEFAULT_UMAP_MIN_DIST,
        "metric": DEFAULT_UMAP_METRIC,
        "random_state": config.seed,
    }


def _cache_hit_compatible(bundle_dir: Path, cache_key: str) -> bool:
    """Return True if the bundle's recorded cache_key matches."""
    prov_path = bundle_dir / "provenance.json"
    if not prov_path.exists():
        return False
    try:
        data = json.loads(prov_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return data.get("cache_key") == cache_key


# ---------------------------------------------------------------------------
# projections runner
# ---------------------------------------------------------------------------


def projections_runner(config: AnalysisConfig, entry: PlanEntry) -> dict[str, Any]:
    """Fit a 2D + 3D UMAP for `(model, input)` and write the bundle.

    Returns `{"cache": "miss"|"hit", "n_rows": N, ...}`.
    """
    from hashlib import sha256

    ids, vectors, assembly_hash = _load_input_matrix(config, entry)

    algorithm_config = _projections_algorithm_config(config)
    cache_key_payload = {
        "input_source_assembly_hash": assembly_hash,
        "algorithm_config": algorithm_config,
        "seed": config.seed,
    }
    cache_key = "sha256:" + sha256(
        json.dumps(cache_key_payload, sort_keys=True).encode("utf-8")
    ).hexdigest()

    bundle_dir = _bundle_output_path(config, entry)
    if "projections" not in config.invalidate_kinds and _cache_hit_compatible(
        bundle_dir, cache_key
    ):
        return {"cache": "hit", "n_rows": int(ids.shape[0])}

    coords2d, model2d = fit_umap_2d(
        vectors,
        n_neighbors=algorithm_config["n_neighbors"],
        min_dist=algorithm_config["min_dist"],
        metric=algorithm_config["metric"],
        random_state=algorithm_config["random_state"],
    )
    coords3d, model3d = fit_umap_3d(
        vectors,
        n_neighbors=algorithm_config["n_neighbors"],
        min_dist=algorithm_config["min_dist"],
        metric=algorithm_config["metric"],
        random_state=algorithm_config["random_state"],
    )
    mlp2d = fit_parametric_mlp(vectors, coords2d, seed=config.seed)
    mlp3d = fit_parametric_mlp(vectors, coords3d, seed=config.seed)

    started_at = datetime.now(timezone.utc).isoformat()
    write_projections_bundle(
        bundle_dir,
        ids=ids,
        reference_matrix=vectors,
        coords2d=coords2d,
        coords3d=coords3d,
        model2d=model2d,
        model3d=model3d,
        mlp2d=mlp2d,
        mlp3d=mlp3d,
        hyperparameters=algorithm_config,
        metadata_extra={
            "model_key": entry.model_key,
            "input_source": entry.input_source,
            "seed": config.seed,
        },
    )
    # Provenance lands as a sibling file in the bundle dir; write it
    # after the atomic-rename so it's a separate atomic write.
    completed_at = datetime.now(timezone.utc).isoformat()
    state_key = _kind_state_key(config, entry)
    write_bundle_provenance(
        bundle_dir / "provenance.json",
        {
            "schema_version": "stage4.provenance.v1",
            "stage": "analysis",
            "kind": "projections",
            "bundle_path": str(
                bundle_dir.relative_to(Path.cwd())
                if bundle_dir.is_absolute()
                and Path.cwd() in bundle_dir.parents
                else bundle_dir
            ),
            "corpus_state_key": config.corpus_state_key,
            "input_source_assembly_hash": assembly_hash or state_key,
            "algorithm_config_canonical_json": json.dumps(
                algorithm_config, sort_keys=True
            ),
            "cache_key": cache_key,
            "code_revision": config.code_revision,
            "command": config.command_line,
            "seed": config.seed,
            "started_at": started_at,
            "completed_at": completed_at,
        },
    )
    return {
        "cache": "miss",
        "n_rows": int(ids.shape[0]),
        "vector_dim": int(vectors.shape[1]),
    }


# Register on import.
register_kind_runner("projections", projections_runner)
