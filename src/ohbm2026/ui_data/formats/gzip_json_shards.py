"""Candidate #1: status-quo-tightened gzipped JSON shards.

This is the Stage-6 output path — every shard is written as a JSON
file under ``output_dir``, with the tarball assembled by the deploy
workflow (``tar -czf …``). Keeping the existing format verbatim
preserves the regression baseline; the "tightening" comes from
dropping unused fields and moving dense numeric blocks to binary
sidecars (the existing ``minilm_vectors.bin``).

The bench measures this candidate against the other 5 to confirm
that the alternative formats (Parquet, SQLite, DuckDB, Arrow IPC)
deliver the promised improvements.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Mapping

from ohbm2026.util.json_io import write_json

# Stage-6 deterministic mtime (2026-01-01 UTC) — preserves tarball
# byte-identity across rebuilds for Dropbox share-link inode stability.
# Lives here (duplicated from builder.py) to avoid a circular import:
# builder.py is the dispatcher that calls into this writer.
DETERMINISTIC_MTIME = 1767225600

__all__ = ["write"]


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
    """Emit Stage-6-shape JSON shards into ``output_dir``.

    Returns the set of file paths the writer touched so the dispatcher
    can prune stale shards from prior builds (same Stage-6 contract).
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    expected: set[Path] = set()

    def _emit(rel: str, payload: Mapping[str, Any]) -> None:
        target = output_dir / rel
        write_json(target, payload)
        # Stage-6 deterministic mtime — preserves tarball byte-identity
        # across rebuilds for Dropbox share-link inode stability.
        os.utime(target, (DETERMINISTIC_MTIME, DETERMINISTIC_MTIME))
        expected.add(target)

    _emit("manifest.json", manifest)
    _emit("abstracts.json", abstracts_envelope)
    _emit("authors.json", authors_envelope)
    _emit("enrichment.json", enrichment_envelope)
    for cell_key, envelope in cells_envelopes.items():
        _emit(f"cells/{cell_key}.json", envelope)
    for (model, inp, kind), envelope in topics_envelopes.items():
        _emit(f"topics/{model}_{inp}_{kind}.json", envelope)
    for cell_key, envelope in neighbors_envelopes.items():
        _emit(f"neighbors/{cell_key}.json", envelope)

    if minilm_bin is not None:
        bin_path = output_dir / "search" / "minilm_vectors.bin"
        bin_path.parent.mkdir(parents=True, exist_ok=True)
        with bin_path.open("wb") as fh:
            fh.write(minilm_bin)
        os.utime(bin_path, (DETERMINISTIC_MTIME, DETERMINISTIC_MTIME))
        expected.add(bin_path)
    _emit("search/minilm_vectors.build_info.json", minilm_sidecar)

    return expected
