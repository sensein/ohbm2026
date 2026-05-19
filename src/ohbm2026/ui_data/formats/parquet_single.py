"""Stage-10 canonical: single-file Parquet container.

One ``data.parquet`` file containing every logical table as a row,
where each row holds serialized Parquet bytes for that table in a
``table_bytes`` BLOB column. ``row_group_size=1`` is used so each
row lands in its own row group — the Parquet footer then carries
explicit per-row-group byte offsets, which the browser-side decoder
can use to issue an HTTP Range request for exactly one logical
table at a time (Phase-4 lazy load).

This is the only Parquet variant compatible with the project's
single-URL deploy model: the SvelteKit bundle is the only thing
shipped to gh-pages; data is fetched at runtime from
``OHBM2026_UI_DATA_PACKAGE_URL`` (Dropbox) with no per-shard mirror.
Multi-file Parquet would require a tarball wrap that defeats per-table
range fetch.

Browser-side decode pattern lives in
``site/src/lib/data_package/tarball.ts`` (kept its Stage-6 filename
for diff churn; the substance is parquet-only). The decoder unpacks
the outer file into a ``Map<path, JsonValue | Uint8Array>`` whose
keys are the Stage-6 shard paths the UI components already consume.

Schema choices:

- Nested fields stay nested. ``Abstract.sections`` → STRUCT column;
  ``Abstract.facets`` → STRUCT of 11 list-of-string fields (kills the
  Stage-6 third ``range: Any`` slot). ``Abstract.topics`` → STRUCT.
- The Enrichment table flattens to two parallel tables: one row per
  claim, one row per figure. Keys are ``(abstract_id, claim_index)``
  / ``(abstract_id, figure_index)``. The Stage-6 ``{str(id): record}``
  dict is gone (FR-201 / FR-202).
- Cells / topics / neighbours stay per-cell because their layouts
  differ across cells.
- Manifest is a small one-row table; the nested cells / facets / search
  fields are heterogeneous, so the manifest is serialised to a JSON
  string column. The browser-side decoder parses it back.
- Compression: zstd level 3 + dictionary encoding on string columns
  for the inner blobs; outer file uses non-dict encoding to keep the
  per-row BLOB byte offsets straightforward.
"""

from __future__ import annotations

import io
import json
from pathlib import Path
from typing import Any, Mapping

import pyarrow as pa
import pyarrow.parquet as pq

__all__ = ["write"]

_INNER_PARQUET_KWARGS = {
    "compression": "zstd",
    "compression_level": 3,
    "use_dictionary": True,
    "write_statistics": True,
}

_OUTER_PARQUET_KWARGS = {
    "compression": "zstd",
    "compression_level": 3,
    "use_dictionary": False,
    "write_statistics": True,
    "row_group_size": 1,
}


def _facets_to_arrow(facets: Mapping[str, Any]) -> dict[str, list[str]]:
    """Coerce the 11-key facet dict to a normalised STRUCT-of-list shape.

    Stage-6 emits ``facets`` as a string-keyed dict (the ``range: Any``
    slot). Stage-10 fixes the schema: each known key becomes its own
    list column. Unknown keys are dropped with a noop.
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
    flat = {
        "schema_version": str(manifest.get("schema_version", "")),
        "format": "parquet-single",
        "manifest_json": json.dumps(manifest, sort_keys=True),
    }
    return pa.Table.from_pylist([flat])


def _to_inner_parquet_bytes(table: pa.Table) -> bytes:
    buf = io.BytesIO()
    pq.write_table(table, buf, **_INNER_PARQUET_KWARGS)
    return buf.getvalue()


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
    target = out / "data.parquet"

    entries: list[tuple[str, bytes]] = []

    manifest_with_format = dict(manifest)
    manifest_with_format["format"] = "parquet-single"

    entries.append(("manifest", _to_inner_parquet_bytes(_manifest_to_table(manifest_with_format))))
    entries.append(("abstracts", _to_inner_parquet_bytes(_abstracts_to_table(abstracts_envelope))))
    entries.append(("authors", _to_inner_parquet_bytes(_authors_to_table(authors_envelope))))

    claims_t, figures_t = _enrichment_to_tables(enrichment_envelope)
    if claims_t.num_rows:
        entries.append(("enrichment_claims", _to_inner_parquet_bytes(claims_t)))
    if figures_t.num_rows:
        entries.append(("enrichment_figures", _to_inner_parquet_bytes(figures_t)))

    for cell_key, env in cells_envelopes.items():
        entries.append((f"cells:{cell_key}", _to_inner_parquet_bytes(_cell_to_table(env))))
    for (model, inp, kind), env in topics_envelopes.items():
        entries.append(
            (f"topics:{model}_{inp}_{kind}", _to_inner_parquet_bytes(_topic_to_table(env)))
        )
    for cell_key, env in neighbors_envelopes.items():
        entries.append(
            (f"neighbors:{cell_key}", _to_inner_parquet_bytes(_neighbours_to_table(env)))
        )

    if minilm_bin is not None:
        entries.append(("search:minilm_vectors", minilm_bin))
    entries.append(
        ("search:minilm_vectors_meta", json.dumps(minilm_sidecar, sort_keys=True).encode())
    )

    outer = pa.table(
        {
            "table_name": pa.array([n for n, _ in entries], type=pa.string()),
            "table_bytes": pa.array([b for _, b in entries], type=pa.large_binary()),
        }
    )
    pq.write_table(outer, target, **_OUTER_PARQUET_KWARGS)

    return {target}
