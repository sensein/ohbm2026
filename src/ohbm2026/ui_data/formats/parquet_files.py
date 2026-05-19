"""Candidate #2: multi-file Parquet.

Each logical table becomes one ``.parquet`` file under ``output_dir``.
Browser-side decoder uses `hyparquet` (or equivalent) for per-row-group
fetches via HTTP `Range:` headers; no SQL engine.

Notes on schema choices:

- Nested fields stay nested. `Abstract.sections` → STRUCT column;
  `Abstract.facets` → STRUCT of 11 list-of-string fields (kills the
  Stage-6 third `range: Any` slot). `Abstract.topics` → STRUCT.
- The Enrichment table flattens to two parallel tables: one row per
  claim, one row per figure. Keys are `(abstract_id, claim_index)` /
  `(abstract_id, figure_index)`. The Stage-6 `{str(id): record}` dict
  is gone (FR-201 / FR-202).
- Cells / topics / neighbours stay per-cell because their layouts
  differ across cells.
- Manifest is a small one-row table; written as a Parquet file so the
  format is uniform (the decoder reads it the same way as every other
  shard).
- Compression: zstd level 3 + dictionary encoding on string columns.
  pyarrow's defaults are sound for OHBM's mostly-text workload.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

import pyarrow as pa
import pyarrow.parquet as pq

__all__ = ["write"]

_PARQUET_KWARGS = {
    "compression": "zstd",
    "compression_level": 3,
    "use_dictionary": True,
    "write_statistics": True,
}


def _facets_to_arrow(facets: Mapping[str, Any]) -> dict[str, list[str]]:
    """Coerce the 11-key facet dict to a normalised STRUCT-of-list shape.

    Stage-6 emits ``facets`` as a string-keyed dict (the `range: Any`
    slot). Stage-10 fixes the schema: each known key becomes its own
    list column. Unknown keys are dropped with a noop — defensive
    against schema drift; the LinkML lint catches anything new.
    """
    keys = (
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
        "accepted_for",
    )
    return {k: list(facets.get(k, []) or []) for k in keys}


def _abstracts_to_table(envelope: Mapping[str, Any]) -> pa.Table:
    """One row per abstract; STRUCT columns for sections / topics / facets."""
    rows = []
    for r in envelope["abstracts"]:
        rows.append(
            {
                "abstract_id": int(r["abstract_id"]),
                "poster_id": str(r["poster_id"]),
                "title": str(r.get("title", "")),
                "accepted_for": str(r.get("accepted_for", "Unknown")),
                "sections": dict(r.get("sections", {})),
                "topics": dict(r.get("topics", {})),
                "methods_checklist": list(r.get("methods_checklist", [])),
                "facets": _facets_to_arrow(r.get("facets", {})),
                "author_ids": list(r.get("author_ids", [])),
                "reference_dois": list(r.get("reference_dois", [])),
                "reference_urls": list(r.get("reference_urls", [])),
                "reference_titles": list(r.get("reference_titles", [])),
            }
        )
    return pa.Table.from_pylist(rows)


def _authors_to_table(envelope: Mapping[str, Any]) -> pa.Table:
    return pa.Table.from_pylist(envelope["authors"])


def _cell_to_table(envelope: Mapping[str, Any]) -> pa.Table:
    return pa.Table.from_pylist(envelope["rows"])


def _topic_to_table(envelope: Mapping[str, Any]) -> pa.Table:
    return pa.Table.from_pylist(envelope["topics"])


def _neighbours_to_table(envelope: Mapping[str, Any]) -> pa.Table:
    """One row per (cell, abstract_id) — un-zips the parallel arrays.

    Stage-6 stored the K-nearest / K-farthest as parallel arrays at the
    shard level. Stage-10 keeps the parallel arrays per row (so each
    row is a single abstract's neighbourhood) — that's the row-oriented
    shape Parquet's columnar storage compresses best.
    """
    rows: list[dict[str, Any]] = []
    for idx, aid in enumerate(envelope["abstract_ids"]):
        rows.append(
            {
                "abstract_id": int(aid),
                "nearest_ids": list(envelope["nearest_ids"][idx]),
                "nearest_distances": list(envelope["nearest_distances"][idx]),
                "farthest_ids": list(envelope["farthest_ids"][idx]),
                "farthest_distances": list(envelope["farthest_distances"][idx]),
            }
        )
    return pa.Table.from_pylist(rows)


def _enrichment_to_tables(envelope: Mapping[str, Any]) -> tuple[pa.Table, pa.Table]:
    """Flatten the Stage-6 ``{str(id): record}`` dict into two tables.

    Returns ``(claims_table, figures_table)``. Each row carries an
    explicit ``abstract_id`` column, eliminating the Stage-6 third
    ``range: Any`` slot.
    """
    claim_rows: list[dict[str, Any]] = []
    figure_rows: list[dict[str, Any]] = []
    for aid_str, rec in envelope.get("records", {}).items():
        aid = int(aid_str)
        for i, c in enumerate(rec.get("claims", []) or []):
            claim_rows.append({"abstract_id": aid, "claim_index": i, **c})
        for i, f in enumerate(rec.get("figures", []) or []):
            figure_rows.append({"abstract_id": aid, "figure_index": i, **f})
    claims_table = pa.Table.from_pylist(claim_rows) if claim_rows else pa.table({})
    figures_table = pa.Table.from_pylist(figure_rows) if figure_rows else pa.table({})
    return claims_table, figures_table


def _manifest_to_table(manifest: Mapping[str, Any]) -> pa.Table:
    """Single-row manifest. Store as one Parquet table.

    Nested cells / facets / search keep their dict shape via a STRUCT
    column; the browser-side decoder reads them as Maps after the
    Parquet read.
    """
    # The manifest's nested shapes are heterogeneous; serialise to JSON
    # string to keep the Parquet schema flat for the meta table. The
    # candidate emitter accepts this one JSON-blob column as an Adapter
    # per the data-model's "Adapter" rubric tag.
    flat = {
        "schema_version": str(manifest.get("schema_version", "")),
        "format": "parquet-files",
        "manifest_json": json.dumps(manifest, sort_keys=True),
    }
    return pa.Table.from_pylist([flat])


def write(
    *,
    output_dir: Path,
    build_info: Mapping[str, Any],
    conference_id: str,
    manifest: Mapping[str, Any],
    abstracts_envelope: Mapping[str, Any],
    authors_envelope: Mapping[str, Any],
    cells_envelopes: Mapping[str, Mapping[str, Any]],
    topics_envelopes: Mapping[tuple[str, str, str], Mapping[str, Any]],
    neighbors_envelopes: Mapping[str, Mapping[str, Any]],
    enrichment_envelope: Mapping[str, Any],
    minilm_bin: bytes | None,
    minilm_sidecar: Mapping[str, Any],
) -> set[Path]:
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    expected: set[Path] = set()

    def _write(table: pa.Table, rel: str) -> None:
        target = out / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        pq.write_table(table, target, **_PARQUET_KWARGS)
        expected.add(target)

    _write(_manifest_to_table(manifest), "manifest.parquet")
    _write(_abstracts_to_table(abstracts_envelope), "abstracts.parquet")
    _write(_authors_to_table(authors_envelope), "authors.parquet")
    claims_t, figures_t = _enrichment_to_tables(enrichment_envelope)
    if claims_t.num_rows:
        _write(claims_t, "enrichment_claims.parquet")
    if figures_t.num_rows:
        _write(figures_t, "enrichment_figures.parquet")
    for cell_key, env in cells_envelopes.items():
        _write(_cell_to_table(env), f"cells/{cell_key}.parquet")
    for (model, inp, kind), env in topics_envelopes.items():
        _write(_topic_to_table(env), f"topics/{model}_{inp}_{kind}.parquet")
    for cell_key, env in neighbors_envelopes.items():
        _write(_neighbours_to_table(env), f"neighbors/{cell_key}.parquet")

    # MiniLM int8 vectors: keep as a binary sidecar — Parquet would
    # carry an opaque BLOB column with no compression win.
    if minilm_bin is not None:
        bin_path = out / "search" / "minilm_vectors.bin"
        bin_path.parent.mkdir(parents=True, exist_ok=True)
        bin_path.write_bytes(minilm_bin)
        expected.add(bin_path)
    sidecar_path = out / "search" / "minilm_vectors.build_info.json"
    sidecar_path.parent.mkdir(parents=True, exist_ok=True)
    sidecar_path.write_text(json.dumps(minilm_sidecar, sort_keys=True))
    expected.add(sidecar_path)

    return expected
