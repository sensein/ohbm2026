"""Candidate #7: single-file nested Parquet.

One ``data.parquet`` file containing every logical table as a row,
where each row holds serialized Parquet bytes for that table in a
``table_bytes`` BLOB column. ``row_group_size=1`` is used so each
row lands in its own row group — the Parquet footer then carries
explicit per-row-group byte offsets, which the browser-side decoder
can use to issue an HTTP Range request for exactly one logical
table at a time.

This is the only Parquet variant compatible with the project's
single-URL deploy model (the SvelteKit bundle is the only thing
shipped to gh-pages; data is fetched at runtime from the
distribution URL, with no per-shard mirroring). Multi-file Parquet
would require a tarball wrap that defeats per-table range-fetch.

Browser-side decode pattern (Phase 3 = full-read; Phase 4 = lazy):

1. Range-fetch the last ~16 KB to read the Parquet footer.
2. Look up the row group whose ``table_name`` matches the request.
3. Range-fetch that row group's bytes.
4. Parse those bytes as a nested Parquet whose rows ARE the logical
   table's rows.

The inner Parquet blobs are themselves zstd-compressed with dict
encoding — exactly the parquet_files candidate's output, just
embedded. Total on-disk size should be within ~1 % of #2's 24 MB
(the extra bytes are the outer file's footer + per-row-group
overhead for ~50 row groups).

The MiniLM vector sidecar is also packed as a blob row so the
whole package is one file. Future browser code does a blob fetch
for ``search:minilm_vectors`` instead of a separate ``.bin``
sidecar URL.
"""

from __future__ import annotations

import io
import json
from pathlib import Path
from typing import Any, Mapping

import pyarrow as pa
import pyarrow.parquet as pq

from ohbm2026.ui_data.formats import parquet_files

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

    # The outer manifest carries the single-file format marker so the
    # browser-side dispatcher routes to ParquetSingleDecoder.
    manifest_with_format = dict(manifest)
    manifest_with_format["format"] = "parquet-single"

    entries.append(
        ("manifest", _to_inner_parquet_bytes(parquet_files._manifest_to_table(manifest_with_format)))
    )
    entries.append(
        ("abstracts", _to_inner_parquet_bytes(parquet_files._abstracts_to_table(abstracts_envelope)))
    )
    entries.append(
        ("authors", _to_inner_parquet_bytes(parquet_files._authors_to_table(authors_envelope)))
    )

    claims_t, figures_t = parquet_files._enrichment_to_tables(enrichment_envelope)
    if claims_t.num_rows:
        entries.append(("enrichment_claims", _to_inner_parquet_bytes(claims_t)))
    if figures_t.num_rows:
        entries.append(("enrichment_figures", _to_inner_parquet_bytes(figures_t)))

    for cell_key, env in cells_envelopes.items():
        entries.append(
            (f"cells:{cell_key}", _to_inner_parquet_bytes(parquet_files._cell_to_table(env)))
        )
    for (model, inp, kind), env in topics_envelopes.items():
        entries.append(
            (
                f"topics:{model}_{inp}_{kind}",
                _to_inner_parquet_bytes(parquet_files._topic_to_table(env)),
            )
        )
    for cell_key, env in neighbors_envelopes.items():
        entries.append(
            (
                f"neighbors:{cell_key}",
                _to_inner_parquet_bytes(parquet_files._neighbours_to_table(env)),
            )
        )

    # MiniLM int8 vectors packed as opaque blob — same bytes as the
    # standalone sidecar. The accompanying metadata is JSON, stored as
    # a tiny blob too so the entire package is one file.
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
