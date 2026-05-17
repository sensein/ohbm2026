"""Stage 4 provenance writer.

Mirrors the Stage 1 / Stage 2.1 / Stage 3 pattern. Two surfaces:

- `assert_path_safe(p)` / `assert_paths_safe([…])` — refuse absolute
  or `~`-prefixed paths (Principle VIII / CA-008).
- `write_bundle_provenance(path, payload)` — atomic write of a
  per-bundle `provenance.json` carrying the
  `corpus_state_key → input_source_assembly_hash → algorithm_config →
  cache_key` input-hash chain plus the code revision + command + seed.
- `write_run_provenance(path, payload)` — atomic write of the
  run-level summary at `data/provenance/analysis/<kind>__<state-key>.json`.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Iterable

from ohbm2026.exceptions import ProvenanceError

__all__ = [
    "PROVENANCE_SCHEMA_VERSION",
    "assert_path_safe",
    "assert_paths_safe",
    "write_bundle_provenance",
    "write_run_provenance",
]


PROVENANCE_SCHEMA_VERSION = "stage4.provenance.v1"


def assert_path_safe(path: str | Path, *, field: str = "path") -> None:
    """Raise `ProvenanceError` if `path` is empty, absolute, or starts with `~`.

    The Stage 4 contract enforces the same path-safety rule as
    Stages 1–3 so bundles + provenance records stay portable across
    machines.
    """
    s = str(path)
    if not s:
        raise ProvenanceError(f"{field} is empty")
    if s.startswith("/") or s.startswith("~"):
        raise ProvenanceError(
            f"{field} must be project-relative (no leading '/' or '~'): {s!r}"
        )
    # Normalized path may still escape via ../ chains; reject those too.
    normalized = os.path.normpath(s)
    if normalized.startswith(".." + os.sep) or normalized == "..":
        raise ProvenanceError(
            f"{field} must not escape the project root: {s!r}"
        )


def assert_paths_safe(
    paths: Iterable[str | Path], *, field: str = "paths"
) -> None:
    for p in paths:
        assert_path_safe(p, field=field)


def _atomic_write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8"
    )
    tmp.replace(path)


def _validate_bundle_payload(payload: dict) -> None:
    required = {
        "schema_version",
        "stage",
        "kind",
        "bundle_path",
        "corpus_state_key",
        "input_source_assembly_hash",
        "algorithm_config_canonical_json",
        "cache_key",
        "code_revision",
        "command",
        "seed",
        "started_at",
        "completed_at",
    }
    missing = required - payload.keys()
    if missing:
        raise ProvenanceError(
            f"bundle provenance missing required fields: {sorted(missing)}"
        )
    assert_path_safe(payload["bundle_path"], field="bundle_path")


def _validate_run_payload(payload: dict) -> None:
    required = {
        "schema_version",
        "stage",
        "run_state_key",
        "corpus_state_key",
        "requested_models",
        "requested_inputs",
        "requested_kinds",
        "seed",
        "skip_llm_topics",
        "strict_matrix",
        "command_line",
        "code_revision",
        "started_at",
        "completed_at",
        "wall_clock_seconds",
        "cache_root",
        "rollup_path",
        "bundles",
    }
    missing = required - payload.keys()
    if missing:
        raise ProvenanceError(
            f"run provenance missing required fields: {sorted(missing)}"
        )
    assert_path_safe(payload["cache_root"], field="cache_root")
    assert_path_safe(payload["rollup_path"], field="rollup_path")
    for entry in payload["bundles"]:
        bundle_path = entry.get("bundle_path")
        if bundle_path is None:
            raise ProvenanceError("bundle entry missing 'bundle_path'")
        assert_path_safe(bundle_path, field="bundles[].bundle_path")


def write_bundle_provenance(path: Path, payload: dict) -> Path:
    """Validate + atomically write a per-bundle `provenance.json`."""
    payload = dict(payload)
    payload.setdefault("schema_version", PROVENANCE_SCHEMA_VERSION)
    payload.setdefault("stage", "analysis")
    _validate_bundle_payload(payload)
    _atomic_write_json(Path(path), payload)
    return Path(path)


def write_run_provenance(path: Path, payload: dict) -> Path:
    """Validate + atomically write the Stage 4 run-level provenance JSON."""
    payload = dict(payload)
    payload.setdefault("schema_version", PROVENANCE_SCHEMA_VERSION)
    payload.setdefault("stage", "analysis")
    _validate_run_payload(payload)
    _atomic_write_json(Path(path), payload)
    return Path(path)
