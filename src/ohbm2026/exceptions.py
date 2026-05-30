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

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    # Re-exported via module-level __getattr__ to avoid a circular
    # import: fetch/__init__.py loads fetch.stage, which itself imports
    # `from ohbm2026.exceptions import ...`. Eager-importing
    # `ohbm2026.fetch.graphql_api` at the top of THIS module triggers
    # fetch/__init__.py before exceptions.py finishes loading, which
    # explodes any direct `from ohbm2026.exceptions import X` outside
    # the cli/dispatch sequence (e.g. a new stage module like
    # `ohbm2026.book.corpus`). Deferring to runtime resolution via
    # __getattr__ keeps the public surface unchanged.
    from ohbm2026.fetch.graphql_api import GraphQLAPIError  # noqa: F401


def __getattr__(name: str):
    if name == "GraphQLAPIError":
        from ohbm2026.fetch.graphql_api import GraphQLAPIError

        return GraphQLAPIError
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


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
    "BookBuildError",
    "PerAbstractRenderError",
    "Stage15Error",
    "NeuroScapeInputError",
    "UmapFitError",
    "UmapCacheError",
    "KnnCacheError",
    "OhbmProjectionError",
    "CrossParquetDriftError",
    "AtlasProvenanceError",
    "AtlasLinkCheckError",
    "Stage19SemanticError",
    "EmbeddingComputeError",
    "VectorsParquetWriteError",
    "VectorsManifestDriftError",
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


class BookBuildError(OhbmStageError):
    """Stage 11 (book-of-abstracts) precondition failed or render aborted.

    Raised by `ohbm2026.book` when the canonical corpus inputs are
    missing/empty, the filtered entry set is empty, the output root
    is unwritable, a required system dep (`pandoc` / `xelatex`) is
    absent from PATH, or pandoc returns non-zero. `details` captures
    subprocess stderr (or any other supporting context) verbatim so
    operators can diagnose without re-running.
    """

    def __init__(self, message: str, *, details: str | None = None) -> None:
        super().__init__(message)
        self.details = details


class PerAbstractRenderError(BookBuildError):
    """Stage 11.1 per-abstract pandoc/Tectonic render aborted.

    Distinct from a build-wide :class:`BookBuildError` so the orchestrator
    can isolate the failing entry, drop it from the assembled PDF, and
    record (poster_id, stderr_tail) under ``provenance.failed_abstracts``
    while the remaining chunks render normally (FR-002).
    """

    def __init__(
        self,
        message: str,
        *,
        poster_id: int | None = None,
        cache_key: str | None = None,
        pandoc_exit_code: int | None = None,
        details: str | None = None,
    ) -> None:
        super().__init__(message, details=details)
        self.poster_id = poster_id
        self.cache_key = cache_key
        self.pandoc_exit_code = pandoc_exit_code


class Stage15Error(OhbmStageError):
    """Base for any failure originating inside Stage 15 (build-atlas-package).

    Concrete subclasses cover the five error paths enumerated in
    ``specs/015-neuroscape-context/research.md#R-009`` plus the shared
    provenance + link-check rules. Each subclass carries structured
    kwargs so the orchestrator and tests can inspect failure context
    without regex-matching message strings.
    """


class NeuroScapeInputError(Stage15Error):
    """NeuroScape v1.0.1 release inputs are missing, malformed, or drifted.

    Raised by ``atlas_package.neuroscape_loader.discover_inputs`` when a
    required file is absent, the HDF5 shard manifest SHA does not match
    the previously recorded ``hdf5_shard_manifest_sha256``, or the
    article/cluster CSV columns no longer match the discovered schema.
    Carries (``file``, ``expected``, ``actual``) so the operator can fix
    the source layout without re-running diagnostics (CA-007).
    """

    def __init__(
        self,
        message: str,
        *,
        file: str | None = None,
        expected: str | None = None,
        actual: str | None = None,
    ) -> None:
        super().__init__(message)
        self.file = file
        self.expected = expected
        self.actual = actual


class UmapFitError(Stage15Error):
    """The UMAP fit step failed (numerical, OOM, or input-shape error).

    Raised when ``umap_fit.fit`` cannot produce a valid 2D or 3D
    embedding — most often because the input vector matrix contains
    non-finite values (NaN / inf) or because the matrix is singular at
    the requested ``n_neighbors``. Carries (``reason``, ``n_vectors``)
    so the orchestrator can include the failure in provenance.
    """

    def __init__(
        self,
        message: str,
        *,
        reason: str | None = None,
        n_vectors: int | None = None,
    ) -> None:
        super().__init__(message)
        self.reason = reason
        self.n_vectors = n_vectors


class UmapCacheError(Stage15Error):
    """The UMAP fit on-disk cache is unreadable or inconsistent.

    Raised by :func:`ohbm2026.atlas_package.umap_fit.fit` when a cache
    entry exists at the expected ``<cache_root>/<state_key>/`` path
    but cannot be loaded (corrupted joblib, missing companion file,
    embedded-shape mismatch with the requested ``n_components``). The
    builder treats this as a precise, recoverable failure: the
    operator can delete the offending directory and re-run to re-fit
    cleanly. Carries (``path``, ``reason``) so the message points at
    the exact file.
    """

    def __init__(
        self,
        message: str,
        *,
        path: str | None = None,
        reason: str | None = None,
    ) -> None:
        super().__init__(message)
        self.path = path
        self.reason = reason


class KnnCacheError(Stage15Error):
    """The k-NN neighbour-index on-disk cache is unreadable or
    inconsistent.

    Raised by :func:`ohbm2026.atlas_package.neighbour_index.build_knn`
    when a cache entry exists at the expected
    ``<cache_root>/<state_key>/`` path but cannot be loaded (missing
    companion array, unreadable ``.npy``, shape mismatch with the
    requested ``k``). Like :class:`UmapCacheError` the builder treats
    this as precise + recoverable: delete the offending directory and
    re-run to recompute the brute-force k-NN cleanly. Carries
    (``path``, ``reason``).
    """

    def __init__(
        self,
        message: str,
        *,
        path: str | None = None,
        reason: str | None = None,
    ) -> None:
        super().__init__(message)
        self.path = path
        self.reason = reason


class OhbmProjectionError(Stage15Error):
    """One or more OHBM 2026 abstracts could not be projected into the
    NeuroScape UMAP space.

    Aggregate semantic (R-009): the projector collects every failing
    ``submission_id`` during the projection pass and the orchestrator
    re-raises this exception ONCE at the end with the full id list.
    A single bad record never aborts a 3K-record projection mid-stream
    (resumability — Principle III).
    """

    def __init__(
        self,
        message: str,
        *,
        failed_submission_ids: list[int] | None = None,
    ) -> None:
        super().__init__(message)
        self.failed_submission_ids = list(failed_submission_ids or [])


class CrossParquetDriftError(Stage15Error):
    """The three publishable parquets have drifted out of agreement.

    Raised by ``parquet_writer`` at build time when the ``clusters``
    row group of ``neuroscape.parquet`` is not row-for-row equal to
    the ``clusters`` row group of ``atlas.parquet``, OR when
    ``atlas.parquet/manifest.sibling_state_keys`` references a
    ``state_key`` that is not present in the corresponding sibling
    parquet's manifest. Browser-side ``loader.ts`` surfaces the same
    condition as a visible UI error banner at view time (R-012).

    Carries (``parquet``, ``field``, ``expected``, ``actual``) so the
    operator can identify the offending field without scanning the
    full output.
    """

    def __init__(
        self,
        message: str,
        *,
        parquet: str | None = None,
        field: str | None = None,
        expected: str | None = None,
        actual: str | None = None,
    ) -> None:
        super().__init__(message)
        self.parquet = parquet
        self.field = field
        self.expected = expected
        self.actual = actual


class AtlasProvenanceError(ProvenanceError, Stage15Error):
    """Stage 15 provenance record cannot be written safely.

    Specialises the shared :class:`ProvenanceError` so callers can
    catch either "any provenance violation" or "specifically a Stage
    15 provenance violation". Raised when a Stage 15 provenance field
    contains an absolute path (starts with ``/``) or a user-home-
    relative path (starts with ``~``) — both violate CA-008 (paths
    must be repo-relative so the bundle is portable).
    """

    def __init__(
        self,
        message: str,
        *,
        field: str | None = None,
        expected: str | None = None,
        actual: str | None = None,
    ) -> None:
        super().__init__(message)
        self.field = field
        self.expected = expected
        self.actual = actual


class AtlasLinkCheckError(Stage15Error):
    """A build-time link-check against an external URL returned 4xx / 5xx.

    Scope is narrow per R-013: only the small fixed set of non-PubMed-
    record URLs is pre-checked (NeuroScape Zenodo / citation / OHBM
    2026 site / cross-conference landing page / NCBI E-utilities
    base). Per-PubMed-record URLs are validated at view time by the
    runtime PubMed fetch (R-015), not at build time.
    """

    def __init__(
        self,
        message: str,
        *,
        url: str | None = None,
        status: int | None = None,
    ) -> None:
        super().__init__(message)
        self.url = url
        self.status = status


class Stage19SemanticError(Stage15Error):
    """Base for any failure originating inside the spec-019 semantic-search
    build step or browser-side ranker.

    Subclasses `Stage15Error` so any existing Stage-15 catcher catches
    Stage-19 errors too — the semantic-index step is wired into the
    `ohbmcli build-atlas-package` orchestrator that Stage 15 established.
    """


class EmbeddingComputeError(Stage19SemanticError):
    """The corpus-side MiniLM embedding compute failed.

    Raised by ``ohbm2026.atlas_package.vectors_compute`` when
    sentence-transformers fails to load the pinned model
    (``Xenova/all-MiniLM-L6-v2``), or inference produces a vector matrix
    with the wrong shape / non-finite values. Carries (``reason``,
    ``n_titles``) so the orchestrator can include the failure in
    provenance.
    """

    def __init__(
        self,
        message: str,
        *,
        reason: str | None = None,
        n_titles: int | None = None,
    ) -> None:
        super().__init__(message)
        self.reason = reason
        self.n_titles = n_titles


class VectorsParquetWriteError(Stage19SemanticError):
    """The semantic-vectors parquet writer detected an invariant violation
    before/during write.

    Raised by ``ohbm2026.atlas_package.semantic_index.write_neuroscape_vectors_parquet``
    when the set of ``pubmed_id`` rows about to be written does not
    match the articles table on ``neuroscape.parquet`` (INV-003), or
    when the per-cluster row-group sort order would defeat predicate
    pushdown. Carries (``path``, ``reason``) so the message points at
    the exact file.
    """

    def __init__(
        self,
        message: str,
        *,
        path: str | None = None,
        reason: str | None = None,
    ) -> None:
        super().__init__(message)
        self.path = path
        self.reason = reason


class VectorsManifestDriftError(Stage19SemanticError):
    """The browser-side semantic-index manifest drifted from its parent
    `neuroscape.parquet` manifest, or the loaded MiniLM model's sha256
    does not match the value pinned in the vectors-parquet manifest.

    The "matched-pair invariant" (research.md R-010): cosine similarity
    across corpus + query embeddings is only meaningful when both
    halves use byte-identical model weights. Raised by the browser
    loader's drift check (extending the existing
    ``site/src/lib/data_package/loader.ts::verifyAtlasSiblingDrift``
    pattern) and by the worker's init handshake. Carries (``path``,
    ``reason``) so the user-visible message can name the offending
    artifact.
    """

    def __init__(
        self,
        message: str,
        *,
        path: str | None = None,
        reason: str | None = None,
    ) -> None:
        super().__init__(message)
        self.path = path
        self.reason = reason


class CommunityResolutionDegenerate(Warning):
    """Warning emitted when community detection at the chosen
    resolution produces a single community holding >90% of abstracts.

    Distinct from `AnalysisError` because the run still writes the
    bundle (edge case 5): the operator may want to adjust resolution,
    not abort. A warning is the right vehicle so the runner's stdout
    summary still records the run as successful.
    """
