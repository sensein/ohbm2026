"""Stage-10 candidate-format emitter package.

Each module in this package corresponds to one candidate from the
``specs/010-export-redesign`` bench matrix:

- ``gzip_json_shards``   — status-quo-tightened (today's emission path).
- ``parquet_files``      — multi-file Parquet (one ``.parquet`` per table).
- ``parquet_duckdb``     — same Parquet + a DuckDB-WASM views sidecar.
- ``sqlite_single``      — single ``.sqlite`` file with FTS5 + range-fetch VFS.
- ``duckdb_single``      — single ``.duckdb`` file.
- ``arrow_ipc``          — per-table Arrow IPC files.

After the bench commits to a winner (``research.md`` § B3), the losing
emitters are pruned in T053. Until then this package holds all six in
parallel so the bench can build all candidates from the same row stream.

Each candidate emitter exposes a single entry point:

    def emit(*, output_dir: Path, row_streams: RowStreams, manifest: ManifestRow) -> None

where ``RowStreams`` bundles every per-entity iterator from the
``ohbm2026.ui_data`` modules above. The candidate writes whatever
files / tables / blobs its container demands under ``output_dir``.
"""

from __future__ import annotations
