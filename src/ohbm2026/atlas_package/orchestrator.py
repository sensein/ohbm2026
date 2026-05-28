"""Stage 15 orchestrator — chains the build into a single callable.

Spec: ``specs/015-neuroscape-context/`` — data-model.md (state
machine) + ``contracts/cli-build-atlas-package.md`` (output paths +
provenance schema) + R-009 (typed-exception subtree).

The orchestrator is the single function the
``ohbmcli build-atlas-package`` CLI wraps. It:

1. Discovers + SHA-checks the NeuroScape v1.0.1 release inputs.
2. Loads the article + cluster tables.
3. Fits 3D and 2D UMAP solutions on the Stage-2 vectors
   (deterministic; cacheable by state key).
4. Projects every OHBM 2026 Stage-2 vector via ``umap.transform``
   into the same UMAP space — aggregating failures per R-009.
5. Builds the k=20 neighbour index over the NeuroScape Stage-2
   vectors.
6. Assigns the deterministic cluster palette.
7. Per-cluster stratified decimation of the backdrop.
8. Writes ``neuroscape.parquet`` + ``atlas.parquet`` + asserts the
   cluster-table cross-parquet invariant.
9. HEAD-checks the small fixed set of non-PubMed-record URLs.
10. Writes a single provenance JSON file alongside the parquets.

The orchestrator is testable end-to-end against the synthetic
fixture from :mod:`tests._atlas_fixtures` plus an in-memory OHBM
2026 corpus — no real network or 461K-row release required for the
unit test (T020).
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

from ohbm2026.exceptions import NeuroScapeInputError

from . import (
    cluster_palette as palette_mod,
    decimation,
    link_check as link_check_mod,
    neighbour_index,
    neuroscape_loader,
    ohbm_projector,
    parquet_writer,
    umap_fit,
)
from .provenance import normalise_path

__all__ = ["OhbmInputRecord", "AtlasBuildConfig", "build_atlas_package"]


@dataclass(frozen=True)
class OhbmInputRecord:
    """One OHBM 2026 abstract worth of input.

    The orchestrator takes the OHBM corpus as a list of these
    rather than re-reading ``voyage_stage2_published`` itself, so
    the CLI wrapper (T030) handles the source-format adapter and
    the test can drive the orchestrator with hand-built data.
    """

    submission_id: int
    poster_id: int
    title: str
    stage2_vector: np.ndarray


@dataclass(frozen=True)
class AtlasBuildConfig:
    """All configuration for a single ``build_atlas_package`` run.

    Default UMAP params (``None`` → R-001 production defaults). Tests
    override them with smaller ``n_neighbors`` so the synthetic
    fixture (≪30 articles) can fit.
    """

    neuroscape_source_root: Path
    ohbm_corpus: Sequence[OhbmInputRecord]
    ohbm2026_state_key: str
    output_root: Path
    umap_cache_root: Path
    voyage_bundle_id: str = "voyage_stage2_published"
    decimated_backdrop_size: int = 50_000
    neighbors_k: int = 20
    umap_params_3d: umap_fit.UmapFitParams | None = None
    umap_params_2d: umap_fit.UmapFitParams | None = None
    primary_palette_size: int = 32
    seed: int = 0
    skip_link_check: bool = False
    link_check_rate: float = 3.0
    code_revision: str = "unknown"
    command_line: str = "ohbmcli build-atlas-package"
    titles_index_bin: bytes = field(default=b"")
    titles_index_meta: Mapping[str, Any] = field(default_factory=dict)
    # When set, the orchestrator records this ISO-8601 UTC string in
    # the parquet manifests' `build_started_utc` AND
    # `build_finished_utc` (so the parquet contents are byte-
    # identical across rebuilds for the same input — SC-004). When
    # None the orchestrator records the wall-clock timestamps, which
    # is the production default and what operators want for audit.
    # The provenance JSON always records wall-clock timestamps
    # separately so the audit trail is complete regardless of pin.
    pinned_built_at: str | None = None
    # Spec 019 — semantic-search index step. Default False to preserve
    # existing Stage-15 test surface; the CLI defaults to True (per
    # contracts/cli-build-atlas-package.md §1) when run by operators.
    semantic_index_enabled: bool = False
    semantic_cache_root: Path | None = None
    semantic_model_id: str = "Xenova/all-MiniLM-L6-v2"


def _state_key(parts: Sequence[str]) -> str:
    h = hashlib.sha256()
    for p in parts:
        h.update(p.encode())
        h.update(b"|")
    return h.hexdigest()[:12]


def _utcnow() -> str:
    return _dt.datetime.now(tz=_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _resolved_umap_params(
    cfg: AtlasBuildConfig,
) -> tuple[umap_fit.UmapFitParams, umap_fit.UmapFitParams]:
    p3 = cfg.umap_params_3d or umap_fit.UmapFitParams(n_components=3, seed=cfg.seed)
    p2 = cfg.umap_params_2d or umap_fit.UmapFitParams(n_components=2, seed=cfg.seed)
    return p3, p2


def _repo_relative(path: Path) -> str:
    """Normalise a path to repo-relative for provenance.

    Tries to relativise against ``cwd`` first (the CLI's normal
    invocation cwd is the repo root). Falls back to the path's
    ``name`` if no relativisation is possible — this keeps the
    Principle-VIII no-absolute-paths rule even when the test runs
    under a tempdir outside the repo.
    """

    try:
        rel = path.resolve().relative_to(Path.cwd().resolve())
        return normalise_path(rel)
    except (ValueError, OSError):
        # Outside the cwd (e.g. unit tests under /var/.../tempdir);
        # use the path's name so the provenance still has SOMETHING
        # identifiable without leaking the absolute machine path.
        return normalise_path(path.name)


def build_atlas_package(cfg: AtlasBuildConfig) -> dict[str, Any]:
    """Run the Stage 15 build end-to-end. Returns the provenance dict."""

    started = _utcnow()

    # 1. Discover + SHA-check inputs.
    bundle = neuroscape_loader.discover_inputs(cfg.neuroscape_source_root)

    # 2. Load articles + clusters + Stage-2 vectors.
    articles = list(neuroscape_loader.iter_articles(bundle))
    pmids = np.array([a.pubmed_id for a in articles], dtype=np.int64)
    # Index Stage-2 vectors by pmid so we can align them to the
    # filtered articles list (the HDF5 may carry articles whose CSV
    # row was filtered out by year-range or missing-cluster guards).
    vec_by_pmid: dict[int, np.ndarray] = {}
    for pmid, vec in neuroscape_loader.iter_stage2_vectors(bundle):
        vec_by_pmid[int(pmid)] = vec
    vectors_list: list[np.ndarray] = []
    aligned_articles = []
    for a in articles:
        v = vec_by_pmid.get(a.pubmed_id)
        if v is None:
            continue
        aligned_articles.append(a)
        vectors_list.append(v)
    articles = aligned_articles
    if not vectors_list:
        raise NeuroScapeInputError(
            "No NeuroScape articles aligned with Stage-2 vectors after filtering",
            file=str(cfg.neuroscape_source_root),
            expected="at least one aligned (article, vector) pair",
            actual="0",
        )
    vectors = np.stack(vectors_list, axis=0).astype(np.float32, copy=False)
    pmids = np.array([a.pubmed_id for a in articles], dtype=np.int64)
    clusters = neuroscape_loader.load_clusters(bundle)

    # 3. UMAP fits — 3D and 2D, independent. Both pass through the
    # on-disk cache so a rebuild with unchanged vectors + params is
    # transform-only (R-007 / SC-005 — "second invocation byte-
    # identical and <60s").
    p3, p2 = _resolved_umap_params(cfg)
    fit3d = umap_fit.fit(vectors, p3, cache_root=cfg.umap_cache_root)
    fit2d = umap_fit.fit(vectors, p2, cache_root=cfg.umap_cache_root)
    # State key is derived from the 3D fit (the canonical orientation
    # for the rotatable scatter). The 2D fit's key would diverge by
    # design — we just want one stable identifier for the produced
    # UMAP solution.
    umap_state_key = fit3d.state_key

    # 4. OHBM 2026 projection.
    oos = [(rec.submission_id, rec.stage2_vector) for rec in cfg.ohbm_corpus]
    projection = ohbm_projector.project(oos, fit3d)
    # We need 2D OHBM coords too — re-transform via the 2D fit on
    # the SAME valid submission ids so the rows align with the 3D
    # output. Failed ids are the same set.
    if projection.submission_ids:
        sid_to_vec = {rec.submission_id: rec.stage2_vector for rec in cfg.ohbm_corpus}
        valid_batch = np.stack(
            [sid_to_vec[s] for s in projection.submission_ids], axis=0
        ).astype(np.float32, copy=False)
        ohbm_2d = np.asarray(fit2d.model.transform(valid_batch), dtype=np.float32)
    else:
        ohbm_2d = np.empty((0, 2), dtype=np.float32)

    # 5. Neighbour index.
    knn = neighbour_index.build_knn(pmids, vectors, k=cfg.neighbors_k)

    # 6. Palette.
    from collections import Counter
    cluster_counts: dict[int, int] = dict(Counter(a.cluster_id for a in articles))
    palette = palette_mod.assign_palette(cluster_counts, primary_size=cfg.primary_palette_size)

    # 7. Decimation.
    cluster_id_arr = np.array([a.cluster_id for a in articles], dtype=np.int16)
    decimated_indices = decimation.stratified_sample(
        cluster_id_arr, target_size=cfg.decimated_backdrop_size, seed=cfg.seed
    )

    # 8. Per-OHBM-record nearest-cluster assignment (in UMAP space).
    # For each projected OHBM record, find the nearest backdrop point
    # in UMAP 3D space and inherit its cluster id. Squared euclidean
    # is sufficient (we only need argmin); chunked along the OHBM
    # axis to bound peak memory at production scale (~3K OHBM × 461K
    # NeuroScape → 1.4G float-pair scratch if materialised
    # in one go).
    nearest_cluster: dict[int, int] = {}
    if projection.submission_ids:
        embedded_3d = fit3d.embedded
        ohbm_3d_coords = projection.coordinates
        chunk = 256
        for start in range(0, ohbm_3d_coords.shape[0], chunk):
            stop = min(start + chunk, ohbm_3d_coords.shape[0])
            diffs = ohbm_3d_coords[start:stop, None, :] - embedded_3d[None, :, :]
            sq = (diffs * diffs).sum(axis=2)
            nearest_idx = np.argmin(sq, axis=1)
            for offset, idx in enumerate(nearest_idx.tolist()):
                nearest_cluster[projection.submission_ids[start + offset]] = articles[idx].cluster_id

    # 9. Compose state keys.
    neuroscape_state_key = _state_key(
        [
            bundle.articles_csv_sha256,
            bundle.clusters_csv_sha256,
            bundle.hdf5_shard_manifest_sha256,
            bundle.model_checkpoint_sha256,
            umap_state_key,
        ]
    )
    atlas_state_key = _state_key(
        [cfg.ohbm2026_state_key, neuroscape_state_key, umap_state_key]
    )

    # 10. Write parquets.
    out_root = Path(cfg.output_root)
    out_root.mkdir(parents=True, exist_ok=True)
    neuroscape_path = out_root / "neuroscape.parquet"
    atlas_path = out_root / "atlas.parquet"
    vectors_path = out_root / "neuroscape_vectors.parquet"

    # Use the pinned timestamp (test path) OR wall clock (production)
    # in the parquet manifests so byte-identity holds across rebuilds
    # when the caller pins.
    manifest_started = cfg.pinned_built_at or started
    manifest_finished = cfg.pinned_built_at or _utcnow()

    # Spec 019 — semantic-index step (optional; default-off in the
    # AtlasBuildConfig dataclass so existing Stage-15 tests are
    # unaffected). When enabled, computes corpus MiniLM vectors,
    # cluster centroids, and emits neuroscape_vectors.parquet
    # alongside neuroscape.parquet. The semantic_index_provenance
    # block is folded into the final provenance JSON below (T022).
    semantic_index_provenance: dict[str, Any] | None = None
    cluster_centroids: dict[int, np.ndarray] = {}
    if cfg.semantic_index_enabled:
        from . import semantic_index, vectors_compute

        sk = vectors_compute.compute_state_key(
            article_set_hash=neuroscape_state_key,
            model_id=cfg.semantic_model_id,
        )
        cache_root = cfg.semantic_cache_root or (Path("data") / "cache" / "atlas-vectors")
        vectors_result = vectors_compute.compute_cluster_vectors(
            article_titles=[a.title for a in articles],
            pubmed_ids=[a.pubmed_id for a in articles],
            cluster_ids=[a.cluster_id for a in articles],
            state_key=sk,
            cache_root=cache_root,
            model_id=cfg.semantic_model_id,
        )
        # Compute cluster centroids from dequantised INT8 vectors so
        # the float32 centroids in neuroscape.parquet are derivable
        # from the bytes in neuroscape_vectors.parquet (INV-001 +
        # data-model.md §1 build-side invariant).
        for cv in vectors_result.clusters:
            deq = cv.vectors_int8.astype(np.float32) / max(vectors_result.scale, 1e-12)
            mean = deq.mean(axis=0)
            n = float(np.linalg.norm(mean))
            cluster_centroids[cv.cluster_id] = (mean / (n if n != 0.0 else 1.0)).astype(np.float32)
        # Flatten the per-cluster vectors back to a single corpus-wide
        # arrangement for the semantic-index parquet writer.
        all_cluster_ids = np.concatenate(
            [np.full(cv.pubmed_ids.shape[0], cv.cluster_id, dtype=np.int16) for cv in vectors_result.clusters]
        )
        all_pubmed_ids = np.concatenate([cv.pubmed_ids for cv in vectors_result.clusters])
        all_vectors = np.concatenate([cv.vectors_int8 for cv in vectors_result.clusters], axis=0)
        vectors_manifest = {
            "schema_version": "semantic_vectors.v1",
            "corpus": "neuroscape",
            "state_key": sk,
            "parent_state_key": neuroscape_state_key,
            "code_revision": cfg.code_revision,
            "command_line": cfg.command_line,
            "seed": cfg.seed,
            "model_id": cfg.semantic_model_id,
            "model_sha256": vectors_result.model_sha256,
            "vector_dim": vectors_compute.VECTOR_DIM,
            "quantization": "int8-global-scale",
            "scale": vectors_result.scale,
            "max_abs_original": vectors_result.max_abs_original,
            "n_vectors": int(all_pubmed_ids.shape[0]),
            "cluster_count": len(vectors_result.clusters),
            "row_group_size": semantic_index.ROW_GROUP_SIZE,
            "build_started_utc": manifest_started,
            "build_finished_utc": manifest_finished,
        }
        semantic_index.write_neuroscape_vectors_parquet(
            out_path=vectors_path,
            cluster_ids=all_cluster_ids,
            pubmed_ids=all_pubmed_ids,
            vectors=all_vectors,
            expected_pubmed_id_set=[a.pubmed_id for a in articles],
            manifest=vectors_manifest,
        )
        semantic_index_provenance = {
            "enabled": True,
            "state_key": sk,
            "model_id": cfg.semantic_model_id,
            "model_sha256": vectors_result.model_sha256,
            "vector_dim": vectors_compute.VECTOR_DIM,
            "quantization": "int8-global-scale",
            "scale": vectors_result.scale,
            "max_abs_original": vectors_result.max_abs_original,
            "n_neuroscape_vectors": int(all_pubmed_ids.shape[0]),
            "n_ohbm_vectors": 0,  # populated when US4 lands
            "cluster_count": len(vectors_result.clusters),
            "cache_hits": vectors_result.cache_hits,
            "cache_misses": vectors_result.cache_misses,
        }

    neuroscape_build_info = {
        "state_key": neuroscape_state_key,
        "code_revision": cfg.code_revision,
        "command_line": cfg.command_line,
        "seed": cfg.seed,
        "umap_state_key": umap_state_key,
        "centroid_table_version": None,  # filled by T029 follow-up with the centroid table sha
        "voyage_bundle_id": None,  # neuroscape parquet doesn't ship voyage info
        "build_started_utc": manifest_started,
        "build_finished_utc": manifest_finished,
    }
    titles_meta = dict(cfg.titles_index_meta)
    titles_meta.setdefault("schema_version", "search.neuroscape_titles.v1")
    titles_meta.setdefault("n_documents", len(articles))
    titles_meta.setdefault("field_set", ["title"])

    parquet_writer.write_neuroscape_parquet(
        out_path=neuroscape_path,
        build_info=neuroscape_build_info,
        articles=articles,
        clusters=clusters,
        cluster_counts=cluster_counts,
        palette=palette,
        embedded_3d=fit3d.embedded,
        embedded_2d=fit2d.embedded,
        knn=knn,
        titles_index_bin=cfg.titles_index_bin,
        titles_index_meta=titles_meta,
        cluster_centroids=cluster_centroids if cluster_centroids else None,
    )

    atlas_build_info = {
        "state_key": atlas_state_key,
        "code_revision": cfg.code_revision,
        "command_line": cfg.command_line,
        "seed": cfg.seed,
        "umap_state_key": umap_state_key,
        "voyage_bundle_id": cfg.voyage_bundle_id,
        "build_started_utc": manifest_started,
        "build_finished_utc": manifest_finished,
    }
    poster_ids = {rec.submission_id: rec.poster_id for rec in cfg.ohbm_corpus}
    titles = {rec.submission_id: rec.title for rec in cfg.ohbm_corpus}

    parquet_writer.write_atlas_parquet(
        out_path=atlas_path,
        build_info=atlas_build_info,
        sibling_state_keys={
            "ohbm2026": cfg.ohbm2026_state_key,
            "neuroscape": neuroscape_state_key,
        },
        articles=articles,
        clusters=clusters,
        cluster_counts=cluster_counts,
        palette=palette,
        embedded_3d=fit3d.embedded,
        embedded_2d=fit2d.embedded,
        decimated_indices=decimated_indices,
        ohbm_overlay=projection,
        ohbm_overlay_2d=ohbm_2d,
        ohbm_poster_ids=poster_ids,
        ohbm_titles=titles,
        ohbm_nearest_cluster=nearest_cluster,
    )

    # 11. Cross-parquet invariant.
    parquet_writer.assert_cluster_tables_match(neuroscape_path, atlas_path)

    # 12. Link check.
    link_report: dict[str, Any]
    if cfg.skip_link_check:
        link_report = {
            "scope": "skipped (skip_link_check=True)",
            "checked_urls": [],
            "n_total": 0,
            "n_2xx": 0,
            "n_3xx": 0,
            "n_4xx": 0,
            "n_5xx": 0,
            "deploy_blocking_failures": [],
        }
    else:
        link_report = link_check_mod.run_link_check(
            rate_per_second=cfg.link_check_rate
        )
        link_check_mod.raise_if_failed(link_report)

    # 13. Provenance.
    n_omitted = len(projection.failed_submission_ids)
    finished = _utcnow()
    provenance = {
        "schema_version": "neuroscape_context_provenance.v1",
        "state_key": atlas_state_key,
        "code_revision": cfg.code_revision,
        "command_line": cfg.command_line,
        "seed": cfg.seed,
        "started_utc": started,
        "finished_utc": finished,
        "inputs": {
            "neuroscape_source_root": _repo_relative(Path(cfg.neuroscape_source_root)),
            "voyage_bundle_id": cfg.voyage_bundle_id,
            "articles_csv_sha256": bundle.articles_csv_sha256,
            "clusters_csv_sha256": bundle.clusters_csv_sha256,
            "domain_model_checkpoint_sha256": bundle.model_checkpoint_sha256,
            "hdf5_shard_manifest_sha256": bundle.hdf5_shard_manifest_sha256,
            "hdf5_shard_count": len(bundle.hdf5_shards),
        },
        "umap_params": {
            "seed": cfg.seed,
            "n_neighbors": p3.n_neighbors,
            "min_dist": p3.min_dist,
            "metric": p3.metric,
            "init": p3.init,
            "n_components_3d": p3.n_components,
            "n_components_2d": p2.n_components,
        },
        "ohbm_inclusion": {
            "n_overlay_points": len(projection.submission_ids),
            "n_omitted": n_omitted,
            "omitted_submission_ids": list(projection.failed_submission_ids),
        },
        "outputs": {
            "neuroscape_parquet": _repo_relative(neuroscape_path),
            "atlas_parquet": _repo_relative(atlas_path),
            "neuroscape_state_key": neuroscape_state_key,
            "atlas_state_key": atlas_state_key,
            "ohbm2026_state_key": cfg.ohbm2026_state_key,
        },
        "link_check": link_report,
        # Spec 019 — semantic-index provenance. Populated only when
        # cfg.semantic_index_enabled is True; absent (None) means the
        # builder ran with --no-semantic-index and no vectors parquet
        # was written.
        "semantic_index": semantic_index_provenance,
    }
    return provenance
