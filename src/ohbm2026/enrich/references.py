"""Stage 2.1 references-component runner.

Thin adapter: wraps the existing `openalex.py` resolution pipeline
through the orchestrator's `_call_reference_strategy` seam. No new
resolution logic in Stage 2.1; just wire-up + record-shape massage.

Drives FR-014.
"""

from __future__ import annotations

import dataclasses
import hashlib
import re
from typing import Any, Literal

from ohbm2026.exceptions import EnrichmentError

__all__ = [
    "ReferencesRunSummary",
    "run_references_component",
]


@dataclasses.dataclass
class ReferencesRunSummary:
    reference_count: int
    resolved_count: int
    unresolved_count: int
    latency_ms: float


def _extract_reference_block(abstract: dict) -> str:
    """Pull the references markdown block from the abstract's
    responses list."""
    for response in abstract.get("responses", []) or []:
        name = (response.get("question_name") or "").strip().lower()
        if "reference" in name:
            return (response.get("value") or "").strip()
    return ""


def _split_references(reference_block: str) -> list[str]:
    """Best-effort line-split fallback for the synchronous case.

    The full reference-resolution pipeline in `openalex.py` does
    its own LLM-assisted splitting; this helper is the
    minimum-viable splitter for cases where the async path isn't
    invoked.
    """
    if not reference_block:
        return []
    return [line.strip() for line in reference_block.splitlines() if line.strip()]


def _cache_key(raw_reference: str, strategy_id: str) -> str:
    h = hashlib.sha256()
    h.update(raw_reference.encode("utf-8"))
    h.update(b"||")
    h.update(strategy_id.encode("utf-8"))
    return h.hexdigest()


def _coerce_resolution_record(
    raw: Any, *, raw_reference: str, strategy_id: str
) -> dict:
    """Map an openalex-style resolution result onto the Stage 2
    `ReferenceResolution` schema (raw_reference, doi, pmid,
    openalex_id, title, authors, year, resolution_status,
    resolution_source, strategy_id, cache_key)."""
    if isinstance(raw, dict):
        out = dict(raw)
    else:
        out = {}
    out.setdefault("raw_reference", raw_reference)
    out.setdefault("doi", None)
    out.setdefault("pmid", None)
    out.setdefault("openalex_id", None)
    out.setdefault("title", None)
    out.setdefault("authors", None)
    out.setdefault("year", None)
    status = out.get("resolution_status")
    if status not in {"resolved", "partial", "unresolved"}:
        # Coerce booleans / unknown values to a documented enum
        # value so the downstream record satisfies the contract.
        if status:
            out["resolution_status"] = "partial"
        else:
            out["resolution_status"] = "unresolved"
    out.setdefault("resolution_source", None)
    out["strategy_id"] = strategy_id
    out["cache_key"] = _cache_key(raw_reference, strategy_id)
    return out


def run_references_component(
    abstract: dict,
    *,
    strategy_id: str,
    resolver: Any | None = None,
) -> tuple[list[dict], ReferencesRunSummary]:
    """Run the references component for one abstract.

    `resolver` is the bound openalex callable that takes
    `(reference_text, strategy_id, **opts)` and returns a list of
    resolution-result records. Tests inject a callable; production
    callers wire it to `openalex.collect_reference_metadata` (or
    a sync wrapper around the existing async pipeline).

    Returns `(resolution_record_list, ReferencesRunSummary)`.

    Raises `EnrichmentError` only when the resolver itself errors;
    per-reference unresolvable results are recorded as
    `resolution_status="unresolved"` and do NOT abort the run.
    """
    import time

    block = _extract_reference_block(abstract)
    if not block:
        return [], ReferencesRunSummary(0, 0, 0, 0.0)

    if resolver is None:
        # Default resolver: local DOI/PMID extraction only. Returns
        # `resolution_status="unresolved"` for every reference unless
        # a DOI or PMID can be extracted from the raw text. The
        # heavyweight OpenAlex / Semantic Scholar resolution path
        # lives in `openalex.collect_reference_cache` and operates
        # on the whole corpus at once; wiring it to a per-abstract
        # seam requires a separate spec round (Stage 2.2 candidate).
        # Operators can pass an explicit resolver via the
        # `resolver=` kwarg to plug richer resolution in.
        from ohbm2026.enrich import openalex as _openalex

        def _local_resolver(reference_text: str, strategy_id: str) -> list[dict]:
            lines = _split_references(reference_text)
            records: list[dict] = []
            for raw in lines:
                dois = _openalex.extract_dois(raw)
                pmid = _openalex.extract_pmid(raw)
                title = _openalex.guess_reference_title(raw)
                year = _openalex.extract_reference_year(raw)
                doi = _openalex.normalize_doi(dois[0]) if dois else None
                status = "partial" if (doi or pmid) else "unresolved"
                source = "local_doi" if doi else ("local_pmid" if pmid else None)
                records.append({
                    "raw_reference": raw,
                    "doi": doi,
                    "pmid": pmid,
                    "openalex_id": None,
                    "title": title or None,
                    "authors": None,
                    "year": year,
                    "resolution_status": status,
                    "resolution_source": source,
                })
            return records
        resolver = _local_resolver

    start = time.perf_counter()
    try:
        raw_results = resolver(reference_text=block, strategy_id=strategy_id)
    except TypeError:
        # Fallback to positional signature.
        try:
            raw_results = resolver(block, strategy_id)
        except Exception as exc:
            raise EnrichmentError(
                f"references: resolver call failed: {type(exc).__name__}: {exc}"
            ) from exc
    except Exception as exc:
        raise EnrichmentError(
            f"references: resolver call failed: {type(exc).__name__}: {exc}"
        ) from exc
    elapsed_ms = (time.perf_counter() - start) * 1000.0

    if raw_results is None:
        raw_results = []

    out: list[dict] = []
    resolved = 0
    unresolved = 0
    # The resolver may return results in the same order as the raw
    # references (when its own splitter ran) OR may return a single
    # bundle for the whole block. Defensively split locally if the
    # resolver gave back fewer results than reference lines.
    lines = _split_references(block)
    iter_lines = iter(lines) if lines else iter([block])
    for result in raw_results:
        raw_reference = (
            result.get("raw_reference") if isinstance(result, dict) else None
        ) or next(iter_lines, block)
        record = _coerce_resolution_record(
            result, raw_reference=raw_reference, strategy_id=strategy_id,
        )
        if record["resolution_status"] == "resolved":
            resolved += 1
        else:
            unresolved += 1
        out.append(record)

    summary = ReferencesRunSummary(
        reference_count=len(out),
        resolved_count=resolved,
        unresolved_count=unresolved,
        latency_ms=elapsed_ms,
    )
    return out, summary
