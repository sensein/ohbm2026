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
from hashlib import sha256
from pathlib import Path
from typing import Any

import numpy as np

from ohbm2026.analyze.centroids import (
    assign_nearest_centroid,
    load_centroid_table,
    write_neuroscape_clusters_bundle,
)
from ohbm2026.analyze.communities import (
    DEFAULT_KNN_K,
    DEFAULT_RESOLUTION_MAX,
    DEFAULT_RESOLUTION_MIN,
    DEFAULT_RESOLUTION_POINTS,
    detect_communities,
    write_communities_bundle,
)
from ohbm2026.analyze.topic_clusters import (
    run_topic_clustering,
    write_topic_clusters_bundle,
)
from ohbm2026.analyze.topics import (
    DEFAULT_LLM_MODEL_ID,
    DEFAULT_PROMPT_VERSION,
    build_topics_artifact,
)
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
from ohbm2026.exceptions import AnalysisError


__all__ = [
    "projections_runner",
    "neuroscape_clusters_runner",
    "communities_runner",
    "topic_clusters_runner",
    "load_abstract_texts",
]


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


# ---------------------------------------------------------------------------
# neuroscape_clusters runner
# ---------------------------------------------------------------------------


def _neuroscape_algorithm_config(config: AnalysisConfig) -> dict[str, Any]:
    """The algorithm config hashed into the neuroscape_clusters cache key."""
    return {
        "centroid_table_dir": str(config.neuroscape_centroids_dir),
        "seed": config.seed,
    }


def _read_stage3_neuroscape_checkpoint_sha(
    config: AnalysisConfig, entry: PlanEntry
) -> str | None:
    """Read the `domain_model_checkpoint_sha256` from the Stage 3 neuroscape
    bundle's provenance, if recorded.

    The Stage 3 neuroscape derivation step writes the checkpoint SHA into
    the bundle's provenance so Stage 4 can refuse to assign centroids
    that were derived from a different checkpoint.
    """
    component = "title" if entry.input_source == "abstract" else entry.input_source
    bundle = (
        config.embeddings_root
        / entry.model_key
        / f"{component}__{config.corpus_state_key}"
    )
    prov_path = bundle / "provenance.json"
    if not prov_path.exists():
        return None
    try:
        data = json.loads(prov_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data.get("domain_model_checkpoint_sha256")


def neuroscape_clusters_runner(
    config: AnalysisConfig, entry: PlanEntry
) -> dict[str, Any]:
    """Assign each row of the `(neuroscape, input)` matrix to its nearest
    published NeuroScape centroid by spherical angular distance.

    Only runs for `model_key == "neuroscape"` — the published centroids
    live in the domain-embedding space, so we consume the Stage 3
    neuroscape bundle directly (no on-the-fly Stage-2 projection). If
    invoked against any other model (e.g., direct programmatic call
    bypassing build_plan), raises `AnalysisError`.

    Before assignment, compares the centroid metadata's recorded
    `domain_model_checkpoint_sha256` against the Stage 3 neuroscape
    bundle's provenance (when available) and refuses on mismatch.
    """
    if entry.model_key != "neuroscape":
        raise AnalysisError(
            f"neuroscape_clusters_runner: model_key={entry.model_key!r} is "
            f"unsupported. The published NeuroScape centroids live in the "
            f"domain-embedding space; only `model == 'neuroscape'` is valid."
        )

    ids, vectors, assembly_hash = _load_input_matrix(config, entry)

    centroid_table = load_centroid_table(config.neuroscape_centroids_dir)

    # Checkpoint-SHA gate: if the centroid metadata recorded a checkpoint
    # SHA AND the Stage 3 neuroscape bundle recorded one too, they must
    # match — otherwise the centroids were derived from a different
    # Stage-2 lens than the one that produced the input vectors.
    centroid_sha = centroid_table.domain_model_checkpoint_sha256
    stage3_sha = _read_stage3_neuroscape_checkpoint_sha(config, entry)
    if centroid_sha and stage3_sha and centroid_sha != stage3_sha:
        from ohbm2026.exceptions import CentroidTableVersionMismatch

        raise CentroidTableVersionMismatch(
            f"NeuroScape Stage-2 checkpoint mismatch: centroid metadata "
            f"recorded {centroid_sha!r}; Stage 3 neuroscape bundle "
            f"provenance recorded {stage3_sha!r}. Re-derive the centroid "
            f"table from the matching checkpoint or re-run Stage 3 with "
            f"the matching checkpoint."
        )

    # Stage 3 `neuroscape` bundles are already in the 64-dim published
    # domain-embedding space, so the vectors go straight into the
    # nearest-centroid assignment with no re-projection.
    cluster_ids, distances = assign_nearest_centroid(vectors, centroid_table)

    algorithm_config = _neuroscape_algorithm_config(config)
    cache_key_payload = {
        "input_source_assembly_hash": assembly_hash,
        "centroid_table_version": centroid_table.table_version,
        "algorithm_config": algorithm_config,
        "seed": config.seed,
    }
    cache_key = "sha256:" + sha256(
        json.dumps(cache_key_payload, sort_keys=True).encode("utf-8")
    ).hexdigest()

    bundle_dir = _bundle_output_path(config, entry)
    if "neuroscape_clusters" not in config.invalidate_kinds and _cache_hit_compatible(
        bundle_dir, cache_key
    ):
        return {
            "cache": "hit",
            "n_rows": int(ids.shape[0]),
            "n_centroids": int(centroid_table.centroids.shape[0]),
        }

    started_at = datetime.now(timezone.utc).isoformat()
    write_neuroscape_clusters_bundle(
        bundle_dir,
        ids=ids,
        cluster_ids=cluster_ids,
        distances=distances,
        centroid_table=centroid_table,
        source_model=entry.model_key,
        seed=config.seed,
    )
    completed_at = datetime.now(timezone.utc).isoformat()
    # Replace the placeholder provenance the writer used with the real one.
    write_bundle_provenance(
        bundle_dir / "provenance.json",
        {
            "schema_version": "stage4.provenance.v1",
            "stage": "analysis",
            "kind": "neuroscape_clusters",
            "bundle_path": str(
                bundle_dir.relative_to(Path.cwd())
                if bundle_dir.is_absolute()
                and Path.cwd() in bundle_dir.parents
                else bundle_dir
            ),
            "corpus_state_key": config.corpus_state_key,
            "input_source_assembly_hash": assembly_hash or _kind_state_key(config, entry),
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
        "n_centroids": int(centroid_table.centroids.shape[0]),
        "distance_mean": float(distances.mean()),
        "distance_std": float(distances.std()),
    }


# ---------------------------------------------------------------------------
# communities runner
# ---------------------------------------------------------------------------


def _communities_algorithm_config() -> dict[str, Any]:
    """The algorithm config hashed into the communities cache key."""
    return {
        "knn_k": DEFAULT_KNN_K,
        "knn_metric": "ip_normalized",
        "leiden_partition": "CPMVertexPartition",
        "resolution_min": DEFAULT_RESOLUTION_MIN,
        "resolution_max": DEFAULT_RESOLUTION_MAX,
        "resolution_points": DEFAULT_RESOLUTION_POINTS,
    }


def communities_runner(config: AnalysisConfig, entry: PlanEntry) -> dict[str, Any]:
    """Run FAISS+Leiden+CPM community detection for `(model, input)`.

    Returns `{"cache": "miss"|"hit", "n_rows": N, "n_communities": K, ...}`.

    Per FR-007 + clarification Session 2026-05-14 Q5: builds a
    cosine-IP kNN graph over L2-normalized vectors, runs Leiden CPM
    across a 20-point resolution sweep, picks the modularity plateau,
    and reorders so the largest community is `0`.
    """
    from hashlib import sha256

    ids, vectors, assembly_hash = _load_input_matrix(config, entry)

    algorithm_config = _communities_algorithm_config()
    cache_key_payload = {
        "input_source_assembly_hash": assembly_hash,
        "algorithm_config": algorithm_config,
        "seed": config.seed,
    }
    cache_key = "sha256:" + sha256(
        json.dumps(cache_key_payload, sort_keys=True).encode("utf-8")
    ).hexdigest()

    bundle_dir = _bundle_output_path(config, entry)
    if "communities" not in config.invalidate_kinds and _cache_hit_compatible(
        bundle_dir, cache_key
    ):
        return {"cache": "hit", "n_rows": int(ids.shape[0])}

    started_at = datetime.now(timezone.utc).isoformat()
    result = detect_communities(
        vectors,
        knn_k=algorithm_config["knn_k"],
        resolution_min=algorithm_config["resolution_min"],
        resolution_max=algorithm_config["resolution_max"],
        resolution_points=algorithm_config["resolution_points"],
        seed=config.seed,
    )

    # Build the per-cluster topics artifact (FR-009 hybrid pipeline).
    topics_payload: dict[int, dict[str, Any]] = {}
    if result.n_communities > 0:
        abstract_texts = load_abstract_texts(ids)
        topics_payload = build_topics_artifact(
            result.community_ids.astype(int).tolist(),
            abstract_texts,
            cache_dir=config.cache_root
            / "topics"
            / f"{entry.model_key}_{entry.input_source}",
            skip_llm=config.skip_llm_topics,
            llm_model_id=DEFAULT_LLM_MODEL_ID,
            prompt_version=DEFAULT_PROMPT_VERSION,
            llm_call=None,
        )

    write_communities_bundle(
        bundle_dir,
        ids=ids,
        result=result,
        source_model=entry.model_key,
        input_source=entry.input_source,
        seed=config.seed,
        knn_k=algorithm_config["knn_k"],
        resolution_min=algorithm_config["resolution_min"],
        resolution_max=algorithm_config["resolution_max"],
        resolution_points=algorithm_config["resolution_points"],
        topics=topics_payload or None,
    )
    completed_at = datetime.now(timezone.utc).isoformat()
    write_bundle_provenance(
        bundle_dir / "provenance.json",
        {
            "schema_version": "stage4.provenance.v1",
            "stage": "analysis",
            "kind": "communities",
            "bundle_path": str(
                bundle_dir.relative_to(Path.cwd())
                if bundle_dir.is_absolute() and Path.cwd() in bundle_dir.parents
                else bundle_dir
            ),
            "corpus_state_key": config.corpus_state_key,
            "input_source_assembly_hash": assembly_hash or _kind_state_key(config, entry),
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
        "n_communities": int(result.n_communities),
        "selected_resolution": float(result.selected_resolution),
        "largest_community_share": float(result.largest_community_share),
    }


# ---------------------------------------------------------------------------
# Corpus text loader (for topics-attachment)
# ---------------------------------------------------------------------------


def load_abstract_texts(
    abstract_ids: np.ndarray,
    *,
    corpus_path: Path = Path("data/primary/abstracts.json"),
    enriched_path: Path = Path("data/primary/abstracts_enriched.sqlite"),
) -> list[str]:
    """Load per-abstract text concatenations aligned with `abstract_ids`.

    Prefers the enriched SQLite (which has the per-section markdown);
    falls back to the raw `abstracts.json` title + claims-ish blob.
    Returns a list of strings (empty for abstracts that don't resolve).
    """
    by_id: dict[int, str] = {}

    # Try enriched SQLite first
    if enriched_path.exists():
        try:
            from ohbm2026.enrich.storage import iter_enriched

            for record in iter_enriched(enriched_path):
                aid = record.get("id")
                if not isinstance(aid, int):
                    continue
                parts = [
                    record.get("title", "") or "",
                    record.get("introduction_markdown", "") or "",
                    record.get("methods_markdown", "") or "",
                    record.get("results_markdown", "") or "",
                    record.get("conclusion_markdown", "") or "",
                ]
                by_id[aid] = " ".join(p for p in parts if p)
        except Exception:  # noqa: BLE001 — best-effort; fallback below
            pass

    # Fallback: raw corpus JSON
    if not by_id and corpus_path.exists():
        try:
            data = json.loads(corpus_path.read_text(encoding="utf-8"))
            for entry in data.get("abstracts", []):
                aid = entry.get("id")
                if not isinstance(aid, int):
                    continue
                by_id[aid] = str(entry.get("title", "") or "")
        except (OSError, json.JSONDecodeError):
            pass

    return [by_id.get(int(aid), "") for aid in abstract_ids.tolist()]


# ---------------------------------------------------------------------------
# topic_clusters runner
# ---------------------------------------------------------------------------


def _topic_clusters_algorithm_config(config: AnalysisConfig) -> dict[str, Any]:
    return {
        "umap_components": 5,
        "umap_n_neighbors": 15,
        "umap_min_dist": 0.0,
        "min_cluster_size": "auto",
        "seed": config.seed,
    }


def topic_clusters_runner(
    config: AnalysisConfig, entry: PlanEntry
) -> dict[str, Any]:
    """UMAP-reduce → HDBSCAN cluster → optional LLM-grouped topics."""
    from hashlib import sha256

    ids, vectors, assembly_hash = _load_input_matrix(config, entry)

    algorithm_config = _topic_clusters_algorithm_config(config)
    cache_key_payload = {
        "input_source_assembly_hash": assembly_hash,
        "algorithm_config": algorithm_config,
        "seed": config.seed,
        "skip_llm_topics": config.skip_llm_topics,
    }
    cache_key = "sha256:" + sha256(
        json.dumps(cache_key_payload, sort_keys=True).encode("utf-8")
    ).hexdigest()

    bundle_dir = _bundle_output_path(config, entry)
    if "topic_clusters" not in config.invalidate_kinds and _cache_hit_compatible(
        bundle_dir, cache_key
    ):
        return {"cache": "hit", "n_rows": int(ids.shape[0])}

    started_at = datetime.now(timezone.utc).isoformat()
    result = run_topic_clustering(
        vectors,
        umap_components=algorithm_config["umap_components"],
        umap_n_neighbors=algorithm_config["umap_n_neighbors"],
        umap_min_dist=algorithm_config["umap_min_dist"],
        seed=config.seed,
    )

    # Build the per-cluster topics artifact (spaCy + c-TF-IDF + optional LLM).
    topics_payload: dict[int, dict[str, Any]] = {}
    if result.n_topics > 0:
        abstract_texts = load_abstract_texts(ids)
        # Exclude HDBSCAN noise (cluster_id == -1) from the topics map.
        mask = result.topic_cluster_ids >= 0
        if mask.any():
            assignments = result.topic_cluster_ids[mask].astype(int).tolist()
            texts = [abstract_texts[i] for i, keep in enumerate(mask.tolist()) if keep]
            topics_payload = build_topics_artifact(
                assignments,
                texts,
                cache_dir=config.cache_root
                / "topics"
                / f"{entry.model_key}_{entry.input_source}",
                skip_llm=config.skip_llm_topics,
                llm_model_id=DEFAULT_LLM_MODEL_ID,
                prompt_version=DEFAULT_PROMPT_VERSION,
                llm_call=None,  # caller wires enrich.flex_tier when ready
            )

    write_topic_clusters_bundle(
        bundle_dir,
        ids=ids,
        result=result,
        source_model=entry.model_key,
        input_source=entry.input_source,
        seed=config.seed,
        topics=topics_payload or None,
    )
    completed_at = datetime.now(timezone.utc).isoformat()
    write_bundle_provenance(
        bundle_dir / "provenance.json",
        {
            "schema_version": "stage4.provenance.v1",
            "stage": "analysis",
            "kind": "topic_clusters",
            "bundle_path": str(
                bundle_dir.relative_to(Path.cwd())
                if bundle_dir.is_absolute() and Path.cwd() in bundle_dir.parents
                else bundle_dir
            ),
            "corpus_state_key": config.corpus_state_key,
            "input_source_assembly_hash": assembly_hash or _kind_state_key(config, entry),
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
        "n_topics": int(result.n_topics),
        "n_noise": int(result.n_noise),
        "min_cluster_size": int(result.min_cluster_size),
    }


# Register on import.
register_kind_runner("projections", projections_runner)
register_kind_runner("neuroscape_clusters", neuroscape_clusters_runner)
register_kind_runner("communities", communities_runner)
register_kind_runner("topic_clusters", topic_clusters_runner)
