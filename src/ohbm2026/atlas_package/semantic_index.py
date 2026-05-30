"""Stage 19 — write ``neuroscape_vectors.parquet`` (sibling to neuroscape.parquet).

Spec: ``specs/019-neuroscape-semantic-search/contracts/parquet-schemas.md §2``.

The file is a single pyarrow parquet with three columns:

    cluster_id    INT16                          NOT NULL  (sort key, first column)
    pubmed_id     INT64                          NOT NULL
    minilm_vector FIXED_LEN_BYTE_ARRAY(length=384) NOT NULL  (INT8 little-endian)

Rows are sorted by (cluster_id, pubmed_id) so parquet row-group min/max
statistics let the browser predicate-pushdown to ``cluster_id == X`` and
issue a bounded HTTP range request via hyparquet's ``asyncBufferFromUrl``.
Row-group size targets 8192 rows.

The manifest blob is embedded in the parquet's file-level
``key_value_metadata`` as ``manifest_json``; the browser drift checker
extracts it via the same pattern used by Stage 15 sibling-parquet peeks
(``site/src/lib/data_package/loader.ts::verifyAtlasSiblingDrift``).

Invariants enforced at write time:

- INV-003 (data-model.md): the set of pubmed_ids being written MUST
  equal the articles-table's pubmed_id set on neuroscape.parquet. Mismatch
  raises ``VectorsParquetWriteError(reason='pubmed_id_set_mismatch')``.
- The vector matrix shape MUST be (N, 384) with dtype int8; mismatches
  raise ``VectorsParquetWriteError(reason='shape_mismatch' |
  'dtype_mismatch')``.
- The cluster_id array MUST be int16-castable and have the same length as
  the pubmed_id array.
"""

from __future__ import annotations

import io
import json
from pathlib import Path
from typing import Any, Iterable, Mapping

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

from ohbm2026.exceptions import VectorsParquetWriteError

__all__ = ["write_neuroscape_vectors_parquet", "ROW_GROUP_SIZE", "VECTOR_DIM"]

VECTOR_DIM = 384
ROW_GROUP_SIZE = 8192


def _to_sorted_rows(
    cluster_ids: np.ndarray,
    pubmed_ids: np.ndarray,
    vectors: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return (cluster_ids, pubmed_ids, vectors) sorted by (cluster_id ASC,
    pubmed_id ASC). The sort is stable + deterministic so two runs with
    identical inputs produce byte-identical parquet bytes (SC-004)."""
    if cluster_ids.shape[0] != pubmed_ids.shape[0] != vectors.shape[0]:
        raise VectorsParquetWriteError(
            f"row-count mismatch: cluster_ids={cluster_ids.shape[0]} "
            f"pubmed_ids={pubmed_ids.shape[0]} vectors={vectors.shape[0]}",
            reason="row_count_mismatch",
        )
    order = np.lexsort((pubmed_ids, cluster_ids))
    return cluster_ids[order], pubmed_ids[order], vectors[order]


def write_neuroscape_vectors_parquet(
    *,
    out_path: Path,
    cluster_ids: np.ndarray,
    pubmed_ids: np.ndarray,
    vectors: np.ndarray,
    expected_pubmed_id_set: Iterable[int],
    manifest: Mapping[str, Any],
) -> Path:
    """Emit ``neuroscape_vectors.parquet``.

    Parameters
    ----------
    out_path
        Target file path. Parent directory MUST exist.
    cluster_ids
        ``(N,)`` int16-castable cluster assignments aligned with vectors.
    pubmed_ids
        ``(N,)`` int64-castable pubmed_ids aligned with vectors.
    vectors
        ``(N, 384)`` INT8 array of quantised MiniLM embeddings.
    expected_pubmed_id_set
        The pubmed_id set from the articles table on neuroscape.parquet.
        INV-003: equality with the input pubmed_ids set is required.
    manifest
        JSON-serialisable manifest dict per data-model.md §4. Embedded in
        the parquet's key_value_metadata under ``manifest_json``.

    Returns
    -------
    Path
        The written file path (``out_path``).

    Raises
    ------
    VectorsParquetWriteError
        With ``reason`` in {pubmed_id_set_mismatch, shape_mismatch,
        dtype_mismatch, row_count_mismatch}.
    """
    out_path = Path(out_path)
    if vectors.ndim != 2 or vectors.shape[1] != VECTOR_DIM:
        raise VectorsParquetWriteError(
            f"vectors shape {vectors.shape!r} != (N, {VECTOR_DIM})",
            path=str(out_path),
            reason="shape_mismatch",
        )
    if vectors.dtype != np.int8:
        raise VectorsParquetWriteError(
            f"vectors dtype {vectors.dtype!r} != int8",
            path=str(out_path),
            reason="dtype_mismatch",
        )
    expected = set(int(x) for x in expected_pubmed_id_set)
    actual = set(int(x) for x in pubmed_ids.tolist())
    if expected != actual:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        raise VectorsParquetWriteError(
            f"pubmed_id set mismatch: missing={len(missing)} extra={len(extra)} "
            f"(first missing: {missing[:3]}, first extra: {extra[:3]})",
            path=str(out_path),
            reason="pubmed_id_set_mismatch",
        )

    c_sorted, p_sorted, v_sorted = _to_sorted_rows(
        cluster_ids.astype(np.int16, copy=False),
        pubmed_ids.astype(np.int64, copy=False),
        vectors,
    )
    # Each row's 384 INT8 bytes become a FIXED_LEN_BYTE_ARRAY value.
    raw_bytes = v_sorted.tobytes(order="C")
    vector_values: list[bytes] = [
        raw_bytes[i * VECTOR_DIM : (i + 1) * VECTOR_DIM] for i in range(v_sorted.shape[0])
    ]

    table = pa.table(
        {
            "cluster_id": pa.array(c_sorted, type=pa.int16()),
            "pubmed_id": pa.array(p_sorted, type=pa.int64()),
            "minilm_vector": pa.array(vector_values, type=pa.binary(VECTOR_DIM)),
        }
    )
    # Embed the manifest in file-level metadata so the browser can read it
    # via hyparquet's `parquet_metadata` call before fetching any vector
    # row groups (data-model.md §4 / contracts/parquet-schemas.md §2).
    manifest_payload = json.dumps(dict(manifest), sort_keys=True).encode()
    schema_with_meta = table.schema.with_metadata({b"manifest_json": manifest_payload})
    table = table.replace_schema_metadata({b"manifest_json": manifest_payload})

    out_path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(
        table.cast(schema_with_meta),
        out_path,
        row_group_size=ROW_GROUP_SIZE,
        compression="snappy",
        write_statistics=True,
    )
    return out_path


def read_manifest(path: Path) -> dict[str, Any]:
    """Read the embedded manifest from ``neuroscape_vectors.parquet`` without
    touching any row groups. Used by the build-side byte-identity test and
    the browser drift checker's Python-side mirror."""
    pq_file = pq.ParquetFile(Path(path))
    raw = pq_file.metadata.metadata or {}
    blob = raw.get(b"manifest_json")
    if not blob:
        return {}
    return json.loads(blob.decode())
