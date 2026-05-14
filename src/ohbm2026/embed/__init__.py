"""Stage 3 — multi-model per-component embeddings matrix.

Public surface re-exported here so callers can `from ohbm2026.embed
import compose_recipe, run_single_bundle, …` without dipping into
submodules.
"""

from ohbm2026.embed.compose import (
    apply_published_stage2_to_matrix,
    compose_recipe,
)
from ohbm2026.embed.components import (
    ALL_COMPONENTS,
    DEFAULT_COMPONENTS,
    PARTIAL_COMPONENTS,
    abstract_has_component,
    assemble_all_components,
    assemble_component,
)
from ohbm2026.embed.stage import (
    DEFAULT_MODELS,
    BundleResult,
    build_clients,
    build_parser,
    load_enriched_corpus,
    main,
    run_matrix,
    run_single_bundle,
)
from ohbm2026.embed.storage import (
    BUNDLE_SCHEMA_VERSION,
    CACHE_VERSION,
    atomic_write_bytes,
    atomic_write_json,
    bundle_corpus_state_key,
    cache_path_for,
    load_bundle,
    load_cache_entry,
    write_bundle,
    write_cache_entry,
)

__all__ = [
    # compose
    "compose_recipe",
    "apply_published_stage2_to_matrix",
    # components
    "ALL_COMPONENTS",
    "DEFAULT_COMPONENTS",
    "PARTIAL_COMPONENTS",
    "abstract_has_component",
    "assemble_all_components",
    "assemble_component",
    # stage (orchestrator)
    "DEFAULT_MODELS",
    "BundleResult",
    "build_clients",
    "build_parser",
    "load_enriched_corpus",
    "main",
    "run_matrix",
    "run_single_bundle",
    # storage
    "BUNDLE_SCHEMA_VERSION",
    "CACHE_VERSION",
    "atomic_write_bytes",
    "atomic_write_json",
    "bundle_corpus_state_key",
    "cache_path_for",
    "load_bundle",
    "load_cache_entry",
    "write_bundle",
    "write_cache_entry",
]
