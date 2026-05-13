"""Typed exception hierarchy for the OHBM 2026 pipeline.

Stage 1 (`fetch_stage`) defines its own concrete error types under
`Stage1Error`. The base classes here let callers narrow `except`
clauses by stage AND by failure kind without depending on a specific
module's import path.

Per Principle VI, no bare `except` should swallow Stage1Error or
GraphQLAPIError. The module-level `__all__` makes the public surface
explicit so subsequent stages can mirror the pattern.
"""

from __future__ import annotations

from ohbm2026.graphql_api import GraphQLAPIError

__all__ = [
    "GraphQLAPIError",
    "Stage1Error",
    "SchemaContractError",
    "CheckpointError",
    "ProvenanceError",
]


class Stage1Error(RuntimeError):
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


class ProvenanceError(Stage1Error):
    """Provenance record cannot be written safely.

    Raised when a candidate path written into the provenance record is
    absolute (starts with `/`) or user-home-relative (starts with `~`),
    either of which would make the bundle unportable to another
    machine and violates CA-008.
    """
