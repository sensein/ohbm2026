"""Stage 2 orchestrator — enrich the accepted corpus with figures,
claims, and references.

Per-stage pattern (docs/per-stage-pattern.md) at a multi-component scale:

- **input**: data/primary/abstracts.json (read-only) + .env env vars.
- **output**: data/primary/abstracts_enriched.sqlite (single canonical
  atomic-rename target) + optional Parquet sidecar (FR-017).
- **provenance**: data/inputs/abstracts_enrich_provenance__<state-key>.json
  with names-only env-var list, project-relative paths, and the three
  component summaries.
- **error**: typed Stage2Error subtree (EnrichmentError,
  ComponentFailureThresholdError, CacheVersionError, ProvenanceError).
- **resumability**: per-component caches under data/cache/<component>/
  are the checkpoint; an interrupted run leaves them populated and a
  re-invocation reuses them.
- **discovery**: backend availability discovered at runtime;
  malformed LLM responses raise EnrichmentError per CA-007.

The three component-runners (`_call_figure_model`,
`_call_claims_model`, `_call_reference_strategy`) wrap the existing
`enrichment.py` / `openalex.py` building blocks per research.md §9.
"""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import io
import json
import os
import re
import sqlite3
import subprocess
import sys
import uuid
import zlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator, Optional

from ohbm2026 import artifacts as artifacts_module
from ohbm2026 import enrich_storage
from ohbm2026 import enrichment as enrichment_module
from ohbm2026 import stage2_figures
from ohbm2026 import stage2_claims
from ohbm2026 import stage2_references
from ohbm2026.exceptions import (
    CacheVersionError,
    ComponentFailureThresholdError,
    EnrichmentError,
    OhbmStageError,
    ProvenanceError,
    Stage2Error,
)

__all__ = [
    "BackendAvailability",
    "main",
]


# ----- Constants ------------------------------------------------------

_COMPONENTS = ("figures", "claims", "references")

_DEFAULT_FIGURE_MODEL_ID = "gpt-5.4-mini"
_DEFAULT_CLAIMS_MODEL_ID = "gpt-5.4-mini"
_DEFAULT_REFERENCE_STRATEGY_ID = "refs.v1+openai-gpt-5-nano"
_DEFAULT_FIGURE_FAILURE_THRESHOLD = 0.05
_DEFAULT_CLAIM_FAILURE_THRESHOLD = 0.05
_DEFAULT_REFERENCE_FAILURE_THRESHOLD = 1.0
_DEFAULT_CONCURRENCY = 30
_RATE_LIMIT_BACK_OFF_FRACTION = 0.10  # back off when remaining < 10% of limit

# Exit code mapping (mirrors `contracts/cli.md`).
_EXIT_OK = 0
_EXIT_GENERIC = 1
_EXIT_SCHEMA = 2
_EXIT_BOUNDARY = 4
_EXIT_THRESHOLD = 5
_EXIT_EMPTY = 6
_EXIT_CACHE_VERSION = 7


# ----- Backend discovery (Principle VII / CA-007) ---------------------


@dataclasses.dataclass(frozen=True)
class BackendAvailability:
    figures_backend: str | None
    claims_backend: str | None
    references_backend: str | None


def _read_dotenv(path: Path | None) -> dict[str, str]:
    if path is None or not path.exists():
        return {}
    env: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        env[key.strip()] = value.strip().strip("'\"")
    return env


def _classify_backend_availability(
    *,
    env: dict[str, str],
    dotenv_path: Path | None,
) -> BackendAvailability:
    """Discover which figures / claims / references backends are
    actually invocable in this run's environment. Pure: no I/O beyond
    reading the dotenv path and inspecting `env`."""
    combined: dict[str, str] = {}
    combined.update(_read_dotenv(dotenv_path))
    combined.update(env)

    has_openai = bool(combined.get("OPENAI_API_KEY"))
    has_openalex = bool(combined.get("OPENALEX_API"))

    figures = "openai" if has_openai else None
    # Stage 2.1: claims now use OpenAI Responses API directly (no cllm).
    claims = "openai" if has_openai else None
    if has_openai and has_openalex:
        references: str | None = "openai+openalex"
    elif has_openai:
        references = "openai"
    else:
        references = None
    return BackendAvailability(
        figures_backend=figures,
        claims_backend=claims,
        references_backend=references,
    )


# ----- Path safety ----------------------------------------------------


def _project_relative(value: str | os.PathLike[str]) -> str:
    s = os.fspath(value)
    return s.replace(os.sep, "/")


def _assert_paths_safe(*candidates: Path | str) -> None:
    """Refuse to write outside gitignored roots. Raises ProvenanceError
    on absolute or `~`-prefixed candidates."""
    for c in candidates:
        if c is None:
            continue
        s = os.fspath(c)
        if s.startswith("/") or s.startswith("~"):
            raise ProvenanceError(
                f"Stage 2 refuses absolute / ~-prefixed path: {s!r}"
            )


# ----- Hashing helpers ------------------------------------------------


def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _hash_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(64 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _hash_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _hash_record_for_content(record: dict) -> str:
    """Hash one abstract's stable content fields (id + responses +
    figure_urls) — used as the per-abstract content_hash stored
    alongside the enriched record."""
    snapshot = {
        "id": record.get("id"),
        "title": record.get("title"),
        "responses": record.get("responses", []),
        "figure_urls": record.get("figure_urls", []),
    }
    return _sha256_hex(
        json.dumps(snapshot, sort_keys=True, separators=(",", ":")).encode("utf-8")
    )


# ----- Cache helpers --------------------------------------------------


def _atomic_write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + f".tmp.{os.getpid()}")
    tmp.write_text(
        json.dumps(payload, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )
    os.replace(tmp, path)


def _load_cache_entry(path: Path) -> dict | None:
    """Load a cache entry. Returns None on miss, dict on hit. Raises
    CacheVersionError when the on-disk `cache_version` is unrecognized
    (research.md §3 — no silent migration)."""
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise EnrichmentError(f"corrupted cache entry at {path}: {exc}") from exc
    cache_version = payload.get("cache_version")
    if cache_version != enrich_storage.CACHE_VERSION:
        raise CacheVersionError(
            f"cache entry at {path} has version {cache_version!r}; "
            f"expected {enrich_storage.CACHE_VERSION!r}"
        )
    return payload


def _write_cache_entry(
    path: Path,
    *,
    component: str,
    cache_key: str,
    model_id: str,
    input_hash: str,
    payload: dict,
) -> None:
    entry = {
        "cache_version": enrich_storage.CACHE_VERSION,
        "component": component,
        "cache_key": cache_key,
        "model_id": model_id,
        "input_hash": input_hash,
        "computed_at": datetime.now(timezone.utc).isoformat(),
        "payload": payload,
    }
    _atomic_write_json(path, entry)


# ----- Component runners (the test seam) ------------------------------
#
# Stage 2.1 production wiring: each `_call_*_for_abstract` invokes
# the per-abstract production runner from `stage2_*.py`. Tests can
# patch any of the three (e.g.
# `mock.patch.object(enrich_stage, "_call_figures_for_abstract", ...)`)
# or patch one level deeper (the `client.responses.parse` / `create`
# seam inside the runners).


def _make_openai_client() -> Any:
    """Construct the OpenAI client lazily so module-import remains
    cheap and so tests can patch this seam."""
    from openai import OpenAI  # noqa: PLC0415
    return OpenAI()


def _call_figures_for_abstract(
    abstract: dict,
    *,
    model_id: str,
    flex_enabled: bool,
    cwd: Path,
    client: Any,
) -> tuple[list[dict], "stage2_figures.FigureRunSummary"]:
    """Stage 2.1 figures runner — one OpenAI Responses API call per
    abstract carrying all of that abstract's figures + the manuscript
    context."""
    return stage2_figures.run_figure_component(
        abstract,
        model_id=model_id,
        flex_enabled=flex_enabled,
        client=client,
        cwd=cwd,
    )


def _call_claims_for_abstract(
    abstract: dict,
    *,
    model_id: str,
    flex_enabled: bool,
    figure_interpretations: list[dict] | None,
    client: Any,
) -> tuple[list[dict], "stage2_claims.ClaimsRunSummary"]:
    """Stage 2.1 claims runner — one agentic OpenAI Responses API call
    per abstract with three function tools (verify_source_quote,
    lookup_eco_code, dedupe_check)."""
    return stage2_claims.run_claims_component(
        abstract,
        model_id=model_id,
        flex_enabled=flex_enabled,
        figure_interpretations=figure_interpretations,
        client=client,
    )


def _call_references_for_abstract(
    abstract: dict,
    *,
    strategy_id: str,
    resolver: Any | None = None,
) -> tuple[list[dict], "stage2_references.ReferencesRunSummary"]:
    """Stage 2.1 references runner — thin adapter to the existing
    openalex resolution pipeline."""
    return stage2_references.run_references_component(
        abstract,
        strategy_id=strategy_id,
        resolver=resolver,
    )


# ----- Manuscript construction (reuses enrichment.py) -----------------


def _build_claim_manuscript(abstract: dict) -> str:
    sections, additional = enrichment_module.build_sections_markdown(abstract)
    title = abstract.get("title") or ""
    return enrichment_module.build_claim_manuscript_markdown(
        title=title,
        sections_markdown=sections,
        additional_content_questions=additional,
    )


def _extract_reference_block(abstract: dict) -> str:
    for q in abstract.get("responses", []) or []:
        name = (q.get("question_name") or "").strip().lower()
        if "reference" in name:
            return (q.get("value") or "").strip()
    return ""


def _split_references(reference_block: str) -> list[str]:
    """Best-effort line split. The orchestrator caches each individual
    reference, so even crude splitting still gives correct cache reuse
    (per-line content hashed)."""
    if not reference_block:
        return []
    return [line.strip() for line in reference_block.splitlines() if line.strip()]


def _read_image_bytes(local_path: str | None) -> bytes | None:
    if not local_path:
        return None
    p = Path(local_path)
    if not p.exists():
        return None
    return p.read_bytes()


# ----- Component orchestration ----------------------------------------


@dataclasses.dataclass
class _ComponentSummary:
    """Per-component telemetry rolled up across all abstracts.

    Stage 2.1 extends Stage 2's counters with flex-tier counters
    (FR-004) and cost telemetry (FR-019); the orchestrator
    serializes these into the provenance record's `components`
    array.
    """
    component: str
    model_id: str
    cache_hit_count: int = 0
    cache_miss_count: int = 0
    cache_invalidated: bool = False
    failure_count: int = 0
    # Stage 2.1 extensions:
    flex_tier_enabled: bool = False
    flex_timeout_count: int = 0
    tier_fallback_count: int = 0
    retry_exhaustion_count: int = 0
    prompt_tokens_cached: int = 0
    prompt_tokens_uncached: int = 0
    completion_tokens: int = 0
    wall_clock_seconds: float = 0.0
    latencies_ms: list[float] = dataclasses.field(default_factory=list)


def _record_run_telemetry(
    summary: _ComponentSummary, run_summary: Any
) -> None:
    """Accumulate one runner's telemetry into the component summary."""
    if run_summary is None:
        return
    if getattr(run_summary, "flex_timed_out", False):
        summary.flex_timeout_count += 1
        if getattr(run_summary, "tier_used", "flex") == "standard":
            summary.tier_fallback_count += 1
    summary.prompt_tokens_cached += int(getattr(run_summary, "prompt_tokens_cached", 0) or 0)
    summary.prompt_tokens_uncached += int(getattr(run_summary, "prompt_tokens_uncached", 0) or 0)
    summary.completion_tokens += int(getattr(run_summary, "completion_tokens", 0) or 0)
    latency = float(getattr(run_summary, "latency_ms", 0.0) or 0.0)
    summary.wall_clock_seconds += latency / 1000.0
    if latency > 0:
        summary.latencies_ms.append(latency)


def _run_figure_component(
    abstract: dict,
    *,
    model_id: str,
    invalidated: bool,
    summary: _ComponentSummary,
    cache_root: Path,
    cwd: Path,
    flex_enabled: bool = True,
    client: Any | None = None,
) -> list[dict]:
    """Stage 2.1: one OpenAI call per abstract carrying all of that
    abstract's figures. Per-figure cache entries are still written
    so a single figure change invalidates only that figure (though
    the runner re-calls for ALL figures in the abstract — they
    share model context).
    """
    figure_urls = abstract.get("figure_urls") or []
    if not figure_urls:
        return []

    # Compute per-figure cache keys up front so we can decide
    # whether to skip the per-abstract API call entirely.
    local_assets_by_url = {
        a.get("figure_url"): a.get("local_path")
        for a in (abstract.get("local_assets") or [])
    }
    per_figure_keys: list[tuple[str, str, str | None, bytes | None]] = []  # (url, key, local_path, png_bytes)
    for entry in figure_urls:
        url = entry.get("url") or entry.get("figure_url") or ""
        local_path = local_assets_by_url.get(url)
        png_bytes: bytes | None = None
        if local_path:
            abs_path = (cwd / local_path) if not Path(local_path).is_absolute() else Path(local_path)
            if abs_path.exists():
                png_bytes = abs_path.read_bytes()
        if png_bytes is None:
            # Missing asset — surface as a per-figure failure via the
            # production runner (it will raise EnrichmentError).
            cache_key = _sha256_hex(url.encode("utf-8") + model_id.encode("utf-8"))
            per_figure_keys.append((url, cache_key, local_path, None))
            continue
        # Use the canonical PNG bytes for the cache key; the JPEG
        # representation transmitted to the model is reproducible
        # from the same PNG.
        cache_key = _sha256_hex(png_bytes + model_id.encode("utf-8"))
        per_figure_keys.append((url, cache_key, local_path, png_bytes))

    # Try to satisfy every figure from cache.
    cached_payloads: dict[str, dict] = {}
    if not invalidated:
        for url, cache_key, _lp, _pb in per_figure_keys:
            cache_path = cache_root / "figure_analysis" / f"{cache_key}.json"
            entry = _load_cache_entry(cache_path)
            if entry is not None:
                cached_payloads[url] = entry["payload"]

    if len(cached_payloads) == len(per_figure_keys):
        # All cached — assemble and return without a model call.
        summary.cache_hit_count += len(per_figure_keys)
        out = []
        for url, cache_key, local_path, _pb in per_figure_keys:
            record = dict(cached_payloads[url])
            record.setdefault("figure_url", url)
            record.setdefault("local_path", local_path)
            record.setdefault("model_id", model_id)
            record["cache_key"] = cache_key
            out.append(record)
        return out

    # Need a model call. The per-abstract runner sees ALL figures
    # together (siblings) so its output replaces every figure's
    # cache entry for this abstract.
    if client is None:
        client = _make_openai_client()
    records, run_summary = _call_figures_for_abstract(
        abstract,
        model_id=model_id,
        flex_enabled=flex_enabled,
        cwd=cwd,
        client=client,
    )
    _record_run_telemetry(summary, run_summary)

    # Map each returned record to the orchestrator's canonical
    # cache_key (sha256(png_bytes || model_id)) — the runner may
    # have computed its own key, but the orchestrator-level cache
    # uses content-derived keys.
    canonical_keys_by_url = {url: key for url, key, _lp, _pb in per_figure_keys}
    cached_url_set = set(cached_payloads.keys())
    out: list[dict] = []
    for record in records:
        url = record.get("figure_url")
        canonical_key = canonical_keys_by_url.get(url, record.get("cache_key", ""))
        record = dict(record)
        record["cache_key"] = canonical_key
        cache_path = cache_root / "figure_analysis" / f"{canonical_key}.json"
        # Cache payload excludes the cache_key (redundant with filename).
        payload = {k: v for k, v in record.items() if k != "cache_key"}
        _write_cache_entry(
            cache_path,
            component="figures",
            cache_key=canonical_key,
            model_id=model_id,
            input_hash=_sha256_hex((record.get("figure_url") or "").encode("utf-8")),
            payload=payload,
        )
        if url in cached_url_set:
            summary.cache_hit_count += 1
        else:
            summary.cache_miss_count += 1
        out.append(record)
    return out


def _run_claims_component(
    abstract: dict,
    *,
    model_id: str,
    invalidated: bool,
    summary: _ComponentSummary,
    cache_root: Path,
    flex_enabled: bool = True,
    client: Any | None = None,
    figure_interpretations: list[dict] | None = None,
) -> list[dict]:
    """Stage 2.1: one agentic OpenAI call per abstract. Cache key
    includes the ECO vocabulary version so a vocabulary bump
    invalidates all claims caches loudly (FR-013)."""
    manuscript = _build_claim_manuscript(abstract)
    if not manuscript.strip():
        return []
    vocabulary = stage2_claims.load_eco_vocabulary()
    vocab_version = vocabulary["vocabulary_version"]
    cache_key = _sha256_hex(
        manuscript.encode("utf-8")
        + b"||" + model_id.encode("utf-8")
        + b"||" + vocab_version.encode("utf-8")
    )
    cache_path = cache_root / "claim_analysis" / f"{cache_key}.json"
    cached = None if invalidated else _load_cache_entry(cache_path)
    if cached is not None:
        summary.cache_hit_count += 1
        claims = cached["payload"]["claims"]
        out: list[dict] = []
        for claim in claims:
            record = dict(claim)
            record.setdefault("model_id", model_id)
            record["cache_key"] = cache_key
            out.append(record)
        return out

    if client is None:
        client = _make_openai_client()
    records, run_summary = _call_claims_for_abstract(
        abstract,
        model_id=model_id,
        flex_enabled=flex_enabled,
        figure_interpretations=figure_interpretations,
        client=client,
    )
    _record_run_telemetry(summary, run_summary)
    summary.cache_miss_count += 1

    # Override every claim's cache_key to the per-abstract key for
    # this layer (production runner generated its own per-claim
    # key from manuscript + model + vocab — same input, so equal,
    # but be defensive).
    out = []
    for record in records:
        rec = dict(record)
        rec["cache_key"] = cache_key
        out.append(rec)

    _write_cache_entry(
        cache_path,
        component="claims",
        cache_key=cache_key,
        model_id=model_id,
        input_hash=_hash_text(manuscript),
        payload={"claims": out, "vocabulary_version": vocab_version},
    )
    return out


def _run_references_component(
    abstract: dict,
    *,
    strategy_id: str,
    invalidated: bool,
    summary: _ComponentSummary,
    cache_root: Path,
    resolver: Any | None = None,
) -> list[dict]:
    """Stage 2.1: per-reference cache reuse + per-abstract resolver
    call when any reference is uncached. The resolver itself
    handles async concurrency internally via openalex.py's
    existing pool.
    """
    block = _extract_reference_block(abstract)
    refs = _split_references(block)
    if not refs:
        return []

    # Per-reference cache lookup.
    cached_records: dict[str, dict] = {}
    if not invalidated:
        for raw in refs:
            cache_key = _sha256_hex(raw.encode("utf-8") + strategy_id.encode("utf-8"))
            cache_path = cache_root / "reference_metadata" / f"{cache_key}.json"
            entry = _load_cache_entry(cache_path)
            if entry is not None:
                cached_records[raw] = entry["payload"]

    out: list[dict] = []
    if len(cached_records) == len(refs):
        # Every reference cached — assemble and return.
        for raw in refs:
            cache_key = _sha256_hex(raw.encode("utf-8") + strategy_id.encode("utf-8"))
            record = dict(cached_records[raw])
            record.setdefault("raw_reference", raw)
            record.setdefault("strategy_id", strategy_id)
            record["cache_key"] = cache_key
            out.append(record)
            summary.cache_hit_count += 1
        return out

    # Need a resolver call. The resolver returns one record per
    # reference; we merge with cache hits.
    records, _run_summary = _call_references_for_abstract(
        abstract,
        strategy_id=strategy_id,
        resolver=resolver,
    )
    # Index returned records by raw_reference for merge.
    returned_by_raw = {rec["raw_reference"]: rec for rec in records if "raw_reference" in rec}
    cached_set = set(cached_records.keys())
    for raw in refs:
        cache_key = _sha256_hex(raw.encode("utf-8") + strategy_id.encode("utf-8"))
        cache_path = cache_root / "reference_metadata" / f"{cache_key}.json"
        if raw in cached_records:
            record = dict(cached_records[raw])
            summary.cache_hit_count += 1
        else:
            record = dict(returned_by_raw.get(raw, {"raw_reference": raw, "resolution_status": "unresolved"}))
            summary.cache_miss_count += 1
            payload = {k: v for k, v in record.items() if k != "cache_key"}
            _write_cache_entry(
                cache_path,
                component="references",
                cache_key=cache_key,
                model_id=strategy_id,
                input_hash=_hash_text(raw),
                payload=payload,
            )
        record.setdefault("raw_reference", raw)
        record.setdefault("strategy_id", strategy_id)
        record["cache_key"] = cache_key
        out.append(record)
    return out


# ----- Argparse -------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="enrich-abstracts",
        description="Stage 2 — enrich accepted abstracts (figures, claims, references)",
    )
    parser.add_argument("--env-file", default=".env")
    parser.add_argument(
        "--source-corpus",
        default=str(artifacts_module.PRIMARY_ABSTRACTS_PATH),
    )
    parser.add_argument(
        "--enriched-output",
        default=str(artifacts_module.PRIMARY_ENRICHED_CORPUS_PATH),
    )
    parser.add_argument("--figure-model-id", default=_DEFAULT_FIGURE_MODEL_ID)
    parser.add_argument("--claims-model-id", default=_DEFAULT_CLAIMS_MODEL_ID)
    parser.add_argument(
        "--reference-strategy-id", default=_DEFAULT_REFERENCE_STRATEGY_ID
    )
    parser.add_argument(
        "--invalidate",
        action="append",
        choices=list(_COMPONENTS),
        default=[],
        help="Force-invalidate one component's cache (repeatable).",
    )
    parser.add_argument(
        "--figure-failure-threshold",
        type=float,
        default=_DEFAULT_FIGURE_FAILURE_THRESHOLD,
    )
    parser.add_argument(
        "--claim-failure-threshold",
        type=float,
        default=_DEFAULT_CLAIM_FAILURE_THRESHOLD,
    )
    parser.add_argument(
        "--reference-failure-threshold",
        type=float,
        default=_DEFAULT_REFERENCE_FAILURE_THRESHOLD,
    )
    parser.add_argument("--export-parquet", default=None)
    # Stage 2.1 — flex-tier flags (default ON; per-component disable).
    parser.add_argument(
        "--no-flex-figures",
        action="store_true",
        help="Disable OpenAI flex-tier processing for the figures component.",
    )
    parser.add_argument(
        "--no-flex-claims",
        action="store_true",
        help="Disable OpenAI flex-tier processing for the claims component.",
    )
    # Stage 2.1 — concurrency caps (per-component).
    parser.add_argument(
        "--concurrency-figures",
        type=int,
        default=_DEFAULT_CONCURRENCY,
        help="Max in-flight figure-component requests (default 30).",
    )
    parser.add_argument(
        "--concurrency-claims",
        type=int,
        default=_DEFAULT_CONCURRENCY,
        help="Max in-flight claims-component requests (default 30).",
    )
    return parser


# ----- Git revision discovery -----------------------------------------


def _git_revision() -> dict:
    try:
        sha = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], stderr=subprocess.DEVNULL
        ).decode().strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        sha = "0000000"
    try:
        dirty_out = subprocess.check_output(
            ["git", "status", "--porcelain"], stderr=subprocess.DEVNULL
        ).decode().strip()
        dirty = bool(dirty_out)
    except (subprocess.CalledProcessError, FileNotFoundError):
        dirty = False
    return {"git_sha": sha, "dirty": dirty}


# ----- Delta vs previous enriched corpus -----------------------------


def _delta_vs_previous(
    enriched_path: Path, current_ids: set[int]
) -> dict | None:
    if not enriched_path.exists():
        return None
    try:
        con = sqlite3.connect(enriched_path)
        previous_ids = {int(row[0]) for row in con.execute("SELECT id FROM abstracts")}
        con.close()
    except sqlite3.DatabaseError:
        return None
    added = current_ids - previous_ids
    removed = previous_ids - current_ids
    unchanged = current_ids & previous_ids
    return {
        "added_count": len(added),
        "removed_count": len(removed),
        "unchanged_count": len(unchanged),
    }


# ----- Main orchestrator ---------------------------------------------


def _filter_accepted(abstracts: Iterable[dict]) -> list[dict]:
    out: list[dict] = []
    for ab in abstracts:
        accepted_for = (ab.get("accepted_for") or "")
        if isinstance(accepted_for, str) and accepted_for.strip().lower() == "withdrawn":
            continue
        out.append(ab)
    return out


def _scan_env_vars_consulted(backends: BackendAvailability) -> list[str]:
    names: list[str] = []
    if backends.figures_backend == "openai" or backends.claims_backend == "openai":
        names.append("OPENAI_API_KEY")
    if backends.references_backend in {"openai+openalex"}:
        if "OPENALEX_API" not in names:
            names.append("OPENALEX_API")
    return sorted(set(names))


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv if argv is not None else sys.argv[1:])

    cwd = Path.cwd()
    source_path = Path(args.source_corpus)
    enriched_path = Path(args.enriched_output)
    export_parquet_path = Path(args.export_parquet) if args.export_parquet else None

    # Path-safety check.
    try:
        _assert_paths_safe(args.enriched_output)
        if args.export_parquet:
            _assert_paths_safe(args.export_parquet)
    except ProvenanceError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return _EXIT_BOUNDARY

    abs_source = source_path if source_path.is_absolute() else cwd / source_path
    abs_enriched = enriched_path if enriched_path.is_absolute() else cwd / enriched_path
    abs_export_parquet = (
        export_parquet_path
        if export_parquet_path is None or export_parquet_path.is_absolute()
        else cwd / export_parquet_path
    )

    # Discover backends.
    dotenv_path = (cwd / args.env_file) if not Path(args.env_file).is_absolute() else Path(args.env_file)
    backends = _classify_backend_availability(env=dict(os.environ), dotenv_path=dotenv_path)
    if backends.figures_backend is None and backends.claims_backend is None and backends.references_backend is None:
        print(
            "error: no enrichment backend available (set OPENAI_API_KEY in "
            ".env or the environment)",
            file=sys.stderr,
        )
        return _EXIT_GENERIC

    # Load source corpus.
    if not abs_source.exists():
        print(f"error: source corpus not found at {source_path}", file=sys.stderr)
        return _EXIT_GENERIC
    raw_source = abs_source.read_bytes()
    source_hash = _sha256_hex(raw_source)
    payload = json.loads(raw_source.decode("utf-8"))
    abstracts_in = payload.get("abstracts", [])
    accepted = _filter_accepted(abstracts_in)
    if not accepted:
        print("error: source corpus has zero accepted abstracts", file=sys.stderr)
        return _EXIT_EMPTY

    # State key.
    basis = artifacts_module.build_dependency_basis(
        input_sources=[_project_relative(source_path)],
        input_digest=source_hash,
        options={
            "figure_model_id": args.figure_model_id,
            "claims_model_id": args.claims_model_id,
            "reference_strategy_id": args.reference_strategy_id,
            "cache_version": enrich_storage.CACHE_VERSION,
            "storage_version": enrich_storage.STORAGE_VERSION,
        },
    )
    state_key = artifacts_module.build_state_key(basis)

    cache_root = cwd / artifacts_module.CACHE_ROOT
    invalidated_components = set(args.invalidate)
    flex_figures = not args.no_flex_figures
    flex_claims = not args.no_flex_claims
    summaries = {
        "figures": _ComponentSummary(
            component="figures",
            model_id=args.figure_model_id,
            cache_invalidated="figures" in invalidated_components,
            flex_tier_enabled=flex_figures,
        ),
        "claims": _ComponentSummary(
            component="claims",
            model_id=args.claims_model_id,
            cache_invalidated="claims" in invalidated_components,
            flex_tier_enabled=flex_claims,
        ),
        "references": _ComponentSummary(
            component="references",
            model_id=args.reference_strategy_id,
            cache_invalidated="references" in invalidated_components,
            flex_tier_enabled=False,  # references don't go through OpenAI directly.
        ),
    }

    figure_input_total = 0
    claim_input_total = 0
    reference_input_total = 0
    figure_failure_count = 0
    claim_failure_count = 0
    reference_failure_count = 0
    figure_failure_threshold = args.figure_failure_threshold
    claim_failure_threshold = args.claim_failure_threshold
    reference_failure_threshold = args.reference_failure_threshold

    enriched_records: list[dict] = []

    # Process each accepted abstract.
    for abstract in accepted:
        # Figures
        figure_inputs = len(abstract.get("figure_urls") or [])
        figure_input_total += figure_inputs
        try:
            figures_out = _run_figure_component(
                abstract,
                model_id=args.figure_model_id,
                invalidated=summaries["figures"].cache_invalidated,
                summary=summaries["figures"],
                cache_root=cache_root,
                cwd=cwd,
                flex_enabled=flex_figures,
            )
        except CacheVersionError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return _EXIT_CACHE_VERSION
        except EnrichmentError as exc:
            figure_failure_count += max(figure_inputs, 1)
            summaries["figures"].failure_count += max(figure_inputs, 1)
            figures_out = []
            print(
                f"figure enrichment failed for abstract {abstract.get('id')}: {exc}",
                file=sys.stderr,
            )

        # Claims
        try:
            claims_out = _run_claims_component(
                abstract,
                model_id=args.claims_model_id,
                invalidated=summaries["claims"].cache_invalidated,
                summary=summaries["claims"],
                cache_root=cache_root,
                flex_enabled=flex_claims,
                figure_interpretations=figures_out,
            )
            claim_input_total += 1
        except CacheVersionError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return _EXIT_CACHE_VERSION
        except EnrichmentError as exc:
            claim_failure_count += 1
            claim_input_total += 1
            summaries["claims"].failure_count += 1
            claims_out = []
            print(
                f"claims enrichment failed for abstract {abstract.get('id')}: {exc}",
                file=sys.stderr,
            )

        # References
        ref_block = _extract_reference_block(abstract)
        ref_lines = _split_references(ref_block)
        reference_input_total += len(ref_lines)
        try:
            references_out = _run_references_component(
                abstract,
                strategy_id=args.reference_strategy_id,
                invalidated=summaries["references"].cache_invalidated,
                summary=summaries["references"],
                cache_root=cache_root,
            )
        except CacheVersionError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return _EXIT_CACHE_VERSION
        except EnrichmentError as exc:
            reference_failure_count += max(len(ref_lines), 1)
            summaries["references"].failure_count += max(len(ref_lines), 1)
            references_out = []
            print(
                f"reference enrichment failed for abstract {abstract.get('id')}: {exc}",
                file=sys.stderr,
            )

        enriched_record = dict(abstract)
        enriched_record["figure_interpretation"] = figures_out
        enriched_record["claims"] = claims_out
        enriched_record["references"] = references_out
        enriched_records.append(enriched_record)

    # Threshold check AFTER the loop — Principle VI: fail loud, do
    # NOT write a clobbering enriched corpus when a component breached
    # its rate budget across the full input set.
    if figure_input_total > 0:
        rate = figure_failure_count / figure_input_total
        if rate > figure_failure_threshold:
            print(
                f"figure failure rate {rate:.3f} exceeded threshold "
                f"{figure_failure_threshold:.3f}",
                file=sys.stderr,
            )
            return _EXIT_THRESHOLD
    if claim_input_total > 0:
        rate = claim_failure_count / claim_input_total
        if rate > claim_failure_threshold:
            print(
                f"claim failure rate {rate:.3f} exceeded threshold "
                f"{claim_failure_threshold:.3f}",
                file=sys.stderr,
            )
            return _EXIT_THRESHOLD
    if reference_input_total > 0:
        rate = reference_failure_count / reference_input_total
        if rate > reference_failure_threshold:
            print(
                f"reference failure rate {rate:.3f} exceeded threshold "
                f"{reference_failure_threshold:.3f}",
                file=sys.stderr,
            )
            return _EXIT_THRESHOLD

    # Compute delta-vs-previous BEFORE the canonical write so we can
    # read the previous corpus's id set.
    current_ids = {int(r["id"]) for r in enriched_records}
    delta = _delta_vs_previous(abs_enriched, current_ids)

    # Atomic write of enriched corpus.
    with enrich_storage.EnrichedCorpusWriter(
        abs_enriched,
        state_key=state_key,
        source_corpus_hash=source_hash,
        corpus_kind="accepted",
    ) as writer:
        for record in enriched_records:
            writer.write_record(record, content_hash=_hash_record_for_content(record))

    # Optional Parquet export — lazy import.
    parquet_relpath: str | None = None
    if abs_export_parquet is not None:
        import pyarrow as pa  # noqa: PLC0415
        import pyarrow.parquet as pq  # noqa: PLC0415

        ids = []
        payloads = []
        for record in enriched_records:
            ids.append(int(record["id"]))
            payloads.append(json.dumps(record, sort_keys=True, separators=(",", ":")))
        table = pa.table({"id": ids, "payload": payloads})
        abs_export_parquet.parent.mkdir(parents=True, exist_ok=True)
        tmp_parquet = abs_export_parquet.with_name(abs_export_parquet.name + f".tmp.{os.getpid()}")
        pq.write_table(table, tmp_parquet, compression="zstd")
        os.replace(tmp_parquet, abs_export_parquet)
        parquet_relpath = _project_relative(export_parquet_path)

    # Write provenance.
    prov_rel = artifacts_module.build_enrich_provenance_path(state_key)
    abs_prov = cwd / prov_rel
    # Load the embedded ECO vocabulary to record its version in
    # provenance (Stage 2.1 extension; FR-013).
    try:
        eco_vocabulary_version = stage2_claims.load_eco_vocabulary()["vocabulary_version"]
    except Exception:
        eco_vocabulary_version = "unknown"

    def _percentile(values: list[float], pct: float) -> float:
        if not values:
            return 0.0
        sorted_values = sorted(values)
        # Linear interpolation between adjacent points.
        rank = (pct / 100.0) * (len(sorted_values) - 1)
        low = int(rank)
        high = min(low + 1, len(sorted_values) - 1)
        if low == high:
            return sorted_values[low]
        frac = rank - low
        return sorted_values[low] + frac * (sorted_values[high] - sorted_values[low])

    record = {
        "provenance_version": enrich_storage.PROVENANCE_VERSION,
        "run_id": str(uuid.uuid4()),
        "state_key": state_key,
        "run_timestamp": datetime.now(timezone.utc).isoformat(),
        "code_revision": _git_revision(),
        "command_line": list(sys.argv),
        "env_vars_consulted": _scan_env_vars_consulted(backends),
        "source_corpus_path": _project_relative(source_path),
        "source_corpus_hash": source_hash,
        "enriched_corpus_path": _project_relative(enriched_path),
        "corpus_kind": "accepted",
        "abstract_count": len(enriched_records),
        "eco_vocabulary_version": eco_vocabulary_version,
        "components": [
            {
                "component": s.component,
                "model_id": s.model_id,
                "cache_version": enrich_storage.CACHE_VERSION,
                "cache_hit_count": s.cache_hit_count,
                "cache_miss_count": s.cache_miss_count,
                "cache_invalidated": s.cache_invalidated,
                "failure_count": s.failure_count,
                # Stage 2.1 extensions (FR-003 / FR-004 / FR-019):
                "flex_tier_enabled": s.flex_tier_enabled,
                "flex_timeout_count": s.flex_timeout_count,
                "tier_fallback_count": s.tier_fallback_count,
                "retry_exhaustion_count": s.retry_exhaustion_count,
                "prompt_tokens_cached": s.prompt_tokens_cached,
                "prompt_tokens_uncached": s.prompt_tokens_uncached,
                "completion_tokens": s.completion_tokens,
                "wall_clock_seconds": round(s.wall_clock_seconds, 3),
                "latency_p50_ms": round(_percentile(s.latencies_ms, 50.0), 3),
                "latency_p95_ms": round(_percentile(s.latencies_ms, 95.0), 3),
            }
            for s in (summaries["figures"], summaries["claims"], summaries["references"])
        ],
        "delta_vs_previous": delta,
        "figure_failure_count": figure_failure_count,
        "claim_failure_count": claim_failure_count,
        "reference_failure_count": reference_failure_count,
        "parquet_export_path": parquet_relpath,
    }
    _assert_paths_safe(record["source_corpus_path"], record["enriched_corpus_path"])
    if parquet_relpath is not None:
        _assert_paths_safe(parquet_relpath)
    _atomic_write_json(abs_prov, record)

    # Stdout summary (single JSON object per contracts/cli.md).
    summary_out = {
        "enriched_corpus": _project_relative(enriched_path),
        "provenance_record": _project_relative(prov_rel),
        "state_key": state_key,
        "abstract_count": len(enriched_records),
        "components": [
            {
                "component": s.component,
                "model_id": s.model_id,
                "cache_hit_count": s.cache_hit_count,
                "cache_miss_count": s.cache_miss_count,
                "failure_count": s.failure_count,
            }
            for s in (summaries["figures"], summaries["claims"], summaries["references"])
        ],
        "delta_vs_previous": delta,
    }
    print(json.dumps(summary_out, sort_keys=True, separators=(",", ":")))
    return _EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
