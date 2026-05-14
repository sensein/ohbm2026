"""Stage 3 provenance writer.

Mirrors the Stage 1 + Stage 2.1 pattern: provenance is a single JSON
object co-located with the artifact under a gitignored root, carrying
project-relative paths only (Principle VIII). Path safety is enforced
the same way Stage 2.1 does — refuse absolute and `~`-prefixed paths
at write time so the record stays portable across machines.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

from ohbm2026.embed import storage as embed_storage
from ohbm2026.exceptions import ProvenanceError

__all__ = [
    "PROVENANCE_SCHEMA_VERSION",
    "assert_path_safe",
    "assert_paths_safe",
    "write_run_provenance",
]


PROVENANCE_SCHEMA_VERSION = "stage3.provenance.v1"


def assert_path_safe(path: str | Path, *, field: str = "path") -> None:
    """Raise ProvenanceError if `path` is absolute or starts with `~`.

    Matches Stage 2.1's `_assert_paths_safe` contract so Stage 3
    provenance records stay portable.
    """
    s = str(path)
    if not s:
        raise ProvenanceError(f"{field} is empty")
    if s.startswith("/") or s.startswith("~"):
        raise ProvenanceError(
            f"{field} must be project-relative (no leading '/' or '~'): {s!r}"
        )


def assert_paths_safe(paths: Iterable[str | Path], *, field: str = "paths") -> None:
    for p in paths:
        assert_path_safe(p, field=field)


def _validate_payload(payload: dict) -> None:
    required = {
        "schema_version", "state_key", "corpus_state_key", "corpus_source_path",
        "corpus_source_hash", "command_line", "code_revision", "started_at",
        "completed_at", "wall_clock_seconds", "cache_version", "cache_root",
        "failure_threshold", "batch_size", "concurrency_policy",
        "env_vars_consulted", "bundles",
    }
    missing = required - payload.keys()
    if missing:
        raise ProvenanceError(
            f"provenance payload missing required fields: {sorted(missing)}"
        )
    assert_path_safe(payload["corpus_source_path"], field="corpus_source_path")
    assert_path_safe(payload["cache_root"], field="cache_root")
    for entry in payload["bundles"]:
        bundle_path = entry.get("bundle_path")
        if bundle_path is None:
            raise ProvenanceError("bundle entry missing 'bundle_path'")
        assert_path_safe(bundle_path, field=f"bundles[].bundle_path")


def write_run_provenance(path: Path, payload: dict) -> Path:
    """Validate + atomically write the Stage 3 run-level provenance JSON.

    Returns the resulting path. Raises ProvenanceError if the
    payload is malformed or carries unsafe paths.
    """
    payload = dict(payload)
    payload.setdefault("schema_version", PROVENANCE_SCHEMA_VERSION)
    _validate_payload(payload)
    embed_storage.atomic_write_json(Path(path), payload)
    return Path(path)
