"""Typed exception hierarchy for the OHBM 2026 pipeline.

Each stage owns its own concrete error types. A shared base
`OhbmStageError(RuntimeError)` lets callers express "any pipeline
failure originating in a stage orchestrator" with a single `except`
without coupling to a specific stage's import path. `Stage1Error` and
`Stage2Error` both inherit from it. Existing Stage 1 consumers
catching `Stage1Error` keep working unchanged because `Stage1Error`
remains a `RuntimeError` via the wider isinstance chain.

Per Principle VI, no bare `except` should swallow these. The
module-level `__all__` makes the public surface explicit so future
stages can mirror the pattern.
"""

from __future__ import annotations

from ohbm2026.fetch.graphql_api import GraphQLAPIError

__all__ = [
    "GraphQLAPIError",
    "OhbmStageError",
    "Stage1Error",
    "SchemaContractError",
    "CheckpointError",
    "ProvenanceError",
    "FigureFailureError",
    "Stage2Error",
    "EnrichmentError",
    "ContextLengthExceededError",
    "CacheVersionError",
    "ComponentFailureThresholdError",
    "Stage3Error",
    "EmbeddingError",
    "EmbeddingProviderError",
    "EmbeddingBudgetError",
    "EmbeddingContractError",
    "ComponentAssemblyError",
    "EmbeddingThresholdError",
    "AnalysisError",
    "InputBundleMissing",
    "CentroidTableMissing",
    "CentroidTableVersionMismatch",
    "UnsupportedProjectionAlgorithm",
    "ProjectionDimensionMismatch",
    "TopicGroupingHallucination",
    "CommunityResolutionDegenerate",
    "UIBuildError",
    "Stage6Error",
]


class OhbmStageError(RuntimeError):
    """Base for any failure originating inside an ohbm2026 stage orchestrator."""


class Stage1Error(OhbmStageError):
    """Base for any failure originating inside Stage 1 (fetch-abstracts)."""


class SchemaContractError(Stage1Error):
    """Upstream GraphQL schema drift on a hard-contract field.

    Raised when a fetch query body field has been removed, renamed, or
    type-changed upstream. Carries the field path, old shape, and new
    shape in its message so the operator can act without re-running
    diagnostics.
    """


class CheckpointError(Stage1Error):
    """Resume checkpoint cannot be trusted for the current run.

    Raised when `bound_schema_hash` in a persisted checkpoint does not
    match the most recently fetched schema artifact, or when the
    checkpoint's `state_key` does not match the current run's
    `state_key`. Resume MUST require explicit operator intent in either
    case (Principle VI: no silent fallbacks).
    """


class ProvenanceError(OhbmStageError):
    """Provenance record cannot be written safely.

    Raised by any stage when a candidate path written into the
    provenance record is absolute (starts with `/`) or user-home-
    relative (starts with `~`), either of which would make the bundle
    unportable to another machine and violates CA-008 / Principle VIII.
    """


class FigureFailureError(Stage1Error):
    """Figure-asset failure rate exceeded the configured threshold.

    Mapped to exit code 5 by Stage 1 (per contracts/cli.md). The
    operator can rerun after fixing upstream (the existing local
    files are reused; only the failures retry) or raise the
    threshold via ``--figure-failure-threshold`` if upstream
    flakiness is expected.
    """


class UIBuildError(RuntimeError):
    """The static-UI export pipeline produced an unusable bundle.

    Raised when a precondition for the UI export is violated (missing
    inputs, malformed rollup, etc.). Kept as a `RuntimeError` subclass
    rather than an `OhbmStageError` because the UI export is downstream
    of the per-stage pipelines and consumes their canonical artifacts.
    """


class Stage6Error(OhbmStageError):
    """Base class for Stage 6 (UI data-package build) failures.

    Subclassed by :class:`ohbm2026.ui_data.state_key.Stage6BuildError` and
    other Stage 6 callsites. Distinct from :class:`UIBuildError` (which
    covers the legacy ``ui.py`` export path) so callers can differentiate.
    """


class Stage2Error(OhbmStageError):
    """Base for any failure originating inside Stage 2 (enrich-abstracts)."""


class EnrichmentError(Stage2Error):
    """A per-component enrichment call failed.

    Raised when an LLM/HTTP call cannot produce a usable result for a
    single component (figure interpretation, claims extraction, or
    reference resolution) — including schema-drift on the LLM
    response (Principle VII: discovered mismatches surface loudly,
    never as silent fallbacks).
    """


class ContextLengthExceededError(EnrichmentError):
    """The model rejected the request because the input exceeded its
    context window (HTTP 400, code=context_length_exceeded).

    Distinct from generic EnrichmentError so callers can attempt a
    larger-model fallback (deterministic input rejection — same bytes
    will fail identically on any retry of the same model). Still an
    EnrichmentError, so handlers that just count typed failures keep
    working unchanged.
    """


class CacheVersionError(Stage2Error):
    """A cache entry on disk has an unrecognized cache_version.

    Surfaces as exit code 7. Stage 2 treats this loudly rather than
    silently migrating the entry — silent migration risks producing
    records that mix old and new shapes (research.md §3).
    """


class ComponentFailureThresholdError(Stage2Error):
    """The per-component failure rate exceeded its configured threshold.

    Surfaces as exit code 5. The enriched corpus is NOT overwritten
    when this is raised; the previous enriched corpus (if any)
    remains intact and the per-component cache entries written so
    far survive for the next run.
    """


class Stage3Error(OhbmStageError):
    """Base for any failure originating inside Stage 3 (embeddings matrix)."""


class EmbeddingError(Stage3Error):
    """A per-bundle or per-abstract embedding call failed.

    Catch this when you want to handle any Stage 3 embedding-time
    failure regardless of provider, including SDK rejections, schema
    drift in the response, and per-component coverage refusals.
    """


class EmbeddingProviderError(EmbeddingError):
    """Provider returned a transient or terminal error past the retry budget.

    Raised by the per-model runners when the SDK exhausts its
    flex / standard retry attempts (network blip, 5xx, 429s past
    backoff). The orchestrator counts these against the per-bundle
    failure threshold.
    """


class EmbeddingBudgetError(EmbeddingError):
    """Provider reported the daily / monthly budget is exhausted.

    Distinct from EmbeddingProviderError so the runner can exit with
    the resume-friendly exit code 3 (the partial cache is preserved;
    the operator tops up the budget and re-invokes).
    """


class EmbeddingContractError(EmbeddingError):
    """The provider's response did not match the request contract.

    Surfaces when batch cardinality is wrong (fewer / more vectors
    than inputs sent), when the SDK-reported `model` differs from
    the requested model_id (Principle VII), or when the vector
    dimension does not match the previously observed dimension for
    this model. Treated as a hard per-bundle abort, not a per-
    abstract failure, because the contract is broken at the
    provider level.
    """


class ComponentAssemblyError(Stage3Error):
    """The enriched corpus did not yield text for a requested component.

    Raised when an abstract that should have a component (per the
    coverage gate) cannot be assembled — usually a missing field
    in the enriched payload or a malformed record. Distinct from
    "absent" components, which are legitimate and recorded under
    a bundle's `missing_ids`.
    """


class EmbeddingThresholdError(Stage3Error):
    """The per-bundle failure rate exceeded the configured threshold.

    Maps to exit code 5. The partial cache is preserved (matches
    Stage 2.1's `ComponentFailureThresholdError` pattern); the bundle
    directory is NOT written.
    """


class AnalysisError(OhbmStageError):
    """Base for any failure originating inside Stage 4 (analyze-matrix)."""


class InputBundleMissing(AnalysisError):
    """A referenced Stage 3 embedding bundle was not on disk.

    Raised at pre-flight resolution before any analysis fires. Carries
    the expected bundle path in its message so the operator can run
    Stage 3 for the missing `(model, component)` pair.
    """


class CentroidTableMissing(AnalysisError):
    """The precomputed NeuroScape centroid file is absent.

    Raised when `neuroscape_clusters` is requested but
    `data/inputs/neuroscape/centroids__*.npy` (and its companion
    `cluster_table.csv`) cannot be found. Operator must run
    `scripts/derive_neuroscape_centroids.py` once before Stage 4 can
    assign cluster ids.
    """


class CentroidTableVersionMismatch(AnalysisError):
    """The centroid sidecar's version disagrees with the Stage-2
    checkpoint's expected version (CA-007).

    Distinct from `CentroidTableMissing` so operators can tell apart
    "file absent" from "file present but stale". Version is discovered
    at runtime from `cluster_table.csv`; mismatches raise rather than
    silently mapping into the wrong cluster space.
    """


class UnsupportedProjectionAlgorithm(AnalysisError):
    """`project_into_umap` was asked for an algorithm the bundle does
    not list under `metadata.json:supported_algorithms`.

    The bundle's `supported_algorithms` is derived at write time from
    which artifacts were actually persisted — e.g., a coords-only
    bundle (no UMAPModel pickle) does NOT support `native`. The error
    message names the requested algorithm and the supported set so the
    operator can pick a valid one.
    """


class ProjectionDimensionMismatch(AnalysisError):
    """`new_vectors` has a different second-axis dim than the fitted
    UMAP's reference matrix.

    Edge case 2: e.g., projecting a 384-dim MiniLM vector into a UMAP
    fitted on 1024-dim Voyage vectors. Carries both dims in the
    message ("expected D, got d").
    """


class TopicGroupingHallucination(AnalysisError):
    """The LLM topic-grouping pass emitted at least one keyword that
    is not in the per-cluster candidate-phrase shortlist.

    Enforces FR-009's `Keywords ⊆ candidate_phrases` guard so the LLM
    can re-rank/group phrases but cannot invent terms. Carries the
    offending keyword(s) and the cluster id in its message; the
    orchestrator aborts the run rather than caching the hallucinated
    response.
    """


class CommunityResolutionDegenerate(Warning):
    """Warning emitted when community detection at the chosen
    resolution produces a single community holding >90% of abstracts.

    Distinct from `AnalysisError` because the run still writes the
    bundle (edge case 5): the operator may want to adjust resolution,
    not abort. A warning is the right vehicle so the runner's stdout
    summary still records the run as successful.
    """
