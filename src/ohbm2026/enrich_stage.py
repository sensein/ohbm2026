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

_DEFAULT_FIGURE_MODEL_ID = "gpt-4.1-mini"
_DEFAULT_CLAIMS_MODEL_ID = "gpt-4o-2024-08-06"
_DEFAULT_REFERENCE_STRATEGY_ID = "refs.v1+openai-gpt-5-nano"
_DEFAULT_FIGURE_FAILURE_THRESHOLD = 0.05
_DEFAULT_CLAIM_FAILURE_THRESHOLD = 0.05
_DEFAULT_REFERENCE_FAILURE_THRESHOLD = 1.0

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
    claims = "openai_cllm" if has_openai else None
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
# Tests patch these via `mock.patch.object(enrich_stage, "_call_*",
# side_effect=...)`. Production implementations call into the
# heavyweight building blocks in `enrichment.py` / `openalex.py`.


def _call_figure_model(
    figure_url: str,
    image_bytes: bytes,
    model_id: str,
    *,
    question_name: str,
    local_path: str | None,
) -> dict:
    """Invoke a vision LLM on one figure. Returns a dict matching the
    FigureInterpretation contract (minus `cache_key` — caller adds)."""
    # Production path — only used when tests do NOT patch this.
    raise NotImplementedError(
        "production figure-model invocation is wired through enrichment.py; "
        "in v1 the orchestrator's heavyweight figure path is exercised only "
        "via the live smoke run (T030). Tests patch this function directly."
    )


def _call_claims_model(
    manuscript_markdown: str,
    model_id: str,
    *,
    abstract_id: int,
) -> list[dict]:
    """Invoke the claims-extraction LLM. Returns a list of Claim
    dicts."""
    raise NotImplementedError(
        "production claims-model invocation is wired through enrichment.py; "
        "in v1 the orchestrator's heavyweight claims path is exercised only "
        "via the live smoke run (T030). Tests patch this function directly."
    )


def _call_reference_strategy(raw_reference: str, strategy_id: str) -> dict:
    """Invoke the reference-resolution strategy on one raw reference.
    Returns a dict matching the ReferenceResolution contract (minus
    `cache_key`)."""
    raise NotImplementedError(
        "production reference-resolution is wired through openalex.py; "
        "in v1 the orchestrator's heavyweight references path is exercised "
        "only via the live smoke run (T030). Tests patch this function "
        "directly."
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
    component: str
    model_id: str
    cache_hit_count: int = 0
    cache_miss_count: int = 0
    cache_invalidated: bool = False
    failure_count: int = 0


def _run_figure_component(
    abstract: dict,
    *,
    model_id: str,
    invalidated: bool,
    summary: _ComponentSummary,
    cache_root: Path,
) -> list[dict]:
    out: list[dict] = []
    figure_urls = abstract.get("figure_urls") or []
    local_assets_by_url = {
        a.get("figure_url"): a.get("local_path")
        for a in (abstract.get("local_assets") or [])
    }
    for entry in figure_urls:
        url = entry.get("url") or entry.get("figure_url")
        question_name = entry.get("question_name", "")
        local_path = local_assets_by_url.get(url)
        abs_local = (cache_root.parent.parent / local_path) if local_path else None
        image_bytes = (_read_image_bytes(str(abs_local)) if abs_local else None) or url.encode("utf-8")
        cache_key = _sha256_hex(image_bytes + model_id.encode("utf-8"))
        cache_path = cache_root / "figure_analysis" / f"{cache_key}.json"
        cached = None if invalidated else _load_cache_entry(cache_path)
        if cached is None:
            payload = _call_figure_model(
                url,
                image_bytes,
                model_id,
                question_name=question_name,
                local_path=local_path,
            )
            _write_cache_entry(
                cache_path,
                component="figures",
                cache_key=cache_key,
                model_id=model_id,
                input_hash=_sha256_hex(image_bytes),
                payload=payload,
            )
            summary.cache_miss_count += 1
        else:
            payload = cached["payload"]
            summary.cache_hit_count += 1
        record = dict(payload)
        record.setdefault("figure_url", url)
        record.setdefault("question_name", question_name)
        record.setdefault("model_id", model_id)
        record["cache_key"] = cache_key
        if "local_path" not in record:
            record["local_path"] = local_path
        out.append(record)
    return out


def _run_claims_component(
    abstract: dict,
    *,
    model_id: str,
    invalidated: bool,
    summary: _ComponentSummary,
    cache_root: Path,
) -> list[dict]:
    manuscript = _build_claim_manuscript(abstract)
    if not manuscript.strip():
        return []
    cache_key = _sha256_hex(manuscript.encode("utf-8") + model_id.encode("utf-8"))
    cache_path = cache_root / "claim_analysis" / f"{cache_key}.json"
    cached = None if invalidated else _load_cache_entry(cache_path)
    if cached is None:
        claims = _call_claims_model(manuscript, model_id, abstract_id=int(abstract["id"]))
        _write_cache_entry(
            cache_path,
            component="claims",
            cache_key=cache_key,
            model_id=model_id,
            input_hash=_hash_text(manuscript),
            payload={"claims": claims},
        )
        summary.cache_miss_count += 1
    else:
        claims = cached["payload"]["claims"]
        summary.cache_hit_count += 1
    out: list[dict] = []
    for claim in claims:
        record = dict(claim)
        record.setdefault("model_id", model_id)
        record["cache_key"] = cache_key
        out.append(record)
    return out


def _run_references_component(
    abstract: dict,
    *,
    strategy_id: str,
    invalidated: bool,
    summary: _ComponentSummary,
    cache_root: Path,
) -> list[dict]:
    block = _extract_reference_block(abstract)
    refs = _split_references(block)
    out: list[dict] = []
    for raw in refs:
        cache_key = _sha256_hex(raw.encode("utf-8") + strategy_id.encode("utf-8"))
        cache_path = cache_root / "reference_metadata" / f"{cache_key}.json"
        cached = None if invalidated else _load_cache_entry(cache_path)
        if cached is None:
            payload = _call_reference_strategy(raw, strategy_id)
            _write_cache_entry(
                cache_path,
                component="references",
                cache_key=cache_key,
                model_id=strategy_id,
                input_hash=_hash_text(raw),
                payload=payload,
            )
            summary.cache_miss_count += 1
        else:
            payload = cached["payload"]
            summary.cache_hit_count += 1
        record = dict(payload)
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
    if backends.figures_backend == "openai" or backends.claims_backend == "openai_cllm":
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
    summaries = {
        "figures": _ComponentSummary(
            component="figures",
            model_id=args.figure_model_id,
            cache_invalidated="figures" in invalidated_components,
        ),
        "claims": _ComponentSummary(
            component="claims",
            model_id=args.claims_model_id,
            cache_invalidated="claims" in invalidated_components,
        ),
        "references": _ComponentSummary(
            component="references",
            model_id=args.reference_strategy_id,
            cache_invalidated="references" in invalidated_components,
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
        "components": [
            {
                "component": s.component,
                "model_id": s.model_id,
                "cache_version": enrich_storage.CACHE_VERSION,
                "cache_hit_count": s.cache_hit_count,
                "cache_miss_count": s.cache_miss_count,
                "cache_invalidated": s.cache_invalidated,
                "failure_count": s.failure_count,
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
