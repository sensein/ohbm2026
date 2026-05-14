"""Stage 4 analysis & annotation package.

The flat `analyze.py` module was split into per-concern submodules:

- `analyze.storage` — I/O helpers, bundle readers/writers, text-shaping
  utilities, and `write_analysis_bundle` for Stage 4's per-kind output.
- `analyze.clusters` — cluster benchmark + semantic analysis +
  Stage-2 community detection surface (the existing sklearn-based
  pipeline that the cluster_benchmark and semantic_analysis CLIs use).
- `analyze.projections` — UMAP + t-SNE legacy projection / HTML viz
  surface, including the projection-comparison CLI.
- `analyze.errors` — typed `AnalysisError` hierarchy (re-exported from
  `ohbm2026.exceptions`).
- `analyze.provenance` — Stage 4 path-safe provenance writers.

This `__init__.py` re-exports the legacy public surface so existing
downstream callers (ui.py, poster_layout.py, category_evaluation.py,
scripts/, tests/) continue to work without import-path rewrites.
New callers SHOULD import from the submodule that owns the function.
"""

from __future__ import annotations

# ---- storage ----------------------------------------------------------------
from ohbm2026.analyze.storage import (
    ALLOWED_EMBEDDING_FIELDS,
    DEFAULT_EMBEDDING_FIELDS,
    DEFAULT_HF_MODEL,
    DEFAULT_MINILM_MODEL,
    DEFAULT_VOYAGE_MODEL,
    HUGGINGFACE_TOKEN_ENV_VARS,
    NeuroScapeError,
    SECTION_HEADINGS,
    SECTION_MARKDOWN_KEYS,
    build_claim_embedding_text,
    build_distinct_color_map,
    build_embedding_output_name,
    build_embedding_text,
    build_embedding_texts,
    build_embedding_visualization_title,
    build_visualization_records,
    compute_neighbors,
    configure_huggingface_auth,
    embedding_variant_name,
    extract_primary_topic,
    extract_raw_keywords,
    iter_analysis_bundles,
    load_annotation_lookup,
    load_embedding_bundle,
    load_embedding_inputs,
    load_stage1_bundle,
    load_title_lookup,
    model_name_slug,
    normalize_embedding_fields,
    parse_string_list_value,
    unique_strings,
    write_analysis_bundle,
    write_embedding_bundle,
    write_json,
)

# ---- clusters --------------------------------------------------------------
from ohbm2026.analyze.clusters import (
    _agglomerative_kwargs,
    _normalize_rows,
    _normalized_cluster_entropy,
    _normalized_metric_value,
    _valid_benchmark_run,
    align_cluster_records,
    align_semantic_records,
    build_cluster_benchmark_parser,
    build_group_rationale,
    build_knn_graph,
    build_semantic_analysis_parser,
    build_stage2_analysis_parser,
    cluster_benchmark_main,
    cluster_with_method,
    compute_clustering_metrics,
    detect_semantic_communities,
    detect_semantic_communities_at_resolution,
    detect_stage2_communities,
    extract_cluster_keywords,
    load_enriched_lookup,
    prepare_clustering_matrix,
    rank_clustering_benchmark_results,
    run_clustering_benchmark,
    semantic_analysis_main,
    stage2_analysis_main,
    summarize_membership_groups,
    summarize_semantic_clusters,
    summarize_stage2_clusters,
    write_clustering_benchmark,
    write_semantic_analysis,
    write_stage2_analysis,
)

# ---- projections -----------------------------------------------------------
from ohbm2026.analyze.projections import (
    DEFAULT_TSNE_EARLY_EXAGGERATION,
    DEFAULT_TSNE_LEARNING_RATE,
    DEFAULT_TSNE_PERPLEXITY,
    DEFAULT_UMAP_MIN_DIST,
    DEFAULT_UMAP_NEIGHBORS,
    _add_projection_panel_traces,
    _build_linked_highlight_script,
    _cluster_distance_metrics,
    _normalize_tsne_learning_rates,
    _projection_rank_key,
    _projection_trace_customdata,
    build_projection_compare_parser,
    build_projection_graph,
    build_projection_optimize_parser,
    build_umap_parser,
    compute_tsne_projection,
    compute_umap_projection,
    default_projection_output_paths,
    default_umap_output_paths,
    optimize_projection_parameters,
    projection_compare_main,
    projection_optimize_main,
    score_projection,
    umap_main,
    write_projection_comparison_outputs,
    write_umap_outputs,
)

# ---- embed/neuroscape (re-exported for back-compat) ------------------------
from ohbm2026.embed.neuroscape import (
    DEFAULT_STAGE2_HIDDEN_DIMENSIONS,
    DEFAULT_STAGE2_OUTPUT_DIMENSION,
    PUBLISHED_STAGE2_HIDDEN_DIMENSIONS,
    PUBLISHED_STAGE2_OUTPUT_DIMENSION,
    apply_pretrained_stage2_main,
    apply_stage2_model,
    build_apply_pretrained_stage2_parser,
    build_manifest_parser,
    build_stage2_network,
    build_stage2_parser,
    choose_torch_device,
    compute_stage2_losses,
    dimension_correlation,
    evaluate_stage2_model,
    load_pretrained_stage2_model,
    manifest_main,
    normalize_hidden_dimensions,
    split_stage2_matrix,
    stage2_main,
    train_stage2_model,
    write_neuroscape_manifest,
    write_pretrained_stage2_bundle,
    write_stage2_bundle,
)

# ---- composition helpers (re-exported from embed/compose for legacy) -------
from ohbm2026.embed.compose import (
    apply_published_stage2_to_matrix,
    compose_recipe,
)
