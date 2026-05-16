"""Stage 4 orchestrator — `ohbmcli analyze-matrix`.

Iterates the `(model, input_source, analysis_kind)` matrix, dispatches
to per-kind runners, writes per-bundle artifacts atomically, and emits
the canonical `data/outputs/analysis/annotations__<state-key>.{parquet,
sqlite}` rollup.

Per spec FR-001 / FR-002 / FR-003 / FR-014 / FR-017:

- Single canonical CLI entrypoint (`ohbmcli analyze-matrix`).
- Default matrix is **34 bundles** (5 models × 2 inputs × 4 kinds, with
  `neuroscape_clusters` auto-skipped for minilm/openai/pubmedbert
  because the published Stage-2 lens is Voyage-dim-specific).
- Per-analysis cache keyed by `sha256(input_matrix_hash ||
  algorithm_config || seed || prompt_version_when_applicable)`.
- One JSON-per-line bundle summary on stdout, plus a final
  `matrix_complete` line — consistent with Stage 3's contract.
- Refuses to overwrite a bundle whose recorded `corpus_state_key`
  differs from the current run's (FR-013).

The per-kind runners (`projections`, `communities`,
`neuroscape_clusters`, `topic_clusters`) live in their own submodules
and register themselves via `KIND_RUNNERS`. Kinds without a registered
runner raise `NotImplementedError` when dispatched.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any, Callable, Iterable

import numpy as np

from ohbm2026.analyze.provenance import (
    write_bundle_provenance,
    write_run_provenance,
)
from ohbm2026.analyze.rollup import (
    load_neuroscape_cluster_table,
    write_rollup,
)
from ohbm2026.exceptions import AnalysisError, InputBundleMissing

__all__ = [
    "DEFAULT_MODELS",
    "DEFAULT_INPUTS",
    "DEFAULT_KINDS",
    "NEUROSCAPE_COMPATIBLE_MODELS",
    "AnalysisConfig",
    "MatrixPlan",
    "PlanEntry",
    "KIND_RUNNERS",
    "build_plan",
    "run_matrix",
    "main",
]


DEFAULT_MODELS = ("voyage", "minilm", "openai", "pubmedbert", "neuroscape")
DEFAULT_INPUTS = ("abstract", "claims", "methods")
DEFAULT_KINDS = ("projections", "communities", "neuroscape_clusters", "topic_clusters")
NEUROSCAPE_COMPATIBLE_MODELS = frozenset({"neuroscape"})


@dataclass(frozen=True)
class AnalysisConfig:
    """Resolved run config — every flag from contracts/cli.md after parsing."""

    embeddings_root: Path
    output_root: Path
    cache_root: Path
    provenance_root: Path
    corpus_state_key: str
    models: tuple[str, ...]
    inputs: tuple[str, ...]
    kinds: tuple[str, ...]
    seed: int = 42
    skip_llm_topics: bool = False
    strict_matrix: bool = False
    invalidate_kinds: frozenset[str] = frozenset()
    rollup_path: Path | None = None
    sqlite_path: Path | None = None
    neuroscape_centroids_dir: Path = Path("data/inputs/neuroscape")
    code_revision: str = ""
    command_line: str = ""
    env_file: Path = Path(".env")
    dry_run: bool = False
    n_jobs: int = -1  # joblib semantics: -1 = all cores, 1 = serial


@dataclass(frozen=True)
class PlanEntry:
    """One cell of the matrix: a `(model, input, kind)` triple plus the
    resolved input bundle path."""

    model_key: str
    input_source: str
    kind: str
    bundle_path: Path
    skipped: bool = False
    skip_reason: str = ""


@dataclass
class MatrixPlan:
    """The full resolved plan: entries to run plus pre-flight diagnostics."""

    entries: list[PlanEntry] = field(default_factory=list)
    run_state_key: str = ""


# ---------------------------------------------------------------------------
# Dispatch registry
# ---------------------------------------------------------------------------

KindRunner = Callable[[AnalysisConfig, PlanEntry], dict[str, Any]]
KIND_RUNNERS: dict[str, KindRunner] = {}


def register_kind_runner(kind: str, runner: KindRunner) -> None:
    """Register a runner for an analysis kind. Used by per-kind submodules."""
    KIND_RUNNERS[kind] = runner


# ---------------------------------------------------------------------------
# Plan resolution
# ---------------------------------------------------------------------------


def _resolve_corpus_state_key(embeddings_root: Path, explicit: str | None) -> str:
    """Auto-detect the corpus state key from the embeddings root if not
    explicitly provided. Fails loudly when ambiguous."""
    if explicit:
        return explicit
    state_keys: set[str] = set()
    if not embeddings_root.exists():
        return ""
    for model_dir in embeddings_root.iterdir():
        if not model_dir.is_dir() or model_dir.name.startswith("."):
            continue
        for bundle_dir in model_dir.iterdir():
            if not bundle_dir.is_dir() or "__" not in bundle_dir.name:
                continue
            if bundle_dir.name.endswith(".prev"):
                continue
            state_keys.add(bundle_dir.name.split("__", 1)[1])
    if not state_keys:
        return ""
    if len(state_keys) > 1:
        raise AnalysisError(
            f"Cannot auto-detect corpus_state_key: multiple state keys present under "
            f"{embeddings_root}: {sorted(state_keys)}. Pass --corpus-state-key explicitly."
        )
    return next(iter(state_keys))


def _input_bundle_path(
    config: AnalysisConfig, model_key: str, input_source: str
) -> Path:
    """Stage 3 per-component bundle path for `(model, component)`.

    Note: the `abstract` recipe is composed at consumption time from
    `(title, introduction, methods, results, conclusion)`; in that case
    we use the first component (`title`) as the existence sentinel and
    let the per-kind runner pull the full recipe via
    `embed.compose.compose_recipe`. For all other input sources we
    resolve the literal Stage 3 bundle.
    """
    sentinel = "title" if input_source == "abstract" else input_source
    return (
        config.embeddings_root
        / model_key
        / f"{sentinel}__{config.corpus_state_key}"
    )


def build_plan(config: AnalysisConfig) -> MatrixPlan:
    """Resolve the full matrix into a list of `PlanEntry` instances.

    Pre-flight validation:
    - Every `(model, input)` referenced MUST resolve to a Stage 3 bundle
      on disk (`InputBundleMissing` otherwise).
    - `(model, neuroscape_clusters)` is auto-skipped for `model != "neuroscape"`
      because the published NeuroScape centroids live in the
      domain-embedding space (FR-002). `strict_matrix=True` turns the
      skip into a typed error.
    """
    plan = MatrixPlan()
    for model in config.models:
        for input_source in config.inputs:
            bundle_path = _input_bundle_path(config, model, input_source)
            if not bundle_path.exists():
                raise InputBundleMissing(
                    f"Stage 3 bundle not found for ({model}, {input_source}): "
                    f"expected {bundle_path}"
                )
            for kind in config.kinds:
                if kind == "neuroscape_clusters" and model not in NEUROSCAPE_COMPATIBLE_MODELS:
                    if config.strict_matrix:
                        raise AnalysisError(
                            f"--strict-matrix: ({model}, neuroscape_clusters) — "
                            f"this kind only runs for `model == 'neuroscape'`. "
                            f"The published NeuroScape centroids live in the "
                            f"domain-embedding space; consume the Stage 3 "
                            f"neuroscape bundle directly."
                        )
                    plan.entries.append(
                        PlanEntry(
                            model_key=model,
                            input_source=input_source,
                            kind=kind,
                            bundle_path=bundle_path,
                            skipped=True,
                            skip_reason="non_neuroscape_source",
                        )
                    )
                    continue
                plan.entries.append(
                    PlanEntry(
                        model_key=model,
                        input_source=input_source,
                        kind=kind,
                        bundle_path=bundle_path,
                    )
                )

    plan.run_state_key = _compute_run_state_key(config)
    return plan


def _compute_run_state_key(config: AnalysisConfig) -> str:
    """12-char hex derived from the canonical run config (so two runs
    with different configs land at different output paths)."""
    payload = {
        "corpus_state_key": config.corpus_state_key,
        "models": list(config.models),
        "inputs": list(config.inputs),
        "kinds": list(config.kinds),
        "seed": config.seed,
        "skip_llm_topics": config.skip_llm_topics,
        "strict_matrix": config.strict_matrix,
        "code_revision": config.code_revision,
    }
    blob = json.dumps(payload, sort_keys=True).encode("utf-8")
    return sha256(blob).hexdigest()[:12]


# ---------------------------------------------------------------------------
# State-key collision check
# ---------------------------------------------------------------------------


def _existing_corpus_state_key(bundle_dir: Path) -> str | None:
    """Read the recorded `corpus_state_key` from a previously-written
    bundle's `provenance.json`, returning None if absent."""
    prov_path = bundle_dir / "provenance.json"
    if not prov_path.exists():
        return None
    try:
        data = json.loads(prov_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data.get("corpus_state_key")


def _kind_state_key(
    config: AnalysisConfig, entry: PlanEntry
) -> str:
    """12-char hex per-bundle state-key. Combines corpus key, model,
    input, kind, seed, and skip_llm_topics into a deterministic digest."""
    payload = {
        "corpus_state_key": config.corpus_state_key,
        "model_key": entry.model_key,
        "input_source": entry.input_source,
        "kind": entry.kind,
        "seed": config.seed,
        "skip_llm_topics": config.skip_llm_topics,
    }
    return sha256(
        json.dumps(payload, sort_keys=True).encode("utf-8")
    ).hexdigest()[:12]


def _bundle_output_path(config: AnalysisConfig, entry: PlanEntry) -> Path:
    """`data/outputs/analysis/<model>_<input>/<kind>__<state-key>/`."""
    state_key = _kind_state_key(config, entry)
    input_key = f"{entry.model_key}_{entry.input_source}"
    return config.output_root / input_key / f"{entry.kind}__{state_key}"


# ---------------------------------------------------------------------------
# Stdout protocol
# ---------------------------------------------------------------------------


def _emit_event(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, sort_keys=True))


# ---------------------------------------------------------------------------
# Run loop
# ---------------------------------------------------------------------------


def _run_one_entry(
    config: AnalysisConfig, entry: "PlanEntry"
) -> tuple[bool, dict[str, Any], float]:
    """Execute a single runnable entry; return (ok, payload, duration_s).

    On success: `(True, runner_result_dict, duration)`.
    On failure: `(False, {"error": str(exc), "type": exc_class}, duration)`.

    No I/O on stdout — the orchestrator emits events serially in plan order
    once all entries return.
    """
    runner = KIND_RUNNERS.get(entry.kind)
    if runner is None:
        return False, {"error": "runner_not_registered", "type": "AnalysisError"}, 0.0
    start = time.monotonic()
    try:
        result = runner(config, entry)
    except Exception as exc:  # noqa: BLE001
        return (
            False,
            {"error": str(exc), "type": exc.__class__.__name__},
            time.monotonic() - start,
        )
    return True, result, time.monotonic() - start


def _run_entries_parallel(
    config: AnalysisConfig,
    runnable: list[tuple["PlanEntry", Path]],
) -> list[tuple[bool, dict[str, Any], float]]:
    """Run all entries with joblib (or serially when `n_jobs == 1`).

    Workers are independent (each bundle writes its own directory; topic
    cache writes are atomic temp+rename). Result list is plan-ordered.
    """
    if not runnable:
        return []
    if config.n_jobs == 1 or len(runnable) == 1:
        return [_run_one_entry(config, entry) for entry, _ in runnable]

    try:
        from joblib import Parallel, delayed
    except ImportError:
        # Graceful: joblib should be present (declared in [analysis] extra)
        # but if missing we fall back to serial rather than crashing.
        return [_run_one_entry(config, entry) for entry, _ in runnable]

    return Parallel(n_jobs=config.n_jobs, backend="loky")(
        delayed(_run_one_entry)(config, entry) for entry, _ in runnable
    )


def run_matrix(config: AnalysisConfig) -> int:
    """Iterate the matrix, run each entry, write rollup, return exit code.

    Returns:
        0 — all entries succeeded or skipped (legit dim-incompat skip)
        1 — at least one entry failed
        2 — pre-flight failure (input bundle missing, etc.)
    """
    started_at = datetime.now(timezone.utc).isoformat()
    start_wall = time.monotonic()

    try:
        plan = build_plan(config)
    except InputBundleMissing as e:
        _emit_event({"event": "preflight_error", "error": str(e), "type": "InputBundleMissing"})
        return 2
    except AnalysisError as e:
        _emit_event({"event": "preflight_error", "error": str(e), "type": e.__class__.__name__})
        return 2

    if config.dry_run:
        _emit_event({
            "event": "dry_run_plan",
            "run_state_key": plan.run_state_key,
            "n_entries": len(plan.entries),
            "n_to_run": sum(1 for e in plan.entries if not e.skipped),
            "n_skipped": sum(1 for e in plan.entries if e.skipped),
            "entries": [
                {
                    "input_key": f"{e.model_key}_{e.input_source}",
                    "kind": e.kind,
                    "skipped": e.skipped,
                    "skip_reason": e.skip_reason,
                    "bundle_output_path": str(_bundle_output_path(config, e).relative_to(Path.cwd())) if _bundle_output_path(config, e).is_absolute() else str(_bundle_output_path(config, e)),
                }
                for e in plan.entries
            ],
        })
        return 0

    bundles_written = 0
    bundles_cached = 0
    bundles_skipped = 0
    bundle_records: list[dict[str, Any]] = []
    any_failure = False

    # Split into skip/collision events (emitted in plan order, no work) and
    # the runnable list (dispatched via joblib).
    runnable: list[tuple[PlanEntry, Path]] = []
    for entry in plan.entries:
        if entry.skipped:
            _emit_event({
                "event": "bundle_skipped",
                "input_key": f"{entry.model_key}_{entry.input_source}",
                "kind": entry.kind,
                "reason": entry.skip_reason,
                "required_source_model": "neuroscape",
                "actual_source_model": entry.model_key,
            })
            bundles_skipped += 1
            continue

        out_path = _bundle_output_path(config, entry)
        existing_key = _existing_corpus_state_key(out_path)
        if existing_key and existing_key != config.corpus_state_key:
            _emit_event({
                "event": "bundle_skipped",
                "input_key": f"{entry.model_key}_{entry.input_source}",
                "kind": entry.kind,
                "reason": "corpus_state_key_collision",
                "existing_corpus_state_key": existing_key,
                "requested_corpus_state_key": config.corpus_state_key,
            })
            any_failure = True
            continue

        runner = KIND_RUNNERS.get(entry.kind)
        if runner is None:
            _emit_event({
                "event": "bundle_skipped",
                "input_key": f"{entry.model_key}_{entry.input_source}",
                "kind": entry.kind,
                "reason": "runner_not_registered",
            })
            bundles_skipped += 1
            continue

        runnable.append((entry, out_path))

    results = _run_entries_parallel(config, runnable)

    for (entry, out_path), bundle_result in zip(runnable, results):
        ok, payload, duration = bundle_result
        if not ok:
            _emit_event({
                "event": "bundle_error",
                "input_key": f"{entry.model_key}_{entry.input_source}",
                "kind": entry.kind,
                "error": payload["error"],
                "type": payload["type"],
            })
            any_failure = True
            continue

        if payload.get("cache") == "hit":
            bundles_cached += 1
        else:
            bundles_written += 1

        bundle_records.append(
            {
                "bundle_path": str(out_path.relative_to(Path.cwd())) if out_path.is_absolute() and Path.cwd() in out_path.parents else str(out_path),
                "kind": entry.kind,
                "model": entry.model_key,
                "input_source": entry.input_source,
                "cache": payload.get("cache", "miss"),
            }
        )
        _emit_event({
            "event": "bundle_complete",
            "input_key": f"{entry.model_key}_{entry.input_source}",
            "kind": entry.kind,
            "bundle_path": str(out_path),
            "cache": payload.get("cache", "miss"),
            "duration_seconds": round(duration, 2),
            **{k: v for k, v in payload.items() if k != "cache"},
        })

    # Rollup write
    rollup_path = config.rollup_path or (
        config.output_root / f"annotations__{config.corpus_state_key}.parquet"
    )
    sqlite_path = config.sqlite_path or rollup_path.with_suffix(".sqlite")
    nsc_table = load_neuroscape_cluster_table(
        config.neuroscape_centroids_dir / "cluster_table.csv"
    )
    write_rollup(
        config.output_root,
        parquet_path=rollup_path,
        sqlite_path=sqlite_path,
        neuroscape_cluster_table=nsc_table,
    )

    completed_at = datetime.now(timezone.utc).isoformat()
    wall_clock = time.monotonic() - start_wall

    # Run-level provenance
    provenance_path = (
        config.provenance_root
        / f"analysis_run_provenance__{plan.run_state_key}.json"
    )
    write_run_provenance(
        provenance_path,
        {
            "run_state_key": plan.run_state_key,
            "corpus_state_key": config.corpus_state_key,
            "requested_models": list(config.models),
            "requested_inputs": list(config.inputs),
            "requested_kinds": list(config.kinds),
            "seed": config.seed,
            "skip_llm_topics": config.skip_llm_topics,
            "strict_matrix": config.strict_matrix,
            "command_line": config.command_line,
            "code_revision": config.code_revision,
            "started_at": started_at,
            "completed_at": completed_at,
            "wall_clock_seconds": round(wall_clock, 2),
            "cache_root": str(_to_project_relative(config.cache_root)),
            "rollup_path": str(_to_project_relative(rollup_path)),
            "bundles": bundle_records,
        },
    )

    _emit_event({
        "event": "matrix_complete",
        "run_state_key": plan.run_state_key,
        "bundles_written": bundles_written,
        "bundles_cached": bundles_cached,
        "bundles_skipped": bundles_skipped,
        "rollup_path": str(rollup_path),
        "sqlite_path": str(sqlite_path),
        "duration_seconds": round(wall_clock, 2),
    })

    return 1 if any_failure else 0


def _to_project_relative(p: Path) -> Path:
    """Return `p` relative to the current working directory if possible,
    otherwise return as-is. The provenance writer's path-safe check will
    reject any path that didn't make it to project-relative form."""
    try:
        return Path(p).resolve().relative_to(Path.cwd().resolve())
    except (ValueError, OSError):
        return Path(p)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _git_rev_parse_head() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True, stderr=subprocess.DEVNULL
        ).strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return ""


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="ohbmcli analyze-matrix",
        description="Stage 4 canonical analysis & annotation matrix.",
    )
    p.add_argument("--env-file", type=Path, default=Path(".env"))
    p.add_argument("--embeddings-root", type=Path, default=Path("data/outputs/embeddings"))
    p.add_argument("--corpus-state-key", default=None)
    p.add_argument("--models", nargs="+", default=list(DEFAULT_MODELS))
    p.add_argument("--inputs", nargs="+", default=list(DEFAULT_INPUTS))
    p.add_argument("--kinds", nargs="+", default=list(DEFAULT_KINDS))
    p.add_argument("--skip-llm-topics", action="store_true")
    p.add_argument("--scispacy", action="store_true")
    p.add_argument("--strict-matrix", action="store_true")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--cache-root", type=Path, default=Path("data/cache/analysis"))
    p.add_argument("--invalidate", action="append", default=[], choices=list(DEFAULT_KINDS))
    p.add_argument("--output-root", type=Path, default=Path("data/outputs/analysis"))
    p.add_argument("--rollup-path", type=Path, default=None)
    p.add_argument("--provenance-root", type=Path, default=Path("data/provenance/analysis"))
    p.add_argument("--neuroscape-centroids", type=Path, default=Path("data/inputs/neuroscape"))
    p.add_argument("--code-revision", default=None)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--log-level", default="INFO")
    p.add_argument(
        "--n-jobs", type=int, default=-1,
        help="Parallel workers (joblib): -1 = all cores (default), 1 = serial. "
             "Per-bundle work is independent; each worker fits its own UMAP / "
             "FAISS+Leiden / HDBSCAN; recommend constraining "
             "OMP_NUM_THREADS=1 when n_jobs > 1 to avoid OpenMP oversubscription."
    )
    # Hyperparameters — declared for argparse completeness; per-kind
    # runners consume them via config.
    p.add_argument("--umap-n-neighbors", type=int, default=15)
    p.add_argument("--umap-min-dist", type=float, default=0.1)
    p.add_argument("--umap-metric", default="cosine")
    p.add_argument("--community-knn-k", type=int, default=30)
    p.add_argument("--community-resolution-min", type=float, default=0.001)
    p.add_argument("--community-resolution-max", type=float, default=0.1)
    p.add_argument("--community-resolution-points", type=int, default=20)
    p.add_argument("--n-topics", default="auto")
    p.add_argument("--topic-llm-model-id", default="gpt-5.4-mini")
    p.add_argument("--topic-prompt-version", default="v1")
    return p


def _load_env_file(env_path: Path) -> dict[str, str]:
    """Load `.env` and seed `os.environ` for keys the runners need (only
    `OPENAI_API_KEY` for the topic-grouping LLM call); the rest stays
    in-memory. Existing `os.environ` values win (Principle V — never
    overwrite an exported secret)."""
    if not env_path.exists():
        return {}
    values: dict[str, str] = {}
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        key = k.strip()
        val = v.strip().strip('"').strip("'")
        values[key] = val
        if key == "OPENAI_API_KEY" and not os.environ.get(key):
            os.environ[key] = val
    return values


def main(argv: list[str] | None = None) -> int:
    """Entry point — parse argv, build config, dispatch run_matrix."""
    parser = build_parser()
    args = parser.parse_args(argv)

    _load_env_file(args.env_file)  # currently informational; per-kind runners read what they need

    embeddings_root = args.embeddings_root
    try:
        corpus_state_key = _resolve_corpus_state_key(
            embeddings_root, args.corpus_state_key
        )
    except AnalysisError as e:
        _emit_event({"event": "preflight_error", "error": str(e), "type": "AnalysisError"})
        return 2

    config = AnalysisConfig(
        embeddings_root=args.embeddings_root,
        output_root=args.output_root,
        cache_root=args.cache_root,
        provenance_root=args.provenance_root,
        corpus_state_key=corpus_state_key,
        models=tuple(args.models),
        inputs=tuple(args.inputs),
        kinds=tuple(args.kinds),
        seed=args.seed,
        skip_llm_topics=args.skip_llm_topics,
        strict_matrix=args.strict_matrix,
        invalidate_kinds=frozenset(args.invalidate),
        rollup_path=args.rollup_path,
        sqlite_path=args.rollup_path.with_suffix(".sqlite") if args.rollup_path else None,
        neuroscape_centroids_dir=args.neuroscape_centroids,
        code_revision=args.code_revision or _git_rev_parse_head(),
        command_line=" ".join(sys.argv if argv is None else ["ohbmcli", "analyze-matrix"] + list(argv)),
        env_file=args.env_file,
        dry_run=args.dry_run,
        n_jobs=args.n_jobs,
    )
    return run_matrix(config)


if __name__ == "__main__":
    raise SystemExit(main())
