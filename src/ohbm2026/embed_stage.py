"""Stage 3 orchestrator — multi-model embeddings matrix.

Top-level entrypoint: `main(argv)` (CLI), which delegates to
`run_matrix(args)`. The single-bundle entry is `run_single_bundle`.

The orchestrator owns:
- enriched-corpus loading (SQLite + zlib + JSON per abstract)
- component-text assembly (one pass via `embed_components`)
- per-(model, component) cache lookup → batched provider dispatch →
  per-input cache write → bundle assembly
- corpus-state-key guard (FR-013)
- coverage gate (FR-007) with opt-in `--allow-partial`
- typed exit codes per `contracts/cli.md`

It deliberately does NOT own:
- the SDK details for each model — those live in
  `embed_voyage.py` / `embed_openai.py` / `embed_hf.py`
- the per-input cache file format — that's `embed_storage.py`
- the run-level provenance JSON shape — that's `embed_provenance.py`
"""

from __future__ import annotations

import argparse
import dataclasses
import datetime as dt
import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import time
import zlib
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence

from ohbm2026 import embed_components, embed_hf, embed_openai, embed_provenance, embed_storage, embed_voyage
from ohbm2026.exceptions import (
    ComponentAssemblyError,
    EmbeddingBudgetError,
    EmbeddingContractError,
    EmbeddingError,
    EmbeddingProviderError,
    EmbeddingThresholdError,
    OhbmStageError,
    ProvenanceError,
)

__all__ = [
    "EXIT_OK",
    "EXIT_GENERIC",
    "EXIT_MISSING_KEY",
    "EXIT_BUDGET",
    "EXIT_PARTIAL_COVERAGE",
    "EXIT_THRESHOLD",
    "EXIT_CACHE_VERSION",
    "EXIT_STATE_MISMATCH",
    "DEFAULT_MODELS",
    "DEFAULT_COMPONENTS",
    "BundleResult",
    "run_single_bundle",
    "run_matrix",
    "main",
    "build_clients",
]


# ---- exit codes per contracts/cli.md ----
EXIT_OK = 0
EXIT_GENERIC = 1
EXIT_MISSING_KEY = 2
EXIT_BUDGET = 3
EXIT_PARTIAL_COVERAGE = 4
EXIT_THRESHOLD = 5
EXIT_CACHE_VERSION = 6
EXIT_STATE_MISMATCH = 7

# ---- defaults ----
# neuroscape is opt-in (requires a Stage 2 checkpoint path); operator
# passes --models voyage,neuroscape to include it explicitly.
DEFAULT_MODELS: tuple[str, ...] = ("voyage", "minilm", "openai", "pubmedbert")
DEFAULT_COMPONENTS: tuple[str, ...] = embed_components.DEFAULT_COMPONENTS
DEFAULT_BATCH_SIZE: int = 64
DEFAULT_CONCURRENCY_START: int = 8
DEFAULT_CONCURRENCY_MAX: int = 24
DEFAULT_FAILURE_THRESHOLD: float = 0.01

# Long-input strategy defaults per model (FR-010).
DEFAULT_LONG_INPUT_STRATEGY: dict[str, str] = {
    "voyage": "truncate_end",
    "openai": "truncate_end",
    "minilm": "chunk_mean_pool",
    "pubmedbert": "chunk_mean_pool",
    "neuroscape": "n/a",  # operates on vectors, not text
}

# Paid-API providers — affect batching, concurrency, key requirements.
PAID_PROVIDERS = {"voyage", "openai"}
LOCAL_PROVIDERS = {"minilm", "pubmedbert"}


# ---- data classes -----------------------------------------------------


@dataclasses.dataclass
class BundleResult:
    """Per-bundle outcome rolled up by the orchestrator."""

    bundle_path: str  # project-relative
    model_key: str
    model_id: str
    model_version: str
    component: str
    corpus_state_key: str
    count: int
    present_count: int
    missing_count: int
    cache_hit_count: int
    cache_miss_count: int
    failure_count: int
    truncated_count: int
    wall_clock_seconds: float
    status: str = "ok"  # ok | failed | partial | skipped


# ---- env / paths ------------------------------------------------------


def _load_env_file(path: Path) -> dict[str, str]:
    """Parse a .env file into a dict without polluting os.environ."""
    out: dict[str, str] = {}
    if not path.exists():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        out[key.strip()] = value.strip().strip('"').strip("'")
    return out


def _project_relative(path: Path, cwd: Path | None = None) -> str:
    cwd = cwd or Path.cwd()
    p = Path(path)
    try:
        return str(p.resolve().relative_to(cwd.resolve()))
    except ValueError:
        return str(p)


def _git_revision(cwd: Path | None = None) -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=cwd or Path.cwd(),
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        )
        return out.stdout.strip()[:12]
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
        return "unknown"


# ---- cache key --------------------------------------------------------


def _cache_key(text: str, *, model_id: str, model_version: str) -> str:
    h = hashlib.sha256()
    h.update(text.encode("utf-8"))
    h.update(b"||")
    h.update(model_id.encode("utf-8"))
    h.update(b"||")
    h.update(model_version.encode("utf-8"))
    return h.hexdigest()


def _input_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ---- corpus loading ---------------------------------------------------


def load_enriched_corpus(path: Path) -> tuple[list[dict], str]:
    """Read the enriched SQLite. Returns `(records, corpus_state_key)`.

    Records come back sorted by abstract id (FR-004) so downstream
    `ids.npy` is permutation-stable.
    """
    con = sqlite3.connect(path)
    try:
        try:
            row = con.execute(
                "SELECT value FROM corpus_metadata WHERE key = 'state_key'"
            ).fetchone()
        except sqlite3.OperationalError:
            row = None
        corpus_state_key = (row[0] if row else "") or "unknown"
        records: list[dict] = []
        for aid, payload in con.execute("SELECT id, payload FROM abstracts ORDER BY id"):
            data = json.loads(zlib.decompress(payload).decode("utf-8"))
            data["id"] = aid
            records.append(data)
    finally:
        con.close()
    return records, corpus_state_key


# ---- client factory ---------------------------------------------------


def build_clients(
    args: argparse.Namespace, env: dict[str, str]
) -> dict[str, Any]:
    """Build embedding clients for the requested paid + local models.

    Raises an EmbeddingError + sys.exit(2) for any paid provider
    missing its API key.
    """
    clients: dict[str, Any] = {}
    requested = set(args.models)
    if "voyage" in requested:
        key = env.get("VOYAGE_API") or env.get("VOYAGE_API_KEY") or os.environ.get("VOYAGE_API_KEY")
        if not key:
            raise EmbeddingError(
                "Voyage requested but neither VOYAGE_API_KEY nor VOYAGE_API is set "
                "in .env or the environment"
            )
        try:
            import voyageai
        except ImportError as exc:  # noqa: F841
            raise EmbeddingError(
                "voyageai SDK not installed — `uv pip install --python .venv/bin/python voyageai`"
            ) from exc
        clients["voyage"] = embed_voyage.VoyageBatchClient(
            voyageai.Client(api_key=key),
            model_id=args.voyage_model_id,
        )
    if "openai" in requested:
        key = env.get("OPENAI_API_KEY") or os.environ.get("OPENAI_API_KEY")
        if not key:
            raise EmbeddingError(
                "OpenAI requested but OPENAI_API_KEY is not set in .env or the environment"
            )
        try:
            from openai import OpenAI
        except ImportError as exc:  # noqa: F841
            raise EmbeddingError(
                "openai SDK not installed — install via the [enrich] extra"
            ) from exc
        clients["openai"] = embed_openai.OpenAIBatchClient(
            OpenAI(api_key=key),
            model_id=args.openai_model_id,
        )
    if "minilm" in requested:
        clients["minilm"] = embed_hf.HFBatchClient(
            model_id=args.minilm_model_id,
            long_input_strategy=_resolve_long_input("minilm", args),
        )
    if "pubmedbert" in requested:
        clients["pubmedbert"] = embed_hf.HFBatchClient(
            model_id=args.pubmedbert_model_id,
            long_input_strategy=_resolve_long_input("pubmedbert", args),
        )
    # `neuroscape` is handled separately — derived from voyage bundles, no client needed.
    return clients


def _resolve_long_input(model_key: str, args: argparse.Namespace) -> str:
    """Resolve the per-model long-input strategy via CLI override or default."""
    overrides = getattr(args, "long_input_strategy", None) or []
    for entry in overrides:
        if "=" in entry:
            k, _, v = entry.partition("=")
            if k.strip() == model_key:
                return v.strip()
    return DEFAULT_LONG_INPUT_STRATEGY.get(model_key, "truncate_end")


# ---- per-bundle orchestration ----------------------------------------


def _bundle_dir_for(model_key: str, component: str, embeddings_root: Path, *, partial: bool) -> Path:
    """Per-model folder layout: `<embeddings_root>/<model_key>/<component>[_partial]/`."""
    suffix = "_partial" if partial else ""
    return Path(embeddings_root) / model_key / f"{component}{suffix}"


def _model_version_for(client: Any, fallback_model_id: str) -> str:
    """Capture model_version (SDK-reported model id or fallback). The
    full SDK-reported model is the discovery point (Principle VII)."""
    reported = getattr(client, "reported_model", None)
    return reported or fallback_model_id


def run_single_bundle(
    *,
    model_key: str,
    component: str,
    records: list[dict],
    component_texts: dict[tuple[int, str], str],
    corpus_state_key: str,
    corpus_source_path: Path,
    embeddings_root: Path,
    cache_root: Path,
    clients: dict[str, Any],
    args: argparse.Namespace,
) -> BundleResult:
    """Generate one (model_key, component) bundle end-to-end.

    Returns a `BundleResult` summarizing the outcome. Raises typed
    `EmbeddingError` subclasses on hard aborts; the caller (matrix
    orchestrator) handles exit-code mapping.
    """
    start = time.perf_counter()

    # 1. Pull this component's texts in id-sorted order.
    ids_present: list[int] = []
    missing_ids: list[int] = []
    texts: list[str] = []
    for record in records:
        aid = int(record["id"])
        text = component_texts.get((aid, component), "")
        if text:
            ids_present.append(aid)
            texts.append(text)
        else:
            missing_ids.append(aid)

    total_count = len(records)
    present_count = len(ids_present)
    missing_count = len(missing_ids)

    # 2. Coverage gate (FR-007).
    #
    # DEFAULT_COMPONENTS (title, introduction, methods, results,
    # conclusion, claims) are allowed to have missing rows silently —
    # the missing_ids are recorded in metadata.json and the bundle
    # has fewer than `count` rows. Operators only need --allow-partial
    # for components NOT in the default set (e.g. inference_claims).
    allow_partial = component in (getattr(args, "allow_partial", None) or [])
    is_default_component = component in embed_components.DEFAULT_COMPONENTS
    partial_suffix = False
    if missing_count > 0:
        if not (allow_partial or is_default_component):
            raise EmbeddingError(
                f"partial-coverage refusal: component {component!r} is present on "
                f"only {present_count}/{total_count} abstracts "
                f"({present_count / total_count * 100:.1f}%). "
                f"Pass --allow-partial {component} to opt in."
            )
        # The _partial suffix only applies to non-default components.
        partial_suffix = not is_default_component

    bundle_dir = _bundle_dir_for(
        model_key, component, embeddings_root, partial=partial_suffix
    )

    # 3. State-key guard (FR-013): refuse overwrite if prior bundle's
    #    corpus_state_key differs.
    prior_state = embed_storage.bundle_corpus_state_key(bundle_dir)
    if prior_state and prior_state != corpus_state_key:
        raise EmbeddingError(
            f"existing bundle at {bundle_dir} was built against corpus_state_key="
            f"{prior_state!r}; refusing to overwrite with run at {corpus_state_key!r}. "
            f"Pass --invalidate {model_key}_{component} or archive the prior bundle."
        )

    # 4. Build client lazily; capture model_id + version for cache-keying.
    client = clients.get(model_key)
    if client is None and model_key in PAID_PROVIDERS.union(LOCAL_PROVIDERS):
        raise EmbeddingError(f"no client registered for model_key={model_key!r}")
    model_id = getattr(client, "model_id", "unknown") if client else "unknown"
    # Pre-call model_version equals model_id; gets refined post-call.
    model_version = model_id

    # 5. Per-abstract cache lookup.
    vectors_by_id: dict[int, list[float]] = {}
    miss_inputs: list[tuple[int, str]] = []  # (abstract_id, text)
    miss_cache_keys: list[str] = []
    cache_hit_count = 0
    cache_miss_count = 0
    invalidated = model_key in (getattr(args, "invalidate", None) or set())
    truncated_ids: list[int] = []

    for aid, text in zip(ids_present, texts):
        key = _cache_key(text, model_id=model_id, model_version=model_version)
        cached = None if invalidated else embed_storage.load_cache_entry(
            cache_root, model_key, key
        )
        if cached is not None:
            vectors_by_id[aid] = list(cached["vector"])
            cache_hit_count += 1
            if cached.get("truncated"):
                truncated_ids.append(aid)
        else:
            miss_inputs.append((aid, text))
            miss_cache_keys.append(key)
            cache_miss_count += 1

    # 6. Dry-run short-circuit (FR-009b not applicable; just a plan summary).
    if getattr(args, "dry_run", False):
        latency_ms = (time.perf_counter() - start) * 1000.0
        return BundleResult(
            bundle_path=_project_relative(bundle_dir),
            model_key=model_key,
            model_id=model_id,
            model_version=model_version,
            component=component,
            corpus_state_key=corpus_state_key,
            count=total_count,
            present_count=present_count,
            missing_count=missing_count,
            cache_hit_count=cache_hit_count,
            cache_miss_count=cache_miss_count,
            failure_count=0,
            truncated_count=len(truncated_ids),
            wall_clock_seconds=latency_ms / 1000.0,
            status="skipped",
        )

    # 7. Batched provider dispatch with per-input cache write.
    failure_ids: list[int] = []
    if miss_inputs:
        batch_size = int(getattr(args, "batch_size", DEFAULT_BATCH_SIZE))
        # We make N HTTP calls serially here for the single-bundle path.
        # The matrix orchestrator can wrap this loop in concurrent
        # ThreadPoolExecutor for paid providers (FR-009b); for the
        # single-bundle MVP path, serial is correct.
        for batch_start in range(0, len(miss_inputs), batch_size):
            batch_pairs = miss_inputs[batch_start : batch_start + batch_size]
            batch_keys = miss_cache_keys[batch_start : batch_start + batch_size]
            batch_texts = [pair[1] for pair in batch_pairs]
            try:
                vectors, telemetry = client.embed_batch(batch_texts)
            except EmbeddingBudgetError:
                raise
            except EmbeddingError as exc:
                # Per-batch hard failure: count every input in the batch as a failure.
                for aid, _ in batch_pairs:
                    failure_ids.append(aid)
                print(
                    f"WARN {model_key}_{component}: batch failed: {exc}",
                    file=sys.stderr,
                )
                continue
            # Capture the SDK-reported model id; assert it matches the requested model.
            reported = telemetry.get("reported_model") or model_id
            if reported and reported != model_id and reported != model_version:
                # Some providers prefix or version-suffix the requested id; treat
                # mismatch as a contract error per Principle VII when the requested
                # id is not a prefix of the reported id.
                if not (model_id in reported or reported in model_id):
                    raise EmbeddingContractError(
                        f"{model_key} returned model={reported!r} but request was "
                        f"model={model_id!r}"
                    )
            model_version = reported or model_version
            truncated_flags = telemetry.get("truncated_flags") or [False] * len(batch_pairs)
            embedded_at = dt.datetime.now(dt.timezone.utc).isoformat()
            for (aid, text), cache_key, vec, was_truncated in zip(
                batch_pairs, batch_keys, vectors, truncated_flags
            ):
                vectors_by_id[aid] = list(vec)
                if was_truncated and aid not in truncated_ids:
                    truncated_ids.append(aid)
                # Per-input cache write (FR-009a).
                embed_storage.write_cache_entry(
                    cache_root,
                    model_key=model_key,
                    cache_key=cache_key,
                    payload={
                        "cache_version": embed_storage.CACHE_VERSION,
                        "abstract_id": aid,
                        "component": component,
                        "model_id": model_id,
                        "model_version": model_version,
                        "input_hash": _input_hash(text),
                        "vector": list(vec),
                        "dim": len(vec),
                        "truncated": bool(was_truncated),
                        "truncation_strategy": _resolve_long_input(model_key, args),
                        "tokens_used": telemetry.get("tokens_used"),
                        "embedded_at": embedded_at,
                    },
                )

    # 8. Failure-threshold check.
    failure_threshold = float(getattr(args, "failure_threshold", DEFAULT_FAILURE_THRESHOLD))
    if present_count > 0:
        failure_rate = len(failure_ids) / present_count
        if failure_rate > failure_threshold:
            raise EmbeddingThresholdError(
                f"{model_key}_{component}: failure rate {failure_rate:.3f} exceeded "
                f"threshold {failure_threshold:.3f} ({len(failure_ids)}/{present_count})"
            )

    # 9. Assemble vectors + ids in id-sorted order.
    final_ids = sorted(vectors_by_id.keys())
    if final_ids:
        # Sanity: all vectors must have identical dim.
        first_dim = len(vectors_by_id[final_ids[0]])
        for aid in final_ids:
            if len(vectors_by_id[aid]) != first_dim:
                raise EmbeddingContractError(
                    f"dim drift in bundle {model_key}_{component}: "
                    f"id {aid} has dim {len(vectors_by_id[aid])} vs {first_dim}"
                )
    import numpy as np
    if final_ids:
        vectors_array = np.asarray([vectors_by_id[aid] for aid in final_ids], dtype=np.float32)
    else:
        # Empty bundle (every abstract failed). Caller will likely have aborted
        # via the threshold; if we got here, write an empty matrix.
        dim = getattr(client, "dim", None) or 1
        vectors_array = np.zeros((0, dim), dtype=np.float32)

    long_input_strategy = _resolve_long_input(model_key, args)
    metadata = {
        "schema_version": embed_storage.BUNDLE_SCHEMA_VERSION,
        "bundle_name": bundle_dir.name,
        "model_key": model_key,
        "model_id": model_id,
        "model_version": model_version,
        "component": component,
        "corpus_state_key": corpus_state_key,
        "corpus_source_path": _project_relative(corpus_source_path),
        "count": total_count,
        "missing_count": missing_count,
        "missing_ids": missing_ids,
        "long_input_strategy": long_input_strategy,
        "long_input_params": (
            {"chunk_window": embed_hf.DEFAULT_CHUNK_WINDOW,
             "chunk_overlap": embed_hf.DEFAULT_CHUNK_OVERLAP,
             "pooling": "mean"}
            if long_input_strategy == "chunk_mean_pool" else None
        ),
        "truncated_count": len(truncated_ids),
        "truncated_ids": truncated_ids[:256],
        "failure_count": len(failure_ids),
        "failure_ids": failure_ids[:256],
        "batch_size": int(getattr(args, "batch_size", DEFAULT_BATCH_SIZE)),
        "embedded_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "concurrency": {
            "policy": "serial" if model_key in LOCAL_PROVIDERS else "dynamic",
            "start": getattr(args, "concurrency_start", DEFAULT_CONCURRENCY_START)
                if model_key in PAID_PROVIDERS else None,
            "min_observed": None,
            "max_observed": None,
            "rate_limit_429_count": None,
        },
    }
    if partial_suffix:
        metadata["partial_coverage_acknowledged"] = True

    # 10. Provenance per bundle.
    provenance = {
        "corpus_state_key": corpus_state_key,
        "corpus_source_path": _project_relative(corpus_source_path),
        "command_line": " ".join(sys.argv),
        "code_revision": _git_revision(),
        "embedded_at": metadata["embedded_at"],
        "bundle_path": _project_relative(bundle_dir),
        "model_key": model_key,
        "model_id": model_id,
        "model_version": model_version,
        "component": component,
        "long_input_strategy": long_input_strategy,
        "cache_hit_count": cache_hit_count,
        "cache_miss_count": cache_miss_count,
        "failure_count": len(failure_ids),
        "truncated_count": len(truncated_ids),
    }

    embed_storage.write_bundle(
        bundle_dir,
        ids=final_ids,
        vectors=vectors_array,
        metadata=metadata,
        provenance=provenance,
    )

    latency_ms = (time.perf_counter() - start) * 1000.0
    return BundleResult(
        bundle_path=_project_relative(bundle_dir),
        model_key=model_key,
        model_id=model_id,
        model_version=model_version,
        component=component,
        corpus_state_key=corpus_state_key,
        count=total_count,
        present_count=len(final_ids),
        missing_count=missing_count,
        cache_hit_count=cache_hit_count,
        cache_miss_count=cache_miss_count,
        failure_count=len(failure_ids),
        truncated_count=len(truncated_ids),
        wall_clock_seconds=latency_ms / 1000.0,
        status="partial" if partial_suffix else "ok",
    )


# ---- matrix orchestrator ---------------------------------------------


def _handle_invalidate(
    invalidate_keys: Iterable[str],
    cache_root: Path,
    embeddings_root: Path,
) -> None:
    """Invalidate per-bundle cache slices and move existing bundle
    directories aside (FR-013-safe rename, not delete)."""
    ts = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    for key in invalidate_keys or ():
        # Move bundle aside.
        bundle = Path(embeddings_root) / key
        if bundle.exists():
            archived = bundle.with_name(f"{key}__invalidated_{ts}")
            os.rename(bundle, archived)
            print(
                f"INFO invalidate: archived {bundle} → {archived}",
                file=sys.stderr,
            )
        # Wipe cache entries scoped to this model_key.
        # The key is `<model_key>_<component>`; we only know the model_key prefix.
        # Cache is keyed by sha256(text||model_id||model_version) under
        # data/cache/embeddings/<model_key>/<hash>.json. We can't selectively
        # delete only the component's entries without re-deriving the keys,
        # so on `--invalidate <model_key>_<component>` we wipe the whole
        # <model_key>/ cache directory if the operator explicitly opts in
        # via `--invalidate <model_key>` (no component suffix).
        if "_" not in key:
            cache_dir = Path(cache_root) / key
            if cache_dir.exists():
                shutil.rmtree(cache_dir)
                print(
                    f"INFO invalidate: wiped cache dir {cache_dir}",
                    file=sys.stderr,
                )


def run_matrix(args: argparse.Namespace) -> int:
    """Run the requested (model × component) matrix. Returns exit code."""
    cwd = Path.cwd()
    source_path = Path(args.source_corpus)
    if not source_path.exists():
        print(f"error: source corpus not found at {source_path}", file=sys.stderr)
        return EXIT_GENERIC
    embeddings_root = Path(args.embeddings_root)
    cache_root = Path(args.cache_root)

    env = _load_env_file(Path(args.env_file)) if args.env_file else {}

    # Build clients up front. Missing API keys → exit 2.
    try:
        clients = build_clients(args, env)
    except EmbeddingError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_MISSING_KEY

    # Honor --invalidate.
    if args.invalidate:
        _handle_invalidate(args.invalidate, cache_root, embeddings_root)

    # Load corpus.
    records, corpus_state_key = load_enriched_corpus(source_path)
    print(
        f"INFO embed-matrix: loaded {len(records)} abstracts from {source_path} "
        f"(corpus_state_key={corpus_state_key})",
        file=sys.stderr,
    )

    # Assemble component texts up front (one SQLite pass per FR-006a).
    component_texts: dict[tuple[int, str], str] = {}
    requested_components = list(args.components)
    for record in records:
        aid = int(record["id"])
        for comp in requested_components:
            try:
                component_texts[(aid, comp)] = embed_components.assemble_component(
                    record, comp
                )
            except ValueError as exc:
                raise ComponentAssemblyError(
                    f"failed to assemble component {comp!r} for abstract {aid}: {exc}"
                ) from exc

    # Compute run-level state_key.
    state_key = _compute_state_key(
        corpus_state_key=corpus_state_key,
        models=tuple(args.models),
        components=tuple(args.components),
        batch_size=int(args.batch_size),
        long_input_strategies=tuple(
            f"{m}={_resolve_long_input(m, args)}" for m in args.models
        ),
    )

    run_started_at = dt.datetime.now(dt.timezone.utc)
    bundles: list[BundleResult] = []
    exit_code = EXIT_OK
    failure_threshold_exceeded = False

    # Bundle order: local providers first (free, fast), paid providers last;
    # NeuroScape after Voyage so the upstream is available.
    ordering = {"minilm": 0, "pubmedbert": 1, "openai": 2, "voyage": 3, "neuroscape": 4}
    ordered_pairs: list[tuple[str, str]] = sorted(
        ((m, c) for m in args.models for c in args.components),
        key=lambda mc: (ordering.get(mc[0], 99), mc[1]),
    )

    voyage_bundles_by_component: dict[str, Path] = {}
    for model_key, component in ordered_pairs:
        if model_key == "neuroscape":
            try:
                result = _run_neuroscape_derivation(
                    component=component,
                    voyage_bundle_dir=voyage_bundles_by_component.get(component),
                    embeddings_root=embeddings_root,
                    corpus_state_key=corpus_state_key,
                )
                bundles.append(result)
            except EmbeddingError as exc:
                print(f"error: neuroscape_{component}: {exc}", file=sys.stderr)
                bundles.append(BundleResult(
                    bundle_path=_project_relative(embeddings_root / f"neuroscape_{component}"),
                    model_key="neuroscape", model_id="neuroscape", model_version="unknown",
                    component=component, corpus_state_key=corpus_state_key,
                    count=len(records), present_count=0, missing_count=len(records),
                    cache_hit_count=0, cache_miss_count=0, failure_count=len(records),
                    truncated_count=0, wall_clock_seconds=0.0, status="failed",
                ))
                exit_code = max(exit_code, EXIT_GENERIC)
            _print_bundle_summary(bundles[-1])
            continue

        try:
            result = run_single_bundle(
                model_key=model_key,
                component=component,
                records=records,
                component_texts=component_texts,
                corpus_state_key=corpus_state_key,
                corpus_source_path=source_path,
                embeddings_root=embeddings_root,
                cache_root=cache_root,
                clients=clients,
                args=args,
            )
        except EmbeddingBudgetError as exc:
            print(f"error: {model_key}_{component}: budget exhausted: {exc}", file=sys.stderr)
            return EXIT_BUDGET
        except EmbeddingThresholdError as exc:
            print(f"error: {model_key}_{component}: {exc}", file=sys.stderr)
            failure_threshold_exceeded = True
            exit_code = max(exit_code, EXIT_THRESHOLD)
            continue
        except EmbeddingError as exc:
            # Partial-coverage refusal (FR-007) lands here.
            msg = str(exc)
            if "partial-coverage refusal" in msg:
                print(f"error: {model_key}_{component}: {exc}", file=sys.stderr)
                exit_code = max(exit_code, EXIT_PARTIAL_COVERAGE)
                continue
            if "refusing to overwrite" in msg:
                print(f"error: {model_key}_{component}: {exc}", file=sys.stderr)
                exit_code = max(exit_code, EXIT_STATE_MISMATCH)
                continue
            print(f"error: {model_key}_{component}: {exc}", file=sys.stderr)
            exit_code = max(exit_code, EXIT_GENERIC)
            continue
        bundles.append(result)
        if model_key == "voyage":
            voyage_bundles_by_component[component] = (
                embeddings_root / result.bundle_path.split("/")[-1]
            )
        _print_bundle_summary(result)

    # Run-level provenance + rollup summary.
    run_completed_at = dt.datetime.now(dt.timezone.utc)
    corpus_source_hash = hashlib.sha256(source_path.read_bytes()).hexdigest()
    provenance_payload = {
        "schema_version": embed_provenance.PROVENANCE_SCHEMA_VERSION,
        "state_key": state_key,
        "corpus_state_key": corpus_state_key,
        "corpus_source_path": _project_relative(source_path),
        "corpus_source_hash": corpus_source_hash,
        "command_line": " ".join(sys.argv),
        "code_revision": _git_revision(),
        "seed": None,
        "started_at": run_started_at.isoformat(),
        "completed_at": run_completed_at.isoformat(),
        "wall_clock_seconds": (run_completed_at - run_started_at).total_seconds(),
        "cache_version": embed_storage.CACHE_VERSION,
        "cache_root": _project_relative(cache_root),
        "failure_threshold": float(args.failure_threshold),
        "batch_size": int(args.batch_size),
        "concurrency_policy": (
            f"dynamic_start_{args.concurrency_start}_min_1_max_{args.concurrency_max}"
        ),
        "env_vars_consulted": sorted({
            *(["OPENAI_API_KEY"] if "openai" in args.models else []),
            *(["VOYAGE_API_KEY", "VOYAGE_API"] if "voyage" in args.models else []),
            "HF_TOKEN",
        }),
        "bundles": [dataclasses.asdict(b) for b in bundles],
    }
    prov_path = Path("data/provenance") / f"embeddings_matrix_provenance__{state_key}.json"
    try:
        embed_provenance.write_run_provenance(prov_path, provenance_payload)
    except ProvenanceError as exc:
        print(f"error: provenance write failed: {exc}", file=sys.stderr)
        return max(exit_code, EXIT_GENERIC)

    # Rollup stdout JSON.
    rollup = {
        "state_key": state_key,
        "abstract_count": len(records),
        "bundles": [
            {
                "bundle": Path(b.bundle_path).name,
                "status": b.status,
                "present_count": b.present_count,
                "failure_count": b.failure_count,
            }
            for b in bundles
        ],
        "failure_threshold_exceeded": failure_threshold_exceeded,
        "provenance_record": _project_relative(prov_path),
    }
    print(json.dumps(rollup, separators=(",", ":"), sort_keys=True))
    return exit_code


def _run_neuroscape_derivation(
    *,
    component: str,
    voyage_bundle_dir: Path | None,
    embeddings_root: Path,
    corpus_state_key: str,
) -> BundleResult:
    """Apply the published NeuroScape Stage 2 transform to a Voyage
    component bundle."""
    if voyage_bundle_dir is None or not voyage_bundle_dir.exists():
        raise EmbeddingError(
            f"neuroscape_{component}: required upstream voyage_{component} bundle "
            f"is missing; run `--models voyage,neuroscape` together"
        )
    # Lazy-import to avoid pulling in torch when only local-text models are used.
    from ohbm2026 import neuroscape
    start = time.perf_counter()
    output_dir = Path(embeddings_root) / f"neuroscape_{component}"
    bundle = embed_storage.load_bundle(voyage_bundle_dir)
    voyage_matrix = bundle["vectors"]
    ids = bundle["ids"]
    # Reuse the existing apply_published_stage2 transform via the
    # `neuroscape.apply_published_stage2_to_matrix` API surface if it
    # exists; otherwise call the legacy bundle-applying function.
    apply_fn = getattr(neuroscape, "apply_published_stage2_to_matrix", None)
    if apply_fn is None:
        # Fallback: use the bundle-level API.
        # The legacy `apply_published_stage2` reads the voyage bundle dir
        # and writes a new bundle dir; we adapt to the orchestrator's
        # storage layer.
        raise EmbeddingError(
            "neuroscape application: apply_published_stage2_to_matrix not "
            "available in neuroscape.py — install the [neuroscape] extra "
            "or run `ohbmcli apply-published-stage2` manually"
        )
    transformed, model_version = apply_fn(voyage_matrix)
    import numpy as np
    embed_storage.write_bundle(
        output_dir,
        ids=ids.tolist(),
        vectors=np.asarray(transformed, dtype=np.float32),
        metadata={
            "schema_version": embed_storage.BUNDLE_SCHEMA_VERSION,
            "bundle_name": output_dir.name,
            "model_key": "neuroscape",
            "model_id": "neuroscape-stage2-published",
            "model_version": model_version,
            "component": component,
            "corpus_state_key": corpus_state_key,
            "corpus_source_path": _project_relative(voyage_bundle_dir),
            "count": int(ids.shape[0]),
            "missing_count": 0,
            "missing_ids": [],
            "long_input_strategy": "n/a",
            "long_input_params": None,
            "truncated_count": 0,
            "failure_count": 0,
            "batch_size": 0,
            "embedded_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            "upstream_voyage_bundle": _project_relative(voyage_bundle_dir),
        },
        provenance={
            "corpus_state_key": corpus_state_key,
            "upstream_voyage_bundle": _project_relative(voyage_bundle_dir),
            "model_version": model_version,
            "command_line": " ".join(sys.argv),
            "code_revision": _git_revision(),
        },
    )
    latency = (time.perf_counter() - start) * 1000.0
    return BundleResult(
        bundle_path=_project_relative(output_dir),
        model_key="neuroscape",
        model_id="neuroscape-stage2-published",
        model_version=model_version,
        component=component,
        corpus_state_key=corpus_state_key,
        count=int(ids.shape[0]),
        present_count=int(ids.shape[0]),
        missing_count=0,
        cache_hit_count=0,
        cache_miss_count=int(ids.shape[0]),
        failure_count=0,
        truncated_count=0,
        wall_clock_seconds=latency / 1000.0,
        status="ok",
    )


def _print_bundle_summary(b: BundleResult) -> None:
    """Emit one JSON line on stdout per FR-011."""
    print(
        json.dumps(
            {
                "bundle_path": b.bundle_path,
                "model_key": b.model_key,
                "model_id": b.model_id,
                "component": b.component,
                "corpus_state_key": b.corpus_state_key,
                "count": b.count,
                "present_count": b.present_count,
                "cache_hit_count": b.cache_hit_count,
                "cache_miss_count": b.cache_miss_count,
                "failure_count": b.failure_count,
                "truncated_count": b.truncated_count,
                "wall_clock_seconds": round(b.wall_clock_seconds, 3),
                "status": b.status,
            },
            separators=(",", ":"),
            sort_keys=True,
        )
    )


def _compute_state_key(
    *,
    corpus_state_key: str,
    models: tuple[str, ...],
    components: tuple[str, ...],
    batch_size: int,
    long_input_strategies: tuple[str, ...],
) -> str:
    h = hashlib.sha256()
    h.update(corpus_state_key.encode("utf-8"))
    h.update(b"||")
    h.update(",".join(sorted(models)).encode("utf-8"))
    h.update(b"||")
    h.update(",".join(sorted(components)).encode("utf-8"))
    h.update(b"||")
    h.update(str(batch_size).encode("utf-8"))
    h.update(b"||")
    h.update(",".join(sorted(long_input_strategies)).encode("utf-8"))
    return h.hexdigest()[:12]


# ---- CLI parser -------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="embed-matrix", description="Stage 3 — multi-model embeddings matrix")
    parser.add_argument(
        "--source-corpus",
        default="data/primary/abstracts_enriched.sqlite",
    )
    parser.add_argument(
        "--embeddings-root",
        default="data/outputs/embeddings",
    )
    parser.add_argument(
        "--cache-root",
        default="data/cache/embeddings",
    )
    parser.add_argument(
        "--models",
        type=lambda s: [x.strip() for x in s.split(",") if x.strip()],
        default=list(DEFAULT_MODELS),
        help="Comma-separated list of model keys.",
    )
    parser.add_argument(
        "--components",
        type=lambda s: [x.strip() for x in s.split(",") if x.strip()],
        default=list(DEFAULT_COMPONENTS),
        help="Comma-separated list of component names.",
    )
    parser.add_argument(
        "--voyage-model-id", default=embed_voyage.DEFAULT_VOYAGE_MODEL,
    )
    parser.add_argument(
        "--openai-model-id", default=embed_openai.DEFAULT_OPENAI_MODEL,
    )
    parser.add_argument(
        "--minilm-model-id", default=embed_hf.DEFAULT_MINILM_MODEL,
    )
    parser.add_argument(
        "--pubmedbert-model-id", default=embed_hf.DEFAULT_PUBMEDBERT_MODEL,
    )
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    parser.add_argument("--concurrency-start", type=int, default=DEFAULT_CONCURRENCY_START)
    parser.add_argument("--concurrency-max", type=int, default=DEFAULT_CONCURRENCY_MAX)
    parser.add_argument(
        "--long-input-strategy",
        action="append",
        default=[],
        help="Per-model override, e.g. --long-input-strategy minilm=truncate_end (repeatable).",
    )
    parser.add_argument("--failure-threshold", type=float, default=DEFAULT_FAILURE_THRESHOLD)
    parser.add_argument(
        "--allow-partial",
        action="append",
        default=[],
        help="Permit a partial-coverage component bundle (repeatable).",
    )
    parser.add_argument(
        "--invalidate",
        action="append",
        default=[],
        help="Force-invalidate one bundle's cache (model_key or model_key_component; repeatable).",
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--env-file", default=".env")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return run_matrix(args)
    except ComponentAssemblyError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_GENERIC
    except OhbmStageError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_GENERIC


if __name__ == "__main__":
    raise SystemExit(main())
