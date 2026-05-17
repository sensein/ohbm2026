"""Build ``data/manifest.json`` for Stage 6 (T011).

The manifest is the entry point shard the SvelteKit site fetches first. It
declares the schema version, build provenance, cell catalog, facet catalog,
and search-asset URLs.

Per CA-007 the catalogs (models / inputs / cells / facets) MUST be discovered
at build time from the Stage 4 rollup + corpus. No hardcoded lists.
"""

from __future__ import annotations

import sqlite3
import subprocess
from collections.abc import Iterable, Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ohbm2026.ui_data.state_key import (
    Stage6BuildError,
    discover_corpus_state_key,
    discover_rollup_state_key,
)

SCHEMA_VERSION = "ui.v1"
DEFAULT_CELL = {"model": "neuroscape", "input": "abstract"}

# Facet keys whose options come straight from per-abstract values (no regex)
# — emitted by the abstracts builder under the `facets` block of each record.
FACET_KEYS: tuple[str, ...] = (
    "accepted_for",
    "primary_topic",
    "secondary_topic",
    "keywords",
    "methods",
    "study_type",
    "population",
    "field_strength",
    "processing_packages",
    "species",
    "recording_technology",
    "brain_regions",
    "brain_networks",
)

# Human-readable labels — keep parallel with FACET_KEYS so the discovery
# function below stays a single source of truth. (Not a hardcoded value
# *list*; it's a key→label mapping.)
FACET_LABELS: Mapping[str, str] = {
    "accepted_for": "Accepted for",
    "primary_topic": "Primary topic",
    "secondary_topic": "Secondary topic",
    "keywords": "Keywords",
    "methods": "Methods",
    "study_type": "Study type",
    "population": "Population",
    "field_strength": "Field strength",
    "processing_packages": "Processing packages",
    "species": "Species",
    "recording_technology": "Recording technology",
    "brain_regions": "Brain regions",
    "brain_networks": "Brain networks",
}


def _git_revision(repo_root: Path | None = None) -> str:
    """Return the current git HEAD SHA. Best-effort; raises on failure."""

    root = repo_root or Path.cwd()
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
            cwd=root,
        )
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        raise Stage6BuildError(
            f"Failed to read git HEAD revision at {root}: {exc}"
        ) from exc
    return out.stdout.strip()


def make_build_info(
    *,
    corpus_path: Path,
    rollup_db: Path,
    analysis_root: Path | None = None,
    code_revision: str | None = None,
    built_at: str | None = None,
) -> dict[str, str]:
    """Assemble the ``build_info`` block embedded into every shard.

    Per FR-019 + FR-022 + CA-008. The 7-char short SHA enables the page-footer
    affordance to display the committish without revealing the full hash.
    """

    sha = code_revision or _git_revision()
    rollup_state_key = (
        discover_rollup_state_key(analysis_root) if analysis_root else _state_key_from_filename(rollup_db)
    )
    return {
        "corpus_state_key": discover_corpus_state_key(corpus_path),
        "code_revision": sha,
        "code_revision_short": sha[:7] if sha else "",
        "stage4_rollup_state_key": rollup_state_key,
        "built_at": built_at or datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


def _state_key_from_filename(rollup_db: Path) -> str:
    """Extract the state-key suffix from ``annotations__<key>.sqlite``."""

    stem = Path(rollup_db).stem
    prefix = "annotations__"
    if not stem.startswith(prefix):
        raise Stage6BuildError(
            f"Unexpected rollup filename: {rollup_db} (must match annotations__<key>.sqlite)"
        )
    return stem[len(prefix):]


def discover_cells(rollup_db: Path) -> list[tuple[str, str]]:
    """Return distinct ``(model_key, input_source)`` pairs from cluster_topics."""

    with sqlite3.connect(str(rollup_db)) as conn:
        rows = conn.execute(
            "SELECT DISTINCT model_key, input_source FROM cluster_topics ORDER BY 1, 2"
        ).fetchall()
    return [(m, i) for m, i in rows]


def discover_topic_kinds(rollup_db: Path) -> list[tuple[str, str, str]]:
    """Return distinct ``(clustering_method, model_key, input_source)`` triples."""

    with sqlite3.connect(str(rollup_db)) as conn:
        rows = conn.execute(
            "SELECT DISTINCT clustering_method, model_key, input_source FROM cluster_topics ORDER BY 1, 2, 3"
        ).fetchall()
    return [(k, m, i) for k, m, i in rows]


def _facet_options(
    abstracts: Iterable[dict[str, Any]], key: str
) -> list[str]:
    """Discover the alphabetical set of distinct option strings for a facet key.

    `accepted_for` keeps program-order (single value typically) so it's the
    one exception; primary/secondary_topic and the others are sorted.
    """

    seen: set[str] = set()
    for record in abstracts:
        facets = record.get("facets") or {}
        if key in ("primary_topic", "secondary_topic"):
            val = (record.get("topics") or {}).get(
                "primary" if key == "primary_topic" else "secondary"
            )
            if val:
                seen.add(str(val))
            continue
        if key == "accepted_for":
            val = record.get("accepted_for")
            if val:
                seen.add(str(val))
            continue
        value = facets.get(key)
        if isinstance(value, list):
            for item in value:
                if item:
                    seen.add(str(item))
        elif isinstance(value, str) and value:
            seen.add(value)
    return sorted(seen)


def build_manifest(
    *,
    abstracts: list[dict[str, Any]],
    rollup_db: Path,
    build_info: Mapping[str, str],
) -> dict[str, Any]:
    """Assemble the manifest dict per data-model.md §1.

    Discovers cells + topic kinds from the rollup; discovers facet options
    from the corpus. The output is JSON-serializable.
    """

    cells = discover_cells(rollup_db)
    topic_kinds = discover_topic_kinds(rollup_db)

    # Build per-cell topic-shard URL map.
    topic_map: dict[tuple[str, str], dict[str, str]] = {}
    for kind, model, inp in topic_kinds:
        topic_map.setdefault((model, inp), {})[kind] = (
            f"data/topics/{model}_{inp}_{kind}.json"
        )

    cell_entries: list[dict[str, Any]] = []
    for model, inp in cells:
        cell_key = f"{model}_{inp}"
        cell_entries.append(
            {
                "cell_key": cell_key,
                "model": model,
                "input": inp,
                "shard_url": f"data/cells/{cell_key}.json",
                "topic_shards": topic_map.get((model, inp), {}),
            }
        )

    models = sorted({m for m, _ in cells})
    inputs = sorted({i for _, i in cells})

    facet_entries = [
        {
            "key": key,
            "label": FACET_LABELS[key],
            "options": _facet_options(abstracts, key),
        }
        for key in FACET_KEYS
    ]

    return {
        "schema_version": SCHEMA_VERSION,
        "build_info": dict(build_info),
        "corpus_count": len(abstracts),
        "default_cell": dict(DEFAULT_CELL),
        "models": models,
        "inputs": inputs,
        "cells": cell_entries,
        "facets": facet_entries,
        "search": {
            "lexical_index": "data/search/lexical_index.json",
            "minilm_vectors": "data/search/minilm_vectors.bin",
            "minilm_vectors_build_info_url": "data/search/minilm_vectors.build_info.json",
            "minilm_dim": 384,
            "minilm_dtype": "int8",
        },
    }
