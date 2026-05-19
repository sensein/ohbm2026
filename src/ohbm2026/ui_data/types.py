"""Canonical row shapes for the Stage-10 export redesign.

Stage 6 emitted JSON shards as the only on-disk format. Stage 10 introduces
multiple candidate containers (Parquet, SQLite, DuckDB, Arrow IPC, …) — see
``specs/010-export-redesign/research.md``. Every candidate consumes the same
row stream produced by the per-entity ``iter_*()`` functions; this module
locks the row shapes so the candidate emitters under
``ohbm2026.ui_data.formats`` can share one canonical input contract.

Why ``TypedDict`` and not ``dataclass`` / ``pydantic``:

- Every existing builder already yields ``dict[str, Any]`` records. Typing
  them as ``TypedDict`` is zero-cost — the in-memory shape doesn't change,
  static checkers gain field-level visibility, and JSON serialization is
  unaffected.
- A dataclass / pydantic conversion would require rewriting every call
  site that reads ``row['poster_id']`` etc., which is out of scope for this
  refactor (FR-204: zero UI feature regression, and the existing call sites
  span ~12 modules).

When the bench commits to a non-JSON candidate (e.g. Parquet), the emitter
under ``formats/`` is responsible for translating these TypedDicts into the
target format's native row representation (Parquet RecordBatch, SQLite
INSERT, etc.). The row shapes here are the format-agnostic contract.
"""

from __future__ import annotations

from typing import Any, Literal, TypedDict

# ---------------------------------------------------------------------------
# Manifest + build_info envelope
# ---------------------------------------------------------------------------


class BuildInfo(TypedDict):
    corpus_state_key: str
    stage4_rollup_state_key: str
    code_revision: str
    code_revision_short: str
    built_at: str  # ISO-8601 UTC


class ManifestCell(TypedDict, total=False):
    """One entry in ``manifest.cells`` — per-(model, input) cell pointer.

    Backed by the existing ``manifest.json`` shape. Stage-10 candidate
    emitters MAY add format-specific fields (e.g. ``parquet_offset``); this
    TypedDict pins the always-present fields and leaves room via
    ``total=False`` for the optional ones.
    """

    cell_key: str
    model: str
    input: str
    url: str  # shard path / URL relative to the data root
    neighbors_url: str
    topic_shards: dict[str, str]  # {kind: url} — Stage-6 `range: Any` slot, see FR-201


class ManifestFacet(TypedDict):
    key: str
    label: str
    multivalued: bool


class ManifestSearch(TypedDict, total=False):
    minilm_vectors_url: str
    minilm_vectors_build_info_url: str


class ManifestRow(TypedDict, total=False):
    """The single manifest record. Lives at the root of the data tree."""

    schema_version: str
    build_info: BuildInfo
    conference_id: str  # NEW per FR-206 (Stage-10)
    format: str  # NEW per Stage-10 (matches the runtime-decoder enum)
    corpus_count: int
    models: list[str]
    inputs: list[str]
    default_cell: str
    cells: list[ManifestCell]
    facets: list[ManifestFacet]
    search: ManifestSearch


# ---------------------------------------------------------------------------
# Abstract record
# ---------------------------------------------------------------------------


class AbstractTopics(TypedDict):
    primary: str
    primary_subcategory: str
    secondary: str
    secondary_subcategory: str


class AbstractSections(TypedDict):
    introduction: str
    methods: str
    results: str
    conclusion: str
    references: str


class FacetValues(TypedDict, total=False):
    """The 11 per-record facet lists.

    Stage-6 modelled this as ``range: Any`` because LinkML doesn't natively
    type string-keyed dicts. Promoting to a concrete TypedDict eliminates
    the looseness at the source (FR-201) while leaving the on-disk JSON
    shape unchanged.
    """

    keywords: list[str]
    methods: list[str]
    study_type: list[str]
    population: list[str]
    field_strength: list[str]
    processing_packages: list[str]
    species: list[str]
    recording_technology: list[str]
    brain_regions: list[str]
    brain_networks: list[str]
    accepted_for: list[str]


class AbstractRow(TypedDict, total=False):
    abstract_id: int
    poster_id: str
    title: str
    accepted_for: str
    sections: AbstractSections
    topics: AbstractTopics
    methods_checklist: list[str]
    facets: FacetValues
    author_ids: list[int]
    reference_dois: list[str]  # parallel to reference_urls + reference_titles per FR-202
    reference_urls: list[str]
    reference_titles: list[str]


# ---------------------------------------------------------------------------
# Author record
# ---------------------------------------------------------------------------


class AuthorRow(TypedDict):
    author_id: int
    name: str
    affiliations: list[str]
    abstract_ids: list[int]  # reverse index — every abstract this author appears on


# ---------------------------------------------------------------------------
# Cell row (per-(model, input) per-abstract row)
# ---------------------------------------------------------------------------


class CellRow(TypedDict, total=False):
    """One row in a per-(model, input) cell shard.

    ``umap_missing`` is a transitional flag carried over from Stage 6;
    Stage-10 candidates SHOULD use a sparse representation instead
    (omit the row, or set ``umap2d`` / ``umap3d`` to ``None``) per FR-202.
    """

    abstract_id: int
    umap2d: list[float] | None  # 2-tuple
    umap3d: list[float] | None  # 3-tuple
    community_id: int | None
    topic_cluster_id: int | None
    neuroscape_cluster_id: int | None  # only present when model == 'neuroscape'
    umap_missing: bool  # to be deprecated in Stage-10 final commit


# ---------------------------------------------------------------------------
# Topic row (per-(cell_key, kind, cluster_id))
# ---------------------------------------------------------------------------


TopicKind = Literal["communities", "neuroscape_clusters", "topic_clusters"]


class TopicRow(TypedDict, total=False):
    cluster_id: int
    title: str
    description: str
    focus: str
    keywords: list[str]


# ---------------------------------------------------------------------------
# Neighbour row (per-(cell_key, abstract_id))
# ---------------------------------------------------------------------------


class NeighbourRow(TypedDict):
    """k-nearest + k-farthest pairs for one abstract within one cell.

    Stored as parallel arrays of length ``k`` (Stage-6 default ``k=10``).
    The float distances are full precision today; the Stage-10 bench
    measures whether float16 / int8 quantization preserves UI ranking.
    """

    abstract_id: int
    nearest_ids: list[int]
    nearest_distances: list[float]
    farthest_ids: list[int]
    farthest_distances: list[float]


# ---------------------------------------------------------------------------
# Enrichment row (claims + figures per-abstract)
# ---------------------------------------------------------------------------


class ClaimRow(TypedDict, total=False):
    text: str
    source: str  # verbatim quote from the abstract — dominates enrichment.json byte count
    evidence: str  # LLM-generated explanation
    evidence_eco_codes: list[str]  # FR-202: gain a `range: EcoCodeEnum` constraint
    confidence: float


class FigureRow(TypedDict, total=False):
    figure_id: str
    caption_guess: str
    interpretation: str
    ocr_text: str
    keywords: list[str]


class AiProvenance(TypedDict, total=False):
    claims_model_id: str
    claims_eco_vocab_version: str
    figures_model_id: str
    references_strategy_id: str


class EnrichmentRow(TypedDict, total=False):
    """One enrichment record per abstract. Stage-10 promotes ``abstract_id`` to
    a column so the third Stage-6 ``range: Any`` slot (the
    ``{str(abstract_id): EnrichmentRecord}`` dict) becomes a typed table
    (FR-201 / FR-202).
    """

    abstract_id: int
    claims: list[ClaimRow]
    figures: list[FigureRow]


# ---------------------------------------------------------------------------
# MiniLM vectors sidecar (binary tensor block, not a row stream)
# ---------------------------------------------------------------------------


class MinilmVectorsBlock(TypedDict):
    """Binary sidecar carrying int8-quantised MiniLM-L6 embeddings.

    ``vectors`` is a bytes blob (the on-disk ``minilm_vectors.bin``);
    ``shape`` is the (N_abstracts, dim) tuple needed to interpret it.
    Stage-10 candidate emitters MAY move this into the format's container
    (Parquet binary column, SQLite BLOB, DuckDB BLOB) — the bench measures
    whether keeping the sidecar separate is cheaper.
    """

    vectors: bytes
    shape: tuple[int, int]
    dtype: str  # "int8" today
    abstract_ids: list[int]  # parallel to vector rows; FR-202 cross-validation


# ---------------------------------------------------------------------------
# Cross-conference link row (NEW per FR-208)
# ---------------------------------------------------------------------------


CrossConferenceLinkKind = Literal["embedding_neighbour", "claim_overlap", "citation"]


class CrossConferenceLinkRow(TypedDict, total=False):
    """One cross-conference link, e.g. OHBM-abstract ↔ PubMed-paper.

    Empty for the OHBM-2026 base export; populated by a follow-up build
    step after a second conference's data exists. Lives in a separate
    table / shard / file so the OHBM base shards stay byte-identical
    across single-conf vs multi-conf builds (FR-207 / SC-207).
    """

    conf_a: str
    id_a: int | str  # abstract_id / poster_id / DOI / PMID — format-agnostic
    conf_b: str
    id_b: int | str
    link_kind: CrossConferenceLinkKind
    similarity: float
    metadata: dict[str, Any]  # format-specific extras; opaque to the runtime decoder


# ---------------------------------------------------------------------------
# Shard envelope wrappers
# ---------------------------------------------------------------------------
#
# Today's emitters wrap each row-iterator in a JSON envelope carrying
# `schema_version` + `build_info`. Stage-10 candidate emitters use these
# envelope types when they need them; SQLite / DuckDB candidates absorb the
# envelope into a `meta` table instead.


class AbstractsShard(TypedDict):
    schema_version: str
    build_info: BuildInfo
    abstracts: list[AbstractRow]


class AuthorsShard(TypedDict):
    schema_version: str
    build_info: BuildInfo
    authors: list[AuthorRow]


class CellShard(TypedDict):
    schema_version: str
    build_info: BuildInfo
    cell_key: str
    rows: list[CellRow]


class TopicShard(TypedDict):
    schema_version: str
    build_info: BuildInfo
    cell_key: str
    kind: TopicKind
    topics: list[TopicRow]


class NeighbourShard(TypedDict):
    schema_version: str
    build_info: BuildInfo
    cell_key: str
    k: int
    abstract_ids: list[int]
    nearest_ids: list[list[int]]
    nearest_distances: list[list[float]]
    farthest_ids: list[list[int]]
    farthest_distances: list[list[float]]


class EnrichmentShard(TypedDict):
    schema_version: str
    build_info: BuildInfo
    ai_provenance: AiProvenance
    records: list[EnrichmentRow]  # Stage-10: was {str(id): EnrichmentRow}; now a list (FR-201)


__all__ = [
    "AbstractRow",
    "AbstractsShard",
    "AbstractSections",
    "AbstractTopics",
    "AiProvenance",
    "AuthorRow",
    "AuthorsShard",
    "BuildInfo",
    "CellRow",
    "CellShard",
    "ClaimRow",
    "CrossConferenceLinkKind",
    "CrossConferenceLinkRow",
    "EnrichmentRow",
    "EnrichmentShard",
    "FacetValues",
    "FigureRow",
    "ManifestCell",
    "ManifestFacet",
    "ManifestRow",
    "ManifestSearch",
    "MinilmVectorsBlock",
    "NeighbourRow",
    "NeighbourShard",
    "TopicKind",
    "TopicRow",
    "TopicShard",
]
