"""Stage 1 orchestrator — fetch abstracts + persist GraphQL schema.

Replaces the legacy ``ohbmcli ingest`` invocation per FR-014. Calls
out to ``graphql_api`` for upstream I/O, ``schema_diff`` for tiered
drift detection, ``assets`` for the per-record batched fetch with
checkpoint hooks, and ``artifacts`` for path derivation + state-key.

Six contract elements documented in ``docs/per-stage-pattern.md`` and
verified in ``tests/test_fetch_stage.py``:

- **Input contract**: ``OHBM2026_API`` env var (name only). See
  ``_load_api_key`` and ``_build_parser``.
- **Output contract**: corpus snapshot, schema artifact, provenance
  record. See ``_write_corpus``, ``_write_schema_artifact``,
  ``_write_provenance``.
- **Provenance contract**: machine-readable record with no
  absolute/user-home paths. See ``_build_provenance_record`` and
  ``_assert_project_relative``.
- **Error contract**: typed exceptions; loud failures; specific exit
  codes. See ``main``.
- **Resumability contract**: dual-granularity checkpoint, atomic
  rename. See ``_load_or_init_checkpoint`` and ``_atomic_write_json``.
- **Discovery contract**: GraphQL introspection + tiered schema diff.
  See ``_run_introspection`` and ``_classify_schema_drift``.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ohbm2026 import artifacts, assets
from ohbm2026.fetch import graphql_api as _gql
from ohbm2026.fetch import schema_diff as _schema_diff
from ohbm2026.exceptions import (
    CheckpointError,
    FigureFailureError,
    GraphQLAPIError,
    ProvenanceError,
    SchemaContractError,
    Stage1Error,
)

# The orchestrator does not read from `data/primary/abstracts.json`;
# declaration is empty (research.md §4 convention).
CONSUMED_ABSTRACT_FIELDS: frozenset[tuple[str, str]] = frozenset()

PROVENANCE_VERSION = "fetch.provenance.v1"
CHECKPOINT_VERSION = "fetch.checkpoint.v1"
SCHEMA_ARTIFACT_VERSION = "fetch.schema.v1"

# Exit codes per contracts/cli.md.
EXIT_OK = 0
EXIT_GRAPHQL_ERROR = 1
EXIT_SCHEMA_DRIFT = 2
EXIT_CHECKPOINT_ERROR = 3
EXIT_PROVENANCE_ERROR = 4
EXIT_FIGURE_FAILURE = 5
EXIT_EMPTY_CORPUS = 6


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        return _run(args, list(argv) if argv is not None else sys.argv[1:])
    except SchemaContractError as exc:
        print(f"[fetch-abstracts] HARD-tier schema drift: {exc}", file=sys.stderr)
        return EXIT_SCHEMA_DRIFT
    except CheckpointError as exc:
        print(f"[fetch-abstracts] checkpoint error: {exc}", file=sys.stderr)
        return EXIT_CHECKPOINT_ERROR
    except ProvenanceError as exc:
        print(f"[fetch-abstracts] provenance error: {exc}", file=sys.stderr)
        return EXIT_PROVENANCE_ERROR
    except FigureFailureError as exc:
        print(f"[fetch-abstracts] {exc}", file=sys.stderr)
        return EXIT_FIGURE_FAILURE
    except GraphQLAPIError as exc:
        print(f"[fetch-abstracts] GraphQL error: {exc}", file=sys.stderr)
        return EXIT_GRAPHQL_ERROR
    except Stage1Error as exc:
        # Default Stage1Error subclass handler (e.g. empty corpus).
        if "empty corpus" in str(exc).lower():
            print(f"[fetch-abstracts] {exc}", file=sys.stderr)
            return EXIT_EMPTY_CORPUS
        print(f"[fetch-abstracts] {exc}", file=sys.stderr)
        return EXIT_GRAPHQL_ERROR


CORPUS_KINDS = ("accepted", "withdrawn")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Stage 1: fetch OHBM 2026 abstracts + persist GraphQL schema"
    )
    parser.add_argument(
        "--corpus-kind",
        choices=CORPUS_KINDS,
        default="accepted",
        help=(
            "Which corpus to fetch. `accepted` (default) uses "
            "ABSTRACT_IDS_QUERY and writes data/primary/abstracts.json. "
            "`withdrawn` uses WITHDRAWN_IDS_QUERY and writes "
            "data/primary/abstracts_withdrawn.json. The two corpora "
            "never mix; each has its own state-key namespace."
        ),
    )
    parser.add_argument("--env-file", default=".env")
    parser.add_argument("--env-var", default="OHBM2026_API")
    parser.add_argument("--batch-size", type=int, default=50)
    parser.add_argument("--timeout-start-ms", type=int, default=100)
    parser.add_argument("--timeout-limit-seconds", type=float, default=10.0)
    parser.add_argument("--figure-failure-threshold", type=float, default=0.05)
    parser.add_argument("--allow-empty", action="store_true")
    parser.add_argument("--allow-schema-change", action="store_true")
    parser.add_argument("--no-introspect", action="store_true")
    parser.add_argument("--corpus-output", default=None)
    parser.add_argument("--schema-artifact-dir", default=None)
    parser.add_argument("--checkpoint-dir", default=None)
    parser.add_argument("--assets-dir", default=None)
    parser.add_argument("--reuse-existing-assets-only", action="store_true")
    return parser


def _run(args: argparse.Namespace, argv: list[str]) -> int:
    cwd = Path.cwd()

    # ── Input contract ──
    api_key = _load_api_key(cwd, args)

    # ── Discovery contract: state key + introspection + diff ──
    state_key = _compute_state_key(args)
    schema_artifact_path = cwd / artifacts.build_schema_artifact_path(state_key)
    corpus_path = _resolve_corpus_path(cwd, args)
    provenance_path = cwd / artifacts.build_provenance_path(state_key)
    checkpoint_path = cwd / artifacts.build_fetch_checkpoint_path(state_key)
    _assert_project_relative(cwd, schema_artifact_path, provenance_path, checkpoint_path)

    introspection_raw = _run_introspection(api_key, args)
    field_index = _schema_diff.flatten_introspection(introspection_raw)
    current_schema_hash = _schema_diff.hash_field_index(field_index)

    previous_schema_hash, schema_diff_summary = _classify_schema_drift(
        cwd, schema_artifact_path, field_index
    )
    if any(e.tier == "HARD" for e in schema_diff_summary):
        hard = [e for e in schema_diff_summary if e.tier == "HARD"]
        raise SchemaContractError(
            f"HARD-tier drift on {len(hard)} field(s): "
            + ", ".join(f"{e.type_name}.{e.field_name}" for e in hard[:10])
        )

    # ── Resumability contract: checkpoint lifecycle ──
    checkpoint, resumed = _load_or_init_checkpoint(
        checkpoint_path,
        state_key=state_key,
        current_schema_hash=current_schema_hash,
        allow_schema_change=args.allow_schema_change,
    )

    if checkpoint is None:
        # Fresh run: enumerate submissions for the chosen corpus kind
        # and initialize checkpoint.
        ids_fetcher = _resolve_ids_fetcher(args.corpus_kind)
        event_ids, all_submission_ids = ids_fetcher(api_key)
        checkpoint = _new_checkpoint(state_key, current_schema_hash, all_submission_ids, args.batch_size)
        _atomic_write_json(checkpoint_path, checkpoint)
    else:
        all_submission_ids = list(checkpoint.get("all_submission_ids") or [])
        # On resume, don't re-call fetch_abstract_ids; trust the
        # checkpoint's ID universe.
        event_ids = []

    if not all_submission_ids and not args.allow_empty:
        raise Stage1Error("semantically empty corpus (zero accepted submissions)")

    # Compute pending IDs and run the per-batch fetch with hooks.
    completed_ids = set(checkpoint.get("completed_submission_ids") or [])
    pending_ids = [sid for sid in all_submission_ids if sid not in completed_ids]

    abstracts_new: list[dict[str, Any]] = []
    request_counter = {"count": 0, "retries": 0, "reasons": {}}

    def on_batch_complete(batch_ids: list[int]) -> None:
        request_counter["count"] += 1
        merged = sorted(set(checkpoint.get("completed_submission_ids") or []) | set(batch_ids))
        checkpoint["completed_submission_ids"] = merged
        checkpoint["in_flight_batch"] = None
        checkpoint["last_updated_at"] = _utc_now()
        _atomic_write_json(checkpoint_path, checkpoint)

    def on_record_state_change(sid: int, state: str) -> None:
        # Stage 1 v1 emits per-record states for observability; the
        # batch-level checkpoint is the persisted source of truth.
        pass

    assets_dir = _resolve_assets_dir(cwd, args)

    for abstract in assets.fetch_content_batches(
        api_key=api_key,
        submission_ids=pending_ids,
        batch_size=args.batch_size,
        on_batch_complete=on_batch_complete,
        on_record_state_change=on_record_state_change,
        assets_dir=assets_dir,
        reuse_existing_assets_only=args.reuse_existing_assets_only,
        timeout_start=args.timeout_start_ms / 1000,
        timeout_limit=args.timeout_limit_seconds,
    ):
        abstracts_new.append(abstract)

    # Merge previously-completed records from the prior corpus (if any)
    # so the final snapshot is the full corpus, not just this run's
    # delta. Production hardening note: a future iteration can persist
    # completed records inside the checkpoint to eliminate dependence
    # on the prior corpus file surviving across runs.
    abstracts_combined: list[dict[str, Any]] = list(abstracts_new)
    new_ids = {a.get("id") for a in abstracts_new}
    if resumed and corpus_path.exists():
        try:
            previous_corpus = json.loads(corpus_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            previous_corpus = {}
        for prev in previous_corpus.get("abstracts", []) or []:
            pid = prev.get("id")
            if pid in completed_ids and pid not in new_ids:
                abstracts_combined.append(prev)

    abstracts_combined.sort(key=lambda a: a.get("id") or 0)
    final_count = len(abstracts_combined)
    if final_count == 0 and not args.allow_empty:
        raise Stage1Error("semantically empty corpus (zero accepted submissions)")

    # ── Output contract: write corpus + schema artifact + provenance ──
    _write_schema_artifact(
        schema_artifact_path,
        state_key=state_key,
        schema_hash=current_schema_hash,
        introspection_raw=introspection_raw,
        field_index=field_index,
    )

    _write_corpus(corpus_path, event_ids, abstracts_combined)

    # ── Author roster (FR-023) ──
    authors_path = _resolve_authors_path(cwd, args)
    _assert_project_relative(cwd, authors_path)
    author_count = _fetch_and_write_authors(
        api_key=api_key,
        abstracts=abstracts_combined,
        output_path=authors_path,
        request_counter=request_counter,
    )

    figure_asset_count, figure_failure_count = _count_figure_outcomes(abstracts_combined)

    # Figure-failure-rate gate: hard-fail only if the failure RATE
    # exceeds the configured threshold over the attempts that actually
    # touched the network (downloaded vs failed; terminal skips like
    # invalid-URL don't count against the budget).
    total_attempts = figure_asset_count + figure_failure_count
    if (
        total_attempts > 0
        and (figure_failure_count / total_attempts) > args.figure_failure_threshold
    ):
        raise FigureFailureError(
            f"figure-asset failure rate "
            f"{figure_failure_count}/{total_attempts} "
            f"({figure_failure_count / total_attempts:.1%}) exceeds "
            f"--figure-failure-threshold={args.figure_failure_threshold:.1%}"
        )

    provenance = _build_provenance_record(
        cwd=cwd,
        state_key=state_key,
        run_id=checkpoint["run_id"],
        argv=argv,
        env_var=args.env_var,
        endpoint_url=_gql.GRAPHQL_ENDPOINT,
        request_counter=request_counter,
        abstract_count=final_count,
        figure_asset_count=figure_asset_count,
        figure_failure_count=figure_failure_count,
        schema_artifact_path=schema_artifact_path,
        schema_hash=current_schema_hash,
        previous_schema_hash=previous_schema_hash,
        schema_diff_summary=schema_diff_summary,
        checkpoint_path=checkpoint_path if resumed else None,
        resumed=resumed,
        authors_path=authors_path,
        author_count=author_count,
    )
    _write_provenance(provenance_path, provenance)

    # Delete checkpoint on full completion.
    if checkpoint_path.exists():
        checkpoint_path.unlink()

    summary = {
        "corpus_output": _project_relative(cwd, corpus_path),
        "authors_output": _project_relative(cwd, authors_path),
        "schema_artifact": _project_relative(cwd, schema_artifact_path),
        "provenance_record": _project_relative(cwd, provenance_path),
        # Stage 11.1 US4 — renamed from `state_key` for the summary
        # printed to stdout (operator-facing).
        "fetch_state_key": state_key,
        "abstract_count": final_count,
        "author_count": author_count,
        "figure_asset_count": figure_asset_count,
        "figure_failure_count": figure_failure_count,
        "resumed_from_previous_run": resumed,
        "schema_diff_vs_previous": {
            "hard_count": sum(1 for e in schema_diff_summary if e.tier == "HARD"),
            "soft_count": sum(1 for e in schema_diff_summary if e.tier == "SOFT"),
            "informational_count": sum(1 for e in schema_diff_summary if e.tier == "INFORMATIONAL"),
        },
    }
    print(json.dumps(summary, indent=2))
    return EXIT_OK


# ── Helpers ──────────────────────────────────────────────────────────


def _load_api_key(cwd: Path, args: argparse.Namespace) -> str:
    env_file_arg = Path(args.env_file)
    env_file = env_file_arg if env_file_arg.is_absolute() else (cwd / env_file_arg)
    return _gql.get_api_key(env_file, args.env_var)


def _resolve_corpus_path(cwd: Path, args: argparse.Namespace) -> Path:
    if args.corpus_output:
        candidate = Path(args.corpus_output)
        return candidate if candidate.is_absolute() else (cwd / candidate)
    if args.corpus_kind == "withdrawn":
        return cwd / artifacts.PRIMARY_WITHDRAWN_ABSTRACTS_PATH
    return cwd / artifacts.PRIMARY_ABSTRACTS_PATH


def _resolve_ids_fetcher(corpus_kind: str):
    """Return the appropriate ID-fetcher callable for the corpus kind.
    Accepted uses fetch_abstract_ids; withdrawn uses
    fetch_withdrawn_ids. The two have disjoint upstream filters and
    must never be conflated."""
    if corpus_kind == "withdrawn":
        return _gql.fetch_withdrawn_ids
    return _gql.fetch_abstract_ids


def _resolve_assets_dir(cwd: Path, args: argparse.Namespace) -> Path:
    if args.assets_dir:
        candidate = Path(args.assets_dir)
        return candidate if candidate.is_absolute() else (cwd / candidate)
    return cwd / artifacts.PRIMARY_ASSETS_ROOT


def _resolve_authors_path(cwd: Path, args: argparse.Namespace) -> Path:
    """FR-023 / FR-022 parallel: corpus_kind=accepted writes to
    `data/primary/authors.json`; corpus_kind=withdrawn writes to
    `data/primary/authors_withdrawn.json`. Files never mix."""
    if args.corpus_kind == "withdrawn":
        return cwd / artifacts.PRIMARY_AUTHORS_WITHDRAWN_PATH
    return cwd / artifacts.PRIMARY_AUTHORS_PATH


def _fetch_and_write_authors(
    *,
    api_key: str,
    abstracts: list[dict[str, Any]],
    output_path: Path,
    request_counter: dict[str, Any],
) -> int:
    """Collect unique author IDs from the corpus, fetch their details
    via the existing AUTHOR_QUERY, normalize each (dropping email per
    FR-023), and write the roster atomically. Returns the author count.

    The fetch piggybacks on the same run's API key and request
    counter; each author batch (200 IDs) increments the counter.
    Empty author lists are OK — the on-disk file still gets written
    with author_count=0 so downstream consumers can read it
    unconditionally."""
    author_ids: set[int] = set()
    for abstract in abstracts:
        for author in (abstract.get("authors") or []):
            aid = author.get("id") if isinstance(author, dict) else None
            if isinstance(aid, int):
                author_ids.add(aid)
    sorted_ids = sorted(author_ids)

    raw_authors: list[dict[str, Any]] = []
    if sorted_ids:
        raw_authors = _gql.fetch_author_details(api_key, sorted_ids)
        # fetch_author_details batches internally at 200 IDs/batch;
        # count one request per batch.
        request_counter["count"] += (len(sorted_ids) + 199) // 200

    normalized = sorted(
        (assets.normalize_author(a) for a in raw_authors),
        key=lambda a: a.get("id") or 0,
    )
    payload = {
        "fetched_at": _utc_now(),
        "author_count": len(normalized),
        "authors": normalized,
    }
    _atomic_write_json(output_path, payload)
    return len(normalized)


def _compute_state_key(args: argparse.Namespace) -> str:
    ids_query = (
        _gql.WITHDRAWN_IDS_QUERY
        if args.corpus_kind == "withdrawn"
        else _gql.ABSTRACT_IDS_QUERY
    )
    basis = artifacts.build_dependency_basis(
        input_sources=[_gql.GRAPHQL_ENDPOINT],
        options={
            "corpus_kind": args.corpus_kind,
            "ids_query": ids_query,
            "content_query": _gql.ABSTRACT_CONTENTS_QUERY,
            "introspection_query": _gql.INTROSPECTION_QUERY,
            "batch_size": args.batch_size,
        },
        env_boundary=[args.env_var],
    )
    return artifacts.build_state_key(basis, schema_version="fetch.v1")


def _run_introspection(api_key: str, args: argparse.Namespace) -> dict[str, Any]:
    if args.no_introspect:
        return {"queryType": {"name": "Query"}, "types": []}
    return _gql.fetch_schema_introspection(api_key)


def _classify_schema_drift(
    cwd: Path,
    schema_artifact_path: Path,
    current_index: list[_schema_diff.FieldIndexEntry],
) -> tuple[str | None, list[_schema_diff.SchemaDiffEntry]]:
    if not schema_artifact_path.exists():
        return None, []
    try:
        previous = json.loads(schema_artifact_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None, []
    previous_index = [
        _schema_diff.FieldIndexEntry.from_dict(d)
        for d in (previous.get("field_index") or [])
    ]
    previous_hash = previous.get("schema_hash")

    hard_set = _schema_diff.parse_hard_set_from_queries(
        _gql.ABSTRACT_IDS_QUERY,
        _gql.ABSTRACT_CONTENTS_QUERY,
    )
    soft_set = _schema_diff.collect_soft_contract_fields(_iter_consumer_modules())
    diffs = _schema_diff.compare(
        previous_index, current_index, hard_set=hard_set, soft_set=soft_set
    )
    return previous_hash, diffs


def _iter_consumer_modules() -> list[object]:
    """Return modules under ``ohbm2026.*`` that declare
    ``CONSUMED_ABSTRACT_FIELDS``. Stage 1 v1 has none populated; the
    list is collected at runtime so later stages can opt in just by
    adding the attribute to their module."""
    import importlib
    out: list[object] = []
    for mod_name in (
        "ohbm2026.assets",
        "ohbm2026.fetch.stage",
    ):
        try:
            mod = importlib.import_module(mod_name)
        except ImportError:
            continue
        if hasattr(mod, "CONSUMED_ABSTRACT_FIELDS"):
            out.append(mod)
    return out


def _new_checkpoint(
    state_key: str,
    schema_hash: str,
    all_submission_ids: list[int],
    batch_size: int,
) -> dict[str, Any]:
    return {
        "checkpoint_version": CHECKPOINT_VERSION,
        # Stage 11.1 US4 — renamed from `state_key` so the field
        # name no longer collides verbally with Stage 6's
        # `corpus_state_key`. Readers go through
        # `artifacts.read_fetch_state_key` which accepts both names.
        "fetch_state_key": state_key,
        "bound_schema_hash": schema_hash,
        "started_at": _utc_now(),
        "last_updated_at": _utc_now(),
        "run_id": str(uuid.uuid4()),
        "all_submission_ids": list(all_submission_ids),
        "batch_size": batch_size,
        "completed_submission_ids": [],
        "in_flight_batch": None,
    }


def _load_or_init_checkpoint(
    checkpoint_path: Path,
    *,
    state_key: str,
    current_schema_hash: str,
    allow_schema_change: bool,
) -> tuple[dict[str, Any] | None, bool]:
    if not checkpoint_path.exists():
        return None, False
    try:
        ckpt = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise CheckpointError(
            f"Existing checkpoint {checkpoint_path} is unreadable: {exc}"
        ) from exc

    # Accept both field names during the migration window (Stage 11.1 US4).
    ckpt_state_key = ckpt.get("fetch_state_key", ckpt.get("state_key"))
    if ckpt_state_key != state_key:
        raise CheckpointError(
            f"Checkpoint fetch_state_key={ckpt_state_key!r} does not match "
            f"current run fetch_state_key={state_key!r}"
        )

    if ckpt.get("bound_schema_hash") != current_schema_hash and not allow_schema_change:
        raise CheckpointError(
            f"Checkpoint bound_schema_hash={ckpt.get('bound_schema_hash')[:12]!r} "
            f"does not match current schema_hash={current_schema_hash[:12]!r}. "
            f"Refusing to resume silently. Pass --allow-schema-change to "
            f"override (only after confirming the schema change does not "
            f"alter any field the in-flight records depend on)."
        )

    return ckpt, True


def _write_schema_artifact(
    path: Path,
    *,
    state_key: str,
    schema_hash: str,
    introspection_raw: dict[str, Any],
    field_index: list[_schema_diff.FieldIndexEntry],
) -> None:
    payload = {
        "schema_version": SCHEMA_ARTIFACT_VERSION,
        "fetched_at": _utc_now(),
        "endpoint_url": _gql.GRAPHQL_ENDPOINT,
        # Stage 11.1 US4 — renamed field. See _new_checkpoint().
        "fetch_state_key": state_key,
        "schema_hash": schema_hash,
        "introspection_raw": introspection_raw,
        "field_index": [e.to_dict() for e in field_index],
    }
    _atomic_write_json(path, payload)


def _write_corpus(path: Path, event_ids: list[int], abstracts_list: list[dict[str, Any]]) -> None:
    payload = {
        "fetched_at": _utc_now(),
        "event_ids": list(event_ids),
        "abstract_count": len(abstracts_list),
        "abstracts": abstracts_list,
    }
    _atomic_write_json(path, payload)


def _build_provenance_record(
    *,
    cwd: Path,
    state_key: str,
    run_id: str,
    argv: list[str],
    env_var: str,
    endpoint_url: str,
    request_counter: dict[str, Any],
    abstract_count: int,
    figure_asset_count: int,
    figure_failure_count: int,
    schema_artifact_path: Path,
    schema_hash: str,
    previous_schema_hash: str | None,
    schema_diff_summary: list[_schema_diff.SchemaDiffEntry],
    checkpoint_path: Path | None,
    resumed: bool,
    authors_path: Path,
    author_count: int,
) -> dict[str, Any]:
    diff_payload = None
    if previous_schema_hash is not None:
        diff_payload = {
            "previous_schema_hash": previous_schema_hash,
            "current_schema_hash": schema_hash,
            "entries": [
                {
                    "tier": e.tier,
                    "change_kind": e.change_kind,
                    "type_name": e.type_name,
                    "field_name": e.field_name,
                    "previous": e.previous,
                    "current": e.current,
                    "downstream_consumers": list(e.downstream_consumers),
                }
                for e in schema_diff_summary
            ],
        }

    record = {
        "provenance_version": PROVENANCE_VERSION,
        "run_id": run_id,
        # Stage 11.1 US4 — renamed field.
        "fetch_state_key": state_key,
        "run_timestamp": _utc_now(),
        "code_revision": _git_revision(cwd),
        "command_line": ["fetch-abstracts", *argv],
        "env_vars_consulted": [env_var],
        "endpoint_url": endpoint_url,
        "query_count": int(request_counter.get("count", 0)),
        "request_retry_count": int(request_counter.get("retries", 0)),
        "retry_reasons": dict(request_counter.get("reasons") or {}),
        "total_response_bytes": 0,
        "abstract_count": abstract_count,
        "figure_asset_count": figure_asset_count,
        "figure_failure_count": figure_failure_count,
        "schema_artifact_path": _project_relative(cwd, schema_artifact_path),
        "schema_hash": schema_hash,
        "schema_diff_vs_previous": diff_payload,
        "checkpoint_path": _project_relative(cwd, checkpoint_path) if checkpoint_path else None,
        "resumed_from_previous_run": resumed,
        "authors_path": _project_relative(cwd, authors_path),
        "author_count": author_count,
    }
    _assert_provenance_paths_safe(record)
    return record


def _write_provenance(path: Path, record: dict[str, Any]) -> None:
    _atomic_write_json(path, record)


def _count_figure_outcomes(abstracts_list: list[dict[str, Any]]) -> tuple[int, int]:
    asset_count = 0
    failure_count = 0
    for a in abstracts_list:
        for la in a.get("local_assets") or []:
            if la.get("downloaded"):
                asset_count += 1
            elif la.get("error"):
                failure_count += 1
    return asset_count, failure_count


def _assert_provenance_paths_safe(record: dict[str, Any]) -> None:
    for key in ("schema_artifact_path", "checkpoint_path", "authors_path"):
        value = record.get(key)
        if value is None:
            continue
        if value.startswith("/") or value.startswith("~"):
            raise ProvenanceError(
                f"Provenance field {key!r} contains an absolute / user-home "
                f"path: {value!r}. All paths must be project-relative."
            )


def _assert_project_relative(cwd: Path, *paths: Path) -> None:
    for p in paths:
        # `p` may be expressed as `cwd / Path("data/...")`, which makes it
        # absolute. For the no-absolute-paths assertion, we compute the
        # relative form: it must not start with '..' (would escape the
        # repo root) and must not be `~`-prefixed.
        try:
            rel = p.relative_to(cwd)
        except ValueError as exc:
            raise ProvenanceError(
                f"Target path {p} escapes the project root {cwd}"
            ) from exc
        rel_str = str(rel)
        if rel_str.startswith("..") or rel_str.startswith("~"):
            raise ProvenanceError(f"Target path {p} resolves outside project root")


def _project_relative(cwd: Path, p: Path) -> str:
    try:
        return str(p.relative_to(cwd))
    except ValueError:
        return str(p)


def _atomic_write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=path.name + ".",
        suffix=".tmp",
        dir=str(path.parent),
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, sort_keys=False)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_name, path)
    except Exception:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass
        raise


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _git_revision(cwd: Path) -> dict[str, Any]:
    try:
        sha = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(cwd),
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        ).stdout.strip()
        status = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=str(cwd),
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return {"git_sha": "unknown", "dirty": False}
    return {"git_sha": sha or "unknown", "dirty": bool(status)}
