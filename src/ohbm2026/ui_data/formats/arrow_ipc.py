"""Candidate #6: Arrow IPC (file format) per-table.

Each logical table becomes one ``.arrow`` file (Arrow IPC file
format = stream + footer). Browser-side decoder uses
``apache-arrow`` (JS lib) to read RecordBatches.

Compared to Parquet:

- Arrow IPC has *less* compression by default (no column-statistics-
  driven encoding selection). We opt-in to LZ4 frame compression
  via ``write_options.compression='lz4'``; zstd is also available
  but its browser-side decode is slower than LZ4's.
- RecordBatch boundaries are explicit — the bench writes one batch
  per ~1 K rows so the browser can fetch a single batch via HTTP
  Range without reading the whole file.

Same logical schema as ``parquet_files``: per-table file layout,
flat scalar columns, STRUCT for nested fields, parallel-array
neighbours un-zipped into per-row tuples.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

import pyarrow as pa
import pyarrow.ipc as ipc

from ohbm2026.ui_data.formats import parquet_files

__all__ = ["write"]

_IPC_OPTIONS = ipc.IpcWriteOptions(compression="lz4")


def _write_arrow(table: pa.Table, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    with ipc.new_file(target, table.schema, options=_IPC_OPTIONS) as writer:
        # Slice into batches of ~1k rows so range fetches can target a
        # specific batch (footer carries per-batch byte offsets).
        batch_size = 1000
        for offset in range(0, table.num_rows, batch_size):
            writer.write_batch(table.slice(offset, batch_size).combine_chunks().to_batches()[0])


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

    def _emit(table: pa.Table, rel: str) -> None:
        if table.num_rows == 0:
            return
        target = out / rel
        _write_arrow(table, target)
        expected.add(target)

    # Reuse the table-construction helpers from the Parquet emitter —
    # the column shapes are identical, only the file format differs.
    _emit(parquet_files._manifest_to_table(manifest), "manifest.arrow")
    _emit(parquet_files._abstracts_to_table(abstracts_envelope), "abstracts.arrow")
    _emit(parquet_files._authors_to_table(authors_envelope), "authors.arrow")
    claims_t, figures_t = parquet_files._enrichment_to_tables(enrichment_envelope)
    _emit(claims_t, "enrichment_claims.arrow")
    _emit(figures_t, "enrichment_figures.arrow")
    for cell_key, env in cells_envelopes.items():
        _emit(parquet_files._cell_to_table(env), f"cells/{cell_key}.arrow")
    for (model, inp, kind), env in topics_envelopes.items():
        _emit(parquet_files._topic_to_table(env), f"topics/{model}_{inp}_{kind}.arrow")
    for cell_key, env in neighbors_envelopes.items():
        _emit(parquet_files._neighbours_to_table(env), f"neighbors/{cell_key}.arrow")

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
