from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

DATA_ROOT = Path("data")
INPUTS_ROOT = DATA_ROOT / "inputs"
PRIMARY_ROOT = DATA_ROOT / "primary"
CACHE_ROOT = DATA_ROOT / "cache"
OUTPUTS_ROOT = DATA_ROOT / "outputs"
EXPORT_ROOT = Path("export")
SCRATCH_ROOT = Path("tmp")
FETCH_CHECKPOINT_WORKFLOW = "fetch_abstracts"
PRIMARY_ASSETS_ROOT = PRIMARY_ROOT / "assets"
# Legacy alias retained briefly in case any out-of-tree script still
# imports the old name; downstream code SHOULD use
# PRIMARY_ASSETS_ROOT. The actual path now lives under
# data/primary/assets (consistent with the rest of normalized
# canonical data — see FR-008 Clarifications session 2026-05-13).
INPUT_ASSETS_ROOT = PRIMARY_ASSETS_ROOT
INPUT_AUTHORS_PATH = INPUTS_ROOT / "authors.json"
INPUT_PHENOMENA_THEORIES_PATH = INPUTS_ROOT / "abstracts_with_phenomena_with_theories_refined.csv"
INPUT_POSTER_LAYOUT_ROOT = INPUTS_ROOT / "poster_layout"
INPUT_LAYOUT_ASSETS_ROOT = INPUT_POSTER_LAYOUT_ROOT / "layout_assets"
INPUT_LAYOUT_GEOMETRY_PATH = INPUT_LAYOUT_ASSETS_ROOT / "layout_geometry.json"
PRIMARY_ABSTRACTS_PATH = PRIMARY_ROOT / "abstracts.json"
PRIMARY_WITHDRAWN_ABSTRACTS_PATH = PRIMARY_ROOT / "abstracts_withdrawn.json"
PRIMARY_AUTHORS_PATH = PRIMARY_ROOT / "authors.json"
PRIMARY_AUTHORS_WITHDRAWN_PATH = PRIMARY_ROOT / "authors_withdrawn.json"
PRIMARY_ENRICHED_ABSTRACTS_PATH = PRIMARY_ROOT / "abstracts_enriched.json"
PRIMARY_ENRICHED_CORPUS_PATH = PRIMARY_ROOT / "abstracts_enriched.sqlite"
PRIMARY_REFERENCE_METADATA_PATH = PRIMARY_ROOT / "reference_metadata.json"
ENRICH_COMPONENTS = ("figures", "claims", "references")
_ENRICH_CACHE_NAMESPACES = {
    "figures": "figure_analysis",
    "claims": "claim_analysis",
    "references": "reference_metadata",
}
EXPERIMENTS_ROOT = OUTPUTS_ROOT / "experiments"
EXPORTED_SITES_ROOT = OUTPUTS_ROOT / "exported-sites"
PROPOSALS_ROOT = OUTPUTS_ROOT / "proposals"
EMBEDDINGS_ROOT = EXPERIMENTS_ROOT / "embeddings"
PROJECTIONS_ROOT = EXPERIMENTS_ROOT / "projections"
UMAPS_ROOT = EXPERIMENTS_ROOT / "umaps"
SEQUENCING_BENCHMARKS_ROOT = EXPERIMENTS_ROOT / "sequencing_benchmarks"
TITLE_AUDIT_ROOT = EXPERIMENTS_ROOT / "title_audit"
TITLE_MODIFICATIONS_PATH = TITLE_AUDIT_ROOT / "title_modifications.json"

OUTPUT_FAMILIES = ("experiments", "exported-sites", "proposals")
ARTIFACT_CLASSES = ("input", "cache", "output", "scratch")
DEFAULT_SCHEMA_VERSION = "1"


def utc_now_isoformat() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_hashable(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Mapping):
        return {str(key): _normalize_hashable(value[key]) for key in sorted(value)}
    if isinstance(value, (list, tuple)):
        return [_normalize_hashable(item) for item in value]
    if isinstance(value, set):
        return [_normalize_hashable(item) for item in sorted(value, key=lambda item: json.dumps(_normalize_hashable(item), sort_keys=True))]
    return value


def _stable_hash(value: Any, *, length: int = 12) -> str:
    encoded = json.dumps(_normalize_hashable(value), sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:length]


def _normalized_strings(values: Iterable[str] | None) -> list[str]:
    if not values:
        return []
    normalized = sorted({str(value).strip() for value in values if str(value).strip()})
    return normalized


def build_dependency_basis(
    *,
    input_sources: Iterable[str] | None = None,
    input_digest: str | None = None,
    backend: str | None = None,
    model: str | None = None,
    options: Mapping[str, Any] | None = None,
    env_boundary: Iterable[str] | None = None,
    supersedes: str | None = None,
) -> dict[str, Any]:
    basis: dict[str, Any] = {
        "input_sources": _normalized_strings(input_sources),
        "input_digest": str(input_digest).strip() if input_digest else None,
        "backend": str(backend).strip() if backend else None,
        "model": str(model).strip() if model else None,
        "options_digest": _stable_hash(options) if options else None,
        "env_boundary": _normalized_strings(env_boundary),
        "supersedes": str(supersedes).strip() if supersedes else None,
    }
    return {key: value for key, value in basis.items() if value not in (None, [], "")}


def build_state_key(dependency_basis: Mapping[str, Any], *, schema_version: str = DEFAULT_SCHEMA_VERSION) -> str:
    return _stable_hash({"schema_version": schema_version, "dependency_basis": dict(dependency_basis)})


def build_input_snapshot_path(source_name: str, state_key: str, *, suffix: str = ".json") -> Path:
    return INPUTS_ROOT / f"{source_name}__{state_key}{suffix}"


def build_schema_artifact_path(state_key: str) -> Path:
    return build_input_snapshot_path("abstracts_graphql_schema", state_key)


def build_provenance_path(state_key: str) -> Path:
    return build_input_snapshot_path("abstracts_fetch_provenance", state_key)


def build_enrich_provenance_path(state_key: str) -> Path:
    return build_input_snapshot_path("abstracts_enrich_provenance", state_key)


def build_enrich_cache_path(component: str, cache_key: str) -> Path:
    if component not in ENRICH_COMPONENTS:
        raise ValueError(
            f"Unsupported Stage 2 component {component!r}; expected one of {ENRICH_COMPONENTS}"
        )
    if not cache_key or "/" in cache_key or "\\" in cache_key:
        raise ValueError(f"Invalid cache_key {cache_key!r}")
    namespace = _ENRICH_CACHE_NAMESPACES[component]
    return CACHE_ROOT / namespace / f"{cache_key}.json"


def build_fetch_checkpoint_path(state_key: str) -> Path:
    return build_cache_path(FETCH_CHECKPOINT_WORKFLOW, "checkpoint", state_key)


def build_cache_path(workflow: str, artifact_name: str, state_key: str, *, suffix: str = ".json") -> Path:
    return CACHE_ROOT / workflow / f"{artifact_name}__{state_key}{suffix}"


def build_output_path(output_family: str, artifact_name: str, state_key: str) -> Path:
    if output_family not in OUTPUT_FAMILIES:
        raise ValueError(f"Unsupported output family: {output_family}")
    return OUTPUTS_ROOT / output_family / f"{artifact_name}__{state_key}"


def build_publish_path(site_name: str) -> Path:
    return EXPORT_ROOT / site_name


def artifact_root(artifact_class: str, *, output_family: str | None = None) -> Path:
    if artifact_class == "input":
        return INPUTS_ROOT
    if artifact_class == "cache":
        return CACHE_ROOT
    if artifact_class == "output":
        if output_family is None:
            return OUTPUTS_ROOT
        return build_output_path(output_family, "placeholder", "state-key").parent
    if artifact_class == "scratch":
        return SCRATCH_ROOT
    raise ValueError(f"Unsupported artifact class: {artifact_class}")


def build_artifact_metadata(
    *,
    workflow: str,
    artifact_name: str,
    artifact_class: str,
    state_key: str,
    dependency_basis: Mapping[str, Any],
    output_family: str | None = None,
    status: str = "ready",
    schema_version: str = DEFAULT_SCHEMA_VERSION,
    generated_at: str | None = None,
    producer: str | None = None,
) -> dict[str, Any]:
    if artifact_class not in ARTIFACT_CLASSES:
        raise ValueError(f"Unsupported artifact class: {artifact_class}")
    if artifact_class == "output" and output_family and output_family not in OUTPUT_FAMILIES:
        raise ValueError(f"Unsupported output family: {output_family}")
    metadata = {
        "workflow": workflow,
        "artifact_name": artifact_name,
        "artifact_class": artifact_class,
        "output_family": output_family,
        "state_key": state_key,
        "status": status,
        "generated_at": generated_at or utc_now_isoformat(),
        "schema_version": schema_version,
        "producer": producer,
        "dependency_basis": _normalize_hashable(dict(dependency_basis)),
    }
    return {key: value for key, value in metadata.items() if value is not None}


def attach_artifact_metadata(payload: Mapping[str, Any], metadata: Mapping[str, Any]) -> dict[str, Any]:
    enriched = dict(payload)
    enriched["artifact_metadata"] = dict(metadata)
    return enriched


def artifact_metadata(payload: Mapping[str, Any]) -> dict[str, Any] | None:
    metadata = payload.get("artifact_metadata")
    return dict(metadata) if isinstance(metadata, Mapping) else None


def artifact_is_stale(existing_metadata: Mapping[str, Any] | None, *, expected_state_key: str) -> bool:
    if not existing_metadata:
        return True
    return str(existing_metadata.get("state_key") or "") != expected_state_key


def read_fetch_state_key(provenance_doc: Mapping[str, Any]) -> str:
    """Stage 11.1 — read Stage 1's state-key from a fetch provenance doc.

    Accepts both the new ``fetch_state_key`` field name (Stage 11.1+) and
    the legacy ``state_key`` field (pre-Stage-11.1 artefacts on disk),
    so the rename can roll out without invalidating existing local
    provenance files. A :class:`DeprecationWarning` fires on every
    legacy-field read so grepping the project logs surfaces every stale
    artefact.

    Note: the rename is **field-name only** — the Python ``state_key``
    variable across stages and the generic ``state_key`` field inside
    ``build_artifact_metadata`` are intentionally unchanged. Only
    Stage 1's fetch-stage provenance + checkpoint top-level field is
    renamed (it collided verbally with Stage 6's ``corpus_state_key``).
    """

    if "fetch_state_key" in provenance_doc:
        return str(provenance_doc["fetch_state_key"])
    if "state_key" in provenance_doc:
        import warnings

        warnings.warn(
            "Stage 1 provenance uses legacy 'state_key' field; "
            "future fetches emit 'fetch_state_key'. See "
            "specs/012-stage11-followups/research.md R6.",
            DeprecationWarning,
            stacklevel=2,
        )
        return str(provenance_doc["state_key"])
    raise KeyError(
        "no fetch state-key found in provenance doc "
        "(expected 'fetch_state_key' or legacy 'state_key')"
    )


def regeneration_action(existing_metadata: Mapping[str, Any] | None, *, expected_state_key: str) -> str:
    if not existing_metadata:
        return "full_rebuild"
    current_state_key = str(existing_metadata.get("state_key") or "")
    status = str(existing_metadata.get("status") or "")
    if current_state_key == expected_state_key and status in {"running", "error"}:
        return "resume"
    if current_state_key == expected_state_key:
        return "resume"
    return "selective_rebuild"
