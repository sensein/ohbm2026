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

from ohbm2026.graphql_api import GraphQLAPIError

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
    "CacheVersionError",
    "ComponentFailureThresholdError",
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
