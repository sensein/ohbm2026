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


# Stage 11.1 — parquet format version. The browser-side decoder
# dispatches on this. v2 drops the legacy `poster_standby: {first,
# second}` STRUCT in favor of a new `standby_slots` table + two INT8
# index columns on `abstracts`. Loader accepts both shapes for one
# deploy cycle.
PARQUET_FORMAT_VERSION = "parquet-single.v2"


def _collect_standby_by_poster(envelope: Mapping[str, Any]) -> dict[int, dict]:
    """Pull standby datetime pairs from the per-record envelope.

    The legacy v1 path produced records carrying
    ``poster_standby: {first: datetime|None, second: datetime|None}``.
    This v2 emitter still consumes that intermediate shape (no churn
    in ``abstracts.py``) but emits the new shape on the wire.
    """

    out: dict[int, dict] = {}
    for r in envelope["abstracts"]:
        standby = r.get("poster_standby") or {}
        first = standby.get("first")
        second = standby.get("second")
        if first is None and second is None:
            continue
        out[int(r["poster_id"])] = {"first": first, "second": second}
    return out


def _abstracts_to_table(
    envelope: Mapping[str, Any],
    poster_to_index: Mapping[int, tuple[int | None, int | None]],
) -> pa.Table:
    """Build the abstracts table. STRUCT columns for sections / topics
    / facets. ``standby_first_index`` / ``standby_second_index`` are
    INT8 nullable references into the new ``standby_slots`` table
    (Stage 11.1 US2). poster_id is INT16 (range 1-3333). Stage 10:
    ``abstract_id`` (Oxford submission id) is dropped from the export;
    ``poster_id`` is the sole identifier on the wire.
    """
    rows = []
    for r in envelope["abstracts"]:
        pid = int(r["poster_id"])
        first_idx, second_idx = poster_to_index.get(pid, (None, None))
        rows.append(
            {
                "poster_id": pid,
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
                "standby_first_index": first_idx,
                "standby_second_index": second_idx,
            }
        )
    table = pa.Table.from_pylist(rows)
    # Pin types explicitly: poster_id → INT16, standby indices → INT8.
    # Without the casts pylist inference would default to INT64 +
    # waste ~7 B per row × 3 K rows.
    table = table.set_column(
        table.schema.get_field_index("poster_id"),
        "poster_id",
        table["poster_id"].cast(pa.int16()),
    )
    for col in ("standby_first_index", "standby_second_index"):
        idx = table.schema.get_field_index(col)
        table = table.set_column(idx, col, table[col].cast(pa.int8()))
    return table


def _standby_slots_to_table(slots: list[dict]) -> pa.Table:
    """Stage 11.1 US2 — global lookup table of program windows.

    Columns: ``slot_index: INT8``, ``start_utc: TIMESTAMP[ms, UTC]``,
    ``end_utc: TIMESTAMP[ms, UTC]``, ``display_label: VARCHAR``.

    8 rows for OHBM 2026. The UI's ``standby.ts`` consumes the rows
    directly — no further Intl.DateTimeFormat work happens at
    facet-recompute time.
    """

    table = pa.Table.from_pylist(slots)
    table = table.set_column(
        table.schema.get_field_index("slot_index"),
        "slot_index",
        table["slot_index"].cast(pa.int8()),
    )
    for col in ("start_utc", "end_utc"):
        idx = table.schema.get_field_index(col)
        table = table.set_column(idx, col, table[col].cast(pa.timestamp("ms", tz="UTC")))
    return table


def _authors_to_table(envelope: Mapping[str, Any]) -> pa.Table:
    """Authors: `poster_ids` is LIST<INT16> (each author lists every
    accepted poster they co-authored; max poster value 3333)."""
    table = pa.Table.from_pylist(envelope["authors"])
    if "poster_ids" in table.schema.names:
        idx = table.schema.get_field_index("poster_ids")
        table = table.set_column(idx, "poster_ids", table["poster_ids"].cast(pa.list_(pa.int16())))
    return table


def _cell_to_table(envelope: Mapping[str, Any]) -> pa.Table:
    """Cells: poster_id int16, geometry + cluster columns inferred."""
    table = pa.Table.from_pylist(envelope["rows"])
    return table.set_column(
        table.schema.get_field_index("poster_id"),
        "poster_id",
        table["poster_id"].cast(pa.int16()),
    )


def _topic_to_table(envelope: Mapping[str, Any]) -> pa.Table:
    return pa.Table.from_pylist(envelope["topics"])


def _neighbours_to_table(envelope: Mapping[str, Any]) -> pa.Table:
    """Per-row neighbour record: each cell has K=10 nearest + 10 farthest
    poster_ids. All id columns are LIST<INT16> (range 1–3333)."""
    rows: list[dict[str, Any]] = []
    for idx, pid in enumerate(envelope["poster_ids"]):
        rows.append(
            {
                "poster_id": int(pid),
                "nearest_ids": [int(x) for x in envelope["nearest_ids"][idx]],
                "nearest_distances": list(envelope["nearest_distances"][idx]),
                "farthest_ids": [int(x) for x in envelope["farthest_ids"][idx]],
                "farthest_distances": list(envelope["farthest_distances"][idx]),
            }
        )
    table = pa.Table.from_pylist(rows)
    # Cast every id column to int16. The k-length variable-length lists
    # carry their element type from the schema (Parquet stores them as
    # LIST<INT16>; dict-encoded the per-value cost drops to <1 byte).
    for col_name in ("poster_id", "nearest_ids", "farthest_ids"):
        idx = table.schema.get_field_index(col_name)
        if col_name == "poster_id":
            new_col = table[col_name].cast(pa.int16())
        else:
            new_col = table[col_name].cast(pa.list_(pa.int16()))
        table = table.set_column(idx, col_name, new_col)
    return table


def _enrichment_to_tables(envelope: Mapping[str, Any]) -> tuple[pa.Table, pa.Table]:
    """Flatten the records dict into two parallel tables (claims, figures).
    Each row carries the int16 `poster_id` of the abstract it belongs to."""
    claim_rows: list[dict[str, Any]] = []
    figure_rows: list[dict[str, Any]] = []
    for pid_str, rec in envelope.get("records", {}).items():
        pid = int(pid_str)
        for i, c in enumerate(rec.get("claims", []) or []):
            claim_rows.append({"poster_id": pid, "claim_index": i, **c})
        for i, f in enumerate(rec.get("figures", []) or []):
            figure_rows.append({"poster_id": pid, "figure_index": i, **f})
    claims_table = pa.Table.from_pylist(claim_rows) if claim_rows else pa.table({})
    figures_table = pa.Table.from_pylist(figure_rows) if figure_rows else pa.table({})

    def _pin_int16(t: pa.Table) -> pa.Table:
        if t.num_columns == 0 or "poster_id" not in t.schema.names:
            return t
        idx = t.schema.get_field_index("poster_id")
        return t.set_column(idx, "poster_id", t["poster_id"].cast(pa.int16()))

    return _pin_int16(claims_table), _pin_int16(figures_table)


def _manifest_to_table(manifest: Mapping[str, Any]) -> pa.Table:
    flat = {
        "schema_version": str(manifest.get("schema_version", "")),
        "format": "parquet-single",
        # Stage 11.1 — exposes the format version separately from the
        # UI data-package schema_version so the browser-side decoder
        # can branch on it without parsing the inner manifest JSON.
        "format_version": PARQUET_FORMAT_VERSION,
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
    manifest_with_format["format_version"] = PARQUET_FORMAT_VERSION

    # Stage 11.1 US2 — derive the standby_slots table once, then thread
    # the per-poster INT8 lookup map into the abstracts emitter.
    from ohbm2026.ui_data.standby_slots import (
        build_poster_to_index_map,
        derive_standby_slots,
    )

    standby_by_pid = _collect_standby_by_poster(abstracts_envelope)
    standby_slots = derive_standby_slots(standby_by_pid)
    poster_to_index = build_poster_to_index_map(standby_by_pid, standby_slots)

    entries.append(("manifest", _to_inner_parquet_bytes(_manifest_to_table(manifest_with_format))))
    entries.append(
        ("abstracts", _to_inner_parquet_bytes(_abstracts_to_table(abstracts_envelope, poster_to_index)))
    )
    entries.append(("authors", _to_inner_parquet_bytes(_authors_to_table(authors_envelope))))
    if standby_slots:
        entries.append(
            ("standby_slots", _to_inner_parquet_bytes(_standby_slots_to_table(standby_slots)))
        )

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
