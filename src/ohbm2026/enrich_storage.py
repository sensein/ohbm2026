"""SQLite + zlib storage helper for Stage 2 enriched corpus.

Single-file canonical format (research.md §1 storage benchmark).
Schema:

    abstracts(id INTEGER PRIMARY KEY, payload BLOB, content_hash TEXT,
              enriched_at TEXT)
    corpus_metadata(key TEXT PRIMARY KEY, value TEXT)

The `payload` column is the zlib-compressed JSON encoding of one
EnrichedAbstractRecord. The writer writes to a sibling temp file and
renames on `__exit__(exc_type=None)`; an exception during the with-block
leaves the canonical path untouched (atomic-write contract).
"""

from __future__ import annotations

import json
import os
import sqlite3
import zlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, Optional

__all__ = [
    "STORAGE_VERSION",
    "CACHE_VERSION",
    "PROVENANCE_VERSION",
    "EnrichedCorpusWriter",
    "read_one_by_id",
    "iter_enriched",
    "corpus_metadata",
]

STORAGE_VERSION = "enrich.storage.v1"
CACHE_VERSION = "enrich.cache.v1"
PROVENANCE_VERSION = "enrich.provenance.v1"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class EnrichedCorpusWriter:
    """Context manager that writes one SQLite + zlib corpus.

    Usage:

        with EnrichedCorpusWriter(path, state_key=..., source_corpus_hash=...) as w:
            for record in records:
                w.write_record(record)

    On clean exit the temp file is os.replace()'d onto `path`. On
    exception, the temp file is removed; `path` is untouched.
    """

    def __init__(
        self,
        path: Path | str,
        *,
        state_key: str,
        source_corpus_hash: str,
        corpus_kind: str = "accepted",
    ) -> None:
        self._final_path = Path(path)
        self._state_key = state_key
        self._source_corpus_hash = source_corpus_hash
        self._corpus_kind = corpus_kind
        # Temp file named with PID so concurrent runs (if any) don't
        # collide; lives next to the final path so os.replace is atomic.
        suffix = f".tmp.{os.getpid()}"
        self._tmp_path = self._final_path.with_name(self._final_path.name + suffix)
        self._con: sqlite3.Connection | None = None

    def __enter__(self) -> "EnrichedCorpusWriter":
        self._final_path.parent.mkdir(parents=True, exist_ok=True)
        # If a stale temp from a previous interrupted run sits at the
        # same name, drop it before recreating.
        if self._tmp_path.exists():
            self._tmp_path.unlink()
        self._con = sqlite3.connect(self._tmp_path)
        try:
            self._con.executescript(
                """
                PRAGMA journal_mode = WAL;
                PRAGMA synchronous = NORMAL;
                CREATE TABLE abstracts (
                  id            INTEGER PRIMARY KEY,
                  payload       BLOB    NOT NULL,
                  content_hash  TEXT    NOT NULL,
                  enriched_at   TEXT    NOT NULL
                );
                CREATE INDEX abstracts_content_hash ON abstracts(content_hash);
                CREATE TABLE corpus_metadata (
                  key   TEXT PRIMARY KEY,
                  value TEXT NOT NULL
                );
                """
            )
            self._con.executemany(
                "INSERT INTO corpus_metadata(key, value) VALUES (?, ?)",
                [
                    ("storage_version", STORAGE_VERSION),
                    ("corpus_kind", self._corpus_kind),
                    ("built_at", _utc_now_iso()),
                    ("state_key", self._state_key),
                    ("source_corpus_hash", self._source_corpus_hash),
                ],
            )
            self._con.commit()
        except Exception:
            self._con.close()
            self._con = None
            self._cleanup_tmp()
            raise
        return self

    def write_record(self, record: dict, *, content_hash: str | None = None) -> None:
        if self._con is None:
            raise RuntimeError("EnrichedCorpusWriter used outside its with-block")
        aid = record["id"]
        payload = zlib.compress(
            json.dumps(record, sort_keys=True, separators=(",", ":")).encode("utf-8")
        )
        self._con.execute(
            "INSERT INTO abstracts(id, payload, content_hash, enriched_at) VALUES (?, ?, ?, ?)",
            (
                int(aid),
                payload,
                content_hash or "",
                _utc_now_iso(),
            ),
        )

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        if self._con is not None:
            if exc_type is None:
                self._con.commit()
            self._con.close()
            self._con = None
        if exc_type is None:
            # Clean rename onto canonical path.
            os.replace(self._tmp_path, self._final_path)
            self._cleanup_sqlite_sidecars(self._final_path)
        else:
            self._cleanup_tmp()
        # Returning falsy lets the exception propagate.
        return None

    def _cleanup_tmp(self) -> None:
        for candidate in (
            self._tmp_path,
            self._tmp_path.with_suffix(self._tmp_path.suffix + "-wal"),
            self._tmp_path.with_suffix(self._tmp_path.suffix + "-shm"),
            self._tmp_path.with_name(self._tmp_path.name + "-wal"),
            self._tmp_path.with_name(self._tmp_path.name + "-shm"),
            self._tmp_path.with_name(self._tmp_path.name + "-journal"),
        ):
            if candidate.exists():
                candidate.unlink()

    @staticmethod
    def _cleanup_sqlite_sidecars(final: Path) -> None:
        # WAL is checkpointed on close (PRAGMA synchronous=NORMAL +
        # connection close), but in WAL mode SQLite may leave
        # `-wal` / `-shm` sidecars at the temp name. Once renamed we
        # can drop any sidecars at the *temp* name (they were already
        # cleaned by _cleanup_tmp on failure paths; on success they
        # might survive at the original temp basename and need a tidy).
        for suffix in ("-wal", "-shm", "-journal"):
            sidecar = final.with_name(final.name + suffix)
            if sidecar.exists():
                sidecar.unlink()


def _ensure_path(path: Path | str) -> Path:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"enriched corpus not found at {p}")
    return p


def read_one_by_id(path: Path | str, abstract_id: int) -> Optional[dict]:
    """O(1) primary-key lookup. Returns the decoded record or None."""
    p = _ensure_path(path)
    con = sqlite3.connect(p)
    try:
        row = con.execute(
            "SELECT payload FROM abstracts WHERE id = ?", (int(abstract_id),)
        ).fetchone()
    finally:
        con.close()
    if row is None:
        return None
    return json.loads(zlib.decompress(row[0]))


def iter_enriched(path: Path | str) -> Iterator[dict]:
    """Sequential scan, ordered by id ASC."""
    p = _ensure_path(path)
    con = sqlite3.connect(p)
    try:
        for (payload,) in con.execute("SELECT payload FROM abstracts ORDER BY id"):
            yield json.loads(zlib.decompress(payload))
    finally:
        con.close()


def corpus_metadata(path: Path | str) -> dict[str, str]:
    p = _ensure_path(path)
    con = sqlite3.connect(p)
    try:
        rows = con.execute("SELECT key, value FROM corpus_metadata").fetchall()
    finally:
        con.close()
    return {key: value for key, value in rows}
